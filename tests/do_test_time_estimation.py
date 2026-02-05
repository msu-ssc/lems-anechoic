import matplotlib.pyplot as plt
import numpy as np

from msu_anechoic import experiment

short_angles = np.linspace(0, 5, 100)
long_angles = np.linspace(5, 180, 100)
all_angles = np.concatenate([short_angles, long_angles])

horizontal_times = [experiment._estimate_time(angle, kind="horizontal", trace=False) for angle in all_angles]
vertical_times = [experiment._estimate_time(angle, kind="vertical", trace=False) for angle in all_angles]

plt.plot(all_angles, horizontal_times, label="Horizontal")
plt.plot(all_angles, vertical_times, label="Vertical")

plt.gca().axvline(2, color="gray", linestyle="--", label="Transition Angle")
plt.xlabel("Angle (degrees)")
plt.ylabel("Estimated Time (seconds)")
plt.title("Estimated Turntable Movement Time vs Angle")
plt.legend()
plt.grid()
plt.show()
