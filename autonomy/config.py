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

# --- Debug window ---
# The ESP32's stream frame is small (its native resolution); cv2's default
# window mode locks to that exact pixel size and just shows blank padding
# on maximize. Displaying at this larger fixed size makes it actually
# watchable.
DEBUG_WINDOW_NAME = "autonomy"
DEBUG_WINDOW_WIDTH = 960
DEBUG_WINDOW_HEIGHT = 720
