# ESP32 Robot Control — laptop-side UI

React + Vite control panel for the LAFVIN ESP32-CAM 4WD robot car.

This app runs **entirely on your laptop**. It is not served by the robot and
nothing here gets flashed to the ESP32 — it just sends HTTP requests to the
firmware already running on the board.

## Running

```bash
npm install
npm run dev
```

Then open the printed URL (default <http://localhost:5173>).

To produce a static build you can open directly from disk or host anywhere:

```bash
npm run build      # -> dist/
npm run preview    # serve dist/ locally
```

## Connecting to the robot

1. Power on the robot.
2. Join its WiFi network (`ESP32-CAM Robot`, no password).
3. Set **Robot IP** in the header if it is not the default `192.168.4.1`.

The Link indicator turns green once a command gets a response.

## Controls

| Key | Action |
| --- | --- |
| `W` `A` `S` `D` | drive — hold to move, release to stop |
| `Left Shift` | immediate stop |
| `Q` / `E` | light on / off |
| `Space` | shoot |

Bindings use `KeyboardEvent.code`, so they follow physical key *position* and
behave the same on any keyboard layout.

## Architecture

```
src/
  constants/commands.js      command ids (= firmware endpoints), key bindings, timings
  hooks/
    useRobot.js              transport: command -> GET, plus link status
    useRobotControl.js       state machine: what the robot is doing
    useKeyboardControls.js   binds physical keys to the state machine
  components/
    AppHeader.jsx            title + robot IP field
    Panel.jsx                shared card shell
    ControlButton.jsx        hold-to-drive and tap buttons
    DrivePanel.jsx           d-pad, light, shoot
    CameraStream.jsx         MJPEG <img> + placeholder
    StatusPanel.jsx          live drive/light/shoot/link readout
    KeymapPanel.jsx          key reference
  App.jsx                    wires the hooks to the panels
  styles.css                 all styling (plain CSS, class names as in the original)
```

Command ids double as firmware endpoint paths: `go` → `GET /go`. These routes
live in `../app_httpd.cpp` (`startCameraServer`).

### Notes

- **Fresh `XMLHttpRequest` per command.** Reusing one object aborts whatever is
  in flight, and an aborted `/stop` is the one failure that matters.
- **`driveRef` mirrors the `drive` state.** Window-level key listeners are
  registered once; reading React state inside them would see a stale value.
- **Blur stops the robot.** If the window loses focus mid-press the `keyup`
  never arrives, so the robot would otherwise keep driving.
- **CORS.** The firmware sends no CORS headers on the drive routes, so the
  browser blocks *reading* those responses — but the request still reaches the
  robot and the motors still move. The Link indicator may therefore read
  "no response" even while driving works. Camera frames are unaffected: `<img>`
  is not subject to that restriction.
- **`/shoot` needs firmware.** The endpoint only exists after flashing the
  updated `app_httpd.cpp`, and even then actuates nothing — there is no firing
  hardware in this kit.
