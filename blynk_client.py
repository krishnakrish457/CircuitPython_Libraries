import wifi
import socketpool
import time
import struct

LOGO = """
        ___  __          __
       / _ )/ /_ _____  / /__
      / _  / / // / _ \\/  '_/
     /____/_/\\_, /_//_/_/\\_\\
            /___/ for CircuitPython
"""

class BlynkError(Exception):
    pass

class Blynk:
    MSG_RSP = 0
    MSG_LOGIN = 2
    MSG_PING = 6
    MSG_HW = 20
    MSG_HW_SYNC = 16

    STATUS_OK = 200
    STATUS_INVALID_TOKEN = 9

    def __init__(self, token, server="18.201.3.122", port=8080, heartbeat=10):
        self.token = token
        self.server = server
        self.port = port
        self.heartbeat = heartbeat
        self.last_rcv_time = time.monotonic()
        self.last_ping_time = time.monotonic()
        self.pool = socketpool.SocketPool(wifi.radio)
        self.sock = None
        self.msg_id = 1
        self.connected = False
        self.virtual_pin_callbacks = {}

        print(LOGO)

    def connect_wifi(self, ssid, password):
        """Connects to Wi-Fi."""
        print(f"Connecting to Wi-Fi SSID: {ssid}...")
        wifi.radio.connect(ssid, password)
        print(f"Connected to Wi-Fi. IP: {wifi.radio.ipv4_address}")

    def connect(self):
        """Connects to the Blynk server."""
        print(f"Connecting to Blynk server {self.server}:{self.port}...")
        try:
            addr_info = self.pool.getaddrinfo(self.server, self.port)
            addr = addr_info[0][-1]
            self.sock = self.pool.socket()
            self.sock.connect(addr)
            self.sock.settimeout(10)
            print("Socket connected.")

            # Authenticate with the server
            self._send(self._pack_msg(self.MSG_LOGIN, self.token))
            response = self._read_response()
            if response and response[2] == self.STATUS_OK:
                print("Blynk connected and authenticated!")
                self.connected = True
            else:
                raise BlynkError("Invalid response from Blynk server.")
        except Exception as e:
            print(f"Connection error: {e}")
            raise BlynkError("Failed to connect to Blynk server.")

    def _pack_msg(self, msg_type, *args):
        """Pack a message for Blynk protocol."""
        data = "\0".join(str(arg) for arg in args).encode("utf-8")
        return struct.pack("!BHH", msg_type, self._get_msg_id(), len(data)) + data

    def _get_msg_id(self):
        """Generate a new message ID."""
        self.msg_id += 1
        if self.msg_id > 0xFFFF:
            self.msg_id = 1
        return self.msg_id

    def _send(self, msg):
        """Send a message to the server."""
        self.sock.send(msg)

    def _read_response(self):
        """Read and parse a server response."""
        try:
            buf = bytearray(1024)
            bytes_received = self.sock.recv_into(buf)
            if bytes_received > 0:
                return struct.unpack("!BHH", buf[:5]) + (buf[5:5 + struct.unpack("!H", buf[3:5])[0]],)
            else:
                raise BlynkError("No response from server.")
        except Exception as e:
            print(f"Error reading response: {e}")
            return None

    def virtual_write(self, pin, value):
        """Send data to a virtual pin."""
        if not self.connected:
            raise BlynkError("Not connected to server.")
        self._send(self._pack_msg(self.MSG_HW, "vw", pin, value))

    def run(self):
        """Keep the connection alive and process incoming data."""
        if not self.connected:
            self.connect()
        try:
            self._handle_heartbeat()
            self._process_incoming()
        except Exception as e:
            print(f"Run error: {e}")
            self.connected = False

    def _handle_heartbeat(self):
        """Send a heartbeat ping to the server."""
        now = time.monotonic()
        if now - self.last_ping_time > self.heartbeat:
            self._send(self._pack_msg(self.MSG_PING))
            self.last_ping_time = now

    def _process_incoming(self):
        """Process incoming data from the server."""
        self.sock.settimeout(0.1)
        try:
            buf = bytearray(1024)
            bytes_received = self.sock.recv_into(buf)
            if bytes_received > 0:
                msg_type, msg_id, length = struct.unpack("!BHH", buf[:5])
                payload = buf[5:5 + length]
                #print(f"Received message type {msg_type} with payload: {payload}")

                self._process_message(payload)
                self.last_rcv_time = time.monotonic()
        except Exception:
            pass


    def _process_message(self, data):
        """Parse and handle incoming Blynk messages."""
        try:
            if len(data) < 5:
                print("Incomplete header received.")
                return

            cmd, msg_id, length = struct.unpack("!BHH", data[:5])

            if msg_id == 0:
                print("Invalid message ID, disconnecting...")
                self.connected = False
                return

            self.last_rcv_time = time.monotonic()
            payload = data[5:5 + length].decode("utf-8").split("\0")

            if cmd == self.MSG_RSP:
                if msg_id == 1:  # Authentication response
                    if length == self.STATUS_OK:
                        self.connected = True
                        print("Blynk authentication successful!")
                    else:
                        print("Invalid Blynk auth token!")
                        self.connected = False
                return

            elif cmd == self.MSG_PING:
                self._send(self._pack_msg(self.MSG_RSP, self.STATUS_OK, msg_id))
                return

            elif cmd == self.MSG_HW or cmd == self.MSG_HW_SYNC:
                if len(payload) > 1 and payload[0] == "vw":
                    pin = payload[1]
                    values = payload[2:]  # Multiple values support
                    self._handle_virtual_write(pin, values)
                elif len(payload) > 1 and payload[0] == "vr":
                    print(f"Read request for V{payload[1]}")
                return

            print(f"Unexpected command received: {cmd}")

        except Exception as e:
            print(f"Error processing message: {e}")



    def register_virtual_pin(self, pin, callback):
        """Register a callback for a virtual pin."""
        self.virtual_pin_callbacks[pin] = callback
        print(f"Callback registered for virtual pin {pin}")

    def _handle_virtual_write(self, pin, *values):
        """Invoke the callback for a virtual pin with multiple values."""
        if pin in self.virtual_pin_callbacks:
            self.virtual_pin_callbacks[pin](values)  # Pass multiple values as a tuple
        else:
            print(f"No callback/function registered for virtual pin {pin}. Values: {values}")

# # Example usage
# if __name__ == "__main__":
#     WIFI_SSID = "Hali WiFi"
#     WIFI_PASSWORD = "sitcart49dowdalum81"
#     BLYNK_TOKEN = "yBV3AKtpZM9WtgvgR6LzidMEhiqHt7nL"
# 
#     blynk = Blynk(BLYNK_TOKEN)
# 
# #     def handle_v1(value):
# #         print(f"Virtual Pin V1 received value: {value}")
# 
#     try:
#         # Connect to Wi-Fi
#         blynk.connect_wifi(WIFI_SSID, WIFI_PASSWORD)
# 
#         # Connect to Blynk server
#         blynk.connect()
# 
#         #blynk.register_virtual_pin("1", handle_v1)
# 
#         # Main loop
#         while True:
#             blynk.run()
#             time.sleep(1)
#             blynk.virtual_write(2, "Hello from CircuitPython!")
# 
#     except KeyboardInterrupt:
#         print("Disconnected from Blynk.")
