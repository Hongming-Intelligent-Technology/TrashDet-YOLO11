# TrashDet-YOLO11

**简体中文** | [English](README_EN.md)

TrashDet 是一个基于 YOLO11 的垃圾识别与拾捡机器人管理平台。它把整条流程串在一起：拍照或上传图片 → 识别垃圾 → 记录结果和位置 → 统计热点区域 → 调度机器人去清理 → 用新数据继续训练模型。

## 包含什么

| 部分 | 说明 |
|---|---|
| `backend/` | Flask 后端：检测、统计、机器人、训练、登录认证 |
| `frontend/` | React 19 + TypeScript 管理界面，构建后由后端托管 |
| `Rm_arm/` | 机械臂 ESP32 固件（PlatformIO） |
| `Simulator/` | 机器人仿真器（终端版和 Qt 图形版），没有真机也能联调 |

## 主要功能

- **图片检测**：上传图片，返回检测框、类别和置信度，并保存标注后的图片
- **视频检测**：上传视频后在后台处理，通过接口查询进度
- **数据统计**：识别趋势、类别分布、地图点位和热点区域分析
- **机器人管理**：设备注册、心跳、状态同步、控制指令和导航
- **在线训练**：上传 ZIP 数据集，在后台训练新模型（仅管理员）
- **账号系统**：注册、登录、验证码和管理员后台

## 自带模型

仓库内已包含训练好的模型 `backend/model/runs/train/train-200epoch-v11n.pt-bs16/weights/best.pt`（YOLO11n，640×640，200 轮，batch 16）。验证集结果：

| Precision | Recall | mAP50 | mAP50-95 |
|---|---|---|---|
| 0.897 | 0.799 | 0.864 | 0.583 |

训练曲线、混淆矩阵等图表在同一目录下。

## 快速开始

需要 Python 3.10+ 和 Node.js 18+。GPU 推理或训练需要 CUDA，不是必须的。

### 1. 启动后端

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env    # 至少填写 SECRET_KEY
python app.py
```

打开 http://127.0.0.1:5000 。健康检查：http://127.0.0.1:5000/health

**第一次登录**：数据库里没有用户时，系统会自动创建一个管理员。用户名默认是 `admin`，密码和安全码来自 `.env` 中的 `TRASHDET_ADMIN_PASSWORD` 和 `TRASHDET_ADMIN_SECURITY_CODE`。如果没填，会随机生成并在启动日志里打印一次，登录后请立即修改。

### 2. 开发前端（可选）

后端已经自带构建好的前端。只有修改界面时才需要这一步：

```bash
cd frontend
npm install
npm run dev      # 开发模式，/api 请求会转发到 http://127.0.0.1:5000
npm run lint     # 代码检查（oxlint，含 React Hooks 规则）
npm run build    # 类型检查并构建到 backend/static/spa，由后端托管
```

### 3. 运行仿真机器人（可选）

```bash
pip install -r Simulator/requirements.txt
python Simulator/Sim_robot.py --server http://127.0.0.1:5000          # 终端版
python Simulator/Sim_robot.py --gui --server http://127.0.0.1:5000    # Qt 图形版
```

## 配置

配置按以下顺序生效，前面的覆盖后面的：

1. 环境变量
2. `backend/.env`（从 `.env.example` 复制，存放密钥和数据库密码）
3. `backend/runtime_config.yaml`（从 `runtime_config.example.yaml` 复制）
4. `backend/config.py` 中的默认值

常用配置项：

| 配置项 | 作用 |
|---|---|
| `SECRET_KEY` | 会话密钥，必须通过环境变量或 `.env` 设置 |
| `DATABASE_URL` 或 `MYSQL_*` | 数据库连接，都不填则使用 SQLite（`backend/trashdet.db`） |
| `YOLO_MODEL_PATH` | 检测模型路径 |
| `YOLO_CONF_THRESHOLD` | 置信度阈值，默认 0.25 |
| `TRAIN_MAX_CONTENT_LENGTH` | 训练数据集上传大小上限 |
| `CAPTCHA_ENABLED` | 是否开启登录验证码 |

### 使用 MySQL

```sql
CREATE DATABASE trashdet CHARACTER SET utf8mb4;
```

表结构由迁移自动创建，在 `.env` 里填写 `MYSQL_*` 即可。升级版本前请先备份（`mysqldump trashdet > backup.sql`），MySQL 的表结构变更无法回滚。

### 数据库迁移

- 后端启动时会自动执行迁移（Flask-Migrate，见 `backend/migrations/`），旧版本建的数据库也能直接接管。
- 修改模型后生成新迁移：`cd backend && flask --app app:create_app db migrate -m "说明"`

## 部署注意事项

视频检测和训练在后台线程中运行，状态保存在数据库里。服务重启时，未完成的任务会被标记为失败。

生产环境请只用 **一个 worker**，否则后台任务状态会不一致：

```bash
gunicorn -w 1 --threads 8 "app:create_app()"
```

## 接口一览

| 模块 | 接口 |
|---|---|
| 检测 | `POST /api/detect` 图片检测<br>`POST /api/detect/video` 视频检测<br>`GET /api/detect/video/status/<task_id>` 视频任务状态<br>`POST /api/detect/ingest` 写入外部检测结果<br>`GET /api/detect/dependencies` 检查检测依赖 |
| 统计 | `GET /api/stats/summary`<br>`GET /api/stats/hotspots` |
| 机器人 | `POST /api/robot/register`<br>`POST /api/robot/heartbeat`<br>`POST /api/robot/status_update`<br>`POST /api/robot/control`<br>`POST /api/robot/navigate`<br>`GET /api/robot/list` |
| 训练 | `GET /api/train/config`<br>`POST /api/train/start`（仅管理员）<br>`GET /api/train/status`<br>`GET /api/train/status/<job_id>` |
| 账号 | `GET /api/web/session`<br>`POST /api/web/login`<br>`POST /api/web/register`<br>`POST /api/web/logout` |

训练只允许管理员启动，因为上传的权重文件和数据集配置在加载时可以执行代码。

## 测试

测试只需要轻量依赖，不需要 torch 或 ultralytics：

```bash
cd backend
pip install -r requirements-dev.txt
ruff check .
python -m pytest -q test
```

## 常见问题

- **检测接口提示缺少依赖**：调用 `GET /api/detect/dependencies` 查看缺少的包和安装方法。
- **启动时报 MySQL 数据库不存在**：先创建数据库，或清空 `MYSQL_*` 改用 SQLite。
- **上传训练数据被 413 拒绝**：调大 `TRAIN_MAX_CONTENT_LENGTH`；如果在 `runtime_config.yaml` 里设置了 `MAX_CONTENT_LENGTH`，它也不能小于这个值。
- **页面样式错乱**：重新执行 `npm run build`，确认 `backend/static/spa` 是最新的。

## 许可证

AGPL-3.0（与 Ultralytics YOLO 一致），详见 [LICENSE](LICENSE)。
