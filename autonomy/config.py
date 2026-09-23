"""Tunable constants for the autonomy service.

All values here are expected to need empirical tuning against the real
robot; nothing in navigator.py, detector.py, robot_client.py, or stream.py
hardcodes these inline.
"""

# --- Robot connection ---
ROBOT_IP = "192.168.4.1"
ROBOT_HTTP_PORT = 80
ROBOT_STREAM_PORT = 81
ROBOT_HTTP_TIMEOUT_S = 2.0

# --- Detection model ---
MODEL_PATH = "autonomy/models/best.pt"
CONFIDENCE_THRESHOLD = 0.5

# --- Navigation thresholds ---
DEADZONE_FRACTION = 0.15
ARRIVAL_HEIGHT_FRACTION = 0.6
LOST_TARGET_TICKS = 3
ROTATION_STEPS_PER_SWEEP = 12

# --- Motor pulse durations (seconds) ---
TURN_PULSE_S = 0.2
CREEP_PULSE_S = 0.4

# --- Control loop ---
LOOP_INTERVAL_S = 0.25
KILL_SWITCH_KEY = ord(" ")
