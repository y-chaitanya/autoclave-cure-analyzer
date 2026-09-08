# generate_run.py
# Builds a synthetic autoclave cure run, one reading per minute.
import csv
import random
RAMP_RATE = 3.0        # degrees F per minute
SOAK_TEMP = 350.0      # degrees F
START_TEMP = 70.0      # room temperature
SOAK_MINUTES = 120     # hold time at temperature
COOL_RATE = 5.0        # degrees F per minute coming down
END_TEMP = 150.0       # stop logging here
PRESSURE_PSI = 85.0    # held during ramp and soak
VACUUM_INHG = 25.0     # held throughout the run
VENT_RATE_PSI = 4.0    # psi per minute during cool-down
TC2_LAG = 0.85         # probe 2 responds at 85% of the rate
TC3_LAG = 0.70         # probe 3 responds at 70%
NOISE_F = 0.5          # random jitter, plus or minus

def generate_run(fault=None):
    ramp_rate = RAMP_RATE
    soak_minutes = SOAK_MINUTES
    soak_temp = SOAK_TEMP

    if fault == "slow_ramp":
        ramp_rate = RAMP_RATE / 2          # 1.5 F/min, half nominal
    elif fault == "fast_ramp":
        ramp_rate = 6.0                    # double nominal, past a 5 F/min max
    elif fault == "short_dwell":
        soak_minutes = SOAK_MINUTES // 2   # 60 min against a 120 min minimum
    elif fault == "cold_soak":
        soak_temp = SOAK_TEMP - 15.0       # 335 F, 5 F outside a 10 F tolerance

    temperature = START_TEMP
    minute = 0
    readings = []
    pressure = PRESSURE_PSI
    tc1 = START_TEMP
    tc2 = START_TEMP
    tc3 = START_TEMP

    while temperature + ramp_rate <= soak_temp:
        readings.append([minute, round(temperature, 1), round(tc1, 1), round(tc2, 1), round(tc3, 1), round(pressure, 1), VACUUM_INHG])
        tc1 = temperature + random.uniform(-NOISE_F, NOISE_F)
        tc2 = tc2 + (temperature - tc2) * TC2_LAG
        tc3 = tc3 + (temperature - tc3) * TC3_LAG
        temperature = temperature + ramp_rate
        minute = minute + 1

    temperature = soak_temp

    # soak - hold at temperature
    for _ in range(soak_minutes):
        readings.append([minute, round(temperature, 1), round(tc1, 1), round(tc2, 1), round(tc3, 1), round(pressure, 1), VACUUM_INHG])
        tc1 = temperature + random.uniform(-NOISE_F, NOISE_F)
        tc2 = tc2 + (temperature - tc2) * TC2_LAG
        tc3 = tc3 + (temperature - tc3) * TC3_LAG
        minute = minute + 1

    # cool down
    while temperature > END_TEMP:
        
        readings.append([minute, round(temperature, 1), round(tc1, 1), round(tc2, 1), round(tc3, 1), round(pressure, 1), VACUUM_INHG])
        tc1 = temperature + random.uniform(-NOISE_F, NOISE_F)
        tc2 = tc2 + (temperature - tc2) * TC2_LAG
        tc3 = tc3 + (temperature - tc3) * TC3_LAG
        pressure = max(0.0, pressure - VENT_RATE_PSI)
        temperature = temperature - COOL_RATE
        minute = minute + 1
    return readings
    
readings = generate_run("cold_soak")

with open("data/run_001.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["minute", "air_temp_f", "tc1_f", "tc2_f", "tc3_f", "pressure_psi", "vacuum_inhg"])
        writer.writerows(readings)

print("Wrote", len(readings), "readings to data/run_001.csv")