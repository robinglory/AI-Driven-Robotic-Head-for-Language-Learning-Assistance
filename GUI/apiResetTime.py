import datetime

reset_ms = 1754870400000
reset_s = reset_ms / 1000  # convert ms to seconds

reset_time = datetime.datetime.fromtimestamp(reset_s)
print("Rate limit resets at:", reset_time)
