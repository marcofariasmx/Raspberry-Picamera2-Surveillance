import json
import time
from flask import Flask, Response, url_for, render_template
import socket
import threading
import cv2
import numpy as np
import struct
import os

app = Flask(__name__)

VIDEO_STREAM_PORT = 5555
SENSOR_DATA_PORT = 5556
HIGH_RES_PIC_PORT = 5557

# Global variables
frame = None
sensor_data = {}
lock = threading.Lock()

# Directory to save high-resolution images
HIGH_RES_IMAGES_DIR = "high_res_images"
if not os.path.exists(HIGH_RES_IMAGES_DIR):
    os.makedirs(HIGH_RES_IMAGES_DIR)

def handle_video_stream(client_socket):
    global frame
    try:
        payload_size = struct.calcsize("Q")
        data = b""
        while True:
            while len(data) < payload_size:
                packet = client_socket.recv(4 * 1024)
                if not packet: return
                data += packet

            packed_msg_size = data[:payload_size]
            data = data[payload_size:]
            msg_size = struct.unpack("Q", packed_msg_size)[0]

            while len(data) < msg_size:
                data += client_socket.recv(4 * 1024)

            frame_data = data[:msg_size]
            data = data[msg_size:]

            with lock:
                frame = np.frombuffer(frame_data, dtype=np.uint8)
                frame = cv2.imdecode(frame, cv2.IMREAD_COLOR)
    except Exception as e:
        print(f"Video stream connection lost: {e}")
    finally:
        client_socket.close()

def handle_sensor_data(client_socket):
    global sensor_data
    try:
        while True:
            data = client_socket.recv(1024).decode()
            if not data: break
            sensor_data = json.loads(data)
            print("Temperature: {}°C, Humidity: {}%".format(sensor_data.get('temperature', 'N/A'),
                                                           sensor_data.get('humidity', 'N/A')))
    except Exception as e:
        print(f"Sensor data connection lost: {e}")
    finally:
        client_socket.close()

def handle_high_res_picture(client_socket):
    try:
        payload_size = struct.calcsize("Q")
        data = b""
        while True:
            while len(data) < payload_size:
                packet = client_socket.recv(4 * 1024)
                if not packet: return
                data += packet

            packed_msg_size = data[:payload_size]
            data = data[payload_size:]
            msg_size = struct.unpack("Q", packed_msg_size)[0]

            while len(data) < msg_size:
                data += client_socket.recv(4 * 1024)

            frame_data = data[:msg_size]
            data = data[msg_size:]

            image = np.frombuffer(frame_data, dtype=np.uint8)
            image = cv2.imdecode(image, cv2.IMREAD_COLOR)
            image_path = os.path.join(HIGH_RES_IMAGES_DIR, 'high_res_image_{}.jpg'.format(threading.get_ident()))
            cv2.imwrite(image_path, image)
            print("Saved high-resolution image:", image_path)
    except Exception as e:
        print(f"High-res picture connection lost: {e}")
    finally:
        client_socket.close()

def listen_for_connections(port, handler):
    while True:
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(('0.0.0.0', port))
            server_socket.listen()
            print(f"Listening on port {port}")

            while True:
                client_socket, addr = server_socket.accept()
                print(f"Connection from: {addr}")
                client_thread = threading.Thread(target=handler, args=(client_socket,))
                client_thread.start()
        except Exception as e:
            print(f"Error setting up server on port {port}: {e}")
            server_socket.close()
            print(f"Retrying to listen on port {port}...")
            continue

@app.route('/')
def index():
    # Cache-busting by appending a timestamp
    stream_url = url_for('video_feed') + '?nocache=' + str(time.time())
    return render_template('receiver_index.html', stream_url=stream_url)

def generate_frames():
    global frame, lock
    frame_count = 0
    start_time = time.time()

    while True:
        with lock:
            if frame is not None:
                ret, buffer = cv2.imencode('.jpg', frame)
                if ret:
                    frame_encoded = buffer.tobytes()
                    frame_count += 1
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_encoded + b'\r\n')

                    # Check time elapsed and calculate FPS
                    if (time.time() - start_time) > 1:
                        fps = frame_count / (time.time() - start_time)
                        print(f"FPS: {fps:.2f}")
                        frame_count = 0
                        start_time = time.time()

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


if __name__ == '__main__':
    # Start threads for handling connections
    threading.Thread(target=listen_for_connections, args=(VIDEO_STREAM_PORT, handle_video_stream)).start()
    threading.Thread(target=listen_for_connections, args=(SENSOR_DATA_PORT, handle_sensor_data)).start()
    threading.Thread(target=listen_for_connections, args=(HIGH_RES_PIC_PORT, handle_high_res_picture)).start()

    app.run(host='0.0.0.0', port=5000, threaded=True)
