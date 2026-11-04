-- Schema of the removed database/database.sql (before migrations existed).
-- Used by test_migrations_mysql.py to check that old databases upgrade correctly.

CREATE TABLE IF NOT EXISTS `users` (
    `id` INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `username` VARCHAR(50) NOT NULL UNIQUE,
    `password_hash` VARCHAR(255) NOT NULL,
    `security_code` VARCHAR(255) NOT NULL,
    `organization` VARCHAR(120) NULL,
    `role` VARCHAR(20) NOT NULL DEFAULT 'user',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `detection_tasks` (
    `id` INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `source_type` VARCHAR(20) NULL,
    `source_path` VARCHAR(255) NULL,
    `result_path` VARCHAR(255) NULL,
    `device_id` VARCHAR(50) NULL,
    `location` VARCHAR(100) NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    `error_msg` TEXT NULL,
    `user_id` INT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `latitude` DOUBLE NULL,
    `longitude` DOUBLE NULL,
    CONSTRAINT `fk_detection_tasks_user`
        FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `detection_items` (
    `id` INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `task_id` INT NOT NULL,
    `label` VARCHAR(50) NULL,
    `confidence` DOUBLE NULL,
    `x1` INT NULL,
    `y1` INT NULL,
    `x2` INT NULL,
    `y2` INT NULL,
    `area` INT NULL,
    `handle_state` VARCHAR(20) NOT NULL DEFAULT 'NEW',
    `frame_index` INT NULL,
    `snapshot_path` VARCHAR(255) NULL,
    `captured_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT `fk_detection_items_task`
        FOREIGN KEY (`task_id`) REFERENCES `detection_tasks`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `operation_logs` (
    `id` INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NULL,
    `action` VARCHAR(255) NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT `fk_operation_logs_user`
        FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `robots` (
    `id` INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `device_id` VARCHAR(50) NOT NULL UNIQUE,
    `name` VARCHAR(100) NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'OFFLINE',
    `ip_address` VARCHAR(50) NULL,
    `owner_user_id` INT NULL,
    `current_lat` DOUBLE NULL,
    `current_lng` DOUBLE NULL,
    `target_lat` DOUBLE NULL,
    `target_lng` DOUBLE NULL,
    `last_heartbeat` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `next_command` VARCHAR(100) NOT NULL DEFAULT 'IDLE',
    `battery` INT NOT NULL DEFAULT 100,
    `config` JSON NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT `fk_robots_owner_user`
        FOREIGN KEY (`owner_user_id`) REFERENCES `users`(`id`) ON DELETE SET NULL,
    CONSTRAINT `chk_robots_battery`
        CHECK (`battery` >= 0 AND `battery` <= 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `robot_patrol_tasks` (
    `id` INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `robot_id` INT NOT NULL,
    `name` VARCHAR(120) NOT NULL,
    `inspection_area` TEXT NOT NULL,
    `planned_path` TEXT NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'PLANNED',
    `current_waypoint_index` INT NOT NULL DEFAULT 0,
    `created_by_user_id` INT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT `fk_robot_patrol_tasks_robot`
        FOREIGN KEY (`robot_id`) REFERENCES `robots`(`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_robot_patrol_tasks_creator`
        FOREIGN KEY (`created_by_user_id`) REFERENCES `users`(`id`) ON DELETE SET NULL,
    CONSTRAINT `chk_robot_patrol_tasks_waypoint_index`
        CHECK (`current_waypoint_index` >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX `idx_detection_tasks_time_geo`
    ON `detection_tasks` (`created_at`, `latitude`, `longitude`);

CREATE INDEX `idx_detection_tasks_user_id`
    ON `detection_tasks` (`user_id`);

CREATE INDEX `idx_detection_items_task_label`
    ON `detection_items` (`task_id`, `label`);

CREATE INDEX `idx_detection_items_label`
    ON `detection_items` (`label`);

CREATE INDEX `idx_robots_owner_user_id`
    ON `robots` (`owner_user_id`);

CREATE INDEX `idx_robot_patrol_tasks_robot_id`
    ON `robot_patrol_tasks` (`robot_id`, `status`);

CREATE INDEX `idx_robot_patrol_tasks_created_by_user_id`
    ON `robot_patrol_tasks` (`created_by_user_id`);