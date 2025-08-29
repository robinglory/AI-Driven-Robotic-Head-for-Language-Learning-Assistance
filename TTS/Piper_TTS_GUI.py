#!/usr/bin/env python3
"""
Piper TTS GUI (CLI backend)
- No Python piper package required. Calls the piper *binary* directly.
- Keeps your same GUI/UX, caching, playback, and envelope export.
- Sliders remain for UX but do not affect synthesis (piper CLI doesn’t expose those params).

Quick start on your Pi:
  pip install pygame numpy
  python Piper_TTS_GUI_CLI.py

Sanity test (outside the app):
  /home/robinglory/Desktop/Thesis/TTS/piper/build/piper \
    -m /home/robinglory/Desktop/Thesis/TTS/piper/models/en_US-hfc_female-medium.onnx \
    -f /tmp/piper_test.wav <<< 'hello from piper'
  aplay /tmp/piper_test.wav
"""
import wave
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import pygame
from threading import Thread
import os
import tempfile
import hashlib
import re
import time
import json
import random
import numpy as np
import subprocess
from dataclasses import dataclass

# --- CLI mode paths (adjust if needed) ---
PIPER_BIN = "/home/robinglory/Desktop/Thesis/TTS/piper/build/piper"
DEFAULT_VOICE = "/home/robinglory/Desktop/Thesis/TTS/piper/models/en_US-hfc_female-medium.onnx"

# ---------- Tiny tooltip helper (pure Tk, no extradeps) ----------
class Tooltip:
    def __init__(self, widget, text, wraplength=320, delay=500):
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self.delay = delay
        self.id = None
        self.tip = None
        widget.bind("<Enter>", self._enter)
        widget.bind("<Leave>", self._leave)
        widget.bind("<ButtonPress>", self._leave)
    def _enter(self, _):
        self._schedule()
    def _leave(self, _):
        self._unschedule(); self._hide()
    def _schedule(self):
        self._unschedule(); self.id = self.widget.after(self.delay, self._show)
    def _unschedule(self):
        if self.id:
            self.widget.after_cancel(self.id); self.id = None
    def _show(self):
        if self.tip or not self.text: return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        frame = ttk.Frame(tw, padding=8, style="Tooltip.TFrame"); frame.pack()
        label = ttk.Label(frame, text=self.text, justify=tk.LEFT, wraplength=self.wraplength, style="Tooltip.TLabel")
        label.pack()
    def _hide(self):
        if self.tip:
            self.tip.destroy(); self.tip = None

# --- Lightweight SynthesisConfig to keep UI state + cache keys ---
@dataclass
class SynthesisConfig:
    volume: float = 1.0
    length_scale: float = 1.0
    noise_scale: float = 0.667
    noise_w_scale: float = 0.8
    normalize_audio: bool = True

# --- Piper CLI helper ---
def synth_to_wav_cli(text: str, voice_model_path: str, out_wav: str):
    if not os.path.isfile(PIPER_BIN):
        raise RuntimeError(f"Piper binary not found: {PIPER_BIN}")
    if not os.path.isfile(voice_model_path):
        raise RuntimeError(f"Voice model not found: {voice_model_path}")
    # Feed text via stdin to piper
    proc = subprocess.Popen([PIPER_BIN, "-m", voice_model_path, "-f", out_wav],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    stdout, stderr = proc.communicate(text)
    if proc.returncode != 0:
        raise RuntimeError(f"piper CLI failed:\n{stderr}\n{stdout}")

class PiperTTSPlayer:
    def __init__(self, root):
        self.root = root
        self.root.title("Piper TTS – Robotic Head Edition (CLI)")

        # --- style/theme ---
        style = ttk.Style()
        preferred = "clam" if "clam" in style.theme_names() else style.theme_use()
        style.theme_use(preferred)
        style.configure("Primary.TButton", padding=(12, 6), font=("", 10, "bold"))
        style.configure("Toolbar.TFrame", padding=(8, 8))
        style.configure("Group.TLabelframe", padding=(10, 8))
        style.configure("Group.TLabelframe.Label", font=("", 10, "bold"))
        style.configure("Status.TLabel", foreground="#1a1a1a")
        style.configure("Header.TLabel", font=("", 11, "bold"))
        style.configure("Tooltip.TFrame", relief="solid", borderwidth=1)
        style.configure("Tooltip.TLabel", background="#ffffe0")

        # --- audio ---
        pygame.mixer.init()

        # --- model ---
        self.voice_model = tk.StringVar(value=DEFAULT_VOICE)

        # --- caching ---
        self.cache_dir = os.path.join(tempfile.gettempdir(), "piper_tts_cache")
        os.makedirs(self.cache_dir, exist_ok=True)

        # --- UI state ---
        self.temp_dir = tempfile.gettempdir()
        self.normalize_var = tk.BooleanVar(value=True)
        self.add_breaths_var = tk.BooleanVar(value=False)  # placeholder

        # Base synthesis settings
        self.base_syn_config = SynthesisConfig(
            volume=1.0,
            length_scale=1.0,
            noise_scale=0.667,
            noise_w_scale=0.8,
            normalize_audio=True,
        )

        self.emotion_presets = {
            "Neutral": dict(length_scale=1.0, noise_scale=0.667, noise_w_scale=0.8),
            "Friendly": dict(length_scale=0.95, noise_scale=0.8, noise_w_scale=0.9),
            "Calm": dict(length_scale=1.1, noise_scale=0.55, noise_w_scale=0.7),
            "Energetic": dict(length_scale=0.88, noise_scale=0.9, noise_w_scale=1.0),
            "Whispery": dict(length_scale=1.05, noise_scale=1.1, noise_w_scale=1.2),
        }

        self.setup_ui()
        self.load_voice()

        # warm-up: synth + quick play to prime audio
        try:
            tmp = os.path.join(self.temp_dir, "_piper_warmup.wav")
            synth_to_wav_cli("hello", self.voice_model.get(), tmp)
            pygame.mixer.music.load(tmp)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
            os.remove(tmp)
        except Exception:
            pass

    # ---------------- UI ----------------
    def setup_ui(self):
        container = ttk.Frame(self.root, padding=6)
        container.pack(fill=tk.BOTH, expand=True)

        # Toolbar
        toolbar = ttk.Frame(container, style="Toolbar.TFrame")
        toolbar.pack(fill=tk.X, side=tk.TOP)
        gen_btn = ttk.Button(toolbar, text="Generate & Play", style="Primary.TButton", command=self.generate_and_play)
        gen_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.stop_btn = ttk.Button(toolbar, text="Stop", command=self.stop_playback, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="Save WAV…", command=self.save_to_file).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="Export Jaw Envelope", command=self.export_envelope_current).pack(side=tk.LEFT)
        hints = ttk.Label(toolbar, text="Tips: Press Enter to Generate, Esc to Stop", style="Status.TLabel")
        hints.pack(side=tk.RIGHT)
        self.root.bind("<Return>", lambda e: self.generate_and_play())
        self.root.bind("<Escape>", lambda e: self.stop_playback())

        nb = ttk.Notebook(container); nb.pack(fill=tk.BOTH, expand=True, pady=(4, 4))
        synth_tab = ttk.Frame(nb); nb.add(synth_tab, text="Synthesize")

        # Model frame
        model_f = ttk.LabelFrame(synth_tab, text="Voice Model", style="Group.TLabelframe")
        model_f.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 4))
        model_f.columnconfigure(1, weight=1)
        ttk.Label(model_f, text="Model path:").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(model_f, textvariable=self.voice_model)
        entry.grid(row=0, column=1, sticky="ew", padx=6)
        b1 = ttk.Button(model_f, text="Browse", command=self.browse_model)
        b1.grid(row=0, column=2, padx=(0, 6))
        b2 = ttk.Button(model_f, text="Validate", command=self.load_voice)
        b2.grid(row=0, column=3)
        Tooltip(entry, "Path to your Piper .onnx voice model file.")
        Tooltip(b2, "Check that both binary and model exist.")

        # Text input
        ttk.Label(synth_tab, text="Enter text to speak:", style="Header.TLabel").grid(row=1, column=0, sticky="w", padx=6)
        self.text_input = scrolledtext.ScrolledText(synth_tab, wrap=tk.WORD, width=72, height=10)
        self.text_input.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=6)
        synth_tab.rowconfigure(2, weight=1)
        synth_tab.columnconfigure(0, weight=1)
        synth_tab.columnconfigure(1, weight=1)

        # Quick tests
        quick = ttk.Frame(synth_tab)
        quick.grid(row=3, column=0, columnspan=2, sticky="ew", padx=6, pady=(4, 0))
        ttk.Label(quick, text="Quick tests:").pack(side=tk.LEFT)
        ttk.Button(quick, text="Friendly intro", command=lambda: self._set_text("Hi! I'm Lingo. How can I help you today?")).pack(side=tk.LEFT, padx=4)
        ttk.Button(quick, text="Calm explanation", command=lambda: self._set_text("Let me explain that step by step. First, we set up the sensor. Then, we calibrate it.")).pack(side=tk.LEFT, padx=4)

        # Settings (UI only, for continuity)
        s = ttk.LabelFrame(synth_tab, text="Voice Settings", style="Group.TLabelframe")
        s.grid(row=4, column=0, columnspan=2, sticky="ew", padx=6, pady=6)
        for c in range(6): s.columnconfigure(c, weight=1)
        ttk.Label(s, text="Volume").grid(row=0, column=0, sticky=tk.W, padx=2, pady=2)
        self.vol = tk.DoubleVar(value=1.0)
        vol_scale = ttk.Scale(s, from_=0.1, to=2.0, variable=self.vol, orient=tk.HORIZONTAL)
        vol_scale.grid(row=0, column=1, columnspan=4, sticky=tk.EW, padx=6)
        self._add_val_label(s, self.vol, 0, 5)
        Tooltip(vol_scale, "Output loudness. 1.0 = default.")
        ttk.Label(s, text="Base Speed (length_scale)").grid(row=1, column=0, sticky=tk.W, padx=2, pady=2)
        self.speed = tk.DoubleVar(value=1.0)
        sp_scale = ttk.Scale(s, from_=0.6, to=1.6, variable=self.speed, orient=tk.HORIZONTAL)
        sp_scale.grid(row=1, column=1, columnspan=4, sticky=tk.EW, padx=6)
        self._add_val_label(s, self.speed, 1, 5)
        Tooltip(sp_scale, "Speaking rate. Cosmetic in CLI mode.")
        ttk.Label(s, text="Voice Variation (noise_scale)").grid(row=2, column=0, sticky=tk.W, padx=2, pady=2)
        self.noise = tk.DoubleVar(value=0.667)
        ns_scale = ttk.Scale(s, from_=0.0, to=1.5, variable=self.noise, orient=tk.HORIZONTAL)
        ns_scale.grid(row=2, column=1, columnspan=4, sticky=tk.EW, padx=6)
        self._add_val_label(s, self.noise, 2, 5)
        Tooltip(ns_scale, "Cosmetic in CLI mode.")
        ttk.Label(s, text="Speaking Style (noise_w_scale)").grid(row=3, column=0, sticky=tk.W, padx=2, pady=2)
        self.noise_w = tk.DoubleVar(value=0.8)
        nsw_scale = ttk.Scale(s, from_=0.0, to=2.0, variable=self.noise_w, orient=tk.HORIZONTAL)
        nsw_scale.grid(row=3, column=1, columnspan=4, sticky=tk.EW, padx=6)
        self._add_val_label(s, self.noise_w, 3, 5)
        Tooltip(nsw_scale, "Cosmetic in CLI mode.")
        ttk.Label(s, text="Pause multiplier").grid(row=4, column=3, sticky=tk.E, padx=2)
        self.pause_mult = tk.DoubleVar(value=1.0)
        pm_scale = ttk.Scale(s, from_=0.5, to=2.0, variable=self.pause_mult, orient=tk.HORIZONTAL)
        pm_scale.grid(row=4, column=4, sticky=tk.EW, padx=6)
        self._add_val_label(s, self.pause_mult, 4, 5)
        Tooltip(pm_scale, "Scales the silence between sentences.")
        ttk.Button(s, text="Reset to defaults", command=self._reset_sliders).grid(row=5, column=0, columnspan=6, sticky="e", pady=(6, 2))

        # Status bar
        status = ttk.Frame(container); status.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(status, textvariable=self.status_var, style="Status.TLabel").pack(side=tk.LEFT, padx=6, pady=4)

        # FAQ tab
        faq_tab = ttk.Frame(nb); nb.add(faq_tab, text="FAQ & Tips")
        faq_text = tk.Text(faq_tab, wrap=tk.WORD, height=20)
        faq_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        faq_content = (
            "FAQ & Tips\n"
            "-----------\n\n"
            "• Sliders are cosmetic in CLI mode (piper binary doesn’t expose those params).\n"
            "• Use short sentences and punctuation for clearer speech.\n"
            "• Jaw sync: Use Export Jaw Envelope (.json).\n"
        )
        faq_text.insert("1.0", faq_content); faq_text.configure(state="disabled")

    def _add_val_label(self, parent, var, r, c):
        lbl = ttk.Label(parent, text=f"{var.get():.2f}")
        lbl.grid(row=r, column=c, sticky=tk.E, padx=(6,0))
        def update(*_): lbl.config(text=f"{var.get():.2f}")
        if isinstance(var, tk.Variable): var.trace_add("write", update)

    def _reset_sliders(self):
        self.vol.set(1.0); self.speed.set(1.0); self.noise.set(0.667); self.noise_w.set(0.8); self.pause_mult.set(1.0)

    def _set_text(self, s):
        self.text_input.delete("1.0", tk.END); self.text_input.insert(tk.END, s)

    # ---------------- model handling (CLI validate only) ----------------
    def browse_model(self):
        p = filedialog.askopenfilename(title="Select Piper Voice Model", filetypes=[("ONNX models", "*.onnx")])
        if p:
            self.voice_model.set(p); self.load_voice()

    def load_voice(self):
        try:
            path = self.voice_model.get().strip() or DEFAULT_VOICE
            if not os.path.isfile(path):
                raise FileNotFoundError(f"Model not found: {path}")
            if not os.path.isfile(PIPER_BIN):
                raise FileNotFoundError(f"Piper binary not found: {PIPER_BIN}")
            self.status_var.set(f"Voice ready (CLI): {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Load error", str(e)); self.status_var.set("Error loading voice")

    # ---------------- synthesis utils ----------------
    def _cfg_from_ui(self):
        preset = {}
        cfg = SynthesisConfig(
            volume=float(getattr(self, 'vol', tk.DoubleVar(value=1.0)).get()),
            length_scale=float(preset.get("length_scale", getattr(self, 'speed', tk.DoubleVar(value=1.0)).get())),
            noise_scale=float(preset.get("noise_scale", getattr(self, 'noise', tk.DoubleVar(value=0.667)).get())),
            noise_w_scale=float(preset.get("noise_w_scale", getattr(self, 'noise_w', tk.DoubleVar(value=0.8)).get())),
            normalize_audio=bool(getattr(self, 'normalize_var', tk.BooleanVar(value=True)).get()),
        )
        return cfg

    def _hash(self, text, cfg):
        key = json.dumps({
            "text": text,
            "model": self.voice_model.get(),
            "vol": cfg.volume,
            "len": cfg.length_scale,
            "noise": cfg.noise_scale,
            "noisew": cfg.noise_w_scale,
            "norm": cfg.normalize_audio,
        }, sort_keys=True)
        return hashlib.md5(key.encode()).hexdigest()

    def _split_sentences(self, text):
        parts = re.split(r"(\s*[.!?…]+\s*)", text.strip())
        if not parts: return []
        out = []
        for i in range(0, len(parts), 2):
            seg = parts[i]
            if i+1 < len(parts): seg += parts[i+1]
            seg = seg.strip()
            if seg: out.append(seg)
        return out

    def _pause_ms_for_sentence(self, s):
        base = 250
        if s.endswith("?"): base = 400
        elif s.endswith("!"): base = 350
        elif s.endswith("…") or s.endswith("..."): base = 500
        elif s.endswith(","): base = 150
        return int(base * float(self.pause_mult.get()))

    # ------------- main actions -------------
    def generate_and_play(self):
        text = self.text_input.get("1.0", tk.END).strip()
        if not text:
            self.status_var.set("Please enter some text"); return
        self.stop_playback(); self.status_var.set("Generating…")
        Thread(target=self._generate_and_play_thread, args=(text,), daemon=True).start()

    def _generate_and_play_thread(self, text):
        try:
            cfg_base = self._cfg_from_ui()
            sentences = self._split_sentences(text)
            if not sentences:
                self._ui_ready("Nothing to speak"); return
            wav_paths = []
            for s in sentences:
                # Cosmetic jitter for cache key continuity
                jitter = random.uniform(-0.05, 0.05)
                cfg = SynthesisConfig(
                    volume=cfg_base.volume,
                    length_scale=max(0.5, cfg_base.length_scale * (1.0 + jitter)),
                    noise_scale=cfg_base.noise_scale,
                    noise_w_scale=cfg_base.noise_w_scale,
                    normalize_audio=cfg_base.normalize_audio,
                )
                h = self._hash(s, cfg)
                wav_path = os.path.join(self.cache_dir, f"{h}.wav")
                if not os.path.exists(wav_path):
                    synth_to_wav_cli(s, self.voice_model.get(), wav_path)
                wav_paths.append((wav_path, self._pause_ms_for_sentence(s)))
            self._play_sequence(wav_paths); self._ui_ready("Ready")
        except Exception as e:
            self._ui_ready(f"Error: {e}")

    def _play_sequence(self, items):
        self.root.after(0, lambda: self.stop_btn.config(state=tk.NORMAL))
        for wav_path, pause_ms in items:
            if not os.path.exists(wav_path):
                continue
            try:
                pygame.mixer.music.load(wav_path)
                pygame.mixer.music.set_volume(float(self.vol.get()))
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.05)
                time.sleep(pause_ms / 1000.0)
            except Exception as e:
                print("playback error:", e)
        self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))

    def _ui_ready(self, msg="Ready"):
        def _():
            self.status_var.set(msg); self.stop_btn.config(state=tk.DISABLED)
        self.root.after(0, _)

    def stop_playback(self):
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
        self.status_var.set("Playback stopped"); self.stop_btn.config(state=tk.DISABLED)

    # ------------- save/export -------------
    def save_to_file(self):
        text = self.text_input.get("1.0", tk.END).strip()
        if not text:
            self.status_var.set("Please enter some text"); return
        p = filedialog.asksaveasfilename(defaultextension=".wav", filetypes=[("WAV", ".wav")])
        if not p: return
        try:
            cfg = self._cfg_from_ui()
            h = self._hash(text, cfg)
            wav_path = os.path.join(self.cache_dir, f"{h}.wav")
            if not os.path.exists(wav_path):
                synth_to_wav_cli(text, self.voice_model.get(), wav_path)
            with open(wav_path, "rb") as src, open(p, "wb") as dst:
                dst.write(src.read())
            self.status_var.set(f"Saved: {p}")
        except Exception as e:
            self.status_var.set(f"Error saving: {e}")

    def export_envelope_current(self):
        text = self.text_input.get("1.0", tk.END).strip()
        if not text:
            self.status_var.set("Please enter some text"); return
        cfg = self._cfg_from_ui()
        h = self._hash(text, cfg)
        wav_path = os.path.join(self.cache_dir, f"{h}.wav")
        try:
            if not os.path.exists(wav_path):
                synth_to_wav_cli(text, self.voice_model.get(), wav_path)
        except Exception as e:
            self.status_var.set(f"Synthesis error: {e}"); return
        out = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", ".json")], title="Save jaw envelope JSON")
        if not out: return
        try:
            env = self._rms_envelope(wav_path, frame_ms=10)
            with open(out, "w") as f:
                json.dump({"frame_ms": 10, "values": env}, f)
            self.status_var.set(f"Envelope saved: {out}")
        except Exception as e:
            self.status_var.set(f"Envelope error: {e}")

    def _rms_envelope(self, wav_path, frame_ms=10):
        with wave.open(wav_path, "rb") as wf:
            n_channels = wf.getnchannels(); sampwidth = wf.getsampwidth(); fr = wf.getframerate(); n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)
        dtype = np.int16 if sampwidth == 2 else np.int8
        data = np.frombuffer(raw, dtype=dtype)
        if n_channels > 1:
            data = data.reshape(-1, n_channels).mean(axis=1)
        data = data.astype(np.float32) / (np.iinfo(dtype).max if dtype == np.int16 else 127.0)
        hop = int(fr * (frame_ms/1000.0)); hop = max(1, hop)
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
    root = tk.Tk(); app = PiperTTSPlayer(root); root.mainloop()
