#!/usr/bin/env python3
import time, threading
import serial
from serial.tools import list_ports

BAUD = 115200

def find_port():
    for p in list_ports.comports():
        if "ACM" in p.device: return p.device
    for p in list_ports.comports():
        if "USB" in p.device: return p.device
    raise RuntimeError("No Arduino port (ACM/USB) found.")

class Lingo:
    def __init__(self, port=None):
        self.port = port or find_port()
        # open + immediately deassert DTR/RTS to avoid extra resets
        self.ser = serial.Serial(self.port, BAUD, timeout=0.1, write_timeout=1, rtscts=False, dsrdtr=False)
        # IMPORTANT: pull DTR/RTS low so we don't keep resetting the UNO
        try:
            self.ser.setDTR(False)
            self.ser.setRTS(False)
        except Exception:
            pass
        # first open still caused one reset — wait for READY lines to finish
        time.sleep(1.5)
        self.ser.reset_input_buffer()

        self._stop = False
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        buf = b""
        while not self._stop:
            b = self.ser.read(1)
            if not b: 
                continue
            if b in (b"\n", b"\r"):
                if buf:
                    print("[UNO]", buf.decode(errors="replace"))
                    buf = b""
            else:
                buf += b

    def send(self, cmd: str):
        self.ser.write((cmd.strip() + "\n").encode())

    def close(self):
        self._stop = True
        try: self._reader.join(timeout=0.5)
        except: pass
        self.ser.close()

if __name__ == "__main__":
    dev = Lingo()
    try:
        # you’ll see READY… once, then you can interactively send:
        for cmd in ["help", "listen", "think", "talk"]:
            print("[PI] ->", cmd)
            dev.send(cmd)
            time.sleep(2 if cmd=="help" else 9)
        print("[PI] -> stop")
        dev.send("stop")
        time.sleep(9)
    finally:
        dev.close()
