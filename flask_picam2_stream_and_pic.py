from flask import Flask, Response, url_for, send_file, render_template
from picamera2 import Picamera2
#from picamera2.encoders import JpegEncoder
#from picamera2.encoders import MJPEGEncoder
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput
import io
from threading import Condition
from datetime import datetime
import cv2
import os
from libcamera import controls as libcontrols
import time
from threading import Thread, Lock
import sys
import socket
import struct


# Todo: make the file be executed with high permissions at startup so that it can create necessary directories.

app = Flask(__name__)

# Connection parameters
receiver_ip = '192.168.100.40'  # Replace with receiver's IP address
port = 9999


class WatchdogTimer(Thread):
    def __init__(self, timeout, reset_callback):
        Thread.__init__(self)
        self.timeout = timeout
        self.reset_callback = reset_callback
        self.last_heartbeat = time.time()
        self.lock = Lock()
        self.running = True
        self.heartbeat_count = 0

    def run(self):
        while self.running:
            with self.lock:
                if time.time() - self.last_heartbeat > self.timeout:
                    print("Watchdog triggered reset")
                    self.reset_callback()
                    self.last_heartbeat = time.time()
            time.sleep(1)

    def update_heartbeat(self):
        with self.lock:
            self.last_heartbeat = time.time()
        self.heartbeat_count += 1
        print("heartbeat updated..., count: ", str(self.heartbeat_count))

    def stop(self):
        self.running = False

def reset_system():
    print("Resetting the system...")
    os.execv(sys.executable, ['python'] + sys.argv)

watchdog_timeout = 60 * 3  # in seconds, adjust as needed
watchdog = WatchdogTimer(watchdog_timeout, reset_system)
watchdog.start()

PAGE = """
<html>
<head>
<title>picamera2 MJPEG streaming demo</title>
</head>
<body>
<h1>Picamera2 MJPEG Streaming Demo</h1>
<img src="{}" width="1536" height="864">
</body>
</html>
"""


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()


picam2 = Picamera2()

full_resolution = picam2.sensor_resolution
print("Sensor resolution: ")
print(full_resolution)

# main={"size": (1280, 720), "format": "RGB888"}
video_config = picam2.create_video_configuration(main={"size": full_resolution, "format": "RGB888"},
                                                 lores={"size": (640, 480)},
                                                 encode="lores",
                                                 buffer_count=8)    # Need to decrease this to 2-3 in the raspberry pi
                                                                    # zero 2 w to avoid running out of memory when using
                                                                    # the full sensor resolution, specially on the
                                                                    # camera module 3.

initial_controls = {
    "AwbEnable": True,
    "AeEnable": True
    # "AeExposureMode": libcontrols.AeExposureModeEnum.Normal,
    #"FrameDurationLimits": (33333, 1000000)
}

picam2.set_controls(initial_controls)

print("initial controls config: \n")
print(picam2.camera_controls)

picam2.configure(video_config)

encoder = H264Encoder()

output = StreamingOutput()

picam2.start_recording(encoder, FileOutput(output))


# Function to send video frames continuously
def send_video_frames():
    while True:
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.connect((receiver_ip, port))
            print(f"Connected to receiver at {receiver_ip}:{port}")

            while True:
                yuv420 = picam2.capture_array("lores")
                rgb = cv2.cvtColor(yuv420, cv2.COLOR_YUV2RGB_YV12)
                _, buffer = cv2.imencode('.jpg', rgb)
                frame = buffer.tobytes()
                client_socket.sendall(struct.pack("Q", len(frame)) + frame)

        except (BrokenPipeError, ConnectionResetError, socket.error) as e:
            print(f"Connection lost: {e}. Attempting to reconnect in 5 seconds...")
            time.sleep(5)
        finally:
            if client_socket:
                client_socket.close()
                print(f"Disconnected from receiver at {receiver_ip}:{port}")


thread = Thread(target=send_video_frames)
thread.daemon = True
thread.start()

@app.route('/')
def index():
    return PAGE.format(url_for('stream'))


@app.route('/stream')
def stream():
    def generate():
        while True:
            yuv420 = picam2.capture_array("lores")  # Capture YUV420 frame
            rgb = cv2.cvtColor(yuv420, cv2.COLOR_YUV2RGB_YV12)  # Convert YUV to RGB
            frame_encoded = cv2.imencode('.jpg', rgb)[1].tobytes()  # Encode as JPEG

            yield (b'--FRAME\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_encoded + b'\r\n')

    return Response(generate(),
                    mimetype='multipart/x-mixed-replace; boundary=FRAME')


@app.route('/save_pic')
def save_pic():
    # Ensure the 'static' folder exists
    if not os.path.exists('static'):
        os.makedirs('static')

    request = picam2.capture_request()
    img_name = datetime.now().strftime("static/" + "%d-%m-%Y_%H-%M-%S.jpg")
    request.save("main", img_name)
    request.release()
    print(img_name + " SAVED!")

    # Return the image itself to the browser
    return send_file(img_name, mimetype='image/jpeg')


@app.route('/take_pic')
def take_pic():
    # Request a capture
    request = picam2.capture_request()

    # Capture the image to a byte array in the desired format
    img_buffer = io.BytesIO()
    request.save("main", img_buffer, format='jpeg')  # specify the format explicitly
    img_buffer.seek(0)
    request.release()

    # Return the byte array directly to the browser
    return send_file(img_buffer, mimetype='image/jpeg')


@app.route('/controls')
def show_controls():
    # Capture the metadata from the camera
    metadata = picam2.capture_metadata()

    # Print the entire metadata
    print(metadata)
    print(picam2.camera_controls)

    # Return the metadata as a string to the browser
    return str(metadata) + '\n\n\n' + str(picam2.camera_controls)


@app.route('/set_controls/<int:exposure_time>')
def set_controls(exposure_time):
    # WARNING: If a really high exposure value is passed (say 3000 up more or less) then the camera is not able to
    # go back to normal after it has been reset

    if exposure_time > 10000000:
        exposure_time = 10000000
    elif exposure_time < 10000:
        exposure_time = 10000

    # Create a dictionary with the desired controls
    controls = {
        "AwbEnable": False,
        "AeEnable": False,
        # "AeExposureMode": libcontrols.AeExposureModeEnum.Long,
        "FrameDurationLimits": (10000, exposure_time),
        "ExposureTime": exposure_time,
        "AnalogueGain": 8,
        "ColourGains": (2, 1.81)
    }

    # Set the controls on the camera
    picam2.set_controls(controls)

    # with picam2.controls as ctrl:
    #    ctrl.AnalogueGain = 6.0
    #    ctrl.ExposureTime = 6000000

    # Print the controls to the console for confirmation
    print(f"Controls set to: {controls}")

    # Return the controls as a string to the browser for feedback
    return str(controls)


@app.route('/reset')
def reset():
    # Set the controls on the camera
    picam2.set_controls(initial_controls)

    print("RESET triggered")

    return str(initial_controls)

@app.route('/activate_long_exposure_mode')
def activate_long_exposure_mode():
    # Create a dictionary with the desired controls
    controls = {
        # "AwbEnable": False,
        "AeEnable": True,
        "AeExposureMode": libcontrols.AeExposureModeEnum.Long
    }

    # Set the controls on the camera
    picam2.set_controls(controls)

    return str(controls)


@app.route('/browse/')
@app.route('/browse/<path:subpath>')
def browse(subpath=""):
    abs_path = os.path.join("static", subpath)

    if os.path.isdir(abs_path):
        items = sorted(os.listdir(abs_path))
        return render_template('browse.html', items=items, subpath=subpath)
    else:
        dir_path, current_image = os.path.split(abs_path)
        all_images = sorted([img for img in os.listdir(dir_path) if img.endswith(".jpg")])

        try:
            idx = all_images.index(current_image)
            prev_image = all_images[idx - 1] if idx > 0 else None
            next_image = all_images[idx + 1] if idx < len(all_images) - 1 else None
        except ValueError:
            prev_image = next_image = None

        return render_template('image.html', image_path=abs_path,
                               prev_image=os.path.join(dir_path, prev_image) if prev_image else None,
                               next_image=os.path.join(dir_path, next_image) if next_image else None)


def create_directory():
    dir_name = datetime.now().strftime("%d-%m-%Y")
    path = os.path.join('static', dir_name)
    if not os.path.exists(path):
        os.makedirs(path)
    return path

# Add this function to estimate the brightness of an image
def measure_brightness(image_path):
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    _, _, v = cv2.split(hsv)
    return v.mean()  # Return the average brightness

# Constants (in microseconds)
MAX_EXPOSURE_TIME = 10000000
MIN_EXPOSURE_TIME = 100000
EXPOSURE_INCREMENT = 50000
DEFAULT_EXPOSURE_TIME = 100000

# Brightness thresholds with hysteresis buffers
LOW_BRIGHTNESS_THRESHOLD = 40
BUFFER_LOW = 45
HIGH_BRIGHTNESS_THRESHOLD = 60
BUFFER_HIGH = 55
DAY_BRIGHTNESS_THRESHOLD = 75

def save_pic_every_minute():
    exposure_time = DEFAULT_EXPOSURE_TIME

    increasing_exposure = False
    decreasing_exposure = False

    while True:
        path = create_directory()
        img_name = datetime.now().strftime("%H-%M-%S.jpg")
        full_path = os.path.join(path, img_name)

        request = picam2.capture_request()
        request.save("main", full_path)
        request.release()

        brightness = measure_brightness(full_path)
        print(f"Current brightness value: {brightness}")
        print(f"Current exposure_time: {exposure_time}")

        adjusted = False  # Flag to indicate if adjustments were made

        # Start increasing exposure_time when brightness is very low
        if brightness < LOW_BRIGHTNESS_THRESHOLD and not increasing_exposure:
            print("Start increasing exposure_time due to low brightness.")
            increasing_exposure = True
            decreasing_exposure = False

        # Stop increasing exposure_time when brightness surpasses buffer high
        if brightness > BUFFER_HIGH:
            increasing_exposure = False

        # Start decreasing exposure_time when brightness is high
        if brightness > HIGH_BRIGHTNESS_THRESHOLD and not decreasing_exposure:
            print("Start decreasing exposure_time due to sufficient brightness.")
            increasing_exposure = False
            decreasing_exposure = True

        # Stop decreasing exposure_time when brightness falls below buffer low
        if brightness < BUFFER_LOW:
            decreasing_exposure = False

        # Adjust the exposure_time
        if increasing_exposure:
            if exposure_time < MAX_EXPOSURE_TIME:
                exposure_time += EXPOSURE_INCREMENT
                adjusted = True
                print(f"Increased exposure_time to: {exposure_time}")

        elif decreasing_exposure:
            if exposure_time > MIN_EXPOSURE_TIME:
                exposure_time -= EXPOSURE_INCREMENT
                adjusted = True
                print(f"Decreased exposure_time to: {exposure_time}")

        # Reset to daytime settings
        if brightness > DAY_BRIGHTNESS_THRESHOLD:
            if exposure_time <= MIN_EXPOSURE_TIME:
                print("Brightness indicates daylight. Resetting to daytime settings.")
                #Todo: FIX this so that it only gets reset once
                reset()

        if adjusted:
            # Adjust the camera controls
            controls = {
                "AwbEnable": False,
                "AeEnable": False,
                "FrameDurationLimits": (MIN_EXPOSURE_TIME, exposure_time),
                "ExposureTime": exposure_time,
                "AnalogueGain": 8,
                "ColourGains": (2, 1.81)
            }
            picam2.set_controls(controls)

        print(full_path + " SAVED!")

        watchdog.update_heartbeat()

        time.sleep(60)  # Sleep for 60 seconds


if __name__ == '__main__':
    # Start the thread to save pictures every minute
    thread = Thread(target=save_pic_every_minute)
    thread.daemon = True  # This ensures the thread will be stopped when the main program finishes
    thread.start()

    try:
        app.run(host='0.0.0.0', port=8000, threaded=True)
    finally:
        picam2.stop_recording()
        watchdog.stop()
