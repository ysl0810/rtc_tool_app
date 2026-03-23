model ReservoirOptimization

  // ── Controlled releases (optimizer decides) ───────────────────────────────
  input Real Q_rel_eau(fixed = false, min = 2.2653, max = 141.5800)
    "Controlled release from Eau Claire reservoir [m3/s]";

  input Real Q_rel_spirit(fixed = false, min = 2.2653, max = 56.6320)
    "Controlled release from Spirit reservoir [m3/s]";

  // ── Exogenous inflows (read from timeseries_import.csv) ───────────────────
  input Real Qin_eau(fixed = true)      "Natural inflow to Eau Claire [m3/s]";
  input Real Qin_spirit(fixed = true)   "Natural inflow to Spirit [m3/s]";
  input Real Qlocal_merril(fixed = true)  "Local inflow at Merrill dam [m3/s]";
  input Real Qlocal_wis_rap(fixed = true) "Local inflow at Wis Rapids dam [m3/s]";

  // ── State variables: reservoir storage volumes ────────────────────────────
  output Real V_eau(min = 16168436.0, max = 126204412.0)
    "Storage volume of Eau Claire reservoir [m3]";

  output Real V_spirit(min = 31855500.0, max = 32421820.0)
    "Storage volume of Spirit reservoir [m3]";

  // ── Algebraic: total dam flows = release + local inflow ───────────────────
  // Constraint: flow_min <= Q_dam <= flow_max  (enforced in path_constraints)
  output Real Q_dam_merril
    "Total flow through Merrill dam [m3/s]";

  output Real Q_dam_wis_rap
    "Total flow through Wis Rapids dam [m3/s]";

equation
  // ── Mass balance: dV/dt = Qin - Q_rel ────────────────────────────────────
  der(V_eau)    = Qin_eau    - Q_rel_eau;
  der(V_spirit) = Qin_spirit - Q_rel_spirit;

  // ── Dam total flow: Q_dam = Q_rel + local_inflow ──────────────────────────
  // This is the constraint you specified:
  //   flow_min <= Q_rel + Qlocal <= flow_max
  Q_dam_merril  = Q_rel_spirit + Qlocal_merril;
  Q_dam_wis_rap = Q_rel_eau    + Qlocal_wis_rap;

end ReservoirOptimization;
