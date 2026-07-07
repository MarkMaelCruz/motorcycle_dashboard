import serial
import requests
import time
import glob
session = requests.Session()

BAUD_RATE = 115200
def find_arduino_port():

    ports = sorted(glob.glob("/dev/ttyACM*"))

    if not ports:
        raise Exception(
            "No Arduino serial device found."
        )

    print(
        f"Using serial port: {ports[0]}"
    )

    return ports[0]

BACKEND_URL = "https://motorcycle-telemetry-backend-112434217886.asia-southeast1.run.app/telemetry"

last_send_time = 0
SEND_INTERVAL = 0.05

def main():

    print("Connecting to Arduino...")
    port = find_arduino_port()

    ser = serial.Serial(
        port,
        BAUD_RATE,
        timeout=1
    )

    print("Connected.")

    while True:

        try:

            if not ser.in_waiting:
                continue

            line = ser.readline().decode(
                errors="ignore"
            ).strip()

            if not line:
                continue
            #print("RAW:", repr(line))

            if line.startswith("time"):
                continue

            parts = line.split(",")

            if len(parts) != 7:
                continue

            try:
                data = {
                    "time": float(parts[0]),
                    "speed": float(parts[1]),
                    "accel": float(parts[2]),
                    "roll": float(parts[3]),
                    "yaw": float(parts[4]),
                    "lat": float(parts[5]),
                    "lon": float(parts[6])
                }

            except ValueError:
                print("BAD LINE:", repr(line))
                continue

            global last_send_time

            current_time = time.time()

            if current_time - last_send_time < SEND_INTERVAL:
                continue

            last_send_time = current_time

            response = session.post(
                BACKEND_URL,
                json=data,
                timeout=1
            )

            #print("POST:", response.status_code)

        except Exception as e:

            print(
                "ERROR:",
                e
            )

if __name__ == "__main__":
    main()