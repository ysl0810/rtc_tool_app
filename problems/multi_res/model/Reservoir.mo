model Reservoir
  parameter Real dt = 0.25 "Time step (days, 6 hours)";

  input Real Q_in "Inflow";
  input Real R "Release";

  Real S(start=348) "Storage";

equation
  der(S) = (Q_in - R) / dt;
end Reservoir;