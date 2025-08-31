#!/usr/bin/env python3
"""
Piper TTS GUI — Streaming (persistent Piper process)
- Extremely low overhead: keep one Piper process alive; stream text into stdin; audio pipes to aplay.
- One-shot per reply (no per-sentence spawning). Punctuation controls pauses.
- Still supports Save WAV and Jaw Envelope export (those synth to file on demand).
- No Python piper bindings required. Uses your compiled piper binary.

Paths are prefilled for your setup; adjust if needed.
"""
import os, sys, time, json, wave, re, hashlib, tempfile, subprocess, random
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import pygame
import numpy as np

# ----------------- Your paths (adjust if you moved things) -----------------
PIPER_BIN   = "/home/robinglory/Desktop/Thesis/TTS/piper/build/piper"
DEFAULT_VOICE = "/home/robinglory/Desktop/Thesis/TTS/piper/models/en_US-hfc_female-medium.onnx"

# Helpful on your Pi: make sure espeak-ng data is seen
os.environ.setdefault("ESPEAKNG_DATA", "/usr/lib/aarch64-linux-gnu/espeak-ng-data")
os.environ.setdefault("ESPEAK_DATA_PATH", "/usr/lib/aarch64-linux-gnu/espeak-ng-data")
# Piper shared libs in build dir
ld = os.environ.get("LD_LIBRARY_PATH", "")
if "/home/robinglory/Desktop/Thesis/TTS/piper/build" not in ld:
    os.environ["LD_LIBRARY_PATH"] = "/home/robinglory/Desktop/Thesis/TTS/piper/build" + (":"+ld if ld else "")

# ----------------- Tiny tooltip (pure Tk) -----------------
class Tooltip:
    def __init__(self, widget, text, wraplength=320, delay=500):
        self.widget, self.text, self.wraplength, self.delay = widget, text, wraplength, delay
        self.id = None; self.tip = None
        widget.bind("<Enter>", self._enter)
        widget.bind("<Leave>", self._leave)
        widget.bind("<ButtonPress>", self._leave)
    def _enter(self, _): self._schedule()
    def _leave(self, _): self._unschedule(); self._hide()
    def _schedule(self):
        self._unschedule(); self.id = self.widget.after(self.delay, self._show)
    def _unschedule(self):
        if self.id: self.widget.after_cancel(self.id); self.id=None
    def _show(self):
        if self.tip or not self.text: return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tw = tk.Toplevel(self.widget); tw.wm_overrideredirect(True); tw.wm_geometry(f"+{x}+{y}")
        frame = ttk.Frame(tw, padding=8, style="Tooltip.TFrame"); frame.pack()
        ttk.Label(frame, text=self.text, justify=tk.LEFT, wraplength=self.wraplength, style="Tooltip.TLabel").pack()
    def _hide(self):
        if self.tip: self.tip.destroy(); self.tip=None

# ----------------- Persistent Piper process (streaming) -----------------
class PiperProc:
    def __init__(self, piper_bin: str, voice_onnx: str, player_cmd=("aplay",)):
        if not os.path.isfile(piper_bin):
            raise FileNotFoundError(f"Piper binary not found: {piper_bin}")
        if not os.path.isfile(voice_onnx):
            raise FileNotFoundError(f"Voice model not found: {voice_onnx}")
        # Start Piper (stdout = WAV) and pipe into player
        self.p1 = subprocess.Popen([piper_bin, "-m", voice_onnx, "-f", "-"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, bufsize=1)
        try:
            self.p2 = subprocess.Popen(player_cmd, stdin=self.p1.stdout)
        except FileNotFoundError:
            # Fallback to ffplay if aplay missing
            self.p2 = subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-"], stdin=self.p1.stdout,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Allow p1 to receive SIGPIPE if p2 dies
        self.p1.stdout.close()
    def say(self, text: str):
        if not text.strip(): return
        try:
            self.p1.stdin.write(text + "\n")
            self.p1.stdin.flush()
        except Exception as e:
            raise RuntimeError(f"Failed to write to Piper: {e}")
    def close(self):
        try:
            if self.p1 and self.p1.stdin and not self.p1.stdin.closed:
                try: self.p1.stdin.close()
                except Exception: pass
            if self.p1: self.p1.terminate()
        except Exception: pass
        try:
            if self.p2: self.p2.terminate()
        except Exception: pass

# ----------------- GUI App -----------------
class PiperTTSPlayer:
    """GUI class signature kept the same on purpose (generate_and_play + .text_input)
    so /home/robinglory/Desktop/Thesis/AI/main.py can import and use it directly.
    """
    def __init__(self, root):
        self.root = root
        self.root.title("Piper TTS — Streaming (fast)")
        self.voice_model = tk.StringVar(value=DEFAULT_VOICE)
        self.proc: PiperProc|None = None
        self.cache_dir = os.path.join(tempfile.gettempdir(), "piper_tts_cache")
        os.makedirs(self.cache_dir, exist_ok=True)

        # Theme
        style = ttk.Style()
        preferred = "clam" if "clam" in style.theme_names() else style.theme_use()
        style.theme_use(preferred)
        style.configure("Primary.TButton", padding=(12,6), font=("",10,"bold"))
        style.configure("Toolbar.TFrame", padding=(8,8))
        style.configure("Tooltip.TFrame", relief="solid", borderwidth=1)
        style.configure("Tooltip.TLabel", background="#ffffe0")

        container = ttk.Frame(self.root, padding=6); container.pack(fill=tk.BOTH, expand=True)
        # Toolbar
        bar = ttk.Frame(container, style="Toolbar.TFrame"); bar.pack(fill=tk.X)
        ttk.Button(bar, text="Generate & Play", style="Primary.TButton", command=self.generate_and_play).pack(side=tk.LEFT)
        ttk.Button(bar, text="Stop", command=self.stop_playback).pack(side=tk.LEFT, padx=6)
        ttk.Button(bar, text="Save WAV…", command=self.save_to_file).pack(side=tk.LEFT, padx=6)
        ttk.Button(bar, text="Export Jaw Envelope", command=self.export_envelope_current).pack(side=tk.LEFT)
        self.status = tk.StringVar(value="Ready"); ttk.Label(bar, textvariable=self.status).pack(side=tk.RIGHT)

        # Model chooser
        row = ttk.Frame(container); row.pack(fill=tk.X, pady=(6,2))
        ttk.Label(row, text="Model path:").pack(side=tk.LEFT)
        self.model_entry = ttk.Entry(row, textvariable=self.voice_model, width=80); self.model_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Button(row, text="Browse…", command=self.voice_model).pack(side=tk.LEFT)

        # Text box
        ttk.Label(container, text="Enter text to speak:").pack(anchor="w", padx=2)
        self.text_input = scrolledtext.ScrolledText(container, wrap=tk.WORD, width=80, height=10)
        self.text_input.pack(fill=tk.BOTH, expand=True)
        # Quick presets
        quick = ttk.Frame(container); quick.pack(fill=tk.X, pady=4)
        ttk.Label(quick, text="Quick tests:").pack(side=tk.LEFT)
        ttk.Button(quick, text="Friendly intro", command=lambda: self._set_text("Hi! I'm Lingo. How can I help you today?")).pack(side=tk.LEFT, padx=4)
        ttk.Button(quick, text="Calm explanation", command=lambda: self._set_text("Let me explain that step by step. First, we set up the sensor. Then, we calibrate it.")).pack(side=tk.LEFT, padx=4)

        # Keys
        self.root.bind("<Return>", lambda e: self.generate_and_play())
        self.root.bind("<Escape>", lambda e: self.stop_playback())

        # Warm-up + start persistent Piper
        self._start_proc()
        try:
            self._say_stream("hello")
        except Exception:
            pass

    # ------------- Piper process lifecycle -------------
    def _start_proc(self):
        self._stop_proc()
        self.proc = PiperProc(PIPER_BIN, self.voice_model.get(), ("aplay",))
        self.status.set("Voice ready (streaming)")
    def _stop_proc(self):
        if self.proc:
            self.proc.close(); self.proc=None
    def __del__(self):
        self._stop_proc()

    # ------------- UI helpers -------------
    def _set_text(self, s):
        self.text_input.delete("1.0", tk.END); self.text_input.insert(tk.END, s)

    # ------------- Streaming speak -------------
    def _say_stream(self, text: str):
        if not self.proc:
            self._start_proc()
        self.proc.say(text)

    def generate_and_play(self):
        text = self.text_input.get("1.0", tk.END).strip()
        if not text:
            self.status.set("Please enter some text"); return
        self.status.set("Speaking (stream)…")
        try:
            self._say_stream(text)
            self.status.set("Ready")
        except Exception as e:
            self.status.set(f"Error: {e}")

    def stop_playback(self):
        # We can't easily stop mid-stream without killing the player; simplest is to restart pipeline
        try:
            self._start_proc()
            self.status.set("Stopped")
        except Exception as e:
            self.status.set(f"Stop error: {e}")

    # ------------- Save / Export (to-file synthesis) -------------
    def _synth_to_wav_file(self, text: str, out_wav: str):
        if not os.path.isfile(PIPER_BIN):
            raise RuntimeError(f"Piper binary not found: {PIPER_BIN}")
        if not os.path.isfile(self.voice_model.get()):
            raise RuntimeError(f"Voice model not found: {self.voice_model.get()}")
        p = subprocess.Popen([PIPER_BIN, "-m", self.voice_model.get(), "-f", out_wav],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = p.communicate(text)
        if p.returncode != 0:
            raise RuntimeError(f"Piper failed: {stderr}\n{stdout}")
        return out_wav

    def save_to_file(self):
        text = self.text_input.get("1.0", tk.END).strip()
        if not text:
            self.status.set("Please enter some text"); return
        p = filedialog.asksaveasfilename(defaultextension=".wav", filetypes=[("WAV", ".wav")])
        if not p: return
        try:
            self._synth_to_wav_file(text, p)
            self.status.set(f"Saved: {p}")
        except Exception as e:
            self.status.set(f"Error saving: {e}")

    def export_envelope_current(self):
        text = self.text_input.get("1.0", tk.END).strip()
        if not text:
            self.status.set("Please enter some text"); return
        out = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", ".json")], title="Save jaw envelope JSON")
        if not out: return
        try:
            tmp = os.path.join(tempfile.gettempdir(), f"piper_env_{int(time.time())}.wav")
            self._synth_to_wav_file(text, tmp)
            env = self._rms_envelope(tmp, frame_ms=10)
            with open(out, "w") as f:
                json.dump({"frame_ms": 10, "values": env}, f)
            os.remove(tmp)
            self.status.set(f"Envelope saved: {out}")
        except Exception as e:
            self.status.set(f"Envelope error: {e}")

    def _rms_envelope(self, wav_path, frame_ms=10):
        with wave.open(wav_path, "rb") as wf:
            n_channels = wf.getnchannels(); sampwidth = wf.getsampwidth(); fr = wf.getframerate(); n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)
        dtype = np.int16 if sampwidth == 2 else np.int8
        data = np.frombuffer(raw, dtype=dtype)
        if n_channels > 1:
            data = data.reshape(-1, n_channels).mean(axis=1)
        data = data.astype(np.float32) / (np.iinfo(dtype).max if dtype == np.int16 else 127.0)
        hop = max(1, int(fr * (frame_ms/1000.0)))
        values = []
        for i in range(0, len(data), hop):
            seg = data[i:i+hop]
            if len(seg) == 0: break
            rms = float(np.sqrt(np.mean(seg**2) + 1e-9))
            values.append(rms)
        mx = max(values) if values else 1.0
        if mx > 0: values = [min(1.0, v / mx) for v in values]
        return values

if __name__ == "__main__":
    # If you want to run standalone for quick tests
    root = tk.Tk()
    app = PiperTTSPlayer(root)
    root.mainloop()
