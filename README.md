# rtc_tool_app
This directory contains the problem definitions and configurations used by the RTC-Tools application for reservoir operation optimization.

Directory Structure:

```text
problems/
├── single_res/
│ ├── model/
│ │ └── Reservior.mo
│ ├── input/
│ │ └── timeseries_import.csv
│ ├── src/
│ │ └── model_single_res.py
│ ├── output/
│ │ └── timeseries_export.csv
│ └── README.md
├── multi_res/
│ ├── model/
│ │ └── MultiReserviorSystem.mo
│ ├── input/
│ │ └── timeseries_import.csv
│ ├── src/
│ │ └── model_Multi_res.py
│ ├── output/
│ │ └── timeseries_export.csv
│ └── README.md
```
Overview of Each Component:

single_reservoir

Contains the setup for the single reservoir optimization problem.

Purpose: Determine optimal release quantities given rainfall and inflow for one reservoir.

Key Files:

input files: timeseries_import.csv inflow from WVIC data at 6-hour step

model specification — Reservoir.mo modelica files specify the parameters an variables 

optimization script: model_single_res.py  python script using RTC tool to read the input file and solve the single model using LP solver

output file — timeseries_export.csv optimal release quantity inflow at 6-hour step




reservoir_with_dam (multi_res)

Defines the optimization setup for the reservoir + downstream dam system.

Purpose: Jointly optimize release from an upstream reservoir and operations at a downstream dam.

Key Files:

input files: timeseries_import.csv inflow from WVIC data at 6-hour step

model specification — Reservoir.mo modelica files specify the parameters an variables 

optimization script: model_multi_res.py  python script using RTC tool to read the input file and solve the single model using LP solver

output file — timeseries_export.csv optimal release quantity inflow at 6-hour step



How to Use:

1. create a virtual environment using python 
python -m venv env

2. activate the virtual environment 
env/Scripts/Activate

3. install rtc-tool 2.7
pip install rtc-tools==2.7.3

4 execute the script
naivagate to the python script path (e.g. cd problem/single_res/src) and then call python model_single_res.py. the optimized quantity will be saved in output folder.

5. do not change the folder structure otherwise the model will report errors


 
