import pandas as pd
import time
import numpy as np

big_eau_p = r"C:\Users\ylee\OneDrive - Research Triangle Institute\Documents\reservior_op\test\big_eau_test_data.csv"
big_eau   = pd.read_csv(big_eau_p)

print(big_eau.head())


# convert the time into the timeframe format

big_eau["datetime"] = pd.to_datetime(big_eau["date"] + " " + big_eau["time"])
big_eau = big_eau[['datetime','Q_in']]

big_eau["datetime"] = pd.to_datetime(big_eau["datetime"])

# Format
big_eau["datetime"] = (
    big_eau["datetime"]
    .dt.strftime("%m/%d/%Y %H:%M")
    .str.lstrip("0")
    .str.replace("/0", "/", regex=False)
)


# big_eau["datetime"] = big_eau["datetime"].dt.strftime("%-m/%-d/%Y %-H:%M")
print(big_eau.head())
big_eau.to_csv("big_eau_timeformated.csv", index=False) 