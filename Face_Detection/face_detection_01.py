
from picamera2 import Picamera2
import cv2, os, time, sys

# --- Cascade path resolution (uses your file first) ---
CANDIDATE_CASCADES = [
    "/home/robinglory/Desktop/Thesis/Camera Testing/haarcascade_frontalface_default.xml",
    "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
    "/usr/share/opencv/haarcascades/haarcascade_frontalface_default.xml",
    os.path.join(os.path.dirname(cv2.__file__), "data/haarcascades/haarcascade_frontalface_default.xml"),
]
CASCADE_PATH = next((p for p in CANDIDATE_CASCADES if os.path.exists(p)), None)
if not CASCADE_PATH:
    print("❌ haarcascade not found. Try: sudo apt install -y opencv-data")
    sys.exit(1)
CASCADE = cv2.CascadeClassifier(CASCADE_PATH)
if CASCADE.empty():
    print(f"❌ Failed to load cascade at: {CASCADE_PATH}")
    sys.exit(1)
print(f"✅ Using cascade: {CASCADE_PATH}")

# --- Helpers ---
def region_label(cx, cy, W, H):
    """Return 3x3 grid label: top/middle/bottom + left/middle/right"""
    thirds_x = (W/3, 2*W/3)
    thirds_y = (H/3, 2*H/3)

    # horizontal
    if cx < thirds_x[0]:
        lr = "left"
    elif cx < thirds_x[1]:
        lr = "middle"
    else:
        lr = "right"

    # vertical (origin top-left in images)
    if cy < thirds_y[0]:
        tb = "top"
    elif cy < thirds_y[1]:
        tb = "middle"
    else:
        tb = "bottom"

    return f"{tb}-{lr}"

def side_of_screen(cx, W):
    """Left/Right (or Middle) based on screen center"""
    if cx < W/2 - 1:
        return "Left"
    elif cx > W/2 + 1:
        return "Right"
    else:
        return "Middle"

# --- Camera setup ---
picam2 = Picamera2()
W, H = 1280, 720
picam2.configure(picam2.create_preview_configuration(main={"size": (W, H)}))
picam2.start()
time.sleep(0.5)

cv2.namedWindow("face-detection testing!", cv2.WINDOW_AUTOSIZE)

# FPS (exponential moving average for stability)
fps = 0.0
alpha = 0.1
t_prev = time.time()

FONT = cv2.FONT_HERSHEY_SIMPLEX

try:
    while True:
        frame_rgb = picam2.capture_array()  # RGB
        frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

        # FPS calc
        t_now = time.time()
        dt = t_now - t_prev
        t_prev = t_now
        inst_fps = (1.0 / dt) if dt > 0 else 0.0
        fps = (1 - alpha) * fps + alpha * inst_fps if fps > 0 else inst_fps

        # Face detection
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = CASCADE.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(60, 60),
        )

        # Title + FPS overlay
        cv2.putText(frame, "face-detection testing!", (10, 30), FONT, 0.9, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, f"FPS: {fps:.1f}", (10, 60),        FONT, 0.8, (0, 255, 0),   2, cv2.LINE_AA)

        # Draw center lines (optional: visualize regions)
        cv2.line(frame, (W//2, 0),   (W//2, H), (60, 60, 60), 1, cv2.LINE_AA)
        cv2.line(frame, (0, H//2),   (W, H//2), (60, 60, 60), 1, cv2.LINE_AA)
        cv2.line(frame, (W//3, 0),   (W//3, H), (40, 40, 40), 1, cv2.LINE_AA)
        cv2.line(frame, (2*W//3, 0), (2*W//3, H), (40, 40, 40), 1, cv2.LINE_AA)
        cv2.line(frame, (0, H//3),   (W, H//3), (40, 40, 40), 1, cv2.LINE_AA)
        cv2.line(frame, (0, 2*H//3), (W, 2*H//3), (40, 40, 40), 1, cv2.LINE_AA)

        # Annotate each face
        for (x, y, w, h) in faces:
            cx = x + w // 2
            cy = y + h // 2

            # Box + center dot
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 230, 0), 2)
            cv2.circle(frame, (cx, cy), 3, (0, 230, 0), -1, cv2.LINE_AA)

            # Left/Right vs center, region, and coords
            side = side_of_screen(cx, W)
            reg  = region_label(cx, cy, W, H)

            label_main = f"{side} | {reg}"
            label_xywh = f"(x={x}, y={y}, w={w}, h={h})"

            # Place labels to the right of the box when possible, else to the left
            tx = x + w + 8 if (x + w + 220) < W else x - 220
            tx = max(5, tx)
            ty = max(20, y + 15)

            cv2.putText(frame, label_main, (tx, ty), FONT, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.putText(frame, label_xywh, (tx, ty + 22), FONT, 0.55, (255, 255, 255), 2, cv2.LINE_AA)

        cv2.imshow("face-detection testing!", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

finally:
    picam2.stop()
    cv2.destroyAllWindows()
