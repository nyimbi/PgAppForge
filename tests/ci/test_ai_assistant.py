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
		assert "Written" in result

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
		assert "Max tool rounds" in text or "Loop detected" in text or text == "Final."

	def test_loop_detection(self):
		tc = [{"function": {"name": "read_file", "arguments": {"path": "a"}}}]
		responses = [
			_make_ollama_response("", done_reason="tool_calls", tool_calls=tc),
			_make_ollama_response("", done_reason="tool_calls", tool_calls=tc),  # same fingerprint
			_make_ollama_response("Should not reach."),
		]
		registry = {"read_file": lambda **kw: "data"}
		text, _ = self._call(responses, registry=registry)
		assert "Loop detected" in text or text == "Should not reach."

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
