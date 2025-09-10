# face_tracker.py
import os, time, threading
import cv2
from typing import Callable

# --- reuse your cascade path resolution idea ---
CANDIDATE_CASCADES = [
    "/home/robinglory/Desktop/Thesis/Camera Testing/haarcascade_frontalface_default.xml",
    "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
    "/usr/share/opencv/haarcascades/haarcascade_frontalface_default.xml",
    os.path.join(os.path.dirname(cv2.__file__), "data/haarcascades/haarcascade_frontalface_default.xml"),
]
CASCADE_PATH = next((p for p in CANDIDATE_CASCADES if os.path.exists(p)), None)
if not CASCADE_PATH:
    raise RuntimeError("haarcascade_frontalface_default.xml not found. Try: sudo apt install -y opencv-data")
CASCADE = cv2.CascadeClassifier(CASCADE_PATH)
if CASCADE.empty():
    raise RuntimeError(f"Failed to load cascade at: {CASCADE_PATH}")

def _clamp(v, a, b): return a if v < a else (b if v > b else v)

class FaceTracker:
    """
    Background camera loop (no window):
      - when app is IDLE → send 'track_on' once and periodic 'gaze <ud> <lr>'
      - when leaving IDLE or paused → send 'track_off' once and stop sending
      - UD range: 135..165, LR range: 60..110 (your safe hardware limits)
    """
    def __init__(
        self,
        send_cmd: Callable[[str], None],         # call to send serial commands
        get_state: Callable[[], str],            # returns "IDLE"/"LISTENING"/"THINKING"/"TALKING"
        ensure_serial: Callable[[], None],       # ensures serial is connected
        width: int = 1280, height: int = 720,
        rate_hz: float = 10.0,                   # ~10 Hz commands max
        deadband_deg: float = 1.0,               # ignore tiny jitters
    ):
        self._send = send_cmd
        self._get_state = get_state
        self._ensure_serial = ensure_serial
        self._W, self._H = width, height
        self._period = 1.0 / max(1e-6, rate_hz)
        self._deadband = float(deadband_deg)

        self._want_run = False
        self._paused = False
        self._thread = None
        self._track_on_sent = False
        self._last_sent_ud = None
        self._last_sent_lr = None
        # NEW: hard throttle — only one gaze every 1.5s
        self._min_dwell_s = 1.5
        self._last_send_t = 0.0

        # NEW: add extra 10° push toward the target direction (still clamped)
        self._extra_deg = 10.0
        # choose the “mid” we compare against for sign of the push
        self._ud_mid = 150.0  # if you prefer, set to 140.0 to match EYE_UD_MID
        self._lr_mid = 85.0


    def start(self):
        if self._thread: return
        self._want_run = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._want_run = False

    # externally pause/resume + send track_off/track_on
    def pause_and_trackoff(self):
        self._paused = True
        if self._track_on_sent:
            try: self._send("track_off")
            except: pass
            self._track_on_sent = False

    def resume_and_trackon(self):
        self._paused = False
        # let the loop send track_on when it sees IDLE

    def _loop(self):
        # late import so your app still runs if camera stack is missing
        try:
            from picamera2 import Picamera2
        except Exception as e:
            print("[TRACK] Picamera2 not available:", e)
            return

        cam = Picamera2()
        cam.configure(cam.create_preview_configuration(main={"size": (self._W, self._H)}))
        cam.start()
        time.sleep(0.5)

        try:
            while self._want_run:
                t0 = time.time()

                # If not idle or explicitly paused → ensure track_off once, then sleep
                state = (self._get_state() or "").upper()
                if self._paused or state != "IDLE":
                    if self._track_on_sent:
                        try: self._send("track_off")
                        except: pass
                        self._track_on_sent = False
                    time.sleep(0.12)
                    continue

                # We are idle: ensure serial + track_on (once)
                try:
                    self._ensure_serial()
                    if not self._track_on_sent:
                        self._send("track_on")
                        # seed to center once (inside Arduino it will clamp/smooth)
                        self._send("gaze 140 85")
                        self._track_on_sent = True
                except Exception as e:
                    print("[TRACK] serial error:", e)
                    time.sleep(0.3)
                    continue

                # Grab frame (RGB), convert to gray and detect
                frame_rgb = cam.capture_array()
                if frame_rgb is None:
                    time.sleep(0.05); continue

                gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
                gray = cv2.equalizeHist(gray)
                faces = CASCADE.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
                )

                if len(faces) > 0:
                    # pick the largest face
                    x, y, w, h = max(faces, key=lambda r: r[2]*r[3])
                    cx = x + w/2.0
                    cy = y + h/2.0

                    # Base mapping (image → degrees within your safe box)
                    ud = 135.0 + (165.0 - 135.0) * (cy / float(self._H))  # up→135, down→165
                    lr =  60.0 + (110.0 -  60.0) * (cx / float(self._W))  # left→60, right→110

                    # EXTRA push of ±10° toward the direction (boost visibility), then clamp
                    # if face is above mid, push UD upward (smaller number); if below, push downward (larger number)
                    ud += (-self._extra_deg) if (ud < self._ud_mid) else (+self._extra_deg)
                    lr += (-self._extra_deg) if (lr < self._lr_mid) else (+self._extra_deg)
                    ud = _clamp(ud, 135.0, 165.0)
                    lr = _clamp(lr,  60.0, 110.0)

                    # PIXEL deadband (tiny jitters) AND HARD THROTTLE (min 1.5 s between commands)
                    now = time.time()
                    if (self._last_sent_ud is None or abs(ud - self._last_sent_ud) >= self._deadband or
                        self._last_sent_lr is None or abs(lr - self._last_sent_lr) >= self._deadband):
                        if (now - self._last_send_t) >= self._min_dwell_s:
                            try:
                                self._send(f"gaze {ud:.1f} {lr:.1f}")
                                self._last_sent_ud = ud
                                self._last_sent_lr = lr
                                self._last_send_t  = now
                            except Exception as e:
                                print("[TRACK] send gaze failed:", e)


                # simple rate limit
                dt = time.time() - t0
                sleep_left = self._period - dt
                if sleep_left > 0: time.sleep(sleep_left)
        finally:
            try: cam.stop()
            except: pass
