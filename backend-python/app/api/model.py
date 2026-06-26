from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import current_user_id
from ..common import success
from ..dto import AddModelReq
from ..services import model_service

router = APIRouter()


@router.get("/api/v1/models")
async def get_available_models(user_id: int = Depends(current_user_id)):
    return success([item.api_dump() for item in await model_service.get_available_models(user_id)])


@router.post("/api/v1/models")
async def add_custom_model(req: AddModelReq, user_id: int = Depends(current_user_id)):
    return success(await model_service.add_custom_model(user_id, req))


@router.delete("/api/v1/models/{model_id}")
async def delete_custom_model(model_id: str, user_id: int = Depends(current_user_id)):
    await model_service.delete_custom_model(user_id, model_id)
    return success("删除成功")
