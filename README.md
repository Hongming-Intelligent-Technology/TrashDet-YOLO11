# TrashDet-YOLO11

TrashDet-YOLO11 is a YOLO11-based project for trash detection.
It uses the [Ultralytics](https://github.com/ultralytics/ultralytics) package as a dependency and provides a simple custom training entrypoint in train.py.

## Overview

- Base framework: Ultralytics YOLO (installed via pip, pinned in requirements.txt)
- Main use case: custom trash detection model training and deployment
- Pretrained weights: yolo11n.pt / yolo11s.pt are downloaded automatically by Ultralytics
- Trained weights: download best.pt from the GitHub Releases page
- Custom script: train.py (argument-based training launcher)

## Requirements

- Python 3.8+
- PyTorch-compatible environment (CPU or CUDA)
- Windows, Linux, or macOS

## Installation

```bash
git clone https://github.com/HongyiHao-SXIT/TrashDet-YOLO11.git
cd TrashDet-YOLO11
pip install -r requirements.txt
```

For ONNX/TensorRT export support, also run `pip install "ultralytics[export]==8.4.48"`.

## Dataset Preparation

Edit data/trash.yaml (or provide your own YOLO-format dataset YAML), for example:

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
python train.py --data data/trash.yaml --weights yolo11n.pt --epochs 100 --imgsz 640 --batch 16 --name trash-yolo11n
```

Common options:

- --weights: pretrained .pt or model yaml (default yolo11n.pt)
- --data: dataset yaml (default data/trash.yaml)
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

## Project Layout

- train.py: custom training entrypoint
- data/trash.yaml: dataset config
- assets/: demo and result images
- requirements.txt: pinned dependencies
- runs/: training outputs (not committed)

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

This project builds on [Ultralytics YOLO](https://github.com/ultralytics/ultralytics).

## License

AGPL-3.0, following Ultralytics. See LICENSE.
