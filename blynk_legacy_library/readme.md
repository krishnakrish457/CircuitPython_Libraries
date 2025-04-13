# Blynk Library for CircuitPython

[![Version](https://img.shields.io/badge/version-0.2.1-blue)](blynklib_circuitpython.py)

This library provides a client for the [Blynk IoT Platform](https://blynk.io/), specifically adapted for use with [CircuitPython](https://circuitpython.org/). It allows your CircuitPython-powered microcontrollers with network connectivity (like ESP32-S2, ESP32-S3, RP2040 + AirLift, etc.) to connect to Blynk servers (Blynk.Cloud or local servers) and interact with Blynk apps.

This is an adaptation of MicroPython Blynk libraries, leveraging CircuitPython's native `socketpool` for networking.

## Features

*   Connects to Blynk servers (Blynk.Cloud or local).
*   Handles Blynk protocol communication (Login, Ping, Hardware commands).
*   Provides decorators for easy handling of Blynk events:
    *   `@blynk.ON("connected")`
    *   `@blynk.ON("disconnected")`
    *   `@blynk.VIRTUAL_WRITE(pin)`
    *   `@blynk.VIRTUAL_READ(pin)`
*   Basic connection management (attempts reconnection on disconnect).
*   Uses non-blocking reads and a `run()` method suitable for cooperative multitasking in your main loop.

## Requirements

*   A microcontroller board supported by CircuitPython with network capabilities (e.g., built-in WiFi or using a module like ESP32 SPI/UART or WIZnet Ethernet).
*   CircuitPython firmware (latest stable version recommended) installed on your board.
*   Network access configured (WiFi credentials, etc.).
*   A Blynk account and a Blynk Auth Token for your device project.
Contributions (bug reports, feature requests, pull requests) are welcome! Please open an issue to discuss any significant changes before submitting a pull request.

License
This project is licensed under the MIT License - see the LICENSE file for details (if one is provided in the repository, otherwise assume MIT).

Use code with caution.
