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

# --- Camera stream ---
# A frame older than this is never acted on: the robot is held stopped
# until a fresh one arrives (short WiFi gaps are routine).
MAX_FRAME_AGE_S = 1.0
STREAM_CONNECT_TIMEOUT_S = 5.0
# Wait this long for the robot's first response: it streams to one client
# at a time, so a new connection can sit unanswered for a while.
STREAM_HEADER_TIMEOUT_S = 10.0
# Only after no bytes at all for this long is the connection treated as
# dead and reopened.
STREAM_STALL_TIMEOUT_S = 3.0
# How long the control loop holds still before re-checking for a fresh frame.
STALE_FRAME_WAIT_S = 0.2

# --- Detection model ---
MODEL_PATH = "autonomy/models/best.pt"
CONFIDENCE_THRESHOLD = 0.5

# --- Navigation thresholds ---
DEADZONE_FRACTION = 0.15
ARRIVAL_HEIGHT_FRACTION = 0.6
LOST_TARGET_TICKS = 3
ROTATION_STEPS_PER_SWEEP = 12

# --- Continuous search ---
# True: spin right without stopping and look at every frame (fast). False:
# the original pulse-turn-then-look search.
CONTINUOUS_SEARCH = True
# Lower than CONFIDENCE_THRESHOLD: mid-spin frames are blurred, and a
# sighting only stops the robot to re-check on a still frame.
SEARCH_CONFIDENCE_THRESHOLD = 0.35
# Pause after stopping a spin so the confirming frame is still, not blurred.
SPIN_SETTLE_S = 0.4
# After spinning this long with no sighting, creep forward for a new view.
MAX_SPIN_S = 8.0
# Left pulses tried after a sighting to undo overshoot before spinning again.
MAX_CORRECTION_STEPS = 4

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
# The display loop's cv2.waitKey interval; it redraws every pass.
DISPLAY_INTERVAL_MS = 15
