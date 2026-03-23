"""
RTC-Tools 2.8 — Eau Claire / Spirit Reservoir Optimization
Two-reservoir (Eau Claire, Spirit), two-dam (Merrill, Wis Rapids) system.

Objective: minimize deviation from storage targets using goal programming.

Constraint enforced (your specification):
    flow_min <= Q_rel + Q_local <= flow_max   (for each dam)
    i.e.  flow_min_merril  <= Q_rel_spirit + Qlocal_merril  <= flow_max_merril
          flow_min_wis_rap <= Q_rel_eau    + Qlocal_wis_rap <= flow_max_wis_rap

Run from src/ folder:
    python optimization_problem.py
"""

from rtctools.optimization.collocated_integrated_optimization_problem import (
    CollocatedIntegratedOptimizationProblem,
)
from rtctools.optimization.goal_programming_mixin import (
    GoalProgrammingMixin,
    StateGoal,
)
from rtctools.optimization.modelica_mixin import ModelicaMixin
from rtctools.optimization.csv_mixin import CSVMixin
from rtctools.util import run_optimization_problem


# ─────────────────────────────────────────────────────────────────────────────
# GOAL: minimize deviation from storage target
# ─────────────────────────────────────────────────────────────────────────────

class StorageTargetGoal(StateGoal):
    """
    Soft goal: keep reservoir storage as close to target as possible.
    order=2 → L2 norm (penalises large deviations quadratically).

    IMPORTANT: function_range must be set AFTER super().__init__()
    because super() overwrites it if set before.
    """
    order = 2

    def __init__(self, optimization_problem, state, target, v_min, v_max, priority):
        self.state      = state
        self.target_min = target
        self.target_max = target
        self.priority   = priority
        super().__init__(optimization_problem)        # call first
        self.function_range   = (v_min, v_max)       # override AFTER super()
        self.function_nominal = (v_min + v_max) / 2  # override AFTER super()


# ─────────────────────────────────────────────────────────────────────────────
# OPTIMIZATION PROBLEM
# ─────────────────────────────────────────────────────────────────────────────

class ReservoirOptimization(
    GoalProgrammingMixin,
    CSVMixin,
    ModelicaMixin,
    CollocatedIntegratedOptimizationProblem,
):
    """
    System:
        Eau Claire reservoir  → Wis Rapids dam   (Q_dam_wis_rap = Q_rel_eau    + Qlocal_wis_rap)
        Spirit reservoir      → Merrill dam       (Q_dam_merril  = Q_rel_spirit + Qlocal_merril)

    Goal hierarchy:
        Priority 1 → Storage targets (both reservoirs, equal weight)

    Hard constraints (always enforced):
        Q_rel bounds          per reservoir
        V bounds              per reservoir
        Q_dam bounds          per dam  ← flow_min <= Q_rel + Qlocal <= flow_max
    """

    # ── Storage targets [m³] — set to midpoint of allowed range ───────────────
    # Eau Claire: midpoint of [16168436, 126204412]
    TARGET_V_EAU    = (16168436.0 + 126204412.0) / 2   # ~71,186,424 m³
    # Spirit: midpoint of [31855500, 32421820] — very tight band
    TARGET_V_SPIRIT = (31855500.0 + 32421820.0)  / 2   # ~32,138,660 m³

    # ── Physical storage bounds [m³] ──────────────────────────────────────────
    VMIN_EAU,    VMAX_EAU    =  16168436.0, 126204412.0
    VMIN_SPIRIT, VMAX_SPIRIT =  31855500.0,  32421820.0

    # ── Release bounds [m³/s] ─────────────────────────────────────────────────
    QREL_MIN_EAU,    QREL_MAX_EAU    =   2.2653, 141.5800
    QREL_MIN_SPIRIT, QREL_MAX_SPIRIT =   2.2653,  56.6320

    # ── Dam total flow bounds [m³/s] ──────────────────────────────────────────
    # Constraint: flow_min <= Q_rel + Qlocal <= flow_max
    FLOW_MIN_MERRIL,  FLOW_MAX_MERRIL  =  25.4844,  96.2744
    FLOW_MIN_WIS_RAP, FLOW_MAX_WIS_RAP =  36.8108,  80.7006

    def path_goals(self):
        """
        Soft goals applied at every collocation timestep.
        Only differential state variables (V_*) may use StateGoal.
        """
        return [
            StorageTargetGoal(
                self, "V_eau",
                target   = self.TARGET_V_EAU,
                v_min    = self.VMIN_EAU,
                v_max    = self.VMAX_EAU,
                priority = 1,
            ),
            StorageTargetGoal(
                self, "V_spirit",
                target   = self.TARGET_V_SPIRIT,
                v_min    = self.VMIN_SPIRIT,
                v_max    = self.VMAX_SPIRIT,
                priority = 1,
            ),
        ]

    def path_constraints(self, ensemble_member):
        """
        Hard constraints at every collocation point.

        Dam flow constraint enforces your specification:
            flow_min <= Q_rel + Qlocal <= flow_max
        which is equivalent to constraining Q_dam_* defined in model.mo as:
            Q_dam_merril  = Q_rel_spirit + Qlocal_merril
            Q_dam_wis_rap = Q_rel_eau    + Qlocal_wis_rap
        """
        constraints = super().path_constraints(ensemble_member)

        # ── Release bounds ────────────────────────────────────────────────────
        constraints.append((
            self.state("Q_rel_eau"),
            self.QREL_MIN_EAU, self.QREL_MAX_EAU
        ))
        constraints.append((
            self.state("Q_rel_spirit"),
            self.QREL_MIN_SPIRIT, self.QREL_MAX_SPIRIT
        ))

        # ── Storage bounds ────────────────────────────────────────────────────
        constraints.append((
            self.state("V_eau"),
            self.VMIN_EAU, self.VMAX_EAU
        ))
        constraints.append((
            self.state("V_spirit"),
            self.VMIN_SPIRIT, self.VMAX_SPIRIT
        ))

        # ── Dam flow bounds: flow_min <= Q_rel + Qlocal <= flow_max ──────────
        # Q_dam_merril  = Q_rel_spirit + Qlocal_merril  (defined in model.mo)
        # Q_dam_wis_rap = Q_rel_eau    + Qlocal_wis_rap (defined in model.mo)
        constraints.append((
            self.state("Q_dam_merril"),
            self.FLOW_MIN_MERRIL, self.FLOW_MAX_MERRIL
        ))
        constraints.append((
            self.state("Q_dam_wis_rap"),
            self.FLOW_MIN_WIS_RAP, self.FLOW_MAX_WIS_RAP
        ))

        return constraints


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_optimization_problem(ReservoirOptimization)
