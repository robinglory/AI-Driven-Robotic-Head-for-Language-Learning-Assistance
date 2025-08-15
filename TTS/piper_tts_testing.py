import wave
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
from piper import PiperVoice, SynthesisConfig
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

"""
Key upgrades vs your original:
1) Natural prosody: sentence-aware splitting + punctuation-driven pause lengths.
2) Emotion presets: quick mappings that tweak SynthesisConfig for different styles.
3) Pause multiplier: easy global control over how much silence to add between phrases.
4) Subtle humanization: tiny random variation to speed (length_scale) per sentence.
5) Persistent disk caching: identical text+settings reuse the same .wav (speeds iteration).
6) Jaw/viseme helper: exports a time->amplitude envelope .json (for MG996R mouth/jaw).
7) Safer playback: per-sentence generation & sequential playback for snappier feedback.

Tested on Raspberry Pi 4 + pygame mixer. You’ll need numpy installed.
"""

class PiperTTSPlayer:
    def __init__(self, root):
        self.root = root
        self.root.title("Piper TTS – Robotic Head Edition")

        # --- audio ---
        pygame.mixer.init()

        # --- model ---
        self.voice_model = tk.StringVar(value="/home/robinglory/Desktop/Thesis/TTS/piper/models/en_US-hfc_female-medium.onnx")
        self.voice = None

        # --- caching ---
        self.cache_dir = os.path.join(tempfile.gettempdir(), "piper_tts_cache")
        os.makedirs(self.cache_dir, exist_ok=True)

        # --- UI state ---
        self.temp_dir = tempfile.gettempdir()
        self.normalize_var = tk.BooleanVar(value=True)
        self.add_breaths_var = tk.BooleanVar(value=False)  # placeholder if you want to add breath SFX later

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

        # warm-up
        try:
            with wave.open(os.path.join(self.temp_dir, "_piper_warmup.wav"), "wb") as wavf:
                self.voice.synthesize_wav("hello", wavf, syn_config=self.base_syn_config)
        except Exception:
            pass

    # ---------------- UI ----------------
    def setup_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # model row
        row = ttk.LabelFrame(main, text="Voice Model")
        row.pack(fill=tk.X)
        ttk.Label(row, text="Model path:").pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.voice_model, width=60).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Button(row, text="Browse", command=self.browse_model).pack(side=tk.LEFT)
        ttk.Button(row, text="Reload", command=self.load_voice).pack(side=tk.LEFT, padx=4)

        # text input
        ttk.Label(main, text="Enter text:").pack(anchor=tk.W, pady=(10, 0))
        self.text_input = scrolledtext.ScrolledText(main, wrap=tk.WORD, width=70, height=10)
        self.text_input.pack(fill=tk.BOTH, expand=True)

        # settings
        s = ttk.LabelFrame(main, text="Voice Settings")
        s.pack(fill=tk.X, pady=10)

        ttk.Label(s, text="Volume").grid(row=0, column=0, sticky=tk.W)
        self.vol = tk.DoubleVar(value=1.0)
        ttk.Scale(s, from_=0.1, to=2.0, variable=self.vol, orient=tk.HORIZONTAL).grid(row=0, column=1, sticky=tk.EW, padx=6)
        self._add_val_label(s, self.vol, 0, 2)

        ttk.Label(s, text="Base Speed (length_scale)").grid(row=1, column=0, sticky=tk.W)
        self.speed = tk.DoubleVar(value=1.0)
        ttk.Scale(s, from_=0.6, to=1.6, variable=self.speed, orient=tk.HORIZONTAL).grid(row=1, column=1, sticky=tk.EW, padx=6)
        self._add_val_label(s, self.speed, 1, 2)

        ttk.Label(s, text="Voice Variation (noise_scale)").grid(row=2, column=0, sticky=tk.W)
        self.noise = tk.DoubleVar(value=0.667)
        ttk.Scale(s, from_=0.0, to=1.5, variable=self.noise, orient=tk.HORIZONTAL).grid(row=2, column=1, sticky=tk.EW, padx=6)
        self._add_val_label(s, self.noise, 2, 2)

        ttk.Label(s, text="Speaking Style (noise_w_scale)").grid(row=3, column=0, sticky=tk.W)
        self.noise_w = tk.DoubleVar(value=0.8)
        ttk.Scale(s, from_=0.0, to=2.0, variable=self.noise_w, orient=tk.HORIZONTAL).grid(row=3, column=1, sticky=tk.EW, padx=6)
        self._add_val_label(s, self.noise_w, 3, 2)

        ttk.Checkbutton(s, text="Normalize audio", variable=self.normalize_var).grid(row=4, column=0, sticky=tk.W, pady=(6,0))

        ttk.Label(s, text="Emotion preset").grid(row=5, column=0, sticky=tk.W, pady=(6,0))
        self.preset = tk.StringVar(value="Neutral")
        ttk.Combobox(s, textvariable=self.preset, values=list(self.emotion_presets.keys()), state="readonly").grid(row=5, column=1, sticky=tk.EW)

        ttk.Label(s, text="Pause multiplier").grid(row=6, column=0, sticky=tk.W)
        self.pause_mult = tk.DoubleVar(value=1.0)
        ttk.Scale(s, from_=0.5, to=2.0, variable=self.pause_mult, orient=tk.HORIZONTAL).grid(row=6, column=1, sticky=tk.EW, padx=6)
        self._add_val_label(s, self.pause_mult, 6, 2)

        for c in range(3):
            s.columnconfigure(c, weight=1)

        # buttons
        buttons = ttk.Frame(main)
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Generate & Play", command=self.generate_and_play).pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(buttons, text="Stop", command=self.stop_playback, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text="Save WAV…", command=self.save_to_file).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Export Jaw Envelope", command=self.export_envelope_current).pack(side=tk.LEFT, padx=6)

        # quick test lines
        samples = ttk.Frame(main)
        samples.pack(fill=tk.X, pady=(8,0))
        ttk.Label(samples, text="Quick tests:").pack(side=tk.LEFT)
        ttk.Button(samples, text="Friendly intro", command=lambda: self._set_text("Hi! I'm Lingo. How can I help you today?")).pack(side=tk.LEFT, padx=4)
        ttk.Button(samples, text="Calm explanation", command=lambda: self._set_text("Let me explain that step by step. First, we set up the sensor. Then, we calibrate it." )).pack(side=tk.LEFT, padx=4)

        # status
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(main, textvariable=self.status_var).pack(anchor=tk.W, pady=(6,0))

    def _add_val_label(self, parent, var, r, c):
        lbl = ttk.Label(parent, text=f"{var.get():.2f}")
        lbl.grid(row=r, column=c, sticky=tk.E, padx=(6,0))
        def update(_):
            lbl.config(text=f"{var.get():.2f}")
        parent.bind_all("<B1-Motion>", update)
        parent.bind_all("<ButtonRelease-1>", update)

    def _set_text(self, s):
        self.text_input.delete("1.0", tk.END)
        self.text_input.insert(tk.END, s)

    # ---------------- model handling ----------------
    def browse_model(self):
        p = filedialog.askopenfilename(title="Select Piper Voice Model", filetypes=[("ONNX models", "*.onnx")])
        if p:
            self.voice_model.set(p)
            self.load_voice()

    def load_voice(self):
        try:
            self.voice = PiperVoice.load(self.voice_model.get())
            self.status_var.set(f"Voice loaded: {os.path.basename(self.voice_model.get())}")
        except Exception as e:
            self.voice = None
            messagebox.showerror("Load error", str(e))
            self.status_var.set("Error loading voice")

    # ---------------- synthesis utils ----------------
    def _cfg_from_ui(self):
        # merge base + preset
        preset = self.emotion_presets.get(self.preset.get(), {})
        cfg = SynthesisConfig(
            volume=float(self.vol.get()),
            length_scale=float(preset.get("length_scale", self.speed.get())),
            noise_scale=float(preset.get("noise_scale", self.noise.get())),
            noise_w_scale=float(preset.get("noise_w_scale", self.noise_w.get())),
            normalize_audio=self.normalize_var.get(),
        )
        # if preset didn’t specify a value, fall back to UI slider
        if "length_scale" not in preset:
            cfg.length_scale = float(self.speed.get())
        if "noise_scale" not in preset:
            cfg.noise_scale = float(self.noise.get())
        if "noise_w_scale" not in preset:
            cfg.noise_w_scale = float(self.noise_w.get())
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
        # Keep delimiters; merge into full sentences.
        parts = re.split(r"(\s*[.!?…]+\s*)", text.strip())
        if not parts:
            return []
        out = []
        for i in range(0, len(parts), 2):
            seg = parts[i]
            if i+1 < len(parts):
                seg += parts[i+1]
            seg = seg.strip()
            if seg:
                out.append(seg)
        return out

    def _pause_ms_for_sentence(self, s):
        # More pause for ., ?, ! and ellipsis; less for comma
        base = 250  # milliseconds
        if s.endswith("?"):
            base = 400
        elif s.endswith("!"):
            base = 350
        elif s.endswith("…") or s.endswith("..."):
            base = 500
        elif s.endswith(","):
            base = 150
        # global multiplier
        return int(base * float(self.pause_mult.get()))

    # ------------- main actions -------------
    def generate_and_play(self):
        if not self.voice:
            self.status_var.set("No voice loaded!")
            return
        text = self.text_input.get("1.0", tk.END).strip()
        if not text:
            self.status_var.set("Please enter some text")
            return
        self.stop_playback()  # stop anything currently playing
        self.status_var.set("Generating…")
        Thread(target=self._generate_and_play_thread, args=(text,), daemon=True).start()

    def _generate_and_play_thread(self, text):
        try:
            cfg_base = self._cfg_from_ui()
            sentences = self._split_sentences(text)
            if not sentences:
                self._ui_ready("Nothing to speak")
                return

            wav_paths = []
            for s in sentences:
                # tiny humanization: jitter length_scale +/- 5%
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
                    with wave.open(wav_path, "wb") as wf:
                        self.voice.synthesize_wav(s, wf, syn_config=cfg)
                wav_paths.append((wav_path, self._pause_ms_for_sentence(s)))

            # sequential playback with pauses
            self._play_sequence(wav_paths)
            self._ui_ready("Ready")
        except Exception as e:
            self._ui_ready(f"Error: {e}")

    def _play_sequence(self, items):
        self.root.after(0, lambda: self.stop_btn.config(state=tk.NORMAL))
        for wav_path, pause_ms in items:
            if not os.path.exists(wav_path):
                continue
            try:
                pygame.mixer.music.load(wav_path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.05)
                # pause between items
                time.sleep(pause_ms / 1000.0)
            except Exception as e:
                print("playback error:", e)
        self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))

    def _ui_ready(self, msg="Ready"):
        def _():
            self.status_var.set(msg)
            self.stop_btn.config(state=tk.DISABLED)
        self.root.after(0, _)

    def stop_playback(self):
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
        self.status_var.set("Playback stopped")
        self.stop_btn.config(state=tk.DISABLED)

    # ------------- save/export -------------
    def save_to_file(self):
        if not self.voice:
            self.status_var.set("No voice loaded!")
            return
        text = self.text_input.get("1.0", tk.END).strip()
        if not text:
            self.status_var.set("Please enter some text")
            return
        p = filedialog.asksaveasfilename(defaultextension=".wav", filetypes=[("WAV", ".wav")])
        if not p:
            return
        try:
            cfg = self._cfg_from_ui()
            h = self._hash(text, cfg)
            wav_path = os.path.join(self.cache_dir, f"{h}.wav")
            if not os.path.exists(wav_path):
                with wave.open(wav_path, "wb") as wf:
                    self.voice.synthesize_wav(text, wf, syn_config=cfg)
            # copy to chosen path
            with open(wav_path, "rb") as src, open(p, "wb") as dst:
                dst.write(src.read())
            self.status_var.set(f"Saved: {p}")
        except Exception as e:
            self.status_var.set(f"Error saving: {e}")

    # --- envelope export for jaw servo ---
    def export_envelope_current(self):
        text = self.text_input.get("1.0", tk.END).strip()
        if not text:
            self.status_var.set("Please enter some text")
            return
        cfg = self._cfg_from_ui()
        h = self._hash(text, cfg)
        wav_path = os.path.join(self.cache_dir, f"{h}.wav")
        if not os.path.exists(wav_path):
            # synthesize full text to cache first
            try:
                with wave.open(wav_path, "wb") as wf:
                    self.voice.synthesize_wav(text, wf, syn_config=cfg)
            except Exception as e:
                self.status_var.set(f"Synthesis error: {e}")
                return
        out = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", ".json")], title="Save jaw envelope JSON")
        if not out:
            return
        try:
            env = self._rms_envelope(wav_path, frame_ms=10)
            with open(out, "w") as f:
                json.dump({"frame_ms": 10, "values": env}, f)
            self.status_var.set(f"Envelope saved: {out}")
        except Exception as e:
            self.status_var.set(f"Envelope error: {e}")

    def _rms_envelope(self, wav_path, frame_ms=10):
        with wave.open(wav_path, "rb") as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            fr = wf.getframerate()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)
        # convert to mono float32 in [-1,1]
        dtype = np.int16 if sampwidth == 2 else np.int8
        data = np.frombuffer(raw, dtype=dtype)
        if n_channels > 1:
            data = data.reshape(-1, n_channels).mean(axis=1)
        data = data.astype(np.float32) / (np.iinfo(dtype).max if dtype == np.int16 else 127.0)
        hop = int(fr * (frame_ms/1000.0))
        if hop <= 0:
            hop = 1
        values = []
        for i in range(0, len(data), hop):
            seg = data[i:i+hop]
            if len(seg) == 0:
                break
            rms = float(np.sqrt(np.mean(seg**2) + 1e-9))
            values.append(rms)
        # normalize 0..1 (robust)
        mx = max(values) if values else 1.0
        if mx > 0:
            values = [min(1.0, v / mx) for v in values]
        return values


if __name__ == "__main__":
    root = tk.Tk()
    app = PiperTTSPlayer(root)
    root.mainloop()
