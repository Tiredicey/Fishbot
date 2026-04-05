import mss
import pydirectinput
import cv2
import numpy as np
import keyboard
import win32gui
import win32process
import win32api
import threading
import time
import logging
import psutil
import json
import os
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Tuple, Callable

LOG_FILE    = "bot.log"
CONFIG_FILE = "fishbot_config.json"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE)]
)
log = logging.getLogger("FishBot")


@dataclass
class Config:
    cast_hold_ms:           float = 80.0
    cast_timeout_ms:        float = 40000.0
    reel_cooldown_ms:       float = 2500.0
    settle_wait_ms:         float = 3000.0
    qte_interval_ms:        float = 350.0
    qte_keys:               list  = field(default_factory=lambda: ["e", "q", "z", "x"])
    hotkey_start_stop:      str   = "ctrl+shift+s"
    hotkey_exit:            str   = "ctrl+shift+x"
    equip_rod_key:          str   = "0"
    tick_sleep_ms:          float = 50.0
    target_exe:             str   = "RobloxPlayerBeta.exe"

    bobber_hsv_low:         list  = field(default_factory=lambda: [0, 0, 0])
    bobber_hsv_high:        list  = field(default_factory=lambda: [0, 0, 0])
    bobber_min_pixels:      int   = 2
    bobber_max_pixels:      int   = 200
    bobber_calibrated:      bool  = False

    # cyan splash = bite indicator
    splash_hsv_low:         list  = field(default_factory=lambda: [80, 100, 100])
    splash_hsv_high:        list  = field(default_factory=lambda: [100, 255, 255])
    splash_min_pixels:      int   = 20
    splash_calibrated:      bool  = False

    scan_x1_pct:            float = 0.0
    scan_y1_pct:            float = 0.0
    scan_x2_pct:            float = 1.0
    scan_y2_pct:            float = 1.0
    scan_region_set:        bool  = False

    bobber_acquire_frames:  int   = 3
    # consecutive frames splash must be seen to confirm bite
    bite_confirm_frames:    int   = 2

    qte_hsv_low:            list  = field(default_factory=lambda: [0, 0, 0])
    qte_hsv_high:           list  = field(default_factory=lambda: [0, 0, 0])
    qte_min_pixels:         int   = 10
    qte_calibrated:         bool  = False

    def save(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.__dict__, f, indent=2)

    def load(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(self, k):
                    setattr(self, k, v)
        except Exception as e:
            log.warning(f"Config load: {e}")


class FishState(Enum):
    IDLE     = auto()
    EQUIP    = auto()
    CASTING  = auto()
    WAITING  = auto()
    QTE      = auto()
    REELING  = auto()
    COOLDOWN = auto()


STATE_COLORS = {
    FishState.IDLE:     "#777777",
    FishState.EQUIP:    "#ccaa00",
    FishState.CASTING:  "#0099dd",
    FishState.WAITING:  "#00cc55",
    FishState.QTE:      "#ff8800",
    FishState.REELING:  "#ff3333",
    FishState.COOLDOWN: "#7777cc",
}

DARK   = "#1a1a2e"
PANEL  = "#16213e"
CARD   = "#0f3460"
ACCENT = "#e94560"
TEXT   = "#eaeaea"
MUTED  = "#888888"
GREEN  = "#00d26a"
RED    = "#e94560"


class WindowManager:
    def __init__(self, exe_name: str):
        self.exe_name = exe_name
        self._hwnd: Optional[int] = None
        self._cached_rect: Optional[Tuple[int,int,int,int]] = None
        self._rect_ts:  float = 0.0
        self._RECT_TTL: float = 2.0

    def find(self) -> bool:
        found = []
        def cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if self.exe_name.lower() in psutil.Process(pid).name().lower():
                    found.append(hwnd)
            except Exception:
                pass
        win32gui.EnumWindows(cb, None)
        if found:
            self._hwnd = found[0]
            self._cached_rect = None
            rect = win32gui.GetWindowRect(self._hwnd)
            log.info(f"Roblox hwnd={self._hwnd} rect={rect}")
            return True
        log.error(f"Not found: {self.exe_name}")
        return False

    def bring_to_front(self):
        if self._hwnd:
            try:
                win32gui.ShowWindow(self._hwnd, 9)
                win32gui.SetForegroundWindow(self._hwnd)
                time.sleep(0.1)
            except Exception:
                pass

    def is_foreground(self) -> bool:
        try:
            return bool(self._hwnd and win32gui.GetForegroundWindow() == self._hwnd)
        except Exception:
            return False

    def exists(self) -> bool:
        try:
            return bool(self._hwnd and win32gui.IsWindow(self._hwnd))
        except Exception:
            return False

    def get_rect(self) -> Optional[Tuple[int, int, int, int]]:
        if not self._hwnd:
            return None
        now = time.time()
        if self._cached_rect is None or (now - self._rect_ts) > self._RECT_TTL:
            try:
                self._cached_rect = win32gui.GetWindowRect(self._hwnd)
                self._rect_ts     = now
            except Exception:
                return None
        return self._cached_rect


def _grab_frame(sct, wm: WindowManager) -> Optional[np.ndarray]:
    rect = wm.get_rect()
    if not rect:
        return None
    l, t, r, b = rect
    mon   = {"left": l, "top": t,
             "width": max(r - l, 1), "height": max(b - t, 1)}
    raw   = sct.grab(mon)
    frame = np.frombuffer(raw.raw, dtype=np.uint8).reshape(
        (raw.height, raw.width, 4))
    return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)


def _grab_pixel_hsv(x: int, y: int) -> Tuple[np.ndarray, np.ndarray]:
    with mss.mss() as sct:
        mon   = {"left": x - 4, "top": y - 4, "width": 9, "height": 9}
        raw   = sct.grab(mon)
        patch = np.frombuffer(raw.raw, dtype=np.uint8).reshape(
            (raw.height, raw.width, 4))
        bgr = cv2.cvtColor(patch, cv2.COLOR_BGRA2BGR)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        return hsv[4, 4], bgr[4, 4]


def _grab_once(wm: WindowManager) -> Optional[np.ndarray]:
    with mss.mss() as sct:
        return _grab_frame(sct, wm)


class Detector:
    def __init__(self, cfg: Config):
        self.cfg     = cfg
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    def _roi(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        x1 = int(w * self.cfg.scan_x1_pct)
        y1 = int(h * self.cfg.scan_y1_pct)
        x2 = int(w * self.cfg.scan_x2_pct)
        y2 = int(h * self.cfg.scan_y2_pct)
        return frame[y1:y2, x1:x2]

    def _count(self, frame: np.ndarray, lo: list, hi: list) -> int:
        roi  = self._roi(frame)
        hsv  = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv,
                           np.array(lo, dtype=np.uint8),
                           np.array(hi, dtype=np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._kernel)
        return cv2.countNonZero(mask)

    def bobber_pixels(self, frame: np.ndarray) -> int:
        if not self.cfg.bobber_calibrated:
            return -1
        return self._count(frame,
                           self.cfg.bobber_hsv_low,
                           self.cfg.bobber_hsv_high)

    def bobber_visible(self, frame: np.ndarray) -> bool:
        px = self.bobber_pixels(frame)
        return self.cfg.bobber_min_pixels <= px <= self.cfg.bobber_max_pixels

    def splash_pixels(self, frame: np.ndarray) -> int:
        """Count cyan splash pixels — the actual bite indicator."""
        return self._count(frame,
                           self.cfg.splash_hsv_low,
                           self.cfg.splash_hsv_high)

    def splash_visible(self, frame: np.ndarray) -> bool:
        px = self.splash_pixels(frame)
        return px >= self.cfg.splash_min_pixels

    def qte_visible(self, frame: np.ndarray) -> bool:
        if not self.cfg.qte_calibrated:
            return False
        px = self._count(frame, self.cfg.qte_hsv_low, self.cfg.qte_hsv_high)
        return px >= self.cfg.qte_min_pixels

    def save_debug(self, frame: np.ndarray, tag: str):
        try:
            roi = self._roi(frame)
            cv2.imwrite(f"raw_{tag}.png", roi)
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            dbg = roi.copy()
            if self.cfg.bobber_calibrated:
                m = cv2.inRange(hsv,
                                np.array(self.cfg.bobber_hsv_low, dtype=np.uint8),
                                np.array(self.cfg.bobber_hsv_high, dtype=np.uint8))
                dbg[m > 0] = [0, 0, 255]
            # always show splash detection
            m2 = cv2.inRange(hsv,
                             np.array(self.cfg.splash_hsv_low, dtype=np.uint8),
                             np.array(self.cfg.splash_hsv_high, dtype=np.uint8))
            dbg[m2 > 0] = [255, 255, 0]
            if self.cfg.qte_calibrated:
                m3 = cv2.inRange(hsv,
                                 np.array(self.cfg.qte_hsv_low, dtype=np.uint8),
                                 np.array(self.cfg.qte_hsv_high, dtype=np.uint8))
                dbg[m3 > 0] = [0, 255, 255]
            cv2.imwrite(f"debug_{tag}.png", dbg)
            log.info(f"Saved debug_{tag}.png  raw_{tag}.png")
        except Exception as e:
            log.warning(f"Debug save: {e}")


class InputHandler:
    def __init__(self):
        pydirectinput.PAUSE    = 0.0
        pydirectinput.FAILSAFE = False

    def click(self, hold_ms: float = 80.0):
        pydirectinput.mouseDown(button="left")
        time.sleep(max(hold_ms, 10.0) / 1000.0)
        pydirectinput.mouseUp(button="left")
        time.sleep(0.02)

    def tap(self, key: str, hold_ms: float = 60.0):
        key = key.strip().lower()
        if not key:
            return
        try:
            pydirectinput.keyDown(key)
            time.sleep(max(hold_ms, 10.0) / 1000.0)
            pydirectinput.keyUp(key)
            time.sleep(0.02)
        except Exception as e:
            log.warning(f"tap({key}): {e}")


@dataclass
class Stats:
    catches:     int   = 0
    casts:       int   = 0
    timeouts:    int   = 0
    qte_presses: int   = 0
    start_time:  float = field(default_factory=time.time)

    def cph(self) -> float:
        e = (time.time() - self.start_time) / 3600.0
        return self.catches / e if e > 0 else 0.0

    def elapsed_str(self) -> str:
        e = time.time() - self.start_time
        return (f"{int(e//3600):02d}:"
                f"{int((e%3600)//60):02d}:"
                f"{int(e%60):02d}")


class FishBot:
    def __init__(self, cfg: Config, wm: WindowManager,
                 inp: InputHandler, stats: Stats):
        self.cfg   = cfg
        self.wm    = wm
        self.inp   = inp
        self.stats = stats
        self.det   = Detector(cfg)

        self.state       = FishState.IDLE
        self.state_since = time.time()
        self.running     = False
        self._lock       = threading.Lock()
        self._thread: Optional[threading.Thread] = None

        self._acquired      = False
        self._acq_frames    = 0
        self._bite_frames   = 0   # consecutive frames splash seen
        self._debug_saved   = False

        self._last_qte    = 0.0
        self._qte_idx     = 0
        self._qte_start   = 0.0

        self.on_state_change: Optional[Callable] = None
        self.on_log:          Optional[Callable] = None
        self.on_px_update:    Optional[Callable] = None

    def _log(self, msg: str, level: str = "info"):
        getattr(log, level)(msg)
        if self.on_log:
            self.on_log(msg)

    def _elapsed(self) -> float:
        return time.time() - self.state_since

    def _set_state(self, s: FishState):
        self._log(f"{self.state.name} -> {s.name}")
        with self._lock:
            self.state       = s
            self.state_since = time.time()
        self._acquired    = False
        self._acq_frames  = 0
        self._bite_frames = 0
        self._debug_saved = False
        if s == FishState.QTE:
            self._qte_start = time.time()
        if self.on_state_change:
            self.on_state_change(s)

    def start(self):
        self.running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="FishBot")
        self._thread.start()

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        with self._lock:
            self.state = FishState.IDLE
        if self.on_state_change:
            self.on_state_change(FishState.IDLE)

    def _loop(self):
        with mss.mss() as sct:
            while self.running:
                try:
                    self._tick(sct)
                except Exception as e:
                    log.error(f"Tick: {e}", exc_info=True)
                time.sleep(self.cfg.tick_sleep_ms / 1000.0)

    def _grab(self, sct) -> Optional[np.ndarray]:
        return _grab_frame(sct, self.wm)

    def _ensure_fg(self) -> bool:
        if not self.wm.is_foreground():
            self.wm.bring_to_front()
            time.sleep(0.15)
        return self.wm.is_foreground()

    def _do_qte(self):
        now = time.time()
        if now - self._last_qte >= self.cfg.qte_interval_ms / 1000.0:
            if not self.cfg.qte_keys:
                return
            k = self.cfg.qte_keys[self._qte_idx % len(self.cfg.qte_keys)]
            self.inp.tap(k, 60)
            self._qte_idx         += 1
            self._last_qte         = now
            self.stats.qte_presses += 1
            self._log(f"QTE tap: {k}")

    def _tick(self, sct):
        if not self.wm.exists():
            self._log("Roblox closed", "warning")
            self.running = False
            return

        with self._lock:
            cur = self.state

        if cur == FishState.IDLE:
            self._set_state(FishState.EQUIP)

        elif cur == FishState.EQUIP:
            if not self._ensure_fg():
                return
            self.inp.tap(self.cfg.equip_rod_key, 80)
            time.sleep(0.8)
            self._log(f"Rod equipped [{self.cfg.equip_rod_key}]")
            self._set_state(FishState.CASTING)

        elif cur == FishState.CASTING:
            if not self._ensure_fg():
                return
            time.sleep(0.3)
            self.inp.click(self.cfg.cast_hold_ms)
            self.stats.casts += 1
            self._log(f"Cast #{self.stats.casts}")
            time.sleep(self.cfg.settle_wait_ms / 1000.0)
            self._set_state(FishState.WAITING)

        elif cur == FishState.WAITING:
            elapsed = self._elapsed()

            if elapsed > self.cfg.cast_timeout_ms / 1000.0:
                self._log("Timeout - recasting", "warning")
                self.stats.timeouts += 1
                self._set_state(FishState.CASTING)
                return

            frame = self._grab(sct)
            if frame is None:
                return

            if not self._debug_saved and elapsed > 1.0:
                self.det.save_debug(frame, f"cast{self.stats.casts}")
                self._debug_saved = True

            bob_px     = self.det.bobber_pixels(frame)
            splash_px  = self.det.splash_pixels(frame)
            bob_vis    = self.det.bobber_visible(frame)
            splash_vis = self.det.splash_visible(frame)

            if self.on_px_update:
                self.on_px_update(bob_px, splash_px)

            log.debug(f"WAIT bob={bob_px} splash={splash_px} "
                      f"acq={self._acq_frames}/{self.cfg.bobber_acquire_frames} "
                      f"bite={self._bite_frames}/{self.cfg.bite_confirm_frames} "
                      f"acquired={self._acquired}")

            # Phase 1: wait for bobber to appear (confirms cast landed)
            if not self._acquired:
                if bob_vis:
                    self._acq_frames += 1
                    self._log(f"Acquiring bobber {self._acq_frames}/"
                              f"{self.cfg.bobber_acquire_frames} px={bob_px}")
                    if self._acq_frames >= self.cfg.bobber_acquire_frames:
                        self._acquired  = True
                        self._log("Bobber acquired - watching for splash bite")
                else:
                    self._acq_frames = 0
                return  # don't check bite until acquired

            # Phase 2: bobber acquired — detect bite via cyan splash
            # Splash = fish attacking bobber; ignore wave-induced bobber dips
            if splash_vis:
                self._bite_frames += 1
                self._log(f"Splash {self._bite_frames}/"
                          f"{self.cfg.bite_confirm_frames} px={splash_px}")
                if self._bite_frames >= self.cfg.bite_confirm_frames:
                    self._log("BITE detected -> REELING")
                    self._set_state(FishState.REELING)
                    return
            else:
                self._bite_frames = 0

            if self.cfg.qte_calibrated and self.det.qte_visible(frame):
                self._log("QTE detected")
                self._set_state(FishState.QTE)

        elif cur == FishState.QTE:
            if time.time() - self._qte_start > 12.0:
                self._log("QTE timeout -> WAITING")
                self._set_state(FishState.WAITING)
                return

            frame = self._grab(sct)
            if frame is None:
                return

            splash_px  = self.det.splash_pixels(frame)
            splash_vis = self.det.splash_visible(frame)

            if splash_vis:
                self._bite_frames += 1
                if self._bite_frames >= self.cfg.bite_confirm_frames:
                    self._log("BITE during QTE -> REELING")
                    self._set_state(FishState.REELING)
                    return
            else:
                self._bite_frames = 0

            if self.cfg.qte_calibrated:
                if self.det.qte_visible(frame):
                    self._do_qte()
                else:
                    self._set_state(FishState.WAITING)
            else:
                self._do_qte()

        elif cur == FishState.REELING:
            if not self._ensure_fg():
                return
            self.inp.click(self.cfg.cast_hold_ms)
            self.stats.catches += 1
            self._log(f"REEL - Catch #{self.stats.catches}")
            self._set_state(FishState.COOLDOWN)

        elif cur == FishState.COOLDOWN:
            if self._elapsed() > self.cfg.reel_cooldown_ms / 1000.0:
                self._set_state(FishState.CASTING)


class RegionDrawer(tk.Toplevel):
    def __init__(self, parent, wm: WindowManager, cfg: Config,
                 on_save: Callable):
        super().__init__(parent)
        self.wm       = wm
        self.cfg      = cfg
        self._on_save = on_save
        self.title("Draw Scan Region")
        self.configure(bg=DARK)
        self.resizable(True, True)
        self.grab_set()

        tk.Label(self,
                 text="Drag a rectangle over the water area only.\n"
                      "Exclude character, land, and UI.",
                 bg=DARK, fg=TEXT,
                 font=("Segoe UI", 10)).pack(pady=8)

        frame = tk.Frame(self, bg=DARK)
        frame.pack(fill="both", expand=True, padx=8, pady=4)

        self._canvas = tk.Canvas(frame, bg="#000000", cursor="crosshair")
        self._canvas.pack(fill="both", expand=True)

        btn_row = tk.Frame(self, bg=DARK)
        btn_row.pack(pady=8)
        tk.Button(btn_row, text="Refresh", bg=CARD, fg=TEXT,
                  relief="flat", font=("Segoe UI", 9),
                  command=self._load_screenshot).pack(side="left", padx=6)
        tk.Button(btn_row, text="Save Region", bg=GREEN, fg=DARK,
                  relief="flat", font=("Segoe UI", 9, "bold"),
                  command=self._save).pack(side="left", padx=6)
        tk.Button(btn_row, text="Cancel", bg=CARD, fg=MUTED,
                  relief="flat", font=("Segoe UI", 9),
                  command=self.destroy).pack(side="left", padx=6)

        self._img_tk   = None
        self._img_w    = 1
        self._img_h    = 1
        self._rect_id  = None
        self._x0 = self._y0 = self._x1 = self._y1 = 0
        self._dragging = False

        self._canvas.bind("<ButtonPress-1>",   self._on_press)
        self._canvas.bind("<B1-Motion>",        self._on_drag)
        self._canvas.bind("<ButtonRelease-1>",  self._on_release)

        self._load_screenshot()

    def _load_screenshot(self):
        frame = _grab_once(self.wm)
        if frame is None:
            messagebox.showerror("Error", "Cannot grab Roblox.", parent=self)
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self._src_h, self._src_w = rgb.shape[:2]
        disp_w = min(self._src_w, 900)
        disp_h = int(self._src_h * disp_w / self._src_w)
        rgb_r  = cv2.resize(rgb, (disp_w, disp_h))
        self._scale_x = self._src_w / disp_w
        self._scale_y = self._src_h / disp_h
        self._img_w   = disp_w
        self._img_h   = disp_h
        pil = Image.fromarray(rgb_r)
        self._img_tk = ImageTk.PhotoImage(pil)
        self._canvas.config(width=disp_w, height=disp_h)
        self._canvas.create_image(0, 0, anchor="nw", image=self._img_tk)
        self._rect_id = None
        self.geometry(f"{disp_w+20}x{disp_h+120}")

    def _on_press(self, e):
        self._x0 = e.x
        self._y0 = e.y
        self._dragging = True
        if self._rect_id:
            self._canvas.delete(self._rect_id)

    def _on_drag(self, e):
        if not self._dragging:
            return
        if self._rect_id:
            self._canvas.delete(self._rect_id)
        self._x1 = e.x
        self._y1 = e.y
        self._rect_id = self._canvas.create_rectangle(
            self._x0, self._y0, self._x1, self._y1,
            outline="#00ff88", width=2)

    def _on_release(self, e):
        self._x1 = e.x
        self._y1 = e.y
        self._dragging = False

    def _save(self):
        if self._x0 == self._x1 or self._y0 == self._y1:
            messagebox.showwarning("No region",
                                   "Draw a rectangle first.", parent=self)
            return
        x1 = min(self._x0, self._x1)
        y1 = min(self._y0, self._y1)
        x2 = max(self._x0, self._x1)
        y2 = max(self._y0, self._y1)

        self.cfg.scan_x1_pct     = round(x1 * self._scale_x / self._src_w, 4)
        self.cfg.scan_y1_pct     = round(y1 * self._scale_y / self._src_h, 4)
        self.cfg.scan_x2_pct     = round(x2 * self._scale_x / self._src_w, 4)
        self.cfg.scan_y2_pct     = round(y2 * self._scale_y / self._src_h, 4)
        self.cfg.scan_region_set = True
        self._on_save()
        self.destroy()


class ColorSamplerDialog(tk.Toplevel):
    def __init__(self, parent, wm: WindowManager, cfg_ref: Config,
                 title: str, on_confirm: Callable,
                 mode: str = "bobber"):
        super().__init__(parent)
        self.wm          = wm
        self.cfg_ref     = cfg_ref
        self._on_confirm = on_confirm
        self._mode       = mode   # "bobber" | "splash" | "qte"
        self._hsv: Optional[np.ndarray] = None
        self._bgr: Optional[np.ndarray] = None
        self._lo:  Optional[list] = None
        self._hi:  Optional[list] = None
        self._picking = False

        self.title(title)
        self.configure(bg=DARK)
        self.resizable(False, False)
        self.grab_set()

        tk.Label(self, text=title, bg=DARK, fg=TEXT,
                 font=("Segoe UI", 12, "bold")).pack(pady=(14, 2), padx=20)
        tk.Label(self,
                 text=("1. Switch to Roblox, target must be visible\n"
                       "2. Click  \"Pick\"\n"
                       "3. Move cursor over the exact pixel\n"
                       "4. Press  Enter  to capture\n"
                       "5. Adjust sliders, use Test, then Confirm"),
                 bg=DARK, fg=MUTED, font=("Segoe UI", 9),
                 justify="left").pack(padx=20, pady=6)

        self._preview = tk.Label(self, bg="#333333",
                                 width=12, height=2, relief="solid")
        self._preview.pack(pady=4)
        self._info = tk.Label(self, text="No sample",
                              bg=DARK, fg=MUTED, font=("Segoe UI", 9))
        self._info.pack()

        for label, attr, lo_val, hi_val in [
            ("Hue tol ±",  "_tol_h",     8, 30),
            ("Sat floor",  "_sat_floor", 80, 255),
            ("Val floor",  "_val_floor", 80, 255),
        ]:
            row = tk.Frame(self, bg=DARK)
            row.pack(fill="x", padx=20, pady=3)
            tk.Label(row, text=label, bg=DARK, fg=MUTED,
                     font=("Segoe UI", 9), width=10).pack(side="left")
            var = tk.IntVar(value=lo_val)
            setattr(self, attr, var)
            tk.Scale(row, from_=0, to=hi_val, orient="horizontal",
                     variable=var, bg=DARK, fg=TEXT,
                     troughcolor=CARD, highlightthickness=0,
                     command=lambda _: self._update_range()
                     ).pack(side="left", fill="x", expand=True)

        self._range_lbl = tk.Label(self, text="Range: —",
                                   bg=DARK, fg=MUTED, font=("Consolas", 8))
        self._range_lbl.pack(pady=2)

        for label, attr, default in [
            ("Min px", "_min_px",  20),
            ("Max px", "_max_px", 500),
        ]:
            row = tk.Frame(self, bg=DARK)
            row.pack(fill="x", padx=20, pady=3)
            tk.Label(row, text=label, bg=DARK, fg=MUTED,
                     font=("Segoe UI", 9), width=10).pack(side="left")
            var = tk.IntVar(value=default)
            setattr(self, attr, var)
            tk.Scale(row, from_=1, to=500, orient="horizontal",
                     variable=var, bg=DARK, fg=TEXT,
                     troughcolor=CARD, highlightthickness=0
                     ).pack(side="left", fill="x", expand=True)

        btn_row = tk.Frame(self, bg=DARK)
        btn_row.pack(pady=12)
        self._pick_btn = tk.Button(
            btn_row, text="Pick", bg=CARD, fg=TEXT, relief="flat",
            font=("Segoe UI", 9), command=self._start_pick)
        self._pick_btn.pack(side="left", padx=4)
        tk.Button(btn_row, text="Test", bg=CARD, fg=TEXT,
                  relief="flat", font=("Segoe UI", 9),
                  command=self._test).pack(side="left", padx=4)
        tk.Button(btn_row, text="Confirm", bg=GREEN, fg=DARK,
                  relief="flat", font=("Segoe UI", 9, "bold"),
                  command=self._confirm).pack(side="left", padx=4)
        tk.Button(btn_row, text="Cancel", bg=CARD, fg=MUTED,
                  relief="flat", font=("Segoe UI", 9),
                  command=self.destroy).pack(side="left", padx=4)

    def _start_pick(self):
        self._picking = True
        self._pick_btn.config(text="Move cursor → Enter", bg=ACCENT)
        self.bind("<Return>", self._capture)
        self.focus_set()

    def _capture(self, _=None):
        if not self._picking:
            return
        x, y = win32api.GetCursorPos()
        self._hsv, self._bgr = _grab_pixel_hsv(x, y)
        self._picking = False
        self._pick_btn.config(text="Pick", bg=CARD)
        self._update_range()
        r = int(self._bgr[2])
        g = int(self._bgr[1])
        b = int(self._bgr[0])
        self._preview.config(bg=f"#{r:02x}{g:02x}{b:02x}")
        h = int(self._hsv[0])
        s = int(self._hsv[1])
        v = int(self._hsv[2])
        self._info.config(
            text=f"HSV H={h} S={s} V={v}  at ({x},{y})", fg=TEXT)

    def _update_range(self):
        if self._hsv is None:
            return
        th = self._tol_h.get()
        sf = self._sat_floor.get()
        vf = self._val_floor.get()
        h  = int(self._hsv[0])
        self._lo = [max(0, h - th),    sf,  vf]
        self._hi = [min(180, h + th), 255, 255]
        self._range_lbl.config(text=f"lo={self._lo}  hi={self._hi}")

    def _test(self):
        if self._lo is None:
            messagebox.showwarning("No sample", "Pick first.", parent=self)
            return
        frame = _grab_once(self.wm)
        if frame is None:
            messagebox.showerror("Error", "Cannot grab.", parent=self)
            return
        tmp = Config()
        tmp.load()
        tmp.scan_x1_pct = self.cfg_ref.scan_x1_pct
        tmp.scan_y1_pct = self.cfg_ref.scan_y1_pct
        tmp.scan_x2_pct = self.cfg_ref.scan_x2_pct
        tmp.scan_y2_pct = self.cfg_ref.scan_y2_pct

        if self._mode == "bobber":
            tmp.bobber_hsv_low    = self._lo
            tmp.bobber_hsv_high   = self._hi
            tmp.bobber_min_pixels = self._min_px.get()
            tmp.bobber_max_pixels = self._max_px.get()
            tmp.bobber_calibrated = True
            det = Detector(tmp)
            px  = det.bobber_pixels(frame)
            vis = tmp.bobber_min_pixels <= px <= tmp.bobber_max_pixels
            det.save_debug(frame, "test")
            messagebox.showinfo("Test Result",
                f"Bobber pixels: {px}\n"
                f"Min: {tmp.bobber_min_pixels}  Max: {tmp.bobber_max_pixels}\n"
                f"Result: {'✓ VISIBLE' if vis else '✗ NOT VISIBLE'}\n\n"
                f"Check debug_test.png", parent=self)
        elif self._mode == "splash":
            tmp.splash_hsv_low    = self._lo
            tmp.splash_hsv_high   = self._hi
            tmp.splash_min_pixels = self._min_px.get()
            tmp.bobber_calibrated = self.cfg_ref.bobber_calibrated
            tmp.bobber_hsv_low    = self.cfg_ref.bobber_hsv_low
            tmp.bobber_hsv_high   = self.cfg_ref.bobber_hsv_high
            det = Detector(tmp)
            px  = det.splash_pixels(frame)
            vis = px >= tmp.splash_min_pixels
            det.save_debug(frame, "test_splash")
            messagebox.showinfo("Test Result",
                f"Splash pixels: {px}\n"
                f"Min needed: {tmp.splash_min_pixels}\n"
                f"Result: {'✓ SPLASH DETECTED' if vis else '✗ NOT DETECTED'}\n\n"
                f"Check debug_test_splash.png", parent=self)
        else:
            tmp.qte_hsv_low    = self._lo
            tmp.qte_hsv_high   = self._hi
            tmp.qte_min_pixels = self._min_px.get()
            tmp.qte_calibrated = True
            det = Detector(tmp)
            px  = det.qte_visible(frame)
            det.save_debug(frame, "test_qte")
            messagebox.showinfo("Test Result",
                f"QTE detected: {px}\nCheck debug_test_qte.png",
                parent=self)

    def _confirm(self):
        if self._lo is None:
            messagebox.showwarning("No sample", "Pick first.", parent=self)
            return
        self._on_confirm(self._lo, self._hi,
                         self._min_px.get(), self._max_px.get())
        self.destroy()


class HotkeyEntry(tk.Frame):
    def __init__(self, parent, label: str, value: str,
                 on_change: Callable, **kw):
        super().__init__(parent, bg=PANEL, **kw)
        self._cb        = on_change
        self._value     = value
        self._listening = False
        self._held      = set()

        tk.Label(self, text=label, bg=PANEL, fg=MUTED, width=14,
                 anchor="w", font=("Segoe UI", 9)).pack(
                     side="left", padx=(8, 0))
        self._btn = tk.Button(
            self, text=self._fmt(value), width=16,
            bg=CARD, fg=TEXT, relief="flat",
            font=("Segoe UI", 9, "bold"),
            activebackground=ACCENT, activeforeground=TEXT,
            command=self._listen)
        self._btn.pack(side="left", padx=6, pady=3)

    def _fmt(self, v: str) -> str:
        return v.upper() if v else "—"

    def _listen(self):
        if self._listening:
            return
        self._listening = True
        self._held      = set()
        self._btn.config(text="[ press combo... ]", bg=ACCENT)
        self._btn.bind("<KeyPress>",   self._kp)
        self._btn.bind("<KeyRelease>", self._kr)
        self._btn.focus_set()

    _MOD_MAP = {
        "shift_l": "shift", "shift_r": "shift",
        "control_l": "ctrl", "control_r": "ctrl",
        "alt_l": "alt",     "alt_r": "alt",
    }

    def _norm(self, sym: str) -> str:
        return self._MOD_MAP.get(sym.lower(), sym.lower())

    def _kp(self, e):
        if self._listening:
            self._held.add(self._norm(e.keysym))

    def _kr(self, e):
        if not self._listening:
            return
        mods  = [k for k in ("ctrl", "shift", "alt") if k in self._held]
        rest  = [k for k in self._held if k not in ("ctrl", "shift", "alt")]
        combo = "+".join(mods + rest)
        self._listening = False
        self._value     = combo
        self._btn.config(text=self._fmt(combo), bg=CARD)
        self._cb(combo)

    def get(self) -> str:
        return self._value

    def set(self, v: str):
        self._value = v
        self._btn.config(text=self._fmt(v))


class FishBotUI:
    def __init__(self):
        self.cfg    = Config()
        self.cfg.load()
        self.wm     = WindowManager(self.cfg.target_exe)
        self.inp    = InputHandler()
        self.stats  = Stats()
        self.fish:  Optional[FishBot] = None
        self.active = False
        self._hk_lock = threading.Lock()
        self._reg_hks: list = []

        self.root = tk.Tk()
        self.root.title("FishBot")
        self.root.configure(bg=DARK)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build()
        self._reg_hotkeys()
        self._ui_tick()

    def _card(self, parent, title: str) -> tk.LabelFrame:
        f = tk.LabelFrame(parent, text=f" {title} ",
                          bg=PANEL, fg=MUTED,
                          font=("Segoe UI", 8), bd=1, relief="groove")
        f.pack(fill="x", pady=3)
        return f

    def _build(self):
        self._build_header()
        body = tk.Frame(self.root, bg=DARK)
        body.pack(fill="both", padx=10, pady=(0, 10))
        left  = tk.Frame(body, bg=DARK)
        right = tk.Frame(body, bg=DARK)
        left.pack(side="left",  fill="both", expand=True, padx=(0, 5))
        right.pack(side="left", fill="both", expand=True)
        self._build_state(left)
        self._build_stats(left)
        self._build_calibration(left)
        self._build_settings(right)
        self._build_hotkeys(right)
        self._build_log()

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=ACCENT, height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🎣  FishBot", bg=ACCENT, fg=TEXT,
                 font=("Segoe UI", 15, "bold")).pack(side="left", padx=14)
        self._dot = tk.Label(hdr, text="●", bg=ACCENT, fg=MUTED,
                             font=("Segoe UI", 13))
        self._dot.pack(side="right", padx=(0, 14))
        self._status_lbl = tk.Label(hdr, text="STOPPED", bg=ACCENT, fg=TEXT,
                                    font=("Segoe UI", 10, "bold"))
        self._status_lbl.pack(side="right")
        self._start_btn = tk.Button(
            hdr, text="▶  START", bg=GREEN, fg=DARK, relief="flat",
            font=("Segoe UI", 10, "bold"), padx=10, pady=3,
            activebackground="#00ff80", command=self._toggle)
        self._start_btn.pack(side="right", padx=14)

    def _build_state(self, parent):
        c = self._card(parent, "State")
        self._state_lbl = tk.Label(c, text="IDLE", bg=PANEL, fg=MUTED,
                                   font=("Segoe UI", 14, "bold"))
        self._state_lbl.pack(pady=(8, 2))
        self._px_lbl = tk.Label(c, text="bob=— splash=—",
                                bg=PANEL, fg=MUTED, font=("Segoe UI", 8))
        self._px_lbl.pack(pady=(0, 6))

    def _build_stats(self, parent):
        c = self._card(parent, "Session")
        self._sv: dict = {}
        for label in ("Catches", "Casts", "Timeouts", "QTE", "CPH", "Runtime"):
            row = tk.Frame(c, bg=PANEL)
            row.pack(fill="x", padx=10, pady=1)
            tk.Label(row, text=label, bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 9), width=10, anchor="w").pack(side="left")
            v = tk.StringVar(value="0")
            tk.Label(row, textvariable=v, bg=PANEL, fg=TEXT,
                     font=("Segoe UI", 9, "bold"), anchor="e").pack(side="right")
            self._sv[label] = v
        tk.Frame(c, bg=PANEL, height=4).pack()

    def _build_calibration(self, parent):
        c = self._card(parent, "Calibration")
        self._cal_lbls: dict = {}

        for name, attr, cmd in [
            ("Bobber color",   "bobber_calibrated",  self._cal_bobber),
            ("Splash/Bite",    "splash_calibrated",  self._cal_splash),
            ("QTE Indicator",  "qte_calibrated",     self._cal_qte),
        ]:
            row = tk.Frame(c, bg=PANEL)
            row.pack(fill="x", padx=8, pady=3)
            lbl = tk.Label(row, text=f"{name}: ✗", bg=PANEL, fg=RED,
                           font=("Segoe UI", 9), anchor="w", width=20)
            lbl.pack(side="left")
            tk.Button(row, text="Sample", bg=CARD, fg=TEXT,
                      relief="flat", font=("Segoe UI", 8),
                      command=cmd).pack(side="right")
            self._cal_lbls[attr] = lbl

        self._region_lbl = tk.Label(c, text="Scan region: not set",
                                    bg=PANEL, fg=RED, font=("Segoe UI", 8))
        self._region_lbl.pack(pady=2)

        tk.Button(c, text="🖱 Draw Scan Region on Screenshot",
                  bg=CARD, fg=TEXT, relief="flat",
                  font=("Segoe UI", 9, "bold"),
                  command=self._draw_region).pack(pady=4, padx=8, fill="x")

        tk.Button(c, text="Save Debug Screenshot", bg=CARD, fg=MUTED,
                  relief="flat", font=("Segoe UI", 8),
                  command=self._save_debug_now).pack(
                      pady=(2, 8), padx=8, fill="x")

    def _build_settings(self, parent):
        c = self._card(parent, "Settings")
        fields = [
            ("Cast hold (ms)",       "cast_hold_ms",          "float"),
            ("Cast timeout (ms)",    "cast_timeout_ms",       "float"),
            ("Settle wait (ms)",     "settle_wait_ms",        "float"),
            ("Reel cooldown (ms)",   "reel_cooldown_ms",      "float"),
            ("QTE interval (ms)",    "qte_interval_ms",       "float"),
            ("Equip rod key",        "equip_rod_key",         "str"),
            ("QTE keys (csv)",       "qte_keys",              "list"),
            ("Acquire frames",       "bobber_acquire_frames", "int"),
            ("Bite confirm frames",  "bite_confirm_frames",   "int"),
            ("Splash min px",        "splash_min_pixels",     "int"),
            ("Bobber min px",        "bobber_min_pixels",     "int"),
            ("Bobber max px",        "bobber_max_pixels",     "int"),
        ]
        self._sv2: dict = {}
        for label, attr, kind in fields:
            row = tk.Frame(c, bg=PANEL)
            row.pack(fill="x", padx=8, pady=2)
            tk.Label(row, text=label, bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 9), width=19,
                     anchor="w").pack(side="left")
            var = tk.StringVar()
            val = getattr(self.cfg, attr)
            var.set(",".join(val) if kind == "list" else str(val))
            tk.Entry(row, textvariable=var, bg=CARD, fg=TEXT,
                     insertbackground=TEXT, relief="flat",
                     font=("Segoe UI", 9), width=8).pack(side="right")
            self._sv2[attr] = (var, kind)
        tk.Button(c, text="Apply & Save", bg=ACCENT, fg=TEXT,
                  relief="flat", font=("Segoe UI", 9, "bold"),
                  activebackground="#ff6070",
                  command=self._apply).pack(pady=6, padx=8, fill="x")

    def _build_hotkeys(self, parent):
        c = self._card(parent, "Hotkeys")
        for label, attr in (("Start / Stop", "hotkey_start_stop"),
                             ("Exit",         "hotkey_exit")):
            e = HotkeyEntry(c, label, getattr(self.cfg, attr),
                            lambda v, a=attr: self._set_hk(a, v))
            e.pack(fill="x", pady=2)

    def _build_log(self):
        c = self._card(self.root, "Log")
        c.pack(fill="both", padx=10, pady=(0, 10))
        self._log_box = tk.Text(
            c, bg=DARK, fg="#aaaaaa", height=8,
            font=("Consolas", 8), relief="flat",
            state="disabled", wrap="word")
        sb = ttk.Scrollbar(c, command=self._log_box.yview)
        self._log_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log_box.pack(fill="both", expand=True, padx=4, pady=4)

        class _Sink(logging.Handler):
            def __init__(self_, cb):
                super().__init__()
                self_._cb = cb
            def emit(self_, r):
                try:
                    self_._cb(self_.format(r))
                except Exception:
                    pass

        h = _Sink(self._append_log)
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
        log.addHandler(h)

    def _append_log(self, msg: str):
        self.root.after(0, self._append_log_safe, msg)

    def _append_log_safe(self, msg: str):
        self._log_box.configure(state="normal")
        self._log_box.insert("end", msg + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _cal_bobber(self):
        def confirm(lo, hi, min_px, max_px):
            self.cfg.bobber_hsv_low    = lo
            self.cfg.bobber_hsv_high   = hi
            self.cfg.bobber_min_pixels = min_px
            self.cfg.bobber_max_pixels = max_px
            self.cfg.bobber_calibrated = True
            self.cfg.save()
            log.info(f"Bobber calibrated lo={lo} hi={hi} "
                     f"min={min_px} max={max_px}")
        if not self.wm.find():
            messagebox.showerror("Error", "Open Roblox first.")
            return
        ColorSamplerDialog(self.root, self.wm, self.cfg,
                           "Sample Bobber Color", confirm, mode="bobber")

    def _cal_splash(self):
        def confirm(lo, hi, min_px, _max_px):
            self.cfg.splash_hsv_low    = lo
            self.cfg.splash_hsv_high   = hi
            self.cfg.splash_min_pixels = min_px
            self.cfg.splash_calibrated = True
            self.cfg.save()
            log.info(f"Splash calibrated lo={lo} hi={hi} min={min_px}")
        if not self.wm.find():
            messagebox.showerror("Error", "Open Roblox first.")
            return
        messagebox.showinfo(
            "Splash Calibration",
            "Wait for a fish to bite so the cyan splash is visible,\n"
            "then immediately click Pick and hover over the cyan glow.\n\n"
            "Alternatively: hover over a cyan pixel in a screenshot\n"
            "you already have of the bite moment.",
            parent=self.root)
        ColorSamplerDialog(self.root, self.wm, self.cfg,
                           "Sample Cyan Splash (Bite Indicator)",
                           confirm, mode="splash")

    def _cal_qte(self):
        def confirm(lo, hi, min_px, _max_px):
            self.cfg.qte_hsv_low    = lo
            self.cfg.qte_hsv_high   = hi
            self.cfg.qte_min_pixels = min_px
            self.cfg.qte_calibrated = True
            self.cfg.save()
            log.info(f"QTE calibrated lo={lo} hi={hi} min={min_px}")
        if not self.wm.find():
            messagebox.showerror("Error", "Open Roblox first.")
            return
        ColorSamplerDialog(self.root, self.wm, self.cfg,
                           "Sample QTE Indicator Color",
                           confirm, mode="qte")

    def _draw_region(self):
        if not self.wm.find():
            messagebox.showerror("Error", "Open Roblox first.")
            return
        def on_save():
            self.cfg.save()
            self._append_log_safe(
                f"Scan region saved: "
                f"x={self.cfg.scan_x1_pct:.3f}-{self.cfg.scan_x2_pct:.3f} "
                f"y={self.cfg.scan_y1_pct:.3f}-{self.cfg.scan_y2_pct:.3f}")
        RegionDrawer(self.root, self.wm, self.cfg, on_save)

    def _save_debug_now(self):
        if not self.wm.find():
            messagebox.showerror("Error", "Roblox not found.")
            return
        frame = _grab_once(self.wm)
        if frame is None:
            messagebox.showerror("Error", "Cannot capture screen.")
            return
        Detector(self.cfg).save_debug(frame, "manual")
        messagebox.showinfo("Saved", "Saved debug_manual.png  raw_manual.png")

    def _set_hk(self, attr: str, val: str):
        setattr(self.cfg, attr, val)
        self._reg_hotkeys()

    def _reg_hotkeys(self):
        for hk in self._reg_hks:
            try:
                keyboard.remove_hotkey(hk)
            except Exception:
                pass
        self._reg_hks.clear()

        def _r(combo, fn):
            if combo:
                try:
                    keyboard.add_hotkey(combo, fn, suppress=True)
                    self._reg_hks.append(combo)
                except Exception as e:
                    log.warning(f"Hotkey {combo}: {e}")

        _r(self.cfg.hotkey_start_stop, lambda: self.root.after(0, self._toggle))
        _r(self.cfg.hotkey_exit,       lambda: self.root.after(0, self._on_close))

    def _apply(self):
        for attr, (var, kind) in self._sv2.items():
            raw = var.get().strip()
            try:
                if kind == "float":
                    setattr(self.cfg, attr, float(raw))
                elif kind == "int":
                    setattr(self.cfg, attr, int(raw))
                elif kind == "list":
                    setattr(self.cfg, attr,
                            [k.strip() for k in raw.split(",") if k.strip()])
                else:
                    setattr(self.cfg, attr, raw)
            except ValueError:
                messagebox.showerror("Bad value", f"Invalid: {attr} = {raw}")
                return
        self.cfg.save()
        self._append_log_safe("Settings saved.")

    def _toggle(self):
        with self._hk_lock:
            if self.active:
                self._stop()
            else:
                self._start()

    def _start(self):
        if not self.wm.find():
            messagebox.showerror("Not found",
                                 f"Cannot find {self.cfg.target_exe}")
            return
        issues = []
        if not self.cfg.bobber_calibrated:
            issues.append("• Bobber color not sampled")
        if not self.cfg.splash_calibrated:
            issues.append("• Splash/bite color not sampled")
        if not self.cfg.scan_region_set:
            issues.append("• Scan region not drawn")
        if issues:
            if not messagebox.askyesno(
                    "Setup incomplete",
                    "\n".join(issues) + "\n\nContinue anyway?"):
                return

        self.stats = Stats()
        self.fish  = FishBot(self.cfg, self.wm, self.inp, self.stats)
        self.fish.on_state_change = lambda s: self.root.after(0, self._on_state, s)
        self.fish.on_log          = lambda m: self._append_log_safe(m)
        self.fish.on_px_update    = lambda b, s: self.root.after(
            0, self._update_px, b, s)
        self.active = True
        self.fish.start()
        self._start_btn.config(text="■  STOP", bg=RED)
        self._status_lbl.config(text="RUNNING")
        self._dot.config(fg=GREEN)

    def _stop(self):
        self.active = False
        if self.fish:
            self.fish.stop()
        self._start_btn.config(text="▶  START", bg=GREEN)
        self._status_lbl.config(text="STOPPED")
        self._dot.config(fg=MUTED)
        self._state_lbl.config(text="IDLE", fg=MUTED)
        if self.stats:
            log.info(f"Stopped | {self.stats.catches} catches "
                     f"{self.stats.casts} casts CPH={self.stats.cph():.1f}")

    def _on_state(self, state: FishState):
        self._state_lbl.config(text=state.name,
                               fg=STATE_COLORS.get(state, MUTED))

    def _update_px(self, bob_px: int, splash_px: int):
        splash_vis = splash_px >= self.cfg.splash_min_pixels
        self._px_lbl.config(
            text=f"bob={bob_px}  splash={splash_px}"
                 f"{'  BITE!' if splash_vis else ''}",
            fg=RED if splash_vis else GREEN)

    def _update_cal(self):
        labels = {
            "bobber_calibrated":  "Bobber color",
            "splash_calibrated":  "Splash/Bite",
            "qte_calibrated":     "QTE Indicator",
        }
        for attr, name in labels.items():
            lbl = self._cal_lbls.get(attr)
            if lbl:
                if getattr(self.cfg, attr):
                    lbl.config(text=f"{name}: ✓", fg=GREEN)
                else:
                    lbl.config(text=f"{name}: ✗", fg=RED)
        if self.cfg.scan_region_set:
            self._region_lbl.config(
                text=(f"Scan region: set  "
                      f"x={self.cfg.scan_x1_pct:.2f}-{self.cfg.scan_x2_pct:.2f} "
                      f"y={self.cfg.scan_y1_pct:.2f}-{self.cfg.scan_y2_pct:.2f}"),
                fg=GREEN)
        else:
            self._region_lbl.config(text="Scan region: not set", fg=RED)

    def _ui_tick(self):
        if self.active and self.stats:
            s = self.stats
            self._sv["Catches"].set(str(s.catches))
            self._sv["Casts"].set(str(s.casts))
            self._sv["Timeouts"].set(str(s.timeouts))
            self._sv["QTE"].set(str(s.qte_presses))
            self._sv["CPH"].set(f"{s.cph():.1f}")
            self._sv["Runtime"].set(s.elapsed_str())
        self._update_cal()
        self.root.after(500, self._ui_tick)

    def _on_close(self):
        self._stop()
        self.cfg.save()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = FishBotUI()
    app.run()