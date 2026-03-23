"""
check_model.py  —  diagnostic for pymoca 0.9.x / RTC-Tools 2.8
Run from the project ROOT folder (one level above model/, input/, src/).

Usage:
    python check_model.py
"""

import os, sys

# ── versions ──────────────────────────────────────────────────────────────────
try:
    import rtctools
    print(f"rtc-tools : {rtctools.__version__}")
except Exception:
    print("rtc-tools : (no __version__)")

try:
    import pymoca
    print(f"pymoca    : {pymoca.__version__}")
except Exception:
    print("pymoca    : (no __version__)")

# ── locate model folder ───────────────────────────────────────────────────────
base_dir   = os.path.dirname(os.path.abspath(__file__))
model_dir  = os.path.join(base_dir, "model")
model_name = "ReservoirOptimization"

print(f"\nmodel_folder : {model_dir}")
print(f"model_name   : {model_name}")
print("-" * 50)

if not os.path.isdir(model_dir):
    print(f"ERROR: folder not found: {model_dir}")
    sys.exit(1)

mo_file = os.path.join(model_dir, f"{model_name}.mo")
if not os.path.isfile(mo_file):
    print(f"ERROR: .mo file not found: {mo_file}")
    sys.exit(1)

print(f"Found .mo   : {mo_file}")

# ── compile ───────────────────────────────────────────────────────────────────
import pymoca.backends.casadi.api as api

try:
    model = api.transfer_model(
        model_folder     = model_dir,
        model_name       = model_name,
        compiler_options = {"cache": False},
    )
    print("Compilation : SUCCESS\n")
except Exception as e:
    print(f"Compilation : FAILED\n{e}")
    sys.exit(1)

# ── inspect variable objects — find the right attribute ───────────────────────
def var_name(v):
    """Robustly extract a variable name from whatever pymoca returns."""
    for attr in ("name", "symbol", "id", "__str__"):
        try:
            val = getattr(v, attr)
            if callable(val):
                return str(val())
            return str(val)
        except Exception:
            continue
    return repr(v)

def show_vars(label, var_list):
    if not var_list:
        print(f"  {label:12s}: (none)")
        return
    # Also print all attributes of first variable so we can see the schema
    first = var_list[0]
    attrs = [a for a in dir(first) if not a.startswith("_")]
    print(f"  {label:12s} attributes : {attrs}")
    names = [var_name(v) for v in var_list]
    print(f"  {label:12s} values     : {names}")

show_vars("states",     model.states)
show_vars("alg_states", model.alg_states)
show_vars("inputs",     model.inputs)
show_vars("outputs",    model.outputs)
print(f"\n  equations   : {len(model.equations)}")
print("\nModel structure looks good — ready to optimize!")
