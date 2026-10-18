"""Run the bridge: python -m bridge, then open ui_laptop_control.html."""

import os

# Same macOS OpenMP workaround as autonomy/main.py; must be set before cv2
# or torch is imported.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")

import argparse
import signal

from autonomy import config as autonomy_config
from autonomy.robot_client import RobotClient
from autonomy.stream import FrameGrabber
from bridge import config
from bridge.server import make_server
from bridge.service import Bridge


def _load_detector(model_path, confidence):
    from autonomy.detector import Detector

    print(f"bridge: loading model {model_path}")
    try:
        return Detector(model_path, confidence)
    except Exception as exc:
        print(f"bridge: model failed to load ({exc}); video and manual driving only")
        return None


def main():
    parser = argparse.ArgumentParser(description="Laptop-side backend for ui_laptop_control.html")
    parser.add_argument("--host", default=config.BRIDGE_HOST)
    parser.add_argument("--port", type=int, default=config.BRIDGE_PORT)
    parser.add_argument("--robot-ip", default=autonomy_config.ROBOT_IP)
    parser.add_argument("--robot-http-port", type=int, default=autonomy_config.ROBOT_HTTP_PORT)
    parser.add_argument("--robot-stream-port", type=int, default=autonomy_config.ROBOT_STREAM_PORT)
    parser.add_argument("--model", default=autonomy_config.MODEL_PATH)
    args = parser.parse_args()

    def make_robot_client():
        return RobotClient(args.robot_ip, port=args.robot_http_port,
                           timeout_s=autonomy_config.ROBOT_HTTP_TIMEOUT_S)

    # Model first, on the main thread, before any other thread exists.
    detector = _load_detector(args.model, autonomy_config.DETECTOR_CONFIDENCE_THRESHOLD)
    frame_grabber = FrameGrabber(
        args.robot_ip, port=args.robot_stream_port,
        max_frame_age_s=autonomy_config.MAX_FRAME_AGE_S,
        connect_timeout_s=autonomy_config.STREAM_CONNECT_TIMEOUT_S,
        header_timeout_s=autonomy_config.STREAM_HEADER_TIMEOUT_S,
        stall_timeout_s=autonomy_config.STREAM_STALL_TIMEOUT_S,
    )
    bridge = Bridge(frame_grabber, detector, make_robot_client,
                    heartbeat_timeout_s=config.HEARTBEAT_TIMEOUT_S)
    server = make_server(bridge, args.host, args.port)
    print(f"bridge: serving on http://{args.host}:{args.port} -- open ui_laptop_control.html "
          "(Ctrl+C to stop; the robot is stopped on exit)")
    # Treat SIGTERM (e.g. `kill`) like Ctrl+C so shutdown still stops the robot.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("bridge: shutting down")
        bridge.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
