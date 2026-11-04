import os
from typing import Any, Dict

try:
    import yaml
except ImportError:
    yaml = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# Load backend/.env (if present) before Config reads the environment.
# Variables already set in the real environment are not overridden.
if load_dotenv is not None:
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=False)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or "change-this-to-a-random-secret"

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    DATABASE_URL = os.getenv("DATABASE_URL")

    MYSQL_HOST = os.getenv("MYSQL_HOST")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "123456")
    MYSQL_DB = os.getenv("MYSQL_DB")

    if DATABASE_URL:
        SQLALCHEMY_DATABASE_URI = DATABASE_URL
    elif MYSQL_HOST and MYSQL_DB:
        SQLALCHEMY_DATABASE_URI = (
            f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
            "?charset=utf8mb4"
        )
    else:
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'trashdet.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }

    STATIC_DIR = os.path.join(BASE_DIR, "static")
    UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")
    RESULT_DIR = os.path.join(STATIC_DIR, "results")
    LOG_DIR = os.path.join(BASE_DIR, "logs")

    YOLO_MODEL_PATH = os.getenv(
        "YOLO_MODEL_PATH",
        os.path.join(BASE_DIR, "model", "runs", "train", "train-200epoch-v11n.pt-bs16", "weights", "best.pt"),
    )
    YOLO_CONF_THRESHOLD = float(os.getenv("YOLO_CONF_THRESHOLD", 0.25))
    DETECT_LEFT_HALF_ONLY = os.getenv("DETECT_LEFT_HALF_ONLY", "false").lower() in ("1", "true", "yes")
    CAMERA_TIMEOUT_MS = int(os.getenv("CAMERA_TIMEOUT_MS", "3000"))
    SEED = int(os.getenv("SEED", 42))
    CAPTCHA_ENABLED = os.getenv("CAPTCHA_ENABLED", "true").lower() in ("1", "true", "yes")
    CAPTCHA_LENGTH = int(os.getenv("CAPTCHA_LENGTH", "4"))
    CAPTCHA_EXPIRE_SECONDS = int(os.getenv("CAPTCHA_EXPIRE_SECONDS", "180"))
    CAPTCHA_MAX_FAILURES = int(os.getenv("CAPTCHA_MAX_FAILURES", "3"))
    CAPTCHA_COOLDOWN_SECONDS = int(os.getenv("CAPTCHA_COOLDOWN_SECONDS", "5"))

    # 图片上传限制 10 MB；视频限制 200 MB
    # MAX_CONTENT_LENGTH 设为视频上限，图片端点内部再二次校验 IMAGE_MAX_CONTENT_LENGTH
    IMAGE_MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    VIDEO_MAX_CONTENT_LENGTH = 200 * 1024 * 1024
    TRAIN_MAX_CONTENT_LENGTH = int(os.getenv("TRAIN_MAX_CONTENT_LENGTH", str(1024 * 1024 * 1024)))
    MAX_CONTENT_LENGTH = max(VIDEO_MAX_CONTENT_LENGTH, TRAIN_MAX_CONTENT_LENGTH)

    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}


def _parse_yaml_scalar(raw_value):
    text = str(raw_value).strip()
    if not text:
        return ""

    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]

    lowered = text.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"null", "none", "~"}:
        return None

    try:
        if any(mark in text for mark in (".", "e", "E")):
            return float(text)
        return int(text)
    except (TypeError, ValueError):
        return text


def _load_simple_yaml_mapping(config_path):
    data = {}
    current_section = None

    with open(config_path, "r", encoding="utf-8") as fp:
        for raw_line in fp:
            clean_line = raw_line.split("#", 1)[0].rstrip()
            if not clean_line.strip():
                continue

            stripped = clean_line.lstrip()
            indent = len(clean_line) - len(stripped)

            if indent == 0 and stripped.endswith(":"):
                section_name = stripped[:-1].strip()
                if section_name:
                    data[section_name] = {}
                    current_section = section_name
                continue

            if indent > 0 and current_section and ":" in stripped:
                key, raw_value = stripped.split(":", 1)
                key = key.strip()
                if not key:
                    continue
                data[current_section][key] = _parse_yaml_scalar(raw_value)

    return data


def load_yaml_runtime_overrides(base_dir):
    config_path = os.getenv("BUSINESS_CONFIG_PATH", os.path.join(base_dir, "runtime_config.yaml"))
    if not os.path.exists(config_path):
        return {}

    try:
        if yaml is None:
            data = _load_simple_yaml_mapping(config_path)
        else:
            with open(config_path, "r", encoding="utf-8") as fp:
                data = yaml.safe_load(fp) or {}
    except (OSError, ValueError):
        return {}

    if not isinstance(data, dict):
        return {}

    app_raw = data.get("app")
    detect_raw = data.get("detect")
    database_raw = data.get("database")

    app_section: Dict[str, Any] = app_raw if isinstance(app_raw, dict) else {}
    detect_section: Dict[str, Any] = detect_raw if isinstance(detect_raw, dict) else {}
    database_section: Dict[str, Any] = database_raw if isinstance(database_raw, dict) else {}

    def _to_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        if isinstance(value, (int, float)):
            return value != 0
        return default

    def _to_int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    overrides = {}
    # Environment variables take precedence over the YAML file.
    if "SECRET_KEY" in app_section and not os.getenv("SECRET_KEY"):
        overrides["SECRET_KEY"] = app_section.get("SECRET_KEY")
    if "MAX_CONTENT_LENGTH" in app_section:
        overrides["MAX_CONTENT_LENGTH"] = _to_int(app_section.get("MAX_CONTENT_LENGTH"), Config.MAX_CONTENT_LENGTH)
    if "TRAIN_MAX_CONTENT_LENGTH" in app_section:
        overrides["TRAIN_MAX_CONTENT_LENGTH"] = _to_int(
            app_section.get("TRAIN_MAX_CONTENT_LENGTH"),
            Config.TRAIN_MAX_CONTENT_LENGTH,
        )
    if "YOLO_CONF_THRESHOLD" in detect_section:
        overrides["YOLO_CONF_THRESHOLD"] = detect_section.get("YOLO_CONF_THRESHOLD")
    if "LEFT_HALF_ONLY" in detect_section:
        overrides["DETECT_LEFT_HALF_ONLY"] = _to_bool(detect_section.get("LEFT_HALF_ONLY"), Config.DETECT_LEFT_HALF_ONLY)
    if "CAMERA_TIMEOUT_MS" in detect_section:
        overrides["CAMERA_TIMEOUT_MS"] = _to_int(detect_section.get("CAMERA_TIMEOUT_MS"), Config.CAMERA_TIMEOUT_MS)

    if os.getenv("DATABASE_URL") or (os.getenv("MYSQL_HOST") and os.getenv("MYSQL_DB")):
        return overrides

    database_url = database_section.get("DATABASE_URL") or database_section.get("database_url")
    if database_url:
        overrides["SQLALCHEMY_DATABASE_URI"] = str(database_url).strip()
        return overrides

    mysql_host = database_section.get("MYSQL_HOST") or database_section.get("host")
    mysql_db = database_section.get("MYSQL_DB") or database_section.get("name") or database_section.get("database")
    if mysql_host and mysql_db:
        mysql_port = _to_int(database_section.get("MYSQL_PORT") or database_section.get("port"), 3306)
        mysql_user = str(database_section.get("MYSQL_USER") or database_section.get("user") or "root")
        mysql_password = str(database_section.get("MYSQL_PASSWORD") or database_section.get("password") or Config.MYSQL_PASSWORD)
        overrides["SQLALCHEMY_DATABASE_URI"] = (
            f"mysql+pymysql://{mysql_user}:{mysql_password}@{mysql_host}:{mysql_port}/{mysql_db}"
            "?charset=utf8mb4"
        )

    return overrides

