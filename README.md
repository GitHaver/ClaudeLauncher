# Claude Launcher

A tiny desktop app to browse, create, and launch Claude Code projects — no
manual `cd` + terminal dance.

## Setup

```
pip install -r requirements.txt
```

## Run

Double-click **`run.bat`**, or:

```
python main.py
```

## What it does

- **Scan Folder…** — pick a root; it walks *every* folder underneath and lists
  each one containing a `CLAUDE.md` or a `.claude/` directory. A subfolder with
  its own `CLAUDE.md` becomes its own project, shown **indented** under its
  parent. System locations (`Program Files`, `Windows` / `System32`,
  `ProgramData`, recycle bin, etc.), dev-noise folders (`node_modules`,
  `.git`, virtualenvs, …), Claude's own `local-agent-mode-sessions` store, and
  your home dir itself (which only looks like a project because of the global
  `~/.claude` config) are all skipped automatically. Big scans run on a
  background thread with a live progress bar.
- **Open Folder…** — pick any existing folder in one step; it's added to the
  list and `claude` is launched there. Handy for an existing project that isn't
  a Claude project yet (a scan wouldn't find it, since scans only match folders
  that already have a `CLAUDE.md`/`.claude`).
- **Create New…** — pick a location, name a new folder; it's created and
  `claude` is launched inside to initialize it. (If you type the name of a
  folder that already exists, it offers to use that one instead.)
- **▶ Launch** — opens a new `cmd` window in the project folder running
  `claude`, and stamps the project as most-recently-used so it floats to the
  top.
- **🚀 App** — runs the project's own app. The button is a **green outline**
  until you link a file, then **fills green**. The first click on an unlinked
  project asks you to pick the file that starts it; that choice is saved
  per-project for next time (its name shows on the row as `App: …`). How it's
  run is chosen from the file's extension: `.py`/`.pyw` via Python, `.ps1` via
  PowerShell, `.bat`/`.cmd` via `cmd`, `.exe` directly, anything else via its
  default Windows handler. Launching also stamps the project as
  most-recently-used. Once linked, a **⚙** button (same green style) lets you
  point it at a different file.
- **📁 Open folder** — opens the project folder in Windows Explorer.
- **★ Pin** — pushes a project to the very top of the list. Pinned items sort
  first; everything else sorts by last-opened (newest first).
- **▼ / ▶** — collapse or expand a group (a project with nested sub-projects).
  Shown in the second column of the left gutter.
- **⇤ / ⇥** — in the first column of the left gutter (nested projects only):
  ungroup a project so it shows as its own top-level item (`⇤`), or regroup it
  back under its parent (`⇥`). This only changes how it's displayed — the folder
  on disk isn't moved. A project that is both nested *and* has children of its
  own shows both gutter icons side by side.
- **Hide / Unhide** — move a project to the **Hidden** tab and back.
- **✕** — remove a project from the list (the folder on disk is left alone).
- **Rescan All** — re-walk every folder you've scanned before.
- **Clean Up** — remove list entries whose folder is missing or that match the
  ignore rules (system/noise locations). Never deletes anything on disk.
- **Search** — filter by name or path.

Projects sort by last-opened (newest first). Groups whose nested projects were
used recently float up too.

State lives in `launcher_state.json` next to `main.py`. It's created on first
run and holds machine-specific paths, so it's git-ignored — a fresh clone won't
have one, and the app will build it as you scan and launch projects.

## Desktop shortcut + icon

A `.bat` file can't carry its own icon (Windows always draws it with the
generic shell icon), so to get a nice launcher icon you make a **shortcut**:

```
powershell -ExecutionPolicy Bypass -File make_shortcut.ps1
```

This creates **"Claude Launcher"** on your Desktop, pointing at
`pythonw main.py` (no console window) with the custom icon. Pin it to the
taskbar / Start if you like. Re-run the script any time to recreate it.

The icon itself lives in `claude_launcher.ico` and is drawn by
`generate_icon.py` (a terracotta "spark" + a list badge — original artwork, not
Anthropic's logo). Edit that script and re-run it to tweak the look; the app
also uses it for its title-bar / taskbar icon at runtime.

## Notes

- Windows only (it launches `claude` via `cmd`).
- Requires `claude` to be on your PATH (i.e. `claude` works in a plain `cmd`).
