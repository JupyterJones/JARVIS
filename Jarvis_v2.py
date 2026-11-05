#!/usr/bin/env python3
"""
=============================================================================
 Jarvis_v2.py - Autonomous Sci-Fi HUD Assistant (Esperanza Edition)
 Built for Jack | PySide6 Glassmorphic UI | Dual Ollama & KoboldCpp GGUF
 Kokoro TTS & Speech Recognition | Linux Native | Vulkan Accelerated
=============================================================================
"""

import os
import sys

# Limit CPU threads to 4 to prevent pinning all 8 logical cores
os.environ["OMP_NUM_THREADS"] = "4"
os.environ["MKL_NUM_THREADS"] = "4"
os.environ["OPENBLAS_NUM_THREADS"] = "4"
os.environ["NUMEXPR_NUM_THREADS"] = "4"
os.environ["VECLIB_MAXIMUM_THREADS"] = "4"

import math
import time
import json
import uuid
import datetime
import threading
import subprocess
import requests
from pathlib import Path

# PySide6 GUI Components
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QScrollArea, QFrame, QComboBox,
    QProgressBar, QSizePolicy, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, Slot, QPointF
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QRadialGradient, QLinearGradient,
    QFont, QIcon, QPainterPath
)

# Hardware & System
import psutil
from PIL import ImageGrab
import sounddevice as sd

# Audio & Speech
try:
    from kokoro_tts import Kokoro
    KOKORO_AVAILABLE = True
except Exception:
    KOKORO_AVAILABLE = False

try:
    import speech_recognition as sr
    SPEECH_REC_AVAILABLE = True
except Exception:
    SPEECH_REC_AVAILABLE = False

# Suppress ALSA C-level error logs for clean terminal output
import ctypes
try:
    asound = ctypes.cdll.LoadLibrary('libasound.so.2')
    asound.snd_lib_error_set_handler(None)
except Exception:
    pass

# =============================================================================
# Paths & Settings
# =============================================================================
BASE_DIR = Path(__file__).resolve().parent
NOTES_FILE = BASE_DIR / "jarvis_notes.json"
SCREENSHOT_DIR = BASE_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

KOKORO_MODEL = "/home/jack/Desktop/Kokoro-TTS-Pause/kokoro-v1.0.onnx"
KOKORO_VOICES = "/home/jack/Desktop/Kokoro-TTS-Pause/voices-v1.0.bin"

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
KOBOLD_HOST = os.environ.get("KOBOLD_HOST", "http://127.0.0.1:5001")
DEFAULT_MODEL = "llama3.2:3b"

# Generous timeout: 900 seconds (15 minutes) - Never use short timeouts!
GENEROUS_TIMEOUT = 900

# Sci-Fi Color Palette
CLR_BG = "#070b14"
CLR_PANEL = "rgba(13, 22, 40, 0.85)"
CLR_PANEL_SOLID = "#0c1527"
CLR_BORDER = "rgba(0, 229, 255, 0.35)"
CLR_CYAN = "#00e5ff"
CLR_BLUE = "#0088ff"
CLR_GREEN = "#00ff9d"
CLR_AMBER = "#ffaa00"
CLR_RED = "#ff3366"
CLR_TEXT = "#e0f7fa"
CLR_TEXT_MUTED = "#78909c"

# =============================================================================
# Animated Arc Reactor HUD Centerpiece
# =============================================================================
class ArcReactorWidget(QWidget):
    """Futuristic glowing circular Arc Reactor / Audio Waveform Visualizer."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(170, 170)
        self.angle_outer = 0.0
        self.angle_inner = 0.0
        self.pulse = 0.0
        self.pulse_dir = 1
        self.state = "IDLE"  # IDLE, LISTENING, THINKING, SPEAKING
        self.wave_bars = [math.sin(i * 0.4) for i in range(16)]

        # 40 FPS render loop
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(25)

    def set_state(self, state: str):
        self.state = state
        self.update()

    def update_animation(self):
        # Rotation speeds depend on state
        if self.state == "THINKING":
            self.angle_outer = (self.angle_outer + 3.5) % 360
            self.angle_inner = (self.angle_inner - 4.5) % 360
        else:
            self.angle_outer = (self.angle_outer + 0.8) % 360
            self.angle_inner = (self.angle_inner - 1.2) % 360

        # Breathing pulse
        speed = 0.06 if self.state in ["THINKING", "SPEAKING", "LISTENING"] else 0.025
        self.pulse += speed * self.pulse_dir
        if self.pulse >= 1.0:
            self.pulse = 1.0
            self.pulse_dir = -1
        elif self.pulse <= 0.0:
            self.pulse = 0.0
            self.pulse_dir = 1

        # Shift wave bars for speaking / listening animation
        if self.state in ["SPEAKING", "LISTENING"]:
            t = time.time() * 8
            self.wave_bars = [abs(math.sin(t + i * 0.45)) for i in range(16)]

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r_outer = min(cx, cy) - 8

        # Accent color based on state
        if self.state == "LISTENING":
            accent = QColor(CLR_GREEN)
            core_color = QColor(0, 255, 157, int(120 + 80 * self.pulse))
        elif self.state == "THINKING":
            accent = QColor(CLR_AMBER)
            core_color = QColor(255, 170, 0, int(140 + 90 * self.pulse))
        elif self.state == "SPEAKING":
            accent = QColor(CLR_CYAN)
            core_color = QColor(0, 229, 255, int(150 + 100 * self.pulse))
        else:
            accent = QColor(0, 229, 255, 180)
            core_color = QColor(0, 168, 255, int(70 + 60 * self.pulse))

        # 1. Background radial glow
        glow_grad = QRadialGradient(cx, cy, r_outer)
        glow_grad.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), int(45 + 30 * self.pulse)))
        glow_grad.setColorAt(0.7, QColor(10, 25, 50, 60))
        glow_grad.setColorAt(1.0, QColor(7, 11, 20, 0))
        painter.setBrush(QBrush(glow_grad))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(cx, cy), r_outer, r_outer)

        # 2. Outer dashed rotating ring
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self.angle_outer)
        pen_outer = QPen(accent, 1.8)
        pen_outer.setDashPattern([12, 6, 4, 6])
        painter.setPen(pen_outer)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(0, 0), r_outer - 4, r_outer - 4)

        # Tick marks on outer ring
        pen_tick = QPen(QColor(0, 229, 255, 140), 1.2)
        painter.setPen(pen_tick)
        for i in range(12):
            painter.rotate(30)
            painter.drawLine(0, int(r_outer - 8), 0, int(r_outer - 3))
        painter.restore()

        # 3. Inner counter-rotating ring
        r_inner = r_outer * 0.68
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self.angle_inner)
        pen_inner = QPen(QColor(0, 168, 255, 200), 1.5)
        pen_inner.setDashPattern([6, 8])
        painter.setPen(pen_inner)
        painter.drawEllipse(QPointF(0, 0), r_inner, r_inner)

        # 6 Arc segment brackets
        pen_seg = QPen(accent, 2.5)
        painter.setPen(pen_seg)
        for _ in range(6):
            painter.rotate(60)
            painter.drawArc(int(-r_inner), int(-r_inner), int(r_inner * 2), int(r_inner * 2), -15 * 16, 30 * 16)
        painter.restore()

        # 4. Reactive audio wave bars
        if self.state in ["SPEAKING", "LISTENING", "THINKING"]:
            painter.save()
            painter.translate(cx, cy)
            bar_count = len(self.wave_bars)
            angle_step = 360 / bar_count
            for i, val in enumerate(self.wave_bars):
                painter.rotate(angle_step)
                bar_len = 5 + val * 16
                pen_bar = QPen(accent, 2.0)
                painter.setPen(pen_bar)
                painter.drawLine(0, int(r_inner + 4), 0, int(r_inner + 4 + bar_len))
            painter.restore()

        # 5. Core glowing sphere
        r_core = r_outer * 0.35 + (3.0 * self.pulse)
        core_grad = QRadialGradient(cx, cy, r_core)
        core_grad.setColorAt(0.0, QColor(255, 255, 255, 240))
        core_grad.setColorAt(0.35, accent)
        core_grad.setColorAt(0.85, core_color)
        core_grad.setColorAt(1.0, QColor(core_color.red(), core_color.green(), core_color.blue(), 20))
        painter.setBrush(QBrush(core_grad))
        painter.setPen(QPen(QColor(255, 255, 255, 180), 1.0))
        painter.drawEllipse(QPointF(cx, cy), r_core, r_core)


# =============================================================================
# Dual LLM Worker (Ollama & KoboldCpp GGUF)
# =============================================================================
class LLMWorker(QThread):
    token_received = Signal(str)
    finished_response = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, model_choice, system_prompt, history, user_query, parent=None):
        super().__init__(parent)
        self.model_choice = model_choice
        self.system_prompt = system_prompt
        self.history = history
        self.user_query = user_query

    def run(self):
        full_reply = ""
        try:
            if "Kobold" in self.model_choice or self.model_choice.startswith("⚡"):
                # KoboldCpp OpenAI-compatible streaming endpoint
                url = f"{KOBOLD_HOST}/v1/chat/completions"
                messages = [{"role": "system", "content": self.system_prompt}]
                for item in self.history[-10:]:
                    messages.append(item)
                messages.append({"role": "user", "content": self.user_query})

                payload = {
                    "messages": messages,
                    "stream": True,
                    "max_tokens": 512,
                    "temperature": 0.7
                }
                with requests.post(url, json=payload, stream=True, timeout=GENEROUS_TIMEOUT) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if self.isInterruptionRequested():
                            break
                        if line:
                            decoded = line.decode("utf-8").strip()
                            if decoded.startswith("data: "):
                                data_str = decoded[6:].strip()
                                if data_str == "[DONE]":
                                    break
                                chunk = json.loads(data_str)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                token = delta.get("content", "")
                                if token:
                                    full_reply += token
                                    self.token_received.emit(token)
            else:
                # Ollama Streaming Chat API
                url = f"{OLLAMA_HOST}/api/chat"
                messages = [{"role": "system", "content": self.system_prompt}]
                for item in self.history[-10:]:
                    messages.append(item)
                messages.append({"role": "user", "content": self.user_query})

                payload = {
                    "model": self.model_choice,
                    "messages": messages,
                    "stream": True,
                    "options": {
                        "num_thread": 4,  # Cap CPU threads to 4
                        "temperature": 0.72,
                        "num_ctx": 4096
                    }
                }
                with requests.post(url, json=payload, stream=True, timeout=GENEROUS_TIMEOUT) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if self.isInterruptionRequested():
                            break
                        if line:
                            chunk = json.loads(line.decode("utf-8"))
                            token = chunk.get("message", {}).get("content", "")
                            if token:
                                full_reply += token
                                self.token_received.emit(token)
                            if chunk.get("done", False):
                                break

            if not self.isInterruptionRequested():
                self.finished_response.emit(full_reply)
        except Exception as e:
            if not self.isInterruptionRequested():
                self.error_occurred.emit(str(e))


class TTSWorker(QThread):
    started_speaking = Signal()
    finished_speaking = Signal()

    def __init__(self, kokoro_instance, text, voice="af_river", speed=1.05, parent=None):
        super().__init__(parent)
        self.kokoro = kokoro_instance
        self.text = text
        self.voice = voice
        self.speed = speed

    def run(self):
        if not self.kokoro or not self.text.strip():
            return
        try:
            self.started_speaking.emit()
            clean_text = self.text.replace("*", "").replace("#", "").replace("`", "").strip()
            sentences = [s.strip() for s in clean_text.split(".") if s.strip()]
            spoken = ". ".join(sentences[:2]) + "." if len(sentences) > 2 else clean_text

            samples, sr = self.kokoro.create(spoken, voice=self.voice, speed=self.speed, lang="en-us")
            if not self.isInterruptionRequested():
                sd.play(samples, sr)
                sd.wait()
        except Exception as e:
            print(f"TTS Worker Error: {e}")
        finally:
            self.finished_speaking.emit()


class VoiceRecognitionWorker(QThread):
    heard_speech = Signal(str)
    status_msg = Signal(str)
    finished_listening = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.recognizer = sr.Recognizer() if SPEECH_REC_AVAILABLE else None

    def run(self):
        if not self.recognizer:
            self.status_msg.emit("Speech Recognition not available")
            self.finished_listening.emit()
            return

        try:
            self.status_msg.emit("Listening to microphone...")
            with sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.6)
                if self.isInterruptionRequested():
                    return
                audio = self.recognizer.listen(source, timeout=8, phrase_time_limit=12)
                self.status_msg.emit("Transcribing voice...")
                text = self.recognizer.recognize_google(audio)
                if text and not self.isInterruptionRequested():
                    self.heard_speech.emit(text)
        except sr.WaitTimeoutError:
            self.status_msg.emit("Listening timed out (silence)")
        except sr.UnknownValueError:
            self.status_msg.emit("Audio not understood")
        except Exception as e:
            self.status_msg.emit(f"Mic error: {e}")
        finally:
            self.finished_listening.emit()


# =============================================================================
# Chat Bubble Widget
# =============================================================================
class ChatBubble(QFrame):
    def __init__(self, sender: str, text: str, is_user=False, parent=None):
        super().__init__(parent)
        self.is_user = is_user
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        badge_color = CLR_CYAN if not is_user else CLR_BLUE
        sender_lbl = QLabel(f"[{sender}]")
        sender_lbl.setStyleSheet(f"color: {badge_color}; font-weight: bold; font-size: 11px; letter-spacing: 1px;")
        
        time_lbl = QLabel(datetime.datetime.now().strftime("%I:%M %p"))
        time_lbl.setStyleSheet(f"color: {CLR_TEXT_MUTED}; font-size: 10px;")

        header_layout.addWidget(sender_lbl)
        header_layout.addStretch()
        header_layout.addWidget(time_lbl)

        self.msg_lbl = QLabel(text)
        self.msg_lbl.setWordWrap(True)
        self.msg_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.msg_lbl.setStyleSheet(f"color: {CLR_TEXT}; font-size: 13px; line-height: 1.4;")

        layout.addLayout(header_layout)
        layout.addWidget(self.msg_lbl)

        if is_user:
            self.setStyleSheet(f"""
                ChatBubble {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #101c38, stop:1 #0c1830);
                    border: 1px solid rgba(0, 136, 255, 0.4);
                    border-radius: 12px;
                    margin-left: 60px;
                    margin-right: 8px;
                    margin-top: 4px;
                    margin-bottom: 4px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                ChatBubble {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0a1426, stop:1 #0d1a33);
                    border: 1px solid rgba(0, 229, 255, 0.35);
                    border-radius: 12px;
                    margin-right: 60px;
                    margin-left: 8px;
                    margin-top: 4px;
                    margin-bottom: 4px;
                }}
            """)

    def append_text(self, token: str):
        self.msg_lbl.setText(self.msg_lbl.text() + token)


# =============================================================================
# Main Jarvis HUD Window
# =============================================================================
class JarvisWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S. // ESPERANZA MARK II")
        self.resize(1100, 780)
        self.setMinimumSize(920, 640)

        # Initialize TTS Engine in memory
        self.kokoro = None
        if KOKORO_AVAILABLE and Path(KOKORO_MODEL).exists() and Path(KOKORO_VOICES).exists():
            try:
                self.kokoro = Kokoro(KOKORO_MODEL, KOKORO_VOICES)
            except Exception as e:
                print(f"Kokoro load warning: {e}")

        self.voice_enabled = True
        self.current_voice = "af_river"
        self.current_model = DEFAULT_MODEL
        self.history = []
        self.system_prompt = (
            "You are Esperanza, Jack's loyal, brilliant, warm, and highly capable Jarvis-like AI co-pilot. "
            "You run natively on his Linux workstation. Be direct, witty, and concise when answering queries, "
            "and provide code or analysis when asked. Always treat Jack as your visionary partner."
        )

        self.active_llm_worker = None
        self.active_tts_worker = None
        self.active_voice_worker = None
        self.current_assistant_bubble = None

        self.setup_ui()
        self.apply_styles()
        self.start_telemetry_loop()
        self.populate_models()

        # Startup greeting
        QTimer.singleShot(600, self.startup_greeting)

    def setup_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 12, 16, 14)
        main_layout.setSpacing(10)

        # ---------------------------------------------------------------------
        # 1. Top HUD Header: Telemetry & Center Arc Reactor
        # ---------------------------------------------------------------------
        top_hud = QFrame()
        top_hud.setObjectName("topHud")
        top_layout = QHBoxLayout(top_hud)
        top_layout.setContentsMargins(14, 10, 14, 10)
        top_layout.setSpacing(16)

        # Left Column: Telemetry & System Gauges
        left_telemetry = QVBoxLayout()
        left_telemetry.setSpacing(6)

        title_lbl = QLabel("J.A.R.V.I.S. // ESPERANZA")
        title_lbl.setStyleSheet(f"color: {CLR_CYAN}; font-size: 16px; font-weight: bold; letter-spacing: 2px;")
        subtitle_lbl = QLabel("AUTONOMOUS PAIR-PROGRAMMING CO-PILOT")
        subtitle_lbl.setStyleSheet(f"color: {CLR_TEXT_MUTED}; font-size: 9px; letter-spacing: 1px;")

        left_telemetry.addWidget(title_lbl)
        left_telemetry.addWidget(subtitle_lbl)

        # CPU & RAM bars
        self.cpu_lbl = QLabel("CPU: 0%")
        self.cpu_lbl.setStyleSheet(f"color: {CLR_TEXT}; font-size: 11px;")
        self.cpu_bar = QProgressBar()
        self.cpu_bar.setRange(0, 100)
        self.cpu_bar.setFixedHeight(6)
        self.cpu_bar.setTextVisible(False)

        self.ram_lbl = QLabel("RAM: 0%")
        self.ram_lbl.setStyleSheet(f"color: {CLR_TEXT}; font-size: 11px;")
        self.ram_bar = QProgressBar()
        self.ram_bar.setRange(0, 100)
        self.ram_bar.setFixedHeight(6)
        self.ram_bar.setTextVisible(False)

        left_telemetry.addWidget(self.cpu_lbl)
        left_telemetry.addWidget(self.cpu_bar)
        left_telemetry.addWidget(self.ram_lbl)
        left_telemetry.addWidget(self.ram_bar)

        # Center: Arc Reactor Widget
        center_box = QVBoxLayout()
        center_box.setAlignment(Qt.AlignCenter)
        self.arc_reactor = ArcReactorWidget(self)
        center_box.addWidget(self.arc_reactor)

        self.status_pill = QLabel("SYSTEM IDLE // READY")
        self.status_pill.setAlignment(Qt.AlignCenter)
        self.status_pill.setStyleSheet(f"""
            background: rgba(0, 229, 255, 0.12);
            color: {CLR_CYAN};
            border: 1px solid rgba(0, 229, 255, 0.3);
            border-radius: 10px;
            padding: 3px 12px;
            font-size: 10px;
            font-weight: bold;
            letter-spacing: 1.5px;
        """)
        center_box.addWidget(self.status_pill)

        # Right Column: Model Selection & Clock
        right_telemetry = QVBoxLayout()
        right_telemetry.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        right_telemetry.setSpacing(6)

        self.clock_lbl = QLabel("00:00:00 AM")
        self.clock_lbl.setAlignment(Qt.AlignRight)
        self.clock_lbl.setStyleSheet(f"color: {CLR_CYAN}; font-size: 18px; font-weight: bold; font-family: monospace;")
        
        self.date_lbl = QLabel("Loading Date...")
        self.date_lbl.setAlignment(Qt.AlignRight)
        self.date_lbl.setStyleSheet(f"color: {CLR_TEXT_MUTED}; font-size: 11px;")

        model_box = QHBoxLayout()
        model_lbl = QLabel("MODEL:")
        model_lbl.setStyleSheet(f"color: {CLR_TEXT_MUTED}; font-size: 11px; font-weight: bold;")
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(180)
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        model_box.addWidget(model_lbl)
        model_box.addWidget(self.model_combo)

        right_telemetry.addWidget(self.clock_lbl)
        right_telemetry.addWidget(self.date_lbl)
        right_telemetry.addLayout(model_box)

        top_layout.addLayout(left_telemetry, stretch=2)
        top_layout.addLayout(center_box, stretch=2)
        top_layout.addLayout(right_telemetry, stretch=2)

        main_layout.addWidget(top_hud)

        # ---------------------------------------------------------------------
        # 2. Sci-Fi Quick Action Command Ribbon
        # ---------------------------------------------------------------------
        action_bar = QHBoxLayout()
        action_bar.setSpacing(8)

        btn_specs = [
            ("⚡ HUD Stats", self.cmd_system_stats),
            ("🚀 Start Kobold", self.cmd_start_kobold),
            ("📸 Screenshot", self.cmd_screenshot),
            ("🌦 Weather", self.cmd_weather),
            ("📖 Wikipedia", self.cmd_wikipedia),
            ("📝 Notes", self.cmd_notes),
            ("🔊 Vol +", lambda: self.cmd_volume("up")),
            ("🔉 Vol -", lambda: self.cmd_volume("down")),
            ("🔇 Mute", lambda: self.cmd_volume("mute")),
            ("🧹 Clear", self.cmd_clear_chat),
        ]

        for text, slot_func in btn_specs:
            btn = QPushButton(text)
            btn.setObjectName("actionBtn")
            btn.clicked.connect(slot_func)
            action_bar.addWidget(btn)

        main_layout.addLayout(action_bar)

        # ---------------------------------------------------------------------
        # 3. Main Chat Transcript Scroll Area
        # ---------------------------------------------------------------------
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setObjectName("chatScroll")
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(8, 8, 8, 8)
        self.chat_layout.setSpacing(10)
        self.chat_layout.addStretch()

        self.chat_scroll.setWidget(self.chat_container)
        main_layout.addWidget(self.chat_scroll, stretch=1)

        # ---------------------------------------------------------------------
        # 4. Floating Input Dock
        # ---------------------------------------------------------------------
        input_dock = QFrame()
        input_dock.setObjectName("inputDock")
        input_layout = QHBoxLayout(input_dock)
        input_layout.setContentsMargins(10, 8, 10, 8)
        input_layout.setSpacing(10)

        # Voice Input Toggle
        self.voice_btn = QPushButton("🎙 MIC")
        self.voice_btn.setObjectName("voiceBtn")
        self.voice_btn.setCheckable(True)
        self.voice_btn.clicked.connect(self.toggle_mic_listening)

        # Voice Response Mute/Unmute Toggle
        self.tts_toggle_btn = QPushButton("🔊 VOICE: ON")
        self.tts_toggle_btn.setObjectName("ttsToggleBtn")
        self.tts_toggle_btn.clicked.connect(self.toggle_tts_output)

        # Text Input Field
        self.input_field = QLineEdit()
        self.input_field.setObjectName("inputField")
        self.input_field.setPlaceholderText("Ask Jarvis, enter command, or click 🎙 MIC...")
        self.input_field.returnPressed.connect(self.send_message)

        # Send Button
        self.send_btn = QPushButton("➤ SEND")
        self.send_btn.setObjectName("sendBtn")
        self.send_btn.clicked.connect(self.send_message)

        input_layout.addWidget(self.voice_btn)
        input_layout.addWidget(self.tts_toggle_btn)
        input_layout.addWidget(self.input_field, stretch=1)
        input_layout.addWidget(self.send_btn)

        main_layout.addWidget(input_dock)

    def apply_styles(self):
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {CLR_BG};
            }}
            #topHud {{
                background: {CLR_PANEL};
                border: 1px solid {CLR_BORDER};
                border-radius: 14px;
            }}
            #chatScroll {{
                background: {CLR_PANEL};
                border: 1px solid {CLR_BORDER};
                border-radius: 14px;
            }}
            #inputDock {{
                background: {CLR_PANEL};
                border: 1px solid {CLR_BORDER};
                border-radius: 14px;
            }}
            #inputField {{
                background: rgba(8, 15, 28, 0.95);
                border: 1px solid rgba(0, 229, 255, 0.4);
                border-radius: 8px;
                padding: 10px 14px;
                color: {CLR_TEXT};
                font-size: 13px;
            }}
            #inputField:focus {{
                border: 1.5px solid {CLR_CYAN};
            }}
            #sendBtn {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0088ff, stop:1 #00e5ff);
                color: #070b14;
                font-weight: bold;
                font-size: 12px;
                border-radius: 8px;
                padding: 10px 20px;
            }}
            #sendBtn:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0099ff, stop:1 #33eeff);
            }}
            #voiceBtn {{
                background: rgba(12, 25, 45, 0.85);
                border: 1px solid rgba(0, 255, 157, 0.4);
                color: {CLR_GREEN};
                font-weight: bold;
                font-size: 11px;
                border-radius: 8px;
                padding: 8px 14px;
            }}
            #voiceBtn:checked {{
                background: rgba(255, 51, 102, 0.3);
                border: 1.5px solid {CLR_RED};
                color: {CLR_RED};
            }}
            #ttsToggleBtn {{
                background: rgba(12, 25, 45, 0.85);
                border: 1px solid rgba(0, 229, 255, 0.4);
                color: {CLR_CYAN};
                font-weight: bold;
                font-size: 11px;
                border-radius: 8px;
                padding: 8px 14px;
            }}
            #actionBtn {{
                background: rgba(14, 25, 48, 0.75);
                border: 1px solid rgba(0, 229, 255, 0.25);
                color: {CLR_TEXT};
                font-size: 11px;
                font-weight: 500;
                border-radius: 7px;
                padding: 6px 12px;
            }}
            #actionBtn:hover {{
                background: rgba(0, 229, 255, 0.18);
                border: 1px solid {CLR_CYAN};
                color: #ffffff;
            }}
            QProgressBar {{
                background-color: rgba(15, 25, 45, 0.7);
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0088ff, stop:1 #00e5ff);
                border-radius: 3px;
            }}
            QComboBox {{
                background: rgba(10, 20, 36, 0.9);
                border: 1px solid rgba(0, 229, 255, 0.35);
                border-radius: 6px;
                color: {CLR_CYAN};
                padding: 4px 8px;
                font-size: 11px;
            }}
            QComboBox QAbstractItemView {{
                background: #0a1426;
                color: {CLR_TEXT};
                selection-background-color: #0088ff;
                border: 1px solid {CLR_CYAN};
            }}
            QScrollBar:vertical {{
                background: rgba(7, 11, 20, 0.5);
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(0, 229, 255, 0.3);
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {CLR_CYAN};
            }}
        """)

    # -------------------------------------------------------------------------
    # Telemetry & Status Loop
    # -------------------------------------------------------------------------
    def start_telemetry_loop(self):
        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.timeout.connect(self.refresh_telemetry)
        self.telemetry_timer.start(1000)
        self.refresh_telemetry()

    def refresh_telemetry(self):
        now = datetime.datetime.now()
        self.clock_lbl.setText(now.strftime("%I:%M:%S %p"))
        self.date_lbl.setText(now.strftime("%A, %B %d, %Y"))

        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        self.cpu_lbl.setText(f"CPU: {cpu}%")
        self.cpu_bar.setValue(int(cpu))
        self.ram_lbl.setText(f"RAM: {ram.percent}% ({round(ram.used / (1024**3), 1)} / {round(ram.total / (1024**3), 1)} GB)")
        self.ram_bar.setValue(int(ram.percent))

    def populate_models(self):
        models = []
        # Check KoboldCpp
        try:
            rk = requests.get(f"{KOBOLD_HOST}/api/v1/model", timeout=2)
            if rk.status_code == 200:
                mname = rk.json().get("result", "Llama-GGUF")
                models.append(f"⚡ Kobold: {mname}")
        except Exception:
            pass

        # Check Ollama
        try:
            r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=10)
            if r.status_code == 200:
                for m in r.json().get("models", []):
                    models.append(m["name"])
        except Exception:
            pass

        self.model_combo.clear()
        if models:
            self.model_combo.addItems(models)
            if any("Kobold" in m for m in models):
                kobold_entry = next(m for m in models if "Kobold" in m)
                self.model_combo.setCurrentText(kobold_entry)
            elif "esperanza:latest" in models:
                self.model_combo.setCurrentText("esperanza:latest")
            elif DEFAULT_MODEL in models:
                self.model_combo.setCurrentText(DEFAULT_MODEL)
            else:
                self.model_combo.setCurrentIndex(0)
        else:
            self.model_combo.addItem(DEFAULT_MODEL)

    def on_model_changed(self, model_name: str):
        if model_name:
            self.current_model = model_name
            disp = model_name.replace("⚡ ", "")
            self.status_pill.setText(f"MODEL // {disp.upper()}")

    def set_system_status(self, text: str, state="IDLE"):
        self.status_pill.setText(text.upper())
        self.arc_reactor.set_state(state)

    # -------------------------------------------------------------------------
    # Chat & Messaging Core
    # -------------------------------------------------------------------------
    def startup_greeting(self):
        welcome = (
            "All systems online and operational, Jack. Esperanza Jarvis Mark II HUD loaded. "
            "Connected to local Ollama and KoboldCpp GGUF with Kokoro speech synthesis."
        )
        self.append_message("Esperanza", welcome, is_user=False)
        self.speak(welcome)

    def append_message(self, sender: str, text: str, is_user=False):
        bubble = ChatBubble(sender, text, is_user=is_user)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        QTimer.singleShot(50, self.scroll_to_bottom)
        return bubble

    def scroll_to_bottom(self):
        self.chat_scroll.verticalScrollBar().setValue(
            self.chat_scroll.verticalScrollBar().maximum()
        )

    def send_message(self):
        query = self.input_field.text().strip()
        if not query:
            return
        self.input_field.clear()
        self.process_query(query)

    def process_query(self, user_text: str):
        self.append_message("Jack", user_text, is_user=True)

        if self.handle_quick_actions(user_text):
            return

        if self.active_llm_worker and self.active_llm_worker.isRunning():
            self.active_llm_worker.requestInterruption()
            self.active_llm_worker.wait(300)

        self.set_system_status("THINKING // COMPUTING", state="THINKING")
        self.current_assistant_bubble = self.append_message("Esperanza", "", is_user=False)

        self.active_llm_worker = LLMWorker(
            model_choice=self.current_model,
            system_prompt=self.system_prompt,
            history=self.history,
            user_query=user_text,
            parent=self
        )
        self.active_llm_worker.token_received.connect(self.on_token_received)
        self.active_llm_worker.finished_response.connect(self.on_llm_finished)
        self.active_llm_worker.error_occurred.connect(self.on_llm_error)
        self.active_llm_worker.start()

    def on_token_received(self, token: str):
        if self.current_assistant_bubble:
            self.current_assistant_bubble.append_text(token)
            self.scroll_to_bottom()

    def on_llm_finished(self, full_response: str):
        self.set_system_status("IDLE // READY", state="IDLE")
        last_user = ""
        for i in reversed(range(self.chat_layout.count())):
            item = self.chat_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), ChatBubble) and item.widget().is_user:
                last_user = item.widget().msg_lbl.text()
                break
        if last_user:
            self.history.append({"role": "user", "content": last_user})
            self.history.append({"role": "assistant", "content": full_response})

        if self.voice_enabled and full_response:
            self.speak(full_response)

    def on_llm_error(self, err_msg: str):
        self.set_system_status("LLM ERROR", state="IDLE")
        if self.current_assistant_bubble:
            self.current_assistant_bubble.append_text(f"\n[Error: {err_msg}]")

    def speak(self, text: str):
        if not self.voice_enabled or not self.kokoro or not text.strip():
            return
        if self.active_tts_worker and self.active_tts_worker.isRunning():
            sd.stop()
            self.active_tts_worker.requestInterruption()
            self.active_tts_worker.wait(300)

        self.set_system_status("VOCALIZING // KOKORO TTS", state="SPEAKING")
        self.active_tts_worker = TTSWorker(self.kokoro, text, voice=self.current_voice, parent=self)
        self.active_tts_worker.finished_speaking.connect(lambda: self.set_system_status("IDLE // READY", state="IDLE"))
        self.active_tts_worker.start()

    def toggle_tts_output(self):
        self.voice_enabled = not self.voice_enabled
        if self.voice_enabled:
            self.tts_toggle_btn.setText("🔊 VOICE: ON")
            self.tts_toggle_btn.setStyleSheet(f"color: {CLR_CYAN};")
            self.speak("Audio output activated.")
        else:
            self.tts_toggle_btn.setText("🔇 VOICE: OFF")
            self.tts_toggle_btn.setStyleSheet(f"color: {CLR_TEXT_MUTED};")

    def toggle_mic_listening(self):
        if self.voice_btn.isChecked():
            if self.active_voice_worker and self.active_voice_worker.isRunning():
                self.active_voice_worker.requestInterruption()
                self.active_voice_worker.wait(300)
            self.set_system_status("LISTENING // MICROPHONE", state="LISTENING")
            self.active_voice_worker = VoiceRecognitionWorker(parent=self)
            self.active_voice_worker.heard_speech.connect(self.on_speech_heard)
            self.active_voice_worker.status_msg.connect(lambda msg: self.set_system_status(msg, state="LISTENING"))
            self.active_voice_worker.finished_listening.connect(self.on_mic_finished)
            self.active_voice_worker.start()
        else:
            if self.active_voice_worker and self.active_voice_worker.isRunning():
                self.active_voice_worker.requestInterruption()
            self.set_system_status("IDLE // READY", state="IDLE")

    def closeEvent(self, event):
        """Safely clean up all sound and threads when closing the window."""
        try:
            sd.stop()
            for worker in [self.active_tts_worker, self.active_llm_worker, self.active_voice_worker]:
                if worker and worker.isRunning():
                    worker.requestInterruption()
                    worker.wait(300)
                    if worker.isRunning():
                        worker.terminate()
                        worker.wait(100)
        except Exception:
            pass
        event.accept()

    def on_speech_heard(self, text: str):
        self.process_query(text)

    def on_mic_finished(self):
        self.voice_btn.setChecked(False)
        self.set_system_status("IDLE // READY", state="IDLE")

    # -------------------------------------------------------------------------
    # Quick Commands & Sci-Fi Ribbon Handlers
    # -------------------------------------------------------------------------
    def cmd_start_kobold(self):
        """Launch KoboldCpp with Vulkan GPU acceleration."""
        script_path = BASE_DIR / "launch_kobold_vulkan.sh"
        if script_path.exists():
            subprocess.Popen([str(script_path)])
            self.append_message("Esperanza", "🚀 Initializing KoboldCpp Vulkan GPU engine in background...", is_user=False)
            self.speak("Starting KoboldCpp with Vulkan GPU acceleration.")
            QTimer.singleShot(4500, self.populate_models)
        else:
            self.append_message("Esperanza", "Could not locate launch_kobold_vulkan.sh.", is_user=False)

    def handle_quick_actions(self, query: str):
        q = query.lower().strip()
        if "screenshot" in q:
            self.cmd_screenshot()
            return True
        elif any(w in q for w in ["system stats", "pc status", "hardware usage", "check system"]):
            self.cmd_system_stats()
            return True
        elif "weather" in q:
            self.cmd_weather()
            return True
        elif q.startswith("wikipedia "):
            topic = q.replace("wikipedia", "").strip()
            self.fetch_wikipedia(topic)
            return True
        elif any(w in q for w in ["volume up", "volume down", "mute audio"]):
            if "up" in q: self.cmd_volume("up")
            elif "down" in q: self.cmd_volume("down")
            elif "mute" in q: self.cmd_volume("mute")
            return True
        return False

    def cmd_system_stats(self):
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        ollama_ssd = "Mounted" if Path("/media/jack/OLLAMA_SSD").exists() else "Not found"
        boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
        uptime = round((datetime.datetime.now() - boot_time).total_seconds() / 3600, 1)

        msg = (
            f"⚡ **SYSTEM TELEMETRY REPORT** ⚡\n"
            f"• **CPU Utilization**: {cpu}%\n"
            f"• **RAM Memory**: {ram.percent}% ({round(ram.used / (1024**3), 1)} GB / {round(ram.total / (1024**3), 1)} GB)\n"
            f"• **Ubuntu SSD**: {disk.percent}% used ({round(disk.free / (1024**3), 1)} GB free)\n"
            f"• **OLLAMA SSD**: {ollama_ssd}\n"
            f"• **Workstation Uptime**: {uptime} hours\n"
            f"• **Active Brain Model**: {self.current_model}"
        )
        self.append_message("Esperanza", msg, is_user=False)
        self.speak(f"System status: CPU is at {cpu} percent, memory at {ram.percent} percent. All systems green.")

    def cmd_screenshot(self):
        try:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = SCREENSHOT_DIR / f"screenshot_{ts}.png"
            img = ImageGrab.grab()
            img.save(str(save_path))
            msg = f"📸 Full-screen capture saved to:\n`{save_path}`"
            self.append_message("Esperanza", msg, is_user=False)
            self.speak("Screenshot captured and stored.")
        except Exception as e:
            self.append_message("Esperanza", f"Screenshot capture error: {e}", is_user=False)

    def cmd_weather(self):
        try:
            r = requests.get("https://wttr.in/?format=%C+%t+(feels+like+%f),+humidity+%h,+wind+%w", timeout=5)
            if r.status_code == 200:
                report = r.text.strip()
                self.append_message("Esperanza", f"🌦 **Live Weather Report**:\n{report}", is_user=False)
                self.speak(f"Weather report: {report}")
                return
        except Exception as e:
            pass
        self.append_message("Esperanza", "Could not retrieve live weather feed.", is_user=False)

    def cmd_wikipedia(self):
        self.append_message("Esperanza", "Type 'wikipedia [topic]' or your question to research any topic.", is_user=False)

    def fetch_wikipedia(self, topic: str):
        try:
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(topic)}"
            r = requests.get(url, headers={"User-Agent": "EsperanzaJarvis/1.0"}, timeout=6)
            if r.status_code == 200:
                data = r.json()
                extract = data.get("extract", "No extract found.")
                self.append_message("Esperanza", f"📖 **Wikipedia: {topic.title()}**\n\n{extract}", is_user=False)
                self.speak(extract[:220])
                return
        except Exception as e:
            pass
        self.append_message("Esperanza", f"No Wikipedia entry located for '{topic}'.", is_user=False)

    def cmd_notes(self):
        if NOTES_FILE.exists():
            try:
                with open(NOTES_FILE, "r", encoding="utf-8") as f:
                    notes = json.load(f)
                if notes:
                    items = "\n".join([f"• [{n['time']}] {n['note']}" for n in notes])
                    self.append_message("Esperanza", f"📝 **Stored Memories & Notes**:\n{items}", is_user=False)
                    self.speak(f"You have {len(notes)} notes stored in memory.")
                    return
            except Exception:
                pass
        self.append_message("Esperanza", "No notes currently stored in memory.", is_user=False)

    def cmd_volume(self, action: str):
        try:
            if action == "up":
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"], check=True)
                msg = "Volume increased (+10%)."
            elif action == "down":
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"], check=True)
                msg = "Volume decreased (-10%)."
            elif action == "mute":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"], check=True)
                msg = "Audio mute toggled."
            self.set_system_status(msg, state="IDLE")
        except Exception as e:
            self.set_system_status(f"Volume error: {e}", state="IDLE")

    def cmd_clear_chat(self):
        self.history = []
        while self.chat_layout.count() > 1:
            child = self.chat_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.append_message("Esperanza", "Conversation history reset. System ready.", is_user=False)


# =============================================================================
# Entry Point
# =============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    font = QFont("Ubuntu", 10)
    app.setFont(font)

    window = JarvisWindow()
    window.show()
    sys.exit(app.exec())
