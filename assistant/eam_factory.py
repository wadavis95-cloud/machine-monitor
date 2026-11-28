"""Select the configured EAM for assistant runs and draft requests."""

from assistant.eam_contract import EAM
from assistant.hexagon_eam import HexagonEAM
from assistant.sqlite_eam import SQLiteEAM


def create_eam(config) -> EAM:
    name = config["EAM_ADAPTER"]
    if name == "sqlite":
        return SQLiteEAM(config["EAM_PATH"])
    if name == "hexagon":
        return HexagonEAM(config["HEXAGON_URL"], config["HEXAGON_API_KEY"])
    raise ValueError(f"Unknown EAM_ADAPTER: {name!r}. Choose sqlite or hexagon.")
