#!/usr/bin/env python3
"""
STT → LLM(token stream) → TTS (Piper RAW stream, correct sample-rate)

- Continuous RAW PCM to a persistent 'aplay' (doesn't stop after first word).
- Auto-detect voice sample rate from the .json beside the .onnx (no static).
- Minimal UI: [🎤 Speak] [ text ] [Send]
"""

from __future__ import annotations
import os, sys, time, json, wave, struct, math, collections, threading, subprocess, shutil
from queue import Queue, Empty
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# --- Reuse your existing module for paths (PIPER_BIN, DEFAULT_VOICE) ---
# (/home/robinglory/Desktop/Thesis/TTS/streaming_piper_gui.py)
import importlib.machinery, importlib.util
def _load_module_from_path(mod_name: str, file_path: str):
    loader = importlib.machinery.SourceFileLoader(mod_name, file_path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
TTS_MOD_PATH = "/home/robinglory/Desktop/Thesis/TTS/streaming_piper_gui.py"
ttsmod = _load_module_from_path("streaming_piper_gui", TTS_MOD_PATH)  # gives PIPER_BIN, DEFAULT_VOICE  :contentReference[oaicite:2]{index=2}

# --- Optional key manager (your file) ---
KEY_MANAGER_PY = "/home/robinglory/Desktop/Thesis/GUI/key_manager.py"
try:
    keymgr_mod = _load_module_from_path("key_manager", KEY_MANAGER_PY)
    KeyManager = keymgr_mod.KeyManager
except Exception:
    KeyManager = None

# --- Deps ---
try:
    import sounddevice as sd
    import webrtcvad
    from faster_whisper import WhisperModel
except Exception as e:
    raise SystemExit("Missing deps. Run:\n  pip install faster-whisper webrtcvad sounddevice requests\n" + str(e))

import requests

# ------------------- OpenRouter SSE -------------------
def openrouter_stream(api_key: str, model: str, messages, temperature=0.7):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "http://localhost/",
        "X-Title": "AI Voice Tester",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages, "temperature": temperature, "stream": True}
    with requests.post(url, headers=headers, json=payload, stream=True, timeout=300) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                j = json.loads(data)
                delta = j["choices"][0]["delta"].get("content", "")
                if delta:
                    yield delta
            except Exception:
                continue

# ------------------- Piper RAW (persistent) -------------------
def _voice_json_path(onnx_path: str)->str|None:
    base, _ = os.path.splitext(onnx_path)
    j = base + ".json"
    return j if os.path.isfile(j) else None

def _infer_sample_rate(onnx_path: str, default_sr: int = 22050)->int:
    # Allow manual override (useful if your JSON is missing)
    env = os.environ.get("PIPER_SR")
    if env:
        try: return int(env)
        except: pass
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
    # 1) Explicit path from your module
    if piper_bin_hint and os.path.isfile(piper_bin_hint) and os.access(piper_bin_hint, os.X_OK):
        return [piper_bin_hint]
    # 2) PATH
    p = shutil.which("piper")
    if p: return [p]
    # 3) venv bin
    cand = os.path.join(sys.prefix, "bin", "piper")
    if os.path.isfile(cand) and os.access(cand, os.X_OK): return [cand]
    # 4) module runner
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
        self._p1 = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self._p2 = subprocess.Popen([aplay, "-r", str(self.sr), "-f", "S16_LE", "-t", "raw", "-c", "1"],
                                    stdin=self._p1.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, bufsize=0)
        # let aplay own the stdout pipe
        self._p1.stdout.close()

    def say(self, text: str):
        if not text or not text.strip(): return
        if not self._p1 or not self._p1.stdin:
            raise RuntimeError("Piper not started.")
        with self._lock:
            try:
                self._p1.stdin.write(text.strip() + "\n")
                self._p1.stdin.flush()
            except BrokenPipeError:
                # one restart try
                self.close(); self.start()
                self._p1.stdin.write(text.strip() + "\n")
                self._p1.stdin.flush()

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

# ------------------- STT -------------------
FW_BASE = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-base.en"
FW_TINY = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-tiny.en"
TEMP_WAV = "/tmp/fw_dialog.wav"

class VADRecorder:
    """WebRTC VAD + energy gate; writes 16k mono WAV and returns its path."""
    def __init__(self, sample_rate=16000, frame_ms=30, vad_aggr=3, silence_ms=2000, max_record_s=10, device=None,
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

# ------------------- LLM wrapper -------------------
class LLM:
    def __init__(self, model: str = "openai/gpt-4o-mini"):
        self.model = model
        self.key_manager = KeyManager() if KeyManager else None
    def _get_api_key(self)->str:
        if self.key_manager:
            keys = self.key_manager.get_keys()
            api_key = (keys.get("OPENROUTER_API_KEY")
                       or keys.get("QWEN_API_KEY")
                       or keys.get("MISTRAL_API_KEY")
                       or keys.get("GPT_OSS_API_KEY"))
            if api_key: return api_key
        env = os.getenv("OPENROUTER_API_KEY")
        if not env:
            raise RuntimeError("No OpenRouter API key (keys.json or env OPENROUTER_API_KEY).")
        return env
    def stream_chat(self, messages, temperature=0.7):
        return openrouter_stream(self._get_api_key(), self.model, messages, temperature)

# ------------------- Minimal GUI -------------------
DEFAULTS = {
    "frame_ms": 30, "vad_aggr": 3, "silence_ms": 2000, "max_record_s": 10,
    "energy_margin": 2.0, "energy_min": 2200, "energy_max": 6000,
    "use_base": True, "compute_type": "int8",
}

class VoiceTester(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI Voice Tester — Streaming STT→LLM→Piper (RAW, auto-SR)")
        self.geometry("980x720")
        self.cfg = DEFAULTS.copy()
        self._last_ai_text = ""

        # LLM + Piper
        self.llm = LLM()
        self.piper = PiperEngine(ttsmod.PIPER_BIN, ttsmod.DEFAULT_VOICE)  # from your file  :contentReference[oaicite:3]{index=3}
        self.piper.start()

        # STT model (lazy)
        self._stt_model: WhisperModel|None = None

        # UI
        self._build_ui()
        self._say("Lingo", "Ready. Press 🎤 Speak, or type and Send. Streaming TTS is enabled.")

        # Speak a quick hello so you know the pipeline is good
        self.piper.say("Hello. Streaming text to speech is ready.")

        # TTS queue: workers → Tk main → Piper
        self.tts_q: Queue[str] = Queue(maxsize=64)
        self.after(20, self._drain_tts_queue_on_main)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- UI ----
    def _build_ui(self):
        main = ttk.Frame(self); main.pack(fill=tk.BOTH, expand=True)
        self.chat = scrolledtext.ScrolledText(main, wrap=tk.WORD, font=("Segoe UI", 12))
        self.chat.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        row = ttk.Frame(main); row.pack(fill=tk.X, pady=4)
        self.entry = ttk.Entry(row, font=("Segoe UI", 12)); self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", lambda e: self.on_send())
        ttk.Button(row, text="Send", command=self.on_send).pack(side=tk.LEFT, padx=6)
        header = ttk.Frame(main); header.pack(fill=tk.X, pady=4)
        ttk.Button(header, text="🎤 Speak", command=self.on_speak).pack(side=tk.RIGHT)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(main, textvariable=self.status_var).pack(anchor="w", padx=8, pady=4)

    def _say(self, who, msg):
        self.chat.insert(tk.END, f"{who}: {msg}\n\n"); self.chat.see(tk.END)
    def set_status(self, text): self.status_var.set(text); self.update_idletasks()

    # ---- STT ----
    def _ensure_model(self):
        if self._stt_model is not None: return
        model_dir = FW_BASE if self.cfg["use_base"] else FW_TINY
        if not os.path.isdir(model_dir): raise RuntimeError(f"Model folder not found: {model_dir}")
        os.environ.setdefault("OMP_NUM_THREADS","4")
        self._say("System", f"Loading STT model: {model_dir} ({self.cfg['compute_type']})")
        t0=time.perf_counter()
        self._stt_model = WhisperModel(model_dir, device="cpu", compute_type=self.cfg["compute_type"])
        self._say("System", f"STT ready in {time.perf_counter()-t0:.2f}s")

    def stt_capture_and_transcribe(self)->str:
        self._ensure_model()
        rec = VADRecorder(sample_rate=16000, frame_ms=int(self.cfg["frame_ms"]), vad_aggr=int(self.cfg["vad_aggr"]),
                          silence_ms=int(self.cfg["silence_ms"]), max_record_s=int(self.cfg["max_record_s"]),
                          energy_margin=float(self.cfg["energy_margin"]), energy_min=int(self.cfg["energy_min"]),
                          energy_max=int(self.cfg["energy_max"]))
        self.set_status("Recording…")
        wav_path = rec.record(TEMP_WAV)
        self.set_status("Transcribing…")
        t2=time.perf_counter()
        segments, info = self._stt_model.transcribe(
            wav_path, language="en", beam_size=3, vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=400)
        )
        txt = "".join(s.text for s in segments).strip()
        self._say("STT", f"(len≈{info.duration:.2f}s, asr={time.perf_counter()-t2:.2f}s)")
        return txt

    # ---- LLM streaming → UI + TTS batching ----
    def stream_llm_to_ui_and_tts(self, messages):
        punct = ".,;:!?"
        buf = []; words = 0; acc = []
        try:
            for delta in self.llm.stream_chat(messages, temperature=0.7):
                # UI
                self.chat.insert(tk.END, delta); self.chat.see(tk.END)
                acc.append(delta)
                # TTS batches (~5 words or punctuation)
                buf.append(delta); words += delta.count(" ")
                if delta.endswith(tuple(punct)) or words >= 5:
                    chunk = "".join(buf).strip()
                    if chunk: self.tts_q.put(chunk)
                    buf = []; words = 0
            if buf: self.tts_q.put("".join(buf).strip())
        except Exception as e:
            messagebox.showerror("Stream error", str(e))
        finally:
            full = "".join(acc).strip()
            if full: self._last_ai_text = full
            self.chat.insert(tk.END, "\n\n")

    def _drain_tts_queue_on_main(self):
        try:
            chunk = self.tts_q.get_nowait()
        except Empty:
            pass
        else:
            try:
                self.piper.say(chunk)
            except Exception as e:
                print("[TTS] error:", e)
        self.after(20, self._drain_tts_queue_on_main)

    # ---- UI actions ----
    def on_speak(self):
        def _worker():
            try:
                user_text = self.stt_capture_and_transcribe()
                if not user_text:
                    self._say("STT","(No speech detected)"); self.set_status("Ready"); return
                self._say("You", user_text)
                self.set_status("Streaming…")
                messages = [
                    {"role":"system","content":"You are Lingo, a friendly English tutor. Keep answers under 2 sentences and end with a short question. Don't use excessive punctuation marks or symbols"},
                    {"role":"user","content":user_text},
                ]
                self.stream_llm_to_ui_and_tts(messages)
            except Exception as e:
                messagebox.showerror("Error", str(e))
            finally:
                self.set_status("Ready")
        threading.Thread(target=_worker, daemon=True).start()

    def on_send(self):
        user_text = self.entry.get().strip()
        if not user_text: return
        self.entry.delete(0, tk.END)
        self._say("You", user_text)
        self.set_status("Streaming…")
        messages = [
            {"role":"system","content":"You are Lingo, a friendly English tutor. Keep answers under 2 sentences and end with a short question. Don't use excessive punctuation marks or symbols"},
            {"role":"user","content":user_text},
        ]
        def _worker():
            try:
                self.stream_llm_to_ui_and_tts(messages)
            finally:
                self.set_status("Ready")
        threading.Thread(target=_worker, daemon=True).start()

    def _on_close(self):
        try: self.piper.say("Goodbye.")
        except Exception: pass
        self.piper.close()
        self.destroy()

# ------------------- main -------------------
if __name__ == "__main__":
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    app = VoiceTester()
    app.mainloop()
