"""
This module implements a Flask-based web server with functionalities for streaming video and sensor data.
It interfaces with a camera using picamera2, provides routes for camera control, sensor data retrieval,
and supports dynamic image processing. It's designed for use in remote monitoring or surveillance systems.
"""


import json
import re
import subprocess
import psutil
import numpy as np
from flask import Flask, Response, url_for, send_file, render_template, jsonify
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder  #JpegEncoder, MJPEGEncoder
from picamera2.outputs import FileOutput
import io
import threading
from threading import Condition, Thread, Event
from datetime import datetime
import cv2
import os
from libcamera import controls as libcontrols
import time
import sys
import socket
import struct
from werkzeug.serving import ThreadedWSGIServer
from socket import SOL_SOCKET, SO_REUSEADDR
import libcamera

from utils import WatchdogTimer, read_sensor


# Global shutdown event
shutdown_event = Event()


app = Flask(__name__)

# Connection parameters
use_domain_name = True
domain_name = 'marcofarias.com'
ip_address = '192.168.100.10'
receiver_ip = ''
VIDEO_PORT = 5555
SENSOR_DATA_PORT = 5556
HIGH_RES_PIC_PORT = 5557

# Camera rotation if needed
ROTATE_180 = True

# Global variable to control saving automatically taken pictures to disk
SAVE_TO_DISK = False

# Sleep time (in seconds) between data reads and sending
SLEEP_TIME = 30


def shutdown_server():
    """
    Initiates the shutdown process for the server and related threads.

    This function signals all threads to stop, safely stops camera recording, and shuts down the Flask server.
    """
    print("Initiating shutdown...")

    # Signal all threads to stop
    shutdown_event.set()

    # Safely stop camera recording
    try:
        picam2.stop_recording()
        print("picamera stopped")
    except Exception as e:
        print(f"Error stopping camera recording: {e}")

    # Get the current thread
    current_thread = threading.current_thread()
    print("Current thread: ", current_thread.name)

    # Define a timeout for thread joins
    join_timeout = 10

    # Wait for threads to finish, skip if it's the current thread
    if thread.is_alive() and thread != current_thread:
        print("Waiting for save_pic_every_minute thread to finish...")
        thread.join(timeout=join_timeout)
    else:
        print("save_pic_every_minute thread NOT ALIVE OR IS CURRENT THREAD...")

    if send_data_thread.is_alive() and send_data_thread != current_thread:
        print("Waiting for sensor_thread to finish...")
        send_data_thread.join(timeout=join_timeout)
    else:
        print("sensor_thread NOT ALIVE OR IS CURRENT THREAD...")

    if video_thread.is_alive() and video_thread != current_thread:
        print("Waiting for video_thread to finish...")
        video_thread.join(timeout=join_timeout)
    else:
        print("video_thread NOT ALIVE OR IS CURRENT THREAD...")

    if watchdog.is_alive() and current_thread != watchdog:
        print("Stopping watchdog...")
        watchdog.stop()
        watchdog.join(timeout=join_timeout)
        if watchdog.is_alive():
            print("Warning: watchdog did not shut down cleanly.")

    print("Threads stopped. Checking server shutdown...")

    # Shutdown the Flask server
    if server is not None and current_thread != threading.main_thread():
        print("Shutting down server...")
        server.shutdown()

    print("Shutdown complete.")


@app.route('/manual_shutdown')
def manual_shutdown():
    """
    Flask route to manually initiate server shutdown.

    This route triggers the shutdown of the server when accessed.

    Returns:
        str: A message indicating that the server is shutting down.
    """
    shutdown_server()
    return 'Server shutting down...'


@app.route('/complete_shutdown')
def complete_shutdown():
    """
    This method exits the application sending a signal of 100, which in turn tells the main run app to stop re-executing
    this program.
    """
    shutdown_server()
    sys.exit(100)
    return 'Server shutting down...'


class StreamingOutput(io.BufferedIOBase):
    """
        A custom output class for handling streaming video data from the camera.

        Attributes:
            frame (bytes): The current video frame.
            condition (threading.Condition): A condition variable for thread synchronization.

        Methods:
            write(buf): Writes the given buffer to the frame attribute.
        """

    def __init__(self):
        """
        Initializes the StreamingOutput with default values.
        """
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        """
        Writes the given buffer to the frame attribute.

        Args:
            buf (bytes): A buffer containing video frame data.
        """
        with self.condition:
            self.frame = buf
            self.condition.notify_all()


def get_raspberry_pi_model():
    try:
        with open('/proc/device-tree/model', 'r') as f:
            model = f.read()
        return model.strip()  # Remove any trailing whitespace
    except Exception as e:
        return f"Error: {e}"


def normalize_string(s):
    # Remove special characters using regular expressions
    s = re.sub(r'[^A-Za-z0-9 ]+', '', s)
    # Convert to lower case and strip whitespace
    return s.lower().strip()


pi_model = get_raspberry_pi_model()  # Assuming this is your function to get the model
print(f"Raspberry Pi Model: {pi_model}")
normalized_model = normalize_string(pi_model)

if 'raspberry pi zero 2 w rev 10' in normalized_model:
    buffer_count = 4
else:
    buffer_count = 8
print(f"Allocating {buffer_count} buffers")

picam2 = Picamera2()

full_resolution = picam2.sensor_resolution
print("Sensor resolution: ")
print(full_resolution)

# main={"size": (1280, 720), "format": "RGB888"}
video_config = picam2.create_video_configuration(main={"size": full_resolution, "format": "RGB888"},
                                                 lores={"size": (640, 480)},
                                                 encode="lores",
                                                 buffer_count=buffer_count)    # Need to decrease this to 2-3 in the raspberry pi
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

CAM_MODULE_V = 2  # Indicates whether it is the cam module 1, 2, 3...

# Assuming typical Raspberry Pi camera models
if full_resolution == (4608, 2592):
    print("Camera Module v3 detected")
    CAM_MODULE_V = 3
elif full_resolution == (3280, 2464):
    print("Camera Module v2 detected")
    CAM_MODULE_V = 2
elif full_resolution == (2592, 1944):
    print("Camera Module v1")
    CAM_MODULE_V = 1
elif full_resolution == (4056, 3040):
    print("HQ Camera")
else:
    print("Unknown Camera Model")

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
                client_socket.settimeout(30)
                client_socket.connect((receiver_ip, VIDEO_PORT))
                print("")
                print(f"Connected to video receiver at {receiver_ip}:{VIDEO_PORT}")

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

        except socket.timeout:
            continue  # Continue in the event of a timeout

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


def measure_brightness(image_input):
    """
    Method to estimate the brightness of an image
    :param image_input:
    :return:
    """
    # Check if the input is a string (path) or a BytesIO object
    if isinstance(image_input, str):  # It's a file path
        img = cv2.imread(image_input, cv2.IMREAD_COLOR)
    elif isinstance(image_input, io.BytesIO):  # It's a BytesIO object
        img_buffer = np.frombuffer(image_input.getbuffer(), dtype=np.uint8)
        img = cv2.imdecode(img_buffer, cv2.IMREAD_COLOR)
        image_input.seek(0)  # Reset buffer position
    else:
        raise ValueError("Unsupported input type")

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    _, _, v = cv2.split(hsv)
    return v.mean()  # Return the average brightness


def take_timed_picture(save_to_disk: bool = False):
    # Brightness thresholds with hysteresis buffers
    LOW_BRIGHTNESS_THRESHOLD = 40
    BUFFER_LOW = 45
    HIGH_BRIGHTNESS_THRESHOLD = 60
    BUFFER_HIGH = 55
    DAY_BRIGHTNESS_THRESHOLD = 75

    BRIGHTNESS_CHANGE_THRESHOLD = 100

    exposure_time = DEFAULT_EXPOSURE_TIME

    increasing_exposure = False
    decreasing_exposure = False

    last_brightness = None

    is_daylight_reset_done = False  # Flag to track if reset has been done during current daylight period

    while not shutdown_event.is_set():  # while True:
        any_other_failure_condition = True

        # Take the picture
        img_buffer = io.BytesIO()

        # Always capture the image to memory first
        try:
            request = picam2.capture_request()
            request.save("main", img_buffer, format='jpeg')
            request.release()
            img_buffer.seek(0)
        except Exception as e:
            print(f"Error in image capture: {e}")
            break  # Or handle the error as appropriate

        # Conditionally save the image to disk
        if save_to_disk:
            path = create_directory()
            img_name = datetime.now().strftime("%H-%M-%S.jpg")
            full_path = os.path.join(path, img_name)
            with open(full_path, 'wb') as f:
                f.write(img_buffer.getvalue())
            print(f"Image saved to disk at {full_path}")

        brightness = measure_brightness(img_buffer)
        print(f"Current brightness value: {brightness}")
        print(f"Current exposure_time: {exposure_time}")

        adjusted = False  # Flag to indicate if adjustments were made

        # Start increasing exposure_time when brightness is very low
        if brightness < LOW_BRIGHTNESS_THRESHOLD and not increasing_exposure:
            print("Start increasing exposure_time due to low brightness.")
            increasing_exposure = True
            decreasing_exposure = False
            is_daylight_reset_done = False  # Reset the flag if it's no longer daylight

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
                if not is_daylight_reset_done:
                    print("Brightness indicates daylight. Resetting to daytime settings.")
                    reset()  # Call your reset method
                    is_daylight_reset_done = True

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

        any_other_failure_condition = False

        # Send the high resolution picture
        # Initialize a flag to check if the high-res picture was sent
        high_res_pic_sent = False

        # Resolve domain name to IP address
        if use_domain_name:
            receiver_ip = socket.gethostbyname(domain_name)
        else:
            receiver_ip = ip_address

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as pic_socket:
                if shutdown_event.is_set():
                    print("shutdown_event triggered in take_timed_picture() (1)")
                    break
                pic_socket.settimeout(30)  # Set a timeout for connection
                pic_socket.connect((receiver_ip, HIGH_RES_PIC_PORT))

                print("")
                print(f"Connected to image receiver at {receiver_ip}:{HIGH_RES_PIC_PORT}")

                # Send the picture
                img_buffer.seek(0)  # Reset the buffer position to the start
                pic_data = img_buffer.read()
                print("High-resolution picture ready.")
                pic_socket.sendall(struct.pack("Q", len(pic_data)) + pic_data)
                print("High-resolution picture sent.")
                high_res_pic_sent = True

                # total_length = len(pic_data)
                # pic_socket.sendall(struct.pack("Q", total_length))
                # # Send the picture in chunks
                # chunk_size = 1024  # You can adjust this size
                # for i in range(0, total_length, chunk_size):
                #     pic_socket.sendall(pic_data[i:i + chunk_size])
                # print("High-resolution picture sent.")
                # high_res_pic_sent = True


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
        print("Sleeping for the next ", str(SLEEP_TIME), " seconds... \n")
        for _ in range(SLEEP_TIME):  # Assuming you want to sleep for 60 seconds
            time.sleep(1)
            if shutdown_event.is_set():
                print("shutdown_event triggered in save_pic_every_minute() (2)")
                break

    print("save_pic_every_minute thread is shutting down")


def get_cpu_temp():
    # For Raspberry Pi
    try:
        temp = subprocess.check_output(["vcgencmd", "measure_temp"]).decode()
        return float(temp.replace("temp=", "").replace("'C\n", ""))
    except:
        return None


def get_system_uptime():
    try:
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        now = datetime.now()
        uptime = now - boot_time
        return str(uptime)
    except Exception as e:
        print(f"Error getting system uptime: {e}")
        return None


def get_used_ram():
    ram = psutil.virtual_memory()
    return ram.used / (1024 ** 2)  # MB


def get_used_disk():
    disk = psutil.disk_usage('/')
    return disk.used / (1024 ** 3)  # GB


def send_data():
    while not shutdown_event.is_set():  # while True...

        # Resolve domain name to IP address
        if use_domain_name:
            receiver_ip = socket.gethostbyname(domain_name)
        else:
            receiver_ip = ip_address

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sensor_socket:
                sensor_socket.settimeout(30)  # Set a timeout for the connection, time in seconds
                sensor_socket.connect((receiver_ip, SENSOR_DATA_PORT))

                print("")
                print(f"Connected to data receiver at {receiver_ip}:{SENSOR_DATA_PORT}")

                while not shutdown_event.is_set():  # while True...
                    send_data_dict = read_sensor()
                    # Add additional data
                    send_data_dict['cpu_temp'] = get_cpu_temp()
                    send_data_dict['system_uptime'] = get_system_uptime()
                    send_data_dict['used_ram'] = get_used_ram()
                    send_data_dict['used_disk'] = get_used_disk()
                    send_data_dict['datetime'] = datetime.now().isoformat()

                    sensor_socket.sendall(json.dumps(send_data_dict).encode())
                    print("Sensor data sent...")
                    print(send_data_dict)
                    for _ in range(SLEEP_TIME):  # Assuming you want to sleep for X seconds
                        time.sleep(1)
                        if shutdown_event.is_set():
                            print("shutdown_event triggered in send_data() (1)")
                            break

        except TimeoutError as e:
            print(f"Sensor data connection timed out: {e}. Retrying...")
            time.sleep(5)  # Wait before retrying

        except (ConnectionRefusedError, ConnectionResetError, BrokenPipeError) as e:
            print(f"Sensor data connection lost: {e}. Retrying...")
            time.sleep(5)  # Wait before retrying

        except Exception as e:
            print(f"Unexpected error in sending sensor data: {e}")
            #time.sleep(5)  # Wait before retrying
            break

        except socket.timeout:
            continue  # Continue in the event of a timeout

        if shutdown_event.is_set():
            break

    print("send_sensor_data thread is shutting down")


if __name__ == '__main__':
    # Watchdog start
    watchdog_timeout = 60 * 3  # in seconds, adjust as needed
    watchdog = WatchdogTimer(watchdog_timeout, reset_callback=shutdown_server, shutdown_event=shutdown_event)
    watchdog.daemon = True
    watchdog.start()
    print(watchdog.name, " : watchdog thread started")

    # Start thread to send data
    send_data_thread = Thread(target=send_data)
    send_data_thread.daemon = True
    send_data_thread.start()
    print(send_data_thread.name, " : sensor_thread started")

    # Start the thread to save pictures every minute
    thread = Thread(target=take_timed_picture, args=(SAVE_TO_DISK,))
    thread.daemon = True  # This ensures the thread will be stopped when the main program finishes
    thread.start()
    print(thread.name, " : send_timed_image thread started")

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
    except Exception as e:
        print(f"Unexpected error: {e}")
    finally:
        try:
            picam2.stop_recording()
        except Exception as e:
            print(f"Error stopping camera recording during final cleanup: {e}")
        watchdog.stop()
