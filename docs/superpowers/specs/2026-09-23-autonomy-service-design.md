# Autonomy Service: YOLO-Guided Bottle Approach

Status: approved for implementation planning
Date: 2026-09-23

## Purpose

Add a standalone service that drives the robot car by itself: find a red or
green bottle using the ESP32 camera and a custom-trained YOLO model, drive
toward it, and search (rotate, then creep) when nothing is visible. It runs
alongside the existing manual webapp control, not instead of it — same
robot, same firmware, no manual-control code touched.

## Scope

In scope now: the autonomy service itself (`autonomy/` — a new Python
package in this repo), assuming a trained YOLO model file with
`red_bottle` / `green_bottle` classes already exists.

Explicitly out of scope for this spec (separate follow-on work):
- Collecting and labeling the training dataset (Roboflow) and training the
  YOLO model itself. The interface boundary is a `models/best.pt` file with
  those two class names — however that file is produced doesn't affect this
  design.
- Any change to the webapp UI to start/stop autonomy mode from the browser.
  For now the service is launched and killed from a terminal.
- Any firmware (`.ino` / `app_httpd.cpp`) changes. The service only calls
  existing HTTP endpoints.

## Constraints from the existing system

- The ESP32-CAM has no NN-capable hardware — inference must happen off the
  robot. Inference runs on the laptop.
- Drive endpoints (`/go`, `/back`, `/left`, `/right`) are **continuous until
  `/stop`** — confirmed in `app_httpd.cpp`'s `robot_fwd()` /
  `robot_left()` / etc., which set PWM duty directly with no timer. There is
  no "move for N ms" primitive in firmware. Any commanded motion must be
  paired with an explicit follow-up `/stop`, the same hold-then-release
  pattern the existing webapp uses (`webapp/src/hooks/useRobot.js`).
- No ultrasonic/IR/distance sensor exists on this robot (checked
  `ESP32_Camera_4WD_Robot_Car_OV3660_V3.ino` — camera only). Any blind
  driving (e.g. during search) is genuinely blind. This is a real risk,
  mitigated by short pulse durations and a kill switch, not eliminated.
- Camera stream is MJPEG on port 81 (`GET http://<ip>:81/stream`); a single
  still frame is available via `GET http://<ip>/capture`.
- Default robot IP is `192.168.4.1` (robot runs as its own WiFi AP), same
  default the webapp uses.

## Architecture

A new standalone Python service, run manually from a terminal on the
laptop, separate process from the webapp. Directory layout, new top-level
`autonomy/` in this repo:

```
autonomy/
  environment.yml     # conda env: python, ultralytics, opencv-python, requests
  config.py           # robot IP, thresholds, pulse durations, model path
  robot_client.py      # HTTP wrapper: go()/back()/left()/right()/stop()
  stream.py            # MJPEG frame grabber against :81/stream
  detector.py           # loads YOLO model, runs inference -> Detection list
  navigator.py           # pure state machine: detections+state -> command+state
  main.py                 # wires loop + debug window + kill switch together
  models/                  # trained weights dropped in here (gitignored)
  tests/
    test_navigator.py       # unit tests against synthetic detections
```

`navigator.py` takes no dependency on HTTP, OpenCV, or YOLO — it's a pure
function of `(current_state, detections) -> (command, next_state)`, so it
can be fully unit tested without the robot, camera, or model present.

Environment is managed with conda (`environment.yml`), matching the user's
existing workflow, rather than a bare `requirements.txt`.

## Data flow / control loop

`main.py` runs a loop, roughly every 200–300ms (not full video frame rate —
no benefit to reacting faster than a pulse duration, and it keeps
laptop/WiFi load low):

1. Grab the latest frame from `stream.py`.
2. Run `detector.py` on it → list of `Detection(class, confidence, x, y, w, h)`.
3. Pass detections + current state into `navigator.py` → returns a `Command`
   (one of: turn-left, turn-right, creep-forward, stop, none) and the next
   state.
4. If a command other than "none"/"stop" is returned, `main.py` sends it via
   `robot_client.py`, holds for that command's configured pulse duration,
   then sends `/stop`.
5. Draw the frame with detection boxes, labels/confidence, and the current
   state name into an OpenCV debug window.
6. Check for the kill-switch keypress; if pressed, send `/stop` and exit the
   loop immediately.

## Navigation state machine (`navigator.py`)

States: `SEARCHING`, `APPROACHING`, `ARRIVED`.

**SEARCHING** — no detection above the confidence threshold this tick:
- Emit a turn-right pulse, incrementing a rotation-step counter.
- Once the counter reaches a configured "one full rotation" count, instead
  emit one forward creep pulse and reset the counter — a blind
  spiral-outward step between rotation sweeps.
- Any detection above threshold → transition to `APPROACHING`.

**APPROACHING** — best detection (highest confidence across both classes;
no color preference) above threshold:
- Compute the detection box center's horizontal offset from frame center as
  a fraction of frame width.
- If `|offset| > deadzone`: emit turn-left or turn-right pulse (toward
  center), stay in `APPROACHING`.
- Else if box height (as a fraction of frame height) `< arrival_threshold`:
  emit a forward creep pulse, stay in `APPROACHING`.
- Else (centered and large enough): transition to `ARRIVED`.
- If no detection above threshold for `lost_target_ticks` consecutive ticks
  (not a single dropped frame — avoids flicker on a momentary miss):
  transition back to `SEARCHING`.

**ARRIVED** — target reached:
- Emit `/stop`, log which color was reached.
- Terminal for this run: the service keeps running (debug window stays up,
  kill switch still works) but issues no further drive commands. Restart
  the process for another run. (Matches the agreed scope: approach
  whichever bottle is seen first, not a multi-bottle mission.)

All thresholds (`confidence_threshold`, `deadzone`, `arrival_threshold`,
`lost_target_ticks`, rotation-step count, pulse durations) live in
`config.py` as named constants — expect these to need empirical tuning
against the real robot and are not hardcoded inline in `navigator.py`.

## Safety

- Every drive command is a short, explicitly-bounded pulse followed by
  `/stop` — the car is never left issuing an open-ended move by the
  autonomy loop itself.
- Live OpenCV debug window is always shown while the service runs: camera
  feed, detection boxes, current FSM state.
- Kill switch: a keypress in that window (e.g. spacebar) immediately sends
  `/stop` and ends the loop — takes effect within one loop tick.
- If the stream connection drops, or a drive command's HTTP request fails
  (robot unreachable), `main.py` makes a best-effort `/stop` call, then
  either retries the connection with backoff (stream) or exits (persistent
  command failure) rather than continuing to loop blind against a robot
  it's lost contact with.

## Testing

- `tests/test_navigator.py`: unit tests driving the pure state machine with
  synthetic `Detection` lists — e.g. "centered, large detection while
  APPROACHING → ARRIVED", "no detection for `lost_target_ticks` ticks while
  APPROACHING → SEARCHING", "rotation counter reaching its limit while
  SEARCHING → one creep pulse, counter resets". No hardware, camera, or
  model needed to run these.
- `robot_client.py` and `stream.py` are thin enough that they're smoke
  tested manually against the real robot rather than unit tested against
  mocks.
- End-to-end verification is manual: run the service against the real
  robot in a controlled, obstacle-light space, confirm the kill switch
  stops motion within a tick, and observe search → approach → arrived
  transitions look sane for both bottle colors.

## Open items deferred to later work

- Training sub-project (data collection via the robot's own camera,
  Roboflow labeling, Ultralytics fine-tuning) — produces `models/best.pt`.
- Webapp integration to start/stop autonomy mode from the browser instead
  of a terminal.
