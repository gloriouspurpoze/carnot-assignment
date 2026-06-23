"""
api.py — HTTP layer only. No business logic lives here.

Startup loads & processes data once into memory.
GET /vehicles/{device_id}/usage does a dict lookup.
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from data_loader import load_pings, load_vehicles
from processor import VehicleUsage, compute_all_vehicles

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

PINGS_PATH = Path(os.getenv("PINGS_CSV", "data/pings.csv"))
VEHICLES_PATH = Path(os.getenv("VEHICLES_CSV", "data/vehicles.csv"))

# In-memory store — keyed by device_id
_store: dict[str, VehicleUsage] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Loading data from %s and %s", PINGS_PATH, VEHICLES_PATH)
    pings = load_pings(PINGS_PATH)
    vehicles = load_vehicles(VEHICLES_PATH)
    computed = compute_all_vehicles(pings, vehicles)
    _store.update(computed)
    log.info("Loaded %d vehicles", len(_store))
    yield
    _store.clear()


app = FastAPI(
    title="Carnot Vehicle Usage API",
    description="Telematics usage summary per vehicle.",
    lifespan=lifespan,
)


@app.get("/vehicles/{device_id}/usage")
def get_vehicle_usage(device_id: str) -> Any:
    usage = _store.get(device_id)
    if usage is None:
        raise HTTPException(status_code=404, detail=f"device_id '{device_id}' not found")
    return JSONResponse(content=usage.to_dict())


@app.get("/health")
def health():
    return {"status": "ok", "vehicles_loaded": len(_store)}


# cron every hour to compute the usage for all vehicles grouped by device id 
f'''
{
    "device_id": "1234567890",
    "registration_no": "1234567890",
    "ActiveDays": 10,
    "TotalDistanceKm": 1000,
    "Status": "Active",
    "DataIssues": ["No data"],
    "lastcomputed": "2026-06-24T12:00:00Z",
}
'''