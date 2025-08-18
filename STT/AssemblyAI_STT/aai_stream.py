#!/usr/bin/env python3
import os, sys, logging
import assemblyai as aai
from assemblyai.streaming.v3 import (
    StreamingClient, StreamingClientOptions, StreamingEvents,
    StreamingParameters, BeginEvent, TurnEvent, TerminationEvent, StreamingError
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
if not API_KEY:
    print("ERROR: ASSEMBLYAI_API_KEY not set. Run: export ASSEMBLYAI_API_KEY='...'", file=sys.stderr)
    sys.exit(1)

# 16 kHz mono PCM is what the streaming endpoint expects; the SDK's MicrophoneStream handles this for you.
SAMPLE_RATE = 16000

def main():
    try:
        client = StreamingClient(StreamingClientOptions(api_key=API_KEY))
    except Exception as e:
        print(f"ERROR: Could not create StreamingClient: {e}", file=sys.stderr)
        sys.exit(1)

    def on_begin(_c: StreamingClient, ev: BeginEvent):
        print(f"[stream] session started: {ev.id}")
        print("Speak now… (Ctrl+C to stop)")

    def on_turn(_c: StreamingClient, ev: TurnEvent):
        # ev.transcript contains the latest immutable transcript chunk
        if ev.transcript:
            print(ev.transcript)

    def on_end(_c: StreamingClient, ev: TerminationEvent):
        print(f"[stream] terminated. audio={ev.audio_duration_seconds:.2f}s, session={ev.session_duration_seconds:.2f}s")

    def on_err(_c: StreamingClient, err: StreamingError):
        print(f"[stream] ERROR: {err}", file=sys.stderr)

    client.on(StreamingEvents.Begin, on_begin)
    client.on(StreamingEvents.Turn, on_turn)
    client.on(StreamingEvents.Termination, on_end)
    client.on(StreamingEvents.Error, on_err)

    # Connect and stream from microphone (requires assemblyai[extras] + PortAudio / PyAudio)
    try:
        client.connect(StreamingParameters(sample_rate=SAMPLE_RATE, format_turns=True))
    except Exception as e:
        print(f"ERROR: connect() failed: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        mic = aai.extras.MicrophoneStream(sample_rate=SAMPLE_RATE)  # uses PyAudio
    except Exception as e:
        print(f"ERROR: Microphone open failed: {e}\n"
              f"Try: sudo apt install -y python3-pyaudio  (already done)\n"
              f"Also ensure no other process is using the mic.", file=sys.stderr)
        client.disconnect(terminate=True)
        sys.exit(1)

    try:
        client.stream(mic)   # blocks until Ctrl+C
    except KeyboardInterrupt:
        print("\nCtrl+C — stopping…")
    finally:
        client.disconnect(terminate=True)
        try: mic.close()
        except: pass

if __name__ == "__main__":
    main()
