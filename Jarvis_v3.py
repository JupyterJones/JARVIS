#!/usr/bin/env python3
"""
=============================================================================
 Jarvis_v3.py - Stark Industries Holographic HUD Assistant (Esperanza Edition)
 Inspired by Iron Man J.A.R.V.I.S. UI | PySide6 Hardware Rendered HUD
 Dual Ollama & KoboldCpp GGUF | Kokoro Neural TTS | 4-Thread CPU Capped
=============================================================================
"""

import os
import sys

# Strictly limit CPU thread usage to 4 threads to prevent overloading Ryzen 5 3400G
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
    QProgressBar, QSizePolicy, QGraphicsDropShadowEffect, QGridLayout
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, Slot, QPointF, QRectF
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QRadialGradient, QLinearGradient,
    QFont, QIcon, QPainterPath, QPolygonF
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

# Stark HUD Color Palette (from jarvis.png reference)
HUD_BG = "#02060f"
HUD_PANEL = "rgba(4, 12, 28, 0.88)"
HUD_BORDER = "#00d8f6"
HUD_BORDER_FAINT = "rgba(0, 216, 246, 0.28)"
HUD_CYAN = "#00f0ff"
HUD_CYAN_GLOW = "rgba(0, 240, 255, 0.6)"
HUD_BLUE = "#0077ff"
HUD_GREEN = "#00ff9d"
HUD_AMBER = "#ffaa00"
HUD_RED = "#ff2a55"
HUD_TEXT = "#dcf8ff"
HUD_TEXT_MUTED = "#527e99"

# =============================================================================
# Stark Industries Arc Reactor Widget (Centerpiece from jarvis.png)
# =============================================================================
class StarkArcReactor(QWidget):
    """Cinematic Iron Man Mark VI Arc Reactor with Rotating Rings, Coils & Triangle Core."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(260, 260)
        self.angle_outer = 0.0
        self.angle_middle = 0.0
        self.angle_inner = 0.0
        self.radar_angle = 0.0
        self.pulse = 0.0
        self.pulse_dir = 1
        self.state = "IDLE"  # IDLE, LISTENING, THINKING, SPEAKING
        self.wave_bars = [math.sin(i * 0.3) for i in range(24)]

        # 40 FPS render loop
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(25)

    def set_state(self, state: str):
        self.state = state
        self.update()

    def update_animation(self):
        speed_mult = 3.0 if self.state == "THINKING" else (1.8 if self.state == "SPEAKING" else 1.0)
        
        self.angle_outer = (self.angle_outer + 0.6 * speed_mult) % 360
        self.angle_middle = (self.angle_middle - 0.9 * speed_mult) % 360
        self.angle_inner = (self.angle_inner + 1.2 * speed_mult) % 360
        self.radar_angle = (self.radar_angle + 2.5 * speed_mult) % 360

        pulse_speed = 0.05 if self.state in ["THINKING", "SPEAKING", "LISTENING"] else 0.02
        self.pulse += pulse_speed * self.pulse_dir
        if self.pulse >= 1.0:
            self.pulse = 1.0
            self.pulse_dir = -1
        elif self.pulse <= 0.0:
            self.pulse = 0.0
            self.pulse_dir = 1

        if self.state in ["SPEAKING", "LISTENING"]:
            t = time.time() * 9
            self.wave_bars = [abs(math.sin(t + i * 0.35)) for i in range(24)]

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r_max = min(cx, cy) - 10

        # Colors based on state
        if self.state == "LISTENING":
            accent = QColor(HUD_GREEN)
            core_col = QColor(0, 255, 157, int(160 + 80 * self.pulse))
        elif self.state == "THINKING":
            accent = QColor(HUD_AMBER)
            core_col = QColor(255, 170, 0, int(170 + 80 * self.pulse))
        elif self.state == "SPEAKING":
            accent = QColor(HUD_CYAN)
            core_col = QColor(0, 240, 255, int(180 + 75 * self.pulse))
        else:
            accent = QColor(HUD_CYAN)
            core_col = QColor(0, 216, 246, int(110 + 70 * self.pulse))

        # 1. Subtle Outer Glow
        glow_grad = QRadialGradient(cx, cy, r_max)
        glow_grad.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), int(35 + 25 * self.pulse)))
        glow_grad.setColorAt(0.65, QColor(0, 119, 255, 20))
        glow_grad.setColorAt(1.0, QColor(2, 6, 15, 0))
        painter.setBrush(QBrush(glow_grad))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(cx, cy), r_max, r_max)

        # 2. Outer Dial with Compass Ticks & Cardinal Labels
        painter.save()
        painter.translate(cx, cy)
        pen_outer = QPen(QColor(0, 216, 246, 160), 1.2)
        painter.setPen(pen_outer)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(0, 0), r_max - 2, r_max - 2)

        # 36 Tick Marks (every 10 deg)
        for i in range(36):
            tick_len = 7 if (i % 9 == 0) else (4 if i % 3 == 0 else 2)
            painter.drawLine(0, int(-r_max + 2), 0, int(-r_max + 2 + tick_len))
            painter.rotate(10)
        painter.restore()

        # 3. Rotating Calipers Ring
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self.angle_outer)
        pen_caliper = QPen(accent, 1.8)
        pen_caliper.setDashPattern([14, 8, 4, 8])
        painter.setPen(pen_caliper)
        painter.drawEllipse(QPointF(0, 0), r_max - 12, r_max - 12)
        painter.restore()

        # 4. Middle Arc Reactor Coils (10 Glowing Induction Blocks)
        r_coils = r_max - 26
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self.angle_middle)
        coil_count = 10
        coil_angle = 360 / coil_count
        for _ in range(coil_count):
            coil_brush = QBrush(QColor(accent.red(), accent.green(), accent.blue(), int(130 + 80 * self.pulse)))
            painter.setBrush(coil_brush)
            painter.setPen(QPen(QColor(255, 255, 255, 200), 1.0))
            painter.drawRoundedRect(QRectF(-6, -r_coils, 12, 10), 2, 2)
            painter.rotate(coil_angle)
        painter.restore()

        # 5. Inner Dash Ring with Radar Sweep Line
        r_inner = r_max * 0.52
        painter.save()
        painter.translate(cx, cy)
        pen_inner = QPen(QColor(0, 119, 255, 180), 1.4)
        pen_inner.setDashPattern([6, 6])
        painter.setPen(pen_inner)
        painter.drawEllipse(QPointF(0, 0), r_inner, r_inner)

        # Radar Sweep Line
        painter.rotate(self.radar_angle)
        sweep_pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), 180), 1.5)
        painter.setPen(sweep_pen)
        painter.drawLine(0, 0, 0, int(-r_inner))
        painter.restore()

        # 6. Audio Waveform Arc (during voice or speaking)
        if self.state in ["SPEAKING", "LISTENING", "THINKING"]:
            painter.save()
            painter.translate(cx, cy)
            step = 360 / len(self.wave_bars)
            for val in self.wave_bars:
                bar_len = 4 + val * 18
                pen_bar = QPen(accent, 1.8)
                painter.setPen(pen_bar)
                painter.drawLine(0, int(-r_inner + 2), 0, int(-r_inner - bar_len))
                painter.rotate(step)
            painter.restore()

        # 7. Centerpiece: Stark Mark VI Inverted Triangle & Glowing Energy Core
        tri_size = r_inner * 0.72 + (2.5 * self.pulse)
        painter.save()
        painter.translate(cx, cy)

        # Core radial glow
        core_grad = QRadialGradient(0, 0, tri_size * 0.9)
        core_grad.setColorAt(0.0, QColor(255, 255, 255, 240))
        core_grad.setColorAt(0.4, accent)
        core_grad.setColorAt(0.85, core_col)
        core_grad.setColorAt(1.0, QColor(0, 119, 255, 20))
        painter.setBrush(QBrush(core_grad))
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1.5))

        # Inverted triangle polygon
        h_tri = tri_size * math.sqrt(3) / 2
        p1 = QPointF(0, h_tri * 0.6)
        p2 = QPointF(-tri_size * 0.6, -h_tri * 0.45)
        p3 = QPointF(tri_size * 0.6, -h_tri * 0.45)
        tri_poly = QPolygonF([p1, p2, p3])
        painter.drawPolygon(tri_poly)

        # Inner energy iris
        painter.setBrush(QBrush(QColor(255, 255, 255, int(180 + 75 * self.pulse))))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(0, -h_tri * 0.05), tri_size * 0.22, tri_size * 0.22)
        painter.restore()


# =============================================================================
# Rotating Mini Radar Scope (Left HUD Wing)
# =============================================================================
class MiniRadarWidget(QWidget):
    """Small tactical radar scope inspired by jarvis.png."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(130, 130)
        self.angle = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(35)

    def tick(self):
        self.angle = (self.angle + 3.0) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        r = min(cx, cy) - 6

        # Dark radar circle
        p.setBrush(QBrush(QColor(4, 14, 28, 220)))
        p.setPen(QPen(QColor(0, 216, 246, 120), 1.2))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.drawEllipse(QPointF(cx, cy), r * 0.66, r * 0.66)
        p.drawEllipse(QPointF(cx, cy), r * 0.33, r * 0.33)

        # Crosshairs
        p.setPen(QPen(QColor(0, 216, 246, 70), 1.0))
        p.drawLine(int(cx - r), int(cy), int(cx + r), int(cy))
        p.drawLine(int(cx), int(cy - r), int(cx), int(cy + r))

        # Sweep sector
        p.save()
        p.translate(cx, cy)
        p.rotate(self.angle)
        sweep_pen = QPen(QColor(HUD_CYAN), 1.6)
        p.setPen(sweep_pen)
        p.drawLine(0, 0, 0, int(-r))
        p.restore()

        # Target blip
        p.setBrush(QBrush(QColor(HUD_GREEN)))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx + r * 0.45, cy - r * 0.35), 3, 3)


# =============================================================================
# Background Workers (Strictly 4-Thread Capped)
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
                # Ollama Streaming Chat API (Strictly capped to 4 threads!)
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
                        "num_thread": 4,  # Strictly cap to 4 CPU threads
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
            self.status_msg.emit("LISTENING // ACTIVE RADAR MIC")
            with sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.6)
                if self.isInterruptionRequested():
                    return
                audio = self.recognizer.listen(source, timeout=8, phrase_time_limit=12)
                self.status_msg.emit("TRANSCRIBING VOICE...")
                text = self.recognizer.recognize_google(audio)
                if text and not self.isInterruptionRequested():
                    self.heard_speech.emit(text)
        except sr.WaitTimeoutError:
            self.status_msg.emit("LISTENING TIMED OUT")
        except sr.UnknownValueError:
            self.status_msg.emit("AUDIO NOT UNDERSTOOD")
        except Exception as e:
            self.status_msg.emit(f"MIC ERROR: {e}")
        finally:
            self.finished_listening.emit()


# =============================================================================
# Sci-Fi Chat Message Bubble with Tech Brackets
# =============================================================================
class StarkChatBubble(QFrame):
    def __init__(self, sender: str, text: str, is_user=False, parent=None):
        super().__init__(parent)
        self.is_user = is_user
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)

        badge_col = HUD_BLUE if is_user else HUD_CYAN
        sender_lbl = QLabel(f"┌─[ {sender.upper()} ]")
        sender_lbl.setStyleSheet(f"color: {badge_col}; font-weight: bold; font-size: 11px; font-family: monospace; letter-spacing: 1.5px;")
        
        time_lbl = QLabel(datetime.datetime.now().strftime("%H:%M:%S") + " ─┐")
        time_lbl.setStyleSheet(f"color: {HUD_TEXT_MUTED}; font-size: 10px; font-family: monospace;")

        header.addWidget(sender_lbl)
        header.addStretch()
        header.addWidget(time_lbl)

        self.msg_lbl = QLabel(text)
        self.msg_lbl.setWordWrap(True)
        self.msg_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.msg_lbl.setStyleSheet(f"color: {HUD_TEXT}; font-size: 13px; font-family: 'Ubuntu Mono', monospace; line-height: 1.4;")

        layout.addLayout(header)
        layout.addWidget(self.msg_lbl)

        border_color = "rgba(0, 119, 255, 0.5)" if is_user else "rgba(0, 240, 255, 0.45)"
        bg_color = "rgba(6, 18, 38, 0.9)" if is_user else "rgba(3, 14, 30, 0.9)"

        self.setStyleSheet(f"""
            StarkChatBubble {{
                background: {bg_color};
                border: 1px solid {border_color};
                border-radius: 6px;
                margin-left: {40 if is_user else 0}px;
                margin-right: {0 if is_user else 40}px;
                margin-top: 4px;
                margin-bottom: 4px;
            }}
        """)

    def append_text(self, token: str):
        self.msg_lbl.setText(self.msg_lbl.text() + token)


# =============================================================================
# Main Stark Industries HUD Window (Jarvis v3)
# =============================================================================
class JarvisStarkWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("STARK INDUSTRIES // J.A.R.V.I.S. MARK III (ESPERANZA EDITION)")
        self.resize(1200, 840)
        self.setMinimumSize(1020, 700)

        # Kokoro TTS in-memory
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
        QTimer.singleShot(700, self.startup_greeting)

    def setup_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(18, 14, 18, 16)
        main_layout.setSpacing(12)

        # ---------------------------------------------------------------------
        # 1. Top HUD Banner (Inspired by jarvis.png)
        # ---------------------------------------------------------------------
        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(16, 8, 16, 8)

        # Left branding
        brand_box = QVBoxLayout()
        stark_lbl = QLabel("STARK INDUSTRIES // PROTOCOL 11")
        stark_lbl.setStyleSheet(f"color: {HUD_CYAN}; font-size: 14px; font-weight: bold; font-family: monospace; letter-spacing: 2px;")
        sub_lbl = QLabel("J.A.R.V.I.S. CORE ARCHITECTURE // ESPERANZA AI")
        sub_lbl.setStyleSheet(f"color: {HUD_TEXT_MUTED}; font-size: 9px; font-family: monospace; letter-spacing: 1.5px;")
        brand_box.addWidget(stark_lbl)
        brand_box.addWidget(sub_lbl)

        # Center Status Tag
        self.status_pill = QLabel("● SYSTEM IDLE // ALL CHANNELS SECURE")
        self.status_pill.setAlignment(Qt.AlignCenter)
        self.status_pill.setStyleSheet(f"""
            background: rgba(0, 240, 255, 0.12);
            color: {HUD_CYAN};
            border: 1px solid rgba(0, 240, 255, 0.4);
            border-radius: 4px;
            padding: 4px 16px;
            font-size: 11px;
            font-weight: bold;
            font-family: monospace;
            letter-spacing: 2px;
        """)

        # Right Telemetry Tag & Clock
        right_box = QVBoxLayout()
        right_box.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.clock_lbl = QLabel("00:00:00 AM")
        self.clock_lbl.setAlignment(Qt.AlignRight)
        self.clock_lbl.setStyleSheet(f"color: {HUD_CYAN}; font-size: 18px; font-weight: bold; font-family: monospace; letter-spacing: 2px;")
        self.date_lbl = QLabel("LOADING CALENDAR...")
        self.date_lbl.setAlignment(Qt.AlignRight)
        self.date_lbl.setStyleSheet(f"color: {HUD_TEXT_MUTED}; font-size: 10px; font-family: monospace;")
        right_box.addWidget(self.clock_lbl)
        right_box.addWidget(self.date_lbl)

        top_layout.addLayout(brand_box, stretch=2)
        top_layout.addWidget(self.status_pill, stretch=3)
        top_layout.addLayout(right_box, stretch=2)

        main_layout.addWidget(top_bar)

        # ---------------------------------------------------------------------
        # 2. Main Middle Workspace: Left HUD Wing + Center Reactor + Right Chat
        # ---------------------------------------------------------------------
        middle_layout = QHBoxLayout()
        middle_layout.setSpacing(14)

        # A. LEFT WING: Mini Radar + Telemetry Gauges (jarvis.png style)
        left_wing = QFrame()
        left_wing.setObjectName("hudPanel")
        left_wing.setFixedWidth(270)
        left_layout = QVBoxLayout(left_wing)
        left_layout.setContentsMargins(14, 12, 14, 12)
        left_layout.setSpacing(10)

        left_header = QLabel("┌─[ TACTICAL TELEMETRY ]")
        left_header.setStyleSheet(f"color: {HUD_CYAN}; font-size: 11px; font-weight: bold; font-family: monospace;")
        left_layout.addWidget(left_header)

        # Mini Radar
        radar_box = QHBoxLayout()
        radar_box.setAlignment(Qt.AlignCenter)
        self.radar = MiniRadarWidget(self)
        radar_box.addWidget(self.radar)
        left_layout.addLayout(radar_box)

        # Hardware metrics (4-thread capped CPU info)
        self.cpu_lbl = QLabel("CPU (4 THREADS): 0%")
        self.cpu_lbl.setStyleSheet(f"color: {HUD_TEXT}; font-size: 11px; font-family: monospace;")
        self.cpu_bar = QProgressBar()
        self.cpu_bar.setRange(0, 100)
        self.cpu_bar.setFixedHeight(5)
        self.cpu_bar.setTextVisible(False)

        self.ram_lbl = QLabel("RAM: 0%")
        self.ram_lbl.setStyleSheet(f"color: {HUD_TEXT}; font-size: 11px; font-family: monospace;")
        self.ram_bar = QProgressBar()
        self.ram_bar.setRange(0, 100)
        self.ram_bar.setFixedHeight(5)
        self.ram_bar.setTextVisible(False)

        self.storage_lbl = QLabel("SSD STORAGE: OK")
        self.storage_lbl.setStyleSheet(f"color: {HUD_TEXT_MUTED}; font-size: 10px; font-family: monospace;")

        self.uptime_lbl = QLabel("UPTIME: --")
        self.uptime_lbl.setStyleSheet(f"color: {HUD_TEXT_MUTED}; font-size: 10px; font-family: monospace;")

        left_layout.addWidget(self.cpu_lbl)
        left_layout.addWidget(self.cpu_bar)
        left_layout.addWidget(self.ram_lbl)
        left_layout.addWidget(self.ram_bar)
        left_layout.addWidget(self.storage_lbl)
        left_layout.addWidget(self.uptime_lbl)

        # Model selector dropdown
        model_header = QLabel("┌─[ NEURAL CORE SELECT ]")
        model_header.setStyleSheet(f"color: {HUD_CYAN}; font-size: 11px; font-weight: bold; font-family: monospace; margin-top: 8px;")
        left_layout.addWidget(model_header)

        self.model_combo = QComboBox()
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        left_layout.addWidget(self.model_combo)

        left_layout.addStretch()
        middle_layout.addWidget(left_wing)

        # B. CENTER HUD: Big Stark Arc Reactor
        center_wing = QFrame()
        center_wing.setObjectName("hudPanel")
        center_wing.setFixedWidth(290)
        center_layout = QVBoxLayout(center_wing)
        center_layout.setContentsMargins(10, 12, 10, 12)
        center_layout.setAlignment(Qt.AlignCenter)

        center_header = QLabel("┌─[ ARC REACTOR MARK VI ]")
        center_header.setStyleSheet(f"color: {HUD_CYAN}; font-size: 11px; font-weight: bold; font-family: monospace;")
        center_layout.addWidget(center_header)

        self.arc_reactor = StarkArcReactor(self)
        center_layout.addWidget(self.arc_reactor)

        reactor_stats = QLabel("OUTPUT: 3.2 GJ/s // STABLE\nVIBRANIUM CORE FREQ: 44.1 kHz")
        reactor_stats.setAlignment(Qt.AlignCenter)
        reactor_stats.setStyleSheet(f"color: {HUD_TEXT_MUTED}; font-size: 9px; font-family: monospace; letter-spacing: 1px;")
        center_layout.addWidget(reactor_stats)

        middle_layout.addWidget(center_wing)

        # C. RIGHT WING: Holographic Chat & Voice Interface
        right_wing = QFrame()
        right_wing.setObjectName("hudPanel")
        right_layout = QVBoxLayout(right_wing)
        right_layout.setContentsMargins(14, 12, 14, 12)
        right_layout.setSpacing(8)

        right_header = QLabel("┌─[ HOLOGRAPHIC TRANSCRIPT & CO-PILOT LOG ]")
        right_header.setStyleSheet(f"color: {HUD_CYAN}; font-size: 11px; font-weight: bold; font-family: monospace;")
        right_layout.addWidget(right_header)

        self.chat_scroll = QScrollArea()
        self.chat_scroll.setObjectName("chatScroll")
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(4, 4, 4, 4)
        self.chat_layout.setSpacing(8)
        self.chat_layout.addStretch()

        self.chat_scroll.setWidget(self.chat_container)
        right_layout.addWidget(self.chat_scroll, stretch=1)

        middle_layout.addWidget(right_wing, stretch=1)
        main_layout.addLayout(middle_layout, stretch=1)

        # ---------------------------------------------------------------------
        # 3. Sci-Fi Tactical Action Ribbon
        # ---------------------------------------------------------------------
        ribbon_frame = QFrame()
        ribbon_frame.setObjectName("ribbonBar")
        ribbon_layout = QHBoxLayout(ribbon_frame)
        ribbon_layout.setContentsMargins(8, 6, 8, 6)
        ribbon_layout.setSpacing(8)

        actions = [
            ("⚡ HUD STATS", self.cmd_system_stats),
            ("🚀 KOBOLD VULKAN", self.cmd_start_kobold),
            ("📸 SCREENSHOT", self.cmd_screenshot),
            ("🌦 WEATHER", self.cmd_weather),
            ("📖 ARCHIVE WIKI", self.cmd_wikipedia),
            ("📝 MEMORY BANK", self.cmd_notes),
            ("🔊 VOL +", lambda: self.cmd_volume("up")),
            ("🔉 VOL -", lambda: self.cmd_volume("down")),
            ("🔇 MUTE", lambda: self.cmd_volume("mute")),
            ("🧹 PURGE CONTEXT", self.cmd_clear_chat),
        ]

        for text, slot_func in actions:
            b = QPushButton(text)
            b.setObjectName("ribbonBtn")
            b.clicked.connect(slot_func)
            ribbon_layout.addWidget(b)

        main_layout.addWidget(ribbon_frame)

        # ---------------------------------------------------------------------
        # 4. Bottom Stark Input Console Dock
        # ---------------------------------------------------------------------
        input_dock = QFrame()
        input_dock.setObjectName("inputDock")
        input_layout = QHBoxLayout(input_dock)
        input_layout.setContentsMargins(10, 8, 10, 8)
        input_layout.setSpacing(10)

        # Mic Button
        self.voice_btn = QPushButton("🎙 RADAR MIC")
        self.voice_btn.setObjectName("voiceBtn")
        self.voice_btn.setCheckable(True)
        self.voice_btn.clicked.connect(self.toggle_mic_listening)

        # TTS Output Button
        self.tts_toggle_btn = QPushButton("🔊 VOICE: ON")
        self.tts_toggle_btn.setObjectName("ttsBtn")
        self.tts_toggle_btn.clicked.connect(self.toggle_tts_output)

        # Terminal Prompt Label
        prompt_lbl = QLabel("JACK >")
        prompt_lbl.setStyleSheet(f"color: {HUD_CYAN}; font-weight: bold; font-family: monospace; font-size: 13px;")

        # Input line
        self.input_field = QLineEdit()
        self.input_field.setObjectName("inputField")
        self.input_field.setPlaceholderText("Command Stark HUD or enter query (Ollama & KoboldCpp active)...")
        self.input_field.returnPressed.connect(self.send_message)

        # Send Button
        self.send_btn = QPushButton("TRANSMIT ➤")
        self.send_btn.setObjectName("sendBtn")
        self.send_btn.clicked.connect(self.send_message)

        input_layout.addWidget(self.voice_btn)
        input_layout.addWidget(self.tts_toggle_btn)
        input_layout.addWidget(prompt_lbl)
        input_layout.addWidget(self.input_field, stretch=1)
        input_layout.addWidget(self.send_btn)

        main_layout.addWidget(input_dock)

    def apply_styles(self):
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {HUD_BG};
            }}
            #topBar {{
                background: {HUD_PANEL};
                border: 1px solid {HUD_BORDER_FAINT};
                border-radius: 4px;
            }}
            #hudPanel {{
                background: {HUD_PANEL};
                border: 1px solid {HUD_BORDER_FAINT};
                border-radius: 4px;
            }}
            #ribbonBar {{
                background: rgba(3, 10, 24, 0.9);
                border: 1px solid {HUD_BORDER_FAINT};
                border-radius: 4px;
            }}
            #chatScroll {{
                background: rgba(2, 6, 16, 0.85);
                border: 1px solid rgba(0, 216, 246, 0.2);
                border-radius: 4px;
            }}
            #inputDock {{
                background: {HUD_PANEL};
                border: 1px solid {HUD_BORDER};
                border-radius: 4px;
            }}
            #inputField {{
                background: rgba(2, 8, 20, 0.95);
                border: 1px solid rgba(0, 240, 255, 0.35);
                border-radius: 3px;
                padding: 10px 14px;
                color: {HUD_TEXT};
                font-size: 13px;
                font-family: 'Ubuntu Mono', monospace;
            }}
            #inputField:focus {{
                border: 1.5px solid {HUD_CYAN};
                background: rgba(4, 14, 32, 0.95);
            }}
            #sendBtn {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0066cc, stop:1 #00f0ff);
                color: #02060f;
                font-weight: bold;
                font-size: 11px;
                font-family: monospace;
                border-radius: 3px;
                padding: 10px 18px;
                letter-spacing: 1px;
            }}
            #sendBtn:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0077ee, stop:1 #33ffff);
            }}
            #voiceBtn {{
                background: rgba(6, 20, 36, 0.9);
                border: 1px solid rgba(0, 255, 157, 0.5);
                color: {HUD_GREEN};
                font-weight: bold;
                font-size: 11px;
                font-family: monospace;
                border-radius: 3px;
                padding: 8px 14px;
            }}
            #voiceBtn:checked {{
                background: rgba(255, 42, 85, 0.35);
                border: 1.5px solid {HUD_RED};
                color: {HUD_RED};
            }}
            #ttsBtn {{
                background: rgba(6, 20, 36, 0.9);
                border: 1px solid rgba(0, 240, 255, 0.4);
                color: {HUD_CYAN};
                font-weight: bold;
                font-size: 11px;
                font-family: monospace;
                border-radius: 3px;
                padding: 8px 14px;
            }}
            #ribbonBtn {{
                background: rgba(5, 16, 32, 0.85);
                border: 1px solid rgba(0, 216, 246, 0.28);
                color: {HUD_TEXT};
                font-size: 10px;
                font-family: monospace;
                font-weight: bold;
                border-radius: 3px;
                padding: 6px 10px;
                letter-spacing: 0.5px;
            }}
            #ribbonBtn:hover {{
                background: rgba(0, 240, 255, 0.22);
                border: 1px solid {HUD_CYAN};
                color: #ffffff;
            }}
            QProgressBar {{
                background-color: rgba(3, 10, 24, 0.8);
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0066cc, stop:1 #00f0ff);
                border-radius: 2px;
            }}
            QComboBox {{
                background: rgba(4, 14, 30, 0.95);
                border: 1px solid rgba(0, 240, 255, 0.4);
                border-radius: 3px;
                color: {HUD_CYAN};
                padding: 5px 8px;
                font-size: 11px;
                font-family: monospace;
            }}
            QComboBox QAbstractItemView {{
                background: #040e20;
                color: {HUD_TEXT};
                selection-background-color: #0066cc;
                border: 1px solid {HUD_CYAN};
            }}
            QScrollBar:vertical {{
                background: rgba(2, 6, 15, 0.6);
                width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(0, 240, 255, 0.35);
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {HUD_CYAN};
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
        self.clock_lbl.setText(now.strftime("%H:%M:%S"))
        self.date_lbl.setText(now.strftime("%A, %d %B %Y").upper())

        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        self.cpu_lbl.setText(f"CPU (4 THREADS): {cpu}%")
        self.cpu_bar.setValue(int(cpu))
        self.ram_lbl.setText(f"RAM: {ram.percent}% ({round(ram.used / (1024**3), 1)}/{round(ram.total / (1024**3), 1)}G)")
        self.ram_bar.setValue(int(ram.percent))

        disk = psutil.disk_usage('/')
        ollama_status = "OLLAMA SSD: ON" if Path("/media/jack/OLLAMA_SSD").exists() else "OLLAMA SSD: OFF"
        self.storage_lbl.setText(f"UBUNTU SSD: {disk.percent}% // {ollama_status}")

        boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
        uptime_h = round((datetime.datetime.now() - boot_time).total_seconds() / 3600, 1)
        self.uptime_lbl.setText(f"KERNEL UPTIME: {uptime_h} HOURS")

    def populate_models(self):
        models = []
        # Probe KoboldCpp
        try:
            rk = requests.get(f"{KOBOLD_HOST}/api/v1/model", timeout=2)
            if rk.status_code == 200:
                mname = rk.json().get("result", "Llama-GGUF")
                models.append(f"⚡ Kobold: {mname}")
        except Exception:
            pass

        # Probe Ollama
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
            self.status_pill.setText(f"● MODEL ENGAGED // {disp.upper()}")

    def set_system_status(self, text: str, state="IDLE"):
        self.status_pill.setText(f"● {text.upper()}")
        self.arc_reactor.set_state(state)

    # -------------------------------------------------------------------------
    # Chat & Messaging Core
    # -------------------------------------------------------------------------
    def startup_greeting(self):
        welcome = (
            "Stark Industries Mark III HUD online. Welcome back, Jack. "
            "All systems operational, dual Ollama and KoboldCpp GGUF channels active, "
            "and compute locked to 4 threads."
        )
        self.append_message("Esperanza", welcome, is_user=False)
        self.speak(welcome)

    def append_message(self, sender: str, text: str, is_user=False):
        bubble = StarkChatBubble(sender, text, is_user=is_user)
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

        self.set_system_status("THINKING // NEURAL COMPUTE (4 THREADS)", state="THINKING")
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
        self.set_system_status("SYSTEM IDLE // READY", state="IDLE")
        last_user = ""
        for i in reversed(range(self.chat_layout.count())):
            item = self.chat_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), StarkChatBubble) and item.widget().is_user:
                last_user = item.widget().msg_lbl.text()
                break
        if last_user:
            self.history.append({"role": "user", "content": last_user})
            self.history.append({"role": "assistant", "content": full_response})

        if self.voice_enabled and full_response:
            self.speak(full_response)

    def on_llm_error(self, err_msg: str):
        self.set_system_status("CORE ERROR", state="IDLE")
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
        self.active_tts_worker.finished_speaking.connect(lambda: self.set_system_status("SYSTEM IDLE // READY", state="IDLE"))
        self.active_tts_worker.start()

    def toggle_tts_output(self):
        self.voice_enabled = not self.voice_enabled
        if self.voice_enabled:
            self.tts_toggle_btn.setText("🔊 VOICE: ON")
            self.tts_toggle_btn.setStyleSheet(f"color: {HUD_CYAN};")
            self.speak("Audio channel online.")
        else:
            self.tts_toggle_btn.setText("🔇 VOICE: OFF")
            self.tts_toggle_btn.setStyleSheet(f"color: {HUD_TEXT_MUTED};")

    def toggle_mic_listening(self):
        if self.voice_btn.isChecked():
            if self.active_voice_worker and self.active_voice_worker.isRunning():
                self.active_voice_worker.requestInterruption()
                self.active_voice_worker.wait(300)
            self.set_system_status("RADAR MIC // LISTENING", state="LISTENING")
            self.active_voice_worker = VoiceRecognitionWorker(parent=self)
            self.active_voice_worker.heard_speech.connect(self.on_speech_heard)
            self.active_voice_worker.status_msg.connect(lambda msg: self.set_system_status(msg, state="LISTENING"))
            self.active_voice_worker.finished_listening.connect(self.on_mic_finished)
            self.active_voice_worker.start()
        else:
            if self.active_voice_worker and self.active_voice_worker.isRunning():
                self.active_voice_worker.requestInterruption()
            self.set_system_status("SYSTEM IDLE // READY", state="IDLE")

    def on_speech_heard(self, text: str):
        self.process_query(text)

    def on_mic_finished(self):
        self.voice_btn.setChecked(False)
        self.set_system_status("SYSTEM IDLE // READY", state="IDLE")

    # -------------------------------------------------------------------------
    # Quick Commands & Sci-Fi Ribbon Handlers
    # -------------------------------------------------------------------------
    def cmd_start_kobold(self):
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
        
        ollama_ssd = "Mounted (/media/jack/OLLAMA_SSD)" if Path("/media/jack/OLLAMA_SSD").exists() else "Not found"
        boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
        uptime = round((datetime.datetime.now() - boot_time).total_seconds() / 3600, 1)

        msg = (
            f"⚡ **STARK HUD TELEMETRY REPORT** ⚡\n\n"
            f"• **CPU THREAD ALLOCATION**: 4 Cores Locked (Total Load: {cpu}%)\n"
            f"• **RAM UTILIZATION**: {ram.percent}% ({round(ram.used / (1024**3), 1)} GB / {round(ram.total / (1024**3), 1)} GB)\n"
            f"• **UBUNTU SSD**: {disk.percent}% used ({round(disk.free / (1024**3), 1)} GB free)\n"
            f"• **OLLAMA SSD**: {ollama_ssd}\n"
            f"• **WORKSTATION UPTIME**: {uptime} Hours\n"
            f"• **ACTIVE NEURAL ENGINE**: {self.current_model}"
        )
        self.append_message("Esperanza", msg, is_user=False)
        self.speak(f"Telemetry report: CPU is at {cpu} percent, memory at {ram.percent} percent. All systems green.")

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
                self.append_message("Esperanza", f"🌦 **Atmospheric Feed**:\n{report}", is_user=False)
                self.speak(f"Weather report: {report}")
                return
        except Exception as e:
            pass
        self.append_message("Esperanza", "Could not retrieve live weather feed.", is_user=False)

    def cmd_wikipedia(self):
        self.append_message("Esperanza", "Type 'wikipedia [topic]' to query the global archives.", is_user=False)

    def fetch_wikipedia(self, topic: str):
        try:
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(topic)}"
            r = requests.get(url, headers={"User-Agent": "EsperanzaJarvis/1.0"}, timeout=6)
            if r.status_code == 200:
                data = r.json()
                extract = data.get("extract", "No extract found.")
                self.append_message("Esperanza", f"📖 **Global Archive: {topic.title()}**\n\n{extract}", is_user=False)
                self.speak(extract[:220])
                return
        except Exception as e:
            pass
        self.append_message("Esperanza", f"No archive entry found for '{topic}'.", is_user=False)

    def cmd_notes(self):
        if NOTES_FILE.exists():
            try:
                with open(NOTES_FILE, "r", encoding="utf-8") as f:
                    notes = json.load(f)
                if notes:
                    items = "\n".join([f"• [{n['time']}] {n['note']}" for n in notes])
                    self.append_message("Esperanza", f"📝 **Memory Bank Entries**:\n{items}", is_user=False)
                    self.speak(f"You have {len(notes)} notes stored in memory.")
                    return
            except Exception:
                pass
        self.append_message("Esperanza", "Memory bank is currently empty.", is_user=False)

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
        self.append_message("Esperanza", "Context memory purged. All systems calibrated.", is_user=False)

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


# =============================================================================
# Entry Point
# =============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    font = QFont("Ubuntu Mono", 10)
    app.setFont(font)

    window = JarvisStarkWindow()
    window.show()
    sys.exit(app.exec())
