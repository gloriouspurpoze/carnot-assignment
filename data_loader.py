"""
data_loader.py — reads source CSVs, does nothing else.

Deliberately thin. The processor owns the business logic;
this just gets data off disk into DataFrames.
"""
from pathlib import Path

import pandas as pd


def load_pings(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"device_id": str})
    # don't parse ts here — processor handles bad timestamps as a data quality step
    return df


def load_vehicles(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"device_id": str})
