import serial
import requests
import time
import glob

SERIAL_PORT_PATTERN = "/dev/ttyACM*"
BAUD_RATE = 115200

BACKEND_URL = "https://motorcycle-telemetry-backend-112434217886.asia-southeast1.run.app/telemetry"

SEND_INTERVAL = 0.05  # 50 ms = 20 Hz

last_send_time = 0

session = requests.Session()


def find_arduino_port():

    ports = sorted(
        glob.glob(SERIAL_PORT_PATTERN)
    )

    if not ports:
        raise Exception(
            "No Arduino serial device found."
        )

    print(
        f"Using serial port: {ports[0]}"
    )

    return ports[0]


def main():

    global last_send_time

    while True:

        ser = None

        try:

            print(
                "Searching for Arduino..."
            )

            port = find_arduino_port()

            print(
                f"Connecting to {port}"
            )

            ser = serial.Serial(
                port,
                BAUD_RATE,
                timeout=1
            )

            print("Connected.")

            while True:

                if not ser.in_waiting:
                    time.sleep(0.001)
                    continue

                line = ser.readline().decode(
                    errors="ignore"
                ).strip()

                if not line:
                    continue

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
                    continue

                current_time = time.time()

                if (
                    current_time - last_send_time
                    < SEND_INTERVAL
                ):
                    continue

                last_send_time = current_time

                session.post(
                    BACKEND_URL,
                    json=data,
                    timeout=1
                )

        except Exception as e:

            print(
                f"CONNECTION LOST: {e}"
            )

            if ser is not None:

                try:
                    ser.close()
                except:
                    pass

            print(
                "Retrying in 3 seconds..."
            )

            time.sleep(3)


if __name__ == "__main__":
    main()