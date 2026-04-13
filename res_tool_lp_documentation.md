# `res_tool_lp.py` — Method Documentation

## Overview

`res_tool_lp.py` implements a **multi-reservoir, multi-dam Linear Programming (LP) optimization model** for real-time control (RTC) of a river/reservoir system. It uses [PuLP](https://coin-or.github.io/PuLP/) as the LP interface and CBC (or another COIN-OR solver) as the backend.

The model jointly optimizes releases from multiple reservoirs subject to storage bounds, downstream dam flow limits, and (optionally) hydropower revenue. Infeasible hard constraints are relaxed via penalized **soft constraints** (slack variables), ensuring the LP always has a feasible solution.

---

## Data Structures

### `ReservoirSpec`
Defines the physical and operational properties of a single reservoir.

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Unique reservoir identifier |
| `V0` | `float` | Initial storage (m³) |
| `Vmin` | `float` | Minimum allowable storage (m³) |
| `Vmax` | `float` | Maximum allowable storage (m³) |
| `Qmin` | `float` | Minimum release rate (m³/s) |
| `Qmax` | `float` | Maximum release rate (m³/s) |
| `Qin` | `List[float]` | Inflow time series (m³/s), length = number of timesteps |
| `head_elev` | `List[float]` | Pool elevation curve (ft) |
| `head_storage_mcf` | `List[float]` | Corresponding storage values (MCF) |
| `z_tailwater` | `float` | Tailwater elevation (ft), default 0.0 |
| `head_loss_fraction` | `float` | Friction/head-loss fraction (default 0.03) |

If `head_elev` and `head_storage_mcf` are provided, scipy `interp1d` functions are built to convert between storage (m³) and pool elevation (ft) in either direction.

**Unit conversions performed internally:**
- MCF → m³: `storage_m3 = MCF × 1000 × 0.028316`
- Net head (ft): `h = (z_pool − z_tailwater) × (1 − head_loss_fraction)`
- Net head (m): `h_m = h_ft × 0.3048`

### `DamSpec`
Defines a downstream control point (dam) that aggregates upstream reservoir release and local lateral inflow.

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Unique dam identifier |
| `Qmin` | `float` | Minimum flow at dam (m³/s) |
| `Qmax` | `float` | Maximum flow at dam (m³/s) |
| `upstream_reservoir` | `str` | Name of the reservoir directly upstream |
| `local_inflow` | `List[float]` | Lateral inflow time series (m³/s) |

### `PowerSpec`
Links a reservoir to hydropower generation parameters.

| Field | Type | Description |
|---|---|---|
| `reservoir_name` | `str` | Name of the reservoir |
| `electricity_price` | `float` | Power price ($/MWh) |
| `turbine_efficiency` | `float` | Turbine efficiency η (default 0.85) |

### `PenaltyWeights`
Controls the cost of violating soft constraints.

| Field | Default | Description |
|---|---|---|
| `W_V_over` | 1,000,000 | $/m³ for storage exceeding Vmax |
| `W_V_under` | 100,000 | $/m³ for storage falling below Vmin |
| `W_Q_over` | 1,000,000 | $/(m³/s) for dam flow exceeding Qmax |
| `W_Q_under` | 10,000 | $/(m³/s) for dam flow below Qmin |

---

## Decision Variables

For each reservoir `r` and timestep `t`:

| Variable | Bounds | Description |
|---|---|---|
| `Q_rel[r][t]` | `[Qmin(r), Qmax(r)]` | Release rate (m³/s) |
| `s_V_over[r][t]` | `≥ 0` | Slack for storage overflow (m³) |
| `s_V_under[r][t]` | `≥ 0` | Slack for storage underflow (m³) |

For each dam `d` and timestep `t`:

| Variable | Bounds | Description |
|---|---|---|
| `s_Q_over[d][t]` | `≥ 0` | Slack for dam flow over Qmax (m³/s) |
| `s_Q_under[d][t]` | `≥ 0` | Slack for dam flow under Qmin (m³/s) |

---

## Constraints

### 1. Reservoir Mass Balance
Storage at each timestep is computed recursively from the initial condition:

```
V(r, t) = V(r, 0) + Σ_{τ=0}^{t} [Q_in(r, τ) − Q_rel(r, τ)] × Δt
```

This is expressed directly as a linear expression over the decision variables (no explicit state variable `V` is introduced into the LP — storage is a running sum).

### 2. Soft Storage Bounds
```
V(r,t) − s_V_over(r,t)  ≤  Vmax(r)       [overflow slack]
V(r,t) + s_V_under(r,t) ≥  Vmin(r)       [underflow slack]
```

### 3. Dam Flow Balance
```
Q_dam(d, t) = Q_rel(upstream(d), t) + Q_local(d, t)
```

### 4. Soft Dam Flow Bounds
```
Q_dam(d,t) − s_Q_over(d,t)  ≤  Qmax(d)
Q_dam(d,t) + s_Q_under(d,t) ≥  Qmin(d)
```

### 5. Hard Dam Cap on Upstream Release
To prevent the reservoir release alone from exceeding the dam capacity even before local inflow is added:
```
Q_rel(upstream(d), t) ≤  Qmax(d) − Q_local(d, t)    (when cap ≥ 0)
```

---

## Objective Function

The total objective is always **minimized** (PuLP `LpMinimize`). The objective has two parts:

```
min  Z  =  Primary(mode)  +  Penalties
```

### Primary Objectives

#### `minimize_release`
Minimizes total water released across all reservoirs and timesteps:
```
Primary = Σ_r Σ_t  Q_rel(r, t)
```

#### `maximize_profit`
Maximizes hydropower revenue (modeled by minimizing its negative):
```
Primary = −Σ_r Σ_t  rev_per_m3(r) × Q_rel(r, t) × Δt
```
where the per-unit revenue is approximated at the **initial storage head** (linearization):
```
rev_per_m3(r) = η × ρ × g × h_m(V0) / 3.6×10⁹  ×  price   [$/m³]
```
- ρ = 998 kg/m³ (water density)
- g = 9.81 m/s²
- h_m = net head in meters
- price = electricity price in $/MWh

> **Linearization note:** Head varies with storage level, making the true power-revenue term nonlinear (Q × h(V)). To maintain LP tractability, head is fixed at the initial storage V₀. This is an approximation; iterative linearization or a nonlinear solver would be needed for full accuracy.

#### `minimize_spill`
Minimizes total storage overflow (spill) directly:
```
Primary = Σ_r Σ_t  s_V_over(r, t)
```

### Penalty Terms
Added to the primary objective in all modes to discourage constraint violation:
```
Penalties = (W_V_over / Δt) × Σ s_V_over
          + (W_V_under / Δt) × Σ s_V_under
          + W_Q_over  × Σ s_Q_over
          + W_Q_under × Σ s_Q_under
```
> In `minimize_spill` mode, the `W_V_over` penalty is **excluded** from `Penalties` to avoid double-counting the storage overflow slack (which is already the primary objective).

---

## Hydropower Calculations (Post-processing)

After solving, hydropower quantities are computed analytically:

**Energy per timestep (MWh):**
```
E(r, t) = η × ρ × g × h_m(V(r,t)) × Q_rel(r,t) × Δt  /  3.6×10⁹
```
where `h_m` uses the **start-of-period storage** (not the linearized V₀).

**Total revenue ($):**
```
Revenue = Σ_r  [Σ_t E(r,t)] × price(r)
```

> Note: `results()["head"]` contains **n+1 values** (one per storage state, from t=0 to t=n), while `results()["energy_mwh"]` and `results()["Q_rel"]` contain **n values** (one per interval). When indexing head at timestep t, use `head[t]` for the start-of-period head.

---

## Objective Modes Summary

| Mode | Primary goal | Uses PowerSpec? | Requires elevation curve? |
|---|---|---|---|
| `minimize_release` | Minimize total release | No | No |
| `maximize_profit` | Maximize hydropower revenue | Yes | Yes |
| `minimize_spill` | Minimize storage overflow | No | No |

---

## Usage Example

```python
model = ReservoirSystemModel(
    reservoirs  = [eau, spirit],
    dams        = [merril, wis_rap],
    dt          = 6 * 3600,            # 6-hour timestep (seconds)
    mode        = "maximize_profit",
    weights     = PenaltyWeights(),
    power_specs = [PowerSpec("eau", 50.0, 0.85)],
)
status = model.solve()          # returns solver status string
model.summary()                 # prints formatted results table
df = model.dataframe()          # returns wide pandas DataFrame
r  = model.results()            # returns dict with all arrays
vdf = model.violations()        # returns DataFrame of violated constraints
```

---

## Solver Configuration

By default, PuLP's bundled CBC solver is used (`PULP_CBC_CMD`). A custom solver path can be provided:

```python
model = ReservoirSystemModel(..., solver_path="/path/to/cbc")
```

---

## Known Issues / Limitations

| # | Issue | Impact | Status |
|---|---|---|---|
| 1 | **Duplicate MCF value in `spirit_mcf` data** (line ~601): value `162` appears at two consecutive elevations (1429.80 and 1429.90 ft), creating a flat segment in the storage→elevation interpolation. | Possible incorrect elevation lookup near that storage range. | Data should be verified against the original rating table and corrected. |
| 2 | **Linearized head in `maximize_profit`**: head is fixed at V₀ for the LP objective, not updated as storage changes. | Revenue estimate in the objective may be inaccurate for large storage swings. | Use iterative re-linearization or a nonlinear solver for higher accuracy. |
| 3 | **Single upstream reservoir per dam**: the model assumes each dam has exactly one upstream reservoir. Confluences (multiple tributaries above a dam) are not directly supported. | Cannot represent complex river networks where multiple reservoirs feed one dam. | Extend `DamSpec` with a list of upstream reservoirs if needed. |
| 4 | **Head series length (n+1) vs. other series (n)**: `results()["head"]` has one extra entry compared to `results()["Q_rel"]` and `results()["energy_mwh"]`. | Care required when combining arrays (e.g., use `head[:n]` for start-of-period). | By design; documented above. |

---

## File-Level Constants

| Constant | Value | Description |
|---|---|---|
| `RHO` | 998.0 kg/m³ | Water density |
| `G` | 9.81 m/s² | Gravitational acceleration |
| `OBJECTIVE_MODES` | tuple of 3 strings | Valid mode names |
