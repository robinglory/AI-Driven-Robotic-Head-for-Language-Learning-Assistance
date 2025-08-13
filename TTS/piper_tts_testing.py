import wave
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog
from piper import PiperVoice, SynthesisConfig
import pygame
from threading import Thread
import os
import tempfile
import hashlib

class PiperTTSPlayer:
    def __init__(self, root):
        self.root = root
        self.root.title("Advanced Piper TTS Player (Optimized for Pi 4)")
        
        # Initialize pygame for audio playback
        pygame.mixer.init()
        
        # Default to faster low model
        self.voice_model = tk.StringVar(value="/home/robinglory/Desktop/Thesis/TTS/piper/models/en_US-hfc_female-medium.onnx")
        self.voice = None
        
        # Cache dictionary for repeated texts
        self.audio_cache = {}

        # Temporary file for audio
        self.temp_wav = os.path.join(tempfile.gettempdir(), "piper_temp.wav")
        
        # Default synthesis settings - faster speech
        self.syn_config = SynthesisConfig(
            volume=1.0,
            length_scale=0.8,  # faster speaking speed
            noise_scale=1.0,
            noise_w_scale=1.0,
            normalize_audio=True
        )
        
        self.setup_ui()
        self.load_voice()

        # Warm-up the model to remove first-call lag
        self.voice.synthesize_wav("Hello", wave.open(os.devnull, "wb"), syn_config=self.syn_config)

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        model_frame = ttk.LabelFrame(main_frame, text="Voice Model", padding="5")
        model_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(model_frame, text="Model Path:").pack(side=tk.LEFT)
        model_entry = ttk.Entry(model_frame, textvariable=self.voice_model, width=50)
        model_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        ttk.Button(model_frame, text="Browse", command=self.browse_model).pack(side=tk.LEFT)
        ttk.Button(model_frame, text="Reload Voice", command=self.load_voice).pack(side=tk.LEFT, padx=(5, 0))
        
        ttk.Label(main_frame, text="Enter Text:").pack(anchor=tk.W)
        self.text_input = scrolledtext.ScrolledText(main_frame, wrap=tk.WORD, width=60, height=10)
        self.text_input.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        settings_frame = ttk.LabelFrame(main_frame, text="Voice Settings", padding="10")
        settings_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(settings_frame, text="Volume:").grid(row=0, column=0, sticky=tk.W)
        self.volume_slider = ttk.Scale(settings_frame, from_=0.1, to=2.0, value=1.0)
        self.volume_slider.grid(row=0, column=1, sticky=tk.EW, padx=5)
        self.volume_value = ttk.Label(settings_frame, text="1.0")
        self.volume_value.grid(row=0, column=2, padx=(0, 10))
        self.volume_slider.bind("<Motion>", lambda e: self.volume_value.config(text=f"{self.volume_slider.get():.1f}"))
        
        ttk.Label(settings_frame, text="Speed:").grid(row=1, column=0, sticky=tk.W)
        self.speed_slider = ttk.Scale(settings_frame, from_=0.5, to=3.0, value=0.8)  # default faster
        self.speed_slider.grid(row=1, column=1, sticky=tk.EW, padx=5)
        self.speed_value = ttk.Label(settings_frame, text="0.8")
        self.speed_value.grid(row=1, column=2, padx=(0, 10))
        self.speed_slider.bind("<Motion>", lambda e: self.speed_value.config(text=f"{self.speed_slider.get():.1f}"))
        
        ttk.Label(settings_frame, text="Voice Variation:").grid(row=2, column=0, sticky=tk.W)
        self.noise_slider = ttk.Scale(settings_frame, from_=0.0, to=2.0, value=0.667)
        self.noise_slider.grid(row=2, column=1, sticky=tk.EW, padx=5)
        self.noise_value = ttk.Label(settings_frame, text="0.667")
        self.noise_value.grid(row=2, column=2, padx=(0, 10))
        self.noise_slider.bind("<Motion>", lambda e: self.noise_value.config(text=f"{self.noise_slider.get():.3f}"))
        
        ttk.Label(settings_frame, text="Speaking Style:").grid(row=3, column=0, sticky=tk.W)
        self.noise_w_scale_slider = ttk.Scale(settings_frame, from_=0.0, to=2.0, value=0.8)
        self.noise_w_scale_slider.grid(row=3, column=1, sticky=tk.EW, padx=5)
        self.noise_w_scale_value = ttk.Label(settings_frame, text="0.8")
        self.noise_w_scale_value.grid(row=3, column=2, padx=(0, 10))
        self.noise_w_scale_slider.bind("<Motion>", lambda e: self.noise_w_scale_value.config(text=f"{self.noise_w_scale_slider.get():.1f}"))
        
        self.normalize_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(settings_frame, text="Normalize Audio", variable=self.normalize_var).grid(row=4, column=0, columnspan=3, sticky=tk.W)
        
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.play_button = ttk.Button(button_frame, text="Generate & Play", command=self.generate_and_play)
        self.play_button.pack(side=tk.LEFT, padx=(0, 5))
        
        self.stop_button = ttk.Button(button_frame, text="Stop", command=self.stop_playback, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT)
        
        self.save_button = ttk.Button(button_frame, text="Save to File", command=self.save_to_file)
        self.save_button.pack(side=tk.LEFT, padx=5)
        
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(main_frame, textvariable=self.status_var).pack(anchor=tk.W)

    def browse_model(self):
        filepath = filedialog.askopenfilename(
            title="Select Piper Voice Model",
            filetypes=[("ONNX models", "*.onnx")]
        )
        if filepath:
            self.voice_model.set(filepath)
            self.load_voice()

    def load_voice(self):
        try:
            self.voice = PiperVoice.load(self.voice_model.get())
            self.status_var.set(f"Voice loaded: {os.path.basename(self.voice_model.get())}")
        except Exception as e:
            self.status_var.set(f"Error loading voice: {str(e)}")
            self.voice = None

    def get_synthesis_config(self):
        return SynthesisConfig(
            volume=float(self.volume_slider.get()),
            length_scale=float(self.speed_slider.get()),
            noise_scale=float(self.noise_slider.get()),
            noise_w_scale=float(self.noise_w_scale_slider.get()),
            normalize_audio=self.normalize_var.get()
        )

    def generate_and_play(self):
        if not self.voice:
            self.status_var.set("No voice loaded!")
            return
            
        text = self.text_input.get("1.0", tk.END).strip()
        if not text:
            self.status_var.set("Please enter some text")
            return
        
        # Check cache first
        text_hash = hashlib.md5(text.encode()).hexdigest()
        if text_hash in self.audio_cache:
            self.temp_wav = self.audio_cache[text_hash]
            self._play_audio()
            return
        
        self.play_button.config(state=tk.DISABLED)
        self.status_var.set("Generating speech...")
        
        syn_config = self.get_synthesis_config()
        Thread(target=self._generate_and_play_thread, args=(text, syn_config, text_hash), daemon=True).start()

    def _generate_and_play_thread(self, text, syn_config, text_hash):
        try:
            with wave.open(self.temp_wav, "wb") as wav_file:
                self.voice.synthesize_wav(text, wav_file, syn_config=syn_config)
            self.audio_cache[text_hash] = self.temp_wav  # store in cache
            self.root.after(0, self._play_audio)
        except Exception as e:
            self.root.after(0, lambda: self.status_var.set(f"Error: {str(e)}"))
            self.root.after(0, lambda: self.play_button.config(state=tk.NORMAL))

    def _play_audio(self):
        try:
            self.status_var.set("Playing...")
            self.stop_button.config(state=tk.NORMAL)
            pygame.mixer.music.load(self.temp_wav)
            pygame.mixer.music.play()
            self._check_playback()
        except Exception as e:
            self.status_var.set(f"Playback error: {str(e)}")
            self.play_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)

    def _check_playback(self):
        if pygame.mixer.music.get_busy():
            self.root.after(100, self._check_playback)
        else:
            self.status_var.set("Ready")
            self.play_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)

    def stop_playback(self):
        pygame.mixer.music.stop()
        self.status_var.set("Playback stopped")
        self.play_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

    def save_to_file(self):
        if not self.voice:
            self.status_var.set("No voice loaded!")
            return
            
        text = self.text_input.get("1.0", tk.END).strip()
        if not text:
            self.status_var.set("Please enter some text")
            return
        
        filepath = filedialog.asksaveasfilename(
            defaultextension=".wav",
            filetypes=[("WAV files", "*.wav")]
        )
        if not filepath:
            return
        
        self.status_var.set("Saving to file...")
        self.root.update()
        
        try:
            syn_config = self.get_synthesis_config()
            with wave.open(filepath, "wb") as wav_file:
                self.voice.synthesize_wav(text, wav_file, syn_config=syn_config)
            self.status_var.set(f"Saved to: {filepath}")
        except Exception as e:
            self.status_var.set(f"Error saving: {str(e)}")


if __name__ == "__main__":
    root = tk.Tk()
    app = PiperTTSPlayer(root)
    root.mainloop()
