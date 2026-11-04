# TrashDet-YOLO11

TrashDet-YOLO11 is a full-stack platform for waste inspection and cleaning robot operations, including:
- Flask backend services (detection, statistics, robot control, training, authentication)
- Vue 3 single-page frontend (SPA)
- Robot firmware integration examples and local simulation scripts

The project is designed as an end-to-end loop from image capture and garbage detection to data storage, hotspot analytics, robot scheduling, and model retraining.

## Feature Highlights

- Image Detection
  - Upload an image and run YOLO inference
  - Return boxes/classes/confidence and save annotated outputs
  - Support server-side ingest API for external detection results
- Video Detection
  - Upload video and process asynchronously
  - Poll task status/results via API
- Analytics
  - Detection trends, class distribution, and map points
  - Hotspot analysis with geocoding cache
- Robot Management
  - Registration, heartbeat/status sync, control commands, navigation
  - Robot list and status updates
- Online Training
  - Upload dataset ZIP and start async training jobs
  - Query job status, logs, and output artifacts
- Web Auth and Operations
  - Register/login/logout, session state, captcha
  - Task list/detail and management APIs

## Repository Layout

```text
EcoGuard/
├─ backend/                  # Flask backend
│  ├─ app.py                 # Backend entrypoint
│  ├─ config.py              # Config and runtime overrides
│  ├─ runtime_config.example.yaml  # Runtime config template (copy to runtime_config.yaml)
│  ├─ api/                   # detect/stats/robot/train APIs
│  ├─ web/                   # SPA-compatible routes and web APIs
│  ├─ database/              # SQLAlchemy models and DB bootstrap
│  ├─ inference/             # YOLO inference wrapper
│  ├─ model/runs/train/      # Trained model (best.pt and training plots)
│  ├─ test/                  # Backend unit tests
│  └─ requirements.txt       # Python dependencies
├─ frontend/                 # Vue 3 + Vite frontend
│  ├─ src/
│  ├─ package.json
│  └─ vite.config.js         # Build output: backend/static/spa
├─ Rm_arm/                   # Robot arm ESP32 firmware (PlatformIO)
├─ Simulator/                # Robot simulation scripts
└─ LICENSE
```

## Requirements

- Python 3.10+ (recommended)
- Node.js 18+
- Optional: CUDA runtime for GPU inference/training
- Database
  - SQLite by default
  - MySQL supported via config overrides

## Backend Quick Start

1. Create and activate your Python environment.
2. Install backend dependencies.
3. Start the backend service.

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env  # fill in SECRET_KEY etc.
python app.py
```

After startup:
- http://127.0.0.1:5000
- Health endpoint: http://127.0.0.1:5000/health

Notes:
- Database migrations (Flask-Migrate, see `backend/migrations/`) are applied automatically at startup. Databases created by older versions are adopted without being recreated.
- After changing models, generate a migration with `cd backend && flask --app app:create_app db migrate -m "message"`.
- Video detection and training run in background threads; their status is stored in the database, and unfinished jobs are marked as failed when the server restarts.
- In production use a single worker (e.g. `gunicorn -w 1 --threads 8 "app:create_app()"`); multiple workers would split background job state.
- If there are no users, a bootstrap admin account is auto-created (change credentials immediately in production).

## Frontend Development and Build

Development mode:

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api` requests to `http://127.0.0.1:5000` by default.

Production build:

```bash
cd frontend
npm run build
```

Build artifacts are written to `backend/static/spa` and served by the backend.

## Configuration

Backend config precedence:
1. Environment variables
2. `backend/.env` (copy from `backend/.env.example`; holds SECRET_KEY, DB password, etc.)
3. `backend/runtime_config.yaml` (copy from `runtime_config.example.yaml`)
4. Defaults in `backend/config.py`

Common settings:
- `SQLALCHEMY_DATABASE_URI` / `DATABASE_URL`
- `YOLO_MODEL_PATH`
- `YOLO_CONF_THRESHOLD`
- `MAX_CONTENT_LENGTH`
- `TRAIN_MAX_CONTENT_LENGTH`
- `CAPTCHA_ENABLED`

Important:
- `runtime_config.example.yaml` uses MySQL (`trashdet`); set the password via the `MYSQL_PASSWORD` environment variable.
- Set `SECRET_KEY` as an environment variable, never in the config file.
- If that DB does not exist locally, switch to SQLite URI or remove MySQL entries.

## Core APIs

Detection:
- `GET /api/detect/dependencies` dependency health for detection runtime
- `POST /api/detect` image detection
- `POST /api/detect/video` async video detection
- `GET /api/detect/video/status/<task_id>` video task status
- `POST /api/detect/ingest` ingest externally produced detection results

Statistics:
- `GET /api/stats/summary`
- `GET /api/stats/hotspots`

Robot:
- `POST /api/robot/register`
- `POST /api/robot/heartbeat`
- `POST /api/robot/status_update`
- `POST /api/robot/control`
- `POST /api/robot/navigate`
- `GET /api/robot/list`

Training:
- `GET /api/train/config`
- `POST /api/train/start`
- `GET /api/train/status/<job_id>`
- `GET /api/train/status`

Web session and data APIs (excerpt):
- `GET /api/web/session`
- `POST /api/web/login`
- `POST /api/web/register`
- `POST /api/web/logout`
- `GET /api/web/tasks`

## Model and Training Workflow

- Inference implementation is in `backend/inference/yolo_detector.py`.
- Training is triggered asynchronously by `POST /api/train/start`.
- Dataset upload requires ZIP; custom `.pt` weight upload is supported.
- Job result includes output folder and a best-weight hint path.

## Robot Integration and Simulation

- Robot firmware examples are under `Rm_arm/`.
- Desktop simulation scripts are under `Simulator/` (install with `pip install -r Simulator/requirements.txt`).
- Backend robot APIs provide heartbeat, status sync, navigation, and control channels.

## Testing

Run full backend unit tests:

```bash
cd backend
python -m unittest discover -s test -p "test_*.py"
```

If your environment is missing optional dependencies, run baseline tests first:

```bash
cd backend
python -m unittest -q test.test_config test.test_ml_algorithm
```

## Troubleshooting

- Detection API reports missing dependencies
  - Call `GET /api/detect/dependencies` for missing packages and install hints.
- Startup fails with unknown MySQL database
  - Check `backend/runtime_config.yaml` database block; switch to a valid DB or SQLite.
- Training upload rejected with HTTP 413
  - Increase `TRAIN_MAX_CONTENT_LENGTH` and ensure `MAX_CONTENT_LENGTH >= TRAIN_MAX_CONTENT_LENGTH`.
- Frontend style/resource mismatch
  - Use built artifacts from `frontend` and serve from `backend/static/spa`.

## License

This project is licensed under AGPL-3.0, matching Ultralytics YOLO. See `LICENSE` for details.