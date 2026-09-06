# generate_run.py
# Builds a synthetic autoclave cure run, one reading per minute.

RAMP_RATE = 3.0        # degrees F per minute
SOAK_TEMP = 350.0      # degrees F
START_TEMP = 70.0      # room temperature
SOAK_MINUTES = 120     # hold time at temperature
COOL_RATE = 5.0        # degrees F per minute coming down
END_TEMP = 150.0       # stop logging here

temperature = START_TEMP
minute = 0

while temperature + RAMP_RATE <= SOAK_TEMP:
    print(minute, round(temperature, 1))
    temperature = temperature + RAMP_RATE
    minute = minute + 1

temperature = SOAK_TEMP

# soak - hold at temperature
for _ in range(SOAK_MINUTES):
    print(minute, round(temperature, 1))
    minute = minute + 1

# cool down
while temperature > END_TEMP:
    print(minute, round(temperature, 1))
    temperature = temperature - COOL_RATE
    minute = minute + 1

print("Run complete at minute", minute)