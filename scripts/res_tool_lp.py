"""
Reservoir System Optimization Model with Hydraulic Head & Hydropower
====================================================================

Objective function modes:

min Z = Σ_r Σ_t Q_rel(r,t)
      + [(W_V_over / Δt) × Σ s_V⁺(r,t) + (W_V_under / Δt) × Σ s_V⁻(r,t)]
      + [W_Q_over × Σ s_Q⁺(d,t) + W_Q_under × Σ s_Q⁻(d,t)]

maximize_profit: −Σ_r Σ_t p(r,t) × Q_rel(r,t) × Δt
  where p(r,t) = electricity_price × η × ρ × g × h(V(r,t)) / 3.6e9  ($/m³)

Reservoir constraints:
  1. Mass balance:  V(r,t) = V(r,t−1) + [Q_in(r,t) − Q_rel(r,t)] × Δt
  2. Soft storage:  V(r,t) − s_V⁺(r,t) ≤ V_max(r)
                    V(r,t) + s_V⁻(r,t) ≥ V_min(r)

Dam flow constraints:
  1. Flow balance:  Q_dam(d,t) = Q_rel(u(d),t) + Q_local(d,t)
  2. Soft limits:   Q_dam(d,t) − s_Q⁺(d,t) ≤ Q_max(d)
                    Q_dam(d,t) + s_Q⁻(d,t) ≥ Q_min(d)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
import numpy as np
import pandas as pd
import pulp
from scipy.interpolate import interp1d


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ReservoirSpec:
    """Reservoir specification with optional storage-elevation curve."""
    name: str                                    # reservoir name
    V0:   float                                  # initial storage (m³)
    Vmin: float                                  # minimum storage (m³)
    Vmax: float                                  # maximum storage (m³)
    Qmin: float                                  # minimum release (m³/s)
    Qmax: float                                  # maximum release (m³/s)
    Qin:  List[float]                            # inflow time series (m³/s)
    # --- storage-elevation curve ---
    head_elev:        List[float] = field(default_factory=list)   # elevations (ft)
    head_storage_mcf: List[float] = field(default_factory=list)   # storage (MCF)
    z_tailwater:        float = 0.0              # tailwater elevation (ft)
    head_loss_fraction: float = 0.03             # friction loss fraction

    def __post_init__(self):
        """Build interpolation functions from the curve data."""
        self._storage_to_elev = None
        self._elev_to_storage = None
        if self.head_elev and self.head_storage_mcf:
            # Convert MCF to m³: 1 MCF = 1000 cf × 0.028316 m³/cf
            storage_m3 = [s * 1000 * 0.028316 for s in self.head_storage_mcf]
            elev = self.head_elev
            self._storage_to_elev = interp1d(
                storage_m3, elev, kind='linear', fill_value='extrapolate'
            )
            self._elev_to_storage = interp1d(
                elev, storage_m3, kind='linear', fill_value='extrapolate'
            )

    def elevation(self, V: float) -> float:
        """Pool elevation (ft) from storage (m³)."""
        if self._storage_to_elev is None:
            raise ValueError(f"No storage-elevation curve for '{self.name}'")
        return float(self._storage_to_elev(V))

    def net_head(self, V: float) -> float:
        """
        Net hydraulic head (ft).
        h = (z_pool - z_tailwater) × (1 - loss_fraction)
        """
        z_pool = self.elevation(V)
        gross_head = z_pool - self.z_tailwater
        return gross_head * (1.0 - self.head_loss_fraction)

    def net_head_m(self, V: float) -> float:
        """Net hydraulic head in meters."""
        return self.net_head(V) * 0.3048

    @property
    def has_elevation_curve(self) -> bool:
        return self._storage_to_elev is not None


@dataclass
class DamSpec:
    """Dam specification."""
    name:               str            # dam name
    Qmin:               float          # minimum flow (m³/s)
    Qmax:               float          # maximum flow (m³/s)
    upstream_reservoir:  str            # name of upstream reservoir
    local_inflow:       List[float]    # local inflow time series (m³/s)


@dataclass
class PowerSpec:
    """Hydropower specification for a reservoir."""
    reservoir_name:     str            # reservoir with hydropower
    electricity_price:  float          # $/MWh
    turbine_efficiency: float = 0.85   # dimensionless (typical 0.80–0.95)


@dataclass
class PenaltyWeights:
    """Penalty weights for soft constraint violations."""
    W_V_over:  float = 1_000_000.0    # $/m³ storage above Vmax
    W_V_under: float = 100_000.0      # $/m³ storage below Vmin
    W_Q_over:  float = 1_000_000.0    # $/(m³/s) dam flow above Qmax
    W_Q_under: float = 10_000.0       # $/(m³/s) dam flow below Qmin


OBJECTIVE_MODES = ("minimize_release", "maximize_profit", "minimize_spill")

RHO = 998.0    # water density (kg/m³)
G   = 9.81     # gravitational acceleration (m/s²)


# ─────────────────────────────────────────────────────────────────────────────
# MODEL CLASS
# ─────────────────────────────────────────────────────────────────────────────

class ReservoirSystemModel:
    """
    Multi-reservoir / multi-dam LP with soft constraints and hydropower.

    Usage
    -----
    model = ReservoirSystemModel(
        reservoirs  = [eau, spirit],
        dams        = [merril, wis_rap],
        dt          = 6 * 3600,
        mode        = "maximize_profit",
        weights     = PenaltyWeights(),
        power_specs = [PowerSpec("eau", 50.0, 0.85)],
    )
    model.solve()
    model.summary()
    """

    def __init__(
        self,
        reservoirs:  List[ReservoirSpec],
        dams:        List[DamSpec],
        dt:          float,
        mode:        str             = "minimize_release",
        weights:     PenaltyWeights  = None,
        power_specs: List[PowerSpec] = None,
        solver_path: Optional[str]   = None,
    ):
        if mode not in OBJECTIVE_MODES:
            raise ValueError(f"mode must be one of {OBJECTIVE_MODES}, got '{mode}'")

        self.reservoirs  = reservoirs
        self.dams        = dams
        self.dt          = dt
        self.mode        = mode
        self.weights     = weights     or PenaltyWeights()
        self.power_specs = power_specs or []
        self.solver_path = solver_path
        self.n           = len(reservoirs[0].Qin)

        if not all(len(r.Qin) == self.n for r in reservoirs):
            raise ValueError("All ReservoirSpec.Qin must have the same length")

        # Validate power specs have elevation curves
        if self.mode == "maximize_profit":
            power_map = {ps.reservoir_name for ps in self.power_specs}
            for res in self.reservoirs:
                if res.name in power_map and not res.has_elevation_curve:
                    raise ValueError(
                        f"maximize_profit requires a storage-elevation curve "
                        f"for reservoir '{res.name}'"
                    )

        self._prob           = None
        self._Q_rel          = {}
        self._storage_slacks = {}
        self._dam_slacks     = {}
        self._solved         = False
        self._status         = None

        self._validate_specs()
        self._build()

    # ─────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────

    def solve(self) -> str:
        """Solve the LP. Returns solver status string."""
        if self.solver_path:
            solver = pulp.COIN_CMD(path=self.solver_path, msg=0)
        else:
            solver = pulp.PULP_CBC_CMD(msg=0)
        self._prob.solve(solver)
        self._status = pulp.LpStatus[self._prob.status]
        self._solved = True
        return self._status

    def results(self) -> Dict:
        """
        Return dict of all results.

        Keys: status, objective, revenue, Q_rel, V, Q_dam,
              head, energy_mwh, violations
        """
        self._check_solved()
        return {
            "status":     self._status,
            "objective":  pulp.value(self._prob.objective),
            "revenue":    self._compute_revenue(),
            "Q_rel":      self._extract_releases(),
            "V":          self._reconstruct_storage(),
            "Q_dam":      self._compute_dam_flows(),
            "head":       self._compute_head_series(),
            "energy_mwh": self._compute_energy(),
            "violations": self.violations(),
        }

    def violations(self) -> pd.DataFrame:
        """Return DataFrame of all soft constraint violations > 1e-3."""
        self._check_solved()
        rows = []
        for res in self.reservoirs:
            for t in range(self.n):
                ov = pulp.value(self._storage_slacks[res.name]["over"][t])
                un = pulp.value(self._storage_slacks[res.name]["under"][t])
                if ov and ov > 1e-3:
                    rows.append({"t": t+1, "name": res.name,
                                 "type": "storage_overflow",
                                 "magnitude": ov, "unit": "m³"})
                if un and un > 1e-3:
                    rows.append({"t": t+1, "name": res.name,
                                 "type": "storage_underflow",
                                 "magnitude": un, "unit": "m³"})
        for dam in self.dams:
            for t in range(self.n):
                ov = pulp.value(self._dam_slacks[dam.name]["over"][t])
                un = pulp.value(self._dam_slacks[dam.name]["under"][t])
                if ov and ov > 1e-3:
                    rows.append({"t": t+1, "name": dam.name,
                                 "type": "dam_flow_over",
                                 "magnitude": ov, "unit": "m³/s"})
                if un and un > 1e-3:
                    rows.append({"t": t+1, "name": dam.name,
                                 "type": "dam_flow_under",
                                 "magnitude": un, "unit": "m³/s"})
        cols = ["t", "name", "type", "magnitude", "unit"]
        return pd.DataFrame(rows, columns=cols) if rows \
               else pd.DataFrame(columns=cols)

    def summary(self) -> None:
        """Print human-readable results summary."""
        self._check_solved()
        r = self.results()

        print("=" * 80)
        print(f"  Reservoir System Model  |  mode: {self.mode}")
        print(f"  Status    : {r['status']}")
        print(f"  Objective : {r['objective']:.4f}")
        if self.mode == "maximize_profit":
            print(f"  Revenue   : ${r['revenue']:,.2f}")
            total_energy = sum(e.sum() for e in r['energy_mwh'].values())
            print(f"  Total Energy: {total_energy:,.2f} MWh")
        print("=" * 80)

        # Per-reservoir table
        for res in self.reservoirs:
            Q = r["Q_rel"][res.name]
            V = r["V"][res.name]
            print(f"\n  [{res.name}]  Vmin={res.Vmin:,.0f}  Vmax={res.Vmax:,.0f} m³")

            has_head = res.name in r["head"]
            has_energy = res.name in r["energy_mwh"]

            header = f"  {'t':>3}  {'Q_in':>8}  {'Q_rel':>8}  {'V_start':>14}  {'V_end':>14}"
            if has_head:
                header += f"  {'Head(ft)':>9}"
            if has_energy:
                header += f"  {'MWh':>10}"
            header += f"  {'Status':>8}"
            print(header)
            print(f"  {'-' * (len(header) - 2)}")

            for t in range(self.n):
                ok = (res.Vmin - 1e-6 <= V[t+1] <= res.Vmax + 1e-6)
                line = (f"  {t+1:>3}  {res.Qin[t]:>8.2f}  {Q[t]:>8.2f}  "
                        f"  {V[t]:>13,.0f}  {V[t+1]:>13,.0f}")
                if has_head:
                    line += f"  {r['head'][res.name][t]:>9.2f}"
                if has_energy:
                    line += f"  {r['energy_mwh'][res.name][t]:>10.4f}"
                line += f"  {'Okay' if ok else 'VIOLATED':>8}"
                print(line)

        # Per-dam table
        for dam in self.dams:
            Qd = r["Q_dam"][dam.name]
            Qup = r["Q_rel"][dam.upstream_reservoir]
            print(f"\n  [{dam.name}]  Qmin={dam.Qmin:.2f}  Qmax={dam.Qmax:.2f} m³/s")
            print(f"  {'t':>3}  {'Q_rel':>8}  {'Q_local':>9}  {'Q_dam':>8}  {'Status':>8}")
            print(f"  {'-'*3}  {'-'*8}  {'-'*9}  {'-'*8}  {'-'*8}")
            for t in range(self.n):
                ok = (dam.Qmin - 1e-3 <= Qd[t] <= dam.Qmax + 1e-3)
                print(f"  {t+1:>3}  {Qup[t]:>8.2f}  {dam.local_inflow[t]:>9.2f}  "
                      f"{Qd[t]:>8.2f}  {'Okay' if ok else 'VIOLATED':>8}")

        # Violations
        vdf = r["violations"]
        print(f"\n  Violations: "
              f"{'None' if vdf.empty else str(len(vdf)) + ' found'}")
        if not vdf.empty:
            print(vdf.to_string(index=False))
        print("=" * 80)

    def dataframe(self) -> pd.DataFrame:
        """Return all results as a single wide DataFrame."""
        self._check_solved()
        r = self.results()
        d = {}
        for res in self.reservoirs:
            d[f"Q_in_{res.name}"]    = np.round(res.Qin, 4)
            d[f"Q_rel_{res.name}"]   = np.round(r["Q_rel"][res.name], 4)
            d[f"V_start_{res.name}"] = r["V"][res.name][:self.n].astype(int)
            d[f"V_end_{res.name}"]   = r["V"][res.name][1:].astype(int)
            if res.name in r["head"]:
                d[f"head_ft_{res.name}"]  = np.round(r["head"][res.name][:self.n], 2)
                d[f"head_m_{res.name}"]   = np.round(r["head"][res.name][:self.n] * 0.3048, 2)
            if res.name in r["energy_mwh"]:
                d[f"energy_mwh_{res.name}"] = np.round(r["energy_mwh"][res.name], 4)
        for dam in self.dams:
            d[f"Q_local_{dam.name}"] = np.round(dam.local_inflow, 4)
            d[f"Q_dam_{dam.name}"]   = np.round(r["Q_dam"][dam.name], 4)
        return pd.DataFrame(d)

    # ─────────────────────────────────────────────────────────────────────
    # PRIVATE: BUILD
    # ─────────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self._prob = pulp.LpProblem("ReservoirSystemModel", pulp.LpMinimize)
        self._build_variables()
        self._build_constraints()
        self._build_objective()

    def _build_variables(self) -> None:
        for res in self.reservoirs:
            self._Q_rel[res.name] = [
                pulp.LpVariable(
                    f"Q_rel_{res.name}_{t}",
                    lowBound=res.Qmin,
                    upBound=res.Qmax,
                )
                for t in range(self.n)
            ]

    def _build_objective(self) -> None:
        primary   = self._primary_objective()
        penalties = self._penalty_terms()
        self._prob += primary + penalties, "Objective"

    def _primary_objective(self) -> pulp.LpAffineExpression:
        if self.mode == "minimize_release":
            return pulp.lpSum(
                self._Q_rel[res.name][t]
                for res in self.reservoirs
                for t in range(self.n)
            )

        elif self.mode == "maximize_profit":
            # Since head depends on storage (a linear function of Q_rel),
            # and the LP requires linear objectives, we approximate head
            # at the initial storage for each reservoir.
            # For a more accurate (nonlinear) approach, use iterative
            # linearization or switch to a nonlinear solver.
            power_map = {ps.reservoir_name: ps for ps in self.power_specs}
            if not power_map:
                raise ValueError("maximize_profit requires at least one PowerSpec.")

            terms = []
            for res in self.reservoirs:
                if res.name not in power_map:
                    continue
                ps = power_map[res.name]
                # Approximate head at initial storage (linearization)
                h_m = res.net_head_m(res.V0)
                # Revenue per m³ = η × ρ × g × h / 3.6e9 × price
                rev_per_m3 = (ps.turbine_efficiency * RHO * G * h_m / 3.6e9
                              * ps.electricity_price)
                for t in range(self.n):
                    terms.append(rev_per_m3 * self._Q_rel[res.name][t] * self.dt)

            return -pulp.lpSum(terms)

        elif self.mode == "minimize_spill":
            return pulp.lpSum(
                self._storage_slacks[res.name]["over"]
                for res in self.reservoirs
            )

    def _penalty_terms(self) -> pulp.LpAffineExpression:
        w  = self.weights
        dt = self.dt
        return (
              (w.W_V_over / dt) * pulp.lpSum(
                  self._storage_slacks[res.name]["over"]
                  for res in self.reservoirs)
            + (w.W_V_under / dt) * pulp.lpSum(
                  self._storage_slacks[res.name]["under"]
                  for res in self.reservoirs)
            + w.W_Q_over * pulp.lpSum(
                  self._dam_slacks[dam.name]["over"]
                  for dam in self.dams)
            + w.W_Q_under * pulp.lpSum(
                  self._dam_slacks[dam.name]["under"]
                  for dam in self.dams)
        )

    def _build_constraints(self) -> None:
        for res in self.reservoirs:
            self._storage_slacks[res.name] = self._add_reservoir_constraints(res)
        for dam in self.dams:
            self._dam_slacks[dam.name] = self._add_dam_constraints(dam)

    def _add_reservoir_constraints(
        self, res: ReservoirSpec
    ) -> Dict[str, List[pulp.LpVariable]]:
        s_over  = self._make_slacks(f"s_V_over_{res.name}")
        s_under = self._make_slacks(f"s_V_under_{res.name}")
        V_expr  = res.V0
        for t in range(self.n):
            V_expr = V_expr + (res.Qin[t] - self._Q_rel[res.name][t]) * self.dt
            self._prob += V_expr - s_over[t]  <= res.Vmax, f"{res.name}_Vmax_t{t+1}"
            self._prob += V_expr + s_under[t] >= res.Vmin, f"{res.name}_Vmin_t{t+1}"
        return {"over": s_over, "under": s_under}

    def _add_dam_constraints(
        self, dam: DamSpec
    ) -> Dict[str, List[pulp.LpVariable]]:
        s_over  = self._make_slacks(f"s_Q_over_{dam.name}")
        s_under = self._make_slacks(f"s_Q_under_{dam.name}")
        Q_up    = self._Q_rel[dam.upstream_reservoir]
        for t in range(self.n):
            Q_dam = Q_up[t] + dam.local_inflow[t]
            prob  = self._prob
            prob += Q_dam - s_over[t]  <= dam.Qmax, f"{dam.name}_Qmax_t{t+1}"
            prob += Q_dam + s_under[t] >= dam.Qmin, f"{dam.name}_Qmin_t{t+1}"
            hard_cap = dam.Qmax - dam.local_inflow[t]
            if hard_cap >= 0:
                prob += Q_up[t] <= hard_cap, f"{dam.name}_hard_cap_t{t+1}"
        return {"over": s_over, "under": s_under}

    def _validate_specs(self) -> None:
        dam_map = {dam.upstream_reservoir: dam for dam in self.dams}
        for res in self.reservoirs:
            if res.name not in dam_map:
                continue
            dam = dam_map[res.name]
            for t in range(self.n):
                max_rel_at_dam = dam.Qmax - dam.local_inflow[t]
                if max_rel_at_dam < res.Qmin:
                    raise ValueError(
                        f"t={t+1}: [{dam.name}] dam ceiling minus local inflow "
                        f"({max_rel_at_dam:.2f}) < [{res.name}] Qmin ({res.Qmin:.2f}). "
                        f"Raise dam.Qmax or lower res.Qmin."
                    )
    

    # ─────────────────────────────────────────────────────────────────────
    # PRIVATE: EXTRACT / COMPUTE
    # ─────────────────────────────────────────────────────────────────────

    def _make_slacks(self, prefix: str) -> List[pulp.LpVariable]:
        return [pulp.LpVariable(f"{prefix}_{t}", lowBound=0) for t in range(self.n)]

    def _extract_releases(self) -> Dict[str, np.ndarray]:
        return {
            res.name: np.array([
                pulp.value(self._Q_rel[res.name][t]) for t in range(self.n)
            ])
            for res in self.reservoirs
        }

    def _reconstruct_storage(self) -> Dict[str, np.ndarray]:
        Q_rel = self._extract_releases()
        V_out = {}
        for res in self.reservoirs:
            V = np.zeros(self.n + 1)
            V[0] = res.V0
            for t in range(self.n):
                V[t+1] = V[t] + (res.Qin[t] - Q_rel[res.name][t]) * self.dt
            V_out[res.name] = V
        return V_out

    def _compute_dam_flows(self) -> Dict[str, np.ndarray]:
        Q_rel = self._extract_releases()
        return {
            dam.name: Q_rel[dam.upstream_reservoir] + np.array(dam.local_inflow)
            for dam in self.dams
        }

    def _compute_head_series(self) -> Dict[str, np.ndarray]:
        """Net hydraulic head (ft) at each timestep."""
        V = self._reconstruct_storage()
        heads = {}
        for res in self.reservoirs:
            if not res.has_elevation_curve:
                continue
            heads[res.name] = np.array([
                res.net_head(V[res.name][t]) for t in range(self.n + 1)
            ])
        return heads

    def _compute_energy(self) -> Dict[str, np.ndarray]:
        """Energy produced at each timestep (MWh)."""
        V = self._reconstruct_storage()
        Q = self._extract_releases()
        power_map = {ps.reservoir_name: ps for ps in self.power_specs}
        energy = {}
        for res in self.reservoirs:
            if res.name not in power_map:
                continue
            if not res.has_elevation_curve:
                continue
            ps = power_map[res.name]
            E = np.zeros(self.n)
            for t in range(self.n):
                h_m = res.net_head_m(V[res.name][t])
                # Power (W) = η × ρ × g × h × Q
                power_w = ps.turbine_efficiency * RHO * G * h_m * Q[res.name][t]
                # Energy (MWh) = Power (W) × dt (s) / 3.6e9
                E[t] = power_w * self.dt / 3.6e9
            energy[res.name] = E
        return energy

    def _compute_revenue(self) -> float:
        """Total hydropower revenue ($)."""
        energy = self._compute_energy()
        power_map = {ps.reservoir_name: ps for ps in self.power_specs}
        total = 0.0
        for res_name, E in energy.items():
            if res_name in power_map:
                total += E.sum() * power_map[res_name].electricity_price
        return total

    def _check_solved(self) -> None:
        if not self._solved:
            raise RuntimeError("Call model.solve() before accessing results.")


# ─────────────────────────────────────────────────────────────────────────────
# EXAMPLE DATA & USAGE
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    np.random.seed(42)
    dt = 6 * 3600      # 6 hours in seconds
    n  = 12             # 3 days of 6-hourly steps

    # ── Storage-elevation curves ─────────────────────────────────────────

    # Spirit Lake: Head (ft) vs Storage (MCF)
    spirit_elev = [
        1420.88, 1421.00, 1421.10, 1421.20, 1421.30, 1421.40, 1421.50,
        1421.60, 1421.70, 1421.80, 1421.90, 1422.00, 1422.10, 1422.20,
        1422.30, 1422.40, 1422.50, 1422.60, 1422.70, 1422.80, 1422.90,
        1423.00, 1423.10, 1423.20, 1423.30, 1423.40, 1423.50, 1423.60,
        1423.70, 1423.80, 1423.90, 1424.00, 1424.10, 1424.20, 1424.30,
        1424.40, 1424.50, 1424.60, 1424.70, 1424.80, 1424.90, 1425.00,
        1425.10, 1425.20, 1425.30, 1425.40, 1425.50, 1425.60, 1425.70,
        1425.80, 1425.90, 1426.00, 1426.10, 1426.20, 1426.30, 1426.40,
        1426.50, 1426.60, 1426.70, 1426.80, 1426.90, 1427.00, 1427.10,
        1427.20, 1427.30, 1427.40, 1427.50, 1427.60, 1427.70, 1427.80,
        1427.90, 1428.00, 1428.10, 1428.20, 1428.30, 1428.40, 1428.50,
        1428.60, 1428.70, 1428.80, 1428.90, 1429.00, 1429.10, 1429.20,
        1429.30, 1429.40, 1429.50, 1429.60, 1429.70, 1429.80, 1429.90,
        1430.00, 1430.10, 1430.20, 1430.30, 1430.40, 1430.50, 1430.60,
        1430.70, 1430.80, 1430.90, 1431.00, 1431.10, 1431.20, 1431.30,
        1431.40, 1431.50, 1431.60, 1431.70, 1431.80, 1431.90, 1432.00,
        1432.10, 1432.20, 1432.30, 1432.40, 1432.50, 1432.60, 1432.70,
        1432.80, 1432.90, 1433.00, 1433.10, 1433.20, 1433.30, 1433.40,
        1433.50, 1433.60, 1433.70, 1433.80, 1433.90, 1434.00, 1434.10,
        1434.20, 1434.30, 1434.40, 1434.50, 1434.60, 1434.70, 1434.80,
        1434.90, 1435.00, 1435.10, 1435.20, 1435.30, 1435.40, 1435.50,
        1435.60, 1435.70, 1435.80, 1435.90, 1436.00, 1436.10, 1436.20,
        1436.30, 1436.40, 1436.50, 1436.60, 1436.70, 1436.80, 1436.90,
        1437.00, 1437.10, 1437.20, 1437.30, 1437.40, 1437.50, 1437.60,
        1437.70, 1437.80, 1437.88,
    ]
    spirit_mcf = [
        0, 0, 0, 0, 1, 1, 2, 2, 2, 3, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12,
        13, 14, 16, 17, 19, 20, 22, 23, 25, 26, 28, 29, 30, 32, 34, 36,
        38, 39, 41, 43, 45, 47, 49, 51, 54, 56, 59, 61, 63, 66, 68, 71,
        73, 76, 79, 82, 85, 87, 90, 93, 96, 99, 102, 106, 109, 112, 116,
        119, 122, 125, 129, 132, 136, 139, 143, 147, 151, 154, 158, 162,
        162, 169, 173, 177, 182, 186, 190, 194, 198, 203, 207, 211, 216,
        221, 225, 230, 235, 240, 245, 249, 254, 259, 264, 270, 275, 280,
        286, 291, 296, 301, 307, 312, 318, 324, 330, 336, 342, 349, 355,
        361, 367, 373, 379, 386, 393, 400, 407, 413, 420, 427, 434, 441,
        448, 455, 462, 469, 477, 484, 491, 498, 505, 513, 520, 528, 536,
        544, 552, 560, 568, 576, 584, 592, 601, 610, 618, 626, 634, 643,
        652, 660, 668, 677, 686, 695, 704, 713, 722, 731, 740, 749, 756,
    ]

    # Big Eau Claire: Head (ft) vs Storage (MCF)
    eau_elev = [
        1118.00, 1118.10, 1118.20, 1118.30, 1118.40, 1118.50, 1118.60,
        1118.70, 1118.80, 1118.90, 1119.00, 1119.10, 1119.20, 1119.30,
        1119.40, 1119.50, 1119.60, 1119.70, 1119.80, 1119.90, 1120.00,
        1120.10, 1120.20, 1120.30, 1120.40, 1120.50, 1120.60, 1120.70,
        1120.80, 1120.90, 1121.00, 1121.10, 1121.20, 1121.30, 1121.40,
        1121.50, 1121.60, 1121.70, 1121.80, 1121.90, 1122.00, 1122.10,
        1122.20, 1122.30, 1122.40, 1122.50, 1122.60, 1122.70, 1122.80,
        1122.90, 1123.00, 1123.10, 1123.20, 1123.30, 1123.40, 1123.50,
        1123.60, 1123.70, 1123.80, 1123.90, 1124.00, 1124.10, 1124.20,
        1124.30, 1124.40, 1124.50, 1124.60, 1124.70, 1124.80, 1124.90,
        1125.00, 1125.10, 1125.20, 1125.30, 1125.40, 1125.50, 1125.60,
        1125.70, 1125.80, 1125.90, 1126.00, 1126.10, 1126.20, 1126.30,
        1126.40, 1126.50, 1126.60, 1126.70, 1126.80, 1126.90, 1127.00,
        1127.10, 1127.20, 1127.30, 1127.40, 1127.50, 1127.60, 1127.70,
        1127.80, 1127.90, 1128.00, 1128.10, 1128.20, 1128.30, 1128.40,
        1128.50, 1128.60, 1128.70, 1128.80, 1128.90, 1129.00, 1129.10,
        1129.20, 1129.30, 1129.40, 1129.50, 1129.60, 1129.70, 1129.80,
        1129.90, 1130.00, 1130.10, 1130.20, 1130.30, 1130.40, 1130.50,
        1130.60, 1130.70, 1130.80, 1130.90, 1131.00, 1131.10, 1131.20,
        1131.30, 1131.40, 1131.50, 1131.60, 1131.70, 1131.80, 1131.90,
        1132.00, 1132.10, 1132.20, 1132.30, 1132.40, 1132.50, 1132.60,
        1132.70, 1132.80, 1132.90, 1133.00, 1133.10, 1133.20, 1133.30,
        1133.40, 1133.50, 1133.60, 1133.70, 1133.80, 1133.90, 1134.00,
        1134.10, 1134.20, 1134.30, 1134.40, 1134.50, 1134.60, 1134.70,
        1134.80, 1134.90, 1135.00, 1135.10, 1135.20, 1135.30, 1135.40,
        1135.50, 1135.60, 1135.70, 1135.80, 1135.90, 1136.00, 1136.10,
        1136.20, 1136.30, 1136.40, 1136.50, 1136.60, 1136.70, 1136.80,
        1136.90, 1137.00, 1137.10, 1137.20, 1137.30, 1137.40, 1137.50,
        1137.60, 1137.70, 1137.80, 1137.90, 1138.00, 1138.10, 1138.20,
        1138.30, 1138.40, 1138.50, 1138.60, 1138.70, 1138.80, 1138.90,
        1139.00, 1139.10, 1139.20, 1139.30, 1139.40, 1139.50, 1139.60,
        1139.70, 1139.80, 1139.90, 1140.00, 1140.10, 1140.20, 1140.30,
        1140.40, 1140.50, 1140.60, 1140.70, 1140.80, 1140.90, 1141.00,
        1141.10, 1141.20, 1141.30, 1141.40, 1141.50, 1141.60, 1141.70,
        1141.80, 1141.90, 1142.00, 1142.10, 1142.20, 1142.30, 1142.40,
        1142.50, 1142.60, 1142.70, 1142.80, 1142.90, 1143.00, 1143.10,
        1143.20, 1143.30, 1143.40, 1143.50, 1143.60, 1143.70, 1143.80,
        1143.90, 1144.00, 1144.10, 1144.20, 1144.30, 1144.40, 1144.50,
        1144.60, 1144.70, 1144.80, 1144.90, 1145.00, 1145.10, 1145.20,
        1145.30, 1145.43,
    ]
    eau_mcf = [
        117, 121, 126, 131, 136, 141, 145, 150, 155, 160, 165, 170, 176,
        181, 187, 192, 198, 203, 209, 214, 220, 226, 232, 238, 244, 250,
        256, 262, 268, 274, 280, 286, 292, 298, 304, 310, 317, 324, 331,
        338, 345, 352, 359, 366, 373, 380, 387, 394, 401, 408, 416, 423,
        430, 438, 444, 452, 460, 467, 475, 482, 490, 497, 505, 513, 521,
        529, 537, 546, 554, 563, 571, 579, 588, 596, 605, 613, 622, 631,
        640, 649, 658, 667, 677, 686, 696, 705, 714, 724, 733, 743, 752,
        762, 774, 781, 790, 800, 810, 821, 832, 843, 854, 864, 875, 886,
        897, 908, 920, 931, 943, 954, 966, 978, 990, 1002, 1014, 1026,
        1038, 1050, 1062, 1074, 1087, 1100, 1113, 1126, 1139, 1152, 1165,
        1178, 1191, 1204, 1218, 1232, 1245, 1259, 1272, 1286, 1300, 1315,
        1329, 1344, 1358, 1373, 1388, 1403, 1418, 1433, 1448, 1463, 1478,
        1493, 1509, 1525, 1540, 1556, 1571, 1587, 1603, 1620, 1637, 1654,
        1671, 1687, 1704, 1721, 1738, 1755, 1772, 1790, 1808, 1826, 1844,
        1863, 1881, 1900, 1918, 1937, 1956, 1974, 1993, 2011, 2030, 2049,
        2069, 2089, 2109, 2129, 2149, 2170, 2190, 2211, 2231, 2252, 2274,
        2295, 2317, 2338, 2359, 2381, 2403, 2425, 2447, 2469, 2492, 2515,
        2538, 2561, 2584, 2608, 2631, 2655, 2678, 2702, 2726, 2750, 2774,
        2798, 2823, 2848, 2873, 2898, 2923, 2948, 2974, 3000, 3026, 3052,
        3078, 3104, 3130, 3156, 3182, 3209, 3236, 3263, 3290, 3317, 3344,
        3371, 3398, 3425, 3453, 3481, 3509, 3537, 3565, 3594, 3622, 3651,
        3679, 3708, 3736, 3764, 3793, 3822, 3851, 3880, 3910, 3939, 3969,
        3998, 4028, 4058, 4088, 4118, 4148, 4178, 4208, 4238, 4268, 4298,
        4328, 4358, 4388, 4418, 4457,
    ]

    # ── Reservoir specs ──────────────────────────────────────────────────

    eau = ReservoirSpec(
        name="eau",
        V0=4400 * 0.028316 * 1e6,
        Vmin=571 * 0.028316 * 1e6,
        Vmax=4457 * 0.028316 * 1e6,
        Qmin=80 * 0.028316,
        Qmax=5000 * 0.028316,
        Qin=[(q + 100) / 35.315 for q in
             [1590, 1080, 1360, 1580, 1670, 1330, 1420, 1380, 1580, 831, 1410, 1420]],
        head_elev=eau_elev,
        head_storage_mcf=eau_mcf,
        z_tailwater=1100.0,        # ← UPDATE with actual tailwater elevation (ft)
        head_loss_fraction=0.03,
    )

    spirit = ReservoirSpec(
        name="spirit",
        V0=1140 * 0.028316 * 1e6,
        Vmin=1125 * 0.028316 * 1e6,
        Vmax=1145 * 0.028316 * 1e6,
        Qmin=80 * 0.028316,
        Qmax=2000 * 0.028316,
        Qin=[(q + 100) / 35.315 for q in
             [1200.35, 1200.35, 1000.82, 900.58, 1300.25, 1500.25,
              1400.68, 1500.25, 1450.25, 1350.58, 1252.82, 1140.92]],
        head_elev=spirit_elev,
        head_storage_mcf=spirit_mcf,
        z_tailwater=1410.0,        # ← UPDATE with actual tailwater elevation (ft)
        head_loss_fraction=0.03,
    )

    # ── Dam specs ────────────────────────────────────────────────────────

    merril = DamSpec(
        "merril",
        900 * 0.028316,
        3400 * 0.028316,
        "spirit",
        [(q) / 35.315 for q in np.random.normal(1200, 100, n)],
    )

    wis_rap = DamSpec(
        "wis_rap",
        1300 * 0.028316,
        2850 * 0.028316,
        "eau",
        [(q) / 35.315 for q in np.random.normal(1500, 100, n)],
    )

    # ── Power specs ──────────────────────────────────────────────────────

    eau_power = PowerSpec(
        reservoir_name="eau",
        electricity_price=50.0,     # $/MWh
        turbine_efficiency=0.85,
    )

    spirit_power = PowerSpec(
        reservoir_name="spirit",
        electricity_price=50.0,     # $/MWh
        turbine_efficiency=0.85,
    )

    # ════════════════════════════════════════════════════════════════════
    # Mode 1: Minimize release (single reservoir)
    # ════════════════════════════════════════════════════════════════════
    print("\n" + "█" * 80)
    print("  MODE 1: MINIMIZE RELEASE (single reservoir)")
    print("█" * 80)

    model1 = ReservoirSystemModel(
        reservoirs=[eau],
        dams=[wis_rap],
        dt=dt,
        mode="minimize_release",
    )
    model1.solve()
    model1.summary()
    df1 = model1.dataframe()
    print("\nDataFrame:")
    print(df1.to_string())

    # ════════════════════════════════════════════════════════════════════
    # Mode 2: Minimize release (system)
    # ════════════════════════════════════════════════════════════════════
    print("\n" + "█" * 80)
    print("  MODE 2: MINIMIZE RELEASE (system)")
    print("█" * 80)

    model2 = ReservoirSystemModel(
        reservoirs=[eau, spirit],
        dams=[merril, wis_rap],
        dt=dt,
        mode="minimize_release",
    )
    model2.solve()
    model2.summary()
    df2 = model2.dataframe()
    print("\nDataFrame:")
    print(df2.to_string())

    # ════════════════════════════════════════════════════════════════════
    # Mode 3: Maximize profit (system with hydropower)
    # ════════════════════════════════════════════════════════════════════
    print("\n" + "█" * 80)
    print("  MODE 3: MAXIMIZE PROFIT (system with hydropower)")
    print("█" * 80)

    model3 = ReservoirSystemModel(
        reservoirs=[eau, spirit],
        dams=[merril, wis_rap],
        dt=dt,
        mode="maximize_profit",
        power_specs=[eau_power, spirit_power],
    )
    model3.solve()
    model3.summary()
    df3 = model3.dataframe()
    print("\nDataFrame:")
    print(df3.to_string())

    # ── Verify head calculations ─────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  HEAD VERIFICATION")
    print("=" * 80)
    for res in [eau, spirit]:
        print(f"\n  [{res.name}]")
        print(f"    Elevation at V0   : {res.elevation(res.V0):.2f} ft")
        print(f"    Elevation at Vmin : {res.elevation(res.Vmin):.2f} ft")
        print(f"    Elevation at Vmax : {res.elevation(res.Vmax):.2f} ft")
        print(f"    Net head at V0    : {res.net_head(res.V0):.2f} ft "
              f"({res.net_head_m(res.V0):.2f} m)")
        print(f"    Net head at Vmin  : {res.net_head(res.Vmin):.2f} ft "
              f"({res.net_head_m(res.Vmin):.2f} m)")
        print(f"    Net head at Vmax  : {res.net_head(res.Vmax):.2f} ft "
              f"({res.net_head_m(res.Vmax):.2f} m)")
        print(f"    Tailwater elev    : {res.z_tailwater:.2f} ft")