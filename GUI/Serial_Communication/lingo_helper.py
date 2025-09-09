import sys, time
import serial
from serial.tools import list_ports

def find_port():
    for p in list_ports.comports():
        if "ACM" in p.device: return p.device
    for p in list_ports.comports():
        if "USB" in p.device: return p.device
    raise RuntimeError("No Arduino serial port found.")

def send(cmd):
    port = find_port()
    ser = serial.Serial(port, 115200, timeout=0.1)
    time.sleep(1.2)
    ser.reset_input_buffer()
    ser.write((cmd.strip() + "\n").encode())
    # read a little to show response
    t0 = time.time(); buf=b""
    while time.time()-t0 < 2.0:
        b = ser.read(1)
        if not b: continue
        if b in (b"\n", b"\r"):
            if buf:
                print("[UNO]", buf.decode(errors="replace")); buf=b""
        else:
            buf += b
    ser.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 lingo_send.py <command>"); sys.exit(1)
    send(" ".join(sys.argv[1:]))
