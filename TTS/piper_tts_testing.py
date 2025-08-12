import wave
import tkinter as tk
from tkinter import ttk, scrolledtext
from piper import PiperVoice
import pygame
from threading import Thread
import os

class PiperTTSPlayer:
    def __init__(self, root):
        self.root = root
        self.root.title("Piper TTS Player")
        
        # Initialize pygame for audio playback
        pygame.mixer.init()
        
        # Load Piper voice (change path to your model)
        self.voice = PiperVoice.load("/home/robinglory/Desktop/Thesis/TTS/piper/models/en_US-hfc_female-medium.onnx")
        self.temp_wav = "temp_output.wav"
        
        self.setup_ui()
    
    def setup_ui(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Text input
        ttk.Label(main_frame, text="Enter Text:").pack(anchor=tk.W)
        self.text_input = scrolledtext.ScrolledText(main_frame, wrap=tk.WORD, width=60, height=10)
        self.text_input.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(5, 0))
        
        # Generate and Play button
        self.play_button = ttk.Button(button_frame, text="Generate & Play", command=self.generate_and_play)
        self.play_button.pack(side=tk.LEFT, padx=(0, 5))
        
        # Stop button
        self.stop_button = ttk.Button(button_frame, text="Stop", command=self.stop_playback, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT)
        
        # Status label
        self.status_var = tk.StringVar()
        self.status_var.set("Ready")
        ttk.Label(main_frame, textvariable=self.status_var).pack(anchor=tk.W)
    
    def generate_and_play(self):
        text = self.text_input.get("1.0", tk.END).strip()
        if not text:
            self.status_var.set("Please enter some text")
            return
        
        self.play_button.config(state=tk.DISABLED)
        self.status_var.set("Generating speech...")
        
        # Run generation in a separate thread to keep UI responsive
        Thread(target=self._generate_and_play_thread, args=(text,), daemon=True).start()
    
    def _generate_and_play_thread(self, text):
        try:
            # Generate WAV file
            with wave.open(self.temp_wav, "wb") as wav_file:
                self.voice.synthesize_wav(text, wav_file)
            
            # Play the audio
            self.root.after(0, self._play_audio)
        except Exception as e:
            self.root.after(0, lambda: self.status_var.set(f"Error: {str(e)}"))
            self.root.after(0, lambda: self.play_button.config(state=tk.NORMAL))
    
    def _play_audio(self):
        try:
            self.status_var.set("Playing...")
            self.stop_button.config(state=tk.NORMAL)
            
            # Load and play the audio
            pygame.mixer.music.load(self.temp_wav)
            pygame.mixer.music.play()
            
            # Check playback status periodically
            self._check_playback()
        except Exception as e:
            self.status_var.set(f"Playback error: {str(e)}")
            self.play_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
    
    def _check_playback(self):
        if pygame.mixer.music.get_busy():
            # Still playing, check again in 100ms
            self.root.after(100, self._check_playback)
        else:
            # Playback finished
            self.status_var.set("Ready")
            self.play_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            try:
                os.remove(self.temp_wav)
            except:
                pass
    
    def stop_playback(self):
        pygame.mixer.music.stop()
        self.status_var.set("Playback stopped")
        self.play_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        try:
            os.remove(self.temp_wav)
        except:
            pass

if __name__ == "__main__":
    root = tk.Tk()
    app = PiperTTSPlayer(root)
    root.mainloop()
