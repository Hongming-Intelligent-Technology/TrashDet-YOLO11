# TrashDet-YOLO11

TrashDet-YOLO11 is a YOLO11-based project for trash detection, built on top of the Ultralytics codebase.
It keeps the full Ultralytics training/inference/export stack while providing a simple custom training entrypoint in train.py.

## Overview

- Base framework: Ultralytics YOLO
- Main use case: custom trash detection model training and deployment
- Included pretrained weights: yolo11n.pt, yolo11s.pt
- Custom script: train.py (argument-based training launcher)

## Requirements

- Python 3.8+
- PyTorch-compatible environment (CPU or CUDA)
- Windows, Linux, or macOS

## Installation

### Option A: Local editable install (recommended for development)

```bash
git clone https://github.com/HongyiHao-SXIT/TrashDet-YOLO11.git
cd TrashDet-YOLO11
pip install -e .
```

### Option B: Install with export extras

```bash
pip install -e ".[export]"
```

## Dataset Preparation

Prepare a YOLO-format dataset YAML file, for example:

```yaml
path: /path/to/dataset
train: images/train
val: images/val
test: images/test

names:
  0: trash
```

Directory example:

```text
dataset/
  images/
    train/
    val/
    test/
  labels/
    train/
    val/
    test/
  trash.yaml
```

## Training

### Method 1: Custom launcher (recommended in this repo)

train.py wraps YOLO training and exposes common knobs.

```bash
python train.py --data /path/to/trash.yaml --weights yolo11n.pt --epochs 100 --imgsz 640 --batch 16 --name trash-yolo11n
```

Common options:

- --weights: pretrained .pt or model yaml (default yolo11n.pt)
- --cfg: Ultralytics train config (default ultralytics/cfg/default.yaml)
- --data: dataset yaml (required)
- --optimizer: SGD, AdamW, etc.
- --epochs: training epochs
- --project: output root directory (default runs)
- --name: run name (default train-exp)
- --batch: batch size
- --workers: dataloader workers
- --imgsz: input size
- --device: cpu, cuda:0, etc.
- --resume: resume from checkpoint

### Method 2: Native YOLO CLI

```bash
yolo detect train data=/path/to/trash.yaml model=yolo11n.pt epochs=100 imgsz=640
```

## Inference

### CLI

```bash
yolo predict model=runs/train/trash-yolo11n/weights/best.pt source=/path/to/image_or_video
```

### Python

```python
from ultralytics import YOLO

model = YOLO("runs/train/trash-yolo11n/weights/best.pt")
results = model("/path/to/image.jpg")
results[0].show()
```

## Validation and Export

Validate:

```bash
yolo val model=runs/train/trash-yolo11n/weights/best.pt data=/path/to/trash.yaml
```

Export ONNX:

```bash
yolo export model=runs/train/trash-yolo11n/weights/best.pt format=onnx
```

## Key Directories

- ultralytics/: core framework code
- train.py: custom training entrypoint
- tests/: automated tests
- docs/: documentation source
- .github/workflows/: CI workflows
- runs/: training outputs

## CI and Dependency Automation

- CI workflows are in .github/workflows/.
- Dependabot configuration is in .github/dependabot.yml.
- This repository uses grouped and rate-limited Dependabot updates to reduce PR noise.

## Troubleshooting

1. CUDA not found

- Check torch CUDA build and driver versions.
- Try --device cpu to verify baseline execution.

2. OOM during training

- Reduce --batch or --imgsz.
- Use a smaller model such as yolo11n.pt.

3. Dataset path errors

- Ensure the YAML path exists and uses correct relative folders.
- Confirm images/ and labels/ splits match YOLO naming.

## Acknowledgments

This project builds on Ultralytics YOLO and keeps compatibility with its training and deployment ecosystem.

## License

This repository follows the same licensing terms as the project root LICENSE file.
