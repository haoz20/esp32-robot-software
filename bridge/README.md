# bridge

Laptop-side backend for `ui_laptop_control.html`. It gives the page an
**Autonomy** toggle (the robot drives itself) and a **Detection** toggle (YOLO
boxes on the video, including while you drive manually).

```bash
conda activate esp32-robot-autonomy
python -m bridge          # then open ui_laptop_control.html
```

Ctrl+C (or `kill`) stops it, and stops the robot. Without the bridge running
the page still works for manual driving: it falls back to the robot's own
stream and greys out the toggles.

## Why it exists

The robot's camera (`:81/stream`) serves **one client at a time**, and a
browser can't run the YOLO model. So the bridge is the robot's only stream
client and re-serves the video to the page, with boxes drawn when Detection
is on. It reuses `autonomy/`'s `FrameGrabber`, `Detector` and `control_loop`
unchanged.

While the bridge runs it holds the robot's stream, so `python -m
autonomy.main` and `python -m stream.view` can't run at the same time.

## API (`http://localhost:8001`)

| Endpoint | |
|---|---|
| `GET /stream` | MJPEG video, with YOLO boxes when Detection is on |
| `GET /status` | modes, nav state, detections, stream health (JSON) |
| `POST /mode` | `{"auto": true/false, "detect": true/false}`, either key optional |

All responses carry CORS headers, so the page can read them.

## Safety

- Turning Autonomy off always sends `/stop`, again after the control loop
  finishes its current tick.
- Manual input wins: a drive key/button or Stop on the page turns Autonomy off
  (stopping the robot) before the manual command is sent.
- The page polls `/status` twice a second. If no poll arrives for
  `HEARTBEAT_TIMEOUT_S` (3s) -- tab closed, laptop asleep -- the bridge turns
  Autonomy off. A background tab that the browser throttles hard can trip
  this too; keep the page visible while Autonomy runs.
- Stale frames hold the robot stopped, as in `autonomy/`.

Options: `--port`, `--robot-ip`, `--robot-http-port`, `--robot-stream-port`,
`--model`. Tunables are in `bridge/config.py`; robot and autonomy settings
stay in `autonomy/config.py`.

## Test

    pytest bridge/tests
