"""
run_optimization.py
───────────────────
Entry point for the 2-reservoir / 2-dam RTC-Tools optimization.

Run from the project folder:
    python run_optimization.py

Outputs are written to the output/ subfolder by RTC-Tools automatically.
"""

import os
import glob
from datetime import datetime
import pandas as pd
from optimization_problem import ReservoirOptimization


def clear_cache(folder: str) -> None:
    """
    Delete all pymoca cache files in the given folder.
    This forces pymoca to recompile model.mo from scratch,
    ensuring any changes to the Modelica file are picked up.
    """
    pattern = os.path.join(folder, "*.pymoca_cache")
    cache_files = glob.glob(pattern)
    for f in cache_files:
        os.remove(f)
        print(f"  [cache] Deleted: {os.path.basename(f)}")
    if not cache_files:
        print("  [cache] No cache files found — will compile from scratch.")


def main():
    # ── Paths ─────────────────────────────────────────────────────────────────
    base_dir   = os.path.dirname(os.path.abspath(__file__))
    input_dir  = base_dir
    model_dir  = base_dir
    output_dir = os.path.join(base_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("  RTC-Tools Reservoir Optimization")
    print("  2 reservoirs | 2 dams | minimize storage deviation")
    print("=" * 60)

    # ── Always clear pymoca cache so model.mo changes are picked up ───────────
    print("\n  Clearing Modelica cache...")
    clear_cache(base_dir)

    # ── Build and solve ───────────────────────────────────────────────────────
    print("\n  Building optimization problem...")
    problem = ReservoirOptimization(
        model_folder  = model_dir,
        input_folder  = input_dir,
        output_folder = output_dir,
        start_time    = datetime(2024, 1, 1, 0, 0, 0),
        end_time      = datetime(2024, 1, 4, 0, 0, 0),
    )

    print("  Running optimizer...\n")
    problem.optimize()

    # ── Read results ──────────────────────────────────────────────────────────
    results_path = os.path.join(output_dir, "timeseries_export.csv")
    if not os.path.exists(results_path):
        print("\n[WARNING] No output file found. Check solver logs above.")
        return

    df = pd.read_csv(results_path)
    print("\n── Results ──────────────────────────────────────────────")
    print(df.to_string(index=False))

    # ── Constraint check ──────────────────────────────────────────────────────
    print("\n── Constraint Check ─────────────────────────────────────")
    checks = [
        ("V_reservoir_1",      50_000, 200_000, "m³"),
        ("V_reservoir_2",      40_000, 160_000, "m³"),
        ("Q_dam_1",                10,     120, "m³/s"),
        ("Q_dam_2",                 8,     100, "m³/s"),
        ("Q_rel_reservoir_1",       5,     100, "m³/s"),
        ("Q_rel_reservoir_2",       5,      80, "m³/s"),
    ]
    all_ok = True
    for col, lo, hi, unit in checks:
        if col not in df.columns:
            print(f"  {col:30s}  [not in output]")
            continue
        vmin, vmax = df[col].min(), df[col].max()
        ok = (vmin >= lo - 1e-3) and (vmax <= hi + 1e-3)
        status = "✅" if ok else "❌"
        if not ok:
            all_ok = False
        print(f"  {col:30s}  min={vmin:>10.2f}  max={vmax:>10.2f}  {status}")
    print("\n  " + ("All constraints satisfied ✅" if all_ok
                    else "Some constraints violated ❌ — check output above"))

    # ── Storage target deviation ───────────────────────────────────────────────
    print("\n── Storage Target Deviation ─────────────────────────────")
    targets = {"V_reservoir_1": 150_000, "V_reservoir_2": 100_000}
    for col, target in targets.items():
        if col in df.columns:
            deviation = (df[col] - target).abs()
            print(f"  {col:30s}  target={target:>10,.0f}  "
                  f"mean_dev={deviation.mean():>10.2f}  "
                  f"max_dev={deviation.max():>10.2f}  m³")

    print("\n  Results saved to:", results_path)
    print("=" * 60)


if __name__ == "__main__":
    main()
