"""
pgappforge/ai_assistant/agent.py

Ollama-backed ReAct agent with SSE streaming.

Protocol:
  - POST /api/chat to Ollama with tools list
  - If done_reason == "tool_calls": execute tools, append results, loop
  - If done_reason == "stop": yield final answer as SSE event
  - Anti-loop guard: abort after MAX_TOOL_ROUNDS with no new tool names
  - Yields server-sent event lines (b"data: ...\n\n")
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Generator
from typing import Any

import requests

log = logging.getLogger(__name__)

_DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
_DEFAULT_MODEL = "qwen2.5-coder:7b"
MAX_TOOL_ROUNDS = 12   # hard ceiling on ReAct iterations


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse(event: str, data: Any) -> bytes:
	payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
	return f"data: {payload}\n\n".encode()


def _sse_token(text: str) -> bytes:
	return f"data: {json.dumps({'event': 'token', 'data': text})}\n\n".encode()


def _sse_tool_call(name: str, args: dict) -> bytes:
	return f"data: {json.dumps({'event': 'tool_call', 'tool': name, 'args': args})}\n\n".encode()


def _sse_tool_result(name: str, result: str) -> bytes:
	return f"data: {json.dumps({'event': 'tool_result', 'tool': name, 'result': result[:500]})}\n\n".encode()


def _sse_done() -> bytes:
	return b"data: {\"event\": \"done\"}\n\n"


def _sse_error(msg: str) -> bytes:
	return f"data: {json.dumps({'event': 'error', 'message': msg})}\n\n".encode()


# ---------------------------------------------------------------------------
# Ollama client helpers
# ---------------------------------------------------------------------------

def _chat(
	messages: list[dict],
	tools: list[dict],
	model: str,
	ollama_url: str,
	stream: bool = False,
) -> dict:
	"""POST to Ollama /api/chat, return parsed response (non-streaming)."""
	payload = {
		"model": model,
		"messages": messages,
		"tools": tools,
		"stream": stream,
	}
	resp = requests.post(
		f"{ollama_url}/api/chat",
		json=payload,
		timeout=120,
	)
	resp.raise_for_status()
	return resp.json()


def _chat_stream(
	messages: list[dict],
	tools: list[dict],
	model: str,
	ollama_url: str,
) -> Generator[dict, None, None]:
	"""POST to Ollama /api/chat with stream=True, yield each parsed NDJSON line."""
	payload = {
		"model": model,
		"messages": messages,
		"tools": tools,
		"stream": True,
	}
	with requests.post(
		f"{ollama_url}/api/chat",
		json=payload,
		timeout=(10, 30),  # (connect_timeout, read_timeout_per_chunk)
		stream=True,
	) as resp:
		resp.raise_for_status()
		for raw_line in resp.iter_lines():
			if raw_line:
				try:
					yield json.loads(raw_line)
				except json.JSONDecodeError:
					continue


# ---------------------------------------------------------------------------
# ReAct streaming generator
# ---------------------------------------------------------------------------

def run_agent_stream(
	user_message: str,
	tool_schemas: list[dict],
	tool_registry: dict[str, Any],
	system_prompt: str,
	history: list[dict] | None = None,
	model: str = _DEFAULT_MODEL,
	ollama_url: str = _DEFAULT_OLLAMA_URL,
) -> Generator[bytes, None, None]:
	"""Run the ReAct loop and yield SSE-encoded bytes.

	Args:
		user_message:   Latest user message.
		tool_schemas:   JSON Schema list for Ollama tool calling.
		tool_registry:  name → callable mapping (RBAC-filtered).
		system_prompt:  System prompt (from context.build_system_prompt).
		history:        Prior conversation turns (list of role/content dicts).
		model:          Ollama model name.
		ollama_url:     Ollama base URL.

	Yields:
		SSE-encoded bytes. Events: token | tool_call | tool_result | done | error
	"""
	messages: list[dict] = [{"role": "system", "content": system_prompt}]
	if history:
		messages.extend(history)
	messages.append({"role": "user", "content": user_message})

	tool_rounds = 0
	seen_tool_calls: set[str] = set()

	while True:
		try:
			# Stream tokens for UX; collect full content for tool call detection
			accumulated_content = ""
			accumulated_tool_calls: list[dict] = []
			done_reason = "stop"

			for chunk in _chat_stream(messages, tool_schemas, model, ollama_url):
				msg = chunk.get("message", {})
				content_delta = msg.get("content", "")
				if content_delta:
					accumulated_content += content_delta
					yield _sse_token(content_delta)

				# Ollama delivers tool_calls in the final chunk
				if msg.get("tool_calls"):
					accumulated_tool_calls = msg["tool_calls"]

				if chunk.get("done"):
					done_reason = chunk.get("done_reason", "stop")
					break

		except requests.RequestException as exc:
			yield _sse_error(f"Ollama request failed: {exc}")
			return
		except Exception as exc:
			yield _sse_error(f"Agent error: {exc}")
			return

		# --- No tool calls: we're done ---
		if done_reason != "tool_calls" or not accumulated_tool_calls:
			messages.append({"role": "assistant", "content": accumulated_content})
			yield _sse_done()
			return

		# --- Tool calls ---
		tool_rounds += 1
		if tool_rounds > MAX_TOOL_ROUNDS:
			yield _sse_error(f"Exceeded max tool rounds ({MAX_TOOL_ROUNDS}). Stopping.")
			yield _sse_done()
			return

		# Anti-loop: abort if the exact same (name, args) combination repeats
		def _tc_fp(tc: dict) -> str:
			fn = tc.get("function", {})
			return fn.get("name", "") + ":" + json.dumps(fn.get("arguments", {}), sort_keys=True)

		call_fingerprint = "|".join(sorted(_tc_fp(tc) for tc in accumulated_tool_calls))
		if call_fingerprint in seen_tool_calls:
			yield _sse_error("Detected repeated tool call pattern — stopping to avoid loop.")
			yield _sse_done()
			return
		seen_tool_calls.add(call_fingerprint)

		# Append assistant message with tool_calls
		messages.append({
			"role": "assistant",
			"content": accumulated_content,
			"tool_calls": accumulated_tool_calls,
		})

		# Execute each tool and append results
		for tc in accumulated_tool_calls:
			fn_info = tc.get("function", {})
			name = fn_info.get("name", "")
			raw_args = fn_info.get("arguments", {})

			# Ollama sometimes gives args as JSON string
			if isinstance(raw_args, str):
				try:
					raw_args = json.loads(raw_args)
				except json.JSONDecodeError:
					raw_args = {}

			yield _sse_tool_call(name, raw_args)

			fn = tool_registry.get(name)
			if fn is None:
				result = f"Tool '{name}' not available (not in your permission set or unknown)."
			else:
				try:
					result = fn(**raw_args) if isinstance(raw_args, dict) else fn(raw_args)
					if not isinstance(result, str):
						result = json.dumps(result)
				except Exception as exc:
					result = f"Tool '{name}' raised an error: {exc}"

			yield _sse_tool_result(name, result)

			messages.append({
				"role": "tool",
				"name": name,
				"content": result,
			})

		# Continue the loop to get the next assistant response


# ---------------------------------------------------------------------------
# Non-streaming variant (for testing/API use)
# ---------------------------------------------------------------------------

def run_agent_blocking(
	user_message: str,
	tool_schemas: list[dict],
	tool_registry: dict[str, Any],
	system_prompt: str,
	history: list[dict] | None = None,
	model: str = _DEFAULT_MODEL,
	ollama_url: str = _DEFAULT_OLLAMA_URL,
) -> tuple[str, list[dict]]:
	"""Run the ReAct loop without streaming.

	Returns (final_text, updated_history).
	"""
	messages: list[dict] = [{"role": "system", "content": system_prompt}]
	if history:
		messages.extend(history)
	messages.append({"role": "user", "content": user_message})

	tool_rounds = 0
	seen_tool_calls: set[str] = set()

	while True:
		resp = _chat(messages, tool_schemas, model, ollama_url, stream=False)
		msg = resp.get("message", {})
		content = msg.get("content", "")
		done_reason = resp.get("done_reason", "stop")
		tool_calls = msg.get("tool_calls", [])

		if done_reason != "tool_calls" or not tool_calls:
			messages.append({"role": "assistant", "content": content})
			# Return history minus the system prompt
			return content, messages[1:]

		tool_rounds += 1
		if tool_rounds > MAX_TOOL_ROUNDS:
			return f"[Max tool rounds exceeded after {MAX_TOOL_ROUNDS} iterations]", messages[1:]

		def _fp(tc: dict) -> str:
			fn = tc.get("function", {})
			return fn.get("name", "") + ":" + json.dumps(fn.get("arguments", {}), sort_keys=True)

		call_fp = "|".join(sorted(_fp(tc) for tc in tool_calls))
		if call_fp in seen_tool_calls:
			return "[Loop detected — aborting]", messages[1:]
		seen_tool_calls.add(call_fp)

		messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

		for tc in tool_calls:
			fn_info = tc.get("function", {})
			name = fn_info.get("name", "")
			raw_args = fn_info.get("arguments", {})
			if isinstance(raw_args, str):
				try:
					raw_args = json.loads(raw_args)
				except json.JSONDecodeError:
					raw_args = {}
			fn = tool_registry.get(name)
			if fn is None:
				result = f"Tool '{name}' not available."
			else:
				try:
					result = fn(**raw_args) if isinstance(raw_args, dict) else fn(raw_args)
					if not isinstance(result, str):
						result = json.dumps(result)
				except Exception as exc:
					result = f"Tool error: {exc}"
			messages.append({"role": "tool", "name": name, "content": result})


__all__ = [
	"run_agent_stream",
	"run_agent_blocking",
	"MAX_TOOL_ROUNDS",
	"_DEFAULT_MODEL",
	"_DEFAULT_OLLAMA_URL",
]
