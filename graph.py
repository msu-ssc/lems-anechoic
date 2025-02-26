import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

spec_an_df = pd.read_csv("./spec_an.csv", parse_dates=["center_frequency_amplitude_timestamp_before"])
turntable_df = pd.read_csv("./turntable.csv", parse_dates=["timestamp"])

fig, [ax1, ax2] = plt.subplots(2, 1)

ax1: plt.Axes
ax2: plt.Axes

ax1.plot(spec_an_df["center_frequency_amplitude_timestamp_before"], spec_an_df["center_frequency_amplitude"])
ax1.set_xlabel("Timestamp")
ax1.set_ylabel("Center Frequency Amplitude")

ax2.plot(turntable_df["timestamp"], turntable_df["elevation"], "x-", label="Elevation")
ax2.plot(turntable_df["timestamp"], turntable_df["azimuth"], "x-",label="Azimuth")
ax2.legend()
ax2.set_xlabel("Timestamp")
ax2.set_ylabel("Angle")
ax2.set_ylim(-90, 90)
ax2.set_yticks(np.arange(-90, 91, 15))
ax2.grid()

min_timestamp = min(spec_an_df["center_frequency_amplitude_timestamp_before"].min(), turntable_df["timestamp"].min())
max_timestamp = max(spec_an_df["center_frequency_amplitude_timestamp_before"].max(), turntable_df["timestamp"].max())

time_margin = (max_timestamp - min_timestamp) * 0.03
ax1.set_xlim(min_timestamp - time_margin, max_timestamp + time_margin)
ax2.set_xlim(min_timestamp - time_margin, max_timestamp + time_margin)
plt.show()


# Interpolate the power values to match the timestamps of the turntable data
interpolated_power = np.interp(
    pd.to_datetime(turntable_df["timestamp"]).astype(int),
    pd.to_datetime(spec_an_df["center_frequency_amplitude_timestamp_before"]).astype(int),
    spec_an_df["center_frequency_amplitude"]
)

elevation_array = turntable_df["elevation"].to_numpy()

# Sort elevation_array and interpolated_power by elevation_array in ascending order
sorted_indices = np.argsort(elevation_array)
elevation_array = elevation_array[sorted_indices]
interpolated_power = interpolated_power[sorted_indices]

# Plot elevation vs interpolated power
fig, ax3 = plt.subplots()
ax3.plot(elevation_array, interpolated_power, 'o-')
ax3.set_xlabel('Elevation')
ax3.set_ylabel('Interpolated Power')
ax3.set_title('Elevation vs Interpolated Power')

plt.show()