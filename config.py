import dataclasses
import json
from pathlib import Path
from typing import Literal


@dataclasses.dataclass
class Config:
    SPEC_AN_GPIB_ADDRESS: str = "GPIB1::18::INSTR"
    TURN_TABLE_SERIAL_PORT: str = "COM7"
    TURN_TABLE_BAUD_RATE: int = 9600
    AZIMUTH_MARGIN: float = 0.5
    ELEVATION_MARGIN: float = 0.5
    LOG_FOLDER_PATH_STR: str = "./logs"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    def log_folder_path(self) -> Path:
        return Path(self.LOG_FOLDER_PATH_STR)

    def to_json(self, path: Path) -> None:
        comment = "Modify the things in 'config' below to change the configuration. This file should be in the same directory as the controller script."
        data = {
            "comment": comment,
            "config": dataclasses.asdict(self),
        }
        path.write_text(json.dumps(data, indent=4))

    @classmethod
    def from_json(cls, path: Path) -> "Config":
        json_dict = json.loads(path.read_text())
        config_dict = json_dict["config"]
        return Config(**config_dict)


if __name__ == "__main__":
    config = Config()
    config.to_json(Path("config.json"))

    config2 = Config.from_json(Path("config.json"))
    print(config2)
