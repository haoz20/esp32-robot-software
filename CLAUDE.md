# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Software for a LAFVIN ESP32-CAM 4WD robot car (AI-Thinker module, OV3660
camera): firmware for the board, a laptop-side control UI, and a Python
service that drives the robot autonomously toward a detected target using a
YOLO model. The three pieces only talk to each other over the firmware's
HTTP API — each can be used independently.

- `ESP32_Camera_4WD_Robot_Car_OV3660_V3/` — Arduino sketch + `app_httpd.cpp`/`camera_index.h`, flashed to the ESP32-CAM.
- `webapp/` — React + Vite manual control UI, runs on the laptop, never flashed to the board.
- `autonomy/` — standalone Python service that follows a detected target.
- `bridge/` — laptop-side backend for `ui_laptop_control.html`: re-serves the
  stream with YOLO boxes and runs autonomy on/off from the page's toggles.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` — design docs for features (e.g. the autonomy service design/plan).

## Commands

### Autonomy service (Python)

```bash
conda env create -f autonomy/environment.yml
conda activate esp32-robot-autonomy
python -m autonomy.main          # run (needs autonomy/models/best.pt, gitignored)
pytest autonomy/tests            # all tests
pytest autonomy/tests/test_navigator.py::test_name   # single test
```

Press SPACE in the debug window to stop the robot and exit.

### Bridge (Python, same conda env)

```bash
python -m bridge                 # http://localhost:8001, then open ui_laptop_control.html
pytest bridge/tests
```

Use `preview_start` with the `laptop-ui` config to serve `ui_laptop_control.html`.

### Webapp (React/Vite)

```bash
cd webapp
npm install
npm run dev       # dev server, http://localhost:5173
npm run build     # -> dist/
npm run preview   # serve dist/ locally
```

Use `preview_start` with the `robot-control-ui` config in `.claude/launch.json` rather than running `npm run dev` via Bash.

### Firmware

Build/flash with the Arduino IDE (board: AI-Thinker ESP32-CAM). No CLI build in this repo; `build/` contains prior compiled artifacts (gitignored).

## Architecture

### Firmware ↔ everything else

The firmware exposes the only integration point in the system: an HTTP API
on the robot's own WiFi AP (`ESP32-CAM Robot`, default IP `192.168.4.1`).
Both `webapp/` and `autonomy/` are just HTTP clients of it — port 80 for
commands (`/go`, `/back`, `/left`, `/right`, `/stop`, `/ledon`, `/ledoff`,
`/capture`, `/status`), port 81 for the MJPEG stream (`/stream`). Drive
endpoints send no CORS headers, so browser clients can issue commands but
can't reliably read the response.

### Autonomy service (`autonomy/`)

A control loop in `main.py` wires four independently-testable pieces
together each tick: grab a frame (`stream.py`'s `FrameGrabber`) → detect
(`detector.py`'s `Detector`, wraps a YOLO model) → decide a command
(`navigator.py`'s `step()`) → execute as a pulse-then-stop, or a
continuous spin while searching (`robot_client.py`'s `RobotClient`). The
control loop runs in a worker thread; the main thread only redraws the
debug window at stream rate and polls the kill switch (cv2 windows must
stay on the main thread on macOS).

- `navigator.py` is a **pure state machine** (`SEARCHING` → `APPROACHING` →
  `ARRIVED`, driven by `step()`) with zero dependency on requests/cv2/
  ultralytics, so it's unit-tested without any robot/camera/model present.
  All other modules depend on this contract but not vice versa.
- `config.py` centralizes every tunable constant (thresholds, pulse
  durations, IPs/ports) — new tunables belong there, not inlined in the
  modules that use them, since these values need empirical tuning against
  the real robot.
- Every drive command is executed as a timed pulse followed by an explicit
  `/stop` with retries (`_stop_with_retries` in `main.py`): the robot has no
  obstacle sensor and its drive endpoints run until told to stop, so a
  dropped stop is the single highest-risk failure mode. On request failure
  the loop treats it as "nothing happened this tick" and retries next tick
  rather than raising — exiting the process wouldn't stop the robot either.
- A stale frame (older than `MAX_FRAME_AGE_S`) only holds the robot
  stopped; `FrameGrabber` keeps the connection open through short WiFi
  gaps and reconnects itself (exponential backoff, capped at 10s) only
  when no bytes arrive for `STREAM_STALL_TIMEOUT_S`. Don't tear the
  connection down on a stale frame: the firmware streams to one client at
  a time, so a new connection waits behind the dead one.
- Continuous search (`CONTINUOUS_SEARCH`): a mid-spin sighting only stops
  the robot and enters `CONFIRMING`, which re-checks on a still frame and
  pulses left to undo overshoot -- detection latency means the robot has
  always turned past the target by the time it's seen.
- `os.environ` OpenMP thread-limiting (`KMP_DUPLICATE_LIB_OK`,
  `OMP_NUM_THREADS`, etc.) is set at the very top of `main.py` before any
  cv2/torch import — required on macOS where opencv-python and
  ultralytics' torch each bundle their own `libomp.dylib`; removing or
  reordering this reintroduces a process-abort/segfault.

### Bridge (`bridge/`)

- The robot's `:81/stream` serves one client at a time, so the bridge is the
  only stream client and re-serves `/stream` to the page;
  `ui_laptop_control.html` falls back to the robot's stream directly only
  after several missed `/status` polls, so it never grabs the stream from a
  running bridge.
- `service.py`'s `Bridge` reuses autonomy's `control_loop` as-is in a
  thread; the detect worker idles while autonomy runs, since the control
  loop detects itself. `LockedDetector` serializes the shared model.
- `/status` polls double as a heartbeat: no poll for
  `HEARTBEAT_TIMEOUT_S` turns autonomy off. Manual drive input in the page
  turns autonomy off before sending its command.

### Webapp (`webapp/`)

See [webapp/README.md](webapp/README.md) for the full architecture map.
Key points not obvious from file layout alone:

- Command ids in `src/constants/commands.js` double as firmware endpoint
  paths (`go` → `GET /go`); the routes themselves live in `app_httpd.cpp`'s
  `startCameraServer`.
- `useRobot.js` issues a **fresh `XMLHttpRequest` per command** — reusing
  one aborts whatever is in flight, and an aborted `/stop` is the failure
  that matters most.
- `useRobotControl.js` mirrors drive state into a ref (`driveRef`) because
  the window-level key listeners are registered once and would otherwise
  read a stale value.
- Window blur sends a stop, since a `keyup` that fires while unfocused
  never reaches the listener.
