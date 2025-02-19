import datetime
import random
import time
from pathlib import Path
from typing import Callable

from msu_ssc import ssc_log

from msu_anechoic.turntable import AzEl
from msu_anechoic.turntable import TurnTable


def sign(x: float) -> int:
    if x == 0:
        return 0
    return 1 if x > 0 else -1


CSV_PATH = Path("tests/mock_turntable.csv")


class MockTurntable(TurnTable):
    azimuth_rotation_rate = 1.5
    """Degrees per second"""

    elevation_rotation_rate = 1.5
    """Degrees per second"""

    time_step = 0.1
    """Seconds"""

    def __init__(
        self,
        *,
        step_function: Callable,
        start_location: AzEl = AzEl(0, 0),
        csv_path: Path | None = None,
    ):
        self._location = start_location
        self._move_counter = 0
        self.csv_path = csv_path
        self.step_function = step_function

    def _step_concurrent(
        self,
        target_location: AzEl,
        azimuth_margin: float,
        elevation_margin: float,
    ) -> tuple[AzEl, str]:
        # Do a step on the assumption that the azimuth and elevation are done at the same time
        remaining_azimuth = target_location.azimuth - self._location.azimuth
        remaining_elevation = target_location.elevation - self._location.elevation

        need_to_move_azimuth = abs(remaining_azimuth) > azimuth_margin
        need_to_move_elevation = abs(remaining_elevation) > elevation_margin

        if need_to_move_azimuth and need_to_move_elevation:
            delta_azimuth = self.time_step * sign(remaining_azimuth) * self.azimuth_rotation_rate * random.gauss(1, 0.1)
            delta_elevation = self.time_step * sign(remaining_elevation) * self.elevation_rotation_rate * random.gauss(1, 0.1)
            description = "BOTH"
        elif need_to_move_azimuth:
            delta_azimuth = self.time_step * sign(remaining_azimuth) * self.azimuth_rotation_rate * random.gauss(1, 0.1)
            delta_elevation = random.gauss(0, 0.01)
            description = "AZIMUTH_ONLY"
        elif need_to_move_elevation:
            delta_elevation = self.time_step * sign(remaining_elevation) * self.elevation_rotation_rate * random.gauss(1, 0.1)
            delta_azimuth = random.gauss(0, 0.01)
            description = "ELEVATION_ONLY"
        else:
            raise ValueError("Shouldn't be here")
        
        self._location = AzEl(
            azimuth=self._location.azimuth + delta_azimuth,
            elevation=self._location.elevation + delta_elevation,
        )
        ssc_log.debug(f"Moved to {self._location} [CONCURRENT]")
        time.sleep(self.time_step)
        return self._location, f"MOVE_{self._move_counter}_CONCURRENT_{description}"

    def _step_independent(
        self,
        target_location: AzEl,
        azimuth_margin: float,
        elevation_margin: float,
    ) -> tuple[AzEl, str]:
        # Do a step on the assumption that the azimuth and elevation are done at different times
        remaining_azimuth = target_location.azimuth - self._location.azimuth
        remaining_elevation = target_location.elevation - self._location.elevation

        if abs(remaining_azimuth) > azimuth_margin:
            delta_azimuth = self.time_step * sign(remaining_azimuth) * self.azimuth_rotation_rate * random.gauss(1, 0.1)
            delta_elevation = random.gauss(0, 0.01)
            portion = "AZIMUTH"
        elif abs(remaining_elevation) > elevation_margin:
            delta_elevation = (
                self.time_step * sign(remaining_elevation) * self.elevation_rotation_rate * random.gauss(1, 0.1)
            )
            delta_azimuth = random.gauss(0, 0.01)
            portion = "ELEVATION"
        else:
            raise ValueError("Shouldn't be here")
        self._location = AzEl(
            azimuth=self._location.azimuth + delta_azimuth,
            elevation=self._location.elevation + delta_elevation,
        )
        ssc_log.debug(f"Moved to {self._location} [{portion}]")
        time.sleep(self.time_step)
        return self._location, f"MOVE_{self._move_counter}_{portion}"

    def move_to(
        self,
        *,
        azimuth,
        elevation,
        azimuth_margin=0.5,
        elevation_margin=0.5,
        delay=0.1,
    ) -> AzEl:
        ssc_log.debug(f"Moving to {AzEl(azimuth, elevation)}")
        # ASSUMPTION: Movement will be azimuth first, then elevation
        move_start_time = time.monotonic()
        self._move_counter += 1

        # AZIMUTH
        # azimuth_start_time = time.monotonic()
        # azimuth_to_move = azimuth - self._location.azimuth
        # azimuth_direction = sign(azimuth_to_move)
        while True:
            if abs(self._location.azimuth - azimuth) < azimuth_margin and abs(self._location.elevation - elevation) < elevation_margin:
                break

            location, description = self.step_function(
                self,
                target_location=AzEl(azimuth=azimuth, elevation=elevation),
                azimuth_margin=azimuth_margin,
                elevation_margin=elevation_margin,
            )
            self._write_csv(
                timestamp=datetime.datetime.now(),
                elapsed=time.monotonic() - move_start_time,
                loc=location,
                description=description,
            )
            # ASSUMPTION: The elevation will have a little wobble
            # elevation_delta = random.gauss(0, 0.01)

        #     azimuth_delta = azimuth_direction * self.azimuth_rotation_rate * self.time_step * random.gauss(1, 0.1)
        #     self._location = AzEl(
        #         azimuth=self._location.azimuth + azimuth_delta,
        #         elevation=self._location.elevation + elevation_delta,
        #     )

        #     time.sleep(self.time_step)
        #     azimuth_time = time.monotonic() - azimuth_start_time
        #     ssc_log.debug(f"Moved to {self._location} [Azimuth time: {azimuth_time:.3f}]")
        #     self._write_csv(
        #         loc=self._location,
        #         elapsed=time.monotonic() - move_start_time,
        #         description=f"MOVE_{self._move_counter}_AZIMUTH",
        #         timestamp=datetime.datetime.now(),
        #     )

        #     if abs(self._location.azimuth - azimuth) < azimuth_margin:
        #         ssc_log.info(f"Finished azimuth movement in {azimuth_time:.3f}. Final location: {self._location}")
        #         break

        # # ELEVATION
        # elevation_start_time = time.monotonic()
        # elevation_to_move = elevation - self._location.elevation
        # elevation_direction = sign(elevation_to_move)
        # while True:
        #     # ASSUMPTION: The azimuth will have a little wobble
        #     azimuth_delta = random.gauss(0, 0.01)

        #     elevation_delta = elevation_direction * self.elevation_rotation_rate * self.time_step * random.gauss(1, 0.1)
        #     self._location = AzEl(
        #         azimuth=self._location.azimuth + azimuth_delta,
        #         elevation=self._location.elevation + elevation_delta,
        #     )
        #     time.sleep(self.time_step)
        #     elevation_time = time.monotonic() - elevation_start_time
        #     ssc_log.debug(f"Moved to {self._location} [Elevation time: {elevation_time:.3f}]")
        #     self._write_csv(
        #         loc=self._location,
        #         elapsed=time.monotonic() - move_start_time,
        #         description=f"MOVE_{self._move_counter}_ELEVATION",
        #         timestamp=datetime.datetime.now(),
        #     )

        #     if abs(self._location.elevation - elevation) < elevation_margin:
        #         ssc_log.info(f"Finished elevation movement in {elevation_time:.3f}. Final location: {self._location}")
        #         break
        ssc_log.info(
            # f"Finished movement in {time.monotonic() - move_start_time:.3f} Azimuth time: {azimuth_time:.3f}, Elevation time: {elevation_time:.3f} Final location: {self._location}"
            f"Finished movement in {time.monotonic() - move_start_time:.3f} Final location: {self._location}"
        )
        return self._location

    def get_location(self):
        return self._location


if __name__ == "__main__":
    random.seed(40351)
    ssc_log.init(level="DEBUG")
    if CSV_PATH.exists():
        CSV_PATH.unlink()
    turn_table = MockTurntable(
        start_location=AzEl(0, 0),
        csv_path=CSV_PATH,
        step_function=MockTurntable._step_concurrent,
    )

    # print(turn_table.get_location())
    turn_table.move_to(
        azimuth=5,
        elevation=5,
        azimuth_margin=0.1,
        elevation_margin=0.1,
    )
    turn_table.move_to(
        azimuth=3,
        elevation=7,
        azimuth_margin=0.1,
        elevation_margin=0.1,
    )
    turn_table.move_to(
        azimuth=1,
        elevation=-5,
        azimuth_margin=0.1,
        elevation_margin=0.1,
    )
    turn_table.move_to(
        azimuth=4,
        elevation=-7,
        azimuth_margin=0.1,
        elevation_margin=0.1,
    )

    import matplotlib.pyplot as plt
    import pandas as pd

    df = pd.read_csv(CSV_PATH, parse_dates=["timestamp"])
    timespan = df["timestamp"].max() - df["timestamp"].min()
    print(f"Total time: {timespan}")
    fig, ax = plt.subplots()

    for thing in df["description"].unique():
        subset = df[df["description"] == thing]
        ax.scatter(subset["azimuth"], subset["elevation"], label=thing, marker="o")

    ax.legend()
    ax.set_aspect('equal', adjustable='box')

    plt.show()

    # df.plot(x="timestamp", y=["azimuth", "elevation"])
