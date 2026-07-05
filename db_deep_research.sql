-- MySQL dump 10.13  Distrib 5.7.24, for osx11.1 (x86_64)
--
-- Host: localhost    Database: db_deep_research
-- ------------------------------------------------------
-- Server version	9.3.0

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `chat_message`
--

DROP TABLE IF EXISTS `chat_message`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `chat_message` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '消息ID',
  `research_id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '研究ID',
  `role` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '角色: user/assistant',
  `content` mediumtext COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '消息内容',
  `sequence_no` int unsigned NOT NULL COMMENT '序列号',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_research_seq` (`research_id`,`sequence_no`)
) ENGINE=InnoDB AUTO_INCREMENT=89 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='聊天消息';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `model`
--

DROP TABLE IF EXISTS `model`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `model` (
  `id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '模型ID',
  `type` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'GLOBAL/USER',
  `user_id` bigint unsigned DEFAULT NULL COMMENT '拥有者',
  `name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '展示名称',
  `model` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '模型ID',
  `base_url` varchar(256) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '接口地址',
  `api_key` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'API Key',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_type_user_create` (`type`,`user_id`,`create_time` DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='模型配置';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `research_decision_log`
--

DROP TABLE IF EXISTS `research_decision_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `research_decision_log` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `research_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `round_id` bigint DEFAULT NULL,
  `round_no` int DEFAULT NULL,
  `decision_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `action` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `summary` text COLLATE utf8mb4_unicode_ci,
  `payload_json` text COLLATE utf8mb4_unicode_ci,
  `create_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_research_decision_log_round_id` (`round_id`),
  KEY `ix_research_decision_log_round_no` (`round_no`),
  KEY `ix_research_decision_log_research_id` (`research_id`),
  KEY `ix_research_decision_log_decision_type` (`decision_type`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `research_evidence_ledger`
--

DROP TABLE IF EXISTS `research_evidence_ledger`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `research_evidence_ledger` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `research_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `round_id` bigint DEFAULT NULL,
  `work_item_id` bigint DEFAULT NULL,
  `source_url` varchar(1024) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `source_title` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `source_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `strength_score` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `section_hint` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `snippet` text COLLATE utf8mb4_unicode_ci,
  `create_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_research_evidence_ledger_research_id` (`research_id`),
  KEY `ix_research_evidence_ledger_source_type` (`source_type`),
  KEY `ix_research_evidence_ledger_work_item_id` (`work_item_id`),
  KEY `ix_research_evidence_ledger_round_id` (`round_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `research_intervention`
--

DROP TABLE IF EXISTS `research_intervention`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `research_intervention` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `research_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_id` bigint NOT NULL,
  `status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `focus_sections_json` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `reinforce_modes_json` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `note` text COLLATE utf8mb4_unicode_ci,
  `replace_mode` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `requested_round_no` int DEFAULT NULL,
  `target_round_no` int DEFAULT NULL,
  `applied_round_no` int DEFAULT NULL,
  `superseded_by_id` bigint DEFAULT NULL,
  `apply_summary_json` text COLLATE utf8mb4_unicode_ci,
  `reject_code` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `reject_reason` text COLLATE utf8mb4_unicode_ci,
  `create_time` datetime DEFAULT NULL,
  `update_time` datetime DEFAULT NULL,
  `applied_time` datetime DEFAULT NULL,
  `expired_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_research_intervention_research_id` (`research_id`),
  KEY `ix_research_intervention_user_id` (`user_id`),
  KEY `ix_research_intervention_status` (`status`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `research_planning_round`
--

DROP TABLE IF EXISTS `research_planning_round`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `research_planning_round` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `research_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `round_no` int NOT NULL,
  `status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `round_goal` text COLLATE utf8mb4_unicode_ci,
  `intervention_id` bigint DEFAULT NULL,
  `planner_bias_json` text COLLATE utf8mb4_unicode_ci,
  `summary_json` text COLLATE utf8mb4_unicode_ci,
  `create_time` datetime DEFAULT NULL,
  `update_time` datetime DEFAULT NULL,
  `completed_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_research_planning_round_round_no` (`round_no`),
  KEY `ix_research_planning_round_research_id` (`research_id`),
  KEY `ix_research_planning_round_status` (`status`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `research_session`
--

DROP TABLE IF EXISTS `research_session`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `research_session` (
  `id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '研究ID (UUID)',
  `user_id` bigint unsigned NOT NULL COMMENT '用户ID',
  `status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'NEW' COMMENT '状态: NEW/QUEUE/START/IN_SCOPE/NEED_CLARIFICATION/IN_RESEARCH/IN_REPORT/COMPLETED/FAILED',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `start_time` datetime DEFAULT NULL COMMENT '开始研究时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `complete_time` datetime DEFAULT NULL COMMENT '完成时间',
  `model_id` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '模型ID',
  `budget` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '研究预算级别: MEDIUM/HIGH/ULTRA',
  `title` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '研究标题',
  `total_input_tokens` bigint unsigned DEFAULT '0' COMMENT '累计输入Token数',
  `total_output_tokens` bigint unsigned DEFAULT '0' COMMENT '累计输出Token数',
  PRIMARY KEY (`id`),
  KEY `idx_user_status` (`user_id`,`status`),
  KEY `idx_user_update` (`user_id`,`update_time` DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='研究会话';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `research_work_item`
--

DROP TABLE IF EXISTS `research_work_item`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `research_work_item` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `research_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `round_id` bigint NOT NULL,
  `round_no` int NOT NULL,
  `task_key` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `title` varchar(256) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` text COLLATE utf8mb4_unicode_ci,
  `priority` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `result_summary` text COLLATE utf8mb4_unicode_ci,
  `verification_state` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `create_time` datetime DEFAULT NULL,
  `update_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_research_work_item_research_id` (`research_id`),
  KEY `ix_research_work_item_round_id` (`round_id`),
  KEY `ix_research_work_item_status` (`status`),
  KEY `ix_research_work_item_round_no` (`round_no`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `user`
--

DROP TABLE IF EXISTS `user`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `user` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '用户ID',
  `username` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用户名',
  `password` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '密码',
  `google_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Google OpenID (sub)',
  `avatar_url` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '头像URL (DiceBear)',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`),
  UNIQUE KEY `google_id` (`google_id`),
  KEY `idx_google_id` (`google_id`),
  KEY `idx_username` (`username`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `workflow_event`
--

DROP TABLE IF EXISTS `workflow_event`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `workflow_event` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '事件ID',
  `research_id` char(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '研究ID',
  `type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '事件类型',
  `title` varchar(512) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '事件标题',
  `content` mediumtext COLLATE utf8mb4_unicode_ci COMMENT '事件内容',
  `parent_event_id` bigint unsigned DEFAULT NULL COMMENT '父事件ID (用于层级缩进)',
  `sequence_no` int unsigned NOT NULL COMMENT '序列号',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_research_seq` (`research_id`,`sequence_no`),
  KEY `idx_parent` (`parent_event_id`)
) ENGINE=InnoDB AUTO_INCREMENT=1447 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='工作流事件';
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-07-05 14:18:41
