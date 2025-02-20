import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


csv = pd.read_csv("turntable_move_times.csv")
print(csv.dtypes)

fig, ax = plt.subplots()

azimuth_data = csv[
    (csv["DIRECTION"] == "PLUS_AZIMUTH")
    | (csv["DIRECTION"] == "MINUS_AZIMUTH")
]

elevation_data = csv[
    (csv["DIRECTION"] == "PLUS_ELEVATION")
    | (csv["DIRECTION"] == "MINUS_ELEVATION")
]

for data in [azimuth_data, elevation_data]:
    label = "AZIMUTH" if "AZIMUTH" in data["DIRECTION"].iloc[0] else "ELEVATION"
    # if "BOTH" in direction:
    #     continue
    # # if "ELEVATION" in direction:
    # #     continue
    # if "AZIMUTH" in direction:
    #     continue
    # data = csv[
    #     (csv["DIRECTION"] == "PLUS_AZIMUTH")
    #     | (csv["DIRECTION"] == "MINUS_AZIMUTH")
    # ]
    # label = {
    #     "PLUS_AZIMUTH": "+Azimuth (Rightward)",
    #     "MINUS_AZIMUTH": "-Azimuth (Leftward)",
    #     "PLUS_ELEVATION": "+Elevation (Upward)",
    #     "MINUS_ELEVATION": "-Elevation (Downward)",
    # }[direction]
    ax.scatter(data["DISTANCE"], data["TIME"], label=label, marker="o")

    a, b = np.polyfit(data["DISTANCE"], data["TIME"], 1)
    # Calculate R^2 value
    y_pred = a * data["DISTANCE"] + b
    ss_res = np.sum((data["TIME"] - y_pred) ** 2)
    ss_tot = np.sum((data["TIME"] - np.mean(data["TIME"])) ** 2)
    r2 = 1 - (ss_res / ss_tot)
    print(f"{label} R^2: {r2:.2f}")
    # print(f"y = {a:.2f}x + {b:.2f}")
    ax.plot(data["DISTANCE"], a * data["DISTANCE"] + b, "--", label=f"{label} fit: y={a:.2f}x+{b:.2f} [r^2={r2:.4f}]")

ax.set_xlabel("Distance (degrees)")
ax.set_ylabel("Time (seconds)")
# ax.plot(csv["DISTANCE"], csv["TIME"])
ax.grid(which="both")
# ax.set_xlim(0, 5)
# ax.set_ylim(0, 10)
az_m = (14.8-3.15) / (30-.25)
az_b = 3

# line_xs = np.linspace(ax.get_xlim()[0], ax.get_xlim()[1], 100)
# line_ys = az_m * line_xs + az_b
# ax.plot(line_xs, line_ys, label=f"Azimuth Fit (y={az_m:.2f}x+{az_b:.2f})", linestyle="--")
ax.legend()
# ax.set_ylim(bottom=0, top=10)
# ax.set_xlim(left=0 ,right=5)
ax.set_title("Actial time to move turntable")

# ax.set_xticks(list(np.arange(0, 2.51, .25)) + list(np.arange(0, 10, 1)) + list(np.arange(10,30.1,5)))

# ax.plot(csv["DISTANCE"], p(csv["DISTANCE"]), "r--")
plt.show()