# stream

Standalone viewer for testing the robot's camera stream (port 81 `/stream`),
with a connection log and live YOLO detection boxes. Reuses autonomy's
`Detector` and `config` (model path, confidence threshold) but never sends
drive commands.

```bash
conda activate esp32-robot-autonomy   # reuses the autonomy env (opencv, requests, numpy)
python -m stream.view                 # or: --ip 192.168.4.1 --port 81
python -m stream.view --no-detect     # plain stream, no model
python -m stream.view --model autonomy/models/best.pt --conf 0.4
```

Run from the repo root: the default model path (`autonomy/models/best.pt`,
gitignored) is relative to it. If the model fails to load, the error is
logged and the plain stream keeps running.

Press `q` or `ESC` in the window to quit.

**macOS:** if detection segfaults on the first inference, run
`bash autonomy/macos_fix_openmp.sh` once in the activated env (and again
after reinstalling torch). It makes torch share the env's OpenMP runtime;
it only touches the local env, so `environment.yml` and Windows are
unaffected.

The log goes to the console and to `stream/logs/stream-<timestamp>.log`
(gitignored). It records connect attempts, HTTP status and content type,
time to first frame and its resolution, stats every 5s (fps, KB/s, longest
gap between frames, JPEG decode failures), stalls, disconnects and
reconnects (exponential backoff, capped at 10s).

Detection adds to the log: model load time, a line each time the set of
detected labels changes, and inference rate/latency every 5s.

A background thread reads and decodes frames and keeps only the newest one,
so the window always shows the current frame instead of a backlog. Detection
runs in its own thread on the newest frame whenever it's free, and its latest
boxes are drawn on every displayed frame, so slow inference lowers the
detection rate, not the video frame rate.
