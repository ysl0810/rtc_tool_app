model MultiReservoirSystem
  // Time step parameter
  parameter Real dt = 0.25 "Time step (days, 6 hours)";

  // Components
  Reservoir res1(S(start=348)) "Upstream Reservoir";
  Reservoir res2(S(start=200)) "Downstream Dam";

  // Inputs/Outputs
  input Real Q_in_total "External Inflow to Res 1";
  input Real R1 "Controlled Release from Res 1";
  input Real R2 "Controlled Release from Dam 2";

equation
  // Connections
  res1.Q_in = Q_in_total;
  res1.R = R1;

  // The link: Res 2 inflow is Res 1 release
  res2.Q_in = res1.R;
  res2.R = R2;
end MultiReservoirSystem;

model Reservoir
  parameter Real dt = 0.25;
  input Real Q_in;
  input Real R;
  Real S;
equation
  der(S) = (Q_in - R) / dt;
end Reservoir;