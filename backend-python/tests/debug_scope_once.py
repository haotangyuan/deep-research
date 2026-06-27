from __future__ import annotations

import asyncio

import pymysql

from app.infrastructure.llm import AgentScopeChatClient
from app.domain.models import Model
from app.application.prompts import CLARIFY_WITH_USER_INSTRUCTIONS
from app.domain.runtime import ResearchAgentRequest, ResearchMessage
from app.core.timeutil import today_str


def load_mimo_model() -> Model:
    conn = pymysql.connect(
        host="127.0.0.1",
        port=3306,
        user="root",
        password="12345678",
        database="db_deep_research",
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id,type,user_id,name,model,base_url,api_key,create_time,update_time
                FROM model
                WHERE name LIKE '%%mimo%%' OR model LIKE '%%mimo%%'
                LIMIT 1
                """,
            )
            row = cur.fetchone()
            return Model(
                id=row[0],
                type=row[1],
                user_id=row[2],
                name=row[3],
                model=row[4],
                base_url=row[5],
                api_key=row[6],
                create_time=row[7],
                update_time=row[8],
            )
    finally:
        conn.close()


async def main() -> None:
    client = AgentScopeChatClient(load_mimo_model())
    prompt = CLARIFY_WITH_USER_INSTRUCTIONS.format(
        messages="USER: 请用中文简要研究 FastAPI 与 Spring Boot 在小型项目中的差异，最终报告控制在 300 字以内。",
        date=today_str(),
    )
    response = await client.run_agent(
        ResearchAgentRequest.text_only(
            "ScopeAgent",
            "",
            [ResearchMessage.user(prompt)],
            {"research.id": "debug"},
        ),
    )
    print("usage", response.token_usage)
    print("TEXT_START")
    print(response.ai_message.text)
    print("TEXT_END")


if __name__ == "__main__":
    asyncio.run(main())
