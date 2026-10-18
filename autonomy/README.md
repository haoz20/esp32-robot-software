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

## Test

    pytest autonomy/tests
