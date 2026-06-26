package dev.haotangyuan.researcher.application.prompt;

import org.springframework.stereotype.Component;

/**
 * @author: haotangyuan
 */
@Component
public class SearchPrompts {
    public final static String SUMMARIZE_WEBPAGE_PROMPT = """
            你是一名信息提取专员，负责从网页内容中提取关键信息，生成结构化摘要供研究使用。

            <Input>
            <webpage_content>
            {webpage_content}
            </webpage_content>
            </Input>

            <Extraction Guidelines>
            **必须保留的信息**：
            - 数据：数字、统计、百分比、金额
            - 时间：日期、时间点、时间范围
            - 人物：姓名、职位、所属机构
            - 地点：城市、国家、具体位置
            - 引用：专家观点、官方声明
            - 核心事实：主要论点、关键发现、重要结论

            **内容类型处理策略**：
            - 新闻：5W1H（何时、何地、何人、何事、为何、如何）
            - 学术：研究方法、样本量、主要发现、结论
            - 产品：规格、价格、核心功能、差异化特点
            - 观点：主要论点、论据、立场
            - 教程：步骤、要点、注意事项

            **压缩原则**：
            - 目标：原文的 20-30%
            - 保留事实密度高的内容
            - 删除冗余描述和重复信息
            - 保持关键数字和引用的完整性
            </Extraction Guidelines>

            <Output Schema>
            严格按以下 JSON 格式输出，不包含 Markdown 代码块：

            {
              "summary": "结构化摘要，包含所有关键信息",
              "key_excerpts": "重要引用1 | 重要引用2 | 重要引用3"
            }

            **字段说明**：
            - summary: 完整摘要，可使用分段或项目符号组织
            - key_excerpts: 原文中的重要引用，用 | 分隔，最多5条
            </Output Schema>

            <Examples>
            **示例1 - 新闻文章**：
            {
              "summary": "2024年3月15日，苹果公司在春季发布会上推出M4芯片MacBook Pro。新机型搭载18核GPU，性能较M3提升40%，续航达22小时。起售价14999元（14英寸）和18999元（16英寸），3月22日开售。",
              "key_excerpts": "M4是我们迄今最强大的芯片，苹果CEO Tim Cook表示 | 新款MacBook Pro将重新定义专业创作者的工作方式，硬件副总裁John Ternus介绍"
            }

            **示例2 - 研究报告**：
            {
              "summary": "斯坦福大学2024年AI指数报告显示：（1）GPT-4等模型在多项基准测试中超越人类表现；（2）AI领域投资同比增长35%达673亿美元；（3）美国AI论文数量首次被中国超越；（4）68%的企业已部署生成式AI应用。",
              "key_excerpts": "AI能力增长速度远超预期，我们正处于技术拐点，报告主编Yolanda Gil指出 | 监管框架的缺失是当前最大风险，斯坦福HAI主任Fei-Fei Li警告"
            }
            </Examples>

            <Quality Rules>
            【强制】输出必须是有效的 JSON
            【强制】不得遗漏关键数据和人物引用
            【强制】保持原文引用的准确性，不改写
            </Quality Rules>

            今天是 {date}。不要询问用户当前年份或日期。
            """;
}
