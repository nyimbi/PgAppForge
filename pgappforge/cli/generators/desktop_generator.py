"""
Desktop App Generator for PgAppForge

Generates a native desktop wrapper that opens the deployed web application in a
native OS window. The desktop app connects to a remote backend URL — it does NOT
embed or run a local Flask server. This mirrors how Slack, Notion, Linear, and
most modern "desktop apps" work: they wrap the web app in a native container.

Two generation targets:

  pywebview  — system WebView, ~10 MB binary.
               Minimal overhead, looks identical to the browser.
               Supports native dialogs, file picker, and system tray via JS bridge.

  pyside6    — Qt WebEngine, ~150 MB binary.
               Use when you need native print dialogs, global keyboard shortcuts,
               full system tray menus, or direct Qt API access.

Produces:
  run_desktop.py              pywebview entry point
  run_desktop_qt.py           PySide6 entry point (optional)
  desktop.config.json         Default config (API URL, window size)
  requirements-desktop.txt    Runtime deps for chosen target
  desktop/app.spec            PyInstaller spec (pywebview)
  desktop/app_qt.spec         PyInstaller spec (pyside6)
  desktop/Makefile            build / run / dist targets
  desktop/README.md           Usage guide
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DesktopConfig:
	app_name: str
	app_id: str = ""                  # com.company.myapp
	version: str = "0.1.0"
	api_url: str = "https://app.example.com"  # remote backend URL
	window_width: int = 1280
	window_height: int = 800
	min_width: int = 800
	min_height: int = 600
	icon_path: str = ""               # .ico / .icns / .png
	target: str = "pywebview"         # "pywebview" | "pyside6" | "both"

	def __post_init__(self):
		if not self.app_id:
			slug = self.app_name.lower().replace(" ", "").replace("-", "")
			self.app_id = f"com.pgappforge.{slug}"


class DesktopGenerator:
	"""Generates native desktop wrapper files for a pgappforge web application."""

	def __init__(self, config: DesktopConfig, output_dir: str | Path):
		self.config = config
		self.output_dir = Path(output_dir)

	# ── Public API ────────────────────────────────────────────────────────────

	def generate(self) -> dict[str, str]:
		"""Return {relative_path: content} for all generated files."""
		c = self.config
		files: dict[str, str] = {}

		if c.target in ("pywebview", "both"):
			files["run_desktop.py"] = self._pywebview_entry()
			files["desktop/app.spec"] = self._pyinstaller_spec_webview()

		if c.target in ("pyside6", "both"):
			files["run_desktop_qt.py"] = self._pyside6_entry()
			files["desktop/app_qt.spec"] = self._pyinstaller_spec_qt()

		files["desktop.config.json"] = self._config_json()
		files["requirements-desktop.txt"] = self._requirements()
		files["desktop/Makefile"] = self._makefile()
		files["desktop/README.md"] = self._readme()

		# Top-level README and scripts for first-time users
		files["README.md"] = self._gen_toplevel_readme()
		files["scripts/setup_desktop.sh"] = self._gen_setup_script()
		files["scripts/run_desktop.sh"] = self._gen_run_script()

		self._write_files(files)
		# Make scripts executable
		import os
		for script in ["scripts/setup_desktop.sh", "scripts/run_desktop.sh"]:
			path = self.output_dir / script
			if path.exists():
				path.chmod(path.stat().st_mode | 0o755)
		logger.info("Desktop files generated in %s (%d files)", self.output_dir, len(files))
		return files

	# ── pywebview entry point ─────────────────────────────────────────────────

	def _pywebview_entry(self) -> str:
		c = self.config
		icon_kwarg = f', icon="{c.icon_path}"' if c.icon_path else ""
		# Use concatenation for template to avoid f-string brace collisions
		return (
			'#!/usr/bin/env python3\n'
			'"""\n'
			+ c.app_name + ' — desktop wrapper (pywebview)\n'
			'\n'
			'Opens the remote web application in a native OS window.\n'
			'The backend URL is read from desktop.config.json or the\n'
			'PGAF_DESKTOP_URL environment variable.\n'
			'\n'
			'Usage:\n'
			'    python run_desktop.py\n'
			'    python run_desktop.py --debug          # open DevTools\n'
			'    python run_desktop.py --url https://...  # override URL\n'
			'    dist/' + c.app_name + '               # packaged binary\n'
			'"""\n'
			'import json\n'
			'import os\n'
			'import sys\n'
			'from pathlib import Path\n'
			'import webview\n'
			'\n'
			'APP_NAME = ' + repr(c.app_name) + '\n'
			'DEFAULT_CONFIG = Path(__file__).parent / "desktop.config.json"\n'
			'\n'
			'\n'
			'def load_url() -> str:\n'
			'    """Read the backend URL from env → config file → fallback."""\n'
			'    if env := os.environ.get("PGAF_DESKTOP_URL"):\n'
			'        return env\n'
			'    if DEFAULT_CONFIG.exists():\n'
			'        cfg = json.loads(DEFAULT_CONFIG.read_text())\n'
			'        if url := cfg.get("api_url"):\n'
			'            return url\n'
			'    return ' + repr(c.api_url) + '\n'
			'\n'
			'\n'
			'def main() -> None:\n'
			'    debug = "--debug" in sys.argv\n'
			'    url = next((a for a in sys.argv if a.startswith("--url=")), None)\n'
			'    backend_url = url.split("=", 1)[1] if url else load_url()\n'
			'\n'
			'    window = webview.create_window(\n'
			'        title=APP_NAME,\n'
			'        url=backend_url,\n'
			'        width=' + str(c.window_width) + ',\n'
			'        height=' + str(c.window_height) + ',\n'
			'        min_size=(' + str(c.min_width) + ', ' + str(c.min_height) + '),\n'
			'        resizable=True,\n'
			'        text_select=True' + icon_kwarg + ',\n'
			'    )\n'
			'    webview.start(debug=debug)\n'
			'\n'
			'\n'
			'if __name__ == "__main__":\n'
			'    main()\n'
		)

	# ── PySide6 entry point ───────────────────────────────────────────────────

	def _pyside6_entry(self) -> str:
		c = self.config
		icon_block = (
			f'\n        self.setWindowIcon(QIcon("{c.icon_path}"))'
			if c.icon_path else ""
		)
		return (
			'#!/usr/bin/env python3\n'
			'"""\n'
			+ c.app_name + ' — desktop wrapper (PySide6 + QtWebEngine)\n'
			'\n'
			'Richer native integration: native print dialog, full system tray,\n'
			'global keyboard shortcuts, and direct Qt API access.\n'
			'\n'
			'Usage:\n'
			'    python run_desktop_qt.py\n'
			'    PGAF_DESKTOP_URL=https://... python run_desktop_qt.py\n'
			'"""\n'
			'import json\n'
			'import os\n'
			'import sys\n'
			'from pathlib import Path\n'
			'from PySide6.QtWidgets import QApplication, QMainWindow, QStatusBar\n'
			'from PySide6.QtWebEngineWidgets import QWebEngineView\n'
			'from PySide6.QtCore import QUrl\n'
			'from PySide6.QtGui import QIcon\n'
			'\n'
			'APP_NAME = ' + repr(c.app_name) + '\n'
			'APP_VERSION = ' + repr(c.version) + '\n'
			'DEFAULT_CONFIG = Path(__file__).parent / "desktop.config.json"\n'
			'\n'
			'\n'
			'def load_url() -> str:\n'
			'    if env := os.environ.get("PGAF_DESKTOP_URL"):\n'
			'        return env\n'
			'    if DEFAULT_CONFIG.exists():\n'
			'        cfg = json.loads(DEFAULT_CONFIG.read_text())\n'
			'        if url := cfg.get("api_url"):\n'
			'            return url\n'
			'    return ' + repr(c.api_url) + '\n'
			'\n'
			'\n'
			'class MainWindow(QMainWindow):\n'
			'    def __init__(self, url: str):\n'
			'        super().__init__()\n'
			'        self.setWindowTitle(APP_NAME)\n'
			'        self.resize(' + str(c.window_width) + ', ' + str(c.window_height) + ')\n'
			'        self.setMinimumSize(' + str(c.min_width) + ', ' + str(c.min_height) + ')'
			+ icon_block + '\n'
			'\n'
			'        self.browser = QWebEngineView()\n'
			'        self.browser.setUrl(QUrl(url))\n'
			'        self.setCentralWidget(self.browser)\n'
			'\n'
			'        status = QStatusBar()\n'
			'        self.setStatusBar(status)\n'
			'        self.browser.titleChanged.connect(lambda t: status.showMessage(t, 3000))\n'
			'\n'
			'    def closeEvent(self, event):\n'
			'        self.browser.setUrl(QUrl("about:blank"))\n'
			'        super().closeEvent(event)\n'
			'\n'
			'\n'
			'def main() -> None:\n'
			'    url = load_url()\n'
			'    app = QApplication(sys.argv)\n'
			'    app.setApplicationName(APP_NAME)\n'
			'    app.setApplicationVersion(APP_VERSION)\n'
			'    window = MainWindow(url)\n'
			'    window.show()\n'
			'    sys.exit(app.exec())\n'
			'\n'
			'\n'
			'if __name__ == "__main__":\n'
			'    main()\n'
		)

	# ── Config JSON ──────────────────────────────────────────────────────────

	def _config_json(self) -> str:
		c = self.config
		return json.dumps({
			"app_name": c.app_name,
			"api_url": c.api_url,
			"window": {
				"width": c.window_width,
				"height": c.window_height,
				"min_width": c.min_width,
				"min_height": c.min_height,
			},
		}, indent=2) + "\n"

	# ── PyInstaller specs ─────────────────────────────────────────────────────

	def _pyinstaller_spec_webview(self) -> str:
		c = self.config
		icon_arg = f'\n    icon="{c.icon_path}",' if c.icon_path else ""
		return (
			'# desktop/app.spec — PyInstaller spec for pywebview desktop target\n'
			'# Run from project root:  pyinstaller desktop/app.spec\n'
			'import sys\n'
			'from pathlib import Path\n'
			'block_cipher = None\n'
			'root = Path(SPECPATH).parent\n'
			'\n'
			'a = Analysis(\n'
			'    [str(root / "run_desktop.py")],\n'
			'    pathex=[str(root)],\n'
			'    binaries=[],\n'
			'    datas=[(str(root / "desktop.config.json"), ".")],\n'
			'    hiddenimports=["webview", "webview.platforms"],\n'
			'    hookspath=[], runtime_hooks=[],\n'
			'    excludes=["tkinter", "PySide6", "PyQt5"],\n'
			'    cipher=block_cipher,\n'
			')\n'
			'pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)\n'
			'exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas,\n'
			'    name=' + repr(c.app_name) + ',\n'
			'    debug=False, strip=False, upx=True, console=False,' + icon_arg + '\n'
			')\n'
			'if sys.platform == "darwin":\n'
			'    app = BUNDLE(exe,\n'
			'        name=' + repr(c.app_name + ".app") + ',\n'
			'        bundle_identifier=' + repr(c.app_id) + ',\n'
			'        info_plist={"CFBundleShortVersionString": ' + repr(c.version) + ',\n'
			'                    "NSHighResolutionCapable": True},\n'
			'    )\n'
		)

	def _pyinstaller_spec_qt(self) -> str:
		c = self.config
		icon_arg = f'\n    icon="{c.icon_path}",' if c.icon_path else ""
		return (
			'# desktop/app_qt.spec — PyInstaller spec for PySide6 desktop target\n'
			'import sys\n'
			'from pathlib import Path\n'
			'block_cipher = None\n'
			'root = Path(SPECPATH).parent\n'
			'\n'
			'a = Analysis(\n'
			'    [str(root / "run_desktop_qt.py")],\n'
			'    pathex=[str(root)],\n'
			'    binaries=[],\n'
			'    datas=[(str(root / "desktop.config.json"), ".")],\n'
			'    hiddenimports=["PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore"],\n'
			'    hookspath=[], runtime_hooks=[],\n'
			'    excludes=["tkinter", "webview", "PyQt5"],\n'
			'    cipher=block_cipher,\n'
			')\n'
			'pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)\n'
			'exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas,\n'
			'    name=' + repr(c.app_name + "_qt") + ',\n'
			'    debug=False, strip=False, upx=True, console=False,' + icon_arg + '\n'
			')\n'
			'if sys.platform == "darwin":\n'
			'    app = BUNDLE(exe,\n'
			'        name=' + repr(c.app_name + ".app") + ',\n'
			'        bundle_identifier=' + repr(c.app_id) + ',\n'
			'        info_plist={"CFBundleShortVersionString": ' + repr(c.version) + ',\n'
			'                    "NSHighResolutionCapable": True},\n'
			'    )\n'
		)

	# ── requirements ─────────────────────────────────────────────────────────

	def _requirements(self) -> str:
		c = self.config
		lines = ["# Desktop packaging\n", "pyinstaller>=6.0\n"]
		if c.target in ("pywebview", "both"):
			lines += ["\n# pywebview (system WebView wrapper — ~10 MB binary)\n", "pywebview>=5.0\n"]
		if c.target in ("pyside6", "both"):
			lines += [
				"\n# PySide6 (Qt WebEngine — ~150 MB binary, richer native APIs)\n",
				"PySide6>=6.6\n",
				"PySide6-WebEngine>=6.6\n",
			]
		return "".join(lines)

	# ── Makefile ──────────────────────────────────────────────────────────────

	def _makefile(self) -> str:
		c = self.config
		has_webview = c.target in ("pywebview", "both")
		has_qt = c.target in ("pyside6", "both")
		lines = ["# desktop/Makefile\n\n"]
		if has_webview:
			lines += [
				"run:\n",
				"\tpython ../run_desktop.py\n\n",
				"dist:\n",
				"\tcd .. && pyinstaller desktop/app.spec --noconfirm\n",
				f"\t@echo '✓ Binary → dist/{c.app_name}'\n\n",
			]
		if has_qt:
			lines += [
				"run-qt:\n",
				"\tpython ../run_desktop_qt.py\n\n",
				"dist-qt:\n",
				"\tcd .. && pyinstaller desktop/app_qt.spec --noconfirm\n",
				f"\t@echo '✓ Binary → dist/{c.app_name}_qt'\n\n",
			]
		return "".join(lines)

	# ── README ────────────────────────────────────────────────────────────────

	def _readme(self) -> str:
		c = self.config
		has_webview = c.target in ("pywebview", "both")
		has_qt = c.target in ("pyside6", "both")
		parts = [
			f"# {c.app_name} — Desktop\n\n",
			"The desktop app connects to your **remote backend** at the URL configured\n",
			"in `desktop.config.json` or the `PGAF_DESKTOP_URL` environment variable.\n",
			"No local server is started.\n\n",
			f"## Configuration\n\nEdit `desktop.config.json` and set `api_url` to your deployed backend:\n\n",
			"```json\n",
			f'{{\n  "api_url": "https://app.yourdomain.com"\n}}\n',
			"```\n\nOr pass at runtime:\n\n",
			"```bash\nPGAF_DESKTOP_URL=https://staging.yourdomain.com python run_desktop.py\n```\n\n",
		]
		if has_webview:
			parts += [
				"## pywebview (recommended, ~10 MB)\n\n",
				"```bash\npip install pywebview\npython run_desktop.py\n\n",
				"# Package\npip install pyinstaller && make -C desktop dist\n```\n\n",
			]
		if has_qt:
			parts += [
				"## PySide6 + QtWebEngine (~150 MB)\n\n",
				"```bash\npip install PySide6 PySide6-WebEngine\npython run_desktop_qt.py\n\n",
				"# Package\nmake -C desktop dist-qt\n```\n\n",
			]
		parts += [
			"## Distribution\n\n",
			"| Platform | Output |\n|----------|--------|\n",
			f"| macOS | `dist/{c.app_name}.app` |\n",
			f"| Windows | `dist/{c.app_name}.exe` |\n",
			f"| Linux | `dist/{c.app_name}` |\n",
		]
		return "".join(parts)

	# ── file writer ───────────────────────────────────────────────────────────

	def _gen_toplevel_readme(self) -> str:
		c = self.config
		has_webview = c.target in ("pywebview", "both")
		has_qt = c.target in ("pyside6", "both")
		return (
			f"# {c.app_name} — Desktop\n\n"
			f"Native desktop app that opens the **{c.app_name}** web application in a native window.\n"
			"The backend runs on your server — this app is just the native shell.\n\n"
			"## Quick start\n\n"
			"```bash\n"
			"./scripts/setup_desktop.sh    # install Python deps\n"
			"./scripts/run_desktop.sh      # launch the app\n"
			"```\n\n"
			"## Prerequisites\n\n"
			"- Python 3.9+\n"
			"- The pgappforge web backend deployed and accessible\n\n"
			"## Configuration\n\n"
			"Edit `desktop.config.json` and set your backend URL:\n\n"
			"```json\n"
			f'{{\n  "api_url": "https://your-backend.example.com"\n}}\n'
			"```\n\n"
			"Or override at runtime:\n\n"
			"```bash\n"
			f"PGAF_DESKTOP_URL=https://staging.example.com python run_desktop.py\n"
			"```\n\n"
			"## Running\n\n"
			+ (f"```bash\npython run_desktop.py              # pywebview (~10MB binary)\n```\n\n" if has_webview else "")
			+ (f"```bash\npython run_desktop_qt.py            # PySide6 (richer native APIs)\n```\n\n" if has_qt else "")
			+ "## Packaging as a native binary\n\n"
			"```bash\npip install pyinstaller\nmake -C desktop dist\n# Produces: dist/"
			+ c.app_name
			+ " (macOS/Linux) or dist/"
			+ c.app_name
			+ ".exe (Windows)\n```\n\n"
			"---\n*Generated by pgappforge.*\n"
		)

	def _gen_setup_script(self) -> str:
		c = self.config
		has_webview = c.target in ("pywebview", "both")
		has_qt = c.target in ("pyside6", "both")
		deps = []
		if has_webview:
			deps.append("pywebview")
		if has_qt:
			deps.extend(["PySide6", "PySide6-WebEngine"])
		return (
			"#!/usr/bin/env bash\n"
			f"# setup_desktop.sh — install dependencies for {c.app_name} desktop wrapper\n"
			"set -euo pipefail\n\n"
			"echo '▶  Setting up desktop dependencies...'\n\n"
			"# Check Python\n"
			"if ! command -v python3 &>/dev/null; then\n"
			"  echo '✗  Python 3 not found. Install from https://python.org' && exit 1\n"
			"fi\n"
			"echo \"   Python $(python3 --version) ✓\"\n\n"
			"# Install deps\n"
			f"python3 -m pip install --user {' '.join(deps)}\n"
			"echo '   Dependencies installed ✓'\n\n"
			"echo ''\n"
			"echo '✓  Setup complete!'\n"
			"echo '   Edit desktop.config.json to set your backend URL'\n"
			"echo '   Then run: ./scripts/run_desktop.sh'\n"
		)

	def _gen_run_script(self) -> str:
		c = self.config
		has_both = c.target == "both"
		primary = "run_desktop.py" if c.target in ("pywebview", "both") else "run_desktop_qt.py"
		both_block = (
			'if [ "${1:-}" = "--qt" ]; then\n'
			f'  shift; exec python3 run_desktop_qt.py "$@"\n'
			'fi\n'
		) if has_both else ""
		return (
			"#!/usr/bin/env bash\n"
			f"# run_desktop.sh — launch {c.app_name}\n"
			"set -euo pipefail\n"
			'cd "$(dirname "$0")/.."' + "\n\n"
			"# Check desktop.config.json exists\n"
			"if [ ! -f desktop.config.json ]; then\n"
			"  echo '✗  desktop.config.json not found. Run setup first.' && exit 1\n"
			"fi\n\n"
			+ both_block
			+ f"echo '▶  Launching {c.app_name}...'\n"
			f"exec python3 {primary} \"$@\"\n"
		)

	def _write_files(self, files: dict[str, str]) -> None:
		for rel_path, content in files.items():
			abs_path = self.output_dir / rel_path
			abs_path.parent.mkdir(parents=True, exist_ok=True)
			abs_path.write_text(content, encoding="utf-8")
