#!/usr/bin/env python3
"""
VAD auto-stop recorder + Faster-Whisper transcriber (no LLM/TTS)

Your paths:
  Models:
    /home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-tiny.en
    /home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-base.en
  Script:
    /home/robinglory/Desktop/Thesis/AI/fw_vad_tester.py

What it does
------------
• Record from your mic and AUTO‑STOP when silence is detected (WebRTC VAD)
• Or open an existing WAV
• Save captured audio (16 kHz, mono) to /tmp/fw_vad.wav
• Transcribe locally with faster‑whisper (INT8 on CPU) and show timings
• Play the audio via aplay

Install (once)
--------------
  pip install faster-whisper webrtcvad sounddevice

Run
---
  export OMP_NUM_THREADS=4
  python /home/robinglory/Desktop/Thesis/AI/fw_vad_tester.py
"""
from __future__ import annotations
import os, sys, time, wave, struct, collections, math, subprocess

# ---- Config (edit if needed) ----
MODEL_BASE_DIR = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-base.en"
MODEL_TINY_DIR = "/home/robinglory/Desktop/Thesis/STT/faster-whisper/fw-tiny.en"
USE_BASE = True  # True = base.en, False = tiny.en

SAMPLE_RATE = 16000    # Hz
CHANNELS    = 1        # mono
WIDTH       = 2        # 16-bit samples
FRAME_MS    = 30       # WebRTC VAD supports 10/20/30 ms
VAD_AGGR    = 1        # 0=relaxed .. 3=very aggressive
SILENCE_MS  = 500      # stop after this much trailing silence
MAX_RECORD_S= 12       # absolute safety cap (seconds)
OUTPUT_WAV  = "/tmp/fw_vad.wav"
DEFAULT_MIC_DEVICE = None  # None = default input; else use an index from list_devices()

# ---- Imports & checks ----
try:
    import sounddevice as sd
except Exception as e:
    raise SystemExit("sounddevice not installed. Run: pip install sounddevice\n" + str(e))

try:
    import webrtcvad
except Exception as e:
    raise SystemExit("webrtcvad not installed. Run: pip install webrtcvad\n" + str(e))

try:
    from faster_whisper import WhisperModel
except Exception as e:
    raise SystemExit("faster-whisper not installed. Run: pip install faster-whisper\n" + str(e))

# ---- Helpers ----

def list_devices():
    print("\n=== Input Devices (sounddevice) ===")
    print(sd.query_devices())
    print("\nTip: set DEFAULT_MIC_DEVICE to the index of your USB mic if needed.\n")

def _rms_int16(data_bytes: bytes) -> float:
    if not data_bytes:
        return 0.0
    count = len(data_bytes) // WIDTH
    if count == 0:
        return 0.0
    fmt = f"<{count}h"
    samples = struct.unpack(fmt, data_bytes)
    acc = 0
    for s in samples:
        acc += s * s
    mean = acc / float(count)
    return math.sqrt(mean)


def record_with_vad() -> str:
    """Capture audio until trailing silence >= SILENCE_MS using WebRTC VAD."""
    vad = webrtcvad.Vad(VAD_AGGR)
    frame_bytes = int(SAMPLE_RATE * (FRAME_MS / 1000.0)) * WIDTH
    silence_frames_needed = int(SILENCE_MS / FRAME_MS)
    max_frames = int(MAX_RECORD_S * 1000 / FRAME_MS)

    print(f"[VAD] Starting capture @ {SAMPLE_RATE} Hz, frame={FRAME_MS} ms, stop after {SILENCE_MS} ms silence")

    ring = collections.deque()
    voiced_any = False
    trailing_silence = 0
    frames_total = 0

    def _callback(indata, frames, time_info, status):
        nonlocal voiced_any, trailing_silence, frames_total
        buf = indata.tobytes()
        if len(buf) < frame_bytes:
            return
        # take only first channel when capturing >1
        if CHANNELS > 1:
            # sounddevice always gives interleaved float32 unless specified; we request int16
            pass
        is_voiced = False
        # webrtcvad requires 16-bit mono PCM at 8/16/32/48 kHz
        try:
            is_voiced = vad.is_speech(buf, SAMPLE_RATE)
        except Exception:
            is_voiced = False
        ring.append(buf)
        frames_total += 1
        rms = _rms_int16(buf)
        if is_voiced:
            voiced_any = True
            trailing_silence = 0
            print(f"\r[VAD] frames={frames_total} rms={int(rms)}  (speech)", end="")
        else:
            if voiced_any:
                trailing_silence += 1
            print(f"\r[VAD] frames={frames_total} rms={int(rms)}  (silence {trailing_silence*FRAME_MS} ms)", end="")

    # Use int16 mono stream
    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype='int16',
            device=DEFAULT_MIC_DEVICE,
            blocksize=int(SAMPLE_RATE * (FRAME_MS / 1000.0)),
            callback=_callback,
        ):
            t0 = time.time()
            while True:
                time.sleep(FRAME_MS / 1000.0)
                if frames_total >= max_frames:
                    print("\n[VAD] Max recording time reached.")
                    break
                if voiced_any and trailing_silence >= silence_frames_needed:
                    print("\n[VAD] Trailing silence reached — stopping.")
                    break
    except Exception as e:
        raise SystemExit(f"Audio input error: {e}\nUse list_devices() to choose a working input.")

    # Write WAV
    os.makedirs(os.path.dirname(OUTPUT_WAV), exist_ok=True)
    with wave.open(OUTPUT_WAV, 'wb') as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(WIDTH)
        w.setframerate(SAMPLE_RATE)
        while ring:
            w.writeframes(ring.popleft())
    dur = frames_total * FRAME_MS / 1000.0
    print(f"[VAD] Wrote {OUTPUT_WAV} (approx {dur:.2f}s)")
    return OUTPUT_WAV


def transcribe_file(wav_path: str, use_base: bool = True, beam_size: int = 3, vad_filter: bool = True,
                    min_sil_ms: int = 500, compute_type: str = 'int8') -> str:
    model_dir = MODEL_BASE_DIR if use_base else MODEL_TINY_DIR
    if not os.path.isdir(model_dir):
        raise SystemExit(f"Model folder not found: {model_dir}")
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    print(f"[Model] Loading: {model_dir} (compute={compute_type})")
    t0 = time.perf_counter()
    model = WhisperModel(model_dir, device="cpu", compute_type=compute_type)
    t1 = time.perf_counter()
    print(f"[Model] Load time: {t1 - t0:.2f}s")

    print(f"[ASR] Transcribing {wav_path}…")
    t2 = time.perf_counter()
    segments, info = model.transcribe(
        wav_path,
        language="en",
        beam_size=beam_size,
        vad_filter=vad_filter,
        vad_parameters=dict(min_silence_duration_ms=min_sil_ms),
    )
    t3 = time.perf_counter()
    print(f"[ASR] Detected language: {info.language} (p={info.language_probability:.2f})")
    print(f"[ASR] WhisperTime: {t3 - t2:.2f}s  (total incl. load: {t3 - t0:.2f}s)")
    text = "".join(s.text for s in segments).strip()
    return text


def aplay(wav_path: str):
    try:
        subprocess.run(["aplay", wav_path], check=True)
    except Exception as e:
        print(f"[aplay] {e}")

# ---- Simple menu ----
if __name__ == "__main__":
    while True:
        print("\nOptions:")
        print("1) Record with VAD auto-stop and transcribe")
        print("2) Choose audio file and transcribe")
        print("3) List input devices")
        print("4) Play last capture")
        print("5) Quit")
        choice = input("Select: ").strip()

        if choice == '1':
            wav = record_with_vad()
            txt = transcribe_file(wav, use_base=USE_BASE, beam_size=3, vad_filter=True, min_sil_ms=500, compute_type='int8')
            print("\n[Result]\n", txt)
        elif choice == '2':
            path = input("Enter WAV path: ").strip()
            if not os.path.isfile(path):
                print("File not found.")
                continue
            txt = transcribe_file(path, use_base=USE_BASE, beam_size=3, vad_filter=True, min_sil_ms=500, compute_type='int8')
            print("\n[Result]\n", txt)
        elif choice == '3':
            list_devices()
        elif choice == '4':
            if os.path.isfile(OUTPUT_WAV):
                aplay(OUTPUT_WAV)
            else:
                print("No capture yet.")
        elif choice == '5':
            print("Bye!")
            break
        else:
            print("Invalid choice.")
