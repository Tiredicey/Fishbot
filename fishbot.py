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
from typing import Optional, Tuple, Callable, List

LOG_FILE    = "bot.log"
CONFIG_FILE = "fishbot_config.json"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")]
)
log = logging.getLogger("FishBot")

DARK   = "#1a1a2e"
PANEL  = "#16213e"
CARD   = "#0f3460"
ACCENT = "#e94560"
TEXT   = "#eaeaea"
MUTED  = "#888888"
GREEN  = "#00d26a"
RED    = "#e94560"
CYAN   = "#00cfcf"
ORANGE = "#ff9900"


@dataclass
class Config:
    cast_hold_ms:          float = 80.0
    cast_timeout_ms:       float = 40000.0
    reel_cooldown_ms:      float = 2500.0
    settle_wait_ms:        float = 3000.0
    qte_interval_ms:       float = 350.0
    qte_keys:              list  = field(default_factory=lambda: ["e", "q", "z", "x"])
    hotkey_start_stop:     str   = "ctrl+shift+s"
    hotkey_exit:           str   = "ctrl+shift+x"
    hotkey_vision:         str   = "ctrl+shift+v"
    equip_rod_key:         str   = "0"
    tick_sleep_ms:         float = 50.0
    target_exe:            str   = "RobloxPlayerBeta.exe"

    use_bobber_detection:  bool  = True
    use_splash_detection:  bool  = True
    use_qte:               bool  = True
    use_bait:              bool  = False
    use_vision:            bool  = True

    bait_slots:            list  = field(default_factory=lambda: [
                                       {"key": "1", "enabled": True, "label": "Bait 1"}
                                   ])
    bait_select_hold_ms:   float = 80.0
    bait_post_select_ms:   float = 300.0
    bait_click_hold_ms:    float = 80.0
    bait_post_click_ms:    float = 400.0
    bait_post_rod_ms:      float = 400.0

    bobber_hsv_low:        list  = field(default_factory=lambda: [0, 0, 0])
    bobber_hsv_high:       list  = field(default_factory=lambda: [0, 0, 0])
    bobber_min_pixels:     int   = 2
    bobber_max_pixels:     int   = 200
    bobber_calibrated:     bool  = False

    splash_hsv_low:        list  = field(default_factory=lambda: [80, 100, 100])
    splash_hsv_high:       list  = field(default_factory=lambda: [100, 255, 255])
    splash_min_pixels:     int   = 20
    splash_calibrated:     bool  = False

    scan_x1_pct:           float = 0.0
    scan_y1_pct:           float = 0.0
    scan_x2_pct:           float = 1.0
    scan_y2_pct:           float = 1.0
    scan_region_set:       bool  = False

    bobber_acquire_frames: int   = 3
    bite_confirm_frames:   int   = 2

    qte_hsv_low:           list  = field(default_factory=lambda: [0, 0, 0])
    qte_hsv_high:          list  = field(default_factory=lambda: [0, 0, 0])
    qte_min_pixels:        int   = 10
    qte_calibrated:        bool  = False
    qte_scan_x1_pct:       float = 0.0
    qte_scan_y1_pct:       float = 0.0
    qte_scan_x2_pct:       float = 1.0
    qte_scan_y2_pct:       float = 1.0
    qte_region_set:        bool  = False

    def save(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.__dict__, f, indent=2)
        except Exception as e:
            log.warning(f"Config save: {e}")

    def load(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(self, k):
                    setattr(self, k, v)
        except Exception as e:
            log.warning(f"Config load: {e}")

    def active_bait_slots(self) -> List[dict]:
        return [s for s in self.bait_slots if s.get("enabled", True) and s.get("key", "").strip()]

    def active_bait_keys(self) -> List[str]:
        return [s["key"].strip() for s in self.active_bait_slots()]


class FishState(Enum):
    IDLE     = auto()
    EQUIP    = auto()
    BAIT     = auto()
    CASTING  = auto()
    WAITING  = auto()
    QTE      = auto()
    REELING  = auto()
    COOLDOWN = auto()


STATE_COLORS = {
    FishState.IDLE:     "#777777",
    FishState.EQUIP:    "#ccaa00",
    FishState.BAIT:     "#ff9900",
    FishState.CASTING:  "#0099dd",
    FishState.WAITING:  "#00cc55",
    FishState.QTE:      "#ff8800",
    FishState.REELING:  "#ff3333",
    FishState.COOLDOWN: "#7777cc",
}


class WindowManager:
    def __init__(self, exe_name: str):
        self.exe_name     = exe_name
        self._hwnd: Optional[int] = None
        self._cached_rect: Optional[Tuple[int, int, int, int]] = None
        self._rect_ts     = 0.0
        self._RECT_TTL    = 2.0

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
        try:
            win32gui.EnumWindows(cb, None)
        except Exception:
            pass
        if found:
            self._hwnd = found[0]
            self._cached_rect = None
            try:
                log.info(f"Awesome, found Roblox! Window handle: {self._hwnd}, Area: {win32gui.GetWindowRect(self._hwnd)}")
            except Exception:
                pass
            return True
        self.title("🔍 Bot Vision — Seeing What I See")
        return False

    def bring_to_front(self):
        if not self._hwnd:
            return
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
    try:
        rect = wm.get_rect()
        if not rect:
            return None
        l, t, r, b = rect
        mon = {"left": l, "top": t, "width": max(r - l, 1), "height": max(b - t, 1)}
        raw = sct.grab(mon)
        arr = np.frombuffer(raw.raw, dtype=np.uint8).reshape((raw.height, raw.width, 4))
        return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
    except Exception as e:
        log.debug(f"grab_frame: {e}")
        return None


def _grab_pixel_hsv(x: int, y: int) -> Tuple[np.ndarray, np.ndarray]:
    with mss.mss() as sct:
        mon   = {"left": x - 4, "top": y - 4, "width": 9, "height": 9}
        raw   = sct.grab(mon)
        patch = np.frombuffer(raw.raw, dtype=np.uint8).reshape((raw.height, raw.width, 4))
        bgr   = cv2.cvtColor(patch, cv2.COLOR_BGRA2BGR)
        hsv   = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        return hsv[4, 4], bgr[4, 4]


def _grab_once(wm: WindowManager) -> Optional[np.ndarray]:
    with mss.mss() as sct:
        return _grab_frame(sct, wm)


def _safe_roi(frame: np.ndarray, x1p: float, y1p: float,
              x2p: float, y2p: float) -> Optional[np.ndarray]:
    h, w = frame.shape[:2]
    x1 = max(0, min(int(w * x1p), w))
    y1 = max(0, min(int(h * y1p), h))
    x2 = max(0, min(int(w * x2p), w))
    y2 = max(0, min(int(h * y2p), h))
    if x2 - x1 < 1 or y2 - y1 < 1:
        return None
    return frame[y1:y2, x1:x2]


class Detector:
    def __init__(self, cfg: Config):
        self.cfg     = cfg
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    def _roi(self, frame: np.ndarray) -> Optional[np.ndarray]:
        return _safe_roi(frame, self.cfg.scan_x1_pct, self.cfg.scan_y1_pct,
                         self.cfg.scan_x2_pct, self.cfg.scan_y2_pct)

    def _qte_roi(self, frame: np.ndarray) -> Optional[np.ndarray]:
        if not self.cfg.qte_region_set:
            return self._roi(frame)
        return _safe_roi(frame, self.cfg.qte_scan_x1_pct, self.cfg.qte_scan_y1_pct,
                         self.cfg.qte_scan_x2_pct, self.cfg.qte_scan_y2_pct)

    def _mask(self, roi: np.ndarray, lo: list, hi: list) -> np.ndarray:
        try:
            hsv  = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv,
                               np.array(lo, dtype=np.uint8),
                               np.array(hi, dtype=np.uint8))
            return cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._kernel)
        except Exception:
            return np.zeros(roi.shape[:2], dtype=np.uint8)

    def _count(self, frame: np.ndarray, lo: list, hi: list) -> int:
        roi = self._roi(frame)
        if roi is None:
            return 0
        return cv2.countNonZero(self._mask(roi, lo, hi))

    def bobber_pixels(self, frame: np.ndarray) -> int:
        if not self.cfg.bobber_calibrated or not self.cfg.use_bobber_detection:
            return -1
        return self._count(frame, self.cfg.bobber_hsv_low, self.cfg.bobber_hsv_high)

    def bobber_visible(self, frame: np.ndarray) -> bool:
        px = self.bobber_pixels(frame)
        if px < 0:
            return False
        return self.cfg.bobber_min_pixels <= px <= self.cfg.bobber_max_pixels

    def splash_pixels(self, frame: np.ndarray) -> int:
        if not self.cfg.use_splash_detection:
            return 0
        return self._count(frame, self.cfg.splash_hsv_low, self.cfg.splash_hsv_high)

    def splash_visible(self, frame: np.ndarray) -> bool:
        return self.splash_pixels(frame) >= self.cfg.splash_min_pixels

    def qte_pixels(self, frame: np.ndarray) -> int:
        if not self.cfg.qte_calibrated or not self.cfg.use_qte:
            return 0
        roi = self._qte_roi(frame)
        if roi is None:
            return 0
        return cv2.countNonZero(self._mask(roi, self.cfg.qte_hsv_low, self.cfg.qte_hsv_high))

    def qte_visible(self, frame: np.ndarray) -> bool:
        return self.qte_pixels(frame) >= self.cfg.qte_min_pixels

    def build_overlay(self, frame: np.ndarray) -> np.ndarray:
        try:
            roi = self._roi(frame)
            if roi is None:
                return frame.copy()
            out = roi.copy()
            if self.cfg.bobber_calibrated and self.cfg.use_bobber_detection:
                m = self._mask(out, self.cfg.bobber_hsv_low, self.cfg.bobber_hsv_high)
                out[m > 0] = [0, 0, 220]
            if self.cfg.use_splash_detection:
                m2 = self._mask(out, self.cfg.splash_hsv_low, self.cfg.splash_hsv_high)
                out[m2 > 0] = [220, 220, 0]
            if self.cfg.qte_calibrated and self.cfg.use_qte:
                qroi = self._qte_roi(frame)
                if qroi is not None:
                    qout = qroi.copy()
                    m3   = self._mask(qout, self.cfg.qte_hsv_low, self.cfg.qte_hsv_high)
                    qout[m3 > 0] = [0, 220, 220]
                    if self.cfg.qte_region_set:
                        fh, fw = frame.shape[:2]
                        ry1 = int(fh * self.cfg.scan_y1_pct)
                        rx1 = int(fw * self.cfg.scan_x1_pct)
                        qy1 = int(fh * self.cfg.qte_scan_y1_pct)
                        qx1 = int(fw * self.cfg.qte_scan_x1_pct)
                        oy1 = max(qy1 - ry1, 0)
                        ox1 = max(qx1 - rx1, 0)
                        oy2 = min(oy1 + qout.shape[0], out.shape[0])
                        ox2 = min(ox1 + qout.shape[1], out.shape[1])
                        if oy2 > oy1 and ox2 > ox1:
                            out[oy1:oy2, ox1:ox2] = qout[:oy2 - oy1, :ox2 - ox1]
                    else:
                        out[m3 > 0] = [0, 220, 220]
            cv2.rectangle(out, (0, 0), (out.shape[1] - 1, out.shape[0] - 1), (80, 80, 80), 1)
            return out
        except Exception as e:
            log.debug(f"build_overlay: {e}")
            return frame.copy()

    def save_debug(self, frame: np.ndarray, tag: str):
        try:
            roi = self._roi(frame)
            if roi is not None:
                cv2.imwrite(f"raw_{tag}.png", roi)
            cv2.imwrite(f"debug_{tag}.png", self.build_overlay(frame))
            log.info(f"Saved debug_{tag}.png raw_{tag}.png")
        except Exception as e:
            log.warning(f"Debug save: {e}")


class InputHandler:
    def __init__(self):
        pydirectinput.PAUSE    = 0.0
        pydirectinput.FAILSAFE = False

    def click(self, hold_ms: float = 80.0):
        try:
            pydirectinput.mouseDown(button="left")
            time.sleep(max(hold_ms, 10.0) / 1000.0)
            pydirectinput.mouseUp(button="left")
            time.sleep(0.02)
        except Exception as e:
            log.warning(f"click: {e}")

    def tap(self, key: str, hold_ms: float = 60.0):
        k = key.strip().lower()
        if not k:
            return
        try:
            pydirectinput.keyDown(k)
            time.sleep(max(hold_ms, 10.0) / 1000.0)
            pydirectinput.keyUp(k)
            time.sleep(0.02)
        except Exception as e:
            log.warning(f"tap({k!r}): {e}")

    def bait_sequence(self, bait_key: str, rod_key: str,
                      select_hold_ms: float, post_select_ms: float,
                      click_hold_ms: float, post_click_ms: float,
                      post_rod_ms: float) -> str:
        k = bait_key.strip().lower()
        r = rod_key.strip().lower()
        if not k:
            return "ERROR: bait key is empty"
        if not r:
            return "ERROR: rod key is empty"
        try:
            pydirectinput.keyDown(k)
            time.sleep(max(select_hold_ms, 10.0) / 1000.0)
            pydirectinput.keyUp(k)
            time.sleep(max(post_select_ms, 50.0) / 1000.0)
            pydirectinput.mouseDown(button="left")
            time.sleep(max(click_hold_ms, 10.0) / 1000.0)
            pydirectinput.mouseUp(button="left")
            time.sleep(max(post_click_ms, 50.0) / 1000.0)
            pydirectinput.keyDown(r)
            time.sleep(max(select_hold_ms, 10.0) / 1000.0)
            pydirectinput.keyUp(r)
            time.sleep(max(post_rod_ms, 50.0) / 1000.0)
            return f"OK: [{k}] selected → left click → [{r}] re-equipped"
        except Exception as e:
            return f"ERROR: {e}"


@dataclass
class Stats:
    catches:     int   = 0
    casts:       int   = 0
    timeouts:    int   = 0
    qte_presses: int   = 0
    bait_uses:   int   = 0
    start_time:  float = field(default_factory=time.time)

    def cph(self) -> float:
        e = (time.time() - self.start_time) / 3600.0
        return self.catches / e if e > 0 else 0.0

    def elapsed_str(self) -> str:
        e = time.time() - self.start_time
        return f"{int(e//3600):02d}:{int((e%3600)//60):02d}:{int(e%60):02d}"


class FishBot:
    def __init__(self, cfg: Config, wm: WindowManager,
                 inp: InputHandler, stats: Stats):
        self.cfg   = cfg
        self.wm    = wm
        self.inp   = inp
        self.stats = stats
        self.det   = Detector(cfg)

        self.state        = FishState.IDLE
        self.state_since  = time.time()
        self.running      = False
        self._state_lock  = threading.Lock()
        self._thread: Optional[threading.Thread] = None

        self._acquired    = False
        self._acq_frames  = 0
        self._bite_frames = 0
        self._debug_saved = False
        self._last_qte    = 0.0
        self._qte_idx     = 0
        self._qte_start   = 0.0
        self._bait_idx    = 0

        self.on_state_change:   Optional[Callable] = None
        self.on_log:            Optional[Callable] = None
        self.on_px_update:      Optional[Callable] = None
        self.on_frame:          Optional[Callable] = None
        self.on_stopped:        Optional[Callable] = None
        self.on_bait_activated: Optional[Callable] = None

    def _log(self, msg: str, level: str = "info"):
        getattr(log, level)(msg)
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass

    def _elapsed(self) -> float:
        return time.time() - self.state_since

    def _set_state(self, s: FishState):
        self._log(f"{self.state.name} -> {s.name}")
        with self._state_lock:
            self.state       = s
            self.state_since = time.time()
        self._acquired    = False
        self._acq_frames  = 0
        self._bite_frames = 0
        self._debug_saved = False
        if s == FishState.QTE:
            self._qte_start = time.time()
        if self.on_state_change:
            try:
                self.on_state_change(s)
            except Exception:
                pass

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="FishBot")
        self._thread.start()

    def stop(self):
        self.running = False

    def join(self, timeout: float = 3.0):
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        with self._state_lock:
            self.state = FishState.IDLE
        if self.on_state_change:
            try:
                self.on_state_change(FishState.IDLE)
            except Exception:
                pass
        if self.on_stopped:
            try:
                self.on_stopped()
            except Exception:
                pass

    def _loop(self):
        with mss.mss() as sct:
            while self.running:
                try:
                    self._tick(sct)
                except Exception as e:
                    log.error(f"Tick: {e}", exc_info=True)
                time.sleep(max(self.cfg.tick_sleep_ms, 10.0) / 1000.0)

    def _push_frame(self, frame: np.ndarray):
        if self.cfg.use_vision and self.on_frame and frame is not None:
            try:
                self.on_frame(self.det.build_overlay(frame))
            except Exception:
                pass

    def _ensure_fg(self) -> bool:
        if not self.wm.is_foreground():
            self.wm.bring_to_front()
            time.sleep(0.15)
        return self.wm.is_foreground()

    def _do_qte(self):
        if not self.cfg.use_qte or not self.cfg.qte_keys:
            return
        now = time.time()
        if now - self._last_qte >= self.cfg.qte_interval_ms / 1000.0:
            k = self.cfg.qte_keys[self._qte_idx % len(self.cfg.qte_keys)]
            self.inp.tap(k, 60)
            self._qte_idx         += 1
            self._last_qte         = now
            self.stats.qte_presses += 1
            self._log(f"QTE tap: {k!r}")

    def _next_after_cooldown(self) -> FishState:
        if self.cfg.use_bait and self.cfg.active_bait_slots():
            return FishState.BAIT
        return FishState.CASTING

    def _tick(self, sct):
        if not self.wm.exists():
            self._log("Looks like Roblox was closed. Taking a break!", "warning")
            self.running = False
            return

        with self._state_lock:
            cur = self.state

        if cur == FishState.IDLE:
            self._set_state(FishState.EQUIP)

        elif cur == FishState.EQUIP:
            if not self._ensure_fg():
                return
            self.inp.tap(self.cfg.equip_rod_key, 80)
            time.sleep(0.4)
            self._log(f"Rod equipped [{self.cfg.equip_rod_key!r}]")
            self._set_state(self._next_after_cooldown())

        elif cur == FishState.BAIT:
            if not self._ensure_fg():
                return
            slots = self.cfg.active_bait_slots()
            if not slots:
                self._log("Bait: no enabled slots — skipping to cast")
                self._set_state(FishState.CASTING)
                return

            slot      = slots[self._bait_idx % len(slots)]
            bait_key  = slot["key"].strip().lower()
            rod_key   = self.cfg.equip_rod_key.strip().lower()
            label     = slot.get("label", bait_key)

            if not bait_key:
                self._log("Bait: slot key is empty — skipping", "warning")
                self._bait_idx += 1
                self._set_state(FishState.CASTING)
                return

            self._log(f"Bait [{label}]: press [{bait_key!r}] → left click → press [{rod_key!r}]")

            result = self.inp.bait_sequence(
                bait_key,
                rod_key,
                self.cfg.bait_select_hold_ms,
                self.cfg.bait_post_select_ms,
                self.cfg.bait_click_hold_ms,
                self.cfg.bait_post_click_ms,
                self.cfg.bait_post_rod_ms,
            )

            self._log(f"Bait result: {result}")
            self._bait_idx    += 1
            self.stats.bait_uses += 1

            if self.on_bait_activated:
                try:
                    self.on_bait_activated(bait_key, label)
                except Exception:
                    pass

            self._set_state(FishState.CASTING)

        elif cur == FishState.CASTING:
            if not self._ensure_fg():
                return
            time.sleep(0.3)
            self.inp.click(self.cfg.cast_hold_ms)
            self.stats.casts += 1
            self._log(f"Casting the line out... (Cast #{self.stats.casts})")
            time.sleep(self.cfg.settle_wait_ms / 1000.0)
            self._set_state(FishState.WAITING)

        elif cur == FishState.WAITING:
            elapsed = self._elapsed()
            if elapsed > self.cfg.cast_timeout_ms / 1000.0:
                self._log("Hmm, no bites for a while. Let's try casting again!", "warning")
                self.stats.timeouts += 1
                self._set_state(FishState.CASTING)
                return

            frame = _grab_frame(sct, self.wm)
            if frame is None:
                return

            self._push_frame(frame)

            if not self._debug_saved and elapsed > 1.0:
                self.det.save_debug(frame, f"cast{self.stats.casts}")
                self._debug_saved = True

            bob_px    = self.det.bobber_pixels(frame)
            splash_px = self.det.splash_pixels(frame)

            if self.on_px_update:
                try:
                    self.on_px_update(bob_px, splash_px)
                except Exception:
                    pass

            log.debug(f"WAIT bob={bob_px} splash={splash_px} "
                      f"acq={self._acq_frames} bite={self._bite_frames}")

            if self.cfg.use_bobber_detection and self.cfg.bobber_calibrated:
                if not self._acquired:
                    if self.det.bobber_visible(frame):
                        self._acq_frames += 1
                        if self._acq_frames >= self.cfg.bobber_acquire_frames:
                            self._acquired = True
                            self._log("Got my eyes on the bobber. Waiting for a fish to bite...")
                    else:
                        self._acq_frames = 0
                    return
            else:
                self._acquired = True

            if self.cfg.use_splash_detection and self.cfg.splash_calibrated:
                if self.det.splash_visible(frame):
                    self._bite_frames += 1
                    if self._bite_frames >= self.cfg.bite_confirm_frames:
                        self._log("Fish on! Reeling it in right now!")
                        self._set_state(FishState.REELING)
                        return
                else:
                    self._bite_frames = 0

            if self.cfg.use_qte and self.cfg.qte_calibrated and self.det.qte_visible(frame):
                self._log("QTE detected")
                self._set_state(FishState.QTE)

        elif cur == FishState.QTE:
            if not self.cfg.use_qte:
                self._set_state(FishState.WAITING)
                return
            if time.time() - self._qte_start > 12.0:
                self._log("Missed the prompt... going back to waiting.")
                self._set_state(FishState.WAITING)
                return

            frame = _grab_frame(sct, self.wm)
            if frame is None:
                return
            self._push_frame(frame)

            bob_px    = self.det.bobber_pixels(frame)
            splash_px = self.det.splash_pixels(frame)
            if self.on_px_update:
                try:
                    self.on_px_update(bob_px, splash_px)
                except Exception:
                    pass

            if self.cfg.use_splash_detection and self.det.splash_visible(frame):
                self._bite_frames += 1
                if self._bite_frames >= self.cfg.bite_confirm_frames:
                    self._log("Fish bit while I was focused on the QTE! Reeling it in!")
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
            self._log(f"Woohoo, got one! That makes {self.stats.catches} caught so far!")
            self._set_state(FishState.COOLDOWN)

        elif cur == FishState.COOLDOWN:
            if self._elapsed() > self.cfg.reel_cooldown_ms / 1000.0:
                self._set_state(self._next_after_cooldown())


class VisionViewer(tk.Toplevel):
    _W      = 420
    _H      = 300
    _FPS_MS = 50

    def __init__(self, parent):
        super().__init__(parent)
        self.title("🔍 Bot Vision — Live View")
        self.configure(bg=DARK)
        self.resizable(True, True)
        self.wm_attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._lock         = threading.Lock()
        self._pending: Optional[np.ndarray] = None
        self._img_tk       = None
        self._poll_running = False
        self._fps_count    = 0
        self._fps_disp     = 0
        self._fps_ts       = time.time()

        self._build()

    def _build(self):
        hdr = tk.Frame(self, bg=CARD, height=28)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="BOT VISION  •  LIVE",
                 bg=CARD, fg=CYAN, font=("Segoe UI", 8, "bold")).pack(side="left", padx=8)
        self._fps_lbl = tk.Label(hdr, text="0 fps", bg=CARD, fg=MUTED,
                                 font=("Consolas", 8))
        self._fps_lbl.pack(side="right", padx=8)
        self._state_badge = tk.Label(hdr, text="IDLE", bg=CARD, fg=MUTED,
                                     font=("Segoe UI", 8, "bold"))
        self._state_badge.pack(side="right", padx=4)

        self._canvas = tk.Canvas(self, bg="#000000", width=self._W,
                                 height=self._H, highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)

        leg = tk.Frame(self, bg=DARK)
        leg.pack(fill="x", padx=6, pady=2)
        for col, lbl in [("#4444ff", "Bobber"), ("#dddd00", "Splash/Bite"), ("#00dddd", "QTE")]:
            tk.Label(leg, text="■", fg=col, bg=DARK, font=("Segoe UI", 10)).pack(side="left")
            tk.Label(leg, text=lbl, fg=MUTED, bg=DARK,
                     font=("Segoe UI", 8)).pack(side="left", padx=(0, 10))

        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x")
        self._bob_lbl    = tk.Label(bar, text="bob=—", bg=PANEL, fg=MUTED,
                                    font=("Consolas", 8))
        self._bob_lbl.pack(side="left", padx=8, pady=3)
        self._splash_lbl = tk.Label(bar, text="splash=—", bg=PANEL, fg=MUTED,
                                    font=("Consolas", 8))
        self._splash_lbl.pack(side="left")
        self._bite_badge = tk.Label(bar, text="", bg=PANEL, fg=RED,
                                    font=("Segoe UI", 8, "bold"))
        self._bite_badge.pack(side="right", padx=8)

    def _start_poll(self):
        if not self._poll_running:
            self._poll_running = True
            self._poll()

    def _poll(self):
        if not self._poll_running:
            return
        try:
            if not self.winfo_exists():
                self._poll_running = False
                return
        except Exception:
            self._poll_running = False
            return

        with self._lock:
            frame = self._pending
            self._pending = None

        if frame is not None:
            try:
                cw = self._canvas.winfo_width()  or self._W
                ch = self._canvas.winfo_height() or self._H
                if cw > 4 and ch > 4:
                    fh, fw = frame.shape[:2]
                    scale  = min(cw / max(fw, 1), ch / max(fh, 1))
                    nw     = max(int(fw * scale), 1)
                    nh     = max(int(fh * scale), 1)
                    disp   = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_NEAREST)
                    rgb    = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
                    self._img_tk = ImageTk.PhotoImage(Image.fromarray(rgb))
                    self._canvas.delete("all")
                    self._canvas.create_image(cw // 2, ch // 2,
                                              image=self._img_tk, anchor="center")
                self._fps_count += 1
                now = time.time()
                if now - self._fps_ts >= 1.0:
                    self._fps_disp  = self._fps_count
                    self._fps_count = 0
                    self._fps_ts    = now
                    self._fps_lbl.config(text=f"{self._fps_disp} fps")
            except Exception:
                pass

        self.after(self._FPS_MS, self._poll)

    def push_frame(self, bgr: np.ndarray):
        with self._lock:
            self._pending = bgr

    def set_state(self, state: FishState):
        try:
            if self.winfo_exists():
                color = STATE_COLORS.get(state, MUTED)
                self.after(0, lambda: self._state_badge.config(
                    text=state.name, fg=color) if self.winfo_exists() else None)
        except Exception:
            pass

    def set_pixels(self, bob_px: int, splash_px: int, splash_min: int):
        try:
            if not self.winfo_exists():
                return
            bite = splash_px >= splash_min
            def _upd():
                try:
                    if not self.winfo_exists():
                        return
                    self._bob_lbl.config(text=f"bob={bob_px}")
                    self._splash_lbl.config(text=f"splash={splash_px}",
                                            fg=RED if bite else GREEN)
                    self._bite_badge.config(text="● BITE!" if bite else "")
                except Exception:
                    pass
            self.after(0, _upd)
        except Exception:
            pass

    def _on_close(self):
        self._poll_running = False
        try:
            self.withdraw()
        except Exception:
            pass

    def show_viewer(self):
        try:
            self.deiconify()
            self.wm_attributes("-topmost", True)
            self._start_poll()
        except Exception:
            pass


class RegionDrawer(tk.Toplevel):
    def __init__(self, parent, wm: WindowManager, cfg: Config,
                 on_save: Callable, mode: str = "scan"):
        super().__init__(parent)
        self.wm       = wm
        self.cfg      = cfg
        self._on_save = on_save
        self._mode    = mode
        label         = "water area" if mode == "scan" else "QTE indicator area"
        self.title(f"Draw Region — {label}")
        self.configure(bg=DARK)
        self.resizable(True, True)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        tk.Label(self, text=f"Drag a rectangle over the {label} only.",
                 bg=DARK, fg=TEXT, font=("Segoe UI", 10)).pack(pady=8)

        self._canvas = tk.Canvas(self, bg="#000000", cursor="crosshair")
        self._canvas.pack(fill="both", expand=True, padx=8, pady=4)

        btn_row = tk.Frame(self, bg=DARK)
        btn_row.pack(pady=8)
        tk.Button(btn_row, text="Refresh", bg=CARD, fg=TEXT, relief="flat",
                  font=("Segoe UI", 9), command=self._load).pack(side="left", padx=6)
        tk.Button(btn_row, text="Save Region", bg=GREEN, fg=DARK, relief="flat",
                  font=("Segoe UI", 9, "bold"), command=self._save).pack(side="left", padx=6)
        tk.Button(btn_row, text="Cancel", bg=CARD, fg=MUTED, relief="flat",
                  font=("Segoe UI", 9), command=self.destroy).pack(side="left", padx=6)

        self._img_tk   = None
        self._rect_id  = None
        self._x0 = self._y0 = self._x1 = self._y1 = 0
        self._src_w = self._src_h = 1
        self._scale_x = self._scale_y = 1.0
        self._dragging = False

        self._canvas.bind("<ButtonPress-1>",   self._on_press)
        self._canvas.bind("<B1-Motion>",        self._on_drag)
        self._canvas.bind("<ButtonRelease-1>",  self._on_release)
        self._load()

    def _load(self):
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
        self._img_tk  = ImageTk.PhotoImage(Image.fromarray(rgb_r))
        self._canvas.config(width=disp_w, height=disp_h)
        self._canvas.create_image(0, 0, anchor="nw", image=self._img_tk)
        self._rect_id = None
        self.geometry(f"{disp_w+20}x{disp_h+120}")

    def _on_press(self, e):
        self._x0 = e.x; self._y0 = e.y; self._dragging = True
        if self._rect_id:
            self._canvas.delete(self._rect_id)

    def _on_drag(self, e):
        if not self._dragging:
            return
        if self._rect_id:
            self._canvas.delete(self._rect_id)
        self._x1 = e.x; self._y1 = e.y
        self._rect_id = self._canvas.create_rectangle(
            self._x0, self._y0, self._x1, self._y1, outline="#00ff88", width=2)

    def _on_release(self, e):
        self._x1 = e.x; self._y1 = e.y; self._dragging = False

    def _save(self):
        if self._x0 == self._x1 or self._y0 == self._y1:
            messagebox.showwarning("No region", "Draw a rectangle first.", parent=self)
            return
        x1 = min(self._x0, self._x1); y1 = min(self._y0, self._y1)
        x2 = max(self._x0, self._x1); y2 = max(self._y0, self._y1)
        p  = [round(x1 * self._scale_x / self._src_w, 4),
              round(y1 * self._scale_y / self._src_h, 4),
              round(x2 * self._scale_x / self._src_w, 4),
              round(y2 * self._scale_y / self._src_h, 4)]
        if self._mode == "scan":
            self.cfg.scan_x1_pct     = p[0]; self.cfg.scan_y1_pct = p[1]
            self.cfg.scan_x2_pct     = p[2]; self.cfg.scan_y2_pct = p[3]
            self.cfg.scan_region_set = True
        else:
            self.cfg.qte_scan_x1_pct = p[0]; self.cfg.qte_scan_y1_pct = p[1]
            self.cfg.qte_scan_x2_pct = p[2]; self.cfg.qte_scan_y2_pct = p[3]
            self.cfg.qte_region_set  = True
        try:
            self._on_save()
        except Exception as e:
            log.warning(f"RegionDrawer on_save: {e}")
        self.destroy()


class ColorSamplerDialog(tk.Toplevel):
    def __init__(self, parent, wm: WindowManager, cfg_ref: Config,
                 title: str, on_confirm: Callable, mode: str = "bobber"):
        super().__init__(parent)
        self.wm          = wm
        self.cfg_ref     = cfg_ref
        self._on_confirm = on_confirm
        self._mode       = mode
        self._hsv: Optional[np.ndarray] = None
        self._bgr: Optional[np.ndarray] = None
        self._lo:  Optional[list] = None
        self._hi:  Optional[list] = None
        self._picking    = False

        self.title(title)
        self.configure(bg=DARK)
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        tk.Label(self, text=title, bg=DARK, fg=TEXT,
                 font=("Segoe UI", 12, "bold")).pack(pady=(14, 2), padx=20)
        tk.Label(self, text=self._guide_text(), bg=DARK, fg=MUTED,
                 font=("Segoe UI", 9), justify="left").pack(padx=20, pady=6)

        self._preview = tk.Label(self, bg="#333333", width=12, height=2, relief="solid")
        self._preview.pack(pady=4)
        self._info = tk.Label(self, text="No sample yet", bg=DARK, fg=MUTED,
                              font=("Segoe UI", 9))
        self._info.pack()

        for label, attr, lo_val, hi_val in [
            ("Hue tol ±", "_tol_h",    8,  30),
            ("Sat floor", "_sat_floor", 80, 255),
            ("Val floor", "_val_floor", 80, 255),
        ]:
            row = tk.Frame(self, bg=DARK)
            row.pack(fill="x", padx=20, pady=3)
            tk.Label(row, text=label, bg=DARK, fg=MUTED,
                     font=("Segoe UI", 9), width=10).pack(side="left")
            var = tk.IntVar(value=lo_val)
            setattr(self, attr, var)
            tk.Scale(row, from_=0, to=hi_val, orient="horizontal", variable=var,
                     bg=DARK, fg=TEXT, troughcolor=CARD, highlightthickness=0,
                     command=lambda _: self._update_range()
                     ).pack(side="left", fill="x", expand=True)

        self._range_lbl = tk.Label(self, text="Range: —", bg=DARK, fg=MUTED,
                                   font=("Consolas", 8))
        self._range_lbl.pack(pady=2)

        for label, attr, default, top in [
            ("Min px", "_min_px", 20,  500),
            ("Max px", "_max_px", 500, 5000),
        ]:
            row = tk.Frame(self, bg=DARK)
            row.pack(fill="x", padx=20, pady=3)
            tk.Label(row, text=label, bg=DARK, fg=MUTED,
                     font=("Segoe UI", 9), width=10).pack(side="left")
            var = tk.IntVar(value=default)
            setattr(self, attr, var)
            tk.Scale(row, from_=1, to=top, orient="horizontal", variable=var,
                     bg=DARK, fg=TEXT, troughcolor=CARD, highlightthickness=0
                     ).pack(side="left", fill="x", expand=True)

        btn_row = tk.Frame(self, bg=DARK)
        btn_row.pack(pady=12)
        self._pick_btn = tk.Button(btn_row, text="Pick Pixel", bg=CARD, fg=TEXT,
                                   relief="flat", font=("Segoe UI", 9),
                                   command=self._start_pick)
        self._pick_btn.pack(side="left", padx=4)
        tk.Button(btn_row, text="Test", bg=CARD, fg=TEXT, relief="flat",
                  font=("Segoe UI", 9), command=self._test).pack(side="left", padx=4)
        tk.Button(btn_row, text="Confirm", bg=GREEN, fg=DARK, relief="flat",
                  font=("Segoe UI", 9, "bold"), command=self._confirm).pack(side="left", padx=4)
        tk.Button(btn_row, text="Cancel", bg=CARD, fg=MUTED, relief="flat",
                  font=("Segoe UI", 9), command=self.destroy).pack(side="left", padx=4)

    def _guide_text(self) -> str:
        if self._mode == "bobber":
            return ("1. Bobber must be floating in water in Roblox\n"
                    "2. Click Pick Pixel\n"
                    "3. Hover cursor over the bobber's colored tip\n"
                    "4. Press Enter to capture\n"
                    "5. Click Test — result must say VISIBLE\n"
                    "6. If NOT VISIBLE: lower Sat/Val floor sliders\n"
                    "7. Click Confirm")
        if self._mode == "splash":
            return ("The Splash is the cyan glow when a fish bites (~1 sec).\n\n"
                    "Option A — Live:\n"
                    "  Wait for a bite → Click Pick Pixel → hover cyan glow → Enter\n\n"
                    "Option B — Screenshot:\n"
                    "  Take Win+Shift+S of the bite → hover any cyan pixel → Enter\n\n"
                    "Test → check debug_test_splash.png → Confirm")
        return ("QTE = when the game shows a prompt to press a key.\n\n"
                "1. Fish until a QTE prompt appears on screen\n"
                "2. Click Pick Pixel → hover the unique color of the prompt → Enter\n"
                "3. Draw QTE Region (Calibrate tab) to narrow the scan zone\n"
                "   — prevents false detections from background colors\n"
                "4. Set QTE Keys in Settings (exact keys the game asks you to press)\n"
                "5. Test → Confirm")

    def _start_pick(self):
        self._picking = True
        self._pick_btn.config(text="Hover target → Enter", bg=ACCENT)
        self.bind("<Return>", self._capture)
        self.focus_set()

    def _capture(self, _=None):
        if not self._picking:
            return
        try:
            x, y = win32api.GetCursorPos()
            self._hsv, self._bgr = _grab_pixel_hsv(x, y)
        except Exception as e:
            messagebox.showerror("Capture failed", str(e), parent=self)
            return
        self._picking = False
        self._pick_btn.config(text="Pick Pixel", bg=CARD)
        self._update_range()
        r, g, b = int(self._bgr[2]), int(self._bgr[1]), int(self._bgr[0])
        self._preview.config(bg=f"#{r:02x}{g:02x}{b:02x}")
        h, s, v = int(self._hsv[0]), int(self._hsv[1]), int(self._hsv[2])
        self._info.config(text=f"HSV H={h} S={s} V={v}  at ({x},{y})", fg=TEXT)

    def _update_range(self):
        if self._hsv is None:
            return
        h  = int(self._hsv[0])
        th = self._tol_h.get()
        sf = self._sat_floor.get()
        vf = self._val_floor.get()
        self._lo = [max(0, h - th), sf, vf]
        self._hi = [min(180, h + th), 255, 255]
        self._range_lbl.config(text=f"lo={self._lo}  hi={self._hi}")

    def _test(self):
        if self._lo is None:
            messagebox.showwarning("No sample", "Pick a pixel first.", parent=self)
            return
        frame = _grab_once(self.wm)
        if frame is None:
            messagebox.showerror("Error", "Cannot grab screen.", parent=self)
            return
        tmp = Config()
        tmp.scan_x1_pct          = self.cfg_ref.scan_x1_pct
        tmp.scan_y1_pct          = self.cfg_ref.scan_y1_pct
        tmp.scan_x2_pct          = self.cfg_ref.scan_x2_pct
        tmp.scan_y2_pct          = self.cfg_ref.scan_y2_pct
        tmp.use_bobber_detection = True
        tmp.use_splash_detection = True
        tmp.use_qte              = True
        det = Detector(tmp)

        if self._mode == "bobber":
            tmp.bobber_hsv_low    = self._lo; tmp.bobber_hsv_high   = self._hi
            tmp.bobber_min_pixels = self._min_px.get()
            tmp.bobber_max_pixels = self._max_px.get()
            tmp.bobber_calibrated = True
            px  = det.bobber_pixels(frame)
            vis = tmp.bobber_min_pixels <= px <= tmp.bobber_max_pixels
            det.save_debug(frame, "test")
            messagebox.showinfo("Test",
                f"Pixels: {px}\nMin: {tmp.bobber_min_pixels}  Max: {tmp.bobber_max_pixels}\n\n"
                f"{'✓ VISIBLE — confirm!' if vis else '✗ NOT VISIBLE — lower Sat/Val floor'}\n\n"
                f"See debug_test.png", parent=self)
        elif self._mode == "splash":
            tmp.splash_hsv_low    = self._lo; tmp.splash_hsv_high   = self._hi
            tmp.splash_min_pixels = self._min_px.get()
            tmp.splash_calibrated = True
            tmp.bobber_calibrated = self.cfg_ref.bobber_calibrated
            tmp.bobber_hsv_low    = self.cfg_ref.bobber_hsv_low
            tmp.bobber_hsv_high   = self.cfg_ref.bobber_hsv_high
            px  = det.splash_pixels(frame)
            vis = px >= tmp.splash_min_pixels
            det.save_debug(frame, "test_splash")
            messagebox.showinfo("Test",
                f"Splash pixels: {px}\nMin needed: {tmp.splash_min_pixels}\n\n"
                f"{'✓ DETECTED — confirm!' if vis else '✗ NOT DETECTED — lower floors or resample during live bite'}\n\n"
                f"See debug_test_splash.png", parent=self)
        else:
            tmp.qte_hsv_low      = self._lo; tmp.qte_hsv_high      = self._hi
            tmp.qte_min_pixels   = self._min_px.get()
            tmp.qte_calibrated   = True
            tmp.qte_scan_x1_pct  = self.cfg_ref.qte_scan_x1_pct
            tmp.qte_scan_y1_pct  = self.cfg_ref.qte_scan_y1_pct
            tmp.qte_scan_x2_pct  = self.cfg_ref.qte_scan_x2_pct
            tmp.qte_scan_y2_pct  = self.cfg_ref.qte_scan_y2_pct
            tmp.qte_region_set   = self.cfg_ref.qte_region_set
            px  = det.qte_pixels(frame)
            vis = px >= tmp.qte_min_pixels
            det.save_debug(frame, "test_qte")
            messagebox.showinfo("Test",
                f"QTE pixels: {px}\nMin needed: {tmp.qte_min_pixels}\n\n"
                f"{'✓ DETECTED' if vis else '✗ NOT DETECTED — sample during active QTE or draw QTE region'}\n\n"
                f"See debug_test_qte.png", parent=self)

    def _confirm(self):
        if self._lo is None:
            messagebox.showwarning("No sample", "Pick a pixel first.", parent=self)
            return
        try:
            self._on_confirm(self._lo, self._hi, self._min_px.get(), self._max_px.get())
        except Exception as e:
            log.warning(f"Sampler confirm: {e}")
        self.destroy()


class HotkeyEntry(tk.Frame):
    _MOD_MAP = {"shift_l": "shift", "shift_r": "shift",
                "control_l": "ctrl", "control_r": "ctrl",
                "alt_l": "alt", "alt_r": "alt"}

    def __init__(self, parent, label: str, value: str, on_change: Callable, **kw):
        super().__init__(parent, bg=PANEL, **kw)
        self._cb        = on_change
        self._value     = value
        self._listening = False
        self._held      = set()

        tk.Label(self, text=label, bg=PANEL, fg=MUTED, width=16,
                 anchor="w", font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))
        self._btn = tk.Button(self, text=self._fmt(value), width=18, bg=CARD, fg=TEXT,
                              relief="flat", font=("Segoe UI", 9, "bold"),
                              activebackground=ACCENT, activeforeground=TEXT,
                              command=self._listen)
        self._btn.pack(side="left", padx=6, pady=3)

    def _fmt(self, v): return v.upper() if v else "—"

    def _listen(self):
        if self._listening:
            return
        self._listening = True
        self._held      = set()
        self._btn.config(text="[ press combo... ]", bg=ACCENT)
        self._btn.bind("<KeyPress>",   self._kp)
        self._btn.bind("<KeyRelease>", self._kr)
        self._btn.focus_set()

    def _norm(self, sym): return self._MOD_MAP.get(sym.lower(), sym.lower())

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

    def get(self): return self._value

    def set(self, v):
        self._value = v
        self._btn.config(text=self._fmt(v))


class BaitPanel(tk.LabelFrame):
    _MAX = 9

    def __init__(self, parent, cfg: Config, inp: InputHandler,
                 wm: WindowManager, on_change: Callable):
        super().__init__(parent, text=" Bait Switcher ",
                         bg=PANEL, fg=MUTED, font=("Segoe UI", 8),
                         bd=1, relief="groove")
        self.cfg        = cfg
        self.inp        = inp
        self.wm         = wm
        self._on_change = on_change
        self._rows: list = []
        self._active_lbl: Optional[tk.Label] = None
        self._build()

    def _build(self):
        intro = tk.Frame(self, bg=PANEL)
        intro.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(intro,
                 text="Each slot = one exact Roblox hotbar key.\n"
                      "Bot presses that key ONLY → waits → left-clicks → waits → presses rod key.\n"
                      "Nothing else is ever sent.",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 8),
                 justify="left").pack(anchor="w")

        self._en_var = tk.BooleanVar(value=self.cfg.use_bait)
        tk.Checkbutton(self, text="Enable bait switching", variable=self._en_var,
                       bg=PANEL, fg=TEXT, selectcolor=CARD, activebackground=PANEL,
                       font=("Segoe UI", 9, "bold"),
                       command=self._toggle).pack(anchor="w", padx=10, pady=2)

        seq_frame = tk.LabelFrame(self, text=" Sequence preview ", bg=PANEL, fg=MUTED,
                                  font=("Segoe UI", 8), bd=1, relief="groove")
        seq_frame.pack(fill="x", padx=10, pady=(2, 6))
        self._seq_lbl = tk.Label(seq_frame,
                                 text="Press [?] → wait → Left Click → wait → Press [rod key]",
                                 bg=PANEL, fg=CYAN, font=("Consolas", 8))
        self._seq_lbl.pack(padx=8, pady=4)
        self._active_lbl = tk.Label(seq_frame, text="No slot active",
                                    bg=PANEL, fg=MUTED, font=("Segoe UI", 8))
        self._active_lbl.pack(padx=8, pady=(0, 4))

        self._slots_frame = tk.Frame(self, bg=PANEL)
        self._slots_frame.pack(fill="x", padx=10)
        self._rebuild_slots()

        timing_frame = tk.LabelFrame(self, text=" Timing (ms) ", bg=PANEL, fg=MUTED,
                                     font=("Segoe UI", 8), bd=1, relief="groove")
        timing_frame.pack(fill="x", padx=10, pady=(6, 4))
        self._timing_vars: dict = {}
        timing_fields = [
            ("Key hold",       "bait_select_hold_ms",  10,  500, 80),
            ("After key",      "bait_post_select_ms",  50, 2000, 300),
            ("Click hold",     "bait_click_hold_ms",   10,  500, 80),
            ("After click",    "bait_post_click_ms",   50, 2000, 400),
            ("After rod key",  "bait_post_rod_ms",     50, 2000, 400),
        ]
        for lbl, attr, mn, mx, default in timing_fields:
            row = tk.Frame(timing_frame, bg=PANEL)
            row.pack(fill="x", padx=6, pady=1)
            tk.Label(row, text=lbl, bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 8), width=12, anchor="w").pack(side="left")
            var = tk.IntVar(value=int(getattr(self.cfg, attr, default)))
            tk.Scale(row, from_=mn, to=mx, orient="horizontal", variable=var,
                     bg=PANEL, fg=TEXT, troughcolor=CARD, highlightthickness=0,
                     length=160,
                     command=lambda _, a=attr, v=var: self._timing_change(a, v)
                     ).pack(side="left")
            val_lbl = tk.Label(row, textvariable=var, bg=PANEL, fg=TEXT,
                               font=("Consolas", 8), width=4)
            val_lbl.pack(side="left", padx=4)
            self._timing_vars[attr] = var

        btn_row = tk.Frame(self, bg=PANEL)
        btn_row.pack(fill="x", padx=10, pady=(4, 8))
        tk.Button(btn_row, text="+ Add Slot", bg=CARD, fg=TEXT, relief="flat",
                  font=("Segoe UI", 8), command=self._add).pack(side="left", padx=2)
        tk.Button(btn_row, text="Save All", bg=ACCENT, fg=TEXT, relief="flat",
                  font=("Segoe UI", 8, "bold"), command=self._save).pack(side="right", padx=2)

        self._update_seq_preview()

    def _timing_change(self, attr: str, var: tk.IntVar):
        setattr(self.cfg, attr, float(var.get()))
        self._update_seq_preview()

    def _update_seq_preview(self):
        slots  = self.cfg.active_bait_slots()
        rod    = self.cfg.equip_rod_key.strip() or "?"
        if slots:
            keys   = [s["key"].strip() or "?" for s in slots]
            key_str = "/".join(keys)
        else:
            key_str = "?"
        sh  = int(self.cfg.bait_select_hold_ms)
        ps  = int(self.cfg.bait_post_select_ms)
        ch  = int(self.cfg.bait_click_hold_ms)
        pc  = int(self.cfg.bait_post_click_ms)
        pr  = int(self.cfg.bait_post_rod_ms)
        txt = (f"Press [{key_str}] hold {sh}ms → wait {ps}ms → "
               f"Left Click hold {ch}ms → wait {pc}ms → "
               f"Press [{rod}] → wait {pr}ms")
        try:
            self._seq_lbl.config(text=txt)
        except Exception:
            pass

    def _rebuild_slots(self):
        for w in self._slots_frame.winfo_children():
            w.destroy()
        self._rows.clear()

        hdr = tk.Frame(self._slots_frame, bg=PANEL)
        hdr.pack(fill="x", pady=(2, 0))
        for t, w in [("✓", 2), ("Key", 5), ("Label", 12),
                     ("Sequence", 30), ("Test", 6), ("", 3)]:
            tk.Label(hdr, text=t, bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 8, "bold"), width=w,
                     anchor="w").pack(side="left", padx=2)

        tk.Frame(self._slots_frame, bg=MUTED, height=1).pack(fill="x", pady=2)

        for i, slot in enumerate(self.cfg.bait_slots):
            self._build_slot_row(i, slot)

    def _build_slot_row(self, i: int, slot: dict):
        row = tk.Frame(self._slots_frame, bg=PANEL)
        row.pack(fill="x", pady=2)

        en_var  = tk.BooleanVar(value=slot.get("enabled", True))
        key_var = tk.StringVar(value=slot.get("key", str(i + 1)))
        lbl_var = tk.StringVar(value=slot.get("label", f"Bait {i+1}"))

        en_cb = tk.Checkbutton(row, variable=en_var, bg=PANEL, selectcolor=CARD,
                               activebackground=PANEL,
                               command=lambda v=en_var, idx=i: self._slot_en_change(v, idx))
        en_cb.pack(side="left", padx=2)

        key_entry = tk.Entry(row, textvariable=key_var, bg=CARD, fg=ORANGE,
                             insertbackground=TEXT, relief="flat",
                             font=("Consolas", 10, "bold"), width=4,
                             justify="center")
        key_entry.pack(side="left", padx=2)
        key_entry.bind("<FocusOut>", lambda e, idx=i: self._slot_key_changed(idx))
        key_entry.bind("<Return>",   lambda e, idx=i: self._slot_key_changed(idx))

        lbl_entry = tk.Entry(row, textvariable=lbl_var, bg=CARD, fg=MUTED,
                             insertbackground=TEXT, relief="flat",
                             font=("Segoe UI", 8), width=10)
        lbl_entry.pack(side="left", padx=2)

        rod     = self.cfg.equip_rod_key.strip() or "?"
        key_val = key_var.get().strip() or "?"
        seq_txt = f"[{key_val}] → LClick → [{rod}]"
        seq_lbl = tk.Label(row, text=seq_txt, bg=PANEL, fg=CYAN,
                           font=("Consolas", 7), anchor="w")
        seq_lbl.pack(side="left", padx=4)

        test_btn = tk.Button(row, text="▶ Test", bg=CARD, fg=GREEN, relief="flat",
                             font=("Segoe UI", 8),
                             command=lambda kv=key_var, lv=lbl_var: self._test_slot(kv, lv))
        test_btn.pack(side="left", padx=2)

        tk.Button(row, text="✕", bg=PANEL, fg=RED, relief="flat",
                  font=("Segoe UI", 8),
                  command=lambda idx=i: self._del(idx)).pack(side="right", padx=2)

        self._rows.append((en_var, key_var, lbl_var, seq_lbl))

    def _slot_en_change(self, var: tk.BooleanVar, idx: int):
        if idx < len(self.cfg.bait_slots):
            self.cfg.bait_slots[idx]["enabled"] = var.get()
        self._update_seq_preview()

    def _slot_key_changed(self, idx: int):
        if idx < len(self._rows):
            _, key_var, _, seq_lbl = self._rows[idx]
            k   = key_var.get().strip()
            rod = self.cfg.equip_rod_key.strip() or "?"
            seq_lbl.config(text=f"[{k or '?'}] → LClick → [{rod}]")
        self._update_seq_preview()

    def _test_slot(self, key_var: tk.StringVar, lbl_var: tk.StringVar):
        k = key_var.get().strip()
        r = self.cfg.equip_rod_key.strip()
        lbl = lbl_var.get().strip() or k

        if not k:
            messagebox.showerror("Empty key",
                                 "The slot key is empty.\n"
                                 "Enter the Roblox hotbar number for this bait (e.g. 6).",
                                 parent=self)
            return
        if not r:
            messagebox.showerror("No rod key",
                                 "Equip rod key is empty.\n"
                                 "Set it in Settings → Equip rod key.",
                                 parent=self)
            return

        if not self.wm.exists():
            if not self.wm.find():
                messagebox.showerror("Roblox not found",
                                     "Open Roblox first — the test sends real key presses.",
                                     parent=self)
                return

        answer = messagebox.askyesno(
            "Confirm live test",
            f"This will send to Roblox RIGHT NOW:\n\n"
            f"  1. Press [{k}]  (select \"{lbl}\")\n"
            f"  2. Left Click  (use/equip bait)\n"
            f"  3. Press [{r}]  (re-equip rod)\n\n"
            f"Make sure Roblox is open and your character is in a safe spot.\n\n"
            f"Continue?",
            parent=self)
        if not answer:
            return

        result = self.inp.bait_sequence(
            k, r,
            self.cfg.bait_select_hold_ms,
            self.cfg.bait_post_select_ms,
            self.cfg.bait_click_hold_ms,
            self.cfg.bait_post_click_ms,
            self.cfg.bait_post_rod_ms,
        )
        log.info(f"Bait test [{lbl}]: {result}")

        if result.startswith("OK"):
            messagebox.showinfo("Test complete",
                                f"Sequence finished:\n{result}\n\n"
                                f"Check Roblox — did \"{lbl}\" get selected and used?",
                                parent=self)
        else:
            messagebox.showerror("Test failed", result, parent=self)

    def _toggle(self):
        self.cfg.use_bait = self._en_var.get()
        self._on_change()

    def _add(self):
        if len(self.cfg.bait_slots) >= self._MAX:
            messagebox.showinfo("Whoa there", f"You can only use up to {self._MAX} bait slots.", parent=self)
            return
        n = len(self.cfg.bait_slots) + 1
        self.cfg.bait_slots.append({"key": str(n), "enabled": True, "label": f"Bait {n}"})
        self._rebuild_slots()
        self._update_seq_preview()

    def _del(self, idx: int):
        if len(self.cfg.bait_slots) <= 1:
            messagebox.showinfo("Hold on", "You need to keep at least one bait slot active.", parent=self)
            return
        self.cfg.bait_slots.pop(idx)
        self._rebuild_slots()
        self._update_seq_preview()

    def _save(self):
        new = []
        for en_var, key_var, lbl_var, _ in self._rows:
            k = key_var.get().strip()
            if not k:
                messagebox.showerror("Empty key",
                                     "A slot key is empty.\n"
                                     "Enter the Roblox hotbar number (e.g. 6, 9).",
                                     parent=self)
                return
            if len(k) > 3:
                messagebox.showerror("Key too long",
                                     f"Key {k!r} looks wrong.\n"
                                     "Enter a single key like  6  or  9  — exactly as "
                                     "shown in Roblox hotbar.",
                                     parent=self)
                return
            new.append({"key": k, "enabled": en_var.get(),
                        "label": lbl_var.get().strip() or k})
        self.cfg.bait_slots = new
        self.cfg.use_bait   = self._en_var.get()
        self._update_seq_preview()
        self._on_change()

    def refresh(self):
        self._en_var.set(self.cfg.use_bait)
        self._rebuild_slots()
        self._update_seq_preview()

    def notify_activated(self, key: str, label: str):
        try:
            rod = self.cfg.equip_rod_key.strip() or "?"
            msg = f"Last used: [{key}] \"{label}\" → LClick → [{rod}] ✓"
            if self._active_lbl:
                self._active_lbl.config(text=msg, fg=GREEN)
        except Exception:
            pass


class FishBotUI:
    def __init__(self):
        self.cfg     = Config()
        self.cfg.load()
        self.wm      = WindowManager(self.cfg.target_exe)
        self.inp     = InputHandler()
        self.stats   = Stats()
        self.fish:   Optional[FishBot]      = None
        self.viewer: Optional[VisionViewer] = None

        self.active       = False
        self._stopping    = False
        self._toggle_lock = threading.Lock()
        self._reg_hks: list = []
        self._log_handler: Optional[logging.Handler] = None

        self.root = tk.Tk()
        self.root.title("FishBot")
        self.root.configure(bg=DARK)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build()
        self._reg_hotkeys()
        self._ui_tick()

    def _card(self, parent, title: str) -> tk.LabelFrame:
        f = tk.LabelFrame(parent, text=f" {title} ", bg=PANEL, fg=MUTED,
                          font=("Segoe UI", 8), bd=1, relief="groove")
        f.pack(fill="x", pady=3)
        return f

    def _build(self):
        self._build_header()
        outer = tk.Frame(self.root, bg=DARK)
        outer.pack(fill="both", padx=10, pady=(0, 10))

        nb    = ttk.Notebook(outer)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook",     background=DARK, borderwidth=0)
        style.configure("TNotebook.Tab", background=CARD, foreground=TEXT,
                        padding=[10, 4], font=("Segoe UI", 9))
        style.map("TNotebook.Tab",       background=[("selected", ACCENT)])
        nb.pack(fill="both", expand=True)

        tab_main = tk.Frame(nb, bg=DARK)
        tab_bait = tk.Frame(nb, bg=DARK)
        tab_cal  = tk.Frame(nb, bg=DARK)
        tab_hk   = tk.Frame(nb, bg=DARK)
        nb.add(tab_main, text="  Main  ")
        nb.add(tab_bait, text="  Bait  ")
        nb.add(tab_cal,  text="  Calibrate  ")
        nb.add(tab_hk,   text="  Hotkeys  ")

        left  = tk.Frame(tab_main, bg=DARK)
        right = tk.Frame(tab_main, bg=DARK)
        left.pack(side="left",  fill="both", expand=True, padx=(0, 5), pady=4)
        right.pack(side="left", fill="both", expand=True, pady=4)

        self._build_state(left)
        self._build_stats(left)
        self._build_feature_toggles(left)
        self._build_settings(right)

        self._bait_panel = BaitPanel(tab_bait, self.cfg, self.inp,
                                     self.wm, self._on_bait_change)
        self._bait_panel.pack(fill="both", expand=True, padx=8, pady=8)

        self._build_calibration(tab_cal)
        self._build_hotkeys(tab_hk)
        self._build_log()

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=ACCENT, height=52)
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
        self._start_btn = tk.Button(hdr, text="▶  START", bg=GREEN, fg=DARK,
                                    relief="flat", font=("Segoe UI", 10, "bold"),
                                    padx=10, pady=3, activebackground="#00ff80",
                                    command=self._toggle)
        self._start_btn.pack(side="right", padx=6)
        tk.Button(hdr, text="👁 Vision", bg=CARD, fg=TEXT, relief="flat",
                  font=("Segoe UI", 9), command=self._toggle_vision
                  ).pack(side="right", padx=4)

    def _build_state(self, parent):
        c = self._card(parent, "State")
        self._state_lbl = tk.Label(c, text="IDLE", bg=PANEL, fg=MUTED,
                                   font=("Segoe UI", 14, "bold"))
        self._state_lbl.pack(pady=(8, 2))
        self._px_lbl = tk.Label(c, text="bob=—  splash=—",
                                bg=PANEL, fg=MUTED, font=("Segoe UI", 8))
        self._px_lbl.pack(pady=(0, 6))

    def _build_stats(self, parent):
        c = self._card(parent, "Session")
        self._sv: dict = {}
        for label in ("Catches", "Casts", "Timeouts", "QTE", "Bait Used", "CPH", "Runtime"):
            row = tk.Frame(c, bg=PANEL)
            row.pack(fill="x", padx=10, pady=1)
            tk.Label(row, text=label, bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 9), width=12, anchor="w").pack(side="left")
            v = tk.StringVar(value="0")
            tk.Label(row, textvariable=v, bg=PANEL, fg=TEXT,
                     font=("Segoe UI", 9, "bold"), anchor="e").pack(side="right")
            self._sv[label] = v
        tk.Frame(c, bg=PANEL, height=4).pack()

    def _build_feature_toggles(self, parent):
        c = self._card(parent, "Features  (each works independently)")
        self._feat_vars: dict = {}
        features = [
            ("use_bobber_detection", "Bobber detection",
             "Wait for bobber before watching for bites.\nDisable = skip straight to splash/QTE."),
            ("use_splash_detection", "Splash / Bite detection",
             "Reel when cyan splash is detected.\nDisable = QTE or timeout only."),
            ("use_qte",              "QTE system",
             "Detect QTE prompt and press configured keys.\nDisable = no QTE handling."),
            ("use_bait",             "Bait switching",
             "Press bait slot key + left-click before each cast.\nConfigure in the Bait tab."),
            ("use_vision",           "Live Vision window",
             "Overlay showing bot detections.\nDisable = lower CPU."),
        ]
        for attr, label, tip in features:
            row = tk.Frame(c, bg=PANEL)
            row.pack(fill="x", padx=8, pady=2)
            var = tk.BooleanVar(value=getattr(self.cfg, attr))
            self._feat_vars[attr] = var
            tk.Checkbutton(row, variable=var, bg=PANEL, selectcolor=CARD,
                           activebackground=PANEL,
                           command=lambda a=attr, v=var: self._toggle_feature(a, v)
                           ).pack(side="left")
            col = tk.Frame(row, bg=PANEL)
            col.pack(side="left", padx=4)
            tk.Label(col, text=label, bg=PANEL, fg=TEXT,
                     font=("Segoe UI", 9, "bold"), anchor="w").pack(anchor="w")
            tk.Label(col, text=tip, bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 8), anchor="w", justify="left").pack(anchor="w")

    def _toggle_feature(self, attr: str, var: tk.BooleanVar):
        setattr(self.cfg, attr, var.get())
        self.cfg.save()
        log.info(f"Feature {attr}={var.get()}")
        if attr == "use_vision" and not var.get():
            if self.viewer and self.viewer.winfo_exists():
                self.viewer.withdraw()

    def _build_calibration(self, parent):
        wrap  = tk.Frame(parent, bg=DARK)
        wrap.pack(fill="both", expand=True, padx=8, pady=8)
        left  = tk.Frame(wrap, bg=DARK)
        right = tk.Frame(wrap, bg=DARK)
        left.pack(side="left",  fill="both", expand=True, padx=(0, 4))
        right.pack(side="left", fill="both", expand=True)

        c = tk.LabelFrame(left, text=" Detection Calibration ", bg=PANEL, fg=MUTED,
                          font=("Segoe UI", 8), bd=1, relief="groove")
        c.pack(fill="x")
        self._cal_lbls: dict = {}
        for name, attr, cmd in [
            ("Bobber color",  "bobber_calibrated", self._cal_bobber),
            ("Splash / Bite", "splash_calibrated", self._cal_splash),
            ("QTE Indicator", "qte_calibrated",    self._cal_qte),
        ]:
            row = tk.Frame(c, bg=PANEL)
            row.pack(fill="x", padx=8, pady=3)
            lbl = tk.Label(row, text=f"{name}: ✗", bg=PANEL, fg=RED,
                           font=("Segoe UI", 9), anchor="w", width=18)
            lbl.pack(side="left")
            tk.Button(row, text="Sample", bg=CARD, fg=TEXT, relief="flat",
                      font=("Segoe UI", 8), command=cmd).pack(side="right")
            self._cal_lbls[attr] = lbl

        c2 = tk.LabelFrame(left, text=" Scan Regions ", bg=PANEL, fg=MUTED,
                           font=("Segoe UI", 8), bd=1, relief="groove")
        c2.pack(fill="x", pady=(6, 0))
        self._region_lbl     = tk.Label(c2, text="Scan region: not set",
                                        bg=PANEL, fg=RED, font=("Segoe UI", 8))
        self._region_lbl.pack(pady=(4, 2), padx=8, anchor="w")
        self._qte_region_lbl = tk.Label(c2, text="QTE region: not set (uses scan region)",
                                        bg=PANEL, fg=MUTED, font=("Segoe UI", 8))
        self._qte_region_lbl.pack(pady=(0, 4), padx=8, anchor="w")
        tk.Button(c2, text="🖱 Draw Scan Region (water area)",
                  bg=CARD, fg=TEXT, relief="flat", font=("Segoe UI", 9, "bold"),
                  command=self._draw_scan_region).pack(pady=3, padx=8, fill="x")
        tk.Button(c2, text="🖱 Draw QTE Region (QTE indicator area)",
                  bg=CARD, fg=TEXT, relief="flat", font=("Segoe UI", 9),
                  command=self._draw_qte_region).pack(pady=3, padx=8, fill="x")
        tk.Button(c2, text="Save Debug Screenshot", bg=CARD, fg=MUTED,
                  relief="flat", font=("Segoe UI", 8),
                  command=self._save_debug_now).pack(pady=(2, 8), padx=8, fill="x")

        guide = tk.LabelFrame(right, text=" Quick Setup Guide ", bg=PANEL, fg=MUTED,
                              font=("Segoe UI", 8), bd=1, relief="groove")
        guide.pack(fill="both", expand=True)
        steps = [
            ("1", "Draw Scan Region",   "Drag over water only.\nExclude land, sky, UI."),
            ("2", "Sample Bobber",      "Colored float bobbing\non the water surface."),
            ("3", "Sample Splash/Bite", "Cyan glow appearing\nwhen a fish bites."),
            ("4", "Sample QTE (opt.)",  "On-screen prompt color\nwhen game asks for key.\nDraw QTE Region first."),
            ("5", "Set QTE Keys",       "Settings → QTE keys csv\ne.g. e,q,z"),
        ]
        for num, title, desc in steps:
            row = tk.Frame(guide, bg=PANEL)
            row.pack(fill="x", padx=8, pady=4)
            tk.Label(row, text=num, bg=ACCENT, fg=TEXT, width=2,
                     font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
            col = tk.Frame(row, bg=PANEL)
            col.pack(side="left")
            tk.Label(col, text=title, bg=PANEL, fg=TEXT,
                     font=("Segoe UI", 9, "bold"), anchor="w").pack(anchor="w")
            tk.Label(col, text=desc, bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 8), anchor="w", justify="left").pack(anchor="w")

    def _build_settings(self, parent):
        c = self._card(parent, "Settings")
        fields = [
            ("Cast hold (ms)",      "cast_hold_ms",          "float"),
            ("Cast timeout (ms)",   "cast_timeout_ms",       "float"),
            ("Settle wait (ms)",    "settle_wait_ms",        "float"),
            ("Reel cooldown (ms)",  "reel_cooldown_ms",      "float"),
            ("QTE interval (ms)",   "qte_interval_ms",       "float"),
            ("QTE keys (csv)",      "qte_keys",              "list"),
            ("Equip rod key",       "equip_rod_key",         "str"),
            ("Acquire frames",      "bobber_acquire_frames", "int"),
            ("Bite confirm frames", "bite_confirm_frames",   "int"),
            ("Splash min px",       "splash_min_pixels",     "int"),
            ("Bobber min px",       "bobber_min_pixels",     "int"),
            ("Bobber max px",       "bobber_max_pixels",     "int"),
        ]
        self._sv2: dict = {}
        for label, attr, kind in fields:
            row = tk.Frame(c, bg=PANEL)
            row.pack(fill="x", padx=8, pady=2)
            tk.Label(row, text=label, bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 9), width=20, anchor="w").pack(side="left")
            var = tk.StringVar()
            val = getattr(self.cfg, attr)
            var.set(",".join(val) if kind == "list" else str(val))
            tk.Entry(row, textvariable=var, bg=CARD, fg=TEXT,
                     insertbackground=TEXT, relief="flat",
                     font=("Segoe UI", 9), width=9).pack(side="right")
            self._sv2[attr] = (var, kind)
        tk.Button(c, text="Apply & Save", bg=ACCENT, fg=TEXT, relief="flat",
                  font=("Segoe UI", 9, "bold"), activebackground="#ff6070",
                  command=self._apply).pack(pady=6, padx=8, fill="x")

    def _build_hotkeys(self, parent):
        wrap = tk.Frame(parent, bg=DARK)
        wrap.pack(fill="both", expand=True, padx=8, pady=8)
        c = tk.LabelFrame(wrap, text=" Global Hotkeys ", bg=PANEL, fg=MUTED,
                          font=("Segoe UI", 8), bd=1, relief="groove")
        c.pack(fill="x")
        for label, attr in [("Start / Stop",  "hotkey_start_stop"),
                             ("Exit",          "hotkey_exit"),
                             ("Vision Toggle", "hotkey_vision")]:
            e = HotkeyEntry(c, label, getattr(self.cfg, attr),
                            lambda v, a=attr: self._set_hk(a, v))
            e.pack(fill="x", pady=2)

        info = tk.LabelFrame(wrap, text=" Roblox Slot Hotkeys — How it works ", bg=PANEL, fg=MUTED,
                             font=("Segoe UI", 8), bd=1, relief="groove")
        info.pack(fill="x", pady=(8, 0))
        tk.Label(info,
                 text=("Roblox hotbar slots are 1–9 by default.\n\n"
                       "In the Bait tab, each slot's Key field = the EXACT key\n"
                       "the bot sends to Roblox to select that item.\n\n"
                       "The bot ONLY sends the key you type — nothing else.\n\n"
                       "Example:\n"
                       "  Bait key = 6   →  bot presses 6 only\n"
                       "  Bait key = 9   →  bot presses 9 only\n"
                       "  Rod key  = 0   →  bot presses 0 to re-equip rod\n\n"
                       "Use ▶ Test button on each slot to verify before running."),
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 9),
                 justify="left").pack(padx=10, pady=8, anchor="w")

    def _build_log(self):
        c = self._card(self.root, "Log")
        c.pack(fill="both", padx=10, pady=(0, 10))
        self._log_box = tk.Text(c, bg=DARK, fg="#aaaaaa", height=6,
                                font=("Consolas", 8), relief="flat",
                                state="disabled", wrap="word")
        sb = ttk.Scrollbar(c, command=self._log_box.yview)
        self._log_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log_box.pack(fill="both", expand=True, padx=4, pady=4)

        if self._log_handler:
            log.removeHandler(self._log_handler)

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
        self._log_handler = h

    def _append_log(self, msg: str):
        try:
            self.root.after(0, self._append_log_safe, msg)
        except Exception:
            pass

    def _append_log_safe(self, msg: str):
        try:
            self._log_box.configure(state="normal")
            self._log_box.insert("end", msg + "\n")
            self._log_box.see("end")
            self._log_box.configure(state="disabled")
        except Exception:
            pass

    def _toggle_vision(self):
        if not self.cfg.use_vision:
            return
        try:
            if self.viewer is None or not self.viewer.winfo_exists():
                self.viewer = VisionViewer(self.root)
                self.viewer.show_viewer()
            elif self.viewer.state() == "withdrawn":
                self.viewer.show_viewer()
            else:
                self.viewer.withdraw()
        except Exception as e:
            log.warning(f"toggle_vision: {e}")
            self.viewer = None

    def _ensure_viewer(self):
        if not self.cfg.use_vision:
            return
        try:
            if self.viewer is None or not self.viewer.winfo_exists():
                self.viewer = VisionViewer(self.root)
                self.viewer.show_viewer()
            elif self.viewer.state() == "withdrawn":
                self.viewer.show_viewer()
        except Exception as e:
            log.warning(f"ensure_viewer: {e}")
            self.viewer = None

    def _cal_bobber(self):
        def confirm(lo, hi, min_px, max_px):
            self.cfg.bobber_hsv_low    = lo;  self.cfg.bobber_hsv_high   = hi
            self.cfg.bobber_min_pixels = min_px; self.cfg.bobber_max_pixels = max_px
            self.cfg.bobber_calibrated = True; self.cfg.save()
            log.info(f"Bobber calibrated lo={lo} hi={hi} min={min_px} max={max_px}")
        if not self.wm.find():
            messagebox.showerror("Hold on!", "You need to open Roblox first before we can do this.")
            return
        ColorSamplerDialog(self.root, self.wm, self.cfg,
                           "Sample Bobber Color", confirm, mode="bobber")

    def _cal_splash(self):
        def confirm(lo, hi, min_px, _):
            self.cfg.splash_hsv_low    = lo;  self.cfg.splash_hsv_high   = hi
            self.cfg.splash_min_pixels = min_px; self.cfg.splash_calibrated = True
            self.cfg.save()
            log.info(f"Splash calibrated lo={lo} hi={hi} min={min_px}")
        if not self.wm.find():
            messagebox.showerror("Hold on!", "You need to open Roblox first before we can do this.")
            return
        ColorSamplerDialog(self.root, self.wm, self.cfg,
                           "Sample Cyan Splash (Bite Indicator)", confirm, mode="splash")

    def _cal_qte(self):
        def confirm(lo, hi, min_px, _):
            self.cfg.qte_hsv_low    = lo;  self.cfg.qte_hsv_high   = hi
            self.cfg.qte_min_pixels = min_px; self.cfg.qte_calibrated = True
            self.cfg.save()
            log.info(f"QTE calibrated lo={lo} hi={hi} min={min_px}")
        if not self.wm.find():
            messagebox.showerror("Hold on!", "You need to open Roblox first before we can do this.")
            return
        ColorSamplerDialog(self.root, self.wm, self.cfg,
                           "Sample QTE Indicator Color", confirm, mode="qte")

    def _draw_scan_region(self):
        if not self.wm.find():
            messagebox.showerror("Hold on!", "You need to open Roblox first before we can do this.")
            return
        def on_save():
            self.cfg.save()
            self._append_log_safe(
                f"Scan region saved x={self.cfg.scan_x1_pct:.3f}-{self.cfg.scan_x2_pct:.3f} "
                f"y={self.cfg.scan_y1_pct:.3f}-{self.cfg.scan_y2_pct:.3f}")
        RegionDrawer(self.root, self.wm, self.cfg, on_save, mode="scan")

    def _draw_qte_region(self):
        if not self.wm.find():
            messagebox.showerror("Hold on!", "You need to open Roblox first before we can do this.")
            return
        def on_save():
            self.cfg.save()
            self._append_log_safe(
                f"QTE region saved x={self.cfg.qte_scan_x1_pct:.3f}-{self.cfg.qte_scan_x2_pct:.3f} "
                f"y={self.cfg.qte_scan_y1_pct:.3f}-{self.cfg.qte_scan_y2_pct:.3f}")
        RegionDrawer(self.root, self.wm, self.cfg, on_save, mode="qte")

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

    def _on_bait_change(self):
        self.cfg.save()
        self._append_log_safe(
            f"Bait saved  enabled={self.cfg.use_bait}  "
            f"active_keys={self.cfg.active_bait_keys()}")
        if hasattr(self, "_bait_panel"):
            self._bait_panel._update_seq_preview()

    def _set_hk(self, attr: str, val: str):
        setattr(self.cfg, attr, val)
        self._reg_hotkeys()
        self.cfg.save()

    def _reg_hotkeys(self):
        for hk in list(self._reg_hks):
            try:
                keyboard.remove_hotkey(hk)
            except Exception:
                pass
        self._reg_hks.clear()

        def _r(combo, fn):
            if not combo:
                return
            try:
                keyboard.add_hotkey(combo, fn, suppress=True)
                self._reg_hks.append(combo)
            except Exception as e:
                log.warning(f"Hotkey {combo!r}: {e}")

        _r(self.cfg.hotkey_start_stop, lambda: self.root.after(0, self._toggle))
        _r(self.cfg.hotkey_exit,       lambda: self.root.after(0, self._on_close))
        _r(self.cfg.hotkey_vision,     lambda: self.root.after(0, self._toggle_vision))

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
                messagebox.showerror("Bad value", f"Invalid: {attr} = {raw!r}")
                return
        self.cfg.save()
        if hasattr(self, "_bait_panel"):
            self._bait_panel._update_seq_preview()
        self._append_log_safe("Settings saved.")

    def _toggle(self):
        with self._toggle_lock:
            if self._stopping:
                return
            if self.active:
                self._begin_stop()
            else:
                self._start()

    def _start(self):
        if not self.wm.find():
            messagebox.showerror("Game Not Found", f"I couldn't spot {self.cfg.target_exe}. Please open the game first!")
            return

        if self.cfg.use_bait:
            active = self.cfg.active_bait_slots()
            if not active:
                messagebox.showerror("Bait error",
                                     "Bait switching is enabled but no slots are enabled.\n"
                                     "Go to the Bait tab and enable at least one slot,\n"
                                     "or disable bait switching in Features.")
                return
            for slot in active:
                k = slot.get("key", "").strip()
                if not k:
                    messagebox.showerror("Bait error",
                                         f"Slot \"{slot.get('label', '?')}\" has an empty key.\n"
                                         "Set the Roblox hotbar key for every enabled slot.")
                    return

        issues = []
        if self.cfg.use_bobber_detection and not self.cfg.bobber_calibrated:
            issues.append("• Bobber color not sampled (or disable Bobber detection)")
        if self.cfg.use_splash_detection and not self.cfg.splash_calibrated:
            issues.append("• Splash/bite color not sampled (or disable Splash detection)")
        if not self.cfg.scan_region_set:
            issues.append("• Scan region not drawn")
        if issues:
            if not messagebox.askyesno("Setup incomplete",
                                       "\n".join(issues) + "\n\nContinue anyway?"):
                return

        self.stats = Stats()
        self.fish  = FishBot(self.cfg, self.wm, self.inp, self.stats)
        self.fish.on_state_change   = self._on_state
        self.fish.on_log            = lambda m: self._append_log_safe(m)
        self.fish.on_px_update      = self._on_px_update
        self.fish.on_frame          = self._on_frame
        self.fish.on_stopped        = lambda: self.root.after(0, self._on_fish_stopped)
        self.fish.on_bait_activated = lambda k, l: self.root.after(
            0, self._on_bait_activated, k, l)
        self.active = True
        self._ensure_viewer()
        self.fish.start()
        self._start_btn.config(text="■  STOP", bg=RED)
        self._status_lbl.config(text="RUNNING")
        self._dot.config(fg=GREEN)

    def _begin_stop(self):
        if not self.fish:
            return
        self._stopping = True
        self._start_btn.config(text="stopping…", bg=MUTED, state="disabled")
        self.fish.stop()
        t = threading.Thread(target=self.fish.join, daemon=True, name="FishBot.join")
        t.start()

    def _on_fish_stopped(self):
        self.active    = False
        self._stopping = False
        self._start_btn.config(text="▶  START", bg=GREEN, state="normal")
        self._status_lbl.config(text="STOPPED")
        self._dot.config(fg=MUTED)
        self._state_lbl.config(text="IDLE", fg=MUTED)
        if self.stats:
            log.info(f"Stopped | catches={self.stats.catches} casts={self.stats.casts} "
                     f"CPH={self.stats.cph():.1f}")

    def _on_state(self, state: FishState):
        try:
            self.root.after(0, self._state_lbl.config,
                            {"text": state.name, "fg": STATE_COLORS.get(state, MUTED)})
        except Exception:
            pass
        if self.viewer:
            self.viewer.set_state(state)

    def _on_px_update(self, bob_px: int, splash_px: int):
        try:
            self.root.after(0, self._refresh_px, bob_px, splash_px)
        except Exception:
            pass
        if self.viewer:
            self.viewer.set_pixels(bob_px, splash_px, self.cfg.splash_min_pixels)

    def _refresh_px(self, bob_px: int, splash_px: int):
        try:
            bite = splash_px >= self.cfg.splash_min_pixels
            self._px_lbl.config(
                text=f"bob={bob_px}  splash={splash_px}{'  BITE!' if bite else ''}",
                fg=RED if bite else GREEN)
        except Exception:
            pass

    def _on_frame(self, overlay: np.ndarray):
        if self.cfg.use_vision and self.viewer:
            self.viewer.push_frame(overlay)

    def _on_bait_activated(self, key: str, label: str):
        try:
            if hasattr(self, "_bait_panel"):
                self._bait_panel.notify_activated(key, label)
        except Exception:
            pass

    def _update_cal(self):
        try:
            labels = {"bobber_calibrated": "Bobber color",
                      "splash_calibrated": "Splash / Bite",
                      "qte_calibrated":    "QTE Indicator"}
            for attr, name in labels.items():
                lbl = self._cal_lbls.get(attr)
                if lbl:
                    ok = getattr(self.cfg, attr)
                    lbl.config(text=f"{name}: {'✓' if ok else '✗'}",
                               fg=GREEN if ok else RED)
            if self.cfg.scan_region_set:
                self._region_lbl.config(
                    text=(f"Scan region: set  "
                          f"x={self.cfg.scan_x1_pct:.2f}-{self.cfg.scan_x2_pct:.2f} "
                          f"y={self.cfg.scan_y1_pct:.2f}-{self.cfg.scan_y2_pct:.2f}"),
                    fg=GREEN)
            else:
                self._region_lbl.config(text="Scan region: not set", fg=RED)
            if self.cfg.qte_region_set:
                self._qte_region_lbl.config(
                    text=(f"QTE region: set  "
                          f"x={self.cfg.qte_scan_x1_pct:.2f}-{self.cfg.qte_scan_x2_pct:.2f} "
                          f"y={self.cfg.qte_scan_y1_pct:.2f}-{self.cfg.qte_scan_y2_pct:.2f}"),
                    fg=CYAN)
            else:
                self._qte_region_lbl.config(
                    text="QTE region: not set (uses scan region)", fg=MUTED)
        except Exception:
            pass

    def _ui_tick(self):
        try:
            if self.active and self.stats:
                s = self.stats
                self._sv["Catches"].set(str(s.catches))
                self._sv["Casts"].set(str(s.casts))
                self._sv["Timeouts"].set(str(s.timeouts))
                self._sv["QTE"].set(str(s.qte_presses))
                self._sv["Bait Used"].set(str(s.bait_uses))
                self._sv["CPH"].set(f"{s.cph():.1f}")
                self._sv["Runtime"].set(s.elapsed_str())
            self._update_cal()
        except Exception:
            pass
        self.root.after(500, self._ui_tick)

    def _on_close(self):
        with self._toggle_lock:
            if self.fish and self.active:
                self.fish.stop()
                self.fish.join(timeout=3.0)
        self.cfg.save()
        for hk in list(self._reg_hks):
            try:
                keyboard.remove_hotkey(hk)
            except Exception:
                pass
        if self._log_handler:
            log.removeHandler(self._log_handler)
        try:
            if self.viewer and self.viewer.winfo_exists():
                self.viewer.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = FishBotUI()
    app.run()
