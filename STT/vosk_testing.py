import subprocess, json
from vosk import Model, KaldiRecognizer

model = Model("vosk-model-small-en-us-0.15")
rec = KaldiRecognizer(model, 16000)

sox_cmd = [
    "sox", "-t", "alsa", "plughw:3,0",
    "-r", "16000", "-c", "1", "-b", "16", "-e", "signed-integer",
    "-t", "wav", "-", "gain", "-n", "-3", "highpass", "80"
]

with subprocess.Popen(sox_cmd, stdout=subprocess.PIPE) as proc:
    while True:
        data = proc.stdout.read(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            print(json.loads(rec.Result())["text"])
