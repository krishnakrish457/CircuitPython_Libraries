_VERSION = "0.2.1" # Incremented version for CircuitPython adaptation

import struct
import time
import sys # Used for platform info as os.uname might not be available

# CircuitPython specific imports
import socketpool
import errno

# Use time.monotonic() for timekeeping in CircuitPython
# supervisor.ticks_ms() could also be used but monotonic() is more standard
gettime = lambda: int(time.monotonic() * 1000)

def dummy(*args, **kwargs): # Added **kwargs for compatibility
    pass

# --- Constants --- (No changes needed here)
const = lambda x: x # CircuitPython doesn't benefit from MicroPython's const

MSG_RSP = const(0)
MSG_LOGIN = const(2)
MSG_PING  = const(6)

MSG_TWEET = const(12)
MSG_EMAIL = const(13)
MSG_NOTIFY = const(14)
MSG_BRIDGE = const(15)
MSG_HW_SYNC = const(16)
MSG_INTERNAL = const(17)
MSG_PROPERTY = const(19)
MSG_HW = const(20)
MSG_HW_LOGIN = const(29)
MSG_EVENT_LOG = const(64)

MSG_REDIRECT  = const(41)  # TODO: not implemented
MSG_DBG_PRINT  = const(55) # TODO: not implemented

STA_SUCCESS = const(200)
STA_INVALID_TOKEN = const(9)

DISCONNECTED = const(0)
CONNECTING = const(1)
CONNECTED = const(2)

# --- Welcome Message --- (Adapted for CircuitPython)
try:
    # sys.platform provides basic platform info in CircuitPython
    platform_name = sys.platform
except AttributeError:
    platform_name = "unknown"

print("""
    ___  __          __
   / _ )/ /_ _____  / /__
  / _  / / // / _ \\/  '_/
 /____/_/\\_, /_//_/_/\\_\\
        /___/ for CircuitPython v""" + _VERSION + " (" + platform_name + ")\n")

# --- Blynk Protocol Logic --- (Largely unchanged, uses updated gettime)
class BlynkProtocol:
    def __init__(self, auth, heartbeat=10, buffin=1024, log=None):
        self.callbacks = {}
        self.heartbeat = heartbeat*1000 # ms
        self.buffin = buffin
        self.log = log or dummy
        self.auth = auth
        self.state = DISCONNECTED
        self.msg_id = 1
        self.lastRecv = 0
        self.lastSend = 0
        self.lastPing = 0
        self.bin = b""
        # connect() is now called by the transport layer after socket connection

    # --- Decorators and Callback Registration --- (No changes needed)
    def ON(blynk, evt):
        class Decorator:
            def __init__(self, func):
                self.func = func
                blynk.callbacks[evt] = func
            def __call__(self, *args, **kwargs): # Allow args/kwargs in callback
                return self.func(*args, **kwargs)
        return Decorator

    def VIRTUAL_READ(blynk, pin):
        class Decorator():
            def __init__(self, func):
                self.func = func
                blynk.callbacks["readV"+str(pin)] = func
            def __call__(self, *args, **kwargs): # Allow args/kwargs in callback
                return self.func(*args, **kwargs)
        return Decorator

    def VIRTUAL_WRITE(blynk, pin):
        class Decorator():
            def __init__(self, func):
                self.func = func
                blynk.callbacks["V"+str(pin)] = func
            def __call__(self, *args, **kwargs): # Allow args/kwargs in callback
                return self.func(*args, **kwargs)
        return Decorator

    def on(self, evt, func):
        self.callbacks[evt] = func

    def emit(self, evt, *a, **kv):
        self.log("Event:", evt, "->", *a)
        if evt in self.callbacks:
            # Use try-except for potential signature mismatches (e.g. 'connected' event)
            try:
                self.callbacks[evt](*a, **kv)
            except TypeError as e:
                # If 'connected' event failed, try calling without ping kwarg for compatibility
                if evt == 'connected' and 'ping' in kv:
                     try:
                         self.callbacks[evt]()
                     except Exception as inner_e:
                         self.log("Error calling legacy callback for", evt, ":", inner_e)
                else:
                    self.log("Error calling callback for", evt, ":", e)


    # --- Blynk API Methods --- (No changes needed)
    def virtual_write(self, pin, *val):
        self._send(MSG_HW, 'vw', pin, *val)

    def set_property(self, pin, prop, *val):
        self._send(MSG_PROPERTY, pin, prop, *val)

    def sync_virtual(self, *pins):
        self._send(MSG_HW_SYNC, 'vr', *pins)

    def notify(self, msg):
        self._send(MSG_NOTIFY, msg)

    def tweet(self, msg):
        self._send(MSG_TWEET, msg)

    def log_event(self, event, descr=None):
        if descr is None: # Explicit check is slightly clearer
            self._send(MSG_EVENT_LOG, event)
        else:
            self._send(MSG_EVENT_LOG, event, descr)

    # --- Internal Send Method --- (Minor changes: id kwarg handling)
    def _send(self, cmd, *args, **kwargs):
        if self.state == DISCONNECTED:
            self.log("Warn: Cannot send while disconnected.")
            return

        msg_id = kwargs.get("id", None) # Use .get() for safer access
        if msg_id is None:
            msg_id = self.msg_id
            self.msg_id += 1
            if self.msg_id > 0xFFFF:
                self.msg_id = 1

        # --- Data Payload Encoding ---
        if cmd == MSG_RSP:
            # RSP message body is empty, dlen contains the status code
            data = b''
            # args[0] should contain the status code for RSP
            dlen = args[0] if args else STA_SUCCESS # Default to success if no arg provided

        elif cmd == MSG_HW_LOGIN:
            # HW_LOGIN payload is *just* the auth token bytes
            # Assume self.auth is stored as a string from __init__
            if not args or not isinstance(args[0], str):
                 # This should not happen if called correctly from connect()
                 self.log("Error: HW_LOGIN called without string auth token")
                 return
            data = args[0].encode('utf-8') # Encode the token string directly
            dlen = len(data)

        else:
            # For other commands, join string arguments with null bytes, then encode
            try:
                # Ensure all args are strings before joining
                str_args = [str(arg) for arg in args]
                data = "\0".join(str_args).encode("utf-8")
                dlen = len(data)
            except Exception as e:
                 # Catch potential errors during string conversion/encoding
                 self.log(f"Error encoding data for cmd {cmd}: {e}")
                 return # Don't send malformed data

        # --- Logging ---
        # Log *before* packing. For RSP, dlen is status. For others, it's payload length.
        # Avoid logging the raw auth token itself for security/cleanliness
        if cmd == MSG_HW_LOGIN:
             self.log('<', cmd, msg_id, dlen, '|', "[AUTH_TOKEN]")
        else:
             self.log('<', cmd, msg_id, dlen, '|', *args)

        # --- Packing and Sending ---
        # Pack the header (cmd, id, length)
        hdr = struct.pack("!BHH", cmd, msg_id, dlen)
        # Combine header and data payload
        msg = hdr + data

        # Record send time and send via the transport layer's _write method
        self.lastSend = gettime()
        try:
            self._write(msg) # Relies on transport layer implementation (_write in Blynk class)
        except Exception as e:
            self.log("Error sending:", e)
            self.disconnect() # Disconnect on send error
            # Optional: Re-raise the error if the caller needs to know send failed
            # raise

    # --- Protocol State Management ---
    def connect(self):
        """Initiates the Blynk protocol connection sequence (after socket is connected)."""
        if self.state != CONNECTING: # Should be called when transport moves to CONNECTING
             self.log("Warn: Protocol connect called in unexpected state:", self.state)
             # Reset state anyway? Or just log? Let's reset for robustness.
             self.state = CONNECTING

        self.msg_id = 1
        (self.lastRecv, self.lastSend, self.lastPing) = (gettime(), 0, 0)
        self.bin = b"" # Clear receive buffer
        self._send(MSG_HW_LOGIN, self.auth)

    def disconnect(self):
        """Handles protocol disconnection."""
        if self.state == DISCONNECTED: return
        prev_state = self.state
        self.state = DISCONNECTED
        # Optionally clear callbacks? No, let user handle re-registering if needed.
        if prev_state != DISCONNECTED: # Only emit if actually was connected/connecting
             self.emit('disconnected')
        self.log("Protocol disconnected.")

    # --- Data Processing Logic --- (Unchanged core logic)
    def process(self, data=None): # Allow data=None for timer-only processing
        """Processes incoming data and handles heartbeats/timeouts."""
        if self.state == DISCONNECTED: return

        now = gettime()

        # --- Heartbeat / Ping ---
        # Check for timeout first
        if now - self.lastRecv > self.heartbeat + (self.heartbeat // 2):
            self.log("Heartbeat timeout")
            return self.disconnect() # Let transport handle actual socket close

        # Send ping if needed (connection idle or heartbeat interval passed)
        if (self.state == CONNECTED and
            now - self.lastPing > self.heartbeat // 10 and
            (now - self.lastSend > self.heartbeat or
             now - self.lastRecv > self.heartbeat)):
            try:
                self._send(MSG_PING)
                self.lastPing = now
            except Exception as e:
                 self.log("Error sending ping:", e)
                 # Don't disconnect immediately on ping failure, timeout will catch it
                 pass # Error is logged in _send

        # --- Process Incoming Data ---
        if data: # Append new data if provided
            self.bin += data

        # Process messages in buffer
        while True:
            if len(self.bin) < 5: # Need at least header length
                return # Not enough data yet

            hdr = self.bin[:5]
            cmd, msg_id, dlen = struct.unpack("!BHH", hdr)

            # Basic validation
            if msg_id == 0:
                self.log("Error: Invalid msg_id 0")
                return self.disconnect()
            if dlen < 0 or dlen > self.buffin * 2: # Check dlen sanity (allow slightly larger for safety?)
                 self.log(f"Error: Invalid message length: {dlen} (buffin: {self.buffin})")
                 return self.disconnect()


            self.lastRecv = now # Update last receive time on any valid header

            if cmd == MSG_RSP:
                 # RSP message doesn't have a body, dlen is the status code
                self.bin = self.bin[5:] # Consume header
                status_code = dlen
                self.log('>', cmd, msg_id, '| Status:', status_code)

                if self.state == CONNECTING and msg_id == 1: # Response to login
                    if status_code == STA_SUCCESS:
                        self.state = CONNECTED
                        connect_time = now - self.lastSend # Rough ping estimate
                        # Send client info
                        self._send(MSG_INTERNAL, 'ver', _VERSION, 'h-beat', self.heartbeat // 1000, 'buff-in', self.buffin, 'dev', 'cp') # 'cp' for CircuitPython
                        self.log("Blynk connection successful.")
                        # Emit connected event *after* sending client info
                        self.emit('connected', ping=connect_time)
                    else:
                        self.log("Blynk connection failed. Status:", status_code)
                        if status_code == STA_INVALID_TOKEN:
                            print("!!! ERROR: Invalid Blynk auth token !!!")
                        # Disconnect at the protocol level, transport will close socket
                        return self.disconnect()
                # Handle other RSP if needed (e.g., confirmation for other commands)
                # else: self.log("Received RSP for id:", msg_id, "Status:", status_code)

            else: # Other message types with data body
                if len(self.bin) < 5 + dlen: # Check if full message body is received
                    return # Not enough data yet

                data = self.bin[5 : 5 + dlen]
                self.bin = self.bin[5 + dlen:] # Consume message (header + body)

                # Safely decode arguments, handle potential Unicode errors
                try:
                    args = list(map(lambda x: x.decode('utf8'), data.split(b'\0')))
                except UnicodeDecodeError:
                    self.log("Error: Could not decode UTF-8 message data.")
                    # Possibly disconnect, or just log and continue? Let's log for now.
                    args = [] # Process as empty args

                self.log('>', cmd, msg_id, '|', ','.join(args))

                # --- Dispatch based on command ---
                if cmd == MSG_PING:
                    self._send(MSG_RSP, STA_SUCCESS, id=msg_id)
                elif cmd == MSG_HW or cmd == MSG_BRIDGE:
                    if len(args) > 1:
                        pin_str = args[1]
                        if args[0] == 'vw': # Virtual Write
                            self.emit("V"+pin_str, args[2:]) # Pass remaining args
                            self.emit("V*", pin_str, args[2:]) # Wildcard event
                        elif args[0] == 'vr': # Virtual Read Request
                            self.emit("readV"+pin_str)
                            self.emit("readV*", pin_str) # Wildcard event
                        # Handle other HW commands if needed (pm, dw, dr, aw, ar)
                        else:
                            self.log("Unsupported HW/Bridge command:", args[0])
                    else:
                         self.log("Malformed HW/Bridge message:", args)

                elif cmd == MSG_INTERNAL:
                    if len(args) > 0:
                        self.emit("int_"+args[0], args[1:]) # e.g., int_rtc, int_echo
                    else:
                         self.log("Malformed Internal message:", args)
                # Handle other commands (MSG_NOTIFY, MSG_EMAIL, etc.) if needed
                # These often don't require a client response
                else:
                    self.log("Ignoring unexpected command:", cmd)
                    # Don't disconnect on unknown command from server? Maybe log only.
                    # return self.disconnect()


# --- CircuitPython Transport Layer ---
class Blynk(BlynkProtocol):
    def __init__(self, auth, pool, **kwargs):
        """
        Initializes Blynk for CircuitPython.

        :param str auth: Your Blynk authentication token.
        :param socketpool.SocketPool pool: The active socketpool instance (e.g., from wifi.radio).
        :param str server: Blynk server address (default: 'blynk.cloud').
        :param int port: Blynk server port (default: 80 for non-SSL).
        :param int heartbeat: Heartbeat interval in seconds (default: 10).
        :param int buffin: Input buffer size in bytes (default: 1024).
        :param function log: Optional logging function (default: none).
        """
        self.pool = pool
        self.server = kwargs.pop('server', 'local_server_ip')
        self.port = kwargs.pop('port', 8080) # Default to non-SSL port 80
        # Note: SSL/TLS requires adafruit_requests/ssl module and potentially more memory
        #       Using port 8441/8442 would require SSL context wrapping the socket.

        # Call parent initializer AFTER setting up transport-specific attributes
        super().__init__(auth, **kwargs)

        self.conn = None # Socket object
        # Pre-allocate receive buffer for recv_into
        self.recv_buffer = bytearray(self.buffin)
        self._last_connect_attempt = 0
        self._connect_retry_interval = 5000 # ms (5 seconds)


    def connect(self, timeout=5):
        """
        Establishes connection to the Blynk server using socketpool.
        Handles protocol initiation upon successful connection.

        :param int timeout: Connection timeout in seconds (default: 5).
                         Note: Actual socket connect timeout might be system-dependent.
        """
        if self.state != DISCONNECTED:
            self.log("Already connected or connecting.")
            return True # Indicate already connected/connecting

        now = gettime()
        if now - self._last_connect_attempt < self._connect_retry_interval:
             # self.log("Waiting before next connect attempt...") # Optional: reduce verbosity
             return False # Not time to retry yet

        self._last_connect_attempt = now
        self.log(f"Connecting to {self.server}:{self.port}...")
        self.state = CONNECTING # Set state before attempting connection

        addr_info = None
        try:
            # 1. Resolve Server Address
            # getaddrinfo returns list of (family, type, proto, canonname, sockaddr)
            # sockaddr is typically (ip_address, port)
            addr_info = self.pool.getaddrinfo(self.server, self.port)[0]
            host_ip = addr_info[-1][0]
            host_port = addr_info[-1][1]
            self.log(f"Resolved {self.server} to {host_ip}")

            # 2. Create Socket
            self.conn = self.pool.socket(addr_info[0], addr_info[1])
            # Setting timeout for connect itself? CircuitPython sockets might block here.
            # self.conn.settimeout(timeout) # May not be universally supported/effective

            # 3. Connect
            # The connect call itself might block or raise an error on timeout/failure
            self.conn.connect((host_ip, host_port))

            # 4. Set socket to non-blocking for recv_into
            # CircuitPython sockets used with recv_into often behave non-blockingly by default
            # but explicit setting ensures it. Timeout 0 means non-blocking.
            self.conn.settimeout(0)

            self.log("Socket connected.")

            # 5. Initiate Blynk Protocol Login
            super().connect() # Call the protocol layer's connect logic (sends HW_LOGIN)
            return True # Connection attempt successful (protocol handshake pending)

        except MemoryError as e:
             self.log("Memory Error during connect:", e)
             self.disconnect() # Ensure cleanup
             # Potentially raise or handle memory issue more specifically
             raise # Re-raise memory error as it's critical
        except OSError as e:
            self.log(f"Failed to connect: {e} (errno {e.errno})")
            self.disconnect() # Ensure cleanup (sets state back to DISCONNECTED)
            return False # Connection failed
        except Exception as e:
            self.log(f"Unexpected error during connect: {e}")
            self.disconnect()
            return False # Connection failed

    def disconnect(self):
        """Closes the socket connection and resets protocol state."""
        if self.conn:
            try:
                self.conn.close()
                self.log("Socket closed.")
            except OSError as e:
                 self.log(f"Error closing socket: {e}")
            finally:
                 self.conn = None
        # Call protocol disconnect *after* closing socket
        super().disconnect() # Resets protocol state and emits 'disconnected'

    def _write(self, data):
        """Sends data over the socket."""
        if not self.conn or self.state == DISCONNECTED:
            # self.log("Warn: Attempted to write while disconnected.") # Can be noisy
            raise OSError("Socket not connected") # Raise error if trying to write when not connected

        try:
            # send() should ideally send all data, but can return partial count
            bytes_sent = 0
            while bytes_sent < len(data):
                sent = self.conn.send(data[bytes_sent:])
                if sent == 0: # Socket closed or non-blocking send buffer full?
                    raise OSError("Socket send returned 0")
                bytes_sent += sent
            # self.log(f"Sent {bytes_sent} bytes.") # Optional: for debug

        except OSError as e:
            self.log(f"Socket write error: {e} (errno {e.errno})")
            self.disconnect() # Disconnect if write fails
            raise # Re-raise the exception so caller knows send failed

    def run(self):
        """
        Processes incoming data and maintains the connection.
        This should be called periodically in your main loop.
        """
        # --- 1. Handle connection state ---
        if self.state == DISCONNECTED:
            # Attempt to reconnect if disconnected
            self.connect() # connect() includes retry logic
            return # Nothing more to do if still disconnected

        # --- 2. Process Protocol Timers (Heartbeat, Ping) ---
        # Call process() even if no data received, to handle timeouts/pings
        try:
            super().process(None)
            # Check state again in case process() caused a disconnect (e.g., timeout)
            if self.state == DISCONNECTED:
                return
        except Exception as e:
             self.log("Error in protocol processing:", e)
             self.disconnect()
             return

        # --- 3. Read Incoming Data ---
        data_received = None
        bytes_read = 0
        try:
            # recv_into reads into the buffer, returns bytes read.
            # Non-blocking: returns 0 if no data, raises EAGAIN/EWOULDBLOCK if supported,
            # or raises other OSError on connection error.
            if self.conn: # Ensure socket exists
                 bytes_read = self.conn.recv_into(self.recv_buffer)
                 # self.log(f"recv_into returned {bytes_read}") # Debugging

                 if bytes_read > 0:
                     # Create a memoryview for efficient slicing without copying
                     data_received = memoryview(self.recv_buffer)[:bytes_read]
                     # self.log(f"Received {bytes_read} bytes: {bytes(data_received)}") # Debugging bytes
                 # else: bytes_read == 0 means no data available right now (non-blocking)

        except OSError as e:
            # Check for specific non-blocking errors if needed (may vary by implementation)
            # errno.EAGAIN / errno.EWOULDBLOCK usually mean "try again later" in non-blocking mode
            if e.errno == errno.EAGAIN or e.errno == errno.EWOULDBLOCK:
                 # This is expected in non-blocking mode, just means no data yet
                 pass
            else:
                 # Other OS errors likely indicate a connection problem
                 self.log(f"Socket read error: {e} (errno {e.errno})")
                 self.disconnect()
                 return # Stop processing on read error

        except Exception as e: # Catch other potential errors
             self.log(f"Unexpected error during recv_into: {e}")
             self.disconnect()
             return

        # --- 4. Process Received Data ---
        if data_received:
            try:
                super().process(data_received)
            except Exception as e:
                 self.log("Error processing received data:", e)
                 self.disconnect()
                 return
                 
#modify this into separate file if needed
if __name__ == "__main__":
    import wifi
    import time
    
    WIFI_SSID = ""
    WIFI_PASSWORD = ""
    BLYNK_TOKEN = ""
    
    wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
    pool = socketpool.SocketPool(wifi.radio)
    blynk = Blynk(BLYNK_TOKEN,pool,log=print)  #Pass None for no logs

    @blynk.ON("connected")
    def blynk_connected(ping):
        print(f'Blynk connected. Ping: {ping}ms')
        blynk.sync_virtual(1) # Example: sync pin V1 on connect

    @blynk.ON("disconnected")
    def blynk_disconnected():
        print('Blynk disconnected')
        
    @blynk.VIRTUAL_WRITE(1) # Handler for virtual pin V1 write
    def v1_write_handler(value): # value is a list of strings
        print(f'V1 received: {value}')
    
        
    while True:
     try:
        blynk.run()
        time.sleep(0.1)

     except KeyboardInterrupt:
         print("Interrupted by user.")
         blynk.disconnect()
         break
     except Exception as e:
         print(f"Main loop error: {e}")
         # Attempt to clean up Blynk connection on unexpected error
         blynk.disconnect()
         # Optional: add a delay before potentially restarting loop/rebooting
         time.sleep(5)
