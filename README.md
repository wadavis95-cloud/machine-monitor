# Machine Monitor
[![CI](https://github.com/wadavis95-cloud/machine-monitor/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/wadavis95-cloud/machine-monitor/actions/workflows/ci.yml)

Machine Monitor replays NASA C-MAPSS jet engine sensor readings in a browser dashboard. You can inspect one engine or compare several engines as their readings change cycle by cycle. The dashboard also displays saved estimates of remaining useful life (RUL), the number of cycles an engine is expected to run before failure.

## Setup

Install Python 3.14, Node.js 24, and Make. Run these commands from the repository root on Linux or on an Apple silicon Mac with macOS 14 or newer.

```sh
python3.14 -m venv .venv
```

On Linux, install the CPU build of PyTorch before installing the rest of the dependencies. The Python tests import PyTorch to check the offline models.

```sh
.venv/bin/python -m pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
```

On both platforms, install the Python dependencies into `.venv`.

```sh
make setup
```

## Run

```sh
make run
```

Open [localhost:5002](http://localhost:5002) in your browser. The repository includes the sensor data and predictions CSV needed for the dashboard.

## Test

```sh
make check
```

This runs Ruff's lint and format checks, the Python tests with pytest, and the dashboard tests with Node's built-in test runner. GitHub Actions runs the same command.

## Data flow

```text
data/train_FD001.txt --> loader.py --> Flask API --> browser
                                         ^
                                         |
rul/ (offline) --> data/predictions_FD001.csv
```

- [Project glossary](GLOSSARY.md)
- [Architecture decision records](docs/adr/)
- [RUL model results](reports/rul_results.md)
