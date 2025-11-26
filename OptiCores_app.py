import os, time, json, csv, ctypes, subprocess, threading, multiprocessing, shutil
from collections import deque, defaultdict

import psutil
import customtkinter as ctk
from tkinter import ttk, messagebox, filedialog

try:
    import GPUtil
except Exception:
    GPUtil = None

try:
    from PIL import Image
except Exception:
    Image = None

import win32api, win32con, win32gui, win32process
try:
    import win32job   # optional Job Objects
except Exception:
    win32job = None

try:
    import winreg
except Exception:
    winreg = None

# Matplotlib (Insights graphs)
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

APP_NAME = "OptiCores"
APP_DIR  = os.path.join(os.path.expanduser("~"), "AppData", "Local", "OptiCores")
os.makedirs(APP_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
HIST_PATH   = os.path.join(APP_DIR, "effects_history.json")

SYSTEM_WHITELIST = {
    "System", "System Idle Process", "Registry",
    "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "fontdrvhost.exe"
}

DEFAULT_THRESH = {"bg_cpu": 30.0, "heavy_ram_mb": 800.0}
DEFAULT_REFRESH_SEC = 3.0

PRIORITY = {
    "Idle": win32process.IDLE_PRIORITY_CLASS,
    "Below Normal": win32process.BELOW_NORMAL_PRIORITY_CLASS,
    "Normal": win32process.NORMAL_PRIORITY_CLASS,
    "Above Normal": win32process.ABOVE_NORMAL_PRIORITY_CLASS,
    "High": win32process.HIGH_PRIORITY_CLASS,
    "Realtime": win32process.REALTIME_PRIORITY_CLASS,  # caution
}
PRIORITY_KEYS = list(PRIORITY.keys())

# Memory priority via ctypes
class PROCESS_MEMORY_PRIORITY_INFORMATION(ctypes.Structure):
    _fields_ = [("MemoryPriority", ctypes.c_ulong)]
ProcessMemoryPriority = 0x0003
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi    = ctypes.WinDLL("psapi", use_last_error=True)

def set_memory_priority(handle, level: int):
    info = PROCESS_MEMORY_PRIORITY_INFORMATION(level)
    ok = kernel32.SetProcessInformation(
        handle, ProcessMemoryPriority, ctypes.byref(info), ctypes.sizeof(info)
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())

def empty_working_set(handle):
    ok = psapi.EmptyWorkingSet(handle)
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())

def open_proc(pid, access):
    return win32api.OpenProcess(access, False, pid)

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def fg_pid():
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd: return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid
    except Exception:
        return None

# Power throttling
class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong),
                ("ControlMask", ctypes.c_ulong),
                ("StateMask", ctypes.c_ulong)]
def set_power_throttle(handle, eco_on=True):
    try:
        state = PROCESS_POWER_THROTTLING_STATE()
        state.Version = 1
        state.ControlMask = 0x1      # EXECUTION_SPEED
        state.StateMask   = 0x1 if eco_on else 0x0
        ok = kernel32.SetProcessInformation(handle, 0x00000009, ctypes.byref(state), ctypes.sizeof(state))
        if not ok: raise ctypes.WinError(ctypes.get_last_error())
    except Exception:
        pass  # best-effort

# ---------- Tooltips (bind-safe) ----------
class ToolTip:
    def __init__(self, widget, text, delay=500):
        self.widget, self.text, self.delay = widget, text, delay
        self.tw, self._id = None, None
        self._enabled = True
        try:
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)
        except Exception:
            self._enabled = False
    def _enter(self, _=None):
        if not self._enabled: return
        self._id = self.widget.after(self.delay, self._show)
    def _leave(self, _=None):
        if not self._enabled: return
        if self._id:
            try: self.widget.after_cancel(self._id)
            except Exception: pass
            self._id = None
        self._hide()
    def _show(self):
        try:
            x, y, _, _ = self.widget.bbox("insert")
        except Exception:
            x, y = 0, 0
        x += self.widget.winfo_rootx() + 20
        y += self.widget.winfo_rooty() + 30
        self.tw = ctk.CTkToplevel(self.widget)
        self.tw.overrideredirect(True)
        frame = ctk.CTkFrame(self.tw, corner_radius=8)
        ctk.CTkLabel(frame, text=self.text, justify="left", wraplength=260).pack(padx=8, pady=6)
        frame.pack()
        self.tw.geometry(f"+{x}+{y}")
    def _hide(self):
        if self.tw:
            try: self.tw.destroy()
            except Exception: pass
            self.tw = None

# ---------- Undo stack ----------
class UndoStack:
    def __init__(self, maxlen=4000): self.stack = deque(maxlen=maxlen)
    def push(self, pid, kind, before): self.stack.append((pid, kind, before, time.time()))
    def pop_for_pid(self, pid):
        out, keep = [], deque()
        while self.stack:
            i = self.stack.pop()
            (out if i[0]==pid else keep).appendleft(i)
        self.stack = keep
        return out
UNDO = UndoStack()

# ---------- Effects tracker ----------
class EffectsTracker:
    def __init__(self):
        self.pending = {}  # (pid,action) -> baseline
        self.history = []
        try:
            if os.path.exists(HIST_PATH):
                self.history = json.load(open(HIST_PATH, "r", encoding="utf-8"))
        except Exception:
            self.history = []

    def baseline(self, pid, action, cpu, mem):
        self.pending[(pid, action)] = {"t0": time.time(), "cpu0": cpu, "mem0": mem}

    def finalize(self, pid, action, cpu1, mem1):
        key = (pid, action)
        if key not in self.pending: return None
        rec = self.pending.pop(key)
        rec["cpu1"], rec["mem1"], rec["t1"] = cpu1, mem1, time.time()
        rec["pid"], rec["action"] = pid, action
        rec["d_cpu"] = cpu1 - rec["cpu0"]
        rec["d_mem"] = mem1 - rec["mem0"]
        self.history.append(rec)
        try:
            json.dump(self.history[-200:], open(HIST_PATH, "w", encoding="utf-8"), indent=2)
        except Exception:
            pass
        return rec
EFFECTS = EffectsTracker()

# ---------- Background Governor ----------
class BackgroundGovernor:
    def __init__(self):
        self.enabled = False
        self.job = None
        if win32job:
            try: self.job = win32job.CreateJobObject(None, "OptiCores_BackgroundGovernor")
            except Exception: self.job = None

    def govern(self, pid):
        try:
            h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION |
                               win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE)
        except Exception:
            return
        try:
            old = win32process.GetPriorityClass(h)
            if old > win32process.BELOW_NORMAL_PRIORITY_CLASS:
                win32process.SetPriorityClass(h, win32process.BELOW_NORMAL_PRIORITY_CLASS)
                UNDO.push(pid, "priority", old)
        except Exception: pass
        try:
            set_memory_priority(h, 2)  # Low
            UNDO.push(pid, "memprio", 3)
        except Exception: pass
        try:
            set_power_throttle(h, eco_on=True)
        except Exception: pass
        if self.job:
            try:
                win32job.AssignProcessToJobObject(self.job, h)
                UNDO.push(pid, "job", None)
            except Exception:
                pass

# ---------- Health watcher ----------
class HealthWatcher:
    def __init__(self):
        self.hist_mem = defaultdict(lambda: deque(maxlen=8))
        self.hist_cpu = defaultdict(lambda: deque(maxlen=8))
        self.flags    = {}
    def ingest(self, pid, rss_mb, cpu_pct):
        self.hist_mem[pid].append(rss_mb)
        self.hist_cpu[pid].append(cpu_pct)
        leak = self._is_growing(self.hist_mem[pid])
        spike = any(v >= 35 for v in self.hist_cpu[pid])
        self.flags[pid] = {"leak": leak, "spike": spike}
    @staticmethod
    def _is_growing(dq):
        if len(dq) < 6: return False
        up = sum(1 for i in range(1, len(dq)) if dq[i] >= dq[i-1]*1.03)
        return up >= 4
    def get_flags(self, pid):
        return self.flags.get(pid, {"leak": False, "spike": False})

# ---------- Profiles ----------
PROFILES = {
    "Gaming":  {"fg_priority": "High",  "gov": True,  "plan": "HIGH",
                "desc": "Boost foreground app, High Performance power plan, reduce background noise."},
    "Creator": {"fg_priority": "Above Normal", "gov": True,  "plan": "BALANCED",
                "desc": "Smooth editing/rendering, balanced power, keep background tamed."},
    "Everyday":{"fg_priority": "Normal","gov": False, "plan": "BALANCED",
                "desc": "Best for daily use; balanced plan and default priorities."},
}
def switch_power_plan(tag):
    try:
        if tag == "HIGH":
            subprocess.run(["powercfg", "/setactive", "SCHEME_MIN"], check=False)
        else:
            subprocess.run(["powercfg", "/setactive", "SCHEME_BALANCED"], check=False)
    except Exception:
        pass

# ---------- Startup Manager ----------
class StartupEntry:
    def __init__(self, source, name, command, enabled, kind, path=None, hive="HKCU"):
        self.source  = source   # "HKCU_Run" / "HKLM_Run" / "UserStartup" / "CommonStartup"
        self.name    = name
        self.command = command
        self.enabled = enabled
        self.kind    = kind     # "registry" or "shortcut"
        self.path    = path
        self.hive    = hive

class StartupManager:
    DISABLED_KEY = r"Software\OptiCores\StartupBackup"
    def __init__(self):
        self.user_startup   = os.path.join(os.getenv("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
        self.common_startup = os.path.join(os.getenv("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs\StartUp")
    def list(self):
        entries = []
        self._list_registry(entries, winreg.HKEY_CURRENT_USER,  r"Software\Microsoft\Windows\CurrentVersion\Run", "HKCU_Run", hive="HKCU")
        self._list_registry(entries, winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKLM_Run", hive="HKLM")
        self._list_startup_folder(entries, self.user_startup, "UserStartup")
        self._list_startup_folder(entries, self.common_startup, "CommonStartup")
        return entries
    def _list_registry(self, out, root, subkey, tag, hive="HKCU"):
        if not winreg: return
        try:
            with winreg.OpenKey(root, subkey) as k:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(k, i)
                        out.append(StartupEntry(tag, name, value, True, "registry", path=subkey, hive=hive))
                        i += 1
                    except OSError:
                        break
        except Exception:
            pass
        # disabled backups
        try:
            with winreg.OpenKey(root, self.DISABLED_KEY + "\\" + tag) as k:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(k, i)
                        out.append(StartupEntry(tag, name, value, False, "registry", path=subkey, hive=hive))
                        i += 1
                    except OSError:
                        break
        except Exception:
            pass
    def _list_startup_folder(self, out, folder, tag):
        if not folder or not os.path.isdir(folder): return
        disabled_dir = os.path.join(folder, "Disabled by OptiCores")
        try:
            for f in os.listdir(folder):
                if f.lower().endswith(".lnk"):
                    out.append(StartupEntry(tag, f, os.path.join(folder, f), True, "shortcut", path=folder))
        except Exception: pass
        try:
            if os.path.isdir(disabled_dir):
                for f in os.listdir(disabled_dir):
                    if f.lower().endswith(".lnk"):
                        out.append(StartupEntry(tag, f, os.path.join(disabled_dir, f), False, "shortcut", path=folder))
        except Exception: pass
    def enable(self, e: StartupEntry):
        return self._enable_reg(e) if e.kind=="registry" else self._enable_shortcut(e)
    def disable(self, e: StartupEntry):
        return self._disable_reg(e) if e.kind=="registry" else self._disable_shortcut(e)
    def _disable_reg(self, e):
        try:
            hive = winreg.HKEY_CURRENT_USER if e.hive=="HKCU" else winreg.HKEY_LOCAL_MACHINE
            with winreg.OpenKey(hive, e.path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as run:
                val, typ = winreg.QueryValueEx(run, e.name)
                bk_path = f"{self.DISABLED_KEY}\\{e.source}"
                with winreg.CreateKey(hive, bk_path) as bk:
                    winreg.SetValueEx(bk, e.name, 0, typ, val)
                winreg.DeleteValue(run, e.name)
            return True
        except Exception:
            return False
    def _enable_reg(self, e):
        try:
            hive = winreg.HKEY_CURRENT_USER if e.hive=="HKCU" else winreg.HKEY_LOCAL_MACHINE
            bk_path = f"{self.DISABLED_KEY}\\{e.source}"
            with winreg.OpenKey(hive, bk_path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as bk:
                val, typ = winreg.QueryValueEx(bk, e.name)
                with winreg.OpenKey(hive, e.path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as run:
                    winreg.SetValueEx(run, e.name, 0, typ, val)
                winreg.DeleteValue(bk, e.name)
            return True
        except Exception:
            return False
    def _disable_shortcut(self, e):
        try:
            src = os.path.join(e.path, e.name) if e.enabled else e.command
            disabled_dir = os.path.join(e.path, "Disabled by OptiCores")
            os.makedirs(disabled_dir, exist_ok=True)
            shutil.move(src, os.path.join(disabled_dir, os.path.basename(src)))
            return True
        except Exception: return False
    def _enable_shortcut(self, e):
        try:
            disabled_dir = os.path.join(e.path, "Disabled by OptiCores")
            src = e.command
            shutil.move(src, os.path.join(e.path, os.path.basename(src)))
            return True
        except Exception: return False

STARTUP = StartupManager()

# ---------- Rules / Automation ----------
DEFAULT_RULES = [
    {"pattern": "chrome.exe", "when": "background_cpu>30", "action": "lower_priority"},
    {"pattern": "updater",    "when": "always",            "action": "eco_throttle"},
]
def parse_condition(cond, cpu, role):
    if cond == "always": return True
    try:
        side, rest = cond.split("_", 1)
        metric, val = rest.split(">")
        val = float(val)
        if metric != "cpu": return False
        if side == "background" and role == "Background":
            return cpu > val
        if side == "foreground" and role == "Foreground":
            return cpu > val
    except Exception:
        pass
    return False

# ---------- App ----------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1350x910")
        self.minsize(1180, 820)

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.core_count = multiprocessing.cpu_count()
        self.sort_key = "CPU"
        self.search_term = ""
        self._stop = False

        self.bg_gov = BackgroundGovernor()
        self.health = HealthWatcher()

        self.cpu_snap = {}
        self.cpu_lock = threading.Lock()

        self.rules = DEFAULT_RULES.copy()
        self.startup_item_map = {}  # iid -> StartupEntry

        # Settings / user state
        self.settings = {
            "thresholds": dict(DEFAULT_THRESH),
            "custom_whitelist": [],
            "refresh_sec": DEFAULT_REFRESH_SEC,
            "logo_path": os.path.join("/mnt/data", "88b52a2c-dccd-4240-9f3b-4cb09171fab8.png")  # optional
        }

        # Advisor state
        self._adv_fixes = []           # list of (action, pid, reason)
        self.adv_rows = {}             # iid -> (action, pid, name)

        # Selection state
        self.last_selected_pid = None

        # Insights time series
        self.ts_len = 120
        self.ts_cpu = deque([0]*self.ts_len, maxlen=self.ts_len)
        self.ts_ram = deque([0]*self.ts_len, maxlen=self.ts_len)
        self.ts_gpu = deque([0]*self.ts_len, maxlen=self.ts_len)

        self.current_profile = "Everyday"

        self._build_styles()
        self._build_ui()
        self._load_config()

        # warm-up CPU%
        for p in psutil.process_iter():
            try: p.cpu_percent(interval=None)
            except Exception: pass

        # loops
        threading.Thread(target=self._loop_update_cpu, daemon=True).start()
        threading.Thread(target=self._loop_refresh_ui, daemon=True).start()
        threading.Thread(target=self._loop_follow_foreground, daemon=True).start()
        threading.Thread(target=self._loop_effects_finalize, daemon=True).start()
        threading.Thread(target=self._loop_rules, daemon=True).start()

        if not is_admin():
            self._toast("Tip: run as Administrator to enable all actions.", "warn")
        self.after(800, self._show_quick_tour_once)

    # ---------- styles & layout ----------
    def _build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Tbl.Treeview",
            background="#0B0F14", fieldbackground="#0B0F14", foreground="white",
            rowheight=30, font=("Segoe UI", 10)
        )
        style.configure("Tbl.Treeview.Heading",
            background="#151A21", foreground="white", font=("Segoe UI", 11, "bold")
        )
        style.map("Tbl.Treeview", background=[("selected", "#4F46E5")])

    def _card(self, parent, title, initial="—"):
        f = ctk.CTkFrame(parent, corner_radius=16)
        ctk.CTkLabel(f, text=title, text_color="#9BA3AF").pack(anchor="w", padx=14, pady=(10,0))
        val = ctk.CTkLabel(f, text=initial, font=ctk.CTkFont(size=24, weight="bold"))
        val.pack(anchor="w", padx=14, pady=(0,10))
        return f, val

    def _build_ui(self):
        # Top bar
        top = ctk.CTkFrame(self, corner_radius=0)
        top.grid(row=0, column=0, columnspan=12, sticky="ew")
        for i in range(12): top.grid_columnconfigure(i, weight=1)

        # Logo (if available)
        img_widget = None
        if Image and self.settings.get("logo_path") and os.path.exists(self.settings["logo_path"]):
            try:
                logo_img = ctk.CTkImage(Image.open(self.settings["logo_path"]).resize((28, 28)))
                img_widget = ctk.CTkLabel(top, image=logo_img, text="")
                img_widget.grid(row=0, column=0, padx=(12,4), pady=10, sticky="w")
            except Exception:
                img_widget = None

        ctk.CTkLabel(top, text=APP_NAME, font=ctk.CTkFont(size=22, weight="bold")).grid(
            row=0, column=1 if img_widget else 0, padx=(6 if img_widget else 16), pady=10, sticky="w"
        )

        self.entry_search = ctk.CTkEntry(top, placeholder_text="Search process (name or PID)…", width=340)
        self.entry_search.grid(row=0, column=3, columnspan=3, padx=8, pady=10, sticky="e")
        self.entry_search.bind("<KeyRelease>", lambda e: self._on_search())
        ToolTip(self.entry_search, "Filter by process name or PID.")

        self.seg_sort = ctk.CTkSegmentedButton(top, values=["CPU","Memory","PID","Name"], command=self._on_sort)
        self.seg_sort.set("CPU"); self.seg_sort.grid(row=0, column=6, padx=8, pady=10, sticky="e")
        info = ctk.CTkLabel(top, text="ⓘ", width=18, text_color="#9BA3AF")
        info.grid(row=0, column=7, padx=(0,8), pady=10, sticky="w")
        ToolTip(info, "Sort the table by CPU, Memory, PID, or Name.")

        self.switch_theme = ctk.CTkSwitch(top, text="Light mode", command=self._toggle_theme)
        self.switch_theme.grid(row=0, column=8, padx=8, pady=10, sticky="e")
        ToolTip(self.switch_theme, "Toggle light/dark theme.")

        # Stat cards
        cards = ctk.CTkFrame(self, corner_radius=0)
        cards.grid(row=1, column=0, columnspan=12, padx=16, pady=(4,0), sticky="ew")
        cards.grid_columnconfigure((0,1,2,3), weight=1)
        self.card_cpu, self.val_cpu = self._card(cards, "CPU", "--%")
        self.card_mem, self.val_mem = self._card(cards, "RAM", "--%")
        self.card_gpu, self.val_gpu = self._card(cards, "GPU", "N/A")
        self.card_fg,  self.val_fg  = self._card(cards, "Foreground App", "—")
        self.card_cpu.grid(row=0, column=0, padx=6, sticky="ew")
        self.card_mem.grid(row=0, column=1, padx=6, sticky="ew")
        self.card_gpu.grid(row=0, column=2, padx=6, sticky="ew")
        self.card_fg.grid(row=0, column=3, padx=6, sticky="ew")

        # Body split: LEFT table, RIGHT tabs
        body = ctk.CTkFrame(self)
        body.grid(row=2, column=0, columnspan=12, padx=16, pady=10, sticky="nsew")
        self.grid_rowconfigure(2, weight=1)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)

        # LEFT: Process table (single-select)
        left = ctk.CTkFrame(body, corner_radius=16)
        left.grid(row=0, column=0, sticky="nsew", padx=(0,8))
        left.grid_rowconfigure(0, weight=1); left.grid_columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            left, style="Tbl.Treeview",
            columns=("PID","Name","CPU","Memory","Flags","Role"),
            show="headings", selectmode="browse"
        )
        for col, w in (("PID",90), ("Name",360), ("CPU",100), ("Memory",140), ("Flags",160), ("Role",120)):
            self.tree.heading(col, text=col); self.tree.column(col, anchor="center", width=w, stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())
        ToolTip(self.tree, "Select one process to optimize or manage.")

        # RIGHT: Tabs
        right = ctk.CTkTabview(body, corner_radius=16)
        right.grid(row=0, column=1, sticky="nsew", padx=(8,0))
        tab_opt   = right.add("Optimize")
        tab_prof  = right.add("Profiles")
        tab_start = right.add("Startup")
        tab_ins   = right.add("Insights")
        tab_rules = right.add("Rules")
        tab_adv   = right.add("Advisor")
        tab_sets  = right.add("Settings")
        tab_rep   = right.add("Reports")
        tab_help  = right.add("Help")

        # Optimize tab
        ctk.CTkLabel(tab_opt, text="Selected", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(10,4))
        self.lbl_sel = ctk.CTkLabel(tab_opt, text="—", text_color="#9BA3AF"); self.lbl_sel.pack(anchor="w", padx=12)

        row = ctk.CTkFrame(tab_opt); row.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(row, text="CPU Priority").pack(side="left")
        self.cb_pri = ctk.CTkComboBox(row, values=PRIORITY_KEYS, width=170)
        self.cb_pri.set("Above Normal"); self.cb_pri.pack(side="left", padx=6)
        ctk.CTkButton(tab_opt, text="Apply Priority", command=lambda: self._act_priority()).pack(fill="x", padx=12, pady=4)

        row2 = ctk.CTkFrame(tab_opt); row2.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(row2, text="Memory Priority").pack(side="left")
        self.cb_memprio = ctk.CTkComboBox(row2, values=["VeryLow 1","Low 2","Medium 3","High 4"], width=170)
        self.cb_memprio.set("High 4"); self.cb_memprio.pack(side="left", padx=6)
        ctk.CTkButton(tab_opt, text="Apply Memory Priority", command=lambda: self._act_memprio()).pack(fill="x", padx=12, pady=4)

        ctk.CTkButton(tab_opt, text="Trim RAM", command=lambda: self._act_trim()).pack(fill="x", padx=12, pady=4)

        row3 = ctk.CTkFrame(tab_opt); row3.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(row3, text="Affinity Preset").pack(side="left")
        self.cb_aff = ctk.CTkComboBox(row3, values=["All cores","Half cores even","Half cores odd","First 2 cores"], width=170)
        self.cb_aff.set("All cores"); self.cb_aff.pack(side="left", padx=6)
        ctk.CTkButton(tab_opt, text="Apply Affinity", command=lambda: self._act_affinity()).pack(fill="x", padx=12, pady=4)

        btns1 = ctk.CTkFrame(tab_opt); btns1.pack(fill="x", padx=12, pady=6)
        ctk.CTkButton(btns1, text="Suspend", command=lambda: self._act_suspend()).pack(side="left", expand=True, fill="x", padx=(0,6))
        ctk.CTkButton(btns1, text="Resume",  command=lambda: self._act_resume()).pack(side="left", expand=True, fill="x", padx=6)
        ctk.CTkButton(btns1, text="Kill", fg_color="#ef4444", hover_color="#dc2626",
                      command=lambda: self._act_kill()).pack(side="left", expand=True, fill="x", padx=(6,0))

        btns2 = ctk.CTkFrame(tab_opt); btns2.pack(fill="x", padx=12, pady=6)
        self.chk_game = ctk.CTkSwitch(btns2, text="🎮 Game Mode (boost FG + High Perf plan)", command=self._toggle_game)
        self.chk_gov  = ctk.CTkSwitch(btns2, text="Background Governor (reduce noise)", command=self._toggle_governor)
        self.chk_game.pack(side="left", padx=6); self.chk_gov.pack(side="left", padx=12)
        ctk.CTkButton(tab_opt, text="Revert Changes", fg_color="#374151", command=lambda: self._act_revert()).pack(fill="x", padx=12, pady=(2,8))

        ctk.CTkLabel(tab_opt, text="Effects (impact of recent actions)", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=12)
        self.txt_effects = ctk.CTkTextbox(tab_opt, height=160); self.txt_effects.pack(fill="both", expand=False, padx=12, pady=(2,12))
        ToolTip(self.txt_effects, "After an action, we measure CPU/RAM change and summarize here.")

        # Profiles tab — cards
        self.prof_header = ctk.CTkLabel(tab_prof, text="Current Profile: Everyday", font=ctk.CTkFont(size=16, weight="bold"))
        self.prof_header.pack(anchor="w", padx=12, pady=(12,6))
        grid = ctk.CTkFrame(tab_prof); grid.pack(fill="x", padx=12, pady=(4,12))
        for i in range(3): grid.grid_columnconfigure(i, weight=1)

        def make_prof_card(col, name):
            card = ctk.CTkFrame(grid, corner_radius=16)
            card.grid(row=0, column=col, padx=6, sticky="nsew")
            ctk.CTkLabel(card, text=name, font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=12, pady=(10,4))
            ctk.CTkLabel(card, text=PROFILES[name]["desc"], wraplength=280, justify="left").pack(anchor="w", padx=12, pady=(0,8))
            ctk.CTkButton(card, text="Use", command=lambda n=name: self._apply_profile_named(n)).pack(padx=12, pady=(0,12), fill="x")
        make_prof_card(0, "Gaming")
        make_prof_card(1, "Creator")
        make_prof_card(2, "Everyday")

        # Startup tab
        ctk.CTkLabel(tab_start, text="Startup Apps", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(12,6))
        self.tree_start = ttk.Treeview(tab_start, style="Tbl.Treeview", columns=("Source","Name","Command","Enabled"), show="headings", height=10, selectmode="extended")
        for col, w in (("Source",160), ("Name",220), ("Command",520), ("Enabled",100)):
            self.tree_start.heading(col, text=col); self.tree_start.column(col, anchor="center", width=w, stretch=True)
        self.tree_start.pack(fill="x", padx=12, pady=8)
        ToolTip(self.tree_start, "Toggle items to run at login (registry + startup folders). Reversible.")
        btns = ctk.CTkFrame(tab_start); btns.pack(fill="x", padx=12, pady=(0,12))
        ctk.CTkButton(btns, text="Refresh", command=lambda: self._refresh_startup()).pack(side="left", padx=(0,6))
        ctk.CTkButton(btns, text="Enable",  command=lambda: self._toggle_startup(True)).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="Disable", command=lambda: self._toggle_startup(False)).pack(side="left", padx=6)

        # Insights tab — graphs
        ins = ctk.CTkFrame(tab_ins, corner_radius=16)
        ins.pack(fill="both", expand=True, padx=8, pady=8)
        ctk.CTkLabel(ins, text="Live Metrics (CPU / RAM / GPU)", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(12,0))
        fig = Figure(figsize=(6.4,3.0), dpi=100)
        self.ax = fig.add_subplot(111)
        self.ax.set_ylim(0, 100)
        self.ax.set_ylabel("%"); self.ax.set_xlabel("samples")
        self.line_cpu, = self.ax.plot(list(self.ts_cpu), label="CPU")
        self.line_ram, = self.ax.plot(list(self.ts_ram), label="RAM")
        self.line_gpu, = self.ax.plot(list(self.ts_gpu), label="GPU")
        self.ax.legend(loc="upper right", fontsize=8)
        self.canvas = FigureCanvasTkAgg(fig, master=ins)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=12, pady=12)

        # Rules tab — JIGSAW builder (no typing)
        ctk.CTkLabel(tab_rules, text="Automation Rules (pick & add)", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(12,4))
        self.tree_rules = ttk.Treeview(tab_rules, style="Tbl.Treeview", columns=("Pattern","When","Action"), show="headings", height=8, selectmode="browse")
        for col, w in (("Pattern",260), ("When",220), ("Action",200)):
            self.tree_rules.heading(col, text=col); self.tree_rules.column(col, anchor="center", width=w, stretch=True)
        self.tree_rules.pack(fill="x", padx=12, pady=(4,8))
        self._refresh_rules_tree()

        jig = ctk.CTkFrame(tab_rules); jig.pack(fill="x", padx=12, pady=(2,12))
        jig.grid_columnconfigure((0,1,2,3,4,5), weight=1)

        ctk.CTkLabel(jig, text="Pattern").grid(row=0, column=0, sticky="w", padx=(0,6))
        self.cb_rule_pattern = ctk.CTkComboBox(jig, values=self._rule_pattern_choices(), width=220)
        self.cb_rule_pattern.grid(row=1, column=0, sticky="we", padx=(0,6), pady=(0,6))

        ctk.CTkLabel(jig, text="Scope").grid(row=0, column=1, sticky="w", padx=6)
        self.cb_rule_scope = ctk.CTkComboBox(jig, values=["Always","Foreground","Background"], width=150)
        self.cb_rule_scope.set("Background")
        self.cb_rule_scope.grid(row=1, column=1, sticky="we", padx=6, pady=(0,6))

        ctk.CTkLabel(jig, text="Metric").grid(row=0, column=2, sticky="w", padx=6)
        self.lbl_metric = ctk.CTkLabel(jig, text="CPU >")
        self.lbl_metric.grid(row=1, column=2, sticky="w", padx=6, pady=(0,6))

        ctk.CTkLabel(jig, text="Value").grid(row=0, column=3, sticky="w", padx=6)
        self.rule_val_label = ctk.CTkLabel(jig, text="30")
        self.rule_val_label.grid(row=1, column=3, sticky="e", padx=(0,6), pady=(0,6))
        self.slider_rule_value = ctk.CTkSlider(jig, from_=1, to=95, number_of_steps=94, command=self._on_rule_slider)
        self.slider_rule_value.set(30)
        self.slider_rule_value.grid(row=1, column=4, sticky="we", padx=6, pady=(0,6))

        ctk.CTkLabel(jig, text="Action").grid(row=0, column=5, sticky="w", padx=6)
        self.cb_rule_action = ctk.CTkComboBox(jig, values=["lower_priority","trim","eco_throttle","kill"], width=160)
        self.cb_rule_action.set("lower_priority")
        self.cb_rule_action.grid(row=1, column=5, sticky="we", padx=6, pady=(0,6))

        btnrow = ctk.CTkFrame(tab_rules); btnrow.pack(fill="x", padx=12, pady=(0,12))
        ctk.CTkButton(btnrow, text="Refresh Patterns", command=lambda: self._refresh_rule_patterns()).pack(side="left")
        ctk.CTkButton(btnrow, text="Add Rule", command=lambda: self._add_rule()).pack(side="left", padx=8)

        # Advisor tab — table view
        ctk.CTkLabel(tab_adv, text="Advisor (auto suggestions)", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(12,6))
        self.tree_adv = ttk.Treeview(tab_adv, style="Tbl.Treeview",
                                     columns=("PID","Name","Issue","Suggested"),
                                     show="headings", height=10, selectmode="extended")
        for col, w in (("PID",80), ("Name",220), ("Issue",280), ("Suggested",200)):
            self.tree_adv.heading(col, text=col); self.tree_adv.column(col, anchor="center", width=w, stretch=True)
        self.tree_adv.pack(fill="both", expand=True, padx=12, pady=(2,8))
        advbtns = ctk.CTkFrame(tab_adv); advbtns.pack(fill="x", padx=12, pady=(0,12))
        ctk.CTkButton(advbtns, text="Generate Suggestions", command=lambda: self._refresh_advisor()).pack(side="left")
        ctk.CTkButton(advbtns, text="Apply Selected", command=lambda: self._apply_selected_adv()).pack(side="left", padx=8)
        ctk.CTkButton(advbtns, text="Apply All Safe", command=lambda: self._apply_all_safe()).pack(side="left", padx=8)

        # Settings tab — thresholds + whitelist + REFRESH slider
        ctk.CTkLabel(tab_sets, text="Settings", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(12,6))
        row_s1 = ctk.CTkFrame(tab_sets); row_s1.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(row_s1, text="Background CPU high (%)").pack(side="left")
        self.ent_bgcpu = ctk.CTkEntry(row_s1, width=120); self.ent_bgcpu.pack(side="left", padx=8)
        ctk.CTkLabel(row_s1, text="Heavy RAM (MB)").pack(side="left", padx=(16,0))
        self.ent_heavyram = ctk.CTkEntry(row_s1, width=120); self.ent_heavyram.pack(side="left", padx=8)
        ctk.CTkButton(row_s1, text="Save Thresholds", command=lambda: self._save_thresholds()).pack(side="left", padx=12)

        # Auto refresh slider
        row_rf = ctk.CTkFrame(tab_sets); row_rf.pack(fill="x", padx=12, pady=(6,6))
        ctk.CTkLabel(row_rf, text="Auto refresh interval (seconds)").pack(side="left")
        self.lbl_refresh = ctk.CTkLabel(row_rf, text=f"{DEFAULT_REFRESH_SEC:.0f}")
        self.lbl_refresh.pack(side="right", padx=(8,0))
        self.slider_refresh = ctk.CTkSlider(row_rf, from_=1, to=10, number_of_steps=9, command=self._on_refresh_slider)
        self.slider_refresh.pack(side="right", padx=8, fill="x", expand=True)

        ctk.CTkLabel(tab_sets, text="Custom Whitelist (names, comma-separated)").pack(anchor="w", padx=12, pady=(8,0))
        self.ent_whitelist = ctk.CTkEntry(tab_sets, placeholder_text="e.g., steam.exe, epicgameslauncher.exe")
        self.ent_whitelist.pack(fill="x", padx=12, pady=6)
        btnw = ctk.CTkFrame(tab_sets); btnw.pack(fill="x", padx=12, pady=(0,12))
        ctk.CTkButton(btnw, text="Save Whitelist", command=lambda: self._save_whitelist()).pack(side="left")
        ctk.CTkButton(btnw, text="Add selected to Whitelist", command=lambda: self._add_selected_to_whitelist()).pack(side="left", padx=8)

        # Reports tab
        ctk.CTkLabel(tab_rep, text="Reports & Logs", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(12,6))
        ctk.CTkButton(tab_rep, text="Export current snapshot (CSV)", command=lambda: self._export_snapshot()).pack(anchor="w", padx=12, pady=6)
        ctk.CTkButton(tab_rep, text="Export effects log (JSON)", command=lambda: self._export_effects()).pack(anchor="w", padx=12, pady=(0,8))
        ctk.CTkLabel(tab_rep, text="Activity Log").pack(anchor="w", padx=12)
        self.txt_log = ctk.CTkTextbox(tab_rep, height=280); self.txt_log.pack(fill="both", expand=True, padx=12, pady=(4,12))

        # Help tab
        helpbox = ctk.CTkTextbox(tab_help)
        helpbox.pack(fill="both", expand=True, padx=12, pady=12)
        helpbox.insert("end",
            "Welcome to OptiCores\n"
            "• LEFT: Dashboard — select a process; watch CPU/RAM/GPU cards.\n"
            "• RIGHT tabs:\n"
            "   - Optimize: Priority, Memory priority, Trim, Affinity, Suspend/Resume, Kill, Game Mode, Governor, Revert.\n"
            "   - Profiles: Gaming/Creator/Everyday quick cards.\n"
            "   - Startup: Enable/disable login apps.\n"
            "   - Insights: Live CPU/RAM/GPU graphs.\n"
            "   - Rules: Jigsaw builder (Pattern + Scope + Value + Action).\n"
            "   - Advisor: Column suggestions; apply selected/all.\n"
            "   - Settings: Thresholds, whitelist, auto-refresh interval.\n"
            "   - Reports: Export snapshot/effects, view activity log.\n\n"
            "Notes\n"
            "• Actions are real. Run as Administrator for full control.\n"
            "• Effects panel shows measured CPU/RAM deltas after actions + important events.\n"
            "• Revert restores changes OptiCores made (priority/memprio/affinity).\n"
        )
        helpbox.configure(state="disabled")

    # ---------- toast ----------
    def _toast(self, text, kind="ok"):
        top = ctk.CTkToplevel(self); top.overrideredirect(True); top.after(2600, top.destroy)
        color = "#16a34a" if kind=="ok" else "#f59e0b" if kind=="warn" else "#ef4444"
        frame = ctk.CTkFrame(top, corner_radius=12, fg_color=color)
        ctk.CTkLabel(frame, text=text, font=ctk.CTkFont(size=13, weight="bold"), text_color="white").pack(padx=14, pady=10)
        frame.pack()
        self.update_idletasks()
        try:
            x = self.winfo_x() + self.winfo_width() - 320
            y = self.winfo_y() + self.winfo_height() - 140
            top.geometry(f"+{x}+{y}")
        except Exception:
            pass

    # ---------- quick tour ----------
    def _show_quick_tour_once(self):
        cfg = {}
        try:
            if os.path.exists(CONFIG_PATH): cfg = json.load(open(CONFIG_PATH,"r",encoding="utf-8"))
        except Exception: cfg = {}
        if not cfg.get("tour_done"):
            self._show_quick_tour()
            cfg["tour_done"] = True
            try: json.dump(cfg, open(CONFIG_PATH,"w",encoding="utf-8"), indent=2)
            except Exception: pass

    def _show_quick_tour(self):
        tip = ctk.CTkToplevel(self); tip.title("Quick Tour"); tip.geometry("560x500"); tip.grab_set()
        frame = ctk.CTkFrame(tip, corner_radius=16); frame.pack(fill="both", expand=True, padx=12, pady=12)
        ctk.CTkLabel(frame, text="Welcome to OptiCores", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(10,6))
        msg = (
            "Layout:\n"
            "• LEFT: Dashboard table.\n"
            "• RIGHT: Optimize | Profiles | Startup | Insights | Rules | Advisor | Settings | Reports | Help.\n\n"
            "Flow:\n"
            "1) Select a process on the left.\n"
            "2) Use Optimize to apply actions.\n"
            "3) Check Effects panel and graphs in Insights.\n"
            "4) Use Advisor to apply safe fixes in one click.\n"
            "5) Tweak thresholds/whitelist/refresh in Settings.\n"
        )
        ctk.CTkLabel(frame, text=msg, justify="left", wraplength=520).pack(padx=12, pady=6)
        ctk.CTkButton(frame, text="Got it", command=tip.destroy).pack(pady=10)

    # ---------- config ----------
    def _load_config(self):
        try:
            if os.path.exists(CONFIG_PATH):
                cfg = json.load(open(CONFIG_PATH, "r", encoding="utf-8"))
                theme = cfg.get("theme", "Dark")
                ctk.set_appearance_mode(theme)
                saved_rules = cfg.get("rules")
                if isinstance(saved_rules, list):
                    self.rules = saved_rules
                st = cfg.get("settings")
                if isinstance(st, dict):
                    self.settings["thresholds"].update(st.get("thresholds", {}))
                    self.settings["custom_whitelist"] = st.get("custom_whitelist", [])
                    self.settings["refresh_sec"] = float(st.get("refresh_sec", DEFAULT_REFRESH_SEC))
                    self.settings["logo_path"] = st.get("logo_path", self.settings["logo_path"])
        except Exception:
            pass

        # seed Settings UI
        self.ent_bgcpu.delete(0, "end"); self.ent_bgcpu.insert(0, str(self.settings["thresholds"]["bg_cpu"]))
        self.ent_heavyram.delete(0, "end"); self.ent_heavyram.insert(0, str(self.settings["thresholds"]["heavy_ram_mb"]))
        self.ent_whitelist.delete(0, "end"); self.ent_whitelist.insert(0, ", ".join(self.settings["custom_whitelist"]))
        try:
            self.slider_refresh.set(float(self.settings["refresh_sec"]))
            self.lbl_refresh.configure(text=f"{float(self.settings['refresh_sec']):.0f}")
        except Exception:
            pass
        self._refresh_rules_tree()

    def _save_config(self):
        cfg = {"theme": ctk.get_appearance_mode(), "rules": self.rules, "settings": self.settings}
        try:
            json.dump(cfg, open(CONFIG_PATH, "w", encoding="utf-8"), indent=2)
        except Exception:
            pass

    # ---------- loops ----------
    def _loop_update_cpu(self):
        while not self._stop:
            snap = {}
            for p in psutil.process_iter(["pid"]):
                try: snap[p.info["pid"]] = p.cpu_percent(interval=None) / max(1,self.core_count)
                except Exception: pass
            with self.cpu_lock: self.cpu_snap = snap
            time.sleep(1.0)

    def _loop_refresh_ui(self):
        while not self._stop:
            self.after(0, self._refresh_all)
            try:
                interval = max(1.0, float(self.settings.get("refresh_sec", DEFAULT_REFRESH_SEC)))
            except Exception:
                interval = DEFAULT_REFRESH_SEC
            time.sleep(interval)

    def _loop_follow_foreground(self):
        while not self._stop:
            try:
                if self.chk_game.get():
                    pid = fg_pid()
                    if pid: self._boost_foreground(pid)
            except Exception: pass
            time.sleep(2)

    def _loop_effects_finalize(self):
        while not self._stop:
            time.sleep(6)
            for (pid, action), base in list(EFFECTS.pending.items()):
                try:
                    p = psutil.Process(pid)
                    cpu = p.cpu_percent(interval=None) / max(1, self.core_count)
                    mem = (p.memory_info().rss or 0) / (1024*1024)
                    rec = EFFECTS.finalize(pid, action, cpu, mem)
                    if rec:
                        sign_cpu = "↓" if rec["d_cpu"] < 0 else "↑"
                        sign_mem = "↓" if rec["d_mem"] < 0 else "↑"
                        self._append_effect(f"{action} on PID {pid}: CPU {sign_cpu}{abs(rec['d_cpu']):.1f}%, MEM {sign_mem}{abs(rec['d_mem']):.0f} MB")
                except Exception: pass

    def _loop_rules(self):
        while not self._stop:
            try:
                snap = self._snap()
                fpid = fg_pid()
                uwhitelist = set(n.strip().lower() for n in self.settings["custom_whitelist"])
                for p in psutil.process_iter(["pid","name"]):
                    try:
                        name = (p.info["name"] or "").lower()
                        if name in (n.lower() for n in SYSTEM_WHITELIST): continue
                        if name in uwhitelist: continue
                        pid  = p.info["pid"]
                        cpu  = snap.get(pid, 0.0)
                        role = "Foreground" if fpid and pid == fpid else "Background"
                        for r in self.rules:
                            pat = (r.get("pattern") or "").lower()
                            if pat and pat not in name: continue
                            cond = r.get("when", "always")
                            if parse_condition(cond, cpu, role):
                                self._apply_rule_action(pid, r.get("action","").lower())
                    except Exception:
                        continue
            except Exception:
                pass
            time.sleep(5)

    # ---------- events ----------
    def _toggle_theme(self):
        if self.switch_theme.get():
            ctk.set_appearance_mode("Light"); self.switch_theme.configure(text="Dark mode")
        else:
            ctk.set_appearance_mode("Dark"); self.switch_theme.configure(text="Light mode")
        self._save_config()

    def _on_sort(self, *_):
        self.sort_key = self.seg_sort.get()
        self._refresh_table()

    def _on_search(self):
        self.search_term = self.entry_search.get().strip().lower()
        self._refresh_table()

    def _on_select(self):
        sel = self.tree.selection()
        if not sel:
            self.lbl_sel.configure(text="—")
            self.last_selected_pid = None
            return
        try:
            pid, name, *_ = self.tree.item(sel[0], "values")
            self.last_selected_pid = int(pid)
            self.lbl_sel.configure(text=f"PID {pid} — {name}")
        except Exception:
            self.last_selected_pid = None

    def _toggle_game(self):
        if self.chk_game.get():
            switch_power_plan("HIGH")
            self._log("Game Mode ON — High Performance plan applied; FG app will be boosted.")
            self._append_effect("Game Mode enabled: High Performance plan + FG boost.")
        else:
            switch_power_plan("BALANCED")
            self._log("Game Mode OFF — Balanced plan applied.")
            self._append_effect("Game Mode disabled: Balanced plan restored.")

    def _toggle_governor(self):
        self.bg_gov.enabled = bool(self.chk_gov.get())
        state = "ENABLED" if self.bg_gov.enabled else "DISABLED"
        self._log(f"Background Governor {state}")
        self._append_effect(f"Background Governor {state.lower()}.")

    # ---------- refresh ----------
    def _snap(self):
        with self.cpu_lock: return dict(self.cpu_snap)

    def _refresh_all(self):
        try:
            self.val_cpu.configure(text=f"{psutil.cpu_percent():.1f}%")
            self.val_mem.configure(text=f"{psutil.virtual_memory().percent:.1f}%")
            self.ts_cpu.append(psutil.cpu_percent(interval=None))
            self.ts_ram.append(psutil.virtual_memory().percent)
        except Exception: pass
        try:
            if GPUtil:
                g = GPUtil.getGPUs()
                gpu = g[0].load * 100 if g else 0.0
                self.val_gpu.configure(text=f"{gpu:.1f}%" if g else "N/A")
                self.ts_gpu.append(gpu)
            else:
                self.val_gpu.configure(text="N/A"); self.ts_gpu.append(0.0)
        except Exception:
            self.val_gpu.configure(text="N/A"); self.ts_gpu.append(0.0)

        pid = fg_pid()
        if pid:
            try: self.val_fg.configure(text=psutil.Process(pid).name())
            except Exception: self.val_fg.configure(text=f"PID {pid}")
        else:
            self.val_fg.configure(text="—")

        if hasattr(self, "canvas"):
            self.line_cpu.set_ydata(list(self.ts_cpu))
            self.line_ram.set_ydata(list(self.ts_ram))
            self.line_gpu.set_ydata(list(self.ts_gpu))
            self.canvas.draw_idle()

        self._refresh_table()

    def _refresh_table(self):
        snap = self._snap()
        term = self.search_term
        rows = []
        fpid = fg_pid()
        user_wl = [n.strip().lower() for n in self.settings["custom_whitelist"]]

        for p in psutil.process_iter(["pid","name","memory_info"]):
            try:
                name = p.info["name"] or ""
                lname = name.lower()
                if name in SYSTEM_WHITELIST or lname in user_wl: continue
                pid = p.info["pid"]
                if term and (term not in lname and term not in str(pid)): continue
                cpu = snap.get(pid, 0.0)
                rss_mb = (p.info["memory_info"].rss or 0) / (1024*1024)
                role = "Foreground" if fpid and pid == fpid else "Background"
                self.health.ingest(pid, rss_mb, cpu)
                flags = self.health.get_flags(pid)
                flag_str = ", ".join(k for k,v in flags.items() if v) or "-"
                rows.append((pid, name, cpu, rss_mb, flag_str, role))
            except Exception:
                continue

        key_map = {
            "CPU": lambda x: x[2],
            "Memory": lambda x: x[3],
            "PID": lambda x: x[0],
            "Name": lambda x: x[1].lower()
        }
        rows.sort(key=key_map.get(self.sort_key, key_map["CPU"]), reverse=True)

        current_selection_pid = self.last_selected_pid
        for i in self.tree.get_children(): self.tree.delete(i)
        iid_for_pid = {}
        for pid, name, cpu, mem, flags, role in rows:
            iid = self.tree.insert("", "end", values=(pid, name, f"{cpu:.1f}%", f"{mem:.0f} MB", flags, role))
            iid_for_pid[pid] = iid

        if current_selection_pid and current_selection_pid in iid_for_pid:
            self.tree.selection_set(iid_for_pid[current_selection_pid])
        else:
            self.tree.selection_remove(self.tree.selection())

        if self.bg_gov.enabled:
            for pid, *_ in rows[-25:]:
                self.bg_gov.govern(pid)

    # ---------- Optimize actions ----------
    def _sel_pids(self):
        out = []
        for it in self.tree.selection():
            try: out.append(int(self.tree.item(it, "values")[0]))
            except Exception: pass
        return out

    def _baseline(self, p):
        cpu0 = p.cpu_percent(interval=None)/max(1,self.core_count)
        mem0 = (p.memory_info().rss or 0)/(1024*1024)
        return cpu0, mem0

    def _act_priority(self):
        level = self.cb_pri.get()
        for pid in self._sel_pids():
            try:
                p = psutil.Process(pid)
                if p.name() in SYSTEM_WHITELIST: continue
                cpu0, mem0 = self._baseline(p)
                h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
                old = win32process.GetPriorityClass(h)
                win32process.SetPriorityClass(h, PRIORITY.get(level, win32process.NORMAL_PRIORITY_CLASS))
                UNDO.push(pid, "priority", old)
                EFFECTS.baseline(pid, f"priority→{level}", cpu0, mem0)
                self._toast(f"Priority {level} applied (PID {pid})", "ok")
                self._append_effect(f"Priority set to {level} on PID {pid}.")
            except Exception as e:
                self._toast(f"Priority failed (PID {pid})", "err"); self._log(f"[Priority] PID {pid}: {e}")

    def _act_memprio(self):
        try:
            sel = self.cb_memprio.get().strip().split()[-1]
            level = max(1, min(4, int(sel)))
        except Exception:
            level = 3
        for pid in self._sel_pids():
            try:
                p = psutil.Process(pid)
                if p.name() in SYSTEM_WHITELIST: continue
                cpu0, mem0 = self._baseline(p)
                h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
                set_memory_priority(h, level)
                UNDO.push(pid, "memprio", 3)
                EFFECTS.baseline(pid, f"memprio→{level}", cpu0, mem0)
                self._toast(f"Memory priority {level} applied (PID {pid})", "ok")
                self._append_effect(f"Memory priority {level} set on PID {pid}.")
            except Exception as e:
                self._toast(f"Mem priority failed (PID {pid})", "err"); self._log(f"[MemPrio] PID {pid}: {e}")

    def _act_trim(self):
        for pid in self._sel_pids():
            try:
                p = psutil.Process(pid)
                if p.name() in SYSTEM_WHITELIST: continue
                cpu0, mem0 = self._baseline(p)
                h = open_proc(pid, win32con.PROCESS_SET_QUOTA | win32con.PROCESS_QUERY_INFORMATION)
                UNDO.push(pid, "trim", None)
                empty_working_set(int(h))
                EFFECTS.baseline(pid, "trim", cpu0, mem0)
                self._toast(f"Trimmed working set (PID {pid})", "ok")
                self._append_effect(f"Trim RAM on PID {pid}.")
            except Exception as e:
                self._toast(f"Trim failed (PID {pid})", "err"); self._log(f"[Trim] PID {pid}: {e}")

    def _act_affinity(self):
        preset = self.cb_aff.get()
        for pid in self._sel_pids():
            try:
                p = psutil.Process(pid)
                if p.name() in SYSTEM_WHITELIST: continue
                cpu0, mem0 = self._baseline(p)
                h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
                sys_mask = (1 << self.core_count) - 1
                if preset == "All cores":
                    mask = sys_mask
                elif preset == "Half cores even":
                    mask = sum(1 << i for i in range(self.core_count) if i % 2 == 0)
                elif preset == "Half cores odd":
                    mask = sum(1 << i for i in range(self.core_count) if i % 2 == 1)
                else:  # First 2 cores
                    mask = (1 << min(2, self.core_count)) - 1
                old_aff = win32process.GetProcessAffinityMask(h)[0]
                UNDO.push(pid, "affinity", old_aff)
                win32process.SetProcessAffinityMask(h, mask & sys_mask)
                EFFECTS.baseline(pid, f"affinity→{preset}", cpu0, mem0)
                self._toast(f"Affinity {preset} applied (PID {pid})", "ok")
                self._append_effect(f"Affinity '{preset}' set on PID {pid}.")
            except Exception as e:
                self._toast(f"Affinity failed (PID {pid})", "err"); self._log(f"[Affinity] PID {pid}: {e}")

    def _act_suspend(self):
        for pid in self._sel_pids():
            try:
                p = psutil.Process(pid)
                if p.name() in SYSTEM_WHITELIST: continue
                p.suspend()
                self._toast(f"Suspended PID {pid}", "ok")
                self._append_effect(f"Suspended PID {pid}.")
            except Exception as e:
                self._toast(f"Suspend failed (PID {pid})", "err"); self._log(f"[Suspend] PID {pid}: {e}")

    def _act_resume(self):
        for pid in self._sel_pids():
            try:
                psutil.Process(pid).resume()
                self._toast(f"Resumed PID {pid}", "ok")
                self._append_effect(f"Resumed PID {pid}.")
            except Exception as e:
                self._toast(f"Resume failed (PID {pid})", "err"); self._log(f"[Resume] PID {pid}: {e}")

    def _act_kill(self):
        pids = []
        for pid in self._sel_pids():
            try:
                name = psutil.Process(pid).name()
                if name in SYSTEM_WHITELIST or pid in (os.getpid(), os.getppid()):
                    continue
                pids.append(pid)
            except Exception:
                continue
        if not pids: return self._toast("No safe processes selected.", "warn")
        if not messagebox.askyesno("Confirm", f"Terminate {len(pids)} process(es)?"): return
        for pid in pids:
            try:
                psutil.Process(pid).terminate()
                self._toast(f"Terminated PID {pid}", "ok")
                self._append_effect(f"Killed PID {pid}.")
            except Exception as e:
                self._toast(f"Kill failed (PID {pid})", "err"); self._log(f"[Kill] PID {pid}: {e}")

    def _act_revert(self):
        for pid in self._sel_pids():
            acts = UNDO.pop_for_pid(pid)
            if not acts:
                self._toast(f"No recorded changes for PID {pid}", "warn")
                continue
            try:
                h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
            except Exception:
                continue
            for _, kind, before, _ in acts:
                try:
                    if kind == "priority" and before is not None:
                        win32process.SetPriorityClass(h, before)
                    elif kind == "memprio" and before is not None:
                        set_memory_priority(h, before)
                    elif kind == "affinity" and before is not None:
                        win32process.SetProcessAffinityMask(h, before)
                except Exception:
                    pass
            self._toast(f"Reverted changes (PID {pid})", "ok")
            self._append_effect(f"Reverted changes on PID {pid}.")

    def _boost_foreground(self, pid):
        try:
            h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
            old = win32process.GetPriorityClass(h)
            win32process.SetPriorityClass(h, win32process.HIGH_PRIORITY_CLASS)
            set_memory_priority(h, 4)
            UNDO.push(pid, "priority", old); UNDO.push(pid, "memprio", 3)
        except Exception:
            pass

    # ---------- Rules ----------
    def _apply_rule_action(self, pid, action):
        try:
            if action == "lower_priority":
                h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
                old = win32process.GetPriorityClass(h)
                if old > win32process.BELOW_NORMAL_PRIORITY_CLASS:
                    win32process.SetPriorityClass(h, win32process.BELOW_NORMAL_PRIORITY_CLASS)
                    UNDO.push(pid, "priority", old)
                    self._log(f"[Rule] Lowered priority → PID {pid}")
                    self._append_effect(f"Rule: lowered priority on PID {pid}.")
            elif action == "trim":
                h = open_proc(pid, win32con.PROCESS_SET_QUOTA | win32con.PROCESS_QUERY_INFORMATION)
                empty_working_set(int(h))
                self._log(f"[Rule] Trimmed working set → PID {pid}")
                self._append_effect(f"Rule: trimmed RAM on PID {pid}.")
            elif action == "eco_throttle":
                h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
                set_power_throttle(h, eco_on=True)
                self._log(f"[Rule] Eco throttle on → PID {pid}")
                self._append_effect(f"Rule: eco throttle on PID {pid}.")
            elif action == "kill":
                try:
                    psutil.Process(pid).terminate()
                    self._log(f"[Rule] Terminated PID {pid}")
                    self._append_effect(f"Rule: killed PID {pid}.")
                except Exception as e:
                    self._log(f"[Rule Kill] PID {pid}: {e}")
        except Exception:
            pass

    def _refresh_rules_tree(self):
        for i in self.tree_rules.get_children(): self.tree_rules.delete(i)
        for r in self.rules:
            self.tree_rules.insert("", "end", values=(r.get("pattern",""), r.get("when",""), r.get("action","")))

    def _rule_pattern_choices(self):
        common = ["updater", "launcher", "helper", "chrome.exe", "discord.exe", "teams.exe", "steam.exe"]
        running = set()
        for p in psutil.process_iter(["name"]):
            try:
                nm = (p.info["name"] or "").strip()
                if nm and nm not in SYSTEM_WHITELIST:
                    running.add(nm)
            except Exception:
                pass
        choices = sorted(set(common).union(running))
        return choices[:80] if choices else common

    def _refresh_rule_patterns(self):
        choices = self._rule_pattern_choices()
        try:
            self.cb_rule_pattern.configure(values=choices)
            if choices: self.cb_rule_pattern.set(choices[0])
            self._toast("Patterns refreshed.", "ok")
        except Exception:
            pass

    def _on_rule_slider(self, v):
        try:
            self.rule_val_label.configure(text=f"{float(v):.0f}")
        except Exception:
            pass

    def _add_rule(self):
        pat = self.cb_rule_pattern.get().strip()
        scope = self.cb_rule_scope.get().strip()
        val = int(float(self.rule_val_label.cget("text")))
        act = self.cb_rule_action.get().strip()
        if not pat:
            return self._toast("Pattern is required.", "warn")
        if scope == "Always":
            cond = "always"
        else:
            cond = f"{scope.lower()}_cpu>{val}"
        self.rules.append({"pattern": pat, "when": cond, "action": act})
        self._save_config(); self._refresh_rules_tree()
        self._toast("Rule added.", "ok")
        self._append_effect(f"Rule added: {pat} when {cond} → {act}.")

    # ---------- Startup manager ----------
    def _refresh_startup(self):
        self.startup_item_map.clear()
        for i in self.tree_start.get_children(): self.tree_start.delete(i)
        for e in STARTUP.list():
            iid = self.tree_start.insert("", "end", values=(e.source, e.name, e.command, "Yes" if e.enabled else "No"))
            self.startup_item_map[iid] = e

    def _toggle_startup(self, enable: bool):
        sel = self.tree_start.selection()
        if not sel:
            self._toast("Select startup items first.", "warn"); return
        for iid in sel:
            entry = self.startup_item_map.get(iid)
            if not entry: continue
            ok = STARTUP.enable(entry) if enable else STARTUP.disable(entry)
            if ok:
                entry.enabled = enable
                self.tree_start.set(iid, column="Enabled", value=("Yes" if enable else "No"))
                self._toast(f"{'Enabled' if enable else 'Disabled'}: {entry.name}", "ok")
                self._append_effect(f"Startup {'enabled' if enable else 'disabled'}: {entry.name}.")
            else:
                self._toast(f"Failed: {entry.name}", "err")

    # ---------- Advisor ----------
    def _refresh_advisor(self):
        self._adv_fixes.clear()
        self.adv_rows.clear()
        for i in self.tree_adv.get_children(): self.tree_adv.delete(i)

        t_bg_cpu = float(self.settings["thresholds"].get("bg_cpu", 30.0))
        t_ram_mb = float(self.settings["thresholds"].get("heavy_ram_mb", 800.0))
        snap = self._snap()
        fpid = fg_pid()
        wl = set(n.strip().lower() for n in self.settings["custom_whitelist"])

        vm = psutil.virtual_memory()
        if vm.percent >= 85:
            iid = self.tree_adv.insert("", "end", values=("-", "System", f"RAM high {vm.percent:.0f}%", "Trim heavy BG apps"))
            self.adv_rows[iid] = None  # informational row

        for p in psutil.process_iter(["pid","name","memory_info"]):
            try:
                name = (p.info["name"] or "")
                lname = name.lower()
                if name in SYSTEM_WHITELIST or lname in wl: continue
                pid = p.info["pid"]
                cpu = snap.get(pid, 0.0)
                rss_mb = (p.info["memory_info"].rss or 0)/(1024*1024)
                role = "Foreground" if fpid and pid == fpid else "Background"
                flags = self.health.get_flags(pid)

                # Each suggested action becomes its own row (easy apply)
                if role == "Background" and cpu >= t_bg_cpu:
                    iid = self.tree_adv.insert("", "end", values=(pid, name, f"BG CPU {cpu:.1f}%", "lower_priority"))
                    self.adv_rows[iid] = ("lower_priority", pid, name)
                    iid = self.tree_adv.insert("", "end", values=(pid, name, f"BG CPU {cpu:.1f}%", "eco_throttle"))
                    self.adv_rows[iid] = ("eco_throttle", pid, name)

                if rss_mb >= t_ram_mb:
                    iid = self.tree_adv.insert("", "end", values=(pid, name, f"High RAM {rss_mb:.0f} MB", "trim"))
                    self.adv_rows[iid] = ("trim", pid, name)

                if flags.get("leak"):
                    iid = self.tree_adv.insert("", "end", values=(pid, name, "Mem growth trend", "trim"))
                    self.adv_rows[iid] = ("trim", pid, name)
            except Exception:
                continue

        if not self.tree_adv.get_children():
            self.tree_adv.insert("", "end", values=("-", "-", "System looks good", "—"))

    def _apply_selected_adv(self):
        sel = self.tree_adv.selection()
        if not sel:
            return self._toast("Select suggestion rows first.", "warn")
        applied = 0
        for iid in sel:
            info = self.adv_rows.get(iid)
            if not info: continue
            action, pid, _ = info
            try:
                if action == "lower_priority":
                    self._apply_lower_priority(pid); applied += 1; self._append_effect(f"Advisor: lowered priority on PID {pid}.")
                elif action == "eco_throttle":
                    self._apply_eco(pid); applied += 1; self._append_effect(f"Advisor: eco throttle on PID {pid}.")
                elif action == "trim":
                    self._apply_trim_one(pid); applied += 1; self._append_effect(f"Advisor: trimmed RAM on PID {pid}.")
            except Exception:
                pass
        self._toast(f"Applied {applied} selected fix(es).", "ok")

    def _apply_all_safe(self):
        if not self.adv_rows:
            self._refresh_advisor()
        all_iids = list(self.adv_rows.keys())
        self.tree_adv.selection_set(all_iids)
        self._apply_selected_adv()

    def _apply_lower_priority(self, pid):
        h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
        old = win32process.GetPriorityClass(h)
        if old > win32process.BELOW_NORMAL_PRIORITY_CLASS:
            win32process.SetPriorityClass(h, win32process.BELOW_NORMAL_PRIORITY_CLASS)
            UNDO.push(pid, "priority", old)
            self._log(f"[Advisor] Lowered priority → PID {pid}")

    def _apply_eco(self, pid):
        h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
        set_power_throttle(h, eco_on=True)
        self._log(f"[Advisor] Eco throttle on → PID {pid}")

    def _apply_trim_one(self, pid):
        p = psutil.Process(pid)
        cpu0 = p.cpu_percent(interval=None)/max(1,self.core_count)
        mem0 = (p.memory_info().rss or 0)/(1024*1024)
        h = open_proc(pid, win32con.PROCESS_SET_QUOTA | win32con.PROCESS_QUERY_INFORMATION)
        UNDO.push(pid, "trim", None)
        empty_working_set(int(h))
        EFFECTS.baseline(pid, "trim", cpu0, mem0)
        self._log(f"[Advisor] Trimmed working set → PID {pid}")

    # ---------- Settings handlers ----------
    def _on_refresh_slider(self, value):
        try:
            value = float(value)
            self.settings["refresh_sec"] = value
            self.lbl_refresh.configure(text=f"{value:.0f}")
            self._save_config()
        except Exception:
            pass

    def _save_thresholds(self):
        try:
            self.settings["thresholds"]["bg_cpu"] = float(self.ent_bgcpu.get())
            self.settings["thresholds"]["heavy_ram_mb"] = float(self.ent_heavyram.get())
            self._save_config()
            self._toast("Thresholds saved.", "ok")
            self._append_effect("Thresholds updated.")
        except Exception:
            self._toast("Invalid threshold values.", "err")

    def _save_whitelist(self):
        raw = self.ent_whitelist.get().strip()
        names = [n.strip() for n in raw.split(",") if n.strip()]
        self.settings["custom_whitelist"] = names
        self._save_config()
        self._toast("Whitelist saved.", "ok")
        self._append_effect("Whitelist updated.")
        self._refresh_table()

    def _add_selected_to_whitelist(self):
        sel = self.tree.selection()
        if not sel: return self._toast("Select rows first.", "warn")
        current = set(n.strip().lower() for n in self.settings["custom_whitelist"])
        for it in sel:
            try:
                name = str(self.tree.item(it, "values")[1]).strip()
                if name: current.add(name.lower())
            except Exception:
                pass
        self.settings["custom_whitelist"] = sorted(current)
        self.ent_whitelist.delete(0, "end"); self.ent_whitelist.insert(0, ", ".join(self.settings["custom_whitelist"]))
        self._save_config()
        self._toast("Added to whitelist.", "ok")
        self._append_effect("Added selected to whitelist.")
        self._refresh_table()

    # ---------- Effects display ----------
    def _append_effect(self, line: str):
        try:
            self.txt_effects.insert("end", f"• {line}\n")
            self.txt_effects.see("end")
        except Exception:
            pass

    # ---------- Reports ----------
    def _export_snapshot(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")], initialfile="snapshot.csv")
        if not path: return
        rows = []
        for it in self.tree.get_children():
            rows.append(self.tree.item(it, "values"))
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f); w.writerow(["PID","Name","CPU","Memory","Flags","Role"]); w.writerows(rows)
            self._toast(f"Snapshot saved → {path}", "ok")
        except Exception as e:
            self._toast("Export failed", "err"); self._log(f"[Export snapshot] {e}")

    def _export_effects(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")], initialfile="effects_history.json")
        if not path: return
        try:
            json.dump(EFFECTS.history, open(path, "w", encoding="utf-8"), indent=2)
            self._toast(f"Effects log saved → {path}", "ok")
        except Exception as e:
            self._toast("Export failed", "err"); self._log(f"[Export effects] {e}")

    # ---------- Profiles utils ----------
    def _apply_profile_named(self, name):
        self.current_profile = name
        self._apply_profile()

    def _refresh_profile_box(self):
        # no longer needed (kept for compatibility)
        pass

    def _apply_profile(self):
        name = self.current_profile
        prof = PROFILES.get(name, PROFILES["Everyday"])
        switch_power_plan(prof["plan"])
        self.bg_gov.enabled = bool(prof["gov"])
        self.chk_gov.select() if self.bg_gov.enabled else self.chk_gov.deselect()
        if name == "Gaming":
            if not self.chk_game.get():
                self.chk_game.select(); self._toggle_game()
        else:
            if self.chk_game.get():
                self.chk_game.deselect(); self._toggle_game()
        self.prof_header.configure(text=f"Current Profile: {name}")
        self._log(f"Applied profile: {name}")
        self._append_effect(f"Profile '{name}' applied.")

    # ---------- logging ----------
    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        try:
            self.txt_log.insert("end", f"[{ts}] {msg}\n"); self.txt_log.see("end")
        except Exception:
            print(msg)

    def destroy(self):
        self._stop = True
        self._save_config()
        return super().destroy()

if __name__ == "__main__":
    app = App()
    app.mainloop()
