# --- Replace your camera config block with this ---
from picamera2 import Picamera2, Preview
import cv2, time

picam2 = Picamera2()

# Start in 4:3 to recover more FOV (OV5647 friendly sizes)
FOUR_THIRDS = (1640, 1232)   # Nice binned 4:3 mode
SIXTEEN_NINE = (1280, 720)   # Typical 16:9 (cropped)

current_aspect = "4:3"
W, H = FOUR_THIRDS

def configure(size):
    global W, H
    W, H = size
    cfg = picam2.create_preview_configuration(main={"size": size})
    picam2.configure(cfg)

configure(FOUR_THIRDS)
picam2.start()
time.sleep(0.5)

win = "face-detection testing!"
cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)

try:
    while True:
        frame = picam2.capture_array()
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        # (… your face detection + overlays here …)

        cv2.putText(frame, f"Mode: {current_aspect}  ({W}x{H})",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2, cv2.LINE_AA)
        cv2.putText(frame, "Press 't' to toggle 4:3 <-> 16:9, 'q' to quit",
                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2, cv2.LINE_AA)

        cv2.imshow(win, frame)
        k = cv2.waitKey(1) & 0xFF
        if k == ord('q'):
            break
        elif k == ord('t'):
            # Toggle aspect ratio
            if current_aspect == "4:3":
                current_aspect = "16:9"
                picam2.stop()
                configure(SIXTEEN_NINE)
                picam2.start()
            else:
                current_aspect = "4:3"
                picam2.stop()
                configure(FOUR_THIRDS)
                picam2.start()
finally:
    picam2.stop()
    cv2.destroyAllWindows()
