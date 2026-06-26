from __future__ import annotations

from fastapi import APIRouter, Depends, Header

from ..auth import current_user_id
from ..common import success
from ..dto import ConfirmDirectionReq, SendMessageReq
from ..services import research_service
from ..sse import sse_hub

router = APIRouter()


@router.get("/api/v1/research/create")
async def create_research(num: int, user_id: int = Depends(current_user_id)):
    return success((await research_service.create_research(user_id, num)).api_dump())


@router.get("/api/v1/research/list")
async def research_list(user_id: int = Depends(current_user_id)):
    return success([item.api_dump() for item in await research_service.get_research_list(user_id)])


@router.get("/api/v1/research/sse")
async def stream(
    user_id: int = Depends(current_user_id),
    research_id: str = Header(alias="X-Research-Id"),
    client_id: str = Header(alias="X-Client-Id"),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    return await sse_hub.connect(user_id, research_id, client_id, last_event_id)


@router.get("/api/v1/research/{research_id}")
async def get_research_status(research_id: str, user_id: int = Depends(current_user_id)):
    return success((await research_service.get_research_status(user_id, research_id)).api_dump())


@router.get("/api/v1/research/{research_id}/messages")
async def get_research_messages(research_id: str, user_id: int = Depends(current_user_id)):
    return success((await research_service.get_research_messages(user_id, research_id)).api_dump())


@router.post("/api/v1/research/{research_id}/messages")
async def send_message(research_id: str, req: SendMessageReq, user_id: int = Depends(current_user_id)):
    return success((await research_service.send_message(user_id, research_id, req)).api_dump())


@router.post("/api/v1/research/{research_id}/direction-action")
async def confirm_direction(research_id: str, req: ConfirmDirectionReq, user_id: int = Depends(current_user_id)):
    return success((await research_service.confirm_direction(user_id, research_id, req)).api_dump())


@router.post("/api/v1/research/{research_id}/cancel")
async def cancel_research(research_id: str, user_id: int = Depends(current_user_id)):
    return success((await research_service.cancel_research(user_id, research_id)).api_dump())
