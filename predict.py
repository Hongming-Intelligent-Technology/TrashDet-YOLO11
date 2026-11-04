from argparse import ArgumentParser

from ultralytics import YOLO


def parse_args():
    parser = ArgumentParser(description="Run trash detection on images, videos, folders, or a webcam")
    parser.add_argument("--weights", default="best.pt", help="Trained weight path (download best.pt from Releases)")
    parser.add_argument("--source", required=True, help="Image/video/folder path, URL, or 0 for webcam")
    parser.add_argument("--imgsz", type=int, default=640, help="Inference image size")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument("--device", default=None, help="cuda:0, cpu, or leave empty for auto")
    parser.add_argument("--project", default="runs", help="Output root directory")
    parser.add_argument("--name", default="predict", help="Output run name")
    parser.add_argument("--show", action="store_true", help="Show results in a window")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    model = YOLO(args.weights)
    predict_kwargs = {
        "source": args.source,
        "imgsz": args.imgsz,
        "conf": args.conf,
        "project": args.project,
        "name": args.name,
        "show": args.show,
        "save": True,
    }
    if args.device:
        predict_kwargs["device"] = args.device
    model.predict(**predict_kwargs)
