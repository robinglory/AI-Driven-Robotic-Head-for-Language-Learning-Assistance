from picamera2 import Picamera2, Preview
import cv2

picam2 = Picamera2()
config = picam2.create_preview_configuration(main={"size": (1280, 720)})
picam2.configure(config)
picam2.start()

while True:
    frame = picam2.capture_array()  # numpy array (RGB)
    # Example: simple grayscale conversion for later face detection
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    cv2.imshow("PiCam3 Live", gray)  # or use 'frame' for color
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

picam2.stop()
cv2.destroyAllWindows()
