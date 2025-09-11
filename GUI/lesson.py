# lesson.py
import os
import json
import random
import threading
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from tkinter import font as tkfont
import math, wave, struct, collections, time
from styles import configure_styles
from api_manager import APIManager  # fallback if needed
from face_tracker import FaceTracker

# --- STT deps (same as main.py) ---
try:
    import sounddevice as sd
    import webrtcvad
    from faster_whisper import WhisperModel
except Exception as e:
    raise SystemExit(
        "Missing deps. Run:\n"
        "  pip install faster-whisper webrtcvad sounddevice\n" + str(e)
    )
# --- Piper access ---
import importlib.machinery, importlib.util
def _load_module_from_path(mod_name: str, file_path: str):
    loader = importlib.machinery.SourceFileLoader(mod_name, file_path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module

import shutil, subprocess, sys, json, os, threading

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

# --- Piper persistent engine (binary → sounddevice) ---
class PiperEngine:
    """
    Persistent RAW pipeline:
      (text) → piper --output-raw (bytes) → sounddevice OutputStream
    Provides wait_until_quiet() so we can STOP only after audio is truly done.
    """
    def __init__(self, piper_bin: str, voice_onnx: str):
        if not os.path.isfile(voice_onnx):
            raise RuntimeError(f"Voice model not found: {voice_onnx}")
        self.voice = voice_onnx
        self.sr = _infer_sample_rate(voice_onnx, default_sr=22050)
        self._p1 = None
        self._lock = threading.Lock()
        self._piper_cmd = _find_piper_cmd(piper_bin)
        if not self._piper_cmd:
            raise RuntimeError("piper CLI not found. Install with: pip install piper-tts")

        # playback fields
        self._sd = None               # sounddevice.OutputStream
        self._alive = False
        self._reader = None           # background thread pumping bytes → audio
        self._last_audio_ts = 0.0     # last time audio was written (seconds)

    def start(self):
        import sounddevice as sd
        # Start Piper in **binary** mode (text=False) → stdout is raw bytes
        cmd = self._piper_cmd + ["--model", self.voice, "--output-raw", "--sentence_silence", "0.25"]
        self._p1 = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=False, bufsize=0
        )

        # Start audio device
        self._sd = sd.OutputStream(samplerate=self.sr, channels=1, dtype='int16', blocksize=2048)
        self._sd.start()
        self._alive = True
        self._last_audio_ts = 0.0

        # Pump Piper stdout → sounddevice
        def _pump():
            try:
                while self._alive and self._p1 and self._p1.stdout:
                    data = self._p1.stdout.read(4096)
                    if not data:
                        time.sleep(0.005)
                        continue
                    # reinterpret bytes as int16 and write to device
                    self._sd.write(memoryview(data).cast('h'))
                    self._last_audio_ts = time.time()
            except Exception:
                pass

        self._reader = threading.Thread(target=_pump, daemon=True)
        self._reader.start()

    def say_chunk(self, text: str, final: bool):
        """Write text to Piper; Piper returns audio bytes on stdout which our _pump plays."""
        if not text or not text.strip():
            return
        if not self._p1 or not self._p1.stdin:
            raise RuntimeError("Piper not started.")
        # Piper expects utf-8 text + newline to synthesize a sentence.
        suffix = b"\n" if final else b" "
        with self._lock:
            try:
                self._p1.stdin.write((text.strip()).encode("utf-8") + suffix)
                self._p1.stdin.flush()
            except BrokenPipeError:
                self.close(); self.start()
                self._p1.stdin.write((text.strip()).encode("utf-8") + suffix)
                self._p1.stdin.flush()

    def say(self, text: str):
        self.say_chunk(text, final=True)

    def wait_until_quiet(self, quiet_ms: int = 600, timeout_s: float = 5.0):
        """Block until we’ve had no audio writes for quiet_ms, or timeout."""
        start = time.time()
        q = quiet_ms / 1000.0
        while time.time() - start < timeout_s:
            last = self._last_audio_ts
            if last and (time.time() - last) >= q:
                return
            time.sleep(0.05)

    def close(self):
        try:
            self._alive = False
            if self._sd:
                try: self._sd.stop(); self._sd.close()
                except Exception: pass
        except Exception:
            pass
        try:
            if self._p1 and self._p1.stdin and not self._p1.stdin.closed:
                self._p1.stdin.close()
        except Exception:
            pass
        try:
            if self._p1: self._p1.terminate()
        except Exception:
            pass
        self._p1 = None
        self._sd = None


TTS_MOD_PATH = "/home/robinglory/Desktop/Thesis/TTS/streaming_piper_gui.py"
ttsmod = _load_module_from_path("streaming_piper_gui", TTS_MOD_PATH)  # exposes PIPER_BIN, DEFAULT_VOICE

# ---------- Simple JSON helpers ----------
def load_json(filepath):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
        
# --- STT constants (tiny + temp wav) ---
FW_TINY = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-tiny.en"
TEMP_WAV = "/tmp/fw_lesson.wav"

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
        
# --- Minimal VAD recorder ---
class VADRecorder:
    """WebRTC VAD + energy gate; writes 16k mono WAV and returns its path."""
    def __init__(self, sample_rate=16000, frame_ms=30, vad_aggr=3,
                 silence_ms=1200, max_record_s= 10, device=None,
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

        def _cb(indata, frames, time_info, status):
            nonlocal voiced, trailing, total, energy_thr
            buf=indata.tobytes()
            if len(buf)<frame_bytes: return
            ring.append(buf); total+=1
            if energy_thr is None and len(calib_vals)<calib_frames:
                calib_vals.append(self._rms_int16(buf)); return
            if energy_thr is None and len(calib_vals)==calib_frames:
                base=sorted(calib_vals)[len(calib_vals)//2]
                thr=max(self.energy_min,min(self.energy_max, base*self.energy_margin)); energy_thr=thr
            rms=self._rms_int16(buf)
            try:
                speech = vad.is_speech(buf,self.sample_rate)
            except Exception:
                speech=False
            if energy_thr is not None and rms<energy_thr: speech=False
            if speech: voiced=True; trailing=0
            else:
                if voiced: trailing=min(silence_frames_needed,trailing+1)

        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype='int16',
                             device=self.device, blocksize=frame_samp, callback=_cb):
            while True:
                time.sleep(self.frame_ms/1000.0)
                if total>=max_frames: break
                if voiced and trailing>=silence_frames_needed: break

        os.makedirs(os.path.dirname(out_wav), exist_ok=True)
        with wave.open(out_wav,'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(self.sample_rate)
            while ring: w.writeframes(ring.popleft())
        return out_wav

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
        self.lesson_path = self.current_lesson.get("filepath", f"default_{lesson_type}")

        # Load persisted data
        self.conversation_data = load_json(self.CONVERSATIONS_JSON_PATH)
        self.students_data = load_json(self.STUDENTS_JSON_PATH)
        
        self._stt_model: WhisperModel | None = None
        self.status_var = tk.StringVar(value="Ready")
        
        # --- TTS state (like main.py) ---
        self._tts: PiperEngine | None = None
        self._tts_q: queue.Queue[tuple[str|None, bool]] = queue.Queue(maxsize=128)
        self._pending_gui_text: str | None = None


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
        
        # Start Piper
        self._init_tts()
                # --- Arduino / gesture state (mirror main.py) ---
        self._speech_state = "IDLE"       # IDLE | LISTENING | THINKING | TALKING
        self._speaking_active = False     # flips True on first TTS audio chunk

        def _set_state(s: str):
            # (Keep it simple; main.py prints a line, we can keep it quiet here)
            self._speech_state = s
        self._set_state = _set_state

        def _ensure_serial():
            # If main window exposes _ensure_serial, use it. Otherwise no-op.
            try:
                if hasattr(self.main_app, "_ensure_serial"):
                    self.main_app._ensure_serial()
            except Exception as e:
                print("[SERIAL] ensure error:", e)
        self._ensure_serial = _ensure_serial

        def _serial_send(cmd: str):
            # Proxy to main app's sender, same as main.py’s pipeline
            try:
                if hasattr(self.main_app, "_serial_send"):
                    self.main_app._serial_send(cmd)
                elif hasattr(self.main_app, "serial_send"):
                    self.main_app.serial_send(cmd)
                else:
                    print(f"[SERIAL] (no sender) -> {cmd}")
            except Exception as e:
                print("[SERIAL] send error:", e)
        self._serial_send = _serial_send

        # --- Start face tracker (eyes follow face only while IDLE) ---
        try:
            self._tracker = FaceTracker(
                send_cmd=self._serial_send,
                get_state=lambda: self._speech_state,
                ensure_serial=self._ensure_serial,   # FaceTracker expects this param
                width=1280, height=720,
                rate_hz=10.0,
                deadband_deg=1.0
            )
            self._tracker.start()
        except Exception as _e:
            print("[TRACK] init error:", _e)

        # Drain TTS queue forever
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

        # Keep input row visible
        self.conversation_display = scrolledtext.ScrolledText(
            main_frame,
            wrap=tk.WORD,
            font=self.content_font,
            height=16,            # was 30; this avoids the input row being pushed out
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

        self.user_input = ttk.Entry(input_frame, font=("Segoe UI", 12))
        self.user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.user_input.bind("<Return>", self.handle_input)

        send_btn = ttk.Button(input_frame, text="Send", command=self.handle_input, style="Accent.TButton")
        send_btn.pack(side=tk.RIGHT)

        self.user_input.focus()

        # Replay prior conversation
        for msg in self.conversation_history:
            sender = "You" if msg["role"] == "user" else "Lingo"
            self.display_message(sender, msg["content"])
            
        # status label (left)
        status_lbl = ttk.Label(input_frame, textvariable=self.status_var)
        status_lbl.pack(side=tk.LEFT, padx=(0, 10))

        # 🎤 Speak button
        speak_btn = ttk.Button(input_frame, text="🎤 Speak", command=self.on_speak, style="Accent.TButton")
        speak_btn.pack(side=tk.RIGHT, padx=(0, 10))


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
            "This is going to really boost your English skills!",
            "I'm excited to help you master this important area!",
            "You're making great progress by working on this!",
            "This lesson will take your English to the next level!",
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
            # Make sure tracking is fully stopped on exit so the camera is released
            try:
                if hasattr(self, "_tracker"):
                    self._tracker.pause_and_trackoff()
                    self._tracker.stop()
            except Exception as _e:
                print("[TRACK] stop error:", _e)

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
        """Replace 'Lingo (Thinking…): ' with 'Lingo: ' on first token."""
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
            item = self._stream_queue.get_nowait()
        except queue.Empty:
            self.root.after(15, self._drain_stream_queue)
            return

        # When streaming finishes, stash final text ONCE and tell TTS drainer to commit after speech
        if item is None:
            # NEW: ensure the last buffered chunk reaches TTS before we signal end-of-turn
            if hasattr(self, "_lesson_tts_buf") and self._lesson_tts_buf:
                piece = "".join(self._lesson_tts_buf).strip()
                if piece and self._tts:
                    self._tts_q.put((piece, True))  # flush the last chunk as final
                self._lesson_tts_buf.clear()
                self._lesson_tts_words = 0
            full_text = "".join(getattr(self, "_lesson_full_parts", [])).strip()
            self._pending_gui_text = full_text
            self._tts_q.put((None, True))  # sentinel after all chunks
            return


        # item is a streamed text chunk
        chunk = item

        # Flip "Lingo (Thinking…): " to "Lingo: " on the very first token
        self._replace_thinking_header_if_needed()

        # TTS buffering logic (unchanged)
        if not hasattr(self, "_lesson_tts_buf"):
            self._lesson_tts_buf = []
            self._lesson_tts_words = 0
            self._lesson_last_flush = time.perf_counter()
            self._lesson_full_parts = []
            self._punct_final = (".", "?", "!")
            self._max_words = 10

        self._lesson_full_parts.append(chunk)
        self._lesson_tts_buf.append(chunk)
        self._lesson_tts_words += chunk.count(" ")

        def _flush(final=False):
            piece = "".join(self._lesson_tts_buf).strip()
            if piece and self._tts:
                self._tts_q.put((piece, final))
            self._lesson_tts_buf.clear()
            self._lesson_tts_words = 0
            self._lesson_last_flush = time.perf_counter()

        if chunk.endswith(self._punct_final):
            _flush(final=True)
        else:
            if (self._lesson_tts_words >= self._max_words) or ((time.perf_counter() - self._lesson_last_flush) > 0.9):
                _flush(final=False)

        self.root.after(15, self._drain_stream_queue)

    # ---------- Input handling ----------
    def handle_input(self, event=None):
        if self._streaming:
            return

        user_input = self.user_input.get().strip()
        if not user_input:
            return

        self.display_message("You", user_input)
        self.user_input.delete(0, tk.END)
        # Typed turns still pause tracking during THINK/TALK
        try:
            if hasattr(self, "_tracker"):
                self._tracker.pause_and_trackoff()
        except Exception as _e:
            print("[TRACK] pause error:", _e)

        try:
            # Build lesson-aware prompts that FORCE answers from lesson text only
            lesson = self.student_manager.current_lesson or {}
            lesson_title = lesson.get("title", "")
            lesson_type = self.lesson_type
            lesson_objective = lesson.get("objective", "")
            lesson_text = lesson.get("text", "") or ""

            LESSON_SLICE_LIMIT = 1200
            lesson_slice = lesson_text[:LESSON_SLICE_LIMIT]

            system_rules = (
                "You are Lingo, a personal English tutor. "
                "You are currently teaching a specific LESSON to the student. "
                "CRITICAL:\n"
                "1) Base your responses ONLY on the provided LESSON TEXT below. Do not use outside knowledge.\n"
                "2) If the answer is not in the LESSON TEXT yet, say: \"The lesson text doesn’t say yet.\" and guide the student to the relevant part.\n"
                "3) Keep answers short (≤2 sentences, ≤60 words) and end with one simple question.\n"
                "4) Avoid the '*' character.\n"
                "5) Do not invent names or facts not present in the LESSON TEXT.\n"
                "6) Match the lesson type (Reading/Grammar/Vocabulary):\n"
                "   - Reading: give a brief, text‑based explanation + one comprehension question.\n"
                "   - Grammar: explain the rule using examples from the text; avoid new rules not in text.\n"
                "   - Vocabulary: define/illustrate only words appearing in the text.\n"
            )

            lesson_header = (
                f"LESSON METADATA:\n"
                f"Title: {lesson_title}\n"
                f"Type: {lesson_type}\n"
                f"Objective: {lesson_objective}\n"
            )

            lesson_payload = (
                "LESSON TEXT (authoritative; use this ONLY):\n"
                "<<<BEGIN LESSON TEXT>>>\n"
                f"{lesson_slice}\n"
                "<<<END LESSON TEXT>>>\n"
            )

            # Cap history to last 6 messages (3 pairs) to keep latency low
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

            # Pause tracking while THINK/TALK runs
            try:
                self._tracker.pause_and_trackoff()
            except Exception as _e:
                print("[TRACK] pause error:", _e)

            def worker():
                try:
                    # Prefer main_app.llm streaming; fallback to APIManager if missing for any reason
                    if hasattr(self.llm, "stream_ai_response"):
                        gen = self.llm.stream_ai_response(messages=messages)
                    else:
                        if self._fallback_llm is None:
                            self._fallback_llm = APIManager()
                        gen = self._fallback_llm.stream_ai_response(messages=messages)

                    for chunk in gen:
                        self._stream_queue.put(chunk)                        
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
    
    def _ensure_stt(self):
        if self._stt_model is not None:
            return
        os.environ.setdefault("OMP_NUM_THREADS","4")
        # tiny.en, int8 CPU for speed
        model_dir = FW_TINY
        if not os.path.isdir(model_dir):
            raise RuntimeError(f"STT model folder not found: {model_dir}")
        print(f"[STT] Loading model: {model_dir} (int8)")
        t0=time.perf_counter()
        self._stt_model = WhisperModel(model_dir, device="cpu", compute_type="int8")
        print(f"[STT] Ready in {time.perf_counter()-t0:.2f}s")
        
    def _init_tts(self):
        try:
            self._tts = PiperEngine(ttsmod.PIPER_BIN, ttsmod.DEFAULT_VOICE)
            self._tts.start()
        except Exception as e:
            print("[TTS] init error:", e)

    def _drain_tts_queue(self):
        try:
            item = self._tts_q.get_nowait()
        except queue.Empty:
            self.root.after(20, self._drain_tts_queue)
            return

        try:
            if not self._tts:
                # nothing to speak; just keep draining
                self.root.after(20, self._drain_tts_queue)
                return

            text, is_final = item

            if text is None:
                # ---- SENTINEL: the model finished streaming all chunks ----
                # 1) Commit GUI text now
                pending = (self._pending_gui_text or "").strip()
                if pending:
                    self._append_stream_text(pending + "\n\n")
                    self.student_manager.conversation_history.append({"role": "assistant", "content": pending})

                # 2) Clear UI streaming flags
                self.root.config(cursor="")
                self._streaming = False
                self._pending_gui_text = None
                self._thinking_tagged = False
                self._thinking_start_index = None
                self._first_chunk_seen = False

                # 3) Only STOP after the audio device has really gone quiet
                def _stop_after_quiet():
                    try:
                        self._tts.wait_until_quiet(quiet_ms=600, timeout_s=6.0)
                    except Exception:
                        pass
                    # double STOP like main.py
                    self._serial_send("stop")
                    time.sleep(0.12)
                    self._serial_send("stop")
                    # leave TALKING only after stops
                    self._speaking_active = False
                    self._set_state("IDLE")
                    # resume face tracking a little later
                    try:
                        if hasattr(self, "_tracker"):
                            self.root.after(5000, self._tracker.resume_and_trackon)
                    except Exception as _e:
                        print("[TRACK] resume error:", _e)

                threading.Thread(target=_stop_after_quiet, daemon=True).start()

            else:
                # ---- NORMAL CHUNK ----
                # Begin TALK exactly once on the first audible chunk after THINK
                if not self._speaking_active and self._speech_state == "THINKING":
                    self._serial_send("talk")
                    self._set_state("TALKING")
                    self._speaking_active = True

                # Send every chunk to Piper; 'final' just toggles newline vs space
                self._tts.say_chunk(text, final=is_final)

        except Exception as e:
            print("[TTS] error:", e)

        self.root.after(20, self._drain_tts_queue)



    def on_speak(self):
        if self._streaming:
            return
        def _worker():
            try:
                self._ensure_stt()
                # --- pause face-tracking and start listening gesture ---
                try:
                    self._tracker.pause_and_trackoff()
                except Exception as _e:
                    print("[TRACK] pause error:", _e)

                self._serial_send(random.choice(["listen_left", "listen_right"]))
                self._set_state("LISTENING")

                # 1) RECORD
                self.status_var.set("Recording…")
                rec = VADRecorder(sample_rate=16000, frame_ms=30, vad_aggr=3,
                                  silence_ms=1200, max_record_s=10,
                                  energy_margin=2.0, energy_min=2200, energy_max=6000)
                wav_path = rec.record(TEMP_WAV)

                # 2) TRANSCRIBE (greedy, fastest)
                self.status_var.set("Transcribing…")
                # --- switch to THINK while we transcribe / prepare reply ---
                self._serial_send("think")
                self._set_state("THINKING")

                t0 = time.perf_counter()
                segments, info = self._stt_model.transcribe(
                    wav_path,
                    language="en",
                    beam_size=1,
                    vad_filter=False,
                    temperature=0.0,
                    condition_on_previous_text=False
                )
                user_text = "".join(s.text for s in segments).strip()
                print(f"[STT] (len≈{getattr(info,'duration',0):.2f}s, asr={time.perf_counter()-t0:.2f}s)")
                self.status_var.set("Ready")

                if not user_text:
                    # Just inform the UI; do NOT call LLM
                    self.display_message("STT", "(No speech detected)")
                    return

                # Push transcript into the entry and reuse your existing flow
                self.user_input.delete(0, tk.END)
                self.user_input.insert(0, user_text)
                # Call your existing handler (this preserves your LLM + DB logic)
                self.handle_input()

            except Exception as e:
                self.status_var.set("Ready")
                self.display_message("Lingo", f"[STT error] {e}")

        threading.Thread(target=_worker, daemon=True).start()


    def _generate_system_prompt(self, context):
        """Deprecated: kept for compatibility."""
        return "You are Lingo, a personal English tutor. Use only the provided lesson text."
