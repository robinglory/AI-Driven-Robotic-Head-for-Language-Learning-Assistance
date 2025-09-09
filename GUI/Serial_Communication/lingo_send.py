# lingo_send.py
import sys, time
import serial
from serial.tools import list_ports

BAUD = 115200
READ_SECS = 12  # keep reading long enough to see LISTEN/THINK/RETURN messages

def find_port():
    for p in list_ports.comports():
        if "ACM" in p.device: return p.device
    for p in list_ports.comports():
        if "USB" in p.device: return p.device
    raise SystemExit("No Arduino serial port found (ACM/USB).")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 lingo_send.py <command>"); sys.exit(1)

    cmd = " ".join(sys.argv[1:])
    port = find_port()
    ser = serial.Serial(port, BAUD, timeout=0.1)
    time.sleep(1.2)            # UNO auto-resets on open
    ser.reset_input_buffer()

    ser.write((cmd.strip() + "\n").encode())
    # read back for a bit
    t0 = time.time(); buf=b""
    while time.time() - t0 < READ_SECS:
        b = ser.read(1)
        if not b: continue
        if b in (b"\n", b"\r"):
            if buf:
                print("[UNO]", buf.decode(errors="replace"))
                buf=b""
        else:
            buf += b
    ser.close()
