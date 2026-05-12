from argparse import ArgumentParser
from pathlib import Path

from ultralytics import YOLO


def parse_args():
    parser = ArgumentParser(description="Generic YOLO11 training entrypoint")
    parser.add_argument("--weights", default="yolo11n.pt", help="Pretrained weight path or model yaml")
    parser.add_argument("--cfg", default="ultralytics/cfg/default.yaml", help="Ultralytics training cfg path")
    parser.add_argument("--data", required=True, help="Dataset yaml path")
    parser.add_argument("--optimizer", default="SGD", help="Optimizer name, e.g. SGD or AdamW")
    parser.add_argument("--epochs", type=int, default=200, help="Number of training epochs")
    parser.add_argument("--project", default="runs", help="Output root directory")
    parser.add_argument("--name", default="train-exp", help="Current run name")
    parser.add_argument("--batch", type=int, default=16, help="Batch size")
    parser.add_argument("--workers", type=int, default=8, help="Dataloader workers")
    parser.add_argument("--split", default="val", help="Validation split")
    parser.add_argument("--imgsz", type=int, default=640, help="Input image size")
    parser.add_argument("--device", default=None, help="cuda:0, cpu, or leave empty for auto")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    model = YOLO(str(Path(args.weights)))

    train_kwargs = {
        "cfg": str(Path(args.cfg)),
        "data": str(Path(args.data)),
        "optimizer": args.optimizer,
        "epochs": args.epochs,
        "project": str(Path(args.project)),
        "name": args.name,
        "batch": args.batch,
        "workers": args.workers,
        "split": args.split,
        "imgsz": args.imgsz,
        "resume": args.resume,
    }
    if args.device:
        train_kwargs["device"] = args.device

    model.train(**train_kwargs)
