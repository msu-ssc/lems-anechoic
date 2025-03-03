import math
from pathlib import Path
import random
from typing import Generator, List
from typing import Literal

import numpy as np
import pydantic
from msu_ssc import path_util

from msu_anechoic import AzElTurntable
from msu_anechoic import Coordinate

EXPERIMENTS_FOLDER_PATH = Path("./experiments")


class Grid(pydantic.BaseModel):
    min_azimuth: float
    max_azimuth: float
    azimuth_step_size: float
    min_elevation: float
    max_elevation: float
    elevation_step_size: float
    orientation: Literal["horizontal", "vertical"]
    kind: Literal["antenna", "turntable"] = "antenna"
    neutral_elevation: float = 0.0

    def azimuths(self):
        return list(np.arange(self.min_azimuth, self.max_azimuth + self.azimuth_step_size, self.azimuth_step_size))

    def elevations(self):
        return list(
            np.arange(self.min_elevation, self.max_elevation + self.elevation_step_size, self.elevation_step_size)
        )

    def cuts(self) -> Generator[list[Coordinate], None, None]:
        cut_angles = self.elevations() if self.orientation == "horizontal" else self.azimuths()
        for cut_index, cut_angle in enumerate(cut_angles):
            should_reverse = cut_index % 2 == 1
            yield self.points_for_cut(cut_angle=cut_angle, should_reverse=should_reverse)

    def points_for_cut(self, cut_angle: float, should_reverse: bool = False) -> list[Coordinate]:
        this_cut_angles = self.azimuths() if self.orientation == "horizontal" else self.elevations()
        if should_reverse:
            this_cut_angles = list(reversed(this_cut_angles))

        points: list[Coordinate] = []
        for this_cut_angle in this_cut_angles:
            if self.orientation == "horizontal":
                azimuth = this_cut_angle
                elevation = cut_angle
            else:
                azimuth = cut_angle
                elevation = this_cut_angle

            if self.kind == "antenna":
                point = Coordinate.from_antenna(
                    azimuth=azimuth, elevation=elevation, neutral_elevation=self.neutral_elevation
                )
            elif self.kind == "turntable":
                point = Coordinate.from_turntable(
                    azimuth=azimuth, elevation=elevation, neutral_elevation=self.neutral_elevation
                )
            else:
                raise ValueError(f"Invalid `kind` value: {self.kind}")
            points.append(point)
        return points


class SpecAnConfig(pydantic.BaseModel):
    initial_center_frequency: float
    spans_when_searching: list[float]
    reference_level: float = -10


class SigGenConfig(pydantic.BaseModel):
    center_frequency: float
    power: float
    vernier_power: float


class ExperimentParameters(pydantic.BaseModel):
    short_description: str = "default"
    long_description: str = "default"

    relative_folder_path: Path | None = None
    raw_data_csv_path: Path | None = None
    metadata_json_path: Path | None = None
    log_jsonl_path: Path | None = None
    log_plaintext_path: Path | None = None

    grid: Grid | None = None
    points: list[AzElTurntable] | None = None

    desired_sig_gen_config: SigGenConfig | None = None
    actual_start_sig_gen_config: SigGenConfig | None = None
    actual_finish_sig_gen_config: SigGenConfig | None = None

    desired_spec_an_config: SpecAnConfig | None = None
    actual_start_spec_an_config: SpecAnConfig | None = None
    actual_finish_spec_an_config: SpecAnConfig | None = None

    # experiment_start_time_utc: datetime.datetime | None = None
    # experiment_finish_time_utc: datetime.datetime | None = None
    points: dict[int, AzElTurntable] | None = None
    # az_el_cls: Literal["AzElSpherical", "AzElTurntable"] | None = None

    @pydantic.model_validator(mode="after")
    def _after_validator(self) -> None:
        if self.relative_folder_path is None:
            self.relative_folder_path = path_util.clean_path(EXPERIMENTS_FOLDER_PATH / self.short_description)
        if self.raw_data_csv_path is None:
            self.raw_data_csv_path = self.relative_folder_path / "raw_data.csv"
        if self.metadata_json_path is None:
            self.metadata_json_path = self.relative_folder_path / "experiment_metadata.json"
        if self.log_jsonl_path is None:
            self.log_jsonl_path = self.relative_folder_path / "logs" / "log.jsonl"
        if self.log_plaintext_path is None:
            self.log_plaintext_path = self.relative_folder_path / "logs" / "log.txt"

        if self.grid is not None and self.points is not None:
            raise ValueError("Cannot have both `grid` and `points`")
        elif self.grid is None and self.points is None:
            raise ValueError("Must have either `grid` or `points`")

    # @property
    # def experiment_folder_path(self) -> Path:
    #     return path_util.clean_path(EXPERIMENTS_FOLDER_PATH / self.short_description).expanduser().resolve()

    def write_metadata(self) -> None:
        parent = self.metadata_json_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        self.metadata_json_path.write_text(self.model_dump_json(indent=4))


def run_experiment(
    *,
    parameters: ExperimentParameters,
) -> None:
    from msu_anechoic.spec_an import SpectrumAnalyzerHP8563E
    from msu_anechoic.turn_table import Turntable

    # TODO: Make log params part of the config
    # isort: off
    from msu_ssc import ssc_log

    ssc_log.init(
        level="DEBUG",
        plain_text_file_path=parameters.log_plaintext_path,
        jsonl_file_path=parameters.log_jsonl_path,
    )
    logger = ssc_log.logger.getChild("experiment")
    # isort: on

    # CONNECT TO TURNTABLE
    turn_table = Turntable.find(
        logger=logger.getChild("turntable"),
    )
    if turn_table is None:
        raise ValueError("Could not find turn table")

    # CONNECT TO SPECTRUM ANALYZER
    spec_an = SpectrumAnalyzerHP8563E.find(
        logger=logger.getChild("spec_an"),
    )
    if spec_an is None:
        raise ValueError("Could not find spectrum analyzer")

    # CONFIGURE SPEC AN
    # TODO: Write this method
    spec_an.configure(parameters.desired_spec_an_config)
    center_frequency = spec_an.move_center_to_peak(
        center_frequency=parameters.desired_spec_an_config.initial_center_frequency,
        spans=parameters.desired_spec_an_config.spans_when_searching,
    )
    spec_an.set_reference_level(-10)

    # CONFIGURE SIG GEN
    # This is manual for now
    while True:
        print("Configure the signal generator manually to these settings:")
        print(f"{parameters.desired_sig_gen_config.model_dump_json(indent=4)}")
        user_input = input("Is the signal generator configured correctly? (y/n): ")
        if user_input.lower() == "y":
            break
        else:
            print("Trying again . . . \n")

    # CONFIGURE TURNTABLE
    turn_table.interactively_center()

    # RUN EXPERIMENT
    # TODO



class GeneticAlgorithm:
    def __init__(self, xs: List[float], ys: List[float], population_size=100, generations=500, mutation_rate=0.02):
        self.xs = xs
        self.ys = ys
        self.n = len(xs)
        self.population_size = population_size
        self.generations = generations
        self.mutation_rate = mutation_rate
        self.population = [random.sample(range(self.n), self.n) for _ in range(population_size)]
    
    def distance(self, i: int, j: int) -> float:
        return calc_distance(self.xs[i], self.xs[j], self.ys[i], self.ys[j])
        return math.sqrt((self.xs[i] - self.xs[j]) ** 2 + (self.ys[i] - self.ys[j]) ** 2)
    
    def total_distance(self, path: List[int]) -> float:
        return sum(self.distance(path[i], path[i + 1]) for i in range(len(path) - 1))
    
    def crossover(self, parent1: List[int], parent2: List[int]) -> List[int]:
        size = len(parent1)
        start, end = sorted(random.sample(range(size), 2))
        child = [-1] * size
        child[start:end] = parent1[start:end]
        
        p2_idx = 0
        for i in range(size):
            if child[i] == -1:
                while parent2[p2_idx] in child:
                    p2_idx += 1
                child[i] = parent2[p2_idx]
        
        return child
    
    def mutate(self, path: List[int]) -> List[int]:
        if random.random() < self.mutation_rate:
            a, b = sorted(random.sample(range(len(path)), 2))
            path[a], path[b] = path[b], path[a]
        return path
    
    def evolve(self):
        for _ in range(self.generations):
            self.population.sort(key=self.total_distance)
            new_population = self.population[:10]
            
            while len(new_population) < self.population_size:
                parent1, parent2 = random.sample(self.population[:50], 2)
                child = self.crossover(parent1, parent2)
                new_population.append(self.mutate(child))
            
            self.population = new_population
        
        return self.population[0]

if __name__ == "__main__":
    from msu_anechoic.util.grid import estimated_step_time

    spec_an_config = SpecAnConfig(
        initial_center_frequency=8_450_000_000,
        spans_when_searching=[
            1_000_000,
            100_000,
            10_000,
            1_000,
        ],
    )
    sig_gen_config = SigGenConfig(center_frequency=8_450_000_000, power=-10, vernier_power=0)
    # points = {
    #     0: AzElTurntable(azimuth=-5, elevation=5),
    #     1: AzElTurntable(azimuth=5, elevation=5),
    #     # 2: AzElTurntable(azimuth=-5, elevation=-5),
    #     # 3: AzElTurntable(azimuth=5, elevation=-5),
    # }
    grid = Grid(
        min_azimuth=-10,
        max_azimuth=10,
        azimuth_step_size=4,
        min_elevation=-2,
        max_elevation=2,
        elevation_step_size=1,
        orientation="horizontal",
    )
    experiment = ExperimentParameters(
        short_description="3x3 8.45 GHz",
        long_description="Initial test of a 3x3 grid at 8.45 GHz",
        desired_spec_an_config=spec_an_config,
        desired_sig_gen_config=sig_gen_config,
        # points=points,
        grid=grid,
        # folder=Path("./experiments/mayo01"),
        # az_el_cls="AzElSpherical",
    )
    print(f"{experiment=}")
    print(experiment.model_dump_json(indent=4))

    experiment_2 = ExperimentParameters.model_validate_json(experiment.model_dump_json())
    print(f"{experiment_2=}")

    experiment.write_metadata()

    grid = Grid(
        min_azimuth=-20,
        max_azimuth=20,
        azimuth_step_size=1,
        min_elevation=-20,
        max_elevation=20,
        elevation_step_size=10,
        orientation="horizontal",
        # kind="turntable",
        kind="antenna",
    )

    def calc_distance(az1, az2, el1, el2) -> float:
        azimuth_diff = abs(az1 - az2)
        elevation_diff = abs(el1 - el2)
        # return math.sqrt(azimuth_diff ** 2 + elevation_diff ** 2)
        # return max(azimuth_diff, elevation_diff)
        return estimated_step_time(azimuth=azimuth_diff, elevation=elevation_diff)

    index = 0
    all_points: list[Coordinate] = []
    for cut_index, cut in enumerate(grid.cuts()):
        print(f"Cut {cut_index}:")
        for point_index, point in enumerate(cut):
            print(f"  {cut_index=}, {point_index=}, {index=}: {point}")
            all_points.append(point)
            index += 1

    reachable_points = [point for point in all_points if point.absolute_turntable_elevation <= 45]
    unreachable_points = [point for point in all_points if point.absolute_turntable_elevation > 45]

    import matplotlib.pyplot as plt

    fig, [[ax1, ax2], [ax3, ax4]] = plt.subplots(
        2,
        2,
        # layout="constrained",
    )
    ax1: plt.Axes
    ax2: plt.Axes
    ax3: plt.Axes
    ax4: plt.Axes

    def path_distance(points: list[Coordinate]) -> float:
        distance = 0
        for index, (p1, p2) in enumerate(zip(points[:-1], points[1:])):
            this_distance = calc_distance(p1.turntable_azimuth, p2.turntable_azimuth, p1.turntable_elevation, p2.turntable_elevation)
            distance += this_distance
        return distance

    # Ensure all subplots have equal aspect ratio
    for ax in [ax1, ax2, ax3, ax4]:
        ax.set_aspect("equal", adjustable="box")
        ax.set_xticks(np.arange(-180, 181, 45))
        ax.set_yticks(np.arange(-90, 91, 15))
        ax.grid(True)

    # TURNTABLE COORDS
    tt_azs = [point.turntable_azimuth for point in reachable_points]
    tt_els = [point.turntable_elevation for point in reachable_points]
    tt_indexes = list(range(len(reachable_points)))
    ax1.plot(tt_azs, tt_els, "o-")
    naive_path_distance = path_distance(reachable_points)
    ax1.set_title(f"Turntable coordinates (naive traversal)\n({naive_path_distance:,.0f} seconds)")
    ax1.set_xlabel("Pan")
    ax1.set_ylabel("Tilt")
    for i, txt in enumerate(tt_indexes):
        ax1.annotate(txt, (tt_azs[i], tt_els[i]))
    # ax1.set_xlim(-180, 180)
    # ax1.set_ylim(-90, 90)
    # Plot unreachable points with red X's
    unreachable_tt_azs = [point.turntable_azimuth for point in unreachable_points]
    unreachable_tt_els = [point.turntable_elevation for point in unreachable_points]
    ax1.scatter(unreachable_tt_azs, unreachable_tt_els, c='red', marker='x')

    unreachable_ant_azs = [point.antenna_azimuth for point in unreachable_points]
    unreachable_ant_els = [point.antenna_elevation for point in unreachable_points]
    ax2.scatter(unreachable_ant_azs, unreachable_ant_els, c='red', marker='x')

    ax3.scatter(unreachable_tt_azs, unreachable_tt_els, c='red', marker='x')
    ax4.scatter(unreachable_ant_azs, unreachable_ant_els, c='red', marker='x')

    # ANTENNA COORDS
    ant_azs = [point.antenna_azimuth for point in reachable_points]
    ant_els = [point.antenna_elevation for point in reachable_points]
    ant_indexes = list(range(len(reachable_points)))

    ax2.plot(ant_azs, ant_els, "o--")
    ax2.set_title(f"Antenna coordinates (naive traversal)\n({naive_path_distance:,.0f} seconds)")
    ax2.set_xlabel("Azimuth")
    ax2.set_ylabel("Elevation")
    for i, txt in enumerate(ant_indexes):
        ax2.annotate(txt, (ant_azs[i], ant_els[i]))
    # ax2.set_xlim(-180, 180)
    # ax2.set_ylim(-90, 90)

    def shortest_path(xs: List[float], ys: List[float], path: List[int] = None) -> List[int]:
        """Find the shortest path through the points by optimizing an initially given path.
        
        Return the indexes of the points in the order they should be visited.
        """
        import time

        def distance(i: int, j: int) -> float:
            return calc_distance(xs[i], xs[j], ys[i], ys[j])
            return math.sqrt((xs[i] - xs[j]) ** 2 + (ys[i] - ys[j]) ** 2)
        
        def total_distance(path: List[int]) -> float:
            return sum(distance(path[i], path[i + 1]) for i in range(len(path) - 1))
        
        def swap_2opt(path: List[int]) -> List[int]:
            a, b = sorted(random.sample(range(len(path)), 2))
            return path[:a] + path[a:b+1][::-1] + path[b+1:]
        
        n = len(xs)
        if n == 0:
            return []
        
        if path is None:
            path = list(range(n))  # Default to sequential order if no initial path is given
        
        # return path

        start_distance = total_distance(path)
        print(f"Initial path: {start_distance}")
        # Iterative 2-opt optimization
        improved = True
        start_time = time.monotonic()
        while improved:
            
            improved = False
            for i in range(1, n - 2):
                for j in range(i + 1, n - 1):
                    new_path = path[:i] + path[i:j+1][::-1] + path[j+1:]
                    elapsed_time = time.monotonic() - start_time
                    if elapsed_time > 150:
                        print(f"Time limit reached: {elapsed_time:.2f} seconds")
                        break
                    if total_distance(new_path) < total_distance(path):
                        print(f"Improved path: {total_distance(new_path):.2f} < {total_distance(path):.2f} (started at distance={start_distance:.2f}) ({elapsed_time:,.2f} seconds optimizing)")
                        path = new_path
                        improved = True
        
        return path

    # path = shortest_path(ant_azs, ant_els)
    path = shortest_path(tt_azs, tt_els)

    new_points = [reachable_points[i] for i in path]
    new_path_distance = path_distance(new_points)

    # Plot Turntable coordinates in the order specified by path
    tt_azs_path = [point.turntable_azimuth for point in new_points]
    tt_els_path = [point.turntable_elevation for point in new_points]
    ax3.plot(tt_azs_path, tt_els_path, "o-")
    ax3.set_title(f"Turntable coordinates (Optimized path)\n({new_path_distance:,.0f} seconds)")
    ax3.set_xlabel("Pan")
    ax3.set_ylabel("Tilt")
    for i, txt in enumerate(path):
        ax3.annotate(i, (tt_azs_path[i], tt_els_path[i]))

    # Plot Antenna coordinates in the order specified by path
    ant_azs_path = [point.antenna_azimuth for point in new_points]
    ant_els_path = [point.antenna_elevation for point in new_points]
    ax4.plot(ant_azs_path, ant_els_path, "o--")
    ax4.set_title(f"Antenna coordinates (Optimized path)\n({new_path_distance:,.0f} seconds)")
    ax4.set_xlabel("Azimuth")
    ax4.set_ylabel("Elevation")
    for i, txt in enumerate(path):
        ax4.annotate(i, (ant_azs_path[i], ant_els_path[i]))

    print(f"{path=}")

    plt.show()
