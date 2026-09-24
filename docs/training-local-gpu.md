# Training the bottle-detection YOLO model on a local GPU

This covers training the `red_bottle`/`green_bottle` detection model on a
Windows gaming laptop with an NVIDIA GPU (e.g. an RTX 4050, 6GB VRAM),
using a dataset exported from Roboflow. The result is a `best.pt` file
that goes into `autonomy/models/best.pt` for the autonomy service to load.

If you don't have a local GPU, see the alternative: train on a free cloud
GPU (Kaggle notebook or Google Colab) instead — the same `yolo detect
train` command works there too, just run from a notebook cell.

## 1. Export the dataset from Roboflow

On the Roboflow project's model page:

1. Left sidebar, under `DATA` → **Versions**
2. Open the version the model was trained from
3. **Export Dataset** → format **YOLOv11** (or "YOLO11 PyTorch")
4. Download the zip

Dataset export is free even when raw trained-weight export is gated
behind a paid plan.

## 2. Get the repo onto the training machine

```bash
git clone <your-repo-url-or-path> esp32-robot-software
cd esp32-robot-software
```

Unzip the exported dataset **outside** the repo — it's large (hundreds of
MB, thousands of images) and isn't meant to be committed to git.

## 3. Set up the environment

Install Miniconda or Anaconda for Windows if it isn't already present,
then:

```bash
conda env create -f autonomy/environment.yml
conda activate esp32-robot-autonomy
```

## 4. Verify the GPU is actually being used

```bash
nvidia-smi
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

`nvidia-smi` shows your GPU and the CUDA version your driver supports.
`torch.cuda.is_available()` should print `True`.

If it prints `False`, the default `pip install ultralytics` (inside
`environment.yml`) pulled a CPU-only PyTorch build. Fix by installing the
CUDA build that matches your driver's CUDA version (from `nvidia-smi`'s
output):

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

(swap `cu121` for whatever version matches — e.g. `cu118`, `cu124`.)

## 5. Quick sanity check before the full run

From the folder containing the unzipped dataset's `data.yaml`:

```bash
yolo detect train data=data.yaml model=yolo11n.pt epochs=3 imgsz=640 device=0
```

Confirm it prints `device: cuda:0` (not `cpu`) and completes without a
`FileNotFoundError` on the image paths. This takes a couple of minutes
and catches setup problems before you commit to a long run.

## 6. Train

```bash
yolo detect train data=data.yaml model=yolo11n.pt epochs=100 imgsz=640 device=0 batch=-1 patience=15
```

- `device=0` — use the first CUDA GPU
- `batch=-1` — let Ultralytics auto-size the batch to fit available VRAM
  (avoids an out-of-memory crash on a 6GB card)
- `patience=15` — stop early once validation performance plateaus,
  rather than forcing all 100 epochs
- If you still hit an out-of-memory error, drop to `batch=8` or
  `imgsz=416` manually

Ultralytics prints progress per epoch and saves checkpoints as it goes.

## 7. Retrieve the trained weights

When training finishes (or stops early via `patience`), the best
checkpoint is at:

```
runs/detect/train/weights/best.pt
```

(`last.pt` in the same folder is the final-epoch checkpoint, not
necessarily the best one — use `best.pt`.)

Copy `best.pt` back to the machine running the autonomy service (USB
drive, cloud upload, `scp` — not git, trained weights aren't tracked in
this repo) and place it at:

```
autonomy/models/best.pt
```

## 8. Sanity-check quality against Roboflow's model

There's no guarantee this run matches Roboflow's hosted training exactly
— different hyperparameters, stopping point, and random seed can produce
a somewhat different result even from identical data and architecture.
Before assuming it's good enough:

1. Check the printed mAP/precision/recall, or open
   `runs/detect/train/results.png`
2. Run your `best.pt` against a few of the same test images the
   Roboflow model page showed, and compare confidence scores
3. Only tune further (more epochs, adjusted hyperparameters) if it's
   noticeably worse for the actual task — reliably detecting a bottle a
   few feet from the ESP32 camera, not competition-grade metrics

Once `autonomy/models/best.pt` is in place, the autonomy service is ready
for its hardware smoke test — see `autonomy/README.md`.
