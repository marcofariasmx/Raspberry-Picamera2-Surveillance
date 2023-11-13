from flask import Flask, Response
import socket
import threading
import cv2
import numpy as np
import struct

app = Flask(__name__)

# Server setup for receiving frames
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
host_ip = '0.0.0.0'  # Listen on all available IPs
port = 9999
server_socket.bind((host_ip, port))
server_socket.listen()
print("Listening for incoming connections on port", port)

# Global variables
data = b""
frame = None
lock = threading.Lock()

def handle_client_connection(client_socket):
    global data, frame
    payload_size = struct.calcsize("Q")
    while True:
        while len(data) < payload_size:
            packet = client_socket.recv(4*1024)  # 4K buffer size
            if not packet: break
            data += packet

        packed_msg_size = data[:payload_size]
        data = data[payload_size:]
        msg_size = struct.unpack("Q", packed_msg_size)[0]

        while len(data) < msg_size:
            data += client_socket.recv(4*1024)

        frame_data = data[:msg_size]
        data = data[msg_size:]
        with lock:
            frame = np.frombuffer(frame_data, dtype=np.uint8)
            frame = cv2.imdecode(frame, cv2.IMREAD_COLOR)

@app.route('/')
def index():
    return """
    <html>
    <head>
    <title>Video Streaming</title>
    </head>
    <body>
    <h1>Video Stream</h1>
    <img src="/video_feed">
    </body>
    </html>
    """

def generate_frames():
    global frame, lock
    while True:
        with lock:
            if frame is not None:
                ret, buffer = cv2.imencode('.jpg', frame)
                if ret:
                    frame_encoded = buffer.tobytes()
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_encoded + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

def listen_for_connections():
    while True:
        client_socket, addr = server_socket.accept()
        print('Connection from:', addr)
        client_thread = threading.Thread(target=handle_client_connection, args=(client_socket,))
        client_thread.start()

if __name__ == '__main__':
    listen_thread = threading.Thread(target=listen_for_connections)
    listen_thread.start()
    app.run(host='0.0.0.0', port=5000)
