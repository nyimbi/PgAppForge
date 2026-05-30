"""
pgappforge/plugins/voice/widgets.py

Voice input/output widgets for PgAppForge using the browser's Web Speech API.
No server-side dependencies — purely client-side JavaScript.

Widgets:
    VoiceInputWidget    - Mic button next to any text/textarea field; speech → text
    VoiceReadWidget     - Read-only display that reads the field value via TTS on focus
    VoiceCommandBar     - Floating overlay for navigation, form-fill, and submit commands
"""

from __future__ import annotations

from markupsafe import Markup
from wtforms.widgets import html_params

from pgappforge.fieldwidgets import BS3TextFieldWidget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _once_guard(flag: str) -> str:
	"""Return JS that early-exits if *flag* is already set on window (dedup guard)."""
	return f"if (window['{flag}']) {{ return; }} window['{flag}'] = true;"


# ---------------------------------------------------------------------------
# VoiceInputWidget
# ---------------------------------------------------------------------------

class VoiceInputWidget(BS3TextFieldWidget):
	"""
	Adds a microphone button next to any text/textarea field.

	Clicking the mic button triggers the browser's SpeechRecognition API.
	The recognised transcript is inserted directly into the field value.
	A single inline <script> block is emitted the first time any instance
	renders on a given page (dedup-guarded via window.__fabVoiceInputLoaded).

	Usage::

		class MyForm(DynamicForm):
			name = StringField("Name", widget=VoiceInputWidget())

	The widget degrades silently on browsers without SpeechRecognition support —
	the mic button is hidden via CSS when the API is unavailable.
	"""

	_SCRIPT = r"""
<script>
(function() {
	%(guard)s
	var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
	document.querySelectorAll('.fab-voice-btn').forEach(function(btn) {
		if (!SR) { btn.style.display = 'none'; return; }
		btn.addEventListener('click', function() {
			var fieldId = btn.dataset.target;
			var field = document.getElementById(fieldId);
			if (!field) return;
			var rec = new SR();
			rec.lang = document.documentElement.lang || 'en-US';
			rec.interimResults = false;
			rec.maxAlternatives = 1;
			btn.classList.add('fab-voice-active');
			btn.setAttribute('aria-label', 'Listening…');
			rec.onresult = function(e) {
				field.value = e.results[0][0].transcript;
				field.dispatchEvent(new Event('input', {bubbles: true}));
				field.dispatchEvent(new Event('change', {bubbles: true}));
			};
			rec.onerror = function(e) {
				console.warn('[FAB voice] SpeechRecognition error:', e.error);
				if (window.speechSynthesis) {
					var u = new SpeechSynthesisUtterance('Voice input error: ' + e.error);
					window.speechSynthesis.speak(u);
				}
			};
			rec.onend = function() {
				btn.classList.remove('fab-voice-active');
				btn.setAttribute('aria-label', 'Start voice input');
			};
			rec.start();
		});
	});
})();
</script>
<style>
.fab-voice-input-group { display: flex; align-items: center; gap: 4px; }
.fab-voice-btn {
	background: none; border: 1px solid #ccc; border-radius: 4px;
	cursor: pointer; padding: 4px 8px; line-height: 1; flex-shrink: 0;
	transition: background 0.15s;
}
.fab-voice-btn:hover { background: #f0f0f0; }
.fab-voice-btn.fab-voice-active { background: #fdd; border-color: #c00; }
</style>
"""

	def __call__(self, field, **kwargs) -> Markup:
		kwargs["class"] = "form-control"
		if field.label:
			kwargs.setdefault("placeholder", field.label.text)
		if "name_" in kwargs:
			field.name = kwargs.pop("name_")

		input_html = super(BS3TextFieldWidget, self).__call__(field, **kwargs)

		mic_btn = (
			'<button type="button" class="fab-voice-btn" '
			f'data-target="{field.id}" '
			'aria-label="Start voice input" title="Voice input">'
			'🎤'
			'</button>'
		)
		wrapper = f'<div class="fab-voice-input-group">{input_html}{mic_btn}</div>'

		script = self._SCRIPT % {"guard": _once_guard("__fabVoiceInputLoaded")}
		return Markup(wrapper + script)


# ---------------------------------------------------------------------------
# VoiceReadWidget
# ---------------------------------------------------------------------------

class VoiceReadWidget:
	"""
	Read-only display widget that reads the field value aloud via TTS on focus.

	Renders a <span> with tabindex=0 so it is keyboard-focusable.  When it
	receives focus (mouse or keyboard) the field value is passed to
	SpeechSynthesis.speak().

	Usage::

		class MyForm(DynamicForm):
			notes = StringField("Notes", widget=VoiceReadWidget())

	Degrades gracefully when SpeechSynthesis is unavailable.
	"""

	_SCRIPT = """
<script>
(function() {
	%(guard)s
	document.querySelectorAll('.fab-voice-read').forEach(function(el) {
		el.addEventListener('focus', function() {
			if (!window.speechSynthesis) return;
			window.speechSynthesis.cancel();
			var label = el.dataset.label ? el.dataset.label + '. ' : '';
			var text = label + (el.textContent || el.innerText || '');
			if (!text.trim()) return;
			var u = new SpeechSynthesisUtterance(text.trim());
			u.lang = document.documentElement.lang || 'en-US';
			window.speechSynthesis.speak(u);
		});
		el.addEventListener('blur', function() {
			if (window.speechSynthesis) window.speechSynthesis.cancel();
		});
	});
})();
</script>
<style>
.fab-voice-read {
	display: inline-block; padding: 6px 10px;
	border: 1px solid transparent; border-radius: 4px;
	cursor: default;
}
.fab-voice-read:focus {
	outline: 2px solid #337ab7; border-color: #337ab7;
}
</style>
"""

	def __call__(self, field, **kwargs) -> Markup:
		value = field.data if field.data is not None else ""
		label_text = field.label.text if field.label else ""
		span = (
			f'<span class="fab-voice-read" tabindex="0" '
			f'data-label="{label_text}" '
			f'title="Focus to hear value read aloud">'
			f'{value}'
			f'</span>'
		)
		script = self._SCRIPT % {"guard": _once_guard("__fabVoiceReadLoaded")}
		return Markup(span + script)


# ---------------------------------------------------------------------------
# VoiceCommandBar
# ---------------------------------------------------------------------------

class VoiceCommandBar:
	"""
	Floating command-bar overlay (position: fixed, bottom-right) that listens
	for voice commands and acts on them client-side.

	Supported commands (case-insensitive after stripping punctuation):

	Navigation:
		"go to <view name>"   → navigates to a registered FAB route by name
		"show <view name>"    → alias for "go to"
		"open <view name>"    → alias for "go to"

	Form filling:
		"set <field> to <value>"  → fills the named form field
		"fill <field> with <value>"

	Form actions:
		"submit" / "save"     → clicks the first [type=submit] button
		"cancel" / "reset"    → clicks the first .cancel or [type=reset]

	Activation:
		- Click the floating mic button
		- Say the wake word "hey fab" (continuous background listener)

	Usage — render once in a base template or via the FABVoicePlugin::

		{{ VoiceCommandBar.render() | safe }}

	Or call render() from any view's template context.

	Note: VoiceCommandBar is NOT a WTForms widget; it is a standalone
	renderer producing self-contained HTML+JS.  It inherits from no base class
	intentionally — it has no field to bind to.
	"""

	_HTML = r"""
<div id="fab-voice-bar" aria-label="Voice command bar" role="complementary"
     style="position:fixed;bottom:20px;right:20px;z-index:9999;
            display:flex;flex-direction:column;align-items:flex-end;gap:8px;">
  <div id="fab-voice-status"
       style="background:rgba(0,0,0,0.75);color:#fff;padding:6px 12px;
              border-radius:20px;font-size:13px;display:none;max-width:260px;">
    Listening…
  </div>
  <button id="fab-voice-bar-btn" type="button"
          aria-label="Activate voice commands"
          title="Voice commands (or say 'hey fab')"
          style="width:52px;height:52px;border-radius:50%;border:2px solid #337ab7;
                 background:#fff;cursor:pointer;font-size:22px;
                 box-shadow:0 2px 8px rgba(0,0,0,0.25);
                 display:flex;align-items:center;justify-content:center;">
    🎤
  </button>
</div>
<style>
#fab-voice-bar-btn.fab-voice-active {
	background: #fdd !important;
	border-color: #c00 !important;
	animation: fab-pulse 1s infinite;
}
@keyframes fab-pulse {
	0%,100% { box-shadow: 0 2px 8px rgba(0,0,0,.25); }
	50%      { box-shadow: 0 2px 16px rgba(200,0,0,.5); }
}
</style>
<script>
(function() {
%(guard)s
var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!SR) {
	var btn = document.getElementById('fab-voice-bar-btn');
	if (btn) btn.title = 'Voice commands not supported in this browser';
	return;
}

// ---- registry: map lowercase view names → URLs ----
var VIEW_REGISTRY = (function() {
	// FAB embeds menu links in the DOM; scrape them to build a name→url map.
	var reg = {};
	document.querySelectorAll('.navbar-nav a[href], .nav a[href]').forEach(function(a) {
		var text = (a.textContent || '').trim().toLowerCase();
		if (text && a.href) reg[text] = a.href;
	});
	return reg;
})();

function speak(text) {
	if (!window.speechSynthesis) return;
	window.speechSynthesis.cancel();
	var u = new SpeechSynthesisUtterance(text);
	u.lang = document.documentElement.lang || 'en-US';
	window.speechSynthesis.speak(u);
}

function setStatus(msg) {
	var el = document.getElementById('fab-voice-status');
	if (!el) return;
	el.textContent = msg;
	el.style.display = msg ? 'block' : 'none';
}

function handleCommand(raw) {
	var cmd = raw.toLowerCase().replace(/[.,!?]+$/, '').trim();
	setStatus('Heard: ' + raw);

	// ---- navigate ----
	var navMatch = cmd.match(/^(?:go to|show|open)\s+(.+)$/);
	if (navMatch) {
		var target = navMatch[1].trim();
		var url = VIEW_REGISTRY[target];
		if (url) {
			speak('Navigating to ' + target);
			setTimeout(function() { window.location.href = url; }, 600);
		} else {
			speak('View ' + target + ' not found');
			setStatus('View not found: ' + target);
		}
		return;
	}

	// ---- fill field ----
	var fillMatch = cmd.match(/^(?:set|fill)\s+(.+?)\s+(?:to|with)\s+(.+)$/);
	if (fillMatch) {
		var fieldName = fillMatch[1].trim();
		var value = fillMatch[2].trim();
		// Try id match, name match, placeholder match, label match
		var field = (
			document.getElementById(fieldName) ||
			document.querySelector('[name="' + fieldName + '"]') ||
			document.querySelector('[placeholder*="' + fieldName + '" i]')
		);
		if (!field) {
			// try matching a label text
			var labels = document.querySelectorAll('label');
			for (var i = 0; i < labels.length; i++) {
				if (labels[i].textContent.trim().toLowerCase() === fieldName) {
					var forId = labels[i].htmlFor;
					if (forId) field = document.getElementById(forId);
					break;
				}
			}
		}
		if (field) {
			field.value = value;
			field.dispatchEvent(new Event('input', {bubbles: true}));
			field.dispatchEvent(new Event('change', {bubbles: true}));
			speak('Set ' + fieldName + ' to ' + value);
			setStatus('Set ' + fieldName + ' to ' + value);
		} else {
			speak('Field ' + fieldName + ' not found');
			setStatus('Field not found: ' + fieldName);
		}
		return;
	}

	// ---- submit / save ----
	if (/^(?:submit|save)$/.test(cmd)) {
		var submitBtn = document.querySelector('[type="submit"]');
		if (submitBtn) {
			speak('Submitting form');
			setTimeout(function() { submitBtn.click(); }, 400);
		} else {
			speak('No submit button found');
		}
		return;
	}

	// ---- cancel / reset ----
	if (/^(?:cancel|reset)$/.test(cmd)) {
		var cancelBtn = (
			document.querySelector('.cancel') ||
			document.querySelector('[type="reset"]') ||
			document.querySelector('a[href*="list"]')
		);
		if (cancelBtn) {
			speak('Cancelling');
			setTimeout(function() { cancelBtn.click(); }, 400);
		} else {
			speak('No cancel button found');
		}
		return;
	}

	// ---- unknown ----
	speak('Command not recognised: ' + raw);
	setStatus('Unknown: ' + raw);
}

// ---- one-shot command recognition (triggered by button or wake word) ----
function startCommandSession() {
	var btn = document.getElementById('fab-voice-bar-btn');
	var rec = new SR();
	rec.lang = document.documentElement.lang || 'en-US';
	rec.interimResults = false;
	rec.maxAlternatives = 1;
	if (btn) btn.classList.add('fab-voice-active');
	setStatus('Listening…');
	rec.onresult = function(e) {
		var transcript = e.results[0][0].transcript;
		handleCommand(transcript);
	};
	rec.onerror = function(e) {
		speak('Voice error: ' + e.error);
		setStatus('Error: ' + e.error);
		if (btn) btn.classList.remove('fab-voice-active');
	};
	rec.onend = function() {
		if (btn) btn.classList.remove('fab-voice-active');
		setTimeout(function() { setStatus(''); }, 3000);
	};
	rec.start();
}

// ---- wake-word continuous listener ----
(function startWakeWordListener() {
	var wake = new SR();
	wake.lang = document.documentElement.lang || 'en-US';
	wake.continuous = true;
	wake.interimResults = true;
	wake.onresult = function(e) {
		for (var i = e.resultIndex; i < e.results.length; i++) {
			var t = e.results[i][0].transcript.toLowerCase();
			if (t.indexOf('hey fab') !== -1) {
				wake.stop();
				startCommandSession();
				// restart wake listener after command session ends
				setTimeout(startWakeWordListener, 5000);
				return;
			}
		}
	};
	wake.onend = function() {
		// auto-restart to keep listening
		try { wake.start(); } catch(e) { /* already started */ }
	};
	try { wake.start(); } catch(e) { /* may be blocked before user gesture */ }
})();

// ---- button click ----
var barBtn = document.getElementById('fab-voice-bar-btn');
if (barBtn) {
	barBtn.addEventListener('click', startCommandSession);
}

})();
</script>
"""

	@classmethod
	def render(cls) -> Markup:
		"""Return the command bar HTML+JS as a Markup string for template injection."""
		html = cls._HTML % {"guard": _once_guard("__fabVoiceBarLoaded")}
		return Markup(html)
