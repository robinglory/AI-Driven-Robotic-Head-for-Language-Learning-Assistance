#!/usr/bin/env python3
import os, subprocess, argparse, sys, time
import assemblyai as aai

DEFAULT_MIC = "plughw:3,0"   # your AB13X was card 3, device 0
SAMPLE_RATE = 16000

def record(out_wav: str, seconds: int, mic: str):
    # -f S16_LE = 16-bit PCM, -r 16000 = 16kHz, -c 1 = mono
    cmd = [
        "arecord",
        "-D", mic,
        "-f", "S16_LE",
        "-r", str(SAMPLE_RATE),
        "-c", "1",
        "-d", str(seconds),
        out_wav
    ]
    print(f"[rec] Recording {seconds}s from {mic} → {out_wav}")
    subprocess.run(cmd, check=True)

def transcribe(wav_path: str):
    api_key = os.getenv("ASSEMBLYAI_API_KEY")
    if not api_key:
        print("ERROR: ASSEMBLYAI_API_KEY is not set in your environment.", file=sys.stderr)
        sys.exit(1)

    aai.settings.api_key = api_key
    transcriber = aai.Transcriber()

    # Universal is the default model; formatting/punctuation are on for it.
    # Docs: https://www.assemblyai.com/docs/getting-started/transcribe-an-audio-file
    print("[aai] Uploading & transcribing…")
    t0 = time.time()
    transcript = transcriber.transcribe(wav_path)
    dt = time.time() - t0

    if transcript.error:
        print(f"[aai] Transcription failed: {transcript.error}")
        sys.exit(1)

    print("\n=== TRANSCRIPT ===\n")
    print(transcript.text.strip())
    print("\n==================")
    print(f"[aai] Done in {dt:.1f}s")

def main():
    ap = argparse.ArgumentParser(description="Record with arecord and transcribe with AssemblyAI")
    ap.add_argument("--mic", default=DEFAULT_MIC, help='ALSA device, e.g. "plughw:3,0"')
    ap.add_argument("--seconds", type=int, default=60, help="Record duration in seconds")
    ap.add_argument("--out", default="capture.wav", help="Output WAV path")
    args = ap.parse_args()

    try:
        record(args.out, args.seconds, args.mic)
    except subprocess.CalledProcessError as e:
        print(f"[rec] Recording failed: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        transcribe(args.out)
    except Exception as e:
        print(f"[aai] Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
