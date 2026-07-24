from websocket import create_connection

print("Connecting...")

ws = create_connection(
    "ws://127.0.0.1:8765"
)

print("Connected!")

while True:
    try:
        msg = ws.recv()
        print(msg)

    except Exception as e:  # noqa: BLE001 — test script, broad catch is fine here
        print("ERROR:", e)
        break