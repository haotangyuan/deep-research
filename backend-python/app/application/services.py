from __future__ import annotations

import uuid

from sqlalchemy import and_, desc, or_, select, text

from app.core.auth import generate_token
from app.infrastructure.cache import get_cache
from app.core.common import ModelError, ResearchError, UserError
from app.core.config import get_settings
from app.core.constants import EventType, WorkflowStatus
from app.infrastructure.db import SessionLocal
from app.infrastructure.events import event_publisher
from app.domain.dto import (
    AddModelReq,
    ConfirmDirectionReq,
    CreateResearchResp,
    LoginReq,
    LoginResp,
    ModelResp,
    RegisterReq,
    ResearchMessageResp,
    ResearchStatusResp,
    SendMessageReq,
    SendMessageResp,
    UserInfoResp,
)
from app.infrastructure.llm import model_handler
from app.domain.models import ChatMessage, Model, ResearchSession, User
from app.application.pipeline import agent_pipeline
from app.domain.runtime import ResearchMessage
from app.domain.state import BudgetSnapshot, DeepResearchState, TraceMetadataModel
from app.core.timeutil import now_local


AVATAR_URL_TEMPLATE = "https://api.dicebear.com/9.x/pixel-art/svg?seed={}"


class UserService:
    async def register(self, req: RegisterReq) -> LoginResp:
        async with SessionLocal() as session:
            existing = await session.scalar(select(User).where(User.username == req.username))
            if existing is not None:
                raise UserError("用户名已存在")
            user = User(
                username=req.username,
                password=req.password,
                avatar_url=AVATAR_URL_TEMPLATE.format(req.username),
                create_time=now_local(),
                update_time=now_local(),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return LoginResp(token=generate_token(user.id))

    async def login(self, req: LoginReq) -> LoginResp:
        async with SessionLocal() as session:
            user = await session.scalar(select(User).where(User.username == req.username))
            if user is None:
                raise UserError("用户不存在")
            if user.password is None or user.password != req.password:
                raise UserError("密码错误")
            return LoginResp(token=generate_token(user.id))

    async def get_user_info(self, user_id: int) -> UserInfoResp:
        async with SessionLocal() as session:
            user = await session.get(User, user_id)
            if user is None:
                raise UserError("用户不存在")
            return UserInfoResp(avatar_url=user.avatar_url)


class ModelService:
    async def get_available_models(self, user_id: int) -> list[ModelResp]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(Model)
                .where(or_(Model.type == "GLOBAL", and_(Model.type == "USER", Model.user_id == user_id)))
                .order_by(Model.type.asc(), desc(Model.create_time)),
            )
            return [self._to_resp(model) for model in result.scalars()]

    async def add_custom_model(self, user_id: int, req: AddModelReq) -> str:
        if not req.api_key or not req.base_url or not req.model:
            raise ModelError("模型信息不完整")
        async with SessionLocal() as session:
            model = Model(
                id=uuid.uuid4().hex,
                type="USER",
                user_id=user_id,
                name=req.name or req.model,
                model=req.model,
                base_url=req.base_url,
                api_key=req.api_key,
                create_time=now_local(),
                update_time=now_local(),
            )
            session.add(model)
            await session.commit()
            return model.id

    async def delete_custom_model(self, user_id: int, model_id: str) -> None:
        async with SessionLocal() as session:
            model = await session.get(Model, model_id)
            if model is None:
                raise ModelError("模型不存在")
            if model.type != "USER" or model.user_id != user_id:
                raise ModelError("无权删除此模型")
            active_usage = await session.scalar(
                select(ResearchSession)
                .where(ResearchSession.model_id == model_id, ResearchSession.status.not_in(["COMPLETED", "FAILED"]))
                .limit(1),
            )
            if active_usage is not None:
                raise ModelError("模型正在使用中，无法删除")
            await session.delete(model)
            await session.commit()

    async def get_model_by_id(self, user_id: int, model_id: str) -> Model:
        async with SessionLocal() as session:
            model = await session.get(Model, model_id)
            if model is None:
                raise ModelError("模型不存在")
            if model.type == "GLOBAL" or (model.type == "USER" and model.user_id == user_id):
                return model
            raise ModelError("无权访问此模型")

    @staticmethod
    def _to_resp(model: Model) -> ModelResp:
        return ModelResp(
            id=model.id,
            type=model.type,
            name=model.name,
            model=model.model,
            base_url=model.base_url,
        )


class ResearchService:
    def __init__(self, model_service: ModelService) -> None:
        self.model_service = model_service

    async def create_research(self, user_id: int, num: int) -> CreateResearchResp:
        async with SessionLocal() as session:
            result = await session.execute(
                select(ResearchSession)
                .where(ResearchSession.user_id == user_id, ResearchSession.status == WorkflowStatus.NEW),
            )
            sessions = list(result.scalars())
            old_num = len(sessions)
            if num > old_num:
                for _ in range(num - old_num):
                    session_obj = ResearchSession(
                        id=uuid.uuid4().hex,
                        user_id=user_id,
                        status=WorkflowStatus.NEW,
                        create_time=now_local(),
                        update_time=now_local(),
                        total_input_tokens=0,
                        total_output_tokens=0,
                    )
                    session.add(session_obj)
                    sessions.append(session_obj)
                await session.commit()
            research_ids = [
                item.id
                for item in sorted(sessions, key=lambda value: value.create_time or now_local())[:num]
            ]
        for research_id in research_ids:
            await get_cache().cache_research_ownership(research_id, user_id)
        return CreateResearchResp(research_ids=research_ids)

    async def get_research_list(self, user_id: int) -> list[ResearchStatusResp]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(ResearchSession)
                .where(ResearchSession.user_id == user_id)
                .order_by(desc(ResearchSession.update_time)),
            )
            return [self._status_resp(item) for item in result.scalars()]

    async def get_research_status(self, user_id: int, research_id: str) -> ResearchStatusResp:
        if not await get_cache().verify_research_ownership(research_id, user_id):
            raise ResearchError("研究任务不存在或无权限访问")
        async with SessionLocal() as session:
            session_obj = await session.get(ResearchSession, research_id)
            if session_obj is None:
                raise ResearchError("研究任务不存在")
            return self._status_resp(session_obj)

    async def get_research_messages(self, user_id: int, research_id: str) -> ResearchMessageResp:
        if not await get_cache().verify_research_ownership(research_id, user_id):
            raise ResearchError("研究任务不存在或无权限访问")
        async with SessionLocal() as session:
            session_obj = await session.get(ResearchSession, research_id)
            if session_obj is None:
                raise ResearchError("研究任务不存在")
        timeline = await get_cache().get_timeline(research_id, 0)
        messages = [item.message for item in timeline if item.kind == "message" and item.message is not None]
        events = [item.event for item in timeline if item.kind == "event" and item.event is not None]
        return ResearchMessageResp(
            id=session_obj.id,
            status=session_obj.status,
            title=session_obj.title,
            model_id=session_obj.model_id,
            budget=session_obj.budget,
            messages=messages,
            events=events,
            start_time=session_obj.start_time,
            update_time=session_obj.update_time,
            complete_time=session_obj.complete_time,
            total_input_tokens=session_obj.total_input_tokens,
            total_output_tokens=session_obj.total_output_tokens,
        )

    async def send_message(self, user_id: int, research_id: str, req: SendMessageReq) -> SendMessageResp:
        affected = await self._cas_update_to_queue(research_id, user_id)
        if affected == 0:
            raise ResearchError("启动研究异常")
        async with SessionLocal() as session:
            session_obj = await session.get(ResearchSession, research_id)
            if session_obj is None:
                raise ResearchError("研究不存在")
            if session_obj.user_id != user_id:
                raise ResearchError("无权访问此研究")
            model_id = session_obj.model_id
            budget = session_obj.budget
        if model_id is None:
            if not req.model_id:
                raise ResearchError("模型不应为空")
            model_id = req.model_id
            title = req.content[:20]
            budget = req.budget or "HIGH"
            await self._set_info_if_null(research_id, model_id, budget, title)
        model = await self.model_service.get_model_by_id(user_id, model_id)
        model_handler.add_model(research_id, model)
        budget_name = (budget or "HIGH").upper()
        budget_level = get_settings().budget_levels().get(budget_name) or get_settings().budget_levels()["HIGH"]
        hitl_mode = req.hitl_mode or "DIRECTION_ONLY"
        await get_cache().save_message(research_id, "user", req.content)
        db_messages = await self._load_db_messages(research_id)
        state = DeepResearchState(
            research_id=research_id,
            chat_history=db_messages,
            status=WorkflowStatus.QUEUE,
            trace_metadata_model=TraceMetadataModel(
                research_id=research_id,
                user_id=user_id,
                model_id=model_id,
                budget_level=budget_name,
                agent_framework=get_settings().research_agent_framework,
            ),
            budget=BudgetSnapshot(
                max_conduct_count=budget_level.max_conduct_count,
                max_search_count=budget_level.max_search_count,
                max_concurrent_units=budget_level.max_concurrent_units,
            ),
            budget_name=budget_name,
            supervisor_notes=[],
            researcher_notes=[],
            search_results={},
            search_notes=[],
            hitl_mode=hitl_mode,
        )
        await agent_pipeline.run(state)
        return SendMessageResp(id=research_id, content="已接受任务")

    async def confirm_direction(self, user_id: int, research_id: str, req: ConfirmDirectionReq) -> SendMessageResp:
        affected = await self._cas_confirm_direction(research_id, user_id)
        if affected == 0:
            raise ResearchError("确认操作失败，当前状态不允许确认")
        data = await get_cache().load_checkpoint(research_id)
        if data is None:
            raise ResearchError("会话已过期，请重新发起研究")
        state = DeepResearchState.model_validate(data)
        async with SessionLocal() as session:
            session_obj = await session.get(ResearchSession, research_id)
            if session_obj is None:
                raise ResearchError("研究不存在")
            model_id = session_obj.model_id
        model = await self.model_service.get_model_by_id(user_id, model_id)
        model_handler.add_model(research_id, model)
        if req.action == "APPROVE":
            await get_cache().save_message(research_id, "user", "确认研究方向，开始执行研究")
            state.skip_scope_phase = True
            state.status = WorkflowStatus.QUEUE
            content = "研究方向已确认，开始执行研究"
        else:
            msg = "修改意见: " + req.feedback if req.feedback else "请重新调整研究方向"
            await get_cache().save_message(research_id, "user", msg)
            state.chat_history.append(ResearchMessage.user(msg))
            state.skip_scope_phase = False
            state.hitl_feedback = req.feedback
            state.status = WorkflowStatus.QUEUE
            state.research_brief = None
            content = "已收到修改意见，重新分析研究方向"
        await agent_pipeline.run(state)
        return SendMessageResp(id=research_id, content=content)

    async def cancel_research(self, user_id: int, research_id: str) -> SendMessageResp:
        async with SessionLocal() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE research_session
                    SET status = 'CANCELLED', complete_time = NOW(), update_time = NOW()
                    WHERE id = :id AND user_id = :user_id
                      AND status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')
                    """,
                ),
                {"id": research_id, "user_id": user_id},
            )
            await session.commit()
            if result.rowcount == 0:
                raise ResearchError("取消失败，研究已完成或不存在")
        await event_publisher.publish_event(research_id, EventType.ERROR, "研究已取消", None)
        await event_publisher.publish_message(research_id, "user", "用户取消了本次研究")
        await event_publisher.publish_message(research_id, "assistant", "研究已取消")
        return SendMessageResp(id=research_id, content="研究已取消")

    async def _load_db_messages(self, research_id: str) -> list[ResearchMessage]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(ChatMessage)
                .where(ChatMessage.research_id == research_id)
                .order_by(ChatMessage.sequence_no.asc()),
            )
            messages: list[ResearchMessage] = []
            for item in result.scalars():
                if item.role == "user":
                    messages.append(ResearchMessage.user(item.content))
                else:
                    messages.append(ResearchMessage.assistant(item.content))
            return messages

    async def _cas_update_to_queue(self, research_id: str, user_id: int) -> int:
        async with SessionLocal() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE research_session
                    SET status = 'QUEUE', update_time = NOW()
                    WHERE id = :id AND user_id = :user_id
                      AND status IN ('NEW', 'NEED_CLARIFICATION', 'AWAITING_DIRECTION_CONFIRM', 'CANCELLED')
                    """,
                ),
                {"id": research_id, "user_id": user_id},
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def _cas_confirm_direction(self, research_id: str, user_id: int) -> int:
        async with SessionLocal() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE research_session
                    SET status = 'QUEUE', update_time = NOW()
                    WHERE id = :id AND user_id = :user_id
                      AND status = 'AWAITING_DIRECTION_CONFIRM'
                    """,
                ),
                {"id": research_id, "user_id": user_id},
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def _set_info_if_null(self, research_id: str, model_id: str, budget: str, title: str) -> None:
        async with SessionLocal() as session:
            await session.execute(
                text(
                    """
                    UPDATE research_session
                    SET update_time = NOW(), model_id = :model_id, budget = :budget, title = :title
                    WHERE id = :id AND model_id IS NULL
                    """,
                ),
                {"id": research_id, "model_id": model_id, "budget": budget, "title": title},
            )
            await session.commit()

    @staticmethod
    def _status_resp(session_obj: ResearchSession) -> ResearchStatusResp:
        return ResearchStatusResp(
            id=session_obj.id,
            status=session_obj.status,
            title=session_obj.title,
            model_id=session_obj.model_id,
            budget=session_obj.budget,
            start_time=session_obj.start_time,
            complete_time=session_obj.complete_time,
            total_input_tokens=session_obj.total_input_tokens,
            total_output_tokens=session_obj.total_output_tokens,
        )


user_service = UserService()
model_service = ModelService()
research_service = ResearchService(model_service)
