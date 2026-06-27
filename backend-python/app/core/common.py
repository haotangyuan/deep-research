from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


class AppError(RuntimeError):
    pass


class ResearchError(AppError):
    pass


class UserError(AppError):
    pass


class ModelError(AppError):
    pass


class WorkflowError(AppError):
    pass


def success(data: Any, message: str = "success") -> dict[str, Any]:
    return {"code": 0, "message": message, "data": data}


def failure(message: str, code: int = -1) -> dict[str, Any]:
    return {"code": code, "message": message, "data": None}


def failure_response(message: str, code: int = -1) -> JSONResponse:
    return JSONResponse(failure(message, code))
