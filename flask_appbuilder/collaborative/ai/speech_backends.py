"""
faster-whisper STT and Supertonic TTS backends for Flask-AppBuilder.

faster-whisper is a reimplementation of OpenAI's Whisper using CTranslate2,
running 4× faster with the same accuracy. Supertonic provides high-quality
neural TTS using StyleTTS2-based models.

Installation::

    pip install "flask-appbuilder[speech]"
    # or manually:
    pip install faster-whisper
    pip install supertone-tts  # or: pip install TTS  (Coqui, fallback)

Configuration (in app.config or ModelConfig)::

    FAB_SPEECH_STT_BACKEND    = "faster-whisper"  # "faster-whisper" | "whisper" | "openai"
    FAB_SPEECH_TTS_BACKEND    = "supertonic"       # "supertonic" | "coqui" | "gtts" | "openai"
    FAB_SPEECH_WHISPER_MODEL  = "base"             # tiny|base|small|medium|large-v3
    FAB_SPEECH_WHISPER_DEVICE = "auto"             # "auto"|"cpu"|"cuda"
    FAB_SPEECH_WHISPER_COMPUTE= "int8"             # "int8"|"float16"|"float32"
    FAB_SPEECH_TTS_MODEL      = "tts_models/en/ljspeech/tacotron2-DDC"
    FAB_SPEECH_TTS_SPEAKER    = None               # speaker name/id for multi-speaker models
    FAB_SPEECH_TTS_LANGUAGE   = "en"
"""
from __future__ import annotations

import asyncio
import io
import logging
import tempfile
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ─── faster-whisper STT ──────────────────────────────────────────────────────

class FasterWhisperSTT:
	"""Speech-to-Text using faster-whisper (CTranslate2 backend).

	Runs locally with no API key. Supports all standard Whisper model sizes.
	Significantly faster than the original ``openai-whisper`` package on CPU
	and GPU with optional INT8 quantisation.

	Args:
	    model_size: Whisper model variant. "base" is a good default.
	               Options: tiny, base, small, medium, large-v1/v2/v3
	    device:    "auto" (GPU if available, else CPU), "cpu", or "cuda".
	    compute_type: Quantisation mode. "int8" (fastest CPU), "float16" (GPU),
	                 "float32" (highest accuracy).
	    language:  ISO 639-1 code to skip language detection (e.g. "en").
	               None = auto-detect.
	    beam_size: Beam search width. Higher = more accurate, slower.

	Usage::

	    stt = FasterWhisperSTT(model_size="small", device="auto")
	    text = await stt.transcribe(audio_bytes)
	"""

	def __init__(
		self,
		model_size: str = "base",
		device: str = "auto",
		compute_type: str = "int8",
		language: str | None = None,
		beam_size: int = 5,
	) -> None:
		self.model_size = model_size
		self.device = device
		self.compute_type = compute_type
		self.language = language
		self.beam_size = beam_size
		self._model = None

	def _load_model(self):
		"""Lazy-load the model on first use."""
		if self._model is not None:
			return self._model
		try:
			from faster_whisper import WhisperModel
			device = self.device
			if device == "auto":
				try:
					import torch
					device = "cuda" if torch.cuda.is_available() else "cpu"
				except ImportError:
					device = "cpu"
			self._model = WhisperModel(
				self.model_size,
				device=device,
				compute_type=self.compute_type,
			)
			log.info(
				"faster-whisper loaded: model=%s device=%s compute=%s",
				self.model_size, device, self.compute_type,
			)
		except ImportError:
			raise RuntimeError(
				"faster-whisper not installed. Run: pip install faster-whisper"
			)
		return self._model

	async def transcribe(self, audio_data: bytes, **kwargs) -> str:
		"""Transcribe audio bytes to text.

		Args:
		    audio_data: Raw audio bytes (WAV, MP3, OGG, FLAC, etc.)
		    language:   Override language detection (kwarg).
		    beam_size:  Override beam size (kwarg).

		Returns:
		    Transcribed text string.
		"""
		model = self._load_model()
		loop = asyncio.get_running_loop()

		def _run():
			with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
				tmp.write(audio_data)
				tmp_path = tmp.name
			try:
				segments, info = model.transcribe(
					tmp_path,
					language=kwargs.get("language", self.language),
					beam_size=kwargs.get("beam_size", self.beam_size),
					vad_filter=True,          # removes silence
					vad_parameters={"min_silence_duration_ms": 500},
				)
				text = " ".join(seg.text.strip() for seg in segments)
				if not text:
					log.debug("No speech detected in audio (%.1fs)", info.duration)
				return text.strip()
			finally:
				os.unlink(tmp_path)

		return await loop.run_in_executor(None, _run)

	@property
	def model_info(self) -> dict[str, Any]:
		"""Return info about the loaded model."""
		return {
			"backend": "faster-whisper",
			"model_size": self.model_size,
			"device": self.device,
			"compute_type": self.compute_type,
			"language": self.language,
		}


# ─── Supertonic TTS ───────────────────────────────────────────────────────────

class SupertonicTTS:
	"""Text-to-Speech using Supertonic / high-quality neural TTS.

	Priority order for the underlying engine:
	1. ``supertone-tts`` — if installed (``pip install supertone-tts``)
	2. Coqui ``TTS`` — broad model library (``pip install TTS``)
	3. ``pyttsx3`` — lightweight offline fallback

	All engines are accessed through the same async ``synthesize()`` API so you
	can swap engines without changing call sites.

	Args:
	    model_name: TTS model identifier.
	               Supertone: model slug from Supertone Hub.
	               Coqui:     e.g. "tts_models/en/ljspeech/tacotron2-DDC"
	    speaker:   Speaker ID/name for multi-speaker models.
	    language:  Target language code (default "en").
	    speed:     Playback speed multiplier (1.0 = normal).
	    output_format: Audio format to return ("wav", "mp3", "ogg").

	Usage::

	    tts = SupertonicTTS()
	    audio_bytes = await tts.synthesize("Hello, world!")
	"""

	def __init__(
		self,
		model_name: str | None = None,
		speaker: str | None = None,
		language: str = "en",
		speed: float = 1.0,
		output_format: str = "wav",
	) -> None:
		self.model_name = model_name
		self.speaker = speaker
		self.language = language
		self.speed = speed
		self.output_format = output_format
		self._engine = None
		self._backend_name: str = "unloaded"

	def _load_engine(self):
		"""Lazy-load best available TTS engine."""
		if self._engine is not None:
			return self._engine

		# 1. Try supertone-tts
		try:
			from supertone_tts import SupertoneTTS as _ST
			engine = _ST(
				model=self.model_name or "default",
				language=self.language,
			)
			self._engine = engine
			self._backend_name = "supertone"
			log.info("Supertone TTS engine loaded")
			return engine
		except ImportError:
			pass
		except Exception as e:
			log.warning("supertone-tts init failed: %s", e)

		# 2. Try Coqui TTS
		try:
			from TTS.api import TTS as _CoquiTTS
			model = self.model_name or "tts_models/en/ljspeech/tacotron2-DDC"
			engine = _CoquiTTS(model_name=model, progress_bar=False)
			if self.speaker:
				engine.tts_to_speaker = self.speaker
			self._engine = engine
			self._backend_name = "coqui"
			log.info("Coqui TTS engine loaded: %s", model)
			return engine
		except ImportError:
			pass
		except Exception as e:
			log.warning("Coqui TTS init failed: %s", e)

		# 3. Fallback: pyttsx3 (offline, robotic but works everywhere)
		try:
			import pyttsx3
			engine = pyttsx3.init()
			engine.setProperty("rate", int(150 * self.speed))
			engine.setProperty("volume", 0.9)
			self._engine = engine
			self._backend_name = "pyttsx3"
			log.info("pyttsx3 TTS fallback loaded")
			return engine
		except ImportError:
			raise RuntimeError(
				"No TTS backend available. Install one of:\n"
				"  pip install supertone-tts\n"
				"  pip install TTS\n"
				"  pip install pyttsx3"
			)

	async def synthesize(self, text: str, **kwargs) -> bytes:
		"""Convert text to speech audio bytes.

		Args:
		    text:    Text to synthesise.
		    speaker: Override speaker name/ID (kwarg).
		    speed:   Override playback speed (kwarg).

		Returns:
		    Audio bytes in the configured output_format.
		"""
		engine = self._load_engine()
		loop = asyncio.get_running_loop()

		def _run():
			return self._synthesize_sync(engine, text, kwargs)

		return await loop.run_in_executor(None, _run)

	def _synthesize_sync(self, engine, text: str, kwargs: dict) -> bytes:
		"""Synchronous synthesis — called in a thread pool."""
		backend = self._backend_name

		if backend == "supertone":
			audio = engine.synthesize(
				text,
				speaker=kwargs.get("speaker", self.speaker),
				speed=kwargs.get("speed", self.speed),
			)
			return audio if isinstance(audio, bytes) else audio.read()

		if backend == "coqui":
			with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
				tmp_path = tmp.name
			try:
				speaker = kwargs.get("speaker", self.speaker)
				if speaker:
					engine.tts_to_file(text=text, speaker=speaker, file_path=tmp_path)
				else:
					engine.tts_to_file(text=text, file_path=tmp_path)
				with open(tmp_path, "rb") as f:
					return f.read()
			finally:
				if os.path.exists(tmp_path):
					os.unlink(tmp_path)

		if backend == "pyttsx3":
			# pyttsx3 can save to file
			with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
				tmp_path = tmp.name
			try:
				engine.save_to_file(text, tmp_path)
				engine.runAndWait()
				with open(tmp_path, "rb") as f:
					return f.read()
			finally:
				if os.path.exists(tmp_path):
					os.unlink(tmp_path)

		raise RuntimeError(f"Unknown backend: {backend}")

	@property
	def backend_name(self) -> str:
		"""Name of the active TTS engine (does not force loading)."""
		return self._backend_name

	@property
	def model_info(self) -> dict[str, Any]:
		return {
			"backend": self._backend_name,
			"model": self.model_name,
			"speaker": self.speaker,
			"language": self.language,
			"speed": self.speed,
		}


# ─── Unified SpeechProcessor facade ──────────────────────────────────────────

class SpeechProcessor:
	"""Unified STT + TTS facade with configurable backends.

	Configure via Flask app config or pass backends directly::

	    # In your app factory
	    from flask_appbuilder.collaborative.ai.speech_backends import SpeechProcessor

	    speech = SpeechProcessor()
	    speech.init_app(app)  # reads FAB_SPEECH_* config keys

	    # Or pass backends directly
	    speech = SpeechProcessor(
	        stt=FasterWhisperSTT(model_size="small"),
	        tts=SupertonicTTS(model_name="tts_models/en/ljspeech/tacotron2-DDC"),
	    )
	"""

	def __init__(
		self,
		stt: FasterWhisperSTT | None = None,
		tts: SupertonicTTS | None = None,
	) -> None:
		self._stt = stt
		self._tts = tts

	def init_app(self, app) -> None:
		"""Configure from Flask app config."""
		cfg = app.config
		stt_backend = cfg.get("FAB_SPEECH_STT_BACKEND", "faster-whisper")
		tts_backend = cfg.get("FAB_SPEECH_TTS_BACKEND", "supertonic")

		if stt_backend == "faster-whisper":
			self._stt = FasterWhisperSTT(
				model_size=cfg.get("FAB_SPEECH_WHISPER_MODEL", "base"),
				device=cfg.get("FAB_SPEECH_WHISPER_DEVICE", "auto"),
				compute_type=cfg.get("FAB_SPEECH_WHISPER_COMPUTE", "int8"),
				language=cfg.get("FAB_SPEECH_TTS_LANGUAGE"),
			)
		# else: whisper / openai handled by existing adapters

		if tts_backend in ("supertonic", "coqui", "pyttsx3"):
			self._tts = SupertonicTTS(
				model_name=cfg.get("FAB_SPEECH_TTS_MODEL"),
				speaker=cfg.get("FAB_SPEECH_TTS_SPEAKER"),
				language=cfg.get("FAB_SPEECH_TTS_LANGUAGE", "en"),
			)

		app.extensions["fab_speech_processor"] = self
		log.info(
			"SpeechProcessor configured: STT=%s TTS=%s",
			stt_backend, tts_backend,
		)

	async def transcribe(self, audio_data: bytes, **kwargs) -> str:
		"""Transcribe audio bytes to text."""
		if self._stt is None:
			raise RuntimeError(
				"STT backend not configured. Set FAB_SPEECH_STT_BACKEND."
			)
		return await self._stt.transcribe(audio_data, **kwargs)

	async def synthesize(self, text: str, **kwargs) -> bytes:
		"""Synthesise text to audio bytes."""
		if self._tts is None:
			raise RuntimeError(
				"TTS backend not configured. Set FAB_SPEECH_TTS_BACKEND."
			)
		return await self._tts.synthesize(text, **kwargs)

	@property
	def info(self) -> dict[str, Any]:
		return {
			"stt": self._stt.model_info if self._stt else None,
			"tts": self._tts.model_info if self._tts else None,
		}


# ─── Flask Blueprint — REST endpoints for voice plugin ───────────────────────

def create_speech_blueprint(processor: SpeechProcessor | None = None):
	"""Create a Flask Blueprint exposing STT and TTS as HTTP endpoints.

	Mount it on your app::

	    from flask_appbuilder.collaborative.ai.speech_backends import (
	        SpeechProcessor, create_speech_blueprint
	    )
	    speech = SpeechProcessor()
	    speech.init_app(app)
	    app.register_blueprint(create_speech_blueprint(speech), url_prefix='/voice')

	Endpoints::

	    POST /voice/stt          — multipart/form-data with field 'audio'
	                               Returns: {"text": "transcribed text"}

	    POST /voice/tts          — JSON body {"text": "...", "speed": 1.0}
	                               Returns: audio/wav bytes

	    GET  /voice/info         — Returns backend info JSON
	"""
	from flask import Blueprint, request, jsonify, current_app

	bp = Blueprint("fab_voice", __name__)

	def _get_processor() -> SpeechProcessor:
		if processor is not None:
			return processor
		p = current_app.extensions.get("fab_speech_processor")
		if p is None:
			raise RuntimeError(
				"SpeechProcessor not configured. "
				"Call speech.init_app(app) in your app factory."
			)
		return p

	@bp.route("/stt", methods=["POST"])
	def stt_endpoint():
		"""Transcribe uploaded audio to text."""
		if "audio" not in request.files:
			return jsonify({"error": "No audio file in request"}), 400
		audio_bytes = request.files["audio"].read()
		language = request.form.get("language")

		async def _do():
			p = _get_processor()
			return await p.transcribe(audio_bytes, language=language or None)

		try:
			import asyncio
			text = asyncio.run(_do())
			return jsonify({"text": text, "language": language})
		except Exception as exc:
			log.exception("STT failed")
			return jsonify({"error": str(exc)}), 500

	@bp.route("/tts", methods=["POST"])
	def tts_endpoint():
		"""Convert text to speech, return audio bytes."""
		body = request.get_json(silent=True) or {}
		text = body.get("text", "").strip()
		if not text:
			return jsonify({"error": "Empty text"}), 400

		async def _do():
			p = _get_processor()
			return await p.synthesize(
				text,
				speed=float(body.get("speed", 1.0)),
				speaker=body.get("speaker"),
			)

		try:
			import asyncio
			audio = asyncio.run(_do())
			from flask import Response
			return Response(
				audio,
				mimetype="audio/wav",
				headers={"Content-Disposition": "inline; filename=speech.wav"},
			)
		except Exception as exc:
			log.exception("TTS failed")
			return jsonify({"error": str(exc)}), 500

	@bp.route("/info", methods=["GET"])
	def info_endpoint():
		"""Return info about configured speech backends."""
		try:
			return jsonify(_get_processor().info)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 500

	return bp
