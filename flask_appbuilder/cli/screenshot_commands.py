"""Screenshot CLI commands for Flask-AppBuilder.

Registered under the 'screenshot' group:
  flask fab screenshot all   --output-dir screenshots/ [--width 1280] [--height 720]
  flask fab screenshot view  VIEW_NAME --output-dir screenshots/
  flask fab screenshot list  -- list all registered views
  flask fab screenshot diff  OLD_DIR NEW_DIR -- pixel-diff two screenshot directories

Playwright is a soft dependency; a clear error is emitted if it is absent.
Pillow is required only for the diff subcommand.

Config can be supplied via flags or a .fab-deploy.yml file under the key
'screenshot':

  screenshot:
    base_url: http://localhost:5000
    username: admin
    password: admin
    output_dir: screenshots/
    width: 1280
    height: 720
    views: ["*"]
"""
from __future__ import annotations

import fnmatch
import logging
import os
import pathlib
import socket
import sys
import threading
import time
from typing import Any

import click
from flask import current_app
from flask.cli import with_appcontext

# ---------------------------------------------------------------------------
# Optional dependency guards
# ---------------------------------------------------------------------------

try:
	from playwright.sync_api import sync_playwright, Browser, Page
	_PLAYWRIGHT_AVAILABLE = True
except ImportError:
	_PLAYWRIGHT_AVAILABLE = False

try:
	from PIL import Image, ImageChops
	_PILLOW_AVAILABLE = True
except ImportError:
	_PILLOW_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_WIDTH = 1280
_DEFAULT_HEIGHT = 720
_DEFAULT_USER = "admin"
_DEFAULT_PASS = "admin"
_CONFIG_FILE = ".fab-deploy.yml"
_TERM_WIDTH = 88


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hr(char: str = "─") -> str:
	return char * _TERM_WIDTH


def _header(text: str) -> None:
	click.echo(click.style(_hr("═"), fg="cyan"))
	click.echo(click.style(f"  {text}", fg="cyan", bold=True))
	click.echo(click.style(_hr("═"), fg="cyan"))


def _require_playwright() -> None:
	if not _PLAYWRIGHT_AVAILABLE:
		click.echo(click.style("Error: Playwright is not installed.", fg="red", bold=True))
		click.echo("")
		click.echo("  Install it with:")
		click.echo(click.style("    pip install playwright", fg="yellow"))
		click.echo(click.style("    playwright install chromium", fg="yellow"))
		click.echo("")
		raise SystemExit(1)


def _require_pillow() -> None:
	if not _PILLOW_AVAILABLE:
		click.echo(click.style("Error: Pillow is not installed.", fg="red", bold=True))
		click.echo("")
		click.echo("  Install it with:")
		click.echo(click.style("    pip install Pillow", fg="yellow"))
		click.echo("")
		raise SystemExit(1)


def _load_yml_config() -> dict[str, Any]:
	"""Load screenshot config from .fab-deploy.yml if it exists."""
	cwd = pathlib.Path.cwd()
	candidates = [cwd / _CONFIG_FILE, cwd.parent / _CONFIG_FILE]
	for path in candidates:
		if path.exists():
			try:
				import yaml  # type: ignore[import-untyped]
				with path.open() as fh:
					data = yaml.safe_load(fh) or {}
				return data.get("screenshot", {})
			except Exception as exc:
				logger.debug("Could not parse %s: %s", path, exc)
	return {}


def _free_port() -> int:
	"""Return an ephemeral free TCP port on localhost."""
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
		s.bind(("127.0.0.1", 0))
		return s.getsockname()[1]


def _start_test_server(app: Any, port: int) -> threading.Thread:
	"""Start a Flask dev server in a daemon thread and return it."""
	def _run() -> None:
		# Suppress werkzeug banner
		import logging as _logging
		_logging.getLogger("werkzeug").setLevel(_logging.ERROR)
		app.run(host="127.0.0.1", port=port, use_reloader=False, threaded=True)

	t = threading.Thread(target=_run, daemon=True)
	t.start()
	return t


def _wait_for_server(url: str, timeout: float = 10.0) -> bool:
	"""Poll url until it responds or timeout is reached. Returns True on success."""
	import urllib.request
	import urllib.error
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		try:
			urllib.request.urlopen(url, timeout=1)
			return True
		except Exception:
			time.sleep(0.2)
	return False


def _collect_views(app: Any, patterns: list[str]) -> list[dict[str, str]]:
	"""Return list of {name, endpoint, url} dicts for views matching any pattern."""
	appbuilder = getattr(app, "appbuilder", None)
	if appbuilder is None:
		click.echo(click.style("  No appbuilder instance found on current_app.", fg="red"))
		raise SystemExit(1)

	results: list[dict[str, str]] = []
	seen: set[str] = set()

	for view in appbuilder.baseviews:
		name = view.__class__.__name__
		endpoint = getattr(view, "endpoint", name)
		if endpoint in seen:
			continue
		# Apply glob patterns
		if not any(fnmatch.fnmatch(name, pat) for pat in patterns):
			continue
		seen.add(endpoint)
		# Attempt to build a URL for the default_view of the view
		default = getattr(view, "default_view", "list")
		try:
			from flask import url_for
			with app.app_context():
				url = url_for(f"{endpoint}.{default}")
		except Exception:
			url = f"/{endpoint}/{default}"
		results.append({"name": name, "endpoint": endpoint, "url": url})

	return results


def _login(page: "Page", base_url: str, username: str, password: str) -> None:
	"""Navigate to the FAB login page and authenticate."""
	login_url = f"{base_url}/login/"
	page.goto(login_url, wait_until="networkidle")

	# FAB login form field names
	username_sel = 'input[name="username"], #username'
	password_sel = 'input[name="password"], #password'

	page.fill(username_sel, username)
	page.fill(password_sel, password)
	page.click('input[type="submit"], button[type="submit"]')
	page.wait_for_load_state("networkidle")


def _screenshot_view(
	page: "Page",
	base_url: str,
	view_info: dict[str, str],
	output_dir: pathlib.Path,
	width: int,
	height: int,
) -> pathlib.Path:
	"""Navigate to a view and save a PNG. Returns the saved path."""
	url = f"{base_url}{view_info['url']}"
	page.set_viewport_size({"width": width, "height": height})
	page.goto(url, wait_until="networkidle")

	# Sanitise name for filesystem
	safe_name = view_info["name"].replace("/", "_").replace(" ", "_")
	out_path = output_dir / f"{safe_name}.png"
	page.screenshot(path=str(out_path), full_page=False)
	return out_path


def _run_screenshot_session(
	app: Any,
	view_infos: list[dict[str, str]],
	output_dir: pathlib.Path,
	base_url: str | None,
	username: str,
	password: str,
	width: int,
	height: int,
) -> list[pathlib.Path]:
	"""
	Core screenshot loop.

	If base_url is None, a temporary Flask server is started on a random port.
	Returns list of written PNG paths.
	"""
	_require_playwright()
	output_dir.mkdir(parents=True, exist_ok=True)

	# Decide server strategy
	if base_url is None:
		port = _free_port()
		_start_test_server(app, port)
		base_url = f"http://127.0.0.1:{port}"
		click.echo(f"  Starting test server on {base_url} …")
		if not _wait_for_server(base_url, timeout=15):
			click.echo(click.style("  Server did not start in time.", fg="red"))
			raise SystemExit(1)
		click.echo(click.style("  Server ready.", fg="green"))
	else:
		click.echo(f"  Using existing server at {base_url}")

	saved: list[pathlib.Path] = []

	with sync_playwright() as pw:
		browser: Browser = pw.chromium.launch(headless=True)
		context = browser.new_context(
			viewport={"width": width, "height": height},
			ignore_https_errors=True,
		)
		page: Page = context.new_page()

		click.echo(f"  Logging in as '{username}' …")
		try:
			_login(page, base_url, username, password)
		except Exception as exc:
			click.echo(click.style(f"  Login failed: {exc}", fg="red"))
			browser.close()
			raise SystemExit(1)
		click.echo(click.style("  Logged in.", fg="green"))

		for vi in view_infos:
			try:
				path = _screenshot_view(page, base_url, vi, output_dir, width, height)
				saved.append(path)
				click.echo(
					f"  {click.style('✓', fg='green')} "
					f"{vi['name']:<40} → {path.name}"
				)
			except Exception as exc:
				click.echo(
					f"  {click.style('✗', fg='red')} "
					f"{vi['name']:<40}   {exc}"
				)

		browser.close()

	return saved


# ---------------------------------------------------------------------------
# 'screenshot' command group
# ---------------------------------------------------------------------------

@click.group("screenshot", invoke_without_command=True)
@click.pass_context
def screenshot_group(ctx: click.Context) -> None:
	"""Screenshot FAB views using a headless Chromium browser (via Playwright).

	Sub-commands: all, view, list, diff
	"""
	if ctx.invoked_subcommand is None:
		click.echo(ctx.get_help())


# ---------------------------------------------------------------------------
# screenshot all
# ---------------------------------------------------------------------------

@screenshot_group.command("all")
@click.option(
	"--output-dir", "-o",
	default=None,
	help="Directory to write PNGs into (default: screenshots/).",
)
@click.option("--width", default=None, type=int, help="Viewport width in pixels.")
@click.option("--height", default=None, type=int, help="Viewport height in pixels.")
@click.option("--user", default=None, help="Admin username.")
@click.option("--password", "pwd", default=None, help="Admin password.")
@click.option(
	"--base-url",
	default=None,
	help="Use an already-running server instead of starting one.",
)
@click.option(
	"--views",
	default=None,
	help="Comma-separated glob patterns to restrict which views are captured (default: *).",
)
@with_appcontext
def screenshot_all(
	output_dir: str | None,
	width: int | None,
	height: int | None,
	user: str | None,
	pwd: str | None,
	base_url: str | None,
	views: str | None,
) -> None:
	"""Screenshot every registered FAB view.

	\b
	Examples:
	  flask fab screenshot all
	  flask fab screenshot all --output-dir shots/ --width 1440 --height 900
	  flask fab screenshot all --views "Employee*,Department*"
	"""
	_require_playwright()
	cfg = _load_yml_config()

	out = pathlib.Path(output_dir or cfg.get("output_dir", "screenshots"))
	w = width or cfg.get("width", _DEFAULT_WIDTH)
	h = height or cfg.get("height", _DEFAULT_HEIGHT)
	u = user or cfg.get("username", _DEFAULT_USER)
	p = pwd or cfg.get("password", _DEFAULT_PASS)
	url = base_url or cfg.get("base_url", None)

	raw_patterns = views or ",".join(cfg.get("views", ["*"]))
	patterns = [pat.strip() for pat in raw_patterns.split(",") if pat.strip()]

	_header("Flask-AppBuilder — Screenshot All Views")
	click.echo(f"  Output dir : {out}")
	click.echo(f"  Viewport   : {w}×{h}")
	click.echo(f"  Patterns   : {patterns}")
	click.echo("")

	app = current_app._get_current_object()  # type: ignore[attr-defined]
	view_infos = _collect_views(app, patterns)

	if not view_infos:
		click.echo(click.style("  No matching views found.", fg="yellow"))
		raise SystemExit(0)

	click.echo(f"  Found {len(view_infos)} view(s).\n")

	saved = _run_screenshot_session(app, view_infos, out, url, u, p, w, h)

	click.echo("")
	click.echo(click.style(_hr("═"), fg="green"))
	click.echo(
		click.style(
			f"  Done. {len(saved)}/{len(view_infos)} screenshot(s) saved to {out}/",
			fg="green",
			bold=True,
		)
	)
	click.echo(click.style(_hr("═"), fg="green"))
	click.echo("")


# ---------------------------------------------------------------------------
# screenshot view
# ---------------------------------------------------------------------------

@screenshot_group.command("view")
@click.argument("view_name")
@click.option("--output-dir", "-o", default=None, help="Output directory.")
@click.option("--width", default=None, type=int, help="Viewport width in pixels.")
@click.option("--height", default=None, type=int, help="Viewport height in pixels.")
@click.option("--user", default=None, help="Admin username.")
@click.option("--password", "pwd", default=None, help="Admin password.")
@click.option("--base-url", default=None, help="Use an already-running server.")
@with_appcontext
def screenshot_view(
	view_name: str,
	output_dir: str | None,
	width: int | None,
	height: int | None,
	user: str | None,
	pwd: str | None,
	base_url: str | None,
) -> None:
	"""Screenshot a single FAB view by name (glob pattern supported).

	VIEW_NAME supports glob syntax, e.g. "Employee*".

	\b
	Examples:
	  flask fab screenshot view EmployeeModelView
	  flask fab screenshot view "Employee*" --output-dir shots/
	"""
	_require_playwright()
	cfg = _load_yml_config()

	out = pathlib.Path(output_dir or cfg.get("output_dir", "screenshots"))
	w = width or cfg.get("width", _DEFAULT_WIDTH)
	h = height or cfg.get("height", _DEFAULT_HEIGHT)
	u = user or cfg.get("username", _DEFAULT_USER)
	p = pwd or cfg.get("password", _DEFAULT_PASS)
	url = base_url or cfg.get("base_url", None)

	_header(f"Flask-AppBuilder — Screenshot View: {view_name}")

	app = current_app._get_current_object()  # type: ignore[attr-defined]
	view_infos = _collect_views(app, [view_name])

	if not view_infos:
		click.echo(click.style(f"  No view matching '{view_name}' found.", fg="yellow"))
		click.echo("  Run 'flask fab screenshot list' to see available views.")
		raise SystemExit(1)

	click.echo(f"  Matched {len(view_infos)} view(s).\n")

	saved = _run_screenshot_session(app, view_infos, out, url, u, p, w, h)

	click.echo("")
	click.echo(
		click.style(
			f"  {len(saved)} screenshot(s) saved to {out}/",
			fg="green",
			bold=True,
		)
	)
	click.echo("")


# ---------------------------------------------------------------------------
# screenshot list
# ---------------------------------------------------------------------------

@screenshot_group.command("list")
@click.option(
	"--pattern",
	default="*",
	show_default=True,
	help="Glob pattern to filter view names.",
)
@with_appcontext
def screenshot_list(pattern: str) -> None:
	"""List all FAB views that can be screenshotted.

	\b
	Examples:
	  flask fab screenshot list
	  flask fab screenshot list --pattern "Employee*"
	"""
	_header("Flask-AppBuilder — Registered Views")

	app = current_app._get_current_object()  # type: ignore[attr-defined]
	view_infos = _collect_views(app, [pattern])

	if not view_infos:
		click.echo(click.style(f"  No views match pattern '{pattern}'.", fg="yellow"))
		raise SystemExit(0)

	click.echo(
		f"  {'View Name':<45} {'Endpoint':<35} URL"
	)
	click.echo(click.style("  " + _hr("─"), fg="white", dim=True))

	for vi in sorted(view_infos, key=lambda v: v["name"]):
		click.echo(
			f"  {click.style(vi['name'], fg='green'):<54}"
			f"  {vi['endpoint']:<35}"
			f"  {vi['url']}"
		)

	click.echo("")
	click.echo(
		click.style(
			f"  {len(view_infos)} view(s) found. "
			"Use 'flask fab screenshot all' to capture them.",
			fg="white",
			dim=True,
		)
	)
	click.echo("")


# ---------------------------------------------------------------------------
# screenshot diff
# ---------------------------------------------------------------------------

@screenshot_group.command("diff")
@click.argument("old_dir", type=click.Path(exists=True, file_okay=False))
@click.argument("new_dir", type=click.Path(exists=True, file_okay=False))
@click.option(
	"--threshold",
	default=0,
	show_default=True,
	type=int,
	help="Pixel-diff count above which a file is flagged as changed.",
)
@click.option(
	"--output-dir",
	"-o",
	default=None,
	help="Optional directory to save diff images (highlighted differences).",
)
def screenshot_diff(
	old_dir: str,
	new_dir: str,
	threshold: int,
	output_dir: str | None,
) -> None:
	"""Compare two directories of screenshots and report pixel differences.

	Outputs a summary table showing the pixel-diff count per PNG file.
	Files only present in one directory are flagged as ADDED / REMOVED.

	\b
	Examples:
	  flask fab screenshot diff screenshots/v1 screenshots/v2
	  flask fab screenshot diff before/ after/ --threshold 100 --output-dir diffs/
	"""
	_require_pillow()

	old_path = pathlib.Path(old_dir)
	new_path = pathlib.Path(new_dir)
	diff_out: pathlib.Path | None = pathlib.Path(output_dir) if output_dir else None
	if diff_out:
		diff_out.mkdir(parents=True, exist_ok=True)

	_header(f"Screenshot Diff: {old_dir}  vs  {new_dir}")

	old_pngs = {p.name for p in old_path.glob("*.png")}
	new_pngs = {p.name for p in new_path.glob("*.png")}
	all_names = sorted(old_pngs | new_pngs)

	if not all_names:
		click.echo(click.style("  No PNG files found in either directory.", fg="yellow"))
		raise SystemExit(0)

	# Column widths
	col_file = 45
	col_status = 10
	col_diff = 14

	click.echo(
		f"  {'File':<{col_file}} {'Status':<{col_status}} {'Pixel diff':>{col_diff}}"
	)
	click.echo(click.style("  " + _hr("─"), fg="white", dim=True))

	total_changed = 0
	total_added = 0
	total_removed = 0
	rows: list[tuple[str, str, int | None]] = []

	for name in all_names:
		in_old = name in old_pngs
		in_new = name in new_pngs

		if in_old and not in_new:
			rows.append((name, "REMOVED", None))
			total_removed += 1
			continue
		if in_new and not in_old:
			rows.append((name, "ADDED", None))
			total_added += 1
			continue

		# Both present — compute pixel diff
		try:
			img_old = Image.open(old_path / name).convert("RGB")
			img_new = Image.open(new_path / name).convert("RGB")

			# Resize new to old dimensions if they differ
			if img_old.size != img_new.size:
				img_new = img_new.resize(img_old.size, Image.LANCZOS)

			diff_img = ImageChops.difference(img_old, img_new)
			pixel_diff = sum(
				1
				for px in diff_img.getdata()
				if any(ch > 0 for ch in px)
			)

			if diff_out and pixel_diff > threshold:
				# Save an amplified diff image (each channel ×10 for visibility)
				import PIL.ImageEnhance as _Enh
				enhanced = _Enh.Contrast(diff_img).enhance(10)
				enhanced.save(diff_out / name)

			rows.append((name, "CHANGED" if pixel_diff > threshold else "same", pixel_diff))
			if pixel_diff > threshold:
				total_changed += 1

		except Exception as exc:
			rows.append((name, "ERROR", None))
			logger.debug("Diff error for %s: %s", name, exc)

	# Print table
	for name, status, diff_count in rows:
		if status == "REMOVED":
			colour = "red"
			diff_str = "—"
		elif status == "ADDED":
			colour = "blue"
			diff_str = "—"
		elif status == "ERROR":
			colour = "yellow"
			diff_str = "err"
		elif status == "CHANGED":
			colour = "red"
			diff_str = f"{diff_count:,}"
		else:
			colour = "green"
			diff_str = f"{diff_count:,}" if diff_count is not None else "0"

		click.echo(
			f"  {name:<{col_file}} "
			f"{click.style(status, fg=colour):<{col_status + 9}} "  # +9 for ANSI codes
			f"{diff_str:>{col_diff}}"
		)

	click.echo("")
	click.echo(click.style("  " + _hr("─"), fg="white", dim=True))
	click.echo(
		f"  Total files: {len(all_names)}  "
		f"{click.style(f'changed: {total_changed}', fg='red' if total_changed else 'white')}  "
		f"{click.style(f'added: {total_added}', fg='blue' if total_added else 'white')}  "
		f"{click.style(f'removed: {total_removed}', fg='red' if total_removed else 'white')}"
	)
	if diff_out and (total_changed > 0):
		click.echo(
			click.style(f"  Diff images saved to: {diff_out}/", fg="cyan")
		)
	click.echo("")

	if total_changed or total_removed or total_added:
		raise SystemExit(1)
