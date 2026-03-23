Reservoir Release Optimization using RTC-Tools
Overview

This example demonstrates how to use RTC-Tools (v2.7) to solve a reservoir operation problem:
how much water should be released over time given forecasted inflows, such that reservoir storage remains within a target range.

The optimization uses:

A Modelica reservoir model to describe storage dynamics

Time-series inputs (inflow and storage targets) provided via CSV

Goal programming to keep storage between a minimum and maximum target


Input Data

1. Time-series CSV inputs
 The optimization reads the following columns from a CSV file:

path: single_res\input\timeseries_import.csv

Column Name	Description
time	        Simulation time (6-hour intervals)
Q_in	        Inflow to the reservoir
S_target_min	Minimum desired storage
S_target_max	Maximum desired storage

2. Reservoir Model (Modelica)

The physical behavior of the reservoir is defined in a Modelica file.
path: single_res\model\Reservoir.mo

3. Optimization Setup (main scripts)

The optimization is implemented using RTC-Tools mixins.
path: single_res\src\model_single_res.py


output result

6 hours water release rate
path: single_res\output\timeseries_export.csv





