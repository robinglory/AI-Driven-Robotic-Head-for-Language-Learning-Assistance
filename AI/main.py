#!/usr/bin/env python3
"""
Standalone tester that DOES NOT touch your other apps.
File: /home/robinglory/Desktop/Thesis/AI/main.py
- Uses your STT wrapper (whisper.cpp CLI paths from 60sWhisperGui.py)
- Uses your Piper TTS GUI to speak every reply (voice + typed)
- Uses your KeyManager (OpenRouter keys)
- Adds a "🎧 Test Mic" button to sanity‑check input levels
"""
from __future__ import annotations
import os, subprocess, importlib.machinery, importlib.util, wave, audioop
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import requests

# -------- Paths to your existing modules (leave them as-is) --------
STT_PY = "/home/robinglory/Desktop/Thesis/STT/whisper.cpp/60sWhisperGui.py"
TTS_PY = "/home/robinglory/Desktop/Thesis/TTS/TTS_GUI.py"
KEY_MANAGER_PY = "/home/robinglory/Desktop/Thesis/GUI/key_manager.py"

# -------- Load-by-path helpers (so we don’t rename your files) --------
def _load_module_from_path(mod_name: str, file_path: str):
    loader = importlib.machinery.SourceFileLoader(mod_name, file_path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module

_stt = _load_module_from_path("stt_whisper_gui", STT_PY)
_tts = _load_module_from_path("piper_tts_gui", TTS_PY)
_keym = _load_module_from_path("key_manager", KEY_MANAGER_PY)
KeyManager = _keym.KeyManager

# ------------------- Defaults (your hardware & prefs) -------------------
MIC_INDEX = 3          # from arecord -l → card 3: AB13X USB Audio, device 0
CLIP_SECONDS = 10      # speech capture length
THREADS = 4            # whisper-cli -t
BEAM_SIZE = 3          # whisper-cli -bs
USE_BASE_MODEL = True  # base.en vs tiny.en

# ------------------- OpenRouter LLM via your KeyManager -------------------
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
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "http://localhost/",
            "X-Title": "AI Voice Tester",
            "Content-Type": "application/json",
        }
        payload = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()

# ------------------- App -------------------
class VoiceTester(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI Voice Tester — simple")
        self.geometry("900x640")

        # LLM
        self.key_manager = KeyManager()
        self.llm = LLM(self.key_manager)

        # Hidden TTS window (reuse your player)
        self.tts_root = tk.Toplevel(self)
        self.tts_root.withdraw()
        self.tts = _tts.PiperTTSPlayer(self.tts_root)

        self._last_ai_text = ""
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        top = ttk.Frame(self, padding=12)
        top.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(top)
        header.pack(fill=tk.X)
        ttk.Label(header, text="AI Voice Tester", font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)
        ttk.Button(header, text="🔎 Devices", command=self.on_list_devices).pack(side=tk.RIGHT, padx=4)
        ttk.Button(header, text="🎧 Test Mic", command=self.on_test_mic).pack(side=tk.RIGHT, padx=4)
        ttk.Button(header, text="🔈 Speak Reply", command=self.on_speak_reply).pack(side=tk.RIGHT, padx=4)
        ttk.Button(header, text="🎤 Speak", command=self.on_speak).pack(side=tk.RIGHT, padx=4)

        body = ttk.Frame(top)
        body.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self.chat = scrolledtext.ScrolledText(body, wrap=tk.WORD, font=("Segoe UI", 12))
        self.chat.pack(fill=tk.BOTH, expand=True)
        self._say("Lingo", "Voice test ready. Click 🎤 to dictate, or type below and Send. Typed replies will auto‑speak.")

        row = ttk.Frame(top)
        row.pack(fill=tk.X, pady=(8, 0))
        self.entry = ttk.Entry(row, font=("Segoe UI", 12))
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", lambda e: self.on_send())
        ttk.Button(row, text="Send", command=self.on_send).pack(side=tk.LEFT, padx=6)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status_var).pack(side=tk.BOTTOM, anchor="w", padx=12, pady=6)

    # ---------- helpers ----------
    def _say(self, who: str, msg: str):
        self.chat.insert(tk.END, f"{who}: {msg}\n\n"); self.chat.see(tk.END)
    def set_status(self, text: str):
        self.status_var.set(text); self.update_idletasks()

    # ---------- STT/TTS ----------
    def _stt_paths(self):
        model = _stt.MODEL_BASE if USE_BASE_MODEL else _stt.MODEL_TINY
        return _stt.WHISPER_DIR, _stt.CLI_BIN, model, _stt.TEMP_WAV

    def _wav_stats(self, path: str):
        try:
            with wave.open(path, 'rb') as w:
                nchan = w.getnchannels(); width = w.getsampwidth(); rate = w.getframerate(); frames = w.getnframes()
                data = w.readframes(frames)
            if nchan > 1:
                data = audioop.tomono(data, width, 1, 0)
            peak = audioop.max(data, width) if data else 0
            rms = audioop.rms(data, width) if data else 0
            return peak, rms
        except Exception:
            return 0, 0

    def stt_capture_and_transcribe(self) -> str:
        WHISPER_DIR, CLI_BIN, MODEL, TEMP_WAV = self._stt_paths()
        os.makedirs(os.path.dirname(TEMP_WAV), exist_ok=True)

        # 1) Capture
        self.set_status("Recording…")
        arecord_cmd = ["arecord", "-D", f"plughw:{MIC_INDEX},0", "-f", "S16_LE", "-r", "16000", "-c", "1", "-d", str(CLIP_SECONDS), TEMP_WAV]
        try:
            subprocess.run(arecord_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError:
            # fallback to default
            self._say("System", "plughw failed; retrying with -D default…")
            arecord_cmd = ["arecord", "-D", "default", "-f", "S16_LE", "-r", "16000", "-c", "1", "-d", str(CLIP_SECONDS), TEMP_WAV]
            subprocess.run(arecord_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        peak, rms = self._wav_stats(TEMP_WAV)
        self._say("Recorder", f"peak={peak} rms={rms}")
        if peak < 500 and rms < 200:
            self._say("Hint", "Very quiet input. Raise mic gain in alsamixer (F6 → USB mic).")

        # 2) Transcribe (make sure we write .txt)
        self.set_status("Transcribing…")
        out_base = os.path.join(WHISPER_DIR, "last_transcript")
        cli_cmd = [
            CLI_BIN,
            "-m", MODEL,
            "-t", str(THREADS),
            "-bs", str(BEAM_SIZE),
            "-l", "en",
            "-f", TEMP_WAV,
            "-otxt",               # ensure .txt is written
            "-of", out_base,
        ]
        env = os.environ.copy()
        try:
            env.update(_stt.make_env())
        except Exception:
            pass
        subprocess.run(cli_cmd, check=True, cwd=WHISPER_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        txt_path = out_base + ".txt"
        return open(txt_path, "r", encoding="utf-8", errors="ignore").read().strip() if os.path.exists(txt_path) else ""

    def tts_speak(self, text: str):
        if not text.strip():
            return
        self.tts.text_input.delete("1.0", tk.END)
        self.tts.text_input.insert(tk.END, text)
        self.tts.generate_and_play()

    # ---------- LLM + UI actions ----------
    def llm_reply(self, user_text: str) -> str:
        messages = [
            {"role": "system", "content": "You are Lingo, a friendly English tutor in a robot head. Keep answers under 2 sentences and end with a short question."},
            {"role": "user", "content": user_text},
        ]
        return self.llm.chat(messages)

    def on_speak(self):
        try:
            text = self.stt_capture_and_transcribe()
            if not text:
                self._say("STT", "(No speech detected)"); self.set_status("Ready"); return
            self._say("You", text); self.set_status("Thinking…")
            ai = self.llm_reply(text); self._last_ai_text = ai; self._say("Lingo", ai)
            self.set_status("Speaking…"); self.tts_speak(ai); self.set_status("Ready")
        except Exception as e:
            messagebox.showerror("Error", str(e)); self.set_status("Ready")

    def on_speak_reply(self):
        if not self._last_ai_text.strip():
            self._say("System", "Nothing to speak yet."); return
        self.set_status("Speaking…")
        try:
            self.tts_speak(self._last_ai_text)
        finally:
            self.set_status("Ready")

    def on_send(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)
        self._say("You", text)
        self.set_status("Thinking…")
        try:
            ai = self.llm_reply(text)
            self._last_ai_text = ai
            self._say("Lingo", ai)
            # Auto-speak typed replies too
            self.tts_speak(ai)
            self.set_status("Ready")
        except Exception as e:
            messagebox.showerror("LLM error", str(e)); self.set_status("Ready")

    # ---------- Tools ----------
    def on_list_devices(self):
        try:
            out1 = subprocess.check_output(["arecord", "-l"], text=True, stderr=subprocess.STDOUT)
        except Exception as e:
            out1 = f"arecord -l error: {e}"
        self._say("Devices (arecord)", out1.strip())

    def on_test_mic(self):
        """Quick 3s capture and playback to check input level & routing."""
        test_wav = "/tmp/test_mic.wav"
        try:
            self._say("Test", "Recording 3s…")
            subprocess.run(["arecord","-D",f"plughw:{MIC_INDEX},0","-f","S16_LE","-r","16000","-c","1","-d","3",test_wav], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError:
            self._say("Test", "plughw failed; retry with default…")
            subprocess.run(["arecord","-D","default","-f","S16_LE","-r","16000","-c","1","-d","3",test_wav], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        peak, rms = self._wav_stats(test_wav)
        self._say("Test", f"peak={peak} rms={rms} — playing back…")
        try:
            subprocess.run(["aplay", test_wav], check=True)
        except Exception as e:
            self._say("aplay", f"Playback issue: {e}")

# ------------------- Entry -------------------
if __name__ == "__main__":
    app = VoiceTester()
    app.mainloop()
