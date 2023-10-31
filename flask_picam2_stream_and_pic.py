from flask import Flask, Response, url_for, send_file
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder, MJPEGEncoder, H264Encoder
from picamera2.outputs import FileOutput
import io
from threading import Condition
from datetime import datetime
import cv2
import os
from libcamera import controls as libcontrols


app = Flask(__name__)

PAGE = """
<html>
<head>
<title>picamera2 MJPEG streaming demo</title>
</head>
<body>
<h1>Picamera2 MJPEG Streaming Demo</h1>
<img src="{}" width="1280" height="960">
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

#main={"size": (1280, 720), "format": "RGB888"}
video_config = picam2.create_video_configuration(main={"size": (1640, 1232), "format": "RGB888"},
                                                 lores={"size": (640, 480), "format": "YUV420"},
                                                 raw={"size": (3280, 2464)})

picam2.configure(video_config)

#Try with "AeEnable": False, in set controls to see if it can be modified on the go without having to stop the camera
# picam2.set_controls({"ExposureTime": 5000000, "AnalogueGain": 8, "ColourGains": (2, 1.81)})


encoder1 = H264Encoder(10000000)
encoder2 = MJPEGEncoder(10000000)

output = StreamingOutput()
lores_output = StreamingOutput()

picam2.start_recording(encoder1, FileOutput(output))
picam2.start_recording(encoder2, FileOutput(lores_output), name="lores")

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
    return str(metadata)


@app.route('/set_controls/<int:exposure_time>')
def set_controls(exposure_time):
    # Create a dictionary with the desired controls
    controls = {
        "AwbEnable": 0,
        "AeEnable": False,
        "AeExposureMode": libcontrols.AeExposureModeEnum.Long,
        "FrameDurationLimits": (40000, exposure_time),
        "ExposureTime": exposure_time,
        "AnalogueGain": 8,
        "ColourGains": (2, 1.81)
    }

    # Set the controls on the camera
    picam2.set_controls(controls)

    # So far it needs to stop recording in order for the changes to take effect
    picam2.stop_recording()

    picam2.create_video_configuration(controls=controls)

    picam2.start_recording(encoder1, FileOutput(output))
    picam2.start_recording(encoder2, FileOutput(lores_output), name="lores")

    #with picam2.controls as ctrl:
    #    ctrl.AnalogueGain = 6.0
    #    ctrl.ExposureTime = 6000000

    # Print the controls to the console for confirmation
    print(f"Controls set to: {controls}")

    # Return the controls as a string to the browser for feedback
    return str(controls)


@app.route('/reset')
def reset():
    #
    picam2.stop_recording()

    # Not taking effect, need to have the picam2 controls set to defaults

    picam2.start_recording(encoder1, FileOutput(output))
    picam2.start_recording(encoder2, FileOutput(lores_output), name="lores")

    return "camera reseted"


if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=8000, threaded=True)
    finally:
        picam2.stop_recording()