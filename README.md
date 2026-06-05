<p align="center">
  <img src="assets/flowz-logo.svg" alt="Flowz" width="560">
</p>

<p align="center">
  <strong>Fast voice dictation for Windows.</strong><br>
  Hold a hotkey, speak, release, and Flowz pastes the transcription where you were typing.
</p>

<p align="center">
  <a href="#features">Features</a> -
  <a href="#quick-start">Quick start</a> -
  <a href="#installer">Installer</a> -
  <a href="#brand-kit">Brand kit</a> -
  <a href="#configuration">Configuration</a> -
  <a href="#donate">Donate</a>
</p>

---

## Why Flowz

Flowz is a free, open Windows-first alternative to voice dictation tools like
Wispr Flow. It focuses on one tight workflow:

1. Click any text field.
2. Hold `Ctrl + Windows`.
3. Speak after the ready sound.
4. Release the keys.
5. Flowz transcribes and pastes the text.

It uses `ffmpeg` for microphone capture and any OpenAI-compatible transcription
endpoint, with Groq configured by default.

Flowz is not affiliated with Wispr Flow or its makers.

## Features

- Global hold-to-dictate hotkey: `Ctrl + Windows`.
- Low-latency warm microphone capture with idle timeout.
- Pre-roll buffer to avoid clipping the first syllable.
- Custom ready sound support, including `.mp3` and `.wav` files.
- Silence trimming before upload.
- Automatic paste with clipboard preservation.
- Visual overlay and tray menu.
- Graphical settings window.
- Optional "Start with Windows" support.
- Simple per-user PowerShell installer.
- No third-party Python runtime packages.

## Requirements

- Windows 10 or Windows 11.
- Python 3.10+ if running from source.
- `ffmpeg` available on `PATH`, or configured in settings.
- `curl.exe`, available by default on modern Windows.
- API key for a provider compatible with OpenAI's `/audio/transcriptions` API.

Check tools:

```powershell
python --version
ffmpeg -version
curl.exe --version
```

## Quick Start

Clone and enter the repo:

```powershell
git clone https://github.com/schulxf/flowz.git
cd flowz
```

Configure Flowz:

```powershell
.\Flowz.bat --settings
```

Run it:

```powershell
.\Flowz.bat
```

Use it:

1. Focus the app where you want text.
2. Hold `Ctrl + Windows`.
3. Start speaking after the sound or when the overlay says `Recording`.
4. Release the keys.
5. Flowz pastes the transcript.

## Installer

Build and install for the current Windows user:

```powershell
.\install.ps1 -Build
```

Install and start with Windows:

```powershell
.\install.ps1 -Build -StartWithWindows
```

The installer copies the app to:

```text
%LOCALAPPDATA%\Flowz\Flowz.exe
```

It also creates Start Menu shortcuts for Flowz and Flowz Settings.

Uninstall:

```powershell
.\uninstall.ps1
```

Remove the saved configuration too:

```powershell
.\uninstall.ps1 -RemoveConfig
```

## Brand Kit

Flowz has a lightweight identity system for README, website, installer, and app
surfaces:

```text
BRANDKIT.md
assets/flowz-logo.svg
assets/flowz-brandkit-board.svg
```

The system is built around a fluid blue wordmark, mist-white surfaces, dark ink
panels, and concise product copy. The full guide covers color tokens,
typography, motion, UI states, sound identity, website direction, and usage
rules.

## Build EXE

```powershell
.\build-exe.ps1
```

Output:

```text
dist\Flowz.exe
```

Run the built app:

```powershell
.\dist\Flowz.exe
```

Open settings:

```powershell
.\dist\Flowz.exe --settings
```

Test the ready sound:

```powershell
.\dist\Flowz.exe --test-sound
```

## Configuration

Flowz stores config at:

```text
%APPDATA%\Flowz\config.json
```

If an older `%APPDATA%\FreeFlowWin\config.json` exists, Flowz migrates it on
first run.

Most settings can be edited in the GUI:

```powershell
.\Flowz.bat --settings
```

Important options:

| Setting | Purpose |
| --- | --- |
| `api_key` | Provider API key. |
| `base_url` | OpenAI-compatible API base URL. Default: Groq. |
| `transcription_model` | Model used for transcription. |
| `ffmpeg_device` | DirectShow microphone name. |
| `low_latency_capture` | Keeps the mic warm for faster hotkey response. |
| `low_latency_idle_timeout_seconds` | Releases warm capture after idle time. |
| `low_latency_preroll_ms` | Includes audio before the hotkey to avoid clipping. |
| `trim_silence` | Removes leading/trailing silence before upload. |
| `audio_ready_sound_file` | Optional custom `.mp3` or `.wav` ready sound. |
| `tray_icon` | Enables tray menu controls. |
| `log_timing_metrics` | Logs timing for audio, trim, transcription, and paste. |

## Custom Ready Sound

Set `audio_ready_sound_file` in settings or `config.json`:

```json
{
  "audio_ready_sound": true,
  "audio_ready_sound_file": "D:\\Sync\\DEVELOPING-WIP\\FreeFlowWS\\ribhavagrawal-point-smooth-beep-230573.mp3",
  "audio_ready_sound_backend": "file"
}
```

Test it:

```powershell
.\Flowz.bat --test-sound
```

## Diagnostics

List microphones:

```powershell
.\Flowz.bat --list-devices
```

Record a local WAV without calling the API:

```powershell
.\Flowz.bat --test-record 3
```

Test provider connectivity:

```powershell
.\Flowz.bat --test-api
```

Test paste behavior:

```powershell
.\Flowz.bat --test-paste
```

Show overlay states:

```powershell
.\Flowz.bat --test-overlay
```

Stop a running instance:

```powershell
.\Flowz.bat --stop
```

Logs:

```text
%APPDATA%\Flowz\flowz.log
%APPDATA%\Flowz\last-error.txt
```

## Donate

If Flowz saves you time, donations are welcome.

EVM address:

```text
0x5d72a048D7bd477DC25Bd34Be8Ca0bD58d3db0B4
```

Works on EVM-compatible networks. Always verify the address before sending.

## Security Notes

- Your API key is stored locally in `%APPDATA%\Flowz\config.json`.
- Audio is sent only when you release the dictation hotkey.
- With `low_latency_capture` enabled, Windows may show the microphone as in use
  while Flowz keeps capture warm. It releases automatically after the idle
  timeout, or manually from the tray menu.

## License

Add your preferred license before distributing publicly.
