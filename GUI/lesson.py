# lesson.py — Personalized Lesson Screen with STT → LLM(stream) → TTS (Piper RAW)
# Deps (same as main.py):
#   pip install faster-whisper webrtcvad sounddevice piper-tts python-dotenv
#   sudo apt-get install alsa-utils
#   export PIPER_SR=24000
#
# Notes:
# - LLM handler is reused from main_app.llm (unchanged).
# - We only adjust the lesson-mode system messages to (a) ban emoji and (b) allow ~15% concise outside knowledge
#   while keeping ~85% grounded in the provided lesson text.
# - We strip any accidental emojis from streamed output before TTS/GUI.

import os
import json
import random
import threading
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from tkinter import font as tkfont
import re
import unicodedata
import time

from styles import configure_styles
from api_manager import APIManager  # fallback if needed

# -------------------- NEW: audio & stt deps --------------------
try:
    import sounddevice as sd
    import webrtcvad
    from faster_whisper import WhisperModel
except Exception as e:
    raise SystemExit(
        "Missing audio/STT deps. Run:\n"
        "  pip install faster-whisper webrtcvad sounddevice\n" + str(e)
    )

# -------------------- NEW: import PIPER paths from your module --------------------
import importlib.machinery, importlib.util
def _load_module_from_path(mod_name: str, file_path: str):
    loader = importlib.machinery.SourceFileLoader(mod_name, file_path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module

# Adjust path if needed (same as main.py)
TTS_MOD_PATH = "/home/robinglory/Desktop/Thesis/TTS/streaming_piper_gui.py"
ttsmod = _load_module_from_path("streaming_piper_gui", TTS_MOD_PATH)  # exposes PIPER_BIN, DEFAULT_VOICE

# -------------------- NEW: Piper persistent engine --------------------
import sys, shutil, subprocess, wave, struct, math, collections
def _voice_json_path(onnx_path: str)->str|None:
    base, _ = os.path.splitext(onnx_path)
    j = base + ".json"
    return j if os.path.isfile(j) else None

def _infer_sample_rate(onnx_path: str, default_sr: int = 22050)->int:
    env = os.environ.get("PIPER_SR")
    if env:
        try:
            return int(env)
        except:
            pass
    j = _voice_json_path(onnx_path)
    if j:
        try:
            with open(j, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if isinstance(meta, dict):
                if isinstance(meta.get("sample_rate"), int):
                    return int(meta["sample_rate"])
                if isinstance(meta.get("audio"), dict) and isinstance(meta["audio"].get("sample_rate"), int):
                    return int(meta["audio"]["sample_rate"])
        except Exception:
            pass
    return default_sr

def _find_piper_cmd(piper_bin_hint: str|None)->list[str]|None:
    if piper_bin_hint and os.path.isfile(piper_bin_hint) and os.access(piper_bin_hint, os.X_OK):
        return [piper_bin_hint]
    p = shutil.which("piper")
    if p: return [p]
    cand = os.path.join(sys.prefix, "bin", "piper")
    if os.path.isfile(cand) and os.access(cand, os.X_OK): return [cand]
    try:
        import piper  # noqa
        return [sys.executable, "-m", "piper"]
    except Exception:
        return None

class PiperEngine:
    """
    Persistent RAW pipeline:
      (text) → piper --output-raw → (PCM S16_LE mono) → aplay @ correct SR
    """
    def __init__(self, piper_bin: str, voice_onnx: str):
        if not os.path.isfile(voice_onnx):
            raise RuntimeError(f"Voice model not found: {voice_onnx}")
        self.voice = voice_onnx
        self.sr = _infer_sample_rate(voice_onnx, default_sr=22050)
        self._p1 = None
        self._p2 = None
        self._lock = threading.Lock()
        self._piper_cmd = _find_piper_cmd(piper_bin)
        if not self._piper_cmd:
            raise RuntimeError("piper CLI not found. Install with: pip install piper-tts")

    def start(self):
        aplay = shutil.which("aplay")
        if not aplay:
            raise RuntimeError("aplay not found. Install 'alsa-utils'.")
        cmd = self._piper_cmd + ["--model", self.voice, "--output-raw", "--sentence_silence", "0.25"]
        self._p1 = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1
        )
        self._p2 = subprocess.Popen(
            [aplay, "-r", str(self.sr), "-f", "S16_LE", "-t", "raw", "-c", "1"],
            stdin=self._p1.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, bufsize=0
        )
        self._p1.stdout.close()

    # smarter chunk writer: newline only on sentence ends
    def say_chunk(self, text: str, final: bool):
        if not text or not text.strip():
            return
        if not self._p1 or not self._p1.stdin:
            raise RuntimeError("Piper not started.")
        suffix = "\n" if final else " "
        with self._lock:
            try:
                self._p1.stdin.write(text.strip() + suffix)
                self._p1.stdin.flush()
            except BrokenPipeError:
                self.close(); self.start()
                self._p1.stdin.write(text.strip() + suffix)
                self._p1.stdin.flush()

    def say(self, text: str):
        self.say_chunk(text, final=True)

    def close(self):
        try:
            if self._p1 and self._p1.stdin and not self._p1.stdin.closed:
                self._p1.stdin.close()
        except Exception:
            pass
        try:
            if self._p2: self._p2.terminate()
        except Exception:
            pass
        try:
            if self._p1: self._p1.terminate()
        except Exception:
            pass
        self._p1 = None; self._p2 = None

# -------------------- NEW: VAD recorder (16k, mono) --------------------
class VADRecorder:
    """WebRTC VAD + energy gate; writes 16k mono WAV and returns its path."""
    def __init__(self, sample_rate=16000, frame_ms=30, vad_aggr=3,
                 silence_ms=2000, max_record_s=10, device=None,
                 energy_margin=2.0, energy_min=2200, energy_max=6000, energy_calib_ms=500):
        self.sample_rate=sample_rate; self.frame_ms=frame_ms; self.vad_aggr=vad_aggr
        self.silence_ms=silence_ms; self.max_record_s=max_record_s; self.device=device
        self.energy_margin=energy_margin; self.energy_min=energy_min; self.energy_max=energy_max; self.energy_calib_ms=energy_calib_ms

    @staticmethod
    def _rms_int16(b: bytes)->float:
        if not b: return 0.0
        n=len(b)//2
        if n<=0: return 0.0
        s=struct.unpack(f"<{n}h", b); acc=0
        for x in s: acc+=x*x
        return math.sqrt(acc/float(n))

    def record(self, out_wav: str) -> str:
        vad = webrtcvad.Vad(self.vad_aggr)
        frame_samp = int(self.sample_rate*(self.frame_ms/1000.0))
        frame_bytes = frame_samp*2
        silence_frames_needed = max(1,int(self.silence_ms/self.frame_ms))
        max_frames = int(self.max_record_s*1000/self.frame_ms)
        calib_frames = max(1,int(self.energy_calib_ms/self.frame_ms))
        ring=collections.deque(); voiced=False; trailing=0; total=0
        energy_thr=None; calib_vals=[]
        print(f"[VAD] start {self.sample_rate}Hz frame={self.frame_ms}ms agg={self.vad_aggr} stop>{self.silence_ms}ms")
        def _cb(indata, frames, time_info, status):
            nonlocal voiced, trailing, total, energy_thr
            buf=indata.tobytes()
            if len(buf)<frame_bytes: return
            ring.append(buf); total+=1
            if energy_thr is None and len(calib_vals)<calib_frames:
                calib_vals.append(self._rms_int16(buf))
                if len(calib_vals)==calib_frames:
                    base=sorted(calib_vals)[len(calib_vals)//2]
                    thr=max(self.energy_min,min(self.energy_max, base*self.energy_margin)); energy_thr=thr
                    print(f"\n[VAD] energy floor≈{int(base)} → thr≈{int(thr)}")
                return
            rms=self._rms_int16(buf)
            try:
                speech = vad.is_speech(buf,self.sample_rate)
            except Exception:
                speech=False
            if energy_thr is not None and rms<energy_thr:
                speech=False
            if speech:
                voiced=True; trailing=0
                print(f"\r[VAD] frames={total} rms={int(rms)} (speech)  ", end="")
            else:
                if voiced: trailing=min(silence_frames_needed,trailing+1)
                print(f"\r[VAD] frames={total} rms={int(rms)} (silence {trailing*self.frame_ms} ms)", end="")
        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype='int16', device=self.device,
                             blocksize=frame_samp, callback=_cb):
            while True:
                time.sleep(self.frame_ms/1000.0)
                if total>=max_frames:
                    print("\n[VAD] max time reached"); break
                if voiced and trailing>=silence_frames_needed:
                    print("\n[VAD] silence reached — stop"); break
        os.makedirs(os.path.dirname(out_wav), exist_ok=True)
        with wave.open(out_wav,'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(self.sample_rate)
            while ring: w.writeframes(ring.popleft())
        dur=total*self.frame_ms/1000.0
        print(f"[VAD] wrote {out_wav} (≈{dur:.2f}s)")
        return out_wav

# ---------- Simple JSON helpers ----------
def load_json(filepath):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ---------- Text cleanup helpers (ban emojis) ----------
_EMOJI_RE = re.compile(
    "["  # broad unicode ranges that commonly include emojis/symbols
    "\U0001F300-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U0001FB00-\U0001FBFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "\U00002B00-\U00002BFF"
    "]+",
    flags=re.UNICODE
)

def strip_emoji_and_extras(text: str) -> str:
    if not text:
        return text
    text = _EMOJI_RE.sub("", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cs")
    return re.sub(r"\s{2,}", " ", text).strip(" \t")

# ---------- Constants ----------
FW_BASE = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-base.en"
TEMP_WAV = "/tmp/fw_dialog_lesson.wav"

class LessonScreen:
    STUDENTS_JSON_PATH = "/home/robinglory/Desktop/Thesis/GUI/students.json"
    CONVERSATIONS_JSON_PATH = "/home/robinglory/Desktop/Thesis/GUI/conversations.json"

    def __init__(self, root, main_app, student_manager, lesson_type):
        self.root = root
        self.main_app = main_app
        self.student_manager = student_manager
        self.lesson_type = lesson_type
        self.current_lesson = main_app.current_lesson  # set by dashboard before opening

        # Use the SAME LLM pipeline as main.py (fast + streaming + hedge)
        self.llm = main_app.llm
        self._fallback_llm = None  # lazy: APIManager only if needed

        # Identify user/lesson for persistence
        self.user_id = str(self.student_manager.current_user.get("id", "default"))
        self.lesson_path = (self.current_lesson or {}).get("filepath", f"default_{lesson_type}")

        # Load persisted data
        self.conversation_data = load_json(self.CONVERSATIONS_JSON_PATH)
        self.students_data = load_json(self.STUDENTS_JSON_PATH)

        # Load or start fresh conversation
        self.conversation_history = self.conversation_data.get(self.user_id, {}).get(self.lesson_path, [])
        self.student_manager.conversation_history = self.conversation_history

        # Streaming plumbing
        self._stream_queue: queue.Queue = queue.Queue()
        self._stream_worker: threading.Thread | None = None
        self._streaming = False
        self._thinking_tagged = False
        self._thinking_start_index = None
        self._first_chunk_seen = False
        self._current_response_buffer = []  # accumulate streamed chunks

        # NEW: audio state
        self._stt_model: WhisperModel | None = None
        self._tts = None
        self._tts_q: queue.Queue[tuple[str, bool]] = queue.Queue(maxsize=64)  # (text, is_sentence_end)

        # Window config
        self.root.title(f"Lingo - AI Personal English Teacher ({lesson_type.capitalize()} Section)")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)
        self.root.configure(bg="#f8f9fa")

        # Fonts
        self.title_font = tkfont.Font(family="Segoe UI", size=14, weight="bold")
        self.content_font = tkfont.Font(family="Segoe UI", size=12)
        self.message_font = tkfont.Font(family="Segoe UI", size=11)

        configure_styles()
        self.create_widgets()
        self.load_lesson()

        # Init TTS and drain queue
        self._init_tts()
        self.root.after(20, self._drain_tts_queue)

    # ---------- UI ----------
    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=(20, 15))
        main_frame.pack(fill=tk.BOTH, expand=True)

        header_frame = ttk.Frame(main_frame, style="Header.TFrame")
        header_frame.pack(fill=tk.X, pady=(0, 20), ipady=10)

        ttk.Label(
            header_frame,
            text=f"Lingo - AI Personal English Teacher ({self.lesson_type.capitalize()} Section)",
            style="Header.TLabel"
        ).pack(side=tk.LEFT, padx=10)

        back_btn = ttk.Button(
            header_frame,
            text="◄ Back to Dashboard",
            command=self.return_to_dashboard,
            style="Accent.TButton"
        )
        back_btn.pack(side=tk.RIGHT, padx=10)

        chat_frame = ttk.Frame(main_frame, style="Chat.TFrame")
        chat_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        self.conversation_display = scrolledtext.ScrolledText(
            chat_frame,
            wrap=tk.WORD,
            font=self.content_font,
            height=18,
            padx=15,
            pady=15,
            state='disabled',
            bg="white",
            fg="#2d3436",
            bd=0,
            highlightthickness=0,
            insertbackground="#6c5ce7"
        )
        self.conversation_display.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        self.conversation_display.tag_config("title", font=self.title_font, foreground="#6c5ce7")
        self.conversation_display.tag_config("subtitle", font=("Segoe UI", 12, "bold"), foreground="#2d3436")
        self.conversation_display.tag_config("content", font=self.content_font)
        self.conversation_display.tag_config("ai", foreground="#6c5ce7", font=("Segoe UI", 12, "bold"))
        self.conversation_display.tag_config("user", foreground="#00b894", font=("Segoe UI", 12, "bold"))
        self.conversation_display.tag_config("message", font=("Segoe UI", 12), lmargin1=20, lmargin2=20, spacing3=5)

        input_frame = ttk.Frame(main_frame, style="Input.TFrame")
        input_frame.pack(fill=tk.X)

        # Status label (left)
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(input_frame, textvariable=self.status_var)
        self.status_label.pack(side=tk.LEFT, padx=(0, 10))

        self.user_input = ttk.Entry(input_frame, font=("Segoe UI", 12))
        self.user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.user_input.bind("<Return>", self.handle_input)

        # 🎤 Speak button (primary)
        self.speak_btn = ttk.Button(input_frame, text="🎤 Speak", command=self.on_speak, style="Accent.TButton")
        self.speak_btn.pack(side=tk.RIGHT, padx=(0, 10))
        self.speak_btn.focus_set()

        send_btn = ttk.Button(input_frame, text="Send", command=self.handle_input, style="Accent.TButton")
        send_btn.pack(side=tk.RIGHT)

        # Replay prior conversation
        for msg in self.conversation_history:
            sender = "You" if msg["role"] == "user" else "Lingo"
            self.display_message(sender, msg["content"])

    def set_status(self, txt: str):
        self.status_var.set(txt)
        self.root.update_idletasks()

    def load_lesson(self):
        try:
            if not self.student_manager or not self.student_manager.current_user:
                raise ValueError("Student information not available")

            lesson = self.student_manager.lesson_manager.get_lesson_by_type(
                self.student_manager.current_user["level"],
                self.lesson_type,
                self.student_manager.current_user
            )
            if not lesson:
                messagebox.showerror("Error", "Lesson content not found")
                self.root.destroy()
                return

            self.current_lesson_path = lesson.get("filepath")
            self.student_manager.current_lesson = lesson

            # Align conversation key with current lesson
            self.lesson_path = self.current_lesson_path or self.lesson_path
            self.conversation_data = load_json(self.CONVERSATIONS_JSON_PATH)
            self.conversation_history = self.conversation_data.get(self.user_id, {}).get(self.lesson_path, [])
            self.student_manager.conversation_history = self.conversation_history

            self.display_lesson_content(lesson)
            self.display_personalized_welcome(lesson)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load lesson: {str(e)}")
            self.root.destroy()

    def display_lesson_content(self, lesson):
        self.display_message("system", "=== LESSON CONTENT ===", is_lesson=True)
        self.display_message("system", f"Lesson: {lesson.get('title', 'English Practice')}", is_lesson=True)
        if "objective" in lesson:
            self.display_message("system", f"Objective: {lesson['objective']}", is_lesson=True)
        if "text" in lesson and lesson["text"]:
            self.display_message("system", lesson["text"], is_lesson=True)

    def display_personalized_welcome(self, lesson):
        student_name = self.student_manager.current_user["name"].split()[0]
        praise = random.choice([
            "You're making great progress by working on this!",
            "This will boost your English skills.",
            "I'm excited to guide you through this topic.",
            "This lesson will build your confidence."
        ])
        welcome_msg = (
            f"Hello {student_name}! I'm Lingo, Your Personal AI English Teacher.\n"
            f"Now it's time to learn {self.lesson_type.capitalize()}.\n"
            f"{praise}\n"
            f"Today we'll be working on: {lesson.get('title', 'English Practice')}\n"
        )
        if "objective" in lesson:
            welcome_msg += f"\nOur goal is: {lesson['objective']}"
        self.display_message("Lingo", welcome_msg)

    def display_message(self, sender, message, is_lesson=False):
        self.conversation_display.configure(state='normal')
        if is_lesson:
            self.conversation_display.insert(tk.END, f"\n{message}\n", "content")
        else:
            tag = "ai" if sender == "Lingo" else "user"
            self.conversation_display.insert(tk.END, f"\n{sender}: ", tag)
            self.conversation_display.insert(tk.END, f"{message}\n", "message")
        self.conversation_display.see(tk.END)
        self.conversation_display.configure(state='disabled')

    def return_to_dashboard(self):
        try:
            if getattr(self, "current_lesson_path", None) and self.student_manager:
                self.student_manager.lesson_manager.record_lesson_completion(
                    self.student_manager.current_user["name"],
                    self.student_manager.current_lesson
                )
                data = load_json(self.STUDENTS_JSON_PATH)
                if "_default" in data and self.user_id in data["_default"]:
                    user_data = data["_default"][self.user_id]
                    completed = user_data.get("completed_lessons", [])
                    if self.current_lesson_path not in completed:
                        completed.append(self.current_lesson_path)
                        user_data["completed_lessons"] = completed
                        save_json(self.STUDENTS_JSON_PATH, data)

            try:
                self.root.grab_release()
            except:
                pass

            if isinstance(self.root, tk.Toplevel):
                self.root.destroy()

            if hasattr(self.main_app, "dashboard"):
                self.main_app.dashboard.update_display()
            elif hasattr(self.main_app, "show_dashboard"):
                self.main_app.show_dashboard()

            if hasattr(self.main_app, "root"):
                self.main_app.root.deiconify()
                self.main_app.root.lift()
                self.main_app.root.focus_force()
        except Exception as e:
            print(f"Error returning to dashboard: {e}")

    # ---------- Streaming helpers ----------
    def _append_stream_text(self, text: str):
        self.conversation_display.configure(state='normal')
        self.conversation_display.insert(tk.END, text, "message")
        self.conversation_display.see(tk.END)
        self.conversation_display.configure(state='disabled')

    def _replace_thinking_header_if_needed(self):
        if self._first_chunk_seen or not self._thinking_tagged or self._thinking_start_index is None:
            return
        try:
            self.conversation_display.configure(state='normal')
            start = self._thinking_start_index
            end = f"{start} + {len('Lingo (Thinking…): ')}c"
            self.conversation_display.delete(start, end)
            self.conversation_display.insert(start, "Lingo: ", "ai")
            self.conversation_display.configure(state='disabled')
            self._first_chunk_seen = True
        except Exception:
            pass

    def _drain_stream_queue(self):
        try:
            while True:
                chunk = self._stream_queue.get_nowait()
                if chunk is None:
                    self._streaming = False
                    if not self._first_chunk_seen and self._thinking_tagged and self._thinking_start_index:
                        self._replace_thinking_header_if_needed()
                    self._append_stream_text("\n")
                    self.root.config(cursor="")

                    # Persist full assistant message to history
                    full_assistant = "".join(self._current_response_buffer).strip()
                    if full_assistant:
                        self.student_manager.conversation_history.append(
                            {"role": "assistant", "content": full_assistant}
                        )

                    # Save updated conversation
                    self.conversation_data.setdefault(self.user_id, {})
                    self.conversation_data[self.user_id][self.lesson_path] = self.student_manager.conversation_history
                    save_json(self.CONVERSATIONS_JSON_PATH, self.conversation_data)
                    self._current_response_buffer.clear()
                    return
                else:
                    if not self._first_chunk_seen:
                        self._replace_thinking_header_if_needed()
                    self._current_response_buffer.append(chunk)
                    self._append_stream_text(chunk)
        except queue.Empty:
            pass
        if self._streaming:
            self.root.after(15, self._drain_stream_queue)

    # ---------- Audio helpers ----------
    def _init_tts(self):
        try:
            self._tts = PiperEngine(ttsmod.PIPER_BIN, ttsmod.DEFAULT_VOICE)
            self._tts.start()
        except Exception as e:
            print("[TTS] init error:", e)

    def _ensure_stt(self):
        if self._stt_model is not None: return
        model_dir = FW_BASE
        if not os.path.isdir(model_dir):
            raise RuntimeError(f"STT model folder not found: {model_dir}")
        os.environ.setdefault("OMP_NUM_THREADS","4")
        print(f"[STT] Loading model: {model_dir} (int8)")
        t0=time.perf_counter()
        self._stt_model = WhisperModel(model_dir, device="cpu", compute_type="int8")
        print(f"[STT] Ready in {time.perf_counter()-t0:.2f}s")

    def _drain_tts_queue(self):
        try:
            item = self._tts_q.get_nowait()
        except queue.Empty:
            pass
        else:
            try:
                if self._tts:
                    text, is_final = item
                    self._tts.say_chunk(text, final=is_final)
                    self.set_status("Speaking…")
            except Exception as e:
                print("[TTS] error:", e)
        self.root.after(20, self._drain_tts_queue)

    # ---------- Input handling (typed) ----------
    def handle_input(self, event=None):
        if self._streaming:
            return

        user_input = self.user_input.get().strip()
        if not user_input:
            return

        self.display_message("You", user_input)
        self.user_input.delete(0, tk.END)

        try:
            # Build lesson-aware prompts (keep original style; add 85/15 + no-emoji)
            lesson = self.student_manager.current_lesson or {}
            lesson_title = lesson.get("title", "")
            lesson_type = self.lesson_type
            lesson_objective = lesson.get("objective", "")
            lesson_text = lesson.get("text", "") or ""

            LESSON_SLICE_LIMIT = int(os.getenv("LESSON_SLICE", "4000"))
            lesson_slice = lesson_text[:LESSON_SLICE_LIMIT]

            print("[Lesson] type:", lesson_type, "| title:", lesson_title)
            print("[Lesson] path:", getattr(self, "current_lesson_path", None))
            print("[Lesson] slice[0:160]:", lesson_slice[:160].replace("\n", " "))
            if not lesson_slice.strip():
                print("[Lesson] WARNING: lesson text is empty for this section.")

            system_rules = (
                "You are Lingo, a personal English tutor.\n"
                "You are teaching the following LESSON. Follow these rules:\n"
                "• Ground your response ~85% in the LESSON TEXT below (quote or paraphrase it).\n"
                "• You may add ~15% brief, relevant outside knowledge to improve understanding, but do not contradict the LESSON TEXT.\n"
                "• If the LESSON TEXT does not contain the needed info, say: \"The lesson text doesn’t say yet.\" and ask a short guiding question.\n"
                "• Keep responses short (≤2 sentences, ≤60 words) and end with one short question.\n"
                "• Do not use emojis. Do not use the '*' character.\n"
                "• Match the lesson type (Reading/Grammar/Vocabulary):\n"
                "  - Reading: brief, text-based explanation + one comprehension question.\n"
                "  - Grammar: explain only rules/examples present in the text.\n"
                "  - Vocabulary: define/illustrate only words appearing in the text.\n"
            )

            lesson_header = (
                f"LESSON METADATA:\n"
                f"Title: {lesson_title}\n"
                f"Type: {lesson_type}\n"
                f"Objective: {lesson_objective}\n"
            )

            lesson_payload = (
                "LESSON TEXT (authoritative; primary source):\n"
                "<<<BEGIN LESSON TEXT>>>\n"
                f"{lesson_slice}\n"
                "<<<END LESSON TEXT>>>\n"
            )

            recent_history = self.student_manager.conversation_history[-6:] if self.student_manager.conversation_history else []

            messages = [
                {"role": "system", "content": system_rules},
                {"role": "system", "content": lesson_header + "\n" + lesson_payload},
            ]
            messages.extend(recent_history)
            messages.append({"role": "user", "content": user_input})

            # Start streaming
            self._streaming = True
            self._first_chunk_seen = False
            self._current_response_buffer.clear()
            self.root.config(cursor="watch")

            # Show status header
            self.conversation_display.configure(state='normal')
            self._thinking_start_index = self.conversation_display.index(tk.END)
            self.conversation_display.insert(tk.END, "\nLingo (Thinking…): ", "ai")
            self.conversation_display.configure(state='disabled')
            self.conversation_display.see(tk.END)
            self._thinking_tagged = True

            def worker():
                try:
                    # Prefer shared LLM; fallback to APIManager if missing
                    if hasattr(self.llm, "stream_ai_response"):
                        gen = self.llm.stream_ai_response(messages=messages)
                    else:
                        if self._fallback_llm is None:
                            self._fallback_llm = APIManager()
                        gen = self._fallback_llm.stream_ai_response(messages=messages)

                    # Stream to GUI + TTS simultaneously (cleaned, chunked)
                    punct_final = (".", "?", "!")
                    MAX_WORDS = 10
                    buf = []; words = 0; last_flush = time.perf_counter()

                    def flush(final=False):
                        nonlocal buf, words, last_flush
                        piece = "".join(buf).strip()
                        if piece and self._tts:
                            self._tts_q.put((piece, final))
                        buf = []; words = 0; last_flush = time.perf_counter()

                    for chunk in gen:
                        clean = strip_emoji_and_extras(chunk)
                        if not clean:
                            continue
                        # GUI stream
                        self._stream_queue.put(clean)

                        # TTS batching
                        buf.append(clean); words += clean.count(" ")
                        if clean.endswith(punct_final):
                            flush(final=True)
                            continue
                        if words >= MAX_WORDS or (time.perf_counter() - last_flush) > 0.9:
                            flush(final=False)

                    if buf:
                        flush(final=True)
                    self._stream_queue.put(None)
                except Exception as e:
                    self._stream_queue.put(f"\n[Error: {e}]")
                    self._stream_queue.put(None)

            self._stream_worker = threading.Thread(target=worker, daemon=True)
            self._stream_worker.start()
            self.root.after(15, self._drain_stream_queue)

            # Add user message to history immediately
            self.student_manager.conversation_history.append({"role": "user", "content": user_input})

        except Exception as e:
            print(f"Error in lesson: {str(e)}")
            self.display_message("Lingo", "Let me check the material... One moment please!")

    # ---------- Voice path (record → transcribe → stream LLM → TTS) ----------
    def on_speak(self):
        if self._streaming:
            return
        def _worker():
            try:
                self._ensure_stt()
                # RECORD
                self.set_status("Recording…"); print("[GUI] Recording…")
                rec = VADRecorder(sample_rate=16000, frame_ms=30, vad_aggr=3,
                                  silence_ms=2000, max_record_s=10,
                                  energy_margin=2.0, energy_min=2200, energy_max=6000)
                wav_path = rec.record(TEMP_WAV)

                # TRANSCRIBE
                self.set_status("Transcribing…"); print("[GUI] Transcribing…")
                t0 = time.perf_counter()
                segments, info = self._stt_model.transcribe(
                    wav_path, language="en", beam_size=3, vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=400)
                )
                user_text = "".join(s.text for s in segments).strip()
                print(f"[STT] (len≈{info.duration:.2f}s, asr={time.perf_counter()-t0:.2f}s)")
                self.set_status("Ready")
                if not user_text:
                    self.display_message("STT", "(No speech detected)")
                    return

                # Push transcript to chat & history
                self.display_message("You", user_text)
                self.student_manager.conversation_history.append({"role": "user", "content": user_text})

                # Build lesson-aware messages (same rules as typed)
                lesson = self.student_manager.current_lesson or {}
                lesson_title = lesson.get("title", "")
                lesson_type = self.lesson_type
                lesson_objective = lesson.get("objective", "")
                lesson_text = lesson.get("text", "") or ""
                LESSON_SLICE_LIMIT = int(os.getenv("LESSON_SLICE", "4000"))
                lesson_slice = lesson_text[:LESSON_SLICE_LIMIT]

                system_rules = (
                    "You are Lingo, a personal English tutor.\n"
                    "You are teaching the following LESSON. Follow these rules:\n"
                    "• Ground your response ~85% in the LESSON TEXT below (quote or paraphrase it).\n"
                    "• You may add ~15% brief, relevant outside knowledge to improve understanding, but do not contradict the LESSON TEXT.\n"
                    "• If the LESSON TEXT does not contain the needed info, say: \"The lesson text doesn’t say yet.\" and ask a short guiding question.\n"
                    "• Keep responses short (≤2 sentences, ≤60 words) and end with one short question.\n"
                    "• Do not use emojis. Do not use the '*' character.\n"
                    "• Match the lesson type (Reading/Grammar/Vocabulary).\n"
                )
                lesson_header = (
                    f"LESSON METADATA:\n"
                    f"Title: {lesson_title}\n"
                    f"Type: {lesson_type}\n"
                    f"Objective: {lesson_objective}\n"
                )
                lesson_payload = (
                    "LESSON TEXT (authoritative; primary source):\n"
                    "<<<BEGIN LESSON TEXT>>>\n"
                    f"{lesson_slice}\n"
                    "<<<END LESSON TEXT>>>\n"
                )
                recent_history = self.student_manager.conversation_history[-6:] if self.student_manager.conversation_history else []
                messages = [
                    {"role": "system", "content": system_rules},
                    {"role": "system", "content": lesson_header + "\n" + lesson_payload},
                ]
                messages.extend(recent_history)
                messages.append({"role": "user", "content": user_text})

                # Start streaming
                self._streaming = True
                self._first_chunk_seen = False
                self._current_response_buffer.clear()
                self.root.config(cursor="watch")

                self.conversation_display.configure(state='normal')
                self._thinking_start_index = self.conversation_display.index(tk.END)
                self.conversation_display.insert(tk.END, "\nLingo (Thinking…): ", "ai")
                self.conversation_display.configure(state='disabled')
                self.conversation_display.see(tk.END)
                self._thinking_tagged = True

                punct_final = (".", "?", "!")
                MAX_WORDS = 10
                buf = []; words = 0; last_flush = time.perf_counter()

                def flush(final=False):
                    nonlocal buf, words, last_flush
                    piece = "".join(buf).strip()
                    if piece and self._tts:
                        self._tts_q.put((piece, final))
                    buf = []; words = 0; last_flush = time.perf_counter()

                # Prefer shared LLM; fallback to APIManager if missing
                if hasattr(self.llm, "stream_ai_response"):
                    gen = self.llm.stream_ai_response(messages=messages)
                else:
                    if self._fallback_llm is None:
                        self._fallback_llm = APIManager()
                    gen = self._fallback_llm.stream_ai_response(messages=messages)

                for chunk in gen:
                    clean = strip_emoji_and_extras(chunk)
                    if not clean:
                        continue
                    self._stream_queue.put(clean)
                    buf.append(clean); words += clean.count(" ")
                    if clean.endswith(punct_final):
                        flush(final=True)
                        continue
                    if words >= MAX_WORDS or (time.perf_counter() - last_flush) > 0.9:
                        flush(final=False)

                if buf:
                    flush(final=True)
                self._stream_queue.put(None)
            except Exception as e:
                self._stream_queue.put(f"\n[Error: {e}]")
                self._stream_queue.put(None)

        threading.Thread(target=_worker, daemon=True).start()
        self.root.after(15, self._drain_stream_queue)

    def _on_close(self):
        try:
            if self._tts: self._tts.say("Goodbye.")
        except Exception:
            pass
        try:
            if self._tts: self._tts.close()
        except Exception:
            pass
        try:
            if isinstance(self.root, tk.Toplevel):
                self.root.destroy()
        except:
            pass
