# Autonomy service

Drives the robot toward a detected red or green bottle using the ESP32
camera and a YOLO model. Runs standalone, alongside the manual webapp
control — it only calls the robot's existing HTTP endpoints.

See [../docs/superpowers/specs/2026-09-23-autonomy-service-design.md](../docs/superpowers/specs/2026-09-23-autonomy-service-design.md)
for the design.

## Setup

    conda env create -f autonomy/environment.yml
    conda activate esp32-robot-autonomy
    bash autonomy/macos_fix_openmp.sh   # macOS only; re-run after reinstalling torch

On macOS, torch's bundled OpenMP runtime clashes with the one conda's numpy
loads and segfaults on the first YOLO inference; the script points torch at
the env's copy. It only changes the local env, so Windows is unaffected.

Drop a trained YOLO model (classes `red_bottle`, `green_bottle`) at
`autonomy/models/best.pt` before running.

## Run

    python -m autonomy.main

Press SPACE in the debug window to stop the robot and exit at any time.

The debug window redraws at the stream's frame rate; the control loop runs
in a separate thread, so motor pulses don't make the video lag.

Search works like driving by hand: tap left once, hold still for
`SEARCH_PAUSE_S` (1.5s) and look, tap again. After a full sweep
(`ROTATION_STEPS_PER_SWEEP` taps) with nothing found it creeps forward for a
new view. It only approaches a bottle detected at `CONFIDENCE_THRESHOLD`
(0.8) or above; weaker detections still show in the window but are ignored.
While approaching it keeps the bottle centered, and once the bottle's box is
taller than `NEAR_HEIGHT_FRACTION` it creeps in shorter steps, stopping at
`ARRIVAL_HEIGHT_FRACTION`.

**Calibrate the stopping distance:** there's no distance sensor, so "5cm
away" is judged by the box height. Put a bottle ~5cm in front of the camera,
read `h=` in the log line (`sees: red_bottle 0.91 h=0.87`), and set
`ARRIVAL_HEIGHT_FRACTION` to that value.

`CONTINUOUS_SEARCH = True` switches to spinning without stopping instead. If
frames stop arriving for more than `MAX_FRAME_AGE_S`, the robot is held
stopped until they resume.

## Test

    pytest autonomy/tests
