import os
import time
import logging

logger = logging.getLogger(__name__)

try:
    import cv2
except ImportError:
    cv2 = None
    logger.warning("OpenCV not installed. Annotated image saving will fail.")

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None
    logger.warning("Ultralytics YOLO not installed. Detection will fail.")
except OSError as error:
    YOLO = None
    logger.warning("Ultralytics import failed due to missing torch DLL dependencies: %s", error)


class YOLODetector:
    def __init__(self, model_path=None, default_conf_thres=0.25, left_half_only=False, camera_timeout_ms=3000):
        if YOLO is None:
            raise ImportError("Ultralytics package is not installed.")
        if not model_path:
            raise ValueError("Model path must be provided.")

        self.model_path = model_path
        self.default_conf_thres = self._normalize_conf_threshold(default_conf_thres)
        self.left_half_only = bool(left_half_only)
        self.camera_timeout_ms = max(1, int(camera_timeout_ms))

        self._assert_model_file_health(self.model_path)
        logger.info("Loading YOLO model from: %s", self.model_path)
        try:
            self.model = YOLO(self.model_path)
        except Exception as error:
            raise RuntimeError(f"模型加载失败，可能是权重损坏: {self.model_path}") from error

    @staticmethod
    def _normalize_conf_threshold(conf_thres):
        try:
            value = float(conf_thres)
        except (TypeError, ValueError):
            value = 0.25
        return min(max(value, 0.0), 1.0)

    def _resolve_conf_threshold(self, conf_thres):
        if conf_thres is None:
            return self.default_conf_thres
        return self._normalize_conf_threshold(conf_thres)

    @staticmethod
    def _assert_model_file_health(model_path):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"模型文件不存在: {model_path}")
        if os.path.getsize(model_path) <= 0:
            raise RuntimeError(f"模型文件为空，疑似损坏: {model_path}")

    @staticmethod
    def _assert_output_writable(result_path):
        if not result_path:
            return
        output_dir = os.path.dirname(os.path.abspath(result_path))
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        if output_dir and not os.access(output_dir, os.W_OK):
            raise PermissionError(f"结果目录不可写: {output_dir}")

    def _run_yolo_inference(self, image_or_path, conf_thres):
        try:
            return self.model(image_or_path, save=False, verbose=False, conf=conf_thres)
        except Exception as error:
            raise RuntimeError("YOLO 推理失败，请检查输入数据与模型状态") from error

    @staticmethod
    def _save_annotated_image(annotated_frame, result_path):
        if not result_path:
            return
        if cv2 is None:
            raise RuntimeError("OpenCV package is not installed.")
        if not cv2.imwrite(result_path, annotated_frame):
            raise IOError(f"检测结果保存失败: {result_path}")

    @staticmethod
    def _extract_raw_detections(result):
        detections = []
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return detections

        names = getattr(result, "names", {})
        for box in boxes:
            coords = box.xyxy[0].tolist()
            class_id = int(box.cls[0])
            label = names[class_id]
            confidence = float(box.conf[0])
            detections.append({
                "label": label,
                "confidence": confidence,
                "bbox": coords
            })
        return detections

    @staticmethod
    def _extract_image_width(result, fallback_width=0):
        shape = getattr(result, "orig_shape", None)
        if shape and len(shape) >= 2:
            return shape[1]
        return fallback_width

    def _apply_detection_rules(self, detections, image_width):
        if not self.left_half_only or not image_width:
            return detections

        # 业务约束：仅记录左半屏目标，降低误触发和后续机械臂无效动作。
        mid_x = image_width / 2.0
        return [
            item for item in detections
            if ((item["bbox"][0] + item["bbox"][2]) / 2.0) <= mid_x
        ]

    def analyze_realtime_camera_stream(self, frame, save_result=False, result_path=None, conf_thres=None):
        if frame is None:
            return [], None

        start = time.perf_counter()
        active_conf = self._resolve_conf_threshold(conf_thres)
        results = self._run_yolo_inference(frame, active_conf)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if elapsed_ms > self.camera_timeout_ms:
            raise TimeoutError(f"摄像头帧处理超时: {elapsed_ms:.1f}ms")
        if not results:
            return [], None

        yolo_result = results[0]
        annotated_frame = yolo_result.plot()
        detections = self._extract_raw_detections(yolo_result)
        detections = self._apply_detection_rules(detections, frame.shape[1])

        if save_result:
            self._assert_output_writable(result_path)
            self._save_annotated_image(annotated_frame, result_path)

        return detections, annotated_frame

    def analyze_uploaded_waste_image(self, img_path, save_result=False, result_path=None, conf_thres=None):
        if not img_path or not os.path.exists(img_path):
            raise FileNotFoundError(f"待检测图片不存在: {img_path}")

        active_conf = self._resolve_conf_threshold(conf_thres)
        results = self._run_yolo_inference(img_path, active_conf)
        if not results:
            return []

        yolo_result = results[0]
        detections = self._extract_raw_detections(yolo_result)

        image_width = self._extract_image_width(yolo_result, fallback_width=0)
        detections = self._apply_detection_rules(detections, image_width)

        if save_result:
            self._assert_output_writable(result_path)
            annotated_frame = yolo_result.plot()
            self._save_annotated_image(annotated_frame, result_path)

        return detections

    def collect_detections(self, result):
        return self._extract_raw_detections(result)

    def detect_in_frame(self, frame, save_result=False, result_path=None, conf_thres=0.25):
        return self.analyze_realtime_camera_stream(
            frame=frame,
            save_result=save_result,
            result_path=result_path,
            conf_thres=conf_thres
        )

    def detect_in_image(self, img_path, save_result=False, result_path=None, conf_thres=0.25):
        return self.analyze_uploaded_waste_image(
            img_path=img_path,
            save_result=save_result,
            result_path=result_path,
            conf_thres=conf_thres
        )

