import subprocess, json, sys, signal
from vosk import Model, KaldiRecognizer

MODEL_PATH = "/home/robinglory/Desktop/Thesis/STT/vosk-model-small-en-us-0.15"
#MODEL_PATH = "/home/robinglory/Desktop/Thesis/STT/vosk-model-en-us-0.22-lgraph"

RATE = 16000
CHUNK = 3200  # ~0.1s at 16kHz mono 16-bit

model = Model(MODEL_PATH)
rec = KaldiRecognizer(model, RATE)

# Use plughw so ALSA converts to 16k mono for us
# If card index changes, adjust "plughw:3,0" accordingly.
cmd = [
    "arecord",
    "-D", "plughw:3,0",
    "-f", "S16_LE",
    "-r", str(RATE),
    "-c", "1",
    "-t", "raw"   # raw PCM to stdout (no WAV header)
]

print("Listening… say a short phrase and pause. Ctrl+C to stop.")
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

def stop(*_):
    try: proc.terminate()
    except: pass
    sys.exit(0)

signal.signal(signal.SIGINT, stop)

while True:
    data = proc.stdout.read(CHUNK)
    if not data:
        break
    if rec.AcceptWaveform(data):
        res = json.loads(rec.Result()).get("text","").strip()
        if res:
            print(f"[FINAL] {res}")
    else:
        pres = json.loads(rec.PartialResult()).get("partial","").strip()
        if pres:
            print(f"[PART ] {pres}", end="\r", flush=True)

tail = json.loads(rec.FinalResult()).get("text","").strip()
if tail:
    print(f"\n[FINAL] {tail}")
