"""
Code originally written by Jody Caudill.

Unknown (as of January 2025) what the original purpose of this code was, or what precisely the dependencies are.
"""

import matplotlib.pyplot as plt
import numpy as np
import serial
from time import sleep
import pickle
import pyvisa
import winsound

test = pyvisa.ResourceManager()

specAn = test.open_resource("GPIB1::18::INSTR")

controlBox = serial.Serial("COM7", 9600)

controlBox.write(b"CMD:MOV:-178.000,0.000;")
values = [0, 0]

print("Initialized")
print("Moving to initial point")
# for i in range(100):
while values[1] > -177.5:
    try:
        a = controlBox.read(1000)
        b = str(a, "ascii")
        point1 = b.index("El:")
        point2 = b.index("\r", point1)
        parts = [i.strip() for i in b[point1:point2].split(",")]
        values = [float(i.split(" ")[1]) for i in parts]
        print(values)
        # print(values)
    except ValueError:
        continue
print("Setup Ready")
controlBox.write(b"CMD:MOV:180.000,0.000;")

az = []
val = []
print("Collecting Data")
while values[1] < 179.5:
    try:
        a = controlBox.read(1000)
        b = str(a, "ascii")
        point1 = b.index("El:")
        point2 = b.index("\r", point1)
        parts = [i.strip() for i in b[point1:point2].split(",")]
        values = [float(i.split(" ")[1]) for i in parts]

        traceDataRaw = specAn.query("TRA?").split(",")
        maxVal = max([float(i) for i in traceDataRaw])
        val.append(maxVal)
        az.append(values[1])
        print("Gathered Data Point")
        print(values)
    except ValueError:
        continue
    except KeyboardInterrupt:
        break
print("Data Collected")
az = np.array(az)
az = np.deg2rad(az)
val = np.array(val)
print(az)
print(val)

data = {"az": az, "mag": val}
with open("ANT1_Rolled-8.16625_360_90Pol.pkl", "wb") as outFile:
    pickle.dump(data, outFile)


print("Output File Created")
print("Plotting")
fig, ax = plt.subplots(subplot_kw={"projection": "polar"})
ax.plot(az, val)
# ax.set_rmax(2)
# ax.set_rticks([0.5, 1, 1.5, 2])  # Less radial ticks
ax.set_rlabel_position(-22.5)  # Move radial labels away from plotted line
ax.grid(True)

ax.set_title("AUT Pattern", va="bottom")
winsound.Beep(2500, 250)
plt.show()
print("Complete")


# for i in range()
