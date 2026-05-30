"""
pgappforge/plugins/chatbot/__init__.py

ChatbotPlugin — page-level AI help chatbot for PgAppForge.

Injects a floating chat button (bottom-right) into every page and serves a
REST endpoint the JS widget calls.

Configuration (app.config)::

    FAB_CHATBOT_ENABLED = True
    FAB_CHATBOT_PROVIDER = "ollama"          # any ModelProvider value
    FAB_CHATBOT_MODEL = "llama3.2:3b"
    FAB_CHATBOT_EXCLUDE_PATHS = ["/static/", "/auth/"]
    FAB_CHATBOT_PER_PAGE_CONFIG = {
        "/employee/": "You are an HR assistant...",
    }

Blueprint routes::

    POST /chatbot/api/message
        Body: {page_url, page_title, message, history: [...]}
        Returns: {reply, actions: [{type, url, data}]}

    GET /chatbot/js/chatbot.js
        Returns the floating button + chat panel JS.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from flask import Blueprint, Response, make_response, request, current_app

if TYPE_CHECKING:
	from flask import Flask
	from pgappforge import AppBuilder

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chatbot JS — floating button + slide-in panel (~200 lines vanilla JS)
# ---------------------------------------------------------------------------

_CHATBOT_JS = r"""\
/* PgAppForge Chatbot Plugin
 * Served at /chatbot/js/chatbot.js
 * Floating chat button (bottom-right) + slide-in panel.
 */
(function () {
  'use strict';

  /* ------------------------------------------------------------------ */
  /* State                                                                */
  /* ------------------------------------------------------------------ */
  var history = [];   /* [{role:'user'|'assistant', content:''}, ...] */
  var isOpen  = false;
  var isBusy  = false;

  /* ------------------------------------------------------------------ */
  /* Create DOM                                                           */
  /* ------------------------------------------------------------------ */
  function buildUI() {
    /* Inject CSS */
    var style = document.createElement('style');
    style.textContent = [
      '#fab-chat-btn{position:fixed;bottom:24px;right:24px;z-index:10000;',
      'width:54px;height:54px;border-radius:50%;background:#337ab7;',
      'color:#fff;border:none;cursor:pointer;font-size:24px;',
      'box-shadow:0 2px 10px rgba(0,0,0,.3);',
      'display:flex;align-items:center;justify-content:center;',
      'transition:background .2s;}',
      '#fab-chat-btn:hover{background:#23527c;}',
      '#fab-chat-panel{position:fixed;bottom:90px;right:24px;z-index:10000;',
      'width:320px;max-height:480px;border-radius:10px;',
      'background:#fff;box-shadow:0 4px 20px rgba(0,0,0,.25);',
      'display:none;flex-direction:column;overflow:hidden;',
      'font-family:system-ui,sans-serif;font-size:14px;}',
      '#fab-chat-panel.open{display:flex;}',
      '#fab-chat-header{background:#337ab7;color:#fff;padding:10px 14px;',
      'display:flex;justify-content:space-between;align-items:center;',
      'font-weight:600;}',
      '#fab-chat-close{background:none;border:none;color:#fff;',
      'cursor:pointer;font-size:18px;line-height:1;padding:0 2px;}',
      '#fab-chat-messages{flex:1;overflow-y:auto;padding:10px;',
      'display:flex;flex-direction:column;gap:8px;}',
      '.fab-msg{max-width:88%;padding:8px 12px;border-radius:12px;',
      'line-height:1.4;word-wrap:break-word;}',
      '.fab-msg-user{background:#337ab7;color:#fff;align-self:flex-end;',
      'border-bottom-right-radius:3px;}',
      '.fab-msg-assistant{background:#f0f0f0;color:#222;align-self:flex-start;',
      'border-bottom-left-radius:3px;}',
      '.fab-msg-typing{opacity:.6;font-style:italic;}',
      '#fab-chat-input-row{display:flex;border-top:1px solid #ddd;padding:8px;}',
      '#fab-chat-input{flex:1;border:1px solid #ccc;border-radius:6px;',
      'padding:6px 10px;font-size:14px;outline:none;resize:none;',
      'font-family:inherit;}',
      '#fab-chat-send{margin-left:6px;background:#337ab7;color:#fff;',
      'border:none;border-radius:6px;padding:6px 12px;cursor:pointer;',
      'font-size:14px;}',
      '#fab-chat-send:disabled{opacity:.5;cursor:default;}',
    ].join('');
    document.head.appendChild(style);

    /* Floating button */
    var btn = document.createElement('button');
    btn.id = 'fab-chat-btn';
    btn.setAttribute('aria-label', 'Open AI assistant');
    btn.setAttribute('title', 'AI assistant');
    btn.innerHTML = '&#128172;';
    document.body.appendChild(btn);

    /* Panel */
    var panel = document.createElement('div');
    panel.id = 'fab-chat-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'AI assistant chat');
    panel.innerHTML = [
      '<div id="fab-chat-header">',
      '  <span>AI Assistant</span>',
      '  <button id="fab-chat-close" aria-label="Close chat">&times;</button>',
      '</div>',
      '<div id="fab-chat-messages" aria-live="polite"></div>',
      '<div id="fab-chat-input-row">',
      '  <textarea id="fab-chat-input" rows="1"',
      '    placeholder="Ask something about this page…"',
      '    aria-label="Message"></textarea>',
      '  <button id="fab-chat-send" aria-label="Send">Send</button>',
      '</div>',
    ].join('');
    document.body.appendChild(panel);

    /* Wire events */
    btn.addEventListener('click', togglePanel);
    document.getElementById('fab-chat-close').addEventListener('click', closePanel);
    document.getElementById('fab-chat-send').addEventListener('click', sendMessage);
    document.getElementById('fab-chat-input').addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    /* Auto-resize textarea */
    document.getElementById('fab-chat-input').addEventListener('input', function () {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });
  }

  /* ------------------------------------------------------------------ */
  /* Panel open / close                                                   */
  /* ------------------------------------------------------------------ */
  function togglePanel() { isOpen ? closePanel() : openPanel(); }

  function openPanel() {
    isOpen = true;
    var panel = document.getElementById('fab-chat-panel');
    if (panel) { panel.classList.add('open'); }
    var inp = document.getElementById('fab-chat-input');
    if (inp) { inp.focus(); }
    /* Greet once */
    if (history.length === 0) {
      appendMessage('assistant',
        'Hi! I’m your AI assistant for this page. Ask me anything — I can explain fields, help you navigate, or answer questions about the data.');
    }
  }

  function closePanel() {
    isOpen = false;
    var panel = document.getElementById('fab-chat-panel');
    if (panel) { panel.classList.remove('open'); }
  }

  /* ------------------------------------------------------------------ */
  /* Message rendering                                                    */
  /* ------------------------------------------------------------------ */
  function appendMessage(role, text) {
    var msgs = document.getElementById('fab-chat-messages');
    if (!msgs) return;
    var div = document.createElement('div');
    div.className = 'fab-msg fab-msg-' + role;
    div.textContent = text;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
  }

  function removeTypingIndicator() {
    var el = document.getElementById('fab-chat-typing');
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  /* ------------------------------------------------------------------ */
  /* Page context scrape                                                  */
  /* ------------------------------------------------------------------ */
  function getPageContext() {
    return {
      page_url:   window.location.pathname + window.location.search,
      page_title: document.title,
    };
  }

  /* ------------------------------------------------------------------ */
  /* Send message                                                         */
  /* ------------------------------------------------------------------ */
  function sendMessage() {
    if (isBusy) return;
    var inp = document.getElementById('fab-chat-input');
    var sendBtn = document.getElementById('fab-chat-send');
    if (!inp) return;
    var text = inp.value.trim();
    if (!text) return;

    inp.value = '';
    inp.style.height = 'auto';
    appendMessage('user', text);
    history.push({ role: 'user', content: text });

    /* typing indicator */
    isBusy = true;
    if (sendBtn) sendBtn.disabled = true;
    var typing = appendMessage('assistant', '…');
    if (typing) typing.id = 'fab-chat-typing';

    var ctx = getPageContext();
    var payload = {
      page_url:   ctx.page_url,
      page_title: ctx.page_title,
      message:    text,
      history:    history.slice(-10),   /* last 10 turns */
    };

    fetch('/chatbot/api/message', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      removeTypingIndicator();
      var reply = (data && data.reply) ? data.reply : 'Sorry, I encountered an error.';
      appendMessage('assistant', reply);
      history.push({ role: 'assistant', content: reply });

      /* Handle actions */
      if (data && Array.isArray(data.actions)) {
        data.actions.forEach(function (action) {
          handleAction(action);
        });
      }
    })
    .catch(function (err) {
      removeTypingIndicator();
      appendMessage('assistant', 'Sorry, I couldn’t reach the server. Please try again.');
      console.error('[FAB chatbot]', err);
    })
    .finally(function () {
      isBusy = false;
      if (sendBtn) sendBtn.disabled = false;
      if (inp) inp.focus();
    });
  }

  /* ------------------------------------------------------------------ */
  /* Action handler                                                       */
  /* ------------------------------------------------------------------ */
  function handleAction(action) {
    if (!action || !action.type) return;
    switch (action.type) {
      case 'navigate':
        if (action.url) {
          setTimeout(function () { window.location.href = action.url; }, 800);
        }
        break;
      case 'highlight':
        /* Highlight a field by name or id */
        if (action.field) {
          var el = document.getElementById(action.field) ||
                   document.querySelector('[name="' + action.field + '"]');
          if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            el.style.outline = '3px solid #337ab7';
            setTimeout(function () { el.style.outline = ''; }, 3000);
          }
        }
        break;
      case 'fill':
        if (action.field && action.value !== undefined) {
          var fe = document.getElementById(action.field) ||
                   document.querySelector('[name="' + action.field + '"]');
          if (fe) {
            fe.value = action.value;
            fe.dispatchEvent(new Event('input',  { bubbles: true }));
            fe.dispatchEvent(new Event('change', { bubbles: true }));
          }
        }
        break;
      default:
        /* unknown action — ignore silently */
    }
  }

  /* ------------------------------------------------------------------ */
  /* Boot                                                                 */
  /* ------------------------------------------------------------------ */
  function init() { buildUI(); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  /* Expose for testing */
  window.__fabChatbot = {
    open:        openPanel,
    close:       closePanel,
    sendMessage: sendMessage,
    history:     history,
  };

})();
"""

# ---------------------------------------------------------------------------
# ChatbotPlugin
# ---------------------------------------------------------------------------

_DEFAULT_EXCLUDE = ["/static/", "/chatbot/"]


class ChatbotPlugin:
	"""
	PgAppForge page-level AI chatbot plugin.

	Registers a Blueprint at /chatbot/ and injects the chat widget into every
	HTML response that is not on the exclude list.

	Usage::

		from pgappforge.plugins.chatbot import ChatbotPlugin

		app.config['FAB_CHATBOT_ENABLED'] = True
		app.config['FAB_CHATBOT_PROVIDER'] = 'ollama'
		app.config['FAB_CHATBOT_MODEL']    = 'llama3.2:3b'

		chatbot = ChatbotPlugin()
		chatbot.init_app(app, appbuilder)

	Application factory::

		chatbot = ChatbotPlugin()
		# later:
		chatbot.init_app(app, appbuilder)
	"""

	def __init__(self) -> None:
		self._app: Flask | None = None
		self._appbuilder: AppBuilder | None = None

	# ------------------------------------------------------------------
	# init_app
	# ------------------------------------------------------------------

	def init_app(self, app: Flask, appbuilder: AppBuilder) -> None:
		"""Bind plugin to *app*. No-op if FAB_CHATBOT_ENABLED is False."""
		if not app.config.get("FAB_CHATBOT_ENABLED", False):
			log.debug("ChatbotPlugin: FAB_CHATBOT_ENABLED is False — skipping init")
			return

		self._app = app
		self._appbuilder = appbuilder

		blueprint = Blueprint("fab_chatbot", __name__, url_prefix="/chatbot")

		# ---- GET /chatbot/js/chatbot.js --------------------------------
		@blueprint.route("/js/chatbot.js")
		def chatbot_js() -> Response:
			resp = make_response(_CHATBOT_JS, 200)
			resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
			resp.headers["Cache-Control"] = "public, max-age=3600"
			return resp

		# ---- POST /chatbot/api/message ---------------------------------
		@blueprint.route("/api/message", methods=["POST"])
		def chatbot_message() -> Response:
			return _handle_message(current_app._get_current_object())

		app.register_blueprint(blueprint)
		log.info("ChatbotPlugin: blueprint registered at /chatbot/")

		# ---- after_request: inject <script> tag into HTML responses ----
		exclude_paths: list[str] = app.config.get(
			"FAB_CHATBOT_EXCLUDE_PATHS", []
		) + _DEFAULT_EXCLUDE

		@app.after_request
		def _inject_chatbot(response: Response) -> Response:
			return inject_chatbot(response, exclude_paths)

		log.info("ChatbotPlugin: after_request injection hook registered")


# ---------------------------------------------------------------------------
# Request handler (sync wrapper around async AI call)
# ---------------------------------------------------------------------------

def _handle_message(app: Flask) -> Response:
	"""Process POST /chatbot/api/message."""
	body: dict[str, Any] = request.get_json(silent=True) or {}

	page_url:   str         = body.get("page_url", "")
	page_title: str         = body.get("page_title", "")
	message:    str         = body.get("message", "").strip()
	history:    list[dict]  = body.get("history", [])

	if not message:
		return make_response(
			json.dumps({"error": "message is required"}),
			400,
			{"Content-Type": "application/json"},
		)

	provider_name: str = app.config.get("FAB_CHATBOT_PROVIDER", "ollama")
	model_name:    str = app.config.get("FAB_CHATBOT_MODEL", "llama3.2:3b")
	per_page_cfg:  dict[str, str] = app.config.get("FAB_CHATBOT_PER_PAGE_CONFIG", {})
	app_name:      str = app.config.get("APP_NAME", "PgAppForge")

	# Build system prompt
	system_prompt = _build_system_prompt(
		page_url, page_title, app_name, per_page_cfg
	)

	try:
		reply, actions = _run_ai(
			provider_name, model_name, system_prompt, history, message
		)
	except Exception as exc:
		log.exception("ChatbotPlugin: AI call failed: %s", exc)
		reply = (
			"I'm sorry, I encountered an error communicating with the AI provider. "
			"Please check the server logs or try again later."
		)
		actions = []

	return make_response(
		json.dumps({"reply": reply, "actions": actions}),
		200,
		{"Content-Type": "application/json"},
	)


def _build_system_prompt(
	page_url: str,
	page_title: str,
	app_name: str,
	per_page_cfg: dict[str, str],
) -> str:
	"""Compose the system prompt, merging per-page overrides."""
	# Check per-page config: longest matching prefix wins
	custom: str = ""
	for prefix, blurb in per_page_cfg.items():
		if page_url.startswith(prefix) and len(prefix) > len(custom):
			custom = blurb

	base = (
		f"You are an AI assistant embedded in {app_name}, a web application. "
		f"The user is currently on the page '{page_title}' (URL: {page_url}). "
		"You can:\n"
		"  1. Answer questions about the current page, visible data, or form fields.\n"
		"  2. Explain what form fields are for.\n"
		"  3. Suggest navigation to related pages by including a JSON action block.\n"
		"  4. Describe how to create or update records.\n"
		"Keep answers concise and helpful. "
		"If you want the browser to take an action (navigate, highlight a field, "
		"fill a field), append a JSON block on its own line in this format:\n"
		'  {"action": {"type": "navigate", "url": "/some/path"}}\n'
		'  {"action": {"type": "highlight", "field": "field_name"}}\n'
		'  {"action": {"type": "fill", "field": "field_name", "value": "val"}}\n'
		"Only include action blocks when genuinely useful."
	)

	if custom:
		return f"{base}\n\nAdditional context: {custom}"
	return base


def _run_ai(
	provider_name: str,
	model_name: str,
	system_prompt: str,
	history: list[dict],
	message: str,
) -> tuple[str, list[dict]]:
	"""
	Call the AI provider synchronously (runs async adapter in a new event loop).

	Returns (reply_text, actions_list).
	"""
	# Import here to avoid circular imports at module load time
	from pgappforge.collaborative.ai.ai_models import (
		ModelProvider,
		ModelConfig,
		ChatMessage,
		OllamaAdapter,
		OpenAIAdapter,
		AnthropicAdapter,
		GoogleGeminiAdapter,
		GroqAdapter,
		OpenRouterAdapter,
		MistralAdapter,
		AzureOpenAIAdapter,
	)

	# Map provider string → ModelProvider enum
	try:
		provider = ModelProvider(provider_name.lower())
	except ValueError:
		log.warning("ChatbotPlugin: unknown provider '%s', falling back to ollama", provider_name)
		provider = ModelProvider.OLLAMA

	config = ModelConfig(provider=provider, model_name=model_name)

	# Pick adapter
	_adapter_map = {
		ModelProvider.OLLAMA:       OllamaAdapter,
		ModelProvider.OPENAI:       OpenAIAdapter,
		ModelProvider.ANTHROPIC:    AnthropicAdapter,
		ModelProvider.GOOGLE:       GoogleGeminiAdapter,
		ModelProvider.GROQ:         GroqAdapter,
		ModelProvider.OPENROUTER:   OpenRouterAdapter,
		ModelProvider.MISTRAL:      MistralAdapter,
		ModelProvider.AZURE_OPENAI: AzureOpenAIAdapter,
	}
	adapter_cls = _adapter_map.get(provider, OllamaAdapter)
	adapter = adapter_cls(config)

	# Assemble messages
	messages: list[ChatMessage] = [ChatMessage(role="system", content=system_prompt)]
	for turn in history[:-1]:  # exclude the last turn — that IS the current message
		role = turn.get("role", "user")
		content = turn.get("content", "")
		if role in ("user", "assistant") and content:
			messages.append(ChatMessage(role=role, content=content))
	messages.append(ChatMessage(role="user", content=message))

	# Run async call synchronously
	async def _call() -> str:
		resp = await adapter.chat_completion(messages)
		# ModelResponse or dict depending on adapter
		if hasattr(resp, "content"):
			return resp.content
		if isinstance(resp, dict):
			return resp.get("content", "")
		return str(resp)

	raw: str = asyncio.run(_call())

	# Parse optional action blocks from response text
	reply_lines: list[str] = []
	actions: list[dict] = []
	for line in raw.splitlines():
		stripped = line.strip()
		if stripped.startswith('{"action"'):
			try:
				parsed = json.loads(stripped)
				action = parsed.get("action")
				if isinstance(action, dict) and action.get("type"):
					actions.append(action)
				continue  # don't include raw JSON in the reply text
			except json.JSONDecodeError:
				pass
		reply_lines.append(line)

	reply = "\n".join(reply_lines).strip()
	return reply, actions


# ---------------------------------------------------------------------------
# inject_chatbot — after_request hook
# ---------------------------------------------------------------------------

def inject_chatbot(response: Response, exclude_paths: list[str] | None = None) -> Response:
	"""
	Inject <script src="/chatbot/js/chatbot.js"> before </body>.

	Skips responses that:
	- are not status 200
	- are not text/html
	- are direct passthrough
	- match any prefix in *exclude_paths*
	- contain no </body> tag
	"""
	ct = response.content_type or ""
	if (
		response.status_code != 200
		or "text/html" not in ct
		or response.direct_passthrough
	):
		return response

	path: str = request.path
	for prefix in (exclude_paths or _DEFAULT_EXCLUDE):
		if path.startswith(prefix):
			return response

	data = response.get_data(as_text=True)
	if "</body>" not in data:
		return response

	tag = '<script src="/chatbot/js/chatbot.js"></script>'
	response.set_data(data.replace("</body>", tag + "\n</body>", 1))
	return response


__all__ = [
	"ChatbotPlugin",
	"inject_chatbot",
	"_CHATBOT_JS",
]
