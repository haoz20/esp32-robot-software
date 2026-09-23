"""Thin HTTP wrapper around the robot's drive endpoints.

Mirrors the request pattern the existing webapp uses
(webapp/src/hooks/useRobot.js): a plain GET per command. The firmware's
drive endpoints run continuously until /stop is called — this class does
not pulse or time anything itself, that responsibility lives in main.py.
"""

import requests


class RobotClient:
    def __init__(self, ip, port=80, timeout_s=2.0):
        self._base_url = f"http://{ip}:{port}"
        self._timeout_s = timeout_s

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
        requests.get(f"{self._base_url}{path}", timeout=self._timeout_s)
