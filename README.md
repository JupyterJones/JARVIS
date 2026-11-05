# STARK INDUSTRIES // J.A.R.V.I.S. (ESPERANZA EDITION)
### Holographic AI Co-Pilot & Neural HUD for Linux Workstations

[![Platform: Linux](https://img.shields.io/badge/Platform-Linux-blue?logo=linux)](https://kernel.org)
[![Tauri: 2.0](https://img.shields.io/badge/Framework-Tauri%202.0%20(Rust)-orange?logo=tauri)](https://tauri.app)
[![Inference: Ollama & KoboldCpp](https://img.shields.io/badge/Inference-Ollama%20%2F%20KoboldCpp-purple)](https://ollama.com)
[![Voice: Kokoro ONNX](https://img.shields.io/badge/TTS-Kokoro--82M%20ONNX-green)](https://huggingface.co/hexgrad/Kokoro-82M)
[![License: MIT](https://img.shields.io/badge/License-MIT-brightgreen.svg)](LICENSE)

An Iron Man Mark VI Stark Industries Holographic HUD co-pilot engineered natively for Linux workstations. 

Designed for local-first, cloudless operation with dual runtime support:
1. **High-Performance Rust AppImage** (`./Jarvis-x86_64.AppImage`) powered by **Tauri 2.0**, HTML5 Canvas Arc Reactor physics, tactical radar animations, and self-contained persistent notes.
2. **PySide6 Qt Desktop HUD** (`./run_gui.sh` -> `Jarvis_v3.py`) with sounddevice direct audio synthesis and real-time CPU/RAM diagnostics.

---

## ⚡ Key Highlights

- **Holographic Stark HUD**: Animated Mark VI Arc Reactor (rotating outer calipers, 10 glowing induction coils, Vibranium triangle core, reactive audio spectrum bars).
- **Strict 4-Thread CPU Lock**: Hardware-safe thread enforcement (`num_thread: 4`, `OMP_NUM_THREADS=4`) preventing system lockups on multi-threaded APUs (e.g. AMD Ryzen 5 3400G).
- **Generous 900-Second Timeouts**: Robust cold-start model weight loading from external storage without false timeouts.
- **Dual Local Inference**: Seamless real-time switching between **Ollama** (`127.0.0.1:11434`) and **KoboldCpp GGUF** (`127.0.0.1:5001`).
- **Neural Voice & Universal Portability**:
  - Uses **Kokoro-82M ONNX** (`af_heart`, `am_adam`, `bm_george`, etc.) for human-grade local vocalization.
  - Automatic fallback to the browser **Web Speech API** (`window.speechSynthesis`) if running on any system without Kokoro models.
- **Persistent Notes Archive**: Self-contained storage that automatically saves markdown notes directly to `<AppImage_Dir>/notes/` and captures screenshots to `<AppImage_Dir>/screenshots/`.

---

## 🚀 Quick Start

### 1. Run the Standalone AppImage
```bash
chmod +x Jarvis-x86_64.AppImage
./Jarvis-x86_64.AppImage
```

### 2. Run the PySide6 Qt GUI
```bash
./run_gui.sh
```

---

## 📖 Complete Documentation & Model Setup

For comprehensive instructions on:
- Downloading the Kokoro ONNX voice models (`kokoro-v1.0.onnx` and `voices-v1.0.bin`)
- Setting up local Ollama and KoboldCpp GGUF models
- The 4-Thread Safety and 900s Generous Timeout rules
- Building the AppImage from source

👉 **Read the full guide in [INSTRUCTIONS.md](INSTRUCTIONS.md)**.

---

## 🛠️ Building From Source

```bash
# 1. Install prerequisites (Debian/Ubuntu)
sudo apt update
sudo apt install build-essential libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev patchelf curl

# 2. Build release AppImage with Tauri CLI
cd src-tauri
cargo build --release
cd ..
npx @tauri-apps/cli build -b appimage
```
Output will be generated in `src-tauri/target/release/bundle/appimage/`.

---

## 📜 License
Distributed under the MIT License.
