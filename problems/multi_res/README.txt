Overview
This project optimizes a cascaded water system consisting of an upstream reservoir and a downstream dam. Using RTC-Tools (v2.7), the system calculates optimal release rates ($R_1$ and $R_2$) to keep both water bodies within their respective target storage ranges while accounting for forecasted inflows.The optimization handles the mass balance link:Upstream Reservoir (res1): Receives external environmental inflow.Downstream Dam (res2): Receives the controlled release from the upstream reservoir as its primary inflow.


The optimization balances three main factors:

Upstream Reservoir (res1): Receives external environmental inflow.

Downstream Dam (res2): Receives the controlled release from the upstream reservoir as its primary inflow.

1. Input Data (Time-Series)
The optimization reads time-series data 
path: multi_res\input\timeseries_import.csv.


Column Name         Description
Q_in_totalTotal     external inflow into Reservoir 1 ($m^3/s$).
res1_target_min/max Desired storage range for the Upstream Reservoir.
res2_target_min/max Desired storage range for the Downstream Dam.


2. Multi-Reservoir Model (Modelica)The physical connectivity is defined in single_res\model\Reservoir.mo using a hierarchical structure
path: multi_res\model\MultiReservoirSystem.mo

3. Optimization Setup (main scripts)

The optimization is implemented using RTC-Tools mixins.
path: Multi_res\src\model_multi_res.py


output result

6 hours water release rate
path: Multi_res\output\timeseries_export.csv


