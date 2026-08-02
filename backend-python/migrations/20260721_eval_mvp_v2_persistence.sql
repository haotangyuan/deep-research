-- Eval MVP v2 落库链路 —— 持久化迁移
-- 见 docs/deep-research-eval-mvp-v2-tier-mechanism.md §6
--
-- 幂等、可重跑。新库由 app/infrastructure/db.py ensure_tables() 的 create_all 自动建表；
-- 本脚本仅用于既有库一次性补建 5 张表。MySQL <8.0.19 不支持 ADD COLUMN IF NOT EXISTS，
-- 故建列级补建用「存储过程 + information_schema 守卫」模式。表级 CREATE TABLE IF NOT EXISTS 安全。

-- ===========================================================================
-- 1. 一次性建表（IF NOT EXISTS 保证幂等）
-- ===========================================================================

CREATE TABLE IF NOT EXISTS `research_run` (
  `id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'run_id (uuid hex)',
  `research_id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '研究ID',
  `attempt_no` int unsigned NOT NULL COMMENT '同 research 的执行序号',
  `trigger_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'initial/retry/hitl_resume/clarify_resume/checkpoint_resume',
  `trace_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'OTel trace_id',
  `status` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '终态 workflow status',
  `outcome` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'success/degraded/failed/cancelled/hitl_wait',
  `workflow_mode` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'fixed/ultra_dynamic/...',
  `budget_level` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'MEDIUM/HIGH/ULTRA',
  `request_model` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '请求模型名',
  `response_model` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '响应模型名（MVP 留空）',
  `workflow_commit_sha` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'git commit sha',
  `workflow_dirty` int unsigned DEFAULT NULL COMMENT '是否有未提交改动 0/1',
  `prompt_version_json` text COLLATE utf8mb4_unicode_ci COMMENT '各 prompt family 版本 JSON',
  `prompt_hash_json` text COLLATE utf8mb4_unicode_ci COMMENT '各 prompt family sha256 JSON',
  `template_version` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'workflow template 版本',
  `template_sha256` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'template 规范化后 sha256',
  `evaluator_version` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'evaluator 版本（后续 commit 填）',
  `judge_model` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'judge 模型（后续 commit 填）',
  `fallback_used` int unsigned DEFAULT NULL COMMENT '是否触发降级 0/1',
  `fallback_type` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '降级类型',
  `fallback_reason` text COLLATE utf8mb4_unicode_ci COMMENT '降级原因',
  `input_tokens` bigint unsigned DEFAULT NULL COMMENT '本 run 输入 token（per-run delta）',
  `output_tokens` bigint unsigned DEFAULT NULL COMMENT '本 run 输出 token（per-run delta）',
  `search_count` int unsigned DEFAULT NULL COMMENT '搜索次数',
  `conduct_count` int unsigned DEFAULT NULL COMMENT 'conduct 任务数',
  `round_count` int unsigned DEFAULT NULL COMMENT '动态轮次数',
  `active_duration_ms` bigint unsigned DEFAULT NULL COMMENT '活跃执行耗时',
  `wall_duration_ms` bigint unsigned DEFAULT NULL COMMENT '墙钟耗时',
  `start_time` datetime DEFAULT NULL COMMENT 'run 开始时间',
  `end_time` datetime DEFAULT NULL COMMENT 'run 结束时间',
  `config_json` text COLLATE utf8mb4_unicode_ci COMMENT '运行配置快照',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_research_run_research` (`research_id`),
  KEY `idx_research_run_trace` (`trace_id`),
  UNIQUE KEY `uniq_research_run_attempt` (`research_id`,`attempt_no`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='单次连续后台执行';

CREATE TABLE IF NOT EXISTS `research_artifact` (
  `id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'artifact id (uuid hex)',
  `run_id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'run_id',
  `research_id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '研究ID',
  `artifact_type` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'user_query/research_brief/source_snapshot/evidence_item/round_review/report_final/...',
  `stage_name` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'stage 名',
  `agent_name` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'agent 名',
  `round_no` int unsigned DEFAULT NULL COMMENT '动态轮次',
  `section_id` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '章节ID',
  `angle` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '多角度起草角度',
  `content` mediumtext COLLATE utf8mb4_unicode_ci COMMENT '产物正文',
  `content_ref` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '外部引用路径',
  `content_sha256` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '正文 sha256',
  `request_model` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '请求模型名',
  `response_model` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '响应模型名',
  `prompt_version` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'prompt 版本',
  `prompt_sha256` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'prompt sha256',
  `outcome` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'success/failed',
  `fallback_used` int unsigned DEFAULT NULL COMMENT '是否降级 0/1',
  `metadata_json` text COLLATE utf8mb4_unicode_ci COMMENT '附加元数据',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_research_artifact_run` (`run_id`),
  KEY `idx_research_artifact_research` (`research_id`),
  KEY `idx_research_artifact_type` (`artifact_type`),
  UNIQUE KEY `uniq_research_artifact_key` (`run_id`,`artifact_type`,`round_no`,`section_id`,`angle`,`content_sha256`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='研究产物落库';

CREATE TABLE IF NOT EXISTS `research_llm_call` (
  `id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'llm_call_id (PK 去重 replay)',
  `run_id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'run_id',
  `research_id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '研究ID',
  `stage_name` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'stage 名',
  `agent_name` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'agent 名',
  `round_no` int unsigned DEFAULT NULL COMMENT '动态轮次',
  `report_phase` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '报告阶段 merge/synthesis/section_draft/...',
  `reviewer_lens` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '评审视角',
  `section_id` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '章节ID',
  `request_model` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '请求模型名',
  `response_model` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '响应模型名',
  `attempt_no` int unsigned DEFAULT NULL COMMENT 'Layer-C 重试次数',
  `input_tokens` bigint unsigned DEFAULT NULL COMMENT '输入 token',
  `output_tokens` bigint unsigned DEFAULT NULL COMMENT '输出 token',
  `duration_ms` bigint unsigned DEFAULT NULL COMMENT '耗时',
  `outcome` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'success/failed',
  `error_type` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '异常类名',
  `start_time` datetime DEFAULT NULL COMMENT '开始时间',
  `end_time` datetime DEFAULT NULL COMMENT '结束时间',
  PRIMARY KEY (`id`),
  KEY `idx_research_llm_call_run` (`run_id`),
  KEY `idx_research_llm_call_research` (`research_id`),
  KEY `idx_research_llm_call_stage` (`stage_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='LLM 调用 token 事实源';

CREATE TABLE IF NOT EXISTS `research_stage_usage` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '投影行ID',
  `run_id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'run_id',
  `stage_name` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'stage 名',
  `agent_name` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'agent 名',
  `round_no` int unsigned DEFAULT NULL COMMENT '动态轮次',
  `report_phase` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '报告阶段',
  `reviewer_lens` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '评审视角',
  `section_id` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '章节ID',
  `request_count` int unsigned DEFAULT NULL COMMENT '逻辑调用次数',
  `retry_count` int unsigned DEFAULT NULL COMMENT '物理重试次数',
  `input_tokens` bigint unsigned DEFAULT NULL COMMENT '输入 token 汇总',
  `output_tokens` bigint unsigned DEFAULT NULL COMMENT '输出 token 汇总',
  `duration_ms` bigint unsigned DEFAULT NULL COMMENT '耗时汇总',
  `outcome` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '末次 outcome',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_research_stage_usage_run` (`run_id`),
  UNIQUE KEY `uniq_research_stage_usage_key` (`run_id`,`stage_name`,`agent_name`,`round_no`,`report_phase`,`reviewer_lens`,`section_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='阶段级 token 投影';

CREATE TABLE IF NOT EXISTS `research_claim_manifest` (
  `id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'manifest 行ID',
  `run_id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'run_id',
  `research_id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '研究ID',
  `report_artifact_id` char(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '关联 report artifact id',
  `claim_id` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'claim 标识',
  `claim_text` mediumtext COLLATE utf8mb4_unicode_ci COMMENT 'claim 文本',
  `section_id` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '章节ID',
  `importance` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'critical/major/minor',
  `citation_id` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '引用标识（无引用则 __none__）',
  `citation_url` varchar(1024) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '引用 URL',
  `citation_excerpt` text COLLATE utf8mb4_unicode_ci COMMENT '引用片段',
  `evidence_id` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '证据ID',
  `verifiable` int unsigned DEFAULT NULL COMMENT '是否可核验 0/1',
  `metadata_json` text COLLATE utf8mb4_unicode_ci COMMENT '附加元数据',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_research_claim_manifest_run` (`run_id`),
  KEY `idx_research_claim_manifest_research` (`research_id`),
  KEY `idx_research_claim_manifest_report` (`report_artifact_id`),
  UNIQUE KEY `uniq_research_claim_manifest_key` (`run_id`,`report_artifact_id`,`claim_id`,`citation_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='claim-citation 清单';

-- ===========================================================================
-- 2. 列级补建存储过程（幂等：列已存在则跳过）
--    供后续 commit 增列复用。Commit 1 无列追加，仅建立机制。
-- ===========================================================================

DROP PROCEDURE IF EXISTS `_eval_add_col`;
DELIMITER //
CREATE PROCEDURE `_eval_add_col`(IN tbl VARCHAR(64), IN col VARCHAR(64), IN ddl TEXT)
BEGIN
  DECLARE col_count INT DEFAULT 0;
  SELECT COUNT(*) INTO col_count
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl AND COLUMN_NAME = col;
  IF col_count = 0 THEN
    SET @s = CONCAT('ALTER TABLE `', tbl, '` ADD COLUMN ', ddl);
    PREPARE stmt FROM @s;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END//
DELIMITER ;

-- 后续 commit 在此追加列，示例（当前无）：
-- CALL `_eval_add_col`('research_run', 'new_column', '`new_column` varchar(64) DEFAULT NULL COMMENT ''示例''');

DROP PROCEDURE IF EXISTS `_eval_add_col`;
