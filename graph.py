import datetime
import json
import re
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

spec_an_df = pd.read_csv("./spec_an.csv", parse_dates=["center_frequency_amplitude_timestamp_before"])
turntable_df = pd.read_csv("./turntable_with_jumps.csv", parse_dates=["timestamp"])
turntable_df = pd.read_csv("./turntable.csv", parse_dates=["timestamp"])

turntable_df["actual_elevation"] = turntable_df["elevation"]

# Find row indexes where the actual_elevation column changes by more than 2 degrees
elevation_diff = turntable_df["actual_elevation"].diff().abs()
indexes = elevation_diff[elevation_diff > 2].index
print("Indexes where actual_elevation changes by more than 2 degrees:", indexes)

for index in indexes:
    if index > 0:
        before_jump = turntable_df.loc[index - 1, "actual_elevation"]
        after_jump = turntable_df.loc[index, "actual_elevation"]
        print(f"Discontinuity at index {index}: before jump = {before_jump}, after jump = {after_jump}")

        for index in indexes:
            if index > 0:
                jump_value = turntable_df.loc[index, "actual_elevation"] - turntable_df.loc[index - 1, "actual_elevation"]
                turntable_df.loc[index:, "actual_elevation"] -= jump_value

# exit()
# fig, [ax1, ax2] = plt.subplots(2, 1)
fig, ax2 = plt.subplots(1, 1)

# ax1: plt.Axes
ax2: plt.Axes

# ax1.plot(spec_an_df["center_frequency_amplitude_timestamp_before"], spec_an_df["center_frequency_amplitude"])
# ax1.set_xlabel("Timestamp")
# ax1.set_ylabel("Center Frequency Amplitude")

ax2.plot(turntable_df["timestamp"], turntable_df["elevation"], "x-", label="Reported Elevation")
# ax2.plot(turntable_df["timestamp"], turntable_df["azimuth"], "x-",label="Azimuth")
ax2.plot(turntable_df["timestamp"], turntable_df["actual_elevation"], "x-",label="Actual elevation (approximate)")
ax2.set_xlabel("Timestamp")
ax2.set_ylabel("Angle")
ax2.set_ylim(-90, 90)
ax2.set_yticks(np.arange(-90, 91, 45))

min_timestamp = min(spec_an_df["center_frequency_amplitude_timestamp_before"].min(), turntable_df["timestamp"].min())
max_timestamp = max(spec_an_df["center_frequency_amplitude_timestamp_before"].max(), turntable_df["timestamp"].max())

time_margin = (max_timestamp - min_timestamp) * 0.03
# ax1.set_xlim(min_timestamp - time_margin, max_timestamp + time_margin)
ax2.set_xlim(min_timestamp - time_margin, max_timestamp + time_margin)

annotations = {}

with open("mayo.jsonl", "r") as f:
    annotations = {}
    for line in f:
        data = json.loads(line)
        message = data["message"]
        # print(message)
        if "CMD:MOV" not in message:
            # print(f"---NOPE")
            continue
        timestamp = datetime.datetime.fromisoformat(data["asctime"]).astimezone(datetime.timezone.utc)
        match = re.search(r"CMD:MOV:(-?\d+\.\d+),(-?\d+\.\d+);", message)
        text = "MOVE COMMAND SENT"
        text = str(match.group(0))
        annotations[timestamp] = text

# annotations = {
#     # datetime.datetime.fromisoformat("2025-02-26 16:18:13").astimezone(datetime.timezone.utc): "CMD:MOV:0.000,-60.000",
#     # datetime.datetime.fromisoformat("2025-02-26 16:19:11").astimezone(datetime.timezone.utc): "CMD:MOV:0.000,20.000",
#     # datetime.datetime.fromisoformat("2025-02-26 16:20:42").astimezone(datetime.timezone.utc): "Powered off",
#     # datetime.datetime.fromisoformat("2025-02-26 16:20:45").astimezone(datetime.timezone.utc): "Powered on",

# }

print(annotations)

for timestamp, text in annotations.items():
    # ax1.axvline(timestamp, color="red", linestyle="--")
    ax2.axvline(timestamp, color="red", linestyle="--")
    ax2.text(timestamp, 85, text, rotation=90, verticalalignment="top", horizontalalignment="right")

ax2.axhline(-30.01, color="black", linestyle="--", label="-30.01deg")
ax2.grid()
ax2.legend()

plt.show()


exit()

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