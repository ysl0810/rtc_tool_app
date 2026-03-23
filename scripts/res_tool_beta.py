from dataclasses import dataclass, field
from typing import List, Dict, Optional
import numpy as np
import pandas as pd
import pulp


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES  (pure data — no logic)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ReservoirSpec:
    name: str
    V0:   float
    Vmin: float
    Vmax: float
    Qmin: float
    Qmax: float
    Qin:  List[float]

@dataclass
class DamSpec:
    name:               str
    Qmin:               float
    Qmax:               float
    upstream_reservoir: str
    local_inflow:       List[float]

@dataclass
class PowerSpec:
    reservoir_name: str
    price_per_m3:   float  

@dataclass
class PenaltyWeights:
    W_V_over:  float = 1000000.0
    W_V_under: float = 100000.0
    W_Q_over:  float = 1000000.0
    W_Q_under: float = 10000.0


OBJECTIVE_MODES = ("minimize_release", "maximize_profit", "minimize_spill")

# ─────────────────────────────────────────────────────────────────────────────
# MODEL CLASS
# ─────────────────────────────────────────────────────────────────────────────

class ReservoirSystemModel:
    """
    Builds and solves a multi-reservoir / multi-dam LP with soft constraints.

    Usage
    -----
    model = ReservoirSystemModel(
        reservoirs  = [eau, spirit],
        dams        = [merril, wis_rap],
        dt          = 6 * 3600,
        mode        = "minimize_release",   # or "maximize_profit" / "minimize_spill"
        weights     = PenaltyWeights(),
        power_specs = [],
    )
    model.solve()
    model.summary()
    results = model.results()
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

        self._prob           = None
        self._Q_rel          = {}
        self._storage_slacks = {}
        self._dam_slacks     = {}
        self._solved         = False
        self._status         = None

        self._validate_specs()   # ← check compatibility before building
        self._build()
    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────────

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
        Return a dict of numpy arrays with all results.

        Keys
        ----
        status      : solver status string
        objective   : final objective value
        revenue     : total hydropower revenue ($ ) — maximize_profit mode only
        Q_rel       : {res_name: np.array shape (n,)}   release m³/s
        V           : {res_name: np.array shape (n+1,)} storage m³
        Q_dam       : {dam_name: np.array shape (n,)}   dam flow m³/s
        violations  : pd.DataFrame
        """
        self._check_solved()
        return {
            "status":     self._status,
            "objective":  pulp.value(self._prob.objective),
            "revenue":    self._compute_revenue(),
            "Q_rel":      self._extract_releases(),
            "V":          self._reconstruct_storage(),
            "Q_dam":      self._compute_dam_flows(),
            "violations": self.violations(),
        }
        
    def violations(self) -> pd.DataFrame:
        """Return a DataFrame of all soft constraint violations > 1e-3."""
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
        """Print a human-readable results summary."""
        self._check_solved()
        r = self.results()

        print("=" * 70)
        print(f"  Reservoir System Model  |  mode: {self.mode}")
        print(f"  Status    : {r['status']}")
        print(f"  Objective : {r['objective']:.4f}")
        if self.mode == "maximize_profit":
            print(f"  Revenue   : ${r['revenue']:,.2f}")
        print("=" * 70)

        # per-reservoir table
        for res in self.reservoirs:
            Q  = r["Q_rel"][res.name]
            V  = r["V"][res.name]
            print(f"\n  [{res.name}]  Vmin={res.Vmin:,.0f}  Vmax={res.Vmax:,.0f} m³")
            print(f"  {'t':>3}  {'Q_in':>8}  {'Q_rel':>8}  "
                  f"{'V_start':>14}  {'V_end':>14}  {'ok?':>5}")
            print(f"  {'-'*3}  {'-'*8}  {'-'*8}  {'-'*14}  {'-'*14}  {'-'*5}")
            for t in range(self.n):
                ok = (res.Vmin <= V[t+1] <= res.Vmax)
                print(f"  {t+1:>3}  {res.Qin[t]:>8.2f}  {Q[t]:>8.2f}  "
                      f"  {V[t]:>13,.0f}  {V[t+1]:>13,.0f}  "
                      f"{'Okay' if ok else 'Violated':>5}")

        # per-dam table
        for dam in self.dams:
            Qd = r["Q_dam"][dam.name]
            print(f"\n  [{dam.name}]  Qmin={dam.Qmin:.2f}  Qmax={dam.Qmax:.2f} m³/s")
            print(f"  {'t':>3}  {'Q_local':>9}  {'Q_dam':>8}  {'ok?':>5}")
            print(f"  {'-'*3}  {'-'*9}  {'-'*8}  {'-'*5}")
            for t in range(self.n):
                ok = (dam.Qmin <= Qd[t] <= dam.Qmax)
                print(f"  {t+1:>3}  {dam.local_inflow[t]:>9.2f}  "
                      f"{Qd[t]:>8.2f}  {'Okay' if ok else 'Violated':>5}")

        # violations
        vdf = r["violations"]
        print(f"\n  Violations: "
              f"{'None ' if vdf.empty else str(len(vdf)) + ' found '}")
        if not vdf.empty:
            print(vdf.to_string(index=False))
        print("=" * 70)

    def dataframe(self) -> pd.DataFrame:
        """Return all results as a single wide DataFrame (one row per timestep)."""
        self._check_solved()
        r   = self.results()
        d   = {}
        for res in self.reservoirs:
            d[f"Q_in_{res.name}"]    = np.round(res.Qin, 4)
            d[f"Q_rel_{res.name}"]   = np.round(r["Q_rel"][res.name], 4)
            d[f"V_start_{res.name}"] = r["V"][res.name][:self.n].astype(int)
            d[f"V_end_{res.name}"]   = r["V"][res.name][1:].astype(int)
        for dam in self.dams:
            d[f"Q_local_{dam.name}"] = np.round(dam.local_inflow, 4)
            d[f"Q_dam_{dam.name}"]   = np.round(r["Q_dam"][dam.name], 4)
        return pd.DataFrame(d)
    
    
    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE: BUILD
    # ─────────────────────────────────────────────────────────────────────────
    def _build(self) -> None:
        """Build LP: variables → constraints → objective.
        ORDER MATTERS:
            1. variables   — LP decision variables must exist first
            2. constraints — populates _storage_slacks and _dam_slacks
            3. objective   — reads _storage_slacks and _dam_slacks for penalties
        """
        self._prob = pulp.LpProblem("ReservoirSystemModel", pulp.LpMinimize)
        self._build_variables()     # step 1
        self._build_constraints()   # step 2  ← must come BEFORE _build_objective
        self._build_objective()     # step 3  ← reads slacks built in step 2
        
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
        primary  = self._primary_objective()
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
            power_map = {ps.reservoir_name: ps for ps in self.power_specs}
            if not power_map:
                raise ValueError(
                    "maximize_profit requires at least one PowerSpec."
                )
            return -pulp.lpSum(
                power_map[res.name].price_per_m3
                * self._Q_rel[res.name][t]
                * self.dt
                for res in self.reservoirs
                if res.name in power_map
                for t in range(self.n)
            )

        elif self.mode == "minimize_spill":
            return pulp.lpSum(
                self._storage_slacks[res.name]["over"]
                for res in self.reservoirs
            )
    
    def _penalty_terms(self) -> pulp.LpAffineExpression:
        """
        Soft constraint penalty terms — always added regardless of mode.
        Storage penalties are normalised per m³ (divided by dt).
        Dam flow penalties are per m³/s.
        """
        w  = self.weights
        dt = self.dt
        return (
              (w.W_V_over  / dt) * pulp.lpSum(
                  self._storage_slacks[res.name]["over"]
                  for res in self.reservoirs
              )
            + (w.W_V_under / dt) * pulp.lpSum(
                  self._storage_slacks[res.name]["under"]
                  for res in self.reservoirs
              )
            + w.W_Q_over  * pulp.lpSum(
                  self._dam_slacks[dam.name]["over"]
                  for dam in self.dams
              )
            + w.W_Q_under * pulp.lpSum(
                  self._dam_slacks[dam.name]["under"]
                  for dam in self.dams
              )
        )
           
    def _build_constraints(self) -> None:
        # storage
        for res in self.reservoirs:
            self._storage_slacks[res.name] = self._add_reservoir_constraints(res)
        # dam flow
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
    
    # def _add_dam_constraints(
    #     self, dam: DamSpec
    #     ) -> Dict[str, List[pulp.LpVariable]]:
    #     s_over  = self._make_slacks(f"s_Q_over_{dam.name}")
    #     s_under = self._make_slacks(f"s_Q_under_{dam.name}")
    #     Q_up    = self._Q_rel[dam.upstream_reservoir]
    #     for t in range(self.n):
    #         Q_dam = Q_up[t] + dam.local_inflow[t]
    #         self._prob += Q_dam - s_over[t]  <= dam.Qmax, f"{dam.name}_Qmax_t{t+1}"
    #         self._prob += Q_dam + s_under[t] >= dam.Qmin, f"{dam.name}_Qmin_t{t+1}"
    #     return {"over": s_over, "under": s_under}
    
    
    def _add_dam_constraints(
        self, dam: DamSpec
        ) -> Dict[str, List[pulp.LpVariable]]:
        """
        Soft dam flow constraints + tighten upstream release bounds
        so Q_rel can never exceed dam ceiling on its own.
        """
        s_over  = self._make_slacks(f"s_Q_over_{dam.name}")
        s_under = self._make_slacks(f"s_Q_under_{dam.name}")
        Q_up    = self._Q_rel[dam.upstream_reservoir]

        for t in range(self.n):
            Q_dam = Q_up[t] + dam.local_inflow[t]
            prob  = self._prob

            # ── soft dam flow bounds ──────────────────────────────────────────
            prob += Q_dam - s_over[t]  <= dam.Qmax, f"{dam.name}_Qmax_t{t+1}"
            prob += Q_dam + s_under[t] >= dam.Qmin, f"{dam.name}_Qmin_t{t+1}"

            # ── hard per-timestep release cap from dam ceiling ────────────────
            # Q_rel[t] <= dam.Qmax - local_inflow[t]  (hard upper bound per step)
            # This prevents Q_rel from blowing past dam ceiling even if
            # soft penalty weight is too low
            hard_cap = dam.Qmax - dam.local_inflow[t]
            if hard_cap >= 0:
                prob += Q_up[t] <= hard_cap, f"{dam.name}_hard_cap_t{t+1}"

        return {"over": s_over, "under": s_under}
    
    def _validate_specs(self) -> None:
        """
        Check that reservoir Qmax is compatible with each downstream dam ceiling.
        Warns if releasing at Qmax would always exceed the dam ceiling.
        """
        dam_map = {dam.upstream_reservoir: dam for dam in self.dams}
        for res in self.reservoirs:
            if res.name not in dam_map:
                continue
            dam = dam_map[res.name]
            for t in range(self.n):
                max_rel_at_dam = dam.Qmax - dam.local_inflow[t]
                if res.Qmax > max_rel_at_dam > 0:
                    # Qmax exceeds dam ceiling — soft or hard cap will activate
                    pass  # handled by hard_cap in _add_dam_constraints
                if max_rel_at_dam < res.Qmin:
                    raise ValueError(
                        f"t={t+1}: [{dam.name}] dam ceiling minus local inflow "
                        f"({max_rel_at_dam:.2f}) < [{res.name}] Qmin ({res.Qmin:.2f}). "
                        f"Raise dam.Qmax or lower res.Qmin."
                    )
    
    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE: EXTRACT (Report)
    # ─────────────────────────────────────────────────────────────────────────

    def _make_slacks(self, prefix: str) -> List[pulp.LpVariable]:
        return [
            pulp.LpVariable(f"{prefix}_{t}", lowBound=0)
            for t in range(self.n)
        ]

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

    def _compute_revenue(self) -> float:
        Q_rel     = self._extract_releases()
        power_map = {ps.reservoir_name: ps for ps in self.power_specs}
        return sum(
            power_map[res.name].price_per_m3 * Q_rel[res.name][t] * self.dt
            for res in self.reservoirs
            if res.name in power_map
            for t in range(self.n)
        )

    def _check_solved(self) -> None:
        if not self._solved:
            raise RuntimeError("Call model.solve() before accessing results.")

if __name__ == "__main__":
    np.random.seed(42)
    dt = 6 * 3600      # 6 hours in seconds
    n  = 12            # evlauation period of 3 days with 6-hourly steps
    #=========data for Eau Claire and Spirit Lake reservoirs=========#
    
    # define the EAU class
    eau    = ReservoirSpec(
        "eau",                   # name
        4400*0.028316*1e6,       # initial storage (m³)    
        571*0.028316*1e6,        # minimum storage (m³)
        4457*0.028316*1e6,       # maximum storage (m³)
        80*0.028316,             # minimum flow (m³/s)
        5000*0.028316,           # maximum flow (m³/s)
        [(q+100)/35.315 for q in[1590,1080,1360,1580,1670,1330,1420,1380,1580,831,1410,1420]])  # inflows (m³/s)
    
    
    spirit = ReservoirSpec(
        "spirit", 
        1140*0.028316*1e6, 
        1125*0.028316*1e6,
        1145*0.028316*1e6, 
        80*0.028316, 
        2000*0.028316,
        [(q+100)/35.315 for q in[1200.35,1200.35,1000.82,900.58,1300.25,1500.25,1400.68,1500.25,1450.25,1350.58,1252.82,1140.92]])
    
    
    #=========data for Merril and Wisconsin Dam=========#
    merril  = DamSpec(
        "merril",            # name
        900*0.028316,        # minimum flow (m³/s)
        # 2100*0.028316,       # maximum flow (m³/s) 
        3400*0.028316,       # maximum flow (m³/s)  — raised to match dam ceiling
        "spirit",               # upstream reservoir
        [(q)/35.315 for q in np.random.normal(1200, 100, n)]) # local inflows (m³/s)
    
    wis_rap = DamSpec(
        "wis_rap", 
        1300*0.028316, 
        2850*0.028316, 
        "eau",
        [(q)/35.315 for q in np.random.normal(1500, 100, n)])
    
    
    # ── Mode 1: minimize release ──────────────────────────────────────────────────
    model = ReservoirSystemModel(
        # reservoirs=[eau, spirit],
        reservoirs=[eau], 
        # dams=[merril, wis_rap],
        dams=[wis_rap],
        dt=dt, 
        mode="minimize_release",
    )
    model.solve()
    model.summary()
    df = model.dataframe()
    print(df)
    
    
