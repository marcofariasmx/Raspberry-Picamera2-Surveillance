import sys
from threading import Thread, Lock, Event
import time
import Adafruit_DHT

# Sensor setup
DHT_SENSOR = Adafruit_DHT.DHT22
DHT_PIN = 4  # GPIO pin number


def read_sensor() -> dict:
    humidity, temperature = Adafruit_DHT.read_retry(DHT_SENSOR, DHT_PIN)
    if humidity is not None and temperature is not None:
        return {"temperature": temperature, "humidity": humidity}
    else:
        return {"temperature": "N/A", "humidity": "N/A"}


class WatchdogTimer(Thread):
    def __init__(self, timeout, reset_callback, shutdown_event: Event):
        Thread.__init__(self)
        self.timeout = timeout
        self.reset_callback = reset_callback
        self.last_heartbeat = time.time()
        self.lock = Lock()
        self.running = True
        self.heartbeat_count = 0
        self.shutdown_event = shutdown_event

    def run(self):
        while self.running and not self.shutdown_event.is_set():
            with self.lock:
                if time.time() - self.last_heartbeat > self.timeout:
                    print("Watchdog triggered reset")
                    # Start reset_callback in a separate thread
                    Thread(target=self.execute_reset_callback, daemon=True).start()
                    # Immediately start final_run in another thread
                    Thread(target=self.final_run, daemon=True).start()
            time.sleep(1)

    def execute_reset_callback(self):
        # Execute method in charge of reset
        self.reset_callback()

    def final_run(self):
        print("Final run watchdog activated")
        while self.running:
            with self.lock:
                if time.time() - self.last_heartbeat > self.timeout * 2:
                    print("Something failed shutting down the system, exiting the hard way...")
                    sys.exit(2)

    def update_heartbeat(self):
        with self.lock:
            self.last_heartbeat = time.time()
        self.heartbeat_count += 1
        print("heartbeat updated... count: ", str(self.heartbeat_count))
        # # Only execute this for testing purposes
        # if self.heartbeat_count == 3:
        #     print("fake watchdog stop activated")
        #     print("Watchdog triggered reset")
        #     self.reset_callback()

    def stop(self):
        self.running = False

