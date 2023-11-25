import json
import threading

from flask import Flask, Response, url_for, send_file, render_template, request, jsonify
from picamera2 import Picamera2
#from picamera2.encoders import JpegEncoder
#from picamera2.encoders import MJPEGEncoder
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput
import io
from threading import Condition, Thread, Lock, Event
from datetime import datetime
import cv2
import os
from libcamera import controls as libcontrols
import time
import sys
import socket
import struct
import requests
from werkzeug.serving import ThreadedWSGIServer
from socket import SOL_SOCKET, SO_REUSEADDR
import libcamera
import Adafruit_DHT

# Sensor setup
DHT_SENSOR = Adafruit_DHT.DHT22
DHT_PIN = 4  # GPIO pin number

# Global shutdown event
shutdown_event = Event()


app = Flask(__name__)

# Connection parameters
use_domain_name = False
domain_name = 'marcofarias.com'
ip_address = '192.168.100.10'
receiver_ip = ''
port = 5555
SENSOR_DATA_PORT = 5556
HIGH_RES_PIC_PORT = 5557


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
        while self.running and not shutdown_event.is_set():
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
        print("heartbeat updated... count: ", str(self.heartbeat_count))

    def stop(self):
        self.running = False


def reset_system():
    print("Resetting the system...")
    try:
        requests.post('http://localhost:8000/shutdown')
    except Exception as e:
        print(f"Error during shutdown: {e}")
    os.execv(sys.executable, ['python'] + sys.argv)


def shutdown_server():
    print("Initiating shutdown...")

    # Signal all threads to stop
    shutdown_event.set()

    # Stopping camera
    picam2.stop_recording()
    print("picamera stopped")

    # Get the current thread
    current_thread = threading.current_thread()
    print("Current thread: ", current_thread.name)

    # Wait for threads to finish, except for the current thread if it's the watchdog
    if thread.is_alive():
        print("Waiting for thread to finish...")
        thread.join()
    else:
        print("thread is not alive")

    if sensor_thread.is_alive():
        print("Waiting for sensor_thread to finish...")
        sensor_thread.join()
    else:
        print("sensor_thread is not alive")

    # Add similar checks and joins for other threads
    if video_thread.is_alive():
        print("Waiting for video_thread to finish...")
        video_thread.join()
    else:
        print("video_thread is not alive")

    if watchdog.is_alive() and current_thread != watchdog:
        print("Stopping watchdog...")
        watchdog.stop()
        watchdog.join()

    print("Threads stopped. Checking server shutdown...")

    # Shutdown the Flask server
    if server is not None and current_thread != threading.main_thread():
        print("Shutting down server...")
        server.shutdown()

    print("Shutdown complete.")


@app.route('/shutdown', methods=['POST'])
def shutdown():
    shutdown_server()
    return 'Server shutting down...'

@app.route('/manual_shutdown')
def manual_shutdown():
    shutdown_server()
    return 'Server shutting down...'

@app.route('/manual_reboot')
def manual_reboot():
    shutdown_server()
    os.execv(sys.executable, ['python'] + sys.argv)
    return 'Server shutting down...'

def perform_shutdown():
    print("Resetting the system...")
    shutdown_server()


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

ROTATE_180 = True
if ROTATE_180:
    video_config["transform"] = libcamera.Transform(hflip=1, vflip=1)

picam2.configure(video_config)
encoder = H264Encoder()
output = StreamingOutput()

picam2.start_recording(encoder, FileOutput(output))


def send_video_frames():
    """
    Function to send video frames continuously
    """
    global receiver_ip
    # Todo: try switching to UDP for faster data transfer and also send the pictures every 1 min alongside other data
    while not shutdown_event.is_set():  # while True...
        try:
            # Resolve domain name to IP address
            if use_domain_name:
                receiver_ip = socket.gethostbyname(domain_name)
            else:
                receiver_ip = ip_address

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
                client_socket.connect((receiver_ip, port))
                print("")
                print(f"Connected to receiver at {receiver_ip}:{port}")

                while not shutdown_event.is_set():  # while True:
                    yuv420 = picam2.capture_array("lores")
                    rgb = cv2.cvtColor(yuv420, cv2.COLOR_YUV2RGB_YV12)
                    _, buffer = cv2.imencode('.jpg', rgb)
                    frame = buffer.tobytes()
                    client_socket.sendall(struct.pack("Q", len(frame)) + frame)

                    if shutdown_event.is_set():
                        print("shutdown_event triggered in send_video_frames() (1)")
                        break

        except (BrokenPipeError, ConnectionResetError, socket.error) as e:
            print(f"Connection lost: {e}. Attempting to reconnect...")
            time.sleep(5)  # Wait before retrying

        # Check for shutdown event at a suitable place in your loop
        if shutdown_event.is_set():
            print("shutdown_event triggered in send_video_frames() (2)")
            break

    print("send_video_frames thread is shutting down")


@app.route('/')
def index():
    return render_template('index.html', stream_url=url_for('stream'))


@app.route('/sensor_data')
def sensor_data():
    data = read_sensor()
    return jsonify(data)


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


CAM_MODULE_V = 3  # Indicates whether it is the cam module 1, 2, 3...

# Constants (in microseconds)
if CAM_MODULE_V == 3:
    MAX_EXPOSURE_TIME = int(1000000 * 112)  #112 seconds in total of max exposure
elif CAM_MODULE_V == 2:
    MAX_EXPOSURE_TIME = int(1000000 * 10)
elif CAM_MODULE_V == 1:
    MAX_EXPOSURE_TIME = int(1000000 * .9)
MIN_EXPOSURE_TIME = 100000
EXPOSURE_INCREMENT = 50000
DEFAULT_EXPOSURE_TIME = 100000

# Brightness thresholds with hysteresis buffers
LOW_BRIGHTNESS_THRESHOLD = 40
BUFFER_LOW = 45
HIGH_BRIGHTNESS_THRESHOLD = 60
BUFFER_HIGH = 55
DAY_BRIGHTNESS_THRESHOLD = 75

BRIGHTNESS_CHANGE_THRESHOLD = 100


def save_pic_every_minute():
    exposure_time = DEFAULT_EXPOSURE_TIME

    increasing_exposure = False
    decreasing_exposure = False

    last_brightness = None

    while not shutdown_event.is_set():  # while True:
        any_other_failure_condition = True

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

        # Check for sudden brightness changes
        if last_brightness is not None:
            brightness_change = abs(brightness - last_brightness)
            if brightness_change > BRIGHTNESS_CHANGE_THRESHOLD:
                # Reset to auto
                reset()
                adjusted = False

        # Check for really high brightness values
        if brightness > 200:
            reset()
            adjusted = False

        # If really low exposure values, then increment exposure time twice as fast
        elif brightness < 15:
            exposure_time = min(exposure_time * 2, MAX_EXPOSURE_TIME)

        # If really high exposure, decrement exposure time twice as fast
        elif brightness > 100:
            exposure_time = max(exposure_time / 2, MIN_EXPOSURE_TIME)

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

        last_brightness = brightness  # Update the last brightness value

        print(full_path + " SAVED!")
        any_other_failure_condition = False

        # Send the high resolution picture
        # Initialize a flag to check if the high-res picture was sent
        high_res_pic_sent = False

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as pic_socket:
                if shutdown_event.is_set():
                    print("shutdown_event triggered in save_pic_every_minute() (1)")
                    break
                pic_socket.settimeout(10)  # Set a timeout for connection
                pic_socket.connect((receiver_ip, HIGH_RES_PIC_PORT))
                # Capture and send the picture
                img_buffer = io.BytesIO()
                request = picam2.capture_request()
                request.save("main", img_buffer, format='jpeg')
                img_buffer.seek(0)
                pic_data = img_buffer.read()
                request.release()

                pic_socket.sendall(struct.pack("Q", len(pic_data)) + pic_data)
                print("High-resolution picture sent.")
                high_res_pic_sent = True

        except TimeoutError as e:
            print(f"High-res picture connection timed out: {e}. Retrying...")
        except (ConnectionRefusedError, ConnectionResetError, BrokenPipeError) as e:
            print(f"High-res picture connection lost: {e}. Retrying...")
        except Exception as e:
            print(f"Unexpected error in High-res picture connection: {e}")

        # Update the heartbeat
        if high_res_pic_sent or not any_other_failure_condition:
            watchdog.update_heartbeat()

        # Sleep in smaller increments to allow for shutdown check
        sleep_time = 60
        print("Sleeping for the next ", str(sleep_time), " seconds... \n")
        for _ in range(sleep_time):  # Assuming you want to sleep for 60 seconds
            time.sleep(1)
            if shutdown_event.is_set():
                print("shutdown_event triggered in save_pic_every_minute() (2)")
                break

    print("save_pic_every_minute thread is shutting down")


def read_sensor() -> dict:
    humidity, temperature = Adafruit_DHT.read_retry(DHT_SENSOR, DHT_PIN)
    if humidity is not None and temperature is not None:
        return {"temperature": temperature, "humidity": humidity}
    else:
        return {"temperature": "N/A", "humidity": "N/A"}


def send_sensor_data():
    while not shutdown_event.is_set():  # while True...
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sensor_socket:
                sensor_socket.settimeout(30)  # Set a timeout for the connection, time in seconds
                sensor_socket.connect((receiver_ip, SENSOR_DATA_PORT))

                while not shutdown_event.is_set():  # while True...
                    sensor_data = read_sensor()
                    sensor_socket.sendall(json.dumps(sensor_data).encode())
                    print("Sensor data sent...")
                    print(sensor_data)
                    time.sleep(60)  # Adjust as needed for sensor data frequency

                    if shutdown_event.is_set():
                        print("shutdown_event triggered in send_sensor_data() (1)")
                        break

        except TimeoutError as e:
            print(f"Sensor data connection timed out: {e}. Retrying...")
            time.sleep(5)  # Wait before retrying

        except (ConnectionRefusedError, ConnectionResetError, BrokenPipeError) as e:
            print(f"Sensor data connection lost: {e}. Retrying...")
            time.sleep(5)  # Wait before retrying

        except Exception as e:
            print(f"Unexpected error in sending sensor data: {e}")
            time.sleep(5)  # Wait before retrying

    print("send_sensor_data thread is shutting down")


if __name__ == '__main__':
    # Watchdog start
    watchdog_timeout = 60 * 3  # in seconds, adjust as needed
    watchdog = WatchdogTimer(watchdog_timeout, perform_shutdown)
    watchdog.start()
    print(watchdog.name, " : watchdog thread started")

    # Start thread to send data
    sensor_thread = Thread(target=send_sensor_data)
    sensor_thread.daemon = True
    sensor_thread.start()
    print(sensor_thread.name, " : sensor_thread started")

    # Start the thread to save pictures every minute
    thread = Thread(target=save_pic_every_minute)
    thread.daemon = True  # This ensures the thread will be stopped when the main program finishes
    thread.start()
    print(thread.name, " : thread started")

    # Start thread to send video
    video_thread = Thread(target=send_video_frames)
    video_thread.daemon = True
    video_thread.start()
    print(video_thread.name, " : video_thread started")

    # Create a server instance with threaded support
    server = ThreadedWSGIServer('0.0.0.0', 8000, app)

    # Set SO_REUSEADDR option
    server.socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        print("KeyboardInterrupt received, shutting down the server")
        shutdown_server()

    finally:
        picam2.stop_recording()
        watchdog.stop()
