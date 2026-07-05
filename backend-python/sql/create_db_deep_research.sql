-- Create the default database expected by backend-python/app/core/config.py.
-- Tables are created automatically by the backend on first startup.

CREATE DATABASE IF NOT EXISTS `db_deep_research`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

-- Optional example if you want to create a dedicated application user:
-- CREATE USER IF NOT EXISTS 'deep_research'@'%' IDENTIFIED BY 'change_me';
-- GRANT ALL PRIVILEGES ON `db_deep_research`.* TO 'deep_research'@'%';
-- FLUSH PRIVILEGES;
