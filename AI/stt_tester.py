#!/usr/bin/env python3
"""
Standalone STT tester (no LLM, no TTS)
Folder: /home/robinglory/Desktop/Thesis/AI

What it does
------------
• Record 5s from your chosen ALSA device (arecord)
• Or open an existing WAV file
• Optional safe-normalize if the audio is clipped
• Transcribe with whisper.cpp CLI and show timings
• Play the audio (aplay)

Assumptions
-----------
• Your STT wrapper file defines these correctly:
    WHISPER_DIR, CLI_BIN, MODEL_BASE, MODEL_TINY, TEMP_WAV, (optional) make_env()
• You already built whisper-cli at: WHISPER_DIR/build/bin/whisper-cli

Run
---
python /home/robinglory/Desktop/Thesis/AI/stt_tester.py
"""
from __future__ import annotations
import os, sys, time, subprocess, importlib.machinery, importlib.util, wave, audioop
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox

# ------------------- Paths to your existing STT module -------------------
STT_PY = "/home/robinglory/Desktop/Thesis/STT/whisper.cpp/60sWhisperGui.py"

# ------------------- Dynamic import -------------------
def _load_module_from_path(mod_name: str, file_path: str):
    loader = importlib.machinery.SourceFileLoader(mod_name, file_path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module

_stt = _load_module_from_path("stt_whisper_gui", STT_PY)

# ------------------- Helpers -------------------
def wav_stats(path: str):
    """Return (duration_s, peak, rms, nch, rate) for a WAV file."""
    try:
        with wave.open(path, 'rb') as w:
            nchan = w.getnchannels(); width = w.getsampwidth(); rate = w.getframerate(); frames = w.getnframes()
            data = w.readframes(frames)
        if nchan > 1:
            data = audioop.tomono(data, width, 1, 0)
        peak = audioop.max(data, width) if data else 0
        rms = audioop.rms(data, width) if data else 0
        dur = frames / float(rate) if rate else 0.0
        return dur, peak, rms, nchan, rate
    except Exception:
        return 0.0, 0, 0, 0, 0

def normalize_if_clipped(src_path: str, dst_path: str, peak_limit: int = 30000) -> tuple[bool, str]:
    """If 16-bit PCM is clipped (peak ~32768), scale down to <= peak_limit.
    Returns (changed, message)."""
    try:
        with wave.open(src_path, 'rb') as r:
            nchan, sampwidth, fr, nframes = r.getnchannels(), r.getsampwidth(), r.getframerate(), r.getnframes()
            if sampwidth != 2:
                return False, "Not 16-bit PCM; skipping normalize."
            frames = r.readframes(nframes)
        # mono for peak calc
        mono = audioop.tomono(frames, sampwidth, 1, 0) if nchan > 1 else frames
        peak = audioop.max(mono, sampwidth) if mono else 0
        if peak <= peak_limit:
            return False, f"Peak {peak} <= {peak_limit}; no normalize."
        # scale factor
        gain = float(peak_limit) / float(peak)
        scaled = audioop.mul(frames, sampwidth, gain)
        with wave.open(dst_path, 'wb') as w:
            w.setnchannels(nchan); w.setsampwidth(sampwidth); w.setframerate(fr)
            w.writeframes(scaled)
        return True, f"Clipped peak {peak} → normalized with gain {gain:.2f}."
    except Exception as e:
        return False, f"Normalize failed: {e}"

# ------------------- GUI -------------------
class STTTester(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("STT Tester — whisper.cpp (CLI)")
        self.geometry("960x660")

        # Defaults
        self.mic_index = tk.IntVar(value=3)       # your card 3
        self.seconds   = tk.IntVar(value=5)
        self.threads   = tk.IntVar(value=4)       # -t
        self.beams     = tk.IntVar(value=3)       # -bs
        self.use_base  = tk.BooleanVar(value=True)  # base.en vs tiny.en
        self.do_norm   = tk.BooleanVar(value=True)  # normalize when clipped

        self.current_wav = tk.StringVar(value=_stt.TEMP_WAV)
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        top = ttk.Frame(self, padding=10); top.pack(fill=tk.BOTH, expand=True)

        # Controls
        ctrl = ttk.LabelFrame(top, text="Controls"); ctrl.pack(fill=tk.X)
        ttk.Button(ctrl, text="🎙️ Record 5s", command=self.on_record).pack(side=tk.LEFT, padx=4, pady=6)
        ttk.Button(ctrl, text="📂 Open WAV", command=self.on_open).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="📝 Transcribe", command=self.on_transcribe).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="▶️ Play", command=self.on_play).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="🔎 Devices", command=self.on_devices).pack(side=tk.RIGHT, padx=4)

        # Settings row
        row = ttk.Frame(top); row.pack(fill=tk.X, pady=(6,0))
        ttk.Label(row, text="Mic card").pack(side=tk.LEFT); ttk.Entry(row, textvariable=self.mic_index, width=5).pack(side=tk.LEFT, padx=(2,10))
        ttk.Label(row, text="Seconds").pack(side=tk.LEFT); ttk.Entry(row, textvariable=self.seconds, width=5).pack(side=tk.LEFT, padx=(2,10))
        ttk.Label(row, text="Threads (-t)").pack(side=tk.LEFT); ttk.Entry(row, textvariable=self.threads, width=5).pack(side=tk.LEFT, padx=(2,10))
        ttk.Label(row, text="Beams (-bs)").pack(side=tk.LEFT); ttk.Entry(row, textvariable=self.beams, width=5).pack(side=tk.LEFT, padx=(2,10))
        ttk.Checkbutton(row, text="Use base.en (else tiny.en)", variable=self.use_base).pack(side=tk.LEFT, padx=8)
        ttk.Checkbutton(row, text="Safe-normalize when clipped", variable=self.do_norm).pack(side=tk.LEFT, padx=8)

        # File field
        file_row = ttk.Frame(top); file_row.pack(fill=tk.X, pady=(6,0))
        ttk.Label(file_row, text="Current WAV:").pack(side=tk.LEFT)
        ttk.Entry(file_row, textvariable=self.current_wav).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)

        # Output
        out = ttk.LabelFrame(top, text="Output")
        out.pack(fill=tk.BOTH, expand=True, pady=8)
        self.log = scrolledtext.ScrolledText(out, wrap=tk.WORD, font=("DejaVu Sans Mono", 11))
        self.log.pack(fill=tk.BOTH, expand=True)

    # ---------- Helpers ----------
    def say(self, *parts):
        self.log.insert(tk.END, " ".join(str(p) for p in parts) + "\n")
        self.log.see(tk.END)
        self.update_idletasks()

    # ---------- Actions ----------
    def on_devices(self):
        try:
            out = subprocess.check_output(["arecord","-l"], text=True, stderr=subprocess.STDOUT)
        except Exception as e:
            out = f"arecord -l error: {e}"
        self.say("Devices:\n" + out.strip())

    def on_play(self):
        wav = self.current_wav.get().strip()
        if not os.path.isfile(wav):
            messagebox.showerror("No file", f"WAV not found: {wav}")
            return
        try:
            subprocess.run(["aplay", wav], check=True)
        except Exception as e:
            messagebox.showerror("aplay", str(e))

    def on_open(self):
        path = filedialog.askopenfilename(title="Open WAV", filetypes=[("WAV files","*.wav")])
        if not path:
            return
        self.current_wav.set(path)
        d,p,r,nc,fr = wav_stats(path)
        self.say(f"Opened: {path}")
        self.say(f"Info: duration={d:.2f}s peak={p} rms={r} nch={nc} rate={fr}")

    def on_record(self):
        wav = _stt.TEMP_WAV
        self.current_wav.set(wav)
        os.makedirs(os.path.dirname(wav), exist_ok=True)
        self.say("Recording…")
        cmd = ["arecord","-D",f"plughw:{self.mic_index.get()},0","-f","S16_LE","-r","16000","-c","1","-d",str(self.seconds.get()),wav]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError:
            self.say("plughw failed; retrying -D default…")
            cmd = ["arecord","-D","default","-f","S16_LE","-r","16000","-c","1","-d",str(self.seconds.get()),wav]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        d,p,r,nc,fr = wav_stats(wav)
        self.say(f"Captured: duration={d:.2f}s peak={p} rms={r}")
        if self.do_norm.get() and p >= 32000:
            norm_path = os.path.join(os.path.dirname(wav), "_norm.wav")
            changed, msg = normalize_if_clipped(wav, norm_path)
            self.say("Normalize:", msg)
            if changed:
                self.current_wav.set(norm_path)
                d,p,r,nc,fr = wav_stats(norm_path)
                self.say(f"After normalize: duration={d:.2f}s peak={p} rms={r}")

    def on_transcribe(self):
        wav = self.current_wav.get().strip()
        if not os.path.isfile(wav):
            messagebox.showerror("No file", f"WAV not found: {wav}")
            return
        WHISPER_DIR = _stt.WHISPER_DIR
        CLI_BIN     = _stt.CLI_BIN
        MODEL       = _stt.MODEL_BASE if self.use_base.get() else _stt.MODEL_TINY
        out_base    = os.path.join(WHISPER_DIR, "last_transcript")
        env = os.environ.copy()
        try:
            env.update(_stt.make_env())
        except Exception:
            pass
        # Build command (CLI flags only)
        cmd = [
            CLI_BIN,
            "-m", MODEL,
            "-t", str(self.threads.get()),
            "-bs", str(self.beams.get()),
            "-l", "en",
            "-f", wav,
            "-otxt",
            "-of", out_base,
        ]
        self.say("\nwhisper-cli:", " ".join(cmd))
        t0 = time.perf_counter()
        try:
            subprocess.run(cmd, check=True, cwd=WHISPER_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            self.say("whisper-cli error:", e)
            return
        t1 = time.perf_counter()
        dt = t1 - t0
        txt_path = out_base + ".txt"
        text = open(txt_path, "r", encoding="utf-8", errors="ignore").read().strip() if os.path.exists(txt_path) else "(no .txt produced)"
        self.say(f"Transcribe time: {dt:.2f}s — Threads={self.threads.get()} Beams={self.beams.get()} Model={'base' if self.use_base.get() else 'tiny'}")
        self.say("\nTranscript:\n" + text + "\n")

# ------------------- Entry -------------------
if __name__ == "__main__":
    app = STTTester()
    app.mainloop()
