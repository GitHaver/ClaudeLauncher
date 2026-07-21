"""Claude Launcher — a small desktop app to browse, create and launch
Claude Code projects without touching a terminal by hand.

Windows-only (launches `claude` in a new cmd window).
"""

import os
import sys
import json
import time
import queue
import threading
import subprocess
from datetime import datetime
from collections import defaultdict

import tkinter as tk
import customtkinter as ctk
from tkinter import filedialog, messagebox

# Dark palette for the (native-tk) project rows — matches CustomTkinter's dark
# theme but is ~50x cheaper to build than CTk widgets, which keeps the list snappy.
ROW_BG = "gray20"          # row card
TXT = "#DCE4EE"            # primary text
SUB = "gray55"             # secondary text
SEC_BG, SEC_HOV = "gray30", "gray40"     # secondary buttons
PRI_BG, PRI_HOV = "#1F6AA5", "#144870"   # launch button
APP_BG, APP_HOV = "#2E7D46", "#379451"   # launch-app button (filled = linked)
APP_OUT_HOV = "#264130"                  # launch-app hover when unlinked (outline)
APP_BORDER = "#2E7D46"                    # green outline drawn in both states
PIN_BG, PIN_HOV = "#C9962F", "#E0A838"   # active pin/star
DEL_HOV = "#A33333"        # remove hover

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(APP_DIR, "launcher_state.json")

# Directories we never descend into while scanning (dev noise / huge trees).
PRUNE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".tox", "dist", "build", ".idea",
    ".vscode", ".claude", "site-packages", ".next", "target", ".cache",
}

# System folders (by name, case-insensitive) we never scan for projects —
# catches e.g. "D:\Program Files" that env-var roots below would miss.
IGNORE_NAMES = {
    "windows", "winsxs", "$recycle.bin", "system volume information",
    "recovery", "perflogs", "$windows.~bt", "$windows.~ws",
    "program files", "program files (x86)", "programdata",
    "msocache", "config.msi",
    # Claude's own on-disk session store — not real projects.
    "local-agent-mode-sessions",
}


def _ignored_roots():
    """Absolute system roots (from environment) to skip while scanning."""
    roots = set()
    for var in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)",
                "ProgramW6432", "ProgramData"):
        val = os.environ.get(var)
        if val:
            roots.add(os.path.normcase(os.path.normpath(val)))
    return roots


IGNORE_ROOTS = _ignored_roots()

# The user's home dir itself is never a project — it only looks like one
# because it holds the global ~/.claude config directory.
HOME = os.path.normcase(os.path.normpath(
    os.environ.get("USERPROFILE") or os.path.expanduser("~")))

# Path components (case-insensitive) that disqualify a path from being a project.
_IGNORE_COMPONENTS = ({n.lower() for n in IGNORE_NAMES}
                      | {d.lower() for d in PRUNE_DIRS})


def path_is_ignored(path):
    """True if `path` should not be tracked as a project (matches scan rules)."""
    norm = os.path.normcase(os.path.normpath(path))
    if norm == HOME or norm in IGNORE_ROOTS:
        return True
    for part in norm.split(os.sep):
        if part and (part in _IGNORE_COMPONENTS or part.startswith(".")):
            return True
    return False


# --------------------------------------------------------------------------- #
# Scanning
# --------------------------------------------------------------------------- #
def is_project_dir(path):
    """A folder is a Claude project if it holds a CLAUDE.md or a .claude/ dir."""
    try:
        if os.path.isfile(os.path.join(path, "CLAUDE.md")):
            return True
        if os.path.isdir(os.path.join(path, ".claude")):
            return True
    except OSError:
        pass
    return False


def scan_for_projects(root, progress=None):
    """Walk *every* folder under `root`, returning all project directories.

    `progress`, if given, is called as progress(current_dir, scanned, found)
    for each directory visited — used to drive live UI feedback.
    """
    found = []
    scanned = 0
    for dirpath, dirnames, _filenames in os.walk(root):
        # Prune dev noise, hidden dirs, and system locations so big roots
        # stay fast and we never wander into Program Files / System32 / etc.
        kept = []
        for d in dirnames:
            if d in PRUNE_DIRS or d.startswith(".") or d.lower() in IGNORE_NAMES:
                continue
            full = os.path.normcase(os.path.normpath(os.path.join(dirpath, d)))
            if full in IGNORE_ROOTS:
                continue
            kept.append(d)
        dirnames[:] = kept
        scanned += 1
        if is_project_dir(dirpath) and not path_is_ignored(dirpath):
            found.append(os.path.normpath(dirpath))
        if progress is not None:
            progress(dirpath, scanned, len(found))
    return found


# --------------------------------------------------------------------------- #
# Tree (nested projects render indented under their nearest ancestor project)
# --------------------------------------------------------------------------- #
def _is_ancestor(anc, desc):
    a = os.path.normcase(anc)
    d = os.path.normcase(desc)
    return d != a and d.startswith(a + os.sep)


def build_tree(paths):
    """Given a flat list of project paths, return (roots, children-map).

    Each path's parent is the nearest other project that contains it.
    """
    parent = {}
    for p in paths:
        best = None
        for q in paths:
            if q == p:
                continue
            if _is_ancestor(q, p) and (best is None or len(q) > len(best)):
                best = q
        parent[p] = best

    children = defaultdict(list)
    roots = []
    for p in paths:
        if parent[p] is None:
            roots.append(p)
        else:
            children[parent[p]].append(p)
    return roots, children


# --------------------------------------------------------------------------- #
# Launching
# --------------------------------------------------------------------------- #
def launch_claude(path):
    if sys.platform.startswith("win"):
        # New visible cmd window, cd'd into the project, running `claude`.
        subprocess.Popen(
            "cmd /k claude",
            cwd=path,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    else:
        raise RuntimeError("This launcher currently supports Windows only.")


# File extensions we know how to run, shown to the user in the picker.
LAUNCH_APP_TYPES = [
    ("Runnable files", "*.bat *.cmd *.ps1 *.exe *.py *.pyw"),
    ("Batch / command", "*.bat *.cmd"),
    ("PowerShell script", "*.ps1"),
    ("Executable", "*.exe"),
    ("Python script", "*.py *.pyw"),
    ("All files", "*.*"),
]


def launch_app_file(file_path):
    """Run an app-launch file, picking how to start it from its extension.

    .py/.pyw → python, .ps1 → powershell, .bat/.cmd → cmd, .exe → run
    directly, anything else → let Windows decide (os.startfile).
    """
    if not sys.platform.startswith("win"):
        raise RuntimeError("This launcher currently supports Windows only.")
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File no longer exists:\n{file_path}")

    ext = os.path.splitext(file_path)[1].lower()
    cwd = os.path.dirname(file_path) or None
    new_console = subprocess.CREATE_NEW_CONSOLE

    if ext in (".py", ".pyw"):
        # Prefer console python for .py (visible output) and windowless
        # pythonw for .pyw. sys.executable may itself be pythonw (the
        # launcher runs under it), so resolve the sibling exe by name.
        exe_name = "pythonw.exe" if ext == ".pyw" else "python.exe"
        py_dir = os.path.dirname(sys.executable or "")
        candidate = os.path.join(py_dir, exe_name) if py_dir else ""
        interpreter = candidate if os.path.isfile(candidate) else exe_name
        subprocess.Popen([interpreter, file_path],
                         cwd=cwd, creationflags=new_console)
    elif ext == ".ps1":
        subprocess.Popen(
            ["powershell", "-NoExit", "-ExecutionPolicy", "Bypass",
             "-File", file_path],
            cwd=cwd, creationflags=new_console)
    elif ext in (".bat", ".cmd"):
        subprocess.Popen(["cmd", "/k", file_path],
                         cwd=cwd, creationflags=new_console)
    elif ext == ".exe":
        subprocess.Popen([file_path], cwd=cwd)
    else:
        os.startfile(file_path)          # let the shell pick a handler


# --------------------------------------------------------------------------- #
# Persistent state
# --------------------------------------------------------------------------- #
class State:
    def __init__(self):
        self.scan_roots = []          # list[str]
        self.projects = {}            # normpath -> {"last_accessed": float|None, "hidden": bool}

    def load(self):
        if os.path.isfile(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                return
            self.scan_roots = data.get("scan_roots", [])
            self.projects = {
                os.path.normpath(k): self._normalize(v)
                for k, v in data.get("projects", {}).items()
            }

    @staticmethod
    def _normalize(v):
        return {
            "last_accessed": v.get("last_accessed"),
            "hidden": bool(v.get("hidden", False)),
            "pinned": bool(v.get("pinned", False)),
            "detached": bool(v.get("detached", False)),   # broken out of its group
            "collapsed": bool(v.get("collapsed", False)),  # group folded shut
            "launch_app": v.get("launch_app") or None,     # file to run as "the app"
        }

    def save(self):
        data = {"scan_roots": self.scan_roots, "projects": self.projects}
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def add_project(self, path):
        key = os.path.normpath(path)
        self.projects.setdefault(key, self._normalize({}))
        return key

    def touch(self, key):
        self.projects[key]["last_accessed"] = datetime.now().timestamp()

    def add_scan_root(self, root):
        root = os.path.normpath(root)
        if root not in self.scan_roots:
            self.scan_roots.append(root)


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.store = State()
        self.store.load()
        self.query = ""
        self._scanning = False
        self._dirty = {}            # per-tab: needs re-render?
        self._search_after = None   # debounce handle
        self._anchor = None         # row to keep visually fixed across a rebuild
        # Rows are reused across renders rather than rebuilt: on each render we
        # reconcile the live widgets against the desired list, only creating,
        # updating, reordering or destroying the rows that actually changed.
        self._row_widgets = {}      # path -> row frame
        self._row_parts = {}        # path -> {sub-widget name: widget}
        self._row_desc = {}         # path -> last descriptor rendered
        self._row_order = []        # path list in current pack order
        self._active_frame = None   # which tab's frame the rows belong to
        self._empty_widget = None   # "no projects" placeholder label
        # Existence (isdir/isfile) is cached and refreshed off the UI thread.
        # Rendering NEVER stats the filesystem — a per-row stat on the UI
        # thread stalls hard where file access is slow (network paths, AV/EDR).
        self._exists = {}           # path/file -> bool
        self._exists_busy = False   # a background check is in flight
        self._exists_again = False  # another was requested while busy

        self.title("Claude Launcher")
        self.geometry("860x620")
        self.minsize(640, 400)
        self._set_icon()

        self._build_ui()
        self.refresh()

    def _set_icon(self):
        ico = os.path.join(APP_DIR, "claude_launcher.ico")
        if os.path.isfile(ico):
            try:
                self.iconbitmap(ico)          # title bar + taskbar (Windows)
            except Exception:                 # noqa: BLE001
                pass

    # ---- layout ---------------------------------------------------------- #
    def _build_ui(self):
        # Plain tk font tuples for the native rows (no widget allocation cost).
        self.f_title = ("Segoe UI", 12, "bold")
        self.f_sub = ("Segoe UI", 9)
        self.f_btn = ("Segoe UI", 10)
        self.f_arrow = ("Segoe UI", 15)

        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=10, pady=(10, 4))

        self.btn_scan = ctk.CTkButton(top, text="Scan Folder…", width=110,
                                      command=self.on_scan)
        self.btn_scan.pack(side="left", padx=(6, 4), pady=6)
        self.btn_rescan = ctk.CTkButton(top, text="Rescan All", width=90,
                                        command=self.on_rescan)
        self.btn_rescan.pack(side="left", padx=4)
        self.btn_open = ctk.CTkButton(top, text="Open Folder…", width=110,
                                      command=self.on_add_existing)
        self.btn_open.pack(side="left", padx=4)
        self.btn_create = ctk.CTkButton(top, text="Create New…", width=110,
                                        command=self.on_create)
        self.btn_create.pack(side="left", padx=4)
        self.btn_cleanup = ctk.CTkButton(top, text="Clean Up", width=90,
                                         fg_color="gray30", hover_color="gray40",
                                         command=self.on_cleanup)
        self.btn_cleanup.pack(side="left", padx=4)

        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._schedule_search())
        ctk.CTkEntry(top, placeholder_text="Search…", width=220,
                     textvariable=self.search_var).pack(side="right", padx=(4, 6))

        self.tabs = ctk.CTkTabview(self, command=self._render_active)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=4)
        self.tabs.add("Projects")
        self.tabs.add("Hidden")

        self.proj_frame = ctk.CTkScrollableFrame(self.tabs.tab("Projects"))
        self.proj_frame.pack(fill="both", expand=True)
        self.hidden_frame = ctk.CTkScrollableFrame(self.tabs.tab("Hidden"))
        self.hidden_frame.pack(fill="both", expand=True)

        self.progress = ctk.CTkProgressBar(self, mode="indeterminate")
        # packed only while a scan is running (see _set_scanning)

        self.status = ctk.CTkLabel(self, text="", anchor="w", text_color="gray")
        self.status.pack(fill="x", padx=14, pady=(0, 8))

    # ---- rendering ------------------------------------------------------- #
    def _visible_hidden(self):
        vis, hid = [], []
        for p, m in self.store.projects.items():
            (hid if m.get("hidden") else vis).append(p)
        return vis, hid

    def refresh(self):
        # Mark both tabs stale but only rebuild the one on screen now; the
        # other rebuilds lazily when it's next shown (see _render_active).
        self._dirty = {"Projects": True, "Hidden": True}
        self._render_active()

        vis, hid = self._visible_hidden()
        self.status.configure(
            text=f"{len(vis)} projects · {len(hid)} hidden · "
                 f"{len(self.store.scan_roots)} scan root(s)"
        )
        # Refresh the existence cache in the background; if anything actually
        # changed on disk, the current tab re-renders once the check returns.
        self._start_existence_scan()

    def _render_active(self):
        name = self.tabs.get()
        if not self._dirty.get(name, True):
            return
        self._dirty[name] = False
        vis, hid = self._visible_hidden()
        if name == "Hidden":
            frame, paths, hint = self.hidden_frame, hid, False
        else:
            frame, paths, hint = self.proj_frame, vis, True

        # Switching which tab is on screen: the other tab's rows belong to a
        # different frame, so drop them (they rebuild lazily when reshown).
        if self._active_frame is not frame:
            self._clear_rows()
            self._active_frame = frame

        descriptors, empty_msg = self._compute_rows(paths, empty_hint=hint)

        anchor = self._anchor
        self._anchor = None
        # Measure the anchor row's on-screen offset before we reorder.
        anchor_offset = None
        if anchor and anchor in self._row_widgets:
            w = self._row_widgets[anchor]
            try:
                if w.winfo_exists():
                    anchor_offset = (w.winfo_rooty()
                                     - frame._parent_canvas.winfo_rooty())
            except Exception:                   # noqa: BLE001
                anchor_offset = None
        frac = self._get_scroll(frame)          # fallback: preserve scroll ratio

        self._sync_rows(frame, descriptors, empty_msg)
        frame.update_idletasks()

        def restore():
            if anchor_offset is not None and anchor in self._row_widgets:
                self._anchor_row(frame, self._row_widgets[anchor], anchor_offset)
            else:
                self._set_scroll(frame, frac)

        restore()
        self.after_idle(restore)                # re-apply once geometry settles

    @staticmethod
    def _get_scroll(frame):
        try:
            return frame._parent_canvas.yview()[0]
        except Exception:                       # noqa: BLE001
            return 0.0

    @staticmethod
    def _set_scroll(frame, frac):
        try:
            frame._parent_canvas.yview_moveto(frac)
        except Exception:                       # noqa: BLE001
            pass

    @staticmethod
    def _anchor_row(frame, row, target_offset):
        """Scroll so `row` sits `target_offset` px below the viewport top."""
        canvas = frame._parent_canvas
        try:
            if not row.winfo_exists():
                return
            bbox = canvas.bbox("all")
            if not bbox:
                return
            total_h = bbox[3] - bbox[1]
            if total_h <= 0:
                return
            desired = row.winfo_y() - target_offset
            canvas.yview_moveto(min(1.0, max(0.0, desired / total_h)))
        except Exception:                       # noqa: BLE001
            pass

    def _schedule_search(self):
        if self._search_after is not None:
            self.after_cancel(self._search_after)
        self._search_after = self.after(140, self.on_search)

    def _compute_rows(self, paths, empty_hint):
        """Return (ordered list of row descriptors, empty-message-or-None).

        Pure data — no widgets are created here. The descriptor for each row
        captures everything that affects how it looks, so a later render can
        tell whether a live row needs updating just by comparing descriptors.
        """
        q = self.query
        m = self.store.projects

        def pinned(p):
            return m[p].get("pinned")

        # Nearest ancestor project by path (ignores detach).
        _, nat_children = build_tree(paths)
        nearest = {}
        for parent_p, kids in nat_children.items():
            for c in kids:
                nearest[c] = parent_p

        # Flatten to a single level: a nested project attaches to its
        # *outermost* ancestor project, not the nearest one. This guarantees a
        # project is never both a child and a group container, so each row
        # needs only one gutter icon — an expand toggle for a root that has
        # children, or an ungroup toggle for a nested leaf, never both.
        nat_parent = {}
        for p in paths:
            root = nearest.get(p)
            if root is None:
                continue
            while nearest.get(root) is not None:
                root = nearest[root]
            nat_parent[p] = root

        # Effective parent: None if the node is detached from its group.
        eff_children = defaultdict(list)
        for p in paths:
            par = nat_parent.get(p)
            if par is not None and not m[p].get("detached"):
                eff_children[par].append(p)

        def matches(p):
            return q in os.path.basename(p).lower() or q in p.lower()

        def keep(p):
            if not q or matches(p):
                return True
            return any(keep(c) for c in eff_children.get(p, []))

        _sk_cache = {}

        def sortkey(p):
            if p in _sk_cache:
                return _sk_cache[p]
            own = m[p].get("last_accessed") or 0
            val = max([own] + [sortkey(c) for c in eff_children.get(p, [])])
            _sk_cache[p] = val
            return val

        def top_key(p):
            # Pinned favourites first (by their own last-opened date), then the
            # rest by group recency (newest activity anywhere in the group).
            if pinned(p):
                return (0, -(m[p].get("last_accessed") or 0))
            return (1, -sortkey(p))

        out = []

        def render(p, depth):
            if not keep(p):
                return
            inline = [c for c in eff_children.get(p, []) if not pinned(c)]
            collapsed = bool(m[p].get("collapsed")) and not q
            out.append(self._descriptor(
                p, depth, has_group=bool(inline), collapsed=collapsed,
                groupable=nat_parent.get(p) is not None))
            if collapsed:
                return
            for c in sorted(inline, key=sortkey, reverse=True):
                render(c, depth + 1)

        # Display roots: natural top-level nodes + detached + pinned (pulled out).
        display_roots = [p for p in paths
                         if nat_parent.get(p) is None
                         or m[p].get("detached")
                         or pinned(p)]
        display_roots = [p for p in dict.fromkeys(display_roots) if keep(p)]

        if not display_roots:
            if empty_hint:
                msg = ('No projects yet.\nClick "Scan Folder…" to find existing ones, '
                       'or "Create New…".')
            else:
                msg = "No matches." if q else "Nothing hidden."
            return [], msg

        for r in sorted(display_roots, key=top_key):
            render(r, 0)
        return out, None

    def _descriptor(self, p, depth, has_group, collapsed, groupable):
        """Snapshot of every input that affects how row `p` is drawn."""
        m = self.store.projects[p]
        app = m.get("launch_app") or None
        return {
            "path": p,
            "depth": depth,
            "has_group": has_group,
            "collapsed": collapsed,
            "groupable": groupable,
            "pinned": bool(m.get("pinned")),
            "detached": bool(m.get("detached")),
            "hidden": bool(m.get("hidden")),
            "exists": self._exists.get(p, True),
            "last_accessed": m.get("last_accessed"),
            "app": app,
            "app_missing": app is not None and self._exists.get(app) is False,
        }

    def _tkbtn(self, parent, text, cmd, bg=SEC_BG, hov=SEC_HOV, fg=TXT,
              width=None, font=None, border=None):
        # `border` draws a 1px outline (used by the green launch-app buttons so
        # the outline and filled states keep exactly the same footprint).
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                      activebackground=hov, activeforeground=fg,
                      disabledforeground=SUB, relief="flat", bd=0,
                      highlightthickness=1 if border else 0,
                      highlightbackground=border or bg,
                      highlightcolor=border or bg, cursor="hand2",
                      font=font or self.f_btn, padx=6, pady=3)
        if width:
            b.configure(width=width)
        # Store the base/hover colours on the widget so the hover handlers read
        # the *current* colours — a row's buttons get recoloured in place when
        # its state changes (pin, app link), and a captured colour would leave
        # the hover restoring the old one.
        b._bg, b._hov = bg, hov
        b.bind("<Enter>", lambda _e, w=b:
               w.configure(bg=w._hov) if str(w["state"]) == "normal" else None)
        b.bind("<Leave>", lambda _e, w=b: w.configure(bg=w._bg))
        return b

    @staticmethod
    def _recolor(btn, bg, hov):
        """Change a button's base + hover colours (keeps hover correct)."""
        btn._bg, btn._hov = bg, hov
        btn.configure(bg=bg, activebackground=hov)

    @staticmethod
    def _set_enabled(btn, enabled):
        if enabled:
            btn.configure(state="normal", cursor="hand2")
        else:
            btn.configure(state="disabled", cursor="arrow")

    def _blank_slot(self, parent, width=2, font=None, border=None):
        """An inert, invisible button-sized spacer — reserves a column so the
        visible buttons in that column line up across every row."""
        b = self._tkbtn(parent, " ", None, bg=ROW_BG, hov=ROW_BG,
                        width=width, font=font, border=border)
        # Kill the border colour too, so nothing shows; keep the footprint.
        b.configure(state="disabled", disabledforeground=ROW_BG, cursor="arrow",
                    highlightbackground=ROW_BG, highlightcolor=ROW_BG)
        return b

    # ---- row reconciliation --------------------------------------------- #
    def _clear_rows(self):
        """Destroy all live rows and the empty placeholder (tab switch)."""
        for w in self._row_widgets.values():
            w.destroy()
        self._row_widgets = {}
        self._row_parts = {}
        self._row_desc = {}
        self._row_order = []
        if self._empty_widget is not None:
            self._empty_widget.destroy()
            self._empty_widget = None

    def _sync_rows(self, container, descriptors, empty_msg):
        """Reconcile live row widgets against the desired descriptor list.

        Creates rows for new paths, updates rows whose descriptor changed,
        destroys rows that vanished, and reorders with minimal moves. Rows
        that are unchanged and unmoved are left completely untouched — the
        whole point: no teardown, no flash, near-instant interactions.
        """
        new_order = [d["path"] for d in descriptors]
        new_set = set(new_order)

        # 1. Destroy rows no longer present.
        for p in list(self._row_widgets):
            if p not in new_set:
                self._row_widgets.pop(p).destroy()
                self._row_parts.pop(p, None)
                self._row_desc.pop(p, None)

        # 2. Empty list → show the placeholder, drop any rows, done.
        if not new_order:
            if self._empty_widget is None:
                self._empty_widget = ctk.CTkLabel(
                    container, text=empty_msg or "", text_color="gray")
                self._empty_widget.pack(pady=24)
            else:
                self._empty_widget.configure(text=empty_msg or "")
            self._row_order = []
            return
        if self._empty_widget is not None:
            self._empty_widget.destroy()
            self._empty_widget = None

        # 3. Create new rows (unpacked) and update changed ones.
        forced = set()                       # rows that must be (re)packed
        for d in descriptors:
            p = d["path"]
            old = self._row_desc.get(p)
            if p not in self._row_widgets:
                self._build_row(container, p)
                self._apply_row(p, d)
            elif old != d:
                self._apply_row(p, d)
                if old is not None and old["depth"] != d["depth"]:
                    forced.add(p)            # indent changed → needs re-pack
            self._row_desc[p] = d

        # 4. Reorder to match new_order, moving as few rows as possible.
        self._reorder(new_order, forced)
        self._row_order = new_order

    @staticmethod
    def _lcs(a, b):
        """Set of items forming a longest common subsequence of a and b.

        Items are unique within each list (project paths), so this identifies
        the rows that already sit in the right relative order and can stay put.
        """
        n, m = len(a), len(b)
        if not n or not m:
            return set()
        dp = [[0] * (m + 1) for _ in range(n + 1)]
        for i in range(n - 1, -1, -1):
            for j in range(m - 1, -1, -1):
                dp[i][j] = (dp[i + 1][j + 1] + 1 if a[i] == b[j]
                            else max(dp[i + 1][j], dp[i][j + 1]))
        keep = set()
        i = j = 0
        while i < n and j < m:
            if a[i] == b[j]:
                keep.add(a[i]); i += 1; j += 1
            elif dp[i + 1][j] >= dp[i][j + 1]:
                i += 1
            else:
                j += 1
        return keep

    def _reorder(self, new_order, forced):
        """Pack rows into new_order, repacking only rows that must move."""
        survivors = [p for p in self._row_order if p in self._row_widgets]
        if survivors == new_order and not forced:
            return                            # nothing moved — common fast path
        if not survivors:
            stable = set()
        elif survivors == new_order:
            stable = set(new_order)
        else:
            stable = self._lcs(survivors, new_order)
        stable -= forced

        for i, p in enumerate(new_order):
            if p in stable:
                continue
            before = None
            for q in new_order[i + 1:]:
                if q in stable:
                    before = self._row_widgets[q]
                    break
            depth = self._row_desc[p]["depth"]
            opts = {"fill": "x", "padx": (6 + depth * 26, 6), "pady": 3}
            if before is not None:                # None → append at the end
                opts["before"] = before
            self._row_widgets[p].pack_configure(**opts)

    # ---- row widgets ---------------------------------------------------- #
    def _build_row(self, container, path):
        """Create a row's full (reusable) widget skeleton, unpacked.

        Every widget the row can ever need is created once here; _apply_row
        then just reconfigures text/colour/state and shows or hides the few
        mode-specific pieces (gutter icon, ⚙ vs spacer, the App: line). The
        row frame itself is packed later by _reorder.
        """
        parts = {}
        row = tk.Frame(container, bg=ROW_BG)
        self._row_widgets[path] = row

        # Left gutter — one column so every name label starts at the same x.
        # Holds a single toggle button (collapse/expand for a group root, or
        # ungroup/regroup for a nested leaf) or an invisible spacer; only one
        # is shown at a time (flattening guarantees never both — see
        # _compute_rows).
        gutter = tk.Frame(row, bg=ROW_BG)
        gutter.pack(side="left", padx=(4, 0), pady=4)
        parts["gutter_btn"] = self._tkbtn(gutter, "", None, bg=ROW_BG,
                                          hov=SEC_BG, width=2, font=self.f_arrow)
        parts["gutter_blank"] = self._blank_slot(gutter, width=2,
                                                 font=self.f_arrow)
        parts["gutter_mode"] = None

        info = tk.Frame(row, bg=ROW_BG)
        info.pack(side="left", fill="x", expand=True, padx=8, pady=5)
        parts["name"] = os.path.basename(path) or path
        parts["title"] = tk.Label(info, text="", bg=ROW_BG, fg=TXT, anchor="w",
                                  font=self.f_title)
        parts["title"].pack(fill="x")
        tk.Label(info, text=path, bg=ROW_BG, fg=SUB, anchor="w",
                 font=self.f_sub).pack(fill="x")
        parts["la"] = tk.Label(info, text="", bg=ROW_BG, fg=SUB, anchor="w",
                               font=self.f_sub)
        parts["la"].pack(fill="x")
        parts["app"] = tk.Label(info, text="", bg=ROW_BG, fg=SUB, anchor="w",
                                font=self.f_sub)          # packed on demand
        parts["app_shown"] = False

        btns = tk.Frame(row, bg=ROW_BG)
        btns.pack(side="right", padx=6)
        parts["pin"] = self._tkbtn(btns, "☆", lambda p=path: self.on_toggle_pin(p),
                                   width=2)
        parts["pin"].pack(side="left", padx=3)
        parts["launch"] = self._tkbtn(btns, "▶ Launch",
                                      lambda p=path: self.on_launch(p),
                                      bg=PRI_BG, hov=PRI_HOV)
        parts["launch"].pack(side="left", padx=3)
        # Launch App: always the rocket. Filled green once linked to a file,
        # green outline (no fill) until then. The ⚙ button edits that choice;
        # when there is nothing to edit an invisible slot holds its place so
        # the rocket / Launch / ★ columns stay aligned across every row.
        parts["appbtn"] = self._tkbtn(btns, "🚀 App",
                                      lambda p=path: self.on_launch_app(p),
                                      bg=ROW_BG, hov=APP_OUT_HOV, border=APP_BORDER)
        parts["appbtn"].pack(side="left", padx=3)
        # U+FE0E on the gear forces monochrome/text presentation; without it
        # Windows draws an oversized colour emoji that inflates the button.
        parts["gear"] = self._tkbtn(btns, "⚙︎",
                                    lambda p=path: self.on_edit_launch_app(p),
                                    bg=APP_BG, hov=APP_HOV, width=2,
                                    border=APP_BORDER)
        parts["gear_blank"] = self._blank_slot(btns, width=2, border=APP_BORDER)
        parts["gear_mode"] = None
        parts["open"] = self._tkbtn(btns, "📁",
                                    lambda p=path: self.on_open_folder(p), width=3)
        parts["open"].pack(side="left", padx=3)
        parts["hide"] = self._tkbtn(btns, "Hide",
                                    lambda p=path: self.on_toggle_hide(p))
        parts["hide"].pack(side="left", padx=3)
        self._tkbtn(btns, "✕", lambda p=path: self.on_remove(p),
                    bg=ROW_BG, hov=DEL_HOV, fg=SUB, width=2).pack(side="left", padx=3)

        self._row_parts[path] = parts

    def _apply_row(self, path, d):
        """Reconfigure a live row's widgets to match descriptor `d`."""
        parts = self._row_parts[path]
        exists = d["exists"]

        # Gutter: pick toggle (with the right glyph/command) or spacer.
        gb, blank = parts["gutter_btn"], parts["gutter_blank"]
        if d["has_group"]:
            gb.configure(text="▶" if d["collapsed"] else "▼",
                         command=lambda p=path: self.on_toggle_collapse(p))
            mode = "btn"
        elif d["groupable"] and not d["pinned"]:
            # While pinned the star governs placement (the row floats to the
            # favourites section), so the ungroup arrow is hidden; the detach
            # flag is left untouched so unfavouriting restores the grouping.
            gb.configure(text="⇥" if d["detached"] else "⇤",
                         command=lambda p=path: self.on_toggle_detach(p))
            mode = "btn"
        else:
            mode = "blank"
        if parts["gutter_mode"] != mode:
            if mode == "btn":
                blank.pack_forget(); gb.pack(side="left")
            else:
                gb.pack_forget(); blank.pack(side="left")
            parts["gutter_mode"] = mode

        # Title + tags.
        tags = []
        if d["pinned"]:
            tags.append("★")
        if d["detached"]:
            tags.append("ungrouped")
        if not exists:
            tags.append("missing")
        parts["title"].configure(
            text=parts["name"] + (f"   ({', '.join(tags)})" if tags else ""))

        # Last opened.
        la = d["last_accessed"]
        parts["la"].configure(
            text="Last opened: " + (datetime.fromtimestamp(la)
                                    .strftime("%Y-%m-%d %H:%M") if la else "never"))

        # App: line (shown only when a launch app is linked).
        app = d["app"]
        if app:
            miss = "  (missing)" if d["app_missing"] else ""
            parts["app"].configure(text=f"App: {os.path.basename(app)}{miss}")
            if not parts["app_shown"]:
                parts["app"].pack(fill="x"); parts["app_shown"] = True
        elif parts["app_shown"]:
            parts["app"].pack_forget(); parts["app_shown"] = False

        # Pin star.
        self._recolor(parts["pin"], PIN_BG if d["pinned"] else SEC_BG,
                      PIN_HOV if d["pinned"] else SEC_HOV)
        parts["pin"].configure(text="★" if d["pinned"] else "☆")

        # Launch / App / Open are disabled when the folder is gone.
        self._set_enabled(parts["launch"], exists)
        app_set = app is not None
        self._recolor(parts["appbtn"], APP_BG if app_set else ROW_BG,
                      APP_HOV if app_set else APP_OUT_HOV)
        self._set_enabled(parts["appbtn"], exists)

        # ⚙ edit button vs invisible spacer.
        mode = "gear" if app_set else "blank"
        if parts["gear_mode"] != mode:
            if app_set:
                parts["gear_blank"].pack_forget()
                parts["gear"].pack(before=parts["open"], side="left", padx=3)
            else:
                parts["gear"].pack_forget()
                parts["gear_blank"].pack(before=parts["open"], side="left", padx=3)
            parts["gear_mode"] = mode

        self._set_enabled(parts["open"], exists)
        parts["hide"].configure(text="Unhide" if d["hidden"] else "Hide")

    # ---- actions --------------------------------------------------------- #
    def on_launch(self, path):
        if not os.path.isdir(path):
            messagebox.showerror("Missing folder", f"Folder no longer exists:\n{path}")
            return
        try:
            launch_claude(path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Launch failed", str(e))
            return
        self.store.touch(os.path.normpath(path))
        self.store.save()
        self.refresh()

    def _pick_launch_app(self, path):
        """Ask the user for the file that launches this project's app."""
        current = self.store.projects[path].get("launch_app")
        if current and os.path.isfile(current):
            start = os.path.dirname(current)
        elif os.path.isdir(path):
            start = path
        else:
            start = None
        chosen = filedialog.askopenfilename(
            title="Select the file that launches this app",
            initialdir=start,
            filetypes=LAUNCH_APP_TYPES,
        )
        return os.path.normpath(chosen) if chosen else None

    def on_launch_app(self, path):
        if not os.path.isdir(path):
            messagebox.showerror("Missing folder", f"Folder no longer exists:\n{path}")
            return
        meta = self.store.projects[path]
        app = meta.get("launch_app")

        # First use (or the saved file vanished): ask for one and remember it.
        if not app or not os.path.isfile(app):
            if app and not os.path.isfile(app):
                if not messagebox.askyesno(
                    "App file missing",
                    f"The saved app file no longer exists:\n{app}\n\n"
                    "Choose a different file?"):
                    return
            chosen = self._pick_launch_app(path)
            if not chosen:
                return
            meta["launch_app"] = chosen
            self.store.save()
            self.refresh()
            app = chosen

        try:
            launch_app_file(app)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Launch failed", str(e))
            return
        self.store.touch(os.path.normpath(path))
        self.store.save()
        self.refresh()

    def on_edit_launch_app(self, path):
        meta = self.store.projects[path]
        chosen = self._pick_launch_app(path)
        if not chosen:
            return
        meta["launch_app"] = chosen
        self.store.save()
        self.refresh()

    def on_open_folder(self, path):
        if not os.path.isdir(path):
            messagebox.showerror("Missing folder", f"Folder no longer exists:\n{path}")
            return
        try:
            os.startfile(path)          # opens in Windows Explorer
        except Exception as e:          # noqa: BLE001
            messagebox.showerror("Could not open folder", str(e))

    def on_toggle_hide(self, path):
        m = self.store.projects[path]
        m["hidden"] = not m.get("hidden")
        self.store.save()
        self.refresh()

    def on_toggle_pin(self, path):
        m = self.store.projects[path]
        m["pinned"] = not m.get("pinned")
        self.store.save()
        self.refresh()

    def on_toggle_detach(self, path):
        m = self.store.projects[path]
        m["detached"] = not m.get("detached")
        self.store.save()
        self.refresh()

    def on_toggle_collapse(self, path):
        m = self.store.projects[path]
        m["collapsed"] = not m.get("collapsed")
        self.store.save()
        self._anchor = path          # keep this row fixed on screen
        self.refresh()

    def on_remove(self, path):
        if messagebox.askyesno(
            "Remove from list",
            f"Remove this project from the launcher list?\n\n{path}\n\n"
            "(The folder on disk is NOT deleted.)",
        ):
            self.store.projects.pop(path, None)
            self.store.save()
            self.refresh()

    def on_cleanup(self):
        if self._scanning:
            return
        remove = [p for p in self.store.projects
                  if not os.path.isdir(p) or path_is_ignored(p)]
        if not remove:
            messagebox.showinfo(
                "Clean Up", "Nothing to clean — no missing or ignored projects.")
            return
        if messagebox.askyesno(
            "Clean Up",
            f"Remove {len(remove)} missing/ignored project(s) from the list?\n\n"
            "(Folders on disk are NOT deleted.)",
        ):
            for p in remove:
                self.store.projects.pop(p, None)
            self.store.save()
            self.refresh()
            self.status.configure(text=f"Cleaned up {len(remove)} project(s).")

    def on_scan(self):
        if self._scanning:
            return
        root = filedialog.askdirectory(
            title="Select a folder to scan for Claude projects")
        if not root:
            return
        self.store.add_scan_root(root)
        self.store.save()
        self._start_scan([os.path.normpath(root)])

    def on_rescan(self):
        if self._scanning:
            return
        if not self.store.scan_roots:
            messagebox.showinfo("No scan roots",
                                "You haven't scanned any folders yet.")
            return
        roots = [r for r in self.store.scan_roots if os.path.isdir(r)]
        if not roots:
            messagebox.showinfo("No scan roots",
                                "None of your saved scan folders exist anymore.")
            return
        self._start_scan(roots)

    # ---- threaded scanning ---------------------------------------------- #
    def _set_scanning(self, active):
        self._scanning = active
        state = "disabled" if active else "normal"
        for b in (self.btn_scan, self.btn_rescan, self.btn_open,
                  self.btn_create, self.btn_cleanup):
            b.configure(state=state)
        if active:
            self.progress.pack(fill="x", padx=14, pady=(0, 2), before=self.status)
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def _start_scan(self, roots):
        self._set_scanning(True)
        self.status.configure(text="Scanning…")
        q = queue.Queue()
        threading.Thread(target=self._scan_worker, args=(roots, q),
                         daemon=True).start()
        self.after(80, self._poll_scan, q)

    def _scan_worker(self, roots, q):
        """Runs off the UI thread; reports progress/results via the queue."""
        found = []
        total_scanned = 0
        last_emit = 0.0

        def progress(current_dir, _scanned, _found):
            nonlocal last_emit, total_scanned
            total_scanned += 1
            now = time.monotonic()
            if now - last_emit >= 0.05:          # throttle UI churn
                last_emit = now
                q.put(("progress", current_dir, total_scanned,
                       len(found) + _found))

        try:
            for root in roots:
                if not os.path.isdir(root):
                    continue
                found.extend(scan_for_projects(root, progress=progress))
            q.put(("done", found))
        except Exception as e:                    # noqa: BLE001
            q.put(("error", str(e)))

    def _poll_scan(self, q):
        latest = None
        done = None
        error = None
        try:
            while True:
                msg = q.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    latest = msg
                elif kind == "done":
                    done = msg[1]
                elif kind == "error":
                    error = msg[1]
        except queue.Empty:
            pass

        if latest is not None:
            _, current_dir, scanned, found = latest
            shown = current_dir if len(current_dir) <= 60 else "…" + current_dir[-58:]
            self.status.configure(
                text=f"Scanning… {scanned} folders, {found} project(s): {shown}")

        if error is not None:
            self._set_scanning(False)
            messagebox.showerror("Scan failed", error)
            self.refresh()
            return

        if done is not None:
            existing = set(self.store.projects)
            new = sum(1 for p in done if os.path.normpath(p) not in existing)
            for p in done:
                self.store.add_project(p)
            self.store.save()
            self._set_scanning(False)
            self.refresh()
            self.status.configure(
                text=f"Scan complete — {len(done)} project(s) found, {new} new.")
            return

        self.after(80, self._poll_scan, q)

    # ---- background existence cache ------------------------------------- #
    def _start_existence_scan(self):
        """Re-check every project dir / launch-app file off the UI thread.

        Only one runs at a time; a request made while busy is coalesced into a
        single follow-up. When the results differ from the cache, the current
        tab is re-rendered so "missing" tags appear/clear.
        """
        if self._exists_busy:
            self._exists_again = True
            return
        self._exists_busy = True
        self._exists_again = False
        projects = list(self.store.projects.keys())
        apps = [m["launch_app"] for m in self.store.projects.values()
                if m.get("launch_app")]
        q = queue.Queue()
        threading.Thread(target=self._existence_worker,
                         args=(projects, apps, q), daemon=True).start()
        self.after(60, self._poll_existence, q)

    @staticmethod
    def _existence_worker(projects, apps, q):
        result = {}
        for p in projects:
            try:
                result[p] = os.path.isdir(p)
            except OSError:
                result[p] = False
        for a in apps:
            try:
                result[a] = os.path.isfile(a)
            except OSError:
                result[a] = False
        q.put(result)

    def _poll_existence(self, q):
        try:
            result = q.get_nowait()
        except queue.Empty:
            self.after(60, self._poll_existence, q)
            return
        self._exists_busy = False
        changed = result != self._exists
        self._exists = result
        if self._exists_again:
            self._start_existence_scan()
        if changed:
            # Existence actually moved — repaint the visible tab so the
            # missing/present state is up to date. (No-op in steady state.)
            self._dirty[self.tabs.get()] = True
            self._render_active()

    def on_add_existing(self):
        """Pick any existing folder, add it to the list, and launch claude."""
        folder = filedialog.askdirectory(
            title="Open an existing folder in Claude")
        if not folder:
            return
        key = self.store.add_project(os.path.normpath(folder))
        try:
            launch_claude(folder)
            self.store.touch(key)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Launch failed", str(e))
        self.store.save()
        self.refresh()

    def on_create(self):
        parent = filedialog.askdirectory(
            title="Choose where to create the new project")
        if not parent:
            return
        name = ctk.CTkInputDialog(
            text="New project folder name:", title="Create New Project").get_input()
        if not name or not name.strip():
            return
        name = name.strip()
        newpath = os.path.normpath(os.path.join(parent, name))

        if os.path.exists(newpath):
            if not messagebox.askyesno(
                "Folder exists", f"“{name}” already exists. Use it anyway?"):
                return
        else:
            try:
                os.makedirs(newpath)
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("Could not create folder", str(e))
                return

        key = self.store.add_project(newpath)
        try:
            launch_claude(newpath)
            self.store.touch(key)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Launch failed", str(e))
        self.store.save()
        self.refresh()

    def on_search(self):
        self._search_after = None
        self.query = self.search_var.get().strip().lower()
        self.refresh()


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    App().mainloop()


if __name__ == "__main__":
    main()
