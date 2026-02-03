import os
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

print(os.path.join(os.path.dirname(os.path.abspath(__file__)), "model"))
# --------------------------------------------------
# Storage target goal (RTC-Tools 2.7 compatible)
# --------------------------------------------------
class StorageTargetGoal(StateGoal):
    state = "S"   # REQUIRED in 2.7.x

    def __init__(self, opt_prob, priority=1):

        self.target_min = opt_prob.get_timeseries("S_target_min")
        self.target_max = opt_prob.get_timeseries("S_target_max")
        self.priority = priority

        super().__init__(opt_prob)

        # Function range must cover targets
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
    model_name = "Reservoir"
    
        # 👇 POINT TO model/ SUBFOLDER
    # model_folder = model_folder = os.path.dirname(__file__)
    model_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model")

    def parameters(self, ensemble_member):
        p = super().parameters(ensemble_member)

        # Time step from CSV (seconds)
        t = self.io.times_sec
        p["dt"] = t[1] - t[0]

        return p

    def path_goals(self):
        goals = super().path_goals()
        goals.append(StorageTargetGoal(self, priority=1))
        return goals


# --------------------------------------------------
# Run
# --------------------------------------------------
if __name__ == "__main__":
    run_optimization_problem(ReservoirOptimization)



# import numpy as np

# from rtctools.optimization.collocated_integrated_optimization_problem import (
#     CollocatedIntegratedOptimizationProblem,
# )
# from rtctools.optimization.goal_programming_mixin import (
#     GoalProgrammingMixin,
#     StateGoal,
# )
# from rtctools.optimization.csv_mixin import CSVMixin
# from rtctools.optimization.modelica_mixin import ModelicaMixin
# from rtctools.util import run_optimization_problem


# # --------------------------------------------------
# # Storage target goal
# # --------------------------------------------------
# class StorageTargetGoal(StateGoal):
#     def __init__(self, opt_prob, priority=1):

#         # Read target bounds from CSV
#         target_min = opt_prob.get_timeseries("S_target_min")
#         target_max = opt_prob.get_timeseries("S_target_max")

#         super().__init__(
#             opt_prob,
#             state="S",                      # REQUIRED
#             target_min=target_min,
#             target_max=target_max,
#             priority=priority,
#         )

#         # Function range MUST cover targets
#         self.function_range = (
#             float(np.min(target_min.values)) - 100.0,
#             float(np.max(target_max.values)) + 100.0,
#         )


# # --------------------------------------------------
# # Optimization problem
# # --------------------------------------------------
# class ReservoirOptimization(
#     GoalProgrammingMixin,
#     CSVMixin,
#     ModelicaMixin,
#     CollocatedIntegratedOptimizationProblem,
# ):
#     model_name = "Reservoir"

#     def path_goals(self):
#         goals = super().path_goals()
#         goals.append(StorageTargetGoal(self, priority=1))
#         return goals


# # --------------------------------------------------
# # Run
# # --------------------------------------------------
# if __name__ == "__main__":
#     run_optimization_problem(ReservoirOptimization)








# import numpy as np

# from rtctools.optimization.collocated_integrated_optimization_problem import (
#     CollocatedIntegratedOptimizationProblem,
# )
# from rtctools.optimization.goal_programming_mixin import (
#     GoalProgrammingMixin,
#     StateGoal,
# )
# from rtctools.optimization.control_tree_mixin import ControlTreeMixin
# from rtctools.optimization.csv_mixin import CSVMixin
# from rtctools.optimization.modelica_mixin import ModelicaMixin
# from rtctools.util import run_optimization_problem


# class StorageTargetGoal(StateGoal):
#     def __init__(self, opt_prob, priority=1):
#         self.state_name = "S"  # the variable name of the reservoir in your model
#         self.target_min_ts = opt_prob.get_timeseries("S_target_min")
#         self.target_max_ts = opt_prob.get_timeseries("S_target_max")
#         self.violation_timeseries_id = "S_violation"
#         self.function_value_timeseries_id = "S"
#         self.priority = priority
#         super().__init__(opt_prob)

#         # function range should cover your target_min/max values
#         self.function_range = (min(self.target_min_ts.values) - 100,
#                                max(self.target_max_ts.values) + 100)

#     @property
#     def times(self):
#         # Return the time vector from your target timeseries
#         return self.target_min_ts.times        
        
# class ReservoirOptimization(
#     GoalProgrammingMixin,
#     CSVMixin,
#     ModelicaMixin,
#     ControlTreeMixin,
#     CollocatedIntegratedOptimizationProblem,
# ):
#     model_name = "Reservoir"
    
#     @property
#     def times(self):
#         # Return the time vector of the state
#         return self.target_min.times
    
#     def parameters(self, ensemble_member):
#         p = super().parameters(ensemble_member)
#         t = self.times()
#         p["dt"] = t[1] - t[0]
#         return p
    
#     def path_goals(self):
#         goals = super().path_goals()
#         goals.append(StorageTargetGoal(self, priority=1))
#         return goals
    
    
# if __name__ == "__main__":
#     run_optimization_problem(ReservoirOptimization)

    






    
    # def states(self):
    #     return ["S"]

    # def controls(self):
    #     return ["R"]
    
    # def state_equations(self, ensemble_member):
    #     Q_in = self.get_timeseries("Q_in")
    #     S0 = self.get_timeseries("S0")[0]
    #     dt = self.parameters(ensemble_member)["dt"]

    #     def storage_balance(t, S, R):
    #         if t == 0:
    #             S_prev = S0
    #         else:
    #             S_prev = S[t - 1]
    #         return S_prev + (Q_in[t] - R[t]) * dt

    #     return {"S": storage_balance}
    
    