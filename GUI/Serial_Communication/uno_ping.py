import time
from serial.tools import list_ports
import serial

# List ports
ports = list(list_ports.comports())
print("Ports:")
for p in ports:
    print(" ", p.device, "-", p.description)

# Pick the first ACM or USB
port = next((p.device for p in ports if "ACM" in p.device), None) \
    or next((p.device for p in ports if "USB" in p.device), None)
if not port:
    raise SystemExit("No Arduino found. Plug the UNO via USB.")

print("Using:", port)
ser = serial.Serial(port, 115200, timeout=0.1)
time.sleep(1.2)             # UNO auto-resets; give it time
ser.reset_input_buffer()    # drop boot text

# Send a command from your sketch’s console
ser.write(b"help\n")

t0 = time.time()
buf = b""
print("Reading for 3s:")
while time.time() - t0 < 3:
    b = ser.read(1)
    if not b: 
        continue
    if b in (b"\n", b"\r"):
        if buf:
            print("[UNO]", buf.decode(errors="replace"))
            buf = b""
    else:
        buf += b

ser.close()

