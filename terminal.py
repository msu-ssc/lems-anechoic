"""
Code originally written by Jody Caudill.

Unknown (as of January 2025) what the original purpose of this code was, or what precisely the dependencies are.
"""

import serial

a = serial.Serial("COM7", 9600, timeout=0.01)
while True:
    try:
        query = bytes(input("> "), "ascii")
        if query == b"?":
            print(a.in_waiting)
        elif query == b"?*":
            test = a.reset_input_buffer()
            print("Flushed Buffer")
            print(a.read(8))
        else:
            a.write(query)
    except KeyboardInterrupt:
        break

a.close()
