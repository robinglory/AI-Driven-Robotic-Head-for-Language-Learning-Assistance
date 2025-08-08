from picamera2 import Picamera2
from datetime import datetime
import time

# Initialize camera
picam2 = Picamera2()

# Configure preview
camera_config = picam2.create_still_configuration()
picam2.configure(camera_config)

# Start camera
picam2.start()
time.sleep(2)  # Give the camera time to adjust

# Create filename with timestamp
filename = f"test_image_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"

# Capture image
picam2.capture_file(filename)

print(f"Image saved as {filename}")
