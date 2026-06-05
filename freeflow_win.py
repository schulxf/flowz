#!/usr/bin/env python3
"""
Flowz.

Hold Ctrl + Windows to record, release to transcribe, then paste at the
currently focused cursor.

No third-party Python packages are required. Audio capture uses ffmpeg's
DirectShow input, so ffmpeg must be available on PATH or configured below.
"""

from __future__ import annotations

import argparse
import ctypes
import getpass
import json
import math
import os
import queue
import random
import re
import string
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
import wave
from collections import deque
from ctypes import wintypes
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable


APP_NAME = "Flowz"
APP_DIR_NAME = "Flowz"
LEGACY_APP_DIR_NAMES = ("FreeFlowWin",)
CONFIG_FILE_NAME = "config.json"
LOG_FILE_NAME = "flowz.log"
TRANSPARENT_COLOR = "#010203"
PCM_SAMPLE_RATE = 16000
PCM_CHANNELS = 1
PCM_SAMPLE_WIDTH = 2
PCM_BYTES_PER_SECOND = PCM_SAMPLE_RATE * PCM_CHANNELS * PCM_SAMPLE_WIDTH
LOW_LATENCY_READ_CHUNK_MS = 20

VK_CONTROL = 0x11
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_V = 0x56

CTRL_KEYS = {VK_CONTROL, VK_LCONTROL, VK_RCONTROL}
WIN_KEYS = {VK_LWIN, VK_RWIN}

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205

WH_KEYBOARD_LL = 13
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183
ERROR_CLASS_ALREADY_EXISTS = 1410
EVENT_MODIFY_STATE = 0x0002
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
INFINITE = 0xFFFFFFFF
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
MUTEX_NAME = "Local\\FlowzSingleInstance"
STOP_EVENT_NAME = "Local\\FlowzStop"
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
IDI_APPLICATION = 32512
MF_STRING = 0x00000000
MF_GRAYED = 0x00000001
MF_SEPARATOR = 0x00000800
TPM_RIGHTBUTTON = 0x00000002
TRAY_UID = 1
TRAY_MENU_TOGGLE_PAUSE = 1001
TRAY_MENU_RELEASE_CAPTURE = 1002
TRAY_MENU_OPEN_CONFIG = 1003
TRAY_MENU_EXIT = 1004
TRAY_MENU_SETTINGS = 1005
RUN_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = APP_NAME


def now() -> str:
    return time.strftime("%H:%M:%S")


def log(message: str) -> None:
    line = f"[{now()}] {message}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        path = app_config_dir() / LOG_FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
    except Exception:
        pass


def app_config_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / f".{APP_DIR_NAME.lower()}"


def legacy_app_config_dirs() -> list[Path]:
    base = os.environ.get("APPDATA")
    if base:
        return [Path(base) / name for name in LEGACY_APP_DIR_NAMES]
    return [Path.home() / f".{name.lower()}" for name in LEGACY_APP_DIR_NAMES]


def config_path() -> Path:
    return app_config_dir() / CONFIG_FILE_NAME


def migrate_legacy_config_if_needed() -> None:
    target = config_path()
    if target.exists():
        return
    for legacy_dir in legacy_app_config_dirs():
        legacy_path = legacy_dir / CONFIG_FILE_NAME
        if not legacy_path.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(legacy_path.read_bytes())
        log(f"Migrated config from {legacy_path} to {target}")
        return


def quote_command_arg(value: object) -> str:
    text = str(value)
    return '"' + text.replace('"', '\\"') + '"'


def app_launch_command() -> str:
    if getattr(sys, "frozen", False):
        return quote_command_arg(sys.executable)

    script = Path(__file__).resolve()
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    executable = pythonw if pythonw.exists() else Path(sys.executable)
    return f"{quote_command_arg(executable)} {quote_command_arg(script)}"


def settings_launch_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--settings"]
    return [sys.executable, str(Path(__file__).resolve()), "--settings"]


def launch_settings_window() -> None:
    subprocess.Popen(settings_launch_command(), creationflags=CREATE_NO_WINDOW)


def is_startup_enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REGISTRY_PATH, 0, winreg.KEY_READ) as key:
            for value_name in (RUN_VALUE_NAME, *LEGACY_APP_DIR_NAMES):
                try:
                    winreg.QueryValueEx(key, value_name)
                    return True
                except FileNotFoundError:
                    pass
            return False
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_startup_enabled(enabled: bool, command: str | None = None) -> None:
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_REGISTRY_PATH, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, command or app_launch_command())
            for value_name in LEGACY_APP_DIR_NAMES:
                try:
                    winreg.DeleteValue(key, value_name)
                except FileNotFoundError:
                    pass
        else:
            for value_name in (RUN_VALUE_NAME, *LEGACY_APP_DIR_NAMES):
                try:
                    winreg.DeleteValue(key, value_name)
                except FileNotFoundError:
                    pass


def has_interactive_console() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        return False


def prompt_api_key_gui() -> str:
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception as exc:
        raise RuntimeError("API key is required. Run Flowz.bat --setup first.") from exc

    result = {"value": ""}
    root = tk.Tk()
    root.title("Flowz Setup")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    width = 440
    height = 170
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")

    frame = tk.Frame(root, padx=18, pady=16)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text="Flowz precisa de uma API key da Groq.", anchor="w").pack(fill="x")
    tk.Label(frame, text="Cole a chave. Ela sera salva em %APPDATA%\\Flowz.", anchor="w").pack(fill="x", pady=(2, 10))

    entry = tk.Entry(frame, show="*", width=56)
    entry.pack(fill="x")
    entry.focus_set()

    buttons = tk.Frame(frame)
    buttons.pack(fill="x", pady=(14, 0))

    def save() -> None:
        value = entry.get().strip()
        if not value:
            messagebox.showerror("Flowz", "API key obrigatoria.")
            return
        result["value"] = value
        root.destroy()

    def cancel() -> None:
        root.destroy()

    tk.Button(buttons, text="Salvar", width=12, command=save).pack(side="right")
    tk.Button(buttons, text="Cancelar", width=12, command=cancel).pack(side="right", padx=(0, 8))
    root.bind("<Return>", lambda _event: save())
    root.bind("<Escape>", lambda _event: cancel())
    root.mainloop()
    return result["value"]


@dataclass
class AppConfig:
    api_key: str = ""
    base_url: str = "https://api.groq.com/openai/v1"
    transcription_model: str = "whisper-large-v3"
    language: str = ""
    request_timeout_seconds: int = 60
    http_transport: str = "curl"
    curl_path: str = "curl.exe"
    ffmpeg_path: str = "ffmpeg"
    ffmpeg_device: str = ""
    ffmpeg_startup_probe_ms: int = 80
    ffmpeg_prime_on_startup: bool = True
    ffmpeg_prime_duration_ms: int = 120
    low_latency_capture: bool = True
    low_latency_idle_timeout_seconds: int = 60
    low_latency_preroll_ms: int = 800
    low_latency_ring_seconds: int = 4
    low_latency_ready_timeout_ms: int = 2000
    trim_silence: bool = True
    silence_threshold: int = 300
    silence_padding_ms: int = 280
    silence_min_audio_ms: int = 250
    audio_quality_defaults_version: int = 2
    log_timing_metrics: bool = True
    post_process: bool = False
    post_process_model: str = "openai/gpt-oss-20b"
    paste_result: bool = True
    append_space_after_sentence: bool = True
    preserve_text_clipboard: bool = True
    audio_ready_sound: bool = True
    audio_ready_sound_file: str = ""
    audio_ready_sound_backend: str = "system"
    audio_ready_sound_alias: str = "SystemAsterisk"
    audio_ready_sound_frequency_hz: int = 880
    audio_ready_sound_duration_ms: int = 70
    visual_indicator: bool = True
    visual_indicator_success_seconds: float = 1.1
    tray_icon: bool = True

    @classmethod
    def load(cls) -> "AppConfig":
        migrate_legacy_config_if_needed()
        path = config_path()
        config = cls()

        loaded_audio_defaults_version = config.audio_quality_defaults_version
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                raise RuntimeError(f"Could not read config at {path}: {exc}") from exc
            try:
                loaded_audio_defaults_version = int(data.get("audio_quality_defaults_version", 1) or 1)
            except (TypeError, ValueError):
                loaded_audio_defaults_version = 1
            for key, value in data.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            config.apply_audio_quality_migrations(loaded_audio_defaults_version)

        env_key = (
            os.environ.get("FREEFLOW_API_KEY")
            or os.environ.get("GROQ_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        if env_key and not config.api_key:
            config.api_key = env_key.strip()

        env_base = os.environ.get("FREEFLOW_BASE_URL")
        if env_base:
            config.base_url = env_base.strip()

        return config

    def apply_audio_quality_migrations(self, loaded_version: int) -> None:
        if loaded_version >= 2:
            return
        if self.low_latency_preroll_ms == 500:
            self.low_latency_preroll_ms = 800
        if self.silence_threshold == 450:
            self.silence_threshold = 300
        if self.silence_padding_ms == 140:
            self.silence_padding_ms = 280
        self.audio_quality_defaults_version = 2

    def save(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=True), encoding="utf-8")


def ensure_config(config: AppConfig) -> AppConfig:
    if config.api_key:
        return config

    if not has_interactive_console():
        entered = prompt_api_key_gui().strip()
        if not entered:
            raise RuntimeError("API key is required for transcription.")
        config.api_key = entered
        config.save()
        return config

    print()
    log("No API key found.")
    print(f"Config path: {config_path()}")
    print("Set FREEFLOW_API_KEY/GROQ_API_KEY, or paste a Groq/OpenAI-compatible key now.")
    try:
        entered = getpass.getpass("API key: ").strip()
    except Exception:
        entered = input("API key: ").strip()
    if not entered:
        raise RuntimeError("API key is required for transcription.")
    config.api_key = entered
    config.save()
    log(f"Saved config to {config_path()}")
    return config


def list_audio_devices(ffmpeg_path: str) -> list[str]:
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-list_devices",
        "true",
        "-f",
        "dshow",
        "-i",
        "dummy",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg was not found on PATH. Set ffmpeg_path in config.json.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ffmpeg device listing timed out.") from exc

    output = (result.stderr or "") + "\n" + (result.stdout or "")
    devices: list[str] = []
    for line in output.splitlines():
        match = re.search(r'"([^"]+)"\s+\(audio\)', line)
        if match:
            name = match.group(1)
            if name not in devices:
                devices.append(name)
    return devices


class FFmpegRecorder:
    def __init__(self, config: AppConfig):
        self.config = config
        self.process: subprocess.Popen[bytes] | None = None
        self.output_path: Path | None = None
        self.device_name: str | None = None
        self._lock = threading.Lock()

    def _resolve_device(self) -> str:
        configured = self.config.ffmpeg_device.strip()
        if configured:
            return configured
        if self.device_name:
            return self.device_name
        devices = list_audio_devices(self.config.ffmpeg_path)
        if not devices:
            raise RuntimeError("No DirectShow audio input devices found by ffmpeg.")
        return devices[0]

    def warm_up_device(self) -> str:
        with self._lock:
            self.device_name = self._resolve_device()
            return self.device_name

    def start(self) -> float:
        with self._lock:
            if self.process is not None:
                return 0.0

            start_time = time.perf_counter()
            device = self._resolve_device()
            output = Path(tempfile.gettempdir()) / f"flowz-{int(time.time())}-{random.randint(1000, 9999)}.wav"
            command = [
                self.config.ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "dshow",
                "-i",
                f"audio={device}",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(output),
            ]
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW,
            )
            self._wait_for_startup_probe(process, output, device)

            self.process = process
            self.output_path = output
            self.device_name = device
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            log(f"Recording from: {device} (ffmpeg start checked in {elapsed_ms:.0f} ms)")
            return elapsed_ms

    def prime(self) -> float:
        duration_ms = int_setting(self.config.ffmpeg_prime_duration_ms, 120, 20, 1000)
        output: Path | None = None
        expected_output: Path | None = None
        ready_ms = self.start()
        with self._lock:
            expected_output = self.output_path
        try:
            time.sleep(duration_ms / 1000)
            output = self.stop()
            return ready_ms
        finally:
            for path in (output, expected_output):
                if path is None:
                    continue
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass

    def _wait_for_startup_probe(self, process: subprocess.Popen[bytes], output: Path, device: str) -> None:
        probe_ms = int_setting(self.config.ffmpeg_startup_probe_ms, 80, 0, 1000)
        deadline = time.perf_counter() + (probe_ms / 1000)

        while time.perf_counter() < deadline:
            if process.poll() is not None:
                self._raise_startup_error(process, device)
            try:
                if output.exists() and output.stat().st_size > 44:
                    return
            except OSError:
                pass
            time.sleep(0.008)

        if process.poll() is not None:
            self._raise_startup_error(process, device)

    def _raise_startup_error(self, process: subprocess.Popen[bytes], device: str) -> None:
        stderr = ""
        if process.stderr:
            stderr = process.stderr.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ffmpeg failed to start recording from '{device}'. {stderr.strip()}")

    def stop(self) -> Path:
        with self._lock:
            process = self.process
            output = self.output_path
            self.process = None
            self.output_path = None

        if process is None or output is None:
            raise RuntimeError("Recorder was not running.")

        if process.poll() is None:
            try:
                if process.stdin:
                    process.stdin.write(b"q\n")
                    process.stdin.flush()
            except Exception:
                pass

        try:
            _, stderr_bytes = process.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                _, stderr_bytes = process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                _, stderr_bytes = process.communicate(timeout=3)

        stderr = (stderr_bytes or b"").decode("utf-8", errors="replace").strip()
        if process.returncode not in (0, 255) and not output.exists():
            raise RuntimeError(f"ffmpeg recording failed. {stderr}")

        if not output.exists() or output.stat().st_size <= 44:
            raise RuntimeError("No audio was recorded.")

        return output


class WarmFFmpegRecorder(FFmpegRecorder):
    def __init__(self, config: AppConfig):
        super().__init__(config)
        self.process: subprocess.Popen[bytes] | None = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._watcher_thread: threading.Thread | None = None
        self._reader_stop = threading.Event()
        self._closed = threading.Event()
        self._ready = threading.Event()
        self._ring: deque[bytes] = deque()
        self._ring_bytes = 0
        self._recording = False
        self._recorded_chunks: list[bytes] = []
        self._last_activity = time.perf_counter()
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._chunk_bytes = max(PCM_SAMPLE_WIDTH, pcm_bytes_for_ms(LOW_LATENCY_READ_CHUNK_MS))
        self._start_idle_watcher()

    def prime(self) -> float:
        return self.ensure_capture()

    def ensure_capture(self) -> float:
        start_time = time.perf_counter()
        should_spawn = False
        should_wait = False
        with self._lock:
            self._last_activity = start_time
            if not self._is_process_running_locked():
                should_spawn = True
                should_wait = True
                self._spawn_capture_locked()
            elif not self._ready.is_set():
                should_wait = True

        if should_wait:
            timeout_ms = int_setting(self.config.low_latency_ready_timeout_ms, 2000, 100, 5000)
            if not self._ready.wait(timeout=timeout_ms / 1000):
                with self._lock:
                    process = self.process
                if process is not None and process.poll() is not None:
                    self._raise_warm_startup_error()
                log("Warm capture started, but no audio chunk was received before timeout.")

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        if should_wait:
            log(f"Warm capture ready check took {elapsed_ms:.0f} ms.")
        return elapsed_ms if should_wait else 0.0

    def start(self) -> float:
        elapsed_ms = self.ensure_capture()
        preroll_ms = int_setting(self.config.low_latency_preroll_ms, 500, 0, 5000)
        preroll_bytes = pcm_bytes_for_ms(preroll_ms)
        with self._lock:
            if self._recording:
                return elapsed_ms
            self._recorded_chunks = []
            preroll = self._ring_tail_locked(preroll_bytes)
            if preroll:
                self._recorded_chunks.append(preroll)
            self._recording = True
            self._last_activity = time.perf_counter()
        log(f"Warm recording started with {preroll_ms} ms pre-roll.")
        return elapsed_ms

    def stop(self) -> Path:
        with self._lock:
            if not self._recording:
                raise RuntimeError("Recorder was not running.")
            self._recording = False
            chunks = list(self._recorded_chunks)
            self._recorded_chunks = []
            self._last_activity = time.perf_counter()

        raw_pcm = b"".join(chunks)
        return write_pcm_wav(raw_pcm)

    def clear_recorded_audio(self, reason: str = "manual clear") -> None:
        with self._lock:
            if not self._recording:
                return
            self._recorded_chunks = []
            self._last_activity = time.perf_counter()
        log(f"Warm recorded audio cleared ({reason}).")

    def release_idle_capture(self) -> None:
        with self._lock:
            if self._recording:
                log("Warm capture is recording; release ignored.")
                return
        self._stop_capture("manual release")

    def close(self) -> None:
        self._closed.set()
        self._stop_capture("shutdown")

    def _spawn_capture_locked(self) -> None:
        device = self._resolve_device()
        command = [
            self.config.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "dshow",
            "-i",
            f"audio={device}",
            "-ac",
            str(PCM_CHANNELS),
            "-ar",
            str(PCM_SAMPLE_RATE),
            "-f",
            "s16le",
            "-c:a",
            "pcm_s16le",
            "pipe:1",
        ]
        self._ready.clear()
        self._reader_stop = threading.Event()
        self._ring.clear()
        self._ring_bytes = 0
        self._stderr_tail.clear()
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
        )
        self.device_name = device
        self._reader_thread = threading.Thread(
            target=self._read_stdout_loop,
            args=(self.process, self._reader_stop),
            name="warm-audio-reader",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr_loop,
            args=(self.process, self._reader_stop),
            name="warm-audio-stderr",
            daemon=True,
        )
        self._reader_thread.start()
        self._stderr_thread.start()
        log(f"Warm capture opened from: {device}")

    def _read_stdout_loop(self, process: subprocess.Popen[bytes], stop_event: threading.Event) -> None:
        carry = b""
        try:
            while not stop_event.is_set():
                if not process.stdout:
                    break
                chunk = process.stdout.read(self._chunk_bytes)
                if not chunk:
                    break
                data = carry + chunk
                carry = b""
                if len(data) % PCM_SAMPLE_WIDTH:
                    carry = data[-1:]
                    data = data[:-1]
                if not data:
                    continue
                with self._lock:
                    if process is not self.process:
                        break
                    self._ready.set()
                    self._append_ring_locked(data)
                    if self._recording:
                        self._recorded_chunks.append(data)
        except Exception as exc:
            log(f"Warm capture reader failed: {exc}")
        finally:
            with self._lock:
                if process is self.process and process.poll() is not None:
                    self.process = None
                    self._recording = False

    def _read_stderr_loop(self, process: subprocess.Popen[bytes], stop_event: threading.Event) -> None:
        try:
            if not process.stderr:
                return
            while not stop_event.is_set():
                line = process.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    with self._lock:
                        self._stderr_tail.append(text)
        except Exception:
            pass

    def _start_idle_watcher(self) -> None:
        self._watcher_thread = threading.Thread(target=self._idle_watch_loop, name="warm-audio-idle", daemon=True)
        self._watcher_thread.start()

    def _idle_watch_loop(self) -> None:
        while not self._closed.is_set():
            time.sleep(1.0)
            timeout_seconds = int_setting(self.config.low_latency_idle_timeout_seconds, 60, 0, 3600)
            if timeout_seconds <= 0:
                continue
            should_stop = False
            with self._lock:
                if (
                    self._is_process_running_locked()
                    and not self._recording
                    and time.perf_counter() - self._last_activity >= timeout_seconds
                ):
                    should_stop = True
            if should_stop:
                self._stop_capture("idle timeout")

    def _stop_capture(self, reason: str) -> None:
        with self._lock:
            process = self.process
            self.process = None
            self._recording = False
            self._recorded_chunks = []
            self._ring.clear()
            self._ring_bytes = 0
            self._reader_stop.set()
            self._ready.clear()

        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        log(f"Warm capture stopped ({reason}).")

    def _append_ring_locked(self, data: bytes) -> None:
        max_seconds = int_setting(self.config.low_latency_ring_seconds, 4, 1, 60)
        max_bytes = PCM_BYTES_PER_SECOND * max_seconds
        self._ring.append(data)
        self._ring_bytes += len(data)
        while self._ring and self._ring_bytes > max_bytes:
            removed = self._ring.popleft()
            self._ring_bytes -= len(removed)

    def _ring_tail_locked(self, byte_count: int) -> bytes:
        if byte_count <= 0 or not self._ring:
            return b""
        remaining = min(byte_count, self._ring_bytes)
        parts: list[bytes] = []
        for chunk in reversed(self._ring):
            if remaining <= 0:
                break
            if len(chunk) <= remaining:
                parts.append(chunk)
                remaining -= len(chunk)
            else:
                parts.append(chunk[-remaining:])
                remaining = 0
        parts.reverse()
        return b"".join(parts)

    def _is_process_running_locked(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _raise_warm_startup_error(self) -> None:
        with self._lock:
            details = "\n".join(self._stderr_tail)
        raise RuntimeError(f"ffmpeg failed to start warm capture. {details}".strip())


def create_recorder(config: AppConfig) -> FFmpegRecorder:
    if bool_setting(config.low_latency_capture):
        return WarmFFmpegRecorder(config)
    return FFmpegRecorder(config)


class OpenAICompatibleClient:
    def __init__(self, config: AppConfig):
        self.config = config

    def _url(self, path: str) -> str:
        return self.config.base_url.rstrip("/") + "/" + path.lstrip("/")

    def test_api(self) -> None:
        url = self._url("models")
        if self._use_curl_transport():
            self._run_curl(self._base_curl_config(url, method="GET"))
            return

        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Accept": "application/json",
                "User-Agent": "Flowz/0.1",
            },
        )
        self._send(request)

    def transcribe(self, audio_path: Path) -> str:
        fields = {
            "model": self.config.transcription_model,
            "response_format": "json",
        }
        language = self.config.language.strip()
        if language:
            fields["language"] = language

        if self._use_curl_transport():
            data = self._send_curl_multipart(self._url("audio/transcriptions"), fields, "file", audio_path)
        else:
            boundary = "----flowz" + "".join(random.choice(string.ascii_letters + string.digits) for _ in range(24))
            body = self._multipart_body(boundary, fields, "file", audio_path)
            request = urllib.request.Request(
                self._url("audio/transcriptions"),
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Accept": "application/json",
                    "User-Agent": "Flowz/0.1",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Content-Length": str(len(body)),
                },
            )
            data = self._send(request)
        try:
            payload = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Transcription response was not valid JSON.") from exc

        text = str(payload.get("text", "")).strip()
        return text

    def clean(self, transcript: str) -> str:
        if not self.config.post_process:
            return transcript

        system_prompt = (
            "You are a dictation cleanup layer. Return only the final cleaned text. "
            "No explanations, no markdown, no surrounding quotes. Preserve the user's "
            "meaning and language. Fix punctuation, capitalization, spacing, filler words, "
            "and obvious speech-to-text mistakes. If the input is empty, return EMPTY."
        )
        payload = {
            "model": self.config.post_process_model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"RAW_TRANSCRIPTION: {transcript}"},
            ],
        }
        if self._use_curl_transport():
            data = self._send_curl_json(self._url("chat/completions"), payload)
        else:
            body = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                self._url("chat/completions"),
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Accept": "application/json",
                    "User-Agent": "Flowz/0.1",
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                },
            )
            data = self._send(request)
        try:
            response = json.loads(data.decode("utf-8"))
            content = response["choices"][0]["message"]["content"]
        except Exception as exc:
            raise RuntimeError("Post-processing response was not valid.") from exc
        cleaned = str(content).strip()
        if cleaned.upper() == "EMPTY":
            return ""
        return strip_wrapping_quotes(cleaned)

    def _send(self, request: urllib.request.Request) -> bytes:
        try:
            with urllib.request.urlopen(request, timeout=self.config.request_timeout_seconds) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Provider returned HTTP {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Provider request failed: {exc.reason}") from exc

    def _use_curl_transport(self) -> bool:
        return str(self.config.http_transport).strip().lower() == "curl"

    def _send_curl_multipart(
        self,
        url: str,
        fields: dict[str, str],
        file_field: str,
        file_path: Path
    ) -> bytes:
        lines = self._base_curl_config(url, method="POST")
        for name, value in fields.items():
            lines.append(f'form = "{curl_escape(name)}={curl_escape(value)}"')
        file_value = f"{file_field}=@{file_path.resolve().as_posix()};type=audio/wav"
        lines.append(f'form = "{curl_escape(file_value)}"')
        return self._run_curl(lines)

    def _send_curl_json(self, url: str, payload: dict[str, object]) -> bytes:
        body_path = temp_file_path(".json")
        body_path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            lines = self._base_curl_config(url, method="POST")
            lines.append('header = "Content-Type: application/json"')
            lines.append(f'data-binary = "@{curl_escape(body_path.resolve().as_posix())}"')
            return self._run_curl(lines)
        finally:
            try:
                body_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _base_curl_config(self, url: str, method: str) -> list[str]:
        lines = [
            "silent",
            "show-error",
            f'max-time = "{int(self.config.request_timeout_seconds)}"',
            f'url = "{curl_escape(url)}"',
            f'header = "Authorization: Bearer {curl_escape(self.config.api_key)}"',
            'header = "Accept: application/json"',
            'header = "User-Agent: Flowz/0.1"',
        ]
        if method.upper() != "GET":
            lines.insert(3, f'request = "{curl_escape(method.upper())}"')
        return lines

    def _run_curl(self, lines: list[str]) -> bytes:
        response_path = temp_file_path(".response")
        config_path = temp_file_path(".curlrc")
        try:
            lines = list(lines)
            lines.append(f'output = "{curl_escape(response_path.resolve().as_posix())}"')
            lines.append('write-out = "%{http_code}"')
            config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            result = subprocess.run(
                [self.config.curl_path, "--config", str(config_path)],
                capture_output=True,
                timeout=self.config.request_timeout_seconds + 10,
                creationflags=CREATE_NO_WINDOW,
            )
            stdout = (result.stdout or b"").decode("utf-8", errors="replace").strip()
            stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            body = response_path.read_bytes() if response_path.exists() else b""
            status_match = re.search(r"(\d{3})$", stdout)

            if result.returncode != 0:
                detail = stderr or body.decode("utf-8", errors="replace") or stdout
                raise RuntimeError(f"curl failed with exit code {result.returncode}: {detail}")

            if not status_match:
                raise RuntimeError(f"curl did not report an HTTP status. {stderr or stdout}")

            status = int(status_match.group(1))
            if status != 200:
                detail = body.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Provider returned HTTP {status}: {detail}")
            return body
        except FileNotFoundError as exc:
            raise RuntimeError("curl.exe was not found. Set curl_path in config.json or set http_transport to urllib.") from exc
        finally:
            for path in (response_path, config_path):
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass

    @staticmethod
    def _multipart_body(boundary: str, fields: dict[str, str], file_field: str, file_path: Path) -> bytes:
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.append(f"--{boundary}\r\n".encode("utf-8"))
            chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
            chunks.append(str(value).encode("utf-8"))
            chunks.append(b"\r\n")

        filename = file_path.name
        content_type = "audio/wav"
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode("utf-8")
        )
        chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        chunks.append(file_path.read_bytes())
        chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(chunks)


def temp_file_path(suffix: str) -> Path:
    fd, name = tempfile.mkstemp(prefix="flowz-", suffix=suffix)
    os.close(fd)
    return Path(name)


def curl_escape(value: object) -> str:
    text = str(value)
    return (
        text
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "")
        .replace("\n", "")
    )


def strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].strip()
    return value


def bool_setting(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def int_setting(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(float(str(value).strip()))
    except Exception:
        number = default
    return max(minimum, min(maximum, number))


class NoSpeechRecorded(RuntimeError):
    pass


class TimingTrace:
    def __init__(self, enabled: bool, label: str):
        self.enabled = enabled
        self.label = label
        self.started_at = time.perf_counter()
        self.last_at = self.started_at
        self.items: list[str] = []

    def mark(self, name: str) -> None:
        if not self.enabled:
            return
        now_value = time.perf_counter()
        delta_ms = (now_value - self.last_at) * 1000
        total_ms = (now_value - self.started_at) * 1000
        self.items.append(f"{name}=+{delta_ms:.0f}ms/{total_ms:.0f}ms")
        self.last_at = now_value

    def add(self, name: str, value: str) -> None:
        if self.enabled:
            self.items.append(f"{name}={value}")

    def finish(self) -> None:
        if self.enabled and self.items:
            log(f"{self.label} timing: " + "; ".join(self.items))


def pcm_bytes_for_ms(milliseconds: int) -> int:
    byte_count = int((PCM_BYTES_PER_SECOND * max(0, milliseconds)) / 1000)
    return byte_count - (byte_count % PCM_SAMPLE_WIDTH)


def write_pcm_wav(raw_pcm: bytes, output_path: Path | None = None) -> Path:
    if not raw_pcm:
        raise NoSpeechRecorded("No speech detected.")
    if len(raw_pcm) % PCM_SAMPLE_WIDTH:
        raw_pcm = raw_pcm[:-(len(raw_pcm) % PCM_SAMPLE_WIDTH)]
    if not raw_pcm:
        raise NoSpeechRecorded("No speech detected.")

    path = output_path or temp_file_path(".wav")
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(PCM_CHANNELS)
        wav_file.setsampwidth(PCM_SAMPLE_WIDTH)
        wav_file.setframerate(PCM_SAMPLE_RATE)
        wav_file.writeframes(raw_pcm)
    return path


def pcm16_rms(raw_pcm: bytes) -> float:
    if len(raw_pcm) < PCM_SAMPLE_WIDTH:
        return 0.0
    if len(raw_pcm) % PCM_SAMPLE_WIDTH:
        raw_pcm = raw_pcm[:-(len(raw_pcm) % PCM_SAMPLE_WIDTH)]
    samples = memoryview(raw_pcm).cast("h")
    if not samples:
        return 0.0
    total = 0
    for sample in samples:
        value = int(sample)
        total += value * value
    return math.sqrt(total / len(samples))


def pcm16_peak(raw_pcm: bytes) -> int:
    if len(raw_pcm) < PCM_SAMPLE_WIDTH:
        return 0
    if len(raw_pcm) % PCM_SAMPLE_WIDTH:
        raw_pcm = raw_pcm[:-(len(raw_pcm) % PCM_SAMPLE_WIDTH)]
    samples = memoryview(raw_pcm).cast("h")
    if not samples:
        return 0
    return max(abs(int(sample)) for sample in samples)


def wav_audio_stats(audio_path: Path) -> dict[str, float]:
    with wave.open(str(audio_path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_rate = wav_file.getframerate()
        frames = wav_file.getnframes()
        raw_pcm = wav_file.readframes(frames)
    duration_ms = int((frames / frame_rate) * 1000) if frame_rate else 0
    stats: dict[str, float] = {
        "duration_ms": duration_ms,
        "channels": channels,
        "sample_width": sample_width,
        "frame_rate": frame_rate,
        "rms": 0.0,
        "peak": 0,
    }
    if channels == PCM_CHANNELS and sample_width == PCM_SAMPLE_WIDTH:
        stats["rms"] = round(pcm16_rms(raw_pcm), 1)
        stats["peak"] = pcm16_peak(raw_pcm)
    return stats


def trim_pcm_silence(raw_pcm: bytes, config: AppConfig) -> tuple[bytes, dict[str, int]]:
    if not bool_setting(config.trim_silence):
        return raw_pcm, {"trimmed_start_ms": 0, "trimmed_end_ms": 0}

    threshold = int_setting(config.silence_threshold, 450, 0, 32767)
    if threshold <= 0:
        return raw_pcm, {"trimmed_start_ms": 0, "trimmed_end_ms": 0}

    window_bytes = pcm_bytes_for_ms(20)
    padding_bytes = pcm_bytes_for_ms(int_setting(config.silence_padding_ms, 140, 0, 2000))
    min_audio_bytes = pcm_bytes_for_ms(int_setting(config.silence_min_audio_ms, 250, 0, 10000))
    if len(raw_pcm) % PCM_SAMPLE_WIDTH:
        raw_pcm = raw_pcm[:-(len(raw_pcm) % PCM_SAMPLE_WIDTH)]

    first_voice: int | None = None
    last_voice: int | None = None
    for start in range(0, len(raw_pcm), window_bytes):
        end = min(len(raw_pcm), start + window_bytes)
        if pcm16_rms(raw_pcm[start:end]) >= threshold:
            if first_voice is None:
                first_voice = start
            last_voice = end

    if first_voice is None or last_voice is None:
        raise NoSpeechRecorded("No speech detected.")

    trim_start = max(0, first_voice - padding_bytes)
    trim_end = min(len(raw_pcm), last_voice + padding_bytes)
    trimmed = raw_pcm[trim_start:trim_end]
    if len(trimmed) < min_audio_bytes:
        raise NoSpeechRecorded("No speech detected.")

    return trimmed, {
        "trimmed_start_ms": int((trim_start / PCM_BYTES_PER_SECOND) * 1000),
        "trimmed_end_ms": int(((len(raw_pcm) - trim_end) / PCM_BYTES_PER_SECOND) * 1000),
    }


def trim_wav_silence(audio_path: Path, config: AppConfig) -> tuple[Path, dict[str, int]]:
    if not bool_setting(config.trim_silence):
        return audio_path, {"trimmed_start_ms": 0, "trimmed_end_ms": 0}

    with wave.open(str(audio_path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_rate = wav_file.getframerate()
        raw_pcm = wav_file.readframes(wav_file.getnframes())

    if channels != PCM_CHANNELS or sample_width != PCM_SAMPLE_WIDTH or frame_rate != PCM_SAMPLE_RATE:
        return audio_path, {"trimmed_start_ms": 0, "trimmed_end_ms": 0}

    try:
        trimmed, metrics = trim_pcm_silence(raw_pcm, config)
    except NoSpeechRecorded:
        return audio_path, {"trimmed_start_ms": 0, "trimmed_end_ms": 0, "trim_skipped": 1}
    if len(trimmed) == len(raw_pcm):
        return audio_path, metrics

    trimmed_path = write_pcm_wav(trimmed)
    return trimmed_path, metrics


def mci_send(command: str) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    result = winmm.mciSendStringW(command, buffer, len(buffer), None)
    if result:
        error = ctypes.create_unicode_buffer(512)
        if winmm.mciGetErrorStringW(result, error, len(error)):
            detail = error.value
        else:
            detail = "unknown MCI error"
        raise RuntimeError(f"MCI command failed ({result}): {detail}")
    return buffer.value


def mci_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        return "waveaudio"
    return "mpegvideo"


def play_sound_file(path_text: str, wait: bool = False) -> bool:
    path = Path(os.path.expandvars(os.path.expanduser(path_text))).resolve()
    if not path.exists():
        raise RuntimeError(f"sound file not found: {path}")

    alias = f"flowzready{int(time.time() * 1000)}{random.randint(1000, 9999)}"
    media_type = mci_media_type(path)

    def worker() -> None:
        opened = False
        try:
            mci_send(f'open "{path}" type {media_type} alias {alias}')
            opened = True
            mci_send(f"play {alias} wait")
        except Exception as exc:
            log(f"Ready sound file failed: {exc}")
        finally:
            if opened:
                try:
                    mci_send(f"close {alias}")
                except Exception:
                    pass
                opened = False

    if wait:
        worker()
    else:
        threading.Thread(target=worker, name="ready-sound-file", daemon=True).start()
    return True


def play_ready_sound(config: AppConfig, wait: bool = False) -> bool:
    if not bool_setting(config.audio_ready_sound):
        return False

    frequency = int_setting(config.audio_ready_sound_frequency_hz, 880, 37, 32767)
    duration = int_setting(config.audio_ready_sound_duration_ms, 70, 10, 1000)
    backend = str(config.audio_ready_sound_backend).strip().lower()
    alias = str(config.audio_ready_sound_alias).strip() or "SystemAsterisk"
    try:
        sound_file = str(config.audio_ready_sound_file).strip()
        if sound_file and backend not in {"off", "none", "false", "0"}:
            return play_sound_file(sound_file, wait=wait)

        import winsound

        if backend in {"system", "alias"}:
            flags = winsound.SND_ALIAS
            if not wait:
                flags |= winsound.SND_ASYNC
            flags |= getattr(winsound, "SND_SYSTEM", 0)
            winsound.PlaySound(alias, flags)
            return True

        if backend in {"message", "messagebeep"}:
            winsound.MessageBeep()
            return True

        if backend in {"off", "none", "false", "0"}:
            return False

        winsound.Beep(frequency, duration)
        return True
    except Exception as exc:
        try:
            import winsound

            winsound.MessageBeep()
            return True
        except Exception:
            pass
        try:
            import winsound

            winsound.Beep(frequency, duration)
            return True
        except Exception as fallback_exc:
            log(f"Ready sound failed: {exc}; fallback failed: {fallback_exc}")
    return False


if ctypes.sizeof(ctypes.c_void_p) == 8:
    ULONG_PTR = ctypes.c_ulonglong
else:
    ULONG_PTR = ctypes.c_ulong


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


LRESULT = getattr(wintypes, "LRESULT", ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long)
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HCURSOR),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
    ]


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
winmm = ctypes.WinDLL("winmm", use_last_error=True)

LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    wintypes.LPARAM,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, LowLevelKeyboardProc, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = wintypes.LPARAM
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None
user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
user32.LoadIconW.restype = wintypes.HICON
user32.CreatePopupMenu.argtypes = []
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ULONG_PTR, wintypes.LPCWSTR]
user32.AppendMenuW.restype = wintypes.BOOL
user32.TrackPopupMenu.argtypes = [
    wintypes.HMENU,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.LPVOID,
]
user32.TrackPopupMenu.restype = wintypes.BOOL
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.DestroyMenu.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
kernel32.ReleaseMutex.restype = wintypes.BOOL
kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenEventW.restype = wintypes.HANDLE
kernel32.SetEvent.argtypes = [wintypes.HANDLE]
kernel32.SetEvent.restype = wintypes.BOOL
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL
winmm.mciSendStringW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.UINT, wintypes.HWND]
winmm.mciSendStringW.restype = wintypes.DWORD
winmm.mciGetErrorStringW.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.UINT]
winmm.mciGetErrorStringW.restype = wintypes.BOOL

if ctypes.sizeof(ctypes.c_void_p) == 8:
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_longlong
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
    user32.SetWindowLongPtrW.restype = ctypes.c_longlong

    def get_window_long_ptr(hwnd: int, index: int) -> int:
        return int(user32.GetWindowLongPtrW(hwnd, index))

    def set_window_long_ptr(hwnd: int, index: int, value: int) -> None:
        user32.SetWindowLongPtrW(hwnd, index, value)
else:
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long

    def get_window_long_ptr(hwnd: int, index: int) -> int:
        return int(user32.GetWindowLongW(hwnd, index))

    def set_window_long_ptr(hwnd: int, index: int, value: int) -> None:
        user32.SetWindowLongW(hwnd, index, value)


class SingleInstance:
    def __init__(self) -> None:
        self.handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.already_running = ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def close(self) -> None:
        if self.handle:
            if not self.already_running:
                kernel32.ReleaseMutex(self.handle)
            kernel32.CloseHandle(self.handle)
            self.handle = None


class StopWatcher:
    def __init__(self, target_thread_id: int):
        self.target_thread_id = target_thread_id
        self.handle = kernel32.CreateEventW(None, True, False, STOP_EVENT_NAME)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.thread = threading.Thread(target=self._wait, name="stop-watcher", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def _wait(self) -> None:
        handle = self.handle
        if not handle:
            return
        result = kernel32.WaitForSingleObject(handle, INFINITE)
        if result == WAIT_OBJECT_0:
            user32.PostThreadMessageW(self.target_thread_id, WM_QUIT, 0, 0)


def request_running_app_stop() -> bool:
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False, STOP_EVENT_NAME)
    if not handle:
        return False
    try:
        return bool(kernel32.SetEvent(handle))
    finally:
        kernel32.CloseHandle(handle)


class VisualIndicator:
    def __init__(self, config: AppConfig):
        self.enabled = bool_setting(config.visual_indicator)
        self.success_seconds = float(config.visual_indicator_success_seconds)
        self.events: queue.Queue[tuple[str, str, float | None]] = queue.Queue()
        self.thread: threading.Thread | None = None
        self.root = None
        self.canvas = None
        self.current_state = "idle"
        self.current_text = ""
        self.hide_after: float | None = None
        self.animation_tick = 0
        self.ready = threading.Event()

    def start(self) -> None:
        if not self.enabled or self.thread:
            return
        self.thread = threading.Thread(target=self._run, name="visual-indicator", daemon=True)
        self.thread.start()
        self.ready.wait(timeout=2.0)

    def stop(self) -> None:
        if not self.enabled:
            return
        self.events.put(("stop", "", None))

    def idle(self) -> None:
        self.show("idle", "", None)

    def starting(self) -> None:
        self.show("starting", "Starting", None)

    def recording(self) -> None:
        self.show("recording", "Recording", None)

    def transcribing(self) -> None:
        self.show("transcribing", "Transcribing", None)

    def success(self, text: str = "Pasted") -> None:
        self.show("success", text, self.success_seconds)

    def copied(self) -> None:
        self.show("success", "Copied", self.success_seconds)

    def paused(self) -> None:
        self.show("paused", "Paused", None)

    def empty(self) -> None:
        self.show("empty", "No speech", self.success_seconds)

    def error(self, text: str = "Error") -> None:
        self.show("error", text, 2.4)

    def hide(self) -> None:
        self.idle()

    def show(self, state: str, text: str, duration: float | None) -> None:
        if not self.enabled:
            return
        self.events.put((state, text, duration))

    def _run(self) -> None:
        try:
            import tkinter as tk
        except Exception as exc:
            log(f"Visual indicator disabled: tkinter unavailable ({exc})")
            self.enabled = False
            self.ready.set()
            return

        self.tk = tk
        root = tk.Tk()
        self.root = root
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.94)
        root.configure(bg=TRANSPARENT_COLOR)
        try:
            root.attributes("-transparentcolor", TRANSPARENT_COLOR)
        except Exception:
            pass

        width, height, x, y = self._layout_for_state("idle")
        root.geometry(f"{width}x{height}+{x}+{y}")

        canvas = tk.Canvas(
            root,
            width=width,
            height=height,
            bg=TRANSPARENT_COLOR,
            highlightthickness=0,
            bd=0,
        )
        canvas.pack(fill="both", expand=True)
        self.canvas = canvas

        root.update_idletasks()
        self._make_nonactivating(root.winfo_id())
        root.deiconify()
        self._render()
        self.ready.set()
        self._pump()
        root.mainloop()

    def _make_nonactivating(self, hwnd: int) -> None:
        try:
            style = get_window_long_ptr(hwnd, GWL_EXSTYLE)
            style |= WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT
            set_window_long_ptr(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def _pump(self) -> None:
        while True:
            try:
                state, text, duration = self.events.get_nowait()
            except queue.Empty:
                break

            if state == "stop":
                if self.root:
                    self.root.destroy()
                return

            self.current_state = state
            self.current_text = text
            self.animation_tick = 0
            if duration is None:
                self.hide_after = None
            else:
                self.hide_after = time.time() + duration

            if state == "hidden":
                self.current_state = "idle"
                self.hide_after = None
                if self.root:
                    self.root.deiconify()
                    self._render()
            else:
                if self.root:
                    self.root.deiconify()
                self._render()

        if self.hide_after is not None and time.time() >= self.hide_after:
            self.current_state = "idle"
            self.current_text = ""
            self.hide_after = None
            self._render()
        else:
            self._render()

        if self.root:
            self.root.after(120, self._pump)

    def _render(self) -> None:
        if not self.canvas:
            return

        canvas = self.canvas
        canvas.delete("all")
        state = self.current_state
        self._apply_layout(state)
        width = int(canvas["width"])
        height = int(canvas["height"])
        self.animation_tick += 1

        palette = {
            "idle": ("#101214", "#36d17f", "#ffffff", "#8ca39a"),
            "starting": ("#121316", "#d7a84f", "#ffffff", "#f1d391"),
            "recording": ("#121316", "#ff4d5e", "#ffffff", "#ffb3bb"),
            "transcribing": ("#121316", "#6aa7ff", "#ffffff", "#b9d6ff"),
            "success": ("#101411", "#36d17f", "#ffffff", "#a9f0c7"),
            "paused": ("#141311", "#d7a84f", "#ffffff", "#f1d391"),
            "empty": ("#141311", "#d7a84f", "#ffffff", "#f1d391"),
            "error": ("#171112", "#ff5f6f", "#ffffff", "#ffb3bb"),
        }
        bg, accent, fg, muted = palette.get(state, palette["idle"])

        if state == "idle":
            pulse = 12 + (self.animation_tick % 10) * 0.25
            cx = width // 2
            cy = height // 2
            canvas.create_oval(3, 3, width - 3, height - 3, fill=bg, outline="#2b2d33", width=1)
            canvas.create_oval(cx - pulse, cy - pulse, cx + pulse, cy + pulse, fill="", outline="#1f3a2c", width=1)
            for i, bar_h in enumerate([7, 13, 18, 11, 6]):
                x = cx - 10 + i * 5
                y1 = cy - bar_h / 2
                y2 = cy + bar_h / 2
                color = accent if i == 2 else "#8ff0b8"
                canvas.create_line(x, y1, x, y2, fill=color, width=2, capstyle="round")
            canvas.create_oval(width - 12, 8, width - 7, 13, fill=accent, outline=accent)
            return

        self._rounded_rect(2, 2, width - 2, height - 2, 18, fill=bg, outline="#2b2d33")
        self._rounded_rect(3, 3, width - 3, height - 3, 17, fill="", outline="#202228")

        cx = 28
        cy = height // 2
        if state == "starting":
            dots = (self.animation_tick % 8) + 1
            for i in range(8):
                angle = (i / 8) * 6.28318
                color = accent if i < dots else "#5d4a23"
                x = cx + 8 * math.cos(angle)
                y = cy + 8 * math.sin(angle)
                canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=color, outline=color)
            sub = "opening mic"
        elif state == "recording":
            pulse = 5 + (self.animation_tick % 6)
            canvas.create_oval(cx - pulse, cy - pulse, cx + pulse, cy + pulse, fill="", outline=accent, width=2)
            canvas.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill=accent, outline=accent)
            sub = "release to paste"
        elif state == "transcribing":
            dots = (self.animation_tick % 8) + 1
            for i in range(8):
                angle = (i / 8) * 6.28318
                alpha_index = (i - dots) % 8
                color = accent if alpha_index < 3 else "#33506e"
                x = cx + 8 * math.cos(angle)
                y = cy + 8 * math.sin(angle)
                canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=color, outline=color)
            sub = "cleaning audio"
        elif state == "success":
            canvas.create_line(cx - 8, cy, cx - 2, cy + 6, cx + 9, cy - 7, fill=accent, width=3, capstyle="round", joinstyle="round")
            sub = "ready"
        elif state == "paused":
            canvas.create_line(cx - 5, cy - 8, cx - 5, cy + 8, fill=accent, width=3, capstyle="round")
            canvas.create_line(cx + 5, cy - 8, cx + 5, cy + 8, fill=accent, width=3, capstyle="round")
            sub = "dictation off"
        elif state == "empty":
            canvas.create_line(cx - 8, cy, cx + 8, cy, fill=accent, width=3, capstyle="round")
            sub = "ready"
        else:
            canvas.create_line(cx - 7, cy - 7, cx + 7, cy + 7, fill=accent, width=3, capstyle="round")
            canvas.create_line(cx + 7, cy - 7, cx - 7, cy + 7, fill=accent, width=3, capstyle="round")
            sub = "check terminal"

        canvas.create_text(50, 17, text=self.current_text, fill=fg, anchor="w", font=("Segoe UI", 10, "bold"))
        canvas.create_text(50, 32, text=sub, fill=muted, anchor="w", font=("Segoe UI", 8))

    def _layout_for_state(self, state: str) -> tuple[int, int, int, int]:
        if self.root:
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
        else:
            screen_width = 1920
            screen_height = 1080

        if state == "idle":
            width = 44
            height = 44
            x = max(0, screen_width - width - 22)
            y = max(0, screen_height - height - 78)
            return width, height, x, y

        width = 246
        height = 48
        x = max(0, (screen_width - width) // 2)
        y = 42
        return width, height, x, y

    def _apply_layout(self, state: str) -> None:
        if not self.root or not self.canvas:
            return
        width, height, x, y = self._layout_for_state(state)
        current_width = int(self.canvas["width"])
        current_height = int(self.canvas["height"])
        if current_width != width or current_height != height:
            self.canvas.configure(width=width, height=height)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _rounded_rect(self, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs) -> None:
        if not self.canvas:
            return
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]
        self.canvas.create_polygon(points, smooth=True, splinesteps=20, **kwargs)


class KeyboardHook:
    def __init__(self, on_start: Callable[[], None], on_stop: Callable[[], None]):
        self.on_start = on_start
        self.on_stop = on_stop
        self.ctrl_down = False
        self.win_down = False
        self.combo_down = False
        self.suppress_until_win_up = False
        self.hook_id: wintypes.HHOOK | None = None
        self._lock = threading.Lock()
        self._callback = LowLevelKeyboardProc(self._proc)

    def install(self) -> None:
        module = kernel32.GetModuleHandleW(None)
        hook_id = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._callback, module, 0)
        if not hook_id:
            raise ctypes.WinError(ctypes.get_last_error())
        self.hook_id = hook_id

    def uninstall(self) -> None:
        if self.hook_id:
            user32.UnhookWindowsHookEx(self.hook_id)
            self.hook_id = None

    def modifiers_down(self) -> bool:
        with self._lock:
            return self.ctrl_down or self.win_down

    def wait_for_release(self, timeout_seconds: float = 3.0) -> None:
        deadline = time.time() + timeout_seconds
        while self.modifiers_down() and time.time() < deadline:
            time.sleep(0.02)

    def _proc(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code < 0:
            return user32.CallNextHookEx(self.hook_id, n_code, w_param, l_param)

        event = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        vk = int(event.vkCode)
        is_down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
        is_up = w_param in (WM_KEYUP, WM_SYSKEYUP)
        suppress = False
        should_start = False
        should_stop = False

        if is_down or is_up:
            with self._lock:
                previous_combo = self.combo_down

                if vk in CTRL_KEYS:
                    self.ctrl_down = is_down
                elif vk in WIN_KEYS:
                    self.win_down = is_down

                current_combo = self.ctrl_down and self.win_down
                self.combo_down = current_combo

                if not previous_combo and current_combo:
                    self.suppress_until_win_up = True
                    should_start = True
                elif previous_combo and not current_combo:
                    should_stop = True

                if vk in CTRL_KEYS or vk in WIN_KEYS:
                    if previous_combo or current_combo or self.suppress_until_win_up:
                        suppress = True

                if vk in WIN_KEYS and is_up:
                    self.suppress_until_win_up = False

        if should_start:
            self.on_start()
        if should_stop:
            self.on_stop()

        if suppress:
            return 1
        return user32.CallNextHookEx(self.hook_id, n_code, w_param, l_param)


class Clipboard:
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardSequenceNumber.argtypes = []
    user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL

    @staticmethod
    def get_text() -> str | None:
        if not user32.OpenClipboard(None):
            return None
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                return None
            try:
                return ctypes.wstring_at(pointer)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    @staticmethod
    def sequence_number() -> int:
        return int(user32.GetClipboardSequenceNumber())

    @staticmethod
    def set_text(text: str) -> None:
        data = (text + "\0").encode("utf-16le")
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            raise ctypes.WinError(ctypes.get_last_error())
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)

        for _ in range(20):
            if user32.OpenClipboard(None):
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("Could not open the clipboard.")

        try:
            if not user32.EmptyClipboard():
                raise ctypes.WinError(ctypes.get_last_error())
            if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                raise ctypes.WinError(ctypes.get_last_error())
            handle = None
        finally:
            user32.CloseClipboard()


def make_key_input(vk: int, flags: int = 0) -> INPUT:
    item = INPUT()
    item.type = INPUT_KEYBOARD
    item.union.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    return item


def send_ctrl_v() -> None:
    events = (INPUT * 4)(
        make_key_input(VK_CONTROL, 0),
        make_key_input(VK_V, 0),
        make_key_input(VK_V, KEYEVENTF_KEYUP),
        make_key_input(VK_CONTROL, KEYEVENTF_KEYUP),
    )
    sent = user32.SendInput(len(events), events, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise ctypes.WinError(ctypes.get_last_error())


class FreeFlowController:
    def __init__(self, config: AppConfig, indicator: VisualIndicator):
        self.config = config
        self.indicator = indicator
        self.recorder = create_recorder(config)
        self.client = OpenAICompatibleClient(config)
        self.starting = False
        self.recording = False
        self.transcribing = False
        self.paused = False
        self.stop_requested = False
        self.recording_requested_at: float | None = None
        self.hook: KeyboardHook | None = None
        self._lock = threading.Lock()

    def attach_hook(self, hook: KeyboardHook) -> None:
        self.hook = hook

    def close(self) -> None:
        close = getattr(self.recorder, "close", None)
        if callable(close):
            close()

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self.paused = paused
        if paused:
            self.indicator.paused()
            log("Dictation paused.")
            self.release_warm_capture()
        else:
            self.indicator.success("Ready")
            log("Dictation resumed.")

    def toggle_paused(self) -> bool:
        with self._lock:
            paused = not self.paused
        self.set_paused(paused)
        return paused

    def release_warm_capture(self) -> None:
        release = getattr(self.recorder, "release_idle_capture", None)
        if callable(release):
            release()
        else:
            log("Warm capture is not active in the current recorder mode.")

    def start_recording(self) -> None:
        with self._lock:
            if self.paused or self.starting or self.recording or self.transcribing:
                return
            self.starting = True
            self.stop_requested = False
            self.recording_requested_at = time.perf_counter()
        self.indicator.starting()
        thread = threading.Thread(target=self._start_recording_worker, name="record-start", daemon=True)
        thread.start()

    def _start_recording_worker(self) -> None:
        clear_recorded_audio = getattr(self.recorder, "clear_recorded_audio", None)
        can_clear_recorded_audio = callable(clear_recorded_audio)
        try:
            if not can_clear_recorded_audio:
                self.indicator.recording()
                play_ready_sound(self.config, wait=True)
            log("Ctrl+Win down: opening microphone...")
            ffmpeg_start_ms = self.recorder.start()
        except Exception as exc:
            with self._lock:
                self.starting = False
                self.recording = False
                self.stop_requested = False
                self.recording_requested_at = None
            self.indicator.error("Mic error")
            log(f"Could not start recording: {exc}")
            return

        if can_clear_recorded_audio:
            self.indicator.recording()
            played_ready_sound = play_ready_sound(self.config, wait=True)
        else:
            played_ready_sound = False

        if played_ready_sound and can_clear_recorded_audio:
            clear_recorded_audio("ready sound")

        should_stop = False
        requested_at: float | None = None
        with self._lock:
            self.starting = False
            self.recording = True
            requested_at = self.recording_requested_at
            self.recording_requested_at = None
            if self.stop_requested:
                self.stop_requested = False
                should_stop = True

        if requested_at is not None:
            total_ready_ms = (time.perf_counter() - requested_at) * 1000
            log(f"Recording ready after {total_ready_ms:.0f} ms from hotkey ({ffmpeg_start_ms:.0f} ms ffmpeg start check).")

        if should_stop:
            self.stop_recording()
            return

    def stop_recording(self) -> None:
        with self._lock:
            if self.starting:
                self.stop_requested = True
                return
            if not self.recording:
                return
            self.recording = False
            self.transcribing = True
        self.indicator.transcribing()
        thread = threading.Thread(target=self._stop_and_transcribe, name="transcribe", daemon=True)
        thread.start()

    def _stop_and_transcribe(self) -> None:
        audio_path: Path | None = None
        trimmed_path: Path | None = None
        metrics = TimingTrace(bool_setting(self.config.log_timing_metrics), "Dictation")
        try:
            log("Ctrl+Win released: preparing audio...")
            audio_path = self.recorder.stop()
            metrics.mark("audio_stop")
            try:
                raw_stats = wav_audio_stats(audio_path)
                log(
                    "Recorded audio: "
                    f"{raw_stats['duration_ms']:.0f} ms, "
                    f"rms={raw_stats['rms']}, peak={raw_stats['peak']}."
                )
            except Exception as exc:
                log(f"Could not inspect recorded audio: {exc}")
            trimmed_path, trim_metrics = trim_wav_silence(audio_path, self.config)
            metrics.mark("silence_trim")
            if trim_metrics.get("trim_skipped"):
                log("Silence trim skipped; sending original audio to avoid losing quiet speech.")
            if trim_metrics["trimmed_start_ms"] or trim_metrics["trimmed_end_ms"]:
                metrics.add(
                    "trimmed",
                    f"{trim_metrics['trimmed_start_ms']}ms_start/{trim_metrics['trimmed_end_ms']}ms_end",
                )
                log(
                    "Audio silence trimmed: "
                    f"start={trim_metrics['trimmed_start_ms']} ms, end={trim_metrics['trimmed_end_ms']} ms."
                )
            log("Transcribing...")
            transcript = self.client.transcribe(trimmed_path).strip()
            metrics.mark("transcribe")
            if transcript:
                try:
                    transcript = self.client.clean(transcript).strip()
                    metrics.mark("post_process")
                except Exception as exc:
                    log(f"Cleanup failed, using raw transcript: {exc}")

            if not transcript:
                log("No speech detected.")
                self.indicator.empty()
                return

            if self.config.append_space_after_sentence and transcript[-1:] in ".!?":
                transcript_to_paste = transcript + " "
            else:
                transcript_to_paste = transcript

            log(f"Transcript: {transcript}")
            if self.config.paste_result:
                self._paste(transcript_to_paste)
                metrics.mark("paste")
                self.indicator.success("Pasted")
                log("Pasted.")
            else:
                Clipboard.set_text(transcript_to_paste)
                metrics.mark("clipboard")
                self.indicator.copied()
                log("Copied to clipboard.")
        except NoSpeechRecorded:
            self.indicator.empty()
            log("No speech detected.")
        except Exception as exc:
            self.indicator.error("Error")
            log(f"Error: {exc}")
            debug_path = app_config_dir() / "last-error.txt"
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            debug_path.write_text(traceback.format_exc(), encoding="utf-8")
            log(f"Details written to {debug_path}")
        finally:
            if trimmed_path and trimmed_path != audio_path:
                try:
                    trimmed_path.unlink(missing_ok=True)
                except Exception:
                    pass
            if audio_path:
                try:
                    audio_path.unlink(missing_ok=True)
                except Exception:
                    pass
            with self._lock:
                self.transcribing = False
            metrics.finish()

    def _paste(self, text: str) -> None:
        previous_text = Clipboard.get_text() if self.config.preserve_text_clipboard else None
        Clipboard.set_text(text)
        seq_after_set = Clipboard.sequence_number()
        if self.hook:
            self.hook.wait_for_release()
        time.sleep(0.08)
        send_ctrl_v()
        if previous_text is not None:
            def restore() -> None:
                time.sleep(1.0)
                if Clipboard.sequence_number() == seq_after_set:
                    try:
                        Clipboard.set_text(previous_text)
                    except Exception:
                        pass

            threading.Thread(target=restore, name="clipboard-restore", daemon=True).start()


class TrayIcon:
    def __init__(self, controller: FreeFlowController):
        self.controller = controller
        self.hwnd: wintypes.HWND | None = None
        self.hicon: wintypes.HICON | None = None
        self.class_name = f"{APP_NAME}TrayWindow"
        self._wndproc = WNDPROC(self._window_proc)

    def install(self) -> None:
        instance = kernel32.GetModuleHandleW(None)
        window_class = WNDCLASSW()
        window_class.lpfnWndProc = self._wndproc
        window_class.hInstance = instance
        window_class.lpszClassName = self.class_name
        atom = user32.RegisterClassW(ctypes.byref(window_class))
        if not atom and ctypes.get_last_error() != ERROR_CLASS_ALREADY_EXISTS:
            raise ctypes.WinError(ctypes.get_last_error())

        hwnd = user32.CreateWindowExW(
            0,
            self.class_name,
            APP_NAME,
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            instance,
            None,
        )
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

        self.hwnd = hwnd
        self.hicon = user32.LoadIconW(None, ctypes.cast(ctypes.c_void_p(IDI_APPLICATION), wintypes.LPCWSTR))
        self._notify(NIM_ADD)
        log("Tray icon installed.")

    def uninstall(self) -> None:
        if self.hwnd:
            try:
                self._notify(NIM_DELETE)
            except Exception:
                pass
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None

    def _notify(self, message: int) -> None:
        if not self.hwnd:
            return
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self.hwnd
        data.uID = TRAY_UID
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = WM_TRAYICON
        data.hIcon = self.hicon
        data.szTip = APP_NAME
        if not shell32.Shell_NotifyIconW(message, ctypes.byref(data)):
            raise ctypes.WinError(ctypes.get_last_error())

    def _window_proc(self, hwnd: wintypes.HWND, msg: int, w_param: int, l_param: int) -> int:
        if msg == WM_TRAYICON:
            if l_param in (WM_RBUTTONUP, WM_LBUTTONDBLCLK):
                self._show_menu()
                return 0
        elif msg == WM_COMMAND:
            command_id = int(w_param) & 0xFFFF
            self._handle_command(command_id)
            return 0
        elif msg == WM_DESTROY:
            return 0
        return user32.DefWindowProcW(hwnd, msg, w_param, l_param)

    def _show_menu(self) -> None:
        if not self.hwnd:
            return
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            pause_text = "Resume Dictation" if self.controller.paused else "Pause Dictation"
            user32.AppendMenuW(menu, MF_STRING, TRAY_MENU_SETTINGS, "Settings")
            user32.AppendMenuW(menu, MF_STRING, TRAY_MENU_TOGGLE_PAUSE, pause_text)
            user32.AppendMenuW(menu, MF_STRING, TRAY_MENU_RELEASE_CAPTURE, "Release Warm Capture")
            user32.AppendMenuW(menu, MF_STRING, TRAY_MENU_OPEN_CONFIG, "Open Config Folder")
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, TRAY_MENU_EXIT, "Exit")

            point = wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(point)):
                return
            user32.SetForegroundWindow(self.hwnd)
            user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON, point.x, point.y, 0, self.hwnd, None)
        finally:
            user32.DestroyMenu(menu)

    def _handle_command(self, command_id: int) -> None:
        if command_id == TRAY_MENU_SETTINGS:
            launch_settings_window()
        elif command_id == TRAY_MENU_TOGGLE_PAUSE:
            self.controller.toggle_paused()
        elif command_id == TRAY_MENU_RELEASE_CAPTURE:
            self.controller.release_warm_capture()
        elif command_id == TRAY_MENU_OPEN_CONFIG:
            app_config_dir().mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["explorer.exe", str(app_config_dir())], creationflags=CREATE_NO_WINDOW)
        elif command_id == TRAY_MENU_EXIT:
            user32.PostQuitMessage(0)


def run_app(config: AppConfig) -> None:
    instance = SingleInstance()
    if instance.already_running:
        log("Flowz is already running.")
        instance.close()
        return

    stop_watcher: StopWatcher | None = None
    tray_icon: TrayIcon | None = None
    indicator = VisualIndicator(config)
    indicator.start()
    controller = FreeFlowController(config, indicator)
    try:
        device = controller.recorder.warm_up_device()
        log(f"Using microphone: {device}")
    except Exception as exc:
        log(f"Microphone check failed: {exc}")
        log("The app will still start; recording will retry when you press Ctrl+Win.")
    else:
        if bool_setting(config.ffmpeg_prime_on_startup):
            try:
                log("Priming microphone capture...")
                prime_ms = controller.recorder.prime()
                log(f"Microphone capture primed ({prime_ms:.0f} ms).")
            except Exception as exc:
                log(f"Microphone prime failed: {exc}")
                log("The first recording may be slower, but the app will keep running.")

    hook = KeyboardHook(controller.start_recording, controller.stop_recording)
    controller.attach_hook(hook)
    hook.install()
    try:
        kernel32.SetConsoleTitleW(f"{APP_NAME} - hold Ctrl+Win to dictate")
    except Exception:
        pass

    stop_watcher = StopWatcher(int(kernel32.GetCurrentThreadId()))
    stop_watcher.start()
    if bool_setting(config.tray_icon):
        try:
            tray_icon = TrayIcon(controller)
            tray_icon.install()
        except Exception as exc:
            tray_icon = None
            log(f"Tray icon disabled: {exc}")

    log("Running. Hold Ctrl + Windows to dictate, release to transcribe and paste.")
    log(f"Config: {config_path()}")
    log("Press Ctrl+C in this console to quit.")

    msg = wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    except KeyboardInterrupt:
        log("Exiting...")
    finally:
        hook.uninstall()
        if tray_icon:
            tray_icon.uninstall()
        indicator.stop()
        controller.close()
        if stop_watcher:
            stop_watcher.close()
        instance.close()


def setup_config(config: AppConfig) -> None:
    print(f"Config path: {config_path()}")
    api_key = getpass.getpass("API key (blank to keep current/env): ").strip()
    if api_key:
        config.api_key = api_key

    print(f"Base URL [{config.base_url}]: ", end="")
    base_url = input().strip()
    if base_url:
        config.base_url = base_url

    print(f"Transcription model [{config.transcription_model}]: ", end="")
    model = input().strip()
    if model:
        config.transcription_model = model

    devices = list_audio_devices(config.ffmpeg_path)
    if devices:
        print()
        print("Audio devices:")
        for index, name in enumerate(devices, 1):
            print(f"  {index}. {name}")
        print("Choose device number, or blank for auto/first device: ", end="")
        choice = input().strip()
        if choice:
            selected = devices[int(choice) - 1]
            config.ffmpeg_device = selected
    else:
        print("No audio devices found by ffmpeg.")

    config.save()
    log(f"Saved config to {config_path()}")


def show_settings_gui(config: AppConfig) -> None:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception as exc:
        raise RuntimeError("Tkinter is required for the settings GUI.") from exc

    root = tk.Tk()
    root.title(f"{APP_NAME} Settings")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frame = ttk.Frame(root, padding=14)
    frame.grid(row=0, column=0, sticky="nsew")

    fields: dict[str, tk.Variable] = {}

    def add_header(row: int, text: str) -> int:
        label = ttk.Label(frame, text=text, font=("Segoe UI", 10, "bold"))
        label.grid(row=row, column=0, columnspan=3, sticky="w", pady=(10 if row else 0, 6))
        return row + 1

    def add_entry(row: int, label_text: str, key: str, width: int = 52, show: str = "") -> int:
        ttk.Label(frame, text=label_text).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
        var = tk.StringVar(value=str(getattr(config, key)))
        entry = ttk.Entry(frame, textvariable=var, width=width, show=show)
        entry.grid(row=row, column=1, columnspan=2, sticky="we", pady=3)
        fields[key] = var
        return row + 1

    def add_int(row: int, label_text: str, key: str, width: int = 12) -> int:
        ttk.Label(frame, text=label_text).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
        var = tk.StringVar(value=str(getattr(config, key)))
        entry = ttk.Entry(frame, textvariable=var, width=width)
        entry.grid(row=row, column=1, sticky="w", pady=3)
        fields[key] = var
        return row + 1

    def add_check(row: int, label_text: str, key: str) -> int:
        var = tk.BooleanVar(value=bool_setting(getattr(config, key)))
        checkbox = ttk.Checkbutton(frame, text=label_text, variable=var)
        checkbox.grid(row=row, column=0, columnspan=3, sticky="w", pady=3)
        fields[key] = var
        return row + 1

    row = 0
    row = add_header(row, "Provider")
    row = add_entry(row, "API key", "api_key", show="*")
    row = add_entry(row, "Base URL", "base_url")
    row = add_entry(row, "Transcription model", "transcription_model")
    row = add_entry(row, "Language", "language", width=18)

    row = add_header(row, "Microphone")
    ttk.Label(frame, text="Device").grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
    device_var = tk.StringVar(value=str(config.ffmpeg_device))
    devices: list[str] = []
    try:
        devices = list_audio_devices(config.ffmpeg_path)
    except Exception as exc:
        log(f"Could not list devices for settings GUI: {exc}")
    if config.ffmpeg_device and config.ffmpeg_device not in devices:
        devices.insert(0, config.ffmpeg_device)
    device_combo = ttk.Combobox(frame, textvariable=device_var, values=devices, width=50)
    device_combo.grid(row=row, column=1, columnspan=2, sticky="we", pady=3)
    fields["ffmpeg_device"] = device_var
    row += 1
    row = add_entry(row, "ffmpeg path", "ffmpeg_path")
    row = add_check(row, "Low-latency capture", "low_latency_capture")
    row = add_int(row, "Idle timeout seconds", "low_latency_idle_timeout_seconds")
    row = add_int(row, "Pre-roll ms", "low_latency_preroll_ms")

    row = add_header(row, "Audio")
    row = add_check(row, "Ready sound", "audio_ready_sound")
    ttk.Label(frame, text="Sound file").grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
    sound_file_var = tk.StringVar(value=str(config.audio_ready_sound_file))
    fields["audio_ready_sound_file"] = sound_file_var
    ttk.Entry(frame, textvariable=sound_file_var, width=52).grid(row=row, column=1, sticky="we", pady=3)

    def browse_sound() -> None:
        selected = filedialog.askopenfilename(
            title="Choose ready sound",
            filetypes=[("Audio files", "*.mp3 *.wav"), ("All files", "*.*")],
        )
        if selected:
            sound_file_var.set(selected)

    ttk.Button(frame, text="Browse", command=browse_sound).grid(row=row, column=2, sticky="e", padx=(8, 0), pady=3)
    row += 1
    row = add_entry(row, "Sound backend", "audio_ready_sound_backend", width=18)
    row = add_entry(row, "Windows sound alias", "audio_ready_sound_alias", width=24)
    row = add_int(row, "Tone frequency Hz", "audio_ready_sound_frequency_hz")
    row = add_int(row, "Tone duration ms", "audio_ready_sound_duration_ms")

    row = add_header(row, "Transcription")
    row = add_check(row, "Trim silence", "trim_silence")
    row = add_int(row, "Silence threshold", "silence_threshold")
    row = add_int(row, "Silence padding ms", "silence_padding_ms")
    row = add_check(row, "Post-process text", "post_process")
    row = add_check(row, "Paste result automatically", "paste_result")
    row = add_check(row, "Preserve clipboard text", "preserve_text_clipboard")

    row = add_header(row, "App")
    row = add_check(row, "Visual indicator", "visual_indicator")
    row = add_check(row, "Tray icon", "tray_icon")
    row = add_check(row, "Log timing metrics", "log_timing_metrics")
    startup_var = tk.BooleanVar(value=is_startup_enabled())
    ttk.Checkbutton(frame, text="Start with Windows", variable=startup_var).grid(
        row=row, column=0, columnspan=3, sticky="w", pady=3
    )
    row += 1

    def apply_form() -> None:
        string_keys = {
            "api_key",
            "base_url",
            "transcription_model",
            "language",
            "ffmpeg_path",
            "ffmpeg_device",
            "audio_ready_sound_file",
            "audio_ready_sound_backend",
            "audio_ready_sound_alias",
        }
        bool_keys = {
            "low_latency_capture",
            "audio_ready_sound",
            "trim_silence",
            "post_process",
            "paste_result",
            "preserve_text_clipboard",
            "visual_indicator",
            "tray_icon",
            "log_timing_metrics",
        }
        int_keys = {
            "low_latency_idle_timeout_seconds",
            "low_latency_preroll_ms",
            "audio_ready_sound_frequency_hz",
            "audio_ready_sound_duration_ms",
            "silence_threshold",
            "silence_padding_ms",
        }
        for key in string_keys:
            setattr(config, key, str(fields[key].get()).strip())
        for key in bool_keys:
            setattr(config, key, bool(fields[key].get()))
        for key in int_keys:
            default = int(getattr(AppConfig(), key))
            setattr(config, key, int_setting(fields[key].get(), default, 0, 100000))

    def save() -> None:
        try:
            apply_form()
            config.save()
            set_startup_enabled(bool(startup_var.get()))
            messagebox.showinfo(APP_NAME, f"Settings saved to {config_path()}")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not save settings: {exc}")

    def save_and_close() -> None:
        save()
        root.destroy()

    def test_ready_sound() -> None:
        try:
            apply_form()
            play_ready_sound(config)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not play sound: {exc}")

    buttons = ttk.Frame(frame)
    buttons.grid(row=row, column=0, columnspan=3, sticky="e", pady=(14, 0))
    ttk.Button(buttons, text="Test sound", command=test_ready_sound).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(buttons, text="Save", command=save).grid(row=0, column=1, padx=(0, 8))
    ttk.Button(buttons, text="Save and close", command=save_and_close).grid(row=0, column=2, padx=(0, 8))
    ttk.Button(buttons, text="Cancel", command=root.destroy).grid(row=0, column=3)

    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.mainloop()


def test_record(config: AppConfig, seconds: float) -> None:
    recorder = create_recorder(config)
    output: Path | None = None
    trimmed_output: Path | None = None
    log(f"Recording a local microphone test for {seconds:.1f}s...")
    try:
        recorder.start()
        time.sleep(max(0.1, seconds))
        output = recorder.stop()
        log(f"Recorded {output} ({output.stat().st_size} bytes)")
        try:
            stats = wav_audio_stats(output)
            log(
                "Recorded audio: "
                f"{stats['duration_ms']:.0f} ms, rms={stats['rms']}, peak={stats['peak']}."
            )
        except Exception as exc:
            log(f"Could not inspect recorded audio: {exc}")
        trimmed_output, trim_metrics = trim_wav_silence(output, config)
        if trim_metrics.get("trim_skipped"):
            log("Silence trim would be skipped; original audio would be sent.")
        elif trim_metrics["trimmed_start_ms"] or trim_metrics["trimmed_end_ms"]:
            log(
                "Silence trim would remove "
                f"{trim_metrics['trimmed_start_ms']} ms from start and "
                f"{trim_metrics['trimmed_end_ms']} ms from end."
            )
            if trimmed_output != output:
                log(f"Trimmed test audio: {trimmed_output} ({trimmed_output.stat().st_size} bytes)")
        else:
            log("Silence trim would keep the full audio.")
        log("Delete this file after checking it if you do not need it.")
    finally:
        close = getattr(recorder, "close", None)
        if callable(close):
            close()


def test_api(config: AppConfig) -> None:
    ensure_config(config)
    log("Testing provider API with configured transport...")
    OpenAICompatibleClient(config).test_api()
    log("Provider API test passed.")


def test_paste() -> None:
    text = f"Flowz paste test {time.strftime('%H:%M:%S')}"
    log("Testing clipboard + Ctrl+V. Focus a text field now; pasting in 3 seconds...")
    time.sleep(3)
    Clipboard.set_text(text)
    send_ctrl_v()
    log(f"Paste test sent: {text}")


def test_sound(config: AppConfig) -> None:
    log("Testing ready sound...")
    play_ready_sound(config)
    if str(config.audio_ready_sound_file).strip():
        time.sleep(2.5)
    else:
        duration = int_setting(config.audio_ready_sound_duration_ms, 70, 10, 1000)
        time.sleep(max(0.4, (duration / 1000) + 0.2))
    log("Ready sound test sent.")


def test_overlay(config: AppConfig) -> None:
    indicator = VisualIndicator(config)
    indicator.start()
    try:
        log("Showing overlay state: Starting")
        indicator.starting()
        time.sleep(1.2)
        log("Showing overlay state: Recording")
        indicator.recording()
        time.sleep(1.5)
        log("Showing overlay state: Transcribing")
        indicator.transcribing()
        time.sleep(1.5)
        log("Showing overlay state: Pasted")
        indicator.success("Pasted")
        time.sleep(1.5)
        log("Showing overlay state: Paused")
        indicator.paused()
        time.sleep(1.5)
        log("Showing overlay state: Error")
        indicator.error("Error")
        time.sleep(2.0)
    finally:
        indicator.stop()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Flowz")
    parser.add_argument("--setup", action="store_true", help="Prompt for API key and microphone settings.")
    parser.add_argument("--settings", action="store_true", help="Open the graphical settings window.")
    parser.add_argument("--list-devices", action="store_true", help="List ffmpeg DirectShow audio input devices.")
    parser.add_argument("--config-path", action="store_true", help="Print config path and exit.")
    parser.add_argument("--test-record", type=float, metavar="SECONDS", help="Record a local WAV test without calling the API.")
    parser.add_argument("--test-api", action="store_true", help="Validate provider auth/connectivity without recording.")
    parser.add_argument("--test-paste", action="store_true", help="Copy a test string and send Ctrl+V after 3 seconds.")
    parser.add_argument("--test-sound", action="store_true", help="Play the ready sound once.")
    parser.add_argument("--test-overlay", action="store_true", help="Show the visual indicator states without recording.")
    parser.add_argument("--stop", action="store_true", help="Ask a background Flowz instance to quit.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    config = AppConfig.load()

    if args.config_path:
        print(config_path())
        return 0

    if args.stop:
        stopped = request_running_app_stop()
        if stopped:
            log("Stop signal sent.")
            return 0
        log("No running Flowz instance found.")
        return 1

    if args.list_devices:
        devices = list_audio_devices(config.ffmpeg_path)
        if not devices:
            print("No audio devices found.")
            return 1
        for device in devices:
            print(device)
        return 0

    if args.setup:
        setup_config(config)
        return 0

    if args.settings:
        show_settings_gui(config)
        return 0

    if args.test_record is not None:
        test_record(config, args.test_record)
        return 0

    if args.test_api:
        test_api(config)
        return 0

    if args.test_paste:
        test_paste()
        return 0

    if args.test_sound:
        test_sound(config)
        return 0

    if args.test_overlay:
        test_overlay(config)
        return 0

    config = ensure_config(config)
    run_app(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
