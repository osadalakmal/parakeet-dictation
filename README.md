# Parakeet Dictation (macOS)

Local, fast, privacy-friendly dictation for macOS using NVIDIA Parakeet (MLX on Apple Silicon) with a push-to-talk hotkey.  
Bonus: speak commands to **rewrite selected text** via AWS Bedrock (Claude).

---

## Table of Contents

- [Why this project?](#why-this-project)
- [Features](#features)
- [Demo](#demo)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Push-to-talk dictation](#push-to-talk-dictation)
  - [Voice-driven text editing (Claude via Bedrock)](#voice-driven-text-editing-claude-via-bedrock)
  - [Menu bar controls](#menu-bar-controls)
- [Permissions (macOS)](#permissions-macos)
- [Run in the background](#run-in-the-background)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Roadmap](#roadmap)
- [FAQ](#faq)
- [Credits](#credits)
- [License](#license)

---

## Why this project?

Parakeet Dictation gives you **on-device** speech-to-text on macOS with a **single push-to-talk key** (Globe/Function). It’s built to be:

- **Private**: Audio is processed locally on your Mac.
- **Fast**: Parakeet models are optimized and run great on Apple Silicon via MLX.
- **Practical**: Dictate into *any* app, or select text and **say how to transform it** (“make this more professional”, “translate to Spanish”, etc.)-the app rewrites it via AWS Bedrock and pastes it in place.

---

## Features

- 🖥️ **Menu bar** app (stays out of your way)
- 🎙️ **Push-to-talk**: Press the **Globe / Fn** key to start recording, press again to transcribe & paste
- ⚡ **Local ASR** with **NVIDIA Parakeet** (Apple Silicon via MLX)
- ⌨️ **Auto-paste at cursor** in the foreground app
- ✨ **Voice-driven text editing** (optional): when text is selected, your speech is treated as an instruction and the selection is replaced with the result (via AWS Bedrock → Claude)
- ✅ Clear **recording status** via the menu bar icon
- 🧰 Simple **background mode** (no UI) for power users

---

## Demo

_Add a short GIF here showing:_

1. Globe key down → speaking → Globe key up → text appears
2. Selecting text → Globe key → “make this friendlier” → selection is replaced

---

## Requirements

- **macOS 12+** (Apple Silicon recommended for speed)
- **Python 3.10+**
- **Microphone**
- **Accessibility permission** (to paste text programmatically)
- **PortAudio** (for PyAudio)
- Optional (for AI edits): **AWS account with Bedrock access** (Claude)

---

## Installation

### 1. Install system deps

```bash
brew install portaudio ffmpeg
```

### 2. Clone & install Python deps

```bash
git clone https://github.com/osadalakmal/parakeet-dictation.git
cd parakeet-dictation

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

---

## Configuration

```bash
cp .env.example .env
```

Edit `.env` with your AWS region and credentials if you want Bedrock-powered editing.

---

## Usage

### Push-to-talk dictation

1. Launch the app (see Development or Background sections below).
2. Press the **Globe** (🌐) / Function key to start recording.
3. Speak normally.
4. Press the key again to stop. The app will transcribe and paste the text at your current cursor position.

### Voice-driven text editing (Claude via Bedrock)

1. Select text in any app.
2. Press the Globe / Fn key and speak an instruction, e.g.:
  - “Make this more professional”
  - “Fix the grammar”
  - “Summarize this”
  - “Translate to Spanish”
3. Press the key again to stop. The selected text will be replaced with the edited version.

When no text is selected, your speech is treated as dictation and the text is inserted normally.

### Menu bar controls

- Start/Stop Listening - toggles recording
- Settings - (future) configuration UI
- Quit - exits the app

---

## Permissions (macOS)

- **Microphone**: System Settings → Privacy & Security → Microphone → allow your Terminal/app
- **Accessibility**: System Settings → Privacy & Security → Accessibility → allow your Terminal/app

Without Accessibility permission, the app cannot paste text for you.

---

## Run in the background

```bash
pip install -r requirements.txt
nohup ./run.sh >/dev/null 2>&1 & disown
```

Stop it later:

```bash
ps aux | grep 'src/main.py'
kill -9 <PID>
```

---

## Troubleshooting

- No audio: ensure `portaudio` is installed
- Nothing pastes: check Accessibility permissions
- Bedrock errors: check AWS credentials and region
- High CPU usage: first run warms up the model

---

## Development

```bash
python src/main.py
```

- Menu bar UI via `rumps`
- Hotkey via `pynput`
- Audio capture via `pyaudio`
- ASR via `parakeet-mlx`
- Optional Claude-powered edits via Bedrock

---

## Roadmap

- Preferences UI
- Streaming/partial results
- macOS app packaging
- Latency/quality settings
- Crash logging

---

## FAQ

**Does dictation send audio to the cloud?** No. Local only. Editing uses Bedrock if enabled.  
**What languages are supported?** English.  
**Intel Macs?** Works but slower.

---

## Credits

- Parakeet MLX (NVIDIA Parakeet on Apple Silicon)
- Originally forked from a Whisper-based dictation app

---

## License

MIT
