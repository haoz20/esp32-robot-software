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
(`navigator.py`'s `step()`) → execute as a pulse-then-stop
(`robot_client.py`'s `RobotClient`).

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
- Stream reconnect uses exponential backoff (capped at 10s); the robot is
  kept stopped for the whole duration of a reconnect wait.
- `os.environ` OpenMP thread-limiting (`KMP_DUPLICATE_LIB_OK`,
  `OMP_NUM_THREADS`, etc.) is set at the very top of `main.py` before any
  cv2/torch import — required on macOS where opencv-python and
  ultralytics' torch each bundle their own `libomp.dylib`; removing or
  reordering this reintroduces a process-abort/segfault.

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
