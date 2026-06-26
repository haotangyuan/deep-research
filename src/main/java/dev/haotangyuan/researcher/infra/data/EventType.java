package dev.haotangyuan.researcher.infra.data;

/**
 * 工作流事件类型 (用于前端图标选择)
 * @author: haotangyuan
 */
public class EventType {
    public static final String QUEUE = "QUEUE";           // 排队中
    public static final String SCOPE = "SCOPE";           // 范围分析阶段
    public static final String SUPERVISOR = "SUPERVISOR"; // 研究规划阶段
    public static final String RESEARCH = "RESEARCH";     // 深入研究阶段
    public static final String SEARCH = "SEARCH";         // 搜索阶段
    public static final String REPORT = "REPORT";         // 报告生成阶段
    public static final String DIRECTION_CONFIRM = "DIRECTION_CONFIRM"; // 方向确认阶段
    public static final String ERROR = "ERROR";           // 错误事件
}
