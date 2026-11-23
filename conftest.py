from contextlib import closing
from pathlib import Path

import pytest

from assistant import eam, tools
from assistant.seed import build_eam
from loader import load_data

DATA_DIR = Path(__file__).with_name("data")


@pytest.fixture
def ctx(tmp_path):
    db_path = tmp_path / "eam.sqlite"
    readings = load_data(DATA_DIR / "train_FD001.txt")
    predictions = eam.load_predictions(DATA_DIR / "predictions_FD001.csv")
    build_eam(db_path, readings, predictions, seed=0)
    return tools.load_context(db_path, DATA_DIR)


@pytest.fixture
def conn(ctx):
    with closing(eam.connect(ctx.db_path)) as connection:
        yield connection
