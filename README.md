# TrashDet-YOLO11

TrashDet-YOLO11 是一个面向垃圾巡检与保洁机器人场景的全栈平台，包含：
- 后端 Flask 服务（检测、统计、机器人、训练、认证）
- 前端 React 19 + TypeScript 单页应用（SPA）
- 机器人固件集成示例与本地仿真脚本

项目目标是打通从图像采集、垃圾识别、任务入库、热点统计到机器人调度与模型迭代训练的完整闭环。

## 功能概览

- 图像检测
  - 上传图片后执行 YOLO 推理
  - 返回检测框、类别、置信度，并保存标注图
  - 支持服务侧结果回灌接口（ingest）
- 视频检测
  - 上传视频后异步检测
  - 通过任务状态接口轮询进度与结果
- 数据统计
  - 汇总检测趋势、类别分布、地图点位
  - 提供热点区域分析与地理解析缓存
- 机器人管理
  - 设备注册、心跳/状态同步、控制指令、导航下发
  - 机器人列表与状态更新
- 在线训练
  - 上传数据集 ZIP，异步启动训练任务
  - 查询训练状态、日志与产出目录
- Web 认证与管理
  - 注册/登录/登出、会话状态、验证码
  - 任务列表、详情与管理接口

## 仓库结构

```text
TrashDet-YOLO11/
├─ backend/                  # Flask 后端
│  ├─ app.py                 # 后端入口
│  ├─ config.py              # 配置与运行时覆盖
│  ├─ runtime_config.example.yaml  # 运行时配置模板（复制为 runtime_config.yaml）
│  ├─ api/                   # detect/stats/robot/train API
│  ├─ web/                   # SPA 兼容页面与 Web API
│  ├─ database/              # SQLAlchemy 模型与数据库初始化
│  ├─ inference/             # YOLO 推理封装
│  ├─ model/runs/train/      # 训练好的模型（best.pt 与训练结果图）
│  ├─ test/                  # 后端单元测试
│  └─ requirements.txt       # Python 依赖
├─ frontend/                 # React + TypeScript + Vite 前端
│  ├─ src/
│  ├─ package.json
│  └─ vite.config.js         # build 输出到 backend/static/spa
├─ Rm_arm/                   # 机械臂 ESP32 固件（PlatformIO）
├─ Simulator/                # 机器人仿真脚本
└─ LICENSE
```

## 环境要求

- Python 3.10+（建议）
- Node.js 18+
- 可选：CUDA 环境（若需 GPU 训练/推理）
- 数据库
  - 默认可使用 SQLite
  - 也可通过配置切换 MySQL

## 后端快速开始

1. 创建并激活 Python 环境。
2. 安装依赖。
3. 启动服务。

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env  # 填写 SECRET_KEY 等
python app.py
```

启动后访问：
- http://127.0.0.1:5000
- 健康检查：http://127.0.0.1:5000/health

说明：
- 服务启动时会自动执行数据库迁移（Flask-Migrate，见 `backend/migrations/`）。旧版本创建的数据库会被自动接管，无需重建。
- 修改模型后生成迁移：`cd backend && flask --app app:create_app db migrate -m "说明"`。
- 视频检测与模型训练在后台线程中运行，状态保存在数据库；服务重启时未完成的任务会被标记为失败。
- 生产部署请使用单个 worker（例如 `gunicorn -w 1 --threads 8 "app:create_app()"`），多 worker 会导致后台任务状态不一致。
- 若数据库中无用户，会自动创建引导管理员账号：用户名默认 `admin`，密码和安全码取自 `ECOGUARD_ADMIN_PASSWORD` / `ECOGUARD_ADMIN_SECURITY_CODE`；未设置时随机生成，并在启动日志中打印一次（请登录后立即修改）。

## 前端开发与构建

开发模式：

```bash
cd frontend
npm install
npm run dev
```

默认通过 Vite 代理转发 `/api` 到 `http://127.0.0.1:5000`。

生产构建：

```bash
cd frontend
npm run build
```

构建产物输出到 `backend/static/spa`，由后端统一托管。

## 配置说明

后端配置优先级：
1. 环境变量
2. `backend/.env`（从 `backend/.env.example` 复制，用于存放 SECRET_KEY、数据库密码等）
3. `backend/runtime_config.yaml`（从 `runtime_config.example.yaml` 复制）
4. `backend/config.py` 默认值

常用项：
- `SQLALCHEMY_DATABASE_URI` / `DATABASE_URL`
- `YOLO_MODEL_PATH`
- `YOLO_CONF_THRESHOLD`
- `MAX_CONTENT_LENGTH`
- `TRAIN_MAX_CONTENT_LENGTH`
- `CAPTCHA_ENABLED`

注意：
- `runtime_config.example.yaml` 示例是 MySQL（`trashdet`），数据库密码请通过环境变量 `MYSQL_PASSWORD` 设置。
- `SECRET_KEY` 请通过环境变量设置，不要写入配置文件。
- 使用 MySQL 时需先创建数据库（表由迁移自动创建）：`CREATE DATABASE trashdet CHARACTER SET utf8mb4;`
- 升级到新版本前请先备份数据库（`mysqldump trashdet > backup.sql`），MySQL 的表结构变更无法回滚。
- 若本地没有对应库，可改为 SQLite URI，或移除 MySQL 配置段。

## 主要接口

检测相关：
- `GET /api/detect/dependencies` 检查检测依赖状态
- `POST /api/detect` 图片检测
- `POST /api/detect/video` 视频异步检测
- `GET /api/detect/video/status/<task_id>` 查询视频检测状态
- `POST /api/detect/ingest` 接收外部检测结果入库

统计相关：
- `GET /api/stats/summary` 获取汇总统计
- `GET /api/stats/hotspots` 获取热点分析

机器人相关：
- `POST /api/robot/register`
- `POST /api/robot/heartbeat`
- `POST /api/robot/status_update`
- `POST /api/robot/control`
- `POST /api/robot/navigate`
- `GET /api/robot/list`

训练相关：
- `GET /api/train/config`
- `POST /api/train/start`
- `GET /api/train/status/<job_id>`
- `GET /api/train/status`

Web 会话与业务接口（节选）：
- `GET /api/web/session`
- `POST /api/web/login`
- `POST /api/web/register`
- `POST /api/web/logout`
- `GET /api/web/tasks`

## 模型与训练

- 推理器位于 `backend/inference/yolo_detector.py`。
- 训练任务通过 `POST /api/train/start` 异步执行，仅管理员可启动（上传的权重和数据集配置在加载时可以执行代码）。
- 训练数据需上传 ZIP，支持自定义权重 `.pt`。
- 返回结果中会包含训练产出目录与权重提示路径。

## 机器人与仿真

- 机器人固件示例位于 `Rm_arm/`。
- 桌面仿真脚本位于 `Simulator/`（依赖：`pip install -r Simulator/requirements.txt`）。
- 后端通过机器人 API 提供心跳、状态、导航与控制通道。

## 测试

在后端目录执行：

```bash
cd backend
python -m unittest discover -s test -p "test_*.py"
```

若环境缺少完整依赖，可先运行基础测试：

```bash
cd backend
python -m unittest -q test.test_config test.test_ml_algorithm
```

## 常见问题

- 检测接口返回依赖缺失
  - 先调用 `GET /api/detect/dependencies` 查看缺失包与安装建议。
- 启动时报 MySQL 库不存在
  - 检查 `backend/runtime_config.yaml` 中 database 配置，改为可用库或 SQLite。
- 训练上传被 413 拒绝
  - 增大 `TRAIN_MAX_CONTENT_LENGTH`，并保证 `MAX_CONTENT_LENGTH` 不小于该值。
- 前端样式或资源异常
  - 确保使用 `frontend` 构建产物，并由后端 `backend/static/spa` 提供静态资源。

## 许可证

本项目采用 AGPL-3.0 协议（与 Ultralytics YOLO 保持一致），详见 `LICENSE`。