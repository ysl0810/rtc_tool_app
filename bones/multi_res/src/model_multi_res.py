import numpy as np
from rtctools.optimization.collocated_integrated_optimization_problem import (
    CollocatedIntegratedOptimizationProblem,
)
from rtctools.optimization.goal_programming_mixin import (
    GoalProgrammingMixin,
    StateGoal,
)
from rtctools.optimization.csv_mixin import CSVMixin
from rtctools.optimization.modelica_mixin import ModelicaMixin
from rtctools.util import run_optimization_problem

# --------------------------------------------------
# Updated Storage target goal
# --------------------------------------------------
class StorageTargetGoal(StateGoal):
    # We remove the hardcoded 'state' here and pass it in __init__
    # to make the class reusable for both reservoirs.
    
    def __init__(self, opt_prob, state_name, target_prefix, priority=1):
        self.state = state_name  # e.g., "res1.S"
        
        # Look for target timeseries in CSV (e.g., res1_S_min)
        self.target_min = opt_prob.get_timeseries(f"{target_prefix}_target_min")
        self.target_max = opt_prob.get_timeseries(f"{target_prefix}_target_max")
        self.priority = priority

        super().__init__(opt_prob)

        self.function_range = (
            float(np.min(self.target_min.values)) - 100.0,
            float(np.max(self.target_max.values)) + 100.0,
        )
        
# --------------------------------------------------
# Optimization problem
# --------------------------------------------------
class ReservoirOptimization(
    GoalProgrammingMixin,
    CSVMixin,
    ModelicaMixin,
    CollocatedIntegratedOptimizationProblem,
):
    # 1. Update this to match your new top-level Modelica model name
    model_name = "MultiReservoirSystem"

    def parameters(self, ensemble_member):
        p = super().parameters(ensemble_member)
        t = self.io.times_sec
        # Update dt for the system (Modelica will apply this to both instances)
        p["dt"] = t[1] - t[0]
        return p

    def path_goals(self):
        goals = super().path_goals()
        
        # 2. Add goals for Reservoir 1
        goals.append(StorageTargetGoal(self, "res1.S", "res1", priority=1))
        
        # 3. Add goals for Reservoir 2 (Dam)
        goals.append(StorageTargetGoal(self, "res2.S", "res2", priority=1))
        
        return goals
    
# --------------------------------------------------
# Run
# --------------------------------------------------
if __name__ == "__main__":
    run_optimization_problem(ReservoirOptimization)