#!/usr/bin/env python3
import os, sys, time, json
import cv2
import numpy as np
from picamera2 import Picamera2

# ---------- Camera / UI ----------
W, H = 1280, 720
FONT = cv2.FONT_HERSHEY_SIMPLEX
THRESH_UNKNOWN = 70.0  # lower distance is better; > this => Unknown

# ---------- Cascade (same as your detector) ----------
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

# ---------- LBPH model paths ----------
DB_ROOT = os.path.abspath("FaceDB")
MODEL_DIR = os.path.join(DB_ROOT, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "lbph.yml")
LABELS_PATH = os.path.join(MODEL_DIR, "labels.json")

def check_cv2_face():
    ok = hasattr(cv2, "face") and hasattr(cv2.face, "LBPHFaceRecognizer_create")
    if not ok:
        print("❌ cv2.face not available.")
        print("   Fix: activate venv and run: pip install opencv-contrib-python==4.9.0.80")
        sys.exit(1)

def load_model():
    if not (os.path.exists(MODEL_PATH) and os.path.exists(LABELS_PATH)):
        print("❌ Model files missing. Train first: python train_lbph.py")
        sys.exit(1)
    with open(LABELS_PATH, "r") as f:
        name_to_id = json.load(f)
    id_to_name = {v: k for k, v in name_to_id.items()}
    recog = cv2.face.LBPHFaceRecognizer_create()
    recog.read(MODEL_PATH)
    return recog, id_to_name

def region_label(cx, cy, W, H):
    thirds_x = (W/3, 2*W/3)
    thirds_y = (H/3, 2*H/3)
    lr = "left" if cx < thirds_x[0] else ("middle" if cx < thirds_x[1] else "right")
    tb = "top" if cy < thirds_y[0] else ("middle" if cy < thirds_y[1] else "bottom")
    return f"{tb}-{lr}"

def side_of_screen(cx, W):
    if cx < W/2 - 1: return "Left"
    if cx > W/2 + 1: return "Right"
    return "Middle"

def preprocess(gray, box):
    x,y,w,h = box
    roi = gray[y:y+h, x:x+w]
    if roi.size == 0:
        return None
    roi = cv2.equalizeHist(roi)
    roi = cv2.resize(roi, (200,200), interpolation=cv2.INTER_AREA)
    return roi

def largest_face(faces):
    if len(faces)==0: return None
    return max(faces, key=lambda b: b[2]*b[3])

def main():
    check_cv2_face()
    recognizer, id_to_name = load_model()

    picam2 = Picamera2()
    picam2.configure(picam2.create_preview_configuration(main={"size": (W, H)}))
    picam2.start()
    time.sleep(0.5)

    # FPS smoothing like your script
    fps = 0.0; alpha=0.1; t_prev=time.time()

    try:
        while True:
            rgb = picam2.capture_array()
            frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

            t_now=time.time(); dt=t_now-t_prev; t_prev=t_now
            inst_fps=(1.0/dt) if dt>0 else 0.0
            fps = (1-alpha)*fps + alpha*inst_fps if fps>0 else inst_fps

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            faces = CASCADE.detectMultiScale(gray, 1.1, 5, minSize=(60,60))

            # grid lines like your detector
            cv2.putText(frame, "face-recognition testing!", (10,30), FONT, 0.9, (0,255,255), 2, cv2.LINE_AA)
            cv2.putText(frame, f"FPS: {fps:.1f}", (10,60), FONT, 0.8, (0,255,0), 2, cv2.LINE_AA)
            cv2.line(frame, (W//2,0),(W//2,H),(60,60,60),1,cv2.LINE_AA)
            cv2.line(frame, (0,H//2),(W,H//2),(60,60,60),1,cv2.LINE_AA)
            cv2.line(frame, (W//3,0),(W//3,H),(40,40,40),1,cv2.LINE_AA)
            cv2.line(frame, (2*W//3,0),(2*W//3,H),(40,40,40),1,cv2.LINE_AA)
            cv2.line(frame, (0,H//3),(W,H//3),(40,40,40),1,cv2.LINE_AA)
            cv2.line(frame, (0,2*H//3),(W,2*H//3),(40,40,40),1,cv2.LINE_AA)

            best = largest_face(faces)
            if best is not None:
                x,y,w,h = best
                cx, cy = x + w//2, y + h//2
                cv2.rectangle(frame, (x,y), (x+w,y+h), (0,230,0), 2)
                cv2.circle(frame, (cx,cy), 3, (0,230,0), -1, cv2.LINE_AA)

                roi = preprocess(gray, best)
                if roi is not None:
                    label_id, distance = recognizer.predict(roi)  # lower is better
                    name = id_to_name.get(label_id, "Unknown")
                    if distance > THRESH_UNKNOWN:
                        name = "Unknown"

                    side = side_of_screen(cx, W)
                    reg  = region_label(cx, cy, W, H)
                    label_main = f"{name} | {side} | {reg}"
                    label_sub  = f"LBPH dist={distance:.1f}  thr={THRESH_UNKNOWN:.0f}"

                    tx = x + w + 8 if (x + w + 240) < W else x - 240
                    tx = max(5, tx); ty = max(20, y + 15)

                    cv2.putText(frame, label_main, (tx,ty), FONT, 0.6, (255,255,255), 2, cv2.LINE_AA)
                    cv2.putText(frame, label_sub,  (tx,ty+22), FONT, 0.55,(255,255,255), 2, cv2.LINE_AA)

            cv2.imshow("recognize_live", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    finally:
        picam2.stop()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
