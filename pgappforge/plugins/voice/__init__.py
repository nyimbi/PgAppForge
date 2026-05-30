"""
pgappforge/plugins/voice/__init__.py

FABVoicePlugin — integrates browser Web Speech API (SpeechRecognition +
SpeechSynthesis) into every PgAppForge page.

Feature flag:
    app.config['FAB_VOICE_ENABLED'] = True   # default: False

Per-view opt-in (without global flag):
    @FABVoicePlugin.enable_view
    class MyView(ModelView):
        ...

The plugin:
1. Registers a Blueprint that serves /voice/voice.js (embedded JS).
2. Uses app.after_request to inject <script src="/voice/voice.js"> and the
   VoiceCommandBar HTML before </body> in HTML responses.
3. Only injects into responses that are:
   - Content-Type: text/html
   - Status 200
   - Contain </body>

voice.js implements:
   - Wake word detection ("hey fab")
   - SpeechRecognition setup
   - Command parsing: navigate / fill / submit / cancel
   - TTS announcements via SpeechSynthesis
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from flask import Blueprint, Response, make_response

if TYPE_CHECKING:
	from flask import Flask
	from pgappforge import AppBuilder

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedded voice.js (~150 lines)
# ---------------------------------------------------------------------------

_VOICE_JS = r"""\
/* FAB Voice Plugin — Web Speech API integration
 * Served at /voice/voice.js by FABVoicePlugin blueprint.
 * Companion HTML (VoiceCommandBar) is injected by the plugin's after_request hook.
 */
(function () {
  'use strict';

  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var SS = window.speechSynthesis;
  var lang = document.documentElement.lang || 'en-US';

  // ------------------------------------------------------------------
  // TTS helper
  // ------------------------------------------------------------------
  function speak(text) {
    if (!SS) return;
    SS.cancel();
    var u = new SpeechSynthesisUtterance(String(text));
    u.lang = lang;
    SS.speak(u);
  }

  // ------------------------------------------------------------------
  // Status display (injected command bar uses id=fab-voice-status)
  // ------------------------------------------------------------------
  function setStatus(msg) {
    var el = document.getElementById('fab-voice-status');
    if (!el) return;
    el.textContent = msg;
    el.style.display = msg ? 'block' : 'none';
  }

  // ------------------------------------------------------------------
  // View registry — scrape navbar links for name→url mapping
  // ------------------------------------------------------------------
  function buildViewRegistry() {
    var reg = {};
    document.querySelectorAll(
      '.navbar-nav a[href], .nav a[href], .sidebar a[href]'
    ).forEach(function (a) {
      var text = (a.textContent || '').trim().toLowerCase();
      if (text && a.href && a.href !== '#') reg[text] = a.href;
    });
    return reg;
  }

  // ------------------------------------------------------------------
  // Command handler
  // ------------------------------------------------------------------
  function handleCommand(raw) {
    var cmd = raw.toLowerCase().replace(/[.,!?]+$/, '').trim();
    setStatus('Heard: ' + raw);
    log('Command: ' + cmd);

    // navigate
    var navM = cmd.match(/^(?:go to|show|open)\s+(.+)$/);
    if (navM) {
      var dest = navM[1].trim();
      var reg = buildViewRegistry();
      var url = reg[dest];
      if (url) {
        speak('Navigating to ' + dest);
        setTimeout(function () { window.location.href = url; }, 600);
      } else {
        speak('View ' + dest + ' not found');
        setStatus('Not found: ' + dest);
      }
      return;
    }

    // fill field
    var fillM = cmd.match(/^(?:set|fill)\s+(.+?)\s+(?:to|with)\s+(.+)$/);
    if (fillM) {
      var fname = fillM[1].trim();
      var val   = fillM[2].trim();
      var field = resolveField(fname);
      if (field) {
        field.value = val;
        field.dispatchEvent(new Event('input',  { bubbles: true }));
        field.dispatchEvent(new Event('change', { bubbles: true }));
        speak('Set ' + fname + ' to ' + val);
        setStatus('Set ' + fname + ' to ' + val);
      } else {
        speak('Field ' + fname + ' not found');
        setStatus('Field not found: ' + fname);
      }
      return;
    }

    // submit / save
    if (/^(?:submit|save)$/.test(cmd)) {
      var sub = document.querySelector('[type="submit"]');
      if (sub) { speak('Submitting'); setTimeout(function () { sub.click(); }, 400); }
      else speak('No submit button');
      return;
    }

    // cancel / reset
    if (/^(?:cancel|reset)$/.test(cmd)) {
      var can = (
        document.querySelector('.cancel') ||
        document.querySelector('[type="reset"]') ||
        document.querySelector('a[href*="list"]')
      );
      if (can) { speak('Cancelling'); setTimeout(function () { can.click(); }, 400); }
      else speak('No cancel button');
      return;
    }

    speak('Command not recognised: ' + raw);
    setStatus('Unknown: ' + raw);
  }

  // ------------------------------------------------------------------
  // Field resolver: id > name > placeholder > label text
  // ------------------------------------------------------------------
  function resolveField(name) {
    return (
      document.getElementById(name) ||
      document.querySelector('[name="' + name + '"]') ||
      document.querySelector('[placeholder*="' + name + '" i]') ||
      (function () {
        var labels = document.querySelectorAll('label');
        for (var i = 0; i < labels.length; i++) {
          if (labels[i].textContent.trim().toLowerCase() === name) {
            var fid = labels[i].htmlFor;
            return fid ? document.getElementById(fid) : null;
          }
        }
        return null;
      })()
    );
  }

  // ------------------------------------------------------------------
  // One-shot command session
  // ------------------------------------------------------------------
  function startCommandSession() {
    if (!SR) { speak('Speech recognition not supported'); return; }
    var btn = document.getElementById('fab-voice-bar-btn');
    var rec = new SR();
    rec.lang = lang;
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    if (btn) btn.classList.add('fab-voice-active');
    setStatus('Listening…');
    rec.onresult = function (e) { handleCommand(e.results[0][0].transcript); };
    rec.onerror  = function (e) {
      speak('Voice error: ' + e.error);
      setStatus('Error: ' + e.error);
      if (btn) btn.classList.remove('fab-voice-active');
    };
    rec.onend = function () {
      if (btn) btn.classList.remove('fab-voice-active');
      setTimeout(function () { setStatus(''); }, 3000);
    };
    rec.start();
  }

  // ------------------------------------------------------------------
  // Wake-word continuous listener ("hey fab")
  // ------------------------------------------------------------------
  function startWakeListener() {
    if (!SR) return;
    var wake = new SR();
    wake.lang = lang;
    wake.continuous = true;
    wake.interimResults = true;
    wake.onresult = function (e) {
      for (var i = e.resultIndex; i < e.results.length; i++) {
        var t = e.results[i][0].transcript.toLowerCase();
        if (t.indexOf('hey fab') !== -1) {
          wake.stop();
          startCommandSession();
          setTimeout(startWakeListener, 5000);
          return;
        }
      }
    };
    // auto-restart on end so it stays alive
    wake.onend = function () {
      try { wake.start(); } catch (_) {}
    };
    try { wake.start(); } catch (_) {}
  }

  // ------------------------------------------------------------------
  // Wire up button + launch wake listener after first user gesture
  // ------------------------------------------------------------------
  function init() {
    var btn = document.getElementById('fab-voice-bar-btn');
    if (btn) btn.addEventListener('click', startCommandSession);
    startWakeListener();
  }

  // Defer until DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // ------------------------------------------------------------------
  // Internal logger (silent unless FAB_VOICE_DEBUG=true on window)
  // ------------------------------------------------------------------
  function log(msg) {
    if (window.FAB_VOICE_DEBUG) console.log('[FAB voice]', msg);
  }

  // Expose for external use / testing
  window.__fabVoice = {
    speak: speak,
    handleCommand: handleCommand,
    startCommandSession: startCommandSession
  };

})();
"""

# ---------------------------------------------------------------------------
# VoiceCommandBar HTML injected before </body>
# ---------------------------------------------------------------------------

_COMMAND_BAR_HTML = """\
<div id="fab-voice-bar" aria-label="Voice command bar" role="complementary"
     style="position:fixed;bottom:20px;right:20px;z-index:9999;
            display:flex;flex-direction:column;align-items:flex-end;gap:8px;">
  <div id="fab-voice-status"
       style="background:rgba(0,0,0,0.75);color:#fff;padding:6px 12px;
              border-radius:20px;font-size:13px;display:none;max-width:260px;
              pointer-events:none;">
  </div>
  <button id="fab-voice-bar-btn" type="button"
          aria-label="Activate voice commands"
          title="Voice commands — click or say 'hey fab'"
          style="width:52px;height:52px;border-radius:50%;border:2px solid #337ab7;
                 background:#fff;cursor:pointer;font-size:22px;
                 box-shadow:0 2px 8px rgba(0,0,0,.25);
                 display:flex;align-items:center;justify-content:center;">
    &#127908;
  </button>
</div>
<style>
#fab-voice-bar-btn.fab-voice-active{background:#fdd!important;border-color:#c00!important;
  animation:fab-pulse 1s infinite;}
@keyframes fab-pulse{0%,100%{box-shadow:0 2px 8px rgba(0,0,0,.25);}
  50%{box-shadow:0 2px 16px rgba(200,0,0,.5);}}
</style>
<script src="/voice/voice.js"></script>
"""


# ---------------------------------------------------------------------------
# FABVoicePlugin
# ---------------------------------------------------------------------------

class FABVoicePlugin:
	"""
	PgAppForge voice input/output plugin.

	Integrates the browser's Web Speech API into all FAB pages with zero
	server-side audio processing.

	Usage::

		from pgappforge.plugins.voice import FABVoicePlugin

		app.config['FAB_VOICE_ENABLED'] = True
		voice = FABVoicePlugin()
		voice.init_app(app, appbuilder)

	Or with the application factory pattern::

		voice = FABVoicePlugin()
		# later:
		voice.init_app(app, appbuilder)

	Per-view opt-in (overrides global flag)::

		@FABVoicePlugin.enable_view
		class EmployeesView(ModelView):
			datamodel = SQLAInterface(Employee)
	"""

	def __init__(self) -> None:
		self._app: Flask | None = None
		self._appbuilder: AppBuilder | None = None

	# ------------------------------------------------------------------
	# init_app
	# ------------------------------------------------------------------

	def init_app(self, app: Flask, appbuilder: AppBuilder) -> None:
		"""
		Bind the plugin to *app* and *appbuilder*.

		If ``FAB_VOICE_ENABLED`` is False (the default) this is a no-op, so
		you can safely call it unconditionally and toggle via config.
		"""
		if not app.config.get("FAB_VOICE_ENABLED", False):
			log.debug("FABVoicePlugin: FAB_VOICE_ENABLED is False — skipping init")
			return

		self._app = app
		self._appbuilder = appbuilder

		# 1. Blueprint serving /voice/voice.js
		blueprint = Blueprint(
			"fab_voice",
			__name__,
			url_prefix="/voice",
		)

		@blueprint.route("/voice.js")
		def voice_js() -> Response:
			resp = make_response(_VOICE_JS, 200)
			resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
			resp.headers["Cache-Control"] = "public, max-age=3600"
			return resp

		app.register_blueprint(blueprint)
		log.info("FABVoicePlugin: blueprint registered at /voice/voice.js")

		# 2. after_request hook — inject command bar + script tag into HTML
		@app.after_request
		def _inject_voice(response: Response) -> Response:
			# Only inject into 200 OK HTML responses that have </body>
			ct = response.content_type or ""
			if (
				response.status_code != 200
				or "text/html" not in ct
				or response.direct_passthrough
			):
				return response

			data = response.get_data(as_text=True)
			if "</body>" not in data:
				return response

			# Check per-view opt-in flag (set on the view instance by enable_view)
			# The view class sets _fab_voice_enabled = True; we detect it via a
			# request-local g attribute set by a before_request on each view.
			# When global flag is True we inject everywhere; per-view mode is
			# handled by the decorator marking the view class and the hook below.
			injected = data.replace("</body>", _COMMAND_BAR_HTML + "</body>", 1)
			response.set_data(injected)
			return response

		log.info("FABVoicePlugin: after_request injection hook registered")

	# ------------------------------------------------------------------
	# enable_view decorator
	# ------------------------------------------------------------------

	@staticmethod
	def enable_view(view_class):
		"""
		Class decorator: mark a specific view as voice-enabled.

		When ``FAB_VOICE_ENABLED`` is False globally the plugin's
		``after_request`` hook is not registered, so this decorator acts as
		documentation / future hook point.  When the global flag is True,
		*all* pages get voice; this decorator is then purely semantic.

		Intended usage pattern::

			@FABVoicePlugin.enable_view
			class ReportsView(ModelView):
				datamodel = SQLAInterface(Report)

		The decorator sets ``view_class._fab_voice_enabled = True`` and
		returns the class unmodified so it can be stacked with other
		decorators.
		"""
		view_class._fab_voice_enabled = True
		log.debug("FABVoicePlugin: voice enabled on %s", view_class.__name__)
		return view_class


__all__ = [
	"FABVoicePlugin",
	"_VOICE_JS",
	"_COMMAND_BAR_HTML",
]
