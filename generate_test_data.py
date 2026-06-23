"""
Generates realistic messy pings.csv and vehicles.csv for testing.
Includes the kinds of issues you'd actually see in telematics data.
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random

random.seed(42)
np.random.seed(42)

BASE_DATE = datetime(2024, 3, 1)
END_DATE = datetime(2024, 3, 31)


def date_range(start, days):
    return [start + timedelta(hours=i * 6) for i in range(days * 4)]


vehicles = [
    ("DEV001", "MH12AB1234", "Mahindra 575", "Pune", "individual"),
    ("DEV002", "MH04CD5678", "John Deere 5050", "Nashik", "dealer"),
    ("DEV003", "GJ05EF9012", "Sonalika 750", "Surat", "individual"),
    ("DEV004", "RJ14GH3456", "New Holland 3630", "Jaipur", "fleet"),
    ("DEV005", "MP09IJ7890", "Eicher 380", "Bhopal", "individual"),
    ("DEV006", "UP32KL2345", "Swaraj 855", "Lucknow", "dealer"),
    # No pings device
    ("DEV007", "TN22MN6789", "Kubota MU5501", "Chennai", "fleet"),
]

vehicles_df = pd.DataFrame(
    vehicles,
    columns=["device_id", "registration_no", "model", "region", "owner_type"],
)
vehicles_df.to_csv("data/vehicles.csv", index=False)
print(f"Written {len(vehicles_df)} vehicles")

rows = []

# DEV001 - clean active vehicle, moved recently
odo = 1200.0
for ts in date_range(BASE_DATE, 31):
    if random.random() > 0.3:
        odo += random.uniform(0, 15)
    rows.append(("DEV001", ts.isoformat(), random.choice([0, 1]), round(odo, 2)))

# DEV002 - odometer reset mid-period (device replaced)
odo = 8500.0
for i, ts in enumerate(date_range(BASE_DATE, 31)):
    if i == 40:  # reset
        odo = 120.0
    if random.random() > 0.4:
        odo += random.uniform(0, 20)
    rows.append(("DEV002", ts.isoformat(), random.choice([0, 1]), round(odo, 2)))

# DEV003 - inactive (last moved > 7 days ago)
odo = 4300.0
for ts in date_range(BASE_DATE, 24):  # stopped on march 24
    if random.random() > 0.5:
        odo += random.uniform(0, 8)
    rows.append(("DEV003", ts.isoformat(), random.choice([0, 1]), round(odo, 2)))
# flat pings after that
for ts in date_range(BASE_DATE + timedelta(days=24), 7):
    rows.append(("DEV003", ts.isoformat(), 0, round(odo, 2)))

# DEV004 - duplicate timestamps
odo = 200.0
timestamps = date_range(BASE_DATE, 31)
for ts in timestamps:
    if random.random() > 0.35:
        odo += random.uniform(0, 12)
    rows.append(("DEV004", ts.isoformat(), random.choice([0, 1]), round(odo, 2)))
    # inject duplicate
    if random.random() > 0.85:
        rows.append(("DEV004", ts.isoformat(), random.choice([0, 1]), round(odo + random.uniform(-2, 2), 2)))

# DEV005 - null/missing odometer values sprinkled in
odo = 670.0
for ts in date_range(BASE_DATE, 31):
    if random.random() > 0.4:
        odo += random.uniform(0, 10)
    odo_val = round(odo, 2) if random.random() > 0.1 else None  # 10% nulls
    rows.append(("DEV005", ts.isoformat(), random.choice([0, 1]), odo_val))

# DEV006 - negative odometer values (garbage from device firmware bug)
odo = 3100.0
for ts in date_range(BASE_DATE, 31):
    if random.random() > 0.3:
        odo += random.uniform(0, 18)
    odo_val = round(odo, 2) if random.random() > 0.05 else -999.0  # 5% garbage
    rows.append(("DEV006", ts.isoformat(), random.choice([0, 1]), odo_val))

# DEV007 - no pings at all (already handled by vehicles_df)

pings_df = pd.DataFrame(rows, columns=["device_id", "ts", "ignition", "odometer_km"])

# shuffle so order is not guaranteed
pings_df = pings_df.sample(frac=1, random_state=42).reset_index(drop=True)

pings_df.to_csv("data/pings.csv", index=False)
print(f"Written {len(pings_df)} pings")
print(f"Devices in pings: {pings_df['device_id'].nunique()}")
print(f"Null odometers: {pings_df['odometer_km'].isna().sum()}")
print(f"Negative odometers: {(pings_df['odometer_km'] < 0).sum()}")
