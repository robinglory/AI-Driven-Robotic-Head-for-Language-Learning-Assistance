from picamera2 import Picamera2
import cv2, os, time, sys

# 1) Put your own absolute path first
CANDIDATE_CASCADES = [
    "/home/robinglory/Desktop/Thesis/Camera Testing/haarcascade_frontalface_default.xml",
    "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
    "/usr/share/opencv/haarcascades/haarcascade_frontalface_default.xml",
    # Try within the cv2 package (some builds ship it here)
    os.path.join(os.path.dirname(cv2.__file__), "data/haarcascades/haarcascade_frontalface_default.xml"),
]

CASCADE_PATH = next((p for p in CANDIDATE_CASCADES if os.path.exists(p)), None)
if not CASCADE_PATH:
    print("❌ Could not find haarcascade_frontalface_default.xml.\n"
          "Install it or adjust the path at the top of this script.\n"
          "Tip (Debian/Raspberry Pi OS): sudo apt install -y opencv-data")
    sys.exit(1)

CASCADE = cv2.CascadeClassifier(CASCADE_PATH)
if CASCADE.empty():
    print(f"❌ Cascade failed to load from: {CASCADE_PATH}\n"
          "The file may be corrupt. Reinstall opencv-data or download a fresh copy.")
    sys.exit(1)

print(f"✅ Using cascade: {CASCADE_PATH}")

picam2 = Picamera2()
picam2.configure(picam2.create_preview_configuration(main={"size": (1280, 720)}))
picam2.start()
time.sleep(0.5)  # let AE/AWB/AF settle

cv2.namedWindow("PiCam3 Faces", cv2.WINDOW_AUTOSIZE)

try:
    while True:
        frame = picam2.capture_array()             # RGB
        gray  = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        gray  = cv2.equalizeHist(gray)

        faces = CASCADE.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(60, 60),
        )

        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)

        # imshow expects BGR
        cv2.imshow("PiCam3 Faces", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
finally:
    picam2.stop()
    cv2.destroyAllWindows()
