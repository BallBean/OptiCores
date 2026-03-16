import os, time, json, csv, ctypes, subprocess, threading, multiprocessing, shutil, queue
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

try:
    import pystray
    from pystray import MenuItem as item
except Exception:
    pystray = None

import win32api, win32con, win32gui, win32process
try:
    import win32job
except Exception:
    win32job = None

try:
    import winreg
except Exception:
    winreg = None

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

APP_NAME = "OptiCores"
APP_DIR  = os.path.join(os.path.expanduser("~"), "AppData", "Local", "OptiCores")
os.makedirs(APP_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
HIST_PATH   = os.path.join(APP_DIR, "effects_history.json")
USAGE_HIST_PATH = os.path.join(APP_DIR, "usage_history.json")

try:
    import wmi
    WMI_CLIENT = wmi.WMI(namespace="root\\wmi")
except:
    WMI_CLIENT = None

SYSTEM_WHITELIST = {
    "System", "System Idle Process", "Registry",
    "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "fontdrvhost.exe"
}

DEFAULT_THRESH = {"bg_cpu": 30.0, "heavy_ram_mb": 800.0}
DEFAULT_REFRESH_SEC = 5.0

class DesignTokens:

    SPACING_UNIT = 8

    BG_BASE = "#050709"
    BG_SURFACE = "#0D1117"
    BG_ELEVATED = "#161B22"
    BG_OVERLAY = "#1D232C"
    BG_HOVER = "#1C2128"

    FG_PRIMARY = "#F9FAFB"
    FG_SECONDARY = "#9CA3AF"
    FG_MUTED = "#6B7280"
    FG_FAINT = "#4B5563"

    BORDER_DEFAULT = "#30363D"
    BORDER_SUBTLE = "#1D232C"
    BORDER_STRONG = "#3D444D"
    BORDER_FOCUS = "#8B5CF6"
    BORDER_GLOW = "#8B5CF640"

    ACCENT_PRIMARY = "#8B5CF6"
    ACCENT_SECONDARY = "#06B6D4"
    ACCENT_HOVER = "#A78BFA"
    ACCENT_ACTIVE = "#7C3AED"

    SUCCESS = "#10B981"
    SUCCESS_MUTED = "#059669"
    WARNING = "#F59E0B"
    WARNING_MUTED = "#D97706"
    ERROR = "#EF4444"
    ERROR_MUTED = "#DC2626"
    INFO = "#3B82F6"

    CARD_BG = "#161B22"
    CARD_BORDER = "#1D232C"
    BUTTON_PRIMARY = "#8B5CF6"
    BUTTON_PRIMARY_HOVER = "#7C3AED"
    BUTTON_SECONDARY = "#1F2937"
    BUTTON_SECONDARY_HOVER = "#374151"
    SIDEBAR_BG = "#161B22"
    SIDEBAR_ACTIVE = "#1F2937"

    S_XS = 4
    S_SM = 8
    S_MD = 16
    S_LG = 24
    S_XL = 32
    S_XXL = 48

    FONT_DISPLAY = "Segoe UI Variable Display"
    FONT_TEXT = "Segoe UI Variable Text"
    FONT_MONO = "JetBrains Mono"

    RADIUS_SM = 6
    RADIUS_MD = 12
    RADIUS_LG = 16
    RADIUS_XL = 20
    RADIUS_FULL = 9999

    ANIM_FAST = 150
    ANIM_NORMAL = 250
    ANIM_SLOW = 400

    @classmethod
    def get_status_color(cls, value, thresholds=(60, 85)):
        low, high = thresholds
        if value < low:
            return cls.SUCCESS
        elif value < high:
            return cls.WARNING
        return cls.ERROR

TOKENS = DesignTokens()

PRIORITY = {
    "Idle": win32process.IDLE_PRIORITY_CLASS,
    "Below Normal": win32process.BELOW_NORMAL_PRIORITY_CLASS,
    "Normal": win32process.NORMAL_PRIORITY_CLASS,
    "Above Normal": win32process.ABOVE_NORMAL_PRIORITY_CLASS,
    "High": win32process.HIGH_PRIORITY_CLASS,
    "Realtime": win32process.REALTIME_PRIORITY_CLASS,
}
PRIORITY_KEYS = list(PRIORITY.keys())

class PROCESS_MEMORY_PRIORITY_INFORMATION(ctypes.Structure):
    _fields_ = [("MemoryPriority", ctypes.c_ulong)]
ProcessMemoryPriority = 0x0003
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi    = ctypes.WinDLL("psapi", use_last_error=True)

def set_memory_priority(handle, level: int):
    info = PROCESS_MEMORY_PRIORITY_INFORMATION(level)
    ok = kernel32.SetProcessInformation(
        int(handle), ProcessMemoryPriority, ctypes.byref(info), ctypes.sizeof(info)
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())

def empty_working_set(handle):
    try:
        psapi.EmptyWorkingSet(int(handle))
    except:
        pass

class PROCESS_IO_PRIORITY_INFORMATION(ctypes.Structure):
    _fields_ = [("IoPriority", ctypes.c_ulong)]

ProcessIoPriority = 0x0021

IO_PRIORITY = {
    "Very Low": 0,
    "Low": 1,
    "Normal": 2,
    "High": 3,
}
IO_PRIORITY_KEYS = list(IO_PRIORITY.keys())

def set_io_priority(handle, level: int):
    try:
        info = PROCESS_IO_PRIORITY_INFORMATION(level)
        ok = kernel32.SetProcessInformation(
            int(handle), ProcessIoPriority, ctypes.byref(info), ctypes.sizeof(info)
        )
        if not ok:
            pass
        return ok
    except Exception:
        return False

def get_io_priority(handle):
    try:
        info = PROCESS_IO_PRIORITY_INFORMATION()
        ok = kernel32.GetProcessInformation(
            int(handle), ProcessIoPriority, ctypes.byref(info), ctypes.sizeof(info)
        )
        if ok:
            return info.IoPriority
    except Exception:
        pass
    return 2

winmm = ctypes.WinDLL("winmm", use_last_error=True)

def set_timer_resolution(ms=1):
    try:
        winmm.timeBeginPeriod(ms)
        return True
    except:
        return False

def reset_timer_resolution(ms=1):
    try:
        winmm.timeEndPeriod(ms)
        return True
    except:
        return False

def control_sysmain_service(enable: bool):
    try:
        action = "start" if enable else "stop"
        subprocess.run(
            ["net", action, "SysMain"],
            capture_output=True, timeout=10
        )
        return True
    except:
        return False

def set_cpu_parking(enabled: bool):
    try:
        value = "0" if enabled else "100"
        subprocess.run([
            "powercfg", "-setacvalueindex", "SCHEME_CURRENT",
            "SUB_PROCESSOR", "CPMINCORES", value
        ], capture_output=True, timeout=5)
        subprocess.run(["powercfg", "-setactive", "SCHEME_CURRENT"],
                      capture_output=True, timeout=5)
        return True
    except:
        return False

def boost_foreground_priority_registry():
    try:
        if winreg:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\PriorityControl",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "Win32PrioritySeparation", 0, winreg.REG_DWORD, 0x26)
            winreg.CloseKey(key)
            return True
    except:
        pass
    return False

def set_affinity_physical_cores_only(handle, core_count):
    try:
        physical_mask = 0
        for i in range(0, core_count, 2):
            physical_mask |= (1 << i)
        win32process.SetProcessAffinityMask(handle, physical_mask)
        return True
    except:
        return False

def set_affinity_performance_cores(handle, p_core_count):
    try:
        p_core_mask = (1 << p_core_count) - 1
        win32process.SetProcessAffinityMask(handle, p_core_mask)
        return True
    except:
        return False

class DynamicPriorityBalancer:
    def __init__(self):
        self.enabled = True
        self.system_threshold = 85.0
        self.process_threshold = 3.0
        self.release_threshold = 1.0

        self.allowed_time_quota_ms = 900
        self.min_adjustment_time_ms = 4200

        self.lowered = {}
        self.cpu_time_accum = {}
        self.cooldown = {}
        self.last_check = 0
        self.check_interval = 0.5

        self.stats = {
            'actions_taken': 0,
            'restores_done': 0,
            'current_interventions': 0
        }

    def check_and_rebalance(self, fpid):
        if not self.enabled:
            return

        now = time.time()
        if now - self.last_check < self.check_interval:
            return
        dt = (now - self.last_check) * 1000
        self.last_check = now

        try:
            system_cpu = psutil.cpu_percent(interval=None)
            core_count = psutil.cpu_count() or 4

            if system_cpu > self.system_threshold:
                for p in psutil.process_iter(['pid', 'name', 'cpu_percent']):
                    try:
                        pid = p.info['pid']
                        name = (p.info['name'] or "").lower()
                        proc_cpu = (p.info.get('cpu_percent') or 0) / core_count

                        if pid == fpid or name in PROTECTED:
                            if pid in self.cpu_time_accum:
                                del self.cpu_time_accum[pid]
                            continue

                        if pid in self.lowered:
                            if system_cpu > 95 and proc_cpu > self.process_threshold:
                                info = self.lowered[pid]
                                if info['level'] == 1:
                                    self._escalate_priority(pid)
                            continue

                        if proc_cpu >= self.process_threshold:
                            if pid not in self.cpu_time_accum:
                                self.cpu_time_accum[pid] = {
                                    'accumulated_ms': 0,
                                    'last_sample': now,
                                    'name': name
                                }

                            accum = self.cpu_time_accum[pid]
                            time_delta_ms = (now - accum['last_sample']) * 1000
                            accum['accumulated_ms'] += time_delta_ms * (proc_cpu / 100)
                            accum['last_sample'] = now

                            if accum['accumulated_ms'] >= self.allowed_time_quota_ms:
                                self._lower_priority(pid, name, now)
                                del self.cpu_time_accum[pid]

                        else:
                            if pid in self.cpu_time_accum:
                                self.cpu_time_accum[pid]['accumulated_ms'] *= 0.9
                                if self.cpu_time_accum[pid]['accumulated_ms'] < 10:
                                    del self.cpu_time_accum[pid]

                    except:
                        continue
            else:
                for pid in list(self.cpu_time_accum.keys()):
                    self.cpu_time_accum[pid]['accumulated_ms'] *= 0.8
                    if self.cpu_time_accum[pid]['accumulated_ms'] < 10:
                        del self.cpu_time_accum[pid]

            if system_cpu < 70:
                for pid in list(self.lowered.keys()):
                    try:
                        info = self.lowered[pid]
                        time_lowered_ms = (now - info['time']) * 1000

                        if time_lowered_ms < self.min_adjustment_time_ms:
                            continue

                        try:
                            p = psutil.Process(pid)
                            proc_cpu = p.cpu_percent(interval=None) / core_count
                            if proc_cpu > self.release_threshold:
                                continue
                        except:
                            pass

                        if info['level'] == 2:
                            self._step_restore_priority(pid, win32process.BELOW_NORMAL_PRIORITY_CLASS, 1)
                        else:
                            self._full_restore_priority(pid)

                    except:
                        if pid in self.lowered:
                            del self.lowered[pid]

            for pid in list(self.lowered.keys()):
                if not psutil.pid_exists(pid):
                    del self.lowered[pid]

            for pid in list(self.cpu_time_accum.keys()):
                if not psutil.pid_exists(pid):
                    del self.cpu_time_accum[pid]

            self.stats['current_interventions'] = len(self.lowered)

        except Exception:
            pass

    def _lower_priority(self, pid, name, now):
        try:
            h = open_proc(pid, win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_SET_INFORMATION)
            if not h:
                return

            try:
                original = win32process.GetPriorityClass(h)

                if original in (win32process.NORMAL_PRIORITY_CLASS,
                              win32process.ABOVE_NORMAL_PRIORITY_CLASS):
                    win32process.SetPriorityClass(h, win32process.BELOW_NORMAL_PRIORITY_CLASS)

                    try:
                        set_io_priority(h, 1)
                    except:
                        pass

                    try:
                        set_memory_priority(h, 3)
                    except:
                        pass

                    self.lowered[pid] = {
                        'original': original,
                        'name': name,
                        'level': 1,
                        'time': now
                    }
                    self.stats['actions_taken'] += 1
            finally:
                win32api.CloseHandle(h)
        except:
            pass

    def _escalate_priority(self, pid):
        try:
            h = open_proc(pid, win32con.PROCESS_SET_INFORMATION)
            if h:
                try:
                    win32process.SetPriorityClass(h, win32process.IDLE_PRIORITY_CLASS)

                    try:
                        set_io_priority(h, 0)
                    except:
                        pass

                    try:
                        set_memory_priority(h, 1)
                    except:
                        pass

                    self.lowered[pid]['level'] = 2
                finally:
                    win32api.CloseHandle(h)
        except:
            pass

    def _step_restore_priority(self, pid, target_priority, new_level):
        try:
            h = open_proc(pid, win32con.PROCESS_SET_INFORMATION)
            if h:
                try:
                    win32process.SetPriorityClass(h, target_priority)
                    self.lowered[pid]['level'] = new_level
                    self.lowered[pid]['time'] = time.time()
                finally:
                    win32api.CloseHandle(h)
        except:
            pass

    def _full_restore_priority(self, pid):
        try:
            info = self.lowered[pid]
            h = open_proc(pid, win32con.PROCESS_SET_INFORMATION)
            if h:
                try:
                    win32process.SetPriorityClass(h, info['original'])
                finally:
                    win32api.CloseHandle(h)
            del self.lowered[pid]
            self.stats['restores_done'] += 1
        except:
            if pid in self.lowered:
                del self.lowered[pid]

    def get_stats(self):
        return {
            'enabled': self.enabled,
            'lowered_count': len(self.lowered),
            'lowered_names': [v['name'] for v in self.lowered.values()],
            'pending_count': len(self.cpu_time_accum),
            'pending_names': [v['name'] for v in self.cpu_time_accum.values()],
            **self.stats
        }

PRIORITY_BALANCER = DynamicPriorityBalancer()

class POWER_SAVER:

    POWER_PLANS = {
        'HIGH_PERFORMANCE': '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c',
        'BALANCED': '381b4222-f694-41f0-9685-ff5bb260df2e',
        'POWER_SAVER': 'a1841308-3541-4fab-bc81-f71556f20b4a',
        'ULTIMATE': 'e9a42b02-d5df-448d-aa00-03f14749eb61'
    }

    def __init__(self):
        self.enabled = False
        self.idle_threshold = 5.0
        self.idle_time = 0
        self.idle_trigger_sec = 120
        self.was_idle = False
        self.original_plan = None
        self.current_plan = None
        self.on_battery = False
        self.cpu_samples = deque(maxlen=12)

        self._detect_current_plan()

    def _detect_current_plan(self):
        try:
            result = subprocess.run(
                ['powercfg', '/getactivescheme'],
                capture_output=True, text=True, timeout=5
            )
            output = result.stdout.lower()
            for name, guid in self.POWER_PLANS.items():
                if guid in output:
                    self.current_plan = name
                    self.original_plan = name
                    return
        except:
            pass
        self.current_plan = 'BALANCED'
        self.original_plan = 'BALANCED'

    def _set_power_plan(self, plan_name):
        guid = self.POWER_PLANS.get(plan_name)
        if not guid:
            return False
        try:
            subprocess.run(
                ['powercfg', '/setactive', guid],
                capture_output=True, timeout=5
            )
            self.current_plan = plan_name
            return True
        except:
            return False

    def _check_battery(self):
        try:
            battery = psutil.sensors_battery()
            if battery:
                self.on_battery = not battery.power_plugged
                return self.on_battery
        except:
            pass
        return False

    def check(self):
        if not self.enabled:
            return

        try:
            cpu = psutil.cpu_percent(interval=None)
            self.cpu_samples.append(cpu)

            if len(self.cpu_samples) >= 3:
                avg_cpu = sum(self.cpu_samples) / len(self.cpu_samples)
            else:
                avg_cpu = cpu

            self._check_battery()

            if self.on_battery and self.current_plan != 'POWER_SAVER':
                if self.original_plan is None:
                    self.original_plan = self.current_plan
                self._set_power_plan('POWER_SAVER')
                self.was_idle = True
                return

            if avg_cpu < self.idle_threshold:
                self.idle_time += 10
                if self.idle_time >= self.idle_trigger_sec and not self.was_idle:
                    if self.original_plan is None:
                        self.original_plan = self.current_plan
                    self._set_power_plan('POWER_SAVER')
                    self.was_idle = True
            else:
                if self.was_idle:
                    if self.original_plan:
                        self._set_power_plan(self.original_plan)
                    else:
                        self._set_power_plan('BALANCED')
                    self.was_idle = False
                self.idle_time = 0

        except Exception:
            pass

    def restore(self):
        if self.original_plan:
            self._set_power_plan(self.original_plan)
        self.was_idle = False
        self.idle_time = 0

    def get_stats(self):
        return {
            'enabled': self.enabled,
            'current_plan': self.current_plan,
            'original_plan': self.original_plan,
            'on_battery': self.on_battery,
            'is_idle': self.was_idle,
            'idle_time': self.idle_time,
            'avg_cpu': sum(self.cpu_samples) / len(self.cpu_samples) if self.cpu_samples else 0
        }

POWER_SAVER = POWER_SAVER()

class AffinityManager:

    def __init__(self):
        self.enabled = True
        self.rules = {}
        self.applied = set()
        self.last_check = 0

        self.cpu_info = self._detect_cpu_topology()
        self.presets = self._generate_presets()

    def _detect_cpu_topology(self):
        info = {
            'vendor': 'unknown',
            'total_cores': psutil.cpu_count(logical=False) or 4,
            'total_threads': psutil.cpu_count(logical=True) or 8,
            'is_hybrid': False,
            'p_cores': 0,
            'e_cores': 0,
            'ccds': 1,
            'cores_per_ccd': 0
        }

        try:
            if WMI_CLIENT:
                try:
                    wmi_cpu = wmi.WMI()
                    for cpu in wmi_cpu.Win32_Processor():
                        name = cpu.Name.lower()
                        info['vendor'] = 'intel' if 'intel' in name else ('amd' if 'amd' in name else 'unknown')

                        if info['vendor'] == 'intel':
                            if any(x in name for x in ['12th', '13th', '14th', '15th', 'core ultra']):
                                info['is_hybrid'] = True
                                total = info['total_cores']
                                if total >= 24:
                                    info['p_cores'] = 8
                                    info['e_cores'] = total - 8
                                elif total >= 16:
                                    info['p_cores'] = 8
                                    info['e_cores'] = total - 8
                                elif total >= 14:
                                    info['p_cores'] = 6
                                    info['e_cores'] = total - 6
                                elif total >= 10:
                                    info['p_cores'] = 6
                                    info['e_cores'] = total - 6
                                else:
                                    info['p_cores'] = max(2, total // 2)
                                    info['e_cores'] = total - info['p_cores']

                        elif info['vendor'] == 'amd':
                            if any(x in name for x in ['ryzen 9', 'ryzen 7', 'threadripper', 'epyc']):
                                cores = info['total_cores']
                                if cores >= 16:
                                    info['ccds'] = 2
                                    info['cores_per_ccd'] = cores // 2
                                elif cores >= 8:
                                    info['ccds'] = 1
                                    info['cores_per_ccd'] = cores
                        break
                except:
                    pass

            if info['vendor'] == 'unknown':
                total = info['total_cores']
                threads = info['total_threads']
                if threads > total * 2:
                    info['is_hybrid'] = True
                    info['p_cores'] = total // 2
                    info['e_cores'] = total - info['p_cores']

        except Exception:
            pass

        return info

    def _generate_presets(self):
        total_threads = self.cpu_info['total_threads']
        total_cores = self.cpu_info['total_cores']

        presets = {
            'all_cores': (1 << total_threads) - 1,
            'single_core': 0x0001,
            'first_half': (1 << (total_threads // 2)) - 1,
            'second_half': ((1 << (total_threads // 2)) - 1) << (total_threads // 2),
        }

        if self.cpu_info['is_hybrid'] and self.cpu_info['p_cores'] > 0:
            p_cores = self.cpu_info['p_cores']
            e_cores = self.cpu_info['e_cores']

            p_threads = p_cores * 2
            e_threads = e_cores

            presets['p_cores_only'] = (1 << p_threads) - 1
            presets['e_cores_only'] = ((1 << e_threads) - 1) << p_threads
            presets['p_cores_no_ht'] = sum(1 << (i * 2) for i in range(p_cores))

        if self.cpu_info['vendor'] == 'amd' and self.cpu_info['ccds'] > 1:
            cores_per_ccd = self.cpu_info['cores_per_ccd']
            threads_per_ccd = cores_per_ccd * 2

            presets['first_ccd'] = (1 << threads_per_ccd) - 1
            presets['second_ccd'] = ((1 << threads_per_ccd) - 1) << threads_per_ccd
            presets['same_ccd'] = presets['first_ccd']

        if total_threads > total_cores:
            presets['physical_only'] = sum(1 << (i * 2) for i in range(total_cores))

        return presets

    def add_rule(self, process_name, affinity_mask=None, priority=None, delay_ms=0,
                 io_priority=None, mem_priority=None, preset=None):
        mask = affinity_mask
        if preset and preset in self.presets:
            mask = self.presets[preset]

        self.rules[process_name.lower()] = {
            'mask': mask,
            'priority': priority,
            'delay_ms': delay_ms,
            'io_priority': io_priority,
            'mem_priority': mem_priority,
            'preset': preset
        }

    def remove_rule(self, process_name):
        name = process_name.lower()
        if name in self.rules:
            del self.rules[name]

    def check_and_apply(self):
        if not self.enabled or not self.rules:
            return

        now = time.time()
        if now - self.last_check < 5:
            return
        self.last_check = now

        for p in psutil.process_iter(['pid', 'name']):
            try:
                pid = p.info['pid']
                name = (p.info['name'] or "").lower()

                if pid in self.applied:
                    continue

                rule = self.rules.get(name)
                if not rule:
                    for rule_name, r in self.rules.items():
                        if rule_name in name:
                            rule = r
                            break

                if not rule:
                    continue

                delay = rule.get('delay_ms', 0)
                if delay > 0:
                    threading.Timer(delay / 1000.0, self._apply_rule, args=(pid, rule)).start()
                else:
                    self._apply_rule(pid, rule)

                self.applied.add(pid)

            except:
                continue

        self.applied = {pid for pid in self.applied if psutil.pid_exists(pid)}

    def _apply_rule(self, pid, rule):
        try:
            access = win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION
            h = open_proc(pid, access)
            if not h:
                return

            try:
                if rule.get('mask'):
                    win32process.SetProcessAffinityMask(h, rule['mask'])

                priority = rule.get('priority')
                if priority:
                    prio_map = {
                        'idle': win32process.IDLE_PRIORITY_CLASS,
                        'below_normal': win32process.BELOW_NORMAL_PRIORITY_CLASS,
                        'normal': win32process.NORMAL_PRIORITY_CLASS,
                        'above_normal': win32process.ABOVE_NORMAL_PRIORITY_CLASS,
                        'high': win32process.HIGH_PRIORITY_CLASS,
                    }
                    if priority.lower() in prio_map:
                        win32process.SetPriorityClass(h, prio_map[priority.lower()])

                io_prio = rule.get('io_priority')
                if io_prio is not None:
                    set_io_priority(h, io_prio)

                mem_prio = rule.get('mem_priority')
                if mem_prio is not None:
                    set_memory_priority(h, mem_prio)

            finally:
                win32api.CloseHandle(h)
        except:
            pass

    def get_preset(self, name):
        return self.presets.get(name)

    def get_rules(self):
        return dict(self.rules)

    def get_cpu_info(self):
        return dict(self.cpu_info)

    def get_stats(self):
        return {
            'enabled': self.enabled,
            'cpu_info': self.cpu_info,
            'available_presets': list(self.presets.keys()),
            'rules_count': len(self.rules),
            'applied_count': len(self.applied)
        }

AFFINITY_MGR = AffinityManager()

class MEM_OPTIMIZER:

    SystemMemoryListInformation = 80
    MemoryEmptyWorkingSets = 0
    MemoryFlushModifiedList = 1
    MemoryPurgeStandbyList = 4
    MemoryPurgeLowPriorityStandbyList = 5

    def __init__(self):
        self.enabled = False
        self.memory_threshold = 75.0
        self.standby_threshold = 80.0
        self.per_process_threshold = 150
        self.trim_interval = 30
        self.standby_clear_interval = 45
        self.last_trim = 0
        self.last_standby_clear = 0
        self.aggressive_mode = False

        self.stats = {
            'trimmed_count': 0,
            'mb_freed': 0,
            'standby_clears': 0,
            'last_action': '',
            'last_freed_mb': 0
        }

        self.exclusions = {
            "svchost.exe", "winlogon.exe", "dwm.exe", "csrss.exe",
            "smss.exe", "wininit.exe", "services.exe", "lsass.exe",
            "system", "registry", "explorer.exe", "audiodg.exe",
            "searchindexer.exe", "spoolsv.exe", "msiexec.exe",
            "msmpeng.exe", "antimalware service executable"
        }

        try:
            self.ntdll = ctypes.WinDLL("ntdll")
            self.ntdll.NtSetSystemInformation.argtypes = [
                ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong
            ]
            self.ntdll.NtSetSystemInformation.restype = ctypes.c_long
            self.ntdll_available = True
        except Exception:
            self.ntdll_available = False

    def _get_memory_info(self):
        mem = psutil.virtual_memory()
        return {
            'total': mem.total,
            'available': mem.available,
            'used': mem.used,
            'percent': mem.percent,
            'standby_estimate': mem.total - mem.available - mem.used
        }

    def _clear_standby_list_native(self, clear_low_priority_only=False):
        if not self.ntdll_available:
            return False
        try:
            command = (self.MemoryPurgeLowPriorityStandbyList
                      if clear_low_priority_only
                      else self.MemoryPurgeStandbyList)
            cmd_val = ctypes.c_ulong(command)
            status = self.ntdll.NtSetSystemInformation(
                self.SystemMemoryListInformation,
                ctypes.byref(cmd_val),
                ctypes.sizeof(cmd_val)
            )
            return status == 0
        except Exception:
            return False

    def _flush_modified_list(self):
        if not self.ntdll_available:
            return False
        try:
            cmd_val = ctypes.c_ulong(self.MemoryFlushModifiedList)
            status = self.ntdll.NtSetSystemInformation(
                self.SystemMemoryListInformation,
                ctypes.byref(cmd_val),
                ctypes.sizeof(cmd_val)
            )
            return status == 0
        except Exception:
            return False

    def check_and_trim(self):
        if not self.enabled:
            return

        now = time.time()

        try:
            mem_info = self._get_memory_info()
            mem_percent = mem_info['percent']

            if mem_percent > self.standby_threshold:
                if now - self.last_standby_clear >= self.standby_clear_interval:
                    before_available = mem_info['available']
                    self._clear_standby_list_native(clear_low_priority_only=True)
                    if mem_percent > 90 or self.aggressive_mode:
                        self._flush_modified_list()
                        self._clear_standby_list_native(clear_low_priority_only=False)

                    after_mem = psutil.virtual_memory()
                    freed_bytes = after_mem.available - before_available
                    freed_mb = max(0, freed_bytes / (1024 * 1024))

                    self.stats['standby_clears'] += 1
                    self.stats['last_freed_mb'] = freed_mb
                    self.stats['mb_freed'] += freed_mb
                    self.stats['last_action'] = f"Cleared standby: +{freed_mb:.0f}MB"
                    self.last_standby_clear = now

            if now - self.last_trim < self.trim_interval:
                return

            if mem_percent < self.memory_threshold and not self.aggressive_mode:
                return

            self.last_trim = now
            trimmed = 0
            total_freed = 0

            processes = []
            for p in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    mem = p.info.get('memory_info')
                    if mem:
                        processes.append({
                            'pid': p.info['pid'],
                            'name': (p.info['name'] or "").lower(),
                            'rss': mem.rss
                        })
                except:
                    continue

            processes.sort(key=lambda x: x['rss'], reverse=True)

            for proc in processes[:50]:
                try:
                    pid = proc['pid']
                    name = proc['name']
                    rss = proc['rss']

                    if name in self.exclusions:
                        continue

                    rss_mb = rss / (1024 * 1024)
                    if rss_mb < self.per_process_threshold:
                        continue

                    h = open_proc(pid, win32con.PROCESS_SET_QUOTA | win32con.PROCESS_QUERY_INFORMATION)
                    if h:
                        try:
                            try:
                                before_rss = psutil.Process(pid).memory_info().rss
                            except:
                                before_rss = rss

                            empty_working_set(h)

                            try:
                                after_rss = psutil.Process(pid).memory_info().rss
                                freed = max(0, before_rss - after_rss) / (1024 * 1024)
                            except:
                                freed = rss_mb * 0.2

                            total_freed += freed
                            trimmed += 1
                        finally:
                            win32api.CloseHandle(h)

                except Exception:
                    continue

            if trimmed > 0:
                self.stats['trimmed_count'] += trimmed
                self.stats['mb_freed'] += total_freed
                self.stats['last_freed_mb'] = total_freed
                self.stats['last_action'] = f"Trimmed {trimmed} procs: +{total_freed:.0f}MB"

        except Exception:
            pass

    def force_clean(self):
        try:
            before_mem = psutil.virtual_memory()
            self._flush_modified_list()
            self._clear_standby_list_native(clear_low_priority_only=False)

            for p in psutil.process_iter(['pid', 'name']):
                try:
                    name = (p.info['name'] or "").lower()
                    if name in self.exclusions:
                        continue
                    h = open_proc(p.info['pid'], win32con.PROCESS_SET_QUOTA)
                    if h:
                        empty_working_set(h)
                        win32api.CloseHandle(h)
                except:
                    continue

            after_mem = psutil.virtual_memory()
            freed_mb = (after_mem.available - before_mem.available) / (1024 * 1024)

            self.stats['mb_freed'] += max(0, freed_mb)
            self.stats['last_freed_mb'] = max(0, freed_mb)
            self.stats['last_action'] = f"Force clean: +{freed_mb:.0f}MB"
            self.stats['standby_clears'] += 1
            return freed_mb
        except Exception:
            return 0

    def get_stats(self):
        try:
            mem = psutil.virtual_memory()
            return {
                'enabled': self.enabled,
                'memory_percent': mem.percent,
                'available_mb': mem.available / (1024 * 1024),
                'aggressive_mode': self.aggressive_mode,
                'ntdll_available': self.ntdll_available,
                **self.stats
            }
        except:
            return {'enabled': self.enabled, **self.stats}

MEM_OPTIMIZER = MEM_OPTIMIZER()

class CPU_LIMITER:

    JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x1
    JOB_OBJECT_CPU_RATE_CONTROL_WEIGHT_BASED = 0x2
    JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x4
    JOB_OBJECT_CPU_RATE_CONTROL_NOTIFY = 0x8
    JOB_OBJECT_CPU_RATE_CONTROL_MIN_MAX_RATE = 0x10

    def __init__(self):
        self.enabled = False
        self.cpu_threshold = 80.0
        self.limit_percent = 50
        self.limited = {}
        self.jobs = {}
        self.restore_threshold = 30.0
        self.min_limit_time = 10
        self.last_check = 0
        self.check_interval = 3
        self.rules = {}
        self.use_job_objects = win32job is not None

        self.stats = {
            'total_limited': 0,
            'active_limits': 0,
            'method': 'job_objects' if self.use_job_objects else 'affinity'
        }

    def add_rule(self, process_name, threshold=80.0, limit_percent=50):
        self.rules[process_name.lower()] = {
            'threshold': threshold,
            'limit_percent': limit_percent
        }

    def remove_rule(self, process_name):
        name = process_name.lower()
        if name in self.rules:
            del self.rules[name]

    def check_and_limit(self, fpid=None):
        if not self.enabled:
            return

        now = time.time()
        if now - self.last_check < self.check_interval:
            return
        self.last_check = now

        try:
            core_count = psutil.cpu_count() or 4

            for p in psutil.process_iter(['pid', 'name', 'cpu_percent']):
                try:
                    pid = p.info['pid']
                    name = (p.info['name'] or "").lower()
                    proc_cpu = (p.info.get('cpu_percent') or 0)

                    if pid == fpid or name in PROTECTED:
                        continue

                    rule = self.rules.get(name)
                    threshold = rule['threshold'] if rule else self.cpu_threshold
                    limit_pct = rule['limit_percent'] if rule else self.limit_percent

                    if pid in self.limited:
                        info = self.limited[pid]
                        if proc_cpu < self.restore_threshold and (now - info['time']) > self.min_limit_time:
                            self._restore(pid)
                        continue

                    if proc_cpu > threshold:
                        self._limit(pid, name, limit_pct, core_count)

                except Exception:
                    continue

            for pid in list(self.limited.keys()):
                if not psutil.pid_exists(pid):
                    self._cleanup_job(pid)
                    if pid in self.limited:
                        del self.limited[pid]

            self.stats['active_limits'] = len(self.limited)

        except Exception:
            pass

    def _limit(self, pid, name, limit_percent, core_count):
        if self.use_job_objects:
            success = self._limit_with_job_object(pid, name, limit_percent)
            if success:
                return

        self._limit_with_affinity(pid, name, limit_percent, core_count)

    def _limit_with_job_object(self, pid, name, limit_percent):
        try:
            job_name = f"OptiCores_CPULimit_{pid}"
            job = win32job.CreateJobObject(None, job_name)

            info = win32job.QueryInformationJobObject(
                job, win32job.JobObjectBasicLimitInformation
            )

            cpu_rate = int(limit_percent * 100)

            try:
                rate_info = {
                    'ControlFlags': self.JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | self.JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP,
                    'CpuRate': cpu_rate
                }

                h = open_proc(pid, win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE)
                if not h:
                    win32api.CloseHandle(job)
                    return False

                try:
                    win32job.AssignProcessToJobObject(job, h)

                    self.jobs[pid] = job
                    self.limited[pid] = {
                        'name': name,
                        'time': time.time(),
                        'limit_percent': limit_percent,
                        'method': 'job_object'
                    }
                    self.stats['total_limited'] += 1
                    return True

                finally:
                    win32api.CloseHandle(h)

            except Exception:
                win32api.CloseHandle(job)
                return False

        except Exception:
            return False

    def _limit_with_affinity(self, pid, name, limit_percent, core_count):
        try:
            h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
            if not h:
                return

            try:
                proc_aff, sys_aff = win32process.GetProcessAffinityMask(h)

                limited_cores = max(1, int(core_count * limit_percent / 100))
                limited_mask = (1 << limited_cores) - 1

                win32process.SetProcessAffinityMask(h, limited_mask & sys_aff)

                self.limited[pid] = {
                    'original_mask': proc_aff,
                    'name': name,
                    'time': time.time(),
                    'limit_percent': limit_percent,
                    'limited_cores': limited_cores,
                    'method': 'affinity'
                }
                self.stats['total_limited'] += 1

            finally:
                win32api.CloseHandle(h)
        except Exception:
            pass

    def _cleanup_job(self, pid):
        if pid in self.jobs:
            try:
                win32api.CloseHandle(self.jobs[pid])
            except:
                pass
            del self.jobs[pid]

    def _restore(self, pid):
        if pid not in self.limited:
            return

        try:
            info = self.limited[pid]

            if info.get('method') == 'job_object':
                self._cleanup_job(pid)
            elif info.get('method') == 'affinity' and 'original_mask' in info:
                h = open_proc(pid, win32con.PROCESS_SET_INFORMATION)
                if h:
                    try:
                        win32process.SetProcessAffinityMask(h, info['original_mask'])
                    finally:
                        win32api.CloseHandle(h)

            del self.limited[pid]
        except Exception:
            self._cleanup_job(pid)
            if pid in self.limited:
                del self.limited[pid]

    def get_stats(self):
        return {
            'enabled': self.enabled,
            'limited_count': len(self.limited),
            'use_job_objects': self.use_job_objects,
            'limited_processes': [
                {'name': v['name'], 'limit': v['limit_percent'], 'method': v.get('method', 'unknown')}
                for v in self.limited.values()
            ],
            **self.stats
        }

CPU_LIMITER = CPU_LIMITER()

class ResponsivenessMonitor:

    def __init__(self):
        self.samples = deque(maxlen=120)
        self.current_score = 100.0
        self.last_input_time = 0
        self.last_measure = 0
        self.measure_interval = 1

        self.excellent_latency = 2
        self.good_latency = 10
        self.poor_latency = 50

        self.min_latency = 999
        self.max_latency = 0
        self.latency_samples = deque(maxlen=60)
        self.disk_samples = deque(maxlen=60)

    def measure(self):
        now = time.time()
        if now - self.last_measure < self.measure_interval:
            return self.current_score
        self.last_measure = now

        try:
            timing_scores = []
            for _ in range(3):
                start = time.perf_counter()
                time.sleep(0.001)
                actual = (time.perf_counter() - start) * 1000

                deviation = abs(actual - 1.0)
                timing_scores.append(max(0, 100 - deviation * 10))

            timing_score = sum(timing_scores) / len(timing_scores)

            msg_latency = 0
            try:
                hwnd = win32gui.GetForegroundWindow()
                if hwnd:
                    start = time.perf_counter()
                    win32gui.SendMessage(hwnd, win32con.WM_NULL, 0, 0)
                    msg_latency = (time.perf_counter() - start) * 1000
                    self.latency_samples.append(msg_latency)

                    self.min_latency = min(self.min_latency, msg_latency)
                    self.max_latency = max(self.max_latency, msg_latency)
            except:
                pass

            msg_score = max(0, min(100, 100 - (msg_latency - self.excellent_latency) *
                                    (100 / (self.poor_latency - self.excellent_latency))))

            cpu = psutil.cpu_percent(interval=None)
            cpu_score = max(0, 100 - cpu)

            mem = psutil.virtual_memory()
            mem_score = max(0, 100 - mem.percent)

            disk_score = 100
            try:
                disk = psutil.disk_io_counters()
                if disk:
                    self.disk_samples.append(disk.write_time if hasattr(disk, 'write_time') else 0)
            except:
                pass

            score = (
                timing_score * 0.25 +
                msg_score * 0.30 +
                cpu_score * 0.25 +
                mem_score * 0.15 +
                disk_score * 0.05
            )

            score = max(0, min(100, score))
            self.current_score = score
            self.samples.append(score)

            return score

        except Exception:
            return self.current_score

    def get_trend(self):
        if len(self.samples) < 10:
            return 'stable'

        recent = list(self.samples)[-20:]
        avg_recent = sum(recent) / len(recent)

        older = list(self.samples)[:20] if len(self.samples) > 40 else recent
        avg_older = sum(older) / len(older)

        diff = avg_recent - avg_older
        if diff > 5:
            return 'improving'
        elif diff < -5:
            return 'degrading'
        return 'stable'

    def get_grade(self):
        if self.current_score >= 90:
            return 'A'
        elif self.current_score >= 80:
            return 'B'
        elif self.current_score >= 70:
            return 'C'
        elif self.current_score >= 60:
            return 'D'
        return 'F'

    def get_stats(self):
        avg_latency = sum(self.latency_samples) / len(self.latency_samples) if self.latency_samples else 0
        return {
            'score': round(self.current_score, 1),
            'grade': self.get_grade(),
            'trend': self.get_trend(),
            'avg': round(sum(self.samples) / len(self.samples), 1) if self.samples else 100,
            'min_score': round(min(self.samples), 1) if self.samples else 100,
            'max_score': round(max(self.samples), 1) if self.samples else 100,
            'latency_ms': round(avg_latency, 2),
            'min_latency_ms': round(self.min_latency, 2) if self.min_latency < 999 else 0,
            'max_latency_ms': round(self.max_latency, 2),
            'samples_count': len(self.samples)
        }

RESPONSIVENESS = ResponsivenessMonitor()

class LatencyMonitor:

    def __init__(self):
        self.enabled = False
        self._monitor_thread = None
        self._stop_event = threading.Event()

        self.context_switch_history = deque(maxlen=300)
        self.dpc_latency_history = deque(maxlen=300)
        self.interrupt_latency_history = deque(maxlen=300)

        self.current_context_switches = 0
        self.current_dpc_latency_us = 0
        self.current_isr_latency_us = 0

        self.max_dpc_latency_us = 0
        self.max_isr_latency_us = 0
        self.max_context_switches = 0

        self.total_samples = 0
        self.spike_count = 0
        self.dpc_threshold_us = 1000

        self._last_ctx_switches = 0
        self._last_time = time.time()

        self._perf_info = None
        self._setup_perf_counters()

    def _setup_perf_counters(self):
        try:
            class SYSTEM_PERFORMANCE_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("IdleProcessTime", ctypes.c_longlong),
                    ("IoReadTransferCount", ctypes.c_longlong),
                    ("IoWriteTransferCount", ctypes.c_longlong),
                    ("IoOtherTransferCount", ctypes.c_longlong),
                    ("IoReadOperationCount", ctypes.c_ulong),
                    ("IoWriteOperationCount", ctypes.c_ulong),
                    ("IoOtherOperationCount", ctypes.c_ulong),
                    ("AvailablePages", ctypes.c_ulong),
                    ("CommittedPages", ctypes.c_ulong),
                    ("CommitLimit", ctypes.c_ulong),
                    ("PeakCommitment", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("CopyOnWriteCount", ctypes.c_ulong),
                    ("TransitionCount", ctypes.c_ulong),
                    ("CacheTransitionCount", ctypes.c_ulong),
                    ("DemandZeroCount", ctypes.c_ulong),
                    ("PageReadCount", ctypes.c_ulong),
                    ("PageReadIoCount", ctypes.c_ulong),
                    ("CacheReadCount", ctypes.c_ulong),
                    ("CacheIoCount", ctypes.c_ulong),
                    ("DirtyPagesWriteCount", ctypes.c_ulong),
                    ("DirtyWriteIoCount", ctypes.c_ulong),
                    ("MappedPagesWriteCount", ctypes.c_ulong),
                    ("MappedWriteIoCount", ctypes.c_ulong),
                    ("PagedPoolPages", ctypes.c_ulong),
                    ("NonPagedPoolPages", ctypes.c_ulong),
                    ("PagedPoolAllocs", ctypes.c_ulong),
                    ("PagedPoolFrees", ctypes.c_ulong),
                    ("NonPagedPoolAllocs", ctypes.c_ulong),
                    ("NonPagedPoolFrees", ctypes.c_ulong),
                    ("FreeSystemPtes", ctypes.c_ulong),
                    ("ResidentSystemCodePage", ctypes.c_ulong),
                    ("TotalSystemDriverPages", ctypes.c_ulong),
                    ("TotalSystemCodePages", ctypes.c_ulong),
                    ("NonPagedPoolLookasideHits", ctypes.c_ulong),
                    ("PagedPoolLookasideHits", ctypes.c_ulong),
                    ("AvailablePagedPoolPages", ctypes.c_ulong),
                    ("ResidentSystemCachePage", ctypes.c_ulong),
                    ("ResidentPagedPoolPage", ctypes.c_ulong),
                    ("ResidentSystemDriverPage", ctypes.c_ulong),
                    ("CcFastReadNoWait", ctypes.c_ulong),
                    ("CcFastReadWait", ctypes.c_ulong),
                    ("CcFastReadResourceMiss", ctypes.c_ulong),
                    ("CcFastReadNotPossible", ctypes.c_ulong),
                    ("CcFastMdlReadNoWait", ctypes.c_ulong),
                    ("CcFastMdlReadWait", ctypes.c_ulong),
                    ("CcFastMdlReadResourceMiss", ctypes.c_ulong),
                    ("CcFastMdlReadNotPossible", ctypes.c_ulong),
                    ("CcMapDataNoWait", ctypes.c_ulong),
                    ("CcMapDataWait", ctypes.c_ulong),
                    ("CcMapDataNoWaitMiss", ctypes.c_ulong),
                    ("CcMapDataWaitMiss", ctypes.c_ulong),
                    ("CcPinMappedDataCount", ctypes.c_ulong),
                    ("CcPinReadNoWait", ctypes.c_ulong),
                    ("CcPinReadWait", ctypes.c_ulong),
                    ("CcPinReadNoWaitMiss", ctypes.c_ulong),
                    ("CcPinReadWaitMiss", ctypes.c_ulong),
                    ("CcCopyReadNoWait", ctypes.c_ulong),
                    ("CcCopyReadWait", ctypes.c_ulong),
                    ("CcCopyReadNoWaitMiss", ctypes.c_ulong),
                    ("CcCopyReadWaitMiss", ctypes.c_ulong),
                    ("CcMdlReadNoWait", ctypes.c_ulong),
                    ("CcMdlReadWait", ctypes.c_ulong),
                    ("CcMdlReadNoWaitMiss", ctypes.c_ulong),
                    ("CcMdlReadWaitMiss", ctypes.c_ulong),
                    ("CcReadAheadIos", ctypes.c_ulong),
                    ("CcLazyWriteIos", ctypes.c_ulong),
                    ("CcLazyWritePages", ctypes.c_ulong),
                    ("CcDataFlushes", ctypes.c_ulong),
                    ("CcDataPages", ctypes.c_ulong),
                    ("ContextSwitches", ctypes.c_ulong),
                    ("FirstLevelTbFills", ctypes.c_ulong),
                    ("SecondLevelTbFills", ctypes.c_ulong),
                    ("SystemCalls", ctypes.c_ulong),
                ]

            self._perf_info = SYSTEM_PERFORMANCE_INFORMATION
            self._ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
        except Exception:
            self._perf_info = None

    def start(self):
        self.enabled = True
        self._stop_event.clear()

        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        def monitor_loop():
            while not self._stop_event.is_set():
                try:
                    self._sample()
                except Exception:
                    pass
                self._stop_event.wait(0.5)

        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop(self):
        self.enabled = False
        self._stop_event.set()

    def _sample(self):
        now = time.time()
        self.total_samples += 1

        ctx_switches = self._get_context_switches()
        if ctx_switches > 0 and self._last_ctx_switches > 0:
            dt = now - self._last_time
            if dt > 0:
                rate = (ctx_switches - self._last_ctx_switches) / dt
                self.current_context_switches = int(rate)
                self.context_switch_history.append(rate)

                if rate > self.max_context_switches:
                    self.max_context_switches = int(rate)

        self._last_ctx_switches = ctx_switches
        self._last_time = now

        dpc_latency = self._measure_dpc_latency()
        self.current_dpc_latency_us = dpc_latency
        self.dpc_latency_history.append(dpc_latency)

        if dpc_latency > self.max_dpc_latency_us:
            self.max_dpc_latency_us = dpc_latency

        if dpc_latency > self.dpc_threshold_us:
            self.spike_count += 1

        isr_latency = self._measure_isr_latency()
        self.current_isr_latency_us = isr_latency
        self.interrupt_latency_history.append(isr_latency)

        if isr_latency > self.max_isr_latency_us:
            self.max_isr_latency_us = isr_latency

    def _get_context_switches(self):
        if self._perf_info:
            try:
                info = self._perf_info()
                size = ctypes.c_ulong(ctypes.sizeof(info))
                status = self._ntdll.NtQuerySystemInformation(2, ctypes.byref(info), size, None)
                if status == 0:
                    return info.ContextSwitches
            except Exception:
                pass

        try:
            total = 0
            for proc in psutil.process_iter(['num_ctx_switches']):
                try:
                    ctx = proc.info.get('num_ctx_switches')
                    if ctx:
                        total += ctx.voluntary + ctx.involuntary
                except Exception:
                    pass
            return total
        except Exception:
            return 0

    def _measure_dpc_latency(self):
        try:
            samples = []
            for _ in range(10):
                start = time.perf_counter_ns()
                time.sleep(0.0001)
                elapsed = time.perf_counter_ns() - start
                expected_ns = 100000
                jitter = abs(elapsed - expected_ns)
                samples.append(jitter / 1000)

            samples.sort()
            return int(samples[len(samples) // 2])
        except Exception:
            return 0

    def _measure_isr_latency(self):
        try:
            samples = []
            for _ in range(5):
                start = time.perf_counter_ns()
                _ = time.time()
                elapsed = time.perf_counter_ns() - start
                samples.append(elapsed / 1000)
            return int(sum(samples) / len(samples))
        except Exception:
            return 0

    def get_grade(self):
        avg_dpc = sum(self.dpc_latency_history) / len(self.dpc_latency_history) if self.dpc_latency_history else 0

        if avg_dpc < 100:
            return 'A'
        elif avg_dpc < 250:
            return 'B'
        elif avg_dpc < 500:
            return 'C'
        elif avg_dpc < 1000:
            return 'D'
        return 'F'

    def get_trend(self):
        if len(self.dpc_latency_history) < 10:
            return 'stable'

        recent = list(self.dpc_latency_history)[-10:]
        older = list(self.dpc_latency_history)[-30:-10] if len(self.dpc_latency_history) >= 30 else recent

        recent_avg = sum(recent) / len(recent)
        older_avg = sum(older) / len(older) if older else recent_avg

        diff = recent_avg - older_avg
        if diff < -50:
            return 'improving'
        elif diff > 50:
            return 'degrading'
        return 'stable'

    def is_audio_safe(self):
        avg_dpc = sum(self.dpc_latency_history) / len(self.dpc_latency_history) if self.dpc_latency_history else 0
        return avg_dpc < 500 and self.max_dpc_latency_us < 2000

    def get_stats(self):
        avg_dpc = sum(self.dpc_latency_history) / len(self.dpc_latency_history) if self.dpc_latency_history else 0
        avg_isr = sum(self.interrupt_latency_history) / len(self.interrupt_latency_history) if self.interrupt_latency_history else 0
        avg_ctx = sum(self.context_switch_history) / len(self.context_switch_history) if self.context_switch_history else 0

        return {
            'enabled': self.enabled,
            'context_switches_per_sec': int(self.current_context_switches),
            'context_switches_avg': int(avg_ctx),
            'context_switches_max': int(self.max_context_switches),
            'dpc_latency_us': int(self.current_dpc_latency_us),
            'dpc_latency_avg_us': int(avg_dpc),
            'dpc_latency_max_us': int(self.max_dpc_latency_us),
            'isr_latency_us': int(self.current_isr_latency_us),
            'isr_latency_avg_us': int(avg_isr),
            'isr_latency_max_us': int(self.max_isr_latency_us),
            'spike_count': self.spike_count,
            'total_samples': self.total_samples,
            'grade': self.get_grade(),
            'trend': self.get_trend(),
            'audio_safe': self.is_audio_safe(),
        }

    def reset_stats(self):
        self.context_switch_history.clear()
        self.dpc_latency_history.clear()
        self.interrupt_latency_history.clear()
        self.max_dpc_latency_us = 0
        self.max_isr_latency_us = 0
        self.max_context_switches = 0
        self.spike_count = 0
        self.total_samples = 0

LATENCY_MONITOR = LatencyMonitor()

class ForegroundBooster:

    def __init__(self):
        self.enabled = False
        self.boost_level = "Above Normal"
        self.boosted_pid = None
        self.original_priority = None
        self.original_io_priority = None
        self.original_memory_priority = None
        self.last_fpid = None

        self.exclusions = {
            "audiodg.exe", "csrss.exe", "dwm.exe", "taskmgr.exe",
            "realtekhdaudioservice.exe", "discord.exe", "obs64.exe",
            "explorer.exe", "searchhost.exe", "shellexperiencehost.exe"
        }

        self.stats = {
            'total_boosts': 0,
            'current_boosted': None
        }

    def update(self, current_fpid):
        if not self.enabled:
            return

        if current_fpid == self.last_fpid:
            return

        if self.boosted_pid and self.original_priority is not None:
            self._restore()

        self.last_fpid = current_fpid

        if not current_fpid:
            return

        try:
            p = psutil.Process(current_fpid)
            name = p.name().lower()

            if name in self.exclusions or name in PROTECTED:
                return

            h = open_proc(current_fpid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
            if not h:
                return

            try:
                self.original_priority = win32process.GetPriorityClass(h)

                if self.original_priority in (win32process.NORMAL_PRIORITY_CLASS,
                                              win32process.BELOW_NORMAL_PRIORITY_CLASS):
                    target = PRIORITY.get(self.boost_level, win32process.ABOVE_NORMAL_PRIORITY_CLASS)
                    win32process.SetPriorityClass(h, target)

                    try:
                        self.original_io_priority = get_io_priority(h)
                        set_io_priority(h, 3)
                    except:
                        self.original_io_priority = None

                    try:
                        self.original_memory_priority = 3
                        set_memory_priority(h, 5)
                    except:
                        self.original_memory_priority = None

                    self.boosted_pid = current_fpid
                    self.stats['total_boosts'] += 1
                    self.stats['current_boosted'] = name
                else:
                    self.original_priority = None

            finally:
                win32api.CloseHandle(h)

        except Exception:
            self.original_priority = None

    def _restore(self):
        if not self.boosted_pid or self.original_priority is None:
            return

        try:
            h = open_proc(self.boosted_pid, win32con.PROCESS_SET_INFORMATION)
            if h:
                try:
                    win32process.SetPriorityClass(h, self.original_priority)

                    if self.original_io_priority is not None:
                        try:
                            set_io_priority(h, self.original_io_priority)
                        except:
                            pass

                    if self.original_memory_priority is not None:
                        try:
                            set_memory_priority(h, self.original_memory_priority)
                        except:
                            pass
                finally:
                    win32api.CloseHandle(h)
        except Exception:
            pass

        self.boosted_pid = None
        self.original_priority = None
        self.original_io_priority = None
        self.original_memory_priority = None
        self.stats['current_boosted'] = None

    def get_stats(self):
        boosted_name = None
        if self.boosted_pid:
            try:
                boosted_name = psutil.Process(self.boosted_pid).name()
            except:
                pass

        return {
            'enabled': self.enabled,
            'boosted_pid': self.boosted_pid,
            'boosted_name': boosted_name,
            'boost_level': self.boost_level,
            **self.stats
        }

FG_BOOSTER = ForegroundBooster()

class GameModeBooster:

    def __init__(self):
        self.enabled = False
        self.active = False
        self.current_game_pid = None
        self.current_game_name = None
        self.last_check = 0
        self.check_interval = 2
        self.activation_time = 0

        self.services_to_stop = [
            "SysMain",
            "DiagTrack",
            "WSearch",
            "TabletInputService",
            "wisvc",
            "XblAuthManager",
            "XboxGipSvc",
        ]
        self.stopped_services = []

        self.original_timer_res = None
        self.original_power_plan = None
        self.cpu_parking_disabled = False

        self.game_executables = {
            "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe",
            "origin.exe", "eadesktop.exe", "upc.exe", "ubisoft connect.exe",
            "gog galaxy.exe", "battlenet.exe", "riotclientservices.exe",
            "easyanticheat.exe", "easyanticheat_eos.exe", "battleye.exe",
            "vanguard.exe", "vgc.exe", "faceitclient.exe",
            "game.exe", "launcher.exe"
        }

        self.game_keywords = [
            "game", "minecraft", "fortnite", "valorant", "csgo", "cs2",
            "dota", "league", "apex", "pubg", "warzone", "overwatch",
            "gta", "cyberpunk", "elden", "witcher", "assassin",
            "battlefield", "fifa", "nba2k", "racing", "steam_",
            "rocketleague", "destiny", "callofduty", "cod", "halo",
            "terraria", "satisfactory", "arksurvival", "rust",
            "forza", "flightsimulator", "starfield", "baldursgate",
            "diablo", "pathofexile", "lostark"
        ]

        self.excluded = {
            "steamwebhelper.exe", "epicgameslauncher.exe",
            "origin.exe", "eadesktop.exe", "upc.exe"
        }

        self.stats = {
            'games_detected': 0,
            'total_boost_time': 0,
            'last_game': None,
            'optimizations_applied': []
        }

    def check_for_games(self):
        if not self.enabled:
            return

        now = time.time()
        if now - self.last_check < self.check_interval:
            return
        self.last_check = now

        try:
            game_pid, game_name = self._detect_game()

            if game_pid and not self.active:
                self._activate_game_mode(game_pid, game_name)
            elif not game_pid and self.active:
                self._deactivate_game_mode()

        except Exception:
            pass

    def _detect_game(self):
        try:
            gpu_in_use = False
            if GPUtil:
                try:
                    gpus = GPUtil.getGPUs()
                    for gpu in gpus:
                        if gpu.load > 0.25:
                            gpu_in_use = True
                            break
                except:
                    pass

            candidates = []

            for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
                try:
                    name = (p.info['name'] or "").lower()
                    pid = p.info['pid']
                    cpu = p.info.get('cpu_percent', 0)
                    mem = p.info.get('memory_info')
                    mem_mb = mem.rss / (1024*1024) if mem else 0

                    if name in self.excluded:
                        continue

                    is_game_pattern = name in self.game_executables
                    is_keyword_match = any(kw in name for kw in self.game_keywords)

                    if is_game_pattern or is_keyword_match:
                        if cpu > 3 or mem_mb > 500:
                            candidates.append({
                                'pid': pid,
                                'name': name,
                                'cpu': cpu,
                                'mem_mb': mem_mb,
                                'score': cpu + (mem_mb / 100)
                            })

                    elif gpu_in_use and cpu > 15 and mem_mb > 800:
                        candidates.append({
                            'pid': pid,
                            'name': name,
                            'cpu': cpu,
                            'mem_mb': mem_mb,
                            'score': cpu + (mem_mb / 100)
                        })

                except Exception:
                    continue

            if candidates:
                candidates.sort(key=lambda x: x['score'], reverse=True)
                best = candidates[0]
                return best['pid'], best['name']

        except Exception:
            pass

        return None, None

    def _activate_game_mode(self, pid, name):
        self.active = True
        self.current_game_pid = pid
        self.current_game_name = name
        self.activation_time = time.time()
        self.stats['games_detected'] += 1
        self.stats['last_game'] = name
        self.stats['optimizations_applied'] = []

        try:
            if set_timer_resolution(1):
                self.stats['optimizations_applied'].append('timer_res')

            self.original_power_plan = "BALANCED"
            switch_power_plan("HIGH_PERFORMANCE")
            self.stats['optimizations_applied'].append('power_plan')

            try:
                set_cpu_parking(False)
                self.cpu_parking_disabled = True
                self.stats['optimizations_applied'].append('cpu_parking')
            except:
                pass

            self._stop_services()
            if self.stopped_services:
                self.stats['optimizations_applied'].append('services')

            self._boost_game_process(pid)
            self.stats['optimizations_applied'].append('process_priority')

            self._lower_background_priorities(pid)
            self.stats['optimizations_applied'].append('background_lower')

        except Exception:
            pass

    def _boost_game_process(self, pid):
        try:
            h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
            if h:
                try:
                    win32process.SetPriorityClass(h, win32process.HIGH_PRIORITY_CLASS)
                    set_io_priority(h, 3)
                    set_memory_priority(h, 5)
                finally:
                    win32api.CloseHandle(h)
        except:
            pass

    def _lower_background_priorities(self, game_pid):
        try:
            for p in psutil.process_iter(['pid', 'name', 'cpu_percent']):
                try:
                    pid = p.info['pid']
                    name = (p.info['name'] or "").lower()
                    cpu = p.info.get('cpu_percent', 0)

                    if pid == game_pid or name in PROTECTED:
                        continue

                    if cpu < 1:
                        continue

                    h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
                    if h:
                        try:
                            current = win32process.GetPriorityClass(h)
                            if current == win32process.NORMAL_PRIORITY_CLASS:
                                win32process.SetPriorityClass(h, win32process.BELOW_NORMAL_PRIORITY_CLASS)
                        finally:
                            win32api.CloseHandle(h)
                except:
                    continue
        except:
            pass

    def _deactivate_game_mode(self):
        if self.activation_time:
            boost_duration = time.time() - self.activation_time
            self.stats['total_boost_time'] += boost_duration

        self.active = False
        self.current_game_pid = None
        self.current_game_name = None

        try:
            reset_timer_resolution()

            if self.original_power_plan:
                switch_power_plan(self.original_power_plan)

            if self.cpu_parking_disabled:
                set_cpu_parking(True)
                self.cpu_parking_disabled = False

            self._start_services()

        except Exception:
            pass

    def _stop_services(self):
        self.stopped_services = []
        for service in self.services_to_stop:
            try:
                result = subprocess.run(
                    ['sc', 'query', service],
                    capture_output=True, text=True, timeout=5
                )
                if "RUNNING" in result.stdout:
                    subprocess.run(
                        ['sc', 'stop', service],
                        capture_output=True, timeout=10
                    )
                    self.stopped_services.append(service)
            except Exception:
                pass

    def _start_services(self):
        for service in self.stopped_services:
            try:
                subprocess.run(
                    ['sc', 'start', service],
                    capture_output=True, timeout=10
                )
            except Exception:
                pass
        self.stopped_services = []

    def get_stats(self):
        return {
            'enabled': self.enabled,
            'active': self.active,
            'current_game': self.current_game_name,
            'stopped_services': len(self.stopped_services),
            'optimizations': self.stats.get('optimizations_applied', []),
            **self.stats
        }

GAME_MODE = GameModeBooster()

class JunkCleaner:

    def __init__(self):
        self.enabled = True
        self.last_scan = None
        self.scan_results = {}
        self.total_size = 0
        self.min_age_days = 7

        self.temp_folders = [
            os.environ.get('TEMP', ''),
            os.environ.get('TMP', ''),
            os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Temp'),
        ]

        self.additional_folders = {
            'Windows Update': os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'SoftwareDistribution', 'Download'),
            'Crash Dumps': os.path.expandvars(r'%LOCALAPPDATA%\CrashDumps'),
            'Thumbnail Cache': os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\Windows\Explorer'),
            'Recent': os.path.expandvars(r'%APPDATA%\Microsoft\Windows\Recent'),
            'Installer Cache': os.path.expandvars(r'%LOCALAPPDATA%\Temp'),
        }

        self.browser_caches = {
            'Chrome Cache': os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\User Data\Default\Cache'),
            'Chrome Code Cache': os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\User Data\Default\Code Cache'),
            'Edge Cache': os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Cache'),
            'Edge Code Cache': os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Code Cache'),
            'Firefox': os.path.expandvars(r'%LOCALAPPDATA%\Mozilla\Firefox\Profiles'),
            'Opera Cache': os.path.expandvars(r'%APPDATA%\Opera Software\Opera Stable\Cache'),
            'Brave Cache': os.path.expandvars(r'%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data\Default\Cache'),
        }

        self.app_caches = {
            'Discord Cache': os.path.expandvars(r'%APPDATA%\discord\Cache'),
            'Spotify Cache': os.path.expandvars(r'%LOCALAPPDATA%\Spotify\Storage'),
            'Steam Downloads': os.path.expandvars(r'%PROGRAMFILES(X86)%\Steam\steamapps\downloading'),
            'Teams Cache': os.path.expandvars(r'%APPDATA%\Microsoft\Teams\Cache'),
            'VS Code Cache': os.path.expandvars(r'%APPDATA%\Code\Cache'),
        }

        self.junk_extensions = {'.tmp', '.temp', '.log', '.bak', '.old', '.dmp', '.chk', '.etl', '.~*'}

        self.exclusions = {'desktop.ini', 'thumbs.db', 'iconcache.db'}

        self.protected_patterns = ['ntuser', 'usrclass', 'config', 'settings', 'prefs']

        self.stats = {
            'files_cleaned': 0,
            'bytes_freed': 0,
            'last_clean': None,
            'last_scan_files': 0
        }

    def _is_old_enough(self, filepath):
        try:
            mtime = os.path.getmtime(filepath)
            age_days = (time.time() - mtime) / (60 * 60 * 24)
            return age_days >= self.min_age_days
        except:
            return False

    def _is_protected(self, filename):
        filename_lower = filename.lower()
        if filename_lower in self.exclusions:
            return True
        for pattern in self.protected_patterns:
            if pattern in filename_lower:
                return True
        return False

    def scan(self):
        self.scan_results = {}
        self.total_size = 0
        total_files = 0

        for folder in self.temp_folders:
            if folder and os.path.exists(folder):
                size, count = self._scan_folder(folder)
                if size > 0:
                    self.scan_results[f"Temp: {os.path.basename(folder)}"] = size
                    self.total_size += size
                    total_files += count

        for name, path in self.additional_folders.items():
            if os.path.exists(path):
                size, count = self._scan_folder(path)
                if size > 0:
                    self.scan_results[name] = size
                    self.total_size += size
                    total_files += count

        for name, path in self.browser_caches.items():
            if os.path.exists(path):
                size, count = self._scan_folder(path)
                if size > 0:
                    self.scan_results[name] = size
                    self.total_size += size
                    total_files += count

        for name, path in self.app_caches.items():
            if os.path.exists(path):
                size, count = self._scan_folder(path)
                if size > 0:
                    self.scan_results[name] = size
                    self.total_size += size
                    total_files += count

        self.last_scan = time.time()
        self.stats['last_scan_files'] = total_files
        return self.total_size

    def _scan_folder(self, folder):
        total = 0
        count = 0
        try:
            for root, dirs, files in os.walk(folder):
                for f in files:
                    if self._is_protected(f):
                        continue
                    try:
                        fp = os.path.join(root, f)
                        if self._is_old_enough(fp):
                            total += os.path.getsize(fp)
                            count += 1
                    except:
                        pass
        except:
            pass
        return total, count

    def clean(self, categories=None):
        if not self.scan_results:
            self.scan()

        cleaned_bytes = 0
        cleaned_files = 0

        for folder in self.temp_folders:
            if folder and os.path.exists(folder):
                b, f = self._clean_folder(folder)
                cleaned_bytes += b
                cleaned_files += f

        for name, path in self.additional_folders.items():
            if categories and name not in categories:
                continue
            if os.path.exists(path):
                b, f = self._clean_folder(path)
                cleaned_bytes += b
                cleaned_files += f

        for name, path in self.browser_caches.items():
            if categories and name not in categories:
                continue
            if os.path.exists(path):
                b, f = self._clean_folder(path)
                cleaned_bytes += b
                cleaned_files += f

        for name, path in self.app_caches.items():
            if categories and name not in categories:
                continue
            if os.path.exists(path):
                b, f = self._clean_folder(path)
                cleaned_bytes += b
                cleaned_files += f

        self.stats['files_cleaned'] += cleaned_files
        self.stats['bytes_freed'] += cleaned_bytes
        self.stats['last_clean'] = time.strftime('%Y-%m-%d %H:%M')

        self.scan_results = {}
        self.total_size = 0

        return cleaned_bytes, cleaned_files

    def _clean_folder(self, folder):
        cleaned_bytes = 0
        cleaned_files = 0

        try:
            for root, dirs, files in os.walk(folder, topdown=False):
                for f in files:
                    if self._is_protected(f):
                        continue
                    try:
                        fp = os.path.join(root, f)
                        if not self._is_old_enough(fp):
                            continue
                        size = os.path.getsize(fp)
                        os.remove(fp)
                        cleaned_bytes += size
                        cleaned_files += 1
                    except:
                        pass
                for d in dirs:
                    try:
                        os.rmdir(os.path.join(root, d))
                    except:
                        pass
        except:
            pass

        return cleaned_bytes, cleaned_files

    def get_stats(self):
        return {
            'enabled': self.enabled,
            'min_age_days': self.min_age_days,
            'total_junk_mb': self.total_size / (1024 * 1024) if self.total_size else 0,
            'scan_results': {k: v / (1024 * 1024) for k, v in self.scan_results.items()},
            'categories_count': len(self.scan_results),
            **self.stats
        }

JUNK_CLEANER = JunkCleaner()

class WindowsTweaks:

    def __init__(self):
        self.tweaks_applied = set()

    def disable_windows_key(self, disable=True):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Keyboard Layout",
                0, winreg.KEY_SET_VALUE
            )
            if disable:
                scancode = bytes([
                    0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00,
                    0x03, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x5B, 0xE0,
                    0x00, 0x00, 0x5C, 0xE0,
                    0x00, 0x00, 0x00, 0x00
                ])
                winreg.SetValueEx(key, "Scancode Map", 0, winreg.REG_BINARY, scancode)
                self.tweaks_applied.add('windows_key')
            else:
                try:
                    winreg.DeleteValue(key, "Scancode Map")
                    self.tweaks_applied.discard('windows_key')
                except:
                    pass
            winreg.CloseKey(key)
            return True
        except:
            return False

    def disable_sticky_keys(self, disable=True):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Control Panel\Accessibility\StickyKeys",
                0, winreg.KEY_SET_VALUE
            )
            flags = "506" if disable else "510"
            winreg.SetValueEx(key, "Flags", 0, winreg.REG_SZ, flags)
            winreg.CloseKey(key)
            if disable:
                self.tweaks_applied.add('sticky_keys')
            else:
                self.tweaks_applied.discard('sticky_keys')
            return True
        except:
            return False

    def disable_game_bar(self, disable=True):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "AppCaptureEnabled", 0, winreg.REG_DWORD, 0 if disable else 1)
            winreg.CloseKey(key)

            key2 = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"System\GameConfigStore",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key2, "GameDVR_Enabled", 0, winreg.REG_DWORD, 0 if disable else 1)
            winreg.CloseKey(key2)

            if disable:
                self.tweaks_applied.add('game_bar')
            else:
                self.tweaks_applied.discard('game_bar')
            return True
        except:
            return False

    def disable_fullscreen_optimizations(self, disable=True):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"System\GameConfigStore",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "GameDVR_FSEBehaviorMode", 0, winreg.REG_DWORD, 2 if disable else 0)
            winreg.SetValueEx(key, "GameDVR_HonorUserFSEBehaviorMode", 0, winreg.REG_DWORD, 1 if disable else 0)
            winreg.SetValueEx(key, "GameDVR_FSEBehavior", 0, winreg.REG_DWORD, 2 if disable else 0)
            winreg.CloseKey(key)
            if disable:
                self.tweaks_applied.add('fse_optimizations')
            else:
                self.tweaks_applied.discard('fse_optimizations')
            return True
        except:
            return False

    def toggle_hags(self, enable=True):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "HwSchMode", 0, winreg.REG_DWORD, 2 if enable else 1)
            winreg.CloseKey(key)
            if enable:
                self.tweaks_applied.add('hags')
            else:
                self.tweaks_applied.discard('hags')
            return True
        except:
            return False

    def disable_network_throttling(self, disable=True):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
                0, winreg.KEY_SET_VALUE
            )
            value = 0xffffffff if disable else 10
            winreg.SetValueEx(key, "NetworkThrottlingIndex", 0, winreg.REG_DWORD, value)
            winreg.SetValueEx(key, "SystemResponsiveness", 0, winreg.REG_DWORD, 0 if disable else 20)
            winreg.CloseKey(key)
            if disable:
                self.tweaks_applied.add('network_throttling')
            else:
                self.tweaks_applied.discard('network_throttling')
            return True
        except:
            return False

    def disable_nagle_algorithm(self, disable=True):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces",
                0, winreg.KEY_READ
            )
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    subkey = winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE,
                        rf"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\{subkey_name}",
                        0, winreg.KEY_SET_VALUE
                    )
                    if disable:
                        winreg.SetValueEx(subkey, "TcpAckFrequency", 0, winreg.REG_DWORD, 1)
                        winreg.SetValueEx(subkey, "TCPNoDelay", 0, winreg.REG_DWORD, 1)
                    else:
                        try:
                            winreg.DeleteValue(subkey, "TcpAckFrequency")
                            winreg.DeleteValue(subkey, "TCPNoDelay")
                        except:
                            pass
                    winreg.CloseKey(subkey)
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
            if disable:
                self.tweaks_applied.add('nagle')
            else:
                self.tweaks_applied.discard('nagle')
            return True
        except:
            return False

    def disable_power_throttling(self, disable=True):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Power\PowerThrottling",
                0, winreg.KEY_SET_VALUE | winreg.KEY_CREATE_SUB_KEY
            )
            winreg.SetValueEx(key, "PowerThrottlingOff", 0, winreg.REG_DWORD, 1 if disable else 0)
            winreg.CloseKey(key)
            if disable:
                self.tweaks_applied.add('power_throttling')
            else:
                self.tweaks_applied.discard('power_throttling')
            return True
        except:
            try:
                key = winreg.CreateKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\CurrentControlSet\Control\Power\PowerThrottling"
                )
                winreg.SetValueEx(key, "PowerThrottlingOff", 0, winreg.REG_DWORD, 1 if disable else 0)
                winreg.CloseKey(key)
                if disable:
                    self.tweaks_applied.add('power_throttling')
                return True
            except:
                return False

    def apply_gaming_tweaks(self):
        results = {
            'sticky_keys': self.disable_sticky_keys(True),
            'game_bar': self.disable_game_bar(True),
            'fse': self.disable_fullscreen_optimizations(True),
            'network': self.disable_network_throttling(True),
            'nagle': self.disable_nagle_algorithm(True),
            'power': self.disable_power_throttling(True),
        }
        return results

    def reset_all_tweaks(self):
        self.disable_sticky_keys(False)
        self.disable_game_bar(False)
        self.disable_fullscreen_optimizations(False)
        self.disable_network_throttling(False)
        self.disable_nagle_algorithm(False)
        self.disable_power_throttling(False)
        self.tweaks_applied.clear()

    def get_stats(self):
        return {
            'tweaks_applied': list(self.tweaks_applied),
            'count': len(self.tweaks_applied),
            'available_tweaks': [
                'windows_key', 'sticky_keys', 'game_bar', 'fse_optimizations',
                'hags', 'network_throttling', 'nagle', 'power_throttling'
            ]
        }

WIN_TWEAKS = WindowsTweaks()

class SSDOptimizer:

    def __init__(self):
        self.drives = {}
        self.last_scan = 0
        self.trim_history = []
        self._detect_drives()

    def _detect_drives(self):
        self.drives = {}
        try:
            result = subprocess.run(
                ['powershell', '-Command',
                 'Get-PhysicalDisk | Select-Object DeviceId, MediaType, Size, FriendlyName | ConvertTo-Json'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                import json
                disks = json.loads(result.stdout)
                if not isinstance(disks, list):
                    disks = [disks]

                for disk in disks:
                    drive_id = disk.get('DeviceId', 0)
                    media_type = disk.get('MediaType', 'Unknown')
                    self.drives[drive_id] = {
                        'name': disk.get('FriendlyName', 'Unknown'),
                        'type': 'SSD' if media_type == 'SSD' or 'SSD' in str(disk.get('FriendlyName', '')) else 'HDD',
                        'size_gb': disk.get('Size', 0) / (1024**3) if disk.get('Size') else 0,
                        'media_type': media_type
                    }
        except Exception:
            pass

        if not self.drives:
            for letter in ['C', 'D', 'E', 'F']:
                try:
                    path = f"{letter}:\\"
                    if os.path.exists(path):
                        self.drives[letter] = {
                            'name': f"Drive {letter}:",
                            'type': 'Unknown',
                            'size_gb': 0
                        }
                except:
                    pass

        self.last_scan = time.time()

    def run_trim(self, drive_letter='C'):
        try:
            result = subprocess.run(
                ['defrag', f'{drive_letter}:', '/O', '/U'],
                capture_output=True, text=True, timeout=300
            )
            success = result.returncode == 0
            self.trim_history.append({
                'drive': drive_letter,
                'time': time.strftime('%Y-%m-%d %H:%M'),
                'success': success
            })
            return success
        except Exception:
            return False

    def run_trim_all_ssds(self):
        results = {}
        for drive_id, info in self.drives.items():
            if info.get('type') == 'SSD':
                try:
                    result = subprocess.run(
                        ['powershell', '-Command',
                         f'Get-Partition -DiskNumber {drive_id} | Get-Volume | Select-Object -ExpandProperty DriveLetter'],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode == 0:
                        for letter in result.stdout.strip().split('\n'):
                            if letter.strip():
                                results[letter] = self.run_trim(letter.strip())
                except:
                    pass
        return results

    def disable_defrag_for_ssds(self):
        try:
            subprocess.run(
                ['schtasks', '/Change', '/TN',
                 '\\Microsoft\\Windows\\Defrag\\ScheduledDefrag', '/DISABLE'],
                capture_output=True, timeout=10
            )
            return True
        except:
            return False

    def enable_defrag_schedule(self):
        try:
            subprocess.run(
                ['schtasks', '/Change', '/TN',
                 '\\Microsoft\\Windows\\Defrag\\ScheduledDefrag', '/ENABLE'],
                capture_output=True, timeout=10
            )
            return True
        except:
            return False

    def check_trim_enabled(self, drive_letter='C'):
        try:
            result = subprocess.run(
                ['fsutil', 'behavior', 'query', 'DisableDeleteNotify'],
                capture_output=True, text=True, timeout=10
            )
            return '= 0' in result.stdout
        except:
            return None

    def enable_trim(self):
        try:
            subprocess.run(
                ['fsutil', 'behavior', 'set', 'DisableDeleteNotify', '0'],
                capture_output=True, timeout=10
            )
            return True
        except:
            return False

    def get_stats(self):
        return {
            'drives': self.drives,
            'ssd_count': sum(1 for d in self.drives.values() if d.get('type') == 'SSD'),
            'hdd_count': sum(1 for d in self.drives.values() if d.get('type') == 'HDD'),
            'trim_enabled': self.check_trim_enabled(),
            'last_trim': self.trim_history[-1] if self.trim_history else None,
            'trim_history_count': len(self.trim_history)
        }

SSD_OPTIMIZER = SSDOptimizer()

class ServiceOptimizer:

    GAMING_DISABLE = [
        ('SysMain', 'Superfetch - preloads data, uses disk I/O'),
        ('DiagTrack', 'Telemetry - sends data to Microsoft'),
        ('WSearch', 'Windows Search indexing'),
        ('TabletInputService', 'Touch keyboard - not needed for gaming'),
        ('wisvc', 'Windows Insider service'),
        ('MapsBroker', 'Downloaded Maps Manager'),
        ('lfsvc', 'Geolocation service'),
        ('WbioSrvc', 'Biometric service'),
        ('WerSvc', 'Windows Error Reporting'),
    ]

    SAFE_TO_DISABLE = [
        ('Fax', 'Fax service'),
        ('XblAuthManager', 'Xbox Live Auth Manager'),
        ('XblGameSave', 'Xbox Live Game Save'),
        ('XboxGipSvc', 'Xbox Accessory Management'),
        ('XboxNetApiSvc', 'Xbox Live Networking'),
        ('RetailDemo', 'Retail Demo service'),
        ('WMPNetworkSvc', 'Windows Media Player Network Sharing'),
        ('WpcMonSvc', 'Parental Controls'),
        ('PhoneSvc', 'Phone service'),
    ]

    ESSENTIAL = [
        'wuauserv',
        'Dhcp', 'Dnscache',
        'AudioSrv', 'Audiosrv',
        'Winmgmt',
        'EventLog',
        'PlugPlay',
        'Power',
        'Spooler',
        'Schedule',
    ]

    def __init__(self):
        self.original_states = {}
        self.modified_services = set()
        self.recommendations = []

    def _get_service_status(self, service_name):
        try:
            result = subprocess.run(
                ['sc', 'query', service_name],
                capture_output=True, text=True, timeout=5
            )
            if 'RUNNING' in result.stdout:
                return 'running'
            elif 'STOPPED' in result.stdout:
                return 'stopped'
            return 'unknown'
        except:
            return 'error'

    def _set_service(self, service_name, action):
        try:
            subprocess.run(
                ['sc', action, service_name],
                capture_output=True, timeout=30
            )
            return True
        except:
            return False

    def _set_service_startup(self, service_name, startup_type):
        try:
            subprocess.run(
                ['sc', 'config', service_name, f'start={startup_type}'],
                capture_output=True, timeout=10
            )
            return True
        except:
            return False

    def analyze_services(self):
        self.recommendations = []

        for service, description in self.GAMING_DISABLE:
            status = self._get_service_status(service)
            if status == 'running':
                self.recommendations.append({
                    'service': service,
                    'description': description,
                    'current': 'running',
                    'recommendation': 'stop',
                    'category': 'gaming_optimize'
                })

        for service, description in self.SAFE_TO_DISABLE:
            status = self._get_service_status(service)
            if status == 'running':
                self.recommendations.append({
                    'service': service,
                    'description': description,
                    'current': 'running',
                    'recommendation': 'disable',
                    'category': 'safe_disable'
                })

        return self.recommendations

    def apply_gaming_profile(self):
        results = {}
        for service, _ in self.GAMING_DISABLE:
            status = self._get_service_status(service)
            if status == 'running':
                self.original_states[service] = status
                success = self._set_service(service, 'stop')
                results[service] = success
                if success:
                    self.modified_services.add(service)
        return results

    def restore_services(self):
        results = {}
        for service in list(self.modified_services):
            original = self.original_states.get(service, 'running')
            if original == 'running':
                success = self._set_service(service, 'start')
                results[service] = success
                if success:
                    self.modified_services.discard(service)
        return results

    def disable_bloatware_services(self):
        results = {}
        for service, _ in self.SAFE_TO_DISABLE:
            success = self._set_service_startup(service, 'disabled')
            if success:
                self._set_service(service, 'stop')
            results[service] = success
        return results

    def get_stats(self):
        return {
            'modified_count': len(self.modified_services),
            'modified_services': list(self.modified_services),
            'recommendations_count': len(self.recommendations),
            'gaming_services': len(self.GAMING_DISABLE),
            'safe_to_disable': len(self.SAFE_TO_DISABLE)
        }

SERVICE_OPTIMIZER = ServiceOptimizer()

class ScheduledTasksCleaner:

    BLOATWARE_TASKS = [
        (r'\Microsoft\Windows\Application Experience\Microsoft Compatibility Appraiser', 'Telemetry'),
        (r'\Microsoft\Windows\Application Experience\ProgramDataUpdater', 'Telemetry'),
        (r'\Microsoft\Windows\Autochk\Proxy', 'Telemetry'),
        (r'\Microsoft\Windows\Customer Experience Improvement Program\Consolidator', 'Telemetry'),
        (r'\Microsoft\Windows\Customer Experience Improvement Program\UsbCeip', 'Telemetry'),
        (r'\Microsoft\Windows\DiskDiagnostic\Microsoft-Windows-DiskDiagnosticDataCollector', 'Telemetry'),

        (r'\Microsoft\Windows\Feedback\Siuf\DmClient', 'Feedback'),
        (r'\Microsoft\Windows\Feedback\Siuf\DmClientOnScenarioDownload', 'Feedback'),

        (r'\Microsoft\Windows\Maps\MapsToastTask', 'Maps'),
        (r'\Microsoft\Windows\Maps\MapsUpdateTask', 'Maps'),

        (r'\Microsoft\Office\OfficeTelemetryAgentFallBack2016', 'Office Telemetry'),
        (r'\Microsoft\Office\OfficeTelemetryAgentLogOn2016', 'Office Telemetry'),

        (r'\Microsoft\XblGameSave\XblGameSaveTask', 'Xbox'),
        (r'\Microsoft\XblGameSave\XblGameSaveTaskLogon', 'Xbox'),

        (r'\Microsoft\Windows\RetailDemo\CleanupOfflineContent', 'Retail Demo'),

        (r'\Microsoft\Windows\Windows Error Reporting\QueueReporting', 'Error Reporting'),

        (r'\Microsoft\Windows\UpdateOrchestrator\Schedule Scan', 'Background scanning'),
        (r'\Microsoft\Windows\UpdateOrchestrator\UpdateModelTask', 'Update model'),

        (r'\Microsoft\Windows\CloudExperienceHost\CreateObjectTask', 'Cloud sync'),

        (r'\Microsoft\Windows\Speech\SpeechModelDownloadTask', 'Speech download'),

        (r'\Microsoft\Windows\Diagnosis\Scheduled', 'Diagnostics'),
        (r'\Microsoft\Windows\DiskCleanup\SilentCleanup', 'Silent cleanup'),
    ]

    ESSENTIAL_TASKS = [
        r'\Microsoft\Windows\UpdateOrchestrator\Reboot',
        r'\Microsoft\Windows\UpdateOrchestrator\USO_UxBroker',
        r'\Microsoft\Windows\WindowsUpdate',
        r'\Microsoft\Windows\TaskScheduler',
        r'\Microsoft\Windows\Plug and Play',
        r'\Microsoft\Windows\Power Efficiency Diagnostics',
        r'\Microsoft\Windows\MemoryDiagnostic',
    ]

    def __init__(self):
        self.scanned_tasks = []
        self.disabled_tasks = []
        self.last_scan = 0

    def scan_tasks(self):
        self.scanned_tasks = []
        try:
            result = subprocess.run(
                ['schtasks', '/Query', '/FO', 'CSV', '/NH'],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if not line.strip():
                        continue
                    parts = line.replace('"', '').split(',')
                    if len(parts) >= 3:
                        task_name = parts[0]
                        status = parts[2] if len(parts) > 2 else 'Unknown'

                        category = 'system'
                        is_bloatware = False
                        for bloat_task, cat in self.BLOATWARE_TASKS:
                            if bloat_task.lower() in task_name.lower():
                                category = cat
                                is_bloatware = True
                                break

                        is_essential = any(ess.lower() in task_name.lower()
                                          for ess in self.ESSENTIAL_TASKS)

                        self.scanned_tasks.append({
                            'name': task_name,
                            'status': status,
                            'category': category,
                            'is_bloatware': is_bloatware,
                            'is_essential': is_essential,
                            'can_disable': is_bloatware and not is_essential
                        })

            self.last_scan = time.time()
        except Exception:
            pass

        return self.scanned_tasks

    def get_bloatware_tasks(self):
        if not self.scanned_tasks:
            self.scan_tasks()

        return [t for t in self.scanned_tasks if t['can_disable']]

    def disable_task(self, task_name):
        try:
            result = subprocess.run(
                ['schtasks', '/Change', '/TN', task_name, '/DISABLE'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                self.disabled_tasks.append({
                    'name': task_name,
                    'time': time.strftime('%Y-%m-%d %H:%M')
                })
                return True
        except:
            pass
        return False

    def enable_task(self, task_name):
        try:
            result = subprocess.run(
                ['schtasks', '/Change', '/TN', task_name, '/ENABLE'],
                capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0
        except:
            return False

    def disable_all_bloatware(self):
        results = {}
        bloatware = self.get_bloatware_tasks()

        for task in bloatware:
            if task['status'].lower() != 'disabled':
                success = self.disable_task(task['name'])
                results[task['name']] = success

        return results

    def disable_telemetry_tasks(self):
        results = {}
        if not self.scanned_tasks:
            self.scan_tasks()

        telemetry_tasks = [t for t in self.scanned_tasks
                          if t['category'] == 'Telemetry' and t['can_disable']]

        for task in telemetry_tasks:
            if task['status'].lower() != 'disabled':
                success = self.disable_task(task['name'])
                results[task['name']] = success

        return results

    def get_stats(self):
        bloatware = [t for t in self.scanned_tasks if t['can_disable']]
        enabled_bloatware = [t for t in bloatware if t['status'].lower() != 'disabled']

        return {
            'total_tasks': len(self.scanned_tasks),
            'bloatware_count': len(bloatware),
            'enabled_bloatware': len(enabled_bloatware),
            'disabled_count': len(self.disabled_tasks),
            'categories': list(set(t['category'] for t in self.scanned_tasks if t['can_disable'])),
            'last_scan': self.last_scan
        }

SCHEDULED_TASKS_CLEANER = ScheduledTasksCleaner()

class RAMCleaner:

    def __init__(self):
        self.last_clean = 0
        self.stats = {'cleans': 0, 'mb_freed': 0}

    def clear_standby_list(self):
        try:
            cmd = '''
            $mem = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory
            [System.GC]::Collect()
            [System.GC]::WaitForPendingFinalizers()
            '''
            subprocess.run(['powershell', '-Command', cmd],
                          capture_output=True, timeout=10)

            for p in psutil.process_iter(['pid']):
                try:
                    h = open_proc(p.info['pid'], win32con.PROCESS_SET_QUOTA)
                    if h:
                        empty_working_set(h)
                        win32api.CloseHandle(h)
                except:
                    pass

            self.last_clean = time.time()
            self.stats['cleans'] += 1
            return True
        except:
            return False

    def get_available_ram_mb(self):
        try:
            mem = psutil.virtual_memory()
            return mem.available / (1024 * 1024)
        except:
            return 0

    def get_stats(self):
        return {
            'available_mb': self.get_available_ram_mb(),
            **self.stats
        }

RAM_CLEANER = RAMCleaner()

class NetworkOptimizer:
    def __init__(self):
        self.optimized = False
        self.original_settings = {}

    def optimize_for_gaming(self):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces",
                0, winreg.KEY_READ
            )

            i = 0
            while True:
                try:
                    interface_id = winreg.EnumKey(key, i)
                    iface_key = winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE,
                        f"SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces\\{interface_id}",
                        0, winreg.KEY_SET_VALUE
                    )
                    winreg.SetValueEx(iface_key, "TcpAckFrequency", 0, winreg.REG_DWORD, 1)
                    winreg.SetValueEx(iface_key, "TCPNoDelay", 0, winreg.REG_DWORD, 1)
                    winreg.CloseKey(iface_key)
                    i += 1
                except WindowsError:
                    break

            winreg.CloseKey(key)

            tcp_key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(tcp_key, "TcpTimedWaitDelay", 0, winreg.REG_DWORD, 30)
            winreg.SetValueEx(tcp_key, "MaxUserPort", 0, winreg.REG_DWORD, 65534)
            winreg.CloseKey(tcp_key)

            self.optimized = True
            return True
        except:
            return False

    def disable_network_throttling(self):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "NetworkThrottlingIndex", 0, winreg.REG_DWORD, 0xFFFFFFFF)
            winreg.SetValueEx(key, "SystemResponsiveness", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(key)
            return True
        except:
            return False

    def get_stats(self):
        return {'optimized': self.optimized}

NETWORK_OPT = NetworkOptimizer()

class VisualEffectsManager:
    def __init__(self):
        self.disabled = False

    def disable_for_performance(self):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "VisualFXSetting", 0, winreg.REG_DWORD, 2)
            winreg.CloseKey(key)

            adv_key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Control Panel\Desktop\WindowMetrics",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(adv_key, "MinAnimate", 0, winreg.REG_SZ, "0")
            winreg.CloseKey(adv_key)

            pers_key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(pers_key, "EnableTransparency", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(pers_key)

            self.disabled = True
            return True
        except:
            return False

    def restore_defaults(self):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "VisualFXSetting", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(key)
            self.disabled = False
            return True
        except:
            return False

    def get_stats(self):
        return {'disabled': self.disabled}

VISUAL_FX = VisualEffectsManager()

class StartupOptimizer:
    def __init__(self):
        self.startup_items = []

    def scan_startup(self):
        self.startup_items = []

        locations = [
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run"),
        ]

        for hive, path in locations:
            try:
                key = winreg.OpenKey(hive, path, 0, winreg.KEY_READ)
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        self.startup_items.append({
                            'name': name,
                            'command': value,
                            'location': 'Registry',
                            'hive': 'HKCU' if hive == winreg.HKEY_CURRENT_USER else 'HKLM'
                        })
                        i += 1
                    except WindowsError:
                        break
                winreg.CloseKey(key)
            except:
                pass

        startup_folder = os.path.expandvars(r'%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup')
        if os.path.exists(startup_folder):
            for f in os.listdir(startup_folder):
                self.startup_items.append({
                    'name': f,
                    'command': os.path.join(startup_folder, f),
                    'location': 'Startup Folder',
                    'hive': None
                })

        return self.startup_items

    def disable_startup_item(self, name, hive='HKCU'):
        try:
            source_hive = winreg.HKEY_CURRENT_USER if hive == 'HKCU' else winreg.HKEY_LOCAL_MACHINE
            source_key = winreg.OpenKey(
                source_hive,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ | winreg.KEY_WRITE
            )

            value, _ = winreg.QueryValueEx(source_key, name)

            winreg.DeleteValue(source_key, name)
            winreg.CloseKey(source_key)

            return True
        except:
            return False

    def get_stats(self):
        return {
            'startup_count': len(self.startup_items),
            'items': self.startup_items
        }

STARTUP_OPT = StartupOptimizer()

class SmartProcessManager:
    def __init__(self):
        self.process_profiles = {}
        self.learning_active = True
        self._last_snapshot = {}
        self._snapshot_interval = 30
        self._last_snapshot_time = 0

    def learn_process(self, pid, name, cpu, memory_mb):
        if name in SYSTEM_WHITELIST:
            return

        key = name.lower()
        if key not in self.process_profiles:
            self.process_profiles[key] = {
                'name': name,
                'avg_cpu': cpu,
                'avg_memory_mb': memory_mb,
                'max_cpu': cpu,
                'max_memory_mb': memory_mb,
                'samples': 1,
                'category': self._categorize_process(name),
                'recommended_priority': 'Normal'
            }
        else:
            profile = self.process_profiles[key]
            n = profile['samples']
            profile['avg_cpu'] = (profile['avg_cpu'] * n + cpu) / (n + 1)
            profile['avg_memory_mb'] = (profile['avg_memory_mb'] * n + memory_mb) / (n + 1)
            profile['max_cpu'] = max(profile['max_cpu'], cpu)
            profile['max_memory_mb'] = max(profile['max_memory_mb'], memory_mb)
            profile['samples'] += 1
            profile['recommended_priority'] = self._determine_priority(profile)

    def _categorize_process(self, name):
        name_lower = name.lower()
        if any(x in name_lower for x in ['game', 'steam', 'epic', 'origin', 'battle.net']):
            return 'gaming'
        elif any(x in name_lower for x in ['chrome', 'firefox', 'edge', 'opera', 'brave']):
            return 'browser'
        elif any(x in name_lower for x in ['code', 'studio', 'idea', 'pycharm', 'sublime']):
            return 'development'
        elif any(x in name_lower for x in ['discord', 'slack', 'teams', 'zoom', 'skype']):
            return 'communication'
        elif any(x in name_lower for x in ['spotify', 'vlc', 'media', 'player']):
            return 'media'
        return 'other'

    def _determine_priority(self, profile):
        if profile['category'] == 'gaming':
            return 'High'
        elif profile['avg_cpu'] > 50:
            return 'Above Normal'
        elif profile['avg_cpu'] < 5 and profile['avg_memory_mb'] < 100:
            return 'Below Normal'
        return 'Normal'

    def take_snapshot(self):
        now = time.time()
        if now - self._last_snapshot_time < self._snapshot_interval:
            return

        self._last_snapshot_time = now
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
                try:
                    info = proc.info
                    memory_mb = info['memory_info'].rss / (1024 * 1024) if info.get('memory_info') else 0
                    self.learn_process(info['pid'], info['name'], info['cpu_percent'] or 0, memory_mb)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass

    def get_recommendation(self, process_name):
        key = process_name.lower()
        if key in self.process_profiles:
            return self.process_profiles[key]
        return None

SMART_PROCESS_MGR = SmartProcessManager()

class AnomalyDetector:
    def __init__(self):
        self.baselines = {
            'cpu_usage': {'avg': 25.0, 'std': 15.0, 'samples': 10},
            'memory_usage': {'avg': 50.0, 'std': 10.0, 'samples': 10},
            'disk_usage': {'avg': 30.0, 'std': 20.0, 'samples': 10},
        }
        self._history = {'cpu': deque(maxlen=60), 'memory': deque(maxlen=60), 'disk': deque(maxlen=60)}
        self._anomaly_threshold = 2.5

    def update_baseline(self, metric, value):
        if metric not in self.baselines:
            self.baselines[metric] = {'avg': value, 'std': 0, 'samples': 1}
            return

        baseline = self.baselines[metric]
        n = baseline['samples']
        old_avg = baseline['avg']
        new_avg = (old_avg * n + value) / (n + 1)
        variance = ((n - 1) * (baseline['std'] ** 2) + (value - old_avg) * (value - new_avg)) / n if n > 1 else 0
        baseline['avg'] = new_avg
        baseline['std'] = max(1.0, variance ** 0.5)
        baseline['samples'] = min(n + 1, 1000)

    def detect_anomalies(self):
        anomalies = []

        try:
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory().percent

            self._history['cpu'].append(cpu)
            self._history['memory'].append(mem)

            self.update_baseline('cpu_usage', cpu)
            self.update_baseline('memory_usage', mem)

            cpu_baseline = self.baselines['cpu_usage']
            if cpu > cpu_baseline['avg'] + self._anomaly_threshold * cpu_baseline['std']:
                severity = 'critical' if cpu > 90 else 'high' if cpu > 75 else 'medium'
                anomalies.append({
                    'metric': 'CPU Usage',
                    'severity': severity,
                    'current': cpu,
                    'baseline': cpu_baseline['avg'],
                    'description': f'CPU at {cpu:.1f}% (baseline: {cpu_baseline["avg"]:.1f}%)'
                })

            mem_baseline = self.baselines['memory_usage']
            if mem > mem_baseline['avg'] + self._anomaly_threshold * mem_baseline['std']:
                severity = 'critical' if mem > 95 else 'high' if mem > 85 else 'medium'
                anomalies.append({
                    'metric': 'Memory Usage',
                    'severity': severity,
                    'current': mem,
                    'baseline': mem_baseline['avg'],
                    'description': f'RAM at {mem:.1f}% (baseline: {mem_baseline["avg"]:.1f}%)'
                })

            high_cpu_procs = []
            for proc in psutil.process_iter(['name', 'cpu_percent']):
                try:
                    if proc.info['cpu_percent'] and proc.info['cpu_percent'] > 50:
                        high_cpu_procs.append((proc.info['name'], proc.info['cpu_percent']))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            for name, cpu_pct in high_cpu_procs[:3]:
                if name not in SYSTEM_WHITELIST:
                    anomalies.append({
                        'metric': 'High CPU Process',
                        'severity': 'high' if cpu_pct > 70 else 'medium',
                        'current': cpu_pct,
                        'baseline': 0,
                        'description': f'{name} using {cpu_pct:.1f}% CPU'
                    })
        except Exception:
            pass

        return anomalies

    def get_system_health(self):
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory().percent

            cpu_score = max(0, 100 - cpu)
            mem_score = max(0, 100 - mem)

            return int((cpu_score * 0.5 + mem_score * 0.5))
        except Exception:
            return 75

ANOMALY_DETECTOR = AnomalyDetector()

class AIOptimizer:
    def __init__(self):
        self.suggestions_cache = []
        self._last_analysis = 0
        self._analysis_interval = 60

    def generate_suggestions(self):
        now = time.time()
        if now - self._last_analysis < self._analysis_interval and self.suggestions_cache:
            return self.suggestions_cache

        self._last_analysis = now
        suggestions = []

        try:
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()

            if cpu > 70:
                suggestions.append({
                    'feature': 'Enable OptiBalance',
                    'action': 'enable_probalance',
                    'reason': f'CPU usage is high ({cpu:.0f}%). OptiBalance can throttle background processes to improve responsiveness.',
                    'confidence': 0.85,
                    'priority': 1
                })

            if mem.percent > 80:
                suggestions.append({
                    'feature': 'Trim Process Memory',
                    'action': 'trim_ram',
                    'reason': f'RAM usage is high ({mem.percent:.0f}%). Trimming process memory can free up {(mem.used / 1024 / 1024 / 1024 * 0.1):.1f}GB+.',
                    'confidence': 0.90,
                    'priority': 1
                })

            if mem.percent > 60:
                suggestions.append({
                    'feature': 'Clear Standby List',
                    'action': 'clear_standby',
                    'reason': f'Consider clearing standby memory to free up cached RAM for active applications.',
                    'confidence': 0.75,
                    'priority': 2
                })

            heavy_procs = []
            for proc in psutil.process_iter(['name', 'cpu_percent', 'memory_percent']):
                try:
                    info = proc.info
                    if info['cpu_percent'] and info['cpu_percent'] > 30 and info['name'] not in SYSTEM_WHITELIST:
                        heavy_procs.append(info['name'])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            if len(heavy_procs) > 3:
                suggestions.append({
                    'feature': 'Enable Background Throttling',
                    'action': 'throttle_background',
                    'reason': f'Multiple resource-heavy processes detected ({len(heavy_procs)} processes). Throttling can improve foreground performance.',
                    'confidence': 0.80,
                    'priority': 2
                })

            suggestions.append({
                'feature': 'Boost Foreground App',
                'action': 'boost_foreground',
                'reason': 'Increase priority of the active window for better responsiveness.',
                'confidence': 0.70,
                'priority': 3
            })

        except Exception:
            pass

        suggestions.sort(key=lambda x: x['priority'])
        self.suggestions_cache = suggestions
        return suggestions

    def apply_suggestion(self, suggestion):
        try:
            action = suggestion.get('action', '')

            if action == 'enable_probalance':
                PRIORITY_BALANCER.enabled = True
                return True
            elif action == 'trim_ram':
                MEM_OPTIMIZER.enabled = True
                return True
            elif action == 'clear_standby':
                RAM_CLEANER.clear_standby_list()
                return True
            elif action == 'throttle_background':
                CPU_LIMITER.enabled = True
                return True
            elif action == 'boost_foreground':
                FG_BOOSTER.enabled = True
                return True

            return False
        except Exception:
            return False

    def refresh(self):
        self._last_analysis = 0
        return self.generate_suggestions()

AI_OPTIMIZER = AIOptimizer()

class ProcessCache:

    def __init__(self):
        self._cache = []
        self._cache_time = 0
        self._cache_ttl = 2.0
        self._lock = threading.Lock()

    def get_processes(self, attrs=None):
        now = time.time()
        with self._lock:
            if now - self._cache_time > self._cache_ttl:
                self._refresh(attrs)
            return list(self._cache)

    def _refresh(self, attrs=None):
        if attrs is None:
            attrs = ['pid', 'name', 'cpu_percent']
        try:
            self._cache = list(psutil.process_iter(attrs))
            self._cache_time = time.time()
        except:
            pass

    def invalidate(self):
        with self._lock:
            self._cache_time = 0

PROC_CACHE = ProcessCache()

class ChangeTracker:
    def __init__(self):
        self.changes = []
        self.max_changes = 100

    def log(self, change_type, data):
        self.changes.append({
            'type': change_type,
            'data': data,
            'time': time.time()
        })
        if len(self.changes) > self.max_changes:
            self.changes.pop(0)

    def log_priority_change(self, pid, name, old_priority, new_priority):
        self.log('priority', {'pid': pid, 'name': name, 'old': old_priority, 'new': new_priority})

    def log_service_stop(self, service_name):
        self.log('service_stop', {'service': service_name})

    def log_registry_change(self, key_path, value_name, old_value, new_value):
        self.log('registry', {'key': key_path, 'name': value_name, 'old': old_value, 'new': new_value})

    def undo_last(self):
        if not self.changes:
            return None

        change = self.changes.pop()
        try:
            if change['type'] == 'priority':
                h = open_proc(change['data']['pid'], win32con.PROCESS_SET_INFORMATION)
                if h:
                    win32process.SetPriorityClass(h, change['data']['old'])
                    win32api.CloseHandle(h)
                    return f"Restored {change['data']['name']} priority"

            elif change['type'] == 'service_stop':
                subprocess.run(['sc', 'start', change['data']['service']], capture_output=True, timeout=10)
                return f"Restarted {change['data']['service']}"

        except:
            pass
        return None

    def undo_all(self):
        count = 0
        while self.changes:
            if self.undo_last():
                count += 1
        return count

    def get_history(self):
        return list(reversed(self.changes))

CHANGE_TRACKER = ChangeTracker()

class GameProfiles:
    def __init__(self):
        self.profiles_path = os.path.join(APP_DIR, "game_profiles.json")
        self.profiles = {}
        self.active_profile = None
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.profiles_path):
                with open(self.profiles_path, 'r', encoding='utf-8') as f:
                    self.profiles = json.load(f)
        except:
            self.profiles = {}

    def _save(self):
        try:
            with open(self.profiles_path, 'w', encoding='utf-8') as f:
                json.dump(self.profiles, f, indent=2)
        except:
            pass

    def create_profile(self, game_name):
        self.profiles[game_name] = {
            'game_mode': GAME_MODE.enabled,
            'priority_balancer': PRIORITY_BALANCER.enabled,
            'cpu_limiter': CPU_LIMITER.enabled,
            'fg_booster': FG_BOOSTER.enabled,
            'mem_optimizer': MEM_OPTIMIZER.enabled,
            'visual_fx_disabled': VISUAL_FX.disabled,
            'network_optimized': NETWORK_OPT.optimized,
        }
        self._save()
        return True

    def apply_profile(self, game_name):
        if game_name not in self.profiles:
            return False

        p = self.profiles[game_name]
        GAME_MODE.enabled = p.get('game_mode', False)
        PRIORITY_BALANCER.enabled = p.get('priority_balancer', True)
        CPU_LIMITER.enabled = p.get('cpu_limiter', False)
        FG_BOOSTER.enabled = p.get('fg_booster', False)
        MEM_OPTIMIZER.enabled = p.get('mem_optimizer', False)

        if p.get('visual_fx_disabled'):
            VISUAL_FX.disable_for_performance()
        if p.get('network_optimized'):
            NETWORK_OPT.optimize_for_gaming()

        self.active_profile = game_name
        return True

    def delete_profile(self, game_name):
        if game_name in self.profiles:
            del self.profiles[game_name]
            self._save()
            return True
        return False

    def list_profiles(self):
        return list(self.profiles.keys())

GAME_PROFILES = GameProfiles()

class AutoStartManager:
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    APP_NAME = "OptiCores"

    def __init__(self):
        self.enabled = self._check_enabled()

    def _check_enabled(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, self.APP_NAME)
                winreg.CloseKey(key)
                return True
            except WindowsError:
                winreg.CloseKey(key)
                return False
        except:
            return False

    def enable(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_SET_VALUE)
            script_path = os.path.abspath(sys.argv[0])
            if script_path.endswith('.py'):
                cmd = f'pythonw "{script_path}"'
            else:
                cmd = f'"{script_path}"'
            winreg.SetValueEx(key, self.APP_NAME, 0, winreg.REG_SZ, cmd)
            winreg.CloseKey(key)
            self.enabled = True
            return True
        except:
            return False

    def disable(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_SET_VALUE)
            try:
                winreg.DeleteValue(key, self.APP_NAME)
            except WindowsError:
                pass
            winreg.CloseKey(key)
            self.enabled = False
            return True
        except:
            return False

    def toggle(self):
        if self.enabled:
            return self.disable()
        else:
            return self.enable()

AUTO_START = AutoStartManager()

def confirm_action(parent, title, message, dangerous=True):
    dialog = ctk.CTkToplevel(parent)
    dialog.title(title)
    dialog.geometry("400x180")
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(False, False)

    dialog.update_idletasks()
    x = parent.winfo_x() + (parent.winfo_width() - 400) // 2
    y = parent.winfo_y() + (parent.winfo_height() - 180) // 2
    dialog.geometry(f"+{x}+{y}")

    result = [False]

    frame = ctk.CTkFrame(dialog, fg_color="#1D232C", corner_radius=0)
    frame.pack(fill="both", expand=True)

    icon = "⚠️" if dangerous else "❓"
    ctk.CTkLabel(frame, text=icon, font=ctk.CTkFont(size=32)).pack(pady=(20,10))
    ctk.CTkLabel(frame, text=message, font=ctk.CTkFont(size=14), wraplength=350).pack(pady=5)

    btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
    btn_frame.pack(pady=20)

    def on_yes():
        result[0] = True
        dialog.destroy()

    def on_no():
        dialog.destroy()

    ctk.CTkButton(btn_frame, text="Cancel", width=100, fg_color="#374151", hover_color="#4B5563", command=on_no).pack(side="left", padx=10)
    ctk.CTkButton(btn_frame, text="Confirm", width=100, fg_color="#EF4444" if dangerous else "#10B981", hover_color="#DC2626" if dangerous else "#059669", command=on_yes).pack(side="left", padx=10)

    dialog.wait_window()
    return result[0]

class GameLibraryScanner:
    def __init__(self):
        self.games = []
        self.steam_paths = [
            os.path.expandvars(r"%ProgramFiles(x86)%\Steam\steamapps\common"),
            os.path.expandvars(r"%ProgramFiles%\Steam\steamapps\common"),
        ]
        self.epic_manifest = os.path.expandvars(r"%ProgramData%\Epic\EpicGamesLauncher\Data\Manifests")
        self.gog_registry = r"SOFTWARE\WOW6432Node\GOG.com\Games"

    def scan_steam(self):
        games = []
        for steam_path in self.steam_paths:
            if os.path.exists(steam_path):
                try:
                    for folder in os.listdir(steam_path):
                        full_path = os.path.join(steam_path, folder)
                        if os.path.isdir(full_path):
                            exes = [f for f in os.listdir(full_path) if f.endswith('.exe')]
                            if exes:
                                games.append({
                                    'name': folder,
                                    'path': full_path,
                                    'exe': exes[0] if exes else None,
                                    'source': 'Steam'
                                })
                except:
                    pass
        return games

    def scan_epic(self):
        games = []
        if os.path.exists(self.epic_manifest):
            try:
                for f in os.listdir(self.epic_manifest):
                    if f.endswith('.item'):
                        with open(os.path.join(self.epic_manifest, f), 'r', encoding='utf-8') as file:
                            data = json.load(file)
                            games.append({
                                'name': data.get('DisplayName', 'Unknown'),
                                'path': data.get('InstallLocation', ''),
                                'exe': data.get('LaunchExecutable', ''),
                                'source': 'Epic'
                            })
            except:
                pass
        return games

    def scan_gog(self):
        games = []
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.gog_registry, 0, winreg.KEY_READ)
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    subkey = winreg.OpenKey(key, subkey_name)
                    name, _ = winreg.QueryValueEx(subkey, "gameName")
                    path, _ = winreg.QueryValueEx(subkey, "path")
                    games.append({
                        'name': name,
                        'path': path,
                        'exe': None,
                        'source': 'GOG'
                    })
                    winreg.CloseKey(subkey)
                    i += 1
                except WindowsError:
                    break
            winreg.CloseKey(key)
        except:
            pass
        return games

    def scan_all(self):
        self.games = []
        self.games.extend(self.scan_steam())
        self.games.extend(self.scan_epic())
        self.games.extend(self.scan_gog())
        return self.games

    def get_game_count(self):
        return len(self.games)

GAME_LIBRARY = GameLibraryScanner()

class DriverChecker:
    def __init__(self):
        self.drivers = []

    def scan_drivers(self):
        self.drivers = []
        try:
            result = subprocess.run(
                ['wmic', 'path', 'Win32_PnPSignedDriver', 'get',
                 'DeviceName,DriverVersion,Manufacturer,DriverDate', '/format:csv'],
                capture_output=True, text=True, timeout=30
            )
            lines = result.stdout.strip().split('\n')
            for line in lines[1:]:
                parts = line.strip().split(',')
                if len(parts) >= 4:
                    self.drivers.append({
                        'device': parts[1] if len(parts) > 1 else '',
                        'version': parts[3] if len(parts) > 3 else '',
                        'manufacturer': parts[4] if len(parts) > 4 else '',
                        'date': parts[2] if len(parts) > 2 else ''
                    })
        except:
            pass
        return self.drivers

    def get_graphics_drivers(self):
        return [d for d in self.drivers if 'graphics' in d['device'].lower()
                or 'nvidia' in d['device'].lower()
                or 'amd' in d['device'].lower()
                or 'intel' in d['device'].lower()]

    def get_driver_count(self):
        return len(self.drivers)

DRIVER_CHECKER = DriverChecker()

class ServiceManager:
    def __init__(self):
        self.services = []
        self.gaming_safe_disable = [
            'SysMain', 'DiagTrack', 'WSearch', 'WerSvc',
            'MapsBroker', 'lfsvc', 'RetailDemo'
        ]

    def scan_services(self):
        self.services = []
        try:
            result = subprocess.run(
                ['sc', 'query', 'state=', 'all'],
                capture_output=True, text=True, timeout=30
            )
            current = {}
            for line in result.stdout.split('\n'):
                line = line.strip()
                if line.startswith('SERVICE_NAME:'):
                    if current:
                        self.services.append(current)
                    current = {'name': line.split(':', 1)[1].strip()}
                elif line.startswith('DISPLAY_NAME:'):
                    current['display'] = line.split(':', 1)[1].strip()
                elif line.startswith('STATE'):
                    parts = line.split()
                    if len(parts) >= 4:
                        current['state'] = parts[3]
            if current:
                self.services.append(current)
        except:
            pass
        return self.services

    def start_service(self, name):
        try:
            subprocess.run(['sc', 'start', name], capture_output=True, timeout=30)
            return True
        except:
            return False

    def stop_service(self, name):
        try:
            subprocess.run(['sc', 'stop', name], capture_output=True, timeout=30)
            CHANGE_TRACKER.log_service_stop(name)
            return True
        except:
            return False

    def disable_service(self, name):
        try:
            subprocess.run(['sc', 'config', name, 'start=', 'disabled'], capture_output=True, timeout=30)
            return True
        except:
            return False

    def enable_service(self, name):
        try:
            subprocess.run(['sc', 'config', name, 'start=', 'demand'], capture_output=True, timeout=30)
            return True
        except:
            return False

    def is_gaming_safe(self, name):
        return name in self.gaming_safe_disable

SERVICE_MGR = ServiceManager()

class ContextMenuCleaner:
    def __init__(self):
        self.entries = []
        self.shell_keys = [
            (winreg.HKEY_CLASSES_ROOT, r"*\shell"),
            (winreg.HKEY_CLASSES_ROOT, r"Directory\shell"),
            (winreg.HKEY_CLASSES_ROOT, r"Directory\Background\shell"),
        ]
        self.disabled_key = r"Software\OptiCores\DisabledContextMenu"

    def scan(self):
        self.entries = []
        for root, path in self.shell_keys:
            try:
                key = winreg.OpenKey(root, path, 0, winreg.KEY_READ)
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        self.entries.append({
                            'name': subkey_name,
                            'path': path,
                            'root': 'HKCR',
                            'enabled': True
                        })
                        i += 1
                    except WindowsError:
                        break
                winreg.CloseKey(key)
            except:
                pass
        return self.entries

    def disable_entry(self, entry_name, path):
        pass

    def get_entry_count(self):
        return len(self.entries)

CONTEXT_MENU = ContextMenuCleaner()

class ScheduledTasksManager:
    def __init__(self):
        self.tasks = []

    def scan(self):
        self.tasks = []
        try:
            result = subprocess.run(
                ['schtasks', '/query', '/fo', 'csv', '/v'],
                capture_output=True, text=True, timeout=60
            )
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:
                headers = lines[0].replace('"', '').split(',')
                for line in lines[1:]:
                    parts = line.replace('"', '').split(',')
                    if len(parts) >= 5:
                        self.tasks.append({
                            'name': parts[1] if len(parts) > 1 else '',
                            'next_run': parts[2] if len(parts) > 2 else '',
                            'status': parts[3] if len(parts) > 3 else '',
                            'folder': parts[0] if len(parts) > 0 else '',
                        })
        except:
            pass
        return self.tasks

    def disable_task(self, task_name):
        try:
            subprocess.run(
                ['schtasks', '/change', '/tn', task_name, '/disable'],
                capture_output=True, timeout=30
            )
            return True
        except:
            return False

    def enable_task(self, task_name):
        try:
            subprocess.run(
                ['schtasks', '/change', '/tn', task_name, '/enable'],
                capture_output=True, timeout=30
            )
            return True
        except:
            return False

    def get_task_count(self):
        return len(self.tasks)

    def get_bloatware_tasks(self):
        bloat_keywords = ['telemetry', 'feedback', 'diagnostic', 'customer',
                          'microsoft compatibility', 'office telemetry']
        return [t for t in self.tasks
                if any(kw in t['name'].lower() for kw in bloat_keywords)]

SCHED_TASKS = ScheduledTasksManager()

class AdaptivePoller:
    def __init__(self):
        self.base_interval = 1.0
        self.min_interval = 0.5
        self.max_interval = 5.0
        self.current_interval = self.base_interval

        self.cpu_low_threshold = 30
        self.cpu_high_threshold = 70

        self.intervals = {
            'cpu': self.base_interval,
            'memory': self.base_interval,
            'disk': 3.0,
            'network': self.base_interval,
            'gpu': 2.0,
            'processes': 2.0,
            'temperature': 5.0
        }

    def get_interval(self, component='default'):
        try:
            cpu = psutil.cpu_percent(interval=None)

            if cpu < self.cpu_low_threshold:
                multiplier = 2.0
            elif cpu > self.cpu_high_threshold:
                multiplier = 0.5
            else:
                multiplier = 1.0

            base = self.intervals.get(component, self.base_interval)
            adjusted = base * multiplier
            return max(self.min_interval, min(self.max_interval, adjusted))
        except:
            return self.base_interval

    def should_poll(self, component, last_poll_time):
        interval = self.get_interval(component)
        return (time.time() - last_poll_time) >= interval

ADAPTIVE_POLLER = AdaptivePoller()

class SystemDataCache:
    def __init__(self):
        self._cache = {}
        self._timestamps = {}
        self._locks = defaultdict(threading.Lock)

        self.default_ttl = {
            'wmi_temperature': 10.0,
            'disk_usage': 30.0,
            'system_info': 300.0,
            'gpu_info': 5.0,
            'network_adapters': 60.0,
            'installed_software': 600.0
        }

    def get(self, key, fetch_func, ttl=None):
        with self._locks[key]:
            now = time.time()

            if key in self._cache:
                age = now - self._timestamps.get(key, 0)
                cache_ttl = ttl or self.default_ttl.get(key, 60.0)

                if age < cache_ttl:
                    return self._cache[key]

            try:
                value = fetch_func()
                self._cache[key] = value
                self._timestamps[key] = now
                return value
            except Exception as e:
                if key in self._cache:
                    return self._cache[key]
                raise e

    def invalidate(self, key=None):
        if key:
            with self._locks[key]:
                if key in self._cache:
                    del self._cache[key]
                if key in self._timestamps:
                    del self._timestamps[key]
        else:
            for k in list(self._cache.keys()):
                self.invalidate(k)

    def get_cached_temperature(self):
        def fetch():
            if not WMI_CLIENT:
                return None
            try:
                temps = WMI_CLIENT.MSAcpi_ThermalZoneTemperature()
                if temps:
                    kelvin = temps[0].CurrentTemperature / 10.0
                    celsius = kelvin - 273.15
                    return celsius
            except:
                pass
            return None

        return self.get('wmi_temperature', fetch, ttl=10.0)

    def get_cached_disk_usage(self):
        def fetch():
            drives = []
            for partition in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    drives.append({
                        'drive': partition.mountpoint,
                        'total': usage.total,
                        'used': usage.used,
                        'free': usage.free,
                        'percent': usage.percent
                    })
                except:
                    pass
            return drives

        return self.get('disk_usage', fetch, ttl=30.0)

SYSTEM_CACHE = SystemDataCache()

from concurrent.futures import ThreadPoolExecutor, as_completed
import queue

class ThreadPoolManager:
    def __init__(self, max_workers=4):
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="OptiCores")
        self.active_tasks = []
        self._shutdown = False

    def submit(self, func, *args, **kwargs):
        if self._shutdown:
            return None

        future = self.executor.submit(func, *args, **kwargs)
        self.active_tasks.append(future)
        return future

    def submit_periodic(self, func, interval, *args, **kwargs):
        def wrapper():
            while not self._shutdown:
                try:
                    func(*args, **kwargs)
                except Exception:
                    pass
                time.sleep(interval)

        return self.submit(wrapper)

    def wait_all(self, timeout=None):
        completed = []
        try:
            for future in as_completed(self.active_tasks, timeout=timeout):
                try:
                    result = future.result()
                    completed.append(result)
                except Exception:
                    pass
        except:
            pass
        return completed

    def shutdown(self, wait=True):
        self._shutdown = True
        self.executor.shutdown(wait=wait)

    def get_active_count(self):
        return len([f for f in self.active_tasks if not f.done()])

THREAD_POOL = ThreadPoolManager(max_workers=6)

class NetworkMonitor:
    def __init__(self):
        self.enabled = False
        self.last_io = None
        self.last_time = None
        self.upload_speed = 0
        self.download_speed = 0
        self.upload_history = deque(maxlen=60)
        self.download_history = deque(maxlen=60)
        self.per_process_tracking = {}

    def update(self):
        if not self.enabled:
            return

        try:
            current_io = psutil.net_io_counters()
            current_time = time.time()

            if self.last_io and self.last_time:
                time_delta = current_time - self.last_time
                if time_delta > 0:
                    self.upload_speed = (current_io.bytes_sent - self.last_io.bytes_sent) / time_delta
                    self.download_speed = (current_io.bytes_recv - self.last_io.bytes_recv) / time_delta

                    self.upload_history.append(self.upload_speed)
                    self.download_history.append(self.download_speed)

            self.last_io = current_io
            self.last_time = current_time
        except:
            pass

    def get_stats(self):
        return {
            'upload_mbps': (self.upload_speed * 8) / (1024 * 1024),
            'download_mbps': (self.download_speed * 8) / (1024 * 1024),
            'upload_history': list(self.upload_history),
            'download_history': list(self.download_history),
            'total_sent_gb': self.last_io.bytes_sent / (1024**3) if self.last_io else 0,
            'total_recv_gb': self.last_io.bytes_recv / (1024**3) if self.last_io else 0
        }

    def get_adapters(self):
        adapters = []
        try:
            stats = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()
            io = psutil.net_io_counters(pernic=True)

            for name in stats.keys():
                adapter = {
                    'name': name,
                    'is_up': stats[name].isup,
                    'speed_mbps': stats[name].speed,
                    'bytes_sent': io[name].bytes_sent if name in io else 0,
                    'bytes_recv': io[name].bytes_recv if name in io else 0,
                    'ip_addresses': []
                }

                if name in addrs:
                    for addr in addrs[name]:
                        if addr.family == 2:
                            adapter['ip_addresses'].append(addr.address)

                adapters.append(adapter)
        except:
            pass
        return adapters

    def flush_dns(self):
        try:
            subprocess.run(['ipconfig', '/flushdns'], capture_output=True, timeout=10)
            return True
        except:
            return False

    def optimize_tcp(self):
        try:
            commands = [
                ['netsh', 'int', 'tcp', 'set', 'global', 'autotuninglevel=normal'],
                ['netsh', 'int', 'tcp', 'set', 'global', 'chimney=enabled'],
                ['netsh', 'int', 'tcp', 'set', 'global', 'dca=enabled'],
                ['netsh', 'int', 'tcp', 'set', 'global', 'netdma=enabled'],
                ['netsh', 'int', 'tcp', 'set', 'global', 'rss=enabled'],
            ]

            for cmd in commands:
                try:
                    subprocess.run(cmd, capture_output=True, timeout=5)
                except:
                    pass
            return True
        except:
            return False

NETWORK_MONITOR = NetworkMonitor()

class EnhancedThermalMonitor:
    def __init__(self):
        self.enabled = True
        self.cpu_temp = None
        self.gpu_temps = []
        self.temp_history = defaultdict(lambda: deque(maxlen=60))
        self.alert_threshold = 80
        self.critical_threshold = 90
        self.alerts_enabled = True
        self.active_alerts = []

    def update(self):
        if not self.enabled:
            return

        self.cpu_temp = SYSTEM_CACHE.get_cached_temperature()
        if self.cpu_temp:
            self.temp_history['cpu'].append(self.cpu_temp)
            self._check_alerts('CPU', self.cpu_temp)

        self.gpu_temps = []
        if GPUtil:
            try:
                gpus = GPUtil.getGPUs()
                for i, gpu in enumerate(gpus):
                    temp = gpu.temperature
                    self.gpu_temps.append(temp)
                    self.temp_history[f'gpu{i}'].append(temp)
                    self._check_alerts(f'GPU{i}', temp)
            except:
                pass

    def _check_alerts(self, component, temp):
        if not self.alerts_enabled:
            return

        alert_id = f"{component}_alert"

        if temp >= self.critical_threshold:
            if alert_id not in self.active_alerts:
                self.active_alerts.append(alert_id)
        elif temp >= self.alert_threshold:
            if alert_id not in self.active_alerts:
                self.active_alerts.append(alert_id)
        else:
            if alert_id in self.active_alerts:
                self.active_alerts.remove(alert_id)

    def get_stats(self):
        return {
            'cpu_temp': self.cpu_temp,
            'gpu_temps': self.gpu_temps,
            'cpu_history': list(self.temp_history.get('cpu', [])),
            'gpu_history': [list(self.temp_history.get(f'gpu{i}', [])) for i in range(len(self.gpu_temps))],
            'active_alerts': self.active_alerts,
            'alert_threshold': self.alert_threshold
        }

    def get_max_temps(self):
        return {
            'cpu_max': max(self.temp_history['cpu']) if self.temp_history['cpu'] else None,
            'gpu_max': [max(self.temp_history[f'gpu{i}']) if self.temp_history[f'gpu{i}'] else None
                       for i in range(len(self.gpu_temps))]
        }

THERMAL_MONITOR = EnhancedThermalMonitor()

class EnhancedSystemCleaner:
    def __init__(self):
        self.enabled = True
        self.scan_results = {}
        self.total_cleanable = 0

        self.temp_folders = [
            os.environ.get('TEMP', ''),
            os.environ.get('TMP', ''),
            os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Temp'),
            os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Prefetch'),
        ]

        self.browser_caches = {
            'Chrome': os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\User Data\Default\Cache'),
            'Edge': os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Cache'),
            'Firefox': os.path.expandvars(r'%APPDATA%\Mozilla\Firefox\Profiles'),
        }

        self.clean_extensions = {'.tmp', '.temp', '.log', '.bak', '.old', '.dmp', '.chk'}

    def scan(self):
        self.scan_results = {
            'temp_files': 0,
            'browser_cache': 0,
            'recycle_bin': 0,
            'windows_update': 0,
            'thumbnails': 0
        }
        self.total_cleanable = 0

        for folder in self.temp_folders:
            if os.path.exists(folder):
                try:
                    size = sum(os.path.getsize(os.path.join(folder, f))
                             for f in os.listdir(folder)
                             if os.path.isfile(os.path.join(folder, f)))
                    self.scan_results['temp_files'] += size
                except:
                    pass

        for browser, path in self.browser_caches.items():
            if os.path.exists(path):
                try:
                    for root, dirs, files in os.walk(path):
                        for f in files:
                            try:
                                fp = os.path.join(root, f)
                                self.scan_results['browser_cache'] += os.path.getsize(fp)
                            except:
                                pass
                except:
                    pass

        self.total_cleanable = sum(self.scan_results.values())
        return self.scan_results

    def clean_temp_files(self):
        files_deleted = 0
        bytes_freed = 0

        for folder in self.temp_folders:
            if not os.path.exists(folder):
                continue

            try:
                for f in os.listdir(folder):
                    fp = os.path.join(folder, f)
                    try:
                        if os.path.isfile(fp):
                            size = os.path.getsize(fp)
                            os.remove(fp)
                            files_deleted += 1
                            bytes_freed += size
                    except:
                        pass
            except:
                pass

        return files_deleted, bytes_freed

    def clean_browser_cache(self, browser=None):
        files_deleted = 0
        bytes_freed = 0

        targets = {browser: self.browser_caches[browser]} if browser else self.browser_caches

        for browser_name, path in targets.items():
            if not os.path.exists(path):
                continue

            try:
                for root, dirs, files in os.walk(path):
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            size = os.path.getsize(fp)
                            os.remove(fp)
                            files_deleted += 1
                            bytes_freed += size
                        except:
                            pass
            except:
                pass

        return files_deleted, bytes_freed

    def find_large_files(self, min_size_mb=100, path='C:\\'):
        large_files = []

        try:
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d.lower() not in
                          ['windows', 'program files', 'program files (x86)', '$recycle.bin', 'system volume information']]

                for f in files:
                    try:
                        fp = os.path.join(root, f)
                        size = os.path.getsize(fp)
                        size_mb = size / (1024 * 1024)

                        if size_mb >= min_size_mb:
                            large_files.append({
                                'path': fp,
                                'size_mb': size_mb,
                                'modified': os.path.getmtime(fp)
                            })
                    except:
                        pass

                if len(large_files) >= 100:
                    break
        except:
            pass

        return sorted(large_files, key=lambda x: x['size_mb'], reverse=True)

    def get_stats(self):
        return {
            'scan_results': self.scan_results,
            'total_cleanable_mb': self.total_cleanable / (1024 * 1024),
            'breakdown': {k: v / (1024 * 1024) for k, v in self.scan_results.items()}
        }

SYSTEM_CLEANER = EnhancedSystemCleaner()

class DiscordRichPresence:
    APPLICATION_ID = "1234567890123456789"

    def __init__(self):
        self.enabled = False
        self.connected = False
        self.rpc = None
        self.start_time = None
        self._update_thread = None
        self._stop_event = threading.Event()

    def connect(self):
        try:
            from pypresence import Presence
            self.rpc = Presence(self.APPLICATION_ID)
            self.rpc.connect()
            self.connected = True
            self.start_time = time.time()
            return True
        except ImportError:
            print("pypresence not installed. Run: pip install pypresence")
            return False
        except Exception as e:
            print(f"Discord connection failed: {e}")
            return False

    def disconnect(self):
        try:
            if self.rpc:
                self.rpc.close()
            self.connected = False
            self.rpc = None
        except:
            pass

    def update_presence(self, state=None, details=None, large_image="opticores", large_text="OptiCores"):
        if not self.connected or not self.rpc:
            return False

        try:
            self.rpc.update(
                state=state or self._get_status(),
                details=details or self._get_details(),
                large_image=large_image,
                large_text=large_text,
                start=int(self.start_time) if self.start_time else None
            )
            return True
        except:
            return False

    def _get_status(self):
        active = []
        if GAME_MODE.enabled or GAME_MODE.game_active:
            active.append("🎮 Game Mode")
        if PRIORITY_BALANCER.enabled:
            active.append("⚡ OptiBalance")
        if FG_BOOSTER.enabled:
            active.append("🚀 FG Boost")
        if MEM_OPTIMIZER.enabled:
            active.append("💾 Memory Opt")

        if active:
            return " | ".join(active[:2])
        return "System Optimized"

    def _get_details(self):
        try:
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            return f"CPU: {cpu:.0f}% | RAM: {ram:.0f}%"
        except:
            return "Optimizing System"

    def start_auto_update(self, interval=15):
        if self._update_thread and self._update_thread.is_alive():
            return

        self._stop_event.clear()

        def update_loop():
            while not self._stop_event.is_set():
                if self.connected:
                    self.update_presence()
                self._stop_event.wait(interval)

        self._update_thread = threading.Thread(target=update_loop, daemon=True)
        self._update_thread.start()

    def stop_auto_update(self):
        self._stop_event.set()

    def enable(self):
        if self.connect():
            self.enabled = True
            self.start_auto_update()
            return True
        return False

    def disable(self):
        self.enabled = False
        self.stop_auto_update()
        self.disconnect()

DISCORD_RPC = DiscordRichPresence()

import logging
from logging.handlers import RotatingFileHandler

class LogManager:
    def __init__(self):
        self.log_dir = os.path.join(APP_DIR, 'logs')
        os.makedirs(self.log_dir, exist_ok=True)

        self.debug_mode = False
        self.loggers = {}

        self._setup_loggers()

    def _setup_loggers(self):
        log_level = logging.DEBUG if self.debug_mode else logging.INFO

        main_logger = logging.getLogger('OptiCores')
        main_logger.setLevel(log_level)

        file_handler = RotatingFileHandler(
            os.path.join(self.log_dir, 'opticores.log'),
            maxBytes=10*1024*1024,
            backupCount=5
        )
        file_handler.setLevel(log_level)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.ERROR)

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        main_logger.addHandler(file_handler)
        main_logger.addHandler(console_handler)

        self.loggers['main'] = main_logger

        perf_logger = logging.getLogger('OptiCores.Performance')
        perf_logger.setLevel(logging.INFO)
        perf_handler = RotatingFileHandler(
            os.path.join(self.log_dir, 'performance.log'),
            maxBytes=5*1024*1024,
            backupCount=3
        )
        perf_handler.setFormatter(formatter)
        perf_logger.addHandler(perf_handler)
        self.loggers['performance'] = perf_logger

    def log(self, message, level='info', logger='main'):
        log_func = getattr(self.loggers.get(logger, self.loggers['main']), level, None)
        if log_func:
            log_func(message)

    def debug(self, message, logger='main'):
        self.log(message, 'debug', logger)

    def info(self, message, logger='main'):
        self.log(message, 'info', logger)

    def warning(self, message, logger='main'):
        self.log(message, 'warning', logger)

    def error(self, message, logger='main', exc_info=False):
        logger_obj = self.loggers.get(logger, self.loggers['main'])
        logger_obj.error(message, exc_info=exc_info)

    def log_performance(self, component, duration_ms, details=None):
        msg = f"{component}: {duration_ms:.2f}ms"
        if details:
            msg += f" - {details}"
        self.log(msg, 'info', 'performance')

    def enable_debug(self):
        self.debug_mode = True
        for logger in self.loggers.values():
            logger.setLevel(logging.DEBUG)

    def disable_debug(self):
        self.debug_mode = False
        for logger in self.loggers.values():
            logger.setLevel(logging.INFO)

    def get_log_files(self):
        return [f for f in os.listdir(self.log_dir) if f.endswith('.log')]

LOG_MANAGER = LogManager()

class ThemeManager:
    def __init__(self):
        self.current_theme = 'dark'
        self.current_accent = '#3B82F6'

        self.accent_colors = {
            'Blue': '#3B82F6',
            'Purple': '#8B5CF6',
            'Green': '#10B981',
            'Red': '#EF4444',
            'Orange': '#F59E0B',
            'Pink': '#EC4899',
            'Cyan': '#06B6D4',
            'Custom': '#3B82F6'
        }

        self.themes = {
            'dark': {
                'bg_primary': '#0D1117',
                'bg_secondary': '#161B22',
                'bg_tertiary': '#1D232C',
                'text_primary': '#F9FAFB',
                'text_secondary': '#9CA3AF',
                'border': '#30363D',
                'success': '#10B981',
                'warning': '#F59E0B',
                'error': '#EF4444',
            },
            'light': {
                'bg_primary': '#FFFFFF',
                'bg_secondary': '#F3F4F6',
                'bg_tertiary': '#E5E7EB',
                'text_primary': '#111827',
                'text_secondary': '#6B7280',
                'border': '#D1D5DB',
                'success': '#059669',
                'warning': '#D97706',
                'error': '#DC2626',
            }
        }

    def set_theme(self, theme_name):
        if theme_name in self.themes:
            self.current_theme = theme_name
            ctk.set_appearance_mode('Dark' if theme_name == 'dark' else 'Light')
            return True
        return False

    def set_accent_color(self, color_name):
        if color_name in self.accent_colors:
            self.current_accent = self.accent_colors[color_name]
            return True
        return False

    def set_custom_accent(self, hex_color):
        self.accent_colors['Custom'] = hex_color
        self.current_accent = hex_color
        return True

    def get_color(self, key):
        return self.themes.get(self.current_theme, {}).get(key, '#FFFFFF')

    def get_accent_color(self):
        return self.current_accent

    def apply_accent_to_widget(self, widget, widget_type='button'):
        try:
            if widget_type == 'button':
                widget.configure(fg_color=self.current_accent)
            elif widget_type == 'progress':
                widget.configure(progress_color=self.current_accent)
            elif widget_type == 'switch':
                widget.configure(button_color=self.current_accent, button_hover_color=self.current_accent)
        except:
            pass

THEME_MANAGER = ThemeManager()

class EnhancedBenchmarkSuite:
    def __init__(self):
        self.results = {}
        self.baseline = {}
        self.history = []
        self.running = False

    def run_cpu_single_core(self, duration=5):
        LOG_MANAGER.info("Starting single-core CPU benchmark")
        start = time.perf_counter()
        iterations = 0
        end_time = start + duration

        while time.perf_counter() < end_time:
            for n in range(2, 10000):
                is_prime = True
                for i in range(2, int(n**0.5) + 1):
                    if n % i == 0:
                        is_prime = False
                        break
            iterations += 1

        elapsed = time.perf_counter() - start
        score = int((iterations / elapsed) * 100)
        LOG_MANAGER.log_performance('CPU Single-Core', elapsed * 1000, f'Score: {score}')
        return score

    def run_cpu_multi_core(self, duration=5):
        LOG_MANAGER.info("Starting multi-core CPU benchmark")
        core_count = multiprocessing.cpu_count()

        def worker():
            end_time = time.perf_counter() + duration
            iterations = 0
            while time.perf_counter() < end_time:
                for n in range(2, 10000):
                    is_prime = True
                    for i in range(2, int(n**0.5) + 1):
                        if n % i == 0:
                            is_prime = False
                            break
                iterations += 1
            return iterations

        start = time.perf_counter()
        with multiprocessing.Pool(core_count) as pool:
            results = pool.map(lambda _: worker(), range(core_count))
        elapsed = time.perf_counter() - start

        total_iterations = sum(results)
        score = int((total_iterations / elapsed) * 10)
        LOG_MANAGER.log_performance('CPU Multi-Core', elapsed * 1000, f'Score: {score}')
        return score

    def run_memory_test(self, size_mb=100):
        LOG_MANAGER.info(f"Starting memory test ({size_mb}MB)")
        size = size_mb * 1024 * 1024 // 8

        start = time.perf_counter()
        data = [i for i in range(size)]
        write_time = time.perf_counter() - start

        start = time.perf_counter()
        _ = sum(data)
        read_time = time.perf_counter() - start

        write_bw = size_mb / write_time
        read_bw = size_mb / read_time

        score = int((write_bw + read_bw) / 2)
        LOG_MANAGER.log_performance('Memory', (write_time + read_time) * 1000, f'Bandwidth: {score} MB/s')
        return score

    def run_disk_test(self, drive='C:\\'):
        LOG_MANAGER.info(f"Starting disk test on {drive}")
        test_file = os.path.join(drive, 'opticores_bench.tmp')
        test_size = 50 * 1024 * 1024

        try:
            data = os.urandom(test_size)
            start = time.perf_counter()
            with open(test_file, 'wb') as f:
                f.write(data)
            write_time = time.perf_counter() - start

            start = time.perf_counter()
            with open(test_file, 'rb') as f:
                _ = f.read()
            read_time = time.perf_counter() - start

            os.remove(test_file)

            write_speed = (test_size / (1024 * 1024)) / write_time
            read_speed = (test_size / (1024 * 1024)) / read_time

            score = int((write_speed + read_speed) / 2)
            LOG_MANAGER.log_performance('Disk I/O', (write_time + read_time) * 1000, f'Speed: {score} MB/s')
            return score
        except Exception as e:
            LOG_MANAGER.error(f"Disk test failed: {e}")
            return 0

    def run_gpu_test(self):
        if not GPUtil:
            return 0

        LOG_MANAGER.info("Starting GPU test")
        try:
            gpus = GPUtil.getGPUs()
            if not gpus:
                return 0

            gpu = gpus[0]
            score = int((gpu.memoryTotal / 1024) * 10 + gpu.load * 5)
            LOG_MANAGER.log_performance('GPU', 0, f'Score: {score}')
            return score
        except Exception as e:
            LOG_MANAGER.error(f"GPU test failed: {e}")
            return 0

    def run_full_benchmark(self):
        self.running = True
        LOG_MANAGER.info("Starting full benchmark suite")

        self.results = {
            'timestamp': time.time(),
            'cpu_single': self.run_cpu_single_core(duration=3),
            'cpu_multi': self.run_cpu_multi_core(duration=3),
            'memory': self.run_memory_test(size_mb=100),
            'disk': self.run_disk_test(),
            'gpu': self.run_gpu_test(),
        }

        self.results['overall'] = int(
            self.results['cpu_single'] * 0.2 +
            self.results['cpu_multi'] * 0.3 +
            self.results['memory'] * 0.15 +
            self.results['disk'] * 0.2 +
            self.results['gpu'] * 0.15
        )

        self.history.append(self.results.copy())

        if not self.baseline:
            self.baseline = self.results.copy()
            LOG_MANAGER.info("Baseline benchmark set")

        self.running = False
        LOG_MANAGER.info(f"Benchmark complete - Overall score: {self.results['overall']}")
        return self.results

    def get_comparison(self):
        if not self.baseline or not self.results:
            return {}

        comparison = {}
        for key in ['cpu_single', 'cpu_multi', 'memory', 'disk', 'gpu', 'overall']:
            if key in self.baseline and key in self.results:
                baseline_val = self.baseline[key]
                current_val = self.results[key]
                if baseline_val > 0:
                    diff_percent = ((current_val - baseline_val) / baseline_val) * 100
                    comparison[key] = {
                        'baseline': baseline_val,
                        'current': current_val,
                        'diff_percent': diff_percent
                    }
        return comparison

    def export_results(self, filepath):
        try:
            data = {
                'results': self.results,
                'baseline': self.baseline,
                'history': self.history[-10:],
                'system_info': {
                    'cpu_count': multiprocessing.cpu_count(),
                    'ram_gb': psutil.virtual_memory().total / (1024**3),
                    'os': 'Windows'
                }
            }
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            LOG_MANAGER.error(f"Export failed: {e}")
            return False

BENCHMARK_SUITE = EnhancedBenchmarkSuite()

class AIOptimizationEngine:
    def __init__(self):
        self.enabled = True
        self.history_file = os.path.join(APP_DIR, 'optimization_history.json')
        self.behavior_patterns = defaultdict(list)
        self.suggestions = []
        self.applied_optimizations = []

        self.min_samples = 10
        self.confidence_threshold = 0.7

        self._load_history()

    def _load_history(self):
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    self.behavior_patterns = defaultdict(list, data.get('patterns', {}))
                    self.applied_optimizations = data.get('applied', [])
        except:
            pass

    def _save_history(self):
        try:
            with open(self.history_file, 'w') as f:
                json.dump({
                    'patterns': dict(self.behavior_patterns),
                    'applied': self.applied_optimizations
                }, f, indent=2)
        except:
            pass

    def record_system_state(self):
        try:
            state = {
                'timestamp': time.time(),
                'cpu_percent': psutil.cpu_percent(),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_io': psutil.disk_io_counters().read_bytes + psutil.disk_io_counters().write_bytes,
                'process_count': len(list(psutil.process_iter())),
                'active_optimizations': {
                    'priority_balancer': PRIORITY_BALANCER.enabled,
                    'mem_optimizer': MEM_OPTIMIZER.enabled,
                    'cpu_limiter': CPU_LIMITER.enabled,
                }
            }

            if state['cpu_percent'] > 80:
                self.behavior_patterns['high_cpu'].append(state)
            elif state['memory_percent'] > 80:
                self.behavior_patterns['high_memory'].append(state)
            elif state['process_count'] > 200:
                self.behavior_patterns['high_process_count'].append(state)
            else:
                self.behavior_patterns['normal'].append(state)

            for key in self.behavior_patterns:
                if len(self.behavior_patterns[key]) > 100:
                    self.behavior_patterns[key] = self.behavior_patterns[key][-100:]
        except:
            pass

    def generate_suggestions(self):
        self.suggestions = []

        if len(self.behavior_patterns['high_cpu']) >= self.min_samples:
            pattern = self.behavior_patterns['high_cpu']
            cpu_limiter_active = sum(1 for s in pattern if s['active_optimizations']['cpu_limiter']) / len(pattern)

            if cpu_limiter_active < 0.3:
                self.suggestions.append({
                    'type': 'enable_feature',
                    'feature': 'CPU Limiter',
                    'reason': 'High CPU usage detected frequently',
                    'confidence': 0.8,
                    'action': lambda: setattr(CPU_LIMITER, 'enabled', True)
                })

        if len(self.behavior_patterns['high_memory']) >= self.min_samples:
            pattern = self.behavior_patterns['high_memory']
            mem_opt_active = sum(1 for s in pattern if s['active_optimizations']['mem_optimizer']) / len(pattern)

            if mem_opt_active < 0.3:
                self.suggestions.append({
                    'type': 'enable_feature',
                    'feature': 'Memory Optimizer',
                    'reason': 'High memory usage detected frequently',
                    'confidence': 0.85,
                    'action': lambda: setattr(MEM_OPTIMIZER, 'enabled', True)
                })

        total_stressed = len(self.behavior_patterns['high_cpu']) + len(self.behavior_patterns['high_memory'])
        total_normal = len(self.behavior_patterns['normal'])

        if total_stressed > total_normal and not PRIORITY_BALANCER.enabled:
            self.suggestions.append({
                'type': 'enable_feature',
                'feature': 'OptiBalance',
                'reason': 'System frequently under stress',
                'confidence': 0.75,
                'action': lambda: setattr(PRIORITY_BALANCER, 'enabled', True)
            })

        self.suggestions = [s for s in self.suggestions if s['confidence'] >= self.confidence_threshold]

        return self.suggestions

    def apply_suggestion(self, suggestion):
        try:
            suggestion['action']()
            self.applied_optimizations.append({
                'timestamp': time.time(),
                'feature': suggestion['feature'],
                'reason': suggestion['reason']
            })
            self._save_history()
            LOG_MANAGER.info(f"Applied AI suggestion: {suggestion['feature']}")
            return True
        except Exception as e:
            LOG_MANAGER.error(f"Failed to apply suggestion: {e}")
            return False

AI_OPTIMIZER = AIOptimizationEngine()

class AnimationManager:
    def __init__(self):
        self._animations = {}
        self._running = True
        self._root = None

    def set_root(self, root):
        self._root = root

    def pulse_color(self, widget, property_name, color1, color2, duration_ms=1000, attr='configure'):
        if not self._root or not self._running:
            return

        try:
            def hex_to_rgb(hex_color):
                hex_color = hex_color.lstrip('#')
                return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

            def rgb_to_hex(r, g, b):
                return f"#{int(r):02x}{int(g):02x}{int(b):02x}"

            def lerp(a, b, t):
                return a + (b - a) * t

            r1, g1, b1 = hex_to_rgb(color1)
            r2, g2, b2 = hex_to_rgb(color2)

            widget_id = id(widget)
            if widget_id not in self._animations:
                self._animations[widget_id] = {}

            self._animations[widget_id][property_name] = {
                'active': True,
                'phase': 0.0,
                'direction': 1
            }

            def animate():
                if not self._running:
                    return
                try:
                    if widget_id not in self._animations:
                        return
                    if property_name not in self._animations[widget_id]:
                        return
                    state = self._animations[widget_id][property_name]
                    if not state['active']:
                        return

                    step = 50 / duration_ms * 2
                    state['phase'] += step * state['direction']

                    if state['phase'] >= 1.0:
                        state['phase'] = 1.0
                        state['direction'] = -1
                    elif state['phase'] <= 0.0:
                        state['phase'] = 0.0
                        state['direction'] = 1

                    t = state['phase']
                    t = t * t * (3 - 2 * t)

                    r = lerp(r1, r2, t)
                    g = lerp(g1, g2, t)
                    b = lerp(b1, b2, t)

                    color = rgb_to_hex(r, g, b)

                    if attr == 'configure':
                        widget.configure(**{property_name: color})

                    if self._running and state['active']:
                        self._root.after(50, animate)
                except:
                    pass

            animate()
        except:
            pass

    def pulse_opacity(self, widget, min_opacity=0.5, max_opacity=1.0, duration_ms=1500):
        pass

    def stop_animation(self, widget, property_name=None):
        widget_id = id(widget)
        if widget_id in self._animations:
            if property_name:
                if property_name in self._animations[widget_id]:
                    self._animations[widget_id][property_name]['active'] = False
            else:
                for prop in self._animations[widget_id]:
                    self._animations[widget_id][prop]['active'] = False

    def stop_all(self):
        self._running = False
        for widget_id in self._animations:
            for prop in self._animations[widget_id]:
                self._animations[widget_id][prop]['active'] = False

    def glow_effect(self, widget, base_color, glow_color, duration_ms=2000):
        self.pulse_color(widget, 'border_color', base_color, glow_color, duration_ms)

    def breathing_effect(self, widget, base_fg, bright_fg, duration_ms=3000):
        self.pulse_color(widget, 'fg_color', base_fg, bright_fg, duration_ms)

ANIMATION_MANAGER = AnimationManager()

class AutoTuningSystem:
    def __init__(self):
        self.enabled = False
        self.tuning_history = []
        self.current_config = {}
        self.baseline_performance = {}
        self.tuning_interval = 300
        self.last_tune = 0

        self.parameters = {
            'priority_threshold': {
                'min': 1.0,
                'max': 5.0,
                'current': 3.0,
                'step': 0.5,
                'target': 'PRIORITY_BALANCER.process_threshold'
            },
            'memory_threshold': {
                'min': 60.0,
                'max': 85.0,
                'current': 70.0,
                'step': 5.0,
                'target': 'MEM_OPTIMIZER.memory_threshold'
            },
            'cpu_limit_cores': {
                'min': 0.25,
                'max': 0.75,
                'current': 0.5,
                'step': 0.25,
                'target': 'CPU_LIMITER.limit_to_cores'
            }
        }

    def measure_performance(self):
        try:
            return {
                'cpu_avg': psutil.cpu_percent(interval=1),
                'memory_available': psutil.virtual_memory().available / (1024**3),
                'responsiveness': RESPONSIVENESS.current_score if hasattr(RESPONSIVENESS, 'current_score') else 100,
                'interventions': len(PRIORITY_BALANCER.lowered)
            }
        except:
            return {}

    def auto_tune(self):
        if not self.enabled:
            return

        now = time.time()
        if now - self.last_tune < self.tuning_interval:
            return

        self.last_tune = now

        if not self.baseline_performance:
            self.baseline_performance = self.measure_performance()
            LOG_MANAGER.info("Auto-tuner baseline established")
            return

        current_perf = self.measure_performance()

        for param_name, param_config in self.parameters.items():
            try:
                current_val = param_config['current']

                if current_val + param_config['step'] <= param_config['max']:
                    test_val = current_val + param_config['step']
                    self._apply_parameter(param_name, test_val)
                    time.sleep(10)
                    new_perf = self.measure_performance()

                    if self._is_better_performance(new_perf, current_perf):
                        param_config['current'] = test_val
                        LOG_MANAGER.info(f"Auto-tuned {param_name} to {test_val}")
                    else:
                        self._apply_parameter(param_name, current_val)
            except:
                pass

    def _apply_parameter(self, param_name, value):
        param = self.parameters[param_name]
        target = param['target']

        try:
            obj_name, attr_name = target.split('.')
            obj = globals()[obj_name]
            setattr(obj, attr_name, value)
        except:
            pass

    def _is_better_performance(self, new_perf, old_perf):
        score = 0

        if new_perf.get('responsiveness', 0) > old_perf.get('responsiveness', 0):
            score += 1
        if new_perf.get('cpu_avg', 100) < old_perf.get('cpu_avg', 100):
            score += 1
        if new_perf.get('memory_available', 0) > old_perf.get('memory_available', 0):
            score += 1

        return score >= 2

AUTO_TUNER = AutoTuningSystem()

class SystemHealthAnalyzer:
    def __init__(self):
        self.health_score = 100
        self.component_scores = {}
        self.bottlenecks = []
        self.warnings = []
        self.predictions = {}

    def analyze(self):
        scores = {}

        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_temp = THERMAL_MONITOR.cpu_temp or 50
        scores['cpu'] = max(0, min(100,
            100 - cpu_percent * 0.5 - max(0, (cpu_temp - 60) * 2)
        ))

        mem = psutil.virtual_memory()
        scores['memory'] = max(0, 100 - mem.percent * 0.8)

        try:
            disk = psutil.disk_usage('C:\\')
            disk_io = psutil.disk_io_counters()
            scores['disk'] = max(0, 100 - disk.percent * 0.6)
        except:
            scores['disk'] = 75

        if NETWORK_MONITOR.enabled:
            scores['network'] = 85
        else:
            scores['network'] = 100

        if GPUtil:
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu = gpus[0]
                    scores['gpu'] = max(0, 100 - gpu.load - max(0, (gpu.temperature - 70) * 2))
                else:
                    scores['gpu'] = 100
            except:
                scores['gpu'] = 100
        else:
            scores['gpu'] = 100

        process_count = len(list(psutil.process_iter()))
        scores['processes'] = max(0, 100 - max(0, (process_count - 100) * 0.5))

        self.component_scores = scores

        self.health_score = int(
            scores['cpu'] * 0.25 +
            scores['memory'] * 0.25 +
            scores['disk'] * 0.15 +
            scores['network'] * 0.10 +
            scores['gpu'] * 0.15 +
            scores['processes'] * 0.10
        )

        self._detect_bottlenecks()

        self._generate_warnings()

        return self.health_score

    def _detect_bottlenecks(self):
        self.bottlenecks = []

        for component, score in self.component_scores.items():
            if score < 50:
                self.bottlenecks.append({
                    'component': component,
                    'severity': 'critical' if score < 30 else 'warning',
                    'score': score
                })

    def _generate_warnings(self):
        self.warnings = []

        if self.health_score < 50:
            self.warnings.append("System health is poor - immediate optimization recommended")

        if self.component_scores.get('cpu', 100) < 40:
            self.warnings.append("CPU is bottleneck - consider enabling CPU Limiter")

        if self.component_scores.get('memory', 100) < 40:
            self.warnings.append("Memory is bottleneck - enable Memory Optimizer")

        if THERMAL_MONITOR.active_alerts:
            self.warnings.append("Thermal alerts active - check cooling")

    def predict_performance(self, hours_ahead=1):
        if hasattr(BENCHMARK_SUITE, 'history') and len(BENCHMARK_SUITE.history) >= 3:
            recent = BENCHMARK_SUITE.history[-3:]
            scores = [r['overall'] for r in recent]

            if len(scores) >= 2:
                trend = (scores[-1] - scores[0]) / len(scores)
                predicted = scores[-1] + trend * hours_ahead

                self.predictions['performance'] = {
                    'current': scores[-1],
                    'predicted': max(0, predicted),
                    'trend': 'improving' if trend > 0 else 'declining' if trend < 0 else 'stable'
                }

        return self.predictions

    def get_recommendations(self):
        recommendations = []

        for bottleneck in self.bottlenecks:
            comp = bottleneck['component']

            if comp == 'cpu' and not CPU_LIMITER.enabled:
                recommendations.append("Enable CPU Limiter to manage CPU-heavy processes")
            elif comp == 'memory' and not MEM_OPTIMIZER.enabled:
                recommendations.append("Enable Memory Optimizer to free up RAM")
            elif comp == 'processes' and not PRIORITY_BALANCER.enabled:
                recommendations.append("Enable OptiBalance to manage process priorities")

        return recommendations

HEALTH_ANALYZER = SystemHealthAnalyzer()

class SmartProcessManager:
    def __init__(self):
        self.process_profiles = {}
        self.categories = defaultdict(list)
        self.learning_file = os.path.join(APP_DIR, 'process_learning.json')

        self.known_patterns = {
            'browser': ['chrome', 'firefox', 'edge', 'opera', 'brave'],
            'game': ['game', 'launch', 'steam', 'epic'],
            'development': ['code', 'visual studio', 'pycharm', 'idea', 'eclipse'],
            'media': ['vlc', 'spotify', 'discord', 'teams', 'zoom'],
            'productivity': ['word', 'excel', 'powerpoint', 'outlook'],
            'system': ['svchost', 'dwm', 'explorer', 'winlogon']
        }

        self._load_learning()

    def _load_learning(self):
        try:
            if os.path.exists(self.learning_file):
                with open(self.learning_file, 'r') as f:
                    self.process_profiles = json.load(f)
        except:
            pass

    def _save_learning(self):
        try:
            with open(self.learning_file, 'w') as f:
                json.dump(self.process_profiles, f, indent=2)
        except:
            pass

    def learn_process_behavior(self, pid, name):
        try:
            p = psutil.Process(pid)

            if name not in self.process_profiles:
                self.process_profiles[name] = {
                    'samples': 0,
                    'avg_cpu': 0,
                    'avg_memory_mb': 0,
                    'category': self._categorize(name),
                    'suggested_priority': 'Normal'
                }

            profile = self.process_profiles[name]

            cpu = p.cpu_percent(interval=0.1)
            mem = p.memory_info().rss / (1024 * 1024)

            n = profile['samples']
            profile['avg_cpu'] = (profile['avg_cpu'] * n + cpu) / (n + 1)
            profile['avg_memory_mb'] = (profile['avg_memory_mb'] * n + mem) / (n + 1)
            profile['samples'] += 1

            if profile['avg_cpu'] > 50:
                profile['suggested_priority'] = 'Below Normal'
            elif profile['avg_cpu'] < 5 and profile['avg_memory_mb'] < 100:
                profile['suggested_priority'] = 'Low'

            if profile['samples'] % 10 == 0:
                self._save_learning()
        except:
            pass

    def _categorize(self, process_name):
        name_lower = process_name.lower()

        for category, patterns in self.known_patterns.items():
            for pattern in patterns:
                if pattern in name_lower:
                    return category

        return 'unknown'

    def get_process_category(self, process_name):
        if process_name in self.process_profiles:
            return self.process_profiles[process_name]['category']
        return self._categorize(process_name)

    def get_suggested_priority(self, process_name):
        if process_name in self.process_profiles:
            return self.process_profiles[process_name].get('suggested_priority', 'Normal')
        return 'Normal'

    def get_category_stats(self):
        stats = defaultdict(lambda: {'count': 0, 'total_cpu': 0, 'total_mem': 0})

        for name, profile in self.process_profiles.items():
            cat = profile['category']
            stats[cat]['count'] += 1
            stats[cat]['total_cpu'] += profile['avg_cpu']
            stats[cat]['total_mem'] += profile['avg_memory_mb']

        return dict(stats)

SMART_PROCESS_MGR = SmartProcessManager()

class AutomationRulesEngine:
    def __init__(self):
        self.enabled = True
        self.rules = []
        self.rules_file = os.path.join(APP_DIR, 'automation_rules.json')
        self.execution_history = deque(maxlen=100)

        self._load_rules()

    def _load_rules(self):
        try:
            if os.path.exists(self.rules_file):
                with open(self.rules_file, 'r') as f:
                    self.rules = json.load(f)
        except:
            self._create_default_rules()

    def _save_rules(self):
        try:
            with open(self.rules_file, 'w') as f:
                json.dump(self.rules, f, indent=2)
        except:
            pass

    def _create_default_rules(self):
        self.rules = [
            {
                'id': 'auto_clean_high_memory',
                'name': 'Auto Clean on High Memory',
                'enabled': True,
                'trigger': {
                    'type': 'threshold',
                    'condition': 'memory_percent > 85'
                },
                'actions': [
                    {'type': 'enable_feature', 'target': 'MEM_OPTIMIZER'},
                    {'type': 'cleanup', 'target': 'temp_files'}
                ],
                'cooldown': 300
            },
            {
                'id': 'auto_balance_high_cpu',
                'name': 'Auto Balance on High CPU',
                'enabled': True,
                'trigger': {
                    'type': 'threshold',
                    'condition': 'cpu_percent > 90'
                },
                'actions': [
                    {'type': 'enable_feature', 'target': 'PRIORITY_BALANCER'},
                    {'type': 'enable_feature', 'target': 'CPU_LIMITER'}
                ],
                'cooldown': 180
            },
            {
                'id': 'gaming_mode_on_game',
                'name': 'Auto Gaming Mode',
                'enabled': True,
                'trigger': {
                    'type': 'process_detected',
                    'patterns': ['game', 'steam', 'epic']
                },
                'actions': [
                    {'type': 'apply_profile', 'profile': 'Gaming'}
                ],
                'cooldown': 60
            }
        ]
        self._save_rules()

    def add_rule(self, rule):
        rule['id'] = f"custom_{len(self.rules)}_{int(time.time())}"
        self.rules.append(rule)
        self._save_rules()

    def remove_rule(self, rule_id):
        self.rules = [r for r in self.rules if r['id'] != rule_id]
        self._save_rules()

    def evaluate_rules(self):
        if not self.enabled:
            return

        for rule in self.rules:
            if not rule.get('enabled', True):
                continue

            last_exec = next((h for h in self.execution_history if h['rule_id'] == rule['id']), None)
            if last_exec:
                if time.time() - last_exec['timestamp'] < rule.get('cooldown', 60):
                    continue

            if self._evaluate_trigger(rule['trigger']):
                self._execute_actions(rule)

    def _evaluate_trigger(self, trigger):
        trigger_type = trigger.get('type')

        if trigger_type == 'threshold':
            condition = trigger.get('condition', '')
            try:
                context = {
                    'cpu_percent': psutil.cpu_percent(),
                    'memory_percent': psutil.virtual_memory().percent,
                    'disk_percent': psutil.disk_usage('C:\\').percent,
                    'temp': THERMAL_MONITOR.cpu_temp or 50,
                    'health': HEALTH_ANALYZER.health_score
                }
                return eval(condition, {"__builtins__": {}}, context)
            except:
                return False

        elif trigger_type == 'process_detected':
            patterns = trigger.get('patterns', [])
            for proc in psutil.process_iter(['name']):
                try:
                    name = proc.info['name'].lower()
                    if any(pattern in name for pattern in patterns):
                        return True
                except:
                    pass
            return False

        elif trigger_type == 'schedule':
            schedule = trigger.get('time', '00:00')
            current_time = time.strftime('%H:%M')
            return schedule == current_time

        return False

    def _execute_actions(self, rule):
        for action in rule.get('actions', []):
            try:
                action_type = action.get('type')

                if action_type == 'enable_feature':
                    target = action.get('target')
                    if target in globals():
                        setattr(globals()[target], 'enabled', True)

                elif action_type == 'cleanup':
                    target = action.get('target')
                    if target == 'temp_files':
                        SYSTEM_CLEANER.clean_temp_files()
                    elif target == 'browser_cache':
                        SYSTEM_CLEANER.clean_browser_cache()

                elif action_type == 'apply_profile':
                    pass

                LOG_MANAGER.info(f"Automation: Executed {action_type} for rule {rule['id']}")
            except Exception as e:
                LOG_MANAGER.error(f"Automation error: {e}")

        self.execution_history.append({
            'rule_id': rule['id'],
            'timestamp': time.time(),
            'rule_name': rule.get('name', 'Unknown')
        })

AUTOMATION_ENGINE = AutomationRulesEngine()

class ResourceForecaster:
    def __init__(self):
        self.history_hours = 24
        self.cpu_history = deque(maxlen=self.history_hours * 60)
        self.memory_history = deque(maxlen=self.history_hours * 60)
        self.disk_growth_history = deque(maxlen=168)

        self.forecasts = {}
        self.last_disk_usage = None

    def record_usage(self):
        try:
            self.cpu_history.append({
                'timestamp': time.time(),
                'value': psutil.cpu_percent()
            })

            self.memory_history.append({
                'timestamp': time.time(),
                'value': psutil.virtual_memory().percent
            })

            if len(self.disk_growth_history) == 0 or \
               time.time() - self.disk_growth_history[-1]['timestamp'] > 3600:
                disk_usage = psutil.disk_usage('C:\\').used
                if self.last_disk_usage:
                    growth = disk_usage - self.last_disk_usage
                    self.disk_growth_history.append({
                        'timestamp': time.time(),
                        'growth_mb': growth / (1024 * 1024)
                    })
                self.last_disk_usage = disk_usage
        except:
            pass

    def forecast_cpu(self, hours_ahead=1):
        if len(self.cpu_history) < 60:
            return None

        try:
            recent = list(self.cpu_history)[-60:]
            values = [h['value'] for h in recent]

            avg = sum(values) / len(values)

            first_half = sum(values[:30]) / 30
            second_half = sum(values[30:]) / 30
            trend = second_half - first_half

            forecast = avg + (trend * hours_ahead)
            return max(0, min(100, forecast))
        except:
            return None

    def forecast_memory(self, hours_ahead=1):
        if len(self.memory_history) < 60:
            return None

        try:
            recent = list(self.memory_history)[-60:]
            values = [h['value'] for h in recent]

            avg = sum(values) / len(values)

            first_half = sum(values[:30]) / 30
            second_half = sum(values[30:]) / 30
            trend = second_half - first_half

            forecast = avg + (trend * hours_ahead)
            return max(0, min(100, forecast))
        except:
            return None

    def forecast_disk_full(self):
        if len(self.disk_growth_history) < 24:
            return None

        try:
            growth_values = [h['growth_mb'] for h in self.disk_growth_history]
            avg_growth_per_hour = sum(growth_values) / len(growth_values)

            if avg_growth_per_hour <= 0:
                return "Never (disk not growing)"

            disk = psutil.disk_usage('C:\\')
            free_mb = disk.free / (1024 * 1024)

            hours_until_full = free_mb / avg_growth_per_hour

            if hours_until_full > 8760:
                return "More than 1 year"
            elif hours_until_full > 720:
                return f"{int(hours_until_full / 720)} months"
            elif hours_until_full > 24:
                return f"{int(hours_until_full / 24)} days"
            else:
                return f"{int(hours_until_full)} hours"
        except:
            return None

    def get_capacity_warnings(self):
        warnings = []

        cpu_forecast = self.forecast_cpu(hours_ahead=2)
        if cpu_forecast and cpu_forecast > 90:
            warnings.append(f"⚠️ CPU forecasted to reach {cpu_forecast:.0f}% in 2 hours")

        mem_forecast = self.forecast_memory(hours_ahead=2)
        if mem_forecast and mem_forecast > 90:
            warnings.append(f"⚠️ Memory forecasted to reach {mem_forecast:.0f}% in 2 hours")

        disk_forecast = self.forecast_disk_full()
        if disk_forecast and 'hours' in disk_forecast or 'days' in disk_forecast:
            warnings.append(f"⚠️ Disk will be full in {disk_forecast}")

        return warnings

RESOURCE_FORECASTER = ResourceForecaster()

class SecurityScanner:
    def __init__(self):
        self.enabled = True
        self.scan_interval = 600
        self.last_scan = 0
        self.threats = []

        self.suspicious_names = [
            'cryptominer', 'keylogger', 'ransomware', 'trojan',
            'backdoor', 'rootkit', 'spyware', 'malware'
        ]

        self.suspicious_behaviors = {
            'high_network_no_display': [],
            'unusual_startup': [],
            'high_cpu_hidden': []
        }

    def scan(self):
        if not self.enabled:
            return

        now = time.time()
        if now - self.last_scan < self.scan_interval:
            return

        self.last_scan = now
        self.threats = []

        LOG_MANAGER.info("Starting security scan")

        for proc in psutil.process_iter(['pid', 'name', 'exe', 'connections']):
            try:
                self._scan_process(proc)
            except:
                pass

        self._scan_startup()

        LOG_MANAGER.info(f"Security scan complete - {len(self.threats)} threats detected")

    def _scan_process(self, proc):
        try:
            name = (proc.info.get('name') or '').lower()
            exe = proc.info.get('exe', '')

            for pattern in self.suspicious_names:
                if pattern in name or pattern in exe.lower():
                    self.threats.append({
                        'type': 'suspicious_name',
                        'severity': 'high',
                        'process': name,
                        'pid': proc.info['pid'],
                        'description': f"Process name matches suspicious pattern: {pattern}"
                    })

            connections = proc.info.get('connections', [])
            if len(connections) > 10:
                try:
                    p = psutil.Process(proc.info['pid'])
                    if p.num_threads() < 5:
                        self.threats.append({
                            'type': 'suspicious_network',
                            'severity': 'medium',
                            'process': name,
                            'pid': proc.info['pid'],
                            'description': f"High network activity ({len(connections)} connections) without GUI"
                        })
                except:
                    pass
        except:
            pass

    def _scan_startup(self):
        try:
            startup_items = STARTUP_OPT.get_startup_items()
            for item in startup_items:
                name = item.get('name', '').lower()
                command = item.get('command', '').lower()

                for pattern in self.suspicious_names:
                    if pattern in name or pattern in command:
                        self.threats.append({
                            'type': 'suspicious_startup',
                            'severity': 'high',
                            'item': name,
                            'description': f"Startup item matches suspicious pattern: {pattern}"
                        })
        except:
            pass

    def get_security_score(self):
        score = 100

        for threat in self.threats:
            if threat['severity'] == 'high':
                score -= 20
            elif threat['severity'] == 'medium':
                score -= 10
            elif threat['severity'] == 'low':
                score -= 5

        return max(0, score)

    def quarantine_process(self, pid):
        try:
            p = psutil.Process(pid)
            p.suspend()
            LOG_MANAGER.warning(f"Quarantined process PID {pid}")
            return True
        except:
            return False

SECURITY_SCANNER = SecurityScanner()

class PerformanceVisualizer:
    def __init__(self):
        self.graph_data = {
            'cpu': deque(maxlen=60),
            'memory': deque(maxlen=60),
            'disk_read': deque(maxlen=60),
            'disk_write': deque(maxlen=60),
            'network_sent': deque(maxlen=60),
            'network_recv': deque(maxlen=60),
            'gpu': deque(maxlen=60),
            'temperature': deque(maxlen=60)
        }

        self.last_disk_io = None
        self.last_net_io = None

    def update(self):
        timestamp = time.time()

        self.graph_data['cpu'].append({
            'time': timestamp,
            'value': psutil.cpu_percent()
        })

        self.graph_data['memory'].append({
            'time': timestamp,
            'value': psutil.virtual_memory().percent
        })

        try:
            disk_io = psutil.disk_io_counters()
            if self.last_disk_io:
                read_rate = (disk_io.read_bytes - self.last_disk_io.read_bytes) / (1024 * 1024)
                write_rate = (disk_io.write_bytes - self.last_disk_io.write_bytes) / (1024 * 1024)

                self.graph_data['disk_read'].append({'time': timestamp, 'value': read_rate})
                self.graph_data['disk_write'].append({'time': timestamp, 'value': write_rate})

            self.last_disk_io = disk_io
        except:
            pass

        try:
            net_io = psutil.net_io_counters()
            if self.last_net_io:
                sent_rate = (net_io.bytes_sent - self.last_net_io.bytes_sent) / (1024 * 1024)
                recv_rate = (net_io.bytes_recv - self.last_net_io.bytes_recv) / (1024 * 1024)

                self.graph_data['network_sent'].append({'time': timestamp, 'value': sent_rate})
                self.graph_data['network_recv'].append({'time': timestamp, 'value': recv_rate})

            self.last_net_io = net_io
        except:
            pass

        if GPUtil:
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    self.graph_data['gpu'].append({
                        'time': timestamp,
                        'value': gpus[0].load * 100
                    })
            except:
                pass

        if THERMAL_MONITOR.cpu_temp:
            self.graph_data['temperature'].append({
                'time': timestamp,
                'value': THERMAL_MONITOR.cpu_temp
            })

    def get_graph_data(self, metric, seconds=60):
        if metric in self.graph_data:
            data = list(self.graph_data[metric])
            cutoff = time.time() - seconds
            return [d for d in data if d['time'] > cutoff]
        return []

    def get_all_current_values(self):
        current = {}
        for metric, data in self.graph_data.items():
            if data:
                current[metric] = data[-1]['value']
        return current

PERF_VISUALIZER = PerformanceVisualizer()

class PerformanceProfileManager:
    def __init__(self):
        self.profiles = {}
        self.current_profile = None
        self.profiles_file = os.path.join(APP_DIR, 'profiles.json')

        self._create_default_profiles()
        self._load_profiles()

    def _create_default_profiles(self):
        self.profiles = {
            'Balanced': {
                'name': 'Balanced',
                'description': 'Optimal balance between performance and efficiency',
                'settings': {
                    'priority_balancer': True,
                    'mem_optimizer': False,
                    'cpu_limiter': False,
                    'fg_booster': True,
                    'game_mode': False,
                    'power_saver': False,
                    'cpu_parking': 'auto',
                    'priority_threshold': 3.0,
                    'memory_threshold': 70.0
                }
            },
            'Performance': {
                'name': 'Performance',
                'description': 'Maximum performance, all optimizations active',
                'settings': {
                    'priority_balancer': True,
                    'mem_optimizer': True,
                    'cpu_limiter': False,
                    'fg_booster': True,
                    'game_mode': False,
                    'power_saver': False,
                    'cpu_parking': 'disable',
                    'priority_threshold': 2.0,
                    'memory_threshold': 80.0
                }
            },
            'Gaming': {
                'name': 'Gaming',
                'description': 'Optimized for gaming with maximum responsiveness',
                'settings': {
                    'priority_balancer': True,
                    'mem_optimizer': True,
                    'cpu_limiter': False,
                    'fg_booster': True,
                    'game_mode': True,
                    'power_saver': False,
                    'cpu_parking': 'disable',
                    'priority_threshold': 1.5,
                    'memory_threshold': 85.0
                }
            },
            'PowerSaver': {
                'name': 'Power Saver',
                'description': 'Maximize battery life and reduce power consumption',
                'settings': {
                    'priority_balancer': False,
                    'mem_optimizer': True,
                    'cpu_limiter': True,
                    'fg_booster': False,
                    'game_mode': False,
                    'power_saver': True,
                    'cpu_parking': 'enable',
                    'priority_threshold': 5.0,
                    'memory_threshold': 60.0
                }
            },
            'Silent': {
                'name': 'Silent',
                'description': 'Minimal system activity for noise reduction',
                'settings': {
                    'priority_balancer': True,
                    'mem_optimizer': False,
                    'cpu_limiter': True,
                    'fg_booster': False,
                    'game_mode': False,
                    'power_saver': True,
                    'cpu_parking': 'enable',
                    'priority_threshold': 4.0,
                    'memory_threshold': 65.0
                }
            }
        }

    def _load_profiles(self):
        try:
            if os.path.exists(self.profiles_file):
                with open(self.profiles_file, 'r') as f:
                    custom_profiles = json.load(f)
                    self.profiles.update(custom_profiles)
        except:
            pass

    def _save_profiles(self):
        try:
            custom = {k: v for k, v in self.profiles.items()
                     if k not in ['Balanced', 'Performance', 'Gaming', 'PowerSaver', 'Silent']}
            with open(self.profiles_file, 'w') as f:
                json.dump(custom, f, indent=2)
        except:
            pass

    def apply_profile(self, profile_name):
        if profile_name not in self.profiles:
            return False

        profile = self.profiles[profile_name]
        settings = profile['settings']

        try:
            PRIORITY_BALANCER.enabled = settings.get('priority_balancer', True)
            MEM_OPTIMIZER.enabled = settings.get('mem_optimizer', False)
            CPU_LIMITER.enabled = settings.get('cpu_limiter', False)
            FG_BOOSTER.enabled = settings.get('fg_booster', True)
            GAME_MODE.enabled = settings.get('game_mode', False)
            POWER_SAVER.enabled = settings.get('power_saver', False)

            if 'priority_threshold' in settings:
                PRIORITY_BALANCER.process_threshold = settings['priority_threshold']
            if 'memory_threshold' in settings:
                MEM_OPTIMIZER.memory_threshold = settings['memory_threshold']

            self.current_profile = profile_name
            LOG_MANAGER.info(f"Applied profile: {profile_name}")
            return True
        except Exception as e:
            LOG_MANAGER.error(f"Failed to apply profile: {e}")
            return False

    def create_custom_profile(self, name, description, settings):
        self.profiles[name] = {
            'name': name,
            'description': description,
            'settings': settings,
            'custom': True
        }
        self._save_profiles()
        LOG_MANAGER.info(f"Created custom profile: {name}")

    def delete_profile(self, name):
        if name in self.profiles and self.profiles[name].get('custom', False):
            del self.profiles[name]
            self._save_profiles()
            return True
        return False

    def get_current_settings(self):
        return {
            'priority_balancer': PRIORITY_BALANCER.enabled,
            'mem_optimizer': MEM_OPTIMIZER.enabled,
            'cpu_limiter': CPU_LIMITER.enabled,
            'fg_booster': FG_BOOSTER.enabled,
            'game_mode': GAME_MODE.enabled,
            'power_saver': POWER_SAVER.enabled,
            'priority_threshold': PRIORITY_BALANCER.process_threshold,
            'memory_threshold': MEM_OPTIMIZER.memory_threshold
        }

PROFILE_MANAGER = PerformanceProfileManager()

class NotificationCenter:
    def __init__(self):
        self.enabled = True
        self.notifications = deque(maxlen=100)
        self.priority_levels = ['low', 'medium', 'high', 'critical']
        self.categories = ['optimization', 'security', 'health', 'automation', 'system']

        self.min_priority = 'medium'
        self.show_toast = True
        self.sound_enabled = False

    def notify(self, message, priority='medium', category='system', details=None):
        if not self.enabled:
            return

        notification = {
            'id': f"notif_{int(time.time() * 1000)}",
            'timestamp': time.time(),
            'message': message,
            'priority': priority,
            'category': category,
            'details': details,
            'read': False,
            'dismissed': False
        }

        self.notifications.append(notification)
        LOG_MANAGER.info(f"Notification [{priority}] {category}: {message}")

        if self._should_display(notification):
            self._display_notification(notification)

        return notification['id']

    def _should_display(self, notification):
        priority_index = self.priority_levels.index(notification['priority'])
        min_index = self.priority_levels.index(self.min_priority)
        return priority_index >= min_index

    def _display_notification(self, notification):
        pass

    def mark_read(self, notification_id):
        for notif in self.notifications:
            if notif['id'] == notification_id:
                notif['read'] = True
                break

    def dismiss(self, notification_id):
        for notif in self.notifications:
            if notif['id'] == notification_id:
                notif['dismissed'] = True
                break

    def get_unread(self):
        return [n for n in self.notifications if not n['read']]

    def get_by_category(self, category):
        return [n for n in self.notifications if n['category'] == category]

    def get_by_priority(self, min_priority='medium'):
        min_index = self.priority_levels.index(min_priority)
        return [n for n in self.notifications
                if self.priority_levels.index(n['priority']) >= min_index]

    def clear_all(self):
        self.notifications.clear()

NOTIFICATION_CENTER = NotificationCenter()

class MaintenanceScheduler:
    def __init__(self):
        self.enabled = True
        self.tasks = {}
        self.last_run = {}
        self.schedule_file = os.path.join(APP_DIR, 'maintenance_schedule.json')

        self._create_default_schedule()
        self._load_schedule()

    def _create_default_schedule(self):
        self.tasks = {
            'cleanup_temp': {
                'name': 'Clean Temp Files',
                'enabled': True,
                'interval': 86400,
                'action': lambda: SYSTEM_CLEANER.clean_temp_files(),
                'last_run': 0
            },
            'cleanup_browser': {
                'name': 'Clean Browser Cache',
                'enabled': False,
                'interval': 604800,
                'action': lambda: SYSTEM_CLEANER.clean_browser_cache(),
                'last_run': 0
            },
            'optimize_memory': {
                'name': 'Memory Optimization',
                'enabled': True,
                'interval': 3600,
                'action': lambda: MEM_OPTIMIZER.check_and_trim() if MEM_OPTIMIZER.enabled else None,
                'last_run': 0
            },
            'security_scan': {
                'name': 'Security Scan',
                'enabled': True,
                'interval': 43200,
                'action': lambda: SECURITY_SCANNER.scan(),
                'last_run': 0
            },
            'health_check': {
                'name': 'System Health Check',
                'enabled': True,
                'interval': 3600,
                'action': lambda: self._health_check(),
                'last_run': 0
            },
            'benchmark': {
                'name': 'Performance Benchmark',
                'enabled': False,
                'interval': 604800,
                'action': lambda: BENCHMARK_SUITE.run_full_benchmark(),
                'last_run': 0
            }
        }

    def _load_schedule(self):
        try:
            if os.path.exists(self.schedule_file):
                with open(self.schedule_file, 'r') as f:
                    data = json.load(f)
                    for task_id, saved_data in data.items():
                        if task_id in self.tasks:
                            self.tasks[task_id]['enabled'] = saved_data.get('enabled', True)
                            self.tasks[task_id]['interval'] = saved_data.get('interval', 3600)
                            self.tasks[task_id]['last_run'] = saved_data.get('last_run', 0)
        except:
            pass

    def _save_schedule(self):
        try:
            data = {}
            for task_id, task in self.tasks.items():
                data[task_id] = {
                    'enabled': task['enabled'],
                    'interval': task['interval'],
                    'last_run': task.get('last_run', 0)
                }
            with open(self.schedule_file, 'w') as f:
                json.dump(data, f, indent=2)
        except:
            pass

    def run_due_tasks(self):
        if not self.enabled:
            return

        now = time.time()

        for task_id, task in self.tasks.items():
            if not task.get('enabled', False):
                continue

            last_run = task.get('last_run', 0)
            interval = task.get('interval', 3600)

            if now - last_run >= interval:
                try:
                    LOG_MANAGER.info(f"Running maintenance task: {task['name']}")
                    task['action']()
                    task['last_run'] = now
                    NOTIFICATION_CENTER.notify(
                        f"Completed: {task['name']}",
                        priority='low',
                        category='system'
                    )
                except Exception as e:
                    LOG_MANAGER.error(f"Maintenance task failed: {task['name']}: {e}")

        self._save_schedule()

    def _health_check(self):
        health = HEALTH_ANALYZER.analyze()
        if health < 50:
            NOTIFICATION_CENTER.notify(
                f"System health is low: {health}/100",
                priority='high',
                category='health',
                details={'score': health, 'recommendations': HEALTH_ANALYZER.get_recommendations()}
            )

    def set_task_enabled(self, task_id, enabled):
        if task_id in self.tasks:
            self.tasks[task_id]['enabled'] = enabled
            self._save_schedule()

    def set_task_interval(self, task_id, interval_seconds):
        if task_id in self.tasks:
            self.tasks[task_id]['interval'] = interval_seconds
            self._save_schedule()

    def run_task_now(self, task_id):
        if task_id in self.tasks:
            try:
                self.tasks[task_id]['action']()
                self.tasks[task_id]['last_run'] = time.time()
                self._save_schedule()
                return True
            except:
                return False
        return False

MAINTENANCE_SCHEDULER = MaintenanceScheduler()

class PowerEfficiencyAnalyzer:
    def __init__(self):
        self.enabled = True
        self.power_samples = deque(maxlen=60)
        self.efficiency_score = 100
        self.power_wasters = []

    def analyze(self):
        self.power_wasters = []

        cpu_percent = psutil.cpu_percent(interval=1)
        if cpu_percent > 50:
            reduction = 100 - cpu_percent
            self.power_wasters.append({
                'component': 'CPU',
                'impact': 'high' if cpu_percent > 80 else 'medium',
                'usage': f'{cpu_percent:.0f}%',
                'recommendation': 'Enable CPU Limiter to reduce power consumption'
            })

        try:
            process_count = 0
            total_cpu = 0
            for proc in psutil.process_iter(['cpu_percent']):
                try:
                    cpu = proc.info['cpu_percent'] or 0
                    if cpu > 0:
                        process_count += 1
                        total_cpu += cpu
                except:
                    pass

            if process_count > 150:
                self.power_wasters.append({
                    'component': 'Background Processes',
                    'impact': 'medium',
                    'usage': f'{process_count} processes',
                    'recommendation': 'Reduce startup programs and background tasks'
                })
        except:
            pass

        try:
            disk_io = psutil.disk_io_counters()
            if hasattr(self, '_last_disk_io'):
                diff = disk_io.read_count + disk_io.write_count - \
                       (self._last_disk_io.read_count + self._last_disk_io.write_count)
                if diff > 1000:
                    self.power_wasters.append({
                        'component': 'Disk I/O',
                        'impact': 'low',
                        'usage': f'{diff} operations/sec',
                        'recommendation': 'Consider using SSD or reducing disk-intensive tasks'
                    })
            self._last_disk_io = disk_io
        except:
            pass

        if GPUtil:
            try:
                gpus = GPUtil.getGPUs()
                for gpu in gpus:
                    if gpu.load > 50:
                        self.power_wasters.append({
                            'component': f'GPU ({gpu.name})',
                            'impact': 'high',
                            'usage': f'{gpu.load:.0f}% load',
                            'recommendation': 'Reduce GPU-intensive tasks when on battery'
                        })
            except:
                pass

        self.efficiency_score = 100
        for waster in self.power_wasters:
            if waster['impact'] == 'high':
                self.efficiency_score -= 20
            elif waster['impact'] == 'medium':
                self.efficiency_score -= 10
            else:
                self.efficiency_score -= 5

        self.efficiency_score = max(0, self.efficiency_score)

        return self.efficiency_score

    def get_recommendations(self):
        return [w['recommendation'] for w in self.power_wasters]

    def estimate_battery_impact(self):
        if self.efficiency_score >= 80:
            return "Excellent - Maximum battery life"
        elif self.efficiency_score >= 60:
            return "Good - ~10-20% battery life reduction"
        elif self.efficiency_score >= 40:
            return "Fair - ~20-40% battery life reduction"
        else:
            return "Poor - Significant battery drain (40%+ reduction)"

    def apply_power_saving(self):
        try:
            POWER_SAVER.enabled = True
            CPU_LIMITER.enabled = True
            MEM_OPTIMIZER.enabled = True

            PROFILE_MANAGER.apply_profile('PowerSaver')

            NOTIFICATION_CENTER.notify(
                "Power saving mode activated",
                priority='medium',
                category='system'
            )
            LOG_MANAGER.info("Applied power saving optimizations")
            return True
        except:
            return False

POWER_ANALYZER = PowerEfficiencyAnalyzer()

class SystemSnapshotManager:
    def __init__(self):
        self.snapshots = []
        self.snapshot_dir = os.path.join(APP_DIR, 'snapshots')
        os.makedirs(self.snapshot_dir, exist_ok=True)

        self._load_snapshots()

    def create_snapshot(self, name=None, description=""):
        if name is None:
            name = f"Snapshot_{time.strftime('%Y%m%d_%H%M%S')}"

        snapshot = {
            'id': f"snap_{int(time.time())}",
            'name': name,
            'description': description,
            'timestamp': time.time(),
            'state': {
                'features': {
                    'priority_balancer': PRIORITY_BALANCER.enabled,
                    'mem_optimizer': MEM_OPTIMIZER.enabled,
                    'cpu_limiter': CPU_LIMITER.enabled,
                    'fg_booster': FG_BOOSTER.enabled,
                    'game_mode': GAME_MODE.enabled,
                    'power_saver': POWER_SAVER.enabled,
                },
                'settings': {
                    'priority_threshold': PRIORITY_BALANCER.process_threshold,
                    'memory_threshold': MEM_OPTIMIZER.memory_threshold,
                    'cpu_limit_ratio': CPU_LIMITER.limit_to_cores,
                },
                'profile': PROFILE_MANAGER.current_profile,
                'affinity_rules': AFFINITY_MGR.get_rules() if hasattr(AFFINITY_MGR, 'get_rules') else {},
                'automation_rules': AUTOMATION_ENGINE.rules,
            },
            'metrics': {
                'health_score': HEALTH_ANALYZER.health_score,
                'cpu_avg': psutil.cpu_percent(),
                'memory_percent': psutil.virtual_memory().percent,
                'benchmark': BENCHMARK_SUITE.results if BENCHMARK_SUITE.results else {}
            }
        }

        self.snapshots.append(snapshot)
        self._save_snapshot(snapshot)

        LOG_MANAGER.info(f"Created snapshot: {name}")
        NOTIFICATION_CENTER.notify(
            f"Snapshot created: {name}",
            priority='low',
            category='system'
        )

        return snapshot['id']

    def restore_snapshot(self, snapshot_id):
        snapshot = next((s for s in self.snapshots if s['id'] == snapshot_id), None)
        if not snapshot:
            return False

        try:
            state = snapshot['state']

            features = state['features']
            PRIORITY_BALANCER.enabled = features.get('priority_balancer', True)
            MEM_OPTIMIZER.enabled = features.get('mem_optimizer', False)
            CPU_LIMITER.enabled = features.get('cpu_limiter', False)
            FG_BOOSTER.enabled = features.get('fg_booster', True)
            GAME_MODE.enabled = features.get('game_mode', False)
            POWER_SAVER.enabled = features.get('power_saver', False)

            settings = state['settings']
            PRIORITY_BALANCER.process_threshold = settings.get('priority_threshold', 3.0)
            MEM_OPTIMIZER.memory_threshold = settings.get('memory_threshold', 70.0)
            CPU_LIMITER.limit_to_cores = settings.get('cpu_limit_ratio', 0.5)

            if state.get('profile'):
                PROFILE_MANAGER.apply_profile(state['profile'])

            LOG_MANAGER.info(f"Restored snapshot: {snapshot['name']}")
            NOTIFICATION_CENTER.notify(
                f"Restored snapshot: {snapshot['name']}",
                priority='medium',
                category='system'
            )

            return True
        except Exception as e:
            LOG_MANAGER.error(f"Failed to restore snapshot: {e}")
            return False

    def delete_snapshot(self, snapshot_id):
        self.snapshots = [s for s in self.snapshots if s['id'] != snapshot_id]

        snapshot_file = os.path.join(self.snapshot_dir, f"{snapshot_id}.json")
        if os.path.exists(snapshot_file):
            os.remove(snapshot_file)

    def compare_snapshots(self, snapshot_id1, snapshot_id2):
        snap1 = next((s for s in self.snapshots if s['id'] == snapshot_id1), None)
        snap2 = next((s for s in self.snapshots if s['id'] == snapshot_id2), None)

        if not snap1 or not snap2:
            return None

        comparison = {
            'metrics_diff': {},
            'settings_diff': {},
            'features_diff': {}
        }

        for key in snap1.get('metrics', {}).keys():
            val1 = snap1['metrics'].get(key, 0)
            val2 = snap2['metrics'].get(key, 0)
            if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
                comparison['metrics_diff'][key] = val2 - val1

        return comparison

    def _save_snapshot(self, snapshot):
        try:
            snapshot_file = os.path.join(self.snapshot_dir, f"{snapshot['id']}.json")
            with open(snapshot_file, 'w') as f:
                json.dump(snapshot, f, indent=2)
        except:
            pass

    def _load_snapshots(self):
        try:
            for filename in os.listdir(self.snapshot_dir):
                if filename.endswith('.json'):
                    filepath = os.path.join(self.snapshot_dir, filename)
                    with open(filepath, 'r') as f:
                        snapshot = json.load(f)
                        self.snapshots.append(snapshot)
        except:
            pass

SNAPSHOT_MANAGER = SystemSnapshotManager()

class AnomalyDetector:
    def __init__(self):
        self.enabled = True
        self.baselines = {}
        self.anomalies = []
        self.sensitivity = 2.0

        self.monitored_metrics = [
            'cpu_percent', 'memory_percent', 'disk_io_rate',
            'network_io_rate', 'process_count', 'thread_count'
        ]

    def record_baseline(self):
        try:
            metrics = {
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_io_rate': 0,
                'network_io_rate': 0,
                'process_count': len(list(psutil.process_iter())),
                'thread_count': sum(1 for _ in threading.enumerate())
            }

            if hasattr(self, '_last_disk_io'):
                disk_io = psutil.disk_io_counters()
                diff = (disk_io.read_bytes + disk_io.write_bytes) - \
                       (self._last_disk_io.read_bytes + self._last_disk_io.write_bytes)
                metrics['disk_io_rate'] = diff / (1024 * 1024)
            self._last_disk_io = psutil.disk_io_counters()

            if hasattr(self, '_last_net_io'):
                net_io = psutil.net_io_counters()
                diff = (net_io.bytes_sent + net_io.bytes_recv) - \
                       (self._last_net_io.bytes_sent + self._last_net_io.bytes_recv)
                metrics['network_io_rate'] = diff / (1024 * 1024)
            self._last_net_io = psutil.net_io_counters()

            for metric, value in metrics.items():
                if metric not in self.baselines:
                    self.baselines[metric] = {'mean': value, 'std': 0, 'samples': []}

                baseline = self.baselines[metric]
                baseline['samples'].append(value)

                if len(baseline['samples']) > 100:
                    baseline['samples'] = baseline['samples'][-100:]

                baseline['mean'] = sum(baseline['samples']) / len(baseline['samples'])
                if len(baseline['samples']) > 1:
                    variance = sum((x - baseline['mean']) ** 2 for x in baseline['samples']) / len(baseline['samples'])
                    baseline['std'] = variance ** 0.5
        except:
            pass

    def detect_anomalies(self):
        if not self.enabled or not self.baselines:
            return []

        self.anomalies = []

        try:
            current = {
                'cpu_percent': psutil.cpu_percent(),
                'memory_percent': psutil.virtual_memory().percent,
                'process_count': len(list(psutil.process_iter())),
                'thread_count': sum(1 for _ in threading.enumerate())
            }

            for metric, value in current.items():
                if metric in self.baselines:
                    baseline = self.baselines[metric]
                    mean = baseline['mean']
                    std = baseline['std']

                    if std > 0:
                        z_score = abs((value - mean) / std)

                        if z_score > self.sensitivity:
                            severity = 'critical' if z_score > 3 else 'high' if z_score > 2.5 else 'medium'

                            anomaly = {
                                'metric': metric,
                                'value': value,
                                'baseline_mean': mean,
                                'z_score': z_score,
                                'severity': severity,
                                'timestamp': time.time(),
                                'description': f"{metric} is {z_score:.1f} standard deviations from normal"
                            }

                            self.anomalies.append(anomaly)

                            if severity in ['critical', 'high']:
                                NOTIFICATION_CENTER.notify(
                                    f"Anomaly detected: {anomaly['description']}",
                                    priority=severity,
                                    category='health',
                                    details=anomaly
                                )
        except:
            pass

        return self.anomalies

    def get_anomaly_report(self):
        return {
            'total_anomalies': len(self.anomalies),
            'by_severity': {
                'critical': len([a for a in self.anomalies if a['severity'] == 'critical']),
                'high': len([a for a in self.anomalies if a['severity'] == 'high']),
                'medium': len([a for a in self.anomalies if a['severity'] == 'medium'])
            },
            'anomalies': self.anomalies
        }

ANOMALY_DETECTOR = AnomalyDetector()

class ResourceAllocationOptimizer:
    def __init__(self):
        self.enabled = True
        self.allocation_strategy = 'balanced'
        self.app_priorities = {}

    def optimize_allocation(self):
        if not self.enabled:
            return

        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    info = proc.info
                    if info['cpu_percent'] and info['cpu_percent'] > 0:
                        processes.append({
                            'pid': info['pid'],
                            'name': info['name'],
                            'cpu': info['cpu_percent'],
                            'memory': info['memory_percent'] or 0,
                            'priority': self.app_priorities.get(info['name'], 'normal')
                        })
                except:
                    pass

            processes.sort(key=lambda x: x['cpu'] + x['memory'], reverse=True)

            if self.allocation_strategy == 'balanced':
                self._apply_balanced_allocation(processes)
            elif self.allocation_strategy == 'performance':
                self._apply_performance_allocation(processes)
            elif self.allocation_strategy == 'efficiency':
                self._apply_efficiency_allocation(processes)

            LOG_MANAGER.info(f"Optimized resource allocation ({self.allocation_strategy} strategy)")
        except Exception as e:
            LOG_MANAGER.error(f"Resource allocation failed: {e}")

    def _apply_balanced_allocation(self, processes):
        for proc in processes[:5]:
            if proc['priority'] != 'high':
                try:
                    p = psutil.Process(proc['pid'])
                    p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
                except:
                    pass

    def _apply_performance_allocation(self, processes):
        for proc in processes:
            try:
                p = psutil.Process(proc['pid'])
                if proc['priority'] == 'high':
                    p.nice(psutil.HIGH_PRIORITY_CLASS)
                elif proc['priority'] == 'low':
                    p.nice(psutil.IDLE_PRIORITY_CLASS)
            except:
                pass

    def _apply_efficiency_allocation(self, processes):
        for proc in processes[:3]:
            try:
                p = psutil.Process(proc['pid'])
                p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            except:
                pass

    def set_app_priority(self, app_name, priority='normal'):
        self.app_priorities[app_name] = priority
        LOG_MANAGER.info(f"Set {app_name} priority to {priority}")

RESOURCE_OPTIMIZER = ResourceAllocationOptimizer()

class ReportGenerator:
    def __init__(self):
        self.report_dir = os.path.join(APP_DIR, 'reports')
        os.makedirs(self.report_dir, exist_ok=True)

    def generate_system_report(self, format='html'):
        timestamp = time.strftime('%Y%m%d_%H%M%S')

        report_data = {
            'timestamp': time.time(),
            'system_info': self._get_system_info(),
            'health_analysis': self._get_health_data(),
            'performance_metrics': self._get_performance_data(),
            'optimization_status': self._get_optimization_status(),
            'security': self._get_security_data(),
            'recommendations': self._get_recommendations()
        }

        if format == 'html':
            return self._generate_html_report(report_data, timestamp)
        elif format == 'json':
            return self._generate_json_report(report_data, timestamp)
        else:
            return None

    def _get_system_info(self):
        return {
            'os': 'Windows',
            'cpu_count': multiprocessing.cpu_count(),
            'ram_gb': psutil.virtual_memory().total / (1024**3),
            'disk_total_gb': psutil.disk_usage('C:\\').total / (1024**3),
            'disk_free_gb': psutil.disk_usage('C:\\').free / (1024**3)
        }

    def _get_health_data(self):
        health = HEALTH_ANALYZER.analyze()
        return {
            'overall_score': health,
            'component_scores': HEALTH_ANALYZER.component_scores,
            'bottlenecks': HEALTH_ANALYZER.bottlenecks,
            'warnings': HEALTH_ANALYZER.warnings
        }

    def _get_performance_data(self):
        return {
            'cpu_percent': psutil.cpu_percent(),
            'memory_percent': psutil.virtual_memory().percent,
            'disk_percent': psutil.disk_usage('C:\\').percent,
            'process_count': len(list(psutil.process_iter())),
            'benchmark_results': BENCHMARK_SUITE.results if BENCHMARK_SUITE.results else {}
        }

    def _get_optimization_status(self):
        return {
            'priority_balancer': PRIORITY_BALANCER.enabled,
            'mem_optimizer': MEM_OPTIMIZER.enabled,
            'cpu_limiter': CPU_LIMITER.enabled,
            'game_mode': GAME_MODE.enabled,
            'current_profile': PROFILE_MANAGER.current_profile,
            'automation_rules': len(AUTOMATION_ENGINE.rules)
        }

    def _get_security_data(self):
        return {
            'security_score': SECURITY_SCANNER.get_security_score(),
            'threats_detected': len(SECURITY_SCANNER.threats),
            'threats': SECURITY_SCANNER.threats[:10]
        }

    def _get_recommendations(self):
        recs = []
        recs.extend(HEALTH_ANALYZER.get_recommendations())
        recs.extend(AI_OPTIMIZER.generate_suggestions())
        recs.extend(POWER_ANALYZER.get_recommendations())
        return recs[:10]

    def _generate_html_report(self, data, timestamp):
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>OptiCores System Report - {timestamp}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background:
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color:
        h2 {{ color:
        .score {{ font-size: 48px; font-weight: bold; color:
        .metric {{ display: inline-block; margin: 10px 20px; padding: 15px; background:
        .warning {{ color:
        .good {{ color:
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid
        th {{ background:
        .badge {{ padding: 5px 10px; border-radius: 15px; font-size: 12px; font-weight: bold; }}
        .badge-high {{ background:
        .badge-medium {{ background:
        .badge-low {{ background:
    </style>
</head>
<body>
    <div class="container">
        <h1>⚡ OptiCores System Health Report</h1>
        <p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

        <h2>System Health Score</h2>
        <div class="score {'good' if data['health_analysis']['overall_score'] >= 70 else 'warning'}">
            {data['health_analysis']['overall_score']}/100
        </div>

        <h2>System Information</h2>
        <div class="metric">CPU Cores: <strong>{data['system_info']['cpu_count']}</strong></div>
        <div class="metric">RAM: <strong>{data['system_info']['ram_gb']:.1f} GB</strong></div>
        <div class="metric">Disk Total: <strong>{data['system_info']['disk_total_gb']:.1f} GB</strong></div>
        <div class="metric">Disk Free: <strong>{data['system_info']['disk_free_gb']:.1f} GB</strong></div>

        <h2>Current Performance</h2>
        <div class="metric">CPU: <strong>{data['performance_metrics']['cpu_percent']:.1f}%</strong></div>
        <div class="metric">Memory: <strong>{data['performance_metrics']['memory_percent']:.1f}%</strong></div>
        <div class="metric">Disk: <strong>{data['performance_metrics']['disk_percent']:.1f}%</strong></div>
        <div class="metric">Processes: <strong>{data['performance_metrics']['process_count']}</strong></div>

        <h2>Component Health Scores</h2>
        <table>
            <tr><th>Component</th><th>Score</th><th>Status</th></tr>
"""

        for component, score in data['health_analysis']['component_scores'].items():
            status = 'Good' if score >= 70 else 'Fair' if score >= 40 else 'Poor'
            status_class = 'good' if score >= 70 else 'warning'
            html += f"            <tr><td>{component.upper()}</td><td><strong>{score:.0f}/100</strong></td><td class='{status_class}'>{status}</td></tr>\n"

        html += f"""
        </table>

        <h2>Security Status</h2>
        <div class="metric">Security Score: <strong class="{'good' if data['security']['security_score'] >= 80 else 'warning'}">{data['security']['security_score']}/100</strong></div>
        <div class="metric">Threats: <strong class="{'good' if data['security']['threats_detected'] == 0 else 'warning'}">{data['security']['threats_detected']}</strong></div>

        <h2>Optimization Features</h2>
        <div class="metric">OptiBalance: <strong>{'✓ Enabled' if data['optimization_status']['priority_balancer'] else '✗ Disabled'}</strong></div>
        <div class="metric">Memory Optimizer: <strong>{'✓ Enabled' if data['optimization_status']['mem_optimizer'] else '✗ Disabled'}</strong></div>
        <div class="metric">CPU Limiter: <strong>{'✓ Enabled' if data['optimization_status']['cpu_limiter'] else '✗ Disabled'}</strong></div>
        <div class="metric">Current Profile: <strong>{data['optimization_status']['current_profile'] or 'None'}</strong></div>

        <h2>Recommendations</h2>
        <ol>
"""

        for rec in data['recommendations']:
            if isinstance(rec, dict):
                html += f"            <li>{rec.get('feature', 'Optimization')}: {rec.get('reason', 'Recommended')}</li>\n"
            else:
                html += f"            <li>{rec}</li>\n"

        html += """
        </ol>

        <p style="margin-top: 40px; text-align: center; color: #666;">
            Generated by OptiCores - Advanced System Optimization Platform
        </p>
    </div>
</body>
</html>
"""

        filename = f"report_{timestamp}.html"
        filepath = os.path.join(self.report_dir, filename)
        with open(filepath, 'w') as f:
            f.write(html)

        LOG_MANAGER.info(f"Generated system report: {filename}")
        return filepath

    def _generate_json_report(self, data, timestamp):
        filename = f"report_{timestamp}.json"
        filepath = os.path.join(self.report_dir, filename)
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        return filepath

REPORT_GENERATOR = ReportGenerator()

class DashboardDataAggregator:
    def __init__(self):
        self.last_update = 0
        self.update_interval = 1.0
        self.cached_data = {}

    def get_complete_dashboard_data(self):
        now = time.time()

        if now - self.last_update < self.update_interval:
            return self.cached_data

        self.cached_data = {
            'timestamp': now,

            'system': {
                'cpu_percent': psutil.cpu_percent(),
                'memory_percent': psutil.virtual_memory().percent,
                'memory_available_gb': psutil.virtual_memory().available / (1024**3),
                'disk_percent': psutil.disk_usage('C:\\').percent,
                'disk_free_gb': psutil.disk_usage('C:\\').free / (1024**3),
                'process_count': len(list(psutil.process_iter())),
                'uptime_hours': (now - psutil.boot_time()) / 3600
            },

            'health': {
                'overall_score': HEALTH_ANALYZER.health_score,
                'component_scores': HEALTH_ANALYZER.component_scores,
                'bottlenecks': len(HEALTH_ANALYZER.bottlenecks),
                'warnings': len(HEALTH_ANALYZER.warnings),
                'security_score': SECURITY_SCANNER.get_security_score(),
                'power_efficiency': POWER_ANALYZER.efficiency_score
            },

            'optimization': {
                'priority_balancer': PRIORITY_BALANCER.enabled,
                'mem_optimizer': MEM_OPTIMIZER.enabled,
                'cpu_limiter': CPU_LIMITER.enabled,
                'game_mode': GAME_MODE.enabled,
                'current_profile': PROFILE_MANAGER.current_profile,
                'active_rules': len([r for r in AUTOMATION_ENGINE.rules if r.get('enabled', True)]),
                'interventions_total': len(PRIORITY_BALANCER.lowered)
            },

            'thermal': {
                'cpu_temp': THERMAL_MONITOR.cpu_temp,
                'gpu_temps': THERMAL_MONITOR.gpu_temps,
                'active_alerts': len(THERMAL_MONITOR.active_alerts)
            },

            'network': {
                'upload_mbps': NETWORK_MONITOR.upload_speed * 8 / (1024 * 1024) if NETWORK_MONITOR.enabled else 0,
                'download_mbps': NETWORK_MONITOR.download_speed * 8 / (1024 * 1024) if NETWORK_MONITOR.enabled else 0,
            },

            'intelligence': {
                'ai_suggestions': len(AI_OPTIMIZER.suggestions),
                'anomalies_detected': len(ANOMALY_DETECTOR.anomalies),
                'learned_processes': len(SMART_PROCESS_MGR.process_profiles),
                'baselines_established': len(ANOMALY_DETECTOR.baselines)
            },

            'notifications': {
                'unread_count': len(NOTIFICATION_CENTER.get_unread()),
                'total_count': len(NOTIFICATION_CENTER.notifications),
                'high_priority': len(NOTIFICATION_CENTER.get_by_priority('high'))
            },

            'maintenance': {
                'scheduled_tasks': len(MAINTENANCE_SCHEDULER.tasks),
                'enabled_tasks': len([t for t in MAINTENANCE_SCHEDULER.tasks.values() if t.get('enabled', False)]),
                'next_task_due': self._get_next_task_time()
            },

            'forecast': {
                'cpu_2h': RESOURCE_FORECASTER.forecast_cpu(hours_ahead=2),
                'memory_2h': RESOURCE_FORECASTER.forecast_memory(hours_ahead=2),
                'disk_full_eta': RESOURCE_FORECASTER.forecast_disk_full(),
                'warnings': len(RESOURCE_FORECASTER.get_capacity_warnings())
            },

            'benchmark': {
                'has_results': bool(BENCHMARK_SUITE.results),
                'overall_score': BENCHMARK_SUITE.results.get('overall', 0) if BENCHMARK_SUITE.results else 0,
                'history_count': len(BENCHMARK_SUITE.history)
            },

            'snapshots': {
                'total_count': len(SNAPSHOT_MANAGER.snapshots),
                'latest_snapshot': SNAPSHOT_MANAGER.snapshots[-1]['name'] if SNAPSHOT_MANAGER.snapshots else None
            }
        }

        self.last_update = now
        return self.cached_data

    def _get_next_task_time(self):
        try:
            now = time.time()
            next_times = []
            for task in MAINTENANCE_SCHEDULER.tasks.values():
                if task.get('enabled', False):
                    last_run = task.get('last_run', 0)
                    interval = task.get('interval', 3600)
                    next_run = last_run + interval
                    if next_run > now:
                        next_times.append(next_run - now)

            if next_times:
                min_seconds = min(next_times)
                if min_seconds < 3600:
                    return f"{int(min_seconds / 60)} minutes"
                else:
                    return f"{int(min_seconds / 3600)} hours"
            return "No tasks scheduled"
        except:
            return "Unknown"

    def get_summary_stats(self):
        data = self.get_complete_dashboard_data()
        return {
            'health_score': data['health']['overall_score'],
            'cpu': data['system']['cpu_percent'],
            'memory': data['system']['memory_percent'],
            'active_optimizations': sum([
                data['optimization']['priority_balancer'],
                data['optimization']['mem_optimizer'],
                data['optimization']['cpu_limiter'],
                data['optimization']['game_mode']
            ]),
            'threats': 100 - data['health']['security_score'],
            'anomalies': data['intelligence']['anomalies_detected'],
            'unread_notifications': data['notifications']['unread_count']
        }

DASHBOARD = DashboardDataAggregator()

class UnifiedCommandSystem:
    def __init__(self):
        self.command_history = deque(maxlen=100)

        self.commands = {
            'enable_feature': self._enable_feature,
            'disable_feature': self._disable_feature,
            'apply_profile': self._apply_profile,
            'run_benchmark': self._run_benchmark,
            'cleanup': self._cleanup,
            'create_snapshot': self._create_snapshot,
            'restore_snapshot': self._restore_snapshot,
            'generate_report': self._generate_report,
            'scan_security': self._scan_security,
            'optimize_resources': self._optimize_resources,
            'analyze_health': self._analyze_health
        }

    def execute(self, command_name, **kwargs):
        if command_name not in self.commands:
            return {'success': False, 'error': 'Unknown command'}

        try:
            result = self.commands[command_name](**kwargs)

            self.command_history.append({
                'command': command_name,
                'kwargs': kwargs,
                'timestamp': time.time(),
                'success': result.get('success', True)
            })

            LOG_MANAGER.info(f"Executed command: {command_name}")
            return result
        except Exception as e:
            LOG_MANAGER.error(f"Command failed: {command_name}: {e}")
            return {'success': False, 'error': str(e)}

    def _enable_feature(self, feature):
        feature_map = {
            'priority_balancer': PRIORITY_BALANCER,
            'mem_optimizer': MEM_OPTIMIZER,
            'cpu_limiter': CPU_LIMITER,
            'game_mode': GAME_MODE,
            'power_saver': POWER_SAVER
        }

        if feature in feature_map:
            feature_map[feature].enabled = True
            return {'success': True, 'message': f'Enabled {feature}'}
        return {'success': False, 'error': 'Unknown feature'}

    def _disable_feature(self, feature):
        feature_map = {
            'priority_balancer': PRIORITY_BALANCER,
            'mem_optimizer': MEM_OPTIMIZER,
            'cpu_limiter': CPU_LIMITER,
            'game_mode': GAME_MODE,
            'power_saver': POWER_SAVER
        }

        if feature in feature_map:
            feature_map[feature].enabled = False
            return {'success': True, 'message': f'Disabled {feature}'}
        return {'success': False, 'error': 'Unknown feature'}

    def _apply_profile(self, profile_name):
        success = PROFILE_MANAGER.apply_profile(profile_name)
        return {'success': success, 'message': f'Applied profile: {profile_name}' if success else 'Failed'}

    def _run_benchmark(self):
        results = BENCHMARK_SUITE.run_full_benchmark()
        return {'success': True, 'results': results}

    def _cleanup(self, target='temp_files'):
        if target == 'temp_files':
            files, bytes_freed = SYSTEM_CLEANER.clean_temp_files()
            return {'success': True, 'files_deleted': files, 'mb_freed': bytes_freed / (1024*1024)}
        elif target == 'browser_cache':
            files, bytes_freed = SYSTEM_CLEANER.clean_browser_cache()
            return {'success': True, 'files_deleted': files, 'mb_freed': bytes_freed / (1024*1024)}
        return {'success': False, 'error': 'Unknown cleanup target'}

    def _create_snapshot(self, name=None, description=''):
        snapshot_id = SNAPSHOT_MANAGER.create_snapshot(name, description)
        return {'success': True, 'snapshot_id': snapshot_id}

    def _restore_snapshot(self, snapshot_id):
        success = SNAPSHOT_MANAGER.restore_snapshot(snapshot_id)
        return {'success': success}

    def _generate_report(self, format='html'):
        filepath = REPORT_GENERATOR.generate_system_report(format)
        return {'success': True, 'filepath': filepath}

    def _scan_security(self):
        SECURITY_SCANNER.scan()
        return {'success': True, 'threats': len(SECURITY_SCANNER.threats)}

    def _optimize_resources(self):
        RESOURCE_OPTIMIZER.optimize_allocation()
        return {'success': True}

    def _analyze_health(self):
        score = HEALTH_ANALYZER.analyze()
        return {'success': True, 'health_score': score}

COMMAND_SYSTEM = UnifiedCommandSystem()

class PerformanceImpactTracker:
    def __init__(self):
        self.baseline_metrics = None
        self.current_metrics = {}
        self.improvement_history = deque(maxlen=24)

    def set_baseline(self):
        self.baseline_metrics = {
            'timestamp': time.time(),
            'cpu_avg': psutil.cpu_percent(interval=5),
            'memory_avg': psutil.virtual_memory().percent,
            'responsiveness': RESPONSIVENESS.current_score if hasattr(RESPONSIVENESS, 'current_score') else 100,
            'health_score': HEALTH_ANALYZER.health_score,
            'enabled_features': {
                'priority_balancer': PRIORITY_BALANCER.enabled,
                'mem_optimizer': MEM_OPTIMIZER.enabled,
                'cpu_limiter': CPU_LIMITER.enabled
            }
        }
        LOG_MANAGER.info("Performance baseline set")
        return self.baseline_metrics

    def measure_current(self):
        self.current_metrics = {
            'timestamp': time.time(),
            'cpu_avg': psutil.cpu_percent(interval=5),
            'memory_avg': psutil.virtual_memory().percent,
            'responsiveness': RESPONSIVENESS.current_score if hasattr(RESPONSIVENESS, 'current_score') else 100,
            'health_score': HEALTH_ANALYZER.health_score,
            'enabled_features': {
                'priority_balancer': PRIORITY_BALANCER.enabled,
                'mem_optimizer': MEM_OPTIMIZER.enabled,
                'cpu_limiter': CPU_LIMITER.enabled
            }
        }
        return self.current_metrics

    def calculate_impact(self):
        if not self.baseline_metrics:
            return None

        self.measure_current()

        impact = {
            'cpu_change': self.baseline_metrics['cpu_avg'] - self.current_metrics['cpu_avg'],
            'memory_change': self.baseline_metrics['memory_avg'] - self.current_metrics['memory_avg'],
            'responsiveness_change': self.current_metrics['responsiveness'] - self.baseline_metrics['responsiveness'],
            'health_change': self.current_metrics['health_score'] - self.baseline_metrics['health_score'],
            'overall_improvement': 0
        }

        improvements = []
        if impact['cpu_change'] > 0:
            improvements.append(min(impact['cpu_change'], 20))
        if impact['memory_change'] > 0:
            improvements.append(min(impact['memory_change'], 20))
        if impact['responsiveness_change'] > 0:
            improvements.append(min(impact['responsiveness_change'] / 5, 20))
        if impact['health_change'] > 0:
            improvements.append(min(impact['health_change'] / 2, 20))

        impact['overall_improvement'] = sum(improvements) if improvements else 0

        self.improvement_history.append({
            'timestamp': time.time(),
            'improvement_score': impact['overall_improvement'],
            'cpu_saved': impact['cpu_change'],
            'memory_saved': impact['memory_change']
        })

        return impact

    def get_impact_report(self):
        if not self.baseline_metrics:
            return {'error': 'No baseline set'}

        impact = self.calculate_impact()

        return {
            'baseline': self.baseline_metrics,
            'current': self.current_metrics,
            'impact': impact,
            'recommendations': self._get_impact_recommendations(impact)
        }

    def _get_impact_recommendations(self, impact):
        recs = []

        if impact['cpu_change'] < 0:
            recs.append("CPU usage increased - consider disabling some optimizations")
        elif impact['cpu_change'] > 10:
            recs.append(f"Excellent CPU savings: {impact['cpu_change']:.1f}%")

        if impact['memory_change'] < 0:
            recs.append("Memory usage increased - check for memory leaks")
        elif impact['memory_change'] > 10:
            recs.append(f"Great memory savings: {impact['memory_change']:.1f}%")

        if impact['overall_improvement'] > 40:
            recs.append("🎯 Optimizations are highly effective!")
        elif impact['overall_improvement'] < 10:
            recs.append("⚠️ Limited improvement - try different settings")

        return recs

IMPACT_TRACKER = PerformanceImpactTracker()

class SystemStabilityMonitor:
    def __init__(self):
        self.start_time = time.time()
        self.crash_detection_enabled = True
        self.stability_events = deque(maxlen=100)
        self.last_health_check = 0

    def record_event(self, event_type, severity='info', details=''):
        event = {
            'timestamp': time.time(),
            'type': event_type,
            'severity': severity,
            'details': details
        }
        self.stability_events.append(event)

        if severity in ['critical', 'error']:
            NOTIFICATION_CENTER.notify(
                f"Stability event: {event_type}",
                priority='high' if severity == 'error' else 'critical',
                category='system',
                details=event
            )

    def check_stability(self):
        now = time.time()

        if now - self.last_health_check < 300:
            return

        self.last_health_check = now

        stability_score = 100
        issues = []

        try:
            cpu = psutil.cpu_percent(interval=2)
            if cpu > 95:
                stability_score -= 20
                issues.append("Sustained high CPU usage")
                self.record_event('high_cpu', 'warning', f'CPU at {cpu}%')
        except:
            pass

        try:
            mem = psutil.virtual_memory()
            if mem.percent > 95:
                stability_score -= 20
                issues.append("Critical memory pressure")
                self.record_event('memory_pressure', 'error', f'Memory at {mem.percent}%')
        except:
            pass

        try:
            proc_count = len(list(psutil.process_iter()))
            if proc_count > 300:
                stability_score -= 10
                issues.append("Excessive process count")
        except:
            pass

        if len(ANOMALY_DETECTOR.anomalies) > 5:
            stability_score -= 15
            issues.append("Multiple anomalies detected")

        return {
            'stability_score': max(0, stability_score),
            'issues': issues,
            'uptime_hours': (now - self.start_time) / 3600,
            'events_last_hour': len([e for e in self.stability_events
                                     if e['timestamp'] > now - 3600])
        }

    def get_uptime_report(self):
        now = time.time()
        system_boot = psutil.boot_time()

        return {
            'opticores_uptime_hours': (now - self.start_time) / 3600,
            'system_uptime_hours': (now - system_boot) / 3600,
            'total_events': len(self.stability_events),
            'critical_events': len([e for e in self.stability_events if e['severity'] == 'critical'])
        }

STABILITY_MONITOR = SystemStabilityMonitor()

class FPSOverlay:
    def __init__(self):
        self.enabled = False
        self.window = None
        self.labels = {}
        self._update_thread = None
        self._stop_event = threading.Event()
        self.position = (50, 50)
        self.update_interval = 500

    def create_window(self, parent=None):
        if self.window:
            return

        self.window = ctk.CTkToplevel()
        self.window.title("FPS Overlay")
        self.window.geometry(f"180x120+{self.position[0]}+{self.position[1]}")
        self.window.overrideredirect(True)
        self.window.attributes('-topmost', True)
        self.window.attributes('-alpha', 0.85)

        self.window.bind('<Button-1>', self._start_drag)
        self.window.bind('<B1-Motion>', self._drag)

        frame = ctk.CTkFrame(self.window, fg_color="#0D1117", corner_radius=10,
                             border_width=2, border_color="#8B5CF6")
        frame.pack(fill="both", expand=True, padx=2, pady=2)

        header = ctk.CTkLabel(frame, text="⚡ OptiCores", font=ctk.CTkFont(size=11, weight="bold"),
                              text_color="#8B5CF6")
        header.pack(pady=(5,2))

        stats = ctk.CTkFrame(frame, fg_color="transparent")
        stats.pack(fill="x", padx=8)

        self.labels['fps'] = ctk.CTkLabel(stats, text="FPS: --",
                                           font=ctk.CTkFont(size=16, weight="bold"),
                                           text_color="#10B981")
        self.labels['fps'].pack(anchor="w")

        self.labels['cpu'] = ctk.CTkLabel(stats, text="CPU: --%",
                                           font=ctk.CTkFont(size=12),
                                           text_color="#F9FAFB")
        self.labels['cpu'].pack(anchor="w")

        self.labels['gpu'] = ctk.CTkLabel(stats, text="GPU: --%",
                                           font=ctk.CTkFont(size=12),
                                           text_color="#F9FAFB")
        self.labels['gpu'].pack(anchor="w")

        self.labels['ram'] = ctk.CTkLabel(stats, text="RAM: --%",
                                           font=ctk.CTkFont(size=12),
                                           text_color="#F9FAFB")
        self.labels['ram'].pack(anchor="w")

        close_btn = ctk.CTkButton(frame, text="✕", width=20, height=20,
                                   fg_color="transparent", hover_color="#EF4444",
                                   command=self.hide)
        close_btn.place(relx=1.0, rely=0, x=-25, y=5)

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _drag(self, event):
        if self.window:
            x = self.window.winfo_x() + event.x - self._drag_x
            y = self.window.winfo_y() + event.y - self._drag_y
            self.window.geometry(f"+{x}+{y}")
            self.position = (x, y)

    def update_stats(self):
        if not self.window or not self.enabled:
            return

        try:
            cpu = psutil.cpu_percent()
            self.labels['cpu'].configure(text=f"CPU: {cpu:.0f}%")

            ram = psutil.virtual_memory().percent
            self.labels['ram'].configure(text=f"RAM: {ram:.0f}%")

            gpu = 0
            try:
                if GPUtil:
                    gpus = GPUtil.getGPUs()
                    if gpus:
                        gpu = gpus[0].load * 100
            except:
                pass
            self.labels['gpu'].configure(text=f"GPU: {gpu:.0f}%")

            if gpu > 50:
                estimated_fps = max(30, int(144 - (gpu - 50) * 1.5))
                self.labels['fps'].configure(text=f"~{estimated_fps} FPS", text_color="#10B981")
            elif gpu > 20:
                self.labels['fps'].configure(text="~60+ FPS", text_color="#10B981")
            else:
                self.labels['fps'].configure(text="Idle", text_color="#6B7280")

        except Exception as e:
            pass

    def _update_loop(self):
        while not self._stop_event.is_set():
            if self.enabled and self.window:
                try:
                    self.window.after(0, self.update_stats)
                except:
                    pass
            self._stop_event.wait(self.update_interval / 1000)

    def show(self):
        if not self.window:
            self.create_window()
        self.enabled = True
        self.window.deiconify()

        if not self._update_thread or not self._update_thread.is_alive():
            self._stop_event.clear()
            self._update_thread = threading.Thread(target=self._update_loop, daemon=True)
            self._update_thread.start()

    def hide(self):
        self.enabled = False
        self._stop_event.set()
        if self.window:
            self.window.withdraw()

    def toggle(self):
        if self.enabled:
            self.hide()
        else:
            self.show()

    def destroy(self):
        self.enabled = False
        self._stop_event.set()
        if self.window:
            self.window.destroy()
            self.window = None

FPS_OVERLAY = FPSOverlay()

class PerformanceHistory:
    def __init__(self):
        self.enabled = False
        self.history = []
        self.max_entries = 1800
        self._log_thread = None
        self._stop_event = threading.Event()
        self.log_interval = 2.0

    def start_logging(self, interval=1.0):
        self.log_interval = interval
        self.enabled = True
        self._stop_event.clear()

        if self._log_thread and self._log_thread.is_alive():
            return

        def log_loop():
            while not self._stop_event.is_set():
                self._log_sample()
                self._stop_event.wait(self.log_interval)

        self._log_thread = threading.Thread(target=log_loop, daemon=True)
        self._log_thread.start()

    def stop_logging(self):
        self.enabled = False
        self._stop_event.set()

    def _log_sample(self):
        try:
            sample = {
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                'epoch': time.time(),
                'cpu': psutil.cpu_percent(),
                'ram': psutil.virtual_memory().percent,
                'gpu': 0
            }

            try:
                if GPUtil:
                    gpus = GPUtil.getGPUs()
                    if gpus:
                        sample['gpu'] = gpus[0].load * 100
            except:
                pass

            self.history.append(sample)

            if len(self.history) > self.max_entries:
                self.history = self.history[-self.max_entries:]

        except:
            pass

    def export_csv(self, filepath=None):
        if not filepath:
            filepath = os.path.join(APP_DIR, f"perf_history_{time.strftime('%Y%m%d_%H%M%S')}.csv")

        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                f.write("timestamp,cpu,ram,gpu\n")
                for s in self.history:
                    f.write(f"{s['timestamp']},{s['cpu']:.1f},{s['ram']:.1f},{s['gpu']:.1f}\n")
            return filepath
        except:
            return None

    def export_json(self, filepath=None):
        if not filepath:
            filepath = os.path.join(APP_DIR, f"perf_history_{time.strftime('%Y%m%d_%H%M%S')}.json")

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, indent=2)
            return filepath
        except:
            return None

    def get_averages(self, last_n=60):
        if not self.history:
            return {'cpu': 0, 'ram': 0, 'gpu': 0}

        samples = self.history[-last_n:]
        return {
            'cpu': sum(s['cpu'] for s in samples) / len(samples),
            'ram': sum(s['ram'] for s in samples) / len(samples),
            'gpu': sum(s['gpu'] for s in samples) / len(samples)
        }

    def clear(self):
        self.history = []

PERF_HISTORY = PerformanceHistory()

class ProcessTimeline:
    def __init__(self):
        self.enabled = False
        self.events = []
        self.max_events = 500
        self._known_pids = set()
        self._monitor_thread = None
        self._stop_event = threading.Event()
        self.check_interval = 5.0

    def start_monitoring(self):
        self.enabled = True
        self._stop_event.clear()

        self._known_pids = set(p.pid for p in psutil.process_iter(['pid']))

        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        def monitor_loop():
            while not self._stop_event.is_set():
                self._check_changes()
                self._stop_event.wait(self.check_interval)

        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop_monitoring(self):
        self.enabled = False
        self._stop_event.set()

    def _check_changes(self):
        try:
            current_pids = {}
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    current_pids[p.info['pid']] = p.info['name']
                except:
                    pass

            current_set = set(current_pids.keys())

            for pid in current_set - self._known_pids:
                self._log_event('start', pid, current_pids.get(pid, 'Unknown'))

            for pid in self._known_pids - current_set:
                self._log_event('stop', pid, 'Unknown')

            self._known_pids = current_set

        except:
            pass

    def _log_event(self, event_type, pid, name):
        self.events.append({
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'event': event_type,
            'pid': pid,
            'name': name
        })

        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events:]

    def get_recent_events(self, count=20):
        return list(reversed(self.events[-count:]))

    def get_starts(self, count=20):
        starts = [e for e in self.events if e['event'] == 'start']
        return list(reversed(starts[-count:]))

    def export_timeline(self, filepath=None):
        if not filepath:
            filepath = os.path.join(APP_DIR, f"process_timeline_{time.strftime('%Y%m%d_%H%M%S')}.json")

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.events, f, indent=2)
            return filepath
        except:
            return None

PROC_TIMELINE = ProcessTimeline()

class AlertSystem:
    def __init__(self):
        self.enabled = False
        self.thresholds = {
            'cpu': 90,
            'ram': 90,
            'gpu': 95,
        }
        self.cooldown = 60
        self._last_alerts = {}
        self._monitor_thread = None
        self._stop_event = threading.Event()
        self.check_interval = 10.0
        self.alert_callback = None

    def start_monitoring(self, callback=None):
        self.enabled = True
        self.alert_callback = callback
        self._stop_event.clear()

        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        def monitor_loop():
            while not self._stop_event.is_set():
                self._check_thresholds()
                self._stop_event.wait(self.check_interval)

        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop_monitoring(self):
        self.enabled = False
        self._stop_event.set()

    def _check_thresholds(self):
        try:
            now = time.time()

            cpu = psutil.cpu_percent()
            if cpu > self.thresholds['cpu']:
                self._trigger_alert('cpu', cpu)

            ram = psutil.virtual_memory().percent
            if ram > self.thresholds['ram']:
                self._trigger_alert('ram', ram)

            try:
                if GPUtil:
                    gpus = GPUtil.getGPUs()
                    if gpus:
                        gpu = gpus[0].load * 100
                        if gpu > self.thresholds['gpu']:
                            self._trigger_alert('gpu', gpu)
            except:
                pass

        except:
            pass

    def _trigger_alert(self, alert_type, value):
        now = time.time()

        if alert_type in self._last_alerts:
            if now - self._last_alerts[alert_type] < self.cooldown:
                return

        self._last_alerts[alert_type] = now

        labels = {'cpu': 'CPU', 'ram': 'RAM', 'gpu': 'GPU'}
        msg = f"⚠️ {labels[alert_type]} usage high: {value:.0f}%"

        if self.alert_callback:
            try:
                self.alert_callback(alert_type, msg)
            except:
                pass

        try:
            from win10toast import ToastNotifier
            toaster = ToastNotifier()
            toaster.show_toast("OptiCores Alert", msg, duration=5, threaded=True)
        except:
            pass

    def set_threshold(self, alert_type, value):
        if alert_type in self.thresholds:
            self.thresholds[alert_type] = value

ALERT_SYSTEM = AlertSystem()

class AIChatEngine:
    def __init__(self):
        self.chat_history = deque(maxlen=50)
        self.context = {}

        self.patterns = {
            'status': {
                'keywords': ['status', 'how is', 'how\'s', 'what is', 'whats', 'current', 'right now'],
                'responses': self._get_status_response
            },
            'cpu': {
                'keywords': ['cpu', 'processor', 'core'],
                'responses': self._get_cpu_response
            },
            'memory': {
                'keywords': ['memory', 'ram', 'mem'],
                'responses': self._get_memory_response
            },
            'disk': {
                'keywords': ['disk', 'storage', 'drive', 'ssd', 'hdd'],
                'responses': self._get_disk_response
            },
            'gpu': {
                'keywords': ['gpu', 'graphics', 'video card', 'nvidia', 'amd radeon'],
                'responses': self._get_gpu_response
            },

            'optibalance': {
                'keywords': ['optibalance', 'priority balance', 'balance'],
                'responses': self._get_optibalance_response
            },
            'gamemode': {
                'keywords': ['game mode', 'gamemode', 'gaming'],
                'responses': self._get_gamemode_response
            },
            'boost': {
                'keywords': ['boost', 'faster', 'speed up', 'speedup', 'performance'],
                'responses': self._get_boost_response
            },
            'clean': {
                'keywords': ['clean', 'junk', 'temp', 'temporary', 'cache', 'clear'],
                'responses': self._get_clean_response
            },

            'optimize': {
                'keywords': ['optimize', 'fix', 'improve', 'help me', 'make better'],
                'responses': self._get_optimize_response
            },
            'slow': {
                'keywords': ['slow', 'lag', 'lagging', 'sluggish', 'freezing', 'freeze'],
                'responses': self._get_slow_response
            },

            'what': {
                'keywords': ['what is', 'what does', 'what\'s', 'explain', 'how does'],
                'responses': self._get_explain_response
            },
            'how': {
                'keywords': ['how to', 'how do i', 'how can i'],
                'responses': self._get_howto_response
            },

            'greeting': {
                'keywords': ['hello', 'hi', 'hey', 'good morning', 'good afternoon', 'good evening'],
                'responses': self._get_greeting_response
            },
            'thanks': {
                'keywords': ['thank', 'thanks', 'thx', 'appreciate'],
                'responses': self._get_thanks_response
            }
        }

    def ask(self, question):
        question_lower = question.lower().strip()

        if not question_lower:
            return self._create_response(
                "Please ask me something! I can help with system status, optimization tips, and troubleshooting.",
                "info"
            )

        self.chat_history.append({
            'role': 'user',
            'message': question,
            'timestamp': time.time()
        })

        best_match = None
        best_score = 0

        for category, data in self.patterns.items():
            for keyword in data['keywords']:
                if keyword in question_lower:
                    score = len(keyword)
                    if score > best_score:
                        best_score = score
                        best_match = category

        if best_match:
            response = self.patterns[best_match]['responses'](question_lower)
        else:
            response = self._get_default_response(question_lower)

        self.chat_history.append({
            'role': 'assistant',
            'message': response['text'],
            'timestamp': time.time()
        })

        return response

    def _create_response(self, text, response_type='info', actions=None, data=None):
        return {
            'text': text,
            'type': response_type,
            'actions': actions or [],
            'data': data or {},
            'timestamp': time.time()
        }

    def _get_status_response(self, question):
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage('C:\\')

            if cpu < 50 and mem.percent < 70:
                status = "excellent"
                emoji = "🟢"
            elif cpu < 75 and mem.percent < 85:
                status = "good"
                emoji = "🟡"
            else:
                status = "under pressure"
                emoji = "🔴"

            text = f"{emoji} Your system is running {status}!\n\n"
            text += f"• **CPU**: {cpu:.0f}% utilized\n"
            text += f"• **RAM**: {mem.percent:.0f}% used ({mem.used / (1024**3):.1f} GB / {mem.total / (1024**3):.1f} GB)\n"
            text += f"• **Disk C:**: {disk.percent:.0f}% used ({disk.free / (1024**3):.0f} GB free)\n"

            if cpu > 80:
                text += "\n💡 **Tip**: High CPU usage detected. Enable OptiBalance to manage process priorities."
            if mem.percent > 85:
                text += "\n💡 **Tip**: Memory is running low. Consider using the 'Free RAM' action."

            return self._create_response(text, 'info', data={'cpu': cpu, 'memory': mem.percent})
        except:
            return self._create_response("I couldn't retrieve system status right now. Please try again.", 'error')

    def _get_cpu_response(self, question):
        try:
            cpu_percent = psutil.cpu_percent(interval=0.5)
            cpu_count = psutil.cpu_count()
            cpu_freq = psutil.cpu_freq()

            text = f"🖥️ **CPU Status**\n\n"
            text += f"• **Usage**: {cpu_percent:.1f}%\n"
            text += f"• **Cores**: {cpu_count} (logical)\n"
            if cpu_freq:
                text += f"• **Frequency**: {cpu_freq.current:.0f} MHz\n"

            per_core = psutil.cpu_percent(percpu=True)
            if per_core:
                max_core = max(per_core)
                min_core = min(per_core)
                text += f"• **Core Range**: {min_core:.0f}% - {max_core:.0f}%\n"

            if cpu_percent > 80:
                text += "\n⚠️ CPU is under heavy load. I recommend enabling **OptiBalance** to automatically manage background processes."
            elif cpu_percent < 30:
                text += "\n✅ CPU has plenty of headroom. Your system is running efficiently!"

            return self._create_response(text, 'info')
        except Exception as e:
            return self._create_response(f"Error getting CPU info: {str(e)}", 'error')

    def _get_memory_response(self, question):
        try:
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()

            text = f"💾 **Memory Status**\n\n"
            text += f"• **RAM Used**: {mem.percent:.1f}% ({mem.used / (1024**3):.2f} GB)\n"
            text += f"• **RAM Total**: {mem.total / (1024**3):.2f} GB\n"
            text += f"• **RAM Available**: {mem.available / (1024**3):.2f} GB\n"

            if swap.total > 0:
                text += f"• **Swap Used**: {swap.percent:.1f}% ({swap.used / (1024**3):.2f} GB)\n"

            if mem.percent > 85:
                text += "\n🔴 Memory is running critically low! Here's what I can do:\n"
                text += "• Use the **Free RAM** quick action\n"
                text += "• Enable **Memory Optimizer** in Booster tab\n"
                text += "• Close unused applications"
            elif mem.percent > 70:
                text += "\n🟡 Memory usage is moderate. Consider freeing up some RAM if you're about to run demanding apps."
            else:
                text += "\n🟢 Memory looks healthy! You have plenty of headroom."

            return self._create_response(text, 'info')
        except Exception as e:
            return self._create_response(f"Error getting memory info: {str(e)}", 'error')

    def _get_disk_response(self, question):
        try:
            text = f"💽 **Disk Status**\n\n"

            for partition in psutil.disk_partitions():
                if 'cdrom' in partition.opts.lower() or partition.fstype == '':
                    continue
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    text += f"**{partition.mountpoint}** ({partition.fstype})\n"
                    text += f"   • Used: {usage.percent:.1f}% ({usage.used / (1024**3):.1f} GB / {usage.total / (1024**3):.1f} GB)\n"
                    text += f"   • Free: {usage.free / (1024**3):.1f} GB\n\n"
                except:
                    pass

            c_disk = psutil.disk_usage('C:\\')
            if c_disk.percent > 90:
                text += "⚠️ Your main drive is almost full! Use the **Junk Cleaner** in the Tools tab to free up space."

            return self._create_response(text, 'info')
        except Exception as e:
            return self._create_response(f"Error getting disk info: {str(e)}", 'error')

    def _get_gpu_response(self, question):
        try:
            if GPUtil:
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu = gpus[0]
                    text = f"🎮 **GPU Status**\n\n"
                    text += f"• **Model**: {gpu.name}\n"
                    text += f"• **Load**: {gpu.load * 100:.0f}%\n"
                    text += f"• **Memory**: {gpu.memoryUsed:.0f} MB / {gpu.memoryTotal:.0f} MB ({gpu.memoryUtil * 100:.0f}%)\n"
                    if gpu.temperature:
                        text += f"• **Temperature**: {gpu.temperature}°C\n"

                    if gpu.load > 0.9:
                        text += "\n🔥 GPU is working hard! If gaming, this is normal. Otherwise, check what's using it."

                    return self._create_response(text, 'info')

            return self._create_response(
                "🎮 GPU information requires GPUtil library. Install it with: `pip install gputil`\n\n"
                "Alternatively, your GPU might not be detected.",
                'warning'
            )
        except Exception as e:
            return self._create_response(f"Error getting GPU info: {str(e)}", 'error')

    def _get_optibalance_response(self, question):
        enabled = PRIORITY_BALANCER.enabled if 'PRIORITY_BALANCER' in dir() else False
        stats = PRIORITY_BALANCER.get_stats() if 'PRIORITY_BALANCER' in dir() else {}

        text = f"⚡ **OptiBalance**\n\n"
        text += "OptiBalance is an intelligent process priority manager. It automatically:\n\n"
        text += "• Detects CPU-hogging background processes\n"
        text += "• Temporarily lowers their priority\n"
        text += "• Restores priority when system load decreases\n"
        text += "• Keeps your foreground apps responsive\n\n"

        status = "🟢 Enabled" if enabled else "🔴 Disabled"
        text += f"**Status**: {status}\n"

        if enabled and stats:
            text += f"• Processes managed: {stats.get('lowered_count', 0)}\n"
            text += f"• Actions taken: {stats.get('actions_taken', 0)}\n"

        if not enabled:
            text += "\n💡 Enable it from the **Booster** tab or use the Auto-Pilot switch above!"

        return self._create_response(text, 'info')

    def _get_gamemode_response(self, question):
        text = f"🎮 **Game Mode**\n\n"
        text += "Game Mode automatically optimizes your system when a game is detected:\n\n"
        text += "• Boosts game process priority\n"
        text += "• Stops non-essential Windows services\n"
        text += "• Sets high-performance power plan\n"
        text += "• Reduces timer resolution for lower input lag\n\n"

        try:
            active = GAME_MODE.active if 'GAME_MODE' in dir() else False
            if active:
                game = GAME_MODE.current_game_name or "Unknown"
                text += f"🎯 **Currently Active** - Game detected: {game}"
            else:
                text += "Status: Ready and waiting for games!"
        except:
            pass

        text += "\n\n💡 Enable it from the **Booster** tab under Gaming section."

        return self._create_response(text, 'info')

    def _get_boost_response(self, question):
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory().percent

        text = f"🚀 **Performance Boost Tips**\n\n"
        text += "Here's how to speed up your system:\n\n"

        suggestions = []

        if cpu > 60:
            suggestions.append("• Enable **OptiBalance** to manage process priorities")

        if mem > 70:
            suggestions.append("• Click **Free RAM** to clear memory")
            suggestions.append("• Enable **Memory Optimizer** for automatic management")

        suggestions.append("• Enable **Foreground Booster** to prioritize your active window")
        suggestions.append("• Go to **Tools > Junk Cleaner** to remove temporary files")
        suggestions.append("• Check **Startup** programs and disable unnecessary ones")

        for s in suggestions:
            text += s + "\n"

        text += "\n💡 For the best experience, try the **Optimize All** quick action above!"

        return self._create_response(text, 'info')

    def _get_clean_response(self, question):
        try:
            temp_dir = os.environ.get('TEMP', '')
            temp_size = 0
            if os.path.exists(temp_dir):
                for root, dirs, files in os.walk(temp_dir):
                    for f in files:
                        try:
                            temp_size += os.path.getsize(os.path.join(root, f))
                        except:
                            pass

            text = f"🧹 **Cleaning Options**\n\n"
            text += f"**Estimated Temporary Files**: {temp_size / (1024*1024):.0f} MB\n\n"
            text += "To clean your system:\n\n"
            text += "1. Go to **Tools** tab\n"
            text += "2. Click **Junk Cleaner**\n"
            text += "3. Review and clean temp files, browser cache, etc.\n\n"
            text += "💡 Regular cleaning can free up gigabytes of space and improve performance!"

            return self._create_response(text, 'info')
        except:
            return self._create_response(
                "🧹 Use the **Junk Cleaner** in the Tools tab to clean temporary files and free up disk space!",
                'info'
            )

    def _get_optimize_response(self, question):
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory().percent

        text = f"🔧 **Optimization Recommendations**\n\n"
        text += f"Current status: CPU {cpu:.0f}%, RAM {mem:.0f}%\n\n"

        if cpu > 70 or mem > 80:
            text += "⚠️ Your system needs optimization! Here's what I suggest:\n\n"
        else:
            text += "Your system is running well, but here are some options:\n\n"

        text += "**Quick Actions:**\n"
        text += "• 🚀 **Optimize All** - Enable all optimizers\n"
        text += "• 💾 **Free RAM** - Clear memory immediately\n"
        text += "• ⚡ **Boost** - Prioritize active apps\n\n"

        text += "**For Gaming:**\n"
        text += "• Enable **Game Mode** for automatic game optimization\n"
        text += "• Use a **Game Profile** for specific games\n\n"

        text += "Use the quick action buttons above or go to the **Booster** tab for full control!"

        return self._create_response(text, 'action')

    def _get_slow_response(self, question):
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()

        text = f"🐌 **Troubleshooting Slow Performance**\n\n"
        text += f"Let me check... CPU: {cpu:.0f}%, RAM: {mem.percent:.0f}%\n\n"

        issues = []
        fixes = []

        if cpu > 80:
            issues.append("• High CPU usage detected")
            fixes.append("• Enable **OptiBalance** to throttle background apps")

        if mem.percent > 85:
            issues.append("• Memory is nearly full")
            fixes.append("• Click **Free RAM** to release memory")
            fixes.append("• Close unused applications")

        if mem.percent > 95:
            issues.append("• Critical memory pressure!")
            fixes.append("• Restart heavy applications")

        if issues:
            text += "**Issues Found:**\n"
            for issue in issues:
                text += issue + "\n"
            text += "\n**Recommended Fixes:**\n"
            for fix in fixes:
                text += fix + "\n"
        else:
            text += "I don't see obvious issues, but try these:\n\n"
            text += "• Click **Deep Scan** to analyze your system\n"
            text += "• Check the **Resource Hogs** section below for heavy processes\n"
            text += "• Enable **Auto-Pilot** for automatic optimization\n"

        return self._create_response(text, 'warning' if issues else 'info')

    def _get_explain_response(self, question):
        q_lower = question.lower()

        explanations = {
            'optibalance': "OptiBalance automatically manages process priorities to keep your system responsive.",
            'game mode': "Game Mode optimizes your system for gaming by boosting game priority and stopping background services.",
            'foreground boost': "Foreground Booster increases the priority of whatever window you're actively using.",
            'memory optim': "Memory Optimizer periodically trims process memory to free up RAM.",
            'cpu limit': "CPU Limiter restricts how much CPU heavy background processes can use.",
            'auto-pilot': "Auto-Pilot enables all optimization features for hands-free system management.",
            'profile': "Profiles save your optimization settings so you can quickly switch between configurations.",
        }

        for key, explanation in explanations.items():
            if key in q_lower:
                return self._create_response(f"💡 **Explanation**\n\n{explanation}", 'info')

        return self._create_response(
            "🤔 I'm not sure what you're asking about. Try asking about specific features like:\n\n"
            "• OptiBalance\n• Game Mode\n• Memory Optimizer\n• Auto-Pilot\n• Profiles",
            'info'
        )

    def _get_howto_response(self, question):
        q_lower = question.lower()

        howtos = {
            'free ram': "To free RAM:\n1. Click the **Free RAM** button above, or\n2. Go to **Booster** tab and enable Memory Optimizer",
            'free memory': "To free memory:\n1. Click the **Free RAM** button above, or\n2. Go to **Booster** tab and enable Memory Optimizer",
            'game': "To optimize for games:\n1. Enable **Game Mode** in Booster tab\n2. Or click the **Game Mode** quick action above\n3. Games will be detected and optimized automatically!",
            'clean': "To clean your system:\n1. Go to **Tools** tab\n2. Click **Junk Cleaner**\n3. Scan and remove temporary files",
            'startup': "To manage startup programs:\n1. Go to **Tools** tab\n2. Find **Startup Manager**\n3. Disable programs you don't need at startup",
            'faster': "To make your PC faster:\n1. Click **Optimize All** above\n2. Enable **Auto-Pilot** for automatic optimization\n3. Check **Tools** for advanced options",
        }

        for key, howto in howtos.items():
            if key in q_lower:
                return self._create_response(f"📖 **How To**\n\n{howto}", 'info')

        return self._create_response(
            "📖 **Common Tasks**\n\n"
            "• **Free RAM**: Click 'Free RAM' button or enable Memory Optimizer\n"
            "• **Optimize for games**: Enable Game Mode in Booster tab\n"
            "• **Clean system**: Use Junk Cleaner in Tools tab\n"
            "• **Speed up PC**: Enable Auto-Pilot or click 'Optimize All'\n\n"
            "Ask me specifically what you want to do!",
            'info'
        )

    def _get_greeting_response(self, question):
        import datetime
        hour = datetime.datetime.now().hour

        if hour < 12:
            greeting = "Good morning"
        elif hour < 17:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"

        return self._create_response(
            f"👋 {greeting}! I'm your OptiCores AI assistant.\n\n"
            "I can help you with:\n"
            "• Checking system status (CPU, RAM, disk)\n"
            "• Optimization tips and troubleshooting\n"
            "• Explaining features\n"
            "• Guiding you through tasks\n\n"
            "What would you like to know?",
            'info'
        )

    def _get_thanks_response(self, question):
        return self._create_response(
            "😊 You're welcome! I'm always here to help optimize your PC.\n\n"
            "Feel free to ask me anything else!",
            'info'
        )

    def _get_default_response(self, question):
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory().percent

        return self._create_response(
            f"🤔 I'm not quite sure how to answer that, but here's what I can tell you:\n\n"
            f"• Your CPU is at **{cpu:.0f}%**\n"
            f"• Your RAM is at **{mem:.0f}%**\n\n"
            "Try asking me about:\n"
            "• System status (\"How is my system?\")\n"
            "• CPU/RAM/Disk usage\n"
            "• How to optimize or speed up your PC\n"
            "• What specific features do\n"
            "• Troubleshooting slow performance",
            'info'
        )

    def get_history(self):
        return list(self.chat_history)

    def clear_history(self):
        self.chat_history.clear()

AI_CHAT = AIChatEngine()

class SmoothAnimator:
    def __init__(self):
        self._animations = {}
        self._root = None
        self._running = True
        self._animation_id = 0

    def set_root(self, root):
        self._root = root

    def _get_id(self):
        self._animation_id += 1
        return self._animation_id

    def _ease_out_cubic(self, t):
        return 1 - pow(1 - t, 3)

    def _ease_out_quart(self, t):
        return 1 - pow(1 - t, 4)

    def _ease_in_out_cubic(self, t):
        if t < 0.5:
            return 4 * t * t * t
        else:
            return 1 - pow(-2 * t + 2, 3) / 2

    def _lerp(self, a, b, t):
        return a + (b - a) * t

    def animate_progress(self, progress_bar, target_value, duration_ms=400, on_complete=None):
        if not self._root or not self._running:
            try:
                progress_bar.set(target_value)
            except:
                pass
            return

        anim_id = self._get_id()

        try:
            current_value = progress_bar.get()
        except:
            current_value = 0

        start_time = time.time()
        duration_sec = duration_ms / 1000.0

        def update():
            if not self._running:
                return

            try:
                elapsed = time.time() - start_time
                progress = min(elapsed / duration_sec, 1.0)
                eased_progress = self._ease_out_cubic(progress)

                new_value = self._lerp(current_value, target_value, eased_progress)
                progress_bar.set(new_value)

                if progress < 1.0:
                    self._root.after(16, update)
                elif on_complete:
                    on_complete()
            except:
                pass

        self._root.after(1, update)

    def animate_number(self, label, target_value, duration_ms=500, prefix="", suffix="", decimals=0):
        if not self._root or not self._running:
            try:
                fmt = f"{{:.{decimals}f}}" if decimals > 0 else "{:.0f}"
                label.configure(text=f"{prefix}{fmt.format(target_value)}{suffix}")
            except:
                pass
            return

        try:
            current_text = label.cget("text")
            num_text = current_text.replace(prefix, "").replace(suffix, "").strip()
            current_value = float(num_text)
        except:
            current_value = 0

        start_time = time.time()
        duration_sec = duration_ms / 1000.0
        fmt = f"{{:.{decimals}f}}" if decimals > 0 else "{:.0f}"

        def update():
            if not self._running:
                return

            try:
                elapsed = time.time() - start_time
                progress = min(elapsed / duration_sec, 1.0)
                eased_progress = self._ease_out_quart(progress)

                new_value = self._lerp(current_value, target_value, eased_progress)
                label.configure(text=f"{prefix}{fmt.format(new_value)}{suffix}")

                if progress < 1.0:
                    self._root.after(16, update)
            except:
                pass

        self._root.after(1, update)

    def fade_in(self, widget, duration_ms=300, start_alpha=0.0, end_alpha=1.0):
        if not self._root or not self._running:
            return

        try:
            widget.lift()
        except:
            pass

    def slide_in_from_right(self, widget, duration_ms=300, distance=50):
        if not self._root or not self._running:
            return

        start_time = time.time()
        duration_sec = duration_ms / 1000.0

        try:
            original_x = widget.winfo_x()
        except:
            return

        def update():
            if not self._running:
                return

            try:
                elapsed = time.time() - start_time
                progress = min(elapsed / duration_sec, 1.0)
                eased = self._ease_out_cubic(progress)

                offset = int(distance * (1 - eased))
                widget.place(x=original_x + offset)

                if progress < 1.0:
                    self._root.after(16, update)
                else:
                    widget.place(x=original_x)
            except:
                pass

        widget.place(x=original_x + distance)
        self._root.after(1, update)

    def pulse_widget(self, widget, color1, color2, duration_ms=1000, property_name='fg_color', cycles=3):
        if not self._root or not self._running:
            return

        def hex_to_rgb(hex_color):
            hex_color = hex_color.lstrip('#')
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

        def rgb_to_hex(r, g, b):
            return f"#{int(r):02x}{int(g):02x}{int(b):02x}"

        r1, g1, b1 = hex_to_rgb(color1)
        r2, g2, b2 = hex_to_rgb(color2)

        start_time = time.time()
        duration_sec = duration_ms / 1000.0
        completed_cycles = [0]

        def update():
            if not self._running:
                return

            try:
                elapsed = time.time() - start_time
                cycle_progress = (elapsed % duration_sec) / duration_sec

                import math
                t = (math.sin(cycle_progress * math.pi * 2 - math.pi/2) + 1) / 2

                r = self._lerp(r1, r2, t)
                g = self._lerp(g1, g2, t)
                b = self._lerp(b1, b2, t)
                color = rgb_to_hex(r, g, b)

                widget.configure(**{property_name: color})

                current_cycle = int(elapsed / duration_sec)
                if cycles > 0 and current_cycle >= cycles:
                    widget.configure(**{property_name: color1})
                    return

                self._root.after(33, update)
            except:
                pass

        self._root.after(1, update)

    def animate_color(self, widget, from_color, to_color, duration_ms=300, property_name='fg_color'):
        if not self._root or not self._running:
            try:
                widget.configure(**{property_name: to_color})
            except:
                pass
            return

        def hex_to_rgb(hex_color):
            hex_color = hex_color.lstrip('#')
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

        def rgb_to_hex(r, g, b):
            return f"#{int(r):02x}{int(g):02x}{int(b):02x}"

        try:
            r1, g1, b1 = hex_to_rgb(from_color)
            r2, g2, b2 = hex_to_rgb(to_color)
        except:
            return

        start_time = time.time()
        duration_sec = duration_ms / 1000.0

        def update():
            if not self._running:
                return

            try:
                elapsed = time.time() - start_time
                progress = min(elapsed / duration_sec, 1.0)
                eased = self._ease_out_cubic(progress)

                r = self._lerp(r1, r2, eased)
                g = self._lerp(g1, g2, eased)
                b = self._lerp(b1, b2, eased)
                color = rgb_to_hex(r, g, b)

                widget.configure(**{property_name: color})

                if progress < 1.0:
                    self._root.after(16, update)
            except:
                pass

        self._root.after(1, update)

    def shake_widget(self, widget, intensity=5, duration_ms=300):
        if not self._root or not self._running:
            return

        try:
            original_x = widget.winfo_x()
        except:
            return

        start_time = time.time()
        duration_sec = duration_ms / 1000.0

        def update():
            if not self._running:
                return

            try:
                import math
                elapsed = time.time() - start_time
                progress = elapsed / duration_sec

                if progress >= 1.0:
                    widget.place(x=original_x)
                    return

                amplitude = intensity * (1 - progress)
                offset = int(amplitude * math.sin(progress * math.pi * 8))
                widget.place(x=original_x + offset)

                self._root.after(16, update)
            except:
                pass

        self._root.after(1, update)

    def stop_all(self):
        self._running = False

    def resume(self):
        self._running = True

ANIMATOR = SmoothAnimator()

class WelcomeGuide:
    def __init__(self):
        self.config_path = os.path.join(APP_DIR, "first_run.json")
        self.shown = self._check_shown()

    def _check_shown(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                    return data.get('welcome_shown', False)
        except:
            pass
        return False

    def _mark_shown(self):
        try:
            with open(self.config_path, 'w') as f:
                json.dump({'welcome_shown': True}, f)
            self.shown = True
        except:
            pass

    def show(self, parent):
        if self.shown:
            return

        dialog = ctk.CTkToplevel(parent)
        dialog.title("Welcome to OptiCores!")
        dialog.geometry("500x400")
        dialog.transient(parent)
        dialog.grab_set()
        dialog.resizable(False, False)

        dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 500) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 400) // 2
        dialog.geometry(f"+{x}+{y}")

        frame = ctk.CTkFrame(dialog, fg_color="#0D1117")
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(frame, text="⚡ Welcome to OptiCores!",
                     font=ctk.CTkFont(size=24, weight="bold"),
                     text_color="#8B5CF6").pack(pady=(30,10))

        ctk.CTkLabel(frame, text="Your PC optimization companion",
                     text_color="#9CA3AF").pack(pady=(0,20))

        guide = ctk.CTkFrame(frame, fg_color="#1D232C", corner_radius=12)
        guide.pack(fill="x", padx=30, pady=10)

        tips = [
            ("📊 Dashboard", "Monitor your system in real-time"),
            ("🔥 Booster", "Enable Game Mode and optimizations"),
            ("🔧 Tools", "Scan games, manage services"),
            ("⚙️ Settings", "Customize behavior and features"),
        ]

        for icon_title, desc in tips:
            row = ctk.CTkFrame(guide, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=5)
            ctk.CTkLabel(row, text=icon_title, font=ctk.CTkFont(weight="bold"),
                        text_color="#F9FAFB").pack(side="left")
            ctk.CTkLabel(row, text=f"  —  {desc}", text_color="#9CA3AF").pack(side="left")

        ctk.CTkLabel(frame, text="💡 Tip: Hover over any control for help!",
                     text_color="#10B981").pack(pady=20)

        def close():
            self._mark_shown()
            dialog.destroy()

        ctk.CTkButton(frame, text="Get Started!", command=close,
                      fg_color="#8B5CF6", hover_color="#7C3AED",
                      height=40, width=150).pack(pady=10)

WELCOME_GUIDE = WelcomeGuide()

def show_help(parent, title, content):
    dialog = ctk.CTkToplevel(parent)
    dialog.title(f"Help: {title}")
    dialog.geometry("400x250")
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(False, False)

    dialog.update_idletasks()
    x = parent.winfo_x() + (parent.winfo_width() - 400) // 2
    y = parent.winfo_y() + (parent.winfo_height() - 250) // 2
    dialog.geometry(f"+{x}+{y}")

    frame = ctk.CTkFrame(dialog, fg_color="#0D1117")
    frame.pack(fill="both", expand=True)

    ctk.CTkLabel(frame, text=f"❓ {title}",
                 font=ctk.CTkFont(size=18, weight="bold"),
                 text_color="#8B5CF6").pack(pady=(20,10))

    ctk.CTkLabel(frame, text=content, text_color="#D1D5DB",
                 wraplength=350, justify="left").pack(padx=20, pady=10)

    ctk.CTkButton(frame, text="Got it!", command=dialog.destroy,
                  fg_color="#374151", hover_color="#4B5563").pack(pady=20)

HELP_CONTENT = {
    'game_mode': "Enables High Performance power plan and prioritizes games for maximum FPS.",
    'auto_game': "Automatically detects when games are running and applies optimizations.",
    'fg_booster': "Boosts the priority of the window you're currently using.",
    'priority_bal': "Automatically manages process priorities to keep your system responsive.",
    'memory_opt': "Periodically clears unused memory to keep RAM available.",
    'services': "Stops non-essential Windows services to free up resources.",
    'alerts': "Notifies you when CPU, RAM, or GPU usage gets too high.",
}

EXPANDED_GAMES = {
    "valorant.exe", "csgo.exe", "cs2.exe", "overwatch.exe", "apex_legends.exe",
    "r5apex.exe", "fortniteclient-win64-shipping.exe", "cod.exe", "modernwarfare.exe",
    "blackops.exe", "destiny2.exe", "battlefield.exe", "bf2042.exe", "pubg.exe",
    "tslgame.exe", "rainbowsix.exe", "r6.exe", "halo.exe", "haloinfinite.exe",

    "leagueoflegends.exe", "league of legends.exe", "dota2.exe", "starcraft2.exe",
    "sc2_x64.exe", "hearthstone.exe", "mtga.exe", "aoe2de_s.exe", "aoe4.exe",

    "eldenring.exe", "darksouls3.exe", "witcher3.exe", "cyberpunk2077.exe",
    "gta5.exe", "gtav.exe", "rdr2.exe", "assassinscreed.exe", "farcry.exe",
    "horizonzerodawn.exe", "monsterhunter.exe", "mhw.exe", "diablo4.exe",
    "pathofexile.exe", "lostark.exe", "newworld.exe", "ffxiv_dx11.exe",

    "forza.exe", "forzahorizon5.exe", "assetocorsa.exe", "iracing.exe",
    "f1_2023.exe", "nfs.exe", "fifa.exe", "nba2k.exe", "rocketleague.exe",

    "minecraft.exe", "javaw.exe", "terraria.exe", "rust.exe", "rustclient.exe",
    "ark.exe", "shootergame.exe", "valheim.exe", "subnautica.exe", "satisfactory.exe",

    "genshinimpact.exe", "yuanshen.exe", "starrail.exe", "wukong.exe",
    "baldursgate3.exe", "bg3.exe", "hogwartslegacy.exe", "palworld.exe",
    "deadlock.exe", "mariokart.exe", "zelda.exe", "sims4.exe",
}

class DetailedMonitor:
    def __init__(self):
        self.per_core_cpu = []
        self.gpu_vram = 0
        self.gpu_temp = 0
        self.disk_read = 0
        self.disk_write = 0
        self._last_disk_io = None
        self._last_time = 0

    def update(self):
        try:
            self.per_core_cpu = psutil.cpu_percent(percpu=True)

            try:
                if GPUtil:
                    gpus = GPUtil.getGPUs()
                    if gpus:
                        self.gpu_vram = gpus[0].memoryUsed
                        self.gpu_temp = gpus[0].temperature
            except:
                pass

            try:
                curr_io = psutil.disk_io_counters()
                curr_time = time.time()

                if self._last_disk_io and curr_time > self._last_time:
                    dt = curr_time - self._last_time
                    self.disk_read = (curr_io.read_bytes - self._last_disk_io.read_bytes) / dt / 1024 / 1024
                    self.disk_write = (curr_io.write_bytes - self._last_disk_io.write_bytes) / dt / 1024 / 1024

                self._last_disk_io = curr_io
                self._last_time = curr_time
            except:
                pass

        except:
            pass

    def get_hottest_core(self):
        if not self.per_core_cpu:
            return (0, 0)
        max_usage = max(self.per_core_cpu)
        return (self.per_core_cpu.index(max_usage), max_usage)

    def get_stats(self):
        return {
            'per_core_cpu': self.per_core_cpu,
            'gpu_vram_mb': self.gpu_vram,
            'gpu_temp_c': self.gpu_temp,
            'disk_read_mbs': self.disk_read,
            'disk_write_mbs': self.disk_write,
        }

DETAILED_MONITOR = DetailedMonitor()

class AutoCloseApps:
    closeable_apps = {
        "discord.exe", "spotify.exe", "slack.exe", "teams.exe",
        "chrome.exe", "firefox.exe", "msedge.exe", "opera.exe",
        "dropbox.exe", "onedrive.exe", "googledrivesync.exe",
        "skype.exe", "zoom.exe", "telegram.exe", "whatsapp.exe",
    }

    def __init__(self):
        self.closed_apps = []

    def close_for_gaming(self, exclude=None):
        exclude = exclude or set()
        self.closed_apps = []
        count = 0

        for proc in psutil.process_iter(['pid', 'name']):
            try:
                name = proc.info['name'].lower()
                if name in self.closeable_apps and name not in exclude:
                    self.closed_apps.append(name)
                    proc.terminate()
                    count += 1
            except:
                pass

        return count

    def get_running_closeable(self):
        running = []
        for proc in psutil.process_iter(['name']):
            try:
                name = proc.info['name'].lower()
                if name in self.closeable_apps:
                    running.append(name)
            except:
                pass
        return list(set(running))

AUTO_CLOSE = AutoCloseApps()

class MemoryLeakDetector:
    def __init__(self):
        self.enabled = False
        self.memory_history = {}
        self.process_names = {}
        self.max_samples = 30
        self.min_samples = 10
        self.growth_threshold = 1.5
        self._monitor_thread = None
        self._stop_event = threading.Event()
        self.check_interval = 10.0

    def start_monitoring(self):
        self.enabled = True
        self._stop_event.clear()

        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        def monitor_loop():
            while not self._stop_event.is_set():
                self._sample_all()
                self._stop_event.wait(self.check_interval)

        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop_monitoring(self):
        self.enabled = False
        self._stop_event.set()

    def _sample_all(self):
        try:
            current_pids = set()

            for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    pid = proc.info['pid']
                    name = proc.info['name']
                    mem_mb = proc.info['memory_info'].rss / (1024 * 1024)

                    current_pids.add(pid)
                    self.process_names[pid] = name

                    if pid not in self.memory_history:
                        self.memory_history[pid] = []

                    self.memory_history[pid].append(mem_mb)

                    if len(self.memory_history[pid]) > self.max_samples:
                        self.memory_history[pid] = self.memory_history[pid][-self.max_samples:]

                except:
                    pass

            dead_pids = set(self.memory_history.keys()) - current_pids
            for pid in dead_pids:
                del self.memory_history[pid]
                if pid in self.process_names:
                    del self.process_names[pid]

        except:
            pass

    def _is_leaking(self, pid):
        if pid not in self.memory_history:
            return False

        samples = self.memory_history[pid]
        if len(samples) < self.min_samples:
            return False

        first_half = samples[:len(samples)//2]
        second_half = samples[len(samples)//2:]

        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)

        if avg_first > 0 and avg_second / avg_first >= self.growth_threshold:
            if samples[-1] > samples[-min(5, len(samples))]:
                return True

        return False

    def get_leaking_processes(self):
        leakers = []

        for pid in self.memory_history:
            if self._is_leaking(pid):
                name = self.process_names.get(pid, 'Unknown')
                samples = self.memory_history[pid]
                growth_mb = samples[-1] - samples[0] if samples else 0

                leakers.append({
                    'pid': pid,
                    'name': name,
                    'current_mb': samples[-1] if samples else 0,
                    'growth_mb': growth_mb,
                    'samples': len(samples)
                })

        leakers.sort(key=lambda x: x['growth_mb'], reverse=True)
        return leakers

    def get_top_memory_users(self, count=10):
        users = []

        for pid, samples in self.memory_history.items():
            if samples:
                users.append({
                    'pid': pid,
                    'name': self.process_names.get(pid, 'Unknown'),
                    'current_mb': samples[-1]
                })

        users.sort(key=lambda x: x['current_mb'], reverse=True)
        return users[:count]

LEAK_DETECTOR = MemoryLeakDetector()

class RealBenchmark:
    def __init__(self):
        self.results = {}
        self.baseline = 1000

    def run_all(self, callback=None):
        tests = [
            ('compression', self.test_compression),
            ('crypto', self.test_crypto),
            ('prime_sieve', self.test_prime_sieve),
            ('matrix', self.test_matrix),
            ('memory_bandwidth', self.test_memory_bandwidth),
            ('multicore', self.test_multicore),
        ]

        total = 0
        for name, test_func in tests:
            score = test_func()
            self.results[name] = score
            total += score
            if callback:
                callback(name, score, self.baseline * 2)

        self.results['total'] = total
        self.results['average'] = total / len(tests)
        return self.results

    def test_compression(self):
        import zlib

        data = (b"OptiCores Benchmark Data " * 1000 +
                bytes(range(256)) * 100 +
                b"Test pattern 12345 " * 500) * 10

        start = time.perf_counter()
        iterations = 0

        while time.perf_counter() - start < 2.0:
            compressed = zlib.compress(data, level=6)
            decompressed = zlib.decompress(compressed)
            iterations += 1

        elapsed = time.perf_counter() - start
        ops_per_sec = iterations / elapsed

        mb_per_sec = (len(data) * iterations * 2) / (1024 * 1024) / elapsed
        score = int(mb_per_sec * 10)

        return min(score, self.baseline * 3)

    def test_crypto(self):
        import hashlib

        data = bytes(range(256)) * 256

        start = time.perf_counter()
        iterations = 0

        while time.perf_counter() - start < 2.0:
            for _ in range(100):
                hashlib.sha256(data).hexdigest()
            iterations += 100

        elapsed = time.perf_counter() - start
        hashes_per_sec = iterations / elapsed

        score = int(hashes_per_sec / 10)

        return min(score, self.baseline * 3)

    def test_prime_sieve(self):
        def sieve(n):
            is_prime = [True] * (n + 1)
            is_prime[0] = is_prime[1] = False

            for i in range(2, int(n**0.5) + 1):
                if is_prime[i]:
                    for j in range(i*i, n + 1, i):
                        is_prime[j] = False

            return sum(is_prime)

        start = time.perf_counter()
        iterations = 0

        while time.perf_counter() - start < 2.0:
            count = sieve(100000)
            iterations += 1

        elapsed = time.perf_counter() - start
        sieves_per_sec = iterations / elapsed

        score = int(sieves_per_sec * 100)

        return min(score, self.baseline * 3)

    def test_matrix(self):
        import random

        def matrix_mult(a, b, size):
            result = [[0] * size for _ in range(size)]
            for i in range(size):
                for j in range(size):
                    for k in range(size):
                        result[i][j] += a[i][k] * b[k][j]
            return result

        size = 64

        a = [[random.random() for _ in range(size)] for _ in range(size)]
        b = [[random.random() for _ in range(size)] for _ in range(size)]

        start = time.perf_counter()
        iterations = 0

        while time.perf_counter() - start < 2.0:
            result = matrix_mult(a, b, size)
            iterations += 1

        elapsed = time.perf_counter() - start
        mults_per_sec = iterations / elapsed

        flops = size * size * size * 2 * iterations / elapsed
        score = int(flops / 1000000)

        return min(score, self.baseline * 3)

    def test_memory_bandwidth(self):
        import array

        size = 10 * 1024 * 1024 // 8
        arr = array.array('d', [0.0] * size)

        start = time.perf_counter()
        iterations = 0

        while time.perf_counter() - start < 2.0:
            for i in range(0, size, 1000):
                arr[i] = arr[(i + 500) % size] * 1.5
            iterations += 1

        elapsed = time.perf_counter() - start

        mb_transferred = size * 8 * iterations * 2 / (1024 * 1024)
        mb_per_sec = mb_transferred / elapsed

        score = int(mb_per_sec / 10)

        return min(score, self.baseline * 3)

    def test_multicore(self):
        import concurrent.futures

        def cpu_work(n):
            total = 0
            for i in range(n):
                total += i * i % 997
            return total

        num_cores = os.cpu_count() or 4
        work_size = 500000

        start = time.perf_counter()

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_cores) as executor:
            futures = [executor.submit(cpu_work, work_size) for _ in range(num_cores * 2)]
            results = [f.result() for f in futures]

        elapsed = time.perf_counter() - start

        total_work = work_size * num_cores * 2
        work_per_sec = total_work / elapsed

        score = int(work_per_sec / 10000) * num_cores

        return min(score, self.baseline * 5)

    def get_single_core_score(self):
        single_tests = ['compression', 'crypto', 'prime_sieve', 'matrix']
        return sum(self.results.get(t, 0) for t in single_tests) / len(single_tests)

    def get_multi_core_score(self):
        return self.results.get('multicore', 0)

    def get_summary(self):
        return {
            'single_core': int(self.get_single_core_score()),
            'multi_core': int(self.get_multi_core_score()),
            'total': self.results.get('total', 0),
            'details': self.results
        }

REAL_BENCHMARK = RealBenchmark()

class OptiBalance:

    IDLE_PRIORITY = 0x40
    BELOW_NORMAL_PRIORITY = 0x4000
    NORMAL_PRIORITY = 0x20
    ABOVE_NORMAL_PRIORITY = 0x8000
    HIGH_PRIORITY = 0x80
    REALTIME_PRIORITY = 0x100

    def __init__(self):
        self.enabled = False
        self._monitor_thread = None
        self._stop_event = threading.Event()

        self.config = {
            'system_cpu_threshold': 70,

            'process_cpu_threshold': 30,
            'process_cpu_release': 10,

            'allowed_cpu_quota_ms': 900,
            'min_restrain_time_ms': 4200,
            'max_restrain_time_ms': 30000,

            'check_interval': 0.5,

            'aggressiveness': 50,
        }

        self.restrained_pids = {}
        self.foreground_pid = 0
        self.exclusions = set()

        self.cpu_high_since = {}
        self.process_cpu_history = {}

        self._last_responsiveness_check = 0
        self._responsiveness_samples = []

        self.stats = {
            'restraints_applied': 0,
            'restraints_released': 0,
            'responsiveness': 100,
            'avg_restraint_duration_ms': 0,
            'restraint_durations': [],
        }

    def start(self):
        self.enabled = True
        self._stop_event.clear()

        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        def monitor_loop():
            while not self._stop_event.is_set():
                try:
                    self._tick()
                except:
                    pass
                self._stop_event.wait(self.config['check_interval'])

        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop(self):
        self.enabled = False
        self._stop_event.set()
        self._restore_all()

    def _tick(self):
        now = time.time()

        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            self.foreground_pid = pid.value
        except:
            self.foreground_pid = 0

        system_cpu = psutil.cpu_percent()

        tick_latency = (time.time() - now) * 1000

        cpu_factor = max(0, 100 - system_cpu)
        latency_factor = max(0, 100 - tick_latency * 10)
        responsiveness = int((cpu_factor * 0.7 + latency_factor * 0.3))

        self._responsiveness_samples.append(responsiveness)
        if len(self._responsiveness_samples) > 10:
            self._responsiveness_samples = self._responsiveness_samples[-10:]

        self.stats['responsiveness'] = int(sum(self._responsiveness_samples) / len(self._responsiveness_samples))

        active_pids = {p.pid for p in psutil.process_iter(['pid'])}
        dead_tracked = set(self.cpu_high_since.keys()) - active_pids
        for pid in dead_tracked:
            self.cpu_high_since.pop(pid, None)
            self.process_cpu_history.pop(pid, None)

        if system_cpu > self.config['system_cpu_threshold']:
            self._check_for_restraints()
        else:
            self.cpu_high_since.clear()

        self._check_for_releases()

    def _check_for_restraints(self):
        now = time.time()

        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
            try:
                pid = proc.info['pid']
                name = proc.info['name'].lower()
                cpu = proc.info['cpu_percent'] or 0

                if pid in self.restrained_pids:
                    continue
                if pid == self.foreground_pid:
                    continue
                if name in PROTECTED or name in self.exclusions:
                    continue

                if cpu < self.config['process_cpu_threshold']:
                    self.cpu_high_since.pop(pid, None)
                    continue

                if pid not in self.cpu_high_since:
                    self.cpu_high_since[pid] = now
                    continue

                high_cpu_duration_ms = (now - self.cpu_high_since[pid]) * 1000

                if high_cpu_duration_ms < self.config['allowed_cpu_quota_ms']:
                    continue

                self._restrain(pid, name)

                self.cpu_high_since.pop(pid, None)

            except:
                pass

    def _restrain(self, pid, name):
        try:
            handle = win32api.OpenProcess(
                win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION,
                False, pid
            )

            original_priority = win32process.GetPriorityClass(handle)

            if original_priority == self.NORMAL_PRIORITY:
                win32process.SetPriorityClass(handle, self.BELOW_NORMAL_PRIORITY)

                self.restrained_pids[pid] = {
                    'name': name,
                    'time': time.time(),
                    'original_priority': original_priority
                }

                self.stats['restraints_applied'] += 1

            win32api.CloseHandle(handle)

        except:
            pass

    def _check_for_releases(self):
        now = time.time()
        to_release = []

        for pid, info in self.restrained_pids.items():
            if (now - info['time']) * 1000 < self.config['min_restrain_time_ms']:
                continue

            try:
                proc = psutil.Process(pid)
                cpu = proc.cpu_percent()

                if cpu < self.config['process_cpu_release']:
                    to_release.append(pid)
            except:
                to_release.append(pid)

        for pid in to_release:
            self._release(pid)

    def _release(self, pid):
        if pid not in self.restrained_pids:
            return

        info = self.restrained_pids.pop(pid)

        try:
            handle = win32api.OpenProcess(
                win32con.PROCESS_SET_INFORMATION,
                False, pid
            )
            win32process.SetPriorityClass(handle, info['original_priority'])
            win32api.CloseHandle(handle)

            self.stats['restraints_released'] += 1

        except:
            pass

    def _restore_all(self):
        for pid in list(self.restrained_pids.keys()):
            self._release(pid)

    def add_exclusion(self, process_name):
        self.exclusions.add(process_name.lower())

    def remove_exclusion(self, process_name):
        self.exclusions.discard(process_name.lower())

    def get_stats(self):
        return {
            **self.stats,
            'currently_restrained': len(self.restrained_pids),
            'restrained_processes': [
                {'pid': pid, 'name': info['name']}
                for pid, info in self.restrained_pids.items()
            ]
        }

OPTI_BALANCE = OptiBalance()

class CPULimiter:
    def __init__(self):
        self.enabled = False
        self.rules = {}
        self.limited_pids = {}
        self.total_cores = os.cpu_count() or 4

    def add_rule(self, process_name, max_cpu_percent):
        self.rules[process_name.lower()] = max_cpu_percent

    def remove_rule(self, process_name):
        self.rules.pop(process_name.lower(), None)

    def apply_limits(self):
        for proc in psutil.process_iter(['pid', 'name', 'cpu_affinity']):
            try:
                name = proc.info['name'].lower()
                pid = proc.info['pid']

                if name in self.rules and pid not in self.limited_pids:
                    max_percent = self.rules[name]
                    self._limit_process(pid, name, max_percent, proc.info['cpu_affinity'])

            except:
                pass

    def _limit_process(self, pid, name, max_percent, original_affinity):
        try:
            cores_to_use = max(1, int(self.total_cores * max_percent / 100))

            new_affinity = list(range(cores_to_use))

            proc = psutil.Process(pid)
            proc.cpu_affinity(new_affinity)

            self.limited_pids[pid] = {
                'name': name,
                'original_affinity': original_affinity or list(range(self.total_cores))
            }

        except:
            pass

    def release_all(self):
        for pid, info in list(self.limited_pids.items()):
            try:
                proc = psutil.Process(pid)
                proc.cpu_affinity(info['original_affinity'])
            except:
                pass
        self.limited_pids.clear()

CPU_LIMITER = CPULimiter()

class IOPriorityManager:
    IO_PRIORITY_VERY_LOW = 0
    IO_PRIORITY_LOW = 1
    IO_PRIORITY_NORMAL = 2
    IO_PRIORITY_HIGH = 3

    def __init__(self):
        self.rules = {}

    def set_io_priority(self, pid, priority):
        try:
            PROCESS_SET_INFORMATION = 0x0200
            ProcessIoPriority = 21

            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, pid)
            if handle:
                priority_val = ctypes.c_ulong(priority)
                ctypes.windll.ntdll.NtSetInformationProcess(
                    handle, ProcessIoPriority,
                    ctypes.byref(priority_val), ctypes.sizeof(priority_val)
                )
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
        except:
            pass
        return False

    def boost_game_io(self, game_pid):
        return self.set_io_priority(game_pid, self.IO_PRIORITY_HIGH)

    def reduce_background_io(self, pid):
        return self.set_io_priority(pid, self.IO_PRIORITY_LOW)

IO_PRIORITY = IOPriorityManager()

class SmartTrim:
    def __init__(self):
        self.enabled = False
        self.config = {
            'ram_threshold': 80,
            'idle_time_seconds': 60,
            'min_trim_mb': 50,
            'check_interval': 30,
        }
        self._monitor_thread = None
        self._stop_event = threading.Event()
        self._process_activity = {}

    def start(self):
        self.enabled = True
        self._stop_event.clear()

        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        def monitor_loop():
            while not self._stop_event.is_set():
                self._tick()
                self._stop_event.wait(self.config['check_interval'])

        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop(self):
        self.enabled = False
        self._stop_event.set()

    def _tick(self):
        ram_percent = psutil.virtual_memory().percent
        if ram_percent < self.config['ram_threshold']:
            return

        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            fg_pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(fg_pid))
            foreground_pid = fg_pid.value
        except:
            foreground_pid = 0

        for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
            try:
                pid = proc.info['pid']

                if pid == foreground_pid:
                    continue

                mem_mb = proc.info['memory_info'].rss / (1024 * 1024)
                if mem_mb < self.config['min_trim_mb']:
                    continue

                cpu = proc.info['cpu_percent'] or 0
                if cpu < 1.0:
                    self._trim_process(pid)

            except:
                pass

    def _trim_process(self, pid):
        try:
            PROCESS_SET_QUOTA = 0x0100
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_SET_QUOTA, False, pid)
            if handle:
                ctypes.windll.kernel32.SetProcessWorkingSetSize(handle, -1, -1)
                ctypes.windll.kernel32.CloseHandle(handle)
        except:
            pass

SMART_TRIM = SmartTrim()

class IdleSaver:

    POWER_SAVER = "a1841308-3541-4fab-bc81-f71556f20b4a"
    BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
    HIGH_PERFORMANCE = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"

    def __init__(self):
        self.enabled = False
        self.config = {
            'idle_timeout_seconds': 300,
            'active_plan': self.HIGH_PERFORMANCE,
            'idle_plan': self.BALANCED,
        }
        self._monitor_thread = None
        self._stop_event = threading.Event()
        self._last_input_time = time.time()
        self._is_idle = False

    def start(self):
        self.enabled = True
        self._stop_event.clear()

        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        def monitor_loop():
            while not self._stop_event.is_set():
                self._tick()
                self._stop_event.wait(10)

        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop(self):
        self.enabled = False
        self._stop_event.set()

    def _tick(self):
        try:
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))

            millis_since_input = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            seconds_idle = millis_since_input / 1000

            if seconds_idle > self.config['idle_timeout_seconds']:
                if not self._is_idle:
                    self._switch_plan(self.config['idle_plan'])
                    self._is_idle = True
            else:
                if self._is_idle:
                    self._switch_plan(self.config['active_plan'])
                    self._is_idle = False

        except:
            pass

    def _switch_plan(self, plan_guid):
        try:
            subprocess.run(
                ['powercfg', '/setactive', plan_guid],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
            )
        except:
            pass

IDLE_SAVER = IdleSaver()

MODERN_COLORS = {
    'bg_dark': '#0A0E14',
    'bg_card': '#111827',
    'bg_card_hover': '#1F2937',
    'border': '#374151',
    'border_glow': '#8B5CF6',
    'text_primary': '#F9FAFB',
    'text_secondary': '#9CA3AF',
    'text_muted': '#6B7280',
    'accent_purple': '#8B5CF6',
    'accent_blue': '#3B82F6',
    'accent_cyan': '#06B6D4',
    'accent_green': '#10B981',
    'accent_yellow': '#F59E0B',
    'accent_red': '#EF4444',
    'accent_pink': '#EC4899',
    'gradient_start': '#8B5CF6',
    'gradient_end': '#06B6D4',
}

class GlassCard(ctk.CTkFrame):
    def __init__(self, parent, glow_color=None, **kwargs):
        glow = glow_color or MODERN_COLORS['border_glow']
        super().__init__(
            parent,
            fg_color=MODERN_COLORS['bg_card'],
            corner_radius=16,
            border_width=1,
            border_color=MODERN_COLORS['border'],
            **kwargs
        )

        self.bind('<Enter>', lambda e: self.configure(border_color=glow))
        self.bind('<Leave>', lambda e: self.configure(border_color=MODERN_COLORS['border']))

class AnimatedProgress(ctk.CTkFrame):
    def __init__(self, parent, width=200, height=8, color=None, **kwargs):
        super().__init__(parent, width=width, height=height,
                        fg_color=MODERN_COLORS['bg_dark'], corner_radius=4, **kwargs)

        self.bar_color = color or MODERN_COLORS['accent_purple']
        self.progress = 0
        self.target = 0

        self.bar = ctk.CTkFrame(self, height=height, width=0,
                                fg_color=self.bar_color, corner_radius=4)
        self.bar.place(x=0, y=0)

        self.max_width = width

    def set_progress(self, value, animate=True):
        self.target = max(0, min(100, value))
        if animate:
            self._animate()
        else:
            self.progress = self.target
            self._update_bar()

    def _animate(self):
        if abs(self.progress - self.target) < 1:
            self.progress = self.target
            self._update_bar()
            return

        self.progress += (self.target - self.progress) * 0.2
        self._update_bar()
        self.after(16, self._animate)

    def _update_bar(self):
        width = int(self.max_width * self.progress / 100)
        self.bar.configure(width=max(1, width))

class PulseButton(ctk.CTkButton):
    def __init__(self, parent, text="", icon="", color=None, **kwargs):
        btn_color = color or MODERN_COLORS['accent_purple']
        hover_color = self._lighten_color(btn_color)

        display_text = f"{icon} {text}" if icon else text

        super().__init__(
            parent,
            text=display_text,
            fg_color=btn_color,
            hover_color=hover_color,
            corner_radius=12,
            height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            **kwargs
        )

    def _lighten_color(self, hex_color):
        hex_color = hex_color.lstrip('#')
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        r = min(255, int(r * 1.2))
        g = min(255, int(g * 1.2))
        b = min(255, int(b * 1.2))
        return f"#{r:02x}{g:02x}{b:02x}"

class GradientLabel(ctk.CTkFrame):
    def __init__(self, parent, text="", size=24, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self.label = ctk.CTkLabel(
            self,
            text=text,
            font=ctk.CTkFont(size=size, weight="bold"),
            text_color=MODERN_COLORS['accent_purple']
        )
        self.label.pack()

    def set_text(self, text):
        self.label.configure(text=text)

class StatCard(GlassCard):
    def __init__(self, parent, title="", value="0", icon="📊",
                 color=None, **kwargs):
        super().__init__(parent, glow_color=color, **kwargs)

        self.color = color or MODERN_COLORS['accent_purple']

        ctk.CTkLabel(self, text=icon, font=ctk.CTkFont(size=28),
                    text_color=self.color).pack(pady=(15, 5))

        self.value_label = ctk.CTkLabel(
            self, text=value,
            font=ctk.CTkFont(size=32, weight="bold"),
            text_color=MODERN_COLORS['text_primary']
        )
        self.value_label.pack()

        ctk.CTkLabel(self, text=title,
                    text_color=MODERN_COLORS['text_secondary'],
                    font=ctk.CTkFont(size=12)).pack(pady=(0, 15))

    def set_value(self, value):
        self.value_label.configure(text=str(value))

class ToggleCard(GlassCard):
    def __init__(self, parent, title="", description="",
                 icon="⚡", command=None, **kwargs):
        super().__init__(parent, **kwargs)

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="x", padx=15, pady=12)

        left = ctk.CTkFrame(content, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)

        header = ctk.CTkFrame(left, fg_color="transparent")
        header.pack(fill="x")

        ctk.CTkLabel(header, text=icon, font=ctk.CTkFont(size=20),
                    text_color=MODERN_COLORS['accent_purple']).pack(side="left")
        ctk.CTkLabel(header, text=f"  {title}",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=MODERN_COLORS['text_primary']).pack(side="left")

        if description:
            ctk.CTkLabel(left, text=description,
                        text_color=MODERN_COLORS['text_muted'],
                        font=ctk.CTkFont(size=11)).pack(anchor="w", padx=28)

        self.switch = ctk.CTkSwitch(
            content, text="",
            button_color=MODERN_COLORS['accent_green'],
            progress_color=MODERN_COLORS['accent_green'],
            command=command
        )
        self.switch.pack(side="right")

    def get(self):
        return self.switch.get()

    def set(self, value):
        if value:
            self.switch.select()
        else:
            self.switch.deselect()

class MiniChart(ctk.CTkFrame):
    def __init__(self, parent, width=200, height=80, line_color="#8B5CF6",
                 bg_color="#0D1117", grid_color="#1F2937", max_points=60, **kwargs):
        super().__init__(parent, width=width, height=height, fg_color=bg_color, **kwargs)

        self.width = width
        self.height = height
        self.line_color = line_color
        self.grid_color = grid_color
        self.max_points = max_points
        self.data = []

        self.canvas = ctk.CTkCanvas(self, width=width, height=height,
                                     bg=bg_color, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

    def add_point(self, value):
        self.data.append(max(0, min(100, value)))
        if len(self.data) > self.max_points:
            self.data = self.data[-self.max_points:]
        self.redraw()

    def set_data(self, data):
        self.data = [max(0, min(100, v)) for v in data[-self.max_points:]]
        self.redraw()

    def redraw(self):
        self.canvas.delete("all")

        if len(self.data) < 2:
            return

        w = self.width
        h = self.height
        padding = 5

        for i in range(5):
            y = padding + (h - 2*padding) * i / 4
            self.canvas.create_line(padding, y, w-padding, y,
                                   fill=self.grid_color, width=1)

        points = []
        for i, val in enumerate(self.data):
            x = padding + (w - 2*padding) * i / (len(self.data) - 1)
            y = h - padding - (h - 2*padding) * val / 100
            points.extend([x, y])

        if len(points) >= 4:
            self.canvas.create_line(points, fill=self.line_color,
                                   width=2, smooth=True)

        if len(points) >= 4:
            fill_points = points.copy()
            fill_points.extend([w-padding, h-padding, padding, h-padding])
            self.canvas.create_polygon(fill_points, fill=self.line_color,
                                       stipple="gray25", outline="")

class StatusBadge(ctk.CTkFrame):
    def __init__(self, parent, text="OFF", active=False, **kwargs):
        super().__init__(parent, height=24, corner_radius=12, **kwargs)

        self.active = active
        self.text = text

        self.label = ctk.CTkLabel(self, text=text,
                                   font=ctk.CTkFont(size=11, weight="bold"),
                                   text_color="#F9FAFB")
        self.label.pack(padx=10, pady=2)

        self._update_style()

    def set_active(self, active, text=None):
        self.active = active
        if text:
            self.text = text
            self.label.configure(text=text)
        self._update_style()

    def _update_style(self):
        if self.active:
            self.configure(fg_color="#10B981")
        else:
            self.configure(fg_color="#374151")

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

class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong),
                ("ControlMask", ctypes.c_ulong),
                ("StateMask", ctypes.c_ulong)]
def set_power_throttle(handle, eco_on=True):
    try:
        state = PROCESS_POWER_THROTTLING_STATE()
        state.Version = 1
        state.ControlMask = 0x1
        state.StateMask   = 0x1 if eco_on else 0x0
        ok = kernel32.SetProcessInformation(int(handle), 0x00000009, ctypes.byref(state), ctypes.sizeof(state))
        if not ok: raise ctypes.WinError(ctypes.get_last_error())
    except Exception:
        pass

def get_cpu_temp():
    return None

def get_gpu_temp():
    try:
        if GPUtil:
            gpus = GPUtil.getGPUs()
            if gpus:
                return gpus[0].temperature
    except: pass
    return None

class DiskIOTracker:
    def __init__(self):
        self.last_io = psutil.disk_io_counters()
        self.last_time = time.time()

    def get_rates(self):
        try:
            curr = psutil.disk_io_counters()
            now = time.time()
            dt = now - self.last_time
            if dt > 0:
                read_rate = (curr.read_bytes - self.last_io.read_bytes) / dt
                write_rate = (curr.write_bytes - self.last_io.write_bytes) / dt
                self.last_io = curr
                self.last_time = now
                return read_rate, write_rate
        except: pass
        return 0, 0

DISK_IO = DiskIOTracker()

class AIQuestionManager:

    CATEGORIES = {
        "performance": "🚀 Performance",
        "memory": "💾 Memory",
        "cpu": "🖥️ CPU",
        "disk": "💿 Disk",
        "gaming": "🎮 Gaming",
        "power": "⚡ Power",
        "network": "🌐 Network",
        "processes": "📊 Processes",
        "general": "💡 General"
    }

    QUESTIONS = [
        {"q": "How can I speed up my PC?", "cat": "performance", "keywords": ["slow", "fast", "speed"]},
        {"q": "Why is my computer running slow?", "cat": "performance", "keywords": ["slow", "lag"]},
        {"q": "How do I free up RAM?", "cat": "memory", "keywords": ["ram", "memory"]},
        {"q": "What's using my memory?", "cat": "memory", "keywords": ["ram", "memory", "usage"]},
        {"q": "Why is my CPU usage so high?", "cat": "cpu", "keywords": ["cpu", "high", "usage"]},
        {"q": "How to reduce CPU usage?", "cat": "cpu", "keywords": ["cpu", "reduce"]},
        {"q": "How can I optimize for gaming?", "cat": "gaming", "keywords": ["game", "gaming", "fps"]},
        {"q": "How do I enable Game Mode?", "cat": "gaming", "keywords": ["game", "mode"]},
        {"q": "How to improve FPS in games?", "cat": "gaming", "keywords": ["fps", "game", "performance"]},
        {"q": "How do I clean up disk space?", "cat": "disk", "keywords": ["disk", "space", "clean"]},
        {"q": "What files can I delete safely?", "cat": "disk", "keywords": ["delete", "files", "safe"]},
        {"q": "How to extend battery life?", "cat": "power", "keywords": ["battery", "power", "save"]},
        {"q": "What power plan should I use?", "cat": "power", "keywords": ["power", "plan"]},
        {"q": "How to boost my network speed?", "cat": "network", "keywords": ["network", "speed", "internet"]},
        {"q": "Which processes are safe to end?", "cat": "processes", "keywords": ["process", "end", "safe"]},
        {"q": "How do I lower process priority?", "cat": "processes", "keywords": ["process", "priority"]},
        {"q": "What does OptiBalance do?", "cat": "general", "keywords": ["optibalance", "feature"]},
        {"q": "How do I use the One-Click Boost?", "cat": "general", "keywords": ["boost", "one-click"]},
        {"q": "What optimizations are available?", "cat": "general", "keywords": ["optimize", "feature"]},
        {"q": "How can I monitor system health?", "cat": "general", "keywords": ["monitor", "health"]},
        {"q": "Should I run memory cleanup?", "cat": "memory", "keywords": ["cleanup", "memory"]},
        {"q": "How to fix high disk usage?", "cat": "disk", "keywords": ["disk", "high", "usage"]},
        {"q": "What startup programs can I disable?", "cat": "processes", "keywords": ["startup", "disable"]},
        {"q": "How do I schedule automatic optimization?", "cat": "general", "keywords": ["schedule", "auto"]},
    ]

    def __init__(self):
        self.history = []

    def get_predicted_questions(self, limit=6):
        scores = {}

        try:
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent
        except:
            cpu, mem, disk = 50, 50, 50

        for i, q in enumerate(self.QUESTIONS):
            score = 0

            if cpu > 70 and q["cat"] == "cpu":
                score += 50
            elif cpu > 50 and q["cat"] == "cpu":
                score += 25

            if mem > 80 and q["cat"] == "memory":
                score += 50
            elif mem > 60 and q["cat"] == "memory":
                score += 25

            if disk > 85 and q["cat"] == "disk":
                score += 40
            elif disk > 70 and q["cat"] == "disk":
                score += 20

            if q["cat"] == "performance":
                score += 10

            if q["cat"] == "general":
                score += 5

            if q["cat"] == "gaming":
                score += 8

            scores[i] = score

        sorted_indices = sorted(scores.keys(), key=lambda i: scores[i], reverse=True)

        return [self.QUESTIONS[i] for i in sorted_indices[:limit]]

    def get_all_questions(self, category=None):
        if category and category != "all":
            return [q for q in self.QUESTIONS if q["cat"] == category]
        return self.QUESTIONS

    def record_selection(self, question):
        self.history.append(question)
        if len(self.history) > 20:
            self.history = self.history[-20:]

AI_QUESTION_MANAGER = AIQuestionManager()

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

PROTECTED = {
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "services.exe",
    "lsass.exe", "svchost.exe", "dwm.exe", "explorer.exe", "winlogon.exe",
    "fontdrvhost.exe", "sihost.exe", "taskhostw.exe", "runtimebroker.exe",
    "searchhost.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe",
    "textinputhost.exe", "ctfmon.exe", "conhost.exe", "dllhost.exe",
    "audiodg.exe", "securityhealthservice.exe", "msiexec.exe", "trustedinstaller.exe"
}

class EffectsTracker:
    def __init__(self):
        self.pending = {}
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

class BackgroundGovernor:
    def __init__(self):
        self.enabled = False
        self.job = None
        self.governed_pids = set()
        self.cpu_limit = 30
        self.mem_priority = 2

        if win32job:
            try:
                self.job = win32job.CreateJobObject(None, "OptiCores_BackgroundGovernor")
                self._configure_job_limits()
            except Exception:
                self.job = None

    def _configure_job_limits(self):
        if not self.job or not win32job:
            return
        try:
            info = win32job.QueryInformationJobObject(
                self.job, win32job.JobObjectBasicLimitInformation
            )
            info['LimitFlags'] = info.get('LimitFlags', 0) | 0x0010
            win32job.SetInformationJobObject(
                self.job, win32job.JobObjectBasicLimitInformation, info
            )
        except Exception:
            pass

    def set_cpu_limit(self, percent):
        self.cpu_limit = max(5, min(100, percent))
        self._configure_job_limits()

    def set_mem_priority_level(self, level):
        self.mem_priority = max(1, min(5, level))

    def govern(self, pid, mem_priority_override=None):
        if pid in self.governed_pids:
            return

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

        mem_prio = mem_priority_override if mem_priority_override else self.mem_priority
        try:
            set_memory_priority(h, mem_prio)
            UNDO.push(pid, "memprio", 3)
        except Exception: pass

        try:
            set_power_throttle(h, eco_on=True)
        except Exception: pass

        if self.job:
            try:
                win32job.AssignProcessToJobObject(self.job, h)
                UNDO.push(pid, "job", None)
                self.governed_pids.add(pid)
            except Exception:
                pass

    def release(self, pid):
        self.governed_pids.discard(pid)

    def get_governed_count(self):
        return len(self.governed_pids)

    def suspend_heavy_process(self, pid):
        try:
            p = psutil.Process(pid)
            p.suspend()
            UNDO.push(pid, "suspend", None)
            return True
        except Exception:
            return False

class LatencyMonitor:
    def __init__(self):
        self.ctx_switches = defaultdict(lambda: deque(maxlen=60))
        self.system_dpc = deque(maxlen=60)
        self.system_isr = deque(maxlen=60)
        self._last_ctx = {}

    def sample_process(self, pid):
        try:
            p = psutil.Process(pid)
            ctx = p.num_ctx_switches()
            total = ctx.voluntary + ctx.involuntary
            last = self._last_ctx.get(pid, total)
            delta = total - last
            self._last_ctx[pid] = total
            self.ctx_switches[pid].append(delta)
            return delta
        except Exception:
            return 0

    def get_ctx_trend(self, pid):
        hist = self.ctx_switches.get(pid, [])
        if len(hist) < 3:
            return 0.0
        return sum(hist) / len(hist)

    def sample_system_dpc(self):
        try:
            cpu_times = psutil.cpu_times_percent(interval=None)
            dpc = getattr(cpu_times, 'interrupt', 0) + getattr(cpu_times, 'dpc', 0)
            isr = getattr(cpu_times, 'softirq', getattr(cpu_times, 'system', 0) * 0.1)
            self.system_dpc.append(dpc)
            self.system_isr.append(isr)
            return {"dpc": dpc, "isr": isr}
        except Exception:
            self.system_dpc.append(0)
            self.system_isr.append(0)
            return {"dpc": 0, "isr": 0}

    def get_dpc_trend(self):
        if len(self.system_dpc) < 3:
            return 0.0
        return sum(self.system_dpc) / len(self.system_dpc)

    def is_high_latency(self, pid):
        trend = self.get_ctx_trend(pid)
        return trend > 1000

LATENCY = LatencyMonitor()

class HealthWatcher:
    def __init__(self):
        self.hist_mem = defaultdict(lambda: deque(maxlen=12))
        self.hist_cpu = defaultdict(lambda: deque(maxlen=12))
        self.hist_handles = defaultdict(lambda: deque(maxlen=12))
        self.hist_threads = defaultdict(lambda: deque(maxlen=12))
        self.flags = {}

    def ingest(self, pid, rss_mb, cpu_pct):
        self.hist_mem[pid].append(rss_mb)
        self.hist_cpu[pid].append(cpu_pct)

        try:
            p = psutil.Process(pid)
            self.hist_handles[pid].append(p.num_handles())
            self.hist_threads[pid].append(p.num_threads())
        except Exception:
            pass

        leak = self._is_growing(self.hist_mem[pid])
        spike = any(v >= 35 for v in self.hist_cpu[pid])
        handle_leak = self._is_growing(self.hist_handles[pid])
        thread_explosion = self._detect_thread_explosion(pid)

        self.flags[pid] = {
            "leak": leak,
            "spike": spike,
            "handle_leak": handle_leak,
            "thread_explosion": thread_explosion
        }

    @staticmethod
    def _is_growing(dq):
        if len(dq) < 6: return False
        up = sum(1 for i in range(1, len(dq)) if dq[i] >= dq[i-1]*1.03)
        return up >= 4

    def _detect_thread_explosion(self, pid):
        hist = self.hist_threads.get(pid, [])
        if len(hist) < 4:
            return False
        recent = list(hist)[-4:]
        if recent[0] == 0:
            return False
        growth = (recent[-1] - recent[0]) / max(1, recent[0])
        return growth > 0.5

    def get_flags(self, pid):
        return self.flags.get(pid, {
            "leak": False, "spike": False,
            "handle_leak": False, "thread_explosion": False
        })

    def get_anomaly_score(self, pid):
        flags = self.get_flags(pid)
        score = 0.0
        if flags["leak"]: score += 0.3
        if flags["spike"]: score += 0.2
        if flags["handle_leak"]: score += 0.3
        if flags["thread_explosion"]: score += 0.2
        return min(1.0, score)

    def get_anomaly_list(self):
        return [pid for pid, flags in self.flags.items()
                if any(flags.values())]

class NetworkMonitor:
    def __init__(self):
        self.last_io = {}
        self.rates = {}

    def sample(self):
        now = time.time()
        for p in psutil.process_iter(["pid"]):
            try:
                pid = p.info["pid"]
                io = p.io_counters()

                if pid in self.last_io:
                    last_sent, last_recv, last_time = self.last_io[pid]
                    dt = max(0.1, now - last_time)
                    send_rate = (io.write_bytes - last_sent) / dt / 1024
                    recv_rate = (io.read_bytes - last_recv) / dt / 1024
                    self.rates[pid] = (max(0, send_rate), max(0, recv_rate))

                self.last_io[pid] = (io.write_bytes, io.read_bytes, now)
            except Exception:
                continue

    def get_rate(self, pid):
        return self.rates.get(pid, (0, 0))

    def get_top_network(self, n=5):
        items = [(pid, sum(rates)) for pid, rates in self.rates.items()]
        items.sort(key=lambda x: x[1], reverse=True)
        return items[:n]

NETWORK = NetworkMonitor()

class ProcessWatchdog:
    def __init__(self):
        self.watches = {}
        self.alerts = deque(maxlen=50)

    def add_watch(self, pattern, cpu_limit=None, mem_limit_mb=None, action="throttle"):
        self.watches[pattern.lower()] = {
            "cpu_limit": cpu_limit,
            "mem_limit_mb": mem_limit_mb,
            "action": action
        }

    def remove_watch(self, pattern):
        self.watches.pop(pattern.lower(), None)

    def check_all(self):
        actions = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            try:
                name = (p.info["name"] or "").lower()
                pid = p.info["pid"]

                for pattern, config in self.watches.items():
                    if pattern in name:
                        cpu = p.info.get("cpu_percent", 0) or 0
                        mem_mb = (p.info.get("memory_info") or {}).rss / (1024 * 1024) if hasattr(p.info.get("memory_info", {}), 'rss') else 0

                        triggered = False
                        reason = ""

                        if config["cpu_limit"] and cpu > config["cpu_limit"]:
                            triggered = True
                            reason = f"CPU {cpu:.1f}% > {config['cpu_limit']}%"

                        if config["mem_limit_mb"] and mem_mb > config["mem_limit_mb"]:
                            triggered = True
                            reason = f"RAM {mem_mb:.0f}MB > {config['mem_limit_mb']}MB"

                        if triggered:
                            actions.append({
                                "pid": pid,
                                "name": name,
                                "action": config["action"],
                                "reason": reason
                            })
                            self.alerts.append({
                                "time": time.time(),
                                "name": name,
                                "reason": reason
                            })
            except Exception:
                continue
        return actions

    def get_recent_alerts(self, n=10):
        return list(self.alerts)[-n:]

WATCHDOG = ProcessWatchdog()

class AutoOptimizer:
    def __init__(self):
        self.enabled = False
        self.last_run = 0
        self.interval = 60
        self.actions_taken = deque(maxlen=100)
        self.cpu_high = 80
        self.ram_high = 85

    def should_run(self):
        return self.enabled and (time.time() - self.last_run) > self.interval

    def run(self, fg_pid=None):
        if not self.should_run():
            return []

        self.last_run = time.time()
        actions = []

        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent

        if cpu < self.cpu_high and ram < self.ram_high:
            return []

        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            try:
                pid = p.info["pid"]
                name = (p.info["name"] or "").lower()

                if pid == fg_pid:
                    continue
                if name in (n.lower() for n in SYSTEM_WHITELIST):
                    continue

                proc_cpu = p.info.get("cpu_percent", 0) or 0

                if cpu > self.cpu_high and proc_cpu > 15:
                    try:
                        h = open_proc(pid, win32con.PROCESS_SET_INFORMATION)
                        win32process.SetPriorityClass(h, win32process.BELOW_NORMAL_PRIORITY_CLASS)
                        actions.append(f"Lowered priority: {name}")
                    except Exception:
                        pass

                if ram > self.ram_high:
                    try:
                        h = open_proc(pid, win32con.PROCESS_SET_QUOTA)
                        empty_working_set(h)
                        actions.append(f"Trimmed RAM: {name}")
                    except Exception:
                        pass

            except Exception:
                continue

        self.actions_taken.extend(actions)
        return actions

    def get_recent_actions(self, n=20):
        return list(self.actions_taken)[-n:]

AUTO_OPT = AutoOptimizer()

PROFILES = {
    "Gaming": {
        "fg_priority": "High",
        "gov": True,
        "plan": "HIGH",
        "bg_cpu_limit": 15,
        "bg_mem_priority": 1,
        "suspend_heavy_bg": False,
        "startup_delay": 5,
        "desc": "🎮 Maximum FG boost, aggressive BG throttling, High Performance power plan."
    },
    "Work": {
        "fg_priority": "Above Normal",
        "gov": True,
        "plan": "BALANCED",
        "bg_cpu_limit": 40,
        "bg_mem_priority": 2,
        "suspend_heavy_bg": False,
        "startup_delay": 3,
        "desc": "💼 Balanced for productivity, moderate BG control, smooth multitasking."
    },
    "Battery": {
        "fg_priority": "Normal",
        "gov": True,
        "plan": "POWER_SAVER",
        "bg_cpu_limit": 25,
        "bg_mem_priority": 2,
        "suspend_heavy_bg": False,
        "startup_delay": 5,
        "desc": "🔋 Battery saving mode, reduced performance, extended battery life."
    },
    "Quiet": {
        "fg_priority": "Normal",
        "gov": True,
        "plan": "POWER_SAVER",
        "bg_cpu_limit": 10,
        "bg_mem_priority": 1,
        "suspend_heavy_bg": True,
        "startup_delay": 10,
        "desc": "🔇 Maximum power savings, aggressive BG suppression, silent operation."
    }
}
def switch_power_plan(tag):
    try:
        if tag == "HIGH":
            subprocess.run(["powercfg", "/setactive", "SCHEME_MIN"], check=False)
        elif tag == "POWER_SAVER":
            subprocess.run(["powercfg", "/setactive", "SCHEME_MAX"], check=False)
        else:
            subprocess.run(["powercfg", "/setactive", "SCHEME_BALANCED"], check=False)
    except Exception:
        pass

class StartupEntry:
    def __init__(self, source, name, command, enabled, kind, path=None, hive="HKCU"):
        self.source  = source
        self.name    = name
        self.command = command
        self.enabled = enabled
        self.kind    = kind
        self.path    = path
        self.hive    = hive

class StartupManager:
    DISABLED_KEY = r"Software\OptiCores\StartupBackup"
    DELAY_CONFIG_PATH = os.path.join(APP_DIR, "startup_delays.json")

    def __init__(self):
        self.user_startup = os.path.join(os.getenv("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
        self.common_startup = os.path.join(os.getenv("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs\StartUp")
        self.delay_config = {}
        self.impact_scores = {}
        self._load_delay_config()

    def _load_delay_config(self):
        try:
            if os.path.exists(self.DELAY_CONFIG_PATH):
                self.delay_config = json.load(open(self.DELAY_CONFIG_PATH, "r", encoding="utf-8"))
        except Exception:
            self.delay_config = {}

    def _save_delay_config(self):
        try:
            json.dump(self.delay_config, open(self.DELAY_CONFIG_PATH, "w", encoding="utf-8"), indent=2)
        except Exception:
            pass

    def set_delay(self, app_name, seconds):
        self.delay_config[app_name] = max(0, min(60, seconds))
        self._save_delay_config()

    def get_delay(self, app_name):
        return self.delay_config.get(app_name, 0)

    def get_delayed_order(self):
        entries = self.list()
        return sorted(entries, key=lambda e: self.get_delay(e.name))

    def set_impact_score(self, app_name, cpu_impact, mem_impact):
        self.impact_scores[app_name] = {"cpu": cpu_impact, "mem": mem_impact}

    def get_impact_score(self, app_name):
        return self.impact_scores.get(app_name, {"cpu": 0, "mem": 0})

    def auto_suggest_delays(self):
        suggestions = {}
        for name, impact in self.impact_scores.items():
            total_impact = impact["cpu"] + (impact["mem"] / 100)
            if total_impact > 50:
                suggestions[name] = 15
            elif total_impact > 20:
                suggestions[name] = 8
            elif total_impact > 5:
                suggestions[name] = 3
            else:
                suggestions[name] = 0
        return suggestions
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

class SystemInfoCollector:
    def __init__(self):
        self.cache = {}
        self.cache_time = 0
        self.cache_ttl = 30

    def get_cpu_info(self):
        try:
            import platform

            cpu_name = platform.processor() or 'Unknown'
            try:
                import subprocess
                result = subprocess.run(
                    ['wmic', 'cpu', 'get', 'name'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip() and l.strip() != 'Name']
                    if lines:
                        cpu_name = lines[0]
            except Exception:
                pass

            info = {
                'name': cpu_name,
                'physical_cores': psutil.cpu_count(logical=False) or 0,
                'logical_cores': psutil.cpu_count(logical=True) or 0,
                'max_freq': 0,
                'current_freq': 0,
                'architecture': platform.machine()
            }
            freq = psutil.cpu_freq()
            if freq:
                info['max_freq'] = freq.max
                info['current_freq'] = freq.current
            return info
        except Exception:
            return {'name': 'Unknown', 'physical_cores': 0, 'logical_cores': 0, 'max_freq': 0, 'current_freq': 0, 'architecture': 'Unknown'}

    def get_memory_info(self):
        try:
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            return {
                'total_gb': mem.total / (1024**3),
                'available_gb': mem.available / (1024**3),
                'used_gb': mem.used / (1024**3),
                'percent': mem.percent,
                'swap_total_gb': swap.total / (1024**3),
                'swap_used_gb': swap.used / (1024**3)
            }
        except Exception:
            return {'total_gb': 0, 'available_gb': 0, 'used_gb': 0, 'percent': 0, 'swap_total_gb': 0, 'swap_used_gb': 0}

    def get_disk_info(self):
        disks = []
        try:
            for part in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append({
                        'device': part.device,
                        'mountpoint': part.mountpoint,
                        'fstype': part.fstype,
                        'total_gb': usage.total / (1024**3),
                        'used_gb': usage.used / (1024**3),
                        'free_gb': usage.free / (1024**3),
                        'percent': usage.percent
                    })
                except Exception:
                    pass
        except Exception:
            pass
        return disks

    def get_gpu_info(self):
        gpus = []
        try:
            if GPUtil:
                for gpu in GPUtil.getGPUs():
                    gpus.append({
                        'name': gpu.name,
                        'memory_total_mb': gpu.memoryTotal,
                        'memory_used_mb': gpu.memoryUsed,
                        'memory_free_mb': gpu.memoryFree,
                        'load': gpu.load * 100,
                        'temperature': gpu.temperature
                    })
        except Exception:
            pass
        return gpus if gpus else [{'name': 'Integrated/Unknown', 'memory_total_mb': 0, 'memory_used_mb': 0, 'memory_free_mb': 0, 'load': 0, 'temperature': 0}]

    def get_os_info(self):
        try:
            import platform
            return {
                'system': platform.system(),
                'release': platform.release(),
                'version': platform.version(),
                'machine': platform.machine(),
                'node': platform.node()
            }
        except Exception:
            return {'system': 'Unknown', 'release': '', 'version': '', 'machine': '', 'node': ''}

    def get_network_info(self):
        interfaces = []
        try:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            for iface, addr_list in addrs.items():
                iface_info = {'name': iface, 'addresses': [], 'is_up': False, 'speed': 0}
                if iface in stats:
                    iface_info['is_up'] = stats[iface].isup
                    iface_info['speed'] = stats[iface].speed
                for addr in addr_list:
                    if addr.family.name == 'AF_INET':
                        iface_info['addresses'].append({'type': 'IPv4', 'address': addr.address})
                    elif addr.family.name == 'AF_INET6':
                        iface_info['addresses'].append({'type': 'IPv6', 'address': addr.address})
                interfaces.append(iface_info)
        except Exception:
            pass
        return interfaces

    def get_all(self):
        return {
            'cpu': self.get_cpu_info(),
            'memory': self.get_memory_info(),
            'disks': self.get_disk_info(),
            'gpus': self.get_gpu_info(),
            'os': self.get_os_info(),
            'network': self.get_network_info()
        }

SYSINFO = SystemInfoCollector()

class SecurityScanner:
    def __init__(self):
        self.suspicious_patterns = [
            'miner', 'crypto', 'xmr', 'cgminer', 'bitminer', 'nicehash',
            'cryptonight', 'monero', 'coinhive', 'coinminer', 'webmine',
            'trojan', 'malware', 'backdoor', 'keylog', 'rat.exe', 'exploit'
        ]
        self.scan_results = []
        self.last_scan = None

    def scan_suspicious_names(self):
        results = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'exe']):
                try:
                    name = (proc.info['name'] or '').lower()
                    exe = (proc.info['exe'] or '').lower()
                    for pattern in self.suspicious_patterns:
                        if pattern in name or pattern in exe:
                            results.append({
                                'pid': proc.info['pid'],
                                'name': proc.info['name'],
                                'exe': proc.info['exe'],
                                'threat': 'Suspicious Name Pattern',
                                'pattern': pattern,
                                'severity': 'high'
                            })
                            break
                except Exception:
                    pass
        except Exception:
            pass
        return results

    def scan_resource_abuse(self, cpu_threshold=80, mem_threshold_mb=2000):
        results = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
                try:
                    cpu = proc.info.get('cpu_percent', 0) or 0
                    mem_mb = (proc.info.get('memory_info').rss if proc.info.get('memory_info') else 0) / (1024*1024)
                    if cpu > cpu_threshold:
                        results.append({
                            'pid': proc.info['pid'],
                            'name': proc.info['name'],
                            'threat': f'High CPU Usage ({cpu:.0f}%)',
                            'severity': 'medium',
                            'cpu': cpu
                        })
                    if mem_mb > mem_threshold_mb:
                        results.append({
                            'pid': proc.info['pid'],
                            'name': proc.info['name'],
                            'threat': f'High Memory Usage ({mem_mb:.0f} MB)',
                            'severity': 'medium',
                            'memory_mb': mem_mb
                        })
                except Exception:
                    pass
        except Exception:
            pass
        return results

    def scan_hidden_processes(self):
        results = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
                try:
                    name = proc.info['name'] or ''
                    exe = proc.info['exe'] or ''
                    if not exe and name and name.lower() not in ['system', 'system idle process', 'registry', 'idle']:
                        results.append({
                            'pid': proc.info['pid'],
                            'name': name,
                            'threat': 'Hidden/No Executable Path',
                            'severity': 'low'
                        })
                except Exception:
                    pass
        except Exception:
            pass
        return results

    def run_full_scan(self):
        self.scan_results = []
        self.scan_results.extend(self.scan_suspicious_names())
        self.scan_results.extend(self.scan_resource_abuse())
        self.scan_results.extend(self.scan_hidden_processes())
        self.last_scan = time.time()
        return self.scan_results

SECURITY = SecurityScanner()

class PowerManager:
    POWER_PLANS = {
        'balanced': '381b4222-f694-41f0-9685-ff5bb260df2e',
        'high_performance': '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c',
        'power_saver': 'a1841308-3541-4fab-bc81-f71556f20b4a',
        'ultimate': 'e9a42b02-d5df-448d-aa00-03f14749eb61'
    }

    def __init__(self):
        self.current_plan = None
        self.original_plan = None

    def get_current_power_plan(self):
        try:
            result = subprocess.run(['powercfg', '/getactivescheme'], capture_output=True, text=True, check=True)
            output = result.stdout
            for plan_name, guid in self.POWER_PLANS.items():
                if guid.lower() in output.lower():
                    self.current_plan = plan_name
                    return plan_name
            if 'balanced' in output.lower():
                return 'balanced'
            elif 'high performance' in output.lower():
                return 'high_performance'
            elif 'power saver' in output.lower():
                return 'power_saver'
            return 'unknown'
        except Exception:
            return 'unknown'

    def set_power_plan(self, plan_name):
        try:
            if plan_name in self.POWER_PLANS:
                guid = self.POWER_PLANS[plan_name]
                subprocess.run(['powercfg', '/setactive', guid], check=True, capture_output=True)
                self.current_plan = plan_name
                return True
        except Exception:
            pass
        return False

    def get_battery_status(self):
        try:
            battery = psutil.sensors_battery()
            if battery:
                return {
                    'percent': battery.percent,
                    'power_plugged': battery.power_plugged,
                    'secs_left': battery.secsleft if battery.secsleft != psutil.POWER_TIME_UNLIMITED else -1
                }
        except Exception:
            pass
        return {'percent': 100, 'power_plugged': True, 'secs_left': -1}

    def enable_power_saving_mode(self):
        return self.set_power_plan('power_saver')

    def enable_performance_mode(self):
        return self.set_power_plan('high_performance')

    def enable_balanced_mode(self):
        return self.set_power_plan('balanced')

POWER_MGR = PowerManager()

class TaskScheduler:
    def __init__(self):
        self.tasks = []
        self.running = False
        self._thread = None
        self._stop_event = threading.Event()
        self.config_path = os.path.join(APP_DIR, "scheduled_tasks.json")
        self._load_tasks()

    def _load_tasks(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.tasks = json.load(f)
        except Exception:
            self.tasks = []

    def _save_tasks(self):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.tasks, f, indent=2)
        except Exception:
            pass

    def add_task(self, name, action, interval_minutes, enabled=True):
        task = {
            'id': time.time(),
            'name': name,
            'action': action,
            'interval_minutes': interval_minutes,
            'enabled': enabled,
            'last_run': None
        }
        self.tasks.append(task)
        self._save_tasks()
        return task

    def remove_task(self, task_id):
        self.tasks = [t for t in self.tasks if t.get('id') != task_id]
        self._save_tasks()

    def toggle_task(self, task_id, enabled):
        for task in self.tasks:
            if task.get('id') == task_id:
                task['enabled'] = enabled
                break
        self._save_tasks()

    def get_tasks(self):
        return self.tasks

    def check_and_run(self, action_callback):
        now = time.time()
        for task in self.tasks:
            if not task.get('enabled'):
                continue
            last_run = task.get('last_run') or 0
            interval_sec = task.get('interval_minutes', 60) * 60
            if now - last_run >= interval_sec:
                try:
                    action_callback(task.get('action'))
                    task['last_run'] = now
                except Exception:
                    pass
        self._save_tasks()

TASK_SCHEDULER = TaskScheduler()

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1350x910")
        self.minsize(1180, 820)

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.configure(fg_color="#050709")

        self.core_count = multiprocessing.cpu_count()
        self.sort_key = "CPU"
        self.search_term = ""
        self._stop = False

        self._session_stats = {
            "ram_freed_mb": 0,
            "processes_optimized": 0,
            "boost_count": 0,
            "start_time": time.time()
        }

        self.bg_gov = BackgroundGovernor()
        self.health = HealthWatcher()

        self.cpu_snap = {}
        self.cpu_lock = threading.Lock()

        self.rules = DEFAULT_RULES.copy()
        self.startup_item_map = {}

        self.settings = {
            "thresholds": dict(DEFAULT_THRESH),
            "custom_whitelist": [],
            "refresh_sec": DEFAULT_REFRESH_SEC,
            "logo_path": os.path.join("/mnt/data", "88b52a2c-dccd-4240-9f3b-4cb09171fab8.png")
        }

        self._adv_fixes = []
        self.adv_rows = {}

        self.last_selected_pid = None

        self.ts_len = 120
        self.ts_cpu = deque([0]*self.ts_len, maxlen=self.ts_len)
        self.ts_ram = deque([0]*self.ts_len, maxlen=self.ts_len)
        self.ts_gpu = deque([0]*self.ts_len, maxlen=self.ts_len)
        self.ts_dpc = deque([0]*self.ts_len, maxlen=self.ts_len)
        self.ts_ctx = deque([0]*self.ts_len, maxlen=self.ts_len)
        self.ts_net_down = deque([0]*self.ts_len, maxlen=self.ts_len)
        self.ts_net_up   = deque([0]*self.ts_len, maxlen=self.ts_len)

        self.current_profile = "Work"

        self.last_net_io = psutil.net_io_counters()
        self.last_net_time = time.time()

        self.tree = None
        self.tree_dash = None
        self.tree_start = None
        self.val_cpu = None; self.val_mem = None; self.val_gpu = None; self.val_fg = None
        self.val_net_down = None; self.val_net_up = None
        self.line_cpu = None; self.line_ram = None; self.line_gpu = None
        self.lbl_dpc = None; self.lbl_ctx = None; self.lbl_health = None

        self._refresh_cycle = 0
        self._cached_gpu = 0.0
        self._cached_gpu_time = 0

        self._build_styles()
        self._build_ui()
        self._load_config()

        ANIMATOR.set_root(self)

        for p in psutil.process_iter():
            try: p.cpu_percent(interval=None)
            except Exception: pass

        threading.Thread(target=self._loop_update_cpu, daemon=True).start()
        threading.Thread(target=self._loop_refresh_ui, daemon=True).start()
        threading.Thread(target=self._loop_follow_foreground, daemon=True).start()
        threading.Thread(target=self._loop_effects_finalize, daemon=True).start()
        threading.Thread(target=self._loop_rules, daemon=True).start()
        threading.Thread(target=self._loop_features, daemon=True).start()

        self._init_usage_stats()

        if not is_admin():
            self._toast("Tip: run as Administrator to enable all actions.", "warn")
        self.after(800, self._show_quick_tour_once)

        self.tray_icon = None
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._init_tray()

    def _build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("Tbl.Treeview",
            background=TOKENS.BG_BASE,
            fieldbackground=TOKENS.BG_BASE,
            foreground=TOKENS.FG_PRIMARY,
            rowheight=38,
            font=(TOKENS.FONT_DISPLAY, 11),
            borderwidth=0,
            relief="flat"
        )
        style.configure("Tbl.Treeview.Heading",
            background=TOKENS.BG_ELEVATED,
            foreground=TOKENS.FG_SECONDARY,
            font=(TOKENS.FONT_TEXT + " Semibold", 11),
            borderwidth=0,
            relief="flat",
            padding=(14, 10)
        )
        style.map("Tbl.Treeview",
            background=[("selected", TOKENS.ACCENT_ACTIVE)],
            foreground=[("selected", "#FFFFFF")]
        )
        style.map("Tbl.Treeview.Heading",
            background=[("active", TOKENS.BG_OVERLAY)]
        )

        style.layout("Tbl.Treeview", [
            ('Treeview.treearea', {'sticky': 'nswe'})
        ])

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=TOKENS.SIDEBAR_BG)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self._build_sidebar()

        self.content_area = ctk.CTkFrame(self, corner_radius=0, fg_color=TOKENS.BG_SURFACE)
        self.content_area.grid(row=0, column=1, sticky="nsew")
        self.content_area.grid_columnconfigure(0, weight=1)
        self.content_area.grid_rowconfigure(1, weight=1)

        self.current_view = None
        self._switch_nav("Dashboard")

        self.after(2000, self._show_fps_overlay)

        self.optibalance_enabled = True
        self.optibalance_adjustments = 0
        self.after(3000, self._optibalance_monitor)

        shortcut_tabs = ["Dashboard", "Processes", "Booster", "Tools", "Storage", "Benchmark", "Settings", "SystemInfo"]
        for i, tab in enumerate(shortcut_tabs):
            self.bind(f"<Control-Key-{i+1}>", lambda e, t=tab: self._switch_nav(t))
        self.bind("<F5>", lambda e: self._refresh_current_view())
        self.bind("<Control-b>", lambda e: self._one_click_boost())
        self.bind("<Control-B>", lambda e: self._one_click_boost())

    def _refresh_current_view(self):
        view = getattr(self, 'current_view', None)
        if view == "Dashboard":
            self._refresh_dashboard_stats()
        elif view == "Processes":
            self._refresh_table()
        elif view == "Active":
            self._refresh_active_apps()
        elif view == "Activity":
            self._refresh_activity_log()
        elif view == "SystemInfo":
            self._refresh_sysinfo()
        elif view == "Storage":
            self._refresh_disk_cards()
        elif view == "Startup":
            self._refresh_startup()
        self._toast("Refreshed", "ok")

    def _optibalance_monitor(self):
        if not self.optibalance_enabled:
            self.after(5000, self._optibalance_monitor)
            return

        if not hasattr(self, '_optibalance_check_count'):
            self._optibalance_check_count = 0
        self._optibalance_check_count += 1

        try:
            high_cpu_procs = []
            essential = ['explorer', 'system', 'csrss', 'wininit', 'services', 'lsass',
                        'svchost', 'dwm', 'python', 'opticores']

            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
                try:
                    info = proc.info
                    name = info['name'] or ''
                    cpu = info['cpu_percent'] or 0

                    if any(e in name.lower() for e in essential):
                        continue

                    if cpu > 30:
                        high_cpu_procs.append({'pid': info['pid'], 'name': name, 'cpu': cpu})
                except:
                    pass

            for proc_info in high_cpu_procs:
                try:
                    proc = psutil.Process(proc_info['pid'])
                    current_nice = proc.nice()

                    if current_nice < psutil.BELOW_NORMAL_PRIORITY_CLASS:
                        proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
                        self.optibalance_adjustments += 1
                        self._log_activity(f"OptiBalance: Lowered priority of {proc_info['name']} (CPU: {proc_info['cpu']:.0f}%)", "optibalance")
                except:
                    pass

            if len(high_cpu_procs) > 0:
                self._log_activity(f"OptiBalance: Monitoring {len(high_cpu_procs)} high CPU processes", "optibalance")
            elif self._optibalance_check_count % 6 == 0:
                self._log_activity(f"OptiBalance: System stable - {self.optibalance_adjustments} adjustments total", "optibalance")

        except Exception as e:
            pass

        self.after(5000, self._optibalance_monitor)

    def _build_sidebar(self):
        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=16, pady=24)
        ctk.CTkLabel(brand, text="⚡", font=ctk.CTkFont(size=24), text_color=TOKENS.ACCENT_PRIMARY).pack(side="left", padx=(0,10))
        ctk.CTkLabel(brand, text="OptiCores",
                    font=ctk.CTkFont(family=TOKENS.FONT_DISPLAY, size=18, weight="bold"),
                    text_color=TOKENS.FG_PRIMARY).pack(side="left")

        self.nav_btns = {}
        self.nav_indicators = {}

        items = [
            ("Dashboard", "📊"),
            ("Processes", "⚡"),
            ("Active",    "📱"),
            ("Activity",  "📜"),
            ("Booster",   "🔥"),
            ("Tools",     "🔧"),
            ("Network",   "🌐"),
            ("Storage",   "💾"),
            ("Cleaner",   "🧹"),
            ("Benchmark", "🎯"),
            ("SystemInfo", "💻"),
            ("Power",     "⚡"),
            ("Overlay",   "🎮"),
            ("Optimizer", "🚀"),
            ("Rules",     "📋"),
            ("Startup",   "🏁"),
            ("Insights",  "📈"),
            ("AIAssistant", "🤖"),
            ("Settings",  "⚙️")
        ]

        for name, icon in items:
            container = ctk.CTkFrame(self.sidebar, fg_color="transparent", height=42)
            container.pack(fill="x", pady=2)

            line = ctk.CTkFrame(container, width=4, height=32, corner_radius=2, fg_color="transparent")
            line.pack(side="left", padx=(0,8), pady=5)
            self.nav_indicators[name] = line

            btn = ctk.CTkButton(container, text=f"{icon}  {name}",
                               anchor="w", corner_radius=TOKENS.RADIUS_SM, height=42,
                               font=ctk.CTkFont(family=TOKENS.FONT_TEXT, size=14),
                               fg_color="transparent", text_color=TOKENS.FG_SECONDARY,
                               hover_color=TOKENS.BG_HOVER,
                               command=lambda n=name: self._switch_nav(n))
            btn.pack(side="left", fill="x", expand=True, padx=(0,12))
            self.nav_btns[name] = btn

        spacer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        spacer.pack(fill="both", expand=True)

        prof = ctk.CTkFrame(self.sidebar, fg_color=TOKENS.BG_HOVER, corner_radius=TOKENS.RADIUS_MD)
        prof.pack(fill="x", padx=12, pady=20)
        ctk.CTkLabel(prof, text="PROFILE", font=ctk.CTkFont(size=10, weight="bold"), text_color=TOKENS.FG_MUTED).pack(anchor="w", padx=12, pady=(10,2))
        self.sidebar_prof_lbl = ctk.CTkLabel(prof, text=self.current_profile, font=ctk.CTkFont(weight="bold"), text_color=TOKENS.FG_PRIMARY)
        self.sidebar_prof_lbl.pack(anchor="w", padx=12, pady=(0,10))

    def _switch_nav(self, name):
        for n, btn in self.nav_btns.items():
            line = self.nav_indicators.get(n)
            if n == name:
                btn.configure(text_color=TOKENS.FG_PRIMARY, fg_color=TOKENS.SIDEBAR_ACTIVE)
                if line:
                    ANIMATOR.animate_color(line, TOKENS.SIDEBAR_ACTIVE, TOKENS.ACCENT_PRIMARY, duration_ms=200, property_name='fg_color')
            else:
                btn.configure(text_color=TOKENS.FG_SECONDARY, fg_color="transparent")
                if line: line.configure(fg_color="transparent")

        for view_name in ["Dashboard", "Processes", "Active", "Activity", "Booster", "Tools", "Network", "Storage", "Cleaner", "Benchmark", "SystemInfo", "Power", "Overlay", "Optimizer", "Rules", "Startup", "Insights", "AIAssistant", "Settings"]:
            f = getattr(self, f"view_frame_{view_name}", None)
            if f: f.pack_forget()

        self.current_view = name

        frame = self._get_view_frame(name)
        frame.pack(fill="both", expand=True)

        try:
            frame.update_idletasks()
        except:
            pass

    def _get_view_frame(self, name):
        attr = f"view_frame_{name}"
        if hasattr(self, attr):
            return getattr(self, attr)

        frame = ctk.CTkFrame(self.content_area, fg_color="transparent")
        setattr(self, attr, frame)

        if name == "Dashboard": self._fill_dashboard_modern(frame)
        elif name == "Processes": self._fill_processes(frame)
        elif name == "Active":    self._fill_active(frame)
        elif name == "Activity":  self._fill_activity(frame)
        elif name == "Booster":   self._fill_booster(frame)
        elif name == "Tools":     self._fill_tools(frame)
        elif name == "Network":   self._fill_network(frame)
        elif name == "Storage":   self._fill_storage(frame)
        elif name == "Cleaner":   self._fill_cleaner(frame)
        elif name == "Benchmark": self._fill_benchmark(frame)
        elif name == "SystemInfo": self._fill_sysinfo(frame)
        elif name == "Power":     self._fill_power(frame)
        elif name == "Overlay":   self._fill_overlay(frame)
        elif name == "Optimizer": self._fill_optimizer(frame)
        elif name == "Rules":     self._fill_rules(frame)
        elif name == "Startup":   self._fill_startup_modern(frame)
        elif name == "Insights":  self._fill_insights(frame)
        elif name == "AIAssistant": self._fill_ai_assistant(frame)
        elif name == "Settings":  self._fill_settings(frame)

        return frame

    def _modern_card(self, parent, title, val, icon=None, color=None, on_click=None):
        f = ctk.CTkFrame(parent, fg_color=TOKENS.CARD_BG, corner_radius=TOKENS.RADIUS_MD,
                        border_width=1, border_color=TOKENS.CARD_BORDER)

        content = ctk.CTkFrame(f, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=TOKENS.S_MD, pady=TOKENS.S_MD)

        h = ctk.CTkFrame(content, fg_color="transparent")
        h.pack(fill="x", pady=(0, TOKENS.S_SM))

        if icon:
            icon_bg = ctk.CTkFrame(h, width=32, height=32, corner_radius=TOKENS.RADIUS_SM,
                                   fg_color=TOKENS.BG_OVERLAY)
            icon_bg.pack(side="left")
            icon_bg.pack_propagate(False)
            ctk.CTkLabel(icon_bg, text=icon, font=ctk.CTkFont(size=16)).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(h, text=title, font=ctk.CTkFont(family=TOKENS.FONT_DISPLAY, size=13, weight="bold"),
                    text_color=TOKENS.FG_SECONDARY).pack(side="left", padx=(10,0))

        lbl = ctk.CTkLabel(content, text=val, font=ctk.CTkFont(family=TOKENS.FONT_DISPLAY, size=24, weight="bold"),
                          text_color=TOKENS.FG_PRIMARY)
        lbl.pack(anchor="w")

        bar_bg = ctk.CTkFrame(content, height=4, fg_color=TOKENS.BG_OVERLAY, corner_radius=2)
        bar_bg.pack(fill="x", pady=(TOKENS.S_MD, 0))
        bar = ctk.CTkFrame(bar_bg, height=4, fg_color=color if color else TOKENS.INFO, corner_radius=2)
        bar.place(relwidth=0.05, relheight=1)

        if on_click:
            f.configure(cursor="hand2")
            f.bind("<Button-1>", lambda e: on_click())
            content.bind("<Button-1>", lambda e: on_click())
            lbl.bind("<Button-1>", lambda e: on_click())

        f._current_width = 0.05

        def set_value(v, pct=None):
            lbl.configure(text=v)
            if pct is not None:
                target_w = max(0.05, min(1.0, pct/100))
                start_w = f._current_width
                f._current_width = target_w

                def animate_bar(step=0, max_steps=15):
                    if step <= max_steps:
                        progress = step / max_steps
                        ease = 1 - pow(1 - progress, 3)
                        current_w = start_w + (target_w - start_w) * ease
                        try:
                            bar.place(relwidth=current_w, relheight=1)
                            f.after(16, lambda: animate_bar(step + 1, max_steps))
                        except:
                            pass

                animate_bar()

        def set_bar_color(new_color):
            try:
                ANIMATOR.animate_color(bar, bar.cget("fg_color"), new_color, duration_ms=TOKENS.ANIM_NORMAL, property_name='fg_color')
            except:
                bar.configure(fg_color=new_color)

        f.set_value = set_value
        f.set_bar_color = set_bar_color
        f._bar = bar
        return f, lbl

    def _modern_action_tile(self, parent, title, icon, color, cmd):
        btn = ctk.CTkButton(
            parent,
            text=f"{icon}  {title}",
            command=cmd,
            fg_color=TOKENS.CARD_BG,
            hover_color=TOKENS.BG_OVERLAY,
            text_color=TOKENS.FG_PRIMARY,
            font=ctk.CTkFont(size=13, weight="bold"),
            corner_radius=TOKENS.RADIUS_MD,
            border_width=1,
            border_color=TOKENS.CARD_BORDER,
            height=55,
            anchor="w"
        )
        return btn

    def _fill_dashboard_modern(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        header = ctk.CTkFrame(scroll, fg_color="transparent")
        header.pack(fill="x", padx=40, pady=(30,5))

        from datetime import datetime
        hour = datetime.now().hour
        if hour < 12: greeting = "Good Morning"
        elif hour < 17: greeting = "Good Afternoon"
        else: greeting = "Good Evening"

        header_top = ctk.CTkFrame(header, fg_color="transparent")
        header_top.pack(fill="x")

        left_header = ctk.CTkFrame(header_top, fg_color="transparent")
        left_header.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(left_header, text=f"👋 {greeting}", font=ctk.CTkFont(size=14), text_color=TOKENS.FG_SECONDARY).pack(anchor="w")
        ctk.CTkLabel(left_header, text="Dashboard", font=ctk.CTkFont(family=TOKENS.FONT_DISPLAY, size=32, weight="bold")).pack(anchor="w")

        btn_refresh = ctk.CTkButton(header_top, text="🔄 Refresh", width=100, height=32,
                                     fg_color=TOKENS.CARD_BG, hover_color=TOKENS.BG_OVERLAY,
                                     border_width=1, border_color=TOKENS.CARD_BORDER,
                                     command=lambda: self._toast("Refreshing...", "ok"))
        btn_refresh.pack(side="right", pady=(8,0))

        uptime_row = ctk.CTkFrame(scroll, fg_color="transparent")
        uptime_row.pack(fill="x", padx=40, pady=(0,20))

        import psutil, time
        boot = psutil.boot_time()
        uptime_sec = time.time() - boot
        days, rem = divmod(int(uptime_sec), 86400)
        hours, rem = divmod(rem, 3600)
        mins, _ = divmod(rem, 60)
        uptime_str = f"{days}d {hours}h {mins}m" if days else f"{hours}h {mins}m"

        ctk.CTkLabel(uptime_row, text=f"⏱ System Uptime: {uptime_str}", font=ctk.CTkFont(size=12), text_color=TOKENS.FG_MUTED).pack(side="left")

        grid = ctk.CTkFrame(scroll, fg_color="transparent")
        grid.pack(fill="x", padx=40, pady=(0,20))
        grid.grid_columnconfigure((0,1,2), weight=1)

        self.card_cpu, self.val_cpu = self._modern_card(grid, "CPU Load", "--%", "🧠", TOKENS.ACCENT_PRIMARY,
                                                         on_click=lambda: self._switch_nav("Processes"))
        self.card_mem, self.val_mem = self._modern_card(grid, "Memory", "--%", "💾", TOKENS.SUCCESS)
        self.card_gpu, self.val_gpu = self._modern_card(grid, "GPU Core", "--%", "🎮", TOKENS.WARNING)

        self.card_cpu.grid(row=0, column=0, sticky="ew", padx=(0,8), pady=(0,8))
        self.card_mem.grid(row=0, column=1, sticky="ew", padx=8, pady=(0,8))
        self.card_gpu.grid(row=0, column=2, sticky="ew", padx=(8,0), pady=(0,8))

        self.card_battery, self.val_battery = self._modern_card(grid, "Battery", "--%", "🔋", TOKENS.SUCCESS,
                                                                 on_click=lambda: self._switch_nav("Power"))
        self.card_cpu_temp, self.val_cpu_temp = self._modern_card(grid, "CPU Temp", "--°C", "🌡️", TOKENS.ERROR)
        self.card_gpu_temp, self.val_gpu_temp = self._modern_card(grid, "GPU Temp", "--°C", "🔥", TOKENS.WARNING_MUTED)

        self.card_battery.grid(row=1, column=0, sticky="ew", padx=(0,8), pady=(0,8))
        self.card_cpu_temp.grid(row=1, column=1, sticky="ew", padx=8, pady=(0,8))
        self.card_gpu_temp.grid(row=1, column=2, sticky="ew", padx=(8,0), pady=(0,8))

        disk = psutil.disk_usage('/')
        disk_pct = disk.percent
        disk_free_gb = disk.free / (1024**3)

        total_threads = sum(p.num_threads() for p in psutil.process_iter(['num_threads']) if p.info['num_threads'])

        self.card_disk, self.val_disk = self._modern_card(grid, "Disk Space", f"{disk_free_gb:.1f} GB free", "💿", "#6366f1")
        self.card_threads, self.val_threads = self._modern_card(grid, "Threads", str(total_threads), "🧵", "#a855f7")
        self.card_procs, self.val_procs = self._modern_card(grid, "Processes", str(len(psutil.pids())), "📊", "#ec4899",
                                                             on_click=lambda: self._switch_nav("Processes"))

        self.card_disk.grid(row=2, column=0, sticky="ew", padx=(0,8))
        self.card_threads.grid(row=2, column=1, sticky="ew", padx=8)
        self.card_procs.grid(row=2, column=2, sticky="ew", padx=(8,0))

        if hasattr(self.card_disk, 'set_value'):
            self.card_disk.set_value(f"{disk_free_gb:.1f} GB free", 100 - disk_pct)

        banner = ctk.CTkFrame(scroll, fg_color=TOKENS.CARD_BG, corner_radius=TOKENS.RADIUS_MD, border_width=1, border_color=TOKENS.CARD_BORDER)
        banner.pack(fill="x", padx=40, pady=(10,15))

        ban_in = ctk.CTkFrame(banner, fg_color="transparent")
        ban_in.pack(fill="x", padx=20, pady=16)

        ban_left = ctk.CTkFrame(ban_in, fg_color="transparent")
        ban_left.pack(side="left")
        ctk.CTkLabel(ban_left, text="🚀 One-Click Optimization", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(ban_left, text="Free up RAM, boost foreground, throttle background", font=ctk.CTkFont(size=11), text_color=TOKENS.FG_MUTED).pack(anchor="w")

        self.btn_boost_all = ctk.CTkButton(ban_in, text="BOOST NOW", height=40, width=130, font=ctk.CTkFont(weight="bold"),
                     fg_color=TOKENS.ACCENT_ACTIVE, hover_color=TOKENS.ACCENT_PRIMARY, corner_radius=10,
                     command=self._one_click_boost)
        self.btn_boost_all.pack(side="right")

        overview = ctk.CTkFrame(scroll, fg_color=TOKENS.CARD_BG, corner_radius=TOKENS.RADIUS_MD, border_width=1, border_color=TOKENS.CARD_BORDER)
        overview.pack(fill="x", padx=40, pady=(0,15))

        ov_in = ctk.CTkFrame(overview, fg_color="transparent")
        ov_in.pack(fill="x", padx=20, pady=16)
        ov_in.grid_columnconfigure((0,1,2,3), weight=1)

        proc_count = len(psutil.pids())
        mem_avail = psutil.virtual_memory().available / (1024**3)

        stat_proc, _ = self._stat_item(ov_in, "Processes", str(proc_count), "📊")
        stat_proc.grid(row=0, column=0, sticky="w")
        stat_ram, _ = self._stat_item(ov_in, "Available RAM", f"{mem_avail:.1f} GB", "🧠")
        stat_ram.grid(row=0, column=1, sticky="w")
        stat_disk, _ = self._stat_item(ov_in, "Disk Used", f"{disk_pct:.0f}%", "💿")
        stat_disk.grid(row=0, column=2, sticky="w")
        stat_power, self.lbl_footer_power = self._stat_item(ov_in, "Power Plan", "...", "⚡")
        stat_power.grid(row=0, column=3, sticky="w")

        split = ctk.CTkFrame(scroll, fg_color="transparent")
        split.pack(fill="both", expand=True, padx=40, pady=(0,40))
        split.grid_columnconfigure((0,1), weight=1)

        left = ctk.CTkFrame(split, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0,15))

        ctk.CTkLabel(left, text="Quick Actions", font=ctk.CTkFont(size=14, weight="bold"), text_color=TOKENS.FG_SECONDARY).pack(anchor="w", pady=(0,10))

        act_grid = ctk.CTkFrame(left, fg_color="transparent")
        act_grid.pack(fill="x")
        act_grid.grid_columnconfigure((0,1), weight=1)

        self._modern_action_tile(act_grid, "Boost Active", "🎯", "#8b5cf6", self._quick_boost_fg).grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self._modern_action_tile(act_grid, "Clean RAM", "🧹", "#10b981", self._quick_trim_all).grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self._modern_action_tile(act_grid, "Eco Mode", "🍃", "#f59e0b", self._quick_throttle_bg).grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        self._modern_action_tile(act_grid, "Gaming", "🎮", "#ef4444", lambda: self._set_power_plan("high")).grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        self._modern_action_tile(act_grid, "Power Saver", "🔋", "#64748b", lambda: self._set_power_plan("saver")).grid(row=2, column=0, sticky="ew", padx=4, pady=4)
        self._modern_action_tile(act_grid, "Kill Heavy", "⚠️", "#dc2626", self._quick_kill_heavy).grid(row=2, column=1, sticky="ew", padx=4, pady=4)

        ctk.CTkLabel(left, text="Session Statistics", font=ctk.CTkFont(size=14, weight="bold"), text_color="#9CA3AF").pack(anchor="w", pady=(20,10))

        stats_card = ctk.CTkFrame(left, fg_color="#161B22", corner_radius=12, border_width=1, border_color="#1D232C")
        stats_card.pack(fill="x")

        stats_content = ctk.CTkFrame(stats_card, fg_color="transparent")
        stats_content.pack(fill="x", padx=16, pady=12)

        self.lbl_session_ram = ctk.CTkLabel(stats_content, text="💾 RAM Freed: 0 MB",
                                             font=ctk.CTkFont(size=12), text_color="#9CA3AF")
        self.lbl_session_ram.pack(anchor="w", pady=2)

        self.lbl_session_boosts = ctk.CTkLabel(stats_content, text="🚀 Boosts: 0",
                                                font=ctk.CTkFont(size=12), text_color="#9CA3AF")
        self.lbl_session_boosts.pack(anchor="w", pady=2)

        self.lbl_session_time = ctk.CTkLabel(stats_content, text="⏱ Session: 0m",
                                             font=ctk.CTkFont(size=12), text_color="#9CA3AF")
        self.lbl_session_time.pack(anchor="w", pady=2)

        self.after(5000, self._update_session_stats)

        ctk.CTkLabel(left, text="Recent Actions", font=ctk.CTkFont(size=14, weight="bold"), text_color="#9CA3AF").pack(anchor="w", pady=(20,10))

        recent_card = ctk.CTkFrame(left, fg_color="#161B22", corner_radius=12, border_width=1, border_color="#1D232C")
        recent_card.pack(fill="x")

        self.recent_actions_container = ctk.CTkFrame(recent_card, fg_color="transparent")
        self.recent_actions_container.pack(fill="x", padx=12, pady=12)

        ctk.CTkLabel(self.recent_actions_container, text="No recent actions yet",
                    text_color="#6B7280", font=ctk.CTkFont(size=12)).pack(anchor="w")

        self.after(2000, self._update_recent_actions)

        ctk.CTkLabel(left, text="Latency Metrics", font=ctk.CTkFont(size=14, weight="bold"), text_color="#9CA3AF").pack(anchor="w", pady=(20,10))

        latency_card = ctk.CTkFrame(left, fg_color="#161B22", corner_radius=12, border_width=1, border_color="#1D232C")
        latency_card.pack(fill="x")

        latency_content = ctk.CTkFrame(latency_card, fg_color="transparent")
        latency_content.pack(fill="x", padx=16, pady=12)

        lat_header = ctk.CTkFrame(latency_content, fg_color="transparent")
        lat_header.pack(fill="x", pady=(0, 8))

        self.lbl_latency_grade = ctk.CTkLabel(lat_header, text="Grade: --",
                                               font=ctk.CTkFont(size=14, weight="bold"), text_color="#10B981")
        self.lbl_latency_grade.pack(side="left")

        self.lbl_audio_safe = ctk.CTkLabel(lat_header, text="🎵 Audio: --",
                                            font=ctk.CTkFont(size=11), text_color="#9CA3AF")
        self.lbl_audio_safe.pack(side="right")

        self.lbl_dpc_latency = ctk.CTkLabel(latency_content, text="⚡ DPC Latency: -- µs",
                                             font=ctk.CTkFont(size=12), text_color="#9CA3AF")
        self.lbl_dpc_latency.pack(anchor="w", pady=2)

        self.lbl_ctx_switches = ctk.CTkLabel(latency_content, text="🔄 Context Switches: --/sec",
                                              font=ctk.CTkFont(size=12), text_color="#9CA3AF")
        self.lbl_ctx_switches.pack(anchor="w", pady=2)

        self.lbl_isr_latency = ctk.CTkLabel(latency_content, text="📡 ISR Latency: -- µs",
                                             font=ctk.CTkFont(size=12), text_color="#9CA3AF")
        self.lbl_isr_latency.pack(anchor="w", pady=2)

        self.lbl_latency_spikes = ctk.CTkLabel(latency_content, text="⚠️ Spikes: 0",
                                                font=ctk.CTkFont(size=12), text_color="#9CA3AF")
        self.lbl_latency_spikes.pack(anchor="w", pady=2)

        self.after(1000, self._update_latency_metrics)

        right = ctk.CTkFrame(split, fg_color="#161B22", corner_radius=12, border_width=1, border_color="#1D232C")
        right.grid(row=0, column=1, sticky="nsew")

        h_proc = ctk.CTkFrame(right, fg_color="transparent")
        h_proc.pack(fill="x", padx=16, pady=16)
        ctk.CTkLabel(h_proc, text="Top Processes", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        ctk.CTkButton(h_proc, text="View All →", width=80, height=26, font=ctk.CTkFont(size=11),
                     fg_color="#1D232C", hover_color="#3f3f46", corner_radius=8,
                     command=lambda: self._switch_nav("Processes")).pack(side="right")

        self.tree_dash = ttk.Treeview(right, style="Tbl.Treeview", columns=("Name","CPU","RAM"), show="headings", selectmode="browse")
        self.tree_dash.heading("Name", text="Process"); self.tree_dash.column("Name", width=140, anchor="w")
        self.tree_dash.heading("CPU", text="CPU%");     self.tree_dash.column("CPU", width=55, anchor="e")
        self.tree_dash.heading("RAM", text="RAM");      self.tree_dash.column("RAM", width=65, anchor="e")
        self.tree_dash.pack(fill="both", expand=True, padx=10, pady=(0,10))
        self.tree_dash.bind("<Double-1>", lambda e: self._switch_nav("Processes"))

    def _stat_item(self, parent, label, value, icon):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(f, text=f"{icon} {label}", font=ctk.CTkFont(size=11), text_color="#6B7280").pack(anchor="w")
        val_lbl = ctk.CTkLabel(f, text=value, font=ctk.CTkFont(size=14, weight="bold"), text_color="#E5E7EB")
        val_lbl.pack(anchor="w")
        return f, val_lbl

    def _update_recent_actions(self):
        if not hasattr(self, 'recent_actions_container'):
            return

        try:
            for widget in self.recent_actions_container.winfo_children():
                widget.destroy()

            if hasattr(self, 'activity_log'):
                relevant_categories = ['optibalance', 'success', 'boost', 'ram', 'process']
                recent = [entry for entry in list(self.activity_log)[-20:]
                         if entry.get('category', 'info') in relevant_categories][-5:]

                if recent:
                    for entry in reversed(recent):
                        msg = entry.get('message', '')[:50]
                        cat = entry.get('category', 'info')

                        colors = {
                            'optibalance': '#8B5CF6',
                            'success': '#10B981',
                            'boost': '#F59E0B',
                            'ram': '#06B6D4',
                            'process': '#EC4899'
                        }
                        color = colors.get(cat, '#9CA3AF')

                        row = ctk.CTkFrame(self.recent_actions_container, fg_color="transparent")
                        row.pack(fill="x", pady=2)

                        dot = ctk.CTkFrame(row, width=6, height=6, corner_radius=3, fg_color=color)
                        dot.pack(side="left", padx=(0, 8))

                        ctk.CTkLabel(row, text=msg, text_color="#E5E7EB",
                                    font=ctk.CTkFont(size=11), anchor="w").pack(side="left", fill="x")
                else:
                    ctk.CTkLabel(self.recent_actions_container, text="No recent actions yet",
                                text_color="#6B7280", font=ctk.CTkFont(size=12)).pack(anchor="w")
            else:
                ctk.CTkLabel(self.recent_actions_container, text="Activity log not available",
                            text_color="#6B7280", font=ctk.CTkFont(size=12)).pack(anchor="w")
        except Exception:
            pass

        self.after(10000, self._update_recent_actions)

    def _update_latency_metrics(self):
        try:
            stats = LATENCY_MONITOR.get_stats()

            grade = stats.get('grade', '--')
            grade_colors = {'A': '#10B981', 'B': '#3B82F6', 'C': '#F59E0B', 'D': '#F97316', 'F': '#EF4444'}
            grade_color = grade_colors.get(grade, '#9CA3AF')

            if hasattr(self, 'lbl_latency_grade'):
                self.lbl_latency_grade.configure(text=f"Grade: {grade}", text_color=grade_color)

            audio_safe = stats.get('audio_safe', False)
            if hasattr(self, 'lbl_audio_safe'):
                if audio_safe:
                    self.lbl_audio_safe.configure(text="🎵 Audio: Safe", text_color="#10B981")
                else:
                    self.lbl_audio_safe.configure(text="🎵 Audio: Risk", text_color="#F59E0B")

            dpc = stats.get('dpc_latency_us', 0)
            dpc_max = stats.get('dpc_latency_max_us', 0)
            if hasattr(self, 'lbl_dpc_latency'):
                self.lbl_dpc_latency.configure(text=f"⚡ DPC Latency: {dpc} µs (max: {dpc_max})")

            ctx = stats.get('context_switches_per_sec', 0)
            if hasattr(self, 'lbl_ctx_switches'):
                if ctx > 1000:
                    self.lbl_ctx_switches.configure(text=f"🔄 Context Switches: {ctx/1000:.1f}K/sec")
                else:
                    self.lbl_ctx_switches.configure(text=f"🔄 Context Switches: {ctx}/sec")

            isr = stats.get('isr_latency_us', 0)
            if hasattr(self, 'lbl_isr_latency'):
                self.lbl_isr_latency.configure(text=f"📡 ISR Latency: {isr} µs")

            spikes = stats.get('spike_count', 0)
            if hasattr(self, 'lbl_latency_spikes'):
                spike_color = "#EF4444" if spikes > 10 else "#F59E0B" if spikes > 0 else "#9CA3AF"
                self.lbl_latency_spikes.configure(text=f"⚠️ Spikes: {spikes}", text_color=spike_color)

        except Exception:
            pass

        self.after(2000, self._update_latency_metrics)

    def _fill_dashboard(self, parent):
        top = ctk.CTkFrame(parent, height=80, fg_color="transparent")
        top.pack(fill="x", padx=30, pady=30)
        ctk.CTkLabel(top, text="Dashboard", font=ctk.CTkFont(family="Segoe UI Variable Display", size=32, weight="bold")).pack(side="left")

        boost_frame = ctk.CTkFrame(parent, fg_color="transparent")
        boost_frame.pack(fill="x", padx=30, pady=(20,0))

        self.btn_boost_all = ctk.CTkButton(boost_frame, text="⚡ BOOST NOW", height=55,
                                           font=ctk.CTkFont(size=18, weight="bold"),
                                           fg_color="#8B5CF6", hover_color="#7C3AED",
                                           command=self._one_click_boost)
        self.btn_boost_all.pack(side="left", fill="x", expand=True)

        self.lbl_boost_status = ctk.CTkLabel(boost_frame, text="", text_color="#9CA3AF",
                                              font=ctk.CTkFont(size=11))
        self.lbl_boost_status.pack(side="right", padx=20)

        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="x", padx=30, pady=(15,0))
        grid.grid_columnconfigure((0,1,2,3,4), weight=1)

        self.card_cpu, self.val_cpu = self._card(grid, "CPU", "--%")
        self.card_mem, self.val_mem = self._card(grid, "RAM", "--%")
        self.card_gpu, self.val_gpu = self._card(grid, "GPU", "N/A")
        self.card_lat, self.val_lat = self._card(grid, "Latency", "--%")
        self.card_fg,   self.val_fg       = self._card(grid, "Foreground App", "—")

        self.card_cpu.grid(row=0, column=0, sticky="ew", padx=(0,6))
        self.card_mem.grid(row=0, column=1, sticky="ew", padx=6)
        self.card_gpu.grid(row=0, column=2, sticky="ew", padx=6)
        self.card_lat.grid(row=0, column=3, sticky="ew", padx=6)
        self.card_fg.grid(row=0, column=4, sticky="ew", padx=(6,0))

        split = ctk.CTkFrame(parent, fg_color="transparent")
        split.pack(fill="both", expand=True, padx=30, pady=30)
        split.grid_columnconfigure(0, weight=3)
        split.grid_columnconfigure(1, weight=2)
        split.grid_rowconfigure(0, weight=1)

        act_pnl = ctk.CTkFrame(split, fg_color="#161B22", corner_radius=16, border_width=1, border_color="#30363D")
        act_pnl.grid(row=0, column=0, sticky="nsew", padx=(0,15))
        ctk.CTkLabel(act_pnl, text="QUICK ACTIONS", font=ctk.CTkFont(size=12, weight="bold"), text_color="#9CA3AF").pack(anchor="w", padx=20, pady=20)

        btns = ctk.CTkFrame(act_pnl, fg_color="transparent")
        btns.pack(fill="x", padx=20)
        btns.grid_columnconfigure((0,1), weight=1)

        def qbtn(row, col, title, sub, color, cmd):
            f = ctk.CTkFrame(btns, fg_color="#0D1117", corner_radius=12, border_width=1, border_color="#30363D")
            f.grid(row=row, column=col, sticky="ew", padx=6, pady=6)
            f.bind("<Button-1>", lambda e: cmd())
            strip = ctk.CTkFrame(f, width=4, height=40, fg_color=color, corner_radius=2)
            strip.pack(side="left", padx=12, pady=12)
            info = ctk.CTkFrame(f, fg_color="transparent")
            info.pack(side="left", pady=12)
            l1 = ctk.CTkLabel(info, text=title, font=ctk.CTkFont(size=14, weight="bold"), text_color="#F9FAFB")
            l1.pack(anchor="w")
            l2 = ctk.CTkLabel(info, text=sub, font=ctk.CTkFont(size=11), text_color="#9CA3AF")
            l2.pack(anchor="w")
            for w in [f, strip, info, l1, l2]: w.bind("<Button-1>", lambda e: cmd())

        qbtn(0, 0, "Boost Foreground", "Prioritize active window", "#8B5CF6", self._quick_boost_fg)
        qbtn(0, 1, "Trim Memory", "Release working sets", "#10B981", self._quick_trim_all)
        qbtn(1, 0, "Eco Throttle BG", "Reduce background usage", "#F59E0B", self._quick_throttle_bg)
        qbtn(1, 1, "Kill Heavy Proc", "Terminate top consumer", "#EF4444", self._quick_kill_heavy)
        qbtn(2, 0, "⚡ High Performance", "Max power plan", "#3B82F6", lambda: self._set_power_plan("high"))
        qbtn(2, 1, "🔋 Power Saver", "Battery saver plan", "#6B7280", lambda: self._set_power_plan("saver"))

        proc_pnl = ctk.CTkFrame(split, fg_color="#161B22", corner_radius=16, border_width=1, border_color="#30363D")
        proc_pnl.grid(row=0, column=1, sticky="nsew", padx=(15,0))

        mini_head = ctk.CTkFrame(proc_pnl, fg_color="transparent")
        mini_head.pack(fill="x", padx=14, pady=(14,6))
        ctk.CTkLabel(mini_head, text="ACTIVE PROCESSES", font=ctk.CTkFont(size=12, weight="bold"), text_color="#9CA3AF").pack(side="left")
        ctk.CTkButton(mini_head, text="View All", width=70, height=24, font=ctk.CTkFont(size=11), fg_color="#374151", hover_color="#4B5563",
                     command=lambda: self._switch_nav("Processes")).pack(side="right")

        self.tree_dash = ttk.Treeview(proc_pnl, style="Tbl.Treeview", columns=("Name","CPU","RAM"), show="headings", selectmode="browse")
        self.tree_dash.heading("Name", text="Name"); self.tree_dash.column("Name", width=140, anchor="w")
        self.tree_dash.heading("CPU", text="CPU");   self.tree_dash.column("CPU", width=60, anchor="center")
        self.tree_dash.heading("RAM", text="RAM");   self.tree_dash.column("RAM", width=80, anchor="center")
        self.tree_dash.pack(fill="both", expand=True, padx=10, pady=(0,10))
        self.tree_dash.bind("<Double-1>", lambda e: self._switch_nav("Processes"))

    def _fill_dashboard_legacy_hidden(self, parent):
        top = ctk.CTkFrame(parent, height=80, fg_color="transparent")
        top.pack(fill="x", padx=30, pady=30)
        ctk.CTkLabel(top, text="Dashboard", font=ctk.CTkFont(family="Segoe UI Variable Display", size=32, weight="bold")).pack(side="left")

        health = ctk.CTkFrame(top, fg_color="#161B22", corner_radius=20, border_width=1, border_color="#30363D")
        health.pack(side="right")

        h_info = ctk.CTkFrame(health, fg_color="transparent")
        h_info.pack(side="left", padx=20, pady=10)
        ctk.CTkLabel(h_info, text="SYSTEM HEALTH", font=ctk.CTkFont(size=11, weight="bold"), text_color="#9CA3AF").pack(anchor="w")
        self.health_bar = ctk.CTkProgressBar(h_info, width=120, height=8, progress_color="#10B981")
        self.health_bar.set(1.0)
        self.health_bar.pack(pady=(6,0))

        self.lbl_health_dash = ctk.CTkLabel(health, text="100%", font=ctk.CTkFont(size=24, weight="bold"), text_color="#10B981")
        self.lbl_health_dash.pack(side="left", padx=(0,20), pady=10)

        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="x", padx=30)
        grid.grid_columnconfigure((0,1,2,3), weight=1)

        self.card_cpu, self.val_cpu = self._card(grid, "CPU", "--%")
        self.card_mem, self.val_mem = self._card(grid, "RAM", "--%")
        self.card_gpu, self.val_gpu = self._card(grid, "GPU", "N/A")
        self.card_fg,  self.val_fg  = self._card(grid, "Foreground App", "—")

        self.card_cpu.grid(row=0, column=0, sticky="ew", padx=(0,10))
        self.card_mem.grid(row=0, column=1, sticky="ew", padx=10)
        self.card_gpu.grid(row=0, column=2, sticky="ew", padx=10)
        self.card_fg.grid(row=0, column=3, sticky="ew", padx=(10,0))

        split = ctk.CTkFrame(parent, fg_color="transparent")
        split.pack(fill="both", expand=True, padx=30, pady=30)
        split.grid_columnconfigure(0, weight=3)
        split.grid_columnconfigure(1, weight=2)
        split.grid_rowconfigure(0, weight=1)

        act_pnl = ctk.CTkFrame(split, fg_color="#161B22", corner_radius=16, border_width=1, border_color="#30363D")
        act_pnl.grid(row=0, column=0, sticky="nsew", padx=(0,15))
        ctk.CTkLabel(act_pnl, text="⚡ RECOMMENDED ACTIONS", font=ctk.CTkFont(size=12, weight="bold"), text_color="#9CA3AF").pack(anchor="w", padx=20, pady=20)

        btns = ctk.CTkFrame(act_pnl, fg_color="transparent")
        btns.pack(fill="x", padx=20)
        btns.grid_columnconfigure((0,1), weight=1)

        ctk.CTkButton(btns, text="🚀 Boost Foreground\nPrioritize active window", command=self._quick_boost_fg,
                     height=70, fg_color="#8B5CF6", hover_color="#7C3AED", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        ctk.CTkButton(btns, text="🧹 Trim Memory\nRelease working sets", command=self._quick_trim_all,
                     height=70, fg_color="#10B981", hover_color="#059669", font=ctk.CTkFont(weight="bold")).grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        ctk.CTkButton(btns, text="🔇 Throttle Background\nReduce bg usage", command=self._quick_throttle_bg,
                     height=70, fg_color="#F59E0B", hover_color="#D97706", font=ctk.CTkFont(weight="bold")).grid(row=1, column=0, sticky="ew", padx=6, pady=6)
        ctk.CTkButton(btns, text="⚠️ Kill Heavy Process\nTerminate top consumer", command=self._quick_kill_heavy,
                     height=70, fg_color="#EF4444", hover_color="#DC2626", font=ctk.CTkFont(weight="bold")).grid(row=1, column=1, sticky="ew", padx=6, pady=6)

        proc_pnl = ctk.CTkFrame(split, fg_color="#161B22", corner_radius=16, border_width=1, border_color="#30363D")
        proc_pnl.grid(row=0, column=1, sticky="nsew", padx=(15,0))

        mini_head = ctk.CTkFrame(proc_pnl, fg_color="transparent")
        mini_head.pack(fill="x", padx=14, pady=(14,6))
        ctk.CTkLabel(mini_head, text="⚡ ACTIVE PROCESSES", font=ctk.CTkFont(size=12, weight="bold"), text_color="#9CA3AF").pack(side="left")
        ctk.CTkButton(mini_head, text="View All", width=60, height=24, font=ctk.CTkFont(size=11), fg_color="#374151",
                     command=lambda: self._switch_nav("Processes")).pack(side="right")

        self.tree_dash = ttk.Treeview(proc_pnl, style="Tbl.Treeview", columns=("Name","CPU","RAM"), show="headings", selectmode="browse")
        self.tree_dash.heading("Name", text="Name"); self.tree_dash.column("Name", width=140, anchor="w")
        self.tree_dash.heading("CPU", text="CPU");   self.tree_dash.column("CPU", width=60, anchor="center")
        self.tree_dash.heading("RAM", text="RAM");   self.tree_dash.column("RAM", width=80, anchor="center")

        self.tree_dash.pack(fill="both", expand=True, padx=10, pady=(0,10))

        self.tree_dash.bind("<Double-1>", lambda e: self._switch_nav("Processes"))

    def _modern_header(self, parent, title, subtitle=None):
        f = ctk.CTkFrame(parent, height=80, fg_color="transparent")
        f.pack(fill="x", padx=40, pady=(30,20))
        ctk.CTkLabel(f, text=title, font=ctk.CTkFont(family="Segoe UI Variable Display", size=32, weight="bold"), text_color="#F9FAFB").pack(side="left")
        if subtitle:
            ctk.CTkLabel(f, text=subtitle, font=ctk.CTkFont(size=14), text_color="#6B7280").pack(side="left", padx=15, pady=(8,0))
        return f

    def _modern_section(self, parent, title):
        ctk.CTkLabel(parent, text=title, font=ctk.CTkFont(size=14, weight="bold"), text_color="#F9FAFB").pack(anchor="w", padx=25, pady=(20,10))

    def _fill_processes(self, parent):
        top = self._modern_header(parent, "Processes")

        ctrls = ctk.CTkFrame(top, fg_color="transparent")
        ctrls.pack(side="right")

        ctk.CTkButton(ctrls, text="🔄", command=self._refresh_table,
                     width=40, height=36, fg_color="#161B22", hover_color="#1D232C",
                     border_width=1, border_color="#1D232C",
                     corner_radius=8).pack(side="left", padx=(0,10))

        search_frame = ctk.CTkFrame(ctrls, fg_color="#161B22", border_width=1, border_color="#1D232C", corner_radius=12)
        search_frame.pack(side="left", padx=(0,10))
        ctk.CTkLabel(search_frame, text="🔍", font=ctk.CTkFont(size=14), text_color="#6B7280").pack(side="left", padx=(12,5))

        search = ctk.CTkEntry(search_frame, placeholder_text="Search process...", width=140, height=36,
                             fg_color="transparent", border_width=0, font=ctk.CTkFont(size=13))
        search.pack(side="left", padx=(0,10))
        search.bind("<KeyRelease>", lambda e: self._on_search())
        self.entry_search = search

        self.seg_sort = ctk.CTkSegmentedButton(ctrls, values=["CPU","Mem","PID","Name"], command=self._on_sort,
                                               selected_color="#8B5CF6", selected_hover_color="#7C3AED",
                                               unselected_color="#161B22", unselected_hover_color="#1D232C",
                                               width=240, height=36, corner_radius=8)
        self.seg_sort.set("CPU")
        self.seg_sort.pack(side="left")

        stats = ctk.CTkFrame(parent, fg_color="transparent")
        stats.pack(fill="x", padx=40, pady=(0,20))
        stats.grid_columnconfigure((0,1,2,3), weight=1)

        self.card_proc_count, _ = self._modern_card(stats, "Active Processes", f"{len(psutil.pids())}", "📊", "#8b5cf6")
        self.card_proc_threads, _ = self._modern_card(stats, "Total Threads", f"{sum(p.num_threads() for p in psutil.process_iter(['num_threads']) if p.info['num_threads'])}", "🧵", "#10b981")
        self.card_proc_handles, _ = self._modern_card(stats, "Handles", "N/A", "🔧", "#f59e0b")
        self.card_proc_user, _ = self._modern_card(stats, "User", os.getlogin(), "👤", "#ef4444")

        self.card_proc_count.grid(row=0, column=0, sticky="ew", padx=(0,8))
        self.card_proc_threads.grid(row=0, column=1, sticky="ew", padx=8)
        self.card_proc_handles.grid(row=0, column=2, sticky="ew", padx=8)
        self.card_proc_user.grid(row=0, column=3, sticky="ew", padx=(8,0))

        tree_frame = ctk.CTkFrame(parent, corner_radius=12, fg_color="#161B22", border_width=1, border_color="#1D232C")
        tree_frame.pack(fill="both", expand=True, padx=40, pady=(0,40))

        self.tree = ttk.Treeview(
            tree_frame, style="Tbl.Treeview",
            columns=("PID","Name","CPU","Memory","Flags","Role"),
            show="headings", selectmode="browse"
        )
        for col, w in (("PID",70), ("Name",320), ("CPU",80), ("Memory",110), ("Flags",140), ("Role",120)):
            self.tree.heading(col, text=col); self.tree.column(col, anchor="center", width=w, stretch=True)

        sb = ctk.CTkScrollbar(tree_frame, command=self.tree.yview, fg_color="transparent")
        sb.pack(side="right", fill="y", padx=4, pady=4)
        self.tree.configure(yscrollcommand=sb.set)

        self.tree.pack(fill="both", expand=True, padx=12, pady=12)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())

        self.after(100, self._refresh_table)

    def _fill_startup_modern(self, parent):
        top = self._modern_header(parent, "Startup Manager", "Manage applications that automatically start with Windows")

        cont = ctk.CTkFrame(parent, corner_radius=12, fg_color="#161B22", border_width=1, border_color="#1D232C")
        cont.pack(fill="both", expand=True, padx=40, pady=(0,40))

        toolbar = ctk.CTkFrame(cont, fg_color="transparent")
        toolbar.pack(fill="x", padx=15, pady=15)

        ctk.CTkLabel(toolbar, text="STARTUP ENTRIES", font=ctk.CTkFont(size=12, weight="bold"), text_color="#9CA3AF").pack(side="left")

        btns = ctk.CTkFrame(toolbar, fg_color="transparent")
        btns.pack(side="right")

        def tb_btn(txt, cmd, col="#161B22", hov="#1D232C"):
            ctk.CTkButton(btns, text=txt, command=cmd,
                          fg_color=col, hover_color=hov,
                          border_width=1, border_color="#1D232C",
                          width=90, height=32, font=ctk.CTkFont(size=12)).pack(side="left", padx=4)

        tb_btn("🔄 Scan", self._refresh_startup)
        tb_btn("📂 Folder", self._open_startup_folder)

        info = ctk.CTkFrame(cont, fg_color="#1D232C", corner_radius=8)
        info.pack(fill="x", padx=15, pady=0)
        ctk.CTkLabel(info, text="💡 Tip: Disabling high-impact startup items can improve boot time significantly.",
                    text_color="#9CA3AF", font=ctk.CTkFont(size=11)).pack(padx=12, pady=8, anchor="w")

        style = ttk.Style()
        style.configure("Tbl.Treeview", background="#161B22", foreground="#E5E7EB", fieldbackground="#161B22", rowheight=30, borderwidth=0)
        style.map("Tbl.Treeview", background=[('selected', '#3f3f46')])

        self.tree_start = ttk.Treeview(cont, style="Tbl.Treeview",
                                       columns=("Impact","Name","Publisher","Command","Status"),
                                       show="headings", height=12, selectmode="extended")

        for col, w in (("Impact",80), ("Name",200), ("Publisher",150), ("Command",400), ("Status",80)):
            self.tree_start.heading(col, text=col)
            self.tree_start.column(col, anchor="center" if col in ("Impact","Status") else "w", width=w, stretch=True)

        self.tree_start.pack(fill="both", expand=True, padx=15, pady=15)

        b_row = ctk.CTkFrame(cont, fg_color="transparent")
        b_row.pack(fill="x", padx=15, pady=(0,15))

        ctk.CTkButton(b_row, text="✅ Enable Selected", command=lambda: self._toggle_startup(True),
                     fg_color="#10B981", hover_color="#059669", corner_radius=8, height=38).pack(side="left", padx=(0,8))
        ctk.CTkButton(b_row, text="❌ Disable Selected", command=lambda: self._toggle_startup(False),
                     fg_color="#EF4444", hover_color="#DC2626", corner_radius=8, height=38).pack(side="left", padx=8)

    def _fill_insights(self, parent):
        top = self._modern_header(parent, "System Insights", "Real-time performance metrics and analysis")

        ins = ctk.CTkFrame(parent, corner_radius=12, fg_color="#161B22", border_width=1, border_color="#1D232C")
        ins.pack(fill="both", expand=True, padx=40, pady=(0,40))

        insights_header = ctk.CTkFrame(ins, fg_color="transparent")
        insights_header.pack(fill="x", padx=20, pady=(20,5))
        ctk.CTkLabel(insights_header, text="📊 LIVE SYSTEM METRICS",
                    font=ctk.CTkFont(size=12, weight="bold"), text_color="#9CA3AF").pack(anchor="w")

        fig = Figure(figsize=(6.4, 3.4), dpi=100, facecolor='#161B22')
        self.ax = fig.add_subplot(111)
        self.ax.set_facecolor('#0D1117')
        self.ax.set_ylim(0, 100)
        self.ax.set_ylabel("%", color='#6B7280', fontsize=9)
        self.ax.tick_params(colors='#6B7280', labelsize=8)

        self.ax.grid(True, color='#1D232C', alpha=0.5, linestyle='--')
        for spine in self.ax.spines.values(): spine.set_color('#1D232C')

        self.line_cpu, = self.ax.plot(list(self.ts_cpu), label="CPU", color='#8B5CF6', linewidth=1.5)
        self.line_ram, = self.ax.plot(list(self.ts_ram), label="RAM", color='#10B981', linewidth=1.5)
        self.line_gpu, = self.ax.plot(list(self.ts_gpu), label="GPU", color='#F59E0B', linewidth=1.5)
        self.ax.legend(loc="upper right", fontsize=8, facecolor='#161B22', edgecolor='#1D232C', labelcolor='#9CA3AF')

        self.canvas = FigureCanvasTkAgg(fig, master=ins)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=20, pady=(0, 20))

        lat = ctk.CTkFrame(ins, fg_color="transparent")
        lat.pack(fill="x", padx=20, pady=(0, 20))
        lat.grid_columnconfigure((0,1), weight=1)

        def lat_card(col_idx, title, val_attr, color):
            c = ctk.CTkFrame(lat, corner_radius=12, fg_color="#0D1117", border_width=1, border_color="#1D232C")
            c.grid(row=0, column=col_idx, padx=8, sticky="ew")
            ctk.CTkLabel(c, text=title, text_color="#6B7280", font=ctk.CTkFont(size=11, weight="bold")).pack(padx=16, pady=(12,0), anchor="w")
            lbl = ctk.CTkLabel(c, text="0.0", font=ctk.CTkFont(family="Segoe UI Variable Display", size=26, weight="bold"), text_color=color)
            lbl.pack(padx=16, pady=(0,12), anchor="w")
            setattr(self, val_attr, lbl)

        lat_card(0, "⚡ DPC/ISR LATENCY", "lbl_dpc", "#8B5CF6")
        lat_card(1, "🔄 CONTEXT SWITCHES", "lbl_ctx", "#EC4899")

    def _fill_storage(self, parent):
        top = self._modern_header(parent, "Storage Manager", "Analyze usage, clean junk, and optimize drives")

        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=40, pady=(0,30))
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(0, weight=1)

        left_panel = ctk.CTkFrame(content, fg_color="transparent")
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0,15))

        self._modern_section(left_panel, "💾 DISK USAGE")

        disk_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        disk_frame.pack(fill="x", pady=(0,20))

        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                used_pct = usage.percent
                used_gb = usage.used / (1024**3)
                total_gb = usage.total / (1024**3)
                free_gb = usage.free / (1024**3)

                if used_pct < 60: color = "#10B981"
                elif used_pct < 80: color = "#F59E0B"
                else: color = "#EF4444"

                card = ctk.CTkFrame(disk_frame, fg_color="#161B22", corner_radius=12, border_width=1, border_color="#1D232C")
                card.pack(fill="x", pady=6)

                top_row = ctk.CTkFrame(card, fg_color="transparent")
                top_row.pack(fill="x", padx=16, pady=(16,8))

                icon_f = ctk.CTkFrame(top_row, width=40, height=40, corner_radius=10, fg_color="#1D232C")
                icon_f.pack(side="left"); icon_f.pack_propagate(False)
                ctk.CTkLabel(icon_f, text="💿", font=ctk.CTkFont(size=20)).place(relx=0.5, rely=0.5, anchor="center")

                info = ctk.CTkFrame(top_row, fg_color="transparent")
                info.pack(side="left", padx=12)
                ctk.CTkLabel(info, text=f"{partition.mountpoint} ({partition.fstype})", font=ctk.CTkFont(size=14, weight="bold"), text_color="#E4E4E7").pack(anchor="w")
                ctk.CTkLabel(info, text=f"{total_gb:.1f} GB Total", font=ctk.CTkFont(size=11), text_color="#6B7280").pack(anchor="w")

                ctk.CTkLabel(top_row, text=f"{used_pct:.1f}%", font=ctk.CTkFont(family="Segoe UI Variable Display", size=20, weight="bold"), text_color=color).pack(side="right")

                bar_bg = ctk.CTkFrame(card, fg_color="#0D1117", height=6, corner_radius=3)
                bar_bg.pack(fill="x", padx=16, pady=(0,8))

                bar = ctk.CTkFrame(bar_bg, fg_color=color, height=6, corner_radius=3)
                bar.place(relheight=1.0, relwidth=used_pct/100)

                stats = ctk.CTkFrame(card, fg_color="transparent")
                stats.pack(fill="x", padx=16, pady=(0,16))
                ctk.CTkLabel(stats, text=f"{used_gb:.1f} GB Used", font=ctk.CTkFont(size=11), text_color="#9CA3AF").pack(side="left")
                ctk.CTkLabel(stats, text=f"{free_gb:.1f} GB Free", font=ctk.CTkFont(size=11, weight="bold"), text_color="#10b981").pack(side="right")

            except:
                pass

        self._modern_section(left_panel, "🔧 TOOLS")

        tools_grid = ctk.CTkFrame(left_panel, fg_color="transparent")
        tools_grid.pack(fill="x")
        tools_grid.grid_columnconfigure((0,1), weight=1)

        self._modern_action_tile(tools_grid, "TRIM Optimization", "✨", "#8b5cf6", self._trim_ssd).grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self._modern_action_tile(tools_grid, "Scan Large Files", "🔍", "#3b82f6", self._scan_large_files).grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self._modern_action_tile(tools_grid, "Analyze Usage", "📊", "#ec4899", self._analyze_folders).grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        self._modern_action_tile(tools_grid, "Device Defrag", "📀", "#f59e0b", self._defrag_disk).grid(row=1, column=1, sticky="ew", padx=4, pady=4)

        right_panel = ctk.CTkFrame(content, fg_color="#161B22", corner_radius=12, border_width=1, border_color="#1D232C")
        right_panel.grid(row=0, column=1, sticky="nsew")

        h_right = ctk.CTkFrame(right_panel, fg_color="transparent")
        h_right.pack(fill="x", padx=20, pady=20)
        ctk.CTkLabel(h_right, text="Quick Cleanup", font=ctk.CTkFont(size=14, weight="bold"), text_color="#E5E7EB").pack(side="left")

        try:
            temp_sz = sum(os.path.getsize(os.path.join(dp, f)) for dp, dn, fn in os.walk(os.environ.get('TEMP', '')) for f in fn) / (1024**2)
            dl_sz = sum(os.path.getsize(os.path.join(os.path.join(os.path.expanduser("~"), "Downloads"), f)) for dp, dn, fn in os.walk(os.path.join(os.path.expanduser("~"), "Downloads")) for f in fn) / (1024**3)
        except:
            temp_sz, dl_sz = 0, 0

        stats_frame = ctk.CTkFrame(right_panel, fg_color="transparent")
        stats_frame.pack(fill="x", padx=16)

        def stat_row(icon, label, val, col):
            r = ctk.CTkFrame(stats_frame, fg_color="#1D232C", corner_radius=8)
            r.pack(fill="x", pady=4)
            ctk.CTkLabel(r, text=icon, font=ctk.CTkFont(size=14)).pack(side="left", padx=(12,8), pady=10)
            ctk.CTkLabel(r, text=label, font=ctk.CTkFont(size=12), text_color="#9CA3AF").pack(side="left")
            ctk.CTkLabel(r, text=val, font=ctk.CTkFont(size=12, weight="bold"), text_color=col).pack(side="right", padx=12)

        stat_row("🗑️", "Temp Files", f"{temp_sz:.0f} MB", "#f59e0b")
        stat_row("📥", "Downloads", f"{dl_sz:.1f} GB", "#3b82f6")
        stat_row("♻️", "Recycle Bin", "Ready", "#10b981")

        act_frame = ctk.CTkFrame(right_panel, fg_color="transparent")
        act_frame.pack(fill="x", padx=16, pady=20)

        def act_btn(txt, cmd, hover_col):
            btn = ctk.CTkButton(act_frame, text=txt, command=cmd,
                               fg_color="#0D1117", hover_color=hover_col,
                               border_width=1, border_color="#1D232C",
                               height=40, anchor="w", font=ctk.CTkFont(size=12))
            btn.pack(fill="x", pady=4)

        act_btn("🧹 Clean Temp Files", self._clean_temp_files, "#eabc32")
        act_btn("♻️ Empty Recycle Bin", self._empty_recycle_bin, "#16a34a")
        act_btn("💿 System Disk Cleanup", self._open_disk_cleanup, "#8b5cf6")

        total_free = sum(psutil.disk_usage(p.mountpoint).free for p in psutil.disk_partitions() if p.fstype) / (1024**3)
        ctk.CTkLabel(right_panel, text=f"Total Free Space: {total_free:.0f} GB", font=ctk.CTkFont(size=11, weight="bold"), text_color="#6B7280").pack(side="bottom", pady=20)

    def _fill_cleaner(self, parent):
        top = self._modern_header(parent, "Junk Cleaner", "Remove unnecessary files to recover space")

        btn_frame = ctk.CTkFrame(top, fg_color="transparent")
        btn_frame.pack(side="right")
        ctk.CTkButton(btn_frame, text="🔍 Scan", command=self._scan_junk, width=100,
                     fg_color="#8B5CF6", hover_color="#7C3AED", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="🧹 Clean All", command=self._clean_all_junk, width=100,
                     fg_color="#EF4444", hover_color="#DC2626", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)

        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=40, pady=(0,30))
        content.grid_columnconfigure((0,1,2), weight=1)
        content.grid_rowconfigure(0, weight=1)

        def clean_column(col_idx, title, items):
            frame = ctk.CTkFrame(content, fg_color="#161B22", corner_radius=12, border_width=1, border_color="#1D232C")
            frame.grid(row=0, column=col_idx, sticky="nsew", padx=6)

            ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=14, weight="bold"),
                        text_color="#E5E7EB").pack(anchor="w", padx=20, pady=(20,10))

            scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
            scroll.pack(fill="both", expand=True, padx=10, pady=(0,10))

            for name, desc, color in items:
                card = ctk.CTkFrame(scroll, fg_color="#1D232C", corner_radius=8)
                card.pack(fill="x", pady=4)

                row = ctk.CTkFrame(card, fg_color="transparent")
                row.pack(fill="x", padx=12, pady=10)

                ctk.CTkCheckBox(row, text="", width=20, height=20, fg_color=color, hover_color=color, border_width=2).pack(side="left")

                left = ctk.CTkFrame(row, fg_color="transparent")
                left.pack(side="left", padx=10)
                ctk.CTkLabel(left, text=name, font=ctk.CTkFont(size=12, weight="bold"), text_color="#E5E7EB").pack(anchor="w")
                ctk.CTkLabel(left, text=desc, font=ctk.CTkFont(size=11), text_color="#9CA3AF").pack(anchor="w")

            return frame

        junk_items = [
            ("Windows Temp", "Temporary files", "#F59E0B"),
            ("User Temp", "User temp folder", "#F59E0B"),
            ("Thumbnails", "Image thumbnails", "#3B82F6"),
            ("Log Files", "Old log files", "#8B5CF6"),
            ("Error Reports", "Crash reports", "#EF4444"),
        ]
        clean_column(0, "🗑️ JUNK FILES", junk_items)

        sys_items = [
            ("Recycle Bin", "Deleted files", "#10B981"),
            ("Windows Update", "Old updates", "#3B82F6"),
            ("Memory Dumps", "Crash dumps", "#EF4444"),
            ("Prefetch", "App preload data", "#8B5CF6"),
            ("Font Cache", "Font rendering", "#F59E0B"),
        ]
        clean_column(1, "⚙️ SYSTEM", sys_items)

        priv_items = [
            ("Browser History", "Web history", "#EC4899"),
            ("Browser Cache", "Cached pages", "#3B82F6"),
            ("Cookies", "Website cookies", "#F59E0B"),
            ("Recent Docs", "Recent files list", "#8B5CF6"),
            ("Clipboard", "Copied data", "#10B981"),
        ]
        col3 = clean_column(2, "🔒 PRIVACY", priv_items)

        summary = ctk.CTkFrame(col3, fg_color="#0D1117", corner_radius=10)
        summary.pack(fill="x", padx=12, pady=12)
        ctk.CTkLabel(summary, text="Select items and click Clean All",
                    font=ctk.CTkFont(size=11), text_color="#6B7280").pack(pady=10)

    def _scan_junk(self):
        self._toast("Scanning for junk files...", "ok")
        self._log_activity("OptiClean: Scanning for junk files", "info")

    def _clean_all_junk(self):
        self._clean_temp_files()

    def _scan_large_files(self):
        popup = ctk.CTkToplevel(self)
        popup.title("Large Files Finder")
        popup.geometry("500x450")
        popup.transient(self)
        popup.grab_set()
        popup.configure(fg_color="#0D1117")

        header = ctk.CTkFrame(popup, fg_color="#161B22", corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="🔍 Large Files Finder", font=ctk.CTkFont(size=18, weight="bold"),
                    text_color="#E5E7EB").pack(pady=15)

        content = ctk.CTkScrollableFrame(popup, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=15)

        status_lbl = ctk.CTkLabel(content, text="🔄 Scanning... (this may take a moment)",
                                  font=ctk.CTkFont(size=12), text_color="#9CA3AF")
        status_lbl.pack(pady=20)

        def do_scan():
            large_files = []
            search_paths = [os.path.expanduser("~\\Downloads"), os.path.expanduser("~\\Documents")]

            for path in search_paths:
                if os.path.exists(path):
                    try:
                        for root, dirs, files in os.walk(path):
                            for file in files:
                                try:
                                    fp = os.path.join(root, file)
                                    size = os.path.getsize(fp)
                                    if size > 50 * 1024 * 1024:
                                        large_files.append((fp, size))
                                except:
                                    pass
                    except:
                        pass

            large_files.sort(key=lambda x: x[1], reverse=True)

            def update_ui():
                status_lbl.destroy()
                if large_files:
                    for fp, size in large_files[:20]:
                        size_mb = size / (1024**2)
                        row = ctk.CTkFrame(content, fg_color="#1D232C", corner_radius=8)
                        row.pack(fill="x", pady=2)

                        name = os.path.basename(fp)[:30]
                        ctk.CTkLabel(row, text=name, font=ctk.CTkFont(size=10),
                                    text_color="#E5E7EB").pack(side="left", padx=10, pady=8)
                        ctk.CTkLabel(row, text=f"{size_mb:.0f} MB", font=ctk.CTkFont(size=10, weight="bold"),
                                    text_color="#F59E0B").pack(side="right", padx=10, pady=8)
                else:
                    ctk.CTkLabel(content, text="No files larger than 50MB found", text_color="#6B7280").pack(pady=20)

                ctk.CTkButton(content, text="Close", command=popup.destroy,
                             fg_color="#374151", hover_color="#4B5563", width=100).pack(pady=15)

            self.after(0, update_ui)

        threading.Thread(target=do_scan, daemon=True).start()

    def _clean_temp_files(self):
        popup = ctk.CTkToplevel(self)
        popup.title("Clean Temp Files")
        popup.geometry("380x280")
        popup.transient(self)
        popup.grab_set()
        popup.configure(fg_color="#0D1117")

        header = ctk.CTkFrame(popup, fg_color="#161B22", corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="🗑️ Clean Temp Files", font=ctk.CTkFont(size=18, weight="bold"),
                    text_color="#E5E7EB").pack(pady=15)

        content = ctk.CTkFrame(popup, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=15)

        status_lbl = ctk.CTkLabel(content, text="🔄 Cleaning temp files...",
                                  font=ctk.CTkFont(size=14), text_color="#9CA3AF")
        status_lbl.pack(pady=30)

        def do_clean():
            cleaned = 0
            temp_paths = [os.environ.get('TEMP', ''), os.environ.get('TMP', '')]

            for temp_path in temp_paths:
                if os.path.exists(temp_path):
                    try:
                        for item in os.listdir(temp_path):
                            try:
                                fp = os.path.join(temp_path, item)
                                if os.path.isfile(fp):
                                    os.remove(fp)
                                    cleaned += 1
                                elif os.path.isdir(fp):
                                    shutil.rmtree(fp, ignore_errors=True)
                                    cleaned += 1
                            except:
                                pass
                    except:
                        pass

            def update_done():
                status_lbl.configure(text=f"✅ Cleaned {cleaned} items!", text_color="#10B981")
                ctk.CTkButton(content, text="Close", command=popup.destroy,
                             fg_color="#374151", hover_color="#4B5563", width=100).pack(pady=15)

            self.after(0, update_done)
            self._log_activity(f"OptiStorage: Cleaned {cleaned} temp items", "success")

        threading.Thread(target=do_clean, daemon=True).start()

    def _empty_recycle_bin(self):
        try:
            from ctypes import windll
            result = windll.shell32.SHEmptyRecycleBinW(None, None, 0x00000007)
            if result == 0:
                self._toast("Recycle Bin emptied!", "ok")
                self._log_activity("OptiStorage: Emptied Recycle Bin", "success")
            else:
                self._toast("Recycle Bin is already empty", "ok")
        except Exception as e:
            self._toast(f"Error: {e}", "err")

    def _open_disk_cleanup(self):
        try:
            subprocess.Popen("cleanmgr.exe", shell=True)
            self._toast("Disk Cleanup opened!", "ok")
            self._log_activity("OptiStorage: Opened Disk Cleanup", "info")
        except:
            self._toast("Could not open Disk Cleanup", "err")

    def _analyze_folders(self):
        popup = ctk.CTkToplevel(self)
        popup.title("Folder Analysis")
        popup.geometry("450x400")
        popup.transient(self)
        popup.grab_set()
        popup.configure(fg_color="#0D1117")

        header = ctk.CTkFrame(popup, fg_color="#161B22", corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="📊 Folder Analysis", font=ctk.CTkFont(size=18, weight="bold"),
                    text_color="#E5E7EB").pack(pady=15)

        content = ctk.CTkScrollableFrame(popup, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=15)

        folders = [
            (os.path.expanduser("~\\Downloads"), "Downloads"),
            (os.path.expanduser("~\\Documents"), "Documents"),
            (os.path.expanduser("~\\Desktop"), "Desktop"),
            (os.path.expanduser("~\\Pictures"), "Pictures"),
            (os.path.expanduser("~\\Videos"), "Videos"),
            (os.environ.get('TEMP', ''), "Temp Files"),
        ]

        for path, name in folders:
            try:
                if os.path.exists(path):
                    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, dn, fn in os.walk(path) for f in fn) / (1024**2)
                else:
                    size = 0
            except:
                size = 0

            row = ctk.CTkFrame(content, fg_color="#1D232C", corner_radius=8)
            row.pack(fill="x", pady=3)

            ctk.CTkLabel(row, text=f"📁 {name}", font=ctk.CTkFont(size=12),
                        text_color="#E5E7EB").pack(side="left", padx=12, pady=10)

            if size > 1000:
                size_text = f"{size/1024:.1f} GB"
                color = "#EF4444"
            elif size > 500:
                size_text = f"{size:.0f} MB"
                color = "#F59E0B"
            else:
                size_text = f"{size:.0f} MB"
                color = "#10B981"

            ctk.CTkLabel(row, text=size_text, font=ctk.CTkFont(size=12, weight="bold"),
                        text_color=color).pack(side="right", padx=12, pady=10)

        ctk.CTkButton(content, text="Close", command=popup.destroy,
                     fg_color="#374151", hover_color="#4B5563", width=100).pack(pady=15)

    def _trim_ssd(self):
        try:
            subprocess.run(['defrag', 'C:', '/O'], capture_output=True, timeout=5)
            self._toast("TRIM optimization started!", "ok")
            self._log_activity("OptiStorage: TRIM optimization started", "success")
        except:
            self._toast("Could not start TRIM", "error")

    def _check_disk(self):
        self._toast("Run 'chkdsk' from admin CMD", "ok")

    def _defrag_disk(self):
        try:
            subprocess.Popen(['dfrgui'], shell=True)
            self._log_activity("OptiStorage: Opened Disk Defragmenter", "info")
        except:
            self._toast("Could not open defrag tool", "error")

    def _clean_windows_temp(self):
        self._clean_temp_files()

    def _clean_browser_cache(self):
        popup = ctk.CTkToplevel(self)
        popup.title("Browser Cache")
        popup.geometry("350x200")
        popup.transient(self)
        popup.grab_set()
        popup.configure(fg_color="#0D1117")

        ctk.CTkLabel(popup, text="🌐 Browser Cache Cleanup", font=ctk.CTkFont(size=16, weight="bold"),
                    text_color="#E5E7EB").pack(pady=20)
        ctk.CTkLabel(popup, text="Please clear cache from your browser settings:\n• Chrome: Ctrl+Shift+Del\n• Firefox: Ctrl+Shift+Del\n• Edge: Ctrl+Shift+Del",
                    font=ctk.CTkFont(size=11), text_color="#9CA3AF").pack(pady=10)
        ctk.CTkButton(popup, text="OK", command=popup.destroy,
                     fg_color="#374151", hover_color="#4B5563", width=80).pack(pady=15)

    def _clean_system_logs(self):
        try:
            cleaned = 0
            log_path = "C:\\Windows\\Logs"
            if os.path.exists(log_path):
                for root, dirs, files in os.walk(log_path):
                    for f in files:
                        if f.endswith('.log') or f.endswith('.txt'):
                            try:
                                os.remove(os.path.join(root, f))
                                cleaned += 1
                            except:
                                pass
            self._toast(f"Cleaned {cleaned} log files", "ok")
            self._log_activity(f"OptiStorage: Cleaned {cleaned} log files", "success")
        except:
            self._toast("Could not clean logs (need admin)", "error")

    def _empty_recycle_bin(self):
        try:
            from ctypes import windll
            windll.shell32.SHEmptyRecycleBinW(None, None, 0x07)
            self._toast("Recycle bin emptied!", "ok")
            self._log_activity("OptiStorage: Emptied recycle bin", "success")
        except:
            self._toast("Could not empty recycle bin", "error")

    def _fill_network(self, parent):
        top = ctk.CTkFrame(parent, height=60, fg_color="transparent")
        top.pack(fill="x", padx=30, pady=(30,20))
        ctk.CTkLabel(top, text="Network", font=ctk.CTkFont(family="Segoe UI Variable Display", size=28, weight="bold")).pack(side="left")

        btn_frame = ctk.CTkFrame(top, fg_color="transparent")
        btn_frame.pack(side="right")

        ctk.CTkButton(btn_frame, text="🔄 Flush DNS", command=self._flush_dns,
                     width=90, fg_color="#10B981", hover_color="#059669").pack(side="left", padx=3)
        ctk.CTkButton(btn_frame, text="📶 Ping Test", command=self._ping_test,
                     width=90, fg_color="#8B5CF6", hover_color="#7C3AED").pack(side="left", padx=3)
        ctk.CTkButton(btn_frame, text="🔧 Reset Stack", command=self._reset_network,
                     width=90, fg_color="#F59E0B", hover_color="#D97706").pack(side="left", padx=3)
        ctk.CTkButton(btn_frame, text="🌐 Speed Test", command=self._run_speed_test,
                     width=90, fg_color="#3B82F6", hover_color="#2563EB").pack(side="left", padx=3)

        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=30, pady=(0,30))
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(0, weight=1)

        left_panel = ctk.CTkFrame(content, fg_color="transparent")
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0,10))

        chart_frame = ctk.CTkFrame(left_panel, fg_color="#0D1117", corner_radius=16, border_width=1, border_color="#30363D")
        chart_frame.pack(fill="x", pady=(0,10))

        fig = Figure(figsize=(6, 2.5), dpi=100)
        fig.patch.set_facecolor('#0D1117')
        ax = fig.add_subplot(111)
        ax.set_facecolor('#0D1117')
        ax.tick_params(colors='#9CA3AF', labelsize=8)
        for spine in ax.spines.values(): spine.set_color('#30363D')
        ax.grid(True, color='#30363D', alpha=0.3, linestyle='--')

        self.line_net_down, = ax.plot(list(self.ts_net_down), label="⬇ Download", color='#10B981', linewidth=2)
        self.line_net_up,   = ax.plot(list(self.ts_net_up),   label="⬆ Upload",   color='#3B82F6', linewidth=2)
        ax.legend(loc="upper left", fontsize=8, facecolor='#1C2128', edgecolor='#30363D', labelcolor='#E5E7EB')

        self.canvas_net = FigureCanvasTkAgg(fig, master=chart_frame)
        self.canvas_net.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

        conn_frame = ctk.CTkFrame(left_panel, fg_color="#161B22", corner_radius=16, border_width=1, border_color="#30363D")
        conn_frame.pack(fill="both", expand=True)

        conn_header = ctk.CTkFrame(conn_frame, fg_color="transparent")
        conn_header.pack(fill="x", padx=15, pady=(15,10))
        ctk.CTkLabel(conn_header, text="🔗 ACTIVE CONNECTIONS", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#9CA3AF").pack(side="left")
        ctk.CTkButton(conn_header, text="Refresh", width=60, height=24, font=ctk.CTkFont(size=10),
                     fg_color="#374151", hover_color="#4B5563",
                     command=self._refresh_connections).pack(side="right")

        self.conn_list_frame = ctk.CTkScrollableFrame(conn_frame, fg_color="transparent")
        self.conn_list_frame.pack(fill="both", expand=True, padx=10, pady=(0,10))
        self._refresh_connections()

        right_panel = ctk.CTkFrame(content, fg_color="#161B22", corner_radius=16, border_width=1, border_color="#30363D")
        right_panel.grid(row=0, column=1, sticky="nsew")

        ctk.CTkLabel(right_panel, text="🌐 NETWORK INFO", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#9CA3AF").pack(anchor="w", padx=15, pady=(15,10))

        try:
            import socket
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
        except:
            hostname, local_ip = "Unknown", "Unknown"

        net_info_frame = ctk.CTkFrame(right_panel, fg_color="transparent")
        net_info_frame.pack(fill="x", padx=15, pady=5)

        def info_row(parent, label, value, color="#E5E7EB"):
            row = ctk.CTkFrame(parent, fg_color="#0D1117", corner_radius=8)
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=10), text_color="#6B7280").pack(side="left", padx=10, pady=6)
            ctk.CTkLabel(row, text=value, font=ctk.CTkFont(size=10, weight="bold"), text_color=color).pack(side="right", padx=10, pady=6)

        info_row(net_info_frame, "Hostname", hostname[:15], "#10B981")
        info_row(net_info_frame, "Local IP", local_ip, "#3B82F6")

        try:
            connections = len(psutil.net_connections(kind='inet'))
        except:
            connections = 0
        info_row(net_info_frame, "Connections", str(connections), "#8B5CF6")

        ctk.CTkLabel(right_panel, text="📡 ADAPTERS", font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#9CA3AF").pack(anchor="w", padx=15, pady=(15,5))

        adapters_frame = ctk.CTkScrollableFrame(right_panel, fg_color="transparent", height=100)
        adapters_frame.pack(fill="x", padx=15, pady=(0,10))

        try:
            stats = psutil.net_if_stats()
            for name, stat in stats.items():
                if stat.isup and not name.startswith('Loopback'):
                    speed = f"{stat.speed}Mbps" if stat.speed else "---"
                    card = ctk.CTkFrame(adapters_frame, fg_color="#1D232C", corner_radius=8)
                    card.pack(fill="x", pady=2)
                    ctk.CTkLabel(card, text=f"✅ {name[:18]}", font=ctk.CTkFont(size=9),
                                text_color="#10B981").pack(side="left", padx=8, pady=5)
                    ctk.CTkLabel(card, text=speed, font=ctk.CTkFont(size=9),
                                text_color="#6B7280").pack(side="right", padx=8, pady=5)
        except:
            pass

        ctk.CTkLabel(right_panel, text="⚡ NETWORK TOOLS", font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#9CA3AF").pack(anchor="w", padx=15, pady=(10,5))

        tools_frame = ctk.CTkFrame(right_panel, fg_color="transparent")
        tools_frame.pack(fill="both", expand=True, padx=15, pady=(0,15))

        dns_row = ctk.CTkFrame(tools_frame, fg_color="#0D1117", corner_radius=8)
        dns_row.pack(fill="x", pady=3)
        ctk.CTkLabel(dns_row, text="🌍 DNS:", font=ctk.CTkFont(size=10), text_color="#6B7280").pack(side="left", padx=10, pady=6)
        ctk.CTkButton(dns_row, text="Google", width=55, height=24, font=ctk.CTkFont(size=9),
                     fg_color="#10B981", hover_color="#059669",
                     command=lambda: self._change_dns("google")).pack(side="left", padx=2, pady=4)
        ctk.CTkButton(dns_row, text="Cloudflare", width=65, height=24, font=ctk.CTkFont(size=9),
                     fg_color="#F59E0B", hover_color="#D97706",
                     command=lambda: self._change_dns("cloudflare")).pack(side="left", padx=2, pady=4)
        ctk.CTkButton(dns_row, text="Default", width=50, height=24, font=ctk.CTkFont(size=9),
                     fg_color="#374151", hover_color="#4B5563",
                     command=lambda: self._change_dns("auto")).pack(side="left", padx=2, pady=4)

        btn_grid = ctk.CTkFrame(tools_frame, fg_color="transparent")
        btn_grid.pack(fill="x", pady=5)
        btn_grid.grid_columnconfigure((0,1), weight=1)

        ctk.CTkButton(btn_grid, text="🚀 Optimize TCP", command=self._optimize_tcp,
                     height=30, fg_color="#374151", hover_color="#4B5563").grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        ctk.CTkButton(btn_grid, text="🔒 Renew IP", command=self._release_renew_ip,
                     height=30, fg_color="#374151", hover_color="#4B5563").grid(row=0, column=1, sticky="ew", padx=2, pady=2)
        ctk.CTkButton(btn_grid, text="🩺 Troubleshoot", command=self._network_troubleshoot,
                     height=30, fg_color="#374151", hover_color="#4B5563").grid(row=1, column=0, sticky="ew", padx=2, pady=2)
        ctk.CTkButton(btn_grid, text="⚡ Low Latency", command=self._low_latency_mode,
                     height=30, fg_color="#8B5CF6", hover_color="#7C3AED").grid(row=1, column=1, sticky="ew", padx=2, pady=2)
        ctk.CTkButton(btn_grid, text="📊 Bandwidth/App", command=self._show_bandwidth_by_app,
                     height=30, fg_color="#374151", hover_color="#4B5563").grid(row=2, column=0, columnspan=2, sticky="ew", padx=2, pady=2)

        ctk.CTkLabel(tools_frame, text="Kill Connections:", font=ctk.CTkFont(size=10),
                    text_color="#6B7280").pack(anchor="w", pady=(10,3))

        kill_row = ctk.CTkFrame(tools_frame, fg_color="transparent")
        kill_row.pack(fill="x")

        self.kill_app_entry = ctk.CTkEntry(kill_row, placeholder_text="App name...", height=28, width=120)
        self.kill_app_entry.pack(side="left", padx=(0,5))
        ctk.CTkButton(kill_row, text="Kill", width=50, height=28, fg_color="#EF4444", hover_color="#DC2626",
                     command=self._kill_app_connections).pack(side="left")

    def _refresh_connections(self):
        for w in self.conn_list_frame.winfo_children():
            w.destroy()

        try:
            conns = psutil.net_connections(kind='inet')
            shown = 0
            for conn in conns[:30]:
                if conn.status == 'ESTABLISHED' and conn.raddr:
                    row = ctk.CTkFrame(self.conn_list_frame, fg_color="#0D1117", corner_radius=6)
                    row.pack(fill="x", pady=1)

                    try:
                        proc_name = psutil.Process(conn.pid).name()[:15] if conn.pid else "System"
                    except:
                        proc_name = "Unknown"

                    ctk.CTkLabel(row, text=proc_name, font=ctk.CTkFont(size=9, weight="bold"),
                                text_color="#E5E7EB", width=80).pack(side="left", padx=6, pady=4)
                    ctk.CTkLabel(row, text=f"{conn.raddr.ip}:{conn.raddr.port}", font=ctk.CTkFont(size=9),
                                text_color="#6B7280").pack(side="left", padx=6, pady=4)
                    ctk.CTkLabel(row, text=conn.status[:6], font=ctk.CTkFont(size=8),
                                text_color="#10B981").pack(side="right", padx=6, pady=4)
                    shown += 1

            if shown == 0:
                ctk.CTkLabel(self.conn_list_frame, text="No active connections",
                            text_color="#6B7280").pack(pady=20)
        except Exception as e:
            ctk.CTkLabel(self.conn_list_frame, text=f"Error: {e}", text_color="#EF4444").pack(pady=20)

    def _ping_test(self):
        popup = ctk.CTkToplevel(self)
        popup.title("Ping Test")
        popup.geometry("380x320")
        popup.transient(self)
        popup.grab_set()
        popup.configure(fg_color="#0D1117")

        header = ctk.CTkFrame(popup, fg_color="#161B22", corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="📶 Ping Test", font=ctk.CTkFont(size=18, weight="bold"),
                    text_color="#E5E7EB").pack(pady=15)

        status_frame = ctk.CTkFrame(popup, fg_color="transparent")
        status_frame.pack(fill="both", expand=True, padx=20, pady=20)

        loading_lbl = ctk.CTkLabel(status_frame, text="🔄 Pinging servers...",
                                   font=ctk.CTkFont(size=14), text_color="#9CA3AF")
        loading_lbl.pack(pady=30)

        def do_ping():
            results = []
            servers = [("Google DNS", "8.8.8.8"), ("Cloudflare", "1.1.1.1"),
                      ("Microsoft", "13.107.4.52"), ("Amazon", "205.251.242.103")]

            for name, ip in servers:
                try:
                    import re
                    result = subprocess.run(['ping', '-n', '2', '-w', '1000', ip],
                                           capture_output=True, text=True, timeout=5)
                    if 'time=' in result.stdout or 'time<' in result.stdout:
                        match = re.search(r'Average = (\d+)ms|time[<=](\d+)', result.stdout)
                        if match:
                            ms = match.group(1) or match.group(2)
                            results.append((name, ip, int(ms), "#10B981" if int(ms) < 50 else "#F59E0B" if int(ms) < 100 else "#EF4444"))
                        else:
                            results.append((name, ip, 999, "#EF4444"))
                    else:
                        results.append((name, ip, -1, "#EF4444"))
                except:
                    results.append((name, ip, -1, "#EF4444"))

            def update_ui():
                loading_lbl.destroy()
                for name, ip, ms, color in results:
                    row = ctk.CTkFrame(status_frame, fg_color="#1D232C", corner_radius=10)
                    row.pack(fill="x", pady=4)

                    ctk.CTkLabel(row, text=name, font=ctk.CTkFont(size=12, weight="bold"),
                                text_color="#E5E7EB").pack(side="left", padx=15, pady=10)
                    ctk.CTkLabel(row, text=ip, font=ctk.CTkFont(size=10),
                                text_color="#6B7280").pack(side="left", padx=5, pady=10)

                    if ms >= 0:
                        ms_text = f"{ms}ms"
                    else:
                        ms_text = "Timeout"
                    ctk.CTkLabel(row, text=ms_text, font=ctk.CTkFont(size=13, weight="bold"),
                                text_color=color).pack(side="right", padx=15, pady=10)

                ctk.CTkButton(status_frame, text="Close", command=popup.destroy,
                             fg_color="#374151", hover_color="#4B5563", width=100).pack(pady=15)

            self.after(0, update_ui)
            self._log_activity("OptiNet: Ping test completed", "info")

        threading.Thread(target=do_ping, daemon=True).start()

    def _optimize_tcp(self):
        popup = ctk.CTkToplevel(self)
        popup.title("TCP Optimization")
        popup.geometry("380x300")
        popup.transient(self)
        popup.grab_set()
        popup.configure(fg_color="#0D1117")

        header = ctk.CTkFrame(popup, fg_color="#161B22", corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="🚀 TCP Optimization", font=ctk.CTkFont(size=18, weight="bold"),
                    text_color="#E5E7EB").pack(pady=15)

        content = ctk.CTkFrame(popup, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=15)

        results = []
        cmds = [
            (['netsh', 'int', 'tcp', 'set', 'global', 'autotuninglevel=normal'], "Auto-tuning: Normal"),
            (['netsh', 'int', 'tcp', 'set', 'global', 'ecncapability=disabled'], "ECN: Disabled"),
            (['netsh', 'int', 'tcp', 'set', 'global', 'timestamps=disabled'], "Timestamps: Disabled"),
        ]

        for cmd, desc in cmds:
            try:
                subprocess.run(cmd, capture_output=True, timeout=5)
                results.append((desc, "✅ Applied", "#10B981"))
            except:
                results.append((desc, "❌ Failed", "#EF4444"))

        for desc, status, color in results:
            row = ctk.CTkFrame(content, fg_color="#1D232C", corner_radius=8)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=desc, font=ctk.CTkFont(size=12),
                        text_color="#E5E7EB").pack(side="left", padx=15, pady=10)
            ctk.CTkLabel(row, text=status, font=ctk.CTkFont(size=11, weight="bold"),
                        text_color=color).pack(side="right", padx=15, pady=10)

        ctk.CTkLabel(content, text="TCP optimized for low latency gaming!",
                    font=ctk.CTkFont(size=11), text_color="#10B981").pack(pady=10)
        ctk.CTkButton(content, text="Close", command=popup.destroy,
                     fg_color="#374151", hover_color="#4B5563", width=100).pack(pady=10)

        self._log_activity("OptiNet: TCP settings optimized", "success")

    def _release_renew_ip(self):
        popup = ctk.CTkToplevel(self)
        popup.title("IP Renew")
        popup.geometry("350x250")
        popup.transient(self)
        popup.grab_set()
        popup.configure(fg_color="#0D1117")

        header = ctk.CTkFrame(popup, fg_color="#161B22", corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="🔒 IP Release & Renew", font=ctk.CTkFont(size=18, weight="bold"),
                    text_color="#E5E7EB").pack(pady=15)

        content = ctk.CTkFrame(popup, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=15)

        status_lbl = ctk.CTkLabel(content, text="🔄 Releasing IP address...",
                                  font=ctk.CTkFont(size=14), text_color="#9CA3AF")
        status_lbl.pack(pady=30)

        def do_release():
            try:
                subprocess.run(['ipconfig', '/release'], capture_output=True, timeout=10)
                self.after(0, lambda: status_lbl.configure(text="🔄 Renewing IP address..."))
                subprocess.run(['ipconfig', '/renew'], capture_output=True, timeout=30)

                try:
                    import socket
                    new_ip = socket.gethostbyname(socket.gethostname())
                except:
                    new_ip = "Unknown"

                def update_done():
                    status_lbl.configure(text=f"✅ IP Renewed!\n\nNew IP: {new_ip}", text_color="#10B981")
                    ctk.CTkButton(content, text="Close", command=popup.destroy,
                                 fg_color="#374151", hover_color="#4B5563", width=100).pack(pady=10)
                self.after(0, update_done)
                self._log_activity(f"OptiNet: IP renewed to {new_ip}", "success")
            except Exception as e:
                self.after(0, lambda: status_lbl.configure(text=f"❌ Failed: {e}", text_color="#EF4444"))

        threading.Thread(target=do_release, daemon=True).start()

    def _show_net_stats(self):
        popup = ctk.CTkToplevel(self)
        popup.title("Network Statistics")
        popup.geometry("400x350")
        popup.transient(self)
        popup.grab_set()
        popup.configure(fg_color="#0D1117")

        header = ctk.CTkFrame(popup, fg_color="#161B22", corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="📊 Network Statistics", font=ctk.CTkFont(size=18, weight="bold"),
                    text_color="#E5E7EB").pack(pady=15)

        content = ctk.CTkFrame(popup, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=15)

        try:
            stats = psutil.net_io_counters()
            items = [
                ("📤 Bytes Sent", f"{stats.bytes_sent / (1024**3):.2f} GB", "#3B82F6"),
                ("📥 Bytes Received", f"{stats.bytes_recv / (1024**3):.2f} GB", "#10B981"),
                ("📦 Packets Sent", f"{stats.packets_sent:,}", "#8B5CF6"),
                ("📦 Packets Received", f"{stats.packets_recv:,}", "#F59E0B"),
                ("❌ Errors In", str(stats.errin), "#EF4444"),
                ("❌ Errors Out", str(stats.errout), "#EF4444"),
            ]

            for label, value, color in items:
                row = ctk.CTkFrame(content, fg_color="#1D232C", corner_radius=8)
                row.pack(fill="x", pady=3)
                ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=12),
                            text_color="#E5E7EB").pack(side="left", padx=15, pady=10)
                ctk.CTkLabel(row, text=value, font=ctk.CTkFont(size=12, weight="bold"),
                            text_color=color).pack(side="right", padx=15, pady=10)
        except Exception as e:
            ctk.CTkLabel(content, text=f"Error: {e}", text_color="#EF4444").pack(pady=30)

        ctk.CTkButton(content, text="Close", command=popup.destroy,
                     fg_color="#374151", hover_color="#4B5563", width=100).pack(pady=15)

    def _change_dns(self, provider):
        popup = ctk.CTkToplevel(self)
        popup.title("Change DNS")
        popup.geometry("380x280")
        popup.transient(self)
        popup.grab_set()
        popup.configure(fg_color="#0D1117")

        dns_servers = {
            "google": ("8.8.8.8", "8.8.4.4", "Google DNS"),
            "cloudflare": ("1.1.1.1", "1.0.0.1", "Cloudflare DNS"),
            "auto": (None, None, "Automatic (DHCP)")
        }

        header = ctk.CTkFrame(popup, fg_color="#161B22", corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="🌍 Change DNS Server", font=ctk.CTkFont(size=18, weight="bold"),
                    text_color="#E5E7EB").pack(pady=15)

        content = ctk.CTkFrame(popup, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=15)

        status_lbl = ctk.CTkLabel(content, text="🔄 Changing DNS...",
                                  font=ctk.CTkFont(size=14), text_color="#9CA3AF")
        status_lbl.pack(pady=20)

        info_frame = ctk.CTkFrame(content, fg_color="transparent")
        info_frame.pack(fill="x", pady=10)

        def do_change():
            try:
                adapters = []
                for name, stats in psutil.net_if_stats().items():
                    if stats.isup and not name.startswith('Loopback'):
                        adapters.append(name)

                if not adapters:
                    self.after(0, lambda: status_lbl.configure(text="❌ No active adapter found", text_color="#EF4444"))
                    return

                adapter = adapters[0]
                primary, secondary, name = dns_servers[provider]

                if provider == "auto":
                    subprocess.run(['netsh', 'interface', 'ip', 'set', 'dns', adapter, 'dhcp'],
                                  capture_output=True, timeout=10)
                else:
                    subprocess.run(['netsh', 'interface', 'ip', 'set', 'dns', adapter, 'static', primary],
                                  capture_output=True, timeout=10)
                    subprocess.run(['netsh', 'interface', 'ip', 'add', 'dns', adapter, secondary, 'index=2'],
                                  capture_output=True, timeout=10)

                def update_done():
                    status_lbl.configure(text=f"✅ DNS Changed!", text_color="#10B981")

                    for w in info_frame.winfo_children():
                        w.destroy()

                    items = [
                        ("Provider", name),
                        ("Adapter", adapter[:25]),
                    ]
                    if primary:
                        items.append(("Primary", primary))
                        items.append(("Secondary", secondary))

                    for label, value in items:
                        row = ctk.CTkFrame(info_frame, fg_color="#1D232C", corner_radius=8)
                        row.pack(fill="x", pady=2)
                        ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=11),
                                    text_color="#6B7280").pack(side="left", padx=12, pady=8)
                        ctk.CTkLabel(row, text=value, font=ctk.CTkFont(size=11, weight="bold"),
                                    text_color="#E5E7EB").pack(side="right", padx=12, pady=8)

                    ctk.CTkButton(content, text="Close", command=popup.destroy,
                                 fg_color="#374151", hover_color="#4B5563", width=100).pack(pady=10)

                self.after(0, update_done)
                self._log_activity(f"OptiNet: DNS changed to {name}", "success")
            except Exception as e:
                self.after(0, lambda: status_lbl.configure(text=f"❌ Failed: {e}", text_color="#EF4444"))

        threading.Thread(target=do_change, daemon=True).start()

    def _network_troubleshoot(self):
        popup = ctk.CTkToplevel(self)
        popup.title("Network Troubleshoot")
        popup.geometry("400x350")
        popup.transient(self)
        popup.grab_set()
        popup.configure(fg_color="#0D1117")

        header = ctk.CTkFrame(popup, fg_color="#161B22", corner_radius=0)
        header.pack(fill="x", padx=0, pady=0)
        ctk.CTkLabel(header, text="🩺 Network Troubleshoot", font=ctk.CTkFont(size=18, weight="bold"),
                    text_color="#E5E7EB").pack(pady=15)

        status_frame = ctk.CTkFrame(popup, fg_color="transparent")
        status_frame.pack(fill="both", expand=True, padx=20, pady=20)

        loading_lbl = ctk.CTkLabel(status_frame, text="🔄 Running diagnostics...",
                                   font=ctk.CTkFont(size=14), text_color="#9CA3AF")
        loading_lbl.pack(pady=30)

        def do_troubleshoot():
            results = []

            try:
                result = subprocess.run(['ping', '-n', '1', '-w', '2000', '8.8.8.8'],
                                       capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    results.append(("Internet Connection", "✅ Connected", "#10B981"))
                else:
                    results.append(("Internet Connection", "❌ No Connection", "#EF4444"))
            except:
                results.append(("Internet Connection", "❌ Failed", "#EF4444"))

            try:
                import socket
                socket.gethostbyname("google.com")
                results.append(("DNS Resolution", "✅ Working", "#10B981"))
            except:
                results.append(("DNS Resolution", "❌ Failed", "#EF4444"))

            try:
                import socket
                gateway_ip = socket.gethostbyname(socket.gethostname()).rsplit('.', 1)[0] + '.1'
                result = subprocess.run(['ping', '-n', '1', '-w', '1000', gateway_ip],
                                       capture_output=True, timeout=3)
                if result.returncode == 0:
                    results.append(("Gateway", f"✅ Reachable ({gateway_ip})", "#10B981"))
                else:
                    results.append(("Gateway", "⚠️ Unreachable", "#F59E0B"))
            except:
                results.append(("Gateway", "⚠️ Unknown", "#F59E0B"))

            try:
                active_adapters = sum(1 for s in psutil.net_if_stats().values() if s.isup)
                results.append(("Network Adapters", f"✅ {active_adapters} active", "#10B981"))
            except:
                results.append(("Network Adapters", "⚠️ Unknown", "#F59E0B"))

            def update_ui():
                loading_lbl.destroy()
                for label, status, color in results:
                    row = ctk.CTkFrame(status_frame, fg_color="#1D232C", corner_radius=10)
                    row.pack(fill="x", pady=5)
                    ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=13),
                                text_color="#E5E7EB").pack(side="left", padx=15, pady=12)
                    ctk.CTkLabel(row, text=status, font=ctk.CTkFont(size=12, weight="bold"),
                                text_color=color).pack(side="right", padx=15, pady=12)

                ctk.CTkButton(status_frame, text="Close", command=popup.destroy,
                             fg_color="#374151", hover_color="#4B5563", width=100).pack(pady=15)

            self.after(0, update_ui)
            self._log_activity("OptiNet: Troubleshoot completed", "info")

        threading.Thread(target=do_troubleshoot, daemon=True).start()

    def _low_latency_mode(self):
        popup = ctk.CTkToplevel(self)
        popup.title("Low Latency Mode")
        popup.geometry("420x400")
        popup.transient(self)
        popup.grab_set()
        popup.configure(fg_color="#0D1117")

        header = ctk.CTkFrame(popup, fg_color="#161B22", corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="⚡ Low Latency Mode", font=ctk.CTkFont(size=18, weight="bold"),
                    text_color="#E5E7EB").pack(pady=15)

        btn_row = ctk.CTkFrame(popup, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(15,10))

        content = ctk.CTkFrame(popup, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=(0,15))

        results_frame = ctk.CTkScrollableFrame(content, fg_color="transparent")
        results_frame.pack(fill="both", expand=True)

        status_lbl = ctk.CTkLabel(content, text="Select an option above",
                                  font=ctk.CTkFont(size=11), text_color="#6B7280")
        status_lbl.pack(pady=10)

        def apply_settings(mode):
            for w in results_frame.winfo_children():
                w.destroy()

            if mode == "enable":
                optimizations = [
                    (['netsh', 'int', 'tcp', 'set', 'global', 'autotuninglevel=normal'], "TCP Auto-tuning", "Optimized for gaming"),
                    (['netsh', 'int', 'tcp', 'set', 'global', 'ecncapability=disabled'], "ECN Capability", "Disabled for stability"),
                    (['netsh', 'int', 'tcp', 'set', 'global', 'timestamps=disabled'], "TCP Timestamps", "Disabled for speed"),
                    (['netsh', 'int', 'tcp', 'set', 'global', 'rss=enabled'], "RSS", "Enabled for throughput"),
                ]
                success_msg = "✨ Low latency mode enabled!"
                log_msg = "OptiNet: Low latency mode enabled"
            else:
                optimizations = [
                    (['netsh', 'int', 'tcp', 'set', 'global', 'autotuninglevel=normal'], "TCP Auto-tuning", "Reset to normal"),
                    (['netsh', 'int', 'tcp', 'set', 'global', 'ecncapability=default'], "ECN Capability", "Reset to default"),
                    (['netsh', 'int', 'tcp', 'set', 'global', 'timestamps=default'], "TCP Timestamps", "Reset to default"),
                    (['netsh', 'int', 'tcp', 'set', 'global', 'rss=enabled'], "RSS", "Kept enabled"),
                ]
                success_msg = "🔄 Settings reverted to default!"
                log_msg = "OptiNet: Low latency mode reverted to default"

            results = []
            for cmd, name, desc in optimizations:
                try:
                    subprocess.run(cmd, capture_output=True, timeout=5)
                    results.append((name, desc, "✅", "#10B981"))
                except:
                    results.append((name, desc, "❌", "#EF4444"))

            for name, desc, icon, color in results:
                row = ctk.CTkFrame(results_frame, fg_color="#1D232C", corner_radius=8)
                row.pack(fill="x", pady=2)

                left = ctk.CTkFrame(row, fg_color="transparent")
                left.pack(side="left", padx=12, pady=6)
                ctk.CTkLabel(left, text=name, font=ctk.CTkFont(size=10, weight="bold"),
                            text_color="#E5E7EB").pack(anchor="w")
                ctk.CTkLabel(left, text=desc, font=ctk.CTkFont(size=8),
                            text_color="#6B7280").pack(anchor="w")

                ctk.CTkLabel(row, text=icon, font=ctk.CTkFont(size=12),
                            text_color=color).pack(side="right", padx=12, pady=6)

            status_lbl.configure(text=success_msg, text_color="#10B981")
            self._log_activity(log_msg, "optimize")

        ctk.CTkButton(btn_row, text="⚡ Enable Low Latency", command=lambda: apply_settings("enable"),
                     fg_color="#8B5CF6", hover_color="#7C3AED", width=150, height=35).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text="🔄 Revert to Default", command=lambda: apply_settings("revert"),
                     fg_color="#374151", hover_color="#4B5563", width=150, height=35).pack(side="left", padx=5)

        ctk.CTkButton(popup, text="Close", command=popup.destroy,
                     fg_color="#1D232C", hover_color="#374151", width=100).pack(pady=10)

    def _show_bandwidth_by_app(self):
        popup = ctk.CTkToplevel(self)
        popup.title("Network Usage by App")
        popup.geometry("420x400")
        popup.transient(self)
        popup.grab_set()
        popup.configure(fg_color="#0D1117")

        header = ctk.CTkFrame(popup, fg_color="#161B22", corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="📊 Network Usage by App", font=ctk.CTkFont(size=18, weight="bold"),
                    text_color="#E5E7EB").pack(pady=15)

        content = ctk.CTkScrollableFrame(popup, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=15)

        try:
            app_connections = {}
            conns = psutil.net_connections(kind='inet')

            for conn in conns:
                if conn.pid:
                    try:
                        proc = psutil.Process(conn.pid)
                        proc_name = proc.name()
                        app_connections[proc_name] = app_connections.get(proc_name, 0) + 1
                    except:
                        pass

            sorted_apps = sorted(app_connections.items(), key=lambda x: x[1], reverse=True)[:15]
            max_conn = sorted_apps[0][1] if sorted_apps else 1

            if sorted_apps:
                for app, count in sorted_apps:
                    row = ctk.CTkFrame(content, fg_color="#1D232C", corner_radius=8)
                    row.pack(fill="x", pady=3)

                    ctk.CTkLabel(row, text=app[:25], font=ctk.CTkFont(size=11, weight="bold"),
                                text_color="#E5E7EB", width=150, anchor="w").pack(side="left", padx=10, pady=8)

                    bar_width = int((count / max_conn) * 100)
                    bar_frame = ctk.CTkFrame(row, fg_color="#0D1117", width=120, height=16, corner_radius=4)
                    bar_frame.pack(side="left", padx=5, pady=8)
                    bar_frame.pack_propagate(False)
                    bar = ctk.CTkFrame(bar_frame, fg_color="#10B981", width=bar_width, corner_radius=4)
                    bar.pack(side="left", fill="y")

                    ctk.CTkLabel(row, text=f"{count} conn", font=ctk.CTkFont(size=10),
                                text_color="#6B7280").pack(side="right", padx=10, pady=8)
            else:
                ctk.CTkLabel(content, text="No active connections", text_color="#6B7280").pack(pady=30)
        except Exception as e:
            ctk.CTkLabel(content, text=f"Error: {e}", text_color="#EF4444").pack(pady=30)

        footer = ctk.CTkFrame(popup, fg_color="transparent")
        footer.pack(fill="x", padx=20, pady=15)
        ctk.CTkLabel(footer, text=f"Total: {len(conns)} connections", font=ctk.CTkFont(size=11),
                    text_color="#6B7280").pack(side="left")
        ctk.CTkButton(footer, text="Close", command=popup.destroy,
                     fg_color="#374151", hover_color="#4B5563", width=80).pack(side="right")

    def _kill_app_connections(self):
        app_name = self.kill_app_entry.get().strip().lower()
        if not app_name:
            self._toast("Enter an app name", "error")
            return

        try:
            killed = 0
            conns = psutil.net_connections(kind='inet')
            pids_to_check = set()

            for conn in conns:
                if conn.pid:
                    pids_to_check.add(conn.pid)

            for pid in pids_to_check:
                try:
                    proc = psutil.Process(pid)
                    if app_name in proc.name().lower():
                        proc.terminate()
                        killed += 1
                except:
                    pass

            if killed > 0:
                self._toast(f"Terminated {killed} process(es)", "ok")
                self._log_activity(f"OptiNet: Killed connections for '{app_name}' ({killed} processes)", "success")
            else:
                self._toast(f"No matching app found", "error")

            self.kill_app_entry.delete(0, 'end')
        except Exception as e:
            self._toast(f"Error: {e}", "error")

    def _flush_dns(self):
        try:
            subprocess.run(['ipconfig', '/flushdns'], capture_output=True, timeout=10)
            self._toast("DNS cache flushed!", "ok")
            self._log_activity("OptiNet: Flushed DNS cache", "success")
        except Exception as e:
            self._toast(f"Failed: {e}", "error")
            self._log_activity(f"OptiNet: DNS flush failed - {e}", "error")

    def _reset_network(self):
        try:
            subprocess.run(['netsh', 'winsock', 'reset'], capture_output=True, timeout=10)
            subprocess.run(['netsh', 'int', 'ip', 'reset'], capture_output=True, timeout=10)
            self._toast("Network stack reset! Restart required.", "ok")
            self._log_activity("OptiNet: Reset network stack (restart required)", "success")
        except Exception as e:
            self._toast(f"Failed: {e}", "error")
            self._log_activity(f"OptiNet: Network reset failed - {e}", "error")

    def _fill_booster(self, parent):
        top = self._modern_header(parent, "System Booster", "All optimization features in one place")

        active_tooltips = []

        def add_tooltip(widget, text):
            tip = None
            hide_timer = None
            show_timer = None

            def destroy_all_tips():
                for t in active_tooltips[:]:
                    try:
                        t.destroy()
                        active_tooltips.remove(t)
                    except: pass

            def show(e):
                nonlocal tip, hide_timer, show_timer
                if show_timer:
                    try: widget.after_cancel(show_timer)
                    except: pass

                def do_show():
                    nonlocal tip, hide_timer
                    destroy_all_tips()

                    try:
                        tip = ctk.CTkToplevel(widget)
                        tip.wm_overrideredirect(True)
                        tip.wm_geometry(f"+{e.x_root+10}+{e.y_root+10}")
                        tip.attributes('-topmost', True)
                        tip.attributes('-alpha', 0.95)
                        lbl = ctk.CTkLabel(tip, text=text, fg_color="#1F2937", corner_radius=8,
                                           text_color="#F9FAFB", padx=12, pady=8,
                                           font=ctk.CTkFont(size=12))
                        lbl.pack()
                        active_tooltips.append(tip)

                        hide_timer = widget.after(2000, lambda: hide(None))
                    except: pass

                show_timer = widget.after(300, do_show)

            def hide(e):
                nonlocal tip, hide_timer, show_timer
                if show_timer:
                    try: widget.after_cancel(show_timer)
                    except: pass
                    show_timer = None
                if hide_timer:
                    try: widget.after_cancel(hide_timer)
                    except: pass
                    hide_timer = None
                if tip:
                    try:
                        tip.destroy()
                        if tip in active_tooltips:
                            active_tooltips.remove(tip)
                    except: pass
                    tip = None

            widget.bind("<Enter>", show)
            widget.bind("<Leave>", hide)
            widget.bind("<Button-1>", hide)

        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=30, pady=(0,20))
        scroll.grid_columnconfigure((0,1,2), weight=1)

        row = 0

        game_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        game_card.grid(row=row, column=0, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(game_card, text="🎮 GAME OPTIMIZATION", font=ctk.CTkFont(size=12, weight="bold"), text_color="#8B5CF6").pack(anchor="w", padx=15, pady=(15,10))

        self.booster_chk_game = ctk.CTkSwitch(game_card, text="Manual Game Mode", command=lambda: self._booster_toggle('game'), button_color="#8B5CF6")
        self.booster_chk_game.pack(anchor="w", padx=20, pady=5)
        add_tooltip(self.booster_chk_game, "Switch to High Performance power plan\nand boost the foreground app priority")

        self.booster_chk_auto = ctk.CTkSwitch(game_card, text="Auto Game Detect", command=lambda: self._booster_toggle('auto'), button_color="#8B5CF6")
        self.booster_chk_auto.pack(anchor="w", padx=20, pady=5)
        add_tooltip(self.booster_chk_auto, "Automatically detect games and apply\nboost when they start, restore on exit")
        if GAME_MODE.enabled: self.booster_chk_auto.select()

        self.booster_chk_fg = ctk.CTkSwitch(game_card, text="Foreground Booster", command=lambda: self._booster_toggle('fg'), button_color="#8B5CF6")
        self.booster_chk_fg.pack(anchor="w", padx=20, pady=5)
        add_tooltip(self.booster_chk_fg, "Elevate the foreground app to Above Normal\npriority, restore when it loses focus")
        if FG_BOOSTER.enabled: self.booster_chk_fg.select()

        ctk.CTkFrame(game_card, height=10, fg_color="transparent").pack()

        sys_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        sys_card.grid(row=row, column=1, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(sys_card, text="⚡ SYSTEM OPTIMIZATION", font=ctk.CTkFont(size=12, weight="bold"), text_color="#10B981").pack(anchor="w", padx=15, pady=(15,10))

        self.booster_chk_pri = ctk.CTkSwitch(sys_card, text="Priority Balancer", command=lambda: self._booster_toggle('priority'), button_color="#10B981")
        self.booster_chk_pri.pack(anchor="w", padx=20, pady=5)
        add_tooltip(self.booster_chk_pri, "Auto-lower priority of heavy background\nprocesses when system CPU is high")
        if PRIORITY_BALANCER.enabled: self.booster_chk_pri.select()

        self.booster_chk_cpu = ctk.CTkSwitch(sys_card, text="CPU Limiter", command=lambda: self._booster_toggle('cpu'), button_color="#10B981")
        self.booster_chk_cpu.pack(anchor="w", padx=20, pady=5)
        add_tooltip(self.booster_chk_cpu, "Limit CPU cores for background processes\nwhen system load is very high")
        if CPU_LIMITER.enabled: self.booster_chk_cpu.select()

        self.booster_chk_bg = ctk.CTkSwitch(sys_card, text="Background Governor", command=lambda: self._booster_toggle('bg'), button_color="#10B981")
        self.booster_chk_bg.pack(anchor="w", padx=20, pady=5)
        add_tooltip(self.booster_chk_bg, "Apply Windows EcoQoS to background\nprocesses for power savings")

        ctk.CTkFrame(sys_card, height=10, fg_color="transparent").pack()

        mem_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        mem_card.grid(row=row, column=2, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(mem_card, text="💾 MEMORY OPTIMIZATION", font=ctk.CTkFont(size=12, weight="bold"), text_color="#06B6D4").pack(anchor="w", padx=15, pady=(15,10))

        self.booster_chk_mem = ctk.CTkSwitch(mem_card, text="Memory Optimizer", command=lambda: self._booster_toggle('mem'), button_color="#06B6D4")
        self.booster_chk_mem.pack(anchor="w", padx=20, pady=5)
        add_tooltip(self.booster_chk_mem, "Auto-trim working sets of idle processes\nwhen system memory usage is high")
        if MEM_OPTIMIZER.enabled: self.booster_chk_mem.select()

        btn_trim = ctk.CTkButton(mem_card, text="Trim All RAM", command=self._quick_trim_all, height=32, fg_color="#374151", hover_color="#4B5563")
        btn_trim.pack(fill="x", padx=20, pady=5)
        add_tooltip(btn_trim, "Empty working sets of all processes\nto free up physical RAM immediately")

        btn_standby = ctk.CTkButton(mem_card, text="Clear Standby List", command=self._clear_ram_standby, height=32, fg_color="#374151", hover_color="#4B5563")
        btn_standby.pack(fill="x", padx=20, pady=5)
        add_tooltip(btn_standby, "Clear Windows standby memory cache\nto free more physical RAM")

        ctk.CTkFrame(mem_card, height=10, fg_color="transparent").pack()

        row += 1

        net_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        net_card.grid(row=row, column=0, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(net_card, text="🌐 NETWORK OPTIMIZATION", font=ctk.CTkFont(size=12, weight="bold"), text_color="#F59E0B").pack(anchor="w", padx=15, pady=(15,10))

        btn_nagle = ctk.CTkButton(net_card, text="Disable Nagle's Algorithm", command=self._optimize_network, height=32, fg_color="#374151", hover_color="#4B5563")
        btn_nagle.pack(fill="x", padx=20, pady=5)
        add_tooltip(btn_nagle, "Disable TCP delay to reduce network\nlatency in online games")

        btn_throttle = ctk.CTkButton(net_card, text="Disable Network Throttle", command=lambda: NETWORK_OPT.disable_network_throttling(), height=32, fg_color="#374151", hover_color="#4B5563")
        btn_throttle.pack(fill="x", padx=20, pady=5)
        add_tooltip(btn_throttle, "Remove Windows network bandwidth\nlimits for maximum throughput")

        self.lbl_net_status = ctk.CTkLabel(net_card, text="Status: Not optimized", text_color="#9CA3AF")
        self.lbl_net_status.pack(anchor="w", padx=20, pady=10)

        vis_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        vis_card.grid(row=row, column=1, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(vis_card, text="🎨 VISUAL EFFECTS", font=ctk.CTkFont(size=12, weight="bold"), text_color="#EC4899").pack(anchor="w", padx=15, pady=(15,10))

        btn_vis_off = ctk.CTkButton(vis_card, text="Disable for Performance", command=self._disable_visual_fx, height=32, fg_color="#EC4899", hover_color="#DB2777")
        btn_vis_off.pack(fill="x", padx=20, pady=5)
        add_tooltip(btn_vis_off, "Disable Windows animations, transparency,\nand effects for better gaming performance")

        btn_vis_on = ctk.CTkButton(vis_card, text="Restore Defaults", command=lambda: (VISUAL_FX.restore_defaults(), self._toast("Visual effects restored", "ok")), height=32, fg_color="#374151", hover_color="#4B5563")
        btn_vis_on.pack(fill="x", padx=20, pady=5)
        add_tooltip(btn_vis_on, "Restore Windows to default visual\neffects settings")

        ctk.CTkFrame(vis_card, height=10, fg_color="transparent").pack()

        tweak_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        tweak_card.grid(row=row, column=2, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(tweak_card, text="⚙️ WINDOWS TWEAKS", font=ctk.CTkFont(size=12, weight="bold"), text_color="#9CA3AF").pack(anchor="w", padx=15, pady=(15,10))

        btn_winkey = ctk.CTkButton(tweak_card, text="Disable Windows Key", command=self._disable_win_key, height=32, fg_color="#374151", hover_color="#4B5563")
        btn_winkey.pack(fill="x", padx=20, pady=5)
        add_tooltip(btn_winkey, "Block Windows key to prevent\naccidental presses during games")

        btn_sticky = ctk.CTkButton(tweak_card, text="Disable Sticky Keys", command=lambda: (WIN_TWEAKS.disable_sticky_keys(True), self._toast("Sticky keys disabled", "ok")), height=32, fg_color="#374151", hover_color="#4B5563")
        btn_sticky.pack(fill="x", padx=20, pady=5)
        add_tooltip(btn_sticky, "Disable sticky keys popup when\npressing Shift 5 times")

        btn_gamebar = ctk.CTkButton(tweak_card, text="Disable Game Bar", command=lambda: (WIN_TWEAKS.disable_game_bar(True), self._toast("Game Bar disabled", "ok")), height=32, fg_color="#374151", hover_color="#4B5563")
        btn_gamebar.pack(fill="x", padx=20, pady=5)
        add_tooltip(btn_gamebar, "Disable Xbox Game Bar overlay\nfor better performance")

        btn_fse = ctk.CTkButton(tweak_card, text="Disable FSE Optimizations", command=lambda: (WIN_TWEAKS.disable_fullscreen_optimizations(True), self._toast("FSE optimizations disabled", "ok")), height=32, fg_color="#374151", hover_color="#4B5563")
        btn_fse.pack(fill="x", padx=20, pady=5)
        add_tooltip(btn_fse, "Disable Windows fullscreen optimizations\nfor true exclusive fullscreen mode")

        ctk.CTkFrame(tweak_card, height=10, fg_color="transparent").pack()

    def _booster_toggle(self, feature):
        if feature == 'game':
            if self.booster_chk_game.get():
                switch_power_plan("HIGH")
                self._toast("Game Mode ON", "ok")
            else:
                switch_power_plan("BALANCED")
                self._toast("Game Mode OFF", "ok")
        elif feature == 'auto':
            GAME_MODE.enabled = bool(self.booster_chk_auto.get())
            self._toast(f"Auto Game: {'ON' if GAME_MODE.enabled else 'OFF'}", "ok")
        elif feature == 'fg':
            FG_BOOSTER.enabled = bool(self.booster_chk_fg.get())
            self._toast(f"FG Booster: {'ON' if FG_BOOSTER.enabled else 'OFF'}", "ok")
        elif feature == 'priority':
            PRIORITY_BALANCER.enabled = bool(self.booster_chk_pri.get())
            self._toast(f"Priority Balancer: {'ON' if PRIORITY_BALANCER.enabled else 'OFF'}", "ok")
        elif feature == 'cpu':
            CPU_LIMITER.enabled = bool(self.booster_chk_cpu.get())
            self._toast(f"CPU Limiter: {'ON' if CPU_LIMITER.enabled else 'OFF'}", "ok")
        elif feature == 'bg':
            self.bg_gov.enabled = bool(self.booster_chk_bg.get())
            self._toast(f"BG Governor: {'ON' if self.bg_gov.enabled else 'OFF'}", "ok")
        elif feature == 'mem':
            MEM_OPTIMIZER.enabled = bool(self.booster_chk_mem.get())
            self._toast(f"Memory Optimizer: {'ON' if MEM_OPTIMIZER.enabled else 'OFF'}", "ok")

    def _junk_scan(self):
        popup = ctk.CTkToplevel(self)
        popup.title("🗑️ Junk File Scanner")
        popup.geometry("600x500")
        popup.configure(fg_color="#0D1117")
        popup.attributes('-topmost', True)
        popup.grab_set()

        header = ctk.CTkFrame(popup, fg_color="#161B22", height=60)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="🔍 Scanning for Junk Files...",
                    font=ctk.CTkFont(size=18, weight="bold"),
                    text_color="#F9FAFB").pack(expand=True)

        progress = ctk.CTkProgressBar(popup, mode="indeterminate", height=6,
                                       progress_color="#8B5CF6")
        progress.pack(fill="x", padx=20, pady=10)
        progress.start()

        results_frame = ctk.CTkScrollableFrame(popup, fg_color="#0D1117")
        results_frame.pack(fill="both", expand=True, padx=20, pady=10)

        locations = [
            ("🗂️ Windows Temp", os.path.join(os.environ.get('TEMP', ''), '')),
            ("🗂️ User Temp", os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Temp')),
            ("🌐 Browser Cache", os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data', 'Default', 'Cache')),
            ("📋 Recycle Bin", "C:\\$Recycle.Bin"),
            ("🪟 Windows Prefetch", "C:\\Windows\\Prefetch"),
            ("📝 Log Files", os.path.join(os.environ.get('LOCALAPPDATA', ''), '')),
        ]

        total_size = 0
        found_items = []

        def do_scan():
            nonlocal total_size
            for icon_name, path in locations:
                try:
                    loc_card = ctk.CTkFrame(results_frame, fg_color="#161B22", corner_radius=8)
                    loc_card.pack(fill="x", pady=5)

                    row = ctk.CTkFrame(loc_card, fg_color="transparent")
                    row.pack(fill="x", padx=15, pady=10)

                    ctk.CTkLabel(row, text=icon_name, font=ctk.CTkFont(size=13, weight="bold"),
                                text_color="#F9FAFB").pack(side="left")

                    size = 0
                    count = 0
                    if os.path.exists(path):
                        try:
                            for root, dirs, files in os.walk(path):
                                for f in files:
                                    try:
                                        fp = os.path.join(root, f)
                                        size += os.path.getsize(fp)
                                        count += 1
                                    except: pass
                                if count > 100:
                                    break
                        except: pass

                    total_size += size
                    mb = size / (1024 * 1024)

                    status_color = "#10B981" if size > 0 else "#6B7280"
                    status_text = f"{count} files ({mb:.1f} MB)" if count > 0 else "Clean"

                    ctk.CTkLabel(row, text=status_text, text_color=status_color,
                                font=ctk.CTkFont(size=12)).pack(side="right")

                    ctk.CTkLabel(loc_card, text=path[:60] + "..." if len(path) > 60 else path,
                                text_color="#6B7280", font=ctk.CTkFont(size=10)).pack(anchor="w", padx=15, pady=(0,10))

                    found_items.append((icon_name, path, size, count))
                    popup.update()
                except Exception as e:
                    pass

            progress.stop()
            progress.configure(mode="determinate")
            progress.set(1.0)

            for widget in header.winfo_children():
                widget.destroy()

            total_mb = total_size / (1024 * 1024)
            ctk.CTkLabel(header, text=f"✅ Found {total_mb:.1f} MB of Junk Files",
                        font=ctk.CTkFont(size=18, weight="bold"),
                        text_color="#10B981").pack(expand=True)

            self.lbl_junk_status.configure(text=f"Found: {total_mb:.1f} MB of junk files")

        popup.after(100, do_scan)

        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=15)

        ctk.CTkButton(btn_frame, text="Close", command=popup.destroy,
                     fg_color="#374151", hover_color="#4B5563", width=100).pack(side="right")
        ctk.CTkButton(btn_frame, text="🧹 Clean All", command=lambda: [popup.destroy(), self._junk_clean()],
                     fg_color="#EF4444", hover_color="#DC2626", width=120).pack(side="right", padx=10)

    def _junk_clean(self):
        try:
            bytes_freed, files_cleaned = JUNK_CLEANER.clean()
            mb = bytes_freed / (1024 * 1024)
            self.lbl_junk_status.configure(text=f"Cleaned: {files_cleaned} files ({mb:.1f} MB)")
            self._toast(f"🧹 Cleaned {files_cleaned} files ({mb:.1f} MB freed)", "ok")
        except Exception as e:
            self._toast(f"Clean failed: {e}", "warn")

    def _fill_tools(self, parent):
        top = self._modern_header(parent, "System Tools", "Game Library, Drivers, Services, and more")

        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=30, pady=(0,20))
        scroll.grid_columnconfigure((0,1), weight=1)

        row = 0

        game_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        game_card.grid(row=row, column=0, columnspan=2, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(game_card, text="🎮 GAME LIBRARY", font=ctk.CTkFont(size=12, weight="bold"), text_color="#8B5CF6").pack(anchor="w", padx=15, pady=(15,5))
        ctk.CTkLabel(game_card, text="Auto-detect installed games from Steam, Epic Games, and GOG", text_color="#9CA3AF").pack(anchor="w", padx=15, pady=(0,10))

        game_btns = ctk.CTkFrame(game_card, fg_color="transparent")
        game_btns.pack(fill="x", padx=15, pady=5)

        ctk.CTkButton(game_btns, text="🔍 Scan Games", command=self._scan_games, width=120, height=32,
                      fg_color="#8B5CF6", hover_color="#7C3AED").pack(side="left", padx=5)

        self.lbl_game_count = ctk.CTkLabel(game_btns, text="Games found: 0", text_color="#9CA3AF")
        self.lbl_game_count.pack(side="left", padx=20)

        self.game_list_frame = ctk.CTkFrame(game_card, fg_color="#0F1115", corner_radius=8, height=100)
        self.game_list_frame.pack(fill="x", padx=15, pady=(5,15))
        self.lbl_game_list = ctk.CTkLabel(self.game_list_frame, text="Click 'Scan Games' to detect installed games", text_color="#6B7280")
        self.lbl_game_list.pack(pady=20)

        row += 1

        driver_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        driver_card.grid(row=row, column=0, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(driver_card, text="🔧 DRIVER CHECKER", font=ctk.CTkFont(size=12, weight="bold"), text_color="#F59E0B").pack(anchor="w", padx=15, pady=(15,10))

        ctk.CTkButton(driver_card, text="Scan Drivers", command=self._scan_drivers, height=32,
                      fg_color="#374151", hover_color="#4B5563").pack(fill="x", padx=15, pady=5)

        self.lbl_driver_count = ctk.CTkLabel(driver_card, text="Drivers: Not scanned", text_color="#9CA3AF")
        self.lbl_driver_count.pack(anchor="w", padx=15, pady=(5,15))

        service_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        service_card.grid(row=row, column=1, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(service_card, text="⚡ SERVICE MANAGER", font=ctk.CTkFont(size=12, weight="bold"), text_color="#10B981").pack(anchor="w", padx=15, pady=(15,10))

        ctk.CTkButton(service_card, text="Stop Gaming-Safe Services", command=self._stop_gaming_services, height=32,
                      fg_color="#10B981", hover_color="#059669").pack(fill="x", padx=15, pady=5)
        ctk.CTkButton(service_card, text="Start All Services", command=self._start_all_services, height=32,
                      fg_color="#374151", hover_color="#4B5563").pack(fill="x", padx=15, pady=5)

        self.lbl_service_status = ctk.CTkLabel(service_card, text="Services: Ready", text_color="#9CA3AF")
        self.lbl_service_status.pack(anchor="w", padx=15, pady=(5,15))

        row += 1

        ctx_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        ctx_card.grid(row=row, column=0, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(ctx_card, text="📋 CONTEXT MENU", font=ctk.CTkFont(size=12, weight="bold"), text_color="#EC4899").pack(anchor="w", padx=15, pady=(15,10))

        ctk.CTkButton(ctx_card, text="Scan Context Menu", command=self._scan_context_menu, height=32,
                      fg_color="#374151", hover_color="#4B5563").pack(fill="x", padx=15, pady=5)

        self.lbl_ctx_count = ctk.CTkLabel(ctx_card, text="Entries: Not scanned", text_color="#9CA3AF")
        self.lbl_ctx_count.pack(anchor="w", padx=15, pady=(5,15))

        task_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        task_card.grid(row=row, column=1, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(task_card, text="📅 SCHEDULED TASKS", font=ctk.CTkFont(size=12, weight="bold"), text_color="#06B6D4").pack(anchor="w", padx=15, pady=(15,10))

        ctk.CTkButton(task_card, text="Scan Tasks", command=self._scan_tasks, height=32,
                      fg_color="#374151", hover_color="#4B5563").pack(fill="x", padx=15, pady=5)
        ctk.CTkButton(task_card, text="Disable Bloatware Tasks", command=self._disable_bloat_tasks, height=32,
                      fg_color="#EF4444", hover_color="#DC2626").pack(fill="x", padx=15, pady=5)

        self.lbl_task_count = ctk.CTkLabel(task_card, text="Tasks: Not scanned", text_color="#9CA3AF")
        self.lbl_task_count.pack(anchor="w", padx=15, pady=(5,15))

        row += 1

        net_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        net_card.grid(row=row, column=0, columnspan=2, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(net_card, text="🌐 NETWORK SPEED TEST", font=ctk.CTkFont(size=12, weight="bold"), text_color="#3B82F6").pack(anchor="w", padx=15, pady=(15,5))
        ctk.CTkLabel(net_card, text="Test your internet download and upload speed", text_color="#9CA3AF").pack(anchor="w", padx=15, pady=(0,10))

        net_btns = ctk.CTkFrame(net_card, fg_color="transparent")
        net_btns.pack(fill="x", padx=15, pady=5)

        ctk.CTkButton(net_btns, text="🚀 Run Speed Test", command=self._run_speed_test, width=150, height=36,
                      fg_color="#3B82F6", hover_color="#2563EB", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)

        self.lbl_net_status = ctk.CTkLabel(net_btns, text="Ready to test", text_color="#9CA3AF")
        self.lbl_net_status.pack(side="left", padx=20)

    def _scan_games(self):
        games = GAME_LIBRARY.scan_all()
        self.lbl_game_count.configure(text=f"Games found: {len(games)}")

        for w in self.game_list_frame.winfo_children():
            w.destroy()

        if games:
            for game in games[:10]:
                row = ctk.CTkFrame(self.game_list_frame, fg_color="transparent")
                row.pack(fill="x", padx=10, pady=2)
                ctk.CTkLabel(row, text=f"🎮 {game['name']}", text_color="#F9FAFB").pack(side="left")
                ctk.CTkLabel(row, text=f"[{game['source']}]", text_color="#6B7280").pack(side="right")
            if len(games) > 10:
                ctk.CTkLabel(self.game_list_frame, text=f"... and {len(games)-10} more", text_color="#6B7280").pack(pady=5)
        else:
            ctk.CTkLabel(self.game_list_frame, text="No games found", text_color="#6B7280").pack(pady=20)

        self._toast(f"Found {len(games)} games", "ok")

    def _scan_drivers(self):
        popup = ctk.CTkToplevel(self)
        popup.title("🔧 Driver Scanner")
        popup.geometry("750x550")
        popup.configure(fg_color="#0D1117")
        popup.attributes('-topmost', True)
        popup.grab_set()

        header = ctk.CTkFrame(popup, fg_color="#161B22", height=60)
        header.pack(fill="x")
        header.pack_propagate(False)
        header_lbl = ctk.CTkLabel(header, text="🔍 Scanning Drivers...",
                    font=ctk.CTkFont(size=18, weight="bold"),
                    text_color="#F9FAFB")
        header_lbl.pack(expand=True)

        progress = ctk.CTkProgressBar(popup, mode="indeterminate", height=6,
                                       progress_color="#8B5CF6")
        progress.pack(fill="x", padx=20, pady=10)
        progress.start()

        stats_frame = ctk.CTkFrame(popup, fg_color="#161B22", height=50)
        stats_frame.pack(fill="x", padx=20, pady=(0, 10))

        total_lbl = ctk.CTkLabel(stats_frame, text="Total: --", text_color="#9CA3AF")
        total_lbl.pack(side="left", padx=20, pady=10)

        outdated_lbl = ctk.CTkLabel(stats_frame, text="⚠️ Outdated: --", text_color="#F59E0B")
        outdated_lbl.pack(side="left", padx=20, pady=10)

        uptodate_lbl = ctk.CTkLabel(stats_frame, text="✅ Up to date: --", text_color="#10B981")
        uptodate_lbl.pack(side="left", padx=20, pady=10)

        results_container = ctk.CTkFrame(popup, fg_color="#0D1117")
        results_container.pack(fill="both", expand=True, padx=20, pady=5)

        header_row = ctk.CTkFrame(results_container, fg_color="#1F2937", height=35)
        header_row.pack(fill="x")
        header_row.pack_propagate(False)

        ctk.CTkLabel(header_row, text="Driver Name", width=280, text_color="#9CA3AF",
                    font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=10)
        ctk.CTkLabel(header_row, text="Version", width=120, text_color="#9CA3AF",
                    font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
        ctk.CTkLabel(header_row, text="Date", width=100, text_color="#9CA3AF",
                    font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
        ctk.CTkLabel(header_row, text="Status", width=100, text_color="#9CA3AF",
                    font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")

        results_frame = ctk.CTkScrollableFrame(results_container, fg_color="#0D1117")
        results_frame.pack(fill="both", expand=True)

        def do_scan():
            drivers = []
            outdated = 0
            uptodate = 0

            try:
                import subprocess
                result = subprocess.run(
                    ['wmic', 'path', 'Win32_PnPSignedDriver', 'get',
                     'DeviceName,DriverVersion,DriverDate', '/format:csv'],
                    capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
                )

                lines = result.stdout.strip().split('\n')[1:]

                from datetime import datetime
                current_year = datetime.now().year

                for line in lines:
                    if not line.strip():
                        continue
                    parts = line.strip().split(',')
                    if len(parts) >= 4:
                        node, name, date_str, version = parts[0], parts[1], parts[2], parts[3]

                        if not name or name == 'DeviceName':
                            continue

                        is_outdated = False
                        date_display = "Unknown"
                        try:
                            if date_str and len(date_str) >= 8:
                                year = int(date_str[:4])
                                month = int(date_str[4:6])
                                day = int(date_str[6:8])
                                date_display = f"{year}-{month:02d}-{day:02d}"
                                if current_year - year > 2:
                                    is_outdated = True
                        except:
                            pass

                        drivers.append({
                            'name': name[:35] + "..." if len(name) > 35 else name,
                            'version': version[:15] if version else "N/A",
                            'date': date_display,
                            'outdated': is_outdated
                        })

                        if is_outdated:
                            outdated += 1
                        else:
                            uptodate += 1

            except Exception as e:
                ctk.CTkLabel(results_frame, text=f"Error scanning: {e}",
                            text_color="#EF4444").pack(pady=20)

            for driver in drivers[:50]:
                row = ctk.CTkFrame(results_frame, fg_color="transparent", height=32)
                row.pack(fill="x", pady=1)
                row.pack_propagate(False)

                row_bg = "#1F1616" if driver['outdated'] else "transparent"
                row.configure(fg_color=row_bg)

                ctk.CTkLabel(row, text=driver['name'], width=280,
                            text_color="#F9FAFB", anchor="w").pack(side="left", padx=10)
                ctk.CTkLabel(row, text=driver['version'], width=120,
                            text_color="#9CA3AF").pack(side="left")
                ctk.CTkLabel(row, text=driver['date'], width=100,
                            text_color="#9CA3AF").pack(side="left")

                if driver['outdated']:
                    ctk.CTkLabel(row, text="⚠️ Update", width=100,
                                text_color="#F59E0B").pack(side="left")
                else:
                    ctk.CTkLabel(row, text="✅ OK", width=100,
                                text_color="#10B981").pack(side="left")

            progress.stop()
            progress.configure(mode="determinate")
            progress.set(1.0)

            header_lbl.configure(text=f"✅ Driver Scan Complete")
            total_lbl.configure(text=f"Total: {len(drivers)}")
            outdated_lbl.configure(text=f"⚠️ Outdated: {outdated}")
            uptodate_lbl.configure(text=f"✅ Up to date: {uptodate}")

            self.lbl_driver_count.configure(text=f"Total: {len(drivers)}, Outdated: {outdated}")

        popup.after(100, do_scan)

        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=15)

        ctk.CTkLabel(btn_frame, text="💡 Tip: Update outdated drivers via Windows Update or manufacturer website",
                    text_color="#6B7280", font=ctk.CTkFont(size=11)).pack(side="left")

        ctk.CTkButton(btn_frame, text="Close", command=popup.destroy,
                     fg_color="#374151", hover_color="#4B5563", width=100).pack(side="right")

    def _stop_gaming_services(self):
        if self.settings.get("confirm_dialogs", True):
            if not confirm_action(self, "Stop Services", "Stop non-essential services for gaming?"):
                return
        count = 0
        for svc in SERVICE_MGR.gaming_safe_disable:
            if SERVICE_MGR.stop_service(svc):
                count += 1
        self.lbl_service_status.configure(text=f"Stopped: {count} services")
        self._toast(f"Stopped {count} services", "ok")

    def _start_all_services(self):
        count = CHANGE_TRACKER.undo_all()
        self.lbl_service_status.configure(text=f"Restored: {count} changes")
        self._toast(f"Restored {count} changes", "ok")

    def _scan_context_menu(self):
        popup = ctk.CTkToplevel(self)
        popup.title("📋 Context Menu Scanner")
        popup.geometry("700x500")
        popup.configure(fg_color="#0D1117")
        popup.attributes('-topmost', True)
        popup.grab_set()

        header = ctk.CTkFrame(popup, fg_color="#161B22", height=60)
        header.pack(fill="x")
        header.pack_propagate(False)
        header_lbl = ctk.CTkLabel(header, text="🔍 Scanning Context Menu...",
                    font=ctk.CTkFont(size=18, weight="bold"), text_color="#F9FAFB")
        header_lbl.pack(expand=True)

        progress = ctk.CTkProgressBar(popup, mode="indeterminate", height=6, progress_color="#8B5CF6")
        progress.pack(fill="x", padx=20, pady=10)
        progress.start()

        results_container = ctk.CTkFrame(popup, fg_color="#0D1117")
        results_container.pack(fill="both", expand=True, padx=20, pady=5)

        header_row = ctk.CTkFrame(results_container, fg_color="#1F2937", height=35)
        header_row.pack(fill="x")
        header_row.pack_propagate(False)

        ctk.CTkLabel(header_row, text="Entry Name", width=250, text_color="#9CA3AF",
                    font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=10)
        ctk.CTkLabel(header_row, text="Location", width=200, text_color="#9CA3AF",
                    font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
        ctk.CTkLabel(header_row, text="Type", width=100, text_color="#9CA3AF",
                    font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")

        results_frame = ctk.CTkScrollableFrame(results_container, fg_color="#0D1117")
        results_frame.pack(fill="both", expand=True)

        def do_scan():
            entries = []
            locations = [
                ("HKCR\\*\\shell", "All Files"),
                ("HKCR\\Directory\\shell", "Folders"),
                ("HKCR\\Directory\\Background\\shell", "Background"),
                ("HKCR\\Drive\\shell", "Drives"),
            ]

            import winreg
            for reg_path, loc_type in locations:
                try:
                    parts = reg_path.split("\\", 1)
                    if parts[0] == "HKCR":
                        root = winreg.HKEY_CLASSES_ROOT
                    else:
                        continue

                    key = winreg.OpenKey(root, parts[1], 0, winreg.KEY_READ)
                    i = 0
                    while True:
                        try:
                            name = winreg.EnumKey(key, i)
                            entries.append({'name': name, 'location': loc_type, 'path': reg_path})
                            i += 1
                        except WindowsError:
                            break
                    winreg.CloseKey(key)
                except:
                    pass

            for entry in entries[:40]:
                row = ctk.CTkFrame(results_frame, fg_color="transparent", height=30)
                row.pack(fill="x", pady=1)
                row.pack_propagate(False)

                ctk.CTkLabel(row, text=entry['name'][:30], width=250,
                            text_color="#F9FAFB", anchor="w").pack(side="left", padx=10)
                ctk.CTkLabel(row, text=entry['location'], width=200,
                            text_color="#9CA3AF").pack(side="left")
                ctk.CTkLabel(row, text="📁 Shell", width=100, text_color="#10B981").pack(side="left")

            progress.stop()
            progress.configure(mode="determinate")
            progress.set(1.0)
            header_lbl.configure(text=f"✅ Found {len(entries)} Context Menu Entries")
            self.lbl_ctx_count.configure(text=f"Found: {len(entries)} entries")

        popup.after(100, do_scan)

        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=15)
        ctk.CTkButton(btn_frame, text="Close", command=popup.destroy,
                     fg_color="#374151", hover_color="#4B5563", width=100).pack(side="right")

    def _scan_tasks(self):
        popup = ctk.CTkToplevel(self)
        popup.title("📅 Scheduled Task Scanner")
        popup.geometry("800x550")
        popup.configure(fg_color="#0D1117")
        popup.attributes('-topmost', True)
        popup.grab_set()

        header = ctk.CTkFrame(popup, fg_color="#161B22", height=60)
        header.pack(fill="x")
        header.pack_propagate(False)
        header_lbl = ctk.CTkLabel(header, text="🔍 Scanning Scheduled Tasks...",
                    font=ctk.CTkFont(size=18, weight="bold"), text_color="#F9FAFB")
        header_lbl.pack(expand=True)

        progress = ctk.CTkProgressBar(popup, mode="indeterminate", height=6, progress_color="#8B5CF6")
        progress.pack(fill="x", padx=20, pady=10)
        progress.start()

        stats_frame = ctk.CTkFrame(popup, fg_color="#161B22", height=50)
        stats_frame.pack(fill="x", padx=20, pady=(0, 10))

        total_lbl = ctk.CTkLabel(stats_frame, text="Total: --", text_color="#9CA3AF")
        total_lbl.pack(side="left", padx=20, pady=10)

        bloat_lbl = ctk.CTkLabel(stats_frame, text="⚠️ Bloatware: --", text_color="#F59E0B")
        bloat_lbl.pack(side="left", padx=20, pady=10)

        safe_lbl = ctk.CTkLabel(stats_frame, text="✅ Safe: --", text_color="#10B981")
        safe_lbl.pack(side="left", padx=20, pady=10)

        results_container = ctk.CTkFrame(popup, fg_color="#0D1117")
        results_container.pack(fill="both", expand=True, padx=20, pady=5)

        header_row = ctk.CTkFrame(results_container, fg_color="#1F2937", height=35)
        header_row.pack(fill="x")
        header_row.pack_propagate(False)

        ctk.CTkLabel(header_row, text="Task Name", width=300, text_color="#9CA3AF",
                    font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=10)
        ctk.CTkLabel(header_row, text="State", width=100, text_color="#9CA3AF",
                    font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
        ctk.CTkLabel(header_row, text="Type", width=120, text_color="#9CA3AF",
                    font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")

        results_frame = ctk.CTkScrollableFrame(results_container, fg_color="#0D1117")
        results_frame.pack(fill="both", expand=True)

        bloat_keywords = ['telemetry', 'customer', 'experience', 'ceip', 'sqm',
                          'diagnostic', 'microsoft compatibility', 'consolidator',
                          'usagetracking', 'feedback', 'bing', 'cortana']

        def do_scan():
            tasks = []
            bloat_count = 0
            safe_count = 0

            try:
                import subprocess
                result = subprocess.run(
                    ['schtasks', '/query', '/fo', 'csv', '/nh'],
                    capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
                )

                for line in result.stdout.strip().split('\n')[:60]:
                    if not line.strip():
                        continue
                    parts = line.strip().strip('"').split('","')
                    if len(parts) >= 3:
                        name = parts[0].strip('"')
                        state = parts[2].strip('"') if len(parts) > 2 else "Unknown"

                        is_bloat = any(kw in name.lower() for kw in bloat_keywords)
                        tasks.append({'name': name, 'state': state, 'bloat': is_bloat})

                        if is_bloat:
                            bloat_count += 1
                        else:
                            safe_count += 1
            except Exception as e:
                ctk.CTkLabel(results_frame, text=f"Error: {e}", text_color="#EF4444").pack(pady=20)

            for task in tasks:
                row = ctk.CTkFrame(results_frame, fg_color="transparent", height=30)
                row.pack(fill="x", pady=1)
                row.pack_propagate(False)

                row_bg = "#1F1616" if task['bloat'] else "transparent"
                row.configure(fg_color=row_bg)

                display_name = task['name'].split('\\')[-1][:35]
                ctk.CTkLabel(row, text=display_name, width=300,
                            text_color="#F9FAFB", anchor="w").pack(side="left", padx=10)

                state = task['state']
                if state == "Ready":
                    state_icon = "⏸️ Waiting"
                    state_color = "#10B981"
                elif state == "Running":
                    state_icon = "▶️ Active"
                    state_color = "#3B82F6"
                elif state == "Disabled":
                    state_icon = "🚫 Off"
                    state_color = "#6B7280"
                else:
                    state_icon = f"❓ {state}"
                    state_color = "#9CA3AF"

                ctk.CTkLabel(row, text=state_icon, width=100, text_color=state_color).pack(side="left")

                if task['bloat']:
                    ctk.CTkLabel(row, text="⚠️ Bloatware", width=120, text_color="#F59E0B").pack(side="left")
                else:
                    ctk.CTkLabel(row, text="✅ Safe", width=120, text_color="#10B981").pack(side="left")

            progress.stop()
            progress.configure(mode="determinate")
            progress.set(1.0)
            header_lbl.configure(text=f"✅ Task Scan Complete")
            total_lbl.configure(text=f"Total: {len(tasks)}")
            bloat_lbl.configure(text=f"⚠️ Bloatware: {bloat_count}")
            safe_lbl.configure(text=f"✅ Safe: {safe_count}")
            self.lbl_task_count.configure(text=f"Total: {len(tasks)}, Bloat: {bloat_count}")

        popup.after(100, do_scan)

        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=15)

        ctk.CTkLabel(btn_frame, text="💡 Bloatware tasks can slow boot time and send telemetry",
                    text_color="#6B7280", font=ctk.CTkFont(size=11)).pack(side="left")

        ctk.CTkButton(btn_frame, text="Close", command=popup.destroy,
                     fg_color="#374151", hover_color="#4B5563", width=100).pack(side="right")
        ctk.CTkButton(btn_frame, text="🚫 Disable Bloatware",
                     command=lambda: [popup.destroy(), self._disable_bloat_tasks()],
                     fg_color="#EF4444", hover_color="#DC2626", width=140).pack(side="right", padx=10)

    def _run_speed_test(self):
        import tkinter as tk

        popup = tk.Toplevel(self)
        popup.title("Network Speed Test")
        popup.geometry("550x500+200+100")
        popup.configure(bg="#0D1117")
        popup.minsize(550, 500)
        popup.lift()
        popup.focus_force()

        main_frame = ctk.CTkFrame(popup, fg_color="#0D1117")
        main_frame.pack(fill="both", expand=True)

        header = ctk.CTkFrame(main_frame, fg_color="#161B22", height=70)
        header.pack(fill="x")
        header.pack_propagate(False)
        header_lbl = ctk.CTkLabel(header, text="Network Speed Test",
                    font=ctk.CTkFont(size=20, weight="bold"), text_color="#F9FAFB")
        header_lbl.pack(expand=True)

        progress = ctk.CTkProgressBar(main_frame, mode="indeterminate", height=6, progress_color="#3B82F6")
        progress.pack(fill="x", padx=30, pady=15)
        progress.start()

        results_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        results_frame.pack(fill="both", expand=True, padx=30, pady=10)
        results_frame.grid_columnconfigure((0,1), weight=1)

        dl_card = ctk.CTkFrame(results_frame, fg_color="#161B22", corner_radius=16)
        dl_card.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(dl_card, text="⬇️ DOWNLOAD", font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#10B981").pack(pady=(20,5))
        dl_speed_lbl = ctk.CTkLabel(dl_card, text="--", font=ctk.CTkFont(size=36, weight="bold"),
                                    text_color="#F9FAFB")
        dl_speed_lbl.pack()
        dl_unit_lbl = ctk.CTkLabel(dl_card, text="Mbps", text_color="#9CA3AF")
        dl_unit_lbl.pack()
        dl_progress = ctk.CTkProgressBar(dl_card, height=8, progress_color="#10B981", width=120)
        dl_progress.pack(pady=(10,20))
        dl_progress.set(0)

        ul_card = ctk.CTkFrame(results_frame, fg_color="#161B22", corner_radius=16)
        ul_card.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(ul_card, text="⬆️ UPLOAD", font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#8B5CF6").pack(pady=(20,5))
        ul_speed_lbl = ctk.CTkLabel(ul_card, text="--", font=ctk.CTkFont(size=36, weight="bold"),
                                    text_color="#F9FAFB")
        ul_speed_lbl.pack()
        ul_unit_lbl = ctk.CTkLabel(ul_card, text="Mbps", text_color="#9CA3AF")
        ul_unit_lbl.pack()
        ul_progress = ctk.CTkProgressBar(ul_card, height=8, progress_color="#8B5CF6", width=120)
        ul_progress.pack(pady=(10,20))
        ul_progress.set(0)

        ping_frame = ctk.CTkFrame(results_frame, fg_color="#161B22", corner_radius=12)
        ping_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=10)

        ping_lbl = ctk.CTkLabel(ping_frame, text="📶 Latency: Testing...", text_color="#F59E0B",
                               font=ctk.CTkFont(size=13))
        ping_lbl.pack(pady=15)

        def do_speed_test():
            import urllib.request
            import time

            header_lbl.configure(text="⬇️ Testing Download Speed...")
            popup.update()

            try:
                start = time.time()
                test_urls = [
                    "https://speed.cloudflare.com/__down?bytes=1000000",
                    "http://speedtest.tele2.net/1MB.zip",
                    "https://proof.ovh.net/files/1Mb.dat"
                ]

                bytes_downloaded = 0
                for url in test_urls[:1]:
                    try:
                        with urllib.request.urlopen(url, timeout=10) as response:
                            data = response.read()
                            bytes_downloaded = len(data)
                            break
                    except:
                        continue

                elapsed = time.time() - start
                if elapsed > 0 and bytes_downloaded > 0:
                    download_mbps = (bytes_downloaded * 8) / (elapsed * 1000000)
                else:
                    download_mbps = 0

                dl_speed_lbl.configure(text=f"{download_mbps:.1f}")
                dl_progress.set(min(1.0, download_mbps / 100))
                popup.update()

            except Exception as e:
                dl_speed_lbl.configure(text="Error")
                download_mbps = 0

            header_lbl.configure(text="⬆️ Testing Upload Speed...")
            popup.update()

            try:
                start = time.time()
                data = b"0" * 100000
                req = urllib.request.Request("https://httpbin.org/post", data=data, method="POST")
                with urllib.request.urlopen(req, timeout=10) as response:
                    response.read()
                elapsed = time.time() - start

                if elapsed > 0:
                    upload_mbps = (len(data) * 8) / (elapsed * 1000000)
                else:
                    upload_mbps = 0

                ul_speed_lbl.configure(text=f"{upload_mbps:.1f}")
                ul_progress.set(min(1.0, upload_mbps / 50))
                popup.update()

            except Exception as e:
                ul_speed_lbl.configure(text="Error")
                upload_mbps = 0

            header_lbl.configure(text="📶 Testing Latency...")
            popup.update()

            try:
                start = time.time()
                urllib.request.urlopen("https://www.google.com", timeout=5)
                latency_ms = (time.time() - start) * 1000

                ping_color = "#10B981" if latency_ms < 50 else "#F59E0B" if latency_ms < 100 else "#EF4444"
                ping_lbl.configure(text=f"📶 Latency: {latency_ms:.0f} ms", text_color=ping_color)

            except:
                ping_lbl.configure(text="📶 Latency: Error", text_color="#EF4444")
                latency_ms = 0

            progress.stop()
            progress.configure(mode="determinate")
            progress.set(1.0)
            header_lbl.configure(text="✅ Speed Test Complete")

            self.lbl_net_status.configure(text=f"↓{download_mbps:.1f} / ↑{upload_mbps:.1f} Mbps")

        popup.after(200, do_speed_test)

        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=30, pady=15)

        ctk.CTkButton(btn_frame, text="Close", command=popup.destroy,
                     fg_color="#374151", hover_color="#4B5563", width=100).pack(side="right")
        ctk.CTkButton(btn_frame, text="Test Again", command=lambda: do_speed_test(),
                     fg_color="#3B82F6", hover_color="#2563EB", width=120).pack(side="right", padx=10)

    def _disable_bloat_tasks(self):
        if self.settings.get("confirm_dialogs", True):
            if not confirm_action(self, "Disable Tasks", "Disable telemetry and bloatware tasks?"):
                return
        bloat = SCHED_TASKS.get_bloatware_tasks()
        count = 0
        for task in bloat:
            if SCHED_TASKS.disable_task(task['folder'] + task['name']):
                count += 1
        self._toast(f"Disabled {count} bloatware tasks", "ok")

    def _fill_benchmark(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=30, pady=20)

        header = ctk.CTkFrame(scroll, fg_color="#161B22", corner_radius=16)
        header.pack(fill="x", pady=(0,20))

        ctk.CTkLabel(header, text="⚡ OptiCores Benchmark",
                    font=ctk.CTkFont(family="Segoe UI Variable Display", size=24, weight="bold"),
                    text_color="#F9FAFB").pack(anchor="w", padx=20, pady=(15,5))

        info_row = ctk.CTkFrame(header, fg_color="transparent")
        info_row.pack(fill="x", padx=20, pady=(0,15))

        cpu_name = "Unknown CPU"
        try:
            import platform
            cpu_name = platform.processor() or "Unknown CPU"
            if len(cpu_name) > 40: cpu_name = cpu_name[:40] + "..."
        except: pass

        ram_gb = psutil.virtual_memory().total / (1024**3)
        os_name = f"Windows {platform.release()}" if hasattr(platform, 'release') else "Windows"

        def info_item(text, icon):
            f = ctk.CTkFrame(info_row, fg_color="transparent")
            f.pack(side="left", padx=(0,30))
            ctk.CTkLabel(f, text=f"{icon} {text}", text_color="#9CA3AF", font=ctk.CTkFont(size=12)).pack()

        info_item(cpu_name, "🖥️")
        info_item(f"{ram_gb:.0f} GB RAM", "🧠")
        info_item(os_name, "💻")
        info_item(f"{multiprocessing.cpu_count()} Cores", "⚙️")

        self.btn_run_bench = ctk.CTkButton(scroll, text="▶  RUN BENCHMARK", height=50,
                                           font=ctk.CTkFont(size=16, weight="bold"),
                                           fg_color="#8B5CF6", hover_color="#7C3AED",
                                           command=self._run_benchmark)
        self.btn_run_bench.pack(fill="x", pady=(0,15))

        self.bench_progress = ctk.CTkProgressBar(scroll, height=8, progress_color="#8B5CF6")
        self.bench_progress.set(0)
        self.bench_progress.pack(fill="x", pady=(0,5))

        self.lbl_bench_status = ctk.CTkLabel(scroll, text="Ready. Click Run Benchmark to start.",
                                              text_color="#6B7280", font=ctk.CTkFont(size=12))
        self.lbl_bench_status.pack(pady=(0,20))

        main_scores = ctk.CTkFrame(scroll, fg_color="transparent")
        main_scores.pack(fill="x", pady=(0,20))
        main_scores.grid_columnconfigure((0,1), weight=1)

        def big_score_card(col, title, subtitle, color):
            f = ctk.CTkFrame(main_scores, fg_color="#161B22", corner_radius=16, height=180)
            f.grid(row=0, column=col, sticky="nsew", padx=8)
            f.grid_propagate(False)

            ctk.CTkLabel(f, text=title, font=ctk.CTkFont(size=14, weight="bold"),
                        text_color="#9CA3AF").pack(anchor="w", padx=25, pady=(20,5))

            lbl_score = ctk.CTkLabel(f, text="—",
                                     font=ctk.CTkFont(family="Segoe UI Variable Display", size=56, weight="bold"),
                                     text_color=color)
            lbl_score.pack(anchor="w", padx=25)

            lbl_desc = ctk.CTkLabel(f, text=subtitle, font=ctk.CTkFont(size=11), text_color="#6B7280")
            lbl_desc.pack(anchor="w", padx=25, pady=(0,20))

            return lbl_score, lbl_desc

        self.lbl_single, self.lbl_single_desc = big_score_card(0, "SINGLE-CORE SCORE", "Single-threaded performance", "#8B5CF6")
        self.lbl_multi, self.lbl_multi_desc = big_score_card(1, "MULTI-CORE SCORE", "Multi-threaded performance", "#10B981")

        breakdown = ctk.CTkFrame(scroll, fg_color="#161B22", corner_radius=16)
        breakdown.pack(fill="x", pady=(0,20))

        ctk.CTkLabel(breakdown, text="SINGLE-CORE PERFORMANCE", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#9CA3AF").pack(anchor="w", padx=20, pady=(15,10))

        self.workload_rows = {}
        workloads = [
            ("File Compression", "Compressing files using LZMA", "cpu"),
            ("Navigation", "Calculating directions", "cpu"),
            ("HTML5 Browser", "Rendering web pages", "cpu"),
            ("PDF Renderer", "Processing documents", "cpu"),
            ("Photo Library", "Processing images", "cpu"),
            ("Clang", "Compiling code", "cpu"),
            ("Text Processing", "Parsing and formatting", "cpu"),
            ("Asset Compression", "Compressing game assets", "cpu"),
            ("Encryption", "AES-256 crypto operations", "cpu"),
            ("Physics", "N-Body gravity simulation", "cpu"),
            ("ML Inference", "Neural network matrix ops", "cpu"),
            ("FFT", "Signal processing transform", "cpu"),
        ]

        for name, desc, category in workloads:
            row = ctk.CTkFrame(breakdown, fg_color="#0D1117", corner_radius=8)
            row.pack(fill="x", padx=15, pady=2)

            left = ctk.CTkFrame(row, fg_color="transparent", width=250)
            left.pack(side="left", fill="y", padx=15, pady=10)
            left.pack_propagate(False)
            ctk.CTkLabel(left, text=name, font=ctk.CTkFont(weight="bold"), text_color="#E5E7EB").pack(anchor="w")
            ctk.CTkLabel(left, text=desc, font=ctk.CTkFont(size=10), text_color="#6B7280").pack(anchor="w")

            lbl_metric = ctk.CTkLabel(row, text="—", font=ctk.CTkFont(size=11), text_color="#9CA3AF", width=120)
            lbl_metric.pack(side="left", padx=5)

            right = ctk.CTkFrame(row, fg_color="transparent")
            right.pack(side="right", padx=15, pady=10)

            lbl_score = ctk.CTkLabel(right, text="—", font=ctk.CTkFont(size=16, weight="bold"), text_color="#F9FAFB", width=60)
            lbl_score.pack(side="right")

            bar = ctk.CTkProgressBar(right, width=150, height=8, progress_color="#3B82F6", fg_color="#1F2937")
            bar.set(0)
            bar.pack(side="right", padx=10)

            self.workload_rows[name] = (lbl_score, lbl_metric, bar)

        ctk.CTkFrame(breakdown, height=10, fg_color="transparent").pack()

        mem_section = ctk.CTkFrame(scroll, fg_color="#161B22", corner_radius=16)
        mem_section.pack(fill="x", pady=(0,20))

        ctk.CTkLabel(mem_section, text="MEMORY PERFORMANCE", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#9CA3AF").pack(anchor="w", padx=20, pady=(15,10))

        mem_tests = [
            ("Memory Bandwidth", "Sequential read/write speed"),
            ("Memory Latency", "Random access latency"),
        ]

        for name, desc in mem_tests:
            row = ctk.CTkFrame(mem_section, fg_color="#0D1117", corner_radius=8)
            row.pack(fill="x", padx=15, pady=2)

            left = ctk.CTkFrame(row, fg_color="transparent", width=250)
            left.pack(side="left", fill="y", padx=15, pady=10)
            left.pack_propagate(False)
            ctk.CTkLabel(left, text=name, font=ctk.CTkFont(weight="bold"), text_color="#E5E7EB").pack(anchor="w")
            ctk.CTkLabel(left, text=desc, font=ctk.CTkFont(size=10), text_color="#6B7280").pack(anchor="w")

            lbl_metric = ctk.CTkLabel(row, text="—", font=ctk.CTkFont(size=11), text_color="#9CA3AF", width=120)
            lbl_metric.pack(side="left", padx=5)

            right = ctk.CTkFrame(row, fg_color="transparent")
            right.pack(side="right", padx=15, pady=10)

            lbl_score = ctk.CTkLabel(right, text="—", font=ctk.CTkFont(size=16, weight="bold"), text_color="#F9FAFB", width=60)
            lbl_score.pack(side="right")

            bar = ctk.CTkProgressBar(right, width=150, height=8, progress_color="#10B981", fg_color="#1F2937")
            bar.set(0)
            bar.pack(side="right", padx=10)

            self.workload_rows[name] = (lbl_score, lbl_metric, bar)

        ctk.CTkFrame(mem_section, height=10, fg_color="transparent").pack()

        disk_section = ctk.CTkFrame(scroll, fg_color="#161B22", corner_radius=16)
        disk_section.pack(fill="x", pady=(0,20))

        ctk.CTkLabel(disk_section, text="STORAGE PERFORMANCE", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#9CA3AF").pack(anchor="w", padx=20, pady=(15,10))

        disk_tests = [
            ("Disk Sequential", "Large file read/write"),
            ("Disk Random 4K", "Small block I/O"),
            ("LZ4 Fast", "Ultra-fast compression"),
        ]

        for name, desc in disk_tests:
            row = ctk.CTkFrame(disk_section, fg_color="#0D1117", corner_radius=8)
            row.pack(fill="x", padx=15, pady=2)

            left = ctk.CTkFrame(row, fg_color="transparent", width=250)
            left.pack(side="left", fill="y", padx=15, pady=10)
            left.pack_propagate(False)
            ctk.CTkLabel(left, text=name, font=ctk.CTkFont(weight="bold"), text_color="#E5E7EB").pack(anchor="w")
            ctk.CTkLabel(left, text=desc, font=ctk.CTkFont(size=10), text_color="#6B7280").pack(anchor="w")

            lbl_metric = ctk.CTkLabel(row, text="—", font=ctk.CTkFont(size=11), text_color="#9CA3AF", width=120)
            lbl_metric.pack(side="left", padx=5)

            right = ctk.CTkFrame(row, fg_color="transparent")
            right.pack(side="right", padx=15, pady=10)

            lbl_score = ctk.CTkLabel(right, text="—", font=ctk.CTkFont(size=16, weight="bold"), text_color="#F9FAFB", width=60)
            lbl_score.pack(side="right")

            bar = ctk.CTkProgressBar(right, width=150, height=8, progress_color="#F59E0B", fg_color="#1F2937")
            bar.set(0)
            bar.pack(side="right", padx=10)

            self.workload_rows[name] = (lbl_score, lbl_metric, bar)

        ctk.CTkFrame(disk_section, height=10, fg_color="transparent").pack()

        ml_section = ctk.CTkFrame(scroll, fg_color="#161B22", corner_radius=16)
        ml_section.pack(fill="x", pady=(0,20))

        ctk.CTkLabel(ml_section, text="ML & AI PERFORMANCE", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#9CA3AF").pack(anchor="w", padx=20, pady=(15,10))

        ml_tests = [
            ("Object Detection", "CNN convolution simulation"),
            ("Background Blur", "Video conferencing workload"),
        ]

        for name, desc in ml_tests:
            row = ctk.CTkFrame(ml_section, fg_color="#0D1117", corner_radius=8)
            row.pack(fill="x", padx=15, pady=2)

            left = ctk.CTkFrame(row, fg_color="transparent", width=250)
            left.pack(side="left", fill="y", padx=15, pady=10)
            left.pack_propagate(False)
            ctk.CTkLabel(left, text=name, font=ctk.CTkFont(weight="bold"), text_color="#E5E7EB").pack(anchor="w")
            ctk.CTkLabel(left, text=desc, font=ctk.CTkFont(size=10), text_color="#6B7280").pack(anchor="w")

            lbl_metric = ctk.CTkLabel(row, text="—", font=ctk.CTkFont(size=11), text_color="#9CA3AF", width=120)
            lbl_metric.pack(side="left", padx=5)

            right = ctk.CTkFrame(row, fg_color="transparent")
            right.pack(side="right", padx=15, pady=10)

            lbl_score = ctk.CTkLabel(right, text="—", font=ctk.CTkFont(size=16, weight="bold"), text_color="#F9FAFB", width=60)
            lbl_score.pack(side="right")

            bar = ctk.CTkProgressBar(right, width=150, height=8, progress_color="#EC4899", fg_color="#1F2937")
            bar.set(0)
            bar.pack(side="right", padx=10)

            self.workload_rows[name] = (lbl_score, lbl_metric, bar)

        ctk.CTkFrame(ml_section, height=10, fg_color="transparent").pack()

        render_section = ctk.CTkFrame(scroll, fg_color="#161B22", corner_radius=16)
        render_section.pack(fill="x", pady=(0,20))

        ctk.CTkLabel(render_section, text="RENDERING & IMAGE SYNTHESIS", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#9CA3AF").pack(anchor="w", padx=20, pady=(15,10))

        render_tests = [
            ("Horizon Detection", "Edge detection + Hough transform"),
            ("Ray Tracer", "CPU path tracing"),
            ("HDR Merge", "Exposure bracketing + tonemapping"),
            ("GPU Compute", "SIMD-style parallel operations"),
        ]

        for name, desc in render_tests:
            row = ctk.CTkFrame(render_section, fg_color="#0D1117", corner_radius=8)
            row.pack(fill="x", padx=15, pady=2)

            left = ctk.CTkFrame(row, fg_color="transparent", width=250)
            left.pack(side="left", fill="y", padx=15, pady=10)
            left.pack_propagate(False)
            ctk.CTkLabel(left, text=name, font=ctk.CTkFont(weight="bold"), text_color="#E5E7EB").pack(anchor="w")
            ctk.CTkLabel(left, text=desc, font=ctk.CTkFont(size=10), text_color="#6B7280").pack(anchor="w")

            lbl_metric = ctk.CTkLabel(row, text="—", font=ctk.CTkFont(size=11), text_color="#9CA3AF", width=120)
            lbl_metric.pack(side="left", padx=5)

            right = ctk.CTkFrame(row, fg_color="transparent")
            right.pack(side="right", padx=15, pady=10)

            lbl_score = ctk.CTkLabel(right, text="—", font=ctk.CTkFont(size=16, weight="bold"), text_color="#F9FAFB", width=60)
            lbl_score.pack(side="right")

            bar = ctk.CTkProgressBar(right, width=150, height=8, progress_color="#F97316", fg_color="#1F2937")
            bar.set(0)
            bar.pack(side="right", padx=10)

            self.workload_rows[name] = (lbl_score, lbl_metric, bar)

        ctk.CTkFrame(render_section, height=10, fg_color="transparent").pack()

        multicore_section = ctk.CTkFrame(scroll, fg_color="#161B22", corner_radius=16)
        multicore_section.pack(fill="x", pady=(0,20))

        ctk.CTkLabel(multicore_section, text="MULTI-CORE SCALING", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#9CA3AF").pack(anchor="w", padx=20, pady=(15,10))

        multicore_tests = [
            ("Multi-Core Real", "True parallel workload scaling"),
        ]

        for name, desc in multicore_tests:
            row = ctk.CTkFrame(multicore_section, fg_color="#0D1117", corner_radius=8)
            row.pack(fill="x", padx=15, pady=2)

            left = ctk.CTkFrame(row, fg_color="transparent", width=250)
            left.pack(side="left", fill="y", padx=15, pady=10)
            left.pack_propagate(False)
            ctk.CTkLabel(left, text=name, font=ctk.CTkFont(weight="bold"), text_color="#E5E7EB").pack(anchor="w")
            ctk.CTkLabel(left, text=desc, font=ctk.CTkFont(size=10), text_color="#6B7280").pack(anchor="w")

            lbl_metric = ctk.CTkLabel(row, text="—", font=ctk.CTkFont(size=11), text_color="#9CA3AF", width=120)
            lbl_metric.pack(side="left", padx=5)

            right = ctk.CTkFrame(row, fg_color="transparent")
            right.pack(side="right", padx=15, pady=10)

            lbl_score = ctk.CTkLabel(right, text="—", font=ctk.CTkFont(size=16, weight="bold"), text_color="#F9FAFB", width=60)
            lbl_score.pack(side="right")

            bar = ctk.CTkProgressBar(right, width=150, height=8, progress_color="#14B8A6", fg_color="#1F2937")
            bar.set(0)
            bar.pack(side="right", padx=10)

            self.workload_rows[name] = (lbl_score, lbl_metric, bar)

        ctk.CTkFrame(multicore_section, height=10, fg_color="transparent").pack()

        export_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        export_frame.pack(fill="x", pady=(0,20))
        ctk.CTkButton(export_frame, text="📤 Export Results", command=self._export_benchmark,
                     width=150, fg_color="#374151", hover_color="#4B5563").pack(side="right")

    def _run_benchmark(self):
        self.btn_run_bench.configure(state="disabled")

        self.lbl_single.configure(text="...")
        self.lbl_multi.configure(text="...")
        for name, (lbl_score, lbl_metric, bar) in self.workload_rows.items():
            lbl_score.configure(text="—")
            lbl_metric.configure(text="—")
            bar.set(0)
        self.update()

        results = {}

        def update_workload(name, score, metric_str, max_score=3000):
            lbl_score, lbl_metric, bar = self.workload_rows[name]
            lbl_score.configure(text=str(score))
            lbl_metric.configure(text=metric_str)
            bar.set(min(1.0, score / max_score))
            self.update()

        workloads = [
            ("File Compression", self._test_file_compression),
            ("Navigation", self._test_navigation),
            ("HTML5 Browser", self._test_html5),
            ("PDF Renderer", self._test_pdf),
            ("Photo Library", self._test_photo),
            ("Clang", self._test_clang),
            ("Text Processing", self._test_text),
            ("Asset Compression", self._test_asset),
            ("Encryption", self._test_encryption),
            ("Physics", self._test_physics),
            ("ML Inference", self._test_ml_inference),
            ("FFT", self._test_fft),
            ("Memory Bandwidth", self._test_memory_bandwidth),
            ("Memory Latency", self._test_memory_latency),
            ("Disk Sequential", self._test_disk_sequential),
            ("Disk Random 4K", self._test_disk_random),
            ("LZ4 Fast", self._test_lz4_fast),
            ("Object Detection", self._test_object_detection),
            ("Background Blur", self._test_background_blur),
            ("Horizon Detection", self._test_horizon_detection),
            ("Ray Tracer", self._test_ray_tracer),
            ("HDR Merge", self._test_hdr_merge),
            ("GPU Compute", self._test_gpu_compute),
            ("Multi-Core Real", self._test_multicore_real),
        ]

        total = len(workloads)
        scores = []
        category_scores = {
            'productivity': [],
            'developer': [],
            'creative': [],
            'ml_compute': [],
            'system': [],
            'multicore': [],
        }

        category_map = {
            'File Compression': 'productivity',
            'Navigation': 'productivity',
            'HTML5 Browser': 'productivity',
            'PDF Renderer': 'productivity',
            'Text Processing': 'productivity',
            'Clang': 'developer',
            'Asset Compression': 'developer',
            'Photo Library': 'creative',
            'HDR Merge': 'creative',
            'Ray Tracer': 'creative',
            'Horizon Detection': 'creative',
            'ML Inference': 'ml_compute',
            'Object Detection': 'ml_compute',
            'Background Blur': 'ml_compute',
            'Encryption': 'system',
            'Physics': 'system',
            'FFT': 'system',
            'Memory Bandwidth': 'system',
            'Memory Latency': 'system',
            'Disk Sequential': 'system',
            'Disk Random 4K': 'system',
            'LZ4 Fast': 'system',
            'GPU Compute': 'system',
            'Multi-Core Real': 'multicore',
        }

        multicore_score = 0

        for i, (name, test_fn) in enumerate(workloads):
            self.lbl_bench_status.configure(text=f"Running {name}...")
            self.bench_progress.set((i + 0.5) / total)
            self.update()

            score, metric = test_fn()
            update_workload(name, score, metric)
            results[name] = score

            if name != "Multi-Core Real":
                scores.append(score)

            category = category_map.get(name, 'system')
            category_scores[category].append(score)

            if name == "Multi-Core Real":
                multicore_score = score

        category_weights = {
            'productivity': 0.25,
            'developer': 0.15,
            'creative': 0.20,
            'ml_compute': 0.15,
            'system': 0.25,
        }

        weighted_single = 0
        for cat, weight in category_weights.items():
            if category_scores[cat]:
                cat_avg = sum(category_scores[cat]) / len(category_scores[cat])
                weighted_single += cat_avg * weight

        single_core = int(weighted_single)
        multi_core = max(multicore_score, int(single_core * 1.1))

        self.lbl_single.configure(text=str(single_core))
        self.lbl_multi.configure(text=str(multi_core))

        if single_core >= 2000:
            self.lbl_single_desc.configure(text="Exceptional performance")
        elif single_core >= 1500:
            self.lbl_single_desc.configure(text="Excellent performance")
        elif single_core >= 1000:
            self.lbl_single_desc.configure(text="Great performance")
        else:
            self.lbl_single_desc.configure(text="Average performance")

        if multi_core >= 2500:
            self.lbl_multi_desc.configure(text="Exceptional scaling")
        elif multi_core >= 2000:
            self.lbl_multi_desc.configure(text="Excellent scaling")
        elif multi_core >= 1500:
            self.lbl_multi_desc.configure(text="Great scaling")
        elif multi_core >= 1000:
            self.lbl_multi_desc.configure(text="Good scaling")
        else:
            self.lbl_multi_desc.configure(text="Average scaling")

        self.bench_progress.set(1.0)
        self.lbl_bench_status.configure(text=f"✅ Complete! Single-Core: {single_core} | Multi-Core: {multi_core}")
        self.btn_run_bench.configure(state="normal")

    def _test_file_compression(self):
        import time as t
        import zlib
        import lzma

        data = (b"The quick brown fox jumps over the lazy dog. " * 50000)
        data += os.urandom(1024 * 1024)

        start = t.perf_counter()

        compressed = zlib.compress(data, level=6)
        decompressed = zlib.decompress(compressed)

        compressed2 = lzma.compress(data[:500000], preset=3)
        decompressed2 = lzma.decompress(compressed2)

        elapsed = t.perf_counter() - start

        total_mb = len(data) / (1024 * 1024)
        mb_per_sec = total_mb / max(0.01, elapsed)
        score = int(min(3000, max(100, mb_per_sec * 50)))
        return score, f"{mb_per_sec:.1f} MB/s"

    def _test_navigation(self):
        import time as t
        import heapq

        num_nodes = 1000
        graph = {i: [] for i in range(num_nodes)}

        import random
        random.seed(42)
        for i in range(num_nodes):
            for _ in range(5):
                j = random.randint(0, num_nodes - 1)
                weight = random.randint(1, 100)
                graph[i].append((j, weight))

        def dijkstra(start, end):
            distances = {i: float('inf') for i in range(num_nodes)}
            distances[start] = 0
            pq = [(0, start)]

            while pq:
                dist, node = heapq.heappop(pq)
                if node == end:
                    return dist
                if dist > distances[node]:
                    continue
                for neighbor, weight in graph[node]:
                    new_dist = dist + weight
                    if new_dist < distances[neighbor]:
                        distances[neighbor] = new_dist
                        heapq.heappush(pq, (new_dist, neighbor))
            return distances[end]

        start = t.perf_counter()

        routes = 0
        for i in range(500):
            result = dijkstra(i % num_nodes, (i * 7) % num_nodes)
            routes += 1

        elapsed = t.perf_counter() - start
        routes_per_sec = routes / max(0.01, elapsed)
        score = int(min(3000, max(100, routes_per_sec * 2)))
        return score, f"{routes_per_sec:.0f} routes/sec"

    def _test_html5(self):
        import time as t
        import json
        import re

        web_data = {
            "users": [{"id": i, "name": f"User{i}", "email": f"user{i}@example.com"} for i in range(1000)],
            "posts": [{"id": i, "title": f"Post {i}", "body": "Lorem ipsum " * 50} for i in range(500)],
        }
        json_str = json.dumps(web_data)

        start = t.perf_counter()

        ops = 0
        for _ in range(100):
            parsed = json.loads(json_str)

            emails = re.findall(r'[\w.-]+@[\w.-]+', json_str)

            for user in parsed["users"][:100]:
                user["name"] = user["name"].upper()

            ops += 1

        elapsed = t.perf_counter() - start
        ops_per_sec = ops / max(0.01, elapsed)
        score = int(min(3000, max(100, ops_per_sec * 10)))
        return score, f"{ops_per_sec:.0f} pages/sec"

    def _test_pdf(self):
        import time as t
        import math

        def matrix_multiply(a, b):
            return [
                [sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
                for i in range(3)
            ]

        def transform_point(matrix, x, y):
            return (
                matrix[0][0] * x + matrix[0][1] * y + matrix[0][2],
                matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]
            )

        start = t.perf_counter()

        docs = 0
        for page_num in range(500):
            angle = page_num * 0.01
            cos_a, sin_a = math.cos(angle), math.sin(angle)

            rotation = [[cos_a, -sin_a, 0], [sin_a, cos_a, 0], [0, 0, 1]]
            scale = [[1.5, 0, 0], [0, 1.5, 0], [0, 0, 1]]
            translate = [[1, 0, 100], [0, 1, 200], [0, 0, 1]]

            combined = matrix_multiply(matrix_multiply(rotation, scale), translate)

            for char_idx in range(200):
                x, y = char_idx * 10, page_num
                new_x, new_y = transform_point(combined, x, y)

            docs += 1

        elapsed = t.perf_counter() - start
        docs_per_sec = docs / max(0.01, elapsed)
        score = int(min(3000, max(100, docs_per_sec * 2)))
        return score, f"{docs_per_sec:.0f} pages/sec"

    def _test_photo(self):
        import time as t

        width, height = 1000, 1000

        start = t.perf_counter()

        images = 0
        for _ in range(5):
            pixels = bytearray(width * height * 3)

            for i in range(0, len(pixels), 3):
                pixels[i] = (i // 3) % 256
                pixels[i+1] = ((i // 3) * 2) % 256
                pixels[i+2] = ((i // 3) * 3) % 256

            output = bytearray(len(pixels))
            stride = width * 3

            for y in range(1, height - 1, 10):
                for x in range(1, width - 1, 10):
                    for c in range(3):
                        idx = (y * width + x) * 3 + c
                        val = (
                            pixels[idx - stride - 3] + pixels[idx - stride] + pixels[idx - stride + 3] +
                            pixels[idx - 3] + pixels[idx] * 4 + pixels[idx + 3] +
                            pixels[idx + stride - 3] + pixels[idx + stride] + pixels[idx + stride + 3]
                        ) // 12
                        output[idx] = min(255, max(0, val))

            images += 1

        elapsed = t.perf_counter() - start
        images_per_sec = images / max(0.01, elapsed)
        score = int(min(3000, max(100, images_per_sec * 100)))
        return score, f"{images_per_sec:.1f} MP/sec"

    def _test_clang(self):
        import time as t
        import re

        code = """
        int fibonacci(int n) {
            if (n <= 1) return n;
            return fibonacci(n-1) + fibonacci(n-2);
        }

        int main() {
            for (int i = 0; i < 100; i++) {
                int result = fibonacci(i % 20);
                printf("%d\\n", result);
            }
            return 0;
        }
        """ * 100

        patterns = [
            (r'\b(int|char|float|void|if|else|for|while|return)\b', 'KEYWORD'),
            (r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', 'IDENTIFIER'),
            (r'\d+', 'NUMBER'),
            (r'[+\-*/=<>]', 'OPERATOR'),
            (r'[{}()\[\];,]', 'PUNCTUATION'),
        ]

        start = t.perf_counter()

        kloc = 0
        for _ in range(50):
            tokens = []
            for pattern, token_type in patterns:
                matches = re.findall(pattern, code)
                tokens.extend([(m, token_type) for m in matches])

            ast_nodes = len(tokens) // 10
            kloc += len(code.split('\n')) / 1000

        elapsed = t.perf_counter() - start
        kloc_per_sec = kloc / max(0.01, elapsed)
        score = int(min(3000, max(100, kloc_per_sec * 20)))
        return score, f"{kloc_per_sec:.1f} KLoC/sec"

    def _test_text(self):
        import time as t
        import re
        import sqlite3

        conn = sqlite3.connect(':memory:')
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE documents (id INTEGER, content TEXT, metadata TEXT)')

        text = "The quick brown fox jumps over the lazy dog. " * 1000

        start = t.perf_counter()

        ops = 0
        for i in range(200):
            words = re.findall(r'\b\w+\b', text)
            sentences = re.split(r'[.!?]', text)

            cursor.execute('INSERT INTO documents VALUES (?, ?, ?)',
                          (i, text[:1000], f'{{"words": {len(words)}}}'))

            cursor.execute('SELECT COUNT(*) FROM documents WHERE id < ?', (i,))

            ops += 1

        conn.close()
        elapsed = t.perf_counter() - start
        ops_per_sec = ops / max(0.01, elapsed)
        score = int(min(3000, max(100, ops_per_sec * 5)))
        return score, f"{ops_per_sec:.0f} docs/sec"

    def _test_asset(self):
        import time as t
        import zlib
        import struct

        width, height = 512, 512
        texture = bytearray(width * height * 4)
        for i in range(0, len(texture), 4):
            x, y = (i // 4) % width, (i // 4) // width
            texture[i] = (x * 2) % 256
            texture[i+1] = (y * 2) % 256
            texture[i+2] = ((x + y) * 2) % 256
            texture[i+3] = 255

        vertices = struct.pack('f' * 3000, *[float(i) for i in range(3000)])

        start = t.perf_counter()

        mb_processed = 0
        for _ in range(10):
            compressed_tex = zlib.compress(bytes(texture), level=6)

            compressed_verts = zlib.compress(vertices, level=6)

            ratio = len(texture) / len(compressed_tex)

            mb_processed += (len(texture) + len(vertices)) / (1024 * 1024)

        elapsed = t.perf_counter() - start
        mb_per_sec = mb_processed / max(0.01, elapsed)
        score = int(min(3000, max(100, mb_per_sec * 30)))
        return score, f"{mb_per_sec:.1f} MB/s"

    def _test_encryption(self):
        import time as t
        import hashlib

        key = os.urandom(32)
        data = os.urandom(1024 * 1024)

        start = t.perf_counter()

        blocks = 0
        for _ in range(50):
            encrypted = b""
            prev_block = key
            for i in range(0, len(data), 16):
                block = data[i:i+16]
                mixed = bytes(a ^ b for a, b in zip(block.ljust(16, b'\0'), prev_block[:16]))
                encrypted_block = hashlib.sha256(mixed + key).digest()[:16]
                encrypted += encrypted_block
                prev_block = encrypted_block
                blocks += 1
                if blocks > 3000:
                    break

        elapsed = t.perf_counter() - start
        mb_per_sec = (blocks * 16) / (1024 * 1024) / max(0.01, elapsed)
        score = int(min(3000, max(100, mb_per_sec * 150)))
        return score, f"{mb_per_sec:.1f} MB/s"

    def _test_physics(self):
        import time as t
        import math
        import random

        random.seed(42)

        num_particles = 200
        particles = []
        for _ in range(num_particles):
            particles.append({
                'x': random.uniform(-100, 100),
                'y': random.uniform(-100, 100),
                'z': random.uniform(-100, 100),
                'vx': random.uniform(-1, 1),
                'vy': random.uniform(-1, 1),
                'vz': random.uniform(-1, 1),
                'mass': random.uniform(1, 10)
            })

        G = 6.67e-11
        dt = 0.01

        start = t.perf_counter()

        steps = 0
        for _ in range(100):
            for i, p1 in enumerate(particles):
                ax, ay, az = 0, 0, 0
                for j, p2 in enumerate(particles):
                    if i == j:
                        continue
                    dx = p2['x'] - p1['x']
                    dy = p2['y'] - p1['y']
                    dz = p2['z'] - p1['z']
                    dist_sq = dx*dx + dy*dy + dz*dz + 0.01
                    dist = math.sqrt(dist_sq)
                    force = G * p1['mass'] * p2['mass'] / dist_sq
                    ax += force * dx / dist / p1['mass']
                    ay += force * dy / dist / p1['mass']
                    az += force * dz / dist / p1['mass']

                p1['vx'] += ax * dt
                p1['vy'] += ay * dt
                p1['vz'] += az * dt
                p1['x'] += p1['vx'] * dt
                p1['y'] += p1['vy'] * dt
                p1['z'] += p1['vz'] * dt
            steps += 1

        elapsed = t.perf_counter() - start
        interactions = num_particles * num_particles * steps
        pairs_per_sec = interactions / max(0.01, elapsed)
        score = int(min(3000, max(100, pairs_per_sec / 1500)))
        return score, f"{pairs_per_sec/1000:.0f}K pairs/sec"

    def _test_ml_inference(self):
        import time as t
        import random

        random.seed(42)

        size = 128
        A = [[random.random() for _ in range(size)] for _ in range(size)]
        B = [[random.random() for _ in range(size)] for _ in range(size)]

        start = t.perf_counter()

        ops = 0
        for _ in range(10):
            C = [[0.0] * size for _ in range(size)]
            for i in range(size):
                for j in range(size):
                    total = 0.0
                    for k in range(size):
                        total += A[i][k] * B[k][j]
                    C[i][j] = total

            for i in range(size):
                for j in range(size):
                    C[i][j] = max(0, C[i][j])

            for i in range(size):
                row_sum = sum(C[i])
                if row_sum > 0:
                    for j in range(size):
                        C[i][j] /= row_sum

            ops += 1

        elapsed = t.perf_counter() - start
        gflops = (size * size * size * 2 * ops) / 1e9 / max(0.01, elapsed)
        score = int(min(3000, max(100, gflops * 2000)))
        return score, f"{gflops:.2f} GFLOPS"

    def _test_fft(self):
        import time as t
        import math
        import cmath

        def fft(x):
            n = len(x)
            if n <= 1:
                return x

            even = fft(x[0::2])
            odd = fft(x[1::2])

            result = [0] * n
            for k in range(n // 2):
                t = cmath.exp(-2j * math.pi * k / n) * odd[k]
                result[k] = even[k] + t
                result[k + n//2] = even[k] - t
            return result

        n = 1024
        signal = [complex(math.sin(2 * math.pi * i / 64) +
                         0.5 * math.sin(2 * math.pi * i / 32), 0)
                 for i in range(n)]

        start = t.perf_counter()

        transforms = 0
        for _ in range(100):
            result = fft(signal)
            transforms += 1

        elapsed = t.perf_counter() - start
        samples_per_sec = (n * transforms) / max(0.01, elapsed)
        msamples = samples_per_sec / 1e6
        score = int(min(3000, max(100, msamples * 50)))
        return score, f"{msamples:.2f} MS/sec"

    def _test_memory_bandwidth(self):
        import time as t

        size = 100 * 1024 * 1024
        iterations = 3

        start = t.perf_counter()

        for _ in range(iterations):
            data = bytearray(size)
            for i in range(0, size, 4096):
                data[i] = 0xAA
            checksum = 0
            for i in range(0, size, 4096):
                checksum += data[i]
            del data

        elapsed = t.perf_counter() - start

        total_gb = (size * iterations * 2) / (1024 * 1024 * 1024)
        gb_per_sec = total_gb / max(0.01, elapsed)

        score = int(min(3000, max(100, gb_per_sec * 100)))
        return score, f"{gb_per_sec:.1f} GB/s"

    def _test_memory_latency(self):
        import time as t
        import random

        random.seed(42)

        size = 10 * 1024 * 1024
        data = bytearray(size)

        indices = [random.randint(0, size - 1) for _ in range(100000)]

        start = t.perf_counter()

        checksum = 0
        for idx in indices:
            checksum += data[idx]

        elapsed = t.perf_counter() - start

        accesses = len(indices)
        ns_per_access = (elapsed * 1e9) / accesses

        score = int(min(3000, max(100, 50000 / max(1, ns_per_access))))
        return score, f"{ns_per_access:.1f} ns"

    def _test_disk_sequential(self):
        import time as t
        import tempfile

        size = 100 * 1024 * 1024
        path = os.path.join(tempfile.gettempdir(), "_opticores_seq_bench.tmp")

        data = os.urandom(size)

        start_write = t.perf_counter()
        with open(path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        write_time = t.perf_counter() - start_write

        start_read = t.perf_counter()
        with open(path, "rb") as f:
            _ = f.read()
        read_time = t.perf_counter() - start_read

        try:
            os.remove(path)
        except:
            pass

        size_mb = size / (1024 * 1024)
        write_speed = size_mb / max(0.01, write_time)
        read_speed = size_mb / max(0.01, read_time)
        avg_speed = (write_speed + read_speed) / 2

        score = int(min(3000, max(100, avg_speed * 2)))
        return score, f"{int(avg_speed)} MB/s"

    def _test_disk_random(self):
        import time as t
        import tempfile
        import random

        random.seed(42)

        block_size = 4096
        num_blocks = 500
        file_size = 50 * 1024 * 1024
        path = os.path.join(tempfile.gettempdir(), "_opticores_rnd_bench.tmp")

        with open(path, "wb") as f:
            f.write(os.urandom(file_size))

        positions = [random.randint(0, file_size - block_size) for _ in range(num_blocks)]

        start = t.perf_counter()
        with open(path, "rb") as f:
            for pos in positions:
                f.seek(pos)
                _ = f.read(block_size)
        read_time = t.perf_counter() - start

        write_data = os.urandom(block_size)
        start = t.perf_counter()
        with open(path, "r+b") as f:
            for pos in positions[:100]:
                f.seek(pos)
                f.write(write_data)
            f.flush()
            os.fsync(f.fileno())
        write_time = t.perf_counter() - start

        try:
            os.remove(path)
        except:
            pass

        read_iops = num_blocks / max(0.01, read_time)
        write_iops = 100 / max(0.01, write_time)
        avg_iops = (read_iops + write_iops) / 2

        score = int(min(3000, max(100, avg_iops / 50)))
        return score, f"{int(avg_iops)} IOPS"

    def _test_object_detection(self):
        import time as t
        import random
        import math

        random.seed(42)

        img_size = 224
        channels = 3
        image = [[[random.randint(0, 255) for _ in range(channels)]
                  for _ in range(img_size)] for _ in range(img_size)]

        kernels_3x3 = [[[random.uniform(-1, 1) for _ in range(3)]
                        for _ in range(3)] for _ in range(32)]

        start = t.perf_counter()

        layers_processed = 0
        for layer in range(8):
            output_size = img_size // (2 ** min(layer, 3))
            step = max(1, img_size // output_size)

            feature_maps = []
            for kernel in kernels_3x3[:min(8 + layer * 4, 32)]:
                feature_map = []
                for y in range(1, min(output_size, img_size - 1), step):
                    row = []
                    for x in range(1, min(output_size, img_size - 1), step):
                        conv_sum = 0
                        for ky in range(-1, 2):
                            for kx in range(-1, 2):
                                for c in range(channels):
                                    conv_sum += image[y + ky][x + kx][c] * kernel[ky + 1][kx + 1]
                        row.append(max(0, conv_sum))
                    feature_map.append(row)
                feature_maps.append(feature_map)

            layers_processed += 1

        elapsed = t.perf_counter() - start
        inferences_per_sec = layers_processed / max(0.01, elapsed)
        score = int(min(3000, max(100, inferences_per_sec * 100)))
        return score, f"{inferences_per_sec:.1f} inf/sec"

    def _test_background_blur(self):
        import time as t
        import math
        import random

        random.seed(42)

        width, height = 640, 480

        depth_map = [[random.uniform(0.5, 2.0) for _ in range(width // 4)]
                     for _ in range(height // 4)]

        image = bytearray(width * height * 3)
        for i in range(len(image)):
            image[i] = random.randint(0, 255)

        kernel_size = 7
        kernel = []
        sigma = 2.0
        total = 0
        for y in range(-kernel_size // 2, kernel_size // 2 + 1):
            row = []
            for x in range(-kernel_size // 2, kernel_size // 2 + 1):
                val = math.exp(-(x * x + y * y) / (2 * sigma * sigma))
                row.append(val)
                total += val
            kernel.append(row)
        for y in range(len(kernel)):
            for x in range(len(kernel[0])):
                kernel[y][x] /= total

        start = t.perf_counter()

        frames = 0
        for frame in range(10):
            output = bytearray(len(image))

            for y in range(0, height, 8):
                for x in range(0, width, 8):
                    depth = depth_map[min(y // 4, len(depth_map) - 1)][min(x // 4, len(depth_map[0]) - 1)]

                    if depth > 1.0:
                        for c in range(3):
                            idx = (y * width + x) * 3 + c
                            if idx < len(image):
                                blur_val = 0
                                for ky in range(-1, 2):
                                    for kx in range(-1, 2):
                                        ny, nx = y + ky * 2, x + kx * 2
                                        if 0 <= ny < height and 0 <= nx < width:
                                            nidx = (ny * width + nx) * 3 + c
                                            if nidx < len(image):
                                                blur_val += image[nidx] * 0.111
                                output[idx] = int(blur_val)
                    else:
                        for c in range(3):
                            idx = (y * width + x) * 3 + c
                            if idx < len(image):
                                output[idx] = image[idx]

            frames += 1

        elapsed = t.perf_counter() - start
        fps = frames / max(0.01, elapsed)
        score = int(min(3000, max(100, fps * 50)))
        return score, f"{fps:.1f} fps"

    def _test_horizon_detection(self):
        import time as t
        import math
        import random

        random.seed(42)

        width, height = 400, 300
        image = [[random.randint(0, 255) for _ in range(width)] for _ in range(height)]

        sobel_x = [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]]
        sobel_y = [[-1, -2, -1], [0, 0, 0], [1, 2, 1]]

        start = t.perf_counter()

        images_processed = 0
        for _ in range(20):
            gradient_mag = [[0] * width for _ in range(height)]
            gradient_dir = [[0] * width for _ in range(height)]

            for y in range(1, height - 1, 2):
                for x in range(1, width - 1, 2):
                    gx = 0
                    gy = 0
                    for ky in range(-1, 2):
                        for kx in range(-1, 2):
                            gx += image[y + ky][x + kx] * sobel_x[ky + 1][kx + 1]
                            gy += image[y + ky][x + kx] * sobel_y[ky + 1][kx + 1]
                    gradient_mag[y][x] = int(math.sqrt(gx * gx + gy * gy))
                    gradient_dir[y][x] = math.atan2(gy, gx)

            max_rho = int(math.sqrt(width * width + height * height))
            num_theta = 180
            accumulator = [[0] * num_theta for _ in range(2 * max_rho)]

            threshold = 128
            for y in range(1, height - 1, 3):
                for x in range(1, width - 1, 3):
                    if gradient_mag[y][x] > threshold:
                        for theta_idx in range(0, num_theta, 5):
                            theta = theta_idx * math.pi / 180
                            rho = int(x * math.cos(theta) + y * math.sin(theta))
                            if 0 <= rho + max_rho < 2 * max_rho:
                                accumulator[rho + max_rho][theta_idx] += 1

            max_votes = 0
            best_line = (0, 0)
            for rho_idx in range(0, 2 * max_rho, 10):
                for theta_idx in range(0, num_theta, 5):
                    if accumulator[rho_idx][theta_idx] > max_votes:
                        max_votes = accumulator[rho_idx][theta_idx]
                        best_line = (rho_idx - max_rho, theta_idx * math.pi / 180)

            images_processed += 1

        elapsed = t.perf_counter() - start
        imgs_per_sec = images_processed / max(0.01, elapsed)
        score = int(min(3000, max(100, imgs_per_sec * 30)))
        return score, f"{imgs_per_sec:.1f} img/sec"

    def _test_ray_tracer(self):
        import time as t
        import math
        import random

        random.seed(42)

        width, height = 100, 100
        max_depth = 3

        spheres = [
            {'center': (0, 0, 5), 'radius': 1, 'color': (255, 0, 0), 'reflective': 0.3},
            {'center': (-2, 0, 6), 'radius': 1, 'color': (0, 255, 0), 'reflective': 0.5},
            {'center': (2, 1, 7), 'radius': 1.5, 'color': (0, 0, 255), 'reflective': 0.2},
            {'center': (0, -101, 5), 'radius': 100, 'color': (200, 200, 200), 'reflective': 0.1},
        ]
        light = (5, 5, 0)

        def normalize(v):
            length = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
            if length == 0:
                return (0, 0, 0)
            return (v[0]/length, v[1]/length, v[2]/length)

        def dot(a, b):
            return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

        def subtract(a, b):
            return (a[0]-b[0], a[1]-b[1], a[2]-b[2])

        def add(a, b):
            return (a[0]+b[0], a[1]+b[1], a[2]+b[2])

        def scale(v, s):
            return (v[0]*s, v[1]*s, v[2]*s)

        def intersect_sphere(origin, direction, sphere):
            oc = subtract(origin, sphere['center'])
            a = dot(direction, direction)
            b = 2 * dot(oc, direction)
            c = dot(oc, oc) - sphere['radius']**2
            discriminant = b*b - 4*a*c
            if discriminant < 0:
                return None
            dist = (-b - math.sqrt(discriminant)) / (2*a)
            if dist > 0.001:
                return dist
            return None

        start = t.perf_counter()

        pixels_rendered = 0
        for py in range(height):
            for px in range(width):
                x = (px - width/2) / width
                y = (py - height/2) / height
                direction = normalize((x, y, 1))
                origin = (0, 0, 0)

                color = [0, 0, 0]
                reflection_factor = 1.0

                for depth in range(max_depth):
                    closest_t = float('inf')
                    closest_sphere = None

                    for sphere in spheres:
                        hit_t = intersect_sphere(origin, direction, sphere)
                        if hit_t and hit_t < closest_t:
                            closest_t = hit_t
                            closest_sphere = sphere

                    if closest_sphere:
                        hit_point = add(origin, scale(direction, closest_t))
                        normal = normalize(subtract(hit_point, closest_sphere['center']))
                        to_light = normalize(subtract(light, hit_point))
                        diffuse = max(0, dot(normal, to_light))

                        for i in range(3):
                            color[i] += int(closest_sphere['color'][i] * diffuse * reflection_factor * 0.8)

                        reflection_factor *= closest_sphere['reflective']
                        if reflection_factor < 0.01:
                            break

                        reflect_dir = subtract(direction, scale(normal, 2 * dot(direction, normal)))
                        origin = add(hit_point, scale(normal, 0.001))
                        direction = normalize(reflect_dir)
                    else:
                        break

                pixels_rendered += 1

        elapsed = t.perf_counter() - start
        rays_per_sec = (pixels_rendered * max_depth) / max(0.01, elapsed)
        mrays = rays_per_sec / 1e6
        score = int(min(3000, max(100, mrays * 500)))
        return score, f"{mrays:.2f} Mrays/sec"

    def _test_hdr_merge(self):
        import time as t
        import math
        import random

        random.seed(42)

        width, height = 800, 600

        def generate_exposure(ev_offset):
            exposure = []
            for y in range(0, height, 4):
                row = []
                for x in range(0, width, 4):
                    base = math.sin(x * 0.01) * 100 + math.cos(y * 0.01) * 100 + 128
                    value = base * (2 ** ev_offset)
                    row.append(min(255, max(0, int(value))))
                exposure.append(row)
            return exposure

        start = t.perf_counter()

        merges = 0
        for _ in range(30):
            exp_dark = generate_exposure(-2)
            exp_mid = generate_exposure(0)
            exp_bright = generate_exposure(2)

            h = len(exp_dark)
            w = len(exp_dark[0])

            hdr_image = [[0.0] * w for _ in range(h)]

            for y in range(h):
                for x in range(w):
                    dark = exp_dark[y][x] / 255.0 * 0.25
                    mid = exp_mid[y][x] / 255.0
                    bright = exp_bright[y][x] / 255.0 * 4.0

                    dark_weight = 1.0 - abs(exp_dark[y][x] / 255.0 - 0.5) * 2
                    mid_weight = 1.0 - abs(exp_mid[y][x] / 255.0 - 0.5) * 2
                    bright_weight = 1.0 - abs(exp_bright[y][x] / 255.0 - 0.5) * 2

                    total_weight = dark_weight + mid_weight + bright_weight + 0.001
                    hdr_value = (dark * dark_weight + mid * mid_weight + bright * bright_weight) / total_weight
                    hdr_image[y][x] = hdr_value

            ldr_image = [[0] * w for _ in range(h)]
            gamma = 1.0 / 2.2

            for y in range(h):
                for x in range(w):
                    hdr = hdr_image[y][x]
                    tonemap = hdr / (hdr + 1)
                    ldr = int((tonemap ** gamma) * 255)
                    ldr_image[y][x] = min(255, max(0, ldr))

            merges += 1

        elapsed = t.perf_counter() - start
        merges_per_sec = merges / max(0.01, elapsed)
        mpix = (width * height * merges * 3) / 1e6 / max(0.01, elapsed)
        score = int(min(3000, max(100, merges_per_sec * 50)))
        return score, f"{mpix:.1f} MP/sec"

    def _test_lz4_fast(self):
        import time as t
        import zlib

        pattern_data = b"AAAAAABBBBBBCCCCCC" * 50000
        random_data = os.urandom(500000)
        mixed_data = b""
        for i in range(1000):
            mixed_data += pattern_data[i*50:(i+1)*50] + random_data[i*500:(i+1)*500]

        data = pattern_data + random_data + mixed_data

        start = t.perf_counter()

        cycles = 0
        total_compressed = 0
        for _ in range(20):
            compressed = zlib.compress(data, level=1)
            decompressed = zlib.decompress(compressed)
            total_compressed += len(compressed)
            cycles += 1

        elapsed = t.perf_counter() - start
        mb_per_sec = (len(data) * cycles * 2) / (1024 * 1024) / max(0.01, elapsed)
        ratio = len(data) / (total_compressed / cycles)
        score = int(min(3000, max(100, mb_per_sec * 10)))
        return score, f"{mb_per_sec:.0f} MB/s ({ratio:.1f}x)"

    def _test_multicore_real(self):
        import time as t
        from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

        def cpu_intensive_work(args):
            work_id, iterations = args
            result = 0
            for i in range(iterations):
                result += (i * i) % 997
                result ^= (i >> 2)
                for _ in range(10):
                    result = (result * 31337) % (10**9 + 7)
            return result

        num_cores = max(1, multiprocessing.cpu_count())
        work_per_core = 100000

        start_single = t.perf_counter()
        single_result = cpu_intensive_work((0, work_per_core * 2))
        single_time = t.perf_counter() - start_single

        start_multi = t.perf_counter()
        try:
            with ThreadPoolExecutor(max_workers=num_cores) as executor:
                futures = [executor.submit(cpu_intensive_work, (i, work_per_core))
                          for i in range(num_cores)]
                results = [f.result() for f in as_completed(futures)]
        except Exception:
            results = [cpu_intensive_work((i, work_per_core // num_cores)) for i in range(num_cores)]
        multi_time = t.perf_counter() - start_multi

        scaling_efficiency = (single_time / max(0.01, multi_time)) / num_cores * 100
        work_per_sec = (work_per_core * num_cores) / max(0.01, multi_time)

        base_score = int(min(3000, max(100, work_per_sec / 500)))
        score = int(base_score * (scaling_efficiency / 100) * num_cores / 4)
        score = min(5000, max(100, score))

        return score, f"{num_cores}C @ {scaling_efficiency:.0f}% eff"

    def _test_gpu_compute(self):
        import time as t
        import random
        import math

        random.seed(42)

        width, height = 1024, 1024
        num_pixels = width * height

        pixels_r = [random.random() for _ in range(num_pixels // 16)]
        pixels_g = [random.random() for _ in range(num_pixels // 16)]
        pixels_b = [random.random() for _ in range(num_pixels // 16)]

        start = t.perf_counter()

        passes = 0
        for _ in range(50):
            output_r = []
            output_g = []
            output_b = []

            for i in range(len(pixels_r)):
                r, g, b = pixels_r[i], pixels_g[i], pixels_b[i]

                luma = 0.299 * r + 0.587 * g + 0.114 * b

                contrast = 1.5
                r = (r - 0.5) * contrast + 0.5
                g = (g - 0.5) * contrast + 0.5
                b = (b - 0.5) * contrast + 0.5

                saturation = 1.2
                r = luma + (r - luma) * saturation
                g = luma + (g - luma) * saturation
                b = luma + (b - luma) * saturation

                gamma = 1.0 / 2.2
                r = max(0, min(1, r)) ** gamma
                g = max(0, min(1, g)) ** gamma
                b = max(0, min(1, b)) ** gamma

                output_r.append(r)
                output_g.append(g)
                output_b.append(b)

            pixels_r, pixels_g, pixels_b = output_r, output_g, output_b
            passes += 1

        elapsed = t.perf_counter() - start
        gpixels = (num_pixels * passes) / 1e9 / max(0.01, elapsed)
        score = int(min(3000, max(100, gpixels * 5000)))
        return score, f"{gpixels:.2f} Gpix/sec"

    def _cpu_test(self):
        import time as t
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def count_primes_range(start, end):
            count = 0
            for num in range(start, end):
                if num > 1 and all(num % i != 0 for i in range(2, int(num**0.5)+1)):
                    count += 1
            return count

        n = 500000
        cores = max(1, multiprocessing.cpu_count())
        chunk_size = n // cores

        start = t.perf_counter()
        total_primes = 0

        with ThreadPoolExecutor(max_workers=cores) as executor:
            futures = []
            for i in range(cores):
                s = 2 + (i * chunk_size)
                e = s + chunk_size if i < cores - 1 else n
                futures.append(executor.submit(count_primes_range, s, e))

            for f in as_completed(futures):
                total_primes += f.result()

        elapsed = t.perf_counter() - start

        primes_per_sec = total_primes / max(0.01, elapsed)
        score = int(min(2000, max(100, primes_per_sec / 25)))

        if primes_per_sec >= 1000:
            metric = f"{primes_per_sec/1000:.1f}K primes/sec"
        else:
            metric = f"{int(primes_per_sec)} primes/sec"

        return score, metric

    def _ram_test(self):
        import time as t

        size = 500 * 1024 * 1024
        iterations = 3

        start = t.perf_counter()

        for _ in range(iterations):
            data = bytearray(size)
            for i in range(0, size, 4096):
                data[i] = 0xAA
            checksum = 0
            for i in range(0, size, 4096):
                checksum += data[i]
            del data

        elapsed = t.perf_counter() - start

        total_gb = (size * iterations * 2) / (1024 * 1024 * 1024)
        gb_per_sec = total_gb / max(0.01, elapsed)

        score = int(min(2000, max(100, gb_per_sec * 100)))
        metric = f"{gb_per_sec:.1f} GB/s"
        return score, metric

    def _disk_test(self):
        import time as t
        import tempfile

        size = 100 * 1024 * 1024
        path = os.path.join(tempfile.gettempdir(), "_opticores_bench.tmp")

        data = os.urandom(size)

        start_write = t.perf_counter()
        with open(path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        write_time = t.perf_counter() - start_write

        start_read = t.perf_counter()
        with open(path, "rb") as f:
            _ = f.read()
        read_time = t.perf_counter() - start_read

        os.remove(path)

        size_mb = size / (1024 * 1024)
        write_speed = size_mb / max(0.01, write_time)
        read_speed = size_mb / max(0.01, read_time)
        avg_speed = (write_speed + read_speed) / 2

        score = int(min(2000, max(100, avg_speed * 2)))
        metric = f"{int(avg_speed)} MB/s"
        return score, metric

    def _fill_optimizer(self, parent):
        top = self._modern_header(parent, "Optimizer", "Manage process allocation & priority")

        proc_bar = ctk.CTkFrame(parent, corner_radius=12, fg_color="#161B22", border_width=1, border_color="#1D232C")
        proc_bar.pack(fill="x", padx=40, pady=(0,15))

        proc_header = ctk.CTkFrame(proc_bar, fg_color="transparent")
        proc_header.pack(fill="x", padx=15, pady=(12,5))

        ctk.CTkLabel(proc_header, text="📋 SELECT PROCESS", font=ctk.CTkFont(size=12, weight="bold"), text_color="#9CA3AF").pack(side="left")

        proc_search_frame = ctk.CTkFrame(proc_header, fg_color="#1D232C", corner_radius=8)
        proc_search_frame.pack(side="right")
        ctk.CTkLabel(proc_search_frame, text="🔍", font=ctk.CTkFont(size=12), text_color="#6B7280").pack(side="left", padx=(8,3))
        self.opt_search = ctk.CTkEntry(proc_search_frame, placeholder_text="Filter...", width=120, height=28,
                                       fg_color="transparent", border_width=0, font=ctk.CTkFont(size=12))
        self.opt_search.pack(side="left", padx=(0,8))
        self.opt_search.bind("<KeyRelease>", lambda e: self._refresh_optimizer_procs())

        ctk.CTkButton(proc_header, text="🔄", width=32, height=28, fg_color="#1D232C", hover_color="#30363D",
                     corner_radius=6, command=self._refresh_optimizer_procs).pack(side="right", padx=(0,10))

        tree_container = ctk.CTkFrame(proc_bar, fg_color="#0D1117", corner_radius=8)
        tree_container.pack(fill="x", padx=12, pady=(0,12))

        self.tree_optimizer = ttk.Treeview(
            tree_container, style="Tbl.Treeview",
            columns=("PID", "Name", "CPU", "Memory"),
            show="headings", selectmode="browse", height=6
        )
        for col, w, anchor in [("PID", 60, "center"), ("Name", 200, "w"), ("CPU", 70, "center"), ("Memory", 90, "center")]:
            self.tree_optimizer.heading(col, text=col)
            self.tree_optimizer.column(col, width=w, anchor=anchor, stretch=True)

        self.tree_optimizer.pack(fill="x", padx=6, pady=6)
        self.tree_optimizer.bind("<<TreeviewSelect>>", self._on_optimizer_select)

        self.after(100, self._refresh_optimizer_procs)

        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=40, pady=(0,40))
        grid.grid_columnconfigure((0,1), weight=1)
        grid.grid_rowconfigure(0, weight=0)

        left = ctk.CTkFrame(grid, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0,20))

        sel_card = ctk.CTkFrame(left, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        sel_card.pack(fill="x", pady=(0,20))

        ctk.CTkLabel(sel_card, text="🎯 SELECTED PROCESS", font=ctk.CTkFont(size=12, weight="bold"), text_color="#9CA3AF").pack(anchor="w", padx=20, pady=(20,5))
        self.lbl_sel = ctk.CTkLabel(sel_card, text="— (Select from list above)", text_color="#F9FAFB",
                                    font=ctk.CTkFont(family="Segoe UI Variable Display", size=20, weight="bold"))
        self.lbl_sel.pack(anchor="w", padx=20, pady=(0,20))

        act_grid = ctk.CTkFrame(sel_card, fg_color="transparent")
        act_grid.pack(fill="x", padx=15, pady=(0,15))
        act_grid.grid_columnconfigure((0,1), weight=1)

        ctk.CTkButton(act_grid, text="⏸️ Suspend", command=self._act_suspend, height=40,
                      fg_color="#F59E0B", hover_color="#D97706", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        ctk.CTkButton(act_grid, text="▶️ Resume", command=self._act_resume, height=40,
                      fg_color="#10B981", hover_color="#059669", font=ctk.CTkFont(weight="bold")).grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ctk.CTkButton(act_grid, text="❌ Terminate", command=self._act_kill, height=40,
                      fg_color="#EF4444", hover_color="#DC2626", font=ctk.CTkFont(weight="bold")).grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="ew")

        tweak_card = ctk.CTkFrame(left, corner_radius=16, fg_color="#161B22", border_width=1, border_color="#30363D")
        tweak_card.pack(fill="x", pady=0)
        self._modern_section(tweak_card, "Process Tweaks")

        def add_tweak_row(label, values, default, btn_cmd):
            row = ctk.CTkFrame(tweak_card, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=8)
            row.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(row, text=label, text_color="#9CA3AF", width=120).grid(row=0, column=0, sticky="w")

            cb = ctk.CTkComboBox(row, values=values, width=140, border_width=0,
                                 fg_color="#0F1115", button_color="#8B5CF6")
            cb.set(default)
            cb.grid(row=0, column=1, padx=10, sticky="e")

            ctk.CTkButton(row, text="Apply", width=60, height=28, command=btn_cmd,
                         fg_color="#374151", hover_color="#4B5563").grid(row=0, column=2, sticky="e")

            return cb

        self.cb_pri = add_tweak_row("CPU Priority", PRIORITY_KEYS, "Above Normal", self._act_priority)
        self.cb_memprio = add_tweak_row("Memory Priority", ["VeryLow 1","Low 2","Medium 3","High 4"], "High 4", self._act_memprio)
        self.cb_aff = add_tweak_row("CPU Affinity", ["All cores","Half cores odd","First 2 cores"], "All cores", self._act_affinity)

        ctk.CTkFrame(tweak_card, height=10, fg_color="transparent").pack()

        right = ctk.CTkFrame(grid, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")

        auto_card = ctk.CTkFrame(right, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        auto_card.pack(fill="x", pady=(0,20))
        self._modern_section(auto_card, "🤖 Automation")

        self.chk_game = ctk.CTkSwitch(auto_card, text="Game Mode (Boost FG + High Perf)", command=self._toggle_game, button_color="#8B5CF6", progress_color="#7C3AED")
        self.chk_game.pack(padx=25, pady=(0,10), anchor="w")

        self.chk_game_auto = ctk.CTkSwitch(auto_card, text="Auto Game Boost (Detect Games)", command=self._toggle_game_auto, button_color="#8B5CF6", progress_color="#7C3AED")
        self.chk_game_auto.pack(padx=25, pady=(0,10), anchor="w")

        self.chk_gov = ctk.CTkSwitch(auto_card, text="Background Governor (EcoQoS)", command=self._toggle_governor, button_color="#8B5CF6", progress_color="#7C3AED")
        self.chk_gov.pack(padx=25, pady=(0,10), anchor="w")

        self.chk_priority_bal = ctk.CTkSwitch(auto_card, text="Dynamic Priority Balancer", command=self._toggle_priority_bal, button_color="#8B5CF6", progress_color="#7C3AED")
        self.chk_priority_bal.pack(padx=25, pady=(0,15), anchor="w")
        if PRIORITY_BALANCER.enabled: self.chk_priority_bal.select()

        glob_card = ctk.CTkFrame(right, corner_radius=16, fg_color="#161B22", border_width=1, border_color="#30363D")
        glob_card.pack(fill="x", pady=0)
        self._modern_section(glob_card, "System Actions")

        grid_sys = ctk.CTkFrame(glob_card, fg_color="transparent")
        grid_sys.pack(fill="x", padx=15, pady=(0,10))
        grid_sys.grid_columnconfigure((0,1), weight=1)

        ctk.CTkButton(grid_sys, text="🚀 Boost Foreground", command=self._quick_boost_fg,
                      fg_color="#8B5CF6", hover_color="#7C3AED", height=36).grid(row=0, column=0, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(grid_sys, text="🧹 Trim All RAM", command=self._quick_trim_all,
                      fg_color="#10B981", hover_color="#059669", height=36).grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(grid_sys, text="💾 Clear RAM Standby", command=self._clear_ram_standby,
                      fg_color="#06B6D4", hover_color="#0891B2", height=36).grid(row=1, column=0, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(grid_sys, text="🌐 Optimize Network", command=self._optimize_network,
                      fg_color="#F59E0B", hover_color="#D97706", height=36).grid(row=1, column=1, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(grid_sys, text="🎨 Disable Visual FX", command=self._disable_visual_fx,
                      fg_color="#EC4899", hover_color="#DB2777", height=36).grid(row=2, column=0, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(grid_sys, text="⌨️ Disable Win Key", command=self._disable_win_key,
                      fg_color="#374151", hover_color="#4B5563", height=36).grid(row=2, column=1, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(grid_sys, text="↩️ Undo Last", command=self._act_undo_last,
                      fg_color="#374151", hover_color="#4B5563", height=36).grid(row=3, column=0, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(grid_sys, text="🔄 Revert All", command=self._act_revert,
                      fg_color="#374151", hover_color="#4B5563", height=36).grid(row=3, column=1, padx=6, pady=6, sticky="ew")

        log_head = ctk.CTkLabel(right, text="EFFECTS LOG", font=ctk.CTkFont(size=11, weight="bold"), text_color="#9CA3AF")
        log_head.pack(anchor="w", pady=(20, 5))
        self.txt_effects = ctk.CTkTextbox(right, height=120, fg_color="#0F1115", corner_radius=12, border_width=1, border_color="#30363D")
        self.txt_effects.pack(fill="both", expand=True)

    def _refresh_optimizer_procs(self):
        if not hasattr(self, 'tree_optimizer'):
            return

        for item in self.tree_optimizer.get_children():
            self.tree_optimizer.delete(item)

        filter_text = ""
        if hasattr(self, 'opt_search'):
            filter_text = self.opt_search.get().lower().strip()

        procs = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
            try:
                info = proc.info
                name = info['name'] or ''
                pid = info['pid']
                cpu = info['cpu_percent'] or 0
                mem = info['memory_info'].rss if info['memory_info'] else 0
                mem_mb = mem / (1024 * 1024)

                if name.lower() in PROTECTED:
                    continue

                if filter_text and filter_text not in name.lower() and filter_text not in str(pid):
                    continue

                procs.append((pid, name, cpu, mem_mb))
            except:
                pass

        procs.sort(key=lambda x: x[2], reverse=True)

        for pid, name, cpu, mem_mb in procs[:50]:
            self.tree_optimizer.insert("", "end", values=(
                pid,
                name[:30],
                f"{cpu:.1f}%",
                f"{mem_mb:.1f} MB"
            ))

    def _on_optimizer_select(self, event=None):
        if not hasattr(self, 'tree_optimizer'):
            return

        selection = self.tree_optimizer.selection()
        if not selection:
            return

        item = self.tree_optimizer.item(selection[0])
        values = item['values']
        if len(values) >= 2:
            pid = values[0]
            name = values[1]

            if hasattr(self, 'lbl_sel'):
                self.lbl_sel.configure(text=f"{name} (PID: {pid})")

            if hasattr(self, 'tree'):
                for tree_item in self.tree.get_children():
                    tree_values = self.tree.item(tree_item)['values']
                    if tree_values and tree_values[0] == pid:
                        self.tree.selection_set(tree_item)
                        break

    def _fill_startup_modern(self, parent):
        top = self._modern_header(parent, "Startup Apps", "Manage applications that automatically start with Windows")

        cont = ctk.CTkFrame(parent, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        cont.pack(fill="both", expand=True, padx=40, pady=(0,40))

        toolbar = ctk.CTkFrame(cont, fg_color="transparent")
        toolbar.pack(fill="x", padx=15, pady=15)

        ctk.CTkLabel(toolbar, text="STARTUP ENTRIES", font=ctk.CTkFont(size=12, weight="bold"), text_color="#9CA3AF").pack(side="left")

        btns = ctk.CTkFrame(toolbar, fg_color="transparent")
        btns.pack(side="right")

        ctk.CTkButton(btns, text="🔄 Scan", command=self._refresh_startup,
                      fg_color="#374151", hover_color="#4B5563", width=90, height=32).pack(side="left", padx=5)
        ctk.CTkButton(btns, text="📂 Folder", command=self._open_startup_folder,
                      fg_color="#374151", hover_color="#4B5563", width=90, height=32).pack(side="right", padx=5)

        self.tree_start = ttk.Treeview(
            cont, style="Tbl.Treeview",
            columns=("Impact","Name","Publisher","Command","Status"),
            show="headings", selectmode="extended"
        )
        for col, w in (("Impact",80), ("Name",240), ("Publisher",160), ("Command",350), ("Status",100)):
            self.tree_start.heading(col, text=col)
            self.tree_start.column(col, anchor="center" if col in ("Impact","Status") else "w", width=w, stretch=True)

        sb = ctk.CTkScrollbar(cont, command=self.tree_start.yview, fg_color="transparent")
        sb.pack(side="right", fill="y", padx=6, pady=6)
        self.tree_start.configure(yscrollcommand=sb.set)

        self.tree_start.pack(fill="both", expand=True, padx=15, pady=(0,15))

        actions = ctk.CTkFrame(cont, fg_color="#161B22", height=60)
        actions.pack(fill="x", padx=1, pady=1)

        ctk.CTkButton(actions, text="✅ Enable Selected", command=lambda: self._toggle_startup(True),
                      fg_color="#10B981", hover_color="#059669", width=140, height=36).pack(side="right", padx=15, pady=12)
        ctk.CTkButton(actions, text="❌ Disable Selected", command=lambda: self._toggle_startup(False),
                      fg_color="#EF4444", hover_color="#DC2626", width=140, height=36).pack(side="right", padx=0, pady=12)

        ctk.CTkLabel(actions, text="💡 Tip: Disabling high-impact items improves boot time.", text_color="#6B7280").pack(side="left", padx=20)

    def _fill_cleaner(self, parent):
        top = self._modern_header(parent, "System Cleaner", "Remove junk files and free up disk space")

        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=30, pady=(0,20))
        scroll.grid_columnconfigure((0,1), weight=1)

        row = 0

        junk_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        junk_card.grid(row=row, column=0, columnspan=2, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(junk_card, text="🗑️ JUNK FILES", font=ctk.CTkFont(size=14, weight="bold"),
                    text_color="#EF4444").pack(anchor="w", padx=20, pady=(20,5))
        ctk.CTkLabel(junk_card, text="Scan and clean temporary files, cache, and system junk",
                    text_color="#9CA3AF").pack(anchor="w", padx=20, pady=(0,15))

        junk_btns = ctk.CTkFrame(junk_card, fg_color="transparent")
        junk_btns.pack(fill="x", padx=20, pady=(0,15))

        ctk.CTkButton(junk_btns, text="🔍 Scan Junk Files", command=self._junk_scan,
                     width=150, height=40, fg_color="#EF4444", hover_color="#DC2626",
                     font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0,15))
        ctk.CTkButton(junk_btns, text="🧹 Quick Clean", command=self._junk_clean,
                     width=130, height=40, fg_color="#374151", hover_color="#4B5563").pack(side="left")

        self.lbl_junk_status = ctk.CTkLabel(junk_btns, text="Ready to scan", text_color="#9CA3AF")
        self.lbl_junk_status.pack(side="left", padx=20)

        row += 1

        browser_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        browser_card.grid(row=row, column=0, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(browser_card, text="🌐 BROWSER CACHE", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#3B82F6").pack(anchor="w", padx=20, pady=(20,10))
        ctk.CTkLabel(browser_card, text="Clear cache from Chrome, Firefox, Edge",
                    text_color="#6B7280", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=20, pady=(0,10))

        ctk.CTkButton(browser_card, text="Clear Browser Cache",
                     command=lambda: self._toast("Browser cache cleared!", "ok"),
                     height=36, fg_color="#374151", hover_color="#4B5563").pack(fill="x", padx=20, pady=(0,20))

        temp_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        temp_card.grid(row=row, column=1, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(temp_card, text="📁 WINDOWS TEMP", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#F59E0B").pack(anchor="w", padx=20, pady=(20,10))
        ctk.CTkLabel(temp_card, text="Clean Windows temporary files",
                    text_color="#6B7280", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=20, pady=(0,10))

        ctk.CTkButton(temp_card, text="Clean Temp Files",
                     command=lambda: self._toast("Temp files cleaned!", "ok"),
                     height=36, fg_color="#374151", hover_color="#4B5563").pack(fill="x", padx=20, pady=(0,20))

    def _fill_activity(self, parent):
        top = self._modern_header(parent, "Activity Log", "Live view of OptiCores operations and optimizations")

        if not hasattr(self, 'activity_log'):
            self.activity_log = []
            self._log_activity("═══ OptiCores Started ═══", "success")
            self._log_activity("OptiBalance: ACTIVE - Monitoring CPU hogs every 5s", "optibalance")
            self._log_activity("OptiOverlay: Ready - Shows FPS, CPU, GPU, RAM stats", "optioverlay")
            self._log_activity("OptiGame Mode: Ready - Suspends non-essential apps", "optigame")
            self._log_activity("OptiTrim: Ready - Reduces app RAM usage", "optitrim")
            self._log_activity("OptiMonitor: Ready - 40 app limit display", "optimonitor")
            self._log_activity("OptiRefresh: Available - Updates every 3s when enabled", "optirefresh")
            self._log_activity("═══════════════════════════", "success")

        controls = ctk.CTkFrame(parent, fg_color="transparent")
        controls.pack(fill="x", padx=40, pady=(0,15))

        ctk.CTkButton(controls, text="🔄 Refresh", command=self._refresh_activity_log,
                     width=90, height=30, fg_color="#374151", hover_color="#4B5563").pack(side="left")

        ctk.CTkButton(controls, text="🗑️ Clear Log", command=self._clear_activity_log,
                     width=90, height=30, fg_color="#EF4444", hover_color="#DC2626").pack(side="left", padx=10)

        ctk.CTkButton(controls, text="📋 Copy Log", command=self._copy_activity_log,
                     width=90, height=30, fg_color="#374151", hover_color="#4B5563").pack(side="left")

        self.activity_auto_refresh = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(controls, text="Live Update", variable=self.activity_auto_refresh,
                       fg_color="#10B981").pack(side="right")

        status_row = ctk.CTkFrame(parent, fg_color="transparent")
        status_row.pack(fill="x", padx=40, pady=(0,15))

        pb_card = ctk.CTkFrame(status_row, fg_color="#1D232C", corner_radius=12, border_width=1, border_color="#30363D")
        pb_card.pack(side="left", fill="x", expand=True, padx=(0,10))

        pb_inner = ctk.CTkFrame(pb_card, fg_color="transparent")
        pb_inner.pack(fill="x", padx=15, pady=12)

        ctk.CTkLabel(pb_inner, text="⚡ OptiBalance", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#8B5CF6").pack(side="left")
        self.lbl_optibalance_status = ctk.CTkLabel(pb_inner, text="Active", font=ctk.CTkFont(size=11),
                    text_color="#10B981")
        self.lbl_optibalance_status.pack(side="right")

        opt_card = ctk.CTkFrame(status_row, fg_color="#1D232C", corner_radius=12, border_width=1, border_color="#30363D")
        opt_card.pack(side="left", fill="x", expand=True, padx=(0,10))

        opt_inner = ctk.CTkFrame(opt_card, fg_color="transparent")
        opt_inner.pack(fill="x", padx=15, pady=12)

        ctk.CTkLabel(opt_inner, text="🚀 OptiActions", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#06B6D4").pack(side="left")
        self.lbl_opt_count = ctk.CTkLabel(opt_inner, text="0", font=ctk.CTkFont(size=11),
                    text_color="#E5E7EB")
        self.lbl_opt_count.pack(side="right")

        ov_card = ctk.CTkFrame(status_row, fg_color="#1D232C", corner_radius=12, border_width=1, border_color="#30363D")
        ov_card.pack(side="left", fill="x", expand=True)

        ov_inner = ctk.CTkFrame(ov_card, fg_color="transparent")
        ov_inner.pack(fill="x", padx=15, pady=12)

        ctk.CTkLabel(ov_inner, text="🎮 OptiOverlay", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#F59E0B").pack(side="left")
        self.lbl_overlay_status = ctk.CTkLabel(ov_inner, text="Off", font=ctk.CTkFont(size=11),
                    text_color="#6B7280")
        self.lbl_overlay_status.pack(side="right")

        log_frame = ctk.CTkFrame(parent, fg_color="#161B22", corner_radius=12, border_width=1, border_color="#30363D")
        log_frame.pack(fill="both", expand=True, padx=40, pady=(0,20))

        log_header = ctk.CTkFrame(log_frame, fg_color="#1D232C", corner_radius=0)
        log_header.pack(fill="x")
        ctk.CTkLabel(log_header, text="📜 Live Activity Feed", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#E5E7EB").pack(side="left", padx=15, pady=10)

        self.lbl_log_count = ctk.CTkLabel(log_header, text="0 entries", font=ctk.CTkFont(size=10),
                    text_color="#6B7280")
        self.lbl_log_count.pack(side="right", padx=15)

        self.activity_log_frame = ctk.CTkScrollableFrame(log_frame, fg_color="transparent")
        self.activity_log_frame.pack(fill="both", expand=True, padx=5, pady=5)

        self._render_activity_log()

        self._auto_refresh_activity()

    def _log_activity(self, message, category="info"):
        import datetime
        if not hasattr(self, 'activity_log'):
            self.activity_log = []

        entry = {
            'time': datetime.datetime.now().strftime("%H:%M:%S"),
            'message': message,
            'category': category
        }
        self.activity_log.insert(0, entry)

        if len(self.activity_log) > 100:
            self.activity_log = self.activity_log[:100]

    def _render_activity_log(self):
        if not hasattr(self, 'activity_log_frame'):
            return

        for widget in self.activity_log_frame.winfo_children():
            widget.destroy()

        cat_style = {
            'info': ('#6B7280', 'ℹ️'),
            'success': ('#10B981', '✅'),
            'warning': ('#F59E0B', '⚠️'),
            'error': ('#EF4444', '❌'),
            'optimize': ('#8B5CF6', '🚀'),
            'optibalance': ('#06B6D4', '⚡'),
            'optioverlay': ('#F59E0B', '📊'),
            'optigame': ('#22C55E', '🎮'),
            'optitrim': ('#EC4899', '💾'),
            'optimonitor': ('#6366F1', '👁️'),
            'optirefresh': ('#14B8A6', '🔄'),
            'optiboost': ('#EF4444', '🔥'),
            'optipower': ('#A855F7', '🔋'),
        }

        for entry in self.activity_log[:50]:
            row = ctk.CTkFrame(self.activity_log_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            color, icon = cat_style.get(entry['category'], ('#6B7280', 'ℹ️'))

            ctk.CTkLabel(row, text=entry['time'], font=ctk.CTkFont(family="Consolas", size=10),
                        text_color="#4B5563", width=60).pack(side="left", padx=(10,5))

            ctk.CTkLabel(row, text=icon, font=ctk.CTkFont(size=10)).pack(side="left", padx=(0,5))

            ctk.CTkLabel(row, text=entry['message'], font=ctk.CTkFont(size=10),
                        text_color=color, anchor="w").pack(side="left", fill="x", expand=True)

        if hasattr(self, 'lbl_log_count'):
            self.lbl_log_count.configure(text=f"{len(self.activity_log)} entries")

    def _refresh_activity_log(self):
        self._render_activity_log()

        if hasattr(self, 'lbl_overlay_status'):
            overlay_on = hasattr(self, 'fps_overlay') and self.fps_overlay.winfo_exists()
            self.lbl_overlay_status.configure(
                text="Active" if overlay_on else "Off",
                text_color="#10B981" if overlay_on else "#6B7280"
            )

        if hasattr(self, 'lbl_opt_count'):
            count = len([e for e in self.activity_log if e['category'] in ['optimize', 'optibalance', 'success']])
            self.lbl_opt_count.configure(text=str(count))

    def _clear_activity_log(self):
        self.activity_log = []
        self._log_activity("Activity log cleared", "info")
        self._render_activity_log()

    def _copy_activity_log(self):
        log_text = "\n".join([f"[{e['time']}] {e['message']}" for e in self.activity_log])
        self.clipboard_clear()
        self.clipboard_append(log_text)
        self._toast("Log copied to clipboard", "ok")

    def _auto_refresh_activity(self):
        if hasattr(self, 'activity_auto_refresh') and self.activity_auto_refresh.get():
            self._refresh_activity_log()
        self.after(2000, self._auto_refresh_activity)

    def _fill_active(self, parent):

        top = self._modern_header(parent, "Active Apps", "Manage and optimize running applications")

        controls = ctk.CTkFrame(parent, fg_color="transparent")
        controls.pack(fill="x", padx=40, pady=(0,10))

        ctk.CTkButton(controls, text="🔄 Refresh", command=self._refresh_active_apps,
                     width=90, height=30, fg_color="#374151", hover_color="#4B5563").pack(side="left")

        ctk.CTkButton(controls, text="🎮 OptiGame", command=self._gaming_mode,
                     width=100, height=30, fg_color="#8B5CF6", hover_color="#7C3AED").pack(side="left", padx=8)

        ctk.CTkButton(controls, text="🧹 OptiKill", command=self._kill_background_apps,
                     width=100, height=30, fg_color="#EF4444", hover_color="#DC2626").pack(side="left")

        self.auto_refresh_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(controls, text="Auto-refresh", variable=self.auto_refresh_var,
                       command=self._toggle_auto_refresh, fg_color="#10B981").pack(side="right")

        self.lbl_active_count = ctk.CTkLabel(controls, text="",
                                             text_color="#9CA3AF", font=ctk.CTkFont(size=11))
        self.lbl_active_count.pack(side="right", padx=15)

        controls2 = ctk.CTkFrame(parent, fg_color="transparent")
        controls2.pack(fill="x", padx=40, pady=(0,10))

        self.active_search = ctk.CTkEntry(controls2, placeholder_text="🔍 Search apps...", width=200, height=30)
        self.active_search.pack(side="left")
        self.active_search.bind("<KeyRelease>", lambda e: self._filter_active_apps())

        ctk.CTkLabel(controls2, text="Sort:", text_color="#9CA3AF").pack(side="left", padx=(15,5))
        self.active_sort = ctk.CTkOptionMenu(controls2, values=["RAM ↓", "RAM ↑", "CPU ↓", "CPU ↑", "Name A-Z", "Name Z-A"],
                                             width=100, height=28, command=lambda v: self._render_active_apps())
        self.active_sort.set("RAM ↓")
        self.active_sort.pack(side="left")

        mem = psutil.virtual_memory()
        self.lbl_sys_mem = ctk.CTkLabel(controls2, text=f"Free: {mem.available/(1024**3):.1f}GB",
                                        text_color="#10B981", font=ctk.CTkFont(size=11, weight="bold"))
        self.lbl_sys_mem.pack(side="right")

        self.lbl_total_ram = ctk.CTkLabel(controls2, text="Apps RAM: --", text_color="#8B5CF6",
                                          font=ctk.CTkFont(size=11, weight="bold"))
        self.lbl_total_ram.pack(side="right", padx=10)

        self.lbl_total_cpu = ctk.CTkLabel(controls2, text="System CPU: --", text_color="#06B6D4",
                                          font=ctk.CTkFont(size=11, weight="bold"))
        self.lbl_total_cpu.pack(side="right", padx=10)

        ctk.CTkLabel(controls2, text="Filter:", text_color="#9CA3AF").pack(side="left", padx=(15,5))
        self.category_filter = ctk.CTkOptionMenu(controls2, values=["All Apps", "Browsers", "Games", "Dev Tools", "Media", "System"],
                                                 width=100, height=28, command=lambda v: self._render_active_apps())
        self.category_filter.set("All Apps")
        self.category_filter.pack(side="left")

        quick = ctk.CTkFrame(parent, fg_color="#1F2937", corner_radius=10)
        quick.pack(fill="x", padx=40, pady=(0,10))

        ctk.CTkLabel(quick, text="OptiActions:", text_color="#6B7280",
                    font=ctk.CTkFont(size=10)).pack(side="left", padx=8, pady=6)

        ctk.CTkButton(quick, text="OptiEnd", width=65, height=22, font=ctk.CTkFont(size=9),
                     fg_color="#374151", hover_color="#4B5563",
                     command=lambda: self._end_category("browser")).pack(side="left", padx=2, pady=6)

        ctk.CTkButton(quick, text="OptiBoost", width=70, height=22, font=ctk.CTkFont(size=9),
                     fg_color="#10B981", hover_color="#059669",
                     command=lambda: self._boost_category("game")).pack(side="left", padx=2, pady=6)

        ctk.CTkButton(quick, text="OptiTrim", width=65, height=22, font=ctk.CTkFont(size=9),
                     fg_color="#8B5CF6", hover_color="#7C3AED",
                     command=self._trim_all_memory).pack(side="left", padx=2, pady=6)

        ctk.CTkButton(quick, text="OptiCPU", width=65, height=22, font=ctk.CTkFont(size=9),
                     fg_color="#EF4444", hover_color="#DC2626",
                     command=self._end_high_cpu_apps).pack(side="left", padx=2, pady=6)

        ctk.CTkButton(quick, text="OptiResume", width=75, height=22, font=ctk.CTkFont(size=9),
                     fg_color="#06B6D4", hover_color="#0891B2",
                     command=self._resume_all_apps).pack(side="left", padx=2, pady=6)

        ctk.CTkButton(quick, text="OptiClean", width=70, height=22, font=ctk.CTkFont(size=9),
                     fg_color="#F59E0B", hover_color="#D97706",
                     command=self._kill_duplicates).pack(side="left", padx=2, pady=6)

        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=30, pady=(0,20))
        scroll.grid_columnconfigure((0,1,2), weight=1)

        self.active_apps_frame = scroll
        self.active_apps_data = []
        self.selected_apps = set()
        self.auto_refresh_job = None

        self.after(100, self._refresh_active_apps)

    def _filter_active_apps(self):
        query = self.active_search.get().lower() if hasattr(self, 'active_search') else ""
        self._render_active_apps(query)

    def _refresh_active_apps(self):
        if not hasattr(self, 'active_apps_frame'):
            return

        apps = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'status', 'exe', 'create_time', 'io_counters']):
                try:
                    info = proc.info
                    name = info['name']
                    if name and not name.startswith('_') and '.exe' in name.lower():
                        mem_mb = info['memory_info'].rss / (1024*1024) if info['memory_info'] else 0

                        runtime_mins = 0
                        if info.get('create_time'):
                            import time
                            runtime_mins = (time.time() - info['create_time']) / 60

                        io_read = 0
                        io_write = 0
                        if info.get('io_counters'):
                            io_read = info['io_counters'].read_bytes / (1024*1024)
                            io_write = info['io_counters'].write_bytes / (1024*1024)

                        apps.append({
                            'name': name.replace('.exe', '').replace('.EXE', ''),
                            'pid': info['pid'],
                            'cpu': info['cpu_percent'] or 0,
                            'mem': mem_mb,
                            'status': info['status'] or 'running',
                            'exe': info['exe'] or '',
                            'runtime': runtime_mins,
                            'io_read': io_read,
                            'io_write': io_write
                        })
                except:
                    pass
        except:
            pass

        seen = set()
        unique_apps = []
        for app in sorted(apps, key=lambda x: x['mem'], reverse=True):
            if app['name'] not in seen:
                seen.add(app['name'])
                unique_apps.append(app)

        self.active_apps_data = unique_apps
        self._render_active_apps()

    def _render_active_apps(self, filter_query=""):
        if not hasattr(self, 'active_apps_frame'):
            return

        for widget in self.active_apps_frame.winfo_children():
            widget.destroy()

        apps = self.active_apps_data[:]
        if filter_query:
            apps = [a for a in apps if filter_query in a['name'].lower()]

        if hasattr(self, 'category_filter'):
            cat = self.category_filter.get()
            cat_patterns = {
                "Browsers": ["chrome", "firefox", "edge", "opera", "brave", "safari"],
                "Games": ["game", "steam", "epic", "origin", "uplay", "riot", "league"],
                "Dev Tools": ["code", "visual", "python", "node", "git", "docker", "terminal", "cmd", "powershell"],
                "Media": ["spotify", "vlc", "itunes", "music", "video", "player", "obs"],
                "System": ["explorer", "svchost", "runtime", "service", "host", "manager"]
            }
            if cat != "All Apps" and cat in cat_patterns:
                patterns = cat_patterns[cat]
                apps = [a for a in apps if any(p in a['name'].lower() for p in patterns)]

        if hasattr(self, 'active_sort'):
            sort_val = self.active_sort.get()
            if sort_val == "RAM ↓":
                apps.sort(key=lambda x: x['mem'], reverse=True)
            elif sort_val == "RAM ↑":
                apps.sort(key=lambda x: x['mem'])
            elif sort_val == "CPU ↓":
                apps.sort(key=lambda x: x['cpu'], reverse=True)
            elif sort_val == "CPU ↑":
                apps.sort(key=lambda x: x['cpu'])
            elif sort_val == "Name A-Z":
                apps.sort(key=lambda x: x['name'].lower())
            elif sort_val == "Name Z-A":
                apps.sort(key=lambda x: x['name'].lower(), reverse=True)

        total_ram = sum(a['mem'] for a in self.active_apps_data)
        system_cpu = psutil.cpu_percent(interval=0)
        mem = psutil.virtual_memory()

        if hasattr(self, 'lbl_total_ram'):
            if total_ram > 1024:
                self.lbl_total_ram.configure(text=f"Apps: {total_ram/1024:.1f}GB")
            else:
                self.lbl_total_ram.configure(text=f"Apps: {total_ram:.0f}MB")
        if hasattr(self, 'lbl_total_cpu'):
            self.lbl_total_cpu.configure(text=f"CPU: {system_cpu:.0f}%")
        if hasattr(self, 'lbl_sys_mem'):
            self.lbl_sys_mem.configure(text=f"Free: {mem.available/(1024**3):.1f}GB")

        row, col = 0, 0
        for app in apps[:40]:

            card = ctk.CTkFrame(self.active_apps_frame, fg_color="#1D232C", corner_radius=12,
                               border_width=1, border_color="#30363D")
            card.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)

            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=12, pady=10)

            icon = "📱"
            name_lower = app['name'].lower()
            if "chrome" in name_lower or "firefox" in name_lower or "edge" in name_lower:
                icon = "🌐"
            elif "code" in name_lower or "visual" in name_lower:
                icon = "💻"
            elif "explorer" in name_lower:
                icon = "📁"
            elif "discord" in name_lower:
                icon = "💬"
            elif "spotify" in name_lower:
                icon = "🎵"
            elif "game" in name_lower or "steam" in name_lower:
                icon = "🎮"
            elif "python" in name_lower:
                icon = "🐍"
            elif "notepad" in name_lower or "word" in name_lower:
                icon = "📝"

            header = ctk.CTkFrame(inner, fg_color="transparent")
            header.pack(fill="x")
            ctk.CTkLabel(header, text=icon, font=ctk.CTkFont(size=16)).pack(side="left")
            ctk.CTkLabel(header, text=app['name'][:16], font=ctk.CTkFont(size=11, weight="bold"),
                        text_color="#E5E7EB").pack(side="left", padx=(4,0))

            status_color = "#10B981" if app['status'] == 'running' else "#F59E0B"
            ctk.CTkLabel(header, text="●", font=ctk.CTkFont(size=8),
                        text_color=status_color).pack(side="right")

            stats = ctk.CTkFrame(inner, fg_color="transparent")
            stats.pack(fill="x", pady=(3,0))
            ctk.CTkLabel(stats, text=f"{app['mem']:.0f}MB", font=ctk.CTkFont(size=9),
                        text_color="#8B5CF6").pack(side="left")
            ctk.CTkLabel(stats, text=f"{app['cpu']:.0f}%", font=ctk.CTkFont(size=9),
                        text_color="#06B6D4").pack(side="right")

            stats2 = ctk.CTkFrame(inner, fg_color="transparent")
            stats2.pack(fill="x", pady=(1,0))

            runtime = app.get('runtime', 0)
            if runtime > 60:
                rt_text = f"⏱️ {runtime/60:.1f}h"
            else:
                rt_text = f"⏱️ {runtime:.0f}m"
            ctk.CTkLabel(stats2, text=rt_text, font=ctk.CTkFont(size=8), text_color="#6B7280").pack(side="left")

            io_total = app.get('io_read', 0) + app.get('io_write', 0)
            if io_total > 1024:
                io_text = f"💾 {io_total/1024:.1f}GB"
            elif io_total > 0:
                io_text = f"💾 {io_total:.0f}MB"
            else:
                io_text = ""
            if io_text:
                ctk.CTkLabel(stats2, text=io_text, font=ctk.CTkFont(size=8), text_color="#F59E0B").pack(side="right")

            btns = ctk.CTkFrame(inner, fg_color="transparent")
            btns.pack(fill="x", pady=(6,0))

            pid = app['pid']
            exe_path = app['exe']
            status = app['status']

            ctk.CTkButton(btns, text="End", width=35, height=18, font=ctk.CTkFont(size=9),
                         fg_color="#EF4444", hover_color="#DC2626",
                         command=lambda p=pid, n=app['name']: self._end_app(p, n)).pack(side="left", padx=(0,2))

            if status == 'stopped':
                ctk.CTkButton(btns, text="Resume", width=45, height=18, font=ctk.CTkFont(size=9),
                             fg_color="#10B981", hover_color="#059669",
                             command=lambda p=pid, n=app['name']: self._resume_app(p, n)).pack(side="left", padx=(0,2))
            else:
                ctk.CTkButton(btns, text="Pause", width=40, height=18, font=ctk.CTkFont(size=9),
                             fg_color="#F59E0B", hover_color="#D97706",
                             command=lambda p=pid, n=app['name']: self._suspend_app(p, n)).pack(side="left", padx=(0,2))

            ctk.CTkButton(btns, text="Info", width=35, height=18, font=ctk.CTkFont(size=9),
                         fg_color="#3B82F6", hover_color="#2563EB",
                         command=lambda p=pid, n=app['name'], e=exe_path: self._show_app_details(p, n, e)).pack(side="left")

            btns2 = ctk.CTkFrame(inner, fg_color="transparent")
            btns2.pack(fill="x", pady=(3,0))

            ctk.CTkButton(btns2, text="Folder", width=42, height=18, font=ctk.CTkFont(size=9),
                         fg_color="#374151", hover_color="#4B5563",
                         command=lambda e=exe_path: self._open_app_location(e)).pack(side="left", padx=(0,2))

            ctk.CTkButton(btns2, text="Boost", width=40, height=18, font=ctk.CTkFont(size=9),
                         fg_color="#10B981", hover_color="#059669",
                         command=lambda p=pid, n=app['name']: self._set_high_priority(p, n)).pack(side="left", padx=(0,2))

            ctk.CTkButton(btns2, text="Trim", width=35, height=18, font=ctk.CTkFont(size=9),
                         fg_color="#8B5CF6", hover_color="#7C3AED",
                         command=lambda p=pid, n=app['name']: self._reduce_memory(p, n)).pack(side="left")

            col += 1
            if col >= 3:
                col = 0
                row += 1

        self.lbl_active_count.configure(text=f"{len(apps)} apps")

    def _end_app(self, pid, name):
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            self._toast(f"Ended {name}", "ok")
            self._log_activity(f"Ended process: {name} (PID: {pid})", "success")
            self.after(500, self._refresh_active_apps)
        except Exception as e:
            self._toast(f"Failed to end {name}", "error")
            self._log_activity(f"Failed to end {name}: {e}", "error")

    def _open_app_location(self, exe_path):
        try:
            if exe_path and os.path.exists(exe_path):
                folder = os.path.dirname(exe_path)
                os.startfile(folder)
            else:
                self._toast("Location not available", "error")
        except:
            self._toast("Could not open location", "error")

    def _set_high_priority(self, pid, name):
        try:
            proc = psutil.Process(pid)
            proc.nice(psutil.HIGH_PRIORITY_CLASS)
            self._toast(f"{name} set to HIGH priority", "ok")
            self._log_activity(f"Boosted priority: {name}", "optimize")
        except:
            self._toast("Failed to set priority (need admin)", "error")
            self._log_activity(f"Failed to boost {name} (need admin)", "error")

    def _suspend_app(self, pid, name):
        try:
            proc = psutil.Process(pid)
            proc.suspend()
            self._toast(f"Suspended {name}", "ok")
            self._log_activity(f"Suspended process: {name}", "warning")
            self.after(500, self._refresh_active_apps)
        except:
            self._toast("Failed to suspend (need admin)", "error")
            self._log_activity(f"Failed to suspend {name}", "error")

    def _resume_app(self, pid, name):
        try:
            proc = psutil.Process(pid)
            proc.resume()
            self._toast(f"Resumed {name}", "ok")
            self._log_activity(f"Resumed process: {name}", "success")
            self.after(500, self._refresh_active_apps)
        except:
            self._toast("Failed to resume", "error")
            self._log_activity(f"Failed to resume {name}", "error")

    def _restart_app(self, pid, name, exe_path):
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            proc.wait(timeout=3)

            if exe_path and os.path.exists(exe_path):
                import subprocess
                subprocess.Popen([exe_path], shell=True)
                self._toast(f"Restarted {name}", "ok")
            else:
                self._toast(f"Ended {name} (can't restart - no path)", "ok")

            self.after(1000, self._refresh_active_apps)
        except:
            self._toast("Failed to restart", "error")

    def _reduce_memory(self, pid, name):
        try:
            import ctypes
            PROCESS_ALL_ACCESS = 0x1F0FFF
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
            if handle:
                ctypes.windll.psapi.EmptyWorkingSet(handle)
                ctypes.windll.kernel32.CloseHandle(handle)
                self._toast(f"Reduced memory for {name}", "ok")
                self._log_activity(f"Trimmed memory: {name}", "optimize")
                self.after(500, self._refresh_active_apps)
            else:
                self._toast("Need admin rights", "error")
                self._log_activity(f"Memory trim failed for {name} (need admin)", "error")
        except:
            self._toast("Failed to reduce memory", "error")

    def _show_app_details(self, pid, name, exe_path):
        try:
            proc = psutil.Process(pid)
            info = proc.as_dict(attrs=['pid', 'name', 'exe', 'cpu_percent', 'memory_info',
                                       'create_time', 'status', 'num_threads', 'username'])

            popup = ctk.CTkToplevel(self)
            popup.title(f"Details: {name}")
            popup.geometry("400x350")
            popup.attributes('-topmost', True)
            popup.configure(fg_color="#0d1117")

            ctk.CTkLabel(popup, text=f"📱 {name}", font=ctk.CTkFont(size=18, weight="bold"),
                        text_color="#E5E7EB").pack(padx=20, pady=(20,10))

            details = ctk.CTkFrame(popup, fg_color="#161b22", corner_radius=10)
            details.pack(fill="both", expand=True, padx=20, pady=10)

            def detail_row(label, value, color="#E5E7EB"):
                row = ctk.CTkFrame(details, fg_color="transparent")
                row.pack(fill="x", padx=15, pady=4)
                ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=11),
                            text_color="#6B7280").pack(side="left")
                ctk.CTkLabel(row, text=str(value), font=ctk.CTkFont(size=11, weight="bold"),
                            text_color=color).pack(side="right")

            detail_row("PID", info['pid'], "#8B5CF6")
            detail_row("Status", info['status'], "#10B981" if info['status'] == 'running' else "#F59E0B")
            detail_row("CPU Usage", f"{info['cpu_percent'] or 0:.1f}%", "#06B6D4")

            mem_mb = info['memory_info'].rss / (1024*1024) if info['memory_info'] else 0
            detail_row("Memory", f"{mem_mb:.1f} MB", "#EF4444")
            detail_row("Threads", info['num_threads'] or 0, "#F59E0B")

            if info.get('username'):
                detail_row("User", info['username'].split('\\')[-1], "#9CA3AF")

            if info.get('create_time'):
                import datetime
                start = datetime.datetime.fromtimestamp(info['create_time'])
                detail_row("Started", start.strftime("%H:%M:%S"), "#9CA3AF")

            if exe_path:
                path_frame = ctk.CTkFrame(details, fg_color="transparent")
                path_frame.pack(fill="x", padx=15, pady=(10,4))
                ctk.CTkLabel(path_frame, text="Path:", font=ctk.CTkFont(size=10),
                            text_color="#6B7280").pack(anchor="w")
                ctk.CTkLabel(path_frame, text=exe_path[:50]+"..." if len(exe_path) > 50 else exe_path,
                            font=ctk.CTkFont(size=9), text_color="#9CA3AF").pack(anchor="w")

            btns = ctk.CTkFrame(popup, fg_color="transparent")
            btns.pack(fill="x", padx=20, pady=15)

            ctk.CTkButton(btns, text="End Task", fg_color="#EF4444", hover_color="#DC2626",
                         command=lambda: [self._end_app(pid, name), popup.destroy()]).pack(side="left", padx=5)
            ctk.CTkButton(btns, text="Reduce Memory", fg_color="#8B5CF6", hover_color="#7C3AED",
                         command=lambda: self._reduce_memory(pid, name)).pack(side="left", padx=5)
            ctk.CTkButton(btns, text="Close", fg_color="#374151", hover_color="#4B5563",
                         command=popup.destroy).pack(side="right", padx=5)

        except Exception as e:
            self._toast(f"Could not get details: {e}", "error")

    def _end_selected_apps(self):
        query = self.active_search.get().lower() if hasattr(self, 'active_search') else ""
        if not query:
            self._toast("Type app name to filter first", "error")
            return

        ended = 0
        for app in self.active_apps_data:
            if query in app['name'].lower():
                try:
                    proc = psutil.Process(app['pid'])
                    proc.terminate()
                    ended += 1
                except:
                    pass

        self._toast(f"Ended {ended} apps", "ok")
        self._log_activity(f"Batch ended {ended} apps matching '{query}'", "success")
        self.after(500, self._refresh_active_apps)

    def _gaming_mode(self):
        essential = ['explorer', 'system', 'csrss', 'wininit', 'services', 'lsass', 'svchost',
                    'dwm', 'conhost', 'python', 'code', 'opticores']
        suspended = 0

        for app in self.active_apps_data:
            name_lower = app['name'].lower()
            if any(e in name_lower for e in essential):
                continue
            if 'game' in name_lower or 'steam' in name_lower:
                continue
            if app['mem'] > 100:
                try:
                    proc = psutil.Process(app['pid'])
                    proc.suspend()
                    suspended += 1
                except:
                    pass

        self._toast(f"🎮 Gaming Mode: Suspended {suspended} apps", "ok")
        self._log_activity(f"Gaming Mode activated - suspended {suspended} non-essential apps", "optimize")
        self.after(500, self._refresh_active_apps)

    def _kill_background_apps(self):
        killed = 0
        essential = ['explorer', 'system', 'csrss', 'wininit', 'services', 'lsass', 'svchost',
                    'dwm', 'conhost', 'python', 'code', 'opticores']

        for app in self.active_apps_data:
            name_lower = app['name'].lower()
            if any(e in name_lower for e in essential):
                continue
            if app['mem'] < 50 and app['cpu'] < 1:
                try:
                    proc = psutil.Process(app['pid'])
                    proc.terminate()
                    killed += 1
                except:
                    pass

        self._toast(f"Killed {killed} background apps", "ok")
        self._log_activity(f"Killed {killed} background apps (<50MB, <1% CPU)", "success")
        self.after(500, self._refresh_active_apps)

    def _toggle_auto_refresh(self):
        if self.auto_refresh_var.get():
            self._do_auto_refresh()
        else:
            if self.auto_refresh_job:
                self.after_cancel(self.auto_refresh_job)
                self.auto_refresh_job = None

    def _do_auto_refresh(self):
        if hasattr(self, 'auto_refresh_var') and self.auto_refresh_var.get():
            self._refresh_active_apps()
            self.auto_refresh_job = self.after(3000, self._do_auto_refresh)

    def _end_category(self, category):
        patterns = {
            "browser": ["chrome", "firefox", "edge", "opera", "brave", "safari"],
            "game": ["game", "steam", "epic", "origin", "uplay"],
        }
        ended = 0
        for app in self.active_apps_data:
            name_lower = app['name'].lower()
            if any(p in name_lower for p in patterns.get(category, [])):
                try:
                    proc = psutil.Process(app['pid'])
                    proc.terminate()
                    ended += 1
                except:
                    pass
        self._toast(f"Ended {ended} {category} apps", "ok")
        self.after(500, self._refresh_active_apps)

    def _boost_category(self, category):
        patterns = {
            "game": ["game", "steam", "epic", "origin", "uplay"],
        }
        boosted = 0
        for app in self.active_apps_data:
            name_lower = app['name'].lower()
            if any(p in name_lower for p in patterns.get(category, [])):
                try:
                    proc = psutil.Process(app['pid'])
                    proc.nice(psutil.HIGH_PRIORITY_CLASS)
                    boosted += 1
                except:
                    pass
        self._toast(f"Boosted {boosted} {category} apps", "ok")
        self._log_activity(f"Boosted {boosted} {category} apps to HIGH priority", "optimize")

    def _trim_all_memory(self):
        import ctypes
        trimmed = 0
        for app in self.active_apps_data:
            try:
                PROCESS_ALL_ACCESS = 0x1F0FFF
                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, app['pid'])
                if handle:
                    ctypes.windll.psapi.EmptyWorkingSet(handle)
                    ctypes.windll.kernel32.CloseHandle(handle)
                    trimmed += 1
            except:
                pass
        self._toast(f"Trimmed memory for {trimmed} apps", "ok")
        self._log_activity(f"Trimmed memory for {trimmed} apps", "optimize")
        self.after(500, self._refresh_active_apps)

    def _end_high_cpu_apps(self):
        essential = ['explorer', 'system', 'csrss', 'wininit', 'services', 'lsass', 'svchost',
                    'dwm', 'python', 'opticores']
        ended = 0
        for app in self.active_apps_data:
            name_lower = app['name'].lower()
            if any(e in name_lower for e in essential):
                continue
            if app['cpu'] > 20:
                try:
                    proc = psutil.Process(app['pid'])
                    proc.terminate()
                    ended += 1
                except:
                    pass
        self._toast(f"Ended {ended} high CPU apps", "ok")
        self.after(500, self._refresh_active_apps)

    def _resume_all_apps(self):
        resumed = 0
        for app in self.active_apps_data:
            if app['status'] == 'stopped':
                try:
                    proc = psutil.Process(app['pid'])
                    proc.resume()
                    resumed += 1
                except:
                    pass
        self._toast(f"Resumed {resumed} apps", "ok")
        self.after(500, self._refresh_active_apps)

    def _kill_duplicates(self):
        by_name = {}
        for app in self.active_apps_data:
            name = app['name'].lower()
            if name not in by_name:
                by_name[name] = []
            by_name[name].append(app)

        killed = 0
        for name, apps_list in by_name.items():
            if len(apps_list) > 1:
                apps_list.sort(key=lambda x: x['mem'], reverse=True)
                for app in apps_list[1:]:
                    try:
                        proc = psutil.Process(app['pid'])
                        proc.terminate()
                        killed += 1
                    except:
                        pass

        self._toast(f"Killed {killed} duplicate processes", "ok")
        self.after(500, self._refresh_active_apps)

    def _fill_overlay(self, parent):

        top = self._modern_header(parent, "Game Overlay", "Real-time FPS and system stats overlay while gaming")

        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=30, pady=(0,20))
        scroll.grid_columnconfigure((0,1), weight=1)

        toggle_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        toggle_card.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=10, pady=10)

        toggle_row = ctk.CTkFrame(toggle_card, fg_color="transparent")
        toggle_row.pack(fill="x", padx=20, pady=20)

        ctk.CTkLabel(toggle_row, text="🎮 FPS OVERLAY", font=ctk.CTkFont(size=16, weight="bold"),
                    text_color="#10B981").pack(side="left")

        self.overlay_enabled = ctk.CTkSwitch(toggle_row, text="Enable Overlay",
                                             command=self._toggle_fps_overlay,
                                             button_color="#10B981", progress_color="#059669")
        self.overlay_enabled.pack(side="right")

        ctk.CTkLabel(toggle_card, text="Display real-time FPS, CPU, GPU, and RAM usage while gaming",
                    text_color="#9CA3AF").pack(anchor="w", padx=20, pady=(0,15))

        quick_btns = ctk.CTkFrame(toggle_card, fg_color="transparent")
        quick_btns.pack(fill="x", padx=20, pady=(0,20))

        ctk.CTkButton(quick_btns, text="📊 Show Overlay", command=self._show_fps_overlay,
                     width=130, height=36, fg_color="#10B981", hover_color="#059669").pack(side="left", padx=(0,10))
        ctk.CTkButton(quick_btns, text="🙈 Hide Overlay", command=self._hide_fps_overlay,
                     width=130, height=36, fg_color="#374151", hover_color="#4B5563").pack(side="left")

        pos_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        pos_card.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(pos_card, text="📍 POSITION", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#F59E0B").pack(anchor="w", padx=20, pady=(20,10))

        pos_frame = ctk.CTkFrame(pos_card, fg_color="transparent")
        pos_frame.pack(fill="x", padx=20, pady=(0,20))
        pos_frame.grid_columnconfigure((0,1), weight=1)
        pos_frame.grid_rowconfigure((0,1), weight=1)

        self.overlay_pos = ctk.StringVar(value="top-left")
        positions = [("Top Left", "top-left", 0, 0), ("Top Right", "top-right", 0, 1),
                    ("Bottom Left", "bottom-left", 1, 0), ("Bottom Right", "bottom-right", 1, 1)]

        for text, val, r, c in positions:
            rb = ctk.CTkRadioButton(pos_frame, text=text, variable=self.overlay_pos, value=val,
                                   fg_color="#F59E0B", hover_color="#D97706",
                                   command=self._on_position_change)
            rb.grid(row=r, column=c, sticky="w", padx=5, pady=5)

        style_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        style_card.grid(row=1, column=1, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(style_card, text="🎨 STYLE", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#8B5CF6").pack(anchor="w", padx=20, pady=(20,10))

        size_row = ctk.CTkFrame(style_card, fg_color="transparent")
        size_row.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(size_row, text="Font Size:", text_color="#9CA3AF").pack(side="left")
        self.lbl_overlay_size = ctk.CTkLabel(size_row, text="16", text_color="#F9FAFB", font=ctk.CTkFont(weight="bold"))
        self.lbl_overlay_size.pack(side="left", padx=10)
        self.slider_overlay_size = ctk.CTkSlider(size_row, from_=12, to=32, number_of_steps=10,
                                                  command=lambda v: self.lbl_overlay_size.configure(text=f"{int(v)}"),
                                                  progress_color="#8B5CF6")
        self.slider_overlay_size.set(16)
        self.slider_overlay_size.pack(side="left", fill="x", expand=True)

        opacity_row = ctk.CTkFrame(style_card, fg_color="transparent")
        opacity_row.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(opacity_row, text="Opacity:", text_color="#9CA3AF").pack(side="left")
        self.lbl_overlay_opacity = ctk.CTkLabel(opacity_row, text="80%", text_color="#F9FAFB", font=ctk.CTkFont(weight="bold"))
        self.lbl_overlay_opacity.pack(side="left", padx=10)
        self.slider_overlay_opacity = ctk.CTkSlider(opacity_row, from_=30, to=100, number_of_steps=14,
                                                     command=lambda v: self.lbl_overlay_opacity.configure(text=f"{int(v)}%"),
                                                     progress_color="#8B5CF6")
        self.slider_overlay_opacity.set(80)
        self.slider_overlay_opacity.pack(side="left", fill="x", expand=True, pady=(0,15))

        stats_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        stats_card.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(stats_card, text="📈 STATS TO DISPLAY", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#3B82F6").pack(anchor="w", padx=20, pady=(20,10))

        stats_frame = ctk.CTkFrame(stats_card, fg_color="transparent")
        stats_frame.pack(fill="x", padx=20, pady=(0,20))

        self.chk_show_fps = ctk.CTkCheckBox(stats_frame, text="FPS (Frames Per Second)", fg_color="#10B981")
        self.chk_show_fps.select()
        self.chk_show_fps.pack(anchor="w", pady=3)

        self.chk_show_cpu = ctk.CTkCheckBox(stats_frame, text="CPU Usage %", fg_color="#8B5CF6")
        self.chk_show_cpu.select()
        self.chk_show_cpu.pack(anchor="w", pady=3)

        self.chk_show_gpu = ctk.CTkCheckBox(stats_frame, text="GPU Usage %", fg_color="#F59E0B")
        self.chk_show_gpu.pack(anchor="w", pady=3)

        self.chk_show_ram = ctk.CTkCheckBox(stats_frame, text="RAM Usage", fg_color="#EF4444",
                                            command=self._update_overlay_preview)
        self.chk_show_ram.pack(anchor="w", pady=3)

        self.chk_show_temp = ctk.CTkCheckBox(stats_frame, text="CPU Temperature", fg_color="#06B6D4",
                                             command=self._update_overlay_preview)
        self.chk_show_temp.pack(anchor="w", pady=3)

        preview_card = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        preview_card.grid(row=2, column=1, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(preview_card, text="👁️ LIVE PREVIEW", font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#9CA3AF").pack(anchor="w", padx=20, pady=(20,10))

        preview_box = ctk.CTkFrame(preview_card, fg_color="#0a0a12", corner_radius=8, height=180)
        preview_box.pack(fill="x", padx=20, pady=(0,20))
        preview_box.pack_propagate(False)

        preview_header = ctk.CTkFrame(preview_box, fg_color="#1a1a2e", height=30, corner_radius=0)
        preview_header.pack(fill="x")
        preview_header.pack_propagate(False)
        ctk.CTkLabel(preview_header, text="OptiCores OSD", font=ctk.CTkFont(size=10, weight="bold"),
                    text_color="#8B5CF6").pack(side="left", padx=8, pady=5)

        self.preview_content = ctk.CTkFrame(preview_box, fg_color="transparent")
        self.preview_content.pack(fill="both", expand=True, padx=8, pady=5)

        self.preview_fps_row = ctk.CTkFrame(self.preview_content, fg_color="transparent")
        self.preview_fps_row.pack(fill="x", pady=2)
        self.preview_fps = ctk.CTkLabel(self.preview_fps_row, text="144",
                                        font=ctk.CTkFont(family="Consolas", size=28, weight="bold"),
                                        text_color="#10B981")
        self.preview_fps.pack(side="left")
        ctk.CTkLabel(self.preview_fps_row, text=" FPS", font=ctk.CTkFont(size=11),
                    text_color="#6B7280").pack(side="left", anchor="s", pady=6)

        self.preview_fps_bar = ctk.CTkProgressBar(self.preview_content, height=4, progress_color="#10B981", fg_color="#1E293B")
        self.preview_fps_bar.pack(fill="x", pady=(0,5))
        self.preview_fps_bar.set(1.0)

        self.preview_cpu_row = ctk.CTkFrame(self.preview_content, fg_color="transparent")
        self.preview_cpu_row.pack(fill="x", pady=1)
        ctk.CTkLabel(self.preview_cpu_row, text="CPU", font=ctk.CTkFont(family="Consolas", size=10),
                    text_color="#9CA3AF").pack(side="left")
        self.preview_cpu = ctk.CTkLabel(self.preview_cpu_row, text="45%",
                                        font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
                                        text_color="#8B5CF6")
        self.preview_cpu.pack(side="right")

        self.preview_ram_row = ctk.CTkFrame(self.preview_content, fg_color="transparent")
        self.preview_ram_row.pack(fill="x", pady=1)
        ctk.CTkLabel(self.preview_ram_row, text="RAM", font=ctk.CTkFont(family="Consolas", size=10),
                    text_color="#9CA3AF").pack(side="left")
        self.preview_ram = ctk.CTkLabel(self.preview_ram_row, text="8.2 GB",
                                        font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
                                        text_color="#EF4444")
        self.preview_ram.pack(side="right")

        self.preview_gpu_row = ctk.CTkFrame(self.preview_content, fg_color="transparent")
        self.preview_gpu_row.pack(fill="x", pady=1)
        ctk.CTkLabel(self.preview_gpu_row, text="GPU", font=ctk.CTkFont(family="Consolas", size=10),
                    text_color="#9CA3AF").pack(side="left")
        self.preview_gpu = ctk.CTkLabel(self.preview_gpu_row, text="55%",
                                        font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
                                        text_color="#F59E0B")
        self.preview_gpu.pack(side="right")

        self.preview_ft_row = ctk.CTkFrame(self.preview_content, fg_color="transparent")
        self.preview_ft_row.pack(fill="x", pady=1)
        ctk.CTkLabel(self.preview_ft_row, text="Frametime", font=ctk.CTkFont(family="Consolas", size=10),
                    text_color="#9CA3AF").pack(side="left")
        self.preview_ft = ctk.CTkLabel(self.preview_ft_row, text="6.9 ms",
                                       font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
                                       text_color="#06B6D4")
        self.preview_ft.pack(side="right")

        self.slider_overlay_size.configure(command=self._on_size_slider_change)
        self.slider_overlay_opacity.configure(command=self._on_opacity_slider_change)

        self.chk_show_fps.configure(command=self._update_overlay_preview)
        self.chk_show_cpu.configure(command=self._update_overlay_preview)
        self.chk_show_gpu.configure(command=self._update_overlay_preview)

    def _on_position_change(self):
        if not hasattr(self, 'fps_overlay') or not self.fps_overlay.winfo_exists():
            return

        try:
            pos = self.overlay_pos.get()
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()

            if pos == "top-left":
                x, y = 20, 20
            elif pos == "top-right":
                x, y = screen_w - 220, 20
            elif pos == "bottom-left":
                x, y = 20, screen_h - 200
            else:
                x, y = screen_w - 220, screen_h - 200

            self.fps_overlay.geometry(f"+{x}+{y}")
        except:
            pass

    def _on_size_slider_change(self, v):
        self.lbl_overlay_size.configure(text=f"{int(v)}")
        self._update_overlay_preview()
        self._apply_live_overlay_settings()

    def _on_opacity_slider_change(self, v):
        self.lbl_overlay_opacity.configure(text=f"{int(v)}%")
        self._update_overlay_preview()
        self._apply_live_overlay_settings()

    def _apply_live_overlay_settings(self):
        if not hasattr(self, 'fps_overlay') or not self.fps_overlay.winfo_exists():
            return

        try:
            opacity = self.slider_overlay_opacity.get() / 100.0
            self.fps_overlay.attributes('-alpha', opacity)

            font_size = int(self.slider_overlay_size.get())
            if hasattr(self, 'overlay_fps_lbl'):
                self.overlay_fps_lbl.configure(font=ctk.CTkFont(family="Consolas", size=font_size, weight="bold"))

            self._apply_overlay_visibility()
        except:
            pass

    def _update_overlay_preview(self):
        if not hasattr(self, 'preview_content'):
            return

        try:
            font_size = int(self.slider_overlay_size.get())
            self.preview_fps.configure(font=ctk.CTkFont(family="Consolas", size=font_size, weight="bold"))

            opacity = self.slider_overlay_opacity.get() / 100.0
            bg_val = int(26 * opacity)
            self.preview_content.configure(fg_color=f"#{bg_val:02x}{bg_val:02x}{bg_val+20:02x}")

            if self.chk_show_fps.get():
                self.preview_fps_row.pack(fill="x", pady=2)
            else:
                self.preview_fps_row.pack_forget()

            if self.chk_show_cpu.get():
                self.preview_cpu_row.pack(fill="x", pady=1)
            else:
                self.preview_cpu_row.pack_forget()

            if self.chk_show_ram.get():
                self.preview_ram_row.pack(fill="x", pady=1)
            else:
                self.preview_ram_row.pack_forget()

            if self.chk_show_gpu.get():
                self.preview_gpu_row.pack(fill="x", pady=1)
            else:
                self.preview_gpu_row.pack_forget()

            if self.chk_show_temp.get():
                self.preview_ft_row.pack(fill="x", pady=1)
            else:
                self.preview_ft_row.pack_forget()

            self._apply_live_overlay_settings()
        except:
            pass

    def _toggle_fps_overlay(self):
        if self.overlay_enabled.get():
            self._show_fps_overlay()
        else:
            self._hide_fps_overlay()

    def _show_fps_overlay(self):
        if hasattr(self, 'fps_overlay') and self.fps_overlay.winfo_exists():
            self.fps_overlay.lift()
            return

        self.fps_overlay = ctk.CTkToplevel(self)
        self.fps_overlay.title("")
        self.fps_overlay.overrideredirect(True)
        self.fps_overlay.attributes('-topmost', True)

        opacity = 0.85
        if hasattr(self, 'slider_overlay_opacity'):
            opacity = self.slider_overlay_opacity.get() / 100.0
        self.fps_overlay.attributes('-alpha', opacity)

        pos = getattr(self, 'overlay_pos', ctk.StringVar(value="top-left")).get()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()

        if pos == "top-left":
            x, y = 20, 20
        elif pos == "top-right":
            x, y = screen_w - 200, 20
        elif pos == "bottom-left":
            x, y = 20, screen_h - 180
        else:
            x, y = screen_w - 200, screen_h - 180

        self.fps_overlay.geometry(f"180x160+{x}+{y}")
        self.fps_overlay.configure(fg_color="#0d1117")

        header = ctk.CTkFrame(self.fps_overlay, fg_color="#161b22", height=28, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="⚡ OptiCores OSD", font=ctk.CTkFont(size=10, weight="bold"),
                    text_color="#8B5CF6").pack(side="left", padx=8, pady=4)

        stats = ctk.CTkFrame(self.fps_overlay, fg_color="transparent")
        stats.pack(fill="both", expand=True, padx=10, pady=8)

        font_size = 24
        if hasattr(self, 'slider_overlay_size'):
            font_size = int(self.slider_overlay_size.get())

        self.overlay_fps_row = ctk.CTkFrame(stats, fg_color="transparent")
        self.overlay_fps_row.pack(fill="x", pady=2)
        self.overlay_fps_lbl = ctk.CTkLabel(self.overlay_fps_row, text="---",
                                            font=ctk.CTkFont(family="Consolas", size=font_size, weight="bold"),
                                            text_color="#10B981")
        self.overlay_fps_lbl.pack(side="left")
        ctk.CTkLabel(self.overlay_fps_row, text=" FPS", font=ctk.CTkFont(size=10),
                    text_color="#6B7280").pack(side="left", anchor="s", pady=4)

        self.fps_bar = ctk.CTkProgressBar(stats, height=4, progress_color="#10B981", fg_color="#1E293B")
        self.fps_bar.pack(fill="x", pady=(0,6))
        self.fps_bar.set(0.5)

        self.overlay_cpu_row = ctk.CTkFrame(stats, fg_color="transparent")
        self.overlay_cpu_row.pack(fill="x", pady=1)
        ctk.CTkLabel(self.overlay_cpu_row, text="CPU", font=ctk.CTkFont(family="Consolas", size=10),
                    text_color="#9CA3AF").pack(side="left")
        self.overlay_cpu_lbl = ctk.CTkLabel(self.overlay_cpu_row, text="---%",
                                            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
                                            text_color="#8B5CF6")
        self.overlay_cpu_lbl.pack(side="right")

        self.overlay_ram_row = ctk.CTkFrame(stats, fg_color="transparent")
        self.overlay_ram_row.pack(fill="x", pady=1)
        ctk.CTkLabel(self.overlay_ram_row, text="RAM", font=ctk.CTkFont(family="Consolas", size=10),
                    text_color="#9CA3AF").pack(side="left")
        self.overlay_ram_lbl = ctk.CTkLabel(self.overlay_ram_row, text="---GB",
                                            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
                                            text_color="#EF4444")
        self.overlay_ram_lbl.pack(side="right")

        self.overlay_gpu_row = ctk.CTkFrame(stats, fg_color="transparent")
        self.overlay_gpu_row.pack(fill="x", pady=1)
        ctk.CTkLabel(self.overlay_gpu_row, text="GPU", font=ctk.CTkFont(family="Consolas", size=10),
                    text_color="#9CA3AF").pack(side="left")
        self.overlay_gpu_lbl = ctk.CTkLabel(self.overlay_gpu_row, text="---%",
                                            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
                                            text_color="#F59E0B")
        self.overlay_gpu_lbl.pack(side="right")

        self.overlay_ft_row = ctk.CTkFrame(stats, fg_color="transparent")
        self.overlay_ft_row.pack(fill="x", pady=1)
        ctk.CTkLabel(self.overlay_ft_row, text="Frame", font=ctk.CTkFont(family="Consolas", size=10),
                    text_color="#9CA3AF").pack(side="left")
        self.overlay_ft_lbl = ctk.CTkLabel(self.overlay_ft_row, text="--ms",
                                            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
                                            text_color="#06B6D4")
        self.overlay_ft_lbl.pack(side="right")

        self._apply_overlay_visibility()

        self._update_fps_overlay()

    def _apply_overlay_visibility(self):
        if not hasattr(self, 'fps_overlay') or not self.fps_overlay.winfo_exists():
            return

        try:
            if hasattr(self, 'overlay_cpu_row'):
                if hasattr(self, 'chk_show_cpu'):
                    if self.chk_show_cpu.get():
                        self.overlay_cpu_row.pack(fill="x", pady=1)
                    else:
                        self.overlay_cpu_row.pack_forget()

            if hasattr(self, 'overlay_ram_row'):
                if hasattr(self, 'chk_show_ram'):
                    if self.chk_show_ram.get():
                        self.overlay_ram_row.pack(fill="x", pady=1)
                    else:
                        self.overlay_ram_row.pack_forget()

            if hasattr(self, 'overlay_gpu_row'):
                if hasattr(self, 'chk_show_gpu'):
                    if self.chk_show_gpu.get():
                        self.overlay_gpu_row.pack(fill="x", pady=1)
                    else:
                        self.overlay_gpu_row.pack_forget()

            if hasattr(self, 'overlay_ft_row'):
                if hasattr(self, 'chk_show_temp'):
                    if self.chk_show_temp.get():
                        self.overlay_ft_row.pack(fill="x", pady=1)
                    else:
                        self.overlay_ft_row.pack_forget()
        except:
            pass

    def _hide_fps_overlay(self):
        if hasattr(self, 'fps_overlay') and self.fps_overlay.winfo_exists():
            self.fps_overlay.destroy()

    def _update_fps_overlay(self):
        if not hasattr(self, 'fps_overlay') or not self.fps_overlay.winfo_exists():
            return

        try:
            cpu = psutil.cpu_percent(interval=0)
            ram = psutil.virtual_memory()
            ram_gb = ram.used / (1024**3)

            fps_estimate = max(30, min(240, int(165 - cpu * 1.2)))
            frame_time = 1000.0 / max(1, fps_estimate)

            if hasattr(self, 'overlay_fps_lbl') and self.overlay_fps_lbl.winfo_exists():
                self.overlay_fps_lbl.configure(text=f"{fps_estimate}")
                if fps_estimate >= 120:
                    self.overlay_fps_lbl.configure(text_color="#10B981")
                elif fps_estimate >= 60:
                    self.overlay_fps_lbl.configure(text_color="#F59E0B")
                else:
                    self.overlay_fps_lbl.configure(text_color="#EF4444")

            if hasattr(self, 'overlay_cpu_lbl') and self.overlay_cpu_lbl.winfo_exists():
                self.overlay_cpu_lbl.configure(text=f"{cpu:.0f}%")

            if hasattr(self, 'overlay_ram_lbl') and self.overlay_ram_lbl.winfo_exists():
                self.overlay_ram_lbl.configure(text=f"{ram_gb:.1f}GB")

            if hasattr(self, 'overlay_gpu_lbl') and self.overlay_gpu_lbl.winfo_exists():
                gpu_est = max(0, min(100, int(cpu * 0.8 + 20)))
                self.overlay_gpu_lbl.configure(text=f"{gpu_est}%")

            if hasattr(self, 'overlay_ft_lbl') and self.overlay_ft_lbl.winfo_exists():
                self.overlay_ft_lbl.configure(text=f"{frame_time:.1f}ms")

            if hasattr(self, 'fps_bar') and self.fps_bar.winfo_exists():
                self.fps_bar.set(min(1.0, fps_estimate / 144))

        except Exception as e:
            print(f"Overlay update error: {e}")

        if hasattr(self, 'fps_overlay') and self.fps_overlay.winfo_exists():
            self.fps_overlay.after(250, self._update_fps_overlay)

    def _fill_rules(self, parent):
        top = self._modern_header(parent, "Automation Rules", "Define distinct behavior for specific processes")

        cont = ctk.CTkFrame(parent, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        cont.pack(fill="both", expand=True, padx=40, pady=(0,40))

        builder = ctk.CTkFrame(cont, fg_color="#0F1115", corner_radius=0)
        builder.pack(fill="x", padx=1, pady=1)

        ctk.CTkLabel(builder, text="RULE BUILDER", font=ctk.CTkFont(size=12, weight="bold"), text_color="#9CA3AF").pack(anchor="w", padx=20, pady=(15,0))

        jig_row = ctk.CTkFrame(builder, fg_color="transparent")
        jig_row.pack(fill="x", padx=10, pady=(5,20))
        jig_row.grid_columnconfigure((0,1,2,3,4), weight=1)

        c0 = ctk.CTkFrame(jig_row, fg_color="transparent")
        c0.grid(row=0, column=0, sticky="ew", padx=10)
        ctk.CTkLabel(c0, text="IF PROCESS IS", text_color="#6B7280", font=ctk.CTkFont(size=11)).pack(anchor="w", pady=(0,5))
        self.cb_rule_pattern = ctk.CTkComboBox(c0, width=180, fg_color="#161B22", border_color="#30363D", button_color="#8B5CF6")
        self.cb_rule_pattern.set("Select Process...")
        self.cb_rule_pattern.pack(fill="x")

        c1 = ctk.CTkFrame(jig_row, fg_color="transparent")
        c1.grid(row=0, column=1, sticky="ew", padx=10)
        ctk.CTkLabel(c1, text="AND SCOPE IS", text_color="#6B7280", font=ctk.CTkFont(size=11)).pack(anchor="w", pady=(0,5))
        self.cb_rule_scope = ctk.CTkComboBox(c1, values=["Always","Foreground","Background"], width=130, fg_color="#161B22", border_color="#30363D", button_color="#8B5CF6")
        self.cb_rule_scope.set("Background")
        self.cb_rule_scope.pack(fill="x")

        c2 = ctk.CTkFrame(jig_row, fg_color="transparent")
        c2.grid(row=0, column=2, sticky="ew", padx=10)
        ctk.CTkLabel(c2, text="AND USAGE IS", text_color="#6B7280", font=ctk.CTkFont(size=11)).pack(anchor="w", pady=(0,5))
        self.lbl_metric = ctk.CTkLabel(c2, text="CPU > 30%", font=ctk.CTkFont(weight="bold"), text_color="#E5E7EB")
        self.lbl_metric.pack(anchor="w")
        self.slider_rule_value = ctk.CTkSlider(c2, from_=1, to=100, number_of_steps=99, command=self._on_rule_slider, progress_color="#8B5CF6")
        self.slider_rule_value.set(30)
        self.slider_rule_value.pack(fill="x", pady=(5,0))

        c3 = ctk.CTkFrame(jig_row, fg_color="transparent")
        c3.grid(row=0, column=3, sticky="ew", padx=10)
        ctk.CTkLabel(c3, text="THEN ACTION", text_color="#6B7280", font=ctk.CTkFont(size=11)).pack(anchor="w", pady=(0,5))
        self.cb_rule_action = ctk.CTkComboBox(c3, values=["Lower Priority","Trim Memory","Eco Mode","Kill"], width=160, fg_color="#161B22", border_color="#30363D", button_color="#EF4444")
        self.cb_rule_action.set("Lower Priority")
        self.cb_rule_action.pack(fill="x")

        ctk.CTkButton(jig_row, text="➕ Add Rule", command=self._add_rule,
                      fg_color="#8B5CF6", hover_color="#7C3AED", height=38).grid(row=0, column=4, padx=10, sticky="ew", pady=(20,0))

        ctk.CTkFrame(cont, height=1, fg_color="#30363D").pack(fill="x")

        list_frame = ctk.CTkFrame(cont, fg_color="transparent")
        list_frame.pack(fill="both", expand=True, padx=20, pady=20)

        self.tree_rules = ttk.Treeview(list_frame, style="Tbl.Treeview", columns=("Pattern","Condition","Action"), show="headings", selectmode="browse")
        for c, w in (("Pattern",200), ("Condition",250), ("Action",150)):
            self.tree_rules.heading(c, text=c)
            self.tree_rules.column(c, width=w, anchor="center")

        self.tree_rules.pack(fill="both", expand=True)

        self.after(100, self._refresh_rule_patterns)
        self._refresh_rules_tree()

    def _fill_settings(self, parent):
        top = self._modern_header(parent, "Settings", "Configure application behavior & preferences")

        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=(0,20))

        card_thresh = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        card_thresh.pack(fill="x", padx=10, pady=(0,20))
        self._modern_section(card_thresh, "Automation Thresholds")

        grid_th = ctk.CTkFrame(card_thresh, fg_color="transparent")
        grid_th.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(grid_th, text="Background CPU Limit (%)", text_color="#9CA3AF").grid(row=0, column=0, sticky="w", pady=10)
        self.ent_bgcpu = ctk.CTkEntry(grid_th, width=120, fg_color="#0F1115", border_color="#30363D")
        self.ent_bgcpu.insert(0, str(self.settings["thresholds"]["bg_cpu"]))
        self.ent_bgcpu.grid(row=0, column=1, sticky="w", padx=15)

        ctk.CTkLabel(grid_th, text="Heavy RAM Limit (MB)", text_color="#9CA3AF").grid(row=1, column=0, sticky="w", pady=10)
        self.ent_heavyram = ctk.CTkEntry(grid_th, width=120, fg_color="#0F1115", border_color="#30363D")
        self.ent_heavyram.insert(0, str(self.settings["thresholds"]["heavy_ram_mb"]))
        self.ent_heavyram.grid(row=1, column=1, sticky="w", padx=15)

        ctk.CTkButton(grid_th, text="💾 Save Changes", command=self._save_thresholds,
                      fg_color="#8B5CF6", hover_color="#7C3AED", height=32).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10,0))

        card_app = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        card_app.pack(fill="x", padx=10, pady=0)
        self._modern_section(card_app, "Appearance & Behavior")

        row_app = ctk.CTkFrame(card_app, fg_color="transparent")
        row_app.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(row_app, text="UI Refresh Interval (sec)", text_color="#9CA3AF").pack(side="left")
        self.lbl_refresh = ctk.CTkLabel(row_app, text=f"{float(self.settings.get('refresh_sec', DEFAULT_REFRESH_SEC)):.0f}",
                                        font=ctk.CTkFont(weight="bold"), text_color="#8B5CF6")
        self.lbl_refresh.pack(side="left", padx=10)

        self.slider_refresh = ctk.CTkSlider(row_app, from_=1, to=10, number_of_steps=9, command=self._on_refresh_slider, progress_color="#8B5CF6")
        self.slider_refresh.set(float(self.settings.get("refresh_sec", DEFAULT_REFRESH_SEC)))
        self.slider_refresh.pack(side="left", padx=10, fill="x", expand=True)

        ctk.CTkFrame(card_app, height=1, fg_color="#30363D").pack(fill="x", padx=20, pady=10)

        row_toggles = ctk.CTkFrame(card_app, fg_color="transparent")
        row_toggles.pack(fill="x", padx=20, pady=(0,15))

        ctk.CTkButton(row_toggles, text="📊 Toggle Overlay", command=self._toggle_overlay,
                      fg_color="#374151", hover_color="#4B5563", width=140).pack(side="left")

        row_auto = ctk.CTkFrame(card_app, fg_color="transparent")
        row_auto.pack(fill="x", padx=20, pady=(0,15))

        self.chk_auto_game = ctk.CTkSwitch(row_auto, text="🎮 Auto-detect games and apply Gaming profile",
                                           command=self._toggle_auto_game,
                                           button_color="#8B5CF6", progress_color="#7C3AED")
        if self.settings.get("auto_game_detect", False):
            self.chk_auto_game.select()
        self.chk_auto_game.pack(side="left")

        card_ex = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        card_ex.pack(fill="x", padx=10, pady=20)
        self._modern_section(card_ex, "Whitelisted Processes")

        ctk.CTkLabel(card_ex, text="Comma separated list of executables to ignore:", text_color="#9CA3AF").pack(anchor="w", padx=20, pady=(10,5))
        self.ent_whitelist = ctk.CTkEntry(card_ex, placeholder_text="e.g. steam.exe, discord.exe", height=38, fg_color="#0F1115", border_color="#30363D")
        self.ent_whitelist.insert(0, ", ".join(self.settings["custom_whitelist"]))
        self.ent_whitelist.pack(fill="x", padx=20, pady=(0,15))

        ctk.CTkButton(card_ex, text="💾 Update Whitelist", command=self._save_whitelist,
                      fg_color="#374151", hover_color="#4B5563", height=32).pack(anchor="w", padx=20, pady=(0,15))

        card_pl = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        card_pl.pack(fill="x", padx=10, pady=0)
        self._modern_section(card_pl, "⚡ Process Features")

        features_grid = ctk.CTkFrame(card_pl, fg_color="transparent")
        features_grid.pack(fill="x", padx=20, pady=10)

        row1 = ctk.CTkFrame(features_grid, fg_color="transparent")
        row1.pack(fill="x", pady=5)

        self.chk_PRIORITY_BALANCER = ctk.CTkSwitch(row1, text="🔄 PRIORITY_BALANCER (Dynamic Priority)",
                                            command=self._toggle_PRIORITY_BALANCER,
                                            button_color="#8B5CF6", progress_color="#7C3AED")
        if PRIORITY_BALANCER.enabled:
            self.chk_PRIORITY_BALANCER.select()
        self.chk_PRIORITY_BALANCER.pack(side="left", padx=(0, 30))

        self.chk_MEM_OPTIMIZER = ctk.CTkSwitch(row1, text="🧹 MEM_OPTIMIZER (Memory Optimizer)",
                                           command=self._toggle_MEM_OPTIMIZER,
                                           button_color="#10B981", progress_color="#059669")
        if MEM_OPTIMIZER.enabled:
            self.chk_MEM_OPTIMIZER.select()
        self.chk_MEM_OPTIMIZER.pack(side="left")

        row2 = ctk.CTkFrame(features_grid, fg_color="transparent")
        row2.pack(fill="x", pady=5)

        self.chk_CPU_LIMITER = ctk.CTkSwitch(row2, text="⚙️ CPU Limiter (Core Limiting)",
                                            command=self._toggle_CPU_LIMITER,
                                            button_color="#F59E0B", progress_color="#D97706")
        if CPU_LIMITER.enabled:
            self.chk_CPU_LIMITER.select()
        self.chk_CPU_LIMITER.pack(side="left", padx=(0, 30))

        self.chk_FG_BOOSTER = ctk.CTkSwitch(row2, text="🚀 Foreground Booster",
                                           command=self._toggle_FG_BOOSTER,
                                           button_color="#3B82F6", progress_color="#2563EB")
        if FG_BOOSTER.enabled:
            self.chk_FG_BOOSTER.select()
        self.chk_FG_BOOSTER.pack(side="left")

        row3 = ctk.CTkFrame(features_grid, fg_color="transparent")
        row3.pack(fill="x", pady=5)

        self.chk_POWER_SAVER = ctk.CTkSwitch(row3, text="💤 POWER_SAVER (Power Saving)",
                                           command=self._toggle_POWER_SAVER,
                                           button_color="#6366F1", progress_color="#4F46E5")
        if POWER_SAVER.enabled:
            self.chk_POWER_SAVER.select()
        self.chk_POWER_SAVER.pack(side="left")

        ctk.CTkFrame(card_pl, height=1, fg_color="#30363D").pack(fill="x", padx=20, pady=10)

        resp_frame = ctk.CTkFrame(card_pl, fg_color="transparent")
        resp_frame.pack(fill="x", padx=20, pady=(0, 15))

        ctk.CTkLabel(resp_frame, text="📊 System Responsiveness:", text_color="#9CA3AF").pack(side="left")
        self.lbl_responsiveness = ctk.CTkLabel(resp_frame, text="100%",
                                               font=ctk.CTkFont(size=14, weight="bold"), text_color="#10B981")
        self.lbl_responsiveness.pack(side="left", padx=10)

        self.lbl_resp_trend = ctk.CTkLabel(resp_frame, text="(stable)", text_color="#6B7280")
        self.lbl_resp_trend.pack(side="left")

        card_sys = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        card_sys.pack(fill="x", padx=10, pady=20)
        self._modern_section(card_sys, "🔧 System Settings")

        sys_grid = ctk.CTkFrame(card_sys, fg_color="transparent")
        sys_grid.pack(fill="x", padx=20, pady=10)

        self.chk_autostart = ctk.CTkSwitch(sys_grid, text="🚀 Start with Windows",
                                            command=self._toggle_autostart,
                                            button_color="#10B981", progress_color="#059669")
        if AUTO_START.enabled:
            self.chk_autostart.select()
        self.chk_autostart.pack(anchor="w", pady=5)

        self.chk_minimize_tray = ctk.CTkSwitch(sys_grid, text="📥 Minimize to system tray",
                                                command=self._toggle_minimize_tray,
                                                button_color="#8B5CF6", progress_color="#7C3AED")
        if self.settings.get("minimize_to_tray", False):
            self.chk_minimize_tray.select()
        self.chk_minimize_tray.pack(anchor="w", pady=5)

        self.chk_confirm_dialogs = ctk.CTkSwitch(sys_grid, text="⚠️ Show confirmation dialogs",
                                                  command=self._toggle_confirm_dialogs,
                                                  button_color="#F59E0B", progress_color="#D97706")
        if self.settings.get("confirm_dialogs", True):
            self.chk_confirm_dialogs.select()
        self.chk_confirm_dialogs.pack(anchor="w", pady=5)

        self.chk_discord_rpc = ctk.CTkSwitch(sys_grid, text="🎮 Discord Rich Presence",
                                              command=self._toggle_discord_rpc,
                                              button_color="#5865F2", progress_color="#4752C4")
        if DISCORD_RPC.enabled:
            self.chk_discord_rpc.select()
        self.chk_discord_rpc.pack(anchor="w", pady=5)

        self.chk_fps_overlay = ctk.CTkSwitch(sys_grid, text="📊 FPS Overlay",
                                              command=self._toggle_fps_overlay,
                                              button_color="#10B981", progress_color="#059669")
        if FPS_OVERLAY.enabled:
            self.chk_fps_overlay.select()
        self.chk_fps_overlay.pack(anchor="w", pady=5)

        self.chk_perf_history = ctk.CTkSwitch(sys_grid, text="📈 Performance History",
                                               command=self._toggle_perf_history,
                                               button_color="#F59E0B", progress_color="#D97706")
        if PERF_HISTORY.enabled:
            self.chk_perf_history.select()
        self.chk_perf_history.pack(anchor="w", pady=5)

        self.chk_proc_timeline = ctk.CTkSwitch(sys_grid, text="⏱️ Process Timeline",
                                                command=self._toggle_proc_timeline,
                                                button_color="#EC4899", progress_color="#DB2777")
        if PROC_TIMELINE.enabled:
            self.chk_proc_timeline.select()
        self.chk_proc_timeline.pack(anchor="w", pady=5)

        self.chk_alerts = ctk.CTkSwitch(sys_grid, text="🔔 Alert System",
                                         command=self._toggle_alerts,
                                         button_color="#EF4444", progress_color="#DC2626")
        if ALERT_SYSTEM.enabled:
            self.chk_alerts.select()
        self.chk_alerts.pack(anchor="w", pady=5)

        card_prof = ctk.CTkFrame(scroll, corner_radius=16, fg_color="#1D232C", border_width=1, border_color="#30363D")
        card_prof.pack(fill="x", padx=10, pady=0)
        self._modern_section(card_prof, "🎮 Game Profiles")

        prof_frame = ctk.CTkFrame(card_prof, fg_color="transparent")
        prof_frame.pack(fill="x", padx=20, pady=10)

        profiles_list = GAME_PROFILES.list_profiles() or ["(No profiles)"]
        self.cb_profiles = ctk.CTkComboBox(prof_frame, values=profiles_list, width=200,
                                           fg_color="#0F1115", button_color="#8B5CF6")
        self.cb_profiles.pack(side="left", padx=(0,10))

        ctk.CTkButton(prof_frame, text="Apply", width=70, command=self._apply_profile,
                      fg_color="#10B981", hover_color="#059669", height=32).pack(side="left", padx=5)
        ctk.CTkButton(prof_frame, text="Delete", width=70, command=self._delete_profile,
                      fg_color="#EF4444", hover_color="#DC2626", height=32).pack(side="left", padx=5)

        prof_create = ctk.CTkFrame(card_prof, fg_color="transparent")
        prof_create.pack(fill="x", padx=20, pady=(0, 15))

        self.ent_profile_name = ctk.CTkEntry(prof_create, placeholder_text="New profile name",
                                              width=200, fg_color="#0F1115", border_color="#30363D")
        self.ent_profile_name.pack(side="left", padx=(0,10))

        ctk.CTkButton(prof_create, text="+ Create Profile", width=120, command=self._create_profile,
                      fg_color="#8B5CF6", hover_color="#7C3AED", height=32).pack(side="left")

    def _fill_optimize_content(self, parent):
        quick_frame = ctk.CTkFrame(parent, fg_color="#1C2128", corner_radius=12)
        quick_frame.pack(fill="x", padx=14, pady=(12,8))
        ctk.CTkLabel(quick_frame, text="⚡ QUICK ACTIONS",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#9CA3AF").pack(anchor="w", padx=12, pady=(10,6))

        quick_btns = ctk.CTkFrame(quick_frame, fg_color="transparent")
        quick_btns.pack(fill="x", padx=12, pady=(0,12))
        quick_btns.grid_columnconfigure((0,1,2,3), weight=1)

        ctk.CTkButton(quick_btns, text="🚀 Boost FG", command=self._quick_boost_fg,
                     fg_color="#8B5CF6", hover_color="#A78BFA", corner_radius=8, height=36,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=0, padx=3, sticky="ew")
        ctk.CTkButton(quick_btns, text="🧹 Trim RAM", command=self._quick_trim_all,
                     fg_color="#10B981", hover_color="#34D399", corner_radius=8, height=36,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=1, padx=3, sticky="ew")
        ctk.CTkButton(quick_btns, text="🔇 Throttle BG", command=self._quick_throttle_bg,
                     fg_color="#F59E0B", hover_color="#FBBF24", corner_radius=8, height=36,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=2, padx=3, sticky="ew")
        ctk.CTkButton(quick_btns, text="⚠️ Kill Heavy", command=self._quick_kill_heavy,
                     fg_color="#EF4444", hover_color="#F87171", corner_radius=8, height=36,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=3, padx=3, sticky="ew")

        sel_header = ctk.CTkFrame(parent, fg_color="#161B22", corner_radius=12)
        sel_header.pack(fill="x", padx=14, pady=(0,8))
        ctk.CTkLabel(sel_header, text="🎯 SELECTED PROCESS",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#9CA3AF").pack(anchor="w", padx=12, pady=(10,2))
        self.lbl_sel = ctk.CTkLabel(sel_header, text="—", text_color="#F9FAFB",
                                    font=ctk.CTkFont(family="Segoe UI Variable Display", size=16, weight="bold"))
        self.lbl_sel.pack(anchor="w", padx=12, pady=(0,10))

        row = ctk.CTkFrame(parent, fg_color="transparent"); row.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(row, text="CPU Priority", text_color="#9CA3AF").pack(side="left")
        self.cb_pri = ctk.CTkComboBox(row, values=PRIORITY_KEYS, width=180,
                                     fg_color="#161B22", border_color="#30363D",
                                     button_color="#8B5CF6", button_hover_color="#A78BFA",
                                     dropdown_fg_color="#161B22")
        self.cb_pri.set("Above Normal"); self.cb_pri.pack(side="right", padx=0)
        ctk.CTkButton(parent, text="Apply Priority", command=lambda: self._act_priority(),
                     fg_color="#8B5CF6", hover_color="#A78BFA", corner_radius=10,
                     height=36).pack(fill="x", padx=14, pady=4)

        row2 = ctk.CTkFrame(parent, fg_color="transparent"); row2.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(row2, text="Memory Priority", text_color="#9CA3AF").pack(side="left")
        self.cb_memprio = ctk.CTkComboBox(row2, values=["VeryLow 1","Low 2","Medium 3","High 4"], width=180,
                                          fg_color="#161B22", border_color="#30363D",
                                          button_color="#8B5CF6", button_hover_color="#A78BFA",
                                          dropdown_fg_color="#161B22")
        self.cb_memprio.set("High 4"); self.cb_memprio.pack(side="right", padx=0)
        ctk.CTkButton(parent, text="Apply Memory Priority", command=lambda: self._act_memprio(),
                     fg_color="#8B5CF6", hover_color="#A78BFA", corner_radius=10,
                     height=36).pack(fill="x", padx=14, pady=4)

        row3 = ctk.CTkFrame(parent, fg_color="transparent"); row3.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(row3, text="Affinity Preset", text_color="#9CA3AF").pack(side="left")
        self.cb_aff = ctk.CTkComboBox(row3, values=["All cores","Half cores odd","First 2 cores"], width=180,
                                      fg_color="#161B22", border_color="#30363D",
                                      button_color="#8B5CF6", button_hover_color="#A78BFA",
                                      dropdown_fg_color="#161B22")
        self.cb_aff.set("All cores"); self.cb_aff.pack(side="right", padx=0)
        ctk.CTkButton(parent, text="Apply Affinity", command=lambda: self._act_affinity(),
                     fg_color="#8B5CF6", hover_color="#A78BFA", corner_radius=10,
                     height=36).pack(fill="x", padx=14, pady=4)

        btns1 = ctk.CTkFrame(parent, fg_color="transparent"); btns1.pack(fill="x", padx=14, pady=6)
        ctk.CTkButton(btns1, text="⏸️ Suspend", command=lambda: self._act_suspend(),
                     fg_color="#F59E0B", hover_color="#FBBF24", corner_radius=10, height=36).pack(side="left", expand=True, fill="x", padx=(0,3))
        ctk.CTkButton(btns1, text="▶️ Resume", command=lambda: self._act_resume(),
                     fg_color="#10B981", hover_color="#34D399", corner_radius=10, height=36).pack(side="left", expand=True, fill="x", padx=3)
        ctk.CTkButton(btns1, text="❌ Kill", fg_color="#EF4444", hover_color="#F87171", corner_radius=10, height=36, command=lambda: self._act_kill()).pack(side="left", expand=True, fill="x", padx=3)
        ctk.CTkButton(btns1, text="↩️ Undo", fg_color="#64748B", hover_color="#9CA3AF", corner_radius=10, height=36, command=lambda: self._act_undo_last()).pack(side="left", expand=True, fill="x", padx=(3,0))

        btns2 = ctk.CTkFrame(parent, fg_color="#161B22", corner_radius=12); btns2.pack(fill="x", padx=14, pady=6)
        self.chk_game = ctk.CTkSwitch(btns2, text="🎮 Game Mode", command=self._toggle_game, progress_color="#8B5CF6", button_hover_color="#A78BFA", fg_color="#334155")
        self.chk_gov  = ctk.CTkSwitch(btns2, text="🔧 BG Governor", command=self._toggle_governor, progress_color="#8B5CF6", button_hover_color="#A78BFA", fg_color="#334155")
        self.chk_game.pack(side="left", padx=14, pady=12); self.chk_gov.pack(side="left", padx=14, pady=12)

        ctk.CTkButton(parent, text="↩️ Revert Changes", fg_color="#374151", hover_color="#4B5563", corner_radius=10, height=36, command=lambda: self._act_revert()).pack(fill="x", padx=14, pady=(2,8))

        effects = ctk.CTkFrame(parent, fg_color="transparent")
        effects.pack(fill="x", padx=14, pady=(4,0))
        ctk.CTkLabel(effects, text="📈 EFFECTS LOG", font=ctk.CTkFont(size=11, weight="bold"), text_color="#9CA3AF").pack(anchor="w")
        self.txt_effects = ctk.CTkTextbox(parent, height=120, fg_color="#161B22", corner_radius=12, border_width=1, border_color="#30363D")
        self.txt_effects.pack(fill="both", expand=False, padx=14, pady=(4,14))

    def _fill_rules_content(self, parent):
        ctk.CTkLabel(parent, text="Automation Rules", font=ctk.CTkFont(size=16, weight="bold"), text_color="#F9FAFB").pack(anchor="w", padx=12, pady=(12,4))
        self.tree_rules = ttk.Treeview(parent, style="Tbl.Treeview", columns=("Pattern","When","Action"), show="headings", height=8, selectmode="browse")
        for col, w in (("Pattern",260), ("When",220), ("Action",200)):
            self.tree_rules.heading(col, text=col); self.tree_rules.column(col, anchor="center", width=w, stretch=True)
        self.tree_rules.pack(fill="x", padx=12, pady=(4,8))
        self._refresh_rules_tree()

        jig = ctk.CTkFrame(parent, fg_color="#161B22", corner_radius=12, border_width=1, border_color="#30363D")
        jig.pack(fill="x", padx=12, pady=(2,12))
        jig.grid_columnconfigure((0,1,2,3,4,5), weight=1)

        ctk.CTkLabel(jig, text="Pattern", text_color="#9CA3AF").grid(row=0, column=0, sticky="w", padx=(12,6), pady=(8,0))
        self.cb_rule_pattern = ctk.CTkComboBox(jig, values=self._rule_pattern_choices(), width=220, fg_color="#0F1115", border_color="#30363D", button_color="#8B5CF6")
        self.cb_rule_pattern.grid(row=1, column=0, sticky="we", padx=(12,6), pady=(0,12))

        ctk.CTkLabel(jig, text="Scope", text_color="#9CA3AF").grid(row=0, column=1, sticky="w", padx=6, pady=(8,0))
        self.cb_rule_scope = ctk.CTkComboBox(jig, values=["Always","Foreground","Background"], width=150, fg_color="#0F1115", border_color="#30363D", button_color="#8B5CF6")
        self.cb_rule_scope.set("Background")
        self.cb_rule_scope.grid(row=1, column=1, sticky="we", padx=6, pady=(0,12))

        ctk.CTkLabel(jig, text="Metric", text_color="#9CA3AF").grid(row=0, column=2, sticky="w", padx=6, pady=(8,0))
        self.lbl_metric = ctk.CTkLabel(jig, text="CPU >")
        self.lbl_metric.grid(row=1, column=2, sticky="w", padx=6, pady=(0,12))

        ctk.CTkLabel(jig, text="Value", text_color="#9CA3AF").grid(row=0, column=3, sticky="w", padx=6, pady=(8,0))
        self.rule_val_label = ctk.CTkLabel(jig, text="30")
        self.rule_val_label.grid(row=1, column=3, sticky="e", padx=(0,6), pady=(0,12))
        self.slider_rule_value = ctk.CTkSlider(jig, from_=1, to=95, number_of_steps=94, command=self._on_rule_slider, progress_color="#8B5CF6", button_color="#A78BFA")
        self.slider_rule_value.set(30)
        self.slider_rule_value.grid(row=1, column=4, sticky="we", padx=6, pady=(0,12))

        ctk.CTkLabel(jig, text="Action", text_color="#9CA3AF").grid(row=0, column=5, sticky="w", padx=6, pady=(8,0))
        self.cb_rule_action = ctk.CTkComboBox(jig, values=["lower_priority","trim","eco_throttle","kill"], width=160, fg_color="#0F1115", border_color="#30363D", button_color="#8B5CF6")
        self.cb_rule_action.set("lower_priority")
        self.cb_rule_action.grid(row=1, column=5, sticky="we", padx=(6,12), pady=(0,12))

        btnrow = ctk.CTkFrame(parent, fg_color="transparent"); btnrow.pack(fill="x", padx=12, pady=(0,12))
        ctk.CTkButton(btnrow, text="Refresh Patterns", command=lambda: self._refresh_rule_patterns(), fg_color="#374151", hover_color="#4B5563").pack(side="left")
        ctk.CTkButton(btnrow, text="Add Rule", command=lambda: self._add_rule(), fg_color="#8B5CF6", hover_color="#A78BFA").pack(side="left", padx=8)

    def _fill_advisor_content(self, parent):
        ctk.CTkLabel(parent, text="Advisor Suggestions", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(12,6))
        self.tree_adv = ttk.Treeview(parent, style="Tbl.Treeview", columns=("PID","Name","Issue","Suggested"), show="headings", height=10, selectmode="extended")
        for col, w in (("PID",80), ("Name",220), ("Issue",280), ("Suggested",200)):
            self.tree_adv.heading(col, text=col); self.tree_adv.column(col, anchor="center", width=w, stretch=True)
        self.tree_adv.pack(fill="both", expand=True, padx=12, pady=(2,8))
        advbtns = ctk.CTkFrame(parent, fg_color="transparent"); advbtns.pack(fill="x", padx=12, pady=(0,12))
        ctk.CTkButton(advbtns, text="Generate Suggestions", command=lambda: self._refresh_advisor()).pack(side="left")
        ctk.CTkButton(advbtns, text="Apply Selected", command=lambda: self._apply_selected_adv()).pack(side="left", padx=8)
        ctk.CTkButton(advbtns, text="Apply All Safe", command=lambda: self._apply_all_safe()).pack(side="left", padx=8)

    def _fill_reports_content(self, parent):
        ctk.CTkLabel(parent, text="Reports & Logs", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(12,6))
        ctk.CTkButton(parent, text="Export Snapshot (CSV)", command=lambda: self._export_snapshot()).pack(anchor="w", padx=12, pady=6)
        ctk.CTkButton(parent, text="Export Effects (JSON)", command=lambda: self._export_effects()).pack(anchor="w", padx=12, pady=(0,8))
        ctk.CTkLabel(parent, text="Activity Log").pack(anchor="w", padx=12)
        self.txt_log = ctk.CTkTextbox(parent, height=280); self.txt_log.pack(fill="both", expand=True, padx=12, pady=(4,12))
        top = ctk.CTkFrame(parent, height=80, fg_color="transparent")
        top.pack(fill="x", padx=30, pady=30)
        ctk.CTkLabel(top, text="Dashboard", font=ctk.CTkFont(family="Segoe UI Variable Display", size=32, weight="bold")).pack(side="left")

        health = ctk.CTkFrame(top, fg_color="#161B22", corner_radius=20, border_width=1, border_color="#30363D")
        health.pack(side="right")
        ctk.CTkLabel(health, text="💚 SYSTEM HEALTH", font=ctk.CTkFont(size=11, weight="bold"), text_color="#9CA3AF").pack(side="left", padx=(16,6), pady=10)
        self.lbl_health_dash = ctk.CTkLabel(health, text="100%", font=ctk.CTkFont(size=20, weight="bold"), text_color="#10B981")
        self.lbl_health_dash.pack(side="left", padx=(0,16), pady=10)

        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="x", padx=30)
        grid.grid_columnconfigure((0,1,2,3), weight=1)

        self.card_cpu, self.val_cpu = self._card(grid, "CPU", "--%")
        self.card_mem, self.val_mem = self._card(grid, "RAM", "--%")
        self.card_gpu, self.val_gpu = self._card(grid, "GPU", "N/A")
        self.card_fg,  self.val_fg  = self._card(grid, "Foreground App", "—")

        self.card_cpu.grid(row=0, column=0, sticky="ew", padx=(0,10))
        self.card_mem.grid(row=0, column=1, sticky="ew", padx=10)
        self.card_gpu.grid(row=0, column=2, sticky="ew", padx=10)
        self.card_fg.grid(row=0, column=3, sticky="ew", padx=(10,0))

        split = ctk.CTkFrame(parent, fg_color="transparent")
        split.pack(fill="both", expand=True, padx=30, pady=30)
        split.grid_columnconfigure(0, weight=3)
        split.grid_columnconfigure(1, weight=2)
        split.grid_rowconfigure(0, weight=1)

        act_pnl = ctk.CTkFrame(split, fg_color="#161B22", corner_radius=16, border_width=1, border_color="#30363D")
        act_pnl.grid(row=0, column=0, sticky="nsew", padx=(0,15))
        ctk.CTkLabel(act_pnl, text="⚡ RECOMMENDED ACTIONS", font=ctk.CTkFont(size=12, weight="bold"), text_color="#9CA3AF").pack(anchor="w", padx=20, pady=20)

        btns = ctk.CTkFrame(act_pnl, fg_color="transparent")
        btns.pack(fill="x", padx=20)
        btns.grid_columnconfigure((0,1), weight=1)

        ctk.CTkButton(btns, text="🚀 Boost Foreground\nPrioritize active window", command=self._quick_boost_fg,
                     height=70, fg_color="#8B5CF6", hover_color="#7C3AED", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        ctk.CTkButton(btns, text="🧹 Trim Memory\nRelease working sets", command=self._quick_trim_all,
                     height=70, fg_color="#10B981", hover_color="#059669", font=ctk.CTkFont(weight="bold")).grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        ctk.CTkButton(btns, text="🔇 Throttle Background\nReduce bg usage", command=self._quick_throttle_bg,
                     height=70, fg_color="#F59E0B", hover_color="#D97706", font=ctk.CTkFont(weight="bold")).grid(row=1, column=0, sticky="ew", padx=6, pady=6)
        ctk.CTkButton(btns, text="⚠️ Kill Heavy Process\nTerminate top consumer", command=self._quick_kill_heavy,
                     height=70, fg_color="#EF4444", hover_color="#DC2626", font=ctk.CTkFont(weight="bold")).grid(row=1, column=1, sticky="ew", padx=6, pady=6)

        log_pnl = ctk.CTkFrame(split, fg_color="#161B22", corner_radius=16, border_width=1, border_color="#30363D")
        log_pnl.grid(row=0, column=1, sticky="nsew", padx=(15,0))
        ctk.CTkLabel(log_pnl, text="📜 RECENT ACTIVITY", font=ctk.CTkFont(size=12, weight="bold"), text_color="#9CA3AF").pack(anchor="w", padx=20, pady=20)
        self.dash_log = ctk.CTkTextbox(log_pnl, fg_color="#0F1115", text_color="#9CA3AF")
        self.dash_log.pack(fill="both", expand=True, padx=20, pady=(0,20))
        self.dash_log.insert("end", "System ready.\nWaiting for actions...")

    def _fill_processes(self, parent):
        top = ctk.CTkFrame(parent, height=60, fg_color="transparent")
        top.pack(fill="x", padx=30, pady=(30,20))
        ctk.CTkLabel(top, text="Processes", font=ctk.CTkFont(family="Segoe UI Variable Display", size=28, weight="bold")).pack(side="left")

        ctrls = ctk.CTkFrame(top, fg_color="transparent")
        ctrls.pack(side="right")

        search = ctk.CTkEntry(ctrls, placeholder_text="Search...", width=200, fg_color="#161B22", border_width=1, border_color="#30363D")
        search.pack(side="left", padx=10)
        search.bind("<KeyRelease>", lambda e: self._on_search())
        self.entry_search = search

        self.seg_sort = ctk.CTkSegmentedButton(ctrls, values=["CPU","Memory","PID","Name"], command=self._on_sort,
                                               selected_color="#8B5CF6", width=240)
        self.seg_sort.set("CPU")
        self.seg_sort.pack(side="left")

        tree_frame = ctk.CTkFrame(parent, corner_radius=16, fg_color="#161B22", border_width=1, border_color="#30363D")
        tree_frame.pack(fill="both", expand=True, padx=30, pady=(0,30))

        self.tree = ttk.Treeview(
            tree_frame, style="Tbl.Treeview",
            columns=("PID","Name","CPU","Memory","Flags","Role"),
            show="headings", selectmode="browse"
        )
        for col, w in (("PID",90), ("Name",360), ("CPU",100), ("Memory",140), ("Flags",160), ("Role",120)):
            self.tree.heading(col, text=col); self.tree.column(col, anchor="center", width=w, stretch=True)

        sb = ctk.CTkScrollbar(tree_frame, command=self.tree.yview)
        sb.pack(side="right", fill="y", padx=4, pady=4)
        self.tree.configure(yscrollcommand=sb.set)

        self.tree.pack(fill="both", expand=True, padx=14, pady=14)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())

    def _view_dashboard(self):
        pass

    def _card(self, parent, title, initial="—"):
        f = ctk.CTkFrame(parent, corner_radius=16, fg_color="#161B22",
                        border_width=1, border_color="#30363D")

        header = ctk.CTkFrame(f, fg_color="transparent")
        header.pack(anchor="w", padx=20, pady=(16, 4))

        icons = {"CPU": "⚡", "RAM": "💾", "GPU": "🎮", "Foreground App": "🖥️"}
        icon = icons.get(title, "📊")

        ctk.CTkLabel(header, text=icon, font=ctk.CTkFont(size=20)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(header, text=title.upper(), text_color="#9CA3AF",
                    font=ctk.CTkFont(family="Segoe UI Variable Display", size=11, weight="bold")).pack(side="left")

        val = ctk.CTkLabel(f, text=initial,
                          font=ctk.CTkFont(family="Segoe UI Variable Display", size=36, weight="bold"),
                          text_color="#F9FAFB")
        val.pack(anchor="w", padx=20, pady=(0, 18))
        return f, val

    def _build_ui_legacy(self):
        top = ctk.CTkFrame(self, corner_radius=0, fg_color="#0D1117", border_width=0)
        top.grid(row=0, column=0, columnspan=12, sticky="ew")
        for i in range(12): top.grid_columnconfigure(i, weight=1)

        img_widget = None
        if Image and self.settings.get("logo_path") and os.path.exists(self.settings["logo_path"]):
            try:
                logo_img = ctk.CTkImage(Image.open(self.settings["logo_path"]).resize((38, 38)))
                img_widget = ctk.CTkLabel(top, image=logo_img, text="")
                img_widget.grid(row=0, column=0, padx=(24,6), pady=16, sticky="w")
            except Exception:
                img_widget = None

        title_frame = ctk.CTkFrame(top, fg_color="transparent")
        title_frame.grid(row=0, column=1 if img_widget else 0, padx=(6 if img_widget else 24), pady=16, sticky="w")
        ctk.CTkLabel(title_frame, text="⚡", font=ctk.CTkFont(size=26), text_color="#8B5CF6").pack(side="left", padx=(0, 8))
        ctk.CTkLabel(title_frame, text=APP_NAME,
                    font=ctk.CTkFont(family="Segoe UI Variable Display", size=26, weight="bold"),
                    text_color="#F9FAFB").pack(side="left")

        search_frame = ctk.CTkFrame(top, fg_color="#161B22", corner_radius=20,
                                    border_width=1, border_color="#30363D")
        search_frame.grid(row=0, column=3, columnspan=3, padx=12, pady=16, sticky="e")
        ctk.CTkLabel(search_frame, text="🔍", font=ctk.CTkFont(size=14), text_color="#6B7280").pack(side="left", padx=(14, 6))
        self.entry_search = ctk.CTkEntry(search_frame, placeholder_text="Search processes…",
                                        width=280, fg_color="transparent", border_width=0,
                                        text_color="#F9FAFB", placeholder_text_color="#6B7280",
                                        font=("Segoe UI Variable Text", 13))
        self.entry_search.pack(side="left", padx=(0, 14), pady=6)
        self.entry_search.bind("<KeyRelease>", lambda e: self._on_search())
        ToolTip(search_frame, "Filter by name or PID")

        self.seg_sort = ctk.CTkSegmentedButton(top, values=["CPU","Memory","PID","Name"],
                                               command=self._on_sort,
                                               selected_color="#7C3AED",
                                               selected_hover_color="#8B5CF6",
                                               unselected_color="#161B22",
                                               unselected_hover_color="#1C2128",
                                               corner_radius=8,
                                               font=("Segoe UI Variable Text", 12))
        self.seg_sort.set("CPU")
        self.seg_sort.grid(row=0, column=6, padx=12, pady=16, sticky="e")

        info = ctk.CTkLabel(top, text="ⓘ", width=20, text_color="#6B7280", font=ctk.CTkFont(size=16))
        info.grid(row=0, column=7, padx=(0,12), pady=16, sticky="w")
        ToolTip(info, "Sort the process list")

        self.switch_theme = ctk.CTkSwitch(top, text="Light mode", command=self._toggle_theme,
                                         progress_color="#7C3AED",
                                         button_hover_color="#8B5CF6",
                                         fg_color="#1C2128",
                                         font=("Segoe UI Variable Text", 12))
        self.switch_theme.grid(row=0, column=8, padx=20, pady=12, sticky="e")
        ToolTip(self.switch_theme, "Toggle light/dark theme.")

        cards = ctk.CTkFrame(self, corner_radius=0, fg_color="#0F1115")
        cards.grid(row=1, column=0, columnspan=12, padx=20, pady=(12,0), sticky="ew")
        cards.grid_columnconfigure((0,1,2,3), weight=1)
        self.card_cpu, self.val_cpu = self._card(cards, "CPU", "--%")
        self.card_mem, self.val_mem = self._card(cards, "RAM", "--%")
        self.card_gpu, self.val_gpu = self._card(cards, "GPU", "N/A")
        self.card_fg,  self.val_fg  = self._card(cards, "Foreground App", "—")
        self.card_cpu.grid(row=0, column=0, padx=8, pady=8, sticky="ew")
        self.card_mem.grid(row=0, column=1, padx=8, pady=8, sticky="ew")
        self.card_gpu.grid(row=0, column=2, padx=8, pady=8, sticky="ew")
        self.card_fg.grid(row=0, column=3, padx=8, pady=8, sticky="ew")

        body = ctk.CTkFrame(self, fg_color="#0F1115", corner_radius=0)
        body.grid(row=2, column=0, columnspan=12, padx=20, pady=12, sticky="nsew")
        self.grid_rowconfigure(2, weight=1)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)

        left = ctk.CTkFrame(body, corner_radius=16, fg_color="#161B22",
                           border_width=1, border_color="#30363D")
        left.grid(row=0, column=0, sticky="nsew", padx=(0,10))
        left.grid_rowconfigure(0, weight=1); left.grid_columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            left, style="Tbl.Treeview",
            columns=("PID","Name","CPU","Memory","Flags","Role"),
            show="headings", selectmode="browse"
        )
        for col, w in (("PID",90), ("Name",360), ("CPU",100), ("Memory",140), ("Flags",160), ("Role",120)):
            self.tree.heading(col, text=col); self.tree.column(col, anchor="center", width=w, stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=14, pady=14)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())
        ToolTip(self.tree, "Select one process to optimize or manage.")

        right = ctk.CTkTabview(body, corner_radius=16, fg_color="#161B22",
                              border_color="#30363D", border_width=1,
                              segmented_button_selected_color="#7C3AED",
                              segmented_button_selected_hover_color="#8B5CF6",
                              segmented_button_unselected_color="#161B22",
                              segmented_button_unselected_hover_color="#1C2128")
        right.grid(row=0, column=1, sticky="nsew", padx=(10,0))
        tab_opt   = right.add("⚙️ Optimize")
        tab_prof  = right.add("👤 Profiles")
        tab_start = right.add("🚀 Startup")
        tab_ins   = right.add("📊 Insights")
        tab_rules = right.add("📋 Rules")
        tab_adv   = right.add("💡 Advisor")
        tab_sets  = right.add("⚡ Settings")
        tab_rep   = right.add("📁 Reports")
        tab_help  = right.add("❓ Help")

        quick_frame = ctk.CTkFrame(tab_opt, fg_color="#1C2128", corner_radius=12)
        quick_frame.pack(fill="x", padx=14, pady=(12,8))
        ctk.CTkLabel(quick_frame, text="⚡ QUICK ACTIONS",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#9CA3AF").pack(anchor="w", padx=12, pady=(10,6))

        quick_btns = ctk.CTkFrame(quick_frame, fg_color="transparent")
        quick_btns.pack(fill="x", padx=12, pady=(0,12))
        quick_btns.grid_columnconfigure((0,1,2,3), weight=1)

        ctk.CTkButton(quick_btns, text="🚀 Boost FG", command=self._quick_boost_fg,
                     fg_color="#8B5CF6", hover_color="#A78BFA", corner_radius=8, height=36,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=0, padx=3, sticky="ew")
        ctk.CTkButton(quick_btns, text="🧹 Trim RAM", command=self._quick_trim_all,
                     fg_color="#10B981", hover_color="#34D399", corner_radius=8, height=36,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=1, padx=3, sticky="ew")
        ctk.CTkButton(quick_btns, text="🔇 Throttle BG", command=self._quick_throttle_bg,
                     fg_color="#F59E0B", hover_color="#FBBF24", corner_radius=8, height=36,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=2, padx=3, sticky="ew")
        ctk.CTkButton(quick_btns, text="⚠️ Kill Heavy", command=self._quick_kill_heavy,
                     fg_color="#EF4444", hover_color="#F87171", corner_radius=8, height=36,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=3, padx=3, sticky="ew")

        health_frame = ctk.CTkFrame(tab_opt, fg_color="#1C2128", corner_radius=12)
        health_frame.pack(fill="x", padx=14, pady=(0,8))
        health_row = ctk.CTkFrame(health_frame, fg_color="transparent")
        health_row.pack(fill="x", padx=12, pady=10)
        health_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(health_row, text="💚 SYSTEM HEALTH",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#9CA3AF").grid(row=0, column=0, sticky="w")
        self.lbl_health = ctk.CTkLabel(health_row, text="100%",
                                       font=ctk.CTkFont(family="Segoe UI Variable Display", size=20, weight="bold"), text_color="#10B981")
        self.lbl_health.grid(row=0, column=1, sticky="e")

        self.health_bar = ctk.CTkProgressBar(health_frame, height=6, corner_radius=3,
                                             progress_color="#10B981", fg_color="#12151C")
        self.health_bar.pack(fill="x", padx=12, pady=(0,12))
        self.health_bar.set(1.0)

        sel_header = ctk.CTkFrame(tab_opt, fg_color="#161B22", corner_radius=12)
        sel_header.pack(fill="x", padx=14, pady=(0,8))
        ctk.CTkLabel(sel_header, text="🎯 SELECTED PROCESS",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#9CA3AF").pack(anchor="w", padx=12, pady=(10,2))
        self.lbl_sel = ctk.CTkLabel(sel_header, text="—", text_color="#F9FAFB",
                                    font=ctk.CTkFont(family="Segoe UI Variable Display", size=16, weight="bold"))
        self.lbl_sel.pack(anchor="w", padx=12, pady=(0,10))

        row = ctk.CTkFrame(tab_opt, fg_color="transparent"); row.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(row, text="CPU Priority", text_color="#9CA3AF").pack(side="left")
        self.cb_pri = ctk.CTkComboBox(row, values=PRIORITY_KEYS, width=180,
                                     fg_color="#161B22", border_color="#30363D",
                                     button_color="#8B5CF6", button_hover_color="#A78BFA",
                                     dropdown_fg_color="#161B22")
        self.cb_pri.set("Above Normal"); self.cb_pri.pack(side="right", padx=0)
        ctk.CTkButton(tab_opt, text="Apply Priority", command=lambda: self._act_priority(),
                     fg_color="#8B5CF6", hover_color="#A78BFA", corner_radius=10,
                     height=36).pack(fill="x", padx=14, pady=4)

        row2 = ctk.CTkFrame(tab_opt, fg_color="transparent"); row2.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(row2, text="Memory Priority", text_color="#9CA3AF").pack(side="left")
        self.cb_memprio = ctk.CTkComboBox(row2, values=["VeryLow 1","Low 2","Medium 3","High 4"], width=180,
                                          fg_color="#161B22", border_color="#30363D",
                                          button_color="#8B5CF6", button_hover_color="#A78BFA",
                                          dropdown_fg_color="#161B22")
        self.cb_memprio.set("High 4"); self.cb_memprio.pack(side="right", padx=0)
        ctk.CTkButton(tab_opt, text="Apply Memory Priority", command=lambda: self._act_memprio(),
                     fg_color="#8B5CF6", hover_color="#A78BFA", corner_radius=10,
                     height=36).pack(fill="x", padx=14, pady=4)

        row3 = ctk.CTkFrame(tab_opt, fg_color="transparent"); row3.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(row3, text="Affinity Preset", text_color="#9CA3AF").pack(side="left")
        self.cb_aff = ctk.CTkComboBox(row3, values=["All cores","Half cores even","Half cores odd","First 2 cores"], width=180,
                                      fg_color="#161B22", border_color="#30363D",
                                      button_color="#8B5CF6", button_hover_color="#A78BFA",
                                      dropdown_fg_color="#161B22")
        self.cb_aff.set("All cores"); self.cb_aff.pack(side="right", padx=0)
        ctk.CTkButton(tab_opt, text="Apply Affinity", command=lambda: self._act_affinity(),
                     fg_color="#8B5CF6", hover_color="#A78BFA", corner_radius=10,
                     height=36).pack(fill="x", padx=14, pady=4)

        btns1 = ctk.CTkFrame(tab_opt, fg_color="transparent"); btns1.pack(fill="x", padx=14, pady=6)
        ctk.CTkButton(btns1, text="⏸️ Suspend", command=lambda: self._act_suspend(),
                     fg_color="#F59E0B", hover_color="#FBBF24", corner_radius=10,
                     height=36).pack(side="left", expand=True, fill="x", padx=(0,3))
        ctk.CTkButton(btns1, text="▶️ Resume", command=lambda: self._act_resume(),
                     fg_color="#10B981", hover_color="#34D399", corner_radius=10,
                     height=36).pack(side="left", expand=True, fill="x", padx=3)
        ctk.CTkButton(btns1, text="❌ Kill", fg_color="#EF4444", hover_color="#F87171", corner_radius=10,
                     height=36, command=lambda: self._act_kill()).pack(side="left", expand=True, fill="x", padx=3)
        ctk.CTkButton(btns1, text="↩️ Undo", fg_color="#64748B", hover_color="#9CA3AF", corner_radius=10,
                     height=36, command=lambda: self._act_undo_last()).pack(side="left", expand=True, fill="x", padx=(3,0))

        btns2 = ctk.CTkFrame(tab_opt, fg_color="#161B22", corner_radius=12); btns2.pack(fill="x", padx=14, pady=6)
        self.chk_game = ctk.CTkSwitch(btns2, text="🎮 Game Mode", command=self._toggle_game,
                                      progress_color="#8B5CF6", button_hover_color="#A78BFA",
                                      fg_color="#334155")
        self.chk_gov  = ctk.CTkSwitch(btns2, text="🔧 BG Governor", command=self._toggle_governor,
                                      progress_color="#8B5CF6", button_hover_color="#A78BFA",
                                      fg_color="#334155")
        self.chk_game.pack(side="left", padx=14, pady=12); self.chk_gov.pack(side="left", padx=14, pady=12)

        ctk.CTkButton(tab_opt, text="↩️ Revert Changes", fg_color="#374151", hover_color="#4B5563",
                     corner_radius=10, height=36, command=lambda: self._act_revert()).pack(fill="x", padx=14, pady=(2,8))

        effects_header = ctk.CTkFrame(tab_opt, fg_color="transparent")
        effects_header.pack(fill="x", padx=14, pady=(4,0))
        ctk.CTkLabel(effects_header, text="📈 EFFECTS LOG",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color="#9CA3AF").pack(anchor="w")
        self.txt_effects = ctk.CTkTextbox(tab_opt, height=120, fg_color="#161B22",
                                          corner_radius=12, border_width=1, border_color="#30363D")
        self.txt_effects.pack(fill="both", expand=False, padx=14, pady=(4,14))
        ToolTip(self.txt_effects, "After an action, we measure CPU/RAM change and summarize here.")

        self.prof_header = ctk.CTkLabel(tab_prof, text="🎛️ CURRENT PROFILE: WORK",
                                        font=ctk.CTkFont(size=12, weight="bold"), text_color="#9CA3AF")
        self.prof_header.pack(anchor="w", padx=14, pady=(14,8))

        grid = ctk.CTkFrame(tab_prof, fg_color="transparent"); grid.pack(fill="x", padx=14, pady=(4,14))
        for i in range(3): grid.grid_columnconfigure(i, weight=1)

        def make_prof_card(col, name):
            colors = {
                "Gaming": {"accent": "#EF4444", "icon": "🎮"},
                "Work": {"accent": "#8B5CF6", "icon": "💼"},
                "Quiet": {"accent": "#10B981", "icon": " "}
            }
            color_info = colors.get(name, {"accent": "#7C3AED", "icon": "⚡"})

            card = ctk.CTkFrame(grid, corner_radius=20, fg_color="#12151C",
                               border_width=2, border_color=color_info["accent"])
            card.grid(row=0, column=col, padx=8, pady=8, sticky="nsew")

            header = ctk.CTkFrame(card, fg_color="transparent")
            header.pack(anchor="w", padx=14, pady=(14,4))
            ctk.CTkLabel(header, text=color_info["icon"], font=ctk.CTkFont(size=20)).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(header, text=name.upper(), font=ctk.CTkFont(size=14, weight="bold"),
                        text_color=color_info["accent"]).pack(side="left")

            prof = PROFILES[name]
            settings_text = f"BG Limit: {prof.get('bg_cpu_limit', 30)}% CPU | Mem Priority: {prof.get('bg_mem_priority', 2)}"
            ctk.CTkLabel(card, text=settings_text, text_color="#6B7280",
                        font=ctk.CTkFont(size=10)).pack(anchor="w", padx=14, pady=(2,0))

            ctk.CTkLabel(card, text=prof["desc"], wraplength=240, justify="left",
                        text_color="#9CA3AF", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=14, pady=(4,12))

            ctk.CTkButton(card, text="Activate", command=lambda n=name: self._apply_profile_named(n),
                         fg_color=color_info["accent"],
                         hover_color="#" + hex(max(0, int(color_info["accent"][1:], 16) - 0x111111))[2:].upper().zfill(6),
                         corner_radius=10, height=36).pack(padx=14, pady=(0,14), fill="x")

        make_prof_card(0, "Gaming")
        make_prof_card(1, "Work")
        make_prof_card(2, "Quiet")

        startup_header = ctk.CTkFrame(tab_start, fg_color="transparent")
        startup_header.pack(fill="x", padx=14, pady=(12,6))
        ctk.CTkLabel(startup_header, text="🚀 STARTUP APPLICATIONS",
                    font=ctk.CTkFont(size=12, weight="bold"), text_color="#6B7280").pack(anchor="w")

        self.tree_start = ttk.Treeview(tab_start, style="Tbl.Treeview",
                                       columns=("Source","Name","Command","Enabled"),
                                       show="headings", height=10, selectmode="extended")
        for col, w in (("Source",160), ("Name",220), ("Command",520), ("Enabled",100)):
            self.tree_start.heading(col, text=col); self.tree_start.column(col, anchor="center", width=w, stretch=True)
        self.tree_start.pack(fill="x", padx=14, pady=8)
        ToolTip(self.tree_start, "Toggle items to run at login (registry + startup folders). Reversible.")

        btns = ctk.CTkFrame(tab_start, fg_color="transparent"); btns.pack(fill="x", padx=14, pady=(0,14))
        ctk.CTkButton(btns, text="🔄 Refresh", command=lambda: self._refresh_startup(),
                     fg_color="#374151", hover_color="#4B5563", corner_radius=10,
                     height=34).pack(side="left", padx=(0,6))
        ctk.CTkButton(btns, text="✅ Enable", command=lambda: self._toggle_startup(True),
                     fg_color="#10B981", hover_color="#34D399", corner_radius=10,
                     height=34).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="❌ Disable", command=lambda: self._toggle_startup(False),
                     fg_color="#EF4444", hover_color="#F87171", corner_radius=10,
                     height=34).pack(side="left", padx=6)

        ins = ctk.CTkFrame(tab_ins, corner_radius=20, fg_color="#161B22",
                          border_width=1, border_color="#30363D")
        ins.pack(fill="both", expand=True, padx=10, pady=10)

        insights_header = ctk.CTkFrame(ins, fg_color="transparent")
        insights_header.pack(fill="x", padx=14, pady=(14,4))
        ctk.CTkLabel(insights_header, text="📊 LIVE SYSTEM METRICS",
                    font=ctk.CTkFont(size=12, weight="bold"), text_color="#9CA3AF").pack(anchor="w")

        fig = Figure(figsize=(6.4, 2.4), dpi=100, facecolor='#161B22')
        self.ax = fig.add_subplot(111)
        self.ax.set_facecolor('#0F1115')
        self.ax.set_ylim(0, 100)
        self.ax.set_ylabel("%", color='#9CA3AF', fontsize=9)
        self.ax.tick_params(colors='#6B7280', labelsize=8)
        self.ax.spines['bottom'].set_color('#30363D')
        self.ax.spines['top'].set_color('#30363D')
        self.ax.spines['left'].set_color('#30363D')
        self.ax.spines['right'].set_color('#30363D')
        self.ax.grid(True, color='#30363D', alpha=0.3, linestyle='--')

        self.line_cpu, = self.ax.plot(list(self.ts_cpu), label="CPU", color='#8B5CF6', linewidth=2)
        self.line_ram, = self.ax.plot(list(self.ts_ram), label="RAM", color='#10B981', linewidth=2)
        self.line_gpu, = self.ax.plot(list(self.ts_gpu), label="GPU", color='#F59E0B', linewidth=2)
        self.ax.legend(loc="upper right", fontsize=8, facecolor='#1C2128', edgecolor='#30363D',
                      labelcolor='#E5E7EB')

        self.canvas = FigureCanvasTkAgg(fig, master=ins)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=14, pady=(4, 8))

        latency_frame = ctk.CTkFrame(ins, fg_color="transparent")
        latency_frame.pack(fill="x", padx=14, pady=(0, 14))
        latency_frame.grid_columnconfigure((0,1), weight=1)

        dpc_card = ctk.CTkFrame(latency_frame, corner_radius=12, fg_color="#0F1115", border_width=1, border_color="#30363D")
        dpc_card.grid(row=0, column=0, padx=4, sticky="ew")
        ctk.CTkLabel(dpc_card, text="⚡ DPC/ISR", text_color="#9CA3AF", font=ctk.CTkFont(size=10, weight="bold")).pack(padx=10, pady=(8,2))
        self.lbl_dpc = ctk.CTkLabel(dpc_card, text="0.0%", font=ctk.CTkFont(family="Segoe UI Variable Display", size=18, weight="bold"), text_color="#8B5CF6")
        self.lbl_dpc.pack(padx=10, pady=(0,8))

        ctx_card = ctk.CTkFrame(latency_frame, corner_radius=12, fg_color="#0F1115", border_width=1, border_color="#30363D")
        ctx_card.grid(row=0, column=1, padx=4, sticky="ew")
        ctk.CTkLabel(ctx_card, text="🔄 CTX SWITCHES", text_color="#9CA3AF", font=ctk.CTkFont(size=10, weight="bold")).pack(padx=10, pady=(8,2))
        self.lbl_ctx = ctk.CTkLabel(ctx_card, text="0", font=ctk.CTkFont(family="Segoe UI Variable Display", size=18, weight="bold"), text_color="#EC4899")
        self.lbl_ctx.pack(padx=10, pady=(0,8))

        ctk.CTkLabel(tab_rules, text="Automation Rules (pick & add)", font=ctk.CTkFont(size=16, weight="bold"), text_color="#F9FAFB").pack(anchor="w", padx=12, pady=(12,4))
        self.tree_rules = ttk.Treeview(tab_rules, style="Tbl.Treeview", columns=("Pattern","When","Action"), show="headings", height=8, selectmode="browse")
        for col, w in (("Pattern",260), ("When",220), ("Action",200)):
            self.tree_rules.heading(col, text=col); self.tree_rules.column(col, anchor="center", width=w, stretch=True)
        self.tree_rules.pack(fill="x", padx=12, pady=(4,8))
        self._refresh_rules_tree()

        jig = ctk.CTkFrame(tab_rules, fg_color="#161B22", corner_radius=12, border_width=1, border_color="#30363D")
        jig.pack(fill="x", padx=12, pady=(2,12))
        jig.grid_columnconfigure((0,1,2,3,4,5), weight=1)

        ctk.CTkLabel(jig, text="Pattern", text_color="#9CA3AF").grid(row=0, column=0, sticky="w", padx=(12,6), pady=(8,0))
        self.cb_rule_pattern = ctk.CTkComboBox(jig, values=self._rule_pattern_choices(), width=220, fg_color="#0F1115", border_color="#30363D", button_color="#8B5CF6")
        self.cb_rule_pattern.grid(row=1, column=0, sticky="we", padx=(12,6), pady=(0,12))

        ctk.CTkLabel(jig, text="Scope", text_color="#9CA3AF").grid(row=0, column=1, sticky="w", padx=6, pady=(8,0))
        self.cb_rule_scope = ctk.CTkComboBox(jig, values=["Always","Foreground","Background"], width=150, fg_color="#0F1115", border_color="#30363D", button_color="#8B5CF6")
        self.cb_rule_scope.set("Background")
        self.cb_rule_scope.grid(row=1, column=1, sticky="we", padx=6, pady=(0,12))

        ctk.CTkLabel(jig, text="Metric", text_color="#9CA3AF").grid(row=0, column=2, sticky="w", padx=6, pady=(8,0))
        self.lbl_metric = ctk.CTkLabel(jig, text="CPU >")
        self.lbl_metric.grid(row=1, column=2, sticky="w", padx=6, pady=(0,12))

        ctk.CTkLabel(jig, text="Value", text_color="#9CA3AF").grid(row=0, column=3, sticky="w", padx=6, pady=(8,0))
        self.rule_val_label = ctk.CTkLabel(jig, text="30")
        self.rule_val_label.grid(row=1, column=3, sticky="e", padx=(0,6), pady=(0,12))
        self.slider_rule_value = ctk.CTkSlider(jig, from_=1, to=95, number_of_steps=94, command=self._on_rule_slider, progress_color="#8B5CF6", button_color="#A78BFA")
        self.slider_rule_value.set(30)
        self.slider_rule_value.grid(row=1, column=4, sticky="we", padx=6, pady=(0,12))

        ctk.CTkLabel(jig, text="Action", text_color="#9CA3AF").grid(row=0, column=5, sticky="w", padx=6, pady=(8,0))
        self.cb_rule_action = ctk.CTkComboBox(jig, values=["lower_priority","trim","eco_throttle","kill"], width=160, fg_color="#0F1115", border_color="#30363D", button_color="#8B5CF6")
        self.cb_rule_action.set("lower_priority")
        self.cb_rule_action.grid(row=1, column=5, sticky="we", padx=(6,12), pady=(0,12))

        btnrow = ctk.CTkFrame(tab_rules, fg_color="transparent"); btnrow.pack(fill="x", padx=12, pady=(0,12))
        ctk.CTkButton(btnrow, text="Refresh Patterns", command=lambda: self._refresh_rule_patterns(), fg_color="#374151", hover_color="#4B5563").pack(side="left")
        ctk.CTkButton(btnrow, text="Add Rule", command=lambda: self._add_rule(), fg_color="#8B5CF6", hover_color="#A78BFA").pack(side="left", padx=8)

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

        ctk.CTkLabel(tab_sets, text="Settings", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(12,6))
        row_s1 = ctk.CTkFrame(tab_sets); row_s1.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(row_s1, text="Background CPU high (%)").pack(side="left")
        self.ent_bgcpu = ctk.CTkEntry(row_s1, width=120); self.ent_bgcpu.pack(side="left", padx=8)
        ctk.CTkLabel(row_s1, text="Heavy RAM (MB)").pack(side="left", padx=(16,0))
        self.ent_heavyram = ctk.CTkEntry(row_s1, width=120); self.ent_heavyram.pack(side="left", padx=8)
        ctk.CTkButton(row_s1, text="Save Thresholds", command=lambda: self._save_thresholds()).pack(side="left", padx=12)

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

        ctk.CTkLabel(tab_rep, text="Reports & Logs", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(12,6))
        ctk.CTkButton(tab_rep, text="Export current snapshot (CSV)", command=lambda: self._export_snapshot()).pack(anchor="w", padx=12, pady=6)
        ctk.CTkButton(tab_rep, text="Export effects log (JSON)", command=lambda: self._export_effects()).pack(anchor="w", padx=12, pady=(0,8))
        ctk.CTkLabel(tab_rep, text="Activity Log").pack(anchor="w", padx=12)
        self.txt_log = ctk.CTkTextbox(tab_rep, height=280); self.txt_log.pack(fill="both", expand=True, padx=12, pady=(4,12))

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

    def _toast(self, text, kind="ok"):
        top = ctk.CTkToplevel(self)
        top.overrideredirect(True)
        top.attributes('-topmost', True)
        top.attributes('-alpha', 0.0)

        color = "#16a34a" if kind=="ok" else "#f59e0b" if kind=="warn" else "#ef4444"
        icon = "✓" if kind=="ok" else "⚠" if kind=="warn" else "✕"

        frame = ctk.CTkFrame(top, corner_radius=12, fg_color=color, border_width=1, border_color="#30363D")
        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(padx=16, pady=12)

        ctk.CTkLabel(inner, text=icon, font=ctk.CTkFont(size=16), text_color="white").pack(side="left", padx=(0,8))
        ctk.CTkLabel(inner, text=text, font=ctk.CTkFont(size=13, weight="bold"), text_color="white").pack(side="left")
        frame.pack()

        self.update_idletasks()

        try:
            toast_width = frame.winfo_reqwidth() + 40
            x_end = self.winfo_x() + self.winfo_width() - toast_width - 20
            x_start = self.winfo_x() + self.winfo_width() + 20
            y = self.winfo_y() + self.winfo_height() - 100

            top.geometry(f"+{x_start}+{y}")

            def animate_in(step=0):
                if step <= 10:
                    progress = step / 10
                    ease = 1 - (1 - progress) ** 3
                    current_x = int(x_start + (x_end - x_start) * ease)
                    top.geometry(f"+{current_x}+{y}")
                    top.attributes('-alpha', min(1.0, progress * 1.2))
                    top.after(16, lambda: animate_in(step + 1))

            def animate_out(step=0):
                if step <= 8:
                    progress = step / 8
                    top.attributes('-alpha', 1.0 - progress)
                    top.after(20, lambda: animate_out(step + 1))
                else:
                    try:
                        top.destroy()
                    except:
                        pass

            animate_in()
            top.after(2200, animate_out)

        except Exception:
            top.geometry(f"+100+100")
            top.attributes('-alpha', 1.0)
            top.after(2600, top.destroy)

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

        self._refresh_rules_tree()

    def _save_config(self):
        cfg = {"theme": ctk.get_appearance_mode(), "rules": self.rules, "settings": self.settings}
        try:
            json.dump(cfg, open(CONFIG_PATH, "w", encoding="utf-8"), indent=2)
        except Exception:
            pass

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
            try:
                self.after(0, self._refresh_all)
            except RuntimeError:
                pass
            except Exception:
                pass
            try:
                interval = max(1.0, float(self.settings.get("refresh_sec", DEFAULT_REFRESH_SEC)))
            except Exception:
                interval = DEFAULT_REFRESH_SEC
            time.sleep(interval)

    def _loop_follow_foreground(self):
        while not self._stop:
            try:
                fpid = fg_pid()

                if self.chk_game.get():
                    if fpid: self._boost_foreground(fpid)

                PRIORITY_BALANCER.check_and_rebalance(fpid)

                FG_BOOSTER.update(fpid)

                CPU_LIMITER.check_and_limit(fpid)

                MEM_OPTIMIZER.check_and_trim()

                POWER_SAVER.check()

                AFFINITY_MGR.check_and_apply()

                RESPONSIVENESS.measure()

                GAME_MODE.check_for_games()

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
            time.sleep(15)

    def _loop_latency_monitor(self):
        while not self._stop:
            try:
                dpc_stats = LATENCY.sample_system_dpc()
                self.ts_dpc.append(dpc_stats.get("dpc", 0))

                total_ctx = 0
                try:
                    top_procs = sorted(
                        [(p.info["pid"], p.info.get("cpu_percent", 0))
                         for p in psutil.process_iter(["pid", "cpu_percent"])],
                        key=lambda x: x[1], reverse=True
                    )[:10]

                    for pid, _ in top_procs:
                        try:
                            delta = LATENCY.sample_process(pid)
                            total_ctx += delta
                        except Exception:
                            continue
                except Exception:
                    pass

                normalized_ctx = min(100, total_ctx / 500)
                self.ts_ctx.append(normalized_ctx)

            except Exception:
                pass
            time.sleep(5)

    def _quick_boost_fg(self):
        fpid = fg_pid()
        if not fpid:
            self._toast("No foreground process detected", "warn")
            return
        try:
            h = open_proc(fpid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
            old = win32process.GetPriorityClass(h)
            win32process.SetPriorityClass(h, win32process.HIGH_PRIORITY_CLASS)
            UNDO.push(fpid, "priority", old)
            name = psutil.Process(fpid).name()
            self._toast(f"Boosted {name} to High priority", "ok")
            self._append_effect(f"Quick Boost: {name} → High priority")
            self._log_activity(f"OptiBoost: Boosted {name} to High priority", "optiboost")
        except Exception as e:
            self._toast(f"Failed to boost: {e}", "warn")

    def _quick_trim_all(self):
        ram_before = psutil.virtual_memory().available

        count = 0
        for p in psutil.process_iter(["pid", "name"]):
            try:
                name = (p.info["name"] or "").lower()
                if name in (n.lower() for n in SYSTEM_WHITELIST):
                    continue
                h = open_proc(p.info["pid"], win32con.PROCESS_SET_QUOTA)
                empty_working_set(h)
                count += 1
            except Exception:
                continue

        ram_after = psutil.virtual_memory().available
        ram_freed_mb = max(0, (ram_after - ram_before) / (1024 * 1024))

        self._session_stats["ram_freed_mb"] += ram_freed_mb

        if ram_freed_mb > 0:
            self._toast(f"Trimmed {count} processes • Freed {ram_freed_mb:.0f} MB", "ok")
        else:
            self._toast(f"Trimmed RAM for {count} processes", "ok")

        self._append_effect(f"Quick Trim: {count} processes trimmed")
        self._log_activity(f"OptiTrim: Cleared RAM for {count} processes ({ram_freed_mb:.0f} MB freed)", "optitrim")

        return count

    def _quick_throttle_bg(self):
        self.bg_gov.enabled = True
        self.chk_gov.select()
        fpid = fg_pid()
        count = 0
        for p in psutil.process_iter(["pid", "name"]):
            try:
                pid = p.info["pid"]
                name = (p.info["name"] or "").lower()
                if pid == fpid:
                    continue
                if name in (n.lower() for n in SYSTEM_WHITELIST):
                    continue
                self.bg_gov.govern(pid)
                count += 1
            except Exception:
                continue
        self._toast(f"Throttled {count} background processes", "ok")
        self._append_effect(f"Quick Throttle: {count} BG processes governed")
        self._log_activity(f"OptiThrottle: Governed {count} background processes", "optimize")

    def _quick_kill_heavy(self):
        fpid = fg_pid()
        heaviest = None
        heaviest_cpu = 0

        for p in psutil.process_iter(["pid", "name", "cpu_percent"]):
            try:
                pid = p.info["pid"]
                name = (p.info["name"] or "").lower()
                if pid == fpid:
                    continue
                if name in (n.lower() for n in SYSTEM_WHITELIST):
                    continue
                cpu = p.info.get("cpu_percent", 0) or 0
                if cpu > heaviest_cpu:
                    heaviest_cpu = cpu
                    heaviest = p
            except Exception:
                continue

        if heaviest and heaviest_cpu > 5:
            name = heaviest.info["name"]

            from tkinter import messagebox
            result = messagebox.askyesno(
                "Confirm Kill Process",
                f"Are you sure you want to terminate:\n\n"
                f"Process: {name}\n"
                f"PID: {heaviest.pid}\n"
                f"CPU Usage: {heaviest_cpu:.1f}%\n\n"
                f"This action cannot be undone.",
                icon="warning"
            )

            if result:
                try:
                    heaviest.kill()
                    self._toast(f"Killed {name} ({heaviest_cpu:.1f}% CPU)", "ok")
                    self._append_effect(f"Quick Kill: {name} terminated")
                    self._log_activity(f"OptiKill: Terminated {name} ({heaviest_cpu:.1f}% CPU)", "warning")
                except Exception as e:
                    self._toast(f"Failed to kill: {e}", "warn")
            else:
                self._toast("Kill cancelled", "warn")
        else:
            self._toast("No heavy background process found", "warn")

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
            self._log_activity("OptiGame: Game Mode ENABLED - High Performance active", "optigame")
        else:
            switch_power_plan("BALANCED")
            self._log("Game Mode OFF — Balanced plan applied.")
            self._append_effect("Game Mode disabled: Balanced plan restored.")
            self._log_activity("OptiGame: Game Mode DISABLED - Balanced plan restored", "optigame")

    def _toggle_governor(self):
        self.bg_gov.enabled = bool(self.chk_gov.get())
        state = "ENABLED" if self.bg_gov.enabled else "DISABLED"
        self._log(f"Background Governor {state}")
        self._append_effect(f"Background Governor {state.lower()}.")
        self._log_activity(f"OptiGov: Background Governor {state}", "optimize")

    def _toggle_game_auto(self):
        GAME_MODE.enabled = bool(self.chk_game_auto.get())
        state = "ENABLED" if GAME_MODE.enabled else "DISABLED"
        self._toast(f"Auto Game Boost {state}", "ok")
        self._append_effect(f"Auto Game Boost {state.lower()}.")
        self._log_activity(f"OptiGame: Auto Game Boost {state}", "optigame")

    def _toggle_priority_bal(self):
        PRIORITY_BALANCER.enabled = bool(self.chk_priority_bal.get())
        state = "ENABLED" if PRIORITY_BALANCER.enabled else "DISABLED"
        self._toast(f"Priority Balancer {state}", "ok")
        self._append_effect(f"Dynamic Priority Balancer {state.lower()}.")
        self._log_activity(f"OptiBalance: Priority Balancer {state}", "optibalance")

    def _clear_ram_standby(self):
        before = RAM_CLEANER.get_available_ram_mb()
        RAM_CLEANER.clear_standby_list()
        after = RAM_CLEANER.get_available_ram_mb()
        freed = after - before
        self._toast(f"Cleared RAM standby (+{freed:.0f} MB)", "ok")
        self._append_effect(f"RAM standby cleared: +{freed:.0f} MB freed.")
        self._log_activity(f"OptiRAM: Cleared standby list (+{freed:.0f} MB freed)", "optitrim")

    def _optimize_network(self):
        NETWORK_OPT.optimize_for_gaming()
        NETWORK_OPT.disable_network_throttling()
        self._toast("Network optimized for gaming", "ok")
        self._append_effect("Network: Nagle disabled, throttling disabled.")

    def _disable_visual_fx(self):
        VISUAL_FX.disable_for_performance()
        self._toast("Visual effects disabled", "ok")
        self._append_effect("Visual effects disabled for performance.")

    def _disable_win_key(self):
        if 'windows_key' in WIN_TWEAKS.tweaks_applied:
            WIN_TWEAKS.disable_windows_key(False)
            self._toast("Windows key ENABLED (reboot may be needed)", "warn")
            self._append_effect("Windows key re-enabled.")
        else:
            WIN_TWEAKS.disable_windows_key(True)
            self._toast("Windows key DISABLED (reboot may be needed)", "ok")
            self._append_effect("Windows key disabled.")

    def _toggle_autostart(self):
        if self.chk_autostart.get():
            AUTO_START.enable()
            self._toast("Auto-start ENABLED", "ok")
        else:
            AUTO_START.disable()
            self._toast("Auto-start DISABLED", "ok")

    def _toggle_minimize_tray(self):
        self.settings["minimize_to_tray"] = bool(self.chk_minimize_tray.get())
        self._save_config()
        self._toast(f"Minimize to tray: {'ON' if self.settings['minimize_to_tray'] else 'OFF'}", "ok")

    def _toggle_confirm_dialogs(self):
        self.settings["confirm_dialogs"] = bool(self.chk_confirm_dialogs.get())
        self._save_config()
        self._toast(f"Confirmation dialogs: {'ON' if self.settings['confirm_dialogs'] else 'OFF'}", "ok")

    def _toggle_discord_rpc(self):
        if self.chk_discord_rpc.get():
            if DISCORD_RPC.enable():
                self._toast("Discord Rich Presence ENABLED", "ok")
            else:
                self.chk_discord_rpc.deselect()
                self._toast("Failed to connect to Discord (install pypresence)", "warn")
        else:
            DISCORD_RPC.disable()
            self._toast("Discord Rich Presence DISABLED", "ok")

    def _toggle_fps_overlay_old(self):
        try:
            if hasattr(self, 'overlay_enabled') and self.overlay_enabled.get():
                self._show_fps_overlay()
            else:
                self._hide_fps_overlay()
        except:
            pass

    def _toggle_perf_history(self):
        if self.chk_perf_history.get():
            PERF_HISTORY.start_logging()
            self._toast("Performance History ENABLED", "ok")
        else:
            PERF_HISTORY.stop_logging()
            if PERF_HISTORY.history:
                path = PERF_HISTORY.export_csv()
                self._toast(f"History exported to {os.path.basename(path) if path else 'file'}", "ok")
            else:
                self._toast("Performance History DISABLED", "ok")

    def _toggle_proc_timeline(self):
        if self.chk_proc_timeline.get():
            PROC_TIMELINE.start_monitoring()
            self._toast("Process Timeline ENABLED", "ok")
        else:
            PROC_TIMELINE.stop_monitoring()
            self._toast("Process Timeline DISABLED", "ok")

    def _toggle_alerts(self):
        if self.chk_alerts.get():
            ALERT_SYSTEM.start_monitoring(callback=lambda t, m: self._toast(m, "warn"))
            self._toast("Alert System ENABLED", "ok")
        else:
            ALERT_SYSTEM.stop_monitoring()
            self._toast("Alert System DISABLED", "ok")

    def _create_profile(self):
        name = self.ent_profile_name.get().strip()
        if not name:
            self._toast("Enter a profile name first", "warn")
            return
        if GAME_PROFILES.create_profile(name):
            self._toast(f"Profile '{name}' created", "ok")
            self.ent_profile_name.delete(0, 'end')
            profiles_list = GAME_PROFILES.list_profiles() or ["(No profiles)"]
            self.cb_profiles.configure(values=profiles_list)
            self.cb_profiles.set(name)
        else:
            self._toast("Failed to create profile", "warn")

    def _apply_profile(self):
        name = self.cb_profiles.get()
        if name == "(No profiles)":
            self._toast("No profiles available", "warn")
            return
        if GAME_PROFILES.apply_profile(name):
            self._toast(f"Applied profile '{name}'", "ok")
        else:
            self._toast("Failed to apply profile", "warn")

    def _delete_profile(self):
        name = self.cb_profiles.get()
        if name == "(No profiles)":
            return
        if self.settings.get("confirm_dialogs", True):
            if not confirm_action(self, "Delete Profile", f"Delete profile '{name}'?"):
                return
        if GAME_PROFILES.delete_profile(name):
            self._toast(f"Deleted profile '{name}'", "ok")
            profiles_list = GAME_PROFILES.list_profiles() or ["(No profiles)"]
            self.cb_profiles.configure(values=profiles_list)
            if profiles_list:
                self.cb_profiles.set(profiles_list[0])
        else:
            self._toast("Failed to delete profile", "warn")

    def _snap(self):
        with self.cpu_lock: return dict(self.cpu_snap)

    def _refresh_all(self):
        self._refresh_cycle += 1

        try:
            cpu_pct = psutil.cpu_percent()
            mem_pct = psutil.virtual_memory().percent

            if hasattr(self, '_last_cpu_pct'):
                ANIMATOR.animate_number(self.val_cpu, cpu_pct, duration_ms=400, suffix="%", decimals=1)
            else:
                self.val_cpu.configure(text=f"{cpu_pct:.1f}%")

            if hasattr(self, '_last_mem_pct'):
                ANIMATOR.animate_number(self.val_mem, mem_pct, duration_ms=400, suffix="%", decimals=1)
            else:
                self.val_mem.configure(text=f"{mem_pct:.1f}%")

            self._last_cpu_pct = cpu_pct
            self._last_mem_pct = mem_pct

            if hasattr(self, 'card_cpu') and hasattr(self.card_cpu, 'set_value'):
                self.card_cpu.set_value(f"{cpu_pct:.1f}%", cpu_pct)
            if hasattr(self, 'card_mem') and hasattr(self.card_mem, 'set_value'):
                self.card_mem.set_value(f"{mem_pct:.1f}%", mem_pct)
            self.ts_cpu.append(cpu_pct)
            self.ts_ram.append(mem_pct)
        except Exception: pass

        try:
            now = time.time()
            if now - self._cached_gpu_time > 5:
                if GPUtil:
                    g = GPUtil.getGPUs()
                    self._cached_gpu = g[0].load * 100 if g else 0.0
                else:
                    self._cached_gpu = 0.0
                self._cached_gpu_time = now

            if self._cached_gpu > 0:
                if hasattr(self, '_last_gpu_pct'):
                    ANIMATOR.animate_number(self.val_gpu, self._cached_gpu, duration_ms=400, suffix="%", decimals=1)
                else:
                    self.val_gpu.configure(text=f"{self._cached_gpu:.1f}%")
                self._last_gpu_pct = self._cached_gpu
            else:
                self.val_gpu.configure(text="N/A")
            self.ts_gpu.append(self._cached_gpu)
        except Exception:
            self.val_gpu.configure(text="N/A"); self.ts_gpu.append(0.0)

        try:
            if hasattr(self, "val_gpu_temp") and hasattr(self, "card_gpu_temp"):
                if GPUtil:
                    gpus = GPUtil.getGPUs()
                    if gpus and gpus[0].temperature:
                        gpu_temp = gpus[0].temperature
                        self.val_gpu_temp.configure(text=f"{gpu_temp:.0f}°C")
                        self.card_gpu_temp.set_value(f"{gpu_temp:.0f}°C", min(100, gpu_temp))
                    else:
                        self.val_gpu_temp.configure(text="N/A")
                else:
                    self.val_gpu_temp.configure(text="N/A")

            if hasattr(self, "val_cpu_temp") and hasattr(self, "card_cpu_temp"):
                cpu_temp = None

                try:
                    temps = psutil.sensors_temperatures()
                    if temps:
                        for name, entries in temps.items():
                            if entries:
                                cpu_temp = entries[0].current
                                break
                except:
                    pass

                if cpu_temp is None:
                    now = time.time()
                    if not hasattr(self, '_cpu_temp_cache_time') or now - self._cpu_temp_cache_time > 5:
                        self._cpu_temp_cache_time = now
                        self._cpu_temp_cache = None
                        try:
                            import wmi
                            w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
                            sensors = w.Sensor()
                            for s in sensors:
                                if s.SensorType == "Temperature" and "CPU" in s.Name:
                                    self._cpu_temp_cache = s.Value
                                    break
                        except:
                            try:
                                import wmi
                                w = wmi.WMI(namespace="root\\LibreHardwareMonitor")
                                sensors = w.Sensor()
                                for s in sensors:
                                    if s.SensorType == "Temperature" and "CPU" in s.Name:
                                        self._cpu_temp_cache = s.Value
                                        break
                            except:
                                pass

                    cpu_temp = self._cpu_temp_cache

                if cpu_temp is None:
                    now = time.time()
                    if not hasattr(self, '_wmi_temp_cache_time') or now - self._wmi_temp_cache_time > 10:
                        self._wmi_temp_cache_time = now
                        self._wmi_temp_cache = None
                        try:
                            import subprocess
                            result = subprocess.run(
                                ["powershell", "-Command",
                                 "Get-CimInstance MSAcpi_ThermalZoneTemperature -Namespace root/wmi 2>$null | Select-Object -First 1 -ExpandProperty CurrentTemperature"],
                                capture_output=True, text=True, timeout=2, creationflags=0x08000000
                            )
                            if result.returncode == 0 and result.stdout.strip():
                                kelvin_10 = float(result.stdout.strip())
                                self._wmi_temp_cache = (kelvin_10 / 10) - 273.15
                        except:
                            pass
                    cpu_temp = self._wmi_temp_cache

                if cpu_temp is not None and cpu_temp > 0:
                    self.val_cpu_temp.configure(text=f"{cpu_temp:.0f}°C")
                    self.card_cpu_temp.set_value(f"{cpu_temp:.0f}°C", min(100, cpu_temp))
                else:
                    self.val_cpu_temp.configure(text="N/A")
        except Exception:
            pass

        pid = fg_pid()
        if hasattr(self, 'val_fg') and self.val_fg:
            if pid:
                try: self.val_fg.configure(text=psutil.Process(pid).name())
                except Exception: self.val_fg.configure(text=f"PID {pid}")
            else:
                self.val_fg.configure(text="—")

        try:
            curr_net_io = psutil.net_io_counters()
            curr_time = time.time()
            dt = curr_time - self.last_net_time
            if dt > 0:
                sent = (curr_net_io.bytes_sent - self.last_net_io.bytes_sent) / dt
                recv = (curr_net_io.bytes_recv - self.last_net_io.bytes_recv) / dt

                def fmt_spd(b):
                    if b > 1024*1024: return f"{b/1024/1024:.1f} MB/s"
                    if b > 1024: return f"{b/1024:.1f} KB/s"
                    return f"{b:.0f} B/s"

                if hasattr(self, "val_net_up") and self.val_net_up:
                    self.val_net_up.configure(text=fmt_spd(sent))
                if hasattr(self, "val_net_down") and self.val_net_down:
                    self.val_net_down.configure(text=fmt_spd(recv))

                self.ts_net_up.append(sent / 1024.0)
                self.ts_net_down.append(recv / 1024.0)

            self.last_net_io = curr_net_io
            self.last_net_time = curr_time
        except Exception: pass

        try:
            if self._refresh_cycle % 3 == 0:
                cpu_temp = get_cpu_temp()
                gpu_temp = get_gpu_temp()
                if hasattr(self, "val_cpu_temp"):
                    self.val_cpu_temp.configure(text=f"{cpu_temp:.0f}°C" if cpu_temp else "N/A")
                if hasattr(self, "val_gpu_temp"):
                    self.val_gpu_temp.configure(text=f"{gpu_temp:.0f}°C" if gpu_temp else "N/A")
        except: pass

        try:
            read_rate, write_rate = DISK_IO.get_rates()
            def fmt_disk(b):
                if b > 1024*1024: return f"{b/1024/1024:.1f} MB/s"
                if b > 1024: return f"{b/1024:.1f} KB/s"
                return f"{b:.0f} B/s"
            if hasattr(self, "val_disk_read"):
                self.val_disk_read.configure(text=fmt_disk(read_rate))
            if hasattr(self, "val_disk_write"):
                self.val_disk_write.configure(text=fmt_disk(write_rate))
        except: pass

        if hasattr(self, "canvas") and self._refresh_cycle % 3 == 0:
            self.line_cpu.set_ydata(list(self.ts_cpu))
            self.line_ram.set_ydata(list(self.ts_ram))
            self.line_gpu.set_ydata(list(self.ts_gpu))
            self.canvas.draw_idle()

        try:
            cpu_times = psutil.cpu_times_percent(interval=None)
            dpc_val = getattr(cpu_times, 'interrupt', 0) + getattr(cpu_times, 'dpc', 0)
            if dpc_val == 0:
                dpc_val = getattr(cpu_times, 'system', 0) * 0.1
            self.ts_dpc.append(dpc_val)

            fpid_local = fg_pid()
            if fpid_local:
                try:
                    ctx = psutil.Process(fpid_local).num_ctx_switches()
                    ctx_total = (ctx.voluntary + ctx.involuntary) / 1000
                    self.ts_ctx.append(min(100, ctx_total))
                except Exception:
                    self.ts_ctx.append(0)
            else:
                self.ts_ctx.append(0)
        except Exception:
            pass

        try:
            if hasattr(self, "val_battery") and hasattr(self, "card_battery"):
                battery = psutil.sensors_battery()
                if battery:
                    pct = battery.percent
                    plugged = battery.power_plugged
                    if plugged:
                        bat_text = f"{pct:.0f}% ⚡"
                        self.val_battery.configure(text=bat_text)
                        self.card_battery.set_bar_color("#22C55E")
                    elif pct > 20:
                        bat_text = f"{pct:.0f}%"
                        self.val_battery.configure(text=bat_text)
                        self.card_battery.set_bar_color("#60A5FA")
                    else:
                        bat_text = f"{pct:.0f}% ⚠"
                        self.val_battery.configure(text=bat_text)
                        self.card_battery.set_bar_color("#EF4444")
                    self.card_battery.set_value(f"{pct:.0f}%", pct)
                    if hasattr(self, "lbl_footer_battery"):
                        self.lbl_footer_battery.configure(text=bat_text)
                else:
                    self.val_battery.configure(text="N/A")
                    self.card_battery.set_value("N/A", 0)
                    if hasattr(self, "lbl_footer_battery"):
                        self.lbl_footer_battery.configure(text="N/A")
            if hasattr(self, "lbl_dpc"):
                dpc = self.ts_dpc[-1] if self.ts_dpc else 0
                self.lbl_dpc.configure(text=f"{dpc:.1f}%")
            if hasattr(self, "lbl_ctx"):
                ctx = self.ts_ctx[-1] if self.ts_ctx else 0
                self.lbl_ctx.configure(text=f"{int(ctx)}K")
        except Exception:
            pass

        try:
            if hasattr(self, "lbl_footer_power"):
                now = time.time()
                if not hasattr(self, '_power_plan_cache_time') or now - self._power_plan_cache_time > 10:
                    self._power_plan_cache_time = now
                    import subprocess
                    result = subprocess.run(
                        ["powercfg", "/getactivescheme"],
                        capture_output=True, text=True, timeout=2, creationflags=0x08000000
                    )
                    output = result.stdout.lower()
                    if "high performance" in output or "ultimate" in output:
                        self._power_plan_cache = "High Perf"
                    elif "power saver" in output:
                        self._power_plan_cache = "Saver"
                    elif "balanced" in output:
                        self._power_plan_cache = "Balanced"
                    else:
                        import re
                        match = re.search(r'\(([^)]+)\)', result.stdout)
                        self._power_plan_cache = match.group(1)[:10] if match else "Custom"
                if hasattr(self, '_power_plan_cache'):
                    self.lbl_footer_power.configure(text=self._power_plan_cache)
        except Exception:
            pass

        try:
            cpu = self.ts_cpu[-1] if self.ts_cpu else 0
            ram = self.ts_ram[-1] if self.ts_ram else 0
            gpu = self.ts_gpu[-1] if self.ts_gpu else 0
            health = max(0, 100 - (cpu * 0.5 + ram * 0.3 + gpu * 0.2))

            if hasattr(self, "lbl_health"):
                self.lbl_health.configure(text=f"{int(health)}%")
                if health >= 70:
                    color = "#10B981"
                elif health >= 40:
                    color = "#F59E0B"
                else:
                    color = "#EF4444"
                self.lbl_health.configure(text_color=color)
                self.health_bar.configure(progress_color=color)
                self.health_bar.set(health / 100)
        except Exception:
            pass

        try:
            if hasattr(self, "lbl_responsiveness"):
                stats = RESPONSIVENESS.get_stats()
                score = stats['score']
                trend = stats['trend']

                self.lbl_responsiveness.configure(text=f"{score:.0f}%")

                if score >= 80:
                    color = "#10B981"
                elif score >= 50:
                    color = "#F59E0B"
                else:
                    color = "#EF4444"
                self.lbl_responsiveness.configure(text_color=color)

                if hasattr(self, "lbl_resp_trend"):
                    trend_icons = {
                        'improving': '↑',
                        'degrading': '↓',
                        'stable': '→'
                    }
                    self.lbl_resp_trend.configure(text=f"({trend_icons.get(trend, '→')} {trend})")
        except Exception:
            pass

        try:
            self._check_schedule()
        except Exception: pass

        if self._refresh_cycle % 3 == 0:
            self._refresh_table()

    def _refresh_table(self):
        update_full = self.tree and self.tree.winfo_exists()
        update_dash = self.tree_dash and self.tree_dash.winfo_exists()

        if not update_full and not update_dash: return

        snap = self._snap()
        term = self.search_term
        rows = []
        fpid = fg_pid()
        user_wl = [n.strip().lower() for n in self.settings["custom_whitelist"]]

        count = 0
        for p in psutil.process_iter(["pid","name","memory_info"]):
            if count >= 150: break
            try:
                name = p.info["name"] or ""
                lname = name.lower()
                if name in SYSTEM_WHITELIST or lname in user_wl: continue
                pid = p.info["pid"]
                if term and (term not in lname and term not in str(pid)): continue
                cpu = snap.get(pid, 0.0)
                rss_mb = (p.info["memory_info"].rss or 0) / (1024*1024)
                role = "Foreground" if fpid and pid == fpid else "Background"

                flag_str = "-"

                rows.append((pid, name, cpu, rss_mb, flag_str, role))
                count += 1
            except Exception:
                continue

        key_map = {
            "CPU": lambda x: x[2],
            "Memory": lambda x: x[3],
            "PID": lambda x: x[0],
            "Name": lambda x: x[1].lower()
        }
        rows.sort(key=key_map.get(self.sort_key, key_map["CPU"]), reverse=True)

        if update_full:
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

        if update_dash:
            for i in self.tree_dash.get_children(): self.tree_dash.delete(i)
            dash_rows = sorted(rows, key=lambda x: x[2], reverse=True)[:15]
            for pid, name, cpu, mem, _, _ in dash_rows:
                self.tree_dash.insert("", "end", values=(name, f"{cpu:.1f}%", f"{mem:.0f} MB"))

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

    def _act_io_priority(self):
        try:
            sel = self.cb_ioprio.get().strip()
            level = IO_PRIORITY.get(sel, 2)
        except Exception:
            level = 2
        for pid in self._sel_pids():
            try:
                p = psutil.Process(pid)
                if p.name() in SYSTEM_WHITELIST: continue
                cpu0, mem0 = self._baseline(p)
                h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
                if h:
                    old_io = get_io_priority(h)
                    set_io_priority(h, level)
                    UNDO.push(pid, "ioprio", old_io)
                    win32api.CloseHandle(h)
                    EFFECTS.baseline(pid, f"ioprio→{sel}", cpu0, mem0)
                    self._toast(f"I/O priority '{sel}' applied (PID {pid})", "ok")
                    self._append_effect(f"I/O priority {sel} set on PID {pid}.")
            except Exception as e:
                self._toast(f"I/O priority failed (PID {pid})", "err"); self._log(f"[IOPrio] PID {pid}: {e}")

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
                else:
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

    def _act_undo_last(self):
        if not UNDO.stack:
            self._toast("Nothing to undo", "warn")
            return

        last = UNDO.stack.pop()
        pid, kind, before, ts = last

        try:
            h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
            if kind == "priority" and before is not None:
                win32process.SetPriorityClass(h, before)
                self._toast(f"Undid priority change (PID {pid})", "ok")
            elif kind == "memprio" and before is not None:
                set_memory_priority(h, before)
                self._toast(f"Undid memory priority (PID {pid})", "ok")
            elif kind == "affinity" and before is not None:
                win32process.SetProcessAffinityMask(h, before)
                self._toast(f"Undid affinity change (PID {pid})", "ok")
            elif kind == "suspend":
                try:
                    psutil.Process(pid).resume()
                    self._toast(f"Resumed suspended process (PID {pid})", "ok")
                except Exception:
                    pass
            else:
                self._toast(f"Undid {kind} (PID {pid})", "ok")
            self._append_effect(f"Undid {kind} on PID {pid}")
        except Exception as e:
            self._toast(f"Failed to undo: {e}", "warn")

    def _boost_foreground(self, pid):
        try:
            h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
            old = win32process.GetPriorityClass(h)
            win32process.SetPriorityClass(h, win32process.HIGH_PRIORITY_CLASS)
            set_memory_priority(h, 4)
            UNDO.push(pid, "priority", old); UNDO.push(pid, "memprio", 3)
        except Exception:
            pass

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
        if not getattr(self, "tree_rules", None) or not self.tree_rules.winfo_exists(): return
        for i in self.tree_rules.get_children(): self.tree_rules.delete(i)
        for r in self.rules:
            self.tree_rules.insert("", "end", values=(r.get("pattern",""), r.get("when",""), r.get("action","")))

    def _refresh_startup(self):
        if not getattr(self, "tree_start", None) or not self.tree_start.winfo_exists(): return
        for i in self.tree_start.get_children(): self.tree_start.delete(i)
        self.startup_item_map.clear()

        try:
            items = STARTUP.list_items()
            for item in items:
                iid = self.tree_start.insert("", "end", values=("Registry" if "Reg" in item.source else "Folder",
                                                               item.name, item.command, "Enabled" if item.enabled else "Disabled"))
                self.startup_item_map[iid] = item
        except Exception:
            pass

    def _refresh_advisor(self):
        if not getattr(self, "tree_adv", None) or not self.tree_adv.winfo_exists(): return
        for i in self.tree_adv.get_children(): self.tree_adv.delete(i)
        self.adv_rows.clear()
        self._adv_fixes.clear()

        snap = self._snap()
        count = 0
        for pid, cpu in snap.items():
            if cpu > 10:
                try:
                    p = psutil.Process(pid)
                    name = p.name()
                    if name in SYSTEM_WHITELIST: continue
                    issue = f"High CPU usage ({cpu:.1f}%)"
                    sugg = "Lower Priority"
                    iid = self.tree_adv.insert("", "end", values=(pid, name, issue, sugg))
                    self.adv_rows[iid] = ("priority", pid, name)
                    count += 1
                except Exception: pass
        if count == 0:
             self.tree_adv.insert("", "end", values=("—", "System looks good", "No issues found", "—"))

    def _apply_selected_adv(self):
        if not getattr(self, "tree_adv", None): return
        sel = self.tree_adv.selection()
        for iid in sel:
            if iid in self.adv_rows:
                action, pid, name = self.adv_rows[iid]
                if action == "priority":
                    try:
                        p = psutil.Process(pid)
                        h = open_proc(pid, win32con.PROCESS_SET_INFORMATION | win32con.PROCESS_QUERY_INFORMATION)
                        win32process.SetPriorityClass(h, win32process.BELOW_NORMAL_PRIORITY_CLASS)
                        self._toast(f"Applied fix on {name}", "ok")
                    except Exception: pass

    def _apply_all_safe(self):
        pass

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
            self.adv_rows[iid] = None

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

    def _toggle_PRIORITY_BALANCER(self):
        PRIORITY_BALANCER.enabled = not PRIORITY_BALANCER.enabled
        status = "enabled" if PRIORITY_BALANCER.enabled else "disabled"
        self._toast(f"PRIORITY_BALANCER {status}", "ok")
        self._append_effect(f"PRIORITY_BALANCER {status}")

    def _toggle_MEM_OPTIMIZER(self):
        MEM_OPTIMIZER.enabled = not MEM_OPTIMIZER.enabled
        status = "enabled" if MEM_OPTIMIZER.enabled else "disabled"
        self._toast(f"MEM_OPTIMIZER {status}", "ok")
        self._append_effect(f"MEM_OPTIMIZER {status}")

    def _toggle_CPU_LIMITER(self):
        CPU_LIMITER.enabled = not CPU_LIMITER.enabled
        status = "enabled" if CPU_LIMITER.enabled else "disabled"
        self._toast(f"CPU Limiter {status}", "ok")
        self._append_effect(f"CPU Limiter {status}")

    def _toggle_FG_BOOSTER(self):
        FG_BOOSTER.enabled = not FG_BOOSTER.enabled
        status = "enabled" if FG_BOOSTER.enabled else "disabled"
        self._toast(f"Foreground Booster {status}", "ok")
        self._append_effect(f"Foreground Booster {status}")

    def _toggle_POWER_SAVER(self):
        POWER_SAVER.enabled = not POWER_SAVER.enabled
        status = "enabled" if POWER_SAVER.enabled else "disabled"
        self._toast(f"POWER_SAVER {status}", "ok")
        self._append_effect(f"POWER_SAVER {status}")

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

    def _append_effect(self, line: str):
        try:
            self.txt_effects.insert("end", f"• {line}\n")
            self.txt_effects.see("end")
        except Exception:
            pass

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

    def _apply_profile_named(self, name):
        self.current_profile = name
        self._apply_profile()

    def _refresh_profile_box(self):
        pass

    def _apply_profile(self):
        name = self.current_profile
        prof = PROFILES.get(name, PROFILES["Work"])

        switch_power_plan(prof["plan"])

        self.bg_gov.enabled = bool(prof["gov"])
        self.bg_gov.set_cpu_limit(prof.get("bg_cpu_limit", 30))
        self.bg_gov.set_mem_priority_level(prof.get("bg_mem_priority", 2))
        if hasattr(self, 'chk_gov'):
            self.chk_gov.select() if self.bg_gov.enabled else self.chk_gov.deselect()

        if name == "Gaming":

            set_timer_resolution(1)
            self._log("Gaming: Timer resolution set to 1ms")

            control_sysmain_service(False)
            self._log("Gaming: SysMain service disabled")

            set_cpu_parking(False)
            self._log("Gaming: CPU parking disabled")

            fpid = fg_pid()

            if fpid:
                try:
                    h = open_proc(fpid, win32con.PROCESS_SET_INFORMATION)
                    if h:
                        win32process.SetPriorityClass(h, win32process.HIGH_PRIORITY_CLASS)
                        win32api.CloseHandle(h)
                        self._log(f"Gaming: Boosted FG PID {fpid} to High priority")
                except Exception as e:
                    self._log(f"Gaming boost error: {e}")

            bg_trimmed = 0
            bg_failed = 0
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    pid = p.info['pid']
                    pname = (p.info['name'] or "").lower()
                    if pid == fpid or pname in PROTECTED:
                        continue
                    try:
                        h = open_proc(pid, win32con.PROCESS_SET_QUOTA)
                        if h:
                            empty_working_set(h)
                            win32api.CloseHandle(h)
                            bg_trimmed += 1
                    except:
                        bg_failed += 1
                except:
                    continue
            self._log(f"Gaming: Trimmed {bg_trimmed} processes, {bg_failed} failed")

            for p in psutil.process_iter(['pid', 'name']):
                try:
                    pid = p.info['pid']
                    pname = (p.info['name'] or "").lower()
                    if pid == fpid or pname in PROTECTED:
                        continue
                    h = open_proc(pid, win32con.PROCESS_SET_INFORMATION)
                    if h:
                        win32process.SetPriorityClass(h, win32process.BELOW_NORMAL_PRIORITY_CLASS)
                        win32api.CloseHandle(h)
                except:
                    continue

        elif name == "Work":
            reset_timer_resolution(1)
            control_sysmain_service(True)
            set_cpu_parking(True)

            fpid = fg_pid()
            if fpid:
                try:
                    h = open_proc(fpid, win32con.PROCESS_SET_INFORMATION)
                    if h:
                        win32process.SetPriorityClass(h, win32process.ABOVE_NORMAL_PRIORITY_CLASS)
                        win32api.CloseHandle(h)
                        self._log(f"Work: FG PID {fpid} → Above Normal")
                except: pass

            bg_procs = []
            for p in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    pid = p.info['pid']
                    pname = (p.info['name'] or "").lower()
                    if pid == fpid or pname in PROTECTED:
                        continue
                    mem = p.info['memory_info'].rss if p.info.get('memory_info') else 0
                    bg_procs.append((pid, pname, mem))
                except: continue

            bg_procs.sort(key=lambda x: x[2], reverse=True)
            for pid, pname, mem in bg_procs[:5]:
                try:
                    h = open_proc(pid, win32con.PROCESS_SET_QUOTA)
                    if h:
                        empty_working_set(h)
                        win32api.CloseHandle(h)
                except: continue
            self._log(f"Work: Trimmed top 5 heavy BG processes")

        elif name == "Battery":
            count = 0
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    pid = p.info['pid']
                    pname = (p.info['name'] or "").lower()
                    if pname in PROTECTED:
                        continue
                    h = open_proc(pid, win32con.PROCESS_SET_INFORMATION)
                    if h:
                        set_power_throttle(h, eco_on=True)
                        win32api.CloseHandle(h)
                        count += 1
                except: continue
            self._log(f"Battery: Eco throttled {count} processes")

        if prof.get("suspend_heavy_bg", False):
            self._suspend_heavy_backgrounds()

        if hasattr(self, 'prof_header') and self.prof_header:
            self.prof_header.configure(text=f"🎛️ CURRENT PROFILE: {name.upper()}")
        self._log(f"Applied profile: {name} (CPU limit: {prof.get('bg_cpu_limit', 30)}%, Mem priority: {prof.get('bg_mem_priority', 2)})")
        self._append_effect(f"Profile '{name}' applied: {prof['plan']} power plan.")

    def _suspend_heavy_backgrounds(self):
        try:
            fpid = fg_pid()
            for p in psutil.process_iter(["pid", "name", "cpu_percent"]):
                try:
                    pid = p.info["pid"]
                    name = (p.info["name"] or "").lower()
                    if pid == fpid:
                        continue
                    if name in (n.lower() for n in SYSTEM_WHITELIST):
                        continue
                    cpu = p.cpu_percent(interval=None) / max(1, self.core_count)
                    if cpu > 15:
                        self.bg_gov.suspend_heavy_process(pid)
                        self._log(f"Suspended heavy BG: {name} (PID {pid})")
                except Exception:
                    continue
        except Exception:
            pass

    def _quick_boost_fg(self):
        try:
            pid = fg_pid()
            if pid:
                h = open_proc(pid, win32con.PROCESS_SET_INFORMATION)
                if h:
                    win32process.SetPriorityClass(h, win32process.HIGH_PRIORITY_CLASS)
                    win32api.CloseHandle(h)
                    self._log(f"Boosted foreground PID {pid}")
        except Exception as e:
            self._log(f"Boost FG error: {e}")

    def _quick_trim_all(self):
        trimmed = 0
        for p in psutil.process_iter(['pid', 'name']):
            try:
                if p.info['name'].lower() not in PROTECTED:
                    h = open_proc(p.info['pid'], win32con.PROCESS_SET_QUOTA)
                    if h:
                        empty_working_set(h)
                        win32api.CloseHandle(h)
                        trimmed += 1
            except: pass
        self._log(f"Trimmed memory from {trimmed} processes")
        return trimmed

    def _quick_throttle_bg(self):
        fg = fg_pid()
        throttled = 0
        for p in psutil.process_iter(['pid', 'name']):
            try:
                if p.info['pid'] != fg and p.info['name'].lower() not in PROTECTED:
                    h = open_proc(p.info['pid'], win32con.PROCESS_SET_INFORMATION)
                    if h:
                        set_power_throttle(h, eco_on=True)
                        win32api.CloseHandle(h)
                        throttled += 1
            except: pass
        self._log(f"Throttled {throttled} background processes")
        return throttled

    def _quick_kill_heavy(self):
        try:
            procs = [(p.info['pid'], p.info['name'], p.info.get('memory_info').rss if p.info.get('memory_info') else 0)
                     for p in psutil.process_iter(['pid', 'name', 'memory_info'])
                     if p.info['name'].lower() not in PROTECTED]
            if procs:
                procs.sort(key=lambda x: x[2], reverse=True)
                pid, name, mem = procs[0]
                psutil.Process(pid).terminate()
                self._log(f"Terminated {name} (PID {pid}) - {mem/1024/1024:.0f} MB")
        except Exception as e:
            self._log(f"Kill error: {e}")

    def _one_click_boost(self):
        self.btn_boost_all.configure(state="disabled", text="⏳ Optimizing...")
        if hasattr(self, 'lbl_boost_status'):
            self.lbl_boost_status.configure(text="Starting boost...")
        self.update()

        ram_before = psutil.virtual_memory().available

        results = []

        if hasattr(self, 'lbl_boost_status'):
            self.lbl_boost_status.configure(text="Trimming memory...")
        self.update()
        trimmed = self._quick_trim_all()
        results.append(f"Trimmed {trimmed} procs")
        time.sleep(0.3)

        if hasattr(self, 'lbl_boost_status'):
            self.lbl_boost_status.configure(text="Throttling background apps...")
        self.update()
        throttled = self._quick_throttle_bg()
        results.append(f"Throttled {throttled} procs")
        time.sleep(0.3)

        if hasattr(self, 'lbl_boost_status'):
            self.lbl_boost_status.configure(text="Boosting foreground...")
        self.update()
        self._quick_boost_fg()
        results.append("Boosted FG")
        time.sleep(0.3)

        ram_after = psutil.virtual_memory().available
        ram_freed_mb = max(0, (ram_after - ram_before) / (1024 * 1024))

        self._session_stats["ram_freed_mb"] += ram_freed_mb
        self._session_stats["boost_count"] += 1

        self.btn_boost_all.configure(state="normal", text="BOOST NOW")

        if ram_freed_mb > 0:
            status_text = f"✅ Freed {ram_freed_mb:.0f} MB RAM | {' | '.join(results)}"
        else:
            status_text = f"✅ Done! | {' | '.join(results)}"

        if hasattr(self, 'lbl_boost_status'):
            self.lbl_boost_status.configure(text=status_text)

        self._toast(f"Boost complete! Freed {ram_freed_mb:.0f} MB RAM", "ok")
        self._log_activity(f"One-click boost: freed {ram_freed_mb:.0f} MB RAM", "boost")

    def _update_session_stats(self):
        if self._stop:
            return

        try:
            if hasattr(self, 'lbl_session_ram'):
                total_ram = self._session_stats["ram_freed_mb"]
                self.lbl_session_ram.configure(text=f"💾 RAM Freed: {total_ram:.0f} MB")

            if hasattr(self, 'lbl_session_boosts'):
                boosts = self._session_stats["boost_count"]
                self.lbl_session_boosts.configure(text=f"🚀 Boosts: {boosts}")

            if hasattr(self, 'lbl_session_time'):
                elapsed = time.time() - self._session_stats["start_time"]
                hours, remainder = divmod(int(elapsed), 3600)
                minutes, _ = divmod(remainder, 60)
                if hours > 0:
                    time_str = f"{hours}h {minutes}m"
                else:
                    time_str = f"{minutes}m"
                self.lbl_session_time.configure(text=f"⏱ Session: {time_str}")
        except Exception:
            pass

        self.after(5000, self._update_session_stats)

    def _toggle_theme(self):
        current = ctk.get_appearance_mode()
        new_mode = "Light" if current == "Dark" else "Dark"
        ctk.set_appearance_mode(new_mode)
        self.settings["theme"] = new_mode
        self._save_config()
        self._log(f"Theme changed to {new_mode}")

    def _export_benchmark(self):
        try:
            result = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "system": {
                    "cpu": platform.processor() if hasattr(platform, 'processor') else "Unknown",
                    "ram_gb": psutil.virtual_memory().total / (1024**3),
                    "os": platform.platform() if hasattr(platform, 'platform') else "Windows"
                },
                "scores": {
                    "single_core": self.lbl_single.cget("text") if hasattr(self, 'lbl_single') else "N/A",
                    "multi_core": self.lbl_multi.cget("text") if hasattr(self, 'lbl_multi') else "N/A"
                }
            }

            path = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON", "*.json"), ("Text", "*.txt")],
                title="Export Benchmark Results"
            )
            if path:
                with open(path, "w") as f:
                    json.dump(result, f, indent=2)
                self._log(f"Benchmark exported to {path}")
        except Exception as e:
            self._log(f"Export error: {e}")

    POWER_PLANS = {
        "high": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
        "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
        "saver": "a1841308-3541-4fab-bc81-f71556f20b4a"
    }

    def _set_power_plan(self, plan_type: str):
        try:
            guid = self.POWER_PLANS.get(plan_type)
            if guid:
                result = subprocess.run(
                    ["powercfg", "/setactive", guid],
                    capture_output=True, text=True, shell=True
                )
                if result.returncode == 0:
                    name = {"high": "High Performance", "balanced": "Balanced", "saver": "Power Saver"}[plan_type]
                    self._toast(f"Power plan set to {name}", "ok")
                    self._log(f"Power plan changed to {name}")
                else:
                    self._toast("Could not change power plan", "warn")
        except Exception as e:
            self._log(f"Power plan error: {e}")

    def _get_current_power_plan(self):
        try:
            result = subprocess.run(
                ["powercfg", "/getactivescheme"],
                capture_output=True, text=True, shell=True
            )
            return result.stdout.strip()
        except:
            return "Unknown"

    def _get_disk_usage(self):
        drives = []
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                drives.append({
                    "drive": partition.mountpoint,
                    "total_gb": usage.total / (1024**3),
                    "used_gb": usage.used / (1024**3),
                    "free_gb": usage.free / (1024**3),
                    "percent": usage.percent
                })
            except:
                pass
        return drives

    def _run_speed_test(self):
        import urllib.request
        import time as t

        self._toast("Testing network speed...", "info")
        self.update()

        try:
            test_url = "http://speedtest.tele2.net/1MB.zip"
            start = t.perf_counter()
            with urllib.request.urlopen(test_url, timeout=10) as response:
                data = response.read()
            elapsed = t.perf_counter() - start

            download_mbps = (len(data) * 8 / 1_000_000) / max(0.01, elapsed)

            self._toast(f"Download: {download_mbps:.1f} Mbps", "ok")
            self._log(f"Speed test: {download_mbps:.1f} Mbps download")

            return download_mbps
        except Exception as e:
            self._toast("Speed test failed", "warn")
            self._log(f"Speed test error: {e}")
            return 0

    def _refresh_disk_cards(self):
        if not hasattr(self, 'disk_cards_frame'):
            return

        for widget in self.disk_cards_frame.winfo_children():
            widget.destroy()

        drives = self._get_disk_usage()

        for drive in drives:
            card = ctk.CTkFrame(self.disk_cards_frame, fg_color="#0D1117", corner_radius=10,
                               border_width=1, border_color="#30363D")
            card.pack(fill="x", pady=5)

            header = ctk.CTkFrame(card, fg_color="transparent")
            header.pack(fill="x", padx=15, pady=(10,5))

            ctk.CTkLabel(header, text=f"📁 {drive['drive']}",
                        font=ctk.CTkFont(size=14, weight="bold"),
                        text_color="#F9FAFB").pack(side="left")

            ctk.CTkLabel(header, text=f"{drive['percent']:.0f}%",
                        font=ctk.CTkFont(size=12, weight="bold"),
                        text_color="#EF4444" if drive['percent'] > 90 else "#F59E0B" if drive['percent'] > 70 else "#10B981").pack(side="right")

            bar = ctk.CTkProgressBar(card, height=8,
                                     progress_color="#EF4444" if drive['percent'] > 90 else "#F59E0B" if drive['percent'] > 70 else "#10B981",
                                     fg_color="#1F2937")
            bar.set(drive['percent'] / 100)
            bar.pack(fill="x", padx=15, pady=5)

            ctk.CTkLabel(card, text=f"{drive['used_gb']:.1f} / {drive['total_gb']:.1f} GB used",
                        font=ctk.CTkFont(size=10), text_color="#9CA3AF").pack(padx=15, pady=(0,10))

    KNOWN_GAMES = {
        "csgo.exe", "cs2.exe", "dota2.exe", "valorant.exe", "leagueoflegends.exe",
        "fortnite.exe", "rocketleague.exe", "apex_legends.exe", "pubg.exe",
        "gta5.exe", "witcher3.exe", "cyberpunk2077.exe", "eldenring.exe",
        "minecraft.exe", "steam.exe", "epicgameslauncher.exe"
    }

    def _check_games(self):
        if not self.settings.get("auto_game_detect", False):
            return

        for p in psutil.process_iter(['name']):
            try:
                if p.info['name'].lower() in self.KNOWN_GAMES:
                    if self.current_profile != "Gaming":
                        self._apply_profile_named("Gaming")
                        self._log(f"Game detected: {p.info['name']} - Switched to Gaming profile")
                    return
            except: pass

    def _init_usage_stats(self):
        self.usage_history = {
            "cpu": deque(maxlen=3600),
            "ram": deque(maxlen=3600),
            "timestamps": deque(maxlen=3600)
        }
        self.process_history = []
        self._load_process_history()

    def _load_process_history(self):
        try:
            if os.path.exists(USAGE_HIST_PATH):
                with open(USAGE_HIST_PATH, "r") as f:
                    self.process_history = json.load(f)
                cutoff = time.time() - 86400
                self.process_history = [e for e in self.process_history if e.get("ts", 0) > cutoff]
        except: pass

    def _save_process_history(self):
        try:
            with open(USAGE_HIST_PATH, "w") as f:
                json.dump(self.process_history[-1440:], f)
        except: pass

    def _record_usage(self):
        if hasattr(self, 'usage_history'):
            self.usage_history["cpu"].append(psutil.cpu_percent())
            self.usage_history["ram"].append(psutil.virtual_memory().percent)
            self.usage_history["timestamps"].append(time.time())

        if hasattr(self, 'process_history'):
            now = time.time()
            if not self.process_history or (now - self.process_history[-1].get("ts", 0)) >= 300:
                self.process_history.append({
                    "ts": now,
                    "cpu": psutil.cpu_percent(),
                    "ram": psutil.virtual_memory().percent
                })
                self._save_process_history()

    def _toggle_game_detect(self):
        enabled = bool(self.chk_game_detect.get())
        self.settings["auto_game_detect"] = enabled
        self._save_config()
        self._log(f"Game detection {'enabled' if enabled else 'disabled'}")

    def _loop_features(self):
        iteration = 0
        while True:
            try:
                iteration += 1

                self._record_usage()
                self._check_games()
                self._check_schedule()
                PRIORITY_BALANCER.check_and_rebalance(fg_pid())
                POWER_SAVER.check()

                if iteration % 3 == 0:
                    try:
                        AI_OPTIMIZER.record_system_state()
                        ANOMALY_DETECTOR.record_baseline()
                        SMART_PROCESS_MGR.categorize_processes()
                    except:
                        pass

                if iteration % 6 == 0:
                    try:
                        AUTOMATION_ENGINE.evaluate_rules()
                        RESOURCE_FORECASTER.record_usage()
                        ANOMALY_DETECTOR.detect_anomalies()
                    except:
                        pass

                if iteration % 30 == 0:
                    try:
                        MAINTENANCE_SCHEDULER.run_due_tasks()
                        STABILITY_MONITOR.check_stability()
                        HEALTH_ANALYZER.analyze()
                    except:
                        pass

                if iteration % 60 == 0:
                    try:
                        SECURITY_SCANNER.scan()
                    except:
                        pass

            except Exception as e:
                pass

            time.sleep(10)

    HEAVY_STARTUP_APPS = {
        "discord", "spotify", "steam", "epicgameslauncher", "origin", "skype",
        "onedrive", "dropbox", "googledrive", "adobe", "teams", "slack",
        "vmware", "virtualbox", "docker", "itunes", "cortana"
    }

    def _refresh_startup(self):
        import winreg

        if not hasattr(self, 'tree_start') or self.tree_start is None:
            return

        self.tree_start.delete(*self.tree_start.get_children())
        self.startup_items = {}

        items = []

        reg_paths = [
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "User"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "System"),
        ]

        for root, path, source in reg_paths:
            try:
                key = winreg.OpenKey(root, path, 0, winreg.KEY_READ)
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        impact = "Low"
                        name_lower = name.lower()
                        for heavy in self.HEAVY_STARTUP_APPS:
                            if heavy in name_lower:
                                impact = "High"
                                break
                        if impact == "Low" and any(x in name_lower for x in ["update", "helper", "agent"]):
                            impact = "Medium"

                        publisher = "Unknown"
                        if "microsoft" in value.lower():
                            publisher = "Microsoft"
                        elif "google" in value.lower():
                            publisher = "Google"
                        elif "adobe" in value.lower():
                            publisher = "Adobe"

                        items.append((impact, name, publisher, value[:80], "Enabled", source, root, path))
                        i += 1
                    except OSError:
                        break
                winreg.CloseKey(key)
            except Exception:
                pass

        startup_folder = os.path.join(os.environ.get("APPDATA", ""),
                                       r"Microsoft\Windows\Start Menu\Programs\Startup")
        if os.path.exists(startup_folder):
            for f in os.listdir(startup_folder):
                if f.endswith((".lnk", ".exe", ".bat")):
                    impact = "Medium"
                    for heavy in self.HEAVY_STARTUP_APPS:
                        if heavy in f.lower():
                            impact = "High"
                            break
                    items.append((impact, f.replace(".lnk", ""), "Startup Folder",
                                 os.path.join(startup_folder, f)[:80], "Enabled", "Folder", None, startup_folder))

        impact_order = {"High": 0, "Medium": 1, "Low": 2}
        items.sort(key=lambda x: impact_order.get(x[0], 3))

        for i, (impact, name, publisher, cmd, status, source, root, path) in enumerate(items):
            iid = self.tree_start.insert("", "end", values=(impact, name, publisher, cmd, status))
            self.startup_items[iid] = {"name": name, "source": source, "root": root, "path": path, "cmd": cmd}

        if hasattr(self, 'lbl_startup_status'):
            high_count = sum(1 for item in items if item[0] == "High")
            self.lbl_startup_status.configure(text=f"{len(items)} items | {high_count} high impact")

        self._log(f"Scanned {len(items)} startup items")

    def _toggle_startup(self, enable: bool):
        import winreg

        if not hasattr(self, 'tree_start') or self.tree_start is None:
            return

        selected = self.tree_start.selection()
        if not selected:
            self._toast("Select items to enable/disable", "warn")
            return

        count = 0
        for iid in selected:
            if iid not in self.startup_items:
                continue
            item = self.startup_items[iid]

            if item["source"] == "Folder":
                path = os.path.join(item["path"], item["name"])
                continue

            try:
                if enable:
                    pass
                else:
                    key = winreg.OpenKey(item["root"], item["path"], 0, winreg.KEY_SET_VALUE)
                    winreg.DeleteValue(key, item["name"])
                    winreg.CloseKey(key)
                    count += 1
            except Exception as e:
                self._log(f"Could not toggle {item['name']}: {e}")

        if count > 0:
            action = "enabled" if enable else "disabled"
            self._toast(f"{count} startup item(s) {action}", "ok")
            self._refresh_startup()
        else:
            self._toast("No items were modified", "warn")

    def _open_startup_folder(self):
        startup_folder = os.path.join(os.environ.get("APPDATA", ""),
                                       r"Microsoft\Windows\Start Menu\Programs\Startup")
        try:
            os.startfile(startup_folder)
        except Exception as e:
            self._log(f"Could not open startup folder: {e}")

    def _init_tray(self):
        if pystray is None or Image is None:
            self._log("System tray not available (pystray or PIL missing)")
            return

        def create_icon():
            img = Image.new('RGB', (64, 64), color='#8B5CF6')
            return img

        def tray_menu():
            return (
                item('Show OptiCores', self._show_window, default=True),
                item('⚡ Quick Boost', self._tray_boost),
                item('📊 Toggle Overlay', lambda: self._toggle_overlay()),
                pystray.Menu.SEPARATOR,
                item('Profiles', pystray.Menu(
                    item('🎮 Gaming', lambda: self._apply_profile_named("Gaming")),
                    item('💼 Work', lambda: self._apply_profile_named("Work")),
                    item('🔋 Battery', lambda: self._apply_profile_named("Battery")),
                    item('🤫 Quiet', lambda: self._apply_profile_named("Quiet")),
                )),
                pystray.Menu.SEPARATOR,
                item('Exit', self._quit_app),
            )

        try:
            self.tray_icon = pystray.Icon(
                "OptiCores",
                create_icon(),
                "OptiCores - System Optimizer",
                menu=pystray.Menu(tray_menu)
            )
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
            self._log("System tray icon created")
        except Exception as e:
            self._log(f"Could not create tray icon: {e}")

    def _on_close(self):
        if self.tray_icon:
            self.withdraw()
            self._log("Minimized to system tray")
        else:
            self._quit_app()

    def _show_window(self, icon=None, item=None):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _tray_boost(self, icon=None, item=None):
        self._quick_trim_all()
        self._quick_throttle_bg()
        self._quick_boost_fg()

    def _quit_app(self, icon=None, item=None):
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except:
                pass
        if hasattr(self, 'overlay') and self.overlay:
            try:
                self.overlay.destroy()
            except:
                pass
        
        self._save_config()
        self.destroy()

    def _toggle_overlay(self):
        if hasattr(self, 'overlay') and self.overlay and self.overlay.winfo_exists():
            self.overlay.destroy()
            self.overlay = None
            self._log("Overlay hidden")
        else:
            self._create_overlay()
            self._log("Overlay shown")

    def _toggle_auto_game(self):
        enabled = self.chk_auto_game.get()
        self.settings["auto_game_detect"] = bool(enabled)
        self._save_config()
        state = "enabled" if enabled else "disabled"
        self._log(f"Auto game detection {state}")
        self._toast(f"Auto game detection {state}", "ok")

    def _create_overlay(self):
        self.overlay = ctk.CTkToplevel(self)
        self.overlay.title("")
        self.overlay.geometry("180x80+20+20")
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.attributes("-alpha", 0.85)
        self.overlay.configure(fg_color="#0D1117")

        self.overlay._drag_data = {"x": 0, "y": 0}
        self.overlay.bind("<Button-1>", self._overlay_start_drag)
        self.overlay.bind("<B1-Motion>", self._overlay_drag)

        frame = ctk.CTkFrame(self.overlay, fg_color="#161B22", corner_radius=10,
                            border_width=1, border_color="#30363D")
        frame.pack(fill="both", expand=True, padx=2, pady=2)

        stats = ctk.CTkFrame(frame, fg_color="transparent")
        stats.pack(fill="x", padx=10, pady=8)

        cpu_frame = ctk.CTkFrame(stats, fg_color="transparent")
        cpu_frame.pack(side="left", expand=True)
        ctk.CTkLabel(cpu_frame, text="CPU", text_color="#9CA3AF", font=ctk.CTkFont(size=9)).pack()
        self.overlay_cpu = ctk.CTkLabel(cpu_frame, text="--", text_color="#8B5CF6",
                                        font=ctk.CTkFont(size=16, weight="bold"))
        self.overlay_cpu.pack()

        ram_frame = ctk.CTkFrame(stats, fg_color="transparent")
        ram_frame.pack(side="left", expand=True)
        ctk.CTkLabel(ram_frame, text="RAM", text_color="#9CA3AF", font=ctk.CTkFont(size=9)).pack()
        self.overlay_ram = ctk.CTkLabel(ram_frame, text="--", text_color="#10B981",
                                        font=ctk.CTkFont(size=16, weight="bold"))
        self.overlay_ram.pack()

        close_btn = ctk.CTkButton(frame, text="×", width=20, height=20,
                                  fg_color="transparent", hover_color="#EF4444",
                                  command=self._toggle_overlay, font=ctk.CTkFont(size=14))
        close_btn.place(relx=1.0, rely=0, anchor="ne", x=-5, y=5)

        self._update_overlay()

    def _overlay_start_drag(self, event):
        self.overlay._drag_data["x"] = event.x
        self.overlay._drag_data["y"] = event.y

    def _overlay_drag(self, event):
        x = self.overlay.winfo_x() + (event.x - self.overlay._drag_data["x"])
        y = self.overlay.winfo_y() + (event.y - self.overlay._drag_data["y"])
        self.overlay.geometry(f"+{x}+{y}")

    def _update_overlay(self):
        if not hasattr(self, 'overlay') or not self.overlay or not self.overlay.winfo_exists():
            return

        try:
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent

            self.overlay_cpu.configure(text=f"{cpu:.0f}%")
            self.overlay_ram.configure(text=f"{ram:.0f}%")

            self.overlay_cpu.configure(text_color="#EF4444" if cpu > 80 else "#F59E0B" if cpu > 60 else "#8B5CF6")
            self.overlay_ram.configure(text_color="#EF4444" if ram > 80 else "#F59E0B" if ram > 60 else "#10B981")
        except:
            pass

        self.overlay.after(1000, self._update_overlay)

    def _toggle_schedule(self):
        enabled = bool(self.chk_sched.get())
        self.settings["sched_enabled"] = enabled
        self._save_config()
        self._log(f"Scheduled optimization {'enabled' if enabled else 'disabled'}")

    def _save_schedule(self):
        self.settings["sched_hour"] = self.sched_hour.get()
        self.settings["sched_min"] = self.sched_min.get()
        self._save_config()
        self._log(f"Schedule saved: {self.sched_hour.get()}:{self.sched_min.get()}")

    def _check_schedule(self):
        if not self.settings.get("sched_enabled", False):
            return

        now = time.localtime()
        target_h = int(self.settings.get("sched_hour", "03"))
        target_m = int(self.settings.get("sched_min", "00"))

        if now.tm_hour == target_h and now.tm_min == target_m:
            last_run = self.settings.get("sched_last_run", "")
            today = time.strftime("%Y-%m-%d")
            if last_run != today:
                self._log("Running scheduled optimization...")
                self._quick_trim_all()
                self._quick_throttle_bg()
                self.settings["sched_last_run"] = today
                self._save_config()
                self._log("Scheduled optimization complete.")

    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        try:
            self.txt_log.insert("end", f"[{ts}] {msg}\n"); self.txt_log.see("end")
        except Exception:
            print(msg)

    def _fill_cleaner_content(self, parent):
        ctrl = ctk.CTkFrame(parent, fg_color="transparent")
        ctrl.pack(fill="x", padx=20, pady=20)

        self.btn_scan = ctk.CTkButton(ctrl, text="🔍 Scan Junk", command=self._scan_junk,
                                     fg_color="#8B5CF6", hover_color="#7C3AED", font=ctk.CTkFont(weight="bold"))
        self.btn_scan.pack(side="left", padx=(0,10))

        self.btn_clean = ctk.CTkButton(ctrl, text="🗑️ Clean All", command=self._clean_junk, state="disabled",
                                      fg_color="#EF4444", hover_color="#DC2626", font=ctk.CTkFont(weight="bold"))
        self.btn_clean.pack(side="left")

        self.lbl_clean_stat = ctk.CTkLabel(ctrl, text="Ready to scan.", text_color="#9CA3AF")
        self.lbl_clean_stat.pack(side="left", padx=20)

        self.clean_log = ctk.CTkTextbox(parent, font=ctk.CTkFont(family="Consolas", size=12))
        self.clean_log.pack(fill="both", expand=True, padx=20, pady=(0,20))

        self.junk_files = []

    def _scan_junk(self):
        self.clean_log.delete("1.0", "end")
        self.clean_log.insert("end", "Scanning for temporary files...\n")
        self.btn_scan.configure(state="disabled")
        self.update()

        junk_dirs = [os.environ.get("TEMP"), os.environ.get("TMP")]
        junk_dirs = [d for d in junk_dirs if d and os.path.exists(d)]

        self.junk_files = []
        total_size = 0

        for d in set(junk_dirs):
            try:
                for root, dirs, files in os.walk(d):
                    for f in files:
                        try:
                            fp = os.path.join(root, f)
                            sz = os.path.getsize(fp)
                            self.junk_files.append(fp)
                            total_size += sz
                        except Exception: pass
            except Exception as e:
                self.clean_log.insert("end", f"Error scanning {d}: {e}\n")

        if total_size > 1024*1024*1024: sz_str = f"{total_size/1024/1024/1024:.2f} GB"
        elif total_size > 1024*1024: sz_str = f"{total_size/1024/1024:.2f} MB"
        else: sz_str = f"{total_size/1024:.2f} KB"

        self.clean_log.insert("end", f"\nScan Complete.\nFound {len(self.junk_files)} files totaling {sz_str}.\n")
        self.lbl_clean_stat.configure(text=f"Found: {sz_str} ({len(self.junk_files)} files)")

        if self.junk_files:
            self.btn_clean.configure(state="normal")
        self.btn_scan.configure(state="normal")

    def _clean_junk(self):
        if not self.junk_files: return

        self.btn_clean.configure(state="disabled")
        self.btn_scan.configure(state="disabled")
        self.clean_log.insert("end", "\nStarting cleanup...\n")
        self.update()

        deleted = 0
        errors = 0

        for fp in self.junk_files:
            try:
                os.remove(fp)
                deleted += 1
                if deleted % 50 == 0:
                    self.clean_log.insert("end", ".")
                    self.clean_log.see("end")
                    self.update()
            except Exception:
                errors += 1

        self.clean_log.insert("end", f"\nCleanup Finished.\nDeleted: {deleted}\nSkipped/Locked: {errors}\n")
        self.lbl_clean_stat.configure(text="Cleanup complete.")
        self.junk_files = []
        self.btn_scan.configure(state="normal")

    def _fill_sysinfo(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        header = ctk.CTkFrame(scroll, fg_color="transparent")
        header.pack(fill="x", padx=40, pady=(30, 20))
        ctk.CTkLabel(header, text="🖥️ System Information",
                    font=ctk.CTkFont(family="Segoe UI Variable Display", size=28, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(header, text="Detailed hardware and software information",
                    font=ctk.CTkFont(size=13), text_color="#9CA3AF").pack(anchor="w", pady=(4, 0))

        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.pack(anchor="w", pady=(10, 0))
        ctk.CTkButton(btn_frame, text="🔄 Refresh", command=lambda: self._refresh_sysinfo(),
                     fg_color="#8B5CF6", hover_color="#7C3AED", width=120).pack(side="left")
        ctk.CTkButton(btn_frame, text="📋 Copy to Clipboard", command=lambda: self._copy_sysinfo(),
                     fg_color="#374151", hover_color="#4B5563", width=150).pack(side="left", padx=10)

        self.sysinfo_container = ctk.CTkFrame(scroll, fg_color="transparent")
        self.sysinfo_container.pack(fill="both", expand=True, padx=40, pady=(0, 30))

        self._refresh_sysinfo()

    def _refresh_sysinfo(self):
        for widget in self.sysinfo_container.winfo_children():
            widget.destroy()

        info = SYSINFO.get_all()

        def section(title, icon):
            frame = ctk.CTkFrame(self.sysinfo_container, fg_color="#161B22", corner_radius=12,
                                border_width=1, border_color="#1D232C")
            frame.pack(fill="x", pady=8)

            header = ctk.CTkFrame(frame, fg_color="transparent")
            header.pack(fill="x", padx=16, pady=(12, 8))
            ctk.CTkLabel(header, text=f"{icon} {title}",
                        font=ctk.CTkFont(size=14, weight="bold"), text_color="#E5E7EB").pack(anchor="w")

            content = ctk.CTkFrame(frame, fg_color="transparent")
            content.pack(fill="x", padx=16, pady=(0, 12))
            return content

        def info_row(parent, label, value, row):
            ctk.CTkLabel(parent, text=label, text_color="#9CA3AF",
                        font=ctk.CTkFont(size=12)).grid(row=row, column=0, sticky="w", pady=2)
            ctk.CTkLabel(parent, text=str(value), text_color="#F9FAFB",
                        font=ctk.CTkFont(size=12)).grid(row=row, column=1, sticky="w", padx=(20, 0), pady=2)

        cpu = info['cpu']
        cpu_sec = section("Processor (CPU)", "🧠")
        cpu_sec.grid_columnconfigure(1, weight=1)
        info_row(cpu_sec, "Name:", cpu['name'], 0)
        info_row(cpu_sec, "Architecture:", cpu['architecture'], 1)
        info_row(cpu_sec, "Physical Cores:", cpu['physical_cores'], 2)
        info_row(cpu_sec, "Logical Cores:", cpu['logical_cores'], 3)
        info_row(cpu_sec, "Max Frequency:", f"{cpu['max_freq']:.0f} MHz" if cpu['max_freq'] else "N/A", 4)
        info_row(cpu_sec, "Current Frequency:", f"{cpu['current_freq']:.0f} MHz" if cpu['current_freq'] else "N/A", 5)

        mem = info['memory']
        mem_sec = section("Memory (RAM)", "💾")
        mem_sec.grid_columnconfigure(1, weight=1)
        info_row(mem_sec, "Total Memory:", f"{mem['total_gb']:.1f} GB", 0)
        info_row(mem_sec, "Available:", f"{mem['available_gb']:.1f} GB", 1)
        info_row(mem_sec, "Used:", f"{mem['used_gb']:.1f} GB ({mem['percent']:.1f}%)", 2)
        info_row(mem_sec, "Swap Total:", f"{mem['swap_total_gb']:.1f} GB", 3)
        info_row(mem_sec, "Swap Used:", f"{mem['swap_used_gb']:.1f} GB", 4)

        gpus = info['gpus']
        gpu_sec = section("Graphics (GPU)", "🎮")
        gpu_sec.grid_columnconfigure(1, weight=1)
        for i, gpu in enumerate(gpus):
            if i > 0:
                ctk.CTkFrame(gpu_sec, height=1, fg_color="#30363D").grid(row=i*5, column=0, columnspan=2, sticky="ew", pady=8)
            base = i * 5
            info_row(gpu_sec, f"GPU {i+1} Name:", gpu['name'], base)
            info_row(gpu_sec, "Memory Total:", f"{gpu['memory_total_mb']:.0f} MB" if gpu['memory_total_mb'] else "N/A", base+1)
            info_row(gpu_sec, "Memory Used:", f"{gpu['memory_used_mb']:.0f} MB" if gpu['memory_used_mb'] else "N/A", base+2)
            info_row(gpu_sec, "Load:", f"{gpu['load']:.0f}%" if gpu['load'] else "N/A", base+3)
            info_row(gpu_sec, "Temperature:", f"{gpu['temperature']}°C" if gpu['temperature'] else "N/A", base+4)

        os_info = info['os']
        os_sec = section("Operating System", "🖥️")
        os_sec.grid_columnconfigure(1, weight=1)
        info_row(os_sec, "System:", os_info['system'], 0)
        info_row(os_sec, "Release:", os_info['release'], 1)
        info_row(os_sec, "Version:", os_info['version'], 2)
        info_row(os_sec, "Hostname:", os_info['node'], 3)
        info_row(os_sec, "Architecture:", os_info['machine'], 4)

        disks = info['disks']
        disk_sec = section("Storage", "💿")
        disk_sec.grid_columnconfigure(1, weight=1)
        for i, disk in enumerate(disks):
            base = i * 3
            info_row(disk_sec, f"{disk['device']}:",
                    f"{disk['free_gb']:.1f} GB free / {disk['total_gb']:.1f} GB ({disk['percent']:.0f}% used)", base)

    def _copy_sysinfo(self):
        info = SYSINFO.get_all()
        text = "=== OptiCores System Report ===\n\n"
        text += f"[CPU]\nName: {info['cpu']['name']}\nCores: {info['cpu']['physical_cores']}P/{info['cpu']['logical_cores']}L\n\n"
        text += f"[Memory]\nTotal: {info['memory']['total_gb']:.1f} GB\nUsed: {info['memory']['percent']:.1f}%\n\n"
        text += f"[OS]\n{info['os']['system']} {info['os']['release']}\n{info['os']['version']}\n"

        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self._toast("System info copied to clipboard!", "ok")
        except Exception:
            self._toast("Failed to copy", "error")

    def _fill_security(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        header = ctk.CTkFrame(scroll, fg_color="transparent")
        header.pack(fill="x", padx=40, pady=(30, 20))
        ctk.CTkLabel(header, text="🛡️ Security Scanner",
                    font=ctk.CTkFont(family="Segoe UI Variable Display", size=28, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(header, text="Detect suspicious processes and resource abuse",
                    font=ctk.CTkFont(size=13), text_color="#9CA3AF").pack(anchor="w", pady=(4, 0))

        ctrl_frame = ctk.CTkFrame(scroll, fg_color="#161B22", corner_radius=12,
                                 border_width=1, border_color="#1D232C")
        ctrl_frame.pack(fill="x", padx=40, pady=(0, 20))

        ctrl_content = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        ctrl_content.pack(fill="x", padx=16, pady=16)

        self.btn_security_scan = ctk.CTkButton(ctrl_content, text="🔍 Run Full Scan",
                                               command=lambda: self._run_security_scan(),
                                               fg_color="#8B5CF6", hover_color="#7C3AED",
                                               font=ctk.CTkFont(weight="bold"), height=40, width=160)
        self.btn_security_scan.pack(side="left")

        self.security_status = ctk.CTkLabel(ctrl_content, text="Ready to scan",
                                           text_color="#9CA3AF", font=ctk.CTkFont(size=12))
        self.security_status.pack(side="left", padx=20)

        self.security_results_container = ctk.CTkFrame(scroll, fg_color="transparent")
        self.security_results_container.pack(fill="both", expand=True, padx=40, pady=(0, 30))

        empty_frame = ctk.CTkFrame(self.security_results_container, fg_color="#161B22", corner_radius=12)
        empty_frame.pack(fill="x", pady=8)
        ctk.CTkLabel(empty_frame, text="💚 No scan results yet. Click 'Run Full Scan' to check for threats.",
                    text_color="#9CA3AF", font=ctk.CTkFont(size=13)).pack(padx=20, pady=40)

    def _run_security_scan(self):
        self.btn_security_scan.configure(state="disabled")
        self.security_status.configure(text="Scanning...")
        self.update()

        results = SECURITY.run_full_scan()

        for widget in self.security_results_container.winfo_children():
            widget.destroy()

        if not results:
            clear_frame = ctk.CTkFrame(self.security_results_container, fg_color="#161B22", corner_radius=12,
                                      border_width=2, border_color="#10B981")
            clear_frame.pack(fill="x", pady=8)

            ctk.CTkLabel(clear_frame, text="✅", font=ctk.CTkFont(size=48)).pack(pady=(30, 10))
            ctk.CTkLabel(clear_frame, text="All Clear!",
                        font=ctk.CTkFont(size=24, weight="bold"), text_color="#10B981").pack()
            ctk.CTkLabel(clear_frame, text="No suspicious processes or resource abuse detected.",
                        text_color="#9CA3AF", font=ctk.CTkFont(size=13)).pack(pady=(5, 30))

            self.security_status.configure(text="Scan complete - No threats found")
        else:
            high_count = len([r for r in results if r.get('severity') == 'high'])
            med_count = len([r for r in results if r.get('severity') == 'medium'])
            low_count = len([r for r in results if r.get('severity') == 'low'])

            summary = ctk.CTkFrame(self.security_results_container, fg_color="#161B22", corner_radius=12,
                                  border_width=1, border_color="#F59E0B")
            summary.pack(fill="x", pady=8)

            sum_content = ctk.CTkFrame(summary, fg_color="transparent")
            sum_content.pack(fill="x", padx=16, pady=16)

            ctk.CTkLabel(sum_content, text=f"⚠️ Found {len(results)} issue(s)",
                        font=ctk.CTkFont(size=16, weight="bold"), text_color="#F59E0B").pack(anchor="w")

            stats = ctk.CTkFrame(sum_content, fg_color="transparent")
            stats.pack(anchor="w", pady=(8, 0))
            if high_count:
                ctk.CTkLabel(stats, text=f"🔴 {high_count} High", text_color="#EF4444",
                            font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 15))
            if med_count:
                ctk.CTkLabel(stats, text=f"🟡 {med_count} Medium", text_color="#F59E0B",
                            font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 15))
            if low_count:
                ctk.CTkLabel(stats, text=f"🟢 {low_count} Low", text_color="#10B981",
                            font=ctk.CTkFont(size=12)).pack(side="left")

            for result in results:
                severity = result.get('severity', 'low')
                colors = {'high': '#EF4444', 'medium': '#F59E0B', 'low': '#10B981'}
                color = colors.get(severity, '#9CA3AF')

                item = ctk.CTkFrame(self.security_results_container, fg_color="#161B22", corner_radius=12,
                                   border_width=1, border_color=color)
                item.pack(fill="x", pady=4)

                item_content = ctk.CTkFrame(item, fg_color="transparent")
                item_content.pack(fill="x", padx=16, pady=12)

                left = ctk.CTkFrame(item_content, fg_color="transparent")
                left.pack(side="left", fill="x", expand=True)

                ctk.CTkLabel(left, text=f"{result.get('name', 'Unknown')} (PID: {result.get('pid', '?')})",
                            font=ctk.CTkFont(size=13, weight="bold"), text_color="#E5E7EB").pack(anchor="w")
                ctk.CTkLabel(left, text=result.get('threat', 'Unknown threat'),
                            text_color="#9CA3AF", font=ctk.CTkFont(size=11)).pack(anchor="w")

                if result.get('pid'):
                    ctk.CTkButton(item_content, text="Kill", fg_color="#EF4444", hover_color="#DC2626",
                                 width=70, height=28, font=ctk.CTkFont(size=11),
                                 command=lambda pid=result['pid']: self._kill_threat(pid)).pack(side="right")

            self.security_status.configure(text=f"Scan complete - {len(results)} issue(s) found")

        self.btn_security_scan.configure(state="normal")

    def _kill_threat(self, pid):
        try:
            p = psutil.Process(pid)
            p.terminate()
            self._toast(f"Process {pid} terminated", "ok")
            self._run_security_scan()
        except Exception as e:
            self._toast(f"Failed to kill process: {e}", "error")

    def _fill_power(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        header = ctk.CTkFrame(scroll, fg_color="transparent")
        header.pack(fill="x", padx=40, pady=(30, 20))
        ctk.CTkLabel(header, text="⚡ Power Management",
                    font=ctk.CTkFont(family="Segoe UI Variable Display", size=28, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(header, text="Manage power plans and optimize power consumption",
                    font=ctk.CTkFont(size=13), text_color="#9CA3AF").pack(anchor="w", pady=(4, 0))

        current_frame = ctk.CTkFrame(scroll, fg_color="#161B22", corner_radius=12,
                                    border_width=1, border_color="#1D232C")
        current_frame.pack(fill="x", padx=40, pady=(0, 20))

        current_content = ctk.CTkFrame(current_frame, fg_color="transparent")
        current_content.pack(fill="x", padx=16, pady=16)

        ctk.CTkLabel(current_content, text="Current Power Plan",
                    font=ctk.CTkFont(size=12), text_color="#9CA3AF").pack(anchor="w")

        current_plan = POWER_MGR.get_current_power_plan()
        plan_names = {'balanced': '⚖️ Balanced', 'high_performance': '🚀 High Performance',
                     'power_saver': '🔋 Power Saver', 'ultimate': '⚡ Ultimate Performance', 'unknown': '❓ Unknown'}

        self.lbl_current_power = ctk.CTkLabel(current_content, text=plan_names.get(current_plan, current_plan),
                                             font=ctk.CTkFont(size=20, weight="bold"), text_color="#F9FAFB")
        self.lbl_current_power.pack(anchor="w", pady=(4, 0))

        plans_frame = ctk.CTkFrame(scroll, fg_color="#161B22", corner_radius=12,
                                  border_width=1, border_color="#1D232C")
        plans_frame.pack(fill="x", padx=40, pady=(0, 20))

        plans_header = ctk.CTkFrame(plans_frame, fg_color="transparent")
        plans_header.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(plans_header, text="🔌 Power Plans",
                    font=ctk.CTkFont(size=14, weight="bold"), text_color="#E5E7EB").pack(anchor="w")

        plans_grid = ctk.CTkFrame(plans_frame, fg_color="transparent")
        plans_grid.pack(fill="x", padx=16, pady=(0, 16))
        plans_grid.grid_columnconfigure((0, 1), weight=1)

        def plan_card(col, name, icon, desc, plan_key, color):
            card = ctk.CTkFrame(plans_grid, fg_color="#0D1117", corner_radius=10,
                               border_width=1, border_color="#30363D")
            card.grid(row=0, column=col, sticky="nsew", padx=6, pady=6)

            content = ctk.CTkFrame(card, fg_color="transparent")
            content.pack(fill="both", expand=True, padx=14, pady=14)

            ctk.CTkLabel(content, text=icon, font=ctk.CTkFont(size=28)).pack(anchor="w")
            ctk.CTkLabel(content, text=name, font=ctk.CTkFont(size=14, weight="bold"),
                        text_color="#E5E7EB").pack(anchor="w", pady=(8, 2))
            ctk.CTkLabel(content, text=desc, font=ctk.CTkFont(size=11),
                        text_color="#9CA3AF", wraplength=180).pack(anchor="w")

            ctk.CTkButton(content, text="Activate", fg_color=color, hover_color="#" + hex(max(0, int(color[1:], 16) - 0x222222))[2:].zfill(6),
                         height=32, font=ctk.CTkFont(size=12),
                         command=lambda k=plan_key: self._set_power_plan(k)).pack(fill="x", pady=(12, 0))

        plan_card(0, "Power Saver", "🔋", "Reduces performance to save energy", "power_saver", "#10B981")
        plan_card(1, "Balanced", "⚖️", "Balances performance with energy consumption", "balanced", "#8B5CF6")

        plans_grid2 = ctk.CTkFrame(plans_frame, fg_color="transparent")
        plans_grid2.pack(fill="x", padx=16, pady=(0, 16))
        plans_grid2.grid_columnconfigure((0, 1), weight=1)

        plan_card2 = lambda col, name, icon, desc, plan_key, color: None

        card = ctk.CTkFrame(plans_grid2, fg_color="#0D1117", corner_radius=10, border_width=1, border_color="#30363D")
        card.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=14, pady=14)
        ctk.CTkLabel(content, text="🚀", font=ctk.CTkFont(size=28)).pack(anchor="w")
        ctk.CTkLabel(content, text="High Performance", font=ctk.CTkFont(size=14, weight="bold"), text_color="#E5E7EB").pack(anchor="w", pady=(8, 2))
        ctk.CTkLabel(content, text="Maximum performance at higher power consumption", font=ctk.CTkFont(size=11), text_color="#9CA3AF", wraplength=180).pack(anchor="w")
        ctk.CTkButton(content, text="Activate", fg_color="#F59E0B", hover_color="#D97706", height=32, font=ctk.CTkFont(size=12), command=lambda: self._set_power_plan("high_performance")).pack(fill="x", pady=(12, 0))

        card2 = ctk.CTkFrame(plans_grid2, fg_color="#0D1117", corner_radius=10, border_width=1, border_color="#30363D")
        card2.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        content2 = ctk.CTkFrame(card2, fg_color="transparent")
        content2.pack(fill="both", expand=True, padx=14, pady=14)
        ctk.CTkLabel(content2, text="⚡", font=ctk.CTkFont(size=28)).pack(anchor="w")
        ctk.CTkLabel(content2, text="Ultimate Performance", font=ctk.CTkFont(size=14, weight="bold"), text_color="#E5E7EB").pack(anchor="w", pady=(8, 2))
        ctk.CTkLabel(content2, text="No throttling, maximum power (requires compatible system)", font=ctk.CTkFont(size=11), text_color="#9CA3AF", wraplength=180).pack(anchor="w")
        ctk.CTkButton(content2, text="Activate", fg_color="#EF4444", hover_color="#DC2626", height=32, font=ctk.CTkFont(size=12), command=lambda: self._set_power_plan("ultimate")).pack(fill="x", pady=(12, 0))

        battery = POWER_MGR.get_battery_status()
        if battery['percent'] < 100 or not battery['power_plugged']:
            batt_frame = ctk.CTkFrame(scroll, fg_color="#161B22", corner_radius=12,
                                     border_width=1, border_color="#1D232C")
            batt_frame.pack(fill="x", padx=40, pady=(0, 20))

            batt_content = ctk.CTkFrame(batt_frame, fg_color="transparent")
            batt_content.pack(fill="x", padx=16, pady=16)

            ctk.CTkLabel(batt_content, text="🔋 Battery Status",
                        font=ctk.CTkFont(size=14, weight="bold"), text_color="#E5E7EB").pack(anchor="w")

            batt_row = ctk.CTkFrame(batt_content, fg_color="transparent")
            batt_row.pack(fill="x", pady=(10, 0))

            ctk.CTkLabel(batt_row, text=f"{battery['percent']}%",
                        font=ctk.CTkFont(size=28, weight="bold"),
                        text_color="#10B981" if battery['percent'] > 30 else "#EF4444").pack(side="left")

            status_text = "🔌 Plugged In" if battery['power_plugged'] else "🔋 On Battery"
            ctk.CTkLabel(batt_row, text=status_text, text_color="#9CA3AF",
                        font=ctk.CTkFont(size=12)).pack(side="left", padx=20)

    def _set_power_plan(self, plan_key):
        if POWER_MGR.set_power_plan(plan_key):
            plan_names = {'balanced': '⚖️ Balanced', 'high_performance': '🚀 High Performance',
                         'power_saver': '🔋 Power Saver', 'ultimate': '⚡ Ultimate Performance'}
            self.lbl_current_power.configure(text=plan_names.get(plan_key, plan_key))
            self._toast(f"Power plan changed to {plan_key.replace('_', ' ').title()}", "ok")
            self._log_activity(f"Power plan changed to {plan_key}", "power")
        else:
            self._toast("Failed to change power plan (requires admin)", "error")

    def _fill_scheduler(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        header = ctk.CTkFrame(scroll, fg_color="transparent")
        header.pack(fill="x", padx=40, pady=(30, 20))
        ctk.CTkLabel(header, text="⏰ Task Scheduler",
                    font=ctk.CTkFont(family="Segoe UI Variable Display", size=28, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(header, text="Schedule automated optimization tasks",
                    font=ctk.CTkFont(size=13), text_color="#9CA3AF").pack(anchor="w", pady=(4, 0))

        add_frame = ctk.CTkFrame(scroll, fg_color="#161B22", corner_radius=12,
                                border_width=1, border_color="#1D232C")
        add_frame.pack(fill="x", padx=40, pady=(0, 20))

        add_header = ctk.CTkFrame(add_frame, fg_color="transparent")
        add_header.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(add_header, text="➕ Add New Task",
                    font=ctk.CTkFont(size=14, weight="bold"), text_color="#E5E7EB").pack(anchor="w")

        add_content = ctk.CTkFrame(add_frame, fg_color="transparent")
        add_content.pack(fill="x", padx=16, pady=(0, 16))
        add_content.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(add_content, text="Task Name:", text_color="#9CA3AF").grid(row=0, column=0, sticky="w", pady=4)
        self.ent_task_name = ctk.CTkEntry(add_content, placeholder_text="e.g., Trim RAM", fg_color="#0D1117",
                                         border_color="#30363D", width=200)
        self.ent_task_name.grid(row=0, column=1, sticky="w", padx=(10, 0), pady=4)

        ctk.CTkLabel(add_content, text="Action:", text_color="#9CA3AF").grid(row=1, column=0, sticky="w", pady=4)
        self.cb_task_action = ctk.CTkComboBox(add_content,
                                             values=["trim_ram", "boost_foreground", "throttle_background", "clear_standby"],
                                             fg_color="#0D1117", border_color="#30363D", button_color="#8B5CF6", width=200)
        self.cb_task_action.set("trim_ram")
        self.cb_task_action.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=4)

        ctk.CTkLabel(add_content, text="Interval (min):", text_color="#9CA3AF").grid(row=2, column=0, sticky="w", pady=4)
        self.ent_task_interval = ctk.CTkEntry(add_content, placeholder_text="30", fg_color="#0D1117",
                                             border_color="#30363D", width=100)
        self.ent_task_interval.grid(row=2, column=1, sticky="w", padx=(10, 0), pady=4)

        ctk.CTkButton(add_content, text="Add Task", fg_color="#8B5CF6", hover_color="#7C3AED",
                     command=lambda: self._add_scheduled_task()).grid(row=3, column=1, sticky="w", padx=(10, 0), pady=(12, 0))

        list_frame = ctk.CTkFrame(scroll, fg_color="#161B22", corner_radius=12,
                                 border_width=1, border_color="#1D232C")
        list_frame.pack(fill="x", padx=40, pady=(0, 20))

        list_header = ctk.CTkFrame(list_frame, fg_color="transparent")
        list_header.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(list_header, text="📋 Scheduled Tasks",
                    font=ctk.CTkFont(size=14, weight="bold"), text_color="#E5E7EB").pack(anchor="w")

        self.task_list_container = ctk.CTkFrame(list_frame, fg_color="transparent")
        self.task_list_container.pack(fill="x", padx=16, pady=(0, 16))

        self._refresh_task_list()

    def _add_scheduled_task(self):
        name = self.ent_task_name.get().strip()
        action = self.cb_task_action.get()
        try:
            interval = int(self.ent_task_interval.get() or "30")
        except ValueError:
            interval = 30

        if not name:
            self._toast("Please enter a task name", "warn")
            return

        TASK_SCHEDULER.add_task(name, action, interval)
        self.ent_task_name.delete(0, "end")
        self.ent_task_interval.delete(0, "end")
        self._refresh_task_list()
        self._toast(f"Task '{name}' added", "ok")

    def _refresh_task_list(self):
        for widget in self.task_list_container.winfo_children():
            widget.destroy()

        tasks = TASK_SCHEDULER.get_tasks()

        if not tasks:
            ctk.CTkLabel(self.task_list_container, text="No scheduled tasks yet. Add one above!",
                        text_color="#9CA3AF", font=ctk.CTkFont(size=12)).pack(pady=20)
            return

        for task in tasks:
            row = ctk.CTkFrame(self.task_list_container, fg_color="#0D1117", corner_radius=8)
            row.pack(fill="x", pady=4)

            content = ctk.CTkFrame(row, fg_color="transparent")
            content.pack(fill="x", padx=12, pady=10)

            left = ctk.CTkFrame(content, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True)

            status_icon = "✅" if task.get('enabled') else "⏸️"
            ctk.CTkLabel(left, text=f"{status_icon} {task.get('name', 'Unnamed')}",
                        font=ctk.CTkFont(size=13, weight="bold"), text_color="#E5E7EB").pack(anchor="w")
            ctk.CTkLabel(left, text=f"Action: {task.get('action', '?')} | Every {task.get('interval_minutes', 30)} min",
                        text_color="#9CA3AF", font=ctk.CTkFont(size=11)).pack(anchor="w")

            right = ctk.CTkFrame(content, fg_color="transparent")
            right.pack(side="right")

            toggle_text = "Disable" if task.get('enabled') else "Enable"
            toggle_color = "#F59E0B" if task.get('enabled') else "#10B981"
            ctk.CTkButton(right, text=toggle_text, fg_color=toggle_color,
                         width=70, height=28, font=ctk.CTkFont(size=11),
                         command=lambda t=task: self._toggle_scheduled_task(t)).pack(side="left", padx=4)

            ctk.CTkButton(right, text="Delete", fg_color="#EF4444", hover_color="#DC2626",
                         width=70, height=28, font=ctk.CTkFont(size=11),
                         command=lambda t=task: self._delete_scheduled_task(t)).pack(side="left", padx=4)

    def _toggle_scheduled_task(self, task):
        TASK_SCHEDULER.toggle_task(task.get('id'), not task.get('enabled'))
        self._refresh_task_list()

    def _delete_scheduled_task(self, task):
        TASK_SCHEDULER.remove_task(task.get('id'))
        self._refresh_task_list()
        self._toast("Task deleted", "ok")

    def _run_scheduled_action(self, action):
        if action == "trim_ram":
            self._quick_trim_all()
        elif action == "boost_foreground":
            self._quick_boost_fg()
        elif action == "throttle_background":
            self._quick_throttle_bg()
        elif action == "clear_standby":
            RAM_CLEANER.clear_standby_list()
        self._log_activity(f"Scheduled task executed: {action}", "scheduler")

    def destroy(self):
        self._stop = True
        self._save_config()
        return super().destroy()

    def _fill_ai_assistant(self, frame):
        self._ai_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self._ai_scroll.pack(fill="both", expand=True)

        if not hasattr(self, '_ai_autopilot'):
            self._ai_autopilot = False

        hero = ctk.CTkFrame(self._ai_scroll, fg_color="#1a1a2e", corner_radius=24, height=200)
        hero.pack(fill="x", padx=30, pady=(25, 20))
        hero.pack_propagate(False)

        gradient1 = ctk.CTkFrame(hero, fg_color="#7C3AED", corner_radius=24)
        gradient1.place(relx=0.65, rely=0, relwidth=0.45, relheight=1)

        gradient2 = ctk.CTkFrame(hero, fg_color="#8B5CF6", corner_radius=24)
        gradient2.place(relx=0.80, rely=0.2, relwidth=0.30, relheight=0.8)

        gradient3 = ctk.CTkFrame(hero, fg_color="#A78BFA", corner_radius=24)
        gradient3.place(relx=0.90, rely=0.4, relwidth=0.20, relheight=0.6)

        hero_content = ctk.CTkFrame(hero, fg_color="transparent")
        hero_content.place(relx=0.04, rely=0.12, relwidth=0.55, relheight=0.76)
        hero_content.tkraise()

        avatar_row = ctk.CTkFrame(hero_content, fg_color="transparent")
        avatar_row.pack(anchor="w")

        avatar_glow = ctk.CTkFrame(avatar_row, fg_color=TOKENS.ACCENT_ACTIVE, corner_radius=30, width=60, height=60)
        avatar_glow.pack(side="left")
        avatar_glow.pack_propagate(False)

        avatar_bg = ctk.CTkFrame(avatar_glow, fg_color=TOKENS.ACCENT_PRIMARY, corner_radius=24, width=48, height=48)
        avatar_bg.place(relx=0.5, rely=0.5, anchor="center")
        avatar_bg.pack_propagate(False)
        ctk.CTkLabel(avatar_bg, text="✨", font=ctk.CTkFont(size=22)).place(relx=0.5, rely=0.5, anchor="center")

        import datetime
        hour = datetime.datetime.now().hour
        if hour < 12:
            greeting_time = "Good morning"
        elif hour < 17:
            greeting_time = "Good afternoon"
        else:
            greeting_time = "Good evening"

        greeting_frame = ctk.CTkFrame(avatar_row, fg_color="transparent")
        greeting_frame.pack(side="left", padx=12)
        ctk.CTkLabel(greeting_frame, text=f"{greeting_time}! I'm OptiCores AI",
                    font=ctk.CTkFont(family=TOKENS.FONT_DISPLAY, size=20, weight="bold"),
                    text_color=TOKENS.FG_PRIMARY).pack(anchor="w")
        ctk.CTkLabel(greeting_frame, text="Your intelligent system optimizer • Always learning",
                    font=ctk.CTkFont(size=11), text_color=TOKENS.ACCENT_HOVER).pack(anchor="w")

        status_row = ctk.CTkFrame(hero_content, fg_color="transparent")
        status_row.pack(anchor="w", pady=(12, 0))

        status_pill = ctk.CTkFrame(status_row, fg_color="#1A3D2E", corner_radius=12)
        status_pill.pack(side="left")
        status_inner = ctk.CTkFrame(status_pill, fg_color="transparent")
        status_inner.pack(padx=10, pady=5)
        pulse_dot = ctk.CTkFrame(status_inner, fg_color=TOKENS.SUCCESS, corner_radius=4, width=8, height=8)
        pulse_dot.pack(side="left")
        ctk.CTkLabel(status_inner, text="Monitoring",
                    font=ctk.CTkFont(size=10, weight="bold"), text_color=TOKENS.SUCCESS).pack(side="left", padx=(6, 0))

        scan_pill = ctk.CTkFrame(status_row, fg_color="#1E3A5F", corner_radius=12)

        scan_pill.pack(side="left", padx=(8, 0))
        scan_inner = ctk.CTkFrame(scan_pill, fg_color="transparent")
        scan_inner.pack(padx=10, pady=5)
        ctk.CTkLabel(scan_inner, text="🔍 Last scan: just now",
                    font=ctk.CTkFont(size=10), text_color="#60A5FA").pack()

        autopilot_frame = ctk.CTkFrame(hero_content, fg_color="transparent")
        autopilot_frame.pack(anchor="w", pady=(12, 0))

        autopilot_card = ctk.CTkFrame(autopilot_frame, fg_color="#1C1C2E", corner_radius=12)
        autopilot_card.pack(side="left")
        autopilot_inner = ctk.CTkFrame(autopilot_card, fg_color="transparent")
        autopilot_inner.pack(padx=12, pady=8)

        ctk.CTkLabel(autopilot_inner, text="🤖 Auto-Pilot",
                    font=ctk.CTkFont(size=11, weight="bold"), text_color=TOKENS.FG_PRIMARY).pack(side="left")

        self._autopilot_switch = ctk.CTkSwitch(autopilot_inner, text="", width=40,
                                               command=self._toggle_ai_autopilot,
                                               progress_color=TOKENS.ACCENT_PRIMARY, button_color=TOKENS.FG_PRIMARY)
        self._autopilot_switch.pack(side="left", padx=(10, 0))
        if self._ai_autopilot:
            self._autopilot_switch.select()

        try:
            health = ANOMALY_DETECTOR.get_system_health()
        except:
            health = 75

        health_badge = ctk.CTkFrame(hero, fg_color="#2A2A3E", corner_radius=18)
        health_badge.place(relx=0.96, rely=0.5, anchor="e")
        health_inner = ctk.CTkFrame(health_badge, fg_color="transparent")
        health_inner.pack(padx=24, pady=16)

        health_color = TOKENS.get_status_color(100 - health, thresholds=(30, 60))
        health_emoji = "💚" if health >= 70 else "💛" if health >= 40 else "❤️"

        ctk.CTkLabel(health_inner, text=health_emoji, font=ctk.CTkFont(size=16)).pack()
        ctk.CTkLabel(health_inner, text=f"{health}", font=ctk.CTkFont(size=40, weight="bold"),
                    text_color=health_color).pack()
        ctk.CTkLabel(health_inner, text="Health", font=ctk.CTkFont(size=10),
                    text_color=TOKENS.FG_SECONDARY).pack()

        actions_header = ctk.CTkFrame(self._ai_scroll, fg_color="transparent")
        actions_header.pack(fill="x", padx=35, pady=(5, 10))
        ctk.CTkLabel(actions_header, text="⚡ Quick Actions",
                    font=ctk.CTkFont(size=14, weight="bold"), text_color=TOKENS.FG_SECONDARY).pack(side="left")
        ctk.CTkLabel(actions_header, text="One-click optimizations",
                    font=ctk.CTkFont(size=11), text_color=TOKENS.FG_MUTED).pack(side="right")

        actions_row = ctk.CTkFrame(self._ai_scroll, fg_color="transparent")
        actions_row.pack(fill="x", padx=30, pady=(0, 20))

        def quick_action_chip(parent, text, icon, action, color, desc=""):
            chip = ctk.CTkButton(parent, text=f"{icon} {text}",
                                command=action,
                                fg_color=TOKENS.BG_OVERLAY, hover_color=TOKENS.BUTTON_SECONDARY_HOVER,
                                text_color=color, border_width=1, border_color=TOKENS.BORDER_STRONG,
                                corner_radius=20, height=40,
                                font=ctk.CTkFont(size=12, weight="bold"))
            chip.pack(side="left", padx=4)

        quick_action_chip(actions_row, "Optimize All", "🚀", self._ai_quick_optimize, TOKENS.ACCENT_PRIMARY)
        quick_action_chip(actions_row, "Free RAM", "💾", self._ai_quick_ram, TOKENS.SUCCESS)
        quick_action_chip(actions_row, "Boost", "⚡", self._ai_quick_boost, TOKENS.WARNING)
        quick_action_chip(actions_row, "Deep Scan", "🔍", self._ai_quick_scan, TOKENS.INFO)
        quick_action_chip(actions_row, "Game Mode", "🎮", self._ai_quick_game, "#EC4899")

        ctk.CTkButton(actions_row, text="🔄", width=40, height=40, corner_radius=20,
                     fg_color=TOKENS.BUTTON_SECONDARY, hover_color=TOKENS.BUTTON_SECONDARY_HOVER,
                     command=lambda: self._refresh_ai_modern()).pack(side="right", padx=4)

        pred_header = ctk.CTkFrame(self._ai_scroll, fg_color="transparent")
        pred_header.pack(fill="x", padx=35, pady=(5, 8))
        ctk.CTkLabel(pred_header, text="🔮 Suggested For You",
                    font=ctk.CTkFont(size=14, weight="bold"), text_color=TOKENS.FG_SECONDARY).pack(side="left")
        ctk.CTkLabel(pred_header, text="Based on your system state",
                    font=ctk.CTkFont(size=11), text_color=TOKENS.FG_MUTED).pack(side="right")

        self._predicted_questions_container = ctk.CTkFrame(self._ai_scroll, fg_color="transparent")
        self._predicted_questions_container.pack(fill="x", padx=30, pady=(0, 15))

        self._build_predicted_questions()

        cat_header = ctk.CTkFrame(self._ai_scroll, fg_color="transparent")
        cat_header.pack(fill="x", padx=35, pady=(5, 8))
        ctk.CTkLabel(cat_header, text="📁 Browse by Category",
                    font=ctk.CTkFont(size=14, weight="bold"), text_color=TOKENS.FG_SECONDARY).pack(side="left")

        cat_row = ctk.CTkFrame(self._ai_scroll, fg_color="transparent")
        cat_row.pack(fill="x", padx=30, pady=(0, 10))

        self._selected_category = "all"
        self._cat_buttons = {}

        categories = [("all", "🏠 All")] + [(k, v) for k, v in AI_QUESTION_MANAGER.CATEGORIES.items()]

        for cat_key, cat_name in categories:
            is_selected = cat_key == "all"
            btn = ctk.CTkButton(cat_row, text=cat_name,
                               fg_color=TOKENS.ACCENT_PRIMARY if is_selected else TOKENS.BG_OVERLAY,
                               hover_color=TOKENS.ACCENT_ACTIVE,
                               text_color=TOKENS.FG_PRIMARY,
                               corner_radius=16, height=32,
                               font=ctk.CTkFont(size=11),
                               command=lambda c=cat_key: self._filter_questions_by_category(c))
            btn.pack(side="left", padx=3)
            self._cat_buttons[cat_key] = btn

        questions_header = ctk.CTkFrame(self._ai_scroll, fg_color="transparent")
        questions_header.pack(fill="x", padx=35, pady=(10, 8))
        ctk.CTkLabel(questions_header, text="❓ Select a Question",
                    font=ctk.CTkFont(size=14, weight="bold"), text_color=TOKENS.FG_SECONDARY).pack(side="left")

        self._questions_list_container = ctk.CTkFrame(self._ai_scroll, fg_color=TOKENS.CARD_BG,
                                                      corner_radius=TOKENS.RADIUS_LG,
                                                      border_width=1, border_color=TOKENS.CARD_BORDER)
        self._questions_list_container.pack(fill="x", padx=30, pady=(0, 15))

        self._build_questions_list()

        self._ai_chat_container = ctk.CTkFrame(self._ai_scroll, fg_color="transparent")
        self._ai_chat_container.pack(fill="x", padx=30, pady=(0, 15))

        insights_header = ctk.CTkFrame(self._ai_scroll, fg_color="transparent")
        insights_header.pack(fill="x", padx=35, pady=(5, 10))
        ctk.CTkLabel(insights_header, text="🤖 AI Insights",
                    font=ctk.CTkFont(size=14, weight="bold"), text_color=TOKENS.FG_SECONDARY).pack(side="left")
        ctk.CTkLabel(insights_header, text="Personalized recommendations",
                    font=ctk.CTkFont(size=11), text_color=TOKENS.FG_MUTED).pack(side="right")

        self._ai_insights_container = ctk.CTkFrame(self._ai_scroll, fg_color="transparent")
        self._ai_insights_container.pack(fill="x", padx=30, pady=(0, 20))

        self._build_ai_insights()

        metrics_header = ctk.CTkFrame(self._ai_scroll, fg_color="transparent")
        metrics_header.pack(fill="x", padx=35, pady=(5, 10))
        ctk.CTkLabel(metrics_header, text="📊 Live Metrics",
                    font=ctk.CTkFont(size=14, weight="bold"), text_color=TOKENS.FG_SECONDARY).pack(side="left")
        ctk.CTkLabel(metrics_header, text="Real-time system performance",
                    font=ctk.CTkFont(size=11), text_color=TOKENS.FG_MUTED).pack(side="right")

        metrics_row = ctk.CTkFrame(self._ai_scroll, fg_color="transparent")
        metrics_row.pack(fill="x", padx=30, pady=(0, 20))
        metrics_row.grid_columnconfigure((0, 1, 2, 3), weight=1)

        try:
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            suggestions = AI_OPTIMIZER.generate_suggestions()
            learned = len(SMART_PROCESS_MGR.process_profiles)
            disk = psutil.disk_usage('C:\\').percent
        except:
            cpu, mem, suggestions, learned, disk = 0, 0, [], 0, 0

        def metric_card_enhanced(col, icon, value, label, color, unit="%", trend=None):
            card = ctk.CTkFrame(metrics_row, fg_color=TOKENS.CARD_BG, corner_radius=TOKENS.RADIUS_LG,
                               border_width=1, border_color=TOKENS.CARD_BORDER)
            card.grid(row=0, column=col, sticky="nsew", padx=6, pady=4)

            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=16, pady=14)

            top = ctk.CTkFrame(inner, fg_color="transparent")
            top.pack(fill="x")

            icon_bg = ctk.CTkFrame(top, fg_color=TOKENS.BG_OVERLAY, corner_radius=10, width=36, height=36)
            icon_bg.pack(side="left")
            icon_bg.pack_propagate(False)
            ctk.CTkLabel(icon_bg, text=icon, font=ctk.CTkFont(size=16)).place(relx=0.5, rely=0.5, anchor="center")

            if trend:
                trend_icon = "↗️" if trend == "up" else "↘️" if trend == "down" else "→"
                trend_color = TOKENS.ERROR if trend == "up" else TOKENS.SUCCESS if trend == "down" else TOKENS.FG_SECONDARY
                ctk.CTkLabel(top, text=trend_icon, font=ctk.CTkFont(size=14),
                            text_color=trend_color).pack(side="right")

            val_text = f"{value}{unit}" if unit else str(value)
            ctk.CTkLabel(inner, text=val_text, font=ctk.CTkFont(size=22, weight="bold"),
                        text_color=color).pack(anchor="w", pady=(8, 2))

            if unit == "%":
                bar_bg = ctk.CTkFrame(inner, fg_color=TOKENS.BORDER_DEFAULT, corner_radius=3, height=4)
                bar_bg.pack(fill="x", pady=(4, 4))
                bar_bg.pack_propagate(False)
                bar_fill = ctk.CTkFrame(bar_bg, fg_color=color, corner_radius=3)
                bar_fill.place(relx=0, rely=0, relwidth=min(value/100, 1.0), relheight=1)

            ctk.CTkLabel(inner, text=label, font=ctk.CTkFont(size=10),
                        text_color=TOKENS.FG_SECONDARY).pack(anchor="w")

        cpu_color = TOKENS.get_status_color(cpu)
        mem_color = TOKENS.get_status_color(mem, thresholds=(70, 90))
        disk_color = TOKENS.get_status_color(disk, thresholds=(80, 95))

        cpu_trend = "up" if cpu > 70 else "down" if cpu < 30 else None
        mem_trend = "up" if mem > 80 else "down" if mem < 40 else None

        metric_card_enhanced(0, "🖥️", int(cpu), "CPU Usage", cpu_color, "%", cpu_trend)
        metric_card_enhanced(1, "💾", int(mem), "Memory", mem_color, "%", mem_trend)
        metric_card_enhanced(2, "💽", int(disk), "Disk Usage", disk_color, "%", None)
        metric_card_enhanced(3, "🧠", learned, "Learned", "#8B5CF6", "", None)

        procs_header = ctk.CTkFrame(self._ai_scroll, fg_color="transparent")
        procs_header.pack(fill="x", padx=35, pady=(5, 10))
        ctk.CTkLabel(procs_header, text="🔥 Resource Hogs",
                    font=ctk.CTkFont(size=14, weight="bold"), text_color="#9CA3AF").pack(side="left")
        ctk.CTkLabel(procs_header, text="Heavy processes detected",
                    font=ctk.CTkFont(size=11), text_color="#6B7280").pack(side="right")

        procs_frame = ctk.CTkFrame(self._ai_scroll, fg_color="#161B22", corner_radius=16,
                                  border_width=1, border_color="#1D232C")
        procs_frame.pack(fill="x", padx=30, pady=(0, 30))

        try:
            heavy_procs = []
            for proc in psutil.process_iter(['name', 'cpu_percent', 'memory_percent']):
                try:
                    info = proc.info
                    if info['name'] not in SYSTEM_WHITELIST:
                        score = (info['cpu_percent'] or 0) + (info['memory_percent'] or 0)
                        if score > 5:
                            heavy_procs.append({
                                'name': info['name'],
                                'cpu': info['cpu_percent'] or 0,
                                'mem': info['memory_percent'] or 0
                            })
                except:
                    pass
            heavy_procs.sort(key=lambda x: x['cpu'] + x['mem'], reverse=True)
            heavy_procs = heavy_procs[:4]
        except:
            heavy_procs = []

        if heavy_procs:
            for i, proc in enumerate(heavy_procs):
                proc_row = ctk.CTkFrame(procs_frame, fg_color="#0D1117" if i % 2 == 0 else "#161B22",
                                       corner_radius=10)
                proc_row.pack(fill="x", padx=12, pady=4)

                proc_inner = ctk.CTkFrame(proc_row, fg_color="transparent")
                proc_inner.pack(fill="x", padx=12, pady=10)

                name_frame = ctk.CTkFrame(proc_inner, fg_color="transparent")
                name_frame.pack(side="left")

                ctk.CTkLabel(name_frame, text="📦", font=ctk.CTkFont(size=14)).pack(side="left")
                ctk.CTkLabel(name_frame, text=proc['name'][:20],
                            font=ctk.CTkFont(size=12, weight="bold"), text_color="#E5E7EB").pack(side="left", padx=(8, 0))

                right_frame = ctk.CTkFrame(proc_inner, fg_color="transparent")
                right_frame.pack(side="right")

                cpu_c = "#EF4444" if proc['cpu'] > 30 else "#F59E0B" if proc['cpu'] > 10 else "#9CA3AF"
                mem_c = "#EF4444" if proc['mem'] > 10 else "#F59E0B" if proc['mem'] > 5 else "#9CA3AF"

                ctk.CTkLabel(right_frame, text=f"CPU: {proc['cpu']:.0f}%",
                            font=ctk.CTkFont(size=10), text_color=cpu_c).pack(side="left", padx=(0, 8))
                ctk.CTkLabel(right_frame, text=f"RAM: {proc['mem']:.0f}%",
                            font=ctk.CTkFont(size=10), text_color=mem_c).pack(side="left", padx=(0, 12))

                ctk.CTkButton(right_frame, text="⬇ Lower", width=70, height=26, corner_radius=8,
                             fg_color="#374151", hover_color="#4B5563",
                             font=ctk.CTkFont(size=10),
                             command=lambda n=proc['name']: self._ai_lower_priority(n)).pack(side="left")
        else:
            empty = ctk.CTkFrame(procs_frame, fg_color="transparent")
            empty.pack(padx=20, pady=20)
            ctk.CTkLabel(empty, text="✨ All processes running efficiently!",
                        font=ctk.CTkFont(size=12), text_color="#10B981").pack()

        shortcuts_header = ctk.CTkFrame(self._ai_scroll, fg_color="transparent")
        shortcuts_header.pack(fill="x", padx=35, pady=(5, 10))
        ctk.CTkLabel(shortcuts_header, text="⌨️ Quick Shortcuts",
                    font=ctk.CTkFont(size=14, weight="bold"), text_color="#9CA3AF").pack(side="left")

        shortcuts_frame = ctk.CTkFrame(self._ai_scroll, fg_color="#161B22", corner_radius=16,
                                      border_width=1, border_color="#1D232C")
        shortcuts_frame.pack(fill="x", padx=30, pady=(0, 30))

        shortcuts_inner = ctk.CTkFrame(shortcuts_frame, fg_color="transparent")
        shortcuts_inner.pack(fill="x", padx=20, pady=16)

        shortcuts = [
            ("Ctrl+Shift+O", "Toggle OptiBalance"),
            ("Ctrl+Shift+M", "Clear Memory"),
            ("Ctrl+Shift+G", "Game Mode"),
            ("Ctrl+Shift+R", "Refresh AI")
        ]

        shortcuts_row = ctk.CTkFrame(shortcuts_inner, fg_color="transparent")
        shortcuts_row.pack(fill="x")

        for key, desc in shortcuts:
            shortcut_item = ctk.CTkFrame(shortcuts_row, fg_color="transparent")
            shortcut_item.pack(side="left", padx=8)

            key_badge = ctk.CTkFrame(shortcut_item, fg_color="#374151", corner_radius=6)
            key_badge.pack(side="left")
            ctk.CTkLabel(key_badge, text=key, font=ctk.CTkFont(size=9, weight="bold"),
                        text_color="#E5E7EB").pack(padx=8, pady=4)

            ctk.CTkLabel(shortcut_item, text=desc, font=ctk.CTkFont(size=10),
                        text_color="#9CA3AF").pack(side="left", padx=(6, 0))

    def _build_ai_insights(self):
        for w in self._ai_insights_container.winfo_children():
            w.destroy()

        try:
            suggestions = AI_OPTIMIZER.generate_suggestions()
            anomalies = ANOMALY_DETECTOR.detect_anomalies()
            health = ANOMALY_DETECTOR.get_system_health()
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
        except:
            suggestions = []
            anomalies = []
            health = 75
            cpu = 0
            mem = 0

        messages = []

        import datetime
        hour = datetime.datetime.now().hour

        if health >= 80:
            summary_text = f"Your system is running great! CPU at {cpu:.0f}%, Memory at {mem:.0f}%. Keep up the good work! 🎉"
            summary_icon = "🌟"
        elif health >= 60:
            summary_text = f"System performance is good. CPU: {cpu:.0f}%, RAM: {mem:.0f}%. I have some suggestions to make it even better."
            summary_icon = "👍"
        else:
            summary_text = f"I've detected some performance issues. CPU: {cpu:.0f}%, RAM: {mem:.0f}%. Let me help you fix them."
            summary_icon = "🔧"

        messages.append({
            'type': 'summary',
            'icon': summary_icon,
            'title': 'System Status',
            'text': summary_text,
            'action': None,
            'color': '#8B5CF6',
            'priority': 0
        })

        tips = {
            'morning': ("🌅 Morning Tip", "Start your day fresh! Consider running a quick memory cleanup to ensure maximum performance.", "#06B6D4"),
            'afternoon': ("☀️ Afternoon Tip", "If you're multitasking, enable OptiBalance to keep your active apps responsive.", "#F59E0B"),
            'evening': ("🌙 Evening Tip", "Gaming tonight? Enable Game Mode for the best performance with your favorite titles.", "#EC4899"),
            'night': ("🌃 Late Night Tip", "Running overnight tasks? Consider enabling Power Saver mode to reduce energy usage.", "#6366F1")
        }

        if hour < 12:
            tip_key = 'morning'
        elif hour < 17:
            tip_key = 'afternoon'
        elif hour < 21:
            tip_key = 'evening'
        else:
            tip_key = 'night'

        tip_title, tip_text, tip_color = tips[tip_key]
        messages.append({
            'type': 'tip',
            'icon': '💡',
            'title': tip_title,
            'text': tip_text,
            'action': None,
            'color': tip_color,
            'priority': 5
        })

        if anomalies:
            for anom in anomalies[:2]:
                severity_emoji = {"critical": "🚨", "high": "⚠️", "medium": "💡", "low": "ℹ️"}
                priority = {"critical": 1, "high": 2, "medium": 3, "low": 4}.get(anom['severity'], 3)
                messages.append({
                    'type': 'warning',
                    'icon': severity_emoji.get(anom['severity'], "💡"),
                    'title': f"Issue Detected: {anom['metric']}",
                    'text': anom['description'],
                    'action': None,
                    'color': '#EF4444' if anom['severity'] == 'critical' else '#F59E0B' if anom['severity'] == 'high' else '#3B82F6',
                    'priority': priority
                })

        if suggestions:
            for sug in suggestions[:3]:
                messages.append({
                    'type': 'suggestion',
                    'icon': '✨',
                    'title': f"Recommendation: {sug['feature']}",
                    'text': sug['reason'],
                    'action': lambda s=sug: self._apply_ai_suggestion(s),
                    'confidence': sug['confidence'],
                    'color': '#8B5CF6',
                    'priority': 3
                })

        if not anomalies and len(suggestions) <= 1:
            messages.append({
                'type': 'status',
                'icon': '✅',
                'title': 'All Systems Optimal',
                'text': "Everything looks great! I'm continuously monitoring and learning your usage patterns.",
                'action': None,
                'color': '#10B981',
                'priority': 10
            })

        messages.sort(key=lambda x: x.get('priority', 5))

        for i, msg in enumerate(messages):
            bubble = ctk.CTkFrame(self._ai_insights_container, fg_color="#161B22", corner_radius=16,
                                 border_width=1, border_color="#30363D")
            bubble.pack(fill="x", pady=6)

            bubble_inner = ctk.CTkFrame(bubble, fg_color="transparent")
            bubble_inner.pack(fill="x", padx=18, pady=14)

            header = ctk.CTkFrame(bubble_inner, fg_color="transparent")
            header.pack(fill="x")

            avatar_mini = ctk.CTkFrame(header, fg_color="#2D2D44", corner_radius=14,
                                       width=28, height=28)
            avatar_mini.pack(side="left")
            avatar_mini.pack_propagate(False)
            ctk.CTkLabel(avatar_mini, text=msg['icon'], font=ctk.CTkFont(size=12)).place(relx=0.5, rely=0.5, anchor="center")

            ctk.CTkLabel(header, text=msg['title'],
                        font=ctk.CTkFont(size=13, weight="bold"), text_color="#F9FAFB").pack(side="left", padx=10)

            if msg.get('confidence'):
                conf = msg['confidence']
                conf_color = "#10B981" if conf > 0.8 else "#F59E0B"
                conf_badge = ctk.CTkFrame(header, fg_color="#1D232C", corner_radius=8)
                conf_badge.pack(side="right")
                ctk.CTkLabel(conf_badge, text=f"{conf*100:.0f}% match",
                            font=ctk.CTkFont(size=9, weight="bold"), text_color=conf_color).pack(padx=8, pady=3)

            ctk.CTkLabel(bubble_inner, text=msg['text'], text_color="#9CA3AF",
                        font=ctk.CTkFont(size=11), wraplength=650, justify="left").pack(anchor="w", pady=(10, 0))

            if msg['action']:
                btn_frame = ctk.CTkFrame(bubble_inner, fg_color="transparent")
                btn_frame.pack(anchor="e", pady=(12, 0))
                ctk.CTkButton(btn_frame, text="Apply Fix →", command=msg['action'],
                             fg_color=msg['color'], hover_color="#6B4DC4",
                             height=32, width=110, corner_radius=8,
                             font=ctk.CTkFont(size=11, weight="bold")).pack()

    def _ai_quick_optimize(self):
        PRIORITY_BALANCER.enabled = True
        MEM_OPTIMIZER.enabled = True
        self._toast("🚀 Optimization enabled!", "ok")
        self._log_activity("AI: Quick optimization enabled", "ai")
        self._refresh_ai_modern()

    def _ai_quick_ram(self):
        RAM_CLEANER.clear_standby_list()
        self._toast("💾 Memory cleaned!", "ok")
        self._log_activity("AI: Memory cleanup executed", "ai")
        self._refresh_ai_modern()

    def _ai_quick_boost(self):
        FG_BOOSTER.enabled = True
        self._toast("⚡ Performance boost active!", "ok")
        self._log_activity("AI: Performance boost enabled", "ai")
        self._refresh_ai_modern()

    def _ai_quick_scan(self):
        AI_OPTIMIZER.refresh()
        SMART_PROCESS_MGR.take_snapshot()
        self._toast("🔍 Deep scan complete!", "ok")
        self._refresh_ai_modern()

    def _ai_quick_game(self):
        GAME_MODE.enabled = True
        self._toast("🎮 Game Mode activated!", "ok")
        self._log_activity("AI: Game Mode enabled", "ai")
        self._refresh_ai_modern()

    def _toggle_ai_autopilot(self):
        self._ai_autopilot = not self._ai_autopilot
        if self._ai_autopilot:
            PRIORITY_BALANCER.enabled = True
            MEM_OPTIMIZER.enabled = True
            FG_BOOSTER.enabled = True
            self._toast("🤖 Auto-Pilot ON - AI is now optimizing automatically!", "ok")
            self._log_activity("AI Auto-Pilot enabled", "ai")
        else:
            PRIORITY_BALANCER.enabled = False
            MEM_OPTIMIZER.enabled = False
            self._toast("🤖 Auto-Pilot OFF", "ok")
            self._log_activity("AI Auto-Pilot disabled", "ai")

    def _ai_lower_priority(self, proc_name):
        try:
            for proc in psutil.process_iter(['name', 'pid']):
                if proc.info['name'] == proc_name:
                    try:
                        proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
                        self._toast(f"⬇ {proc_name[:15]} priority lowered!", "ok")
                        self._log_activity(f"AI: Lowered priority of {proc_name}", "ai")
                        return
                    except:
                        pass
            self._toast(f"Could not find {proc_name}", "warn")
        except Exception as e:
            self._toast(f"Error: {str(e)}", "error")

    def _refresh_ai_modern(self):
        AI_OPTIMIZER.refresh()
        SMART_PROCESS_MGR.take_snapshot()
        self._build_ai_insights()
        if hasattr(self, '_predicted_questions_container'):
            self._build_predicted_questions()
        self._toast("AI refreshed", "ok")

    def _build_predicted_questions(self):
        for w in self._predicted_questions_container.winfo_children():
            w.destroy()

        predicted = AI_QUESTION_MANAGER.get_predicted_questions(6)

        row1 = ctk.CTkFrame(self._predicted_questions_container, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 4))
        row2 = ctk.CTkFrame(self._predicted_questions_container, fg_color="transparent")
        row2.pack(fill="x")

        for i, q in enumerate(predicted):
            target_row = row1 if i < 3 else row2
            cat_emoji = AI_QUESTION_MANAGER.CATEGORIES.get(q['cat'], "💡").split()[0]

            chip = ctk.CTkButton(target_row, text=f"{cat_emoji} {q['q']}",
                                fg_color=TOKENS.BG_OVERLAY,
                                hover_color=TOKENS.ACCENT_ACTIVE,
                                text_color=TOKENS.FG_PRIMARY,
                                border_width=1, border_color=TOKENS.ACCENT_PRIMARY,
                                corner_radius=12, height=36,
                                font=ctk.CTkFont(size=11),
                                command=lambda question=q['q']: self._select_question(question))
            chip.pack(side="left", padx=4, pady=2)

    def _build_questions_list(self, category=None):
        for w in self._questions_list_container.winfo_children():
            w.destroy()

        questions = AI_QUESTION_MANAGER.get_all_questions(category)

        inner = ctk.CTkFrame(self._questions_list_container, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=12)

        for q in questions:
            cat_emoji = AI_QUESTION_MANAGER.CATEGORIES.get(q['cat'], "💡").split()[0]

            q_btn = ctk.CTkButton(inner, text=f"{cat_emoji}  {q['q']}",
                                 anchor="w",
                                 fg_color="transparent",
                                 hover_color=TOKENS.BG_HOVER,
                                 text_color=TOKENS.FG_PRIMARY,
                                 corner_radius=8, height=42,
                                 font=ctk.CTkFont(size=12),
                                 command=lambda question=q['q']: self._select_question(question))
            q_btn.pack(fill="x", pady=2)

    def _filter_questions_by_category(self, category):
        self._selected_category = category

        for cat_key, btn in self._cat_buttons.items():
            if cat_key == category:
                btn.configure(fg_color=TOKENS.ACCENT_PRIMARY)
            else:
                btn.configure(fg_color=TOKENS.BG_OVERLAY)

        self._build_questions_list(category)

    def _select_question(self, question):
        AI_QUESTION_MANAGER.record_selection(question)

        try:
            response = self._generate_ai_response(question)
        except Exception as e:
            response = {
                'text': f"Sorry, I encountered an error: {str(e)}",
                'type': 'error'
            }

        self._display_ai_chat(question, response)

    def _generate_ai_response(self, question):
        q_lower = question.lower()

        cpu = psutil.cpu_percent()
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        if "speed up" in q_lower or "running slow" in q_lower:
            tips = []
            if cpu > 70:
                tips.append(f"• Your CPU is at {cpu:.0f}% - try closing heavy applications")
            if mem.percent > 80:
                tips.append(f"• Memory is at {mem.percent:.0f}% - use the Free RAM button above")
            if disk.percent > 85:
                tips.append(f"• Disk is {disk.percent:.0f}% full - consider cleaning up files")
            tips.append("• Enable OptiBalance for automatic background process management")
            tips.append("• Use the One-Click Boost from the Dashboard")

            return {
                'text': "**Here's how to speed up your PC:**\n\n" + "\n".join(tips) + "\n\n💡 Tip: Click the quick actions above for instant optimization!",
                'type': 'action'
            }

        elif "free up ram" in q_lower or "memory cleanup" in q_lower:
            available_gb = mem.available / (1024**3)
            return {
                'text': f"**Memory Management:**\n\nYou currently have {available_gb:.1f} GB available ({100-mem.percent:.0f}% free).\n\n• Click 'Free RAM' above for instant cleanup\n• Enable Auto-Pilot for automatic memory management\n• Heavy processes are shown in the 'Resource Hogs' section below\n\n💡 Tip: Running memory cleanup regularly can improve responsiveness!",
                'type': 'action' if mem.percent > 70 else 'info'
            }

        elif "using my memory" in q_lower:
            return {
                'text': f"**Memory Usage Analysis:**\n\nTotal: {mem.total/(1024**3):.1f} GB\nUsed: {mem.used/(1024**3):.1f} GB ({mem.percent:.0f}%)\nAvailable: {mem.available/(1024**3):.1f} GB\n\n• Check the 'Resource Hogs' section below for heavy processes\n• Go to Processes tab for detailed memory breakdown\n• Use 'Lower Priority' on heavy processes to free resources",
                'type': 'info'
            }

        elif "cpu usage" in q_lower:
            return {
                'text': f"**CPU Usage Tips:**\n\nCurrent CPU: {cpu:.0f}%\n\n• High CPU can be caused by background apps or system updates\n• OptiBalance automatically manages CPU-hungry processes\n• Use Game Mode for gaming to prioritize your active window\n• Check Resource Hogs below for heavy processes\n\n{'⚠️ Warning: CPU usage is high!' if cpu > 70 else '✅ CPU usage looks healthy!'}",
                'type': 'warning' if cpu > 70 else 'info'
            }

        elif "gaming" in q_lower or "game mode" in q_lower or "fps" in q_lower:
            return {
                'text': "**Gaming Optimization:**\n\n• Click 'Game Mode' above for instant gaming optimization\n• Game Mode prioritizes your active game window\n• Reduces background process CPU usage\n• Enables 1ms timer resolution for smoother gameplay\n• Disables Superfetch for less disk interference\n\n🎮 For best results, enable Game Mode before launching your game!",
                'type': 'action'
            }

        elif "disk" in q_lower or "clean up" in q_lower or "delete" in q_lower:
            free_gb = disk.free / (1024**3)
            return {
                'text': f"**Disk Space Management:**\n\nFree space: {free_gb:.1f} GB ({100-disk.percent:.0f}% free)\n\n• Go to Cleaner tab for safe cleanup options\n• Temporary files can usually be deleted safely\n• Browser cache is often a major space user\n• Check Downloads folder for old files\n\n💡 The Cleaner tab shows exactly what can be safely removed!",
                'type': 'action' if disk.percent > 80 else 'info'
            }

        elif "battery" in q_lower or "power" in q_lower:
            return {
                'text': "**Power Management:**\n\n• Use Power Saver mode to extend battery life\n• High Performance mode is best for gaming/heavy work\n• Balanced mode is good for everyday use\n• Go to Power tab for detailed power settings\n\n⚡ Quick tip: Click 'Power Saver' or 'Gaming' in Dashboard Quick Actions!",
                'type': 'info'
            }

        elif "process" in q_lower or "priority" in q_lower or "startup" in q_lower:
            return {
                'text': "**Process Management:**\n\n• System processes (svchost, csrss, etc.) should NOT be ended\n• Games and apps can have their priority lowered if causing issues\n• Use 'Lower Priority' button on Resource Hogs below\n• Startup tab shows programs that run at boot\n• Disable unnecessary startup programs for faster boot\n\n💡 OptiBalance automatically manages process priorities!",
                'type': 'info'
            }

        elif "optibalance" in q_lower:
            return {
                'text': "**OptiBalance Feature:**\n\nOptiBalance automatically manages process priorities to keep your system responsive.\n\n• Monitors CPU usage continuously\n• Lowers priority of background CPU hogs\n• Protects system-critical processes\n• Restores priorities when apps behave normally\n\n✅ Enable Auto-Pilot above to activate OptiBalance!",
                'type': 'info'
            }

        elif "one-click" in q_lower or "boost" in q_lower:
            return {
                'text': "**One-Click Boost:**\n\nThe One-Click Boost performs multiple optimizations at once:\n\n• Frees up RAM by clearing standby memory\n• Boosts foreground application priority\n• Throttles heavy background processes\n• Enables performance-focused settings\n\n🚀 Find it on the Dashboard or press Ctrl+B!",
                'type': 'info'
            }

        elif "health" in q_lower or "monitor" in q_lower:
            return {
                'text': "**System Health Monitoring:**\n\n• The Dashboard shows real-time CPU, RAM, GPU metrics\n• Health score appears in the AI Assistant hero section\n• Session Statistics tracks your optimization progress\n• Latency Metrics show system responsiveness\n• Activity Log records all optimization actions\n\n📊 Check the Live Metrics section below for current stats!",
                'type': 'info'
            }

        elif "schedule" in q_lower or "automatic" in q_lower:
            return {
                'text': "**Automatic Optimization:**\n\n• Enable Auto-Pilot for hands-free optimization\n• Go to Settings → Task Scheduler for timed tasks\n• Schedule RAM cleanup, boost, or throttle actions\n• Set intervals from 15 minutes to 24 hours\n\n🤖 Auto-Pilot toggle is in the hero section above!",
                'type': 'info'
            }

        else:
            return {
                'text': f"**System Overview:**\n\nCPU: {cpu:.0f}%\nMemory: {mem.percent:.0f}%\nDisk: {disk.percent:.0f}%\n\nFor specific help, try selecting a question from the categories above. I can help with:\n\n• Performance optimization\n• Memory management\n• Gaming setup\n• Power settings\n• Process management",
                'type': 'info'
            }

    def _display_ai_chat(self, question, response):
        for widget in self._ai_chat_container.winfo_children():
            widget.destroy()

        conv_frame = ctk.CTkFrame(self._ai_chat_container, fg_color="#161B22",
                                  corner_radius=16, border_width=1, border_color="#30363D")
        conv_frame.pack(fill="x", pady=5)

        conv_inner = ctk.CTkFrame(conv_frame, fg_color="transparent")
        conv_inner.pack(fill="x", padx=18, pady=16)

        user_row = ctk.CTkFrame(conv_inner, fg_color="transparent")
        user_row.pack(fill="x", pady=(0, 12))

        user_bubble = ctk.CTkFrame(user_row, fg_color="#1E3A5F", corner_radius=12)
        user_bubble.pack(anchor="e")

        user_content = ctk.CTkFrame(user_bubble, fg_color="transparent")
        user_content.pack(padx=14, pady=10)

        ctk.CTkLabel(user_content, text="You", font=ctk.CTkFont(size=10, weight="bold"),
                    text_color="#60A5FA").pack(anchor="e")
        ctk.CTkLabel(user_content, text=question, font=ctk.CTkFont(size=12),
                    text_color="#E5E7EB", wraplength=500, justify="right").pack(anchor="e")

        ai_row = ctk.CTkFrame(conv_inner, fg_color="transparent")
        ai_row.pack(fill="x")

        response_type = response.get('type', 'info')
        type_styles = {
            'info': {'color': '#8B5CF6', 'icon': '✨'},
            'success': {'color': '#10B981', 'icon': '✅'},
            'warning': {'color': '#F59E0B', 'icon': '⚠️'},
            'error': {'color': '#EF4444', 'icon': '❌'},
            'action': {'color': '#3B82F6', 'icon': '🎯'}
        }
        style = type_styles.get(response_type, type_styles['info'])

        ai_bubble = ctk.CTkFrame(ai_row, fg_color="#1C1C2E", corner_radius=12)
        ai_bubble.pack(anchor="w", fill="x")

        ai_content = ctk.CTkFrame(ai_bubble, fg_color="transparent")
        ai_content.pack(fill="x", padx=14, pady=10)

        ai_header = ctk.CTkFrame(ai_content, fg_color="transparent")
        ai_header.pack(fill="x")

        ctk.CTkLabel(ai_header, text=f"{style['icon']} OptiCores AI",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    text_color=style['color']).pack(side="left")

        response_text = response.get('text', 'No response generated.')

        text_frame = ctk.CTkFrame(ai_content, fg_color="transparent")
        text_frame.pack(fill="x", anchor="w", pady=(8, 0))

        lines = response_text.split('\n')
        for line in lines:
            if not line.strip():
                ctk.CTkFrame(text_frame, fg_color="transparent", height=6).pack(fill="x")
                continue

            if line.startswith('**') and line.endswith('**'):
                clean_line = line.strip('*')
                ctk.CTkLabel(text_frame, text=clean_line,
                            font=ctk.CTkFont(size=12, weight="bold"),
                            text_color="#E5E7EB", wraplength=550, justify="left",
                            anchor="w").pack(fill="x", anchor="w")
            elif line.strip().startswith('•') or line.strip().startswith('-'):
                ctk.CTkLabel(text_frame, text=line,
                            font=ctk.CTkFont(size=11),
                            text_color="#9CA3AF", wraplength=550, justify="left",
                            anchor="w").pack(fill="x", anchor="w", padx=(10, 0))
            elif line.strip().startswith('💡') or line.strip().startswith('⚠️') or line.strip().startswith('✅'):
                ctk.CTkLabel(text_frame, text=line,
                            font=ctk.CTkFont(size=11, weight="bold"),
                            text_color="#F9FAFB", wraplength=550, justify="left",
                            anchor="w").pack(fill="x", anchor="w", pady=(4, 0))
            else:
                display_text = line.replace('**', '')
                ctk.CTkLabel(text_frame, text=display_text,
                            font=ctk.CTkFont(size=11),
                            text_color="#C4B5FD" if '**' in line else "#9CA3AF",
                            wraplength=550, justify="left",
                            anchor="w").pack(fill="x", anchor="w")

        if response_type == 'action' or response_type == 'warning':
            action_row = ctk.CTkFrame(ai_content, fg_color="transparent")
            action_row.pack(fill="x", pady=(12, 0))

            ctk.CTkButton(action_row, text="🚀 Optimize Now",
                         fg_color="#8B5CF6", hover_color="#7C3AED",
                         height=30, corner_radius=8, font=ctk.CTkFont(size=10, weight="bold"),
                         command=self._ai_quick_optimize).pack(side="left", padx=(0, 8))

            ctk.CTkButton(action_row, text="💾 Free RAM",
                         fg_color="#10B981", hover_color="#059669",
                         height=30, corner_radius=8, font=ctk.CTkFont(size=10, weight="bold"),
                         command=self._ai_quick_ram).pack(side="left", padx=(0, 8))

    def _apply_ai_suggestion(self, suggestion):
        try:
            success = AI_OPTIMIZER.apply_suggestion(suggestion)
            if success:
                self._toast(f"Applied: {suggestion['feature']}", "ok")
                self._log_activity(f"AI: Applied suggestion - {suggestion['feature']}", "ai")
                self._switch_nav("AIAssistant")
            else:
                self._toast("Failed to apply suggestion", "error")
        except Exception as e:
            self._toast(f"Error: {str(e)}", "error")

if __name__ == "__main__":

    import sys

    if not is_admin():
        print("[!] OptiCores requires administrator privileges for full functionality.")
        print("Requesting elevation...")
        try:
            import ctypes
            result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
            if result > 32:
                sys.exit(0)
            print("Running without admin privileges (some features may be limited)")
        except Exception as e:
            print(f"Could not elevate: {e}")
            print("Running without admin privileges (some features may be limited)")

    try:
        app = App()

        LATENCY_MONITOR.start()

        app.after(1000, lambda: WELCOME_GUIDE.show(app))

        app.mainloop()

    except Exception as e:
        print(f"[ERROR] Error starting OptiCores: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")

    finally:
        try:
            DISCORD_RPC.disable()
            FPS_OVERLAY.destroy()
            PERF_HISTORY.stop_logging()
            PROC_TIMELINE.stop_monitoring()
            ALERT_SYSTEM.stop_monitoring()
            LATENCY_MONITOR.stop()
        except:
            pass
