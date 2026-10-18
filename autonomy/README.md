# Autonomy service

Drives the robot toward a detected red or green bottle using the ESP32
camera and a YOLO model. Runs standalone, alongside the manual webapp
control — it only calls the robot's existing HTTP endpoints.

See [../docs/superpowers/specs/2026-09-23-autonomy-service-design.md](../docs/superpowers/specs/2026-09-23-autonomy-service-design.md)
for the design.

## Setup

    conda env create -f autonomy/environment.yml
    conda activate esp32-robot-autonomy

Drop a trained YOLO model (classes `red_bottle`, `green_bottle`) at
`autonomy/models/best.pt` before running.

## Run

    python -m autonomy.main

Press SPACE in the debug window to stop the robot and exit at any time.

The debug window redraws at the stream's frame rate; the control loop runs
in a separate thread, so motor pulses don't make the video lag.

By default the robot searches by spinning right continuously and checking
every frame (`CONTINUOUS_SEARCH` in `config.py`). A sighting mid-spin stops
it; it then re-checks on a still frame and turns back left in short pulses
if it overshot. Set `CONTINUOUS_SEARCH = False` for the original
pulse-turn-then-look search. If frames stop arriving for more than
`MAX_FRAME_AGE_S`, the robot is held stopped until they resume.

## Test

    pytest autonomy/tests
