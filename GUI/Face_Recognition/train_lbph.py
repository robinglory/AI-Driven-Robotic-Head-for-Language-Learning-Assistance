#!/usr/bin/env python3
import os, sys, json, cv2
import numpy as np

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

def load_dataset():
    images, labels, name_to_id = [], [], {}
    next_id = 0
    for name in sorted(os.listdir(DB_ROOT)):
        person_dir = os.path.join(DB_ROOT, name)
        if not os.path.isdir(person_dir) or name == "models":
            continue
        if name not in name_to_id:
            name_to_id[name] = next_id
            next_id += 1
        label_id = name_to_id[name]
        for fn in sorted(os.listdir(person_dir)):
            if fn.lower().endswith(".png"):
                p = os.path.join(person_dir, fn)
                img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                images.append(img)
                labels.append(label_id)
    if not images:
        print("❌ No training images found. Run capture_faces.py first.")
        sys.exit(1)
    return images, np.array(labels, dtype=np.int32), name_to_id

def main():
    check_cv2_face()
    os.makedirs(MODEL_DIR, exist_ok=True)
    images, labels, name_to_id = load_dataset()

    print(f"🧠 Training LBPH on {len(images)} images across {len(name_to_id)} classes...")
    recognizer = cv2.face.LBPHFaceRecognizer_create(radius=1, neighbors=8, grid_x=8, grid_y=8)
    recognizer.train(images, labels)
    recognizer.save(MODEL_PATH)
    with open(LABELS_PATH, "w") as f:
        json.dump(name_to_id, f, indent=2)
    print(f"✅ Saved model: {MODEL_PATH}")
    print(f"✅ Saved labels: {LABELS_PATH}")

if __name__ == "__main__":
    main()
