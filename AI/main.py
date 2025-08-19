#!/usr/bin/env python3
"""
AI Voice Tester — LLM + Faster‑Whisper (VAD) + Piper TTS
Folder: /home/robinglory/Desktop/Thesis/AI/main.py

What changed vs your previous AI/main:
- Replaced whisper.cpp CLI with Faster‑Whisper (CTranslate2) + WebRTC VAD auto‑stop
- Loads model ONCE and reuses it (very fast transcribes)
- Keeps your OpenRouter LLM + Piper TTS flow
- Adds an STT Settings tab to tweak VAD + model params

Model folders (as you created):
  /home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-base.en
  /home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-tiny.en

One‑time deps:
  pip install faster-whisper webrtcvad sounddevice requests

Run:
  source ~/myenv/bin/activate
  export OMP_NUM_THREADS=4
  python /home/robinglory/Desktop/Thesis/AI/main.py
"""
from __future__ import annotations
import os, time, json, wave, struct, math, collections, threading, queue, subprocess, importlib.machinery, importlib.util
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import requests

# ------------------- Fixed external module paths -------------------
STT_TTS_DIR = "/home/robinglory/Desktop/Thesis/TTS/TTS_GUI.py"
KEY_MANAGER_PY = "/home/robinglory/Desktop/Thesis/GUI/key_manager.py"

# ------------------- Load modules by path -------------------
def _load_module_from_path(mod_name: str, file_path: str):
    loader = importlib.machinery.SourceFileLoader(mod_name, file_path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module

_tts = _load_module_from_path("piper_tts_gui", STT_TTS_DIR)
_keymgr = _load_module_from_path("key_manager", KEY_MANAGER_PY)
KeyManager = _keymgr.KeyManager

# ------------------- Third‑party STT libs -------------------
try:
    import sounddevice as sd
    import webrtcvad
    from faster_whisper import WhisperModel
except Exception as e:
    raise SystemExit("Missing deps. Run: pip install faster-whisper webrtcvad sounddevice\n"+str(e))

# ------------------- Paths for Faster‑Whisper models -------------------
FW_BASE = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-base.en"
FW_TINY = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-tiny.en"
TEMP_WAV = "/tmp/fw_dialog.wav"

# ------------------- LLM via OpenRouter -------------------
class LLM:
    def __init__(self, key_manager: KeyManager, model: str = "openai/gpt-4o-mini"):
        self.key_manager = key_manager
        self.model = model
    def chat(self, messages: list[dict], max_tokens: int = 256, temperature: float = 0.7) -> str:
        keys = self.key_manager.get_keys()
        api_key = keys.get("QWEN_API_KEY") or keys.get("MISTRAL_API_KEY") or keys.get("GPT_OSS_API_KEY")
        if not api_key:
            raise RuntimeError("No API key found in current profile. Configure keys.json in GUI folder.")
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "HTTP-Referer": "http://localhost/", "X-Title": "AI Voice Tester", "Content-Type": "application/json"}
        payload = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        r = requests.post(url, headers=headers, json=payload, timeout=60); r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

# ------------------- VAD Recorder -------------------
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

# ------------------- App GUI -------------------
DEFAULTS = {
    # VAD
    "frame_ms": 30,
    "vad_aggr": 1,
    "silence_ms": 1000,
    "max_record_s": 12,
    "energy_margin": 2.0,
    "energy_min": 2200,
    "energy_max": 6000,
    # Model
    "use_base": True,         # True=base.en, False=tiny.en
    "compute_type": "int8",   # best for Pi
}

class VoiceTester(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI Voice Tester — Faster‑Whisper VAD")
        self.geometry("980x720")
        self.key_manager = KeyManager()
        self.llm = LLM(self.key_manager)
        self.cfg = DEFAULTS.copy()
        self._last_ai_text = ""
        # TTS player
        self.tts_root = tk.Toplevel(self); self.tts_root.withdraw()
        self.tts = _tts.PiperTTSPlayer(self.tts_root)
        # STT model (lazy load on first use)
        self._stt_model: WhisperModel|None = None
        self._build_ui()

    # -------- UI --------
    def _build_ui(self):
        nb = ttk.Notebook(self); nb.pack(fill=tk.BOTH, expand=True)
        # Chat tab
        chat_tab = ttk.Frame(nb); nb.add(chat_tab, text="Chat")
        self.chat = scrolledtext.ScrolledText(chat_tab, wrap=tk.WORD, font=("Segoe UI", 12))
        self.chat.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self._say("Lingo", "Voice test ready. Click 🎤 to dictate, or type below and Send. Typed replies will auto‑speak.")
        row = ttk.Frame(chat_tab); row.pack(fill=tk.X, pady=4)
        self.entry = ttk.Entry(row, font=("Segoe UI", 12)); self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", lambda e: self.on_send())
        ttk.Button(row, text="Send", command=self.on_send).pack(side=tk.LEFT, padx=6)
        header = ttk.Frame(chat_tab); header.pack(fill=tk.X, pady=4)
        ttk.Button(header, text="🎤 Speak", command=self.on_speak).pack(side=tk.RIGHT)
        ttk.Button(header, text="🔈 Speak Reply", command=self.on_speak_reply).pack(side=tk.RIGHT, padx=6)
        ttk.Button(header, text="🔎 Devices", command=self.on_list_devices).pack(side=tk.RIGHT, padx=6)
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
        add_row(r,"VAD aggressiveness (0-3)","vad_aggr"); r+=1
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
                # cast numbers where expected
                if k in ("frame_ms","vad_aggr","silence_ms","max_record_s","energy_min","energy_max"):
                    try: self.cfg[k]=int(float(v.get()))
                    except: pass
                elif k in ("energy_margin",):
                    try: self.cfg[k]=float(v.get())
                    except: pass
                else:
                    self.cfg[k]=v.get()
        self._say("System", f"STT settings updated: {self.cfg}")
        # force model reload if compute_type or model toggled
        self._stt_model=None

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
        self._stt_model = WhisperModel(model_dir, device="cpu", compute_type=self.cfg["compute_type"])  # keep resident
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

    # -------- TTS --------
    def tts_speak(self,text:str):
        if not text.strip(): return
        self.tts.text_input.delete("1.0",tk.END); self.tts.text_input.insert(tk.END,text); self.tts.generate_and_play()

    # -------- LLM --------
    def llm_reply(self,user_text:str)->str:
        messages=[
            {"role":"system","content":"You are Lingo, a friendly English tutor in a robot head. Keep answers under 2 sentences and end with a short question."},
            {"role":"user","content":user_text},
        ]
        return self.llm.chat(messages)

    # -------- UI actions --------
    def on_speak(self):
        try:
            text=self.stt_capture_and_transcribe()
            if not text:
                self._say("STT","(No speech detected)"); self.set_status("Ready"); return
            self._say("You",text); self.set_status("Thinking…")
            ai=self.llm_reply(text); self._last_ai_text=ai; self._say("Lingo",ai)
            self.set_status("Speaking…"); self.tts_speak(ai); self.set_status("Ready")
        except Exception as e:
            messagebox.showerror("Error",str(e)); self.set_status("Ready")

    def on_speak_reply(self):
        if not self._last_ai_text.strip(): self._say("System","Nothing to speak yet."); return
        self.set_status("Speaking…"); self.tts_speak(self._last_ai_text); self.set_status("Ready")

    def on_send(self):
        text=self.entry.get().strip()
        if not text: return
        self.entry.delete(0,tk.END); self._say("You",text); self.set_status("Thinking…")
        try:
            ai=self.llm_reply(text); self._last_ai_text=ai; self._say("Lingo",ai); self.tts_speak(ai); self.set_status("Ready")
        except Exception as e:
            messagebox.showerror("LLM error",str(e)); self.set_status("Ready")

    def on_list_devices(self):
        try:
            out = sd.query_devices()
            text_lines=[f"{i}: {d['name']} (in={d.get('max_input_channels',0)}, out={d.get('max_output_channels',0)})" for i,d in enumerate(out)]
            self._say("Devices (sounddevice)", "\n"+"\n".join(text_lines))
        except Exception as e:
            self._say("Devices", f"error: {e}")

# ------------------- Entry -------------------
if __name__ == "__main__":
    app = VoiceTester(); app.mainloop()
