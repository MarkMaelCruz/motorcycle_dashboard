import asyncio
import json

import serial
from websockets.asyncio.server import serve

SERIAL_PORT = "/dev/ttyACM0"
BAUD_RATE = 115200

clients = set()

async def websocket_handler(websocket):
    print("Client connected")

    clients.add(websocket)

    try:
        await websocket.wait_closed()

    finally:
        clients.discard(websocket)
        print("Client disconnected")

async def serial_reader():

    ser = serial.Serial(
        SERIAL_PORT,
        BAUD_RATE,
        timeout=1
    )

    print("Connected to Arduino")

    while True:

        try:

            if ser.in_waiting:

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

                data = {
                    "time": float(parts[0]),
                    "speed": float(parts[1]),
                    "accel": float(parts[2]),
                    "roll": float(parts[3]),
                    "yaw": float(parts[4]),
                    "lat": float(parts[5]),
                    "lon": float(parts[6])
                }

                message = json.dumps(data)

                if clients:

                    await asyncio.gather(
                        *[
                            client.send(message)
                            for client in clients.copy()
                        ],
                        return_exceptions=True
                    )

            await asyncio.sleep(0.001)

        except Exception as e:  # noqa: BLE001 — intentional: keep websocket loop alive on serial errors
            print("SERIAL ERROR:", e)

async def main():

    print("Starting WebSocket server...")

    asyncio.create_task(
        serial_reader()
    )

    async with serve(
        websocket_handler,
        "0.0.0.0",
        8765
    ):

        print("WebSocket running")
        print("Port: 8765")

        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())