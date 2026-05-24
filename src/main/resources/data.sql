-- 用户表
CREATE TABLE IF NOT EXISTS `user` (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '用户ID',
    username        VARCHAR(128)    DEFAULT NULL UNIQUE COMMENT '用户名',
    password        VARCHAR(128)    DEFAULT NULL COMMENT '密码',
    google_id       VARCHAR(64)     DEFAULT NULL UNIQUE COMMENT 'Google OpenID (sub)',
    avatar_url      VARCHAR(512)    DEFAULT NULL COMMENT '头像URL (DiceBear)',
    create_time     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    KEY idx_google_id (google_id),
    KEY idx_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表';

-- 研究会话表
-- Primary Key: UUID (由 MyBatis-Plus ASSIGN_UUID 生成)
CREATE TABLE IF NOT EXISTS research_session (
    id              CHAR(32)        NOT NULL PRIMARY KEY COMMENT '研究ID (UUID)',
    user_id         BIGINT UNSIGNED NOT NULL COMMENT '用户ID',
    status          VARCHAR(32)     NOT NULL DEFAULT 'NEW' COMMENT '状态: NEW/QUEUE/START/IN_SCOPE/NEED_CLARIFICATION/IN_RESEARCH/IN_REPORT/COMPLETED/FAILED',
    create_time     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    start_time      DATETIME        DEFAULT NULL COMMENT '开始研究时间',
    update_time     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    complete_time   DATETIME        DEFAULT NULL COMMENT '完成时间',
    model_id        VARCHAR(256)    DEFAULT NULL COMMENT '模型ID',
    budget          VARCHAR(16)     DEFAULT NULL COMMENT '研究预算级别: MEDIUM/HIGH/ULTRA',
    title           VARCHAR(256)    DEFAULT NULL COMMENT '研究标题',
    total_input_tokens  BIGINT UNSIGNED DEFAULT 0 COMMENT '累计输入Token数',
    total_output_tokens BIGINT UNSIGNED DEFAULT 0 COMMENT '累计输出Token数',
    KEY idx_user_status (user_id, status),
    KEY idx_user_update (user_id, update_time DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='研究会话';

-- 模型表
CREATE TABLE IF NOT EXISTS model (
    id          CHAR(32)        NOT NULL PRIMARY KEY COMMENT '模型ID',
    type        VARCHAR(16)     NOT NULL COMMENT 'GLOBAL/USER',
    user_id     BIGINT UNSIGNED DEFAULT NULL COMMENT '拥有者',
    name        VARCHAR(128)    NOT NULL COMMENT '展示名称',
    model       VARCHAR(128)    NOT NULL COMMENT '模型ID',
    base_url    VARCHAR(256)    NOT NULL COMMENT '接口地址',
    api_key     VARCHAR(256)    DEFAULT NULL COMMENT 'API Key',
    create_time DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    KEY idx_type_user_create (type, user_id, create_time DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='模型配置';

-- 聊天消息表
-- 存储用户与助手的对话消息
CREATE TABLE IF NOT EXISTS chat_message (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '消息ID',
    research_id     CHAR(32)        NOT NULL COMMENT '研究ID',
    role            VARCHAR(16)     NOT NULL COMMENT '角色: user/assistant',
    content         MEDIUMTEXT      NOT NULL COMMENT '消息内容',
    sequence_no     INT UNSIGNED    NOT NULL COMMENT '序列号',
    create_time     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    KEY idx_research_seq (research_id, sequence_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='聊天消息';

-- 工作流事件表
-- 记录研究过程中的各类事件
CREATE TABLE IF NOT EXISTS workflow_event (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '事件ID',
    research_id     CHAR(32)        NOT NULL COMMENT '研究ID',
    type            VARCHAR(32)     NOT NULL COMMENT '事件类型',
    title           VARCHAR(512)    NOT NULL COMMENT '事件标题',
    content         MEDIUMTEXT      DEFAULT NULL COMMENT '事件内容',
    parent_event_id BIGINT UNSIGNED DEFAULT NULL COMMENT '父事件ID (用于层级缩进)',
    sequence_no     INT UNSIGNED    NOT NULL COMMENT '序列号',
    create_time     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    KEY idx_research_seq (research_id, sequence_no),
    KEY idx_parent (parent_event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='工作流事件';
