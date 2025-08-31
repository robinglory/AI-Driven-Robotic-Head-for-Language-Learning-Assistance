#!/usr/bin/env python3
"""
AI Voice Tester — LLM + Faster-Whisper (VAD) + Piper TTS (STREAMING)

What this version does:
- Keeps your Faster-Whisper + WebRTC VAD STT (auto-stop), default max 10s.
- Uses your existing key manager (keys.json profiles) OR env var.
- Integrates the STREAMING Piper GUI module and calls _say_stream() directly.
- Adds true token streaming from OpenRouter → Piper: speech starts immediately.
- Keeps your non-stream "Speak Reply" path intact.

Deps:
  pip install faster-whisper webrtcvad sounddevice requests

Run:
  source ~/myenv/bin/activate
  export OMP_NUM_THREADS=4
  python /home/robinglory/Desktop/Thesis/AI/main.py
"""
from __future__ import annotations
import os, time, json, wave, struct, math, collections, threading, importlib.machinery, importlib.util
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# ------------------- External module paths -------------------
STT_TTS_DIR   = "/home/robinglory/Desktop/Thesis/TTS/streaming_piper_gui.py"   # streaming GUI module
KEY_MANAGER_PY = "/home/robinglory/Desktop/Thesis/GUI/key_manager.py"

# ------------------- Dynamic imports -------------------
def _load_module_from_path(mod_name: str, file_path: str):
    loader = importlib.machinery.SourceFileLoader(mod_name, file_path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module

_ttsmod = _load_module_from_path("streaming_piper_gui", STT_TTS_DIR)
_keymgr = _load_module_from_path("key_manager", KEY_MANAGER_PY)
KeyManager = _keymgr.KeyManager

# ------------------- Third-party STT libs -------------------
try:
    import sounddevice as sd
    import webrtcvad
    from faster_whisper import WhisperModel
except Exception as e:
    raise SystemExit("Missing deps. Run: pip install faster-whisper webrtcvad sounddevice\n" + str(e))

# ------------------- OpenRouter streaming (SSE) -------------------
import requests

def openrouter_stream(api_key: str, model: str, messages, temperature=0.7):
    """Yield text deltas as they arrive via SSE."""
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "http://localhost/",
        "X-Title": "AI Voice Tester",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
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

def speak_streaming_tokens(tts_gui, token_iter, flush_words=5, flush_punct=".,;:!?"):
    """
    Buffer a few words / punctuation, then flush into streaming Piper.
    This is smoother than per-token writes and still near-real-time.
    """
    buf = []
    words = 0
    def _flush():
        nonlocal buf, words
        if not buf:
            return
        chunk = "".join(buf).strip()
        if chunk:
            if hasattr(tts_gui, "_say_stream"):
                tts_gui._say_stream(chunk)            # persistent Piper → aplay
            elif hasattr(tts_gui, "proc") and hasattr(tts_gui.proc, "say"):
                tts_gui.proc.say(chunk)
            else:
                # Fallback: textbox + generate (still streams in your GUI)
                tts_gui.text_input.delete("1.0", tk.END)
                tts_gui.text_input.insert(tk.END, chunk)
                tts_gui.generate_and_play()
        buf = []
        words = 0

    for tok in token_iter:
        buf.append(tok)
        words += tok.count(" ")
        if tok.endswith(tuple(flush_punct)) or words >= flush_words:
            _flush()
    _flush()

# ------------------- Faster-Whisper paths -------------------
FW_BASE = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-base.en"
FW_TINY = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-tiny.en"
TEMP_WAV = "/tmp/fw_dialog.wav"

# ------------------- Simple LLM (non-stream) -------------------
class LLM:
    def __init__(self, key_manager: KeyManager, model: str = "openai/gpt-4o-mini"):
        self.key_manager = key_manager
        self.model = model
    def _get_api_key(self) -> str:
        keys = self.key_manager.get_keys()
        # Try common labels; fall back to OPENROUTER_API_KEY if present
        api_key = (keys.get("OPENROUTER_API_KEY")
                   or keys.get("QWEN_API_KEY")
                   or keys.get("MISTRAL_API_KEY")
                   or keys.get("GPT_OSS_API_KEY")
                   or os.getenv("OPENROUTER_API_KEY"))
        if not api_key:
            raise RuntimeError("No OpenRouter API key in profile or env.")
        return api_key
    def chat(self, messages: list[dict], max_tokens: int = 256, temperature: float = 0.7) -> str:
        api_key = self._get_api_key()
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "http://localhost/",
            "X-Title": "AI Voice Tester",
            "Content-Type": "application/json",
        }
        payload = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        r = requests.post(url, headers=headers, json=payload, timeout=60); r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    def stream_chat(self, messages, temperature=0.7):
        api_key = self._get_api_key()
        return openrouter_stream(api_key, self.model, messages, temperature=temperature)

# ------------------- VAD Recorder -------------------
class VADRecorder:
    """WebRTC VAD + optional energy gate. Writes a 16k mono WAV and returns its path."""
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

# ------------------- App GUI -------------------
DEFAULTS = {
    # VAD
    "frame_ms": 30,
    "vad_aggr": 3,
    "silence_ms": 2000,
    "max_record_s": 10,      # << capped to 10s per your request
    "energy_margin": 2.0,
    "energy_min": 2200,
    "energy_max": 6000,
    # STT model
    "use_base": True,         # True=base.en, False=tiny.en
    "compute_type": "int8",   # good on Pi
}

class VoiceTester(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI Voice Tester — Faster-Whisper VAD + Streaming Piper")
        self.geometry("980x720")
        self.key_manager = KeyManager()
        self.llm = LLM(self.key_manager)
        self.cfg = DEFAULTS.copy()
        self._last_ai_text = ""

        # TTS: streaming Piper GUI kept in a hidden window
        self.tts_root = tk.Toplevel(self); self.tts_root.withdraw()
        self.tts = _ttsmod.PiperTTSPlayer(self.tts_root)  # exposes _say_stream()

        # STT model (lazy)
        self._stt_model: WhisperModel|None = None

        self._build_ui()

    # -------- UI --------
    def _build_ui(self):
        nb = ttk.Notebook(self); nb.pack(fill=tk.BOTH, expand=True)

        # Chat tab
        chat_tab = ttk.Frame(nb); nb.add(chat_tab, text="Chat")
        self.chat = scrolledtext.ScrolledText(chat_tab, wrap=tk.WORD, font=("Segoe UI", 12))
        self.chat.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self._say("Lingo", "Ready. 🎤 STT works; type and Send; or use 🛰️ Stream for instant speaking.")
        row = ttk.Frame(chat_tab); row.pack(fill=tk.X, pady=4)
        self.entry = ttk.Entry(row, font=("Segoe UI", 12)); self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", lambda e: self.on_send())
        ttk.Button(row, text="Send", command=self.on_send).pack(side=tk.LEFT, padx=6)
        ttk.Button(row, text="🛰️ Stream", command=self.on_send_streaming).pack(side=tk.LEFT)

        header = ttk.Frame(chat_tab); header.pack(fill=tk.X, pady=4)
        ttk.Button(header, text="🎤 Speak", command=self.on_speak).pack(side=tk.RIGHT)
        ttk.Button(header, text="🔈 Speak Reply", command=self.on_speak_reply).pack(side=tk.RIGHT, padx=6)
        ttk.Button(header, text="🔎 Devices", command=self.on_list_devices).pack(side=tk.RIGHT, padx=6)
        ttk.Button(header, text="🔄 API Key", command=self.on_rotate_keys).pack(side=tk.RIGHT, padx=6)

        self.status_var = tk.StringVar(value="Ready"); ttk.Label(chat_tab, textvariable=self.status_var).pack(anchor="w", padx=8, pady=4)

        # STT Settings tab
        stt_tab = ttk.Frame(nb); nb.add(stt_tab, text="STT Settings")
        self.vars = {}
        def add_row(r, label, key, kind="entry"):
            ttk.Label(stt_tab, text=label).grid(row=r, column=0, sticky="w", padx=8, pady=4)
            if kind=="check":
                v=tk.BooleanVar(value=self.cfg[key]); ttk.Checkbutton(stt_tab, variable=v).grid(row=r, column=1, sticky="w")
            else:
                v=tk.StringVar(value=str(self.cfg[key])); ttk.Entry(stt_tab, textvariable=v, width=10).grid(row=r, column=1, sticky="w")
            self.vars[key]=v
        r=0
        add_row(r,"Frame (ms)","frame_ms"); r+=1
        add_row(r,"VAD aggressiveness (0–3)","vad_aggr"); r+=1
        add_row(r,"Silence stop (ms)","silence_ms"); r+=1
        add_row(r,"Max record (s)","max_record_s"); r+=1
        add_row(r,"Energy margin","energy_margin"); r+=1
        add_row(r,"Energy min","energy_min"); r+=1
        add_row(r,"Energy max","energy_max"); r+=1
        add_row(r,"Use base.en (else tiny.en)","use_base","check"); r+=1
        add_row(r,"compute_type","compute_type"); r+=1
        ttk.Button(stt_tab, text="Apply", command=self.apply_stt).grid(row=r, column=0, columnspan=2, pady=8)

    def apply_stt(self):
        for k,v in self.vars.items():
            if isinstance(v, tk.BooleanVar):
                self.cfg[k]=bool(v.get())
            else:
                if k in ("frame_ms","vad_aggr","silence_ms","max_record_s","energy_min","energy_max"):
                    try: self.cfg[k]=int(float(v.get()))
                    except: pass
                elif k in ("energy_margin",):
                    try: self.cfg[k]=float(v.get())
                    except: pass
                else:
                    self.cfg[k]=v.get()
        self._say("System", f"STT settings updated: {self.cfg}")
        self._stt_model=None   # reload on next use

    # -------- helpers --------
    def _say(self, who, msg):
        self.chat.insert(tk.END, f"{who}: {msg}\n\n"); self.chat.see(tk.END)
    def set_status(self, text):
        self.status_var.set(text); self.update_idletasks()

    # -------- STT --------
    def _ensure_model(self):
        if self._stt_model is not None: return
        model_dir = FW_BASE if self.cfg["use_base"] else FW_TINY
        if not os.path.isdir(model_dir):
            raise RuntimeError(f"Model folder not found: {model_dir}")
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
        segments, info = self._stt_model.transcribe(wav_path, language="en", beam_size=3, vad_filter=True,
                                                     vad_parameters=dict(min_silence_duration_ms=400))
        txt="".join(s.text for s in segments).strip()
        self._say("STT", f"(len≈{info.duration:.2f}s, asr={time.perf_counter()-t2:.2f}s)")
        return txt

    # -------- TTS helpers --------
    def tts_speak(self, text:str):
        if not text.strip(): return
        # DIRECT streaming path → lowest latency
        if hasattr(self.tts, "_say_stream"):
            self.tts._say_stream(text)
        else:
            self.tts.text_input.delete("1.0",tk.END); self.tts.text_input.insert(tk.END,text); self.tts.generate_and_play()

    # -------- LLM wrappers --------
    def llm_reply(self,user_text:str)->str:
        messages=[
            {"role":"system","content":"You are Lingo, a friendly English tutor in a robot head. Keep answers under 2 sentences and end with a short question."},
            {"role":"user","content":user_text},
        ]
        return self.llm.chat(messages)
    def llm_stream(self,user_text:str):
        messages=[
            {"role":"system","content":"You are Lingo, a friendly English tutor in a robot head. Keep answers under 2 sentences and end with a short question."},
            {"role":"user","content":user_text},
        ]
        return messages, self.llm.stream_chat(messages, temperature=0.7)

    # -------- UI actions --------
    def on_speak(self):
        def _worker():
            try:
                text=self.stt_capture_and_transcribe()
                if not text:
                    self._say("STT","(No speech detected)"); self.set_status("Ready"); return
                self._say("You",text); self.set_status("Thinking…")
                ai=self.llm_reply(text); self._last_ai_text=ai; self._say("Lingo",ai)
                self.set_status("Speaking…"); self.tts_speak(ai); self.set_status("Ready")
            except Exception as e:
                messagebox.showerror("Error",str(e)); self.set_status("Ready")
        threading.Thread(target=_worker, daemon=True).start()

    def on_speak_reply(self):
        if not self._last_ai_text.strip():
            self._say("System","Nothing to speak yet."); return
        self.set_status("Speaking…")
        def _worker():
            try:
                self.tts_speak(self._last_ai_text)
            finally:
                self.set_status("Ready")
        threading.Thread(target=_worker, daemon=True).start()

    def on_send(self):
        text=self.entry.get().strip()
        if not text: return
        self.entry.delete(0,tk.END); self._say("You",text); self.set_status("Thinking…")
        def _worker():
            try:
                ai=self.llm_reply(text); self._last_ai_text=ai; self._say("Lingo",ai)
                self.tts_speak(ai)
            except Exception as e:
                messagebox.showerror("LLM error",str(e))
            finally:
                self.set_status("Ready")
        threading.Thread(target=_worker, daemon=True).start()

    def on_send_streaming(self):
        user_text = self.entry.get().strip()
        if not user_text: return
        self.entry.delete(0,tk.END)
        self._say("You", user_text)
        self.set_status("Streaming…")

        messages, token_iter = self.llm_stream(user_text)

        # UI stream (optional—show text as it arrives)
        def _ui_stream():
            try:
                acc = []
                for delta in openrouter_stream(self.llm._get_api_key(), self.llm.model, messages, temperature=0.7):
                    acc.append(delta)
                    self.chat.insert(tk.END, delta); self.chat.see(tk.END)
                full = "".join(acc).strip()
                if full:
                    self._last_ai_text = full
                    self.chat.insert(tk.END, "\n\n")
            except Exception as e:
                messagebox.showerror("Error", str(e))

        # Audio stream (speech immediately)
        def _tts_stream():
            try:
                speak_streaming_tokens(self.tts, token_iter, flush_words=5)
            except Exception as e:
                messagebox.showerror("TTS stream error", str(e))
            finally:
                self.set_status("Ready")

        threading.Thread(target=_ui_stream, daemon=True).start()
        threading.Thread(target=_tts_stream, daemon=True).start()

    def on_list_devices(self):
        try:
            out = sd.query_devices()
            lines=[f"{i}: {d['name']} (in={d.get('max_input_channels',0)}, out={d.get('max_output_channels',0)})" for i,d in enumerate(out)]
            self._say("Devices", "\n".join(lines))
        except Exception as e:
            self._say("Devices", f"error: {e}")

    def on_rotate_keys(self):
        try:
            keys_path = os.path.join(os.path.dirname(KEY_MANAGER_PY), "keys.json")
            if not os.path.exists(keys_path):
                messagebox.showerror("Error", "keys.json file not found"); return
            with open(keys_path, 'r') as f:
                accounts_data = json.load(f)
            profiles = accounts_data.get("profiles", [])
            if not profiles:
                messagebox.showerror("Error", "No profiles found in keys.json"); return

            current_profile = self.key_manager.get_current_profile()
            current_index = 0
            for i, profile in enumerate(profiles):
                if profile.get("label") == current_profile:
                    current_index = i; break
            next_index = (current_index + 1) % len(profiles)
            next_profile = profiles[next_index]["label"]
            self.key_manager.switch_profile(next_profile)
            self._say("System", f"Switched to API account: {next_profile}")
            self.set_status(f"Using API account: {next_profile}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to rotate API keys: {str(e)}")

if __name__ == "__main__":
    app = VoiceTester()
    app.mainloop()
