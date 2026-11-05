#!/usr/bin/env python3
"""
=============================================================================
 Jarvis_v1.py - Esperanza Jarvis AI Assistant
 Built for Jack | Powered by Ollama & Kokoro TTS | Linux Native
=============================================================================
"""

import os
import sys

# Limit CPU threads to 4
os.environ["OMP_NUM_THREADS"] = "4"
os.environ["MKL_NUM_THREADS"] = "4"
os.environ["OPENBLAS_NUM_THREADS"] = "4"
os.environ["NUMEXPR_NUM_THREADS"] = "4"

import time
import json
import uuid
import datetime
import threading
import subprocess
import requests
from pathlib import Path

# UI & Styling
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt
from rich.status import Status

# System monitoring
import psutil
from PIL import ImageGrab

# Audio & Speech
import sounddevice as sd
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
# Configuration & Paths
# =============================================================================
BASE_DIR = Path(__file__).resolve().parent
NOTES_FILE = BASE_DIR / "jarvis_notes.json"
SCREENSHOT_DIR = BASE_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

KOKORO_MODEL = "/home/jack/Desktop/Kokoro-TTS-Pause/kokoro-v1.0.onnx"
KOKORO_VOICES = "/home/jack/Desktop/Kokoro-TTS-Pause/voices-v1.0.bin"

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_MODEL = "esperanza:latest"
FALLBACK_MODEL = "llama3.2:3b"

console = Console()

# =============================================================================
# Kokoro TTS Engine (In-Memory, Low-Latency)
# =============================================================================
class TTSEngine:
    def __init__(self, voice="af_river", speed=1.05, enabled=True):
        self.voice = voice
        self.speed = speed
        self.enabled = enabled
        self.kokoro = None
        self._lock = threading.Lock()
        
        if KOKORO_AVAILABLE and Path(KOKORO_MODEL).exists() and Path(KOKORO_VOICES).exists():
            try:
                self.kokoro = Kokoro(KOKORO_MODEL, KOKORO_VOICES)
            except Exception as e:
                console.print(f"[dim yellow]Warning: Kokoro initialization deferred: {e}[/dim yellow]")

    def speak(self, text: str, block=True):
        """Synthesize and play speech in a separate thread or blocking."""
        if not self.enabled or not self.kokoro or not text.strip():
            return

        def _play():
            with self._lock:
                try:
                    # Clean out markdown symbols for clean reading
                    clean_text = text.replace("*", "").replace("#", "").replace("`", "").strip()
                    if not clean_text:
                        return
                    samples, sample_rate = self.kokoro.create(
                        clean_text,
                        voice=self.voice,
                        speed=self.speed,
                        lang="en-us"
                    )
                    sd.play(samples, sample_rate)
                    sd.wait()
                except Exception as err:
                    console.print(f"[dim red]TTS Playback Error: {err}[/dim red]")

        t = threading.Thread(target=_play, daemon=True)
        t.start()
        if block:
            t.join()


# =============================================================================
# Ollama Engine with Memory & Streaming
# =============================================================================
class OllamaEngine:
    def __init__(self, model_name=DEFAULT_MODEL, host=OLLAMA_HOST):
        self.host = host
        self.model_name = self._resolve_model(model_name)
        self.history = []
        self.system_prompt = (
            "You are Esperanza, Jack's loyal, sharp, warm, and highly capable Jarvis-like AI co-pilot. "
            "You run natively on his Linux workstation. Be direct, witty, and concise when answering queries, "
            "and provide code or analysis when asked. Always treat Jack as your visionary partner."
        )

    def _resolve_model(self, preferred):
        """Check if preferred model exists in Ollama; fallback if missing."""
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=30)
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                if preferred in models:
                    return preferred
                # Try without tag
                pref_base = preferred.split(":")[0]
                for m in models:
                    if m.startswith(pref_base):
                        return m
                if models:
                    return models[0]
        except Exception:
            pass
        return FALLBACK_MODEL

    def get_available_models(self):
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=30)
            if r.status_code == 200:
                return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            pass
        return []

    def clear_history(self):
        self.history = []

    def chat_stream(self, user_input: str):
        """Yield response tokens via Ollama streaming API with generous timeout."""
        messages = [{"role": "system", "content": self.system_prompt}]
        for item in self.history[-10:]:  # Keep recent context
            messages.append(item)
        messages.append({"role": "user", "content": user_input})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,
            "options": {
                "num_thread": 4,  # Cap CPU threads to 4
                "temperature": 0.7,
                "num_ctx": 4096
            }
        }

        full_reply = ""
        try:
            # Generous timeout: 900 seconds (15 minutes) for loading weights & processing
            with requests.post(f"{self.host}/api/chat", json=payload, stream=True, timeout=900) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if line:
                        chunk = json.loads(line.decode("utf-8"))
                        token = chunk.get("message", {}).get("content", "")
                        full_reply += token
                        yield token
                        if chunk.get("done", False):
                            break
            # Save history
            self.history.append({"role": "user", "content": user_input})
            self.history.append({"role": "assistant", "content": full_reply})
        except Exception as e:
            err_msg = f"[Ollama Connection Error: {e}]"
            yield err_msg


# =============================================================================
# System & Linux Tools
# =============================================================================
class JarvisTools:
    @staticmethod
    def get_system_stats():
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # Check OLLAMA_SSD if present
        ollama_ssd_text = "N/A"
        if Path("/media/jack/OLLAMA_SSD").exists():
            try:
                os_disk = psutil.disk_usage('/media/jack/OLLAMA_SSD')
                ollama_ssd_text = f"{os_disk.percent}% used ({round(os_disk.free / (1024**3), 1)} GB free)"
            except Exception:
                pass

        boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.datetime.now() - boot_time
        uptime_hours = round(uptime.total_seconds() / 3600, 1)

        return {
            "CPU Usage": f"{cpu}%",
            "RAM Usage": f"{ram.percent}% ({round(ram.used / (1024**3), 1)} / {round(ram.total / (1024**3), 1)} GB)",
            "Ubuntu SSD Root": f"{disk.percent}% used ({round(disk.free / (1024**3), 1)} GB free)",
            "OLLAMA SSD": ollama_ssd_text,
            "System Uptime": f"{uptime_hours} hours",
            "Time": datetime.datetime.now().strftime("%I:%M %p"),
            "Date": datetime.datetime.now().strftime("%A, %B %d, %Y")
        }

    @staticmethod
    def control_volume(action: str):
        """pactl volume control."""
        try:
            if "up" in action:
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"], check=True)
                return "Volume increased by 10%."
            elif "down" in action:
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"], check=True)
                return "Volume decreased by 10%."
            elif "mute" in action:
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"], check=True)
                return "Audio mute toggled."
            elif "%" in action:
                # e.g. "set volume to 50%"
                for word in action.split():
                    if "%" in word:
                        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", word], check=True)
                        return f"Volume set to {word}."
        except Exception as e:
            return f"Error controlling volume: {e}"
        return "Unknown volume command."

    @staticmethod
    def take_screenshot():
        """Capture screenshot and save to screenshots directory."""
        try:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = SCREENSHOT_DIR / f"screenshot_{ts}.png"
            img = ImageGrab.grab()
            img.save(str(save_path))
            return str(save_path)
        except Exception as e:
            return f"Screenshot failed: {e}"

    @staticmethod
    def get_weather(location=""):
        """Get fast weather info from wttr.in."""
        try:
            query = f"https://wttr.in/{location}?format=%C+%t+(feels+like+%f),+humidity+%h,+wind+%w"
            r = requests.get(query, timeout=5)
            if r.status_code == 200:
                return r.text.strip()
        except Exception as e:
            return f"Could not retrieve weather: {e}"
        return "Weather service unavailable."

    @staticmethod
    def get_wikipedia(topic: str):
        """Fetch summary from Wikipedia REST API."""
        try:
            clean_topic = topic.replace("wikipedia", "").replace("who is", "").replace("what is", "").strip()
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(clean_topic)}"
            r = requests.get(url, headers={"User-Agent": "EsperanzaJarvis/1.0"}, timeout=5)
            if r.status_code == 200:
                data = r.json()
                return data.get("extract", "No extract found.")
        except Exception as e:
            return f"Wikipedia query error: {e}"
        return f"Could not find Wikipedia results for '{topic}'."

    @staticmethod
    def open_app(app_name: str):
        """Open common Linux applications."""
        try:
            if "code" in app_name or "vscode" in app_name:
                subprocess.Popen(["code", "."])
                return "Opening VS Code in current workspace."
            elif "file" in app_name or "folder" in app_name or "document" in app_name:
                subprocess.Popen(["xdg-open", str(Path.home())])
                return "Opening Home folder."
            elif "browser" in app_name or "web" in app_name:
                subprocess.Popen(["xdg-open", "https://google.com"])
                return "Opening default web browser."
            elif "terminal" in app_name:
                subprocess.Popen(["x-terminal-emulator"])
                return "Opening new terminal session."
        except Exception as e:
            return f"Failed to open app: {e}"
        return f"Unknown application: {app_name}"

    @staticmethod
    def manage_notes(action="show", note=""):
        """Persistent notes file."""
        notes = []
        if NOTES_FILE.exists():
            try:
                with open(NOTES_FILE, "r", encoding="utf-8") as f:
                    notes = json.load(f)
            except Exception:
                notes = []

        if action == "add" and note:
            notes.append({
                "id": str(uuid.uuid4())[:8],
                "time": datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p"),
                "note": note
            })
            with open(NOTES_FILE, "w", encoding="utf-8") as f:
                json.dump(notes, f, indent=2)
            return f"Saved note: '{note}'"
        elif action == "clear":
            if NOTES_FILE.exists():
                NOTES_FILE.unlink()
            return "All notes cleared."
        else:
            return notes


# =============================================================================
# Esperanza Jarvis Core Assistant
# =============================================================================
class JarvisAssistant:
    def __init__(self):
        self.tts = TTSEngine(voice="af_river", speed=1.05, enabled=True)
        self.brain = OllamaEngine(model_name=DEFAULT_MODEL)
        self.voice_mode = False
        self.recognizer = sr.Recognizer() if SPEECH_REC_AVAILABLE else None

    def display_banner(self):
        console.clear()
        title_text = Text()
        title_text.append("★ ESPERANZA JARVIS v1.0 ★\n", style="bold magenta")
        title_text.append("Your Autonomous Pair-Programming AI Co-Pilot & Assistant\n", style="italic cyan")
        title_text.append(f"Model: {self.brain.model_name} | Voice: {self.tts.voice} ({'Enabled' if self.tts.enabled else 'Muted'})", style="dim white")
        
        banner_panel = Panel(
            title_text,
            border_style="bright_blue",
            padding=(1, 2)
        )
        console.print(banner_panel)
        console.print("[dim]Type your message or use commands: [bold cyan]/help[/bold cyan], [bold cyan]/voice[/bold cyan], [bold cyan]/mute[/bold cyan], [bold cyan]/model[/bold cyan], [bold cyan]/exit[/bold cyan][/dim]\n")

    def show_help(self):
        table = Table(title="Jarvis Commands & Voice Triggers", border_style="cyan")
        table.add_column("Command / Trigger", style="bold yellow")
        table.add_column("Description", style="white")
        
        table.add_row("/help", "Show this help table")
        table.add_row("/voice", "Toggle Voice Input mode (Microphone listening)")
        table.add_row("/text", "Switch back to text console mode")
        table.add_row("/mute or /unmute", "Toggle Kokoro TTS voice replies on/off")
        table.add_row("/model [name]", "Change current Ollama model or list them")
        table.add_row("/stats", "Show real-time system stats (CPU, RAM, SSD mounts)")
        table.add_row("/notes", "View saved notes and memories")
        table.add_row("/clear", "Reset conversation memory context")
        table.add_row("/exit or quit", "Shutdown Jarvis")
        table.add_row("--- Natural Triggers ---", "--- Handled Directly ---")
        table.add_row("'weather in [city]'", "Live forecast via wttr.in")
        table.add_row("'wikipedia [topic]'", "Quick Wikipedia summary")
        table.add_row("'volume up / down / mute'", "Adjust system audio volume")
        table.add_row("'take screenshot'", "Full-screen capture to ./screenshots")
        table.add_row("'remember that [fact]'", "Save persistent note")
        table.add_row("'open code / files / browser'", "Launch desktop applications")
        table.add_row("'timer [N] seconds/minutes'", "Set an alarm/reminder")
        
        console.print(table)

    def handle_quick_actions(self, user_text: str):
        """Execute built-in fast actions before hitting LLM."""
        query = user_text.lower().strip()

        # System statistics
        if any(w in query for w in ["system stats", "pc status", "hardware usage", "check system"]):
            stats = JarvisTools.get_system_stats()
            t = Table(title="System Status", border_style="green")
            t.add_column("Component", style="bold cyan")
            t.add_column("Metric", style="bold white")
            for k, v in stats.items():
                t.add_row(k, v)
            console.print(t)
            msg = f"System running smooth: CPU is at {stats['CPU Usage']} and RAM is at {stats['RAM Usage']}."
            self.tts.speak(msg, block=False)
            return True

        # Time / Date
        if query in ["what time is it", "time", "current time"]:
            now = datetime.datetime.now().strftime("%I:%M %p")
            console.print(f"[bold green]Current Time:[/bold green] {now}")
            self.tts.speak(f"The time is {now}", block=False)
            return True

        if query in ["what date is it", "date", "today's date"]:
            today = datetime.datetime.now().strftime("%A, %B %d, %Y")
            console.print(f"[bold green]Today's Date:[/bold green] {today}")
            self.tts.speak(f"Today is {today}", block=False)
            return True

        # Audio / Volume
        if any(w in query for w in ["volume up", "volume down", "mute", "unmute"]) or ("volume" in query and "%" in query):
            reply = JarvisTools.control_volume(query)
            console.print(f"[bold yellow]{reply}[/bold yellow]")
            self.tts.speak(reply, block=False)
            return True

        # Screenshot
        if "screenshot" in query:
            path = JarvisTools.take_screenshot()
            console.print(f"[bold green]Screenshot saved:[/bold green] {path}")
            self.tts.speak("Screenshot captured and saved.", block=False)
            return True

        # Weather
        if "weather" in query:
            location = query.replace("weather", "").replace("in", "").replace("for", "").strip()
            with Status("[cyan]Fetching weather...[/cyan]", console=console):
                info = JarvisTools.get_weather(location)
            console.print(f"[bold cyan]Weather Report:[/bold cyan] {info}")
            self.tts.speak(info, block=False)
            return True

        # Wikipedia
        if query.startswith("wikipedia") or "who was" in query or "who is" in query:
            clean_q = query.replace("wikipedia", "")
            with Status(f"[cyan]Searching Wikipedia for '{clean_q.strip()}'...[/cyan]", console=console):
                summary = JarvisTools.get_wikipedia(clean_q)
            console.print(Panel(summary, title=f"Wikipedia: {clean_q.title()}", border_style="blue"))
            self.tts.speak(summary[:250], block=False)
            return True

        # Notes / Memory
        if query.startswith("remember that ") or query.startswith("remember "):
            note = user_text[user_text.lower().find("remember") + 8:].replace("that", "").strip()
            msg = JarvisTools.manage_notes("add", note)
            console.print(f"[bold green]{msg}[/bold green]")
            self.tts.speak("Note memorized, Jack.", block=False)
            return True

        if any(w in query for w in ["what did i tell you to remember", "show notes", "show memory", "my notes"]):
            notes = JarvisTools.manage_notes("show")
            if not notes:
                console.print("[yellow]No notes stored yet.[/yellow]")
                self.tts.speak("You haven't stored any notes yet.", block=False)
            else:
                table = Table(title="Stored Notes & Memories", border_style="magenta")
                table.add_column("Date", style="dim cyan")
                table.add_column("Memory", style="white")
                for n in notes:
                    table.add_row(n["time"], n["note"])
                console.print(table)
                self.tts.speak(f"You have {len(notes)} notes saved in memory.", block=False)
            return True

        # Timer
        if query.startswith("timer ") or query.startswith("remind me in "):
            # Parse number
            words = query.split()
            seconds = 60
            for i, w in enumerate(words):
                if w.isdigit():
                    num = int(w)
                    if i + 1 < len(words) and "min" in words[i + 1]:
                        seconds = num * 60
                    else:
                        seconds = num
                    break

            def _timer_alert():
                time.sleep(seconds)
                console.print(f"\n[bold red blink]🔔 TIMER ALERT:[/bold red blink] {seconds} seconds elapsed!")
                self.tts.speak(f"Jack, your {seconds} second timer is up!", block=True)

            threading.Thread(target=_timer_alert, daemon=True).start()
            msg = f"Timer set for {seconds} seconds."
            console.print(f"[bold green]{msg}[/bold green]")
            self.tts.speak(msg, block=False)
            return True

        # Open Apps
        if any(w in query for w in ["open code", "open vs code", "open browser", "open files", "open terminal"]):
            msg = JarvisTools.open_app(query)
            console.print(f"[bold green]{msg}[/bold green]")
            self.tts.speak(msg, block=False)
            return True

        return False

    def listen_microphone(self):
        """Listen to microphone using SpeechRecognition with ALSA suppression."""
        if not self.recognizer:
            console.print("[red]Speech recognition is unavailable in this environment.[/red]")
            return None

        with sr.Microphone() as source:
            console.print("[dim cyan]🎤 Listening... (Speak now)[/dim cyan]")
            self.recognizer.adjust_for_ambient_noise(source, duration=0.6)
            try:
                audio = self.recognizer.listen(source, timeout=6, phrase_time_limit=10)
                console.print("[dim]Processing voice...[/dim]")
                query = self.recognizer.recognize_google(audio)
                return query
            except sr.WaitTimeoutError:
                return None
            except sr.UnknownValueError:
                console.print("[dim yellow]Could not understand audio.[/dim yellow]")
                return None
            except Exception as e:
                console.print(f"[dim red]Mic error: {e}[/dim red]")
                return None

    def process_query(self, user_input: str):
        """Process user input through quick actions or Ollama."""
        user_input = user_input.strip()
        if not user_input:
            return

        # Check built-in quick tools first
        if self.handle_quick_actions(user_input):
            return

        # Stream response from Ollama
        console.print(f"\n[bold magenta]Esperanza ({self.brain.model_name}):[/bold magenta]")
        full_reply = ""
        
        for token in self.brain.chat_stream(user_input):
            sys.stdout.write(token)
            sys.stdout.flush()
            full_reply += token

        sys.stdout.write("\n\n")
        sys.stdout.flush()

        # Speak concise summary or reply via Kokoro
        if self.tts.enabled and full_reply:
            # If reply is long, speak the first 2-3 sentences for snappiness
            sentences = [s.strip() for s in full_reply.split(".") if s.strip()]
            spoken_part = ". ".join(sentences[:2]) + "." if len(sentences) > 2 else full_reply
            self.tts.speak(spoken_part, block=False)

    def run(self):
        self.display_banner()
        self.tts.speak("Esperanza Jarvis online. Ready when you are, Jack.", block=False)

        while True:
            try:
                user_text = ""
                if self.voice_mode:
                    user_text = self.listen_microphone()
                    if not user_text:
                        continue
                    console.print(f"[bold cyan]Jack (Voice):[/bold cyan] {user_text}")
                else:
                    user_text = Prompt.ask("[bold cyan]Jack[/bold cyan]")

                clean = user_text.strip().lower()

                # Commands
                if clean in ["/exit", "exit", "quit", "/quit", "goodbye"]:
                    console.print("[magenta]Esperanza: Standing down. Have a great session, Jack![/magenta]")
                    self.tts.speak("Goodbye, Jack.", block=True)
                    break

                elif clean == "/help":
                    self.show_help()
                    continue

                elif clean == "/voice":
                    if not SPEECH_REC_AVAILABLE:
                        console.print("[red]Microphone input is not supported (PyAudio / SpeechRecognition missing).[/red]")
                    else:
                        self.voice_mode = not self.voice_mode
                        status = "ACTIVATED" if self.voice_mode else "DEACTIVATED"
                        console.print(f"[bold green]Voice Mode {status}.[/bold green]")
                        self.tts.speak(f"Voice mode {status.lower()}.", block=False)
                    continue

                elif clean == "/text":
                    self.voice_mode = False
                    console.print("[bold green]Switched to Text Mode.[/bold green]")
                    continue

                elif clean in ["/mute", "mute audio", "silence"]:
                    self.tts.enabled = False
                    console.print("[yellow]Audio replies MUTED.[/yellow]")
                    continue

                elif clean in ["/unmute", "unmute audio"]:
                    self.tts.enabled = True
                    console.print("[green]Audio replies UNMUTED.[/green]")
                    self.tts.speak("Audio enabled.", block=False)
                    continue

                elif clean.startswith("/model"):
                    parts = user_text.split()
                    if len(parts) > 1:
                        target_model = parts[1]
                        available = self.brain.get_available_models()
                        if target_model in available:
                            self.brain.model_name = target_model
                            console.print(f"[bold green]Switched model to:[/bold green] {target_model}")
                            self.tts.speak(f"Model switched to {target_model}.", block=False)
                        else:
                            console.print(f"[red]Model '{target_model}' not found in Ollama.[/red]")
                            console.print(f"Available: {', '.join(available)}")
                    else:
                        models = self.brain.get_available_models()
                        console.print(f"[cyan]Active Model:[/cyan] [bold]{self.brain.model_name}[/bold]")
                        console.print(f"[cyan]Installed Models:[/cyan] {', '.join(models)}")
                    continue

                elif clean == "/stats":
                    self.handle_quick_actions("system stats")
                    continue

                elif clean == "/notes":
                    self.handle_quick_actions("show notes")
                    continue

                elif clean == "/clear":
                    self.brain.clear_history()
                    console.print("[yellow]Conversation history cleared.[/yellow]")
                    continue

                # Process the query
                self.process_query(user_text)

            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Session interrupted. Goodbye, Jack![/yellow]")
                break
            except Exception as e:
                console.print(f"[bold red]Unexpected Error:[/bold red] {e}")


# =============================================================================
# Main Entry Point
# =============================================================================
if __name__ == "__main__":
    assistant = JarvisAssistant()
    assistant.run()
