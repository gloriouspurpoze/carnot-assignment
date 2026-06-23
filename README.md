# Carnot Vehicle Usage Service

## How to run

From the project root (`carnot/`). Defaults use `data/pings.csv` and `data/vehicles.csv`.

### 1. Install dependencies

**macOS / Linux (bash or zsh)**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows PowerShell**

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Windows CMD**

```cmd
python -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt
```

### 2. Start the API server

**macOS / Linux**

```bash
# Default CSV paths (data/pings.csv, data/vehicles.csv)
uvicorn api:app --reload

# Or set paths explicitly:
PINGS_CSV=data/pings.csv VEHICLES_CSV=data/vehicles.csv uvicorn api:app --reload
```

**Windows PowerShell**

```powershell
# Default CSV paths
uvicorn api:app --reload

# Or set paths explicitly:
$env:PINGS_CSV="data/pings.csv"; $env:VEHICLES_CSV="data/vehicles.csv"; uvicorn api:app --reload
```

**Windows CMD**

```cmd
REM Default CSV paths
uvicorn api:app --reload

REM Or set paths explicitly:
set PINGS_CSV=data\pings.csv
set VEHICLES_CSV=data\vehicles.csv
uvicorn api:app --reload
```

Server runs at `http://localhost:8000`.

**Troubleshooting: `WinError 10013` on Windows**

Port 8000 is already in use (often a leftover `uvicorn` process). Either stop it or use another port:

```powershell
# See what is using port 8000
netstat -ano | findstr ":8000"

# Stop the process (replace 12345 with the PID from the last column)
taskkill /PID 12345 /F

# Or start on a different port
uvicorn api:app --reload --port 8080
```

### 3. Try the endpoints

**macOS / Linux**

```bash
curl http://localhost:8000/vehicles/DEV001/usage
curl http://localhost:8000/health
```

**Windows PowerShell**

```powershell
curl http://localhost:8000/vehicles/DEV001/usage
curl http://localhost:8000/health
```

**Windows CMD**

```cmd
curl http://localhost:8000/vehicles/DEV001/usage
curl http://localhost:8000/health
```

### 4. Run tests

**macOS / Linux**

```bash
pytest tests/ -v
```

**Windows PowerShell**

```powershell
pytest tests/ -v
```

**Windows CMD**

```cmd
pytest tests/ -v
```

---

## Data issues found (and how they're handled)

| Issue | How handled |
|---|---|
| **Odometer resets / device replacements** | Negative deltas between consecutive readings are skipped entirely. Only increases count toward distance. |
| **Duplicate timestamps** | Same device + same timestamp with different odometer values — kept the higher reading (more travelled = more likely the real value), collapsed to one row. |
| **Null / missing odometer values** | Rows dropped. Can't derive a delta without both endpoints. |
| **Negative odometer values** | Rows dropped. These are firmware sentinel values (-999 etc.), not real readings. |
| **Implausibly large single-hop jumps** | Deltas > 500 km between consecutive pings are skipped as sensor spikes. The threshold is a judgement call — tunable. |
| **Unsorted input** | Pings sorted by timestamp before any delta computation. |
| **Vehicles with zero pings** | Returned with `status: no_data`, `total_distance_km: 0`. |

Each response includes a `data_issues` field listing what was found per vehicle, so nothing silently disappears.

---

## How I used AI tools

Used Claude throughout, mostly as a pair-programmer to:
- Cross-check the odometer delta edge cases (reset vs. spike vs. legit jump)
- Generate realistic messy test data covering each issue type
- Gut-check the `active_days` definition (days with at least one positive delta, not just days with pings)

The judgement calls (500 km spike threshold, duplicate resolution strategy, period_end inference from max timestamp) were mine. 

Let me be perfectly honest!! AI generated the whole code and i just happen to understand your requirement and guide it in the key decisions and learn fastAPI pretty fast to get you this solution "
---

## Structure

```
api.py           — HTTP layer only (FastAPI). No business logic.
processor.py     — All computation: cleaning, distance, active_days, status.
data_loader.py   — Reads CSVs. Nothing else.
tests/
  test_processor.py — Edge cases on the parts easy to get wrong.
data/
  pings.csv
  vehicles.csv
generate_test_data.py — Generates realistic messy test data (dev only).
```

The split is intentional: `processor.py` takes DataFrames in, returns plain dicts out. No FastAPI imports, no file paths. That's what makes it testable without spinning up a server.
One more change in production would be a caching db for fast data serving.