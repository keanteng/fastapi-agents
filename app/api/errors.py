from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.runs.models import ErrorBody

logger = logging.getLogger(__name__)


class AppError(Exception):
    """An HTTP error carrying the machine-readable error-envelope fields."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details=None,
        run_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.run_id = run_id


def register_error_handlers(app: FastAPI) -> None:
    """Wire the error-envelope handlers (incl. the FastAPI 422 override)."""

    @app.exception_handler(AppError)
    async def _app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        body = ErrorBody(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            run_id=exc.run_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": body.model_dump(mode="json")},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        body = ErrorBody(
            code="validation_error",
            message="request validation failed",
            details=jsonable_encoder(exc.errors()),
            run_id=None,
        )
        return JSONResponse(
            status_code=422,
            content={"error": body.model_dump(mode="json")},
        )

    @app.exception_handler(Exception)
    async def _internal_error_handler(
        _request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("unhandled error: %s", exc)
        body = ErrorBody(
            code="internal_error",
            message="internal server error",
            details=None,
            run_id=None,
        )
        return JSONResponse(
            status_code=500,
            content={"error": body.model_dump(mode="json")},
        )
