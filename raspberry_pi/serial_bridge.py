import serial
import requests

SERIAL_PORT = "/dev/ttyACM0"
BAUD_RATE = 115200

BACKEND_URL = "http://localhost:8080/telemetry"

def main():

    print("Connecting to Arduino...")

    ser = serial.Serial(
        SERIAL_PORT,
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
            print("RAW:", repr(line))

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

            response = requests.post(
                BACKEND_URL,
                json=data,
                timeout=1
            )

            print("POST:", response.status_code)

        except Exception as e:

            print(
                "ERROR:",
                e
            )

if __name__ == "__main__":
    main()