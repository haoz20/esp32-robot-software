# ESP32 Robot Software

Software for a LAFVIN ESP32-CAM 4WD robot car (AI-Thinker module, OV3660
camera): the firmware that runs on the board, a laptop-side control UI, and a
Python service that drives the robot autonomously toward a detected target
using a YOLO model.

The three pieces are independent and talk to each other only over the
firmware's HTTP API — you can flash the firmware and drive manually with the
webapp, or add the autonomy service on top, without changing anything else.

## Components

### Firmware ([`ESP32_Camera_4WD_Robot_Car_OV3660_V3.ino`](ESP32_Camera_4WD_Robot_Car_OV3660_V3.ino), [`app_httpd.cpp`](app_httpd.cpp), [`camera_index.h`](camera_index.h))

Arduino sketch flashed to the ESP32-CAM. Starts a WiFi access point
(`ESP32-CAM Robot`), serves an MJPEG camera stream, and exposes an HTTP API
for driving the motors and light:

| Endpoint | Action |
| --- | --- |
| `/go`, `/back`, `/left`, `/right` | drive |
| `/stop` | stop motors |
| `/ledon`, `/ledoff` | onboard light |
| `/capture` | single JPEG frame |
| `/stream` | MJPEG video stream |
| `/status` | current state |

Build/flash with the Arduino IDE (board: AI-Thinker ESP32-CAM).

### Laptop control UI ([`webapp/`](webapp/))

React + Vite app that runs entirely on your laptop and drives the robot over
its HTTP API — nothing here is flashed to the board. WASD to drive, Q/E for
the light, Space to shoot. See [webapp/README.md](webapp/README.md) for setup,
keybindings, and architecture notes.

```bash
cd webapp
npm install
npm run dev
```

Two static HTML variants of the control panel ([`ui_laptop_control.html`](ui_laptop_control.html),
[`ui_preview.html`](ui_preview.html)) are also available if you'd rather not
run a dev server.

### Autonomy service ([`autonomy/`](autonomy/))

Standalone Python service that grabs frames from the robot's camera stream,
runs a YOLO detector for a target (e.g. a red or green bottle), and drives
the robot toward it by calling the same HTTP endpoints the webapp uses. See
[autonomy/README.md](autonomy/README.md) for setup and
[docs/superpowers/specs/2026-09-23-autonomy-service-design.md](docs/superpowers/specs/2026-09-23-autonomy-service-design.md)
for the design.

```bash
conda env create -f autonomy/environment.yml
conda activate esp32-robot-autonomy
python -m autonomy.main
```

Requires a trained YOLO model at `autonomy/models/best.pt` (not tracked in
git — see [docs/training-local-gpu.md](docs/training-local-gpu.md) for
training it yourself).

## Repo layout

```
ESP32_Camera_4WD_Robot_Car_OV3660_V3.ino   firmware entry point
app_httpd.cpp, camera_index.h              firmware HTTP server + camera
webapp/                                    laptop control UI (React)
autonomy/                                  autonomous target-following service
docs/                                      design docs, specs, training notes
```

`models/` and `datasets/` are gitignored — trained weights and training data
are expected to be large and are not checked into this repo.

## Typical usage

1. Flash the firmware to the ESP32-CAM.
2. Power on the robot and join its WiFi network (`ESP32-CAM Robot`).
3. Either:
   - drive manually with the [webapp](webapp/), or
   - run the [autonomy service](autonomy/) to have it follow a target on its
     own.
