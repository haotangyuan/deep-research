-- Eval MVP v2 Commit 6 —— Eval 数据层迁移（dataset / experiment / case_run / score）
-- 见 docs/deep-research-eval-mvp-v2-tier-mechanism.md §6.7-6.10
--
-- 幂等、可重跑。新库由 app/infrastructure/db.py ensure_tables() 的 create_all 自动建表；
-- 本脚本仅用于既有库一次性补建 4 张 eval 表。

-- ===========================================================================
-- 1. eval_dataset_item
-- ===========================================================================
CREATE TABLE IF NOT EXISTS `eval_dataset_item` (
  `id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'dataset_item_id (uuid hex)',
  `dataset_name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '数据集名',
  `dataset_version` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '数据集版本',
  `source_research_id` char(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '来源 research_id',
  `source_run_id` char(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '来源 run_id',
  `query_snapshot` mediumtext COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '脱敏后的题目快照',
  `query_sha256` char(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '题目 sha256（去重）',
  `task_type` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '事实检索/技术比较/...',
  `language` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `as_of_date` date DEFAULT NULL COMMENT '题目 as-of 日期',
  `required_points_json` text COLLATE utf8mb4_unicode_ci COMMENT '必须覆盖的要点',
  `reference_facts_json` text COLLATE utf8mb4_unicode_ci COMMENT '关键参考事实',
  `forbidden_claims_json` text COLLATE utf8mb4_unicode_ci COMMENT '禁止出现的声明',
  `source_policy_json` text COLLATE utf8mb4_unicode_ci COMMENT '来源策略',
  `evaluation_contract_json` text COLLATE utf8mb4_unicode_ci COMMENT 'Eval 前冻结的约束、预期意图、适用档位与机制标签',
  `privacy_status` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'candidate/privacy_reviewed/.../retired',
  `annotation_status` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'annotating/ready/...',
  `sample_reason` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '分层抽样理由',
  `split_name` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'train/val/test',
  `create_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_eval_dataset_name_version` (`dataset_name`,`dataset_version`,`split_name`,`task_type`),
  UNIQUE KEY `uniq_eval_dataset_item_query` (`dataset_name`,`dataset_version`,`query_sha256`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Eval 候选题目（脱敏、版本化）';

-- ===========================================================================
-- 2. eval_experiment
-- ===========================================================================
CREATE TABLE IF NOT EXISTS `eval_experiment` (
  `id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'experiment_id (uuid hex)',
  `name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `dataset_name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `dataset_version` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `experiment_type` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'tier_comparison/high_report_ablation/reviewer_ablation/multi_round_ablation/section_team_ablation/claim_verifier_ablation',
  `baseline_experiment_id` char(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `workflow_version` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `evaluator_version` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `judge_model` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `config_json` text COLLATE utf8mb4_unicode_ci,
  `status` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'planned/running/completed/failed',
  `create_time` datetime DEFAULT NULL,
  `complete_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_eval_experiment_dataset` (`dataset_name`,`dataset_version`),
  KEY `idx_eval_experiment_type` (`experiment_type`),
  KEY `idx_eval_experiment_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Eval 实验定义';

-- ===========================================================================
-- 3. eval_case_run
-- ===========================================================================
CREATE TABLE IF NOT EXISTS `eval_case_run` (
  `id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'case_run_id (uuid hex)',
  `experiment_id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `dataset_item_id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `run_id` char(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '关联 research_run.id',
  `variant_name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'MEDIUM/HIGH/ULTRA 或机制 variant',
  `repeat_no` int DEFAULT '0',
  `gate_passed` tinyint DEFAULT NULL COMMENT 'Hard Gate 是否通过 0/1',
  `failure_reasons_json` text COLLATE utf8mb4_unicode_ci,
  `total_score` decimal(8,4) DEFAULT NULL,
  `estimated_cost` decimal(12,6) DEFAULT NULL,
  `create_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_eval_case_run_key` (`experiment_id`,`dataset_item_id`,`variant_name`,`repeat_no`),
  KEY `idx_eval_case_run_experiment` (`experiment_id`),
  KEY `idx_eval_case_run_item` (`dataset_item_id`),
  KEY `idx_eval_case_run_run` (`run_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Eval 单次回放运行';

-- ===========================================================================
-- 4. eval_score
-- ===========================================================================
CREATE TABLE IF NOT EXISTS `eval_score` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `case_run_id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `metric_name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `metric_group` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'gate/recall/factuality/source/analysis/presentation',
  `score_value` decimal(10,6) DEFAULT NULL,
  `label_value` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `passed` tinyint DEFAULT NULL,
  `evaluator_name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `evaluator_version` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `judge_model` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `reason` text COLLATE utf8mb4_unicode_ci,
  `details_json` mediumtext COLLATE utf8mb4_unicode_ci,
  `create_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_eval_score_key` (`case_run_id`,`metric_name`,`evaluator_version`),
  KEY `idx_eval_score_case_run` (`case_run_id`),
  KEY `idx_eval_score_metric` (`metric_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Eval 通用分数';

-- ===========================================================================
-- 存量库补列（Dataset Contract）
-- 用 information_schema 守卫，幂等可重跑。
-- ===========================================================================
DROP PROCEDURE IF EXISTS `_eval_add_col`;
DELIMITER //
CREATE PROCEDURE `_eval_add_col`(IN tbl VARCHAR(64), IN col VARCHAR(64), IN ddl TEXT)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl AND COLUMN_NAME = col
  ) THEN
    SET @s = CONCAT('ALTER TABLE `', tbl, '` ADD COLUMN `', col, '` ', ddl);
    PREPARE stmt FROM @s; EXECUTE stmt; DEALLOCATE PREPARE stmt;
  END IF;
END //
DELIMITER ;
CALL `_eval_add_col`('eval_dataset_item', 'evaluation_contract_json', "text COLLATE utf8mb4_unicode_ci COMMENT 'Eval 前冻结的约束、预期意图、适用档位与机制标签'");
DROP PROCEDURE IF EXISTS `_eval_add_col`;
