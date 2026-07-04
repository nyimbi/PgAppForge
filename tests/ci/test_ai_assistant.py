"""
tests/ci/test_ai_assistant.py

Unit tests for the Ollama dev assistant module.
Tests cover: tools (path safety, RBAC), context (repo map, system prompt),
agent (blocking ReAct loop with mocked Ollama), and SSE event encoding.

No real Ollama required — HTTP calls are patched via unittest.mock.
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# tools.py
# ---------------------------------------------------------------------------

class TestSafePath:
	def setup_method(self):
		import pgappforge.ai_assistant.tools as t
		self._orig_root = t.PROJECT_ROOT
		self.tmp = Path(tempfile.mkdtemp()).resolve()  # resolve macOS /var -> /private/var symlink
		t.PROJECT_ROOT = self.tmp

	def teardown_method(self):
		import pgappforge.ai_assistant.tools as t
		t.PROJECT_ROOT = self._orig_root

	def test_safe_path_within_root(self):
		from pgappforge.ai_assistant.tools import safe_path
		import pgappforge.ai_assistant.tools as t
		t.PROJECT_ROOT = self.tmp
		p = safe_path("subdir/file.py")
		assert p == self.tmp / "subdir" / "file.py"

	def test_safe_path_traversal_rejected(self):
		from pgappforge.ai_assistant.tools import safe_path, PROJECT_ROOT
		import pgappforge.ai_assistant.tools as t
		t.PROJECT_ROOT = self.tmp
		with pytest.raises(PermissionError):
			safe_path("../../etc/passwd")

	def test_safe_path_empty_returns_root(self):
		from pgappforge.ai_assistant.tools import safe_path
		import pgappforge.ai_assistant.tools as t
		t.PROJECT_ROOT = self.tmp
		assert safe_path("") == self.tmp


class TestReadFile:
	def setup_method(self):
		import pgappforge.ai_assistant.tools as t
		self._orig_root = t.PROJECT_ROOT
		self.tmp = Path(tempfile.mkdtemp()).resolve()
		t.PROJECT_ROOT = self.tmp

	def teardown_method(self):
		import pgappforge.ai_assistant.tools as t
		t.PROJECT_ROOT = self._orig_root

	def test_read_existing_file(self):
		(self.tmp / "hello.py").write_text("print('hi')")
		from pgappforge.ai_assistant.tools import read_file
		result = read_file("hello.py")
		assert result == "print('hi')"

	def test_read_missing_file(self):
		from pgappforge.ai_assistant.tools import read_file
		result = read_file("nope.py")
		assert "not found" in result.lower()

	def test_read_not_a_file(self):
		(self.tmp / "adir").mkdir()
		from pgappforge.ai_assistant.tools import read_file
		result = read_file("adir")
		assert "not a file" in result.lower()


class TestWriteFile:
	def setup_method(self):
		import pgappforge.ai_assistant.tools as t
		self._orig_root = t.PROJECT_ROOT
		self.tmp = Path(tempfile.mkdtemp()).resolve()
		t.PROJECT_ROOT = self.tmp

	def teardown_method(self):
		import pgappforge.ai_assistant.tools as t
		t.PROJECT_ROOT = self._orig_root

	def test_write_creates_file(self):
		from pgappforge.ai_assistant.tools import write_file
		result = write_file("new/file.py", "x = 1")
		assert (self.tmp / "new" / "file.py").read_text() == "x = 1"
		# New file: result is a unified diff showing all lines as additions
		assert "+x = 1" in result or "Written" in result

	def test_write_traversal_blocked(self):
		from pgappforge.ai_assistant.tools import write_file
		with pytest.raises(PermissionError):
			write_file("../../evil.sh", "rm -rf /")


class TestListDirectory:
	def setup_method(self):
		import pgappforge.ai_assistant.tools as t
		self._orig_root = t.PROJECT_ROOT
		self.tmp = Path(tempfile.mkdtemp()).resolve()
		t.PROJECT_ROOT = self.tmp

	def teardown_method(self):
		import pgappforge.ai_assistant.tools as t
		t.PROJECT_ROOT = self._orig_root

	def test_list_root(self):
		(self.tmp / "alpha.py").write_text("")
		(self.tmp / "beta/").mkdir()
		from pgappforge.ai_assistant.tools import list_directory
		result = list_directory("")
		assert "alpha.py" in result
		assert "beta/" in result

	def test_list_not_a_dir(self):
		from pgappforge.ai_assistant.tools import list_directory
		result = list_directory("nonexistent")
		assert "not a directory" in result.lower()


class TestReadLog:
	def setup_method(self):
		import pgappforge.ai_assistant.tools as t
		self._orig_root = t.PROJECT_ROOT
		self.tmp = Path(tempfile.mkdtemp()).resolve()
		t.PROJECT_ROOT = self.tmp

	def teardown_method(self):
		import pgappforge.ai_assistant.tools as t
		t.PROJECT_ROOT = self._orig_root

	def test_read_last_n_lines(self):
		(self.tmp / "app.log").write_text("\n".join(f"line {i}" for i in range(200)))
		from pgappforge.ai_assistant.tools import read_log
		result = read_log("app.log", last_n_lines=10)
		lines = result.splitlines()
		assert len(lines) == 10
		assert lines[0] == "line 190"
		assert lines[-1] == "line 199"

	def test_read_log_missing_file(self):
		from pgappforge.ai_assistant.tools import read_log
		result = read_log("nope.log")
		assert "not found" in result.lower()

	def test_read_log_traversal_blocked(self):
		from pgappforge.ai_assistant.tools import read_log
		with pytest.raises(PermissionError):
			read_log("../../etc/passwd")

	def test_read_log_default_lines(self):
		(self.tmp / "big.log").write_text("\n".join(f"L{i}" for i in range(500)))
		from pgappforge.ai_assistant.tools import read_log
		result = read_log("big.log")
		lines = result.splitlines()
		assert len(lines) == 150  # default

	def test_read_log_cap_at_2000(self):
		(self.tmp / "huge.log").write_text("\n".join(f"X{i}" for i in range(3000)))
		from pgappforge.ai_assistant.tools import read_log
		result = read_log("huge.log", last_n_lines=9999)
		assert len(result.splitlines()) == 2000


class TestGetEnvVars:
	def test_masks_sensitive_keys(self, monkeypatch):
		monkeypatch.setenv("FLASK_SECRET_KEY", "super-secret-value")
		monkeypatch.setenv("FLASK_DEBUG", "1")
		from pgappforge.ai_assistant.tools import get_env_vars
		result = get_env_vars()
		assert "***" in result
		assert "super-secret-value" not in result

	def test_shows_nonsensitive_value(self, monkeypatch):
		monkeypatch.setenv("FLASK_DEBUG", "true")
		from pgappforge.ai_assistant.tools import get_env_vars
		result = get_env_vars()
		assert "FLASK_DEBUG=true" in result

	def test_filters_unrelated_vars(self, monkeypatch):
		monkeypatch.setenv("PATH", "/usr/bin:/bin")
		monkeypatch.setenv("HOME", "/root")
		from pgappforge.ai_assistant.tools import get_env_vars
		result = get_env_vars()
		assert "PATH=" not in result
		assert "HOME=" not in result

	def test_registered_in_all_four_places(self):
		from pgappforge.ai_assistant.tools import (
			TOOL_SCHEMAS, READ_TOOL_NAMES, _TOOL_FN_MAP, get_env_vars,
		)
		assert "get_env_vars" in READ_TOOL_NAMES
		assert any(s["function"]["name"] == "get_env_vars" for s in TOOL_SCHEMAS)
		assert "get_env_vars" in _TOOL_FN_MAP
		assert _TOOL_FN_MAP["get_env_vars"] is get_env_vars


class TestBuildToolRegistry:
	def test_admin_gets_write_tools(self):
		from pgappforge.ai_assistant.tools import build_tool_registry, WRITE_TOOL_NAMES
		schemas, registry = build_tool_registry({"Admin"})
		names = {s["function"]["name"] for s in schemas}
		for w in WRITE_TOOL_NAMES:
			assert w in names
		for w in WRITE_TOOL_NAMES:
			assert w in registry

	def test_viewer_no_write_tools(self):
		from pgappforge.ai_assistant.tools import build_tool_registry, WRITE_TOOL_NAMES
		schemas, registry = build_tool_registry({"Viewer"})
		names = {s["function"]["name"] for s in schemas}
		for w in WRITE_TOOL_NAMES:
			assert w not in names
		for w in WRITE_TOOL_NAMES:
			assert w not in registry

	def test_developer_has_write(self):
		from pgappforge.ai_assistant.tools import build_tool_registry, WRITE_TOOL_NAMES
		schemas, registry = build_tool_registry({"Developer"})
		names = {s["function"]["name"] for s in schemas}
		for w in WRITE_TOOL_NAMES:
			assert w in names

	def test_empty_roles_read_only(self):
		from pgappforge.ai_assistant.tools import build_tool_registry, READ_TOOL_NAMES, WRITE_TOOL_NAMES
		schemas, registry = build_tool_registry(set())
		names = {s["function"]["name"] for s in schemas}
		# Read tools present, write tools absent
		for r in READ_TOOL_NAMES:
			assert r in names
		for w in WRITE_TOOL_NAMES:
			assert w not in names


class TestRunCommandAllowlist:
	def test_blocked_rm(self):
		from pgappforge.ai_assistant.tools import run_command
		result = run_command("rm -rf /tmp/x")
		assert "blocked" in result.lower()

	def test_blocked_sudo(self):
		from pgappforge.ai_assistant.tools import run_command
		result = run_command("sudo ls")
		assert "blocked" in result.lower()

	def test_not_in_allowlist(self):
		from pgappforge.ai_assistant.tools import run_command
		result = run_command("echo hello")
		assert "not in allowlist" in result.lower()

	def test_blocked_find_exec(self):
		from pgappforge.ai_assistant.tools import run_command
		result = run_command("find . -name '*.py' -exec cat {} \\;")
		assert "blocked" in result.lower()

	def test_blocked_pipe_to_shell(self):
		from pgappforge.ai_assistant.tools import run_command
		result = run_command("git log | bash")
		assert "blocked" in result.lower()

	def test_git_status_executes(self):
		from pgappforge.ai_assistant.tools import run_command
		result = run_command("git status")
		# git may complain about no repo in a temp dir, but it should not be blocked
		assert "blocked" not in result.lower()
		assert "not in allowlist" not in result.lower()

	def test_python_pip_list_executes(self):
		"""Python interpreter path must match allowlist case-sensitively (macOS /Users/ fix)."""
		from pgappforge.ai_assistant.tools import run_command, _PYTHON
		result = run_command(f"{_PYTHON} -m pip list")
		assert "blocked" not in result.lower()
		assert "not in allowlist" not in result.lower()
		# pip list output always contains "Package" or "pip"
		assert any(w in result for w in ("Package", "pip", "Version"))


# ---------------------------------------------------------------------------
# context.py
# ---------------------------------------------------------------------------

class TestGenerateRepoMap:
	def test_generates_map_for_python_files(self):
		with tempfile.TemporaryDirectory() as td:
			root = Path(td)
			(root / "mymod.py").write_text("class Foo:\n    def bar(self): pass\n")
			from pgappforge.ai_assistant.context import generate_repo_map
			result = generate_repo_map(root)
			assert "class Foo" in result
			assert "def bar" in result

	def test_skips_venv(self):
		with tempfile.TemporaryDirectory() as td:
			root = Path(td)
			venv = root / ".venv" / "lib"
			venv.mkdir(parents=True)
			(venv / "skip.py").write_text("class Hidden: pass")
			(root / "visible.py").write_text("class Visible: pass")
			from pgappforge.ai_assistant.context import generate_repo_map
			result = generate_repo_map(root)
			assert "Visible" in result
			assert "Hidden" not in result

	def test_max_files_cap(self):
		with tempfile.TemporaryDirectory() as td:
			root = Path(td)
			for i in range(5):
				(root / f"mod{i}.py").write_text(f"def fn{i}(): pass")
			from pgappforge.ai_assistant.context import generate_repo_map
			result = generate_repo_map(root, max_files=3)
			assert "..." in result


class TestBuildSystemPrompt:
	def test_includes_base_prompt(self):
		with tempfile.TemporaryDirectory() as td:
			from pgappforge.ai_assistant.context import build_system_prompt
			result = build_system_prompt(Path(td), include_repo_map=False)
			assert "PgAppForge" in result
			assert "TABS" in result

	def test_custom_app_name(self):
		with tempfile.TemporaryDirectory() as td:
			from pgappforge.ai_assistant.context import build_system_prompt
			result = build_system_prompt(Path(td), app_name="MyApp", include_repo_map=False)
			assert "MyApp" in result

	def test_extra_context_appended(self):
		with tempfile.TemporaryDirectory() as td:
			from pgappforge.ai_assistant.context import build_system_prompt
			result = build_system_prompt(Path(td), include_repo_map=False, extra_context="Focus on billing.")
			assert "Focus on billing." in result

	def test_repo_map_included(self):
		with tempfile.TemporaryDirectory() as td:
			(Path(td) / "foo.py").write_text("class Bar: pass")
			from pgappforge.ai_assistant.context import build_system_prompt
			result = build_system_prompt(Path(td), include_repo_map=True)
			assert "class Bar" in result


# ---------------------------------------------------------------------------
# agent.py — blocking ReAct loop with mocked Ollama
# ---------------------------------------------------------------------------

def _make_ollama_response(content: str, done_reason: str = "stop", tool_calls=None) -> dict:
	msg: dict = {"role": "assistant", "content": content}
	if tool_calls:
		msg["tool_calls"] = tool_calls
	return {"message": msg, "done": True, "done_reason": done_reason}


class TestRunAgentBlocking:
	def _call(self, responses, user_msg="hello", tools=None, registry=None):
		from pgappforge.ai_assistant.agent import run_agent_blocking
		tools = tools or []
		registry = registry or {}
		with patch("pgappforge.ai_assistant.agent.requests.post") as mock_post:
			mock_responses = [MagicMock() for _ in responses]
			for mr, resp in zip(mock_responses, responses):
				mr.raise_for_status = MagicMock()
				mr.json.return_value = resp
			mock_post.side_effect = mock_responses
			return run_agent_blocking(
				user_msg, tools, registry,
				system_prompt="You are a helper.",
			)

	def test_simple_response(self):
		text, hist = self._call([_make_ollama_response("Hello back!")])
		assert text == "Hello back!"
		assert len(hist) == 2  # user + assistant

	def test_single_tool_call(self):
		tc = [{"function": {"name": "read_file", "arguments": {"path": "foo.py"}}}]
		responses = [
			_make_ollama_response("", done_reason="tool_calls", tool_calls=tc),
			_make_ollama_response("I read it."),
		]
		registry = {"read_file": lambda path: "# content"}
		text, hist = self._call(responses, registry=registry)
		assert text == "I read it."
		# tool result should be in history
		roles = [h["role"] for h in hist]
		assert "tool" in roles

	def test_unknown_tool_returns_error_message(self):
		tc = [{"function": {"name": "nonexistent_tool", "arguments": {}}}]
		responses = [
			_make_ollama_response("", done_reason="tool_calls", tool_calls=tc),
			_make_ollama_response("Done."),
		]
		text, hist = self._call(responses, registry={})
		assert text == "Done."

	def test_max_rounds_exceeded(self):
		from pgappforge.ai_assistant.agent import MAX_TOOL_ROUNDS
		tc = [{"function": {"name": "read_file", "arguments": {"path": "a"}}}]
		# Different args each time to avoid the fingerprint loop guard
		rounds_responses = []
		for i in range(MAX_TOOL_ROUNDS + 2):
			unique_tc = [{"function": {"name": f"tool_{i}", "arguments": {}}}]
			rounds_responses.append(_make_ollama_response("", done_reason="tool_calls", tool_calls=unique_tc))
		# Final stop response that may never be reached
		rounds_responses.append(_make_ollama_response("Final."))

		registry = {f"tool_{i}": lambda **kw: "ok" for i in range(MAX_TOOL_ROUNDS + 2)}
		text, _ = self._call(rounds_responses, registry=registry)
		assert "Max tool rounds exceeded" in text

	def test_loop_detection(self):
		tc = [{"function": {"name": "read_file", "arguments": {"path": "a"}}}]
		responses = [
			_make_ollama_response("", done_reason="tool_calls", tool_calls=tc),
			_make_ollama_response("", done_reason="tool_calls", tool_calls=tc),  # same fingerprint
			_make_ollama_response("Should not reach."),
		]
		registry = {"read_file": lambda **kw: "data"}
		text, _ = self._call(responses, registry=registry)
		assert text == "[Loop detected — aborting]"

	def test_history_passed_through(self):
		from pgappforge.ai_assistant.agent import run_agent_blocking
		captured = []
		def fake_post(url, json, **kw):
			captured.append(json["messages"][:])
			m = MagicMock()
			m.raise_for_status = MagicMock()
			m.json.return_value = _make_ollama_response("reply")
			return m
		with patch("pgappforge.ai_assistant.agent.requests.post", side_effect=fake_post):
			run_agent_blocking(
				"new msg", [], {},
				system_prompt="sys",
				history=[{"role": "user", "content": "prev"}, {"role": "assistant", "content": "ans"}],
			)
		msgs = captured[0]
		roles = [m["role"] for m in msgs]
		assert roles == ["system", "user", "assistant", "user"]


# ---------------------------------------------------------------------------
# agent.py — SSE streaming helpers
# ---------------------------------------------------------------------------

class TestSSEHelpers:
	def test_sse_token(self):
		from pgappforge.ai_assistant.agent import _sse_token
		raw = _sse_token("hello")
		assert raw.startswith(b"data: ")
		data = json.loads(raw[6:].decode().split("\n")[0])
		assert data["event"] == "token"
		assert data["data"] == "hello"

	def test_sse_done(self):
		from pgappforge.ai_assistant.agent import _sse_done
		raw = _sse_done()
		assert b"done" in raw

	def test_sse_error(self):
		from pgappforge.ai_assistant.agent import _sse_error
		raw = _sse_error("oops")
		data = json.loads(raw[6:].decode().split("\n")[0])
		assert data["event"] == "error"
		assert "oops" in data["message"]

	def test_sse_tool_call(self):
		from pgappforge.ai_assistant.agent import _sse_tool_call
		raw = _sse_tool_call("read_file", {"path": "x.py"})
		data = json.loads(raw[6:].decode().split("\n")[0])
		assert data["event"] == "tool_call"
		assert data["tool"] == "read_file"


# ---------------------------------------------------------------------------
# agent.py — streaming generator (mocked NDJSON stream)
# ---------------------------------------------------------------------------

class TestRunAgentStream:
	def _collect(self, chunks, user_msg="hi", registry=None):
		"""Collect all SSE bytes from the streaming generator."""
		from pgappforge.ai_assistant.agent import run_agent_stream

		class FakeResp:
			def __init__(self, lines):
				self._lines = [l.encode() for l in lines]
				self.status_code = 200
			def raise_for_status(self): pass
			def __enter__(self): return self
			def __exit__(self, *a): pass
			def iter_lines(self): return self._lines

		with patch("pgappforge.ai_assistant.agent.requests.post", return_value=FakeResp(chunks)):
			events = list(run_agent_stream(
				user_msg, [], registry or {},
				system_prompt="sys",
			))
		return events

	def _parse_events(self, raw_events):
		result = []
		for b in raw_events:
			text = b.decode()
			for line in text.splitlines():
				if line.startswith("data: "):
					try:
						result.append(json.loads(line[6:]))
					except Exception:
						pass
		return result

	def test_simple_token_stream(self):
		lines = [
			json.dumps({"message": {"role": "assistant", "content": "Hello"}}),
			json.dumps({"message": {"role": "assistant", "content": " world"}, "done": True, "done_reason": "stop"}),
		]
		events = self._parse_events(self._collect(lines))
		token_events = [e for e in events if e["event"] == "token"]
		assert any(e["data"] == "Hello" for e in token_events)
		assert any(e["event"] == "done" for e in events)

	def test_stream_error_on_request_failure(self):
		from pgappforge.ai_assistant.agent import run_agent_stream
		with patch("pgappforge.ai_assistant.agent.requests.post", side_effect=Exception("refused")):
			events = self._parse_events(list(run_agent_stream(
				"hi", [], {}, system_prompt="sys",
			)))
		assert any(e["event"] == "error" for e in events)


# ---------------------------------------------------------------------------
# agent.py — streaming with tool calls (multi-round)
# ---------------------------------------------------------------------------

class TestRunAgentStreamWithToolCalls:
	"""SSE streaming path where done_reason=='tool_calls' triggers tool execution."""

	def _run(self, first_lines, second_lines, registry=None):
		"""Run stream with two sequential Ollama calls mocked."""
		from pgappforge.ai_assistant.agent import run_agent_stream

		class FakeResp:
			def __init__(self, lines):
				self._lines = [l.encode() for l in lines]
				self.status_code = 200
			def raise_for_status(self): pass
			def __enter__(self): return self
			def __exit__(self, *a): pass
			def iter_lines(self): return iter(self._lines)

		call_count = [0]
		responses = [first_lines, second_lines]

		def fake_post(*args, **kwargs):
			resp = FakeResp(responses[call_count[0]])
			call_count[0] += 1
			return resp

		with patch("pgappforge.ai_assistant.agent.requests.post", side_effect=fake_post):
			events_raw = list(run_agent_stream(
				"What files exist?", [], registry or {},
				system_prompt="sys",
			))

		parsed = []
		for b in events_raw:
			for line in b.decode().splitlines():
				if line.startswith("data: "):
					try:
						parsed.append(json.loads(line[6:]))
					except Exception:
						pass
		return parsed, call_count[0]

	def test_tool_call_triggers_second_round(self):
		tc = [{"function": {"name": "list_directory", "arguments": {"path": ""}}}]
		first = [
			json.dumps({"message": {"role": "assistant", "content": ""}}),
			json.dumps({"message": {"role": "assistant", "content": "", "tool_calls": tc},
						"done": True, "done_reason": "tool_calls"}),
		]
		second = [
			json.dumps({"message": {"role": "assistant", "content": "Found files."}}),
			json.dumps({"message": {"role": "assistant", "content": ""},
						"done": True, "done_reason": "stop"}),
		]
		registry = {"list_directory": lambda path="": "file1.py\nfile2.py"}
		events, rounds = self._run(first, second, registry=registry)
		assert rounds == 2
		assert any(e["event"] == "tool_call" and e["tool"] == "list_directory" for e in events)
		assert any(e["event"] == "tool_result" for e in events)
		assert any(e["event"] == "done" for e in events)

	def test_tool_result_in_token_stream(self):
		tc = [{"function": {"name": "read_file", "arguments": {"path": "main.py"}}}]
		first = [
			json.dumps({"message": {"role": "assistant", "content": "", "tool_calls": tc},
						"done": True, "done_reason": "tool_calls"}),
		]
		second = [
			json.dumps({"message": {"role": "assistant", "content": "Here it is."}}),
			json.dumps({"message": {"role": "assistant", "content": ""},
						"done": True, "done_reason": "stop"}),
		]
		registry = {"read_file": lambda path="": "x = 1"}
		events, _ = self._run(first, second, registry=registry)
		token_texts = [e["data"] for e in events if e["event"] == "token"]
		assert "Here it is." in "".join(token_texts)

	def test_unknown_tool_yields_error_result_then_continues(self):
		tc = [{"function": {"name": "nonexistent", "arguments": {}}}]
		first = [
			json.dumps({"message": {"role": "assistant", "content": "", "tool_calls": tc},
						"done": True, "done_reason": "tool_calls"}),
		]
		second = [
			json.dumps({"message": {"role": "assistant", "content": "Sorry, can't do that."},
						"done": True, "done_reason": "stop"}),
		]
		events, rounds = self._run(first, second, registry={})
		assert rounds == 2
		# tool_result event for unknown tool still fires (with error message)
		tool_results = [e for e in events if e["event"] == "tool_result"]
		assert len(tool_results) == 1
		assert "not available" in tool_results[0]["result"]


# ---------------------------------------------------------------------------
# views.py — _sanitize_history
# ---------------------------------------------------------------------------

class TestSanitizeHistory:
	def _sanitize(self, raw):
		from pgappforge.ai_assistant.views import _sanitize_history
		return _sanitize_history(raw)

	def test_strips_system_role(self):
		raw = [
			{"role": "system", "content": "injected system prompt"},
			{"role": "user", "content": "hello"},
		]
		result = self._sanitize(raw)
		roles = [r["role"] for r in result]
		assert "system" not in roles
		assert "user" in roles

	def test_strips_tool_role(self):
		raw = [
			{"role": "tool", "content": "tool output"},
			{"role": "assistant", "content": "ok"},
		]
		result = self._sanitize(raw)
		assert all(r["role"] != "tool" for r in result)

	def test_caps_content_at_8000(self):
		raw = [{"role": "user", "content": "x" * 10000}]
		result = self._sanitize(raw)
		assert len(result[0]["content"]) == 8000

	def test_caps_turns_at_40(self):
		raw = [{"role": "user", "content": f"msg {i}"} for i in range(60)]
		result = self._sanitize(raw)
		assert len(result) == 40
		# last 40 kept
		assert result[0]["content"] == "msg 20"
		assert result[-1]["content"] == "msg 59"

	def test_rejects_non_dict_entries(self):
		raw = ["not a dict", {"role": "user", "content": "valid"}, 42]
		result = self._sanitize(raw)
		assert len(result) == 1
		assert result[0]["content"] == "valid"

	def test_rejects_non_string_content(self):
		raw = [{"role": "user", "content": ["list", "of", "things"]}]
		result = self._sanitize(raw)
		assert result == []

	def test_empty_list(self):
		assert self._sanitize([]) == []


# ---------------------------------------------------------------------------
# views.py — _get_ollama_models
# ---------------------------------------------------------------------------

class TestGetOllamaModels:
	def test_returns_model_names(self):
		from pgappforge.ai_assistant.views import _get_ollama_models
		fake_resp = MagicMock()
		fake_resp.raise_for_status = MagicMock()
		fake_resp.json.return_value = {"models": [
			{"name": "qwen2.5-coder:7b"},
			{"name": "llama3.1:8b"},
		]}
		with patch("pgappforge.ai_assistant.views._req.get", return_value=fake_resp):
			result = _get_ollama_models("http://localhost:11434")
		assert result == ["qwen2.5-coder:7b", "llama3.1:8b"]

	def test_returns_empty_on_connection_error(self):
		from pgappforge.ai_assistant.views import _get_ollama_models
		with patch("pgappforge.ai_assistant.views._req.get", side_effect=Exception("refused")):
			result = _get_ollama_models("http://localhost:11434")
		assert result == []

	def test_returns_empty_on_bad_json(self):
		from pgappforge.ai_assistant.views import _get_ollama_models
		fake_resp = MagicMock()
		fake_resp.raise_for_status = MagicMock()
		fake_resp.json.return_value = {}  # missing "models" key
		with patch("pgappforge.ai_assistant.views._req.get", return_value=fake_resp):
			result = _get_ollama_models("http://localhost:11434")
		assert result == []

	def test_returns_empty_on_http_error(self):
		from pgappforge.ai_assistant.views import _get_ollama_models
		fake_resp = MagicMock()
		fake_resp.raise_for_status.side_effect = Exception("503")
		with patch("pgappforge.ai_assistant.views._req.get", return_value=fake_resp):
			result = _get_ollama_models("http://localhost:11434")
		assert result == []


# ---------------------------------------------------------------------------
# agent.py — MAX_TOOL_RESULT_CHARS truncation
# ---------------------------------------------------------------------------

class TestToolResultTruncation:
	def test_large_tool_result_truncated_in_messages(self):
		"""Tool results > MAX_TOOL_RESULT_CHARS must not reach messages verbatim."""
		from pgappforge.ai_assistant.agent import run_agent_blocking, MAX_TOOL_RESULT_CHARS

		big_result = "A" * (MAX_TOOL_RESULT_CHARS + 5000)
		tc = [{"function": {"name": "read_file", "arguments": {"path": "big.py"}}}]
		responses = [
			_make_ollama_response("", done_reason="tool_calls", tool_calls=tc),
			_make_ollama_response("Done."),
		]
		registry = {"read_file": lambda path="": big_result}

		captured_messages = []

		def fake_post(url, json, **kw):
			captured_messages.append(json["messages"][:])
			idx = len(captured_messages) - 1
			m = MagicMock()
			m.raise_for_status = MagicMock()
			m.json.return_value = responses[idx]
			return m

		with patch("pgappforge.ai_assistant.agent.requests.post", side_effect=fake_post):
			run_agent_blocking("read the big file", [], registry, system_prompt="sys")

		# Second call's messages include the tool result — must be capped
		second_call_msgs = captured_messages[1]
		tool_msgs = [m for m in second_call_msgs if m.get("role") == "tool"]
		assert len(tool_msgs) == 1
		assert len(tool_msgs[0]["content"]) == MAX_TOOL_RESULT_CHARS

	def test_small_tool_result_passes_unchanged(self):
		from pgappforge.ai_assistant.agent import run_agent_blocking, MAX_TOOL_RESULT_CHARS

		small_result = "x = 1\n"
		tc = [{"function": {"name": "read_file", "arguments": {"path": "x.py"}}}]
		responses = [
			_make_ollama_response("", done_reason="tool_calls", tool_calls=tc),
			_make_ollama_response("Done."),
		]
		registry = {"read_file": lambda path="": small_result}

		captured_messages = []

		def fake_post(url, json, **kw):
			captured_messages.append(json["messages"][:])
			m = MagicMock()
			m.raise_for_status = MagicMock()
			m.json.return_value = responses[len(captured_messages) - 1]
			return m

		with patch("pgappforge.ai_assistant.agent.requests.post", side_effect=fake_post):
			run_agent_blocking("read x.py", [], registry, system_prompt="sys")

		second_call_msgs = captured_messages[1]
		tool_msgs = [m for m in second_call_msgs if m.get("role") == "tool"]
		assert tool_msgs[0]["content"] == small_result


# ---------------------------------------------------------------------------
# tools.py — patch_file
# ---------------------------------------------------------------------------

class TestPatchFile:
	def setup_method(self):
		import pgappforge.ai_assistant.tools as t
		self._orig_root = t.PROJECT_ROOT
		self.tmp = Path(tempfile.mkdtemp()).resolve()
		t.PROJECT_ROOT = self.tmp

	def teardown_method(self):
		import pgappforge.ai_assistant.tools as t
		t.PROJECT_ROOT = self._orig_root

	def test_patch_replaces_exactly_once(self):
		(self.tmp / "f.py").write_text("x = 1\ny = 2\n")
		from pgappforge.ai_assistant.tools import patch_file
		result = patch_file("f.py", "x = 1", "x = 99")
		assert (self.tmp / "f.py").read_text() == "x = 99\ny = 2\n"
		assert "-x = 1" in result
		assert "+x = 99" in result

	def test_patch_not_found_returns_helpful_message(self):
		(self.tmp / "f.py").write_text("x = 1\n")
		from pgappforge.ai_assistant.tools import patch_file
		result = patch_file("f.py", "z = 99", "z = 0")
		assert "not found" in result.lower()
		assert "x = 1" in result  # shows file content for context

	def test_patch_ambiguous_fails(self):
		(self.tmp / "f.py").write_text("x = 1\nx = 1\n")
		from pgappforge.ai_assistant.tools import patch_file
		result = patch_file("f.py", "x = 1", "x = 2")
		assert "2 times" in result
		assert (self.tmp / "f.py").read_text() == "x = 1\nx = 1\n"  # unchanged

	def test_patch_missing_file(self):
		from pgappforge.ai_assistant.tools import patch_file
		result = patch_file("nope.py", "a", "b")
		assert "not found" in result.lower()

	def test_patch_traversal_blocked(self):
		from pgappforge.ai_assistant.tools import patch_file
		with pytest.raises(PermissionError):
			patch_file("../../etc/hosts", "localhost", "evil")

	def test_patch_writes_audit_log(self):
		(self.tmp / "f.py").write_text("a = 1\n")
		from pgappforge.ai_assistant.tools import patch_file
		patch_file("f.py", "a = 1", "a = 2")
		audit_path = self.tmp / "logs" / "dev_assistant_audit.jsonl"
		assert audit_path.exists()
		record = json.loads(audit_path.read_text().strip())
		assert record["action"] == "patch_file"
		assert record["path"] == "f.py"


# ---------------------------------------------------------------------------
# tools.py — write_file now returns unified diff
# ---------------------------------------------------------------------------

class TestWriteFileDiff:
	def setup_method(self):
		import pgappforge.ai_assistant.tools as t
		self._orig_root = t.PROJECT_ROOT
		self.tmp = Path(tempfile.mkdtemp()).resolve()
		t.PROJECT_ROOT = self.tmp

	def teardown_method(self):
		import pgappforge.ai_assistant.tools as t
		t.PROJECT_ROOT = self._orig_root

	def test_new_file_no_diff_marker(self):
		from pgappforge.ai_assistant.tools import write_file
		result = write_file("new.py", "x = 1\n")
		# New file: diff shows only additions
		assert (self.tmp / "new.py").read_text() == "x = 1\n"
		assert "+x = 1" in result or "Written" in result

	def test_overwrite_shows_diff(self):
		(self.tmp / "g.py").write_text("old line\n")
		from pgappforge.ai_assistant.tools import write_file
		result = write_file("g.py", "new line\n")
		assert "-old line" in result
		assert "+new line" in result

	def test_no_change_says_so(self):
		(self.tmp / "h.py").write_text("same\n")
		from pgappforge.ai_assistant.tools import write_file
		result = write_file("h.py", "same\n")
		assert "no change" in result.lower()


# ---------------------------------------------------------------------------
# tools.py — get_db_schema (mocked SQLAlchemy)
# ---------------------------------------------------------------------------

class TestGetDbSchema:
	def test_no_dsn_returns_message(self, monkeypatch):
		monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
		monkeypatch.delenv("DATABASE_URL", raising=False)
		from pgappforge.ai_assistant.tools import get_db_schema
		result = get_db_schema()
		assert "no sqlalchemy_database_uri" in result.lower() or "no " in result.lower()

	def test_returns_table_list(self, monkeypatch):
		monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "postgresql://u:p@h/db")
		mock_insp = MagicMock()
		mock_insp.get_table_names.return_value = ["user", "role", "permission"]
		mock_engine = MagicMock()

		with patch("pgappforge.ai_assistant.tools._get_db_engine", return_value=mock_engine), \
			 patch("pgappforge.ai_assistant.tools.sa_inspect", return_value=mock_insp):
			from pgappforge.ai_assistant.tools import get_db_schema
			result = get_db_schema()
		assert "user" in result
		assert "role" in result

	def test_returns_column_details(self, monkeypatch):
		monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "postgresql://u:p@h/db")
		from sqlalchemy import String, Integer
		mock_insp = MagicMock()
		mock_insp.get_columns.return_value = [
			{"name": "id", "type": Integer(), "nullable": False, "default": None},
			{"name": "name", "type": String(), "nullable": True, "default": None},
		]
		mock_insp.get_pk_constraint.return_value = {"constrained_columns": ["id"]}
		mock_insp.get_foreign_keys.return_value = []
		mock_insp.get_indexes.return_value = []
		mock_engine = MagicMock()

		with patch("pgappforge.ai_assistant.tools._get_db_engine", return_value=mock_engine), \
			 patch("pgappforge.ai_assistant.tools.sa_inspect", return_value=mock_insp):
			from pgappforge.ai_assistant.tools import get_db_schema
			result = get_db_schema("user")
		assert "id" in result
		assert "[PK]" in result
		assert "name" in result

	def test_engine_error_returns_message(self, monkeypatch):
		monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "postgresql://u:p@h/db")
		mock_engine = MagicMock()
		with patch("pgappforge.ai_assistant.tools._get_db_engine", return_value=mock_engine), \
			 patch("pgappforge.ai_assistant.tools.sa_inspect", side_effect=Exception("conn refused")):
			from pgappforge.ai_assistant.tools import get_db_schema
			result = get_db_schema()
		assert "failed" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# tools.py — alembic_status
# ---------------------------------------------------------------------------

class TestAlembicStatus:
	def test_returns_current_and_heads(self):
		from pgappforge.ai_assistant.tools import alembic_status
		fake = MagicMock()
		fake.stdout = "abc123 (head)\n"
		fake.stderr = ""
		fake2 = MagicMock()
		fake2.stdout = "abc123\n"
		fake2.stderr = ""
		with patch("pgappforge.ai_assistant.tools.subprocess.run", side_effect=[fake, fake2]):
			result = alembic_status()
		assert "abc123" in result
		assert "Current revision" in result
		assert "Available heads" in result

	def test_alembic_not_found(self):
		from pgappforge.ai_assistant.tools import alembic_status
		with patch("pgappforge.ai_assistant.tools.subprocess.run",
				   side_effect=FileNotFoundError()):
			result = alembic_status()
		assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# tools.py — get_project_deps
# ---------------------------------------------------------------------------

class TestGetProjectDeps:
	def setup_method(self):
		import pgappforge.ai_assistant.tools as t
		self._orig_root = t.PROJECT_ROOT
		self.tmp = Path(tempfile.mkdtemp()).resolve()
		t.PROJECT_ROOT = self.tmp

	def teardown_method(self):
		import pgappforge.ai_assistant.tools as t
		t.PROJECT_ROOT = self._orig_root

	def test_reads_requirements_txt(self):
		(self.tmp / "requirements.txt").write_text("flask>=3.0\nsqlalchemy>=2.0\n")
		from pgappforge.ai_assistant.tools import get_project_deps
		result = get_project_deps()
		assert "flask" in result
		assert "sqlalchemy" in result

	def test_reads_pyproject_toml(self):
		(self.tmp / "pyproject.toml").write_text('[project]\nname = "myapp"\n')
		from pgappforge.ai_assistant.tools import get_project_deps
		result = get_project_deps()
		assert "myapp" in result


# ---------------------------------------------------------------------------
# tools.py — read_audit_log + audit side-effects
# ---------------------------------------------------------------------------

class TestAuditLog:
	def setup_method(self):
		import pgappforge.ai_assistant.tools as t
		self._orig_root = t.PROJECT_ROOT
		self.tmp = Path(tempfile.mkdtemp()).resolve()
		t.PROJECT_ROOT = self.tmp

	def teardown_method(self):
		import pgappforge.ai_assistant.tools as t
		t.PROJECT_ROOT = self._orig_root

	def test_no_audit_log_returns_message(self):
		from pgappforge.ai_assistant.tools import read_audit_log
		result = read_audit_log()
		assert "no audit log" in result.lower()

	def test_write_file_creates_audit_entry(self):
		from pgappforge.ai_assistant.tools import write_file, read_audit_log
		write_file("x.py", "a = 1\n")
		audit = read_audit_log()
		assert "write_file" in audit

	def test_patch_file_creates_audit_entry(self):
		(self.tmp / "y.py").write_text("b = 2\n")
		from pgappforge.ai_assistant.tools import patch_file, read_audit_log
		patch_file("y.py", "b = 2", "b = 3")
		audit = read_audit_log()
		assert "patch_file" in audit

	def test_last_n_limits_entries(self):
		import pgappforge.ai_assistant.tools as t
		log_path = t.PROJECT_ROOT / t._AUDIT_SUBPATH
		log_path.parent.mkdir(parents=True, exist_ok=True)
		for i in range(10):
			with log_path.open("a") as fh:
				fh.write(f'{{"action":"write_file","n":{i}}}\n')
		from pgappforge.ai_assistant.tools import read_audit_log
		result = read_audit_log(last_n=3)
		assert result.count("write_file") == 3


# ---------------------------------------------------------------------------
# tools.py — git_commit + git_create_branch
# ---------------------------------------------------------------------------

class TestGitWriteTools:
	def test_git_commit_empty_message_rejected(self):
		from pgappforge.ai_assistant.tools import git_commit
		result = git_commit("")
		assert "required" in result.lower()

	def test_git_commit_calls_add_then_commit(self):
		from pgappforge.ai_assistant.tools import git_commit
		add_result = MagicMock(returncode=0, stdout="", stderr="")
		commit_result = MagicMock(returncode=0, stdout="[main abc1234] test msg\n", stderr="")
		with patch("pgappforge.ai_assistant.tools.subprocess.run",
				   side_effect=[add_result, commit_result]) as mock_run:
			result = git_commit("test msg")
		calls = [c.args[0] for c in mock_run.call_args_list]
		assert calls[0] == ["git", "add", "-u"]
		assert calls[1][:2] == ["git", "commit"]
		assert "abc1234" in result

	def test_git_commit_add_failure_short_circuits(self):
		from pgappforge.ai_assistant.tools import git_commit
		add_result = MagicMock(returncode=1, stdout="", stderr="not a repo")
		with patch("pgappforge.ai_assistant.tools.subprocess.run", return_value=add_result):
			result = git_commit("msg")
		assert "failed" in result.lower()

	def test_git_create_branch_empty_name_rejected(self):
		from pgappforge.ai_assistant.tools import git_create_branch
		result = git_create_branch("")
		assert "required" in result.lower()

	def test_git_create_branch_sanitises_name(self):
		from pgappforge.ai_assistant.tools import git_create_branch
		checkout_result = MagicMock(returncode=0, stdout="Switched to a new branch 'feat-foo'\n", stderr="")
		with patch("pgappforge.ai_assistant.tools.subprocess.run",
				   return_value=checkout_result) as mock_run:
			git_create_branch("feat/foo bar!")
		called_args = mock_run.call_args.args[0]
		branch_arg = called_args[3]
		assert " " not in branch_arg
		assert "!" not in branch_arg

	def test_new_tools_in_write_role(self):
		from pgappforge.ai_assistant.tools import WRITE_TOOL_NAMES
		assert "patch_file" in WRITE_TOOL_NAMES
		assert "git_commit" in WRITE_TOOL_NAMES
		assert "git_create_branch" in WRITE_TOOL_NAMES

	def test_new_read_tools_in_read_role(self):
		from pgappforge.ai_assistant.tools import READ_TOOL_NAMES
		assert "get_db_schema" in READ_TOOL_NAMES
		assert "alembic_status" in READ_TOOL_NAMES
		assert "get_project_deps" in READ_TOOL_NAMES
		assert "read_audit_log" in READ_TOOL_NAMES


# ---------------------------------------------------------------------------
# _db.py — shared engine singleton
# ---------------------------------------------------------------------------

class TestSharedEngine:
	def setup_method(self):
		from pgappforge.ai_assistant._db import reset_engine
		reset_engine()

	def teardown_method(self):
		from pgappforge.ai_assistant._db import reset_engine
		reset_engine()

	def test_get_engine_returns_none_without_dsn(self, monkeypatch):
		monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
		from pgappforge.ai_assistant._db import get_engine
		result = get_engine()
		assert result is None

	def test_reset_engine_clears_cached_engine(self, monkeypatch):
		import pgappforge.ai_assistant._db as db_mod
		fake = object()
		db_mod._engine = fake
		from pgappforge.ai_assistant._db import reset_engine, get_engine
		monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
		reset_engine()
		assert db_mod._engine is None
		assert get_engine() is None

	def test_get_engine_creates_engine_with_valid_dsn(self, monkeypatch):
		monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "postgresql://u:p@localhost/testdb")
		mock_engine = MagicMock()
		# create_engine is imported at module level in _db.py, so patch it there
		with patch("pgappforge.ai_assistant._db.create_engine", return_value=mock_engine) as mock_ce:
			from pgappforge.ai_assistant._db import get_engine
			engine = get_engine()
		assert engine is mock_engine
		mock_ce.assert_called_once()
		# Verify pool config was passed
		_, kwargs = mock_ce.call_args
		assert kwargs.get("pool_pre_ping") is True
		assert kwargs.get("pool_size") == 2


# ---------------------------------------------------------------------------
# tools.py — semantic_search
# ---------------------------------------------------------------------------

class TestSemanticSearch:
	def test_empty_query_returns_error(self):
		from pgappforge.ai_assistant.tools import semantic_search
		result = semantic_search("")
		assert result.startswith("Error:")

	def test_whitespace_query_returns_error(self):
		from pgappforge.ai_assistant.tools import semantic_search
		result = semantic_search("   ")
		assert result.startswith("Error:")

	def test_no_embeddings_module_returns_message(self):
		import pgappforge.ai_assistant.tools as t
		orig = t._HAS_EMBEDDINGS
		try:
			t._HAS_EMBEDDINGS = False
			from pgappforge.ai_assistant.tools import semantic_search
			result = semantic_search("auth handler")
		finally:
			t._HAS_EMBEDDINGS = orig
		assert "not available" in result.lower()

	def test_top_k_clamped_and_delegates(self):
		import pgappforge.ai_assistant.tools as t
		orig_has = t._HAS_EMBEDDINGS
		captured = {}
		def fake_search(query, top_k, root):
			captured["top_k"] = top_k
			return "ok"
		orig_fn = t._search_embeddings
		t._HAS_EMBEDDINGS = True
		t._search_embeddings = fake_search
		try:
			t.semantic_search("auth", top_k=999)
		finally:
			t._HAS_EMBEDDINGS = orig_has
			t._search_embeddings = orig_fn
		assert captured["top_k"] == 20


# ---------------------------------------------------------------------------
# tools.py — search_web
# ---------------------------------------------------------------------------

class TestSearchWeb:
	def test_empty_query_returns_error(self, monkeypatch):
		monkeypatch.delenv("SEARXNG_URL", raising=False)
		from pgappforge.ai_assistant.tools import search_web
		result = search_web("")
		assert result.startswith("Error:")

	def test_no_searxng_url_returns_message(self, monkeypatch):
		monkeypatch.delenv("SEARXNG_URL", raising=False)
		from pgappforge.ai_assistant.tools import search_web
		result = search_web("python async")
		assert "SEARXNG_URL" in result

	def test_successful_search(self, monkeypatch):
		monkeypatch.setenv("SEARXNG_URL", "http://searx.local")
		fake_resp = MagicMock()
		fake_resp.raise_for_status = MagicMock()
		fake_resp.json.return_value = {"results": [
			{"title": "Python docs", "url": "https://docs.python.org", "content": "Python async tutorial."},
			{"title": "RealPython", "url": "https://realpython.com", "content": "Async deep dive."},
		]}
		with patch("pgappforge.ai_assistant.tools._req.get", return_value=fake_resp):
			from pgappforge.ai_assistant.tools import search_web
			result = search_web("python async", num_results=2)
		assert "Python docs" in result
		assert "docs.python.org" in result

	def test_request_failure_returns_error(self, monkeypatch):
		monkeypatch.setenv("SEARXNG_URL", "http://searx.local")
		with patch("pgappforge.ai_assistant.tools._req.get", side_effect=Exception("timeout")):
			from pgappforge.ai_assistant.tools import search_web
			result = search_web("query")
		assert "failed" in result.lower()


# ---------------------------------------------------------------------------
# tools.py — get_ci_status
# ---------------------------------------------------------------------------

class TestGetCIStatus:
	def test_gh_not_found_returns_install_hint(self):
		from pgappforge.ai_assistant.tools import get_ci_status
		with patch("pgappforge.ai_assistant.tools.subprocess.run",
				   side_effect=FileNotFoundError()):
			result = get_ci_status()
		assert "gh CLI not found" in result

	def test_auth_failure_returns_login_hint(self):
		from pgappforge.ai_assistant.tools import get_ci_status
		fake = MagicMock(returncode=1, stdout="", stderr="not logged in — run gh auth login")
		with patch("pgappforge.ai_assistant.tools.subprocess.run", return_value=fake):
			result = get_ci_status()
		assert "gh auth login" in result

	def test_successful_run_list_parsed(self):
		from pgappforge.ai_assistant.tools import get_ci_status
		runs = [
			{"status": "completed", "conclusion": "success", "name": "CI",
			 "headBranch": "main", "createdAt": "2026-06-17T12:00:00Z", "databaseId": 42},
		]
		fake = MagicMock(returncode=0, stdout=json.dumps(runs), stderr="")
		with patch("pgappforge.ai_assistant.tools.subprocess.run", return_value=fake):
			result = get_ci_status()
		assert "success" in result
		assert "CI" in result


# ---------------------------------------------------------------------------
# tools.py — find_usages
# ---------------------------------------------------------------------------

class TestFindUsages:
	def setup_method(self):
		import pgappforge.ai_assistant.tools as t
		self._orig_root = t.PROJECT_ROOT
		self.tmp = Path(tempfile.mkdtemp()).resolve()
		t.PROJECT_ROOT = self.tmp

	def teardown_method(self):
		import pgappforge.ai_assistant.tools as t
		t.PROJECT_ROOT = self._orig_root

	def test_empty_symbol_returns_error(self):
		from pgappforge.ai_assistant.tools import find_usages
		result = find_usages("")
		assert result.startswith("Error:")

	def test_special_chars_sanitized(self):
		from pgappforge.ai_assistant.tools import find_usages
		captured = {}
		def fake_run(cmd, **kw):
			captured["cmd"] = cmd
			return MagicMock(stdout="", stderr="", returncode=0)
		with patch("pgappforge.ai_assistant.tools.subprocess.run", side_effect=fake_run):
			find_usages("rm -rf; evil")
		# The symbol passed to rg/grep must not contain spaces or semicolons
		sym_arg = captured["cmd"][-2]  # symbol is second-to-last positional arg
		assert ";" not in sym_arg
		assert " " not in sym_arg

	def test_no_usages_returns_message(self):
		from pgappforge.ai_assistant.tools import find_usages
		fake = MagicMock(stdout="", stderr="", returncode=1)
		with patch("pgappforge.ai_assistant.tools.subprocess.run", return_value=fake):
			result = find_usages("nonexistent_symbol")
		assert "no usages" in result.lower()

	def test_output_truncated_at_150_lines(self):
		from pgappforge.ai_assistant.tools import find_usages
		big_output = "\n".join(f"line{i}: x = foo_bar()" for i in range(200))
		fake = MagicMock(stdout=big_output, stderr="", returncode=0)
		with patch("pgappforge.ai_assistant.tools.subprocess.run", return_value=fake):
			result = find_usages("foo_bar")
		assert "truncated" in result.lower()
		# At most 150 result lines + 1 truncation notice + header
		assert result.count("line") <= 152


# ---------------------------------------------------------------------------
# tools.py — get_test_coverage
# ---------------------------------------------------------------------------

class TestGetTestCoverage:
	def setup_method(self):
		import pgappforge.ai_assistant.tools as t
		self._orig_root = t.PROJECT_ROOT
		self.tmp = Path(tempfile.mkdtemp()).resolve()
		t.PROJECT_ROOT = self.tmp

	def teardown_method(self):
		import pgappforge.ai_assistant.tools as t
		t.PROJECT_ROOT = self._orig_root

	def test_traversal_path_blocked(self):
		from pgappforge.ai_assistant.tools import get_test_coverage
		result = get_test_coverage("../../etc/passwd")
		assert "traversal" in result.lower() or "permission" in result.lower()

	def test_mocked_subprocess_returns_output(self):
		from pgappforge.ai_assistant.tools import get_test_coverage
		fake = MagicMock(stdout="TOTAL  1000   50   95%\n", stderr="", returncode=0)
		with patch("pgappforge.ai_assistant.tools.subprocess.run", return_value=fake):
			result = get_test_coverage()
		assert "95%" in result


# ---------------------------------------------------------------------------
# tools.py — rollback_changes
# ---------------------------------------------------------------------------

class TestRollbackChanges:
	def setup_method(self):
		import pgappforge.ai_assistant.tools as t
		self._orig_root = t.PROJECT_ROOT
		self.tmp = Path(tempfile.mkdtemp()).resolve()
		t.PROJECT_ROOT = self.tmp

	def teardown_method(self):
		import pgappforge.ai_assistant.tools as t
		t.PROJECT_ROOT = self._orig_root

	def test_clean_tree_returns_nothing_to_rollback(self):
		from pgappforge.ai_assistant.tools import rollback_changes
		clean = MagicMock(stdout="", stderr="", returncode=0)
		with patch("pgappforge.ai_assistant.tools.subprocess.run", return_value=clean):
			result = rollback_changes()
		assert "clean" in result.lower()

	def test_dirty_tree_without_confirm_returns_prompt(self):
		from pgappforge.ai_assistant.tools import rollback_changes
		status = MagicMock(stdout=" M pgappforge/base.py\n", stderr="", returncode=0)
		with patch("pgappforge.ai_assistant.tools.subprocess.run", return_value=status):
			result = rollback_changes()
		assert "confirm='YES'" in result
		assert "base.py" in result

	def test_dirty_tree_rollback_succeeds_with_confirm(self):
		from pgappforge.ai_assistant.tools import rollback_changes
		status = MagicMock(stdout=" M pgappforge/base.py\n", stderr="", returncode=0)
		stash = MagicMock(stdout="Saved working directory and index state\n", stderr="", returncode=0)
		with patch("pgappforge.ai_assistant.tools.subprocess.run",
				   side_effect=[status, stash]):
			result = rollback_changes(confirm="YES")
		assert "stash" in result.lower() or "stashed" in result.lower()
		assert "base.py" in result

	def test_rollback_failure_returns_error(self):
		from pgappforge.ai_assistant.tools import rollback_changes
		status = MagicMock(stdout=" M foo.py\n", stderr="", returncode=0)
		fail = MagicMock(stdout="", stderr="not a git repo", returncode=1)
		with patch("pgappforge.ai_assistant.tools.subprocess.run",
				   side_effect=[status, fail]):
			result = rollback_changes(confirm="YES")
		assert "failed" in result.lower()


# ---------------------------------------------------------------------------
# embeddings.py — chunk_python_file
# ---------------------------------------------------------------------------

class TestChunkPythonFile:
	def test_valid_python_file_yields_ast_chunks(self):
		from pgappforge.ai_assistant.embeddings import chunk_python_file
		tmp = Path(tempfile.mkdtemp())
		f = tmp / "sample.py"
		f.write_text("def foo():\n    return 1\n\nclass Bar:\n    def baz(self):\n        pass\n")
		chunks = chunk_python_file(f)
		assert len(chunks) >= 2
		# Each chunk is prefixed with filename:lineno
		assert any("sample.py" in c for c in chunks)

	def test_syntax_error_falls_back_to_char_chunks(self):
		from pgappforge.ai_assistant.embeddings import chunk_python_file
		tmp = Path(tempfile.mkdtemp())
		f = tmp / "bad.py"
		f.write_text("def broken(\n    # unclosed parenthesis forever\n" + "x = 1\n" * 50)
		chunks = chunk_python_file(f)
		assert len(chunks) >= 1
		# No crash — just char-based fallback
		for c in chunks:
			assert isinstance(c, str)

	def test_missing_file_returns_empty(self):
		from pgappforge.ai_assistant.embeddings import chunk_python_file
		result = chunk_python_file(Path("/nonexistent/path/file.py"))
		assert result == []

	def test_decorator_included_in_chunk(self):
		from pgappforge.ai_assistant.embeddings import chunk_python_file
		tmp = Path(tempfile.mkdtemp())
		f = tmp / "views.py"
		f.write_text(
			"from flask import expose\n\n"
			"class MyView:\n"
			"    @expose('/')\n"
			"    @staticmethod\n"
			"    def index():\n"
			"        return 'ok'\n"
		)
		chunks = chunk_python_file(f)
		# The @expose decorator must be included in the chunk for the index method
		combined = "\n".join(chunks)
		assert "@expose" in combined


# ---------------------------------------------------------------------------
# session_service.py — graceful no-ops without engine
# ---------------------------------------------------------------------------

class TestSessionService:
	def setup_method(self):
		# Ensure no engine exists for isolation
		from pgappforge.ai_assistant._db import reset_engine
		reset_engine()

	def teardown_method(self):
		from pgappforge.ai_assistant._db import reset_engine
		reset_engine()

	def test_ensure_schema_returns_false_without_engine(self, monkeypatch):
		monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
		from pgappforge.ai_assistant.session_service import ensure_schema
		assert ensure_schema() is False

	def test_create_session_returns_none_without_engine(self, monkeypatch):
		monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
		from pgappforge.ai_assistant.session_service import create_session
		assert create_session("user1") is None

	def test_load_session_returns_none_without_engine(self, monkeypatch):
		monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
		from pgappforge.ai_assistant.session_service import load_session
		assert load_session("some-id", "user1") is None

	def test_save_session_returns_false_without_engine(self, monkeypatch):
		monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
		from pgappforge.ai_assistant.session_service import save_session
		assert save_session("some-id", "user1", []) is False

	def test_list_sessions_returns_empty_without_engine(self, monkeypatch):
		monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
		from pgappforge.ai_assistant.session_service import list_sessions
		assert list_sessions("user1") == []

	def test_delete_session_returns_false_without_engine(self, monkeypatch):
		monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
		from pgappforge.ai_assistant.session_service import delete_session
		assert delete_session("some-id", "user1") is False


# ---------------------------------------------------------------------------
# tools.py — all 6 new tools registered in correct role sets
# ---------------------------------------------------------------------------

class TestNewToolRegistration:
	def test_new_read_tools_registered(self):
		from pgappforge.ai_assistant.tools import READ_TOOL_NAMES
		for name in ("semantic_search", "search_web", "get_ci_status",
					 "find_usages", "get_test_coverage"):
			assert name in READ_TOOL_NAMES, f"{name} missing from READ_TOOL_NAMES"

	def test_rollback_in_write_role(self):
		from pgappforge.ai_assistant.tools import WRITE_TOOL_NAMES
		assert "rollback_changes" in WRITE_TOOL_NAMES

	def test_new_tools_in_schema(self):
		from pgappforge.ai_assistant.tools import TOOL_SCHEMAS
		names = {s["function"]["name"] for s in TOOL_SCHEMAS}
		for name in ("semantic_search", "search_web", "get_ci_status",
					 "find_usages", "get_test_coverage", "rollback_changes"):
			assert name in names, f"{name} missing from TOOL_SCHEMAS"

	def test_new_tools_in_fn_map(self):
		from pgappforge.ai_assistant.tools import _TOOL_FN_MAP
		for name in ("semantic_search", "search_web", "get_ci_status",
					 "find_usages", "get_test_coverage", "rollback_changes",
					 "reindex_codebase"):
			assert name in _TOOL_FN_MAP, f"{name} missing from _TOOL_FN_MAP"

	def test_reindex_in_write_role(self):
		from pgappforge.ai_assistant.tools import WRITE_TOOL_NAMES
		assert "reindex_codebase" in WRITE_TOOL_NAMES


# ---------------------------------------------------------------------------
# tools.py — reindex_codebase
# ---------------------------------------------------------------------------

class TestReindexCodebase:
	def test_no_embeddings_module_returns_message(self):
		import pgappforge.ai_assistant.tools as t
		orig = t._HAS_EMBEDDINGS
		try:
			t._HAS_EMBEDDINGS = False
			from pgappforge.ai_assistant.tools import reindex_codebase
			result = reindex_codebase()
		finally:
			t._HAS_EMBEDDINGS = orig
		assert "not available" in result.lower()

	def test_already_running_returns_message(self):
		import pgappforge.ai_assistant.tools as t
		orig = t._HAS_EMBEDDINGS
		t._HAS_EMBEDDINGS = True
		try:
			with patch("pgappforge.ai_assistant.tools._ensure_schema", return_value=True), \
				 patch("pgappforge.ai_assistant.tools._index_codebase",
				       return_value={"status": "already_running"}):
				from pgappforge.ai_assistant.tools import reindex_codebase
				result = reindex_codebase()
		finally:
			t._HAS_EMBEDDINGS = orig
		assert "in progress" in result.lower() or "already" in result.lower()

	def test_successful_reindex_returns_stats(self):
		import pgappforge.ai_assistant.tools as t
		orig = t._HAS_EMBEDDINGS
		t._HAS_EMBEDDINGS = True
		try:
			with patch("pgappforge.ai_assistant.tools._ensure_schema", return_value=True), \
				 patch("pgappforge.ai_assistant.tools._index_codebase",
				       return_value={"files": 10, "chunks": 45, "skipped": 3, "errors": 0}):
				from pgappforge.ai_assistant.tools import reindex_codebase
				result = reindex_codebase()
		finally:
			t._HAS_EMBEDDINGS = orig
		assert "10" in result
		assert "45" in result
