"""Thin HTTP wrapper around the robot's drive endpoints.

Mirrors the request pattern the existing webapp uses
(webapp/src/hooks/useRobot.js): a plain GET per command. The firmware's
drive endpoints run continuously until /stop is called — this class does
not pulse or time anything itself, that responsibility lives in main.py.

Uses a single persistent requests.Session so repeated commands reuse one
TCP connection (HTTP keep-alive) instead of opening a new connection per
call. The autonomy loop issues commands far more often than a human
manually driving would (continuously while searching, not just on
keypress), and repeated connection setup/teardown is real overhead on
the ESP32's constrained network stack -- confirmed as a real problem on
hardware: drive commands started timing out under the autonomy loop's
request rate even though manual control never dropped a connection.
"""

import requests


class RobotClient:
    def __init__(self, ip, port=80, timeout_s=2.0):
        self._base_url = f"http://{ip}:{port}"
        self._timeout_s = timeout_s
        self._session = requests.Session()

    def go(self):
        self._send("/go")

    def back(self):
        self._send("/back")

    def left(self):
        self._send("/left")

    def right(self):
        self._send("/right")

    def stop(self):
        self._send("/stop")

    def _send(self, path):
        self._session.get(f"{self._base_url}{path}", timeout=self._timeout_s)
