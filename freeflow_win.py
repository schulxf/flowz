#!/usr/bin/env python3
"""
FreeFlow Windows MVP.

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
from ctypes import wintypes
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable


APP_NAME = "FreeFlowWin"
APP_DIR_NAME = "FreeFlowWin"
CONFIG_FILE_NAME = "config.json"
LOG_FILE_NAME = "freeflow.log"
TRANSPARENT_COLOR = "#010203"

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

WH_KEYBOARD_LL = 13
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
INFINITE = 0xFFFFFFFF
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
MUTEX_NAME = "Local\\FreeFlowWinSingleInstance"
STOP_EVENT_NAME = "Local\\FreeFlowWinStop"


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


def config_path() -> Path:
    return app_config_dir() / CONFIG_FILE_NAME


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
        raise RuntimeError("API key is required. Run FreeFlowWin.bat --setup first.") from exc

    result = {"value": ""}
    root = tk.Tk()
    root.title("FreeFlowWin Setup")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    width = 440
    height = 170
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")

    frame = tk.Frame(root, padx=18, pady=16)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text="FreeFlowWin precisa de uma API key da Groq.", anchor="w").pack(fill="x")
    tk.Label(frame, text="Cole a chave. Ela sera salva em %APPDATA%\\FreeFlowWin.", anchor="w").pack(fill="x", pady=(2, 10))

    entry = tk.Entry(frame, show="*", width=56)
    entry.pack(fill="x")
    entry.focus_set()

    buttons = tk.Frame(frame)
    buttons.pack(fill="x", pady=(14, 0))

    def save() -> None:
        value = entry.get().strip()
        if not value:
            messagebox.showerror("FreeFlowWin", "API key obrigatoria.")
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
    post_process: bool = False
    post_process_model: str = "openai/gpt-oss-20b"
    paste_result: bool = True
    append_space_after_sentence: bool = True
    preserve_text_clipboard: bool = True
    visual_indicator: bool = True
    visual_indicator_success_seconds: float = 1.1

    @classmethod
    def load(cls) -> "AppConfig":
        path = config_path()
        config = cls()

        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise RuntimeError(f"Could not read config at {path}: {exc}") from exc
            for key, value in data.items():
                if hasattr(config, key):
                    setattr(config, key, value)

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

    def start(self) -> None:
        with self._lock:
            if self.process is not None:
                return

            device = self._resolve_device()
            output = Path(tempfile.gettempdir()) / f"freeflow-win-{int(time.time())}-{random.randint(1000, 9999)}.wav"
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
            time.sleep(0.25)
            if process.poll() is not None:
                stderr = ""
                if process.stderr:
                    stderr = process.stderr.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"ffmpeg failed to start recording from '{device}'. {stderr.strip()}")

            self.process = process
            self.output_path = output
            self.device_name = device
            log(f"Recording from: {device}")

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
                "User-Agent": "FreeFlowWin/0.1",
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
            boundary = "----freeflowwin" + "".join(random.choice(string.ascii_letters + string.digits) for _ in range(24))
            body = self._multipart_body(boundary, fields, "file", audio_path)
            request = urllib.request.Request(
                self._url("audio/transcriptions"),
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Accept": "application/json",
                    "User-Agent": "FreeFlowWin/0.1",
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
                    "User-Agent": "FreeFlowWin/0.1",
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
            'header = "User-Agent: FreeFlowWin/0.1"',
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
    fd, name = tempfile.mkstemp(prefix="freeflow-win-", suffix=suffix)
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


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

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
        self.enabled = bool(config.visual_indicator)
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

    def recording(self) -> None:
        self.show("recording", "Recording", None)

    def transcribing(self) -> None:
        self.show("transcribing", "Transcribing", None)

    def success(self, text: str = "Pasted") -> None:
        self.show("success", text, self.success_seconds)

    def copied(self) -> None:
        self.show("success", "Copied", self.success_seconds)

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
            "recording": ("#121316", "#ff4d5e", "#ffffff", "#ffb3bb"),
            "transcribing": ("#121316", "#6aa7ff", "#ffffff", "#b9d6ff"),
            "success": ("#101411", "#36d17f", "#ffffff", "#a9f0c7"),
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
        if state == "recording":
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
        self.recorder = FFmpegRecorder(config)
        self.client = OpenAICompatibleClient(config)
        self.starting = False
        self.recording = False
        self.transcribing = False
        self.stop_requested = False
        self.hook: KeyboardHook | None = None
        self._lock = threading.Lock()

    def attach_hook(self, hook: KeyboardHook) -> None:
        self.hook = hook

    def start_recording(self) -> None:
        with self._lock:
            if self.starting or self.recording or self.transcribing:
                return
            self.starting = True
            self.stop_requested = False
        self.indicator.recording()
        thread = threading.Thread(target=self._start_recording_worker, name="record-start", daemon=True)
        thread.start()

    def _start_recording_worker(self) -> None:
        try:
            log("Ctrl+Win down: recording...")
            self.recorder.start()
        except Exception as exc:
            with self._lock:
                self.starting = False
                self.recording = False
                self.stop_requested = False
            self.indicator.error("Mic error")
            log(f"Could not start recording: {exc}")
            return

        should_stop = False
        with self._lock:
            self.starting = False
            self.recording = True
            if self.stop_requested:
                self.stop_requested = False
                should_stop = True

        if should_stop:
            self.stop_recording()

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
        try:
            log("Ctrl+Win released: preparing audio...")
            audio_path = self.recorder.stop()
            log("Transcribing...")
            transcript = self.client.transcribe(audio_path).strip()
            if transcript:
                try:
                    transcript = self.client.clean(transcript).strip()
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
                self.indicator.success("Pasted")
                log("Pasted.")
            else:
                Clipboard.set_text(transcript_to_paste)
                self.indicator.copied()
                log("Copied to clipboard.")
        except Exception as exc:
            self.indicator.error("Error")
            log(f"Error: {exc}")
            debug_path = app_config_dir() / "last-error.txt"
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            debug_path.write_text(traceback.format_exc(), encoding="utf-8")
            log(f"Details written to {debug_path}")
        finally:
            if audio_path:
                try:
                    audio_path.unlink(missing_ok=True)
                except Exception:
                    pass
            with self._lock:
                self.transcribing = False

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


def run_app(config: AppConfig) -> None:
    instance = SingleInstance()
    if instance.already_running:
        log("FreeFlowWin is already running.")
        instance.close()
        return

    stop_watcher: StopWatcher | None = None
    indicator = VisualIndicator(config)
    indicator.start()
    controller = FreeFlowController(config, indicator)
    try:
        device = controller.recorder.warm_up_device()
        log(f"Using microphone: {device}")
    except Exception as exc:
        log(f"Microphone check failed: {exc}")
        log("The app will still start; recording will retry when you press Ctrl+Win.")

    hook = KeyboardHook(controller.start_recording, controller.stop_recording)
    controller.attach_hook(hook)
    hook.install()
    try:
        kernel32.SetConsoleTitleW(f"{APP_NAME} - hold Ctrl+Win to dictate")
    except Exception:
        pass

    stop_watcher = StopWatcher(int(kernel32.GetCurrentThreadId()))
    stop_watcher.start()

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
        indicator.stop()
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


def test_record(config: AppConfig, seconds: float) -> None:
    recorder = FFmpegRecorder(config)
    log(f"Recording a local microphone test for {seconds:.1f}s...")
    recorder.start()
    time.sleep(max(0.1, seconds))
    output = recorder.stop()
    log(f"Recorded {output} ({output.stat().st_size} bytes)")
    log("Delete this file after checking it if you do not need it.")


def test_api(config: AppConfig) -> None:
    ensure_config(config)
    log("Testing provider API with configured transport...")
    OpenAICompatibleClient(config).test_api()
    log("Provider API test passed.")


def test_paste() -> None:
    text = f"FreeFlowWin paste test {time.strftime('%H:%M:%S')}"
    log("Testing clipboard + Ctrl+V. Focus a text field now; pasting in 3 seconds...")
    time.sleep(3)
    Clipboard.set_text(text)
    send_ctrl_v()
    log(f"Paste test sent: {text}")


def test_overlay(config: AppConfig) -> None:
    indicator = VisualIndicator(config)
    indicator.start()
    try:
        log("Showing overlay state: Recording")
        indicator.recording()
        time.sleep(1.5)
        log("Showing overlay state: Transcribing")
        indicator.transcribing()
        time.sleep(1.5)
        log("Showing overlay state: Pasted")
        indicator.success("Pasted")
        time.sleep(1.5)
        log("Showing overlay state: Error")
        indicator.error("Error")
        time.sleep(2.0)
    finally:
        indicator.stop()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FreeFlow Windows MVP")
    parser.add_argument("--setup", action="store_true", help="Prompt for API key and microphone settings.")
    parser.add_argument("--list-devices", action="store_true", help="List ffmpeg DirectShow audio input devices.")
    parser.add_argument("--config-path", action="store_true", help="Print config path and exit.")
    parser.add_argument("--test-record", type=float, metavar="SECONDS", help="Record a local WAV test without calling the API.")
    parser.add_argument("--test-api", action="store_true", help="Validate provider auth/connectivity without recording.")
    parser.add_argument("--test-paste", action="store_true", help="Copy a test string and send Ctrl+V after 3 seconds.")
    parser.add_argument("--test-overlay", action="store_true", help="Show the visual indicator states without recording.")
    parser.add_argument("--stop", action="store_true", help="Ask a background FreeFlowWin instance to quit.")
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
        log("No running FreeFlowWin instance found.")
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

    if args.test_record is not None:
        test_record(config, args.test_record)
        return 0

    if args.test_api:
        test_api(config)
        return 0

    if args.test_paste:
        test_paste()
        return 0

    if args.test_overlay:
        test_overlay(config)
        return 0

    config = ensure_config(config)
    run_app(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
