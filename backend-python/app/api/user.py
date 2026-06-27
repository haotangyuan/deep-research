from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import current_user_id
from app.core.common import success
from app.domain.dto import LoginReq, RegisterReq
from app.application.services import user_service

router = APIRouter()


@router.post("/api/v1/user/register")
async def register(req: RegisterReq):
    return success((await user_service.register(req)).api_dump())


@router.post("/api/v1/user/login")
async def login(req: LoginReq):
    return success((await user_service.login(req)).api_dump())


@router.get("/api/v1/user/me")
async def me(user_id: int = Depends(current_user_id)):
    return success((await user_service.get_user_info(user_id)).api_dump())
