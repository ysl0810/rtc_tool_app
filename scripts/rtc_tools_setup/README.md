# RTC-Tools Reservoir Optimization Project

## System
- **2 reservoirs** (reservoir_1, reservoir_2) each feeding one dam independently
- **2 dams** (dam_1, dam_2)
- **12 timesteps** of 6 hours each (3-day horizon)
- **Objective**: minimize deviation from storage targets using goal programming

---

## Project Structure

```
rtc_reservoir_project/
    model.mo                  ← Modelica: mass balance physics
    timeseries_import.csv     ← Input: inflows at each timestep
    optimization_problem.py   ← Python: goals & constraints
    run_optimization.py       ← Python: entry point
    output/                   ← Created automatically on first run
        timeseries_export.csv ← Results written here by RTC-Tools
```

---

## Installation

```bash
pip install rtc-tools casadi pandas numpy
```

> RTC-Tools requires Python 3.8+ and a C++ compiler for Modelica compilation.
> On Windows, install **Visual Studio Build Tools** (free) if you get compiler errors:
> https://visualstudio.microsoft.com/visual-cpp-build-tools/

---

## How to Run

Open a terminal in this folder and run:

```bash
python run_optimization.py
```

---

## How It Works

### 1. model.mo (Modelica)
Defines the physical equations:
- `der(V_reservoir_1) = Qin_reservoir_1 - Q_rel_reservoir_1`  (mass balance)
- `Q_dam_1 = Q_rel_reservoir_1 + Qlocal_dam_1`  (dam total flow)

RTC-Tools compiles this with OpenModelica/CasADi and collocates it over time.

### 2. timeseries_import.csv
Provides the exogenous inputs at each timestep:
- `Qin_reservoir_1`, `Qin_reservoir_2` — natural inflows
- `Qlocal_dam_1`, `Qlocal_dam_2` — local inflows at each dam

### 3. optimization_problem.py (Goal Programming)
Two priority levels:

| Priority | Goal | Type |
|----------|------|------|
| 1 (first) | Dam flow within [Qmin, Qmax] | Soft bound (L1) |
| 2 (second) | Storage close to target | Soft target (L2) |

Hard constraints (always enforced):
- Release bounds: Q_rel in [Qmin, Qmax]
- Storage bounds: V in [Vmin, Vmax]

### 4. run_optimization.py
Entry point. Runs the optimizer and prints:
- Full results table
- Constraint violation check
- Storage target deviation summary

---

## Customizing

### Change storage targets
In `optimization_problem.py`:
```python
TARGET_V_RES1 = 150_000.0   # ← change this
TARGET_V_RES2 = 100_000.0   # ← change this
```

### Change inflow data
Edit `timeseries_import.csv` — one row per timestep, time in seconds.

### Add more timesteps
Add rows to `timeseries_import.csv` (keep 6-hour spacing: 0, 21600, 43200, ...).

### Change goal priority weights
Swap `order = 1` (L1) to `order = 2` (L2) in any Goal class for stronger
penalization of large deviations.

---

## Key Parameters

| Parameter | Reservoir 1 | Reservoir 2 |
|-----------|-------------|-------------|
| V0 (m³) | 100,000 | 80,000 |
| Vmin (m³) | 50,000 | 40,000 |
| Vmax (m³) | 200,000 | 160,000 |
| Vtarget (m³) | 150,000 | 100,000 |
| Qmin release (m³/s) | 5 | 5 |
| Qmax release (m³/s) | 100 | 80 |

| Parameter | Dam 1 | Dam 2 |
|-----------|-------|-------|
| Feeds from | reservoir_1 | reservoir_2 |
| Qmin (m³/s) | 10 | 8 |
| Qmax (m³/s) | 120 | 100 |
