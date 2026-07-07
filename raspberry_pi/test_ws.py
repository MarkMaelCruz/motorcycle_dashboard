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

    except Exception as e:
        print("ERROR:", e)
        break