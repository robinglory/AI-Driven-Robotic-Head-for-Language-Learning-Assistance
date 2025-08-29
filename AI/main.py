#!/usr/bin/env python3
"""
Single-file Voice Tester — Faster-Whisper (VAD) + OpenRouter LLM + Piper TTS
Target: Raspberry Pi 4 (4GB)

Key goals vs your previous main.py:
- REMOVE dependency on external TTS GUI module (no more TTS/TTS_GUI.py import)
- Keep a simple Tkinter UI (Chat + Settings)
- Keep model resident for fast STT; auto-stop recording via WebRTC VAD
- Call Piper binary directly for TTS (configurable paths)
- Add safe threading so the UI never freezes during STT/LLM/TTS
- Track timings for each stage

Requirements:
  pip install faster-whisper webrtcvad sounddevice requests
  sudo apt-get install -y piper aplay   # (or have Piper installed elsewhere)

Run:
  source ~/myenv/bin/activate
  export OMP_NUM_THREADS=4
  python ai_voice_tester.py

Notes:
- Update Settings → Piper binary / Piper model path to match your system.
- Keys: it will read OpenRouter key from env OPENROUTER_API_KEY, or from
  /home/robinglory/Desktop/Thesis/GUI/keys.json (profiles[] array). The
  "🔄 API Key" button cycles profiles and persists selection to
  ~/.config/ai_voice_tester/state.json
"""
from __future__ import annotations
import os, sys, json, time, wave, struct, math, collections, threading, queue, tempfile, subprocess
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from typing import Optional

# ---------- Third‑party ----------
try:
    import sounddevice as sd
    import webrtcvad
    from faster_whisper import WhisperModel
except Exception as e:
    raise SystemExit("Missing deps. Run: pip install faster-whisper webrtcvad sounddevice\n" + str(e))

# ---------- Paths & Defaults ----------
STT_FW_BASE = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-base.en"
STT_FW_TINY = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-tiny.en"
KEYS_JSON   = "/home/robinglory/Desktop/Thesis/GUI/keys.json"
STATE_DIR   = os.path.expanduser("~/.config/ai_voice_tester")
STATE_PATH  = os.path.join(STATE_DIR, "state.json")
TEMP_WAV    = "/tmp/fw_dialog.wav"

DEFAULTS = {
    # VAD
    "frame_ms": 30,
    "vad_aggr": 3,          # 0..3 (3 = most aggressive)
    "silence_ms": 2000,
    "max_record_s": 12,
    "energy_margin": 2.0,   # energy gate multiplier (auto-calibrated)
    "energy_min": 2200,
    "energy_max": 6000,
    # STT model
    "use_base": True,       # True=base.en, False=tiny.en
    "compute_type": "int8", # good on Pi
    # TTS
    "piper_bin": "/usr/bin/piper",               # adjust as needed
    "piper_model": "/home/robinglory/Desktop/Thesis/TTS/piper/en_US-amy-medium.onnx",  # adjust as needed
    "player_cmd": "aplay",  # or paplay/ffplay (installed)
}

# ---------- Utilities ----------
def _ensure_dirs():
    os.makedirs(STATE_DIR, exist_ok=True)


def _read_json(path: str, default):
    try:
        with open(path, "r") as f: return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(data, f, indent=2)
    os.replace(tmp, path)


# ---------- Key Management ----------
class KeyStore:
    """Load OpenRouter API keys from env or keys.json with profiles.
    - Env var OPENROUTER_API_KEY takes precedence if present.
    - Else reads KEYS_JSON (profiles: [{label: str, ...keys...}]).
    - Persists the selected profile label to STATE_PATH.
    """
    def __init__(self, keys_json: str = KEYS_JSON, state_path: str = STATE_PATH):
        _ensure_dirs()
        self.keys_json = keys_json
        self.state_path = state_path
        self._profiles = []  # type: list[dict]
        self._label = None   # type: Optional[str]
        self._load()

    def _load(self):
        # env key wins
        if os.getenv("OPENROUTER_API_KEY"):
            self._profiles = [{"label": "ENV", "OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY")}]
            self._label = "ENV"
            return
        data = _read_json(self.keys_json, {})
        self._profiles = data.get("profiles", []) if isinstance(data, dict) else []
        saved = _read_json(self.state_path, {})
        self._label = saved.get("profile") if saved else (self._profiles[0]["label"] if self._profiles else None)

    def _persist(self):
        _write_json(self.state_path, {"profile": self._label or ""})

    def labels(self):
        return [p.get("label", f"#{i}") for i,p in enumerate(self._profiles)]

    def current_label(self) -> str:
        return self._label or ""

    def cycle(self) -> str:
        if not self._profiles:
            self._label = "ENV" if os.getenv("OPENROUTER_API_KEY") else ""
            self._persist(); return self.current_label()
        labels = self.labels()
        try:
            i = labels.index(self.current_label())
        except ValueError:
            i = -1
        i = (i + 1) % len(labels)
        self._label = labels[i]
        self._persist()
        return self._label

    def get_api_key(self) -> Optional[str]:
        # env
        if self._label == "ENV" and os.getenv("OPENROUTER_API_KEY"):
            return os.getenv("OPENROUTER_API_KEY")
        # profiles lookup
        for p in self._profiles:
            if p.get("label") == self._label:
                # Try common fields you used before
                for k in ("OPENROUTER_API_KEY", "QWEN_API_KEY", "MISTRAL_API_KEY", "GPT_OSS_API_KEY"):
                    if p.get(k):
                        return p.get(k)
        return None


# ---------- LLM via OpenRouter ----------
import requests
class LLM:
    def __init__(self, keystore: KeyStore, model: str = "openai/gpt-4o-mini"):
        self.keystore = keystore
        self.model = model

    def chat(self, messages: list[dict], max_tokens: int = 256, temperature: float = 0.7) -> str:
        api_key = self.keystore.get_api_key()
        if not api_key:
            raise RuntimeError("No OpenRouter API key. Set OPENROUTER_API_KEY or profiles in keys.json.")
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "http://localhost/",
            "X-Title": "AI Voice Tester",
            "Content-Type": "application/json",
        }
        payload = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


# ---------- Piper TTS Engine (no external module) ----------
class PiperEngine:
    def __init__(self, piper_bin: str, model_path: str, player_cmd: str = "aplay"):
        self.piper_bin = piper_bin
        self.model_path = model_path
        self.player_cmd = player_cmd

    def _check(self):
        if not (os.path.isfile(self.piper_bin) and os.access(self.piper_bin, os.X_OK)):
            raise RuntimeError(f"Piper binary not found or not executable: {self.piper_bin}")
        if not os.path.isfile(self.model_path):
            raise RuntimeError(f"Piper model not found: {self.model_path}")

    def speak(self, text: str):
        text = (text or "").strip()
        if not text: return
        self._check()
        # Create temp WAV
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wavf:
            wav_path = wavf.name
        try:
            # Synthesize using Piper
            proc = subprocess.run([
                self.piper_bin,
                "-m", self.model_path,
                "-f", wav_path,
                "-t", text,
            ], capture_output=True, text=True, check=True)
            # Play WAV
            play_cmd = [self.player_cmd, wav_path]
            subprocess.run(play_cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Piper failed: {e}\n{e.stderr}")
        finally:
            try: os.remove(wav_path)
            except Exception: pass


# ---------- VAD Recorder ----------
class VADRecorder:
    """WebRTC VAD + optional energy gate. Writes a 16k mono WAV and returns its path."""
    def __init__(self, sample_rate=16000, frame_ms=30, vad_aggr=1, silence_ms=500, max_record_s=12, device=None,
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


# ---------- Tkinter App ----------
class VoiceTester(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI Voice Tester — Single File")
        self.geometry("980x720")
        self.cfg = DEFAULTS.copy()
        self._stt_model: Optional[WhisperModel] = None
        self.keystore = KeyStore()
        self.llm = LLM(self.keystore)
        self.tts = PiperEngine(self.cfg["piper_bin"], self.cfg["piper_model"], self.cfg["player_cmd"])
        self._last_ai_text = ""
        self._busy = False
        self._build_ui()

    # ---- UI ----
    def _build_ui(self):
        nb = ttk.Notebook(self); nb.pack(fill=tk.BOTH, expand=True)
        # Chat tab
        chat = ttk.Frame(nb); nb.add(chat, text="Chat")
        self.chat = scrolledtext.ScrolledText(chat, wrap=tk.WORD, font=("Segoe UI", 12))
        self.chat.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self._say("Lingo", "Ready. Click 🎤 to speak or type and Send. Replies auto-speak.")
        row = ttk.Frame(chat); row.pack(fill=tk.X, pady=4)
        self.entry = ttk.Entry(row, font=("Segoe UI", 12)); self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", lambda e: self.on_send())
        ttk.Button(row, text="Send", command=self.on_send).pack(side=tk.LEFT, padx=6)
        header = ttk.Frame(chat); header.pack(fill=tk.X, pady=4)
        ttk.Button(header, text="🎤 Speak", command=self.on_speak).pack(side=tk.RIGHT)
        ttk.Button(header, text="🔈 Speak Reply", command=self.on_speak_reply).pack(side=tk.RIGHT, padx=6)
        ttk.Button(header, text="🔎 Devices", command=self.on_list_devices).pack(side=tk.RIGHT, padx=6)
        ttk.Button(header, text="🔄 API Key", command=self.on_rotate_keys).pack(side=tk.RIGHT, padx=6)
        self.status_var = tk.StringVar(value=f"API: {self.keystore.current_label() or '—'}");
        ttk.Label(chat, textvariable=self.status_var).pack(anchor="w", padx=8, pady=4)
        # Settings tab
        st = ttk.Frame(nb); nb.add(st, text="Settings")
        self.vars = {}
        def add_row(r, label, key, kind="entry"):
            ttk.Label(st, text=label).grid(row=r, column=0, sticky="w", padx=8, pady=4)
            if kind=="check":
                v=tk.BooleanVar(value=self.cfg[key]); ttk.Checkbutton(st, variable=v).grid(row=r, column=1, sticky="w")
            else:
                v=tk.StringVar(value=str(self.cfg[key])); ttk.Entry(st, textvariable=v, width=40).grid(row=r, column=1, sticky="w")
            self.vars[key]=v
        r=0
        # STT
        ttk.Label(st, text="STT – Faster‑Whisper").grid(row=r, column=0, columnspan=2, sticky="w", padx=8); r+=1
        add_row(r,"Frame (ms)","frame_ms"); r+=1
        add_row(r,"VAD aggressiveness (0–3)","vad_aggr"); r+=1
        add_row(r,"Silence stop (ms)","silence_ms"); r+=1
        add_row(r,"Max record (s)","max_record_s"); r+=1
        add_row(r,"Energy margin","energy_margin"); r+=1
        add_row(r,"Energy min","energy_min"); r+=1
        add_row(r,"Energy max","energy_max"); r+=1
        add_row(r,"Use base.en (else tiny.en)","use_base","check"); r+=1
        add_row(r,"compute_type","compute_type"); r+=1
        # TTS
        ttk.Label(st, text="TTS – Piper").grid(row=r, column=0, columnspan=2, sticky="w", padx=8); r+=1
        add_row(r,"Piper binary","piper_bin"); r+=1
        add_row(r,"Piper model (.onnx)","piper_model"); r+=1
        add_row(r,"Player command","player_cmd"); r+=1
        ttk.Button(st, text="Apply", command=self.apply_settings).grid(row=r, column=0, columnspan=2, pady=8)
        r+=1
        ttk.Button(st, text="🔊 TTS Test", command=lambda: self._safe_thread(self._tts_test)).grid(row=r, column=0, columnspan=2, pady=4)

    def _say(self, who, msg):
        self.chat.insert(tk.END, f"{who}: {msg}\n\n"); self.chat.see(tk.END)

    def set_status(self, text):
        self.status_var.set(text); self.update_idletasks()

    # ---- Settings & Apply ----
    def apply_settings(self):
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
        # Update TTS engine with new paths
        self.tts = PiperEngine(self.cfg["piper_bin"], self.cfg["piper_model"], self.cfg["player_cmd"])
        self._stt_model = None  # force STT reload if model/compute type changed
        self._say("System", f"Applied: {self.cfg}")

    # ---- Threads helper ----
    def _safe_thread(self, target):
        if self._busy: return
        self._busy = True
        t = threading.Thread(target=lambda: self._thread_wrapper(target), daemon=True)
        t.start()

    def _thread_wrapper(self, target):
        try:
            target()
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            self._busy = False
            self.after(0, lambda: self.set_status(f"API: {self.keystore.current_label() or '—'}"))

    # ---- STT ----
    def _ensure_model(self):
        if self._stt_model is not None: return
        model_dir = STT_FW_BASE if self.cfg["use_base"] else STT_FW_TINY
        if not os.path.isdir(model_dir):
            raise RuntimeError(f"Model folder not found: {model_dir}")
        os.environ.setdefault("OMP_NUM_THREADS","4")
        self.after(0, lambda: self._say("System", f"Loading STT model: {model_dir} ({self.cfg['compute_type']})"))
        t0=time.perf_counter()
        self._stt_model = WhisperModel(model_dir, device="cpu", compute_type=self.cfg["compute_type"])
        self.after(0, lambda: self._say("System", f"STT ready in {time.perf_counter()-t0:.2f}s"))

    def _stt_transcribe_once(self) -> str:
        self._ensure_model()
        rec = VADRecorder(sample_rate=16000, frame_ms=int(self.cfg["frame_ms"]), vad_aggr=int(self.cfg["vad_aggr"]),
                          silence_ms=int(self.cfg["silence_ms"]), max_record_s=int(self.cfg["max_record_s"]),
                          energy_margin=float(self.cfg["energy_margin"]), energy_min=int(self.cfg["energy_min"]),
                          energy_max=int(self.cfg["energy_max"]))
        self.after(0, lambda: self.set_status("Recording…"))
        wav_path = rec.record(TEMP_WAV)
        self.after(0, lambda: self.set_status("Transcribing…"))
        t2=time.perf_counter()
        segments, info = self._stt_model.transcribe(wav_path, language="en", beam_size=3, vad_filter=True,
                                                     vad_parameters=dict(min_silence_duration_ms=400))
        txt="".join(s.text for s in segments).strip()
        self.after(0, lambda: self._say("STT", f"(len≈{info.duration:.2f}s, asr={time.perf_counter()-t2:.2f}s)"))
        return txt

    # ---- LLM ----
    def _llm_reply(self, user_text:str) -> str:
        messages=[
            {"role":"system","content":"You are Lingo, a friendly English tutor in a robot head. Keep answers under 2 sentences and end with a short question."},
            {"role":"user","content":user_text},
        ]
        return self.llm.chat(messages)

    # ---- TTS ----
    def _tts_speak(self, text:str):
        if not text.strip(): return
        self.tts.speak(text)

    # ---- Pipeline threads ----
    def _pipeline_speak(self):
        t0=time.perf_counter()
        try:
            text = self._stt_transcribe_once()
            if not text:
                self.after(0, lambda: self._say("STT", "(No speech detected)"))
                return
            self.after(0, lambda: self._say("You", text))
            self.after(0, lambda: self.set_status("Thinking…"))
            t_llm = time.perf_counter()
            ai = self._llm_reply(text)
            t_tts = time.perf_counter()
            self._last_ai_text = ai
            self.after(0, lambda: self._say("Lingo", ai))
            self.after(0, lambda: self.set_status("Speaking…"))
            self._tts_speak(ai)
            t_end = time.perf_counter()
            self.after(0, lambda: self._say("System", f"timings: total={(t_end-t0):.2f}s | LLM={(t_tts-t_llm):.2f}s | TTS={(t_end-t_tts):.2f}s"))
        finally:
            self.after(0, lambda: self.set_status(f"API: {self.keystore.current_label() or '—'}"))

    def _pipeline_send(self, text: str):
        t0=time.perf_counter()
        try:
            if not text: return
            self.after(0, lambda: self._say("You", text))
            self.after(0, lambda: self.set_status("Thinking…"))
            t_llm = time.perf_counter()
            ai = self._llm_reply(text)
            t_tts = time.perf_counter()
            self._last_ai_text = ai
            self.after(0, lambda: self._say("Lingo", ai))
            self.after(0, lambda: self.set_status("Speaking…"))
            self._tts_speak(ai)
            t_end = time.perf_counter()
            self.after(0, lambda: self._say("System", f"timings: total={(t_end-t0):.2f}s | LLM={(t_tts-t_llm):.2f}s | TTS={(t_end-t_tts):.2f}s"))
        finally:
            self.after(0, lambda: self.set_status(f"API: {self.keystore.current_label() or '—'}"))

    def _tts_test(self):
        self.after(0, lambda: self.set_status("Speaking…"))
        self._tts_speak("Hello, this is a Piper test on your robotic head. How are you today?")

    # ---- UI Handlers ----
    def on_speak(self):
        self._safe_thread(self._pipeline_speak)

    def on_speak_reply(self):
        if not self._last_ai_text.strip():
            self._say("System","Nothing to speak yet."); return
        self._safe_thread(lambda: self._tts_speak(self._last_ai_text))

    def on_send(self):
        text=self.entry.get().strip()
        self.entry.delete(0,tk.END)
        if not text: return
        self._safe_thread(lambda: self._pipeline_send(text))

    def on_list_devices(self):
        try:
            out = sd.query_devices()
            text_lines=[f"{i}: {d['name']} (in={d.get('max_input_channels',0)}, out={d.get('max_output_channels',0)})" for i,d in enumerate(out)]
            self._say("Devices (sounddevice)", "\n"+"\n".join(text_lines))
        except Exception as e:
            self._say("Devices", f"error: {e}")

    def on_rotate_keys(self):
        label = self.keystore.cycle()
        self.set_status(f"Using API account: {label or '—'}")
        self._say("System", f"Switched to API account: {label or '—'}")


if __name__ == "__main__":
    app = VoiceTester()
    app.mainloop()
