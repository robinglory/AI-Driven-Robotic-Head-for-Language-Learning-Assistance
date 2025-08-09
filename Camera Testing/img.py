from picamera2 import Picamera2
import time
import cv2

picam2 = Picamera2()
preview_config = picam2.create_preview_configuration()
picam2.configure(preview_config)
picam2.start()

for _ in range(30):  # grab 30 frames (~1 second at 30fps)
    frame = picam2.capture_array()
    cv2.imshow("Camera Preview", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

picam2.stop()
cv2.destroyAllWindows()
