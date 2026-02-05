import os
import sys
import time
import json
import math
import wave
import struct
import shutil
import queue
import threading
import collections
import subprocess
from datetime import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext
from face_tracker import FaceTracker
from dotenv import load_dotenv
from openai import OpenAI

# UI modules
from styles import configure_styles
from login import LoginScreen
from student_manager import StudentManager
from lesson_manager import LessonManager

# --- Arduino serial helper (from gui_serial.py) ---
from gui_serial import UnoSerial  # reuses your existing class
try:
    from serial.tools import list_ports  # for auto-pick of the port
except Exception:
    list_ports = None

# Multi-account manager (keys.json + settings.json)
from key_manager import KeyManager

# -------------------- NEW: audio & stt deps --------------------
try:
    import sounddevice as sd
    import webrtcvad
    from faster_whisper import WhisperModel
except Exception as e:
    raise SystemExit(
        "Missing deps. Run:\n"
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

# Adjust path if needed (you told me it is correct)
TTS_MOD_PATH = "/home/robinglory/Desktop/Thesis/TTS/streaming_piper_gui.py"
ttsmod = _load_module_from_path("streaming_piper_gui", TTS_MOD_PATH)  # exposes PIPER_BIN, DEFAULT_VOICE

# -------------------- NEW: Piper persistent engine --------------------
def _voice_json_path(onnx_path: str)->str|None:
    base, _ = os.path.splitext(onnx_path)
    j = base + ".json"
    return j if os.path.isfile(j) else None

def _infer_sample_rate(onnx_path: str, default_sr: int = 22050)->int:
    # Allow manual override via environment (you use 24000)
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
        
# inside class MainAIChat, replace the whole open_login() with this:

def open_login(self):
    # Pause face tracking & free camera
    try:
        if getattr(self, "_tracker", None):
            self._tracker.pause_and_trackoff()
    except Exception as _e:
        print("[TRACK] pause for login error:", _e)

    if self.login_window and self.login_window.winfo_exists():
        self.login_window.lift()
        return

    self.login_window = tk.Toplevel(self.root)
    self.login_window.protocol("WM_DELETE_WINDOW", self.on_login_close)
    LoginScreen(self.login_window, self)
    self.login_window.geometry("400x300")
    self.login_window.transient(self.root)
    self.login_window.grab_set()

def on_login_close(self):
    if self.login_window:
        self.login_window.destroy()
        self.login_window = None
    try:
        if getattr(self, "_tracker", None):
            # resume after 1200 ms to avoid racing Picamera2 teardown
            self.root.after(1200, self._tracker.resume_and_trackon)
    except Exception as _e:
        print("[TRACK] resume after login error:", _e)

class PiperEngine:
    """
    Persistent RAW pipeline:
      (text) → piper --output-raw → (PCM S16_LE mono) → sounddevice OutputStream
    Allows us to know when playback has actually drained.
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
        self._sd = None
        self._alive = False
        self._reader = None
        self._last_audio_ts = 0.0

    def start(self):
        import sounddevice as sd
        # Start Piper in **binary** mode (text=False) so stdout is bytes
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

        # Pump piper stdout → sounddevice
        def _pump():
            try:
                while self._alive and self._p1 and self._p1.stdout:
                    data = self._p1.stdout.read(4096)
                    if not data:
                        time.sleep(0.005)
                        continue
                    # Write to audio device; this blocks until accepted by device buffer
                    self._sd.write(memoryview(data).cast('h'))  # reinterpret bytes as int16
                    self._last_audio_ts = time.time()
            except Exception:
                pass
        self._reader = threading.Thread(target=_pump, daemon=True)
        self._reader.start()

    # ---- smarter chunk writer (no newline mid-sentence) ----
    def say_chunk(self, text: str, final: bool):
        """Write chunk with minimal pause mid-sentence; newline only at sentence end."""
        if not text or not text.strip():
            return
        if not self._p1 or not self._p1.stdin:
            raise RuntimeError("Piper not started.")
        suffix = "\n" if final else " "
        with self._lock:
            try:
                self._p1.stdin.write((text.strip() + suffix).encode("utf-8"))
                self._p1.stdin.flush()
            except BrokenPipeError:
                self.close(); self.start()
                self._p1.stdin.write((text.strip() + suffix).encode("utf-8"))
                self._p1.stdin.flush()

    # kept for legacy/simple calls
    def say(self, text: str):
        self.say_chunk(text, final=True)

    def wait_until_quiet(self, quiet_ms: int = 600, poll_ms: int = 40):
        """
        Block until no audio has been written to the device for 'quiet_ms'.
        Use after you've fed the sentinel to ensure playback really finished.
        """
        deadline = float(quiet_ms) / 1000.0
        while True:
            now = time.time()
            last = self._last_audio_ts
            if last > 0 and (now - last) >= deadline:
                return
            time.sleep(poll_ms / 1000.0)

    def close(self):
        try:
            self._alive = False
            if self._p1 and self._p1.stdin and not self._p1.stdin.closed:
                self._p1.stdin.close()
        except Exception:
            pass
        try:
            if self._sd:
                self._sd.stop(); self._sd.close()
        except Exception:
            pass
        try:
            if self._p1: self._p1.terminate()
        except Exception:
            pass
        self._p1 = None; self._sd = None; self._reader = None


# -------------------- NEW: VAD recorder (16k, mono) --------------------
class VADRecorder:
    """WebRTC VAD + energy gate; writes 16k mono WAV and returns its path."""
    def __init__(self, sample_rate=16000, frame_ms=20, vad_aggr=3,
                 silence_ms=1200, max_record_s=10, device=None,
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

# -------------------- Existing constants (unchanged LLM) --------------------
load_dotenv()

SOFT_TIMEOUT_SECONDS = 6.0
DEFAULT_MAX_TOKENS = 48
DEFAULT_STOP = ["\n\n", "Question:", "Q:", "Lingo:", "You:"]


# STT models (paths unchanged)
FW_BASE = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-base.en"
FW_TINY = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-tiny.en"  # kept for completeness
TEMP_WAV = "/tmp/fw_dialog.wav"

# -------------------- Your existing LLM handler (with watchdog hedge) --------------------
class LLMHandler:
    """
    General chat LLM with:
      - streaming + hedged requests (winner-first),
      - multi-account profiles via KeyManager,
      - NO automatic profile rotation. On quota/auth/rate errors, emits a clear
        message instructing the user to switch profile from the GUI.
    """
    def __init__(self, key_manager: KeyManager):
        self.key_manager = key_manager
        self._reload_providers_from_profile()
        self.current_provider = 0
        self.client = self._create_client()
    
    def _max_tokens_for(self, messages):
        try:
            # If there is any system message, clamp to 48 for concise lesson replies
            if any(m.get("role") == "system" for m in messages):
                return 48
        except Exception:
            pass
        return DEFAULT_MAX_TOKENS


    #def _reload_providers_from_profile(self):
    #    keys = self.key_manager.get_keys()
    #    self.api_providers = [
    #       {
    #           "name": "Qwen3 Coder",
    #          "api_key": keys["QWEN_API_KEY"],
    #            "model": "qwen/qwen3-coder:free",
    #            "headers": {"HTTP-Referer": "http://localhost:3000", "X-Title": "Lingo AI Assistant"},
    #        },
    #        {
    #            "name": "Dolphin Mistral 24B",
    #            "api_key": keys["MISTRAL_API_KEY"],
    #            "model": "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    #            "headers": {"HTTP-Referer": "http://localhost:3000", "X-Title": "Lingo AI Assistant"},
    #        },
     #       {
    #            "name": "GPT-OSS-120B",
    #            "api_key": keys["GPT_OSS_API_KEY"],
    ##            "model": "openai/gpt-oss-120b:free",
    #            "headers": {"HTTP-Referer": "http://localhost:3000", "X-Title": "Lingo AI Assistant"},
    #        }
    #    ]
    
    def _reload_providers_from_profile(self):
        keys = self.key_manager.get_keys()
        self.api_providers = [
            {
                "name": "Arcee AI",
                "api_key": keys["ARCEE_API_KEY"],
                "model": "arcee-ai/trinity-large-preview:free",
                "headers": {"HTTP-Referer": "http://localhost:3000", "X-Title": "Lingo AI Teacher"},
            },
            {
                "name": "Liquid AI",
                "api_key": keys["LIQUID_API_KEY"],
                "model": "liquid/lfm-2.5-1.2b-thinking:free",
                "headers": {"HTTP-Referer": "http://localhost:3000", "X-Title": "Lingo AI Teacher"},
            },
            {
                "name": "Molmo AI",
                "api_key": keys["MOLMO_API_KEY"],
                "model": "allenai/molmo-2-8b:free",
                "headers": {"HTTP-Referer": "http://localhost:3000", "X-Title": "Lingo AI Teacher"},
            }
        ]



    def _create_client(self, provider_idx=None):
        idx = self.current_provider if provider_idx is None else provider_idx
        p = self.api_providers[idx]
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=p["api_key"], timeout=20.0)
        client._client.headers.update(p["headers"])
        return client

    def _switch_provider(self):
        self.current_provider = (self.current_provider + 1) % len(self.api_providers)
        print(f"Switching model to {self.api_providers[self.current_provider]['name']}...")
        self.client = self._create_client()

    def switch_profile(self, index: int):
        self.key_manager.switch_to(index)
        self._reload_providers_from_profile()
        self.current_provider = 0
        self.client = self._create_client()

    def next_profile(self):
        idx = self.key_manager.next_profile()
        self._reload_providers_from_profile()
        self.current_provider = 0
        self.client = self._create_client()
        return idx

    def _is_quota_or_auth_error(self, exc_msg: str) -> bool:
        m = exc_msg.lower()
        if any(w in m for w in ["429", "too many requests", "rate"]): return True
        if any(w in m for w in ["401", "403", "unauthorized", "forbidden", "invalid api key"]): return True
        if "insufficient_quota" in m: return True
        return False

    def _quota_message(self) -> str:
        label = self.key_manager.get_active_label()
        return (f"[API Notice] The current OpenRouter account “{label}” appears to be rate-limited or out of quota. "
                f"Please click the API button at the top to switch profiles, then try again.")

    # (Blocking) left as-is
    def get_ai_response(self, message=None, conversation_history=None, lesson_context=None, messages=None):
        if messages is None:
            if message is None:
                raise ValueError("Either message or messages must be provided")

            if lesson_context:
                system_msg = (
                    f"You are Lingo teaching {lesson_context['student_name']} (Level: {lesson_context['student_level']}). "
                    f"Current Lesson: {lesson_context['lesson_title']}\n"
                    f"Objective: {lesson_context['lesson_objective']}\n"
                    "Rules (MANDATORY):\n"
                    "• BASE ANSWERS ONLY on lesson content the user is studying now. If not present, say: "
                    "\"The lesson text doesn’t say yet.\" and ask a tiny guiding question.\n"
                    "• 1–2 sentences MAX (≤40 words total) + end with ONE short question.\n"
                    "• NO emojis. NO asterisks '*'.\n"
                    "• Do NOT start with phrases like 'In this lesson,' 'We will learn,' or repeat prior lines.\n"
                    "• Avoid repeating yourself or re-stating the same example.\n"
                )
            else:
                system_msg = (
                    "You are Lingo, a friendly AI English Teacher.\n"
                    "Rules: 1–2 sentences (≤40 words) + end with ONE short question. "
                    "No emojis. Avoid the '*' character. Do not repeat yourself."
                )


            messages = [{"role": "system", "content": system_msg}]
            if conversation_history:
                messages.extend(conversation_history[-4:])
                messages = [
                m for m in messages
                if not (m.get("role") == "assistant"
                        and isinstance(m.get("content"), str)
                        and m["content"].strip().lower().startswith(("in this lesson", "we will learn")))
]

            messages.append({"role": "user", "content": message})

        p = self.api_providers[self.current_provider]
        try:
            # NEW: compute per-request max_tokens
            max_tokens = self._max_tokens_for(messages)

            resp = self.client.chat.completions.create(
                model=p["model"],
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.4,
                stop=DEFAULT_STOP
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            emsg = str(e)
            if self._is_quota_or_auth_error(emsg):
                return self._quota_message()
            print(f"Error with {p['name']}: {emsg}")
            self._switch_provider()
            return "I'm having trouble connecting right now. Please try again."


    # ---------- Streaming + Hedge + first-token fallback ----------
    def stream_ai_response(self, message=None, conversation_history=None, lesson_context=None, messages=None):
        """
        Yields text chunks as they arrive.
        Races two providers (A,B). If no first token within FIRST_TOKEN_TIMEOUT, starts C.
        Only the first provider to emit continues; others are signaled to stop.
        """
        import time as _time
        import threading

        FIRST_TOKEN_TIMEOUT = 8.0  # seconds

        # --- BUILD MESSAGES ONLY IF NOT PROVIDED ---
        if messages is None:
            if message is None and lesson_context is None and not conversation_history:
                raise ValueError("Either `messages` or (`message` and optional context) must be provided")

            if lesson_context:
                system_msg = (
                    f"You are Lingo teaching {lesson_context['student_name']} (Level: {lesson_context['student_level']}). "
                    f"Current Lesson: {lesson_context['lesson_title']}\n"
                    f"Objective: {lesson_context['lesson_objective']}\n"
                    "Rules (MANDATORY):\n"
                    "• BASE ANSWERS ONLY on lesson content the user is studying now. If not present, say: "
                    "\"The lesson text doesn’t say yet.\" and ask a tiny guiding question.\n"
                    "• 1–2 sentences MAX (≤40 words total) + end with ONE short question.\n"
                    "• NO emojis. NO asterisks '*'.\n"
                    "• Do NOT start with phrases like 'In this lesson,' 'We will learn,' or repeat prior lines.\n"
                    "• Avoid repeating yourself or re-stating the same example.\n"
                )
            else:
                system_msg = (
                    "You are Lingo, a friendly AI English Teacher.\n"
                    "Rules: 1–2 sentences (≤40 words) + end with ONE short question. "
                    "No emojis. Avoid the '*' character. Do not repeat yourself."
                )

            messages = [{"role": "system", "content": system_msg}]
            if conversation_history:
                # keep ONLY last 2 exchanges
                messages.extend(conversation_history[-4:])
                messages = [
                    m for m in messages
                    if not (m.get("role") == "assistant"
                            and isinstance(m.get("content"), str)
                            and m["content"].strip().lower().startswith(("in this lesson", "we will learn")))
                ]
            if message is not None:
                messages.append({"role": "user", "content": message})
        # NEW: compute per-request max_tokens once for all streams
        _req_max_tokens = self._max_tokens_for(messages)

        idx_a = self.current_provider
        idx_b = (self.current_provider + 1) % len(self.api_providers)
        idx_c = (self.current_provider + 2) % len(self.api_providers)

        out_q: queue.Queue = queue.Queue()
        import re
        EMOJI_RE = re.compile(
            r"[\U0001F300-\U0001F6FF\U0001F900-\U0001F9FF\U0001FA70-\U0001FAFF\U00002700-\U000027BF]+"
        )

        def sanitize_text(s: str) -> str:
            if not s: return s
            # strip emojis & stray asterisks, collapse spaces
            s = EMOJI_RE.sub("", s)
            s = s.replace("*", "")
            return s

        winner_lock = threading.Lock()
        winner_idx = {"value": None}
        first_token_time = {"value": None}
        stop_flags = {idx_a: threading.Event(), idx_b: threading.Event(), idx_c: threading.Event()}
        sentinels_needed = 0

        def stream_from_provider(provider_idx: int):
            p = self.api_providers[provider_idx]
            def _open_stream():
                client = self._create_client(provider_idx)
                return client.chat.completions.create(
                    model=p["model"],
                    messages=messages,
                    max_tokens=_req_max_tokens,   # ← use the computed value
                    temperature=0.4,
                    stop=DEFAULT_STOP,
                    stream=True
                )

            try:
                stream = _open_stream()
                for event in stream:
                    if stop_flags[provider_idx].is_set():
                        break
                    delta = getattr(event.choices[0].delta, "content", None)
                    if not delta:
                        continue
                    delta = sanitize_text(delta)

                    with winner_lock:
                        now = _time.time()
                        if winner_idx["value"] is None:
                            winner_idx["value"] = provider_idx
                            first_token_time["value"] = now
                            for k in stop_flags.keys():
                                if k != provider_idx:
                                    stop_flags[k].set()
                        elif winner_idx["value"] != provider_idx:
                            break
                    out_q.put(delta)
            except Exception as e:
                emsg = str(e)
                with winner_lock:
                    if winner_idx["value"] is None:
                        if self._is_quota_or_auth_error(emsg):
                            out_q.put("\n" + self._quota_message())
                        else:
                            out_q.put(f"\n[Error: {p['name']} failed: {emsg}]")
            finally:
                out_q.put((provider_idx, None))

        # Start A & B
        ta = threading.Thread(target=stream_from_provider, args=(idx_a,), daemon=True)
        tb = threading.Thread(target=stream_from_provider, args=(idx_b,), daemon=True)
        ta.start(); tb.start()
        sentinels_needed = 2

        # Watchdog: if no first token, start C
        def watchdog():
            nonlocal sentinels_needed
            start = _time.time()
            while (_time.time() - start) < FIRST_TOKEN_TIMEOUT:
                with winner_lock:
                    if winner_idx["value"] is not None:
                        return
                _time.sleep(0.02)
            with winner_lock:
                if winner_idx["value"] is None and not stop_flags[idx_c].is_set():
                    tc = threading.Thread(target=stream_from_provider, args=(idx_c,), daemon=True)
                    tc.start()
                    sentinels_needed += 1
        threading.Thread(target=watchdog, daemon=True).start()

        # Drain outputs from whichever wins
        finished = 0
        # de-dup across stream: only emit NEW suffix beyond what we've already yielded
        accumulated = ""

        while finished < sentinels_needed:
            item = out_q.get()
            if isinstance(item, tuple) and item[1] is None:
                finished += 1
                continue
            # item is a chunk string
            new_text = str(item)
            # If provider glitch repeats earlier content, keep only the novel suffix
            if new_text and accumulated:
                # longest common prefix trim
                common = 0
                max_check = min(len(accumulated), len(new_text))
                while common < max_check and accumulated[-max_check+common] == new_text[common]:
                    common += 1
            # simpler & faster: just drop if chunk is already fully contained at the end
            if new_text and new_text in accumulated[-1024:]:
                new_text = ""
            if new_text:
                accumulated += new_text
                yield new_text

# -------------------- GUI (kept style; TTS-first policy) --------------------
class MainAIChat:
    def __init__(self, root):
        self.root = root
        self.root.title("Lingo - AI English Teacher")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)
        self.root.configure(bg="#f8f9fa")

        configure_styles()
        # --- Arduino serial + gesture state ---
        self._uno = UnoSerial()      # serial session to Arduino
        self._uno_port = None        # last-connected port
        self._speech_state = "IDLE"  # IDLE | LISTENING | THINKING | TALKING
        self._speaking_active = False  # flips True on first TTS chunk

        # Key manager + LLM
        self.key_manager = KeyManager()
        self.llm = LLMHandler(self.key_manager)

        self.lesson_manager = LessonManager(llm_handler=self.llm)
        self.student_manager = StudentManager(lesson_manager=self.lesson_manager)

        self.current_lesson = None
        self.conversation_history = []
        self.login_window = None
        self.dashboard_window = None

        # audio state
        self._stt_model: WhisperModel|None = None
        self._tts = None

        # TTS queue: tuples of (text, is_sentence_end); sentinel is (None, True)
        self._tts_q: queue.Queue[tuple[str|None, bool]] = queue.Queue(maxsize=128)

        # streaming state (single turn at a time)
        self._streaming = False

        # spinner state
        self._thinking = False
        self._spinner_phase = 0
        self._spinner_glyphs = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

        # pending full text for GUI (printed after TTS finishes)
        self._pending_gui_text: str|None = None

        self.create_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Start Piper
        self._init_tts()
        # NEW: start face tracker in the background (eyes follow face when IDLE)
        self._tracker = FaceTracker(
            send_cmd=self._serial_send,
            get_state=lambda: self._speech_state,
            ensure_serial=self._ensure_serial,
            width=1280, height=720,     # match your camera config
            rate_hz=10.0,               # 10 Hz max command rate
            deadband_deg=1.0
        )
        self._tracker.start()
        # --- Nudge the Arduino to PARK twice on startup (non-blocking) ---
        def _startup_park():
            try:
                # ensure we are connected first
                self._ensure_serial()
                # small wait so UNO finishes boot text
                time.sleep(0.2)
                self._serial_send("park")
                time.sleep(0.12)
                self._serial_send("park")
            except Exception as _e:
                print("[SERIAL] startup park error:", _e)
        threading.Thread(target=_startup_park, daemon=True).start()


        # Drain TTS queue
        self.root.after(20, self._drain_tts_queue)

    # ---- setup helpers ----
    def _init_tts(self):
        try:
            self._tts = PiperEngine(ttsmod.PIPER_BIN, ttsmod.DEFAULT_VOICE)
            self._tts.start()
        except Exception as e:
            print("[TTS] init error:", e)
    
    # ---------- ARDUINO SERIAL HELPERS ----------
    def _ensure_serial(self):
        if self._uno_port:
            return
        try:
            if list_ports is None:
                return
            ports = list(list_ports.comports())
            ports = sorted(ports, key=lambda p: (("ACM" not in p.device), ("USB" not in p.device), p.device))
            if not ports:
                print("[SERIAL] no ports")
                return
            self._uno_port = ports[0].device
            self._uno.connect(self._uno_port, baud=115200)
            print(f"[SERIAL] connected {self._uno_port}")
            # NEW: hard reset pose on boot — double park
            self._uno.send("park"); time.sleep(0.12)
            self._uno.send("park"); time.sleep(0.12)
            print(f"park")
            
            # new: push your preferred durations
            self._uno.send("set_total_listen 6000")
            self._uno.send("set_return 2500")
            self._uno.send("set_total_think 10000")
        except Exception as e:
            print("[SERIAL] connect failed:", e)

    def _serial_send(self, cmd: str):
        try:
            self._ensure_serial()
            if not self._uno or not self._uno.ser or not self._uno.ser.is_open:
                return
            self._uno.send(cmd)
            print(f"[SERIAL] -> {cmd}")
        except Exception as e:
            print("[SERIAL] send failed:", e)


    def _set_state(self, new_state: str):
        """Debounce and print state changes."""
        if self._speech_state == new_state:
            return
        print(f"[STATE] {self._speech_state} -> {new_state}")
        self._speech_state = new_state

    def _ensure_stt(self):
        if self._stt_model is not None: return
        model_dir = FW_TINY  # fixed path you prefer
        if not os.path.isdir(model_dir):
            raise RuntimeError(f"STT model folder not found: {model_dir}")
        os.environ.setdefault("OMP_NUM_THREADS","4")
        print(f"[STT] Loading model: {model_dir} (int8)")
        t0=time.perf_counter()
        self._stt_model = WhisperModel(model_dir, device="cpu", compute_type="int8")
        print(f"[STT] Ready in {time.perf_counter()-t0:.2f}s")

    # ---- UI ----
    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=(20, 15))
        main_frame.pack(fill=tk.BOTH, expand=True)

        header_frame = ttk.Frame(main_frame, style="Header.TFrame")
        header_frame.pack(fill=tk.X, pady=(0, 20), ipady=10)

        ttk.Label(header_frame, text="Lingo - AI English Teacher", style="Header.TLabel").pack(side=tk.LEFT, padx=10)

        self.profile_btn = ttk.Button(
            header_frame,
            text=f"API: {self.key_manager.get_active_label()}",
            command=self._cycle_profile,
            style="TButton"
        )
        self.profile_btn.pack(side=tk.RIGHT, padx=10)

        login_btn = ttk.Button(header_frame, text="Login to Personal Tutor Mode", command=self.open_login, style="Accent.TButton")
        login_btn.pack(side=tk.RIGHT, padx=10)

        chat_frame = ttk.Frame(main_frame, style="Chat.TFrame")
        chat_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        self.chat_display = scrolledtext.ScrolledText(
            chat_frame,
            wrap=tk.WORD,
            font=("Segoe UI", 12),
            height=20,
            padx=15,
            pady=15,
            state='disabled',
            bg="white",
            fg="#2d3436",
            bd=0,
            highlightthickness=0,
            insertbackground="#6c5ce7"
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True)

        input_frame = ttk.Frame(main_frame, style="Input.TFrame")
        input_frame.pack(fill=tk.X)

        # Status label (left)
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(input_frame, textvariable=self.status_var)
        self.status_label.pack(side=tk.LEFT, padx=(0, 10))

        self.user_input = ttk.Entry(input_frame, font=("Segoe UI", 12))
        self.user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.user_input.bind("<Return>", self.send_message)

        # 🎤 Speak button (primary)
        self.speak_btn = ttk.Button(input_frame, text="🎤 Speak", command=self.on_speak, style="Accent.TButton")
        self.speak_btn.pack(side=tk.RIGHT, padx=(0, 10))
        self.speak_btn.focus_set()

        send_btn = ttk.Button(input_frame, text="Send", command=self.send_message, style="Accent.TButton")
        send_btn.pack(side=tk.RIGHT)

        self.display_message("Lingo", "Hello! I'm Lingo, your AI English Teacher. How can I help you today?")

    def set_status(self, text: str):
        self.status_var.set(text)
        self.root.update_idletasks()

    # ---- spinner helpers ----
    def _start_thinking(self):
        if self._thinking: return
        self._thinking = True
        def _tick():
            if not self._thinking: return
            g = self._spinner_glyphs[self._spinner_phase % len(self._spinner_glyphs)]
            self.set_status(f"Thinking… {g}")
            self._spinner_phase += 1
            self.root.after(120, _tick)
        _tick()

    def _stop_thinking(self):
        self._thinking = False
        self.set_status("Ready")

    # ---- chat helpers ----
    def _cycle_profile(self):
        idx = self.llm.next_profile()
        label = self.key_manager.get_active_label()
        self.profile_btn.config(text=f"API: {label}")
        self.display_message("Lingo", f"Switched API profile to: {label}")

    def display_message(self, sender, message):
        self.chat_display.configure(state='normal')
        self.chat_display.tag_config("ai", foreground="#6c5ce7", font=("Segoe UI", 12, "bold"))
        self.chat_display.tag_config("user", foreground="#00b894", font=("Segoe UI", 12, "bold"))
        self.chat_display.tag_config("message", font=("Segoe UI", 12), lmargin1=20, lmargin2=20, spacing3=5)
        self.chat_display.insert(tk.END, f"{sender}: ", "ai" if sender == "Lingo" else "user")
        self.chat_display.insert(tk.END, f"{message}\n\n", "message")
        self.chat_display.see(tk.END)
        self.chat_display.configure(state='disabled')

    def _append_stream_text(self, text: str):
        self.chat_display.configure(state='normal')
        self.chat_display.insert(tk.END, text, "message")
        self.chat_display.see(tk.END)
        self.chat_display.configure(state='disabled')

    # ---- TTS drain (also commits GUI after speech ends) ----
    def _drain_tts_queue(self):
        try:
            item = self._tts_q.get_nowait()
        except queue.Empty:
            pass
        else:
            try:
                if self._tts:
                    text, is_final = item
                    if text is None:
                        # Sentinel: TTS input fully fed; commit GUI text now
                        pending = (self._pending_gui_text or "").strip()
                        if pending:
                            self._append_stream_text(pending + "\n\n")
                            self.conversation_history.append({"role": "assistant", "content": pending})
                        # turn end
                        self.root.config(cursor="")
                        self._stop_thinking()
                        self.set_status("Ready")
                        self._streaming = False
                        self._pending_gui_text = None
                        # --- Arduino: double STOP at end of speech ---
                        # --- Arduino: double STOP shortly AFTER audio finishes ---
                        def _double_stop_after_playback():
                            try:
                                # Wait until audio device has been quiet for 600 ms
                                self._tts.wait_until_quiet(quiet_ms=600)
                                self._serial_send("stop")
                                time.sleep(0.12)
                                self._serial_send("stop")
                                # only now leave TALKING
                                self._speaking_active = False
                                self._set_state("IDLE")
                                # NEW: wait 5s in idle, then resume soft face tracking
                                def _resume_later():
                                    try: self._tracker.resume_and_trackon()
                                    except Exception as _e: print("[TRACK] resume error:", _e)
                                self.root.after(5000, _resume_later)
                            except Exception as _e:
                                print("[SERIAL] stop error:", _e)

                        threading.Thread(target=_double_stop_after_playback, daemon=True).start()


                        
                    else:
                        # --- Arduino: TALK starts on first audio chunk ---
                        if not self._speaking_active and self._speech_state == "THINKING":
                            self._serial_send("talk")
                            self._set_state("TALKING")
                            self._speaking_active = True
                        self._tts.say_chunk(text, final=is_final)
                        self.set_status("Speaking…")
            except Exception as e:
                print("[TTS] error:", e)
        self.root.after(20, self._drain_tts_queue)

    # ---- typed path (TTS-first, GUI-after) ----
    def send_message(self, event=None):
        if self._streaming:
            return

        message = self.user_input.get().strip()
        if not message:
            return

        self.display_message("You", message)
        self.user_input.delete(0, tk.END)

        self.conversation_history.append({"role": "user", "content": message})

        simple = self.get_simple_response(message.lower())
        if simple:
            # TTS-first for simple responses too
            self._begin_turn_gui_header()
            self._pending_gui_text = simple
            self._tts_q.put((simple, True))
            self._tts_q.put((None, True))  # sentinel → print after speech
            return

        lesson_context = None
        if getattr(self.student_manager, "current_user", None) and self.current_lesson:
            lesson_context = {
                "student_name": self.student_manager.current_user["name"],
                "student_level": self.student_manager.current_user["level"],
                "lesson_title": self.current_lesson.get("title", ""),
                "lesson_objective": self.current_lesson.get("objective", "")
            }

        self._begin_turn_gui_header()
        # --- Arduino: THINK for typed path too ---
        self._serial_send("think")
        self._speech_state = "THINKING"
        # NEW: pause tracking while THINK/TALK runs
        try: self._tracker.pause_and_trackoff()
        except Exception as _e: print("[TRACK] pause error:", _e)



        def worker():
            try:
                # Accumulate full text for GUI while feeding TTS immediately
                full_parts = []
                punct_final = (".", "?", "!")
                MAX_WORDS = 10
                buf = []; words = 0; last_flush = time.perf_counter()

                def flush(final=False):
                    nonlocal buf, words, last_flush
                    piece = "".join(buf).strip()
                    if piece and self._tts:
                        self._tts_q.put((piece, final))
                    buf = []; words = 0; last_flush = time.perf_counter()

                for chunk in self.llm.stream_ai_response(
                    message=message,
                    conversation_history=self.conversation_history,
                    lesson_context=lesson_context
                ):
                    full_parts.append(chunk)
                    buf.append(chunk); words += chunk.count(" ")
                    if chunk.endswith(punct_final):
                        flush(final=True)
                        continue
                    if words >= MAX_WORDS or (time.perf_counter() - last_flush) > 0.9:
                        flush(final=False)

                if buf:
                    flush(final=True)

                # hold full text for GUI, then signal TTS turn end
                self._pending_gui_text = "".join(full_parts).strip()
                self._tts_q.put((None, True))  # sentinel
            except Exception as e:
                self._pending_gui_text = f"[Error: {e}]"
                self._tts_q.put((None, True))
                self._serial_send("stop")
                self._set_state("IDLE")


        threading.Thread(target=worker, daemon=True).start()

    # ---- helper: start GUI turn header & state ----
    def _begin_turn_gui_header(self):
        self._streaming = True
        self.root.config(cursor="watch")
        self.chat_display.configure(state='normal')
        self.chat_display.tag_config("ai", foreground="#6c5ce7", font=("Segoe UI", 12, "bold"))
        self.chat_display.tag_config("message", font=("Segoe UI", 12), lmargin1=20, lmargin2=20, spacing3=5)
        self.chat_display.insert(tk.END, "Lingo: ", "ai")
        self.chat_display.configure(state='disabled')
        self.chat_display.see(tk.END)
        self._start_thinking()

    # ---- voice path (TTS-first, GUI-after) ----
    def on_speak(self):
        if self._streaming:
            return
        def _worker():
            try:
                self._ensure_stt()
                # RECORD
                self.set_status("Recording…"); print("[GUI] Recording…")
                
                # NEW: pause tracking and send track_off so gestures have full control
                try: self._tracker.pause_and_trackoff()
                except Exception as _e: print("[TRACK] pause error:", _e)
                
                import random
                side_cmd = random.choice(["listen_left", "listen_right"])
                self._serial_send(side_cmd)
                self._set_state("LISTENING")
                rec = VADRecorder(sample_rate=16000, frame_ms=30, vad_aggr=3,
                                  silence_ms=1200, max_record_s=10,
                                  energy_margin=2.0, energy_min=2200, energy_max=6000)
                self._speech_state = "LISTENING"
                wav_path = rec.record(TEMP_WAV)

                # TRANSCRIBE
                self.set_status("Transcribing…"); print("[GUI] Transcribing…")
                # --- Arduino: THINK during STT/LLM ---
                self._serial_send("think")
                self._set_state("THINKING")

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
                    self._serial_send("stop")
                    self._set_state("IDLE")
                    return

                # push transcript to chat & history
                self.display_message("You", user_text)
                self.conversation_history.append({"role": "user", "content": user_text})

                # lesson context
                lesson_context = None
                if getattr(self.student_manager, "current_user", None) and self.current_lesson:
                    lesson_context = {
                        "student_name": self.student_manager.current_user["name"],
                        "student_level": self.student_manager.current_user["level"],
                        "lesson_title": self.current_lesson.get("title", ""),
                        "lesson_objective": self.current_lesson.get("objective", "")
                    }

                # start turn (GUI header only)
                self._begin_turn_gui_header()

                # TTS-first streaming
                full_parts = []
                punct_final = (".", "?", "!")
                MAX_WORDS = 10
                buf = []; words = 0; last_flush = time.perf_counter()

                def flush(final=False):
                    nonlocal buf, words, last_flush
                    piece = "".join(buf).strip()
                    if piece and self._tts:
                        self._tts_q.put((piece, final))
                    buf = []; words = 0; last_flush = time.perf_counter()

                for chunk in self.llm.stream_ai_response(
                    message=user_text,
                    conversation_history=self.conversation_history,
                    lesson_context=lesson_context
                ):
                    full_parts.append(chunk)
                    buf.append(chunk); words += chunk.count(" ")
                    if chunk.endswith(punct_final):
                        flush(final=True)
                        continue
                    if words >= MAX_WORDS or (time.perf_counter() - last_flush) > 0.9:
                        flush(final=False)

                if buf:
                    flush(final=True)

                self._pending_gui_text = "".join(full_parts).strip()
                self._tts_q.put((None, True))  # sentinel → commit GUI
            except Exception as e:
                self._pending_gui_text = f"[Error: {e}]"
                self._tts_q.put((None, True))
                self._serial_send("stop")
                self._set_state("IDLE")


        threading.Thread(target=_worker, daemon=True).start()

    def get_simple_response(self, message):
        import random
        if any(word in message for word in ["hello", "hi", "hey"]):
            return random.choice([
                "Hello there! How can I help you today?",
                "Hi! What would you like to know?",
                "Greetings! What's on your mind?"
            ])
        elif any(word in message for word in ["how are you", "how's it going"]):
            return "I'm doing well and ready to help! How are you?"
        elif any(word in message for word in ["bye", "goodbye", "see you"]):
            return "Goodbye! Feel free to come back if you have more questions."
        elif "time" in message:
            return f"The current time is {datetime.now().strftime('%H:%M')}."
        elif "date" in message:
            return f"Today's date is {datetime.now().strftime('%Y-%m-%d')}."
        return None

    def open_login(self):
        # Pause face tracking to free the camera and send 'track_off' to UNO
        try:
            if getattr(self, "_tracker", None):
                self._tracker.pause_and_trackoff()
        except Exception as _e:
            print("[TRACK] pause for login error:", _e)

        if self.login_window and self.login_window.winfo_exists():
            self.login_window.lift()
            return
        self.login_window = tk.Toplevel(self.root)
        self.login_window.protocol("WM_DELETE_WINDOW", self.on_login_close)
        LoginScreen(self.login_window, self)
        self.login_window.geometry("400x300")
        self.login_window.transient(self.root)
        self.login_window.grab_set()


    def on_login_close(self):
        if self.login_window:
            self.login_window.destroy()
            self.login_window = None
        try:
            if getattr(self, "_tracker", None):
                # Give recognize_live.py time to release camera cleanly
                self.root.after(1200, self._tracker.resume_and_trackon)
        except Exception as _e:
            print("[TRACK] resume after login error:", _e)


    def return_to_main(self):
        if self.dashboard_window:
            self.dashboard_window.destroy()
            self.dashboard_window = None
        self.root.deiconify()

    def _on_close(self):
        try:
            if self._tts: self._tts.say("Goodbye.")
        except Exception:
            pass
        try:
            if self._tts: self._tts.close()
            if getattr(self, "_tracker", None): self._tracker.stop()
        except Exception:
            pass
        self.root.destroy()

# -------------------- main --------------------
if __name__ == "__main__":
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    root = tk.Tk()
    app = MainAIChat(root)
    root.mainloop()
