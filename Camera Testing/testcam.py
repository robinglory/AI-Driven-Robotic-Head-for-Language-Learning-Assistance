import subprocess
import sys
import termios
import tty
import time
import signal
import os

def get_key():
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch

def main():
    print("Starting camera preview... Press 'c' to capture, 'q' to quit.")

    # Start libcamera-hello in the background (detached)
    preview = subprocess.Popen(["libcamera-hello"], start_new_session=True)

    try:
        while True:
            key = get_key()
            if key == 'c':
                print("Capturing image...")
                subprocess.run(["libcamera-still", "-o", "capture.jpg"])
                print("Image saved as capture.jpg")
            elif key == 'q':
                print("Exiting...")
                # Kill the preview process group
                os.killpg(preview.pid, signal.SIGTERM)
                break
    except KeyboardInterrupt:
        os.killpg(preview.pid, signal.SIGTERM)
        print("\nInterrupted and exiting")

if __name__ == "__main__":
    main()
