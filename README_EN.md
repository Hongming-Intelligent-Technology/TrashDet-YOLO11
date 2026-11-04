# TrashDet-YOLO11

[简体中文](README.md) | **English**

TrashDet is a trash detection and cleanup-robot management platform built on YOLO11. It connects the whole loop: capture or upload an image → detect trash → record results and locations → find hotspot areas → send a robot to clean up → retrain the model on new data.

## What's inside

| Part | Description |
|---|---|
| `backend/` | Flask backend: detection, statistics, robots, training, authentication |
| `frontend/` | React 19 + TypeScript dashboard, built into the backend and served by it |
| `Rm_arm/` | ESP32 firmware for the robot arm (PlatformIO) |
| `Simulator/` | Robot simulators (terminal and Qt GUI) for testing without hardware |

## Features

- **Image detection**: upload an image and get boxes, classes and confidence scores, plus a saved annotated image
- **Video detection**: upload a video, process it in the background and poll its progress
- **Analytics**: detection trends, class distribution, map points and hotspot analysis
- **Robot management**: registration, heartbeat, status sync, control commands and navigation
- **Online training**: upload a ZIP dataset and train a new model in the background (admins only)
- **Accounts**: registration, login, captcha and an admin panel

## Bundled model

The repo ships a trained model at `backend/model/runs/train/train-200epoch-v11n.pt-bs16/weights/best.pt` (YOLO11n, 640×640, 200 epochs, batch 16). Validation results:

| Precision | Recall | mAP50 | mAP50-95 |
|---|---|---|---|
| 0.897 | 0.799 | 0.864 | 0.583 |

Training curves, the confusion matrix and other plots are in the same folder.

## Quick start

Requires Python 3.10+ and Node.js 18+. CUDA is optional, for GPU inference or training.

### 1. Run the backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env    # set at least SECRET_KEY
python app.py
```

Open http://127.0.0.1:5000. Health check: http://127.0.0.1:5000/health

**First login**: when the database has no users, an admin account is created. The username defaults to `admin`; the password and security code come from `TRASHDET_ADMIN_PASSWORD` and `TRASHDET_ADMIN_SECURITY_CODE` in `.env`. If they're not set, random ones are generated and printed once in the startup log. Change them right after logging in.

### 2. Work on the frontend (optional)

The backend already includes a built frontend. You only need this step to change the UI:

```bash
cd frontend
npm install
npm run dev      # dev server; /api requests go to http://127.0.0.1:5000
npm run lint     # lint with oxlint, including React hooks rules
npm run build    # type-check and build into backend/static/spa, served by the backend
```

### 3. Run a simulated robot (optional)

```bash
pip install -r Simulator/requirements.txt
python Simulator/Sim_robot.py --server http://127.0.0.1:5000          # terminal version
python Simulator/Sim_robot.py --gui --server http://127.0.0.1:5000    # Qt GUI version
```

## Configuration

Settings are applied in this order; earlier sources override later ones:

1. Environment variables
2. `backend/.env` (copy from `.env.example`; holds secrets and DB passwords)
3. `backend/runtime_config.yaml` (copy from `runtime_config.example.yaml`)
4. Defaults in `backend/config.py`

Common settings:

| Setting | Purpose |
|---|---|
| `SECRET_KEY` | Session key; must be set via an environment variable or `.env` |
| `DATABASE_URL` or `MYSQL_*` | Database connection; leave both empty to use SQLite (`backend/trashdet.db`) |
| `YOLO_MODEL_PATH` | Path to the detection model |
| `YOLO_CONF_THRESHOLD` | Confidence threshold, default 0.25 |
| `TRAIN_MAX_CONTENT_LENGTH` | Maximum training dataset upload size |
| `CAPTCHA_ENABLED` | Turn the login captcha on or off |

### Using MySQL

```sql
CREATE DATABASE trashdet CHARACTER SET utf8mb4;
```

Migrations create the tables; just fill in `MYSQL_*` in `.env`. Back up before upgrading (`mysqldump trashdet > backup.sql`), because MySQL schema changes can't be rolled back.

### Database migrations

- Migrations run automatically at startup (Flask-Migrate, see `backend/migrations/`). Databases created by older versions are adopted as-is.
- After changing a model, generate a migration: `cd backend && flask --app app:create_app db migrate -m "message"`

## Deployment notes

Video detection and training run in background threads, with their status stored in the database. Unfinished jobs are marked as failed when the server restarts.

In production, use a **single worker**, or background job state will be split between workers:

```bash
gunicorn -w 1 --threads 8 "app:create_app()"
```

## API overview

| Area | Endpoints |
|---|---|
| Detection | `POST /api/detect` image detection<br>`POST /api/detect/video` video detection<br>`GET /api/detect/video/status/<task_id>` video job status<br>`POST /api/detect/ingest` store external detection results<br>`GET /api/detect/dependencies` check detection dependencies |
| Statistics | `GET /api/stats/summary`<br>`GET /api/stats/hotspots` |
| Robots | `POST /api/robot/register`<br>`POST /api/robot/heartbeat`<br>`POST /api/robot/status_update`<br>`POST /api/robot/control`<br>`POST /api/robot/navigate`<br>`GET /api/robot/list` |
| Training | `GET /api/train/config`<br>`POST /api/train/start` (admins only)<br>`GET /api/train/status`<br>`GET /api/train/status/<job_id>` |
| Accounts | `GET /api/web/session`<br>`POST /api/web/login`<br>`POST /api/web/register`<br>`POST /api/web/logout` |

Only admins can start training, because uploaded weights and dataset configs can run code when loaded.

## Testing

Tests only need lightweight dependencies (no torch or ultralytics):

```bash
cd backend
pip install -r requirements-dev.txt
ruff check .
python -m pytest -q test
```

## Troubleshooting

- **Detection says dependencies are missing**: call `GET /api/detect/dependencies` to see which packages are missing and how to install them.
- **Startup fails because the MySQL database doesn't exist**: create it first, or clear `MYSQL_*` to use SQLite.
- **Training upload rejected with HTTP 413**: raise `TRAIN_MAX_CONTENT_LENGTH`. If `runtime_config.yaml` sets `MAX_CONTENT_LENGTH`, it must not be smaller.
- **Pages look broken**: run `npm run build` again so `backend/static/spa` is up to date.

## License

AGPL-3.0, matching Ultralytics YOLO. See [LICENSE](LICENSE).
