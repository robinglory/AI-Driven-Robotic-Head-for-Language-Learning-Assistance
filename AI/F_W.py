#!/usr/bin/env python3
"""
Standalone Faster-Whisper tester
File: /home/robinglory/Desktop/Thesis/AI/faster_whisper.py

- Record short clips from mic (arecord) or open .wav files
- Transcribe using Faster-Whisper (local model)
- Show text + timings
"""

import os, sys, time, subprocess, wave
from faster_whisper import WhisperModel

# -------- Paths --------
MODEL_TINY = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-tiny.en"
MODEL_BASE = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-base.en"
TEMP_WAV   = "/tmp/fw_record.wav"

# -------- Load model --------
def load_model(use_base=True):
    model_path = MODEL_BASE if use_base else MODEL_TINY
    print(f"Loading model: {model_path}")
    # compute_type="int8" is lighter for Raspberry Pi
    return WhisperModel(model_path, device="cpu", compute_type="int8")

# -------- Recorder --------
def record_audio(seconds=7, mic_index=3, rate=16000):
    """Record audio with arecord."""
    print(f"[Recorder] Capturing {seconds}s from mic index {mic_index}...")
    cmd = [
        "arecord",
        "-D", f"plughw:{mic_index},0",
        "-f", "S16_LE",
        "-r", str(rate),
        "-c", "1",
        "-d", str(seconds),
        TEMP_WAV,
    ]
    subprocess.run(cmd, check=True)
    return TEMP_WAV

def wav_stats(path):
    try:
        with wave.open(path, "rb") as w:
            nchan = w.getnchannels()
            width = w.getsampwidth()
            rate = w.getframerate()
            frames = w.getnframes()
        dur = frames / float(rate)
        return f"{rate} Hz, {nchan} ch, {dur:.1f}s"
    except Exception as e:
        return f"(error reading wav: {e})"

# -------- Transcriber --------
def transcribe(model, wav_path):
    print(f"[Transcribe] {wav_path} ({wav_stats(wav_path)})")
    start = time.time()
    segments, info = model.transcribe(wav_path, beam_size=3, language="en")
    print(f"[Model] Duration={info.duration:.2f}s, WhisperTime={time.time()-start:.2f}s")
    text = "".join(seg.text for seg in segments)
    return text.strip()

# -------- Menu --------
def main():
    model = load_model(use_base=True)  # change to False for tiny.en

    while True:
        print("\nOptions:")
        print("1) Record 7s and transcribe")
        print("2) Choose audio file and transcribe")
        print("3) Quit")
        choice = input("Select: ").strip()

        if choice == "1":
            path = record_audio(7)
            text = transcribe(model, path)
            print("\n[Result]\n", text)

        elif choice == "2":
            path = input("Enter wav path: ").strip()
            if not os.path.isfile(path):
                print("File not found.")
                continue
            text = transcribe(model, path)
            print("\n[Result]\n", text)

        elif choice == "3":
            print("Bye!")
            break
        else:
            print("Invalid choice.")

if __name__ == "__main__":
    main()
