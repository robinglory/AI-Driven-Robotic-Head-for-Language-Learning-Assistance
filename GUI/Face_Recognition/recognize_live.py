#!/usr/bin/env python3
import os, sys, time, json, argparse
import cv2
import numpy as np
from picamera2 import Picamera2

# ---------- Camera / UI ----------
W, H = 1280, 720
FONT = cv2.FONT_HERSHEY_SIMPLEX
THRESH_UNKNOWN = 70.0   # LBPH distance; lower is better; > threshold => Unknown
STABLE_FRAMES = 5       # consecutive frames with same non-Unknown name

# ---------- Cascade ----------
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
ROOT = os.path.abspath(os.path.dirname(__file__))
DB_ROOT = os.path.join(ROOT, "FaceDB")
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

def run_once_json(timeout_s=12, show_window=False):
    """Show window if requested; print one JSON line {name, distance} and exit."""
    check_cv2_face()
    recognizer, id_to_name = load_model()

    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(main={"size": (W, H)}))
    cam.start()
    time.sleep(0.5)

    t0 = time.time()
    stable_name = None
    stable_count = 0

    try:
        while True:
            rgb = cam.capture_array()
            frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            faces = CASCADE.detectMultiScale(gray, 1.1, 5, minSize=(60,60))
            best = largest_face(faces)

            if best is not None:
                roi = preprocess(gray, best)
                if roi is not None:
                    label_id, distance = recognizer.predict(roi)
                    name = id_to_name.get(label_id, "Unknown")
                    if distance > THRESH_UNKNOWN:
                        name = "Unknown"

                    if name != "Unknown":
                        if stable_name == name:
                            stable_count += 1
                        else:
                            stable_name = name
                            stable_count = 1

                        if stable_count >= STABLE_FRAMES:
                            print(json.dumps({"name": name, "distance": float(distance)}))
                            sys.exit(0)
                    else:
                        stable_name = None
                        stable_count = 0

            if show_window:
                # Minimal overlay text; 'q' cancels
                cv2.putText(frame, "Face Login…", (10,30), FONT, 0.9, (0,255,255), 2, cv2.LINE_AA)
                cv2.imshow("Face Login", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    print(json.dumps({"name": None}))
                    sys.exit(3)

            if time.time() - t0 > timeout_s:
                print(json.dumps({"name": None}))
                sys.exit(2)
    finally:
        cam.stop()
        if show_window:
            cv2.destroyAllWindows()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="Exit after confident recognition")
    ap.add_argument("--json", action="store_true", help="Output a single JSON line result")
    ap.add_argument("--timeout", type=int, default=12, help="Seconds to wait in --once mode")
    ap.add_argument("--show", action="store_true", help="Show window in --once mode")
    args = ap.parse_args()

    if args.once and args.json:
        run_once_json(timeout_s=args.timeout, show_window=args.show)
        return

    # ------- Original live test mode (unchanged) -------
    check_cv2_face()
    recognizer, id_to_name = load_model()

    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(main={"size": (W, H)}))
    cam.start()
    time.sleep(0.5)

    fps = 0.0; alpha=0.1; t_prev=time.time()
    try:
        while True:
            rgb = cam.capture_array()
            frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

            t_now=time.time(); dt=t_now-t_prev; t_prev=t_now
            inst_fps=(1.0/dt) if dt>0 else 0.0
            fps = (1-alpha)*fps + alpha*inst_fps if fps>0 else inst_fps

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            faces = CASCADE.detectMultiScale(gray, 1.1, 5, minSize=(60,60))

            cv2.putText(frame, "face-recognition testing!", (10,30), FONT, 0.9, (0,255,255), 2, cv2.LINE_AA)
            cv2.putText(frame, f"FPS: {fps:.1f}", (10,60), FONT, 0.8, (0,255,0), 2, cv2.LINE_AA)

            best = largest_face(faces)
            if best is not None:
                x,y,w,h = best
                cv2.rectangle(frame, (x,y), (x+w,y+h), (0,230,0), 2)
                roi = preprocess(gray, best)
                if roi is not None:
                    label_id, distance = recognizer.predict(roi)
                    name = id_to_name.get(label_id, "Unknown")
                    if distance > THRESH_UNKNOWN:
                        name = "Unknown"

                    label = f"{name}  (dist {distance:.1f} / thr {THRESH_UNKNOWN:.0f})"
                    tx = x + w + 8 if (x + w + 240) < W else x - 240
                    tx = max(5, tx); ty = max(20, y + 15)
                    cv2.putText(frame, label, (tx,ty), FONT, 0.6, (255,255,255), 2, cv2.LINE_AA)

            cv2.imshow("recognize_live", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    finally:
        cam.stop()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
