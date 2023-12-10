# sender_settings_template.py

# Connection parameters
use_domain_name = True  # Set to False to use IP address instead
domain_name = 'example.com'  # Domain name, change as needed
ip_address = '192.168.x.x'  # IP address, change as needed
receiver_ip = ''  # Receiver IP address, set if known
VIDEO_PORT = 5555  # Port for video transmission
DATA_PORT = 5556  # Port for data transmission
HIGH_RES_PIC_PORT = 5557  # Port for high-resolution pictures

# Camera rotation if needed
ROTATE_180 = False  # Set to True if camera rotation is needed

# Global variable to control saving automatically taken pictures to disk
SAVE_TO_DISK = False  # Set to True to save pictures to disk

# Sleep time (in seconds) between data reads and sending
SLEEP_TIME = 30  # Adjust sleep time as needed
