# Raspberry-Picamera2-Surveillance
This projects uses Flask as a webserver that lets you see a low resolution live stream (640 x 480 px) while taking higher resolution images every minute (1640 x 1232 px). It also autoadjusts exposure for night photography as well, sacrificing fps.

It utilizes Python's Picamera2 library.


Environment conditions:
----------------------
-Raspberry Pi Zero 2W / Raspberry Pi 4 (8GB).

-Raspberry Pi OS: Debian Bookworm 64 bit

-Python 3.11.2

-Picamera module v2 / v3


-------------------------
Install with:

git clone https://github.com/marcofariasmx/Raspberry-Picamera2-Surveillance.git

cd Raspberry-Picamera2-Surveillance

chmod +x install.sh

bash install.sh


