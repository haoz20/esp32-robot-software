"""Tunables for the bridge service. Robot, stream and autonomy settings stay
in autonomy/config.py; the bridge reuses them."""

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8001

# Autonomy turns itself off if no UI has polled /status for this long (the
# UI polls every 0.5s; a closed tab or sleeping laptop stops the polls).
HEARTBEAT_TIMEOUT_S = 3.0

# Re-encoding quality for /stream. The robot's own frames are already JPEG;
# keep this high so re-serving adds little visible loss.
STREAM_JPEG_QUALITY = 85
STREAM_POLL_S = 0.01
# /stream marks the video "STREAM STALLED" once the newest frame is older
# than this.
STALE_AFTER_S = 1.0
