"""
Tests for the parts most likely to be wrong:
- odometer reset handling
- active_days counting
- status boundary (exactly 7 days)
- data quality filtering
"""
import pytest
import pandas as pd
from datetime import datetime, timedelta, date

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from processor import (
    _clean_pings,
    _compute_distance,
    _compute_active_days,
    _compute_status,
    compute_all_vehicles,
)


def make_pings(readings: list[tuple]) -> pd.DataFrame:
    """Helper: [(ts_offset_hours, odometer), ...]"""
    base = datetime(2024, 3, 1)
    rows = []
    for hours, odo in readings:
        rows.append({
            "device_id": "TEST",
            "ts": (base + timedelta(hours=hours)).isoformat(),
            "ignition": 1,
            "odometer_km": odo,
        })
    return pd.DataFrame(rows)


# ── Distance calculation ────────────────────────────────────────────────────

class TestComputeDistance:
    def test_simple_increasing(self):
        df = make_pings([(0, 100), (1, 110), (2, 125)])
        cleaned, _ = _clean_pings(df)
        dist, issues = _compute_distance(cleaned)
        assert dist == pytest.approx(25.0)
        assert issues == []

    def test_odometer_reset_not_counted(self):
        """Device replaced mid-period: 100→200→50→150. Should give 100+100=200, not 250."""
        df = make_pings([(0, 100), (1, 200), (2, 50), (3, 150)])
        cleaned, _ = _clean_pings(df)
        dist, issues = _compute_distance(cleaned)
        assert dist == pytest.approx(200.0)
        assert any("reset" in i for i in issues)

    def test_flat_odometer_zero_distance(self):
        """Parked vehicle: no movement."""
        df = make_pings([(0, 500), (1, 500), (2, 500)])
        cleaned, _ = _clean_pings(df)
        dist, _ = _compute_distance(cleaned)
        assert dist == pytest.approx(0.0)

    def test_spike_filtered(self):
        """A single 600 km jump between pings should be skipped as implausible."""
        df = make_pings([(0, 100), (1, 700), (2, 710)])
        cleaned, _ = _clean_pings(df)
        dist, issues = _compute_distance(cleaned)
        # 600 km skipped, only 10 km counted
        assert dist == pytest.approx(10.0)
        assert any("implausibly large" in i for i in issues)

    def test_single_ping_zero_distance(self):
        df = make_pings([(0, 100)])
        cleaned, _ = _clean_pings(df)
        dist, _ = _compute_distance(cleaned)
        assert dist == pytest.approx(0.0)


# ── Active days ─────────────────────────────────────────────────────────────

class TestActiveDays:
    def test_counts_days_with_movement(self):
        # movement on day 1 and day 3, nothing on day 2
        df = make_pings([
            (0, 100), (1, 110),   # day 1, moved
            (24, 110), (25, 110), # day 2, parked
            (48, 110), (49, 120), # day 3, moved
        ])
        cleaned, _ = _clean_pings(df)
        assert _compute_active_days(cleaned) == 2

    def test_no_movement_zero_days(self):
        df = make_pings([(0, 100), (24, 100), (48, 100)])
        cleaned, _ = _clean_pings(df)
        assert _compute_active_days(cleaned) == 0


# ── Status ───────────────────────────────────────────────────────────────────

class TestComputeStatus:
    def _df_with_dates(self, readings: list[tuple]) -> pd.DataFrame:
        """readings: [(date_obj, odometer)]"""
        rows = [{"ts": pd.Timestamp(d), "odometer_km": odo} for d, odo in readings]
        return pd.DataFrame(rows)

    def test_active_moved_within_7_days(self):
        period_end = date(2024, 3, 31)
        df = self._df_with_dates([
            (date(2024, 3, 25), 100),
            (date(2024, 3, 26), 120),  # moved, within 7 days of period end
        ])
        assert _compute_status(df, period_end) == "active"

    def test_inactive_last_moved_8_days_ago(self):
        period_end = date(2024, 3, 31)
        df = self._df_with_dates([
            (date(2024, 3, 1), 100),
            (date(2024, 3, 23), 200),  # last movement 8 days before period end
            (date(2024, 3, 24), 200),
            (date(2024, 3, 31), 200),  # pings exist but no movement
        ])
        assert _compute_status(df, period_end) == "inactive"

    def test_no_data(self):
        assert _compute_status(pd.DataFrame(), date(2024, 3, 31)) == "no_data"


# ── Data cleaning ─────────────────────────────────────────────────────────

class TestCleanPings:
    def test_negative_odometer_dropped(self):
        df = make_pings([(0, 100), (1, -999), (2, 110)])
        cleaned, issues = _clean_pings(df)
        assert (cleaned["odometer_km"] < 0).sum() == 0
        assert any("negative" in i for i in issues)

    def test_null_odometer_dropped(self):
        df = make_pings([(0, 100), (1, 105)])
        df.loc[1, "odometer_km"] = None
        cleaned, issues = _clean_pings(df)
        assert len(cleaned) == 1
        assert any("null" in i for i in issues)

    def test_duplicate_timestamps_resolved(self):
        """Duplicate ts: keep the higher odometer."""
        base = datetime(2024, 3, 1)
        ts = base.isoformat()
        df = pd.DataFrame([
            {"device_id": "TEST", "ts": ts, "ignition": 1, "odometer_km": 100},
            {"device_id": "TEST", "ts": ts, "ignition": 0, "odometer_km": 105},  # duplicate, higher
        ])
        cleaned, issues = _clean_pings(df)
        assert len(cleaned) == 1
        assert cleaned.iloc[0]["odometer_km"] == 105
        assert any("duplicate" in i for i in issues)

    def test_unsorted_input_sorted_after_clean(self):
        """Input in reverse time order — output should be sorted."""
        df = make_pings([(2, 120), (0, 100), (1, 110)])
        cleaned, _ = _clean_pings(df)
        assert list(cleaned["odometer_km"]) == [100, 110, 120]


# ── Integration: full pipeline ────────────────────────────────────────────

class TestIntegration:
    def test_no_data_vehicle(self):
        pings = pd.DataFrame(columns=["device_id", "ts", "ignition", "odometer_km"])
        vehicles = pd.DataFrame([{
            "device_id": "GHOST",
            "registration_no": "XX00XX0000",
            "model": "Unknown",
            "region": "Unknown",
            "owner_type": "individual",
        }])
        results = compute_all_vehicles(pings, vehicles)
        assert results["GHOST"].status == "no_data"
        assert results["GHOST"].total_distance_km == 0.0
