import csv
from flask import Flask, Response, url_for, render_template
import os
import datetime
import threading
import socket
import cv2
import numpy as np
import struct
import json


class SingleItemQueue:
    def __init__(self):
        self.item = None
        self.lock = threading.Lock()

    def put(self, item):
        with self.lock:
            self.item = item

    def get(self):
        with self.lock:
            return self.item

    def is_empty(self):
        return self.item is None


app = Flask(__name__)

VIDEO_STREAM_PORT = 5555
DATA_PORT = 5556
HIGH_RES_PIC_PORT = 5557

# Global variables
frame_queue = SingleItemQueue()
received_data = {}
lock = threading.Lock()

# Global dictionary to hold queues for each video stream
video_stream_queues = {}
#selected_cam = list(video_stream_queues)[0]
selected_cam = 'rancho_cam'


# Function to get or create a queue for a specific video stream
def get_video_stream_queue(stream_id):
    global video_stream_queues
    if stream_id not in video_stream_queues:
        video_stream_queues[stream_id] = SingleItemQueue()
    return video_stream_queues[stream_id]


# Directory to save high-resolution images
HIGH_RES_IMAGES_DIR = os.path.join(app.static_folder, 'high_res_images')
if not os.path.exists(HIGH_RES_IMAGES_DIR):
    os.makedirs(HIGH_RES_IMAGES_DIR)


def handle_video_stream(client_socket):
    try:
        payload_size = struct.calcsize("Q")
        data = b""
        while True:
            # Receive the size of the sender's ID
            while len(data) < payload_size:
                packet = client_socket.recv(4 * 1024)
                if not packet: return
                data += packet

            # Extract the size of the sender's ID
            packed_id_size = data[:payload_size]
            data = data[payload_size:]
            id_size = struct.unpack("Q", packed_id_size)[0]

            # Receive the sender's ID
            while len(data) < id_size:
                data += client_socket.recv(4 * 1024)

            # Extract the sender's ID
            sender_id = data[:id_size].decode()
            data = data[id_size:]

            # Receive the size of the image
            while len(data) < payload_size:
                data += client_socket.recv(4 * 1024)

            # Extract the size of the image
            packed_img_size = data[:payload_size]
            data = data[payload_size:]
            img_size = struct.unpack("Q", packed_img_size)[0]

            # Receive the image
            while len(data) < img_size:
                data += client_socket.recv(4 * 1024)

            # Extract the image
            frame_data = data[:img_size]
            data = data[img_size:]

            # Process and put the frame in the appropriate queue
            with lock:
                frame = np.frombuffer(frame_data, dtype=np.uint8)
                frame = cv2.imdecode(frame, cv2.IMREAD_COLOR)

                if frame is not None:
                    # Check if a queue exists for this sender, if not, create one
                    if sender_id not in video_stream_queues:
                        video_stream_queues[sender_id] = SingleItemQueue()

                    video_stream_queues[sender_id].put(frame)

    except Exception as e:
        print(f"Video stream connection lost: {e}")
    finally:
        client_socket.close()


def save_received_data_to_csv(data, sender_id):
    base_directory = "received_data"
    sender_directory = os.path.join(base_directory, sender_id)
    os.makedirs(sender_directory, exist_ok=True)  # Create the directory if it doesn't exist

    # Path for the CSV file specific to the sender
    received_data_file = os.path.join(sender_directory, "received_data.csv")

    file_exists = os.path.isfile(received_data_file)
    with open(received_data_file, mode='a', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=data.keys())

        if not file_exists:
            writer.writeheader()  # Write the header only once

        writer.writerow(data)
        print(f"Received data from {sender_id} appended to CSV file.")


def handle_received_data(client_socket):
    global received_data
    try:
        while True:
            data = client_socket.recv(1024).decode()
            if not data: break
            received_data = json.loads(data)

            # Extract the sender's identifier
            sender_id = received_data.pop('sender_id', 'Unknown')

            # Save data to CSV
            save_received_data_to_csv(received_data, sender_id)

            temperature = received_data.get('temperature', 'N/A')
            humidity = received_data.get('humidity', 'N/A')

            temperature_str = "{:.2f}°C".format(temperature) if isinstance(temperature, (int, float)) else 'N/A'
            humidity_str = "{:.2f}%".format(humidity) if isinstance(humidity, (int, float)) else 'N/A'

            print(f"Data received from {sender_id}:")
            print("Temperature: {}, Humidity: {}".format(temperature_str, humidity_str))
            print("ALL DATA:")
            print(received_data)
    except Exception as e:
        print(f"Sensor data connection lost: {e}")
    finally:
        client_socket.close()


def handle_high_res_picture(client_socket):
    try:
        payload_size = struct.calcsize("Q")
        data = b""
        while True:
            # First, receive the size of the sender's ID
            while len(data) < payload_size:
                packet = client_socket.recv(4 * 1024)
                if not packet: return
                data += packet

            # Extract the size of the sender's ID
            packed_id_size = data[:payload_size]
            data = data[payload_size:]
            id_size = struct.unpack("Q", packed_id_size)[0]

            # Now, receive the sender's ID
            while len(data) < id_size:
                data += client_socket.recv(4 * 1024)

            # Extract the sender's ID
            sender_id = data[:id_size].decode()
            data = data[id_size:]

            print(f"Received high-resolution image from sender: {sender_id}")

            # Next, receive the size of the image
            while len(data) < payload_size:
                data += client_socket.recv(4 * 1024)

            # Extract the size of the image
            packed_msg_size = data[:payload_size]
            data = data[payload_size:]
            msg_size = struct.unpack("Q", packed_msg_size)[0]

            # Now, receive the image
            while len(data) < msg_size:
                data += client_socket.recv(4 * 1024)

            # Extract the image
            frame_data = data[:msg_size]
            data = data[msg_size:]

            # Process and save the image
            image = np.frombuffer(frame_data, dtype=np.uint8)
            image = cv2.imdecode(image, cv2.IMREAD_COLOR)

            # Current date and time
            current_date = datetime.datetime.now().strftime("%Y-%m-%d")
            current_time = datetime.datetime.now().strftime("%H-%M-%S")

            # Create directory path for current date and sender ID
            date_directory = os.path.join(HIGH_RES_IMAGES_DIR, sender_id, current_date)

            # Make sure the directory exists
            os.makedirs(date_directory, exist_ok=True)

            # Define the full path for the image
            image_path = os.path.join(date_directory, f'{current_time}.jpg')

            # Save the image
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


def get_latest_high_res_image():
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
    base_directory = os.path.join('high_res_images')
    full_base_path = os.path.join(app.static_folder, base_directory)

    if os.path.exists(full_base_path):
        # List and sort subdirectories alphabetically
        subdirectories = sorted([d for d in os.listdir(full_base_path) if os.path.isdir(os.path.join(full_base_path, d))])
        if subdirectories:
            # Select the first subdirectory alphabetically
            #selected_subdirectory = subdirectories[0]
            selected_subdirectory = selected_cam
            date_directory = os.path.join(selected_subdirectory, current_date)
            full_path = os.path.join(app.static_folder, base_directory, date_directory)

            if os.path.exists(full_path):
                # List files in the date directory
                files = sorted([f for f in os.listdir(full_path) if os.path.isfile(os.path.join(full_path, f))], key=lambda x: os.path.getmtime(os.path.join(full_path, x)), reverse=True)
                if files:
                    # Construct the relative path to the file
                    relative_path = os.path.join(base_directory, date_directory, files[0]).replace('\\', '/')

                    return relative_path

    #return os.path.join(app.static_folder, 'no-image-available.jpg').replace('\\', '/')
    return 'no-image-available.jpg'


@app.route('/latest_image_url')
def latest_image_url():
    latest_image = get_latest_high_res_image()  # This function returns the latest image's relative path
    if latest_image:
        return url_for('static', filename=latest_image)
    else:
        return ''  # Return an empty string or a default image path if no image is found


@app.route('/')
def index():
    latest_image = get_latest_high_res_image()
    stream_url = url_for('video_feed')
    # Use global sensor data
    global received_data
    return render_template('receiver_index.html', stream_url=stream_url, latest_image=latest_image, sensor_data=received_data)


def generate_frames_for_stream(stream_id):
    while True:
        stream_queue = video_stream_queues.get(stream_id)
        if stream_queue and not stream_queue.is_empty():
            frame = stream_queue.get()
            ret, buffer = cv2.imencode('.jpg', frame)
            if ret:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')


@app.route('/video_feed')
def video_feed():
    # Fixme: Hardcoded for now
    stream_id = selected_cam
    return Response(generate_frames_for_stream(stream_id), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/sensor_data')
def get_sensor_data():
    # Todo: handle separation of received data to show for each camera
    global received_data
    return json.dumps(received_data)


if __name__ == '__main__':
    # Start threads for handling connections
    threading.Thread(target=listen_for_connections, args=(VIDEO_STREAM_PORT, handle_video_stream)).start()
    threading.Thread(target=listen_for_connections, args=(DATA_PORT, handle_received_data)).start()
    threading.Thread(target=listen_for_connections, args=(HIGH_RES_PIC_PORT, handle_high_res_picture)).start()

    # IF on debug mode, things get messy with threads and they stop working properly.
    app.run(host='0.0.0.0', port=5000, threaded=True)
