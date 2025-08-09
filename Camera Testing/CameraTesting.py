from picamera2 import Picamera2, Preview
import time

picam2 = Picamera2()

# Configure camera
config = picam2.create_still_configuration()
picam2.configure(config)

# Take picture
picam2.start()
time.sleep(2)  # Camera warm-up time
picam2.capture_file("image.jpg")
print("Picture saved as image.jpg")

# For video recording
video_config = picam2.create_video_configuration()
picam2.configure(video_config)
picam2.start_recording("video.h264")
time.sleep(5)  # Record for 5 seconds
picam2.stop_recording()
print("Video saved as video.h264")

picam2.close()