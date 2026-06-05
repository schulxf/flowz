#!/usr/bin/env python3
"""Flowz settings window.

A premium, frameless tkinter UI for Flowz settings: dark sidebar with live
status, pill tabs, custom toggles, segmented controls, and dual dark/light
themes. Standard library only.

The engine module (freeflow_win) is injected to avoid circular imports:

    import flowz_ui
    flowz_ui.show_settings_window(config, engine)
"""

from __future__ import annotations

import ctypes
import math
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog


# ---------------------------------------------------------------------------
# Design tokens (Flowz Brand System v1.0)
# ---------------------------------------------------------------------------

BLUE = "#1E9BEF"
CYAN = "#5CCBFF"
ICE = "#B9ECFF"
DEEP = "#0871C7"
OK = "#2BD4A0"
WARN = "#F5B23A"
BAD = "#FF6473"

THEMES = {
    "dark": {
        "win": "#0F1521",
        "win2": "#0C111B",
        "sidebar": "#0B0F18",
        "panel": "#121A28",
        "panel2": "#0F1623",
        "field": "#0C1320",
        "field_focus": "#0E1726",
        "line": "#222A37",       # white 7% over panel
        "line2": "#2E3542",      # white 12%
        "line3": "#3D434F",      # white 18%
        "text": "#E8EEF6",
        "muted": "#94A2B6",
        "faint": "#5C687B",
        "tab_active": "#1A2433",
        "titlebar_hover": "#1A2230",
    },
    "light": {
        "win": "#FFFFFF",
        "win2": "#F7FAFD",
        "sidebar": "#0C1422",
        "panel": "#FFFFFF",
        "panel2": "#F4F7FB",
        "field": "#FFFFFF",
        "field_focus": "#FFFFFF",
        "line": "#E5EBF3",
        "line2": "#D7E0EC",
        "line3": "#C3D0E0",
        "text": "#0D1726",
        "muted": "#5C6B80",
        "faint": "#8A98AC",
        "tab_active": "#FFFFFF",
        "titlebar_hover": "#EDF2F8",
    },
}

# The sidebar keeps the dark ink palette in both themes.
SIDEBAR = {
    "card": "#151A23",
    "card_line": "#1C212B",
    "stat_line": "#171C25",
    "text": "#E8EEF6",
    "tag": "#7C8AA0",
    "sub": "#8A97AC",
    "stat_k": "#6B788D",
    "stat_v": "#DCE4EF",
    "path": "#79879C",
}

MARK_STOPS = [(0.0, (0xB9, 0xEC, 0xFF)), (0.45, (0x5C, 0xCB, 0xFF)), (1.0, (0x1E, 0x9B, 0xEF))]
EQ_BARS = [10, 7, 14, 5, 11, 8, 13, 6, 9, 12, 7, 10, 5, 8]

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % rgb


def _mix(c1: str, c2: str, t: float) -> str:
    a = tuple(int(c1[i : i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i : i + 2], 16) for i in (1, 3, 5))
    return _hex(tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3)))


def _grad(stops, t: float) -> str:
    t = max(0.0, min(1.0, t))
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            span = (t1 - t0) or 1.0
            f = (t - t0) / span
            return _hex(tuple(round(c0[i] + (c1[i] - c0[i]) * f) for i in range(3)))
    return _hex(stops[-1][1])


def _cubic(p0, p1, p2, p3, steps: int):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        pts.append((
            u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
        ))
    return pts


def ribbon_path(steps: int = 48):
    """Brand mark path in a 0..100 viewBox (M20 52 C 30 26,42 26,50 50 S 70 74,80 48)."""
    a = _cubic((20, 52), (30, 26), (42, 26), (50, 50), steps)
    b = _cubic((50, 50), (58, 74), (70, 74), (80, 48), steps)
    return a + b[1:]


def draw_mark(canvas: tk.Canvas, x: float, y: float, size: float, width_frac: float = 0.10) -> None:
    """Draw the gradient voice ribbon at (x, y) top-left, given box size."""
    pts = ribbon_path()
    n = len(pts)
    w = max(1, round(size * width_frac))
    for i in range(n - 1):
        color = _grad(MARK_STOPS, i / (n - 1))
        x0, y0 = x + pts[i][0] / 100 * size, y + pts[i][1] / 100 * size
        x1, y1 = x + pts[i + 1][0] / 100 * size, y + pts[i + 1][1] / 100 * size
        canvas.create_line(x0, y0, x1, y1, fill=color, width=w, capstyle="round")


def draw_app_icon(canvas: tk.Canvas, x: float, y: float, size: float) -> None:
    """Squircle app icon with the ribbon (flat-color approximation of the gradient bg)."""
    pad = size * 0.04
    rrect(canvas, x + pad, y + pad, x + size - pad, y + size - pad, size * 0.27,
          fill="#0E3461", outline="#27405F", width=1)
    draw_mark(canvas, x, y, size, width_frac=0.09)


def rrect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """Rounded rectangle as a smoothed polygon."""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


# ---------------------------------------------------------------------------
# Stroke icons (24x24 design grid, drawn with canvas primitives)
# ---------------------------------------------------------------------------

def draw_icon(canvas: tk.Canvas, name: str, cx: float, cy: float, size: float, color: str, lw: int | None = None):
    s = size / 24.0
    w = lw or max(1, round(size * 0.085))

    def L(*coords, **kw):
        pts = [cx + (px - 12) * s for px in coords[0::2]]
        pts2 = [cy + (py - 12) * s for py in coords[1::2]]
        flat = [v for pair in zip(pts, pts2) for v in pair]
        canvas.create_line(*flat, fill=color, width=w, capstyle="round", joinstyle="round", **kw)

    def R(x1, y1, x2, y2, r=2.0):
        rrect(canvas, cx + (x1 - 12) * s, cy + (y1 - 12) * s, cx + (x2 - 12) * s, cy + (y2 - 12) * s,
              r * s, fill="", outline=color, width=w)

    def ARC(x1, y1, x2, y2, start, extent):
        canvas.create_arc(cx + (x1 - 12) * s, cy + (y1 - 12) * s, cx + (x2 - 12) * s, cy + (y2 - 12) * s,
                          start=start, extent=extent, style="arc", outline=color, width=w)

    if name == "provider":
        L(3, 7, 21, 7)
        L(3, 12, 21, 12)
        L(3, 17, 13, 17)
    elif name == "capture":
        R(9, 3, 15, 14, 3)
        ARC(5, 4, 19, 18, 180, 180)
        L(12, 18, 12, 21)
    elif name == "cue":
        L(11, 5, 6, 9, 3, 9, 3, 15, 6, 15, 11, 19, 11, 5)
        ARC(12, 9, 20, 15, -60, 120)
        ARC(13, 6, 25, 18, -60, 120)
    elif name == "output":
        L(4, 17, 4, 7, 6, 5, 15, 5, 20, 10, 20, 17, 18, 19, 6, 19, 4, 17)
        L(8, 13, 16, 13)
        L(8, 16, 13, 16)
    elif name == "app":
        R(3, 3, 10, 10, 1.5)
        R(14, 3, 21, 10, 1.5)
        R(3, 14, 10, 21, 1.5)
        R(14, 14, 21, 21, 1.5)
    elif name == "eye":
        ARC(2, 5, 22, 19, 0, 360)
        canvas.create_oval(cx - 3 * s, cy - 3 * s, cx + 3 * s, cy + 3 * s, outline=color, width=w)
    elif name == "eye_off":
        ARC(2, 5, 22, 19, 0, 360)
        canvas.create_oval(cx - 3 * s, cy - 3 * s, cx + 3 * s, cy + 3 * s, outline=color, width=w)
        L(4, 4, 20, 20)
    elif name == "folder":
        L(3, 18, 3, 7, 5, 5, 9, 5, 11, 7, 19, 7, 21, 9, 21, 18, 19, 19, 5, 19, 3, 18)
    elif name == "caret":
        L(7, 10, 12, 15, 17, 10)
    elif name == "play":
        L(9, 6, 9, 18, 18, 12, 9, 6)
    elif name == "zap":
        L(13, 3, 5, 14, 11, 14, 10, 21, 19, 10, 13, 10, 13, 3)
    elif name == "sun":
        canvas.create_oval(cx - 4 * s, cy - 4 * s, cx + 4 * s, cy + 4 * s, outline=color, width=w)
        for ang in range(0, 360, 45):
            rad = math.radians(ang)
            L(12 + 6.2 * math.cos(rad), 12 + 6.2 * math.sin(rad),
              12 + 8.5 * math.cos(rad), 12 + 8.5 * math.sin(rad))
    elif name == "moon":
        ARC(3, 3, 21, 21, 50, 250)
        ARC(1, 0, 15, 14, -60, 130)
    elif name == "min":
        L(5, 12, 19, 12)
    elif name == "max":
        R(5, 5, 19, 19, 2.5)
    elif name == "close":
        L(6, 6, 18, 18)
        L(18, 6, 6, 18)
    elif name == "check":
        L(5, 12.5, 10, 17.5, 19, 7)


# ---------------------------------------------------------------------------
# Settings window
# ---------------------------------------------------------------------------

class SettingsWindow:
    WIN_W = 1100
    WIN_H = 704
    SIDEBAR_W = 248

    TABS = [
        ("provider", "Provider"),
        ("capture", "Capture"),
        ("cue", "Ready Cue"),
        ("output", "Output"),
        ("app", "App"),
    ]

    STRING_KEYS = {
        "api_key", "base_url", "transcription_model", "language", "http_transport",
        "curl_path", "ffmpeg_path", "ffmpeg_device", "audio_ready_sound_file",
        "audio_ready_sound_backend", "audio_ready_sound_alias", "post_process_model",
    }
    BOOL_KEYS = {
        "low_latency_capture", "ffmpeg_prime_on_startup", "audio_ready_sound",
        "trim_silence", "post_process", "paste_result", "append_space_after_sentence",
        "preserve_text_clipboard", "visual_indicator", "tray_icon", "log_timing_metrics",
    }
    INT_KEYS = {
        "request_timeout_seconds", "low_latency_idle_timeout_seconds",
        "low_latency_preroll_ms", "low_latency_ring_seconds", "low_latency_ready_timeout_ms",
        "ffmpeg_startup_probe_ms", "ffmpeg_prime_duration_ms",
        "audio_ready_sound_frequency_hz", "audio_ready_sound_duration_ms",
        "silence_threshold", "silence_padding_ms", "silence_min_audio_ms",
    }
    FLOAT_KEYS = {"visual_indicator_success_seconds"}

    def __init__(self, config, engine):
        self.config = config
        self.engine = engine
        self.theme_name = getattr(config, "ui_theme", "dark") or "dark"
        if self.theme_name not in THEMES:
            self.theme_name = "dark"
        self.tab = "provider"
        self.entries: dict[str, tk.Entry] = {}
        self.values: dict[str, object] = {}
        self._anim_items: list = []
        self._status_after = None
        self._tick = 0
        self._minimizing = False
        self._mapped_once = False

        self._load_values()
        self._build_root()
        self.rebuild()
        self._animate()

    # -- state ------------------------------------------------------------

    def _load_values(self) -> None:
        cfg = self.config
        for key in self.STRING_KEYS | self.INT_KEYS | self.FLOAT_KEYS:
            self.values[key] = str(getattr(cfg, key))
        for key in self.BOOL_KEYS:
            self.values[key] = self.engine.bool_setting(getattr(cfg, key))
        try:
            self.values["__startup__"] = self.engine.is_startup_enabled()
        except Exception:
            self.values["__startup__"] = False

    def _sync_entries(self) -> None:
        for key, entry in list(self.entries.items()):
            try:
                self.values[key] = entry.get()
            except tk.TclError:
                pass

    def apply_form(self) -> None:
        self._sync_entries()
        cfg, eng = self.config, self.engine
        defaults = eng.AppConfig()
        for key in self.STRING_KEYS:
            setattr(cfg, key, str(self.values[key]).strip())
        for key in self.BOOL_KEYS:
            setattr(cfg, key, bool(self.values[key]))
        for key in self.INT_KEYS:
            setattr(cfg, key, eng.int_setting(self.values[key], int(getattr(defaults, key)), 0, 100000))
        for key in self.FLOAT_KEYS:
            try:
                value = float(str(self.values[key]).strip())
            except (TypeError, ValueError):
                value = float(getattr(defaults, key))
            setattr(cfg, key, max(0.1, min(value, 20.0)))
        cfg.audio_quality_defaults_version = defaults.audio_quality_defaults_version
        cfg.ui_theme = self.theme_name
        self._refresh_stats()

    # -- root / chrome ------------------------------------------------------

    def _build_root(self) -> None:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("Flowz Settings")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        dpi = self.root.winfo_fpixels("1i")
        self.scale = max(1.0, dpi / 96.0)
        s = self.px

        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w = min(s(self.WIN_W), int(sw * 0.96))
        h = min(s(self.WIN_H), int(sh * 0.94))
        x, y = (sw - w) // 2, max(0, (sh - h) // 2 - s(10))
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.win_w, self.win_h = w, h
        self._normal_geometry = f"{w}x{h}+{x}+{y}"
        self._maximized = False

        self._init_fonts()
        self._set_window_icon()
        self.root.after(10, self._apply_native_styles)
        self.root.after(1400, self._release_startup_topmost)
        self.root.bind("<Map>", self._on_map)
        self.root.deiconify()

    def _release_startup_topmost(self) -> None:
        try:
            self.root.attributes("-topmost", False)
        except Exception:
            pass

    def px(self, v: float) -> int:
        return round(v * self.scale)

    def _init_fonts(self) -> None:
        families = set(tkfont.families(self.root))

        def pick(*names: str) -> str:
            for name in names:
                if name in families:
                    return name
            return "Segoe UI"

        self.f_display = pick("Sora", "Segoe UI Variable Display", "Segoe UI")
        self.f_ui = pick("Manrope", "Segoe UI Variable Text", "Segoe UI")

    def font(self, size: float, weight: str = "normal", display: bool = False) -> tuple:
        return (self.f_display if display else self.f_ui, -self.px(size), weight)

    def _set_window_icon(self) -> None:
        base = getattr(sys, "_MEIPASS", None)
        candidates = []
        if base:
            candidates.append(Path(base) / "assets" / "flowz.ico")
        candidates.append(Path(__file__).resolve().parent / "assets" / "flowz.ico")
        for path in candidates:
            if path.exists():
                try:
                    self.root.iconbitmap(default=str(path))
                except Exception:
                    pass
                return

    def _hwnd(self) -> int:
        return ctypes.windll.user32.GetParent(self.root.winfo_id())

    def _apply_native_styles(self) -> None:
        try:
            hwnd = self._hwnd()
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) if hasattr(user32, "GetWindowLongPtrW") else user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            if hasattr(user32, "SetWindowLongPtrW"):
                user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
            else:
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            pref = ctypes.c_int(DWMWCP_ROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref), ctypes.sizeof(pref)
            )
        except Exception:
            pass

    def _on_map(self, _event=None) -> None:
        if self._minimizing:
            self._minimizing = False
            self.root.overrideredirect(True)
            self.root.after(10, self._apply_native_styles)
        self._mapped_once = True

    def _minimize(self) -> None:
        self._minimizing = True
        self.root.overrideredirect(False)
        self.root.iconify()

    def _toggle_maximize(self) -> None:
        if self._maximized:
            self.root.geometry(self._normal_geometry)
            self._maximized = False
        else:
            self._normal_geometry = self.root.winfo_geometry()
            rect = ctypes.wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                self.root.geometry(
                    f"{rect.right - rect.left}x{rect.bottom - rect.top}+{rect.left}+{rect.top}"
                )
                self._maximized = True

    # -- theme / rebuild ----------------------------------------------------

    @property
    def t(self) -> dict:
        return THEMES[self.theme_name]

    def toggle_theme(self) -> None:
        self._sync_entries()
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        try:
            self.config.ui_theme = self.theme_name
            self.config.save()
        except Exception:
            pass
        self.rebuild()

    def rebuild(self) -> None:
        self._anim_items.clear()
        self.entries.clear()
        for child in self.root.winfo_children():
            child.destroy()
        t = self.t
        s = self.px
        self.root.configure(bg=t["win"])

        self._build_titlebar()

        body = tk.Frame(self.root, bg=t["win"])
        body.pack(fill="both", expand=True)
        self._build_sidebar(body)

        content = tk.Frame(body, bg=t["win"])
        content.pack(side="left", fill="both", expand=True)

        head = tk.Frame(content, bg=t["win"])
        head.pack(fill="x", padx=s(30), pady=(s(20), 0))
        tk.Label(head, text="Flowz Settings", font=self.font(21, "bold", display=True),
                 bg=t["win"], fg=t["text"]).pack(anchor="w")
        tk.Label(head, text="Voice capture, ready cue, transcription, and startup behavior.",
                 font=self.font(13), bg=t["win"], fg=t["muted"]).pack(anchor="w", pady=(s(4), 0))
        self._build_tabs(head)

        self._panel_host = tk.Frame(content, bg=t["win"])
        self._panel_host.pack(fill="both", expand=True)
        self._build_panel()

        self._build_footer(content)

    # -- titlebar -----------------------------------------------------------

    def _build_titlebar(self) -> None:
        t = self.t
        s = self.px
        bar = tk.Frame(self.root, bg=t["win"], height=s(46))
        bar.pack(fill="x")
        bar.pack_propagate(False)
        sep = tk.Frame(self.root, bg=t["line"], height=1)
        sep.pack(fill="x")

        left = tk.Frame(bar, bg=t["win"])
        left.pack(side="left", padx=(s(16), 0))
        mark = tk.Canvas(left, width=s(20), height=s(20), bg=t["win"], highlightthickness=0)
        mark.pack(side="left")
        draw_mark(mark, 0, 0, s(20), width_frac=0.12)
        title = tk.Label(left, text="Flowz", font=self.font(13.5, "bold", display=True),
                         bg=t["win"], fg=t["text"])
        title.pack(side="left", padx=(s(10), 0))
        sub = tk.Label(left, text="Settings", font=self.font(13), bg=t["win"], fg=t["faint"])
        sub.pack(side="left", padx=(s(7), 0))

        for widget in (bar, left, title, sub):
            widget.bind("<ButtonPress-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
        bar.bind("<Double-Button-1>", lambda e: self._toggle_maximize())

        right = tk.Frame(bar, bg=t["win"])
        right.pack(side="right", padx=(0, s(10)))

        self._make_theme_toggle(right)
        for name, cmd, danger in (("min", self._minimize, False),
                                  ("max", self._toggle_maximize, False),
                                  ("close", self.root.destroy, True)):
            self._make_window_button(right, name, cmd, danger)

    def _make_theme_toggle(self, parent: tk.Frame) -> None:
        t = self.t
        s = self.px
        label = "Light" if self.theme_name == "dark" else "Dark"
        icon = "sun" if self.theme_name == "dark" else "moon"
        w, h = s(74), s(30)
        c = tk.Canvas(parent, width=w, height=h, bg=t["win"], highlightthickness=0, cursor="hand2")
        c.pack(side="left", padx=(0, s(10)))

        def paint(hover: bool) -> None:
            c.delete("all")
            rrect(c, 1, 1, w - 1, h - 1, s(8), fill=t["win"],
                  outline=t["line2"] if hover else t["line"], width=1)
            draw_icon(c, icon, s(15), h / 2, s(15), t["text"] if hover else t["muted"])
            c.create_text(s(26), h / 2, text=label, anchor="w", font=self.font(12, "bold"),
                          fill=t["text"] if hover else t["muted"])

        paint(False)
        c.bind("<Enter>", lambda e: paint(True))
        c.bind("<Leave>", lambda e: paint(False))
        c.bind("<Button-1>", lambda e: self.toggle_theme())

    def _make_window_button(self, parent: tk.Frame, name: str, cmd, danger: bool) -> None:
        t = self.t
        s = self.px
        w, h = s(34), s(30)
        c = tk.Canvas(parent, width=w, height=h, bg=t["win"], highlightthickness=0, cursor="hand2")
        c.pack(side="left", padx=(s(2), 0))

        def paint(hover: bool) -> None:
            c.delete("all")
            if hover:
                rrect(c, 0, 0, w, h, s(8), fill="#E33B4E" if danger else t["titlebar_hover"], width=0)
            color = "#FFFFFF" if (hover and danger) else (t["text"] if hover else t["muted"])
            draw_icon(c, name, w / 2, h / 2, s(11.5), color, lw=max(1, s(1.4)))

        paint(False)
        c.bind("<Enter>", lambda e: paint(True))
        c.bind("<Leave>", lambda e: paint(False))
        c.bind("<Button-1>", lambda e: cmd())

    def _drag_start(self, event) -> None:
        self._drag_off = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag_move(self, event) -> None:
        x = event.x_root - self._drag_off[0]
        y = event.y_root - self._drag_off[1]
        self.root.geometry(f"+{x}+{y}")

    # -- sidebar ------------------------------------------------------------

    def _build_sidebar(self, body: tk.Frame) -> None:
        t = self.t
        s = self.px
        sb = tk.Frame(body, bg=t["sidebar"], width=s(self.SIDEBAR_W))
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        pad = s(20)
        brand = tk.Frame(sb, bg=t["sidebar"])
        brand.pack(anchor="w", padx=pad, pady=(s(22), 0))
        icon = tk.Canvas(brand, width=s(34), height=s(34), bg=t["sidebar"], highlightthickness=0)
        icon.pack(side="left")
        draw_app_icon(icon, 0, 0, s(34))
        wm = tk.Canvas(brand, width=s(86), height=s(34), bg=t["sidebar"], highlightthickness=0)
        wm.pack(side="left", padx=(s(10), 0))
        self._draw_wordmark(wm, 0, s(17), 24)

        tk.Label(sb, text="Fast dictation - settings", font=self.font(11.5),
                 bg=t["sidebar"], fg=SIDEBAR["tag"]).pack(anchor="w", padx=pad, pady=(s(7), 0))

        # Status card with pulsing dot + animated equalizer
        card_w = s(self.SIDEBAR_W) - 2 * pad
        card_h = s(104)
        card = tk.Canvas(sb, width=card_w, height=card_h, bg=t["sidebar"], highlightthickness=0)
        card.pack(padx=pad, pady=(s(20), 0))
        rrect(card, 1, 1, card_w - 1, card_h - 1, s(13), fill=SIDEBAR["card"],
              outline=SIDEBAR["card_line"], width=1)
        self._status_dot = card.create_oval(s(15), s(16), s(15) + s(8), s(16) + s(8), fill=OK, outline=OK)
        self._status_ring = card.create_oval(0, 0, 0, 0, outline=SIDEBAR["card"], width=1)
        self._status_title = card.create_text(s(32), s(20), text="Ready cue sent", anchor="w",
                                              font=self.font(13, "bold"), fill=SIDEBAR["text"])
        self._eq_canvas = card
        self._eq_bars = []
        bar_y = s(58)
        for i in range(len(EQ_BARS)):
            x = s(16) + i * s(6.4)
            color = _mix(CYAN, BLUE, i / (len(EQ_BARS) - 1))
            self._eq_bars.append(card.create_line(x, bar_y, x, bar_y - s(8), fill=color,
                                                  width=s(3), capstyle="round"))
        card.create_text(s(15), s(76), anchor="nw", text="Hold Ctrl + Win, wait for the cue,",
                         font=self.font(11.5), fill=SIDEBAR["sub"])
        card.create_text(s(15), s(90), anchor="nw", text="then speak.",
                         font=self.font(11.5), fill=SIDEBAR["sub"])

        # Stats
        stats = tk.Frame(sb, bg=t["sidebar"])
        stats.pack(fill="x", padx=pad, pady=(s(18), 0))
        self._stat_labels = {}
        for key, label in (("mic", "Microphone"), ("capture", "Capture"),
                           ("model", "Model"), ("cue", "Cue")):
            tk.Frame(stats, bg=SIDEBAR["stat_line"], height=1).pack(fill="x")
            tk.Label(stats, text=label.upper(), font=self.font(10, "bold"),
                     bg=t["sidebar"], fg=SIDEBAR["stat_k"]).pack(anchor="w", pady=(s(10), 0))
            value = tk.Label(stats, text="", font=self.font(12.5, "bold"), bg=t["sidebar"],
                             fg=SIDEBAR["stat_v"], wraplength=card_w - s(4), justify="left")
            value.pack(anchor="w", pady=(s(2), s(9)))
            self._stat_labels[key] = value
        self._refresh_stats()

    def _draw_wordmark(self, canvas: tk.Canvas, x: float, cy: float, size: float) -> None:
        font = (self.f_display, -self.px(size), "bold")
        measurer = tkfont.Font(family=self.f_display, size=-self.px(size), weight="bold")
        word = "flowz"
        total = measurer.measure(word)
        run = 0
        for i, ch in enumerate(word):
            color = _grad(MARK_STOPS, run / max(1, total))
            canvas.create_text(x + run, cy, text=ch, anchor="w", font=font, fill=color)
            run += measurer.measure(ch)

    def _refresh_stats(self) -> None:
        if not hasattr(self, "_stat_labels"):
            return
        device = str(self.values.get("ffmpeg_device", "")).strip() or "Auto microphone"
        preroll = self.engine.int_setting(self.values.get("low_latency_preroll_ms", 800), 800, 0, 5000)
        model = str(self.values.get("transcription_model", "")).strip() or "whisper-large-v3"
        cue = "Ready cue on" if self.values.get("audio_ready_sound") else "Cue muted"
        for key, text in (("mic", device), ("capture", f"{preroll} ms pre-roll - warm"),
                          ("model", model), ("cue", cue)):
            try:
                self._stat_labels[key].configure(text=text)
            except tk.TclError:
                pass

    # -- tabs -----------------------------------------------------------------

    def _build_tabs(self, parent: tk.Frame) -> None:
        t = self.t
        s = self.px
        holder = tk.Frame(parent, bg=t["win"])
        holder.pack(anchor="w", pady=(s(17), 0))

        font = tkfont.Font(family=self.f_ui, size=-self.px(13), weight="bold")
        pads, gap, ih = s(16), s(4), s(34)
        widths = [font.measure(label) + s(22) + 2 * pads for _, label in self.TABS]
        total_w = sum(widths) + gap * (len(self.TABS) + 1) + 2
        total_h = ih + 2 * gap + 2

        c = tk.Canvas(holder, width=total_w, height=total_h, bg=t["win"], highlightthickness=0)
        c.pack()
        self._tabs_canvas = c
        self._tab_zones: list[tuple[float, float, str]] = []

        def paint(hover_id: str | None = None) -> None:
            c.delete("all")
            self._tab_zones.clear()
            rrect(c, 1, 1, total_w - 1, total_h - 1, s(12), fill=t["panel2"], outline=t["line"], width=1)
            x = gap + 1
            for (tab_id, label), tw in zip(self.TABS, widths):
                active = tab_id == self.tab
                if active:
                    rrect(c, x, gap + 1, x + tw, gap + 1 + ih, s(9), fill=t["tab_active"],
                          outline=t["line"] if self.theme_name == "dark" else t["line2"], width=1)
                color = t["text"] if (active or hover_id == tab_id) else t["muted"]
                draw_icon(c, tab_id, x + pads + s(7), gap + 1 + ih / 2, s(15), color)
                c.create_text(x + pads + s(20), gap + 1 + ih / 2, text=label, anchor="w",
                              font=font, fill=color)
                self._tab_zones.append((x, x + tw, tab_id))
                x += tw + gap

        def tab_at(event) -> str | None:
            for x0, x1, tab_id in self._tab_zones:
                if x0 <= event.x <= x1:
                    return tab_id
            return None

        def on_click(event) -> None:
            tab_id = tab_at(event)
            if tab_id and tab_id != self.tab:
                self._sync_entries()
                self.tab = tab_id
                paint()
                self._build_panel()

        c.bind("<Button-1>", on_click)
        c.bind("<Motion>", lambda e: paint(tab_at(e)))
        c.bind("<Leave>", lambda e: paint())
        c.configure(cursor="hand2")
        paint()

    # -- scrollable panel ------------------------------------------------------

    def _build_panel(self) -> None:
        t = self.t
        s = self.px
        for child in self._panel_host.winfo_children():
            child.destroy()

        canvas = tk.Canvas(self._panel_host, bg=t["win"], highlightthickness=0)
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=t["win"])
        window = canvas.create_window(0, 0, window=inner, anchor="nw")

        sbar = tk.Canvas(self._panel_host, width=s(9), bg=t["win"], highlightthickness=0)
        sbar.pack(side="right", fill="y")

        def update_scrollbar(*_):
            sbar.delete("all")
            top, bottom = canvas.yview()
            if bottom - top >= 1.0:
                return
            h = sbar.winfo_height()
            y0, y1 = top * h, bottom * h
            rrect(sbar, s(2), y0 + 2, s(7), max(y0 + s(24), y1) - 2, s(3), fill=t["line2"], width=0)

        def on_configure(_=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window, width=canvas.winfo_width())
            update_scrollbar()

        inner.bind("<Configure>", on_configure)
        canvas.bind("<Configure>", on_configure)
        canvas.configure(yscrollcommand=lambda *a: update_scrollbar())

        def on_wheel(event):
            if canvas.winfo_exists():
                canvas.yview_scroll(-int(event.delta / 80), "units")
                update_scrollbar()

        for widget in (canvas, inner):
            widget.bind("<MouseWheel>", on_wheel)
        self._panel_wheel = on_wheel

        grid = tk.Frame(inner, bg=t["win"])
        grid.pack(fill="x", padx=(s(30), s(22)), pady=(s(22), s(22)))
        grid.columnconfigure(0, weight=1, uniform="col")
        grid.columnconfigure(1, weight=1, uniform="col")
        self._grid = grid
        self._grid_row = 0
        self._grid_col = 0

        builder = {
            "provider": self._tab_provider,
            "capture": self._tab_capture,
            "cue": self._tab_cue,
            "output": self._tab_output,
            "app": self._tab_app,
        }[self.tab]
        builder()

    def _slot(self, span: bool = False) -> tuple[tk.Frame, int, int]:
        if span and self._grid_col == 1:
            self._grid_row += 1
            self._grid_col = 0
        row, col = self._grid_row, self._grid_col
        if span:
            self._grid_row += 1
        else:
            if col == 1:
                self._grid_row += 1
            self._grid_col = (col + 1) % 2
        return self._grid, row, col

    def _place(self, widget: tk.Widget, row: int, col: int, span: bool = False) -> None:
        s = self.px
        widget.grid(row=row, column=col, columnspan=2 if span else 1, sticky="ew",
                    padx=(0, 0 if (col == 1 or span) else s(34)), pady=(0, s(18)))
        self._bind_wheel(widget)

    def _bind_wheel(self, widget: tk.Widget) -> None:
        widget.bind("<MouseWheel>", self._panel_wheel)
        for child in widget.winfo_children():
            self._bind_wheel(child)

    # -- field components -------------------------------------------------------

    def _field_shell(self, label: str, hint: str, span: bool = False) -> tk.Frame:
        t = self.t
        s = self.px
        grid, row, col = self._slot(span)
        box = tk.Frame(grid, bg=t["win"])
        tk.Label(box, text=label, font=self.font(13.5, "bold"), bg=t["win"], fg=t["text"]
                 ).pack(anchor="w")
        if hint:
            tk.Label(box, text=hint, font=self.font(12), bg=t["win"], fg=t["muted"],
                     wraplength=s(396), justify="left").pack(anchor="w", pady=(s(1), s(8)))
        else:
            tk.Frame(box, bg=t["win"], height=s(8)).pack()
        self._place(box, row, col, span)
        return box

    def _entry(self, parent: tk.Frame, key: str, mono: bool = False, secret: bool = False,
               suffix: str = "", placeholder: str = "", width: int | None = None) -> None:
        t = self.t
        s = self.px
        h = s(42)
        c = tk.Canvas(parent, height=h, bg=t["win"], highlightthickness=0,
                      width=s(width) if width else 0)
        c.pack(fill="x" if not width else "none", anchor="w")

        state = {"focus": False, "hover": False, "show": False}

        def paint() -> None:
            c.delete("border")
            w = c.winfo_width()
            if w <= 4:
                return
            border = BLUE if state["focus"] else (t["line3"] if state["hover"] else t["line2"])
            rrect(c, 1, 1, w - 2, h - 2, s(10), fill=t["field_focus"] if state["focus"] else t["field"],
                  outline=border, width=2 if state["focus"] else 1, tags="border")
            c.tag_lower("border")
            if suffix:
                c.delete("suffix")
                c.create_text(w - s(13), h / 2, text=suffix, anchor="e",
                              font=(self.f_display, -s(12)), fill=t["faint"], tags="suffix")

        font = (self.f_display, -s(13.5)) if (mono or secret) else (self.f_ui, -s(14))
        entry = tk.Entry(c, bd=0, relief="flat", font=font, bg=t["field"], fg=t["text"],
                         insertbackground=t["text"], highlightthickness=0,
                         disabledbackground=t["field"],
                         show="*" if secret else "")
        value = str(self.values.get(key, ""))
        entry.insert(0, value)
        self.entries[key] = entry

        right_pad = s(40) if secret else (s(58) if suffix else s(13))

        def layout(_=None) -> None:
            w = c.winfo_width()
            c.delete("entrywin")
            c.create_window(s(13), h / 2, window=entry, anchor="w",
                            width=max(s(40), w - s(13) - right_pad), tags="entrywin")
            paint()
            if secret:
                draw_reveal()

        def on_focus(focused: bool) -> None:
            state["focus"] = focused
            entry.configure(bg=t["field_focus"] if focused else t["field"])
            paint()
            self.values[key] = entry.get()

        entry.bind("<FocusIn>", lambda e: on_focus(True))
        entry.bind("<FocusOut>", lambda e: on_focus(False))
        entry.bind("<KeyRelease>", lambda e: self.values.__setitem__(key, entry.get()))
        c.bind("<Enter>", lambda e: (state.__setitem__("hover", True), paint()))
        c.bind("<Leave>", lambda e: (state.__setitem__("hover", False), paint()))
        c.bind("<Configure>", layout)
        c.bind("<Button-1>", lambda e: entry.focus_set())

        if secret:
            def draw_reveal() -> None:
                c.delete("reveal")
                w = c.winfo_width()
                icon = "eye_off" if state["show"] else "eye"
                draw_icon(c, icon, w - s(22), h / 2, s(15), t["muted"])
                rect = c.create_rectangle(w - s(36), s(6), w - s(8), h - s(6), fill="", width=0,
                                          tags="reveal")
                c.tag_bind(rect, "<Button-1>", toggle_reveal)

            def toggle_reveal(_=None) -> None:
                state["show"] = not state["show"]
                entry.configure(show="" if state["show"] else "*")
                c.delete("all")
                layout()

    def _select(self, parent: tk.Frame, key: str, options: list[str]) -> None:
        t = self.t
        s = self.px
        h = s(42)
        c = tk.Canvas(parent, height=h, bg=t["win"], highlightthickness=0, cursor="hand2")
        c.pack(fill="x")
        state = {"hover": False}

        def paint(_=None) -> None:
            c.delete("all")
            w = c.winfo_width()
            if w <= 4:
                return
            rrect(c, 1, 1, w - 2, h - 2, s(10), fill=t["field"],
                  outline=t["line3"] if state["hover"] else t["line2"], width=1)
            text = str(self.values.get(key, "")) or (options[0] if options else "")
            c.create_text(s(13), h / 2, text=text, anchor="w", font=(self.f_ui, -s(14)),
                          fill=t["text"], width=w - s(50))
            draw_icon(c, "caret", w - s(20), h / 2, s(15), t["muted"])

        def open_menu(_=None) -> None:
            menu = tk.Menu(c, tearoff=0, bg=t["panel2"], fg=t["text"],
                           activebackground=BLUE, activeforeground="#FFFFFF",
                           relief="flat", bd=0, font=(self.f_ui, -s(13)))
            for opt in options:
                menu.add_command(label=opt,
                                 command=lambda o=opt: (self.values.__setitem__(key, o), paint(),
                                                        self._refresh_stats()))
            menu.tk_popup(c.winfo_rootx() + s(4), c.winfo_rooty() + h)

        c.bind("<Configure>", paint)
        c.bind("<Enter>", lambda e: (state.__setitem__("hover", True), paint()))
        c.bind("<Leave>", lambda e: (state.__setitem__("hover", False), paint()))
        c.bind("<Button-1>", open_menu)

    def _segmented(self, parent: tk.Frame, key: str, options: list[str]) -> None:
        t = self.t
        s = self.px
        font = tkfont.Font(family=self.f_ui, size=-s(12.5), weight="bold")
        pad, ih, gap = s(14), s(28), s(2)
        widths = [font.measure(o) + 2 * pad for o in options]
        total_w = sum(widths) + gap * (len(options) + 1) + s(4)
        total_h = ih + s(8)
        c = tk.Canvas(parent, width=total_w, height=total_h, bg=t["win"], highlightthickness=0,
                      cursor="hand2")
        c.pack(anchor="w")
        zones: list[tuple[float, float, str]] = []

        def paint() -> None:
            c.delete("all")
            zones.clear()
            rrect(c, 1, 1, total_w - 1, total_h - 1, s(10), fill=t["panel2"], outline=t["line2"], width=1)
            x = gap + s(2)
            current = str(self.values.get(key, options[0]))
            for opt, tw in zip(options, widths):
                active = opt == current
                if active:
                    rrect(c, x, s(4), x + tw, s(4) + ih, s(7), fill=BLUE, width=0)
                c.create_text(x + tw / 2, s(4) + ih / 2, text=opt, font=font,
                              fill="#FFFFFF" if active else t["muted"])
                zones.append((x, x + tw, opt))
                x += tw + gap

        def on_click(event) -> None:
            for x0, x1, opt in zones:
                if x0 <= event.x <= x1:
                    self.values[key] = opt
                    paint()
                    return

        c.bind("<Button-1>", on_click)
        paint()

    def _toggle_row(self, label: str, hint: str, key: str, span: bool = False,
                    command=None) -> None:
        t = self.t
        s = self.px
        grid, row, col = self._slot(span)
        h = s(64)
        c = tk.Canvas(grid, height=h, bg=t["win"], highlightthickness=0, cursor="hand2")
        state = {"hover": False}

        def paint(_=None) -> None:
            c.delete("all")
            w = c.winfo_width()
            if w <= 4:
                return
            rrect(c, 1, 1, w - 2, h - 2, s(12), fill=t["panel2"],
                  outline=t["line2"] if state["hover"] else t["line"], width=1)
            c.create_text(s(15), s(15), text=label, anchor="nw",
                          font=self.font(13.5, "bold"), fill=t["text"])
            c.create_text(s(15), s(34), text=hint, anchor="nw", font=self.font(12),
                          fill=t["muted"], width=w - s(90))
            # switch
            on = bool(self.values.get(key))
            sx, sy, sw, sh = w - s(57), s(18), s(42), s(25)
            if on:
                rrect(c, sx, sy, sx + sw, sy + sh, sh / 2,
                      fill=_mix(BLUE, CYAN, 0.18 if state["hover"] else 0.0),
                      outline=_mix(CYAN, BLUE, 0.35), width=1)
            else:
                rrect(c, sx, sy, sx + sw, sy + sh, sh / 2, fill=t["line3"], width=0)
            kx = sx + (sw - s(22)) if on else sx + s(3)
            c.create_oval(kx, sy + s(3), kx + s(19), sy + s(22), fill="#FFFFFF", width=0)

        def toggle(_=None) -> None:
            self.values[key] = not bool(self.values.get(key))
            paint()
            self._refresh_stats()
            if command:
                command(bool(self.values[key]))

        c.bind("<Configure>", paint)
        c.bind("<Enter>", lambda e: (state.__setitem__("hover", True), paint()))
        c.bind("<Leave>", lambda e: (state.__setitem__("hover", False), paint()))
        c.bind("<Button-1>", toggle)
        self._place(c, row, col, span)

    def _section_title(self, text: str) -> None:
        t = self.t
        s = self.px
        grid, row, _ = self._slot(span=True)
        box = tk.Frame(grid, bg=t["win"])
        label = tk.Label(box, text=text, font=(self.f_display, -s(13), "bold"),
                         bg=t["win"], fg=t["muted"])
        label.pack(side="left")
        line = tk.Frame(box, bg=t["line"], height=1)
        line.pack(side="left", fill="x", expand=True, padx=(s(10), 0), pady=(s(2), 0))
        box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(s(6), s(16)))

    def _ghost_button(self, parent: tk.Frame, text: str, icon: str | None, command,
                      side: str = "left") -> None:
        t = self.t
        s = self.px
        font = tkfont.Font(family=self.f_ui, size=-s(13), weight="bold")
        w = font.measure(text) + (s(52) if icon else s(32))
        h = s(40)
        c = tk.Canvas(parent, width=w, height=h, bg=parent["bg"], highlightthickness=0,
                      cursor="hand2")
        c.pack(side=side, padx=(0, s(9)))

        def paint(hover: bool) -> None:
            c.delete("all")
            rrect(c, 1, 1, w - 1, h - 1, s(10), fill=t["line"] if hover else "",
                  outline=t["line3"] if hover else t["line2"], width=1)
            tx = s(16)
            if icon:
                draw_icon(c, icon, s(22), h / 2, s(15), t["text"])
                tx = s(34)
            c.create_text(tx, h / 2, text=text, anchor="w", font=font, fill=t["text"])

        paint(False)
        c.bind("<Enter>", lambda e: paint(True))
        c.bind("<Leave>", lambda e: paint(False))
        c.bind("<Button-1>", lambda e: command())

    # -- tab contents ------------------------------------------------------------

    def _tab_provider(self) -> None:
        box = self._field_shell("API key", "Stored locally in your Flowz config file.")
        self._entry(box, "api_key", secret=True)
        box = self._field_shell("Base URL", "Any OpenAI-compatible transcription endpoint.")
        self._entry(box, "base_url", mono=True)
        box = self._field_shell("Transcription model", "Example: whisper-large-v3.")
        self._entry(box, "transcription_model", mono=True)
        box = self._field_shell("Language", "Optional ISO language hint. Leave blank for auto.")
        self._entry(box, "language", mono=True, placeholder="auto")
        box = self._field_shell("Request timeout", "Network timeout for API calls.")
        self._entry(box, "request_timeout_seconds", mono=True, suffix="seconds")
        box = self._field_shell("HTTP transport", "Use curl for Windows reliability, or urllib.")
        self._segmented(box, "http_transport", ["curl", "urllib"])
        box = self._field_shell("curl path", "Usually curl.exe on modern Windows.", span=True)
        self._entry(box, "curl_path", mono=True, width=410)

    def _tab_capture(self) -> None:
        devices: list[str] = []
        try:
            devices = self.engine.list_audio_devices(str(self.values.get("ffmpeg_path", "ffmpeg")))
        except Exception as exc:
            self.engine.log(f"Could not list devices for settings GUI: {exc}")
        current = str(self.values.get("ffmpeg_device", "")).strip()
        options = ["Auto (first device)"] + devices if devices else ["Auto (first device)"]
        if current and current not in devices:
            options.insert(1, current)
        if not current:
            self.values["ffmpeg_device"] = ""

        box = self._field_shell("Microphone device", "Pick the DirectShow input used by ffmpeg.")
        # map between display text and stored value
        key = "ffmpeg_device"
        display_key = "__device_display__"
        self.values[display_key] = current or "Auto (first device)"

        t, s = self.t, self.px
        h = s(42)
        c = tk.Canvas(box, height=h, bg=t["win"], highlightthickness=0, cursor="hand2")
        c.pack(fill="x")

        def paint(_=None) -> None:
            c.delete("all")
            w = c.winfo_width()
            if w <= 4:
                return
            rrect(c, 1, 1, w - 2, h - 2, s(10), fill=t["field"], outline=t["line2"], width=1)
            c.create_text(s(13), h / 2, text=str(self.values[display_key]), anchor="w",
                          font=(self.f_ui, -s(14)), fill=t["text"], width=w - s(50))
            draw_icon(c, "caret", w - s(20), h / 2, s(15), t["muted"])

        def choose(opt: str) -> None:
            self.values[display_key] = opt
            self.values[key] = "" if opt == "Auto (first device)" else opt
            paint()
            self._refresh_stats()

        def open_menu(_=None) -> None:
            menu = tk.Menu(c, tearoff=0, bg=t["panel2"], fg=t["text"], activebackground=BLUE,
                           activeforeground="#FFFFFF", relief="flat", bd=0, font=(self.f_ui, -s(13)))
            for opt in options:
                menu.add_command(label=opt, command=lambda o=opt: choose(o))
            menu.tk_popup(c.winfo_rootx() + s(4), c.winfo_rooty() + h)

        c.bind("<Configure>", paint)
        c.bind("<Button-1>", open_menu)

        box = self._field_shell("ffmpeg path", "Leave as ffmpeg to use the bundled copy in the installer.")
        self._entry(box, "ffmpeg_path", mono=True)

        self._section_title("Warm capture")
        self._toggle_row("Low-latency capture", "Keeps the microphone warm for faster response.",
                         "low_latency_capture")
        self._toggle_row("Prime on startup", "Runs a tiny capture at launch to wake the device.",
                         "ffmpeg_prime_on_startup")

        for label, hint, key2, suffix in (
            ("Idle timeout", "Releases warm capture after inactivity.", "low_latency_idle_timeout_seconds", "seconds"),
            ("Pre-roll", "Safety buffer that protects the first word.", "low_latency_preroll_ms", "ms"),
            ("Ring buffer", "Maximum warm audio history kept in memory.", "low_latency_ring_seconds", "seconds"),
            ("Ready timeout", "How long to wait for warm capture.", "low_latency_ready_timeout_ms", "ms"),
            ("Startup probe", "Direct recording startup check duration.", "ffmpeg_startup_probe_ms", "ms"),
            ("Prime duration", "Length of startup priming capture.", "ffmpeg_prime_duration_ms", "ms"),
        ):
            box = self._field_shell(label, hint)
            self._entry(box, key2, mono=True, suffix=suffix)

    def _tab_cue(self) -> None:
        self._toggle_row("Ready sound", "Audio confirmation that speech can begin.",
                         "audio_ready_sound", span=True)
        box = self._field_shell(
            "Sound file",
            "Custom MP3 or WAV cue. Flowz clears captured cue audio before transcribing.",
            span=True,
        )
        t, s = self.t, self.px
        row = tk.Frame(box, bg=t["win"])
        row.pack(fill="x")
        inner = tk.Frame(row, bg=t["win"])
        inner.pack(side="left", fill="x", expand=True)
        self._entry(inner, "audio_ready_sound_file", mono=True)

        def browse() -> None:
            selected = filedialog.askopenfilename(
                title="Choose ready sound",
                filetypes=[("Audio files", "*.mp3 *.wav"), ("All files", "*.*")],
            )
            if selected:
                entry = self.entries.get("audio_ready_sound_file")
                if entry:
                    entry.delete(0, "end")
                    entry.insert(0, selected)
                self.values["audio_ready_sound_file"] = selected

        btns = tk.Frame(row, bg=t["win"])
        btns.pack(side="left", padx=(s(8), 0))
        self._ghost_button(btns, "Browse", "folder", browse)

        box = self._field_shell("Sound backend", "How the ready cue is produced.")
        self._select(box, "audio_ready_sound_backend", ["file", "system", "alias", "message", "tone", "off"])
        box = self._field_shell("Windows sound alias", "Used when backend is system or alias.")
        self._entry(box, "audio_ready_sound_alias", mono=True)
        box = self._field_shell("Tone frequency", "Fallback tone frequency.")
        self._entry(box, "audio_ready_sound_frequency_hz", mono=True, suffix="Hz")
        box = self._field_shell("Tone duration", "Fallback tone duration.")
        self._entry(box, "audio_ready_sound_duration_ms", mono=True, suffix="ms")

    def _tab_output(self) -> None:
        self._section_title("Silence trimming")
        self._toggle_row("Trim silence", "Falls back to original audio if speech is quiet.",
                         "trim_silence")
        box = self._field_shell("Silence threshold", "Lower is more tolerant of soft voice.")
        self._entry(box, "silence_threshold", mono=True)
        box = self._field_shell("Silence padding", "Extra audio kept around detected speech.")
        self._entry(box, "silence_padding_ms", mono=True, suffix="ms")
        box = self._field_shell("Minimum audio", "Minimum usable speech segment length.")
        self._entry(box, "silence_min_audio_ms", mono=True, suffix="ms")

        self._section_title("Text & paste")
        self._toggle_row("Post-process text", "Runs an LLM cleanup pass after transcription.",
                         "post_process")
        box = self._field_shell("Post-process model", "Model used for cleanup.")
        self._entry(box, "post_process_model", mono=True)
        self._toggle_row("Paste result automatically", "Paste at cursor right after transcription.",
                         "paste_result")
        self._toggle_row("Append space after sentence", "Adds a trailing space after final punctuation.",
                         "append_space_after_sentence")
        self._toggle_row("Preserve clipboard text", "Restores prior clipboard text after paste.",
                         "preserve_text_clipboard")

    def _tab_app(self) -> None:
        self._section_title("Interface")
        self._toggle_row("Visual indicator", "Shows capture and transcription status on screen.",
                         "visual_indicator")
        box = self._field_shell("Success display", "How long success states remain visible.")
        self._entry(box, "visual_indicator_success_seconds", mono=True, suffix="seconds")
        self._toggle_row("Tray icon", "Adds pause, settings, and exit controls to the system tray.",
                         "tray_icon")
        self._toggle_row("Log timing metrics", "Writes capture, trim, transcription, and paste timings to the log.",
                         "log_timing_metrics")

        self._section_title("System")
        self._toggle_row("Start with Windows", "Adds or removes the Flowz run key for this user.",
                         "__startup__")

        t, s = self.t, self.px
        box = self._field_shell("Diagnostics", "Run quick checks without leaving settings.")
        row = tk.Frame(box, bg=t["win"])
        row.pack(anchor="w")
        self._ghost_button(row, "Record 3s", "capture", lambda: self._run_diagnostic(
            "Recording 3s sample...", lambda: (self.apply_form(), self.engine.test_record(self.config, 3))))
        self._ghost_button(row, "Test API", "zap", lambda: self._run_diagnostic(
            "Testing API endpoint...", lambda: (self.apply_form(), self.engine.test_api(self.config))))
        self._ghost_button(row, "Open config", "output", self._open_config_folder)

    # -- footer -------------------------------------------------------------------

    def _build_footer(self, content: tk.Frame) -> None:
        t = self.t
        s = self.px
        tk.Frame(content, bg=t["line"], height=1).pack(fill="x", side="bottom")
        foot = tk.Frame(content, bg=t["win"], height=s(60))
        foot.pack(fill="x", side="bottom")
        foot.pack_propagate(False)

        status = tk.Frame(foot, bg=t["win"])
        status.pack(side="left", padx=(s(28), 0))
        self._status_dot_small = tk.Canvas(status, width=s(9), height=s(9), bg=t["win"],
                                           highlightthickness=0)
        self._status_dot_small.pack(side="left")
        self._paint_status_dot(OK)
        self._status_label = tk.Label(status, text="Ready cue sent.", font=self.font(13),
                                      bg=t["win"], fg=t["muted"])
        self._status_label.pack(side="left", padx=(s(9), 0))

        actions = tk.Frame(foot, bg=t["win"])
        actions.pack(side="right", padx=(0, s(18)))

        self._footer_button(actions, "Test cue", "secondary", self._test_cue, icon="play")
        self._footer_button(actions, "Cancel", "secondary", self.root.destroy)
        self._footer_button(actions, "Save", "secondary", self._save)
        self._footer_button(actions, "Save and close", "primary", self._save_and_close)

    def _paint_status_dot(self, color: str) -> None:
        c = self._status_dot_small
        c.delete("all")
        s = self.px
        c.create_oval(1, 1, s(8), s(8), fill=color, outline=color)

    def _footer_button(self, parent: tk.Frame, text: str, kind: str, command,
                       icon: str | None = None) -> None:
        t = self.t
        s = self.px
        font = tkfont.Font(family=self.f_ui, size=-s(13.5), weight="bold")
        w = font.measure(text) + (s(56) if icon else s(36))
        h = s(40)
        c = tk.Canvas(parent, width=w, height=h, bg=t["win"], highlightthickness=0,
                      cursor="hand2", takefocus=0)
        c.pack(side="left", padx=(s(9), 0))

        def paint(hover: bool) -> None:
            c.delete("all")
            if kind == "primary":
                rrect(c, 1, 1, w - 1, h - 1, s(10),
                      fill=_mix(BLUE, CYAN, 0.12 if hover else 0.0),
                      outline=_mix(CYAN, BLUE, 0.35), width=1)
                fg = "#FFFFFF"
            else:
                rrect(c, 1, 1, w - 1, h - 1, s(10), fill=t["panel2"] if hover else "",
                      outline=t["line3"] if hover else t["line2"], width=1)
                fg = t["text"]
            tx = w / 2
            if icon:
                total = font.measure(text) + s(20)
                draw_icon(c, icon, tx - total / 2 + s(6), h / 2, s(14), fg)
                c.create_text(tx - total / 2 + s(20), h / 2, text=text, anchor="w", font=font, fill=fg)
            else:
                c.create_text(tx, h / 2, text=text, font=font, fill=fg)

        paint(False)
        c.bind("<Enter>", lambda e: paint(True))
        c.bind("<Leave>", lambda e: paint(False))
        c.bind("<Button-1>", lambda e: command())

    # -- actions ---------------------------------------------------------------

    def toast(self, message: str, tone: str = "ok") -> None:
        colors = {"ok": OK, "busy": BLUE, "warn": WARN, "bad": BAD}
        try:
            self._status_label.configure(text=message)
            self._paint_status_dot(colors.get(tone, OK))
        except tk.TclError:
            return
        if self._status_after:
            try:
                self.root.after_cancel(self._status_after)
            except Exception:
                pass
        self._status_after = self.root.after(
            2600, lambda: (self._status_label.configure(text="Ready cue sent."),
                           self._paint_status_dot(OK)))

    def _save(self) -> bool:
        try:
            self.apply_form()
            self.config.save()
            self.engine.set_startup_enabled(bool(self.values.get("__startup__")))
            self.toast("Settings saved.", "ok")
            return True
        except Exception as exc:
            self.toast(f"Could not save: {exc}", "bad")
            return False

    def _save_and_close(self) -> None:
        if self._save():
            self.root.after(450, self.root.destroy)

    def _test_cue(self) -> None:
        try:
            self.apply_form()
        except Exception as exc:
            self.toast(f"Invalid settings: {exc}", "bad")
            return
        self.toast("Playing ready cue...", "busy")

        def worker() -> None:
            try:
                played = self.engine.play_ready_sound(self.config)
                self.root.after(0, lambda: self.toast(
                    "Ready cue sent." if played else "Ready cue is disabled.",
                    "ok" if played else "warn"))
            except Exception as exc:
                self.root.after(0, lambda: self.toast(f"Cue failed: {exc}", "bad"))

        threading.Thread(target=worker, name="settings-cue", daemon=True).start()

    def _run_diagnostic(self, label: str, target) -> None:
        self.toast(label, "busy")

        def worker() -> None:
            try:
                target()
            except Exception as exc:
                self.root.after(0, lambda: self.toast(str(exc), "bad"))
            else:
                self.root.after(0, lambda: self.toast("Diagnostic completed.", "ok"))

        threading.Thread(target=worker, name="settings-diagnostic", daemon=True).start()

    def _open_config_folder(self) -> None:
        self.engine.app_config_dir().mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer.exe", str(self.engine.app_config_dir())],
                         creationflags=self.engine.CREATE_NO_WINDOW)
        self.toast("Opening config folder...", "busy")

    # -- animation loop -----------------------------------------------------------

    def _animate(self) -> None:
        self._tick += 1
        t = self._tick * 0.07
        try:
            if hasattr(self, "_eq_canvas") and self._eq_canvas.winfo_exists():
                s = self.px
                bar_y = s(58)
                for i, item in enumerate(self._eq_bars):
                    f = ((t - i * 0.07) / 1.1) % 1.0
                    height = 4 + 12 * math.sin(math.pi * f)
                    self._eq_canvas.coords(item, s(16) + i * s(6.4), bar_y,
                                           s(16) + i * s(6.4), bar_y - s(max(3, height)))
                # pulsing dot ring
                phase = (self._tick % 34) / 34
                r = s(4) + phase * s(7)
                cx, cy = s(19), s(20)
                ring_color = _mix("#2BD4A0", SIDEBAR["card"], min(1.0, phase * 1.4))
                self._eq_canvas.coords(self._status_ring, cx - r, cy - r, cx + r, cy + r)
                self._eq_canvas.itemconfigure(self._status_ring, outline=ring_color)
        except tk.TclError:
            pass
        try:
            self.root.after(70, self._animate)
        except tk.TclError:
            pass

    # -- main loop ------------------------------------------------------------------

    def run(self) -> None:
        self.root.mainloop()


def show_settings_window(config, engine) -> None:
    SettingsWindow(config, engine).run()
