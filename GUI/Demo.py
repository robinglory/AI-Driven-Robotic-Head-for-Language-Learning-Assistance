import tkinter as tk
from tkinter import ttk, scrolledtext
import serial, time, threading, random, subprocess, pygame

# ================= CONFIG =================
PIPER_EXE = "/home/robinglory/Desktop/Thesis/TTS/piper/build/piper"
VOICE = "/home/robinglory/Desktop/Thesis/TTS/piper/models/en_US-hfc_female-medium.onnx"
TMP_WAV = "/tmp/tts.wav"
SERIAL_PORT = "/dev/ttyACM0"
BAUD = 115200

PHRASES = [
    "Hello there.", "Hi, I am Lingo.", "What are you doing, my friend?",
    "Welcome to the conference.", "I like talking with humans.",
    "Do you want to learn English?", "Please come closer.", "It is nice to meet you.",
    "I can help you practice.", "Learning is fun, right?", "You look curious today.",
    "Shall we talk together?"
]

running = False

pygame.mixer.init() 

# ================= SERIAL =================
def send(cmd):
    try:
        ser.write((cmd + "\n").encode())
        append_serial(f"> {cmd}")
    except:
        append_serial(f"[ERROR] Failed to send: {cmd}")

def append_serial(msg):
    serial_output.configure(state='normal')
    serial_output.insert(tk.END, msg + "\n")
    serial_output.see(tk.END)
    serial_output.configure(state='disabled')

# ================= TTS =================
import wave
import numpy as np

def generate_wav_and_envelope(text):
    try:
        proc = subprocess.Popen(
            [PIPER_EXE, "-m", VOICE, "-f", TMP_WAV],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True
        )
        _, err = proc.communicate(text)
        if proc.returncode != 0:
            append_serial(f"[TTS ERROR] {err}")
            return None, []
    except Exception as e:
        append_serial(f"[TTS EXCEPTION] {e}")
        return None, []

    try:
        with wave.open(TMP_WAV, "rb") as wf:
            n_channels, sampwidth, fr, n_frames, _, _ = wf.getparams()
            raw = wf.readframes(n_frames)
        dtype = np.int16 if sampwidth == 2 else np.int8
        data = np.frombuffer(raw, dtype=dtype)
        if n_channels > 1:
            data = data.reshape(-1, n_channels).mean(axis=1)
        data = data.astype(np.float32) / (np.iinfo(dtype).max if dtype == np.int16 else 127.0)
        hop = int(fr * 0.01)
        envelope = [float(np.sqrt(np.mean(data[i:i+hop]**2) + 1e-9)) for i in range(0, len(data), hop)]
        mx = max(envelope) if envelope else 1.0
        envelope = [min(1.0, v/mx) for v in envelope]
        return TMP_WAV, envelope
    except Exception as e:
        append_serial(f"[ENVELOPE ERROR] {e}")
        return TMP_WAV, []

def speak(text):
    wav_path, envelope = generate_wav_and_envelope(text)
    if not wav_path or not envelope:
        return
    pygame.mixer.music.load(wav_path)
    pygame.mixer.music.play()
    for rms in envelope:
        jaw_pos = int(rms * 180)
        send(f"jaw {jaw_pos}")
        time.sleep(0.01)
    while pygame.mixer.music.get_busy():
        time.sleep(0.01)
    send("jaw 0")

# ================= LIFE LOOP =================
def expo_loop():
    global running
    while running:
        send("think")
        time.sleep(random.uniform(3,6))
        send("listen_left")
        time.sleep(random.uniform(2,4))
        send("listen_right")
        time.sleep(random.uniform(2,4))
        send("think")
        time.sleep(random.uniform(3,6))
        phrase = random.choice(PHRASES)
        send("talk")
        speak(phrase)
        send("stop")
        send("park")
        time.sleep(random.uniform(5,10))

def start_expo():
    global running
    if not running:
        running = True
        threading.Thread(target=expo_loop, daemon=True).start()
        status.set("EXPO MODE RUNNING")

def stop_expo():
    global running
    running = False
    send("stop")
    send("park")
    status.set("STOPPED")

def manual(cmd):
    stop_expo()
    send(cmd)

# ================= GUI =================
ser = serial.Serial(SERIAL_PORT, BAUD, timeout=1)
time.sleep(2)

root = tk.Tk()
root.title("LINGO CONFERENCE CONTROL")
root.geometry("550x650")
root.configure(bg="#F5F0FF")  # light purple background

style = ttk.Style(root)
style.configure("TButton", font=("Helvetica", 12), padding=5)
style.configure("TLabel", background="#F5F0FF", font=("Helvetica", 12))
style.configure("Header.TLabel", font=("Helvetica", 18, "bold"), foreground="#5D3FD3")

status = tk.StringVar(value="READY")

# Header
ttk.Label(root, text="LINGO CONTROL", style="Header.TLabel").pack(pady=10)
ttk.Label(root, textvariable=status, foreground="#5D3FD3").pack(pady=5)

# Lingo Image Placeholder
#img_frame = tk.Frame(root, bg="#EDE6FF", width=250, height=250)
#img_frame.pack(pady=10)
#img_frame.pack_propagate(False)
#img_label = tk.Label(img_frame, text="Lingo Image", bg="#EDE6FF")
#img_label.pack(expand=True)

# Command Buttons
btn_frame = tk.Frame(root, bg="#F5F0FF")
btn_frame.pack(pady=5)

commands = [("PARK","park"),("THINK","think"),("LISTEN LEFT","listen_left"),
            ("LISTEN RIGHT","listen_right"),("TALK","talk"),("STOP","stop")]

for label, cmd in commands:
    ttk.Button(btn_frame, text=label, command=lambda c=cmd: manual(c)).pack(fill='x', pady=3)

# Expo Mode Buttons
ttk.Button(root, text="▶ START EXPO MODE", style="TButton",
           command=start_expo).pack(fill='x', pady=10, padx=50)
ttk.Button(root, text="■ STOP EXPO MODE", style="TButton",
           command=stop_expo).pack(fill='x', pady=5, padx=50)

# Serial Output Viewer
ttk.Label(root, text="Serial Output:").pack(pady=5)
serial_output = scrolledtext.ScrolledText(root, width=60, height=10, state='disabled', wrap='word')
serial_output.pack(pady=5, padx=10)

root.mainloop()
