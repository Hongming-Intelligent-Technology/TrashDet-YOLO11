-- TrashDet MySQL schema (migration revision 0003).
--
-- Creates the `trashdet` database and all tables on an EMPTY MySQL server:
--   mysql -u root -p < backend/database/schema.sql
--
-- You usually don't need this file: the backend creates and upgrades the tables itself on
-- startup (Flask-Migrate, backend/migrations/). Use it when you want to create the schema by
-- hand, e.g. with a DBA account while the app runs with fewer privileges.
--
-- Generated from backend/database/models.py. If the models change, add a migration and
-- regenerate this file; the alembic_version row at the end must match the newest migration.

CREATE DATABASE IF NOT EXISTS trashdet CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE trashdet;

CREATE TABLE train_jobs (
  id VARCHAR(32) NOT NULL,
  status VARCHAR(20) NOT NULL,
  created_at VARCHAR(32),
  started_at VARCHAR(32),
  completed_at VARCHAR(32),
  error TEXT,
  meta_json TEXT,
  result_json TEXT,
  logs_json TEXT,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE users (
  id INTEGER NOT NULL AUTO_INCREMENT,
  username VARCHAR(50) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  security_code VARCHAR(255) NOT NULL,
  organization VARCHAR(120),
  `role` VARCHAR(20) NOT NULL DEFAULT 'user',
  PRIMARY KEY (id),
  UNIQUE (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE detection_tasks (
  id INTEGER NOT NULL AUTO_INCREMENT,
  source_type VARCHAR(20),
  source_path VARCHAR(255),
  result_path VARCHAR(255),
  device_id VARCHAR(50),
  location VARCHAR(255),
  status VARCHAR(20),
  error_msg TEXT,
  user_id INTEGER,
  created_at DATETIME,
  latitude DOUBLE,
  longitude DOUBLE,
  PRIMARY KEY (id),
  CONSTRAINT fk_detection_tasks_user_id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX ix_detection_tasks_created_at ON detection_tasks (created_at);

CREATE INDEX ix_detection_tasks_latitude ON detection_tasks (latitude);

CREATE INDEX ix_detection_tasks_user_id ON detection_tasks (user_id);

CREATE TABLE operation_logs (
  id INTEGER NOT NULL AUTO_INCREMENT,
  user_id INTEGER,
  action VARCHAR(255),
  created_at DATETIME,
  PRIMARY KEY (id),
  CONSTRAINT fk_operation_logs_user_id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE robots (
  id INTEGER NOT NULL AUTO_INCREMENT,
  device_id VARCHAR(50) NOT NULL,
  name VARCHAR(100),
  status VARCHAR(20),
  ip_address VARCHAR(50),
  owner_user_id INTEGER,
  current_lat DOUBLE,
  current_lng DOUBLE,
  target_lat DOUBLE,
  target_lng DOUBLE,
  last_heartbeat DATETIME,
  next_command VARCHAR(100),
  battery INTEGER,
  config JSON,
  created_at DATETIME,
  PRIMARY KEY (id),
  UNIQUE (device_id),
  CONSTRAINT fk_robots_owner_user_id FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX ix_robots_owner_user_id ON robots (owner_user_id);

CREATE TABLE detection_items (
  id INTEGER NOT NULL AUTO_INCREMENT,
  task_id INTEGER NOT NULL,
  label VARCHAR(50),
  confidence FLOAT,
  x1 INTEGER,
  y1 INTEGER,
  x2 INTEGER,
  y2 INTEGER,
  area INTEGER,
  handle_state VARCHAR(20),
  frame_index INTEGER,
  snapshot_path VARCHAR(255),
  captured_at DATETIME,
  updated_at DATETIME,
  PRIMARY KEY (id),
  CONSTRAINT fk_detection_items_task_id FOREIGN KEY(task_id) REFERENCES detection_tasks (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX ix_detection_items_label ON detection_items (label);

CREATE INDEX ix_detection_items_task_id ON detection_items (task_id);

CREATE TABLE robot_patrol_tasks (
  id INTEGER NOT NULL AUTO_INCREMENT,
  robot_id INTEGER NOT NULL,
  name VARCHAR(120) NOT NULL,
  inspection_area TEXT NOT NULL,
  planned_path TEXT,
  status VARCHAR(20) NOT NULL,
  current_waypoint_index INTEGER NOT NULL,
  created_by_user_id INTEGER,
  created_at DATETIME,
  updated_at DATETIME,
  PRIMARY KEY (id),
  FOREIGN KEY(robot_id) REFERENCES robots (id) ON DELETE CASCADE,
  CONSTRAINT fk_robot_patrol_tasks_created_by_user_id FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX ix_robot_patrol_tasks_created_at ON robot_patrol_tasks (created_at);

CREATE INDEX ix_robot_patrol_tasks_created_by_user_id ON robot_patrol_tasks (created_by_user_id);

CREATE INDEX ix_robot_patrol_tasks_robot_id ON robot_patrol_tasks (robot_id);

CREATE INDEX ix_robot_patrol_tasks_robot_id_status ON robot_patrol_tasks (robot_id, status);

-- Tells the backend the schema is already at the newest migration, so it won't try to
-- adopt and re-migrate these tables on startup.
CREATE TABLE alembic_version (
  version_num VARCHAR(32) NOT NULL,
  CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO alembic_version (version_num) VALUES ('0003');
