"""
processor.py — vehicle usage computation from raw telematics pings.

Separation of concerns: this module has zero knowledge of HTTP or file paths.
It takes DataFrames in, returns plain dicts out. Testable in isolation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class VehicleUsage:
    device_id: str
    registration_no: Optional[str]
    model: Optional[str]
    region: Optional[str]
    owner_type: Optional[str]
    total_distance_km: float
    active_days: int
    status: str  # "active" | "inactive" | "no_data"
    data_issues: list[str]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_distance_km"] = round(d["total_distance_km"], 2)
        return d


def _clean_pings(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Clean a single device's ping DataFrame.
    Returns (cleaned_df, list_of_issue_notes).

    Issues we handle:
    1. Non-parseable timestamps → drop row
    2. Duplicate timestamps → keep the row with the higher odometer (more travelled = more real)
    3. Null odometer values → drop row (can't contribute to distance)
    4. Negative odometer values → drop row (firmware garbage)
    5. Implausibly large single-hop jumps → drop that delta (>500 km in one ping interval is noise)
    """
    issues: list[str] = []
    df = raw.copy()

    # 1. Parse timestamps
    original_len = len(df)
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    bad_ts = df["ts"].isna().sum()
    if bad_ts:
        issues.append(f"{bad_ts} row(s) with unparseable timestamps dropped")
    df = df.dropna(subset=["ts"])

    # 2. Coerce odometer to numeric (catches strings like "N/A", "-")
    df["odometer_km"] = pd.to_numeric(df["odometer_km"], errors="coerce")

    # 3. Drop null odometers
    null_odo = df["odometer_km"].isna().sum()
    if null_odo:
        issues.append(f"{null_odo} row(s) with null odometer dropped")
    df = df.dropna(subset=["odometer_km"])

    # 4. Drop negative odometers (firmware bug / sentinel values like -999)
    neg_odo = (df["odometer_km"] < 0).sum()
    if neg_odo:
        issues.append(f"{neg_odo} row(s) with negative odometer dropped")
    df = df[df["odometer_km"] >= 0]

    # 5. Sort by time before anything else
    df = df.sort_values("ts").reset_index(drop=True)

    # 6. Duplicate timestamps: keep max odometer per timestamp
    dupes = df.duplicated(subset=["ts"], keep=False).sum()
    if dupes:
        issues.append(f"{dupes} row(s) with duplicate timestamps collapsed (kept max odometer)")
    df = df.groupby("ts", as_index=False)["odometer_km"].max()
    df = df.sort_values("ts").reset_index(drop=True)

    if len(df) < original_len and not issues:
        issues.append(f"{original_len - len(df)} rows dropped in cleaning")

    return df, issues


def _compute_distance(df: pd.DataFrame) -> tuple[float, list[str]]:
    """
    Sum odometer increases between consecutive pings in time order.

    Rules:
    - Decrease → device reset/replacement, don't count (skip that delta)
    - Zero → vehicle parked, fine
    - Implausibly large jump (>500 km between consecutive pings) → skip (sensor spike)

    Returns (total_km, additional_issue_notes)
    """
    MAX_SINGLE_HOP_KM = 500.0
    issues: list[str] = []

    if len(df) < 2:
        return 0.0, issues

    deltas = df["odometer_km"].diff().iloc[1:]  # skip NaN at index 0

    resets = (deltas < 0).sum()
    if resets:
        issues.append(f"{resets} odometer reset(s) detected and skipped")

    spikes = ((deltas > 0) & (deltas > MAX_SINGLE_HOP_KM)).sum()
    if spikes:
        issues.append(f"{spikes} implausibly large jump(s) (>{MAX_SINGLE_HOP_KM} km) skipped")

    valid_deltas = deltas[(deltas > 0) & (deltas <= MAX_SINGLE_HOP_KM)]
    return float(valid_deltas.sum()), issues


def _compute_active_days(df: pd.DataFrame) -> int:
    """
    Count distinct calendar days on which the vehicle actually moved
    (i.e. had at least one positive odometer delta on that day).
    """
    if len(df) < 2:
        return 0

    df = df.copy()
    df["delta"] = df["odometer_km"].diff()
    df["date"] = df["ts"].dt.date

    moved = df[df["delta"] > 0]
    return moved["date"].nunique()


def _compute_status(df: pd.DataFrame, period_end: date) -> str:
    """
    active   → moved at least once in the last 7 days of the data period
    inactive → has data but didn't move in the last 7 days
    no_data  → no pings at all
    """
    if df.empty:
        return "no_data"

    window_start = period_end - timedelta(days=7)
    recent = df[df["ts"].dt.date > window_start]

    if len(recent) < 2:
        return "inactive"

    recent_deltas = recent["odometer_km"].diff().iloc[1:]
    moved = (recent_deltas > 0).any()
    return "active" if moved else "inactive"


def compute_all_vehicles(
    pings_df: pd.DataFrame,
    vehicles_df: pd.DataFrame,
) -> dict[str, VehicleUsage]:
    """
    Main entry point. Compute usage for every vehicle in vehicles_df.
    Returns a dict keyed by device_id.
    """
    # Infer the end of the data period from the pings themselves
    if not pings_df.empty:
        pings_df = pings_df.copy()
        pings_df["ts"] = pd.to_datetime(pings_df["ts"], errors="coerce")
        period_end: date = pings_df["ts"].dropna().max().date()
    else:
        period_end = date.today()

    log.info("Data period end: %s", period_end)

    results: dict[str, VehicleUsage] = {}

    for _, vehicle in vehicles_df.iterrows():
        device_id = vehicle["device_id"]
        vehicle_pings = pings_df[pings_df["device_id"] == device_id].copy()

        vehicle_meta = {
            "registration_no": vehicle.get("registration_no"),
            "model": vehicle.get("model"),
            "region": vehicle.get("region"),
            "owner_type": vehicle.get("owner_type"),
        }

        if vehicle_pings.empty:
            results[device_id] = VehicleUsage(
                device_id=device_id,
                **vehicle_meta,
                total_distance_km=0.0,
                active_days=0,
                status="no_data",
                data_issues=["no pings found for this device"],
            )
            continue

        cleaned, clean_issues = _clean_pings(vehicle_pings)
        distance, dist_issues = _compute_distance(cleaned)
        active_days = _compute_active_days(cleaned)
        status = _compute_status(cleaned, period_end)

        all_issues = clean_issues + dist_issues

        results[device_id] = VehicleUsage(
            device_id=device_id,
            **vehicle_meta,
            total_distance_km=distance,
            active_days=active_days,
            status=status,
            data_issues=all_issues,
        )

        log.info(
            "%s → %.1f km, %d active days, %s, issues: %s",
            device_id, distance, active_days, status, all_issues or "none",
        )

    return results
