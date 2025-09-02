#!/usr/bin/env python3
import os, sys, time, json
import cv2
import numpy as np
from picamera2 import Picamera2

# ---------- Config ----------
W, H = 1280, 720
IMG_SIZE = (200, 200)
SAVE_ROOT = os.path.abspath("FaceDB")

# ---------- Cascade path resolution (same as your detector) ----------
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

def preprocess_face(gray, box):
    x, y, w, h = box
    roi = gray[y:y+h, x:x+w]
    if roi.size == 0:
        return None
    roi = cv2.equalizeHist(roi)
    roi = cv2.resize(roi, IMG_SIZE, interpolation=cv2.INTER_AREA)
    return roi

def largest_face(faces):
    if len(faces) == 0: return None
    return max(faces, key=lambda b: b[2]*b[3])

def main():
    if len(sys.argv) < 2:
        print("Usage: python capture_faces.py <PersonName>")
        sys.exit(1)
    name = sys.argv[1]
    person_dir = os.path.join(SAVE_ROOT, name)
    os.makedirs(person_dir, exist_ok=True)
    print(f"📂 Saving faces to: {person_dir}")
    print("Keys: [c]=capture, [q]=quit")

    picam2 = Picamera2()
    picam2.configure(picam2.create_preview_configuration(main={"size": (W, H)}))
    picam2.start()
    time.sleep(0.5)

    FONT = cv2.FONT_HERSHEY_SIMPLEX
    count = len([f for f in os.listdir(person_dir) if f.lower().endswith(".png")])

    try:
        while True:
            rgb = picam2.capture_array()
            frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray  = cv2.equalizeHist(gray)

            faces = CASCADE.detectMultiScale(gray, 1.1, 5, minSize=(60,60))
            best = largest_face(faces)

            if best is not None:
                x,y,w,h = best
                cv2.rectangle(frame, (x,y), (x+w, y+h), (0,230,0), 2)

            cv2.putText(frame, f"Name: {name}  Captured: {count}", (10,30), FONT, 0.8, (0,255,255), 2, cv2.LINE_AA)
            cv2.putText(frame, "Press 'c' to capture  |  'q' to quit", (10,60), FONT, 0.6, (255,255,255), 2, cv2.LINE_AA)
            cv2.imshow("capture_faces", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            if key == ord('c') and best is not None:
                face_img = preprocess_face(gray, best)
                if face_img is not None:
                    out_path = os.path.join(person_dir, f"img_{count:04d}.png")
                    cv2.imwrite(out_path, face_img)
                    count += 1
                    print(f"💾 Saved {out_path}")

    finally:
        picam2.stop()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
