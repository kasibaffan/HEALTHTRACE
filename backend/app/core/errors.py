import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("healthtrace.errors")


class AppError(Exception):
    """Expected, user-presentable error."""

    def __init__(self, status_code: int, message: str, code: str = "error"):
        self.status_code, self.message, self.code = status_code, message, code


def not_found(what: str = "Resource") -> AppError:
    return AppError(404, f"{what} not found.", "not_found")


def forbidden(message: str = "You do not have permission to do that.") -> AppError:
    return AppError(403, message, "forbidden")


def conflict(message: str) -> AppError:
    return AppError(409, message, "conflict")


def _body(request: Request, status: int, message: str, code: str, extra: dict | None = None):
    payload = {"detail": message, "code": code, "requestId": getattr(request.state, "request_id", None)}
    if extra:
        payload.update(extra)
    return JSONResponse(status_code=status, content=payload)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return _body(request, exc.status_code, exc.message, exc.code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        return _body(request, exc.status_code, str(exc.detail), "http_error")

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        fields = {".".join(str(p) for p in e["loc"][1:]): e["msg"] for e in exc.errors()}
        return _body(request, 422, "Please check the highlighted fields.", "validation_error", {"fields": fields})

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        log.exception("unhandled error", extra={"request_id": getattr(request.state, "request_id", None)})
        return _body(request, 500, "Something went wrong on our side. Please try again.", "internal_error")
