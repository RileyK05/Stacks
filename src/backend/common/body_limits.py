"""Bound incoming bytes before JSON allocation or multipart file spooling."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from src.backend.common.companion_config import load_companion_policy
from src.backend.common.lifecycle_config import load_lifecycle_policy
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_LIMIT_EXCEEDED = "stacks.body_limit_exceeded"


def request_limit(scope: Scope) -> int:
    headers = Headers(scope=scope)
    if "multipart/form-data" not in headers.get("content-type", "").lower():
        return 64 * 1024 * 1024
    path = scope.get("path", "")
    policy = load_lifecycle_policy()
    if path.endswith("/courses/import"):
        limit = policy.max_import_bytes
    elif path.endswith("/sources"):
        limit = policy.max_raw_upload_bytes
    else:
        limit = load_companion_policy().max_upload_bytes
    return limit + 1024 * 1024  # Multipart boundary and small form fields.


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = request_limit(scope)
        headers = Headers(scope=scope)
        declared = headers.get("content-length", "")
        # A header of thousands of digits is rejected before int() ever sees
        # it: Python caps that conversion and would answer 500 (CR-14).
        if declared.isdecimal() and (len(declared) > 20 or int(declared) > limit):
            await JSONResponse(
                {"detail": "Request body exceeds the upload limit."}, 413
            )(scope, receive, send)
            return
        received = 0

        async def bounded_receive() -> Message:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > limit:
                scope[_LIMIT_EXCEEDED] = True
                detail = "Request body exceeds the upload limit."
                if "multipart/form-data" in headers.get("content-type", "").lower():
                    # Starlette closes its temporary files on MultiPartException.
                    raise MultiPartException(detail)
                raise HTTPException(413, detail)
            return message

        await self.app(scope, bounded_receive, send)


def install_body_limits(app: FastAPI) -> None:
    app.add_middleware(BodyLimitMiddleware)

    @app.exception_handler(HTTPException)
    async def limited_error(request: Request, error: HTTPException) -> Response:
        if request.scope.get(_LIMIT_EXCEEDED):
            return JSONResponse(
                {"detail": "Request body exceeds the upload limit."}, 413
            )
        return await http_exception_handler(request, error)
