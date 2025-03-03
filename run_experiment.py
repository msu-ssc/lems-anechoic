from pathlib import Path
from msu_anechoic.experiment import Experiment

import argparse

argparser = argparse.ArgumentParser()
argparser.add_argument("--path", type=str, help="Path to the configuration file", required=True)
args = argparser.parse_args()

print(f"{args=}")
path = Path(args.path)
print(f"{path=}")
experiment = Experiment.run_file(path=path)