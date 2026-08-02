-- Eval 核心表精简迁移。
--
-- 目标：
-- 1. Token/时延只以 research_llm_call 为明细事实源；
-- 2. 报告正文只以 research_artifact 为事实源；
-- 3. score 通过 case_run -> run/artifact 关联，不重复保存 trace/artifact ID；
-- 4. Dataset 同版本 Query 由数据库唯一约束保证幂等。
--
-- 本脚本幂等，可重复执行。执行前仍建议按常规流程备份数据库。

-- 该表此前只为 Eval 重复落地 Span 标量；现在保留 OTel/Langfuse 属性，
-- 本地 Eval 统一读取 round_review Artifact。
DROP TABLE IF EXISTS `research_span_attribute`;

DROP PROCEDURE IF EXISTS `_eval_drop_col`;
DELIMITER //
CREATE PROCEDURE `_eval_drop_col`(IN tbl VARCHAR(64), IN col VARCHAR(64))
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl AND COLUMN_NAME = col
  ) THEN
    SET @s = CONCAT('ALTER TABLE `', tbl, '` DROP COLUMN `', col, '`');
    PREPARE stmt FROM @s; EXECUTE stmt; DEALLOCATE PREPARE stmt;
  END IF;
END //
DELIMITER ;

CALL `_eval_drop_col`('research_artifact', 'input_tokens');
CALL `_eval_drop_col`('research_artifact', 'output_tokens');
CALL `_eval_drop_col`('research_artifact', 'duration_ms');

CALL `_eval_drop_col`('eval_case_run', 'input_tokens');
CALL `_eval_drop_col`('eval_case_run', 'output_tokens');
CALL `_eval_drop_col`('eval_case_run', 'duration_ms');
CALL `_eval_drop_col`('eval_case_run', 'result_json');
CALL `_eval_drop_col`('eval_case_run', 'research_id');

CALL `_eval_drop_col`('eval_dataset_item', 'original_budget_level');

CALL `_eval_drop_col`('eval_score', 'trace_id');
CALL `_eval_drop_col`('eval_score', 'report_artifact_id');

DROP PROCEDURE IF EXISTS `_eval_drop_col`;

DROP PROCEDURE IF EXISTS `_eval_drop_idx`;
DELIMITER //
CREATE PROCEDURE `_eval_drop_idx`(IN tbl VARCHAR(64), IN idx VARCHAR(128))
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl AND INDEX_NAME = idx
  ) THEN
    SET @s = CONCAT('ALTER TABLE `', tbl, '` DROP INDEX `', idx, '`');
    PREPARE stmt FROM @s; EXECUTE stmt; DEALLOCATE PREPARE stmt;
  END IF;
END //
DELIMITER ;

-- id 已是主键，(run_id, id) 唯一索引没有提供额外约束。
CALL `_eval_drop_idx`('research_llm_call', 'uniq_research_llm_call_run');
CALL `_eval_drop_idx`('eval_score', 'idx_eval_score_trace');
CALL `_eval_drop_idx`('eval_score', 'idx_eval_score_report_artifact');

DROP PROCEDURE IF EXISTS `_eval_drop_idx`;

-- 同一 Dataset Version 中同一 Query 只能出现一次。
SET @eval_dataset_duplicate_count = (
  SELECT COUNT(*)
  FROM (
    SELECT 1
    FROM `eval_dataset_item`
    WHERE `query_sha256` IS NOT NULL
    GROUP BY `dataset_name`, `dataset_version`, `query_sha256`
    HAVING COUNT(*) > 1
  ) AS duplicate_groups
);

SET @eval_dataset_unique_exists = (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'eval_dataset_item'
    AND INDEX_NAME = 'uniq_eval_dataset_item_query'
);

SET @eval_add_dataset_unique_sql = IF(
  @eval_dataset_duplicate_count = 0 AND @eval_dataset_unique_exists = 0,
  'ALTER TABLE `eval_dataset_item` ADD UNIQUE KEY `uniq_eval_dataset_item_query` (`dataset_name`,`dataset_version`,`query_sha256`)',
  'SELECT 1'
);
PREPARE stmt FROM @eval_add_dataset_unique_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 复合唯一索引已经覆盖 Query 去重查询，单列索引不再保留。
SET @eval_dataset_unique_exists = (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'eval_dataset_item'
    AND INDEX_NAME = 'uniq_eval_dataset_item_query'
);
SET @eval_dataset_old_idx_exists = (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'eval_dataset_item'
    AND INDEX_NAME = 'idx_eval_dataset_query_sha'
);
SET @eval_drop_old_dataset_idx_sql = IF(
  @eval_dataset_unique_exists > 0 AND @eval_dataset_old_idx_exists > 0,
  'ALTER TABLE `eval_dataset_item` DROP INDEX `idx_eval_dataset_query_sha`',
  'SELECT 1'
);
PREPARE stmt FROM @eval_drop_old_dataset_idx_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
