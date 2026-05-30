"""
Multi-Modal Data Integration System

Advanced system for integrating images, text, audio, and other media types
into graph analytics with feature extraction and similarity analysis.
"""

import logging
import json
import io
import base64
import hashlib
import mimetypes
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Union, BinaryIO
from dataclasses import dataclass, asdict
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Optional dependencies with fallbacks
try:
	import numpy as np
except ImportError:
	logger.warning("NumPy not available, using basic math operations")
	class MockNumpy:
		@staticmethod
		def array(data): return data
		@staticmethod
		def mean(data): return sum(data) / len(data) if data else 0
		@staticmethod
		def std(data): 
			if not data: return 0
			mean = sum(data) / len(data)
			return (sum((x - mean) ** 2 for x in data) / len(data)) ** 0.5
		@staticmethod
		def histogram(data, bins=10): 
			return list(range(bins)), list(range(bins))
	np = MockNumpy()

try:
	from PIL import Image, ImageFilter, ImageEnhance
	PIL_AVAILABLE = True
except ImportError:
	logger.warning("PIL not available, using basic image processing")
	PIL_AVAILABLE = False
	class MockImage:
		@staticmethod
		def open(fp): return MockImage()
		def resize(self, size): return self
		def convert(self, mode): return self
		def filter(self, f): return self
		def getdata(self): return [128] * 100  # Mock grayscale data
		def histogram(self): return [10] * 256  # Mock histogram
		@property
		def size(self): return (100, 100)
	Image = MockImage()

try:
	import librosa
	LIBROSA_AVAILABLE = True
except ImportError:
	logger.warning("Librosa not available, using basic audio processing")
	LIBROSA_AVAILABLE = False
	class MockLibrosa:
		@staticmethod
		def load(path, sr=22050): return [0.1] * 1000, sr
		@staticmethod
		def stft(y): return np.array([[0.1] * 10] * 10)
		@staticmethod
		def feature():
			class Feature:
				@staticmethod
				def mfcc(y, sr, n_mfcc=13): return [[0.1] * 13] * 10
				@staticmethod
				def spectral_centroid(y, sr): return [[1000]]
				@staticmethod
				def zero_crossing_rate(y): return [[0.1]]
				@staticmethod
				def tempo(y, sr): return 120, [120]
			return Feature()
	librosa = MockLibrosa()

try:
	import cv2
	CV2_AVAILABLE = True
except ImportError:
	logger.warning("OpenCV not available, using basic video processing")
	CV2_AVAILABLE = False
	class MockCV2:
		@staticmethod
		def VideoCapture(path): 
			class MockCap:
				def read(self): return True, np.array([[[128, 128, 128]]])
				def get(self, prop): return 30 if prop == cv2.CAP_PROP_FPS else 100
				def release(self): pass
			return MockCap()
		CAP_PROP_FPS = 5
		CAP_PROP_FRAME_COUNT = 7
	cv2 = MockCV2()

try:
	from sklearn.feature_extraction.text import TfidfVectorizer
	from sklearn.metrics.pairwise import cosine_similarity
	from sklearn.cluster import KMeans
	SKLEARN_AVAILABLE = True
except ImportError:
	logger.warning("Scikit-learn not available, using basic text processing")
	SKLEARN_AVAILABLE = False
	class MockTfidf:
		def fit_transform(self, docs): return [[0.1] * 10] * len(docs)
		def get_feature_names_out(self): return [f"term_{i}" for i in range(10)]
	class MockSimilarity:
		@staticmethod
		def cosine_similarity(X, Y=None): return [[0.8]]
	class MockKMeans:
		def __init__(self, n_clusters=5): self.n_clusters = n_clusters
		def fit(self, X): return self
		def predict(self, X): return [0] * len(X)
		@property
		def cluster_centers_(self): return [[0.1] * 10] * self.n_clusters
	TfidfVectorizer = MockTfidf
	cosine_similarity = MockSimilarity.cosine_similarity
	KMeans = MockKMeans

try:
	import torch
	from transformers import AutoTokenizer, AutoModel
	TRANSFORMERS_AVAILABLE = True
except ImportError:
	logger.warning("Transformers not available, using basic embeddings")
	TRANSFORMERS_AVAILABLE = False
	class MockTokenizer:
		@staticmethod
		def from_pretrained(model_name): return MockTokenizer()
		def __call__(self, text, **kwargs): 
			return {"input_ids": [[1, 2, 3, 4, 5]], "attention_mask": [[1, 1, 1, 1, 1]]}
	class MockModel:
		@staticmethod
		def from_pretrained(model_name): return MockModel()
		def __call__(self, **kwargs):
			class MockOutput:
				last_hidden_state = [[0.1] * 768] * 5  # Mock embeddings
			return MockOutput()
	AutoTokenizer = MockTokenizer
	AutoModel = MockModel

import psycopg2
from pydantic import BaseModel, Field
from uuid_extensions import uuid7str

from .graph_manager import GraphManager
from .activity_tracker import track_database_activity, ActivityType, ActivitySeverity
from ..utils.error_handling import WizardErrorHandler, WizardErrorType, WizardErrorSeverity

logger = logging.getLogger(__name__)


class MediaType:
	"""Supported media types for multi-modal integration"""
	IMAGE = "image"
	AUDIO = "audio"
	VIDEO = "video"
	TEXT = "text"
	DOCUMENT = "document"
	UNKNOWN = "unknown"


class ProcessingMethod:
	"""Available processing methods for different media types"""
	FEATURE_EXTRACTION = "feature_extraction"
	SIMILARITY_ANALYSIS = "similarity_analysis"
	CONTENT_ANALYSIS = "content_analysis"
	METADATA_EXTRACTION = "metadata_extraction"
	CLASSIFICATION = "classification"


@dataclass
class MediaMetadata:
	"""Metadata for multi-modal media files"""
	media_id: str
	filename: str
	media_type: str
	mime_type: str
	file_size: int
	dimensions: Optional[Tuple[int, int]]
	duration: Optional[float]  # For audio/video
	encoding: Optional[str]
	created_at: datetime
	extracted_features: Dict[str, Any]
	similarity_hash: Optional[str]
	content_description: Optional[str]
	
	def to_dict(self) -> Dict[str, Any]:
		return {
			"media_id": self.media_id,
			"filename": self.filename,
			"media_type": self.media_type,
			"mime_type": self.mime_type,
			"file_size": self.file_size,
			"dimensions": self.dimensions,
			"duration": self.duration,
			"encoding": self.encoding,
			"created_at": self.created_at.isoformat(),
			"extracted_features": self.extracted_features,
			"similarity_hash": self.similarity_hash,
			"content_description": self.content_description
		}


@dataclass
class FeatureVector:
	"""Feature vector representation of media content"""
	media_id: str
	feature_type: str
	vector: np.ndarray
	confidence: float
	extraction_method: str
	timestamp: datetime
	
	def to_dict(self) -> Dict[str, Any]:
		return {
			"media_id": self.media_id,
			"feature_type": self.feature_type,
			"vector": self.vector.tolist() if isinstance(self.vector, np.ndarray) else self.vector,
			"confidence": self.confidence,
			"extraction_method": self.extraction_method,
			"timestamp": self.timestamp.isoformat()
		}


class ImageProcessor:
	"""Advanced image processing and feature extraction"""
	
	def __init__(self):
		self.supported_formats = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.webp'}
		
	def extract_features(self, image_data: bytes, filename: str) -> Dict[str, Any]:
		"""Extract comprehensive features from image data"""
		features = {}
		
		try:
			# Load image
			image = Image.open(io.BytesIO(image_data))
			
			# Basic metadata
			features['width'], features['height'] = image.size
			features['mode'] = image.mode
			features['format'] = image.format
			
			# Color analysis
			features.update(self._analyze_colors(image))
			
			# Texture analysis
			features.update(self._analyze_texture(image))
			
			# Edge detection
			features.update(self._analyze_edges(image))
			
			# Histogram features
			features.update(self._extract_histogram_features(image))
			
			# Perceptual hash for similarity
			features['perceptual_hash'] = self._calculate_perceptual_hash(image)
			
			logger.info(f"Extracted {len(features)} image features from {filename}")
			
		except Exception as e:
			logger.error(f"Image feature extraction failed for {filename}: {e}")
			features = {"error": str(e)}
			
		return features
	
	def _analyze_colors(self, image: Image.Image) -> Dict[str, Any]:
		"""Analyze color composition of image"""
		# Convert to RGB if necessary
		if image.mode != 'RGB':
			image = image.convert('RGB')
		
		# Get dominant colors using k-means
		pixels = np.array(image).reshape(-1, 3)
		
		# Sample pixels for performance
		if len(pixels) > 10000:
			indices = np.random.choice(len(pixels), 10000, replace=False)
			pixels = pixels[indices]
		
		kmeans = KMeans(n_clusters=5, random_state=42)
		kmeans.fit(pixels)
		
		dominant_colors = kmeans.cluster_centers_.astype(int).tolist()
		color_percentages = np.bincount(kmeans.labels_) / len(kmeans.labels_)
		
		# Calculate color statistics
		mean_color = pixels.mean(axis=0)
		std_color = pixels.std(axis=0)
		
		return {
			"dominant_colors": dominant_colors,
			"color_percentages": color_percentages.tolist(),
			"mean_color": mean_color.tolist(),
			"color_std": std_color.tolist(),
			"brightness": float(np.mean(pixels)),
			"saturation": float(np.std(pixels))
		}
	
	def _analyze_texture(self, image: Image.Image) -> Dict[str, Any]:
		"""Analyze texture properties using various filters"""
		# Convert to grayscale
		gray = image.convert('L')
		gray_array = np.array(gray)
		
		# Apply different filters
		edges = cv2.Canny(gray_array, 50, 150)
		
		# Calculate texture metrics
		edge_density = np.sum(edges > 0) / edges.size
		
		# Sobel operators for gradient analysis
		sobel_x = cv2.Sobel(gray_array, cv2.CV_64F, 1, 0, ksize=3)
		sobel_y = cv2.Sobel(gray_array, cv2.CV_64F, 0, 1, ksize=3)
		
		gradient_magnitude = np.sqrt(sobel_x**2 + sobel_y**2)
		
		return {
			"edge_density": float(edge_density),
			"mean_gradient": float(np.mean(gradient_magnitude)),
			"gradient_std": float(np.std(gradient_magnitude)),
			"texture_energy": float(np.sum(gradient_magnitude**2))
		}
	
	def _analyze_edges(self, image: Image.Image) -> Dict[str, Any]:
		"""Analyze edge characteristics"""
		# Convert to grayscale
		gray = image.convert('L')
		gray_array = np.array(gray)
		
		# Edge detection with different thresholds
		edges_low = cv2.Canny(gray_array, 30, 100)
		edges_high = cv2.Canny(gray_array, 100, 200)
		
		# Find contours
		contours, _ = cv2.findContours(edges_high, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
		
		# Calculate edge statistics
		total_edge_length = sum(cv2.arcLength(contour, True) for contour in contours)
		
		return {
			"edge_count_low": int(np.sum(edges_low > 0)),
			"edge_count_high": int(np.sum(edges_high > 0)),
			"contour_count": len(contours),
			"total_edge_length": float(total_edge_length),
			"edge_complexity": float(total_edge_length / (image.width * image.height))
		}
	
	def _extract_histogram_features(self, image: Image.Image) -> Dict[str, Any]:
		"""Extract histogram-based features"""
		# RGB histograms
		if image.mode == 'RGB':
			r, g, b = image.split()
			
			r_hist = np.histogram(np.array(r), bins=32, range=(0, 256))[0]
			g_hist = np.histogram(np.array(g), bins=32, range=(0, 256))[0]
			b_hist = np.histogram(np.array(b), bins=32, range=(0, 256))[0]
			
			return {
				"red_histogram": r_hist.tolist(),
				"green_histogram": g_hist.tolist(),
				"blue_histogram": b_hist.tolist(),
				"histogram_entropy": float(-np.sum(r_hist * np.log2(r_hist + 1e-10)))
			}
		else:
			# Grayscale histogram
			gray_array = np.array(image.convert('L'))
			hist = np.histogram(gray_array, bins=32, range=(0, 256))[0]
			
			return {
				"grayscale_histogram": hist.tolist(),
				"histogram_entropy": float(-np.sum(hist * np.log2(hist + 1e-10)))
			}
	
	def _calculate_perceptual_hash(self, image: Image.Image) -> str:
		"""Calculate perceptual hash for similarity comparison"""
		# Resize to 8x8 and convert to grayscale
		small = image.resize((8, 8), Image.LANCZOS).convert('L')
		pixels = list(small.getdata())
		
		# Calculate average
		avg = sum(pixels) / len(pixels)
		
		# Create hash
		bits = []
		for pixel in pixels:
			bits.append('1' if pixel > avg else '0')
		
		# Convert to hex
		hash_hex = hex(int(''.join(bits), 2))[2:]
		return hash_hex.zfill(16)


class AudioProcessor:
	"""Advanced audio processing and feature extraction"""
	
	def __init__(self):
		self.supported_formats = {'.mp3', '.wav', '.flac', '.m4a', '.ogg', '.aac'}
		self.sample_rate = 22050
		
	def extract_features(self, audio_data: bytes, filename: str) -> Dict[str, Any]:
		"""Extract comprehensive features from audio data"""
		features = {}
		
		try:
			# Load audio data
			audio_io = io.BytesIO(audio_data)
			y, sr = librosa.load(audio_io, sr=self.sample_rate)
			
			# Basic properties
			features['duration'] = float(len(y) / sr)
			features['sample_rate'] = sr
			features['channels'] = 1  # librosa loads as mono by default
			
			# Spectral features
			features.update(self._extract_spectral_features(y, sr))
			
			# Rhythmic features
			features.update(self._extract_rhythmic_features(y, sr))
			
			# Timbral features
			features.update(self._extract_timbral_features(y, sr))
			
			# Energy and dynamics
			features.update(self._extract_energy_features(y, sr))
			
			# Audio fingerprint for similarity
			features['audio_fingerprint'] = self._calculate_audio_fingerprint(y, sr)
			
			logger.info(f"Extracted {len(features)} audio features from {filename}")
			
		except Exception as e:
			logger.error(f"Audio feature extraction failed for {filename}: {e}")
			features = {"error": str(e)}
			
		return features
	
	def _extract_spectral_features(self, y: np.ndarray, sr: int) -> Dict[str, Any]:
		"""Extract spectral features from audio"""
		# Compute spectral features
		spectral_centroids = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
		spectral_rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)[0]
		spectral_bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr)[0]
		zero_crossing_rate = librosa.feature.zero_crossing_rate(y)[0]
		
		# MFCCs (Mel-frequency cepstral coefficients)
		mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
		
		return {
			"spectral_centroid_mean": float(np.mean(spectral_centroids)),
			"spectral_centroid_std": float(np.std(spectral_centroids)),
			"spectral_rolloff_mean": float(np.mean(spectral_rolloff)),
			"spectral_bandwidth_mean": float(np.mean(spectral_bandwidth)),
			"zero_crossing_rate_mean": float(np.mean(zero_crossing_rate)),
			"mfcc_features": [float(np.mean(mfcc)) for mfcc in mfccs]
		}
	
	def _extract_rhythmic_features(self, y: np.ndarray, sr: int) -> Dict[str, Any]:
		"""Extract rhythmic and tempo features"""
		# Tempo estimation
		tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
		
		# Rhythm patterns
		onset_frames = librosa.onset.onset_detect(y=y, sr=sr)
		onset_times = librosa.frames_to_time(onset_frames, sr=sr)
		
		# Beat consistency
		if len(beats) > 1:
			beat_intervals = np.diff(librosa.frames_to_time(beats, sr=sr))
			beat_consistency = 1.0 / (np.std(beat_intervals) + 1e-10)
		else:
			beat_consistency = 0.0
		
		return {
			"tempo": float(tempo),
			"beat_count": len(beats),
			"onset_density": float(len(onset_frames) / (len(y) / sr)),
			"beat_consistency": float(beat_consistency),
			"rhythm_regularity": float(np.std(beat_intervals) if len(beats) > 1 else 0.0)
		}
	
	def _extract_timbral_features(self, y: np.ndarray, sr: int) -> Dict[str, Any]:
		"""Extract timbral characteristics"""
		# Chromagram for pitch analysis
		chroma = librosa.feature.chroma_stft(y=y, sr=sr)
		
		# Spectral contrast
		contrast = librosa.feature.spectral_contrast(y=y, sr=sr)
		
		# Tonnetz (harmonic network)
		tonnetz = librosa.feature.tonnetz(y=y, sr=sr)
		
		return {
			"chroma_mean": [float(np.mean(c)) for c in chroma],
			"spectral_contrast_mean": [float(np.mean(c)) for c in contrast],
			"tonnetz_mean": [float(np.mean(t)) for t in tonnetz],
			"harmonic_ratio": float(np.mean(chroma)),
			"timbral_complexity": float(np.mean(contrast))
		}
	
	def _extract_energy_features(self, y: np.ndarray, sr: int) -> Dict[str, Any]:
		"""Extract energy and dynamics features"""
		# RMS energy
		rms = librosa.feature.rms(y=y)[0]
		
		# Dynamic range
		dynamic_range = np.max(y) - np.min(y)
		
		# Energy distribution
		energy_percentiles = np.percentile(rms, [25, 50, 75, 90, 95])
		
		return {
			"rms_energy_mean": float(np.mean(rms)),
			"rms_energy_std": float(np.std(rms)),
			"dynamic_range": float(dynamic_range),
			"energy_percentiles": energy_percentiles.tolist(),
			"loudness_variation": float(np.std(rms))
		}
	
	def _calculate_audio_fingerprint(self, y: np.ndarray, sr: int) -> str:
		"""Calculate audio fingerprint for similarity comparison"""
		# Simple spectral fingerprint
		n_fft = 2048
		hop_length = 512
		
		# Compute short-time Fourier transform
		stft = librosa.stft(y, n_fft=n_fft, hop_length=hop_length)
		magnitude = np.abs(stft)
		
		# Create binary fingerprint based on spectral peaks
		peaks = magnitude > np.mean(magnitude, axis=1, keepdims=True)
		
		# Convert to hash
		fingerprint_bits = peaks.flatten()[:1024]  # Limit size
		fingerprint_int = int(''.join(['1' if bit else '0' for bit in fingerprint_bits[:64]]), 2)
		
		return hex(fingerprint_int)[2:].zfill(16)


class TextProcessor:
	"""Advanced text processing with semantic analysis"""
	
	def __init__(self):
		self.vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
		try:
			# Initialize transformer model for embeddings
			self.tokenizer = AutoTokenizer.from_pretrained('sentence-transformers/all-MiniLM-L6-v2')
			self.model = AutoModel.from_pretrained('sentence-transformers/all-MiniLM-L6-v2')
		except:
			logger.warning("Transformer model not available, using TF-IDF only")
			self.tokenizer = None
			self.model = None
	
	def extract_features(self, text: str, filename: str) -> Dict[str, Any]:
		"""Extract comprehensive features from text"""
		features = {}
		
		try:
			# Basic text statistics
			features.update(self._extract_basic_stats(text))
			
			# Linguistic features
			features.update(self._extract_linguistic_features(text))
			
			# Semantic features
			features.update(self._extract_semantic_features(text))
			
			# Content classification
			features.update(self._classify_content(text))
			
			logger.info(f"Extracted {len(features)} text features from {filename}")
			
		except Exception as e:
			logger.error(f"Text feature extraction failed for {filename}: {e}")
			features = {"error": str(e)}
			
		return features
	
	def _extract_basic_stats(self, text: str) -> Dict[str, Any]:
		"""Extract basic text statistics"""
		words = text.split()
		sentences = text.split('.')
		paragraphs = text.split('\n\n')
		
		# Character analysis
		char_counts = {
			'letters': sum(c.isalpha() for c in text),
			'digits': sum(c.isdigit() for c in text),
			'spaces': sum(c.isspace() for c in text),
			'punctuation': sum(not c.isalnum() and not c.isspace() for c in text)
		}
		
		return {
			"character_count": len(text),
			"word_count": len(words),
			"sentence_count": len(sentences),
			"paragraph_count": len(paragraphs),
			"average_word_length": np.mean([len(word) for word in words]) if words else 0,
			"average_sentence_length": np.mean([len(s.split()) for s in sentences if s.strip()]),
			"character_distribution": char_counts,
			"lexical_diversity": len(set(words)) / len(words) if words else 0
		}
	
	def _extract_linguistic_features(self, text: str) -> Dict[str, Any]:
		"""Extract linguistic features"""
		words = text.lower().split()
		
		# Readability metrics (simplified)
		sentences = [s for s in text.split('.') if s.strip()]
		avg_sentence_length = np.mean([len(s.split()) for s in sentences]) if sentences else 0
		avg_word_length = np.mean([len(word) for word in words]) if words else 0
		
		# Simple readability score
		readability_score = 206.835 - (1.015 * avg_sentence_length) - (84.6 * (avg_word_length / avg_sentence_length))
		
		# Part-of-speech patterns (simplified)
		common_words = ['the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by']
		function_word_ratio = sum(1 for word in words if word in common_words) / len(words) if words else 0
		
		return {
			"readability_score": float(readability_score),
			"function_word_ratio": float(function_word_ratio),
			"average_sentence_length": float(avg_sentence_length),
			"average_word_length": float(avg_word_length),
			"text_complexity": float(avg_word_length * avg_sentence_length / 100)
		}
	
	def _extract_semantic_features(self, text: str) -> Dict[str, Any]:
		"""Extract semantic features using embeddings"""
		features = {}
		
		# TF-IDF features
		try:
			tfidf_vector = self.vectorizer.fit_transform([text])
			tfidf_features = tfidf_vector.toarray()[0]
			
			features["tfidf_mean"] = float(np.mean(tfidf_features))
			features["tfidf_std"] = float(np.std(tfidf_features))
			features["tfidf_max"] = float(np.max(tfidf_features))
			features["tfidf_nonzero_ratio"] = float(np.sum(tfidf_features > 0) / len(tfidf_features))
			
		except Exception as e:
			logger.warning(f"TF-IDF extraction failed: {e}")
		
		# Transformer embeddings
		if self.tokenizer and self.model:
			try:
				inputs = self.tokenizer(text[:512], return_tensors="pt", truncation=True, padding=True)
				
				with torch.no_grad():
					outputs = self.model(**inputs)
					embeddings = outputs.last_hidden_state.mean(dim=1).squeeze()
				
				features["embedding_mean"] = float(torch.mean(embeddings))
				features["embedding_std"] = float(torch.std(embeddings))
				features["embedding_norm"] = float(torch.norm(embeddings))
				
			except Exception as e:
				logger.warning(f"Transformer embedding extraction failed: {e}")
		
		return features
	
	def _classify_content(self, text: str) -> Dict[str, Any]:
		"""Classify text content type and sentiment"""
		# Simple keyword-based classification
		technical_keywords = ['algorithm', 'data', 'system', 'process', 'method', 'analysis', 'research']
		business_keywords = ['market', 'sales', 'revenue', 'customer', 'business', 'strategy', 'profit']
		academic_keywords = ['study', 'research', 'analysis', 'findings', 'methodology', 'conclusion']
		
		text_lower = text.lower()
		
		technical_score = sum(1 for keyword in technical_keywords if keyword in text_lower)
		business_score = sum(1 for keyword in business_keywords if keyword in text_lower)
		academic_score = sum(1 for keyword in academic_keywords if keyword in text_lower)
		
		# Sentiment analysis (simplified)
		positive_words = ['good', 'great', 'excellent', 'positive', 'success', 'improvement', 'beneficial']
		negative_words = ['bad', 'poor', 'negative', 'problem', 'issue', 'failure', 'decline']
		
		positive_count = sum(1 for word in positive_words if word in text_lower)
		negative_count = sum(1 for word in negative_words if word in text_lower)
		
		sentiment_score = (positive_count - negative_count) / (positive_count + negative_count + 1)
		
		return {
			"content_type_scores": {
				"technical": technical_score,
				"business": business_score,
				"academic": academic_score
			},
			"sentiment_score": float(sentiment_score),
			"dominant_content_type": max([
				("technical", technical_score),
				("business", business_score),
				("academic", academic_score)
			], key=lambda x: x[1])[0]
		}


class MultiModalIntegration:
	"""Main multi-modal data integration system"""
	
	def __init__(self, graph_name: str):
		self.graph_name = graph_name
		self.graph_manager = GraphManager(graph_name)
		self.error_handler = WizardErrorHandler()
		
		# Initialize processors
		self.image_processor = ImageProcessor()
		self.audio_processor = AudioProcessor()
		self.text_processor = TextProcessor()
		
		# Media storage and indexing
		self.media_index = {}
		self.feature_index = defaultdict(list)
		
		logger.info(f"Multi-modal integration system initialized for graph: {graph_name}")
	
	def process_media_file(self, file_data: bytes, filename: str, metadata: Dict[str, Any] = None) -> MediaMetadata:
		"""Process a media file and extract features"""
		start_time = datetime.now()
		
		try:
			# Determine media type
			media_type = self._detect_media_type(filename, file_data)
			mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
			
			media_id = uuid7str()
			
			# Extract features based on media type
			if media_type == MediaType.IMAGE:
				features = self.image_processor.extract_features(file_data, filename)
			elif media_type == MediaType.AUDIO:
				features = self.audio_processor.extract_features(file_data, filename)
			elif media_type == MediaType.TEXT:
				text_content = file_data.decode('utf-8', errors='ignore')
				features = self.text_processor.extract_features(text_content, filename)
			else:
				features = {"media_type": media_type, "unsupported": True}
			
			# Calculate similarity hash
			similarity_hash = self._calculate_similarity_hash(file_data, features)
			
			# Create metadata object
			media_metadata = MediaMetadata(
				media_id=media_id,
				filename=filename,
				media_type=media_type,
				mime_type=mime_type,
				file_size=len(file_data),
				dimensions=features.get('dimensions') or (features.get('width'), features.get('height')),
				duration=features.get('duration'),
				encoding=features.get('encoding'),
				created_at=start_time,
				extracted_features=features,
				similarity_hash=similarity_hash,
				content_description=self._generate_content_description(features, media_type)
			)
			
			# Store in graph database
			self._store_media_in_graph(media_metadata, metadata or {})
			
			# Update indexes
			self._update_indexes(media_metadata)
			
			logger.info(f"Processed media file: {filename} ({media_type})")
			
			return media_metadata
			
		except Exception as e:
			self.error_handler.handle_error(
				e, WizardErrorType.DATA_PROCESSING_ERROR, WizardErrorSeverity.MEDIUM
			)
			logger.error(f"Media processing failed for {filename}: {e}")
			raise
	
	def find_similar_media(self, media_id: str, similarity_threshold: float = 0.8, top_k: int = 10) -> List[Dict[str, Any]]:
		"""Find similar media items based on extracted features"""
		try:
			if media_id not in self.media_index:
				return []
			
			target_media = self.media_index[media_id]
			target_features = target_media.extracted_features
			
			similarities = []
			
			# Compare with all other media of the same type
			for other_id, other_media in self.media_index.items():
				if other_id == media_id or other_media.media_type != target_media.media_type:
					continue
				
				similarity = self._calculate_feature_similarity(target_features, other_media.extracted_features)
				
				if similarity >= similarity_threshold:
					similarities.append({
						"media_id": other_id,
						"filename": other_media.filename,
						"similarity_score": similarity,
						"media_type": other_media.media_type
					})
			
			# Sort by similarity and return top_k
			similarities.sort(key=lambda x: x["similarity_score"], reverse=True)
			return similarities[:top_k]
			
		except Exception as e:
			logger.error(f"Similarity search failed: {e}")
			return []
	
	def cluster_media_by_similarity(self, media_type: str = None, n_clusters: int = 5) -> Dict[str, List[str]]:
		"""Cluster media items by feature similarity"""
		try:
			# Filter media by type if specified
			if media_type:
				media_items = [m for m in self.media_index.values() if m.media_type == media_type]
			else:
				media_items = list(self.media_index.values())
			
			if len(media_items) < n_clusters:
				return {"cluster_0": [m.media_id for m in media_items]}
			
			# Extract feature vectors
			feature_vectors = []
			media_ids = []
			
			for media in media_items:
				vector = self._extract_feature_vector(media.extracted_features)
				if vector is not None:
					feature_vectors.append(vector)
					media_ids.append(media.media_id)
			
			if not feature_vectors:
				return {}
			
			# Perform clustering
			feature_matrix = np.array(feature_vectors)
			kmeans = KMeans(n_clusters=min(n_clusters, len(feature_vectors)), random_state=42)
			cluster_labels = kmeans.fit_predict(feature_matrix)
			
			# Group media by clusters
			clusters = defaultdict(list)
			for media_id, label in zip(media_ids, cluster_labels):
				clusters[f"cluster_{label}"].append(media_id)
			
			return dict(clusters)
			
		except Exception as e:
			logger.error(f"Media clustering failed: {e}")
			return {}
	
	def create_media_relationships(self, similarity_threshold: float = 0.7) -> List[Dict[str, Any]]:
		"""Create relationships between similar media items in the graph"""
		relationships_created = []
		
		try:
			for media_id in self.media_index:
				similar_media = self.find_similar_media(media_id, similarity_threshold)
				
				for similar in similar_media:
					# Create similarity relationship
					relationship_props = {
						"similarity_score": similar["similarity_score"],
						"relationship_type": "SIMILAR_TO",
						"created_at": datetime.now().isoformat(),
						"confidence": similar["similarity_score"]
					}
					
					try:
						self.graph_manager.create_relationship(
							media_id, similar["media_id"], "SIMILAR_TO", relationship_props
						)
						
						relationships_created.append({
							"from": media_id,
							"to": similar["media_id"],
							"similarity": similar["similarity_score"]
						})
						
					except Exception as e:
						logger.warning(f"Failed to create relationship: {e}")
			
			logger.info(f"Created {len(relationships_created)} media similarity relationships")
			return relationships_created
			
		except Exception as e:
			logger.error(f"Relationship creation failed: {e}")
			return []
	
	def _detect_media_type(self, filename: str, file_data: bytes) -> str:
		"""Detect media type from filename and content"""
		ext = Path(filename).suffix.lower()
		
		if ext in self.image_processor.supported_formats:
			return MediaType.IMAGE
		elif ext in self.audio_processor.supported_formats:
			return MediaType.AUDIO
		elif ext in {'.mp4', '.avi', '.mov', '.mkv', '.webm'}:
			return MediaType.VIDEO
		elif ext in {'.txt', '.md', '.rst', '.csv'}:
			return MediaType.TEXT
		elif ext in {'.pdf', '.doc', '.docx', '.ppt', '.pptx'}:
			return MediaType.DOCUMENT
		else:
			# Try to detect from content
			try:
				file_data.decode('utf-8')
				return MediaType.TEXT
			except UnicodeDecodeError:
				return MediaType.UNKNOWN
	
	def _calculate_similarity_hash(self, file_data: bytes, features: Dict[str, Any]) -> str:
		"""Calculate a hash for similarity comparison"""
		if "perceptual_hash" in features:
			return features["perceptual_hash"]
		elif "audio_fingerprint" in features:
			return features["audio_fingerprint"]
		else:
			# Fallback to content hash
			return hashlib.md5(file_data).hexdigest()
	
	def _generate_content_description(self, features: Dict[str, Any], media_type: str) -> str:
		"""Generate human-readable content description"""
		if media_type == MediaType.IMAGE:
			desc = f"Image with dimensions {features.get('width', 'unknown')}x{features.get('height', 'unknown')}"
			if 'dominant_colors' in features:
				desc += f", dominant colors present"
			if features.get('edge_density', 0) > 0.1:
				desc += f", high detail/texture"
			return desc
			
		elif media_type == MediaType.AUDIO:
			duration = features.get('duration', 0)
			desc = f"Audio file, duration: {duration:.1f}s"
			if 'tempo' in features:
				desc += f", tempo: {features['tempo']:.0f} BPM"
			return desc
			
		elif media_type == MediaType.TEXT:
			word_count = features.get('word_count', 0)
			content_type = features.get('dominant_content_type', 'general')
			desc = f"Text document, {word_count} words, {content_type} content"
			return desc
			
		else:
			return f"Media file of type {media_type}"
	
	def _store_media_in_graph(self, media_metadata: MediaMetadata, additional_metadata: Dict[str, Any]):
		"""Store media metadata in the graph database"""
		try:
			# Create media node
			node_properties = {
				**media_metadata.to_dict(),
				**additional_metadata,
				"node_type": "MEDIA"
			}
			
			self.graph_manager.create_node("MEDIA", node_properties)
			
			# Create feature nodes and relationships
			self._create_feature_nodes(media_metadata)
			
		except Exception as e:
			logger.error(f"Failed to store media in graph: {e}")
			raise
	
	def _create_feature_nodes(self, media_metadata: MediaMetadata):
		"""Create nodes for specific features and link to media"""
		try:
			features = media_metadata.extracted_features
			
			# Create nodes for significant features
			if media_metadata.media_type == MediaType.IMAGE:
				# Color palette node
				if 'dominant_colors' in features:
					color_node_props = {
						"node_type": "COLOR_PALETTE",
						"colors": features['dominant_colors'],
						"percentages": features.get('color_percentages', []),
						"brightness": features.get('brightness', 0)
					}
					
					color_node_id = self.graph_manager.create_node("COLOR_PALETTE", color_node_props)
					self.graph_manager.create_relationship(
						media_metadata.media_id, color_node_id, "HAS_COLOR_PALETTE", {}
					)
			
			elif media_metadata.media_type == MediaType.AUDIO:
				# Musical characteristics node
				if 'tempo' in features:
					music_node_props = {
						"node_type": "MUSICAL_FEATURES",
						"tempo": features['tempo'],
						"beat_count": features.get('beat_count', 0),
						"energy": features.get('rms_energy_mean', 0)
					}
					
					music_node_id = self.graph_manager.create_node("MUSICAL_FEATURES", music_node_props)
					self.graph_manager.create_relationship(
						media_metadata.media_id, music_node_id, "HAS_MUSICAL_FEATURES", {}
					)
			
		except Exception as e:
			logger.warning(f"Failed to create feature nodes: {e}")
	
	def _update_indexes(self, media_metadata: MediaMetadata):
		"""Update in-memory indexes"""
		self.media_index[media_metadata.media_id] = media_metadata
		
		# Update feature-based indexes
		media_type = media_metadata.media_type
		self.feature_index[media_type].append(media_metadata.media_id)
	
	def _calculate_feature_similarity(self, features1: Dict[str, Any], features2: Dict[str, Any]) -> float:
		"""Calculate similarity between two feature sets"""
		try:
			# Extract numerical features
			vec1 = self._extract_feature_vector(features1)
			vec2 = self._extract_feature_vector(features2)
			
			if vec1 is None or vec2 is None:
				return 0.0
			
			# Calculate cosine similarity
			similarity = cosine_similarity([vec1], [vec2])[0][0]
			return float(similarity)
			
		except Exception:
			return 0.0
	
	def _extract_feature_vector(self, features: Dict[str, Any]) -> Optional[np.ndarray]:
		"""Extract numerical feature vector from features dictionary"""
		try:
			numeric_values = []
			
			def extract_numeric(obj, prefix=""):
				if isinstance(obj, (int, float)):
					numeric_values.append(float(obj))
				elif isinstance(obj, list):
					for item in obj[:10]:  # Limit list size
						if isinstance(item, (int, float)):
							numeric_values.append(float(item))
				elif isinstance(obj, dict):
					for key, value in obj.items():
						if isinstance(value, (int, float)):
							numeric_values.append(float(value))
						elif isinstance(value, list) and len(value) > 0 and isinstance(value[0], (int, float)):
							numeric_values.extend([float(x) for x in value[:5]])  # Limit
			
			extract_numeric(features)
			
			if not numeric_values:
				return None
			
			# Normalize to fixed size
			target_size = 50
			if len(numeric_values) > target_size:
				# Downsample
				indices = np.linspace(0, len(numeric_values) - 1, target_size, dtype=int)
				numeric_values = [numeric_values[i] for i in indices]
			elif len(numeric_values) < target_size:
				# Pad with zeros
				numeric_values.extend([0.0] * (target_size - len(numeric_values)))
			
			return np.array(numeric_values)
			
		except Exception:
			return None
	
	def get_media_statistics(self) -> Dict[str, Any]:
		"""Get comprehensive statistics about processed media"""
		try:
			stats = {
				"total_media_items": len(self.media_index),
				"media_by_type": {},
				"total_features_extracted": 0,
				"average_file_size": 0,
				"processing_summary": {}
			}
			
			# Count by media type
			for media in self.media_index.values():
				media_type = media.media_type
				if media_type not in stats["media_by_type"]:
					stats["media_by_type"][media_type] = {
						"count": 0,
						"total_size": 0,
						"feature_types": set()
					}
				
				stats["media_by_type"][media_type]["count"] += 1
				stats["media_by_type"][media_type]["total_size"] += media.file_size
				stats["media_by_type"][media_type]["feature_types"].update(media.extracted_features.keys())
			
			# Calculate averages
			if stats["total_media_items"] > 0:
				total_size = sum(media.file_size for media in self.media_index.values())
				stats["average_file_size"] = total_size / stats["total_media_items"]
			
			# Convert sets to lists for JSON serialization
			for media_type_stats in stats["media_by_type"].values():
				media_type_stats["feature_types"] = list(media_type_stats["feature_types"])
			
			return stats
			
		except Exception as e:
			logger.error(f"Statistics calculation failed: {e}")
			return {"error": str(e)}


# Global multi-modal integration instances
_multimodal_systems = {}


def get_multimodal_system(graph_name: str) -> MultiModalIntegration:
	"""Get or create a multi-modal integration system for the specified graph"""
	if graph_name not in _multimodal_systems:
		_multimodal_systems[graph_name] = MultiModalIntegration(graph_name)
	return _multimodal_systems[graph_name]


def process_media_batch(graph_name: str, media_files: List[Dict[str, Any]], 
					   max_workers: int = 4) -> List[MediaMetadata]:
	"""Convenience function to process multiple media files in parallel"""
	multimodal_system = get_multimodal_system(graph_name)
	results = []
	
	with ThreadPoolExecutor(max_workers=max_workers) as executor:
		# Submit all files for processing
		future_to_file = {
			executor.submit(
				multimodal_system.process_media_file, 
				file_info["data"], 
				file_info["filename"], 
				file_info.get("metadata", {})
			): file_info
			for file_info in media_files
		}
		
		# Collect results
		for future in future_to_file:
			file_info = future_to_file[future]
			try:
				result = future.result()
				results.append(result)
			except Exception as e:
				logger.error(f"Failed to process media file {file_info['filename']}: {e}")
	
	
	return results


def get_multimodal_integration(graph_name: str) -> MultiModalIntegration:
	"""Get multimodal integration instance (alias for get_multimodal_system)"""
	return get_multimodal_system(graph_name)


def analyze_media_similarity(graph_name: str, media_type: str = "all", 
							 threshold: float = 0.7) -> Dict[str, Any]:
	"""Analyze similarity between media items in a graph"""
	multimodal_system = get_multimodal_system(graph_name)
	return multimodal_system.find_similar_media(media_type, threshold)


def get_media_analysis_report(graph_name: str) -> Dict[str, Any]:
	"""Get comprehensive analysis report for media in a graph"""
	multimodal_system = get_multimodal_system(graph_name)
	return multimodal_system.get_statistics()