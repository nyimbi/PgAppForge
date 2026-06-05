# Tutorial 12: Generating and Running a Desktop App

`flask forge gen desktop` produces a cross-platform Electron application that wraps your pgappforge Flask backend. The same `ModelView` CRUD screens you get in the browser appear in a native window on macOS, Windows, and Linux — with a native menu bar, system tray icon, and the ability to run fully offline.

## Prerequisites

- pgappforge installed: `pip install pgappforge`
- Node.js 20+ and npm
- A PostgreSQL database (this tutorial uses the `employees` example from Tutorial 01)

---

## Step 1 — What the desktop generator produces

The generator introspects your database, generates the Flask app as normal, then wraps it in an Electron shell. You get one directory containing both the Python backend and the Electron frontend — packaged together for distribution as a single installer.

Key characteristics:

- **Same views as the web app** — `ModelView` CRUD, REST API, security, all plugins work identically
- **Embedded Flask server** — Electron spawns a child process running gunicorn on `localhost:5000`; the renderer loads `http://localhost:5000`
- **Native OS integration** — menu bar, system tray, OS file dialogs, notifications
- **Offline-capable** — SQLite fallback when PostgreSQL is unreachable; syncs on reconnect
- **Cross-platform** — one codebase, three installers (`.dmg`, `.exe`, `.AppImage`)

---

## Step 2 — Generate the desktop app

```bash
flask forge gen desktop postgresql://localhost/employees \
  --name MyDesktopApp \
  --output-dir ./mydesktopapp/
```

The generator introspects the database, generates the Flask app into `app/`, then writes the Electron wrapper alongside it:

```
Introspecting postgresql://localhost/employees ...
  Found 8 tables, 63 columns, 12 foreign keys
Generating Flask app → ./mydesktopapp/app/
  ✓ app/models.py
  ✓ app/views.py
  ✓ app/config.py
  ✓ app/run.py
Generating Electron wrapper → ./mydesktopapp/
  ✓ package.json          (electron-builder config, scripts, dependencies)
  ✓ main.js               (Electron entry point — spawns Flask, manages windows)
  ✓ preload.js            (context bridge — exposes safe IPC channels to renderer)
  ✓ renderer/             (HTML shell loaded in the BrowserWindow)
  ✓ assets/               (app icon in .icns / .ico / .png formats)
Generation complete!
  cd mydesktopapp && npm install && npm run dev
```

**`main.js`** is the Electron entry point. It:
1. Spawns the Flask/gunicorn process as a child process
2. Waits for `/health` to return 200 before opening the `BrowserWindow`
3. Loads `http://localhost:5000` in the window
4. Terminates the Flask process when the window closes

**`preload.js`** exposes a minimal IPC bridge (`contextBridge.exposeInMainWorld`) so renderer code can trigger native actions (open file dialog, show notification) without full Node.js access.

**`app/`** is a standard pgappforge app. You can edit it exactly as you would any generated web app.

---

## Step 3 — Running in development

```bash
cd mydesktopapp
npm install          # installs electron, electron-builder, and dev tooling
npm run dev          # starts Flask on :5000, then opens the Electron window
```

`npm run dev` runs two processes concurrently:
- `python app/run.py` — Flask development server with auto-reload
- `electron .` — Electron, which waits for the Flask health check before showing the window

Changes to Python files are picked up by Flask's reloader. Changes to `main.js` or `preload.js` require restarting `npm run dev`.

To open Chrome DevTools inside the Electron window, use the **View → Toggle Developer Tools** menu item, or press `Cmd+Option+I` (macOS) / `Ctrl+Shift+I` (Windows/Linux).

---

## Step 4 — The UI

The browser window shows the same pgappforge interface you would see in a web browser: the sidebar navigation, model list/detail/form views, charts, and any plugins you have enabled. A few additions appear in the desktop version:

**Menu bar** (macOS native / custom on Windows/Linux):

| Menu | Items |
|---|---|
| File | New Record, Open Database, Close Window, Quit |
| Edit | Undo, Redo, Cut, Copy, Paste, Select All |
| View | Reload, Force Reload, Toggle Developer Tools, Actual Size, Zoom In, Zoom Out, Toggle Full Screen |
| Help | About MyDesktopApp, Check for Updates |

**Title bar**: displays the app name and current view title.

**System tray icon**: right-click menu with Show/Hide window and Quit. The app continues running in the tray when the window is closed.

---

## Step 5 — Packaging for distribution

```bash
npm run build            # packages for the current platform
npm run build:mac        # .dmg installer for macOS (arm64 + x64 universal)
npm run build:win        # .exe NSIS installer for Windows x64
npm run build:linux      # .AppImage for Linux x64
```

`electron-builder` reads packaging configuration from `package.json`:

```json
{
  "build": {
    "appId": "com.example.mydesktopapp",
    "productName": "MyDesktopApp",
    "directories": { "output": "dist" },
    "files": ["main.js", "preload.js", "renderer/**", "app/**"],
    "extraResources": [{ "from": "app/", "to": "app/" }],
    "mac":   { "category": "public.app-category.business", "target": "dmg" },
    "win":   { "target": "nsis" },
    "linux": { "target": "AppImage", "category": "Office" }
  }
}
```

The Flask app and its Python dependencies are bundled using PyInstaller (called automatically by the `build` script) and placed in `resources/app/`. End users do not need Python installed.

Built installers appear in `dist/`:

```
dist/
├── MyDesktopApp-1.0.0.dmg          # macOS
├── MyDesktopApp-Setup-1.0.0.exe    # Windows
└── MyDesktopApp-1.0.0.AppImage     # Linux
```

---

## Step 6 — Auto-updating

The generated app includes `electron-updater`. When a new release is published to GitHub Releases (or your own update server), the app checks for updates on startup and prompts the user to install.

Configure the update server URL in `package.json`:

```json
{
  "build": {
    "publish": {
      "provider": "github",
      "owner": "myorg",
      "repo": "mydesktopapp"
    }
  }
}
```

For a self-hosted update server, use `provider: "generic"` and set `url` to the directory where you publish release artifacts. `electron-updater` fetches `latest.yml` / `latest-mac.yml` from that URL to determine whether an update is available.

To publish a new release:

```bash
npm version patch          # bumps version in package.json, creates git tag
npm run build:mac          # (or build:win / build:linux)
gh release create v1.0.1 dist/*.dmg dist/*.exe dist/*.AppImage
```

---

## Step 7 — Offline support

The desktop app ships with a SQLite database alongside PostgreSQL. When the app starts, it tests the PostgreSQL connection. If it fails (e.g., the user is on a plane), it falls back to SQLite automatically.

Configure offline mode in `app/config.py`:

```python
# app/config.py
import os

PGAPPFORGE_OFFLINE_ENABLED = True
PGAPPFORGE_OFFLINE_CONFLICT_STRATEGY = 'server_wins'  # or 'client_wins'

# Primary database — PostgreSQL
SQLALCHEMY_DATABASE_URI = os.environ.get(
    'SQLALCHEMY_DATABASE_URI',
    'postgresql://localhost/employees'
)

# Offline fallback — SQLite in the user's app data directory
SQLALCHEMY_OFFLINE_URI = 'sqlite:///mydesktopapp_offline.db'
```

When PostgreSQL becomes reachable again, the app syncs local changes using the configured conflict strategy:

- `server_wins` — remote state overwrites any local changes made offline (safe default)
- `client_wins` — local changes are pushed to the server, overwriting remote changes
- `manual` — conflicts surface in a review UI before being resolved

The sync is triggered automatically on reconnect and can also be triggered manually from the **File → Sync Now** menu item.

---

## Step 8 — Desktop vs web vs mobile: when to choose each

| | Web (`gen all`) | Mobile (`gen mobile`) | Desktop (`gen desktop`) |
|---|---|---|---|
| **Platform** | Any browser | iOS + Android | macOS, Windows, Linux |
| **Distribution** | URL | App Store / sideload | Installer download |
| **Offline** | PWA (optional) | WatermelonDB sync | SQLite fallback + sync |
| **Auth** | Session / OAuth | JWT + biometric | Session (local) |
| **Database access** | Remote PostgreSQL | REST API only | Direct PostgreSQL or SQLite |
| **UI framework** | Flask + Jinja2 | React Native (Expo) | Flask + Jinja2 in Electron |
| **Best for** | Multi-user SaaS, shared dashboards | Field data capture, mobile-first UX | Internal tools, data-heavy desktop workflows, air-gapped environments |
| **Code sharing** | — | API layer shared with web | Full Flask app shared with web |

**Choose desktop when**: users need a native experience on a workstation, the app handles large local datasets, or the deployment environment is air-gapped or has unreliable network access.

**Choose mobile when**: users are in the field and need iOS/Android with biometric auth and camera access.

**Choose web when**: you need multi-user collaboration, zero-install access, or you are building a SaaS product.

---

## Next steps

- To deploy the web version of the same app, see Tutorial 11
- To generate the mobile version, see Tutorial 08
- `docs/deployment/production_deployment.md` covers server configuration for the Flask backend that the desktop app connects to in production
