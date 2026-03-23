# RTI Agriculture Trade Policy Simulation Impact Model (TradeSIM)

**Authors:** Stanley Lee, Smit Vasquez Caballero, John Farrell, Anna Godwin, Joe Johnson  
**Last Update:** 02/04/26  

**Short Description:** Python package for Agriculture Trade Policy Simulation Model and UX.


tradeSIM/
├── main/
│ ├── data/
│ │ └── elasticities.dta
│ │ └── production.dta
│ │ └── tariff.dta
│ │ └── TDM_clean4.dta
│ │ └── trade.dta
│ └── expand_TDM_dataset_v2.py
│ └── inputs_module.py
│ └── calc_module.py
│ └── atpsm.py
│ └── multiproudcts_app2.py
│ └── requirements.txt


key files: 

**read raw data and create input matrix**
1. expand_TDM_dataset_v2.py   - Loads 2021-2024 TDM commodity datasets only (used for the conference presentation)
2. inputs_module.py           – Loads and processes default input data from `.dta` files (`trade.dta`, `production.dta`, `tariff.dta`, `elasticity.dta`).  
3. custom_inputs_module.py    - Handles user-defined input data. Create input CSVs in the required format (example files provided in `./data`).

**calculations and solving for market clearance price**
1. calc_module.py             – Take the input matrix and carry out core calculations, generate report/table generation, and prepare data visualization.  

**control script that combine the input and calculation modules**
1. atpsm.py – the scripts call both input and calculation modules using the `run_fastm()` function.


how to run the model through python(in terminal)
step 1 ## Create a Virtual Environment (Optional, Recommended)

### Windows

# 0 before you start check if the python.exe have been mapped to PATH

# check if python.exe has been set in the environment variables

Find where your python.exe is located (usually C:\Users\<YourUser>\AppData\Local\Programs\Python\Python312).

Method 1

Open Windows Terminal (PowerShell) as Administrator.

Run the following command (replace the path with your actual folder):

PowerShell
$targetPath = "C:\Users\<YourUser>\AppData\Local\Programs\Python\Python312"
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";" + $targetPath, "User")


Method 2: The Manual GUI Way (Visual)
If you prefer the standard Windows interface, follow these steps:

Open the Start Menu, search for "Edit the system environment variables", and hit Enter.

In the window that appears, click the Environment Variables button at the bottom right.

In the User variables section (top box), find Path and click Edit.

Click New and paste the path to your Python folder.

Click New again and paste the path to your Python \Scripts folder.

Click OK on all windows.


```bash
# 1. Open terminal

# 2. Navigate to project directory
cd path/to/project

# 3. Create virtual environment
python -m venv env

# 4. Activate virtual environment
env\Scripts\activate
```

# 5. navigate the tradeSIM folder containing the moudles
cd path/to/project/tradeSIM

# 6. execute the script
python astpsm.py




