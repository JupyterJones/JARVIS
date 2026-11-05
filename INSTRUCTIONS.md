# STARK INDUSTRIES // J.A.R.V.I.S. (ESPERANZA CO-PILOT)
## Complete User Guide, Deployment & Kokoro-TTS Model Setup

Welcome to **J.A.R.V.I.S. (Esperanza Edition)**, a high-performance, holographic Stark Industries Iron Man Mark VI HUD co-pilot engineered for Linux.

JARVIS features dual deployment runtimes:
1. **Tauri + Rust Standalone AppImage** (`./Jarvis-x86_64.AppImage`) with an animated HTML5 Canvas Arc Reactor, reactive tactical radar, local telemetry, persistent `./notes/` archive, and audio visualizers.
2. **Python + PySide6 Qt Desktop HUD** (`./run_gui.sh` -> `Jarvis_v3.py`) with real-time sounddevice playback and system diagnostics.

---

## 🎙️ Downloading the Kokoro-TTS Models

JARVIS utilizes **Kokoro-82M ONNX**, an ultra-natural, fast, lightweight (82M parameter) neural text-to-speech engine. 

The system requires two model files:
- `kokoro-v1.0.onnx` (~310 MB) — The core neural synthesis engine.
- `voices-v1.0.bin` (~25 MB) — The multi-speaker voice embeddings library (includes `af_heart`, `af_bella`, `am_adam`, `bf_emma`, etc.).

### Option A: Direct Download via Terminal (Recommended)

You can download both models directly into the JARVIS directory using `wget` or `curl`:

```bash
cd ~/Desktop/JARVIS

# Download Kokoro ONNX neural weights (~310MB)
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx

# Download the voice embeddings (~25MB)
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

Or using `curl`:

```bash
cd ~/Desktop/JARVIS

curl -L -O https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -L -O https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

### Option B: Automatic Model Detection Locations

JARVIS automatically detects your Kokoro models in the following order of priority:
1. **Local App Directory**: `./kokoro-v1.0.onnx` and `./voices-v1.0.bin` (in the same folder as the AppImage or script).
2. **Dedicated Kokoro Directory**: `/home/jack/Desktop/Kokoro-TTS-Pause/` (or standard `~/Desktop/Kokoro-82M/`).
3. **Automatic Web Speech Fallback**: If you run the AppImage on another computer or haven't downloaded Kokoro yet, JARVIS **automatically falls back to the system Web Speech API** (`window.speechSynthesis`). You will never get a crash or silent failure!

### Installing the Python Dependencies (For Local High-Fidelity Kokoro)

If running the Python engine or using local Python Kokoro ONNX:

```bash
pip install --upgrade pip
pip install kokoro-tts sounddevice soundfile numpy onnxruntime
```

### Available Voice Personalities in `voices-v1.0.bin`

| Voice ID | Accent & Style | Description |
|---|---|---|
| `af_heart` *(Default)* | American Female | Warm, natural, co-pilot tone (Esperanza Default) |
| `af_bella` | American Female | Energetic, clear, crisp |
| `af_nicole` | American Female | Calm, whisper-soft, measured |
| `am_adam` | American Male | Confident, deep, authoritative |
| `am_michael` | American Male | Technical, brisk, assistant tone |
| `bf_emma` | British Female | Classical British co-pilot |
| `bm_george` | British Male | Traditional British butler / classic JARVIS |

---

## ⚡ The 4-Thread Hardware Safety Rule

> [!IMPORTANT]
> **Strict 4-Thread CPU Lock**:
> LLMs (Ollama / llama.cpp / KoboldCpp) default to using **all available logical CPU threads**. On 4-core / 8-thread APUs (such as the AMD Ryzen 5 3400G), running all 8 threads seizes the CPU at 100%, causing desktop lockups, GUI freezes, and thermal throttling.
> 
> JARVIS strictly enforces `num_thread: 4` and exports:
> ```bash
> export OMP_NUM_THREADS=4
> export MKL_NUM_THREADS=4
> export OPENBLAS_NUM_THREADS=4
> ```
> This guarantees smooth holographic 60 FPS HUD animation while background neural inference proceeds unhindered.

---

## ⏳ Generous Timeout Rule (Never Use Short Timeouts)

> [!CAUTION]
> When models load from external storage (e.g. SATA/USB SSD blobs), initial weight loading can take 60–90 seconds before the first token streams.
> JARVIS strictly mandates a **900-second (15-minute) timeout** across all HTTP clients. Standard 5–30s timeouts will cause false timeouts and connection drops.

---

## 🧠 Local Neural LLM Setup

JARVIS seamlessly connects to dual local inference backends:

### 1. Ollama (Default: `http://127.0.0.1:11434`)
- Start Ollama:
  ```bash
  systemctl --user start ollama   # or: ollama serve
  ```
- Pull recommended co-pilot models:
  ```bash
  ollama pull llama3.2:3b
  ollama pull mistral:7b-instruct
  ```
- JARVIS automatically queries `/api/tags` and populates the HUD model selector.

### 2. KoboldCpp Vulkan Engine (GGUF: `http://127.0.0.1:5001`)
- Run the included Vulkan acceleration script:
  ```bash
  ./launch_kobold_vulkan.sh
  ```
- Or launch from the HUD via the **🚀 KOBOLD VULKAN** button on the action ribbon.

---

## 📝 Persistent Self-Contained Notes (`./notes/`)

Unlike typical AppImages that lose files stored inside ephemeral mounts in `/tmp/`, JARVIS inspects `$APPIMAGE` to find the exact host directory where the binary lives:
- **Notes Directory**: `<Directory_of_AppImage>/notes/`
- **Screenshots Directory**: `<Directory_of_AppImage>/screenshots/`

### How to use Notes:
1. **HUD Action Button**: Click **📝 NOTES** in the action ribbon to open the holographic inspector, view markdown notes, edit, or delete them.
2. **Instant Prompt Command**: Type `/note <text>` or `note: <text>` in the input dock and hit Enter. Esperanza immediately archives it to `./notes/note_YYYYMMDD_HHMMSS_<title>.md`.

---

## 🚀 Launching JARVIS

### Standalone Rust AppImage
```bash
chmod +x Jarvis-x86_64.AppImage
./Jarvis-x86_64.AppImage
```

### PySide6 Qt HUD
```bash
./run_gui.sh
```

---

## 🛠️ Building the AppImage from Source

If cloning from GitHub on any Linux workstation:

```bash
# 1. Install system prerequisites (Ubuntu/Debian)
sudo apt update
sudo apt install build-essential libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev patchelf curl

# 2. Build with Tauri CLI
cd src-tauri
cargo build --release
cd ..
npx @tauri-apps/cli build -b appimage
```
The output binary will be created at:
`src-tauri/target/release/bundle/appimage/Jarvis_1.0.0_amd64.AppImage`
