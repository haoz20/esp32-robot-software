"""HTTP API the laptop UI talks to.

    GET  /stream   MJPEG video, re-served from the bridge's one robot
                   connection, with YOLO boxes when detection is on
    GET  /status   modes, nav state, detections, stream health (JSON);
                   also the UI's heartbeat for the autonomy watchdog
    POST /mode     {"auto": bool, "detect": bool} -- either key optional

Every response carries CORS headers: the UI is opened as a local file (or
from another port), and unlike the robot's own endpoints the UI needs to
read these responses.
"""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bridge import config

_BOUNDARY = "bridgeframe"


def annotate(frame, detections, nav_state, stale):
    import cv2

    image = frame.copy()
    height, width = image.shape[:2]
    for d in detections:
        x1 = int((d.x_center - d.width / 2) * width)
        y1 = int((d.y_center - d.height / 2) * height)
        x2 = int((d.x_center + d.width / 2) * width)
        y2 = int((d.y_center + d.height / 2) * height)
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(image, f"{d.label} {d.confidence:.2f}", (x1, max(y1 - 4, 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
    if nav_state is not None:
        cv2.putText(image, nav_state.state.name, (6, 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
    if stale:
        cv2.putText(image, "STREAM STALLED", (6, height - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)
    return image


def make_handler(bridge):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # /status is polled twice a second; only log the rest.
            if not self.path.startswith("/status"):
                super().log_message(fmt, *args)

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _json(self, payload, code=200):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/status":
                bridge.heartbeat()
                self._json(bridge.status())
            elif path == "/stream":
                self._stream()
            elif path == "/":
                self._json({"service": "robot bridge", "endpoints": ["/stream", "/status", "/mode"]})
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/mode":
                self._json({"error": "not found"}, 404)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self._json({"error": "body must be JSON"}, 400)
                return
            modes = {k: body[k] for k in ("auto", "detect")
                     if k in body and isinstance(body[k], bool)}
            self._json(bridge.set_modes(**modes))

        def _stream(self):
            import cv2

            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={_BOUNDARY}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            grabber = bridge.frame_grabber
            sent_id = -1
            sent_at = 0.0
            try:
                while not bridge.closed:
                    frame_id, frame, age_s = grabber.latest()
                    now = time.monotonic()
                    stale = frame is not None and age_s > config.STALE_AFTER_S
                    # New frame: send it. No new frame for a while: resend
                    # the last one marked stalled, so the page shows it.
                    due = frame is not None and (
                        frame_id != sent_id or (stale and now - sent_at > 0.5))
                    if not due:
                        time.sleep(config.STREAM_POLL_S)
                        continue
                    detections, nav_state = bridge.overlay()
                    ok, jpg = cv2.imencode(
                        ".jpg", annotate(frame, detections, nav_state, stale),
                        [cv2.IMWRITE_JPEG_QUALITY, config.STREAM_JPEG_QUALITY])
                    if not ok:
                        continue
                    data = jpg.tobytes()
                    self.wfile.write(
                        f"--{_BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                        f"Content-Length: {len(data)}\r\n\r\n".encode() + data + b"\r\n")
                    sent_id, sent_at = frame_id, now
            except (BrokenPipeError, ConnectionResetError):
                pass  # the browser closed the stream

    return Handler


def make_server(bridge, host, port):
    server = ThreadingHTTPServer((host, port), make_handler(bridge))
    server.daemon_threads = True
    return server
