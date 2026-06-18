"""Standardized error handling.

Every error response shares the ``ErrorResponse`` shape ``{"error": {...}}``.
Handlers translate FastAPI/Starlette exceptions into that shape so the contract
(and the generated SDK) has one consistent error type. A catch-all turns
unexpected exceptions into a 500 without leaking internals.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from silverfish_api.schemas import ErrorBody, ErrorDetail, ErrorResponse

HTTP_400_BAD_REQUEST = 400
HTTP_404_NOT_FOUND = 404
HTTP_409_CONFLICT = 409
HTTP_413_TOO_LARGE = 413
HTTP_422_VALIDATION = 422
HTTP_500_INTERNAL = 500
HTTP_503_UNAVAILABLE = 503

# Documented error responses, ready to spread into route decorators.
ERROR_500: dict[int | str, dict[str, object]] = {
    HTTP_500_INTERNAL: {"model": ErrorResponse, "description": "Internal server error"},
}
ERROR_404: dict[int | str, dict[str, object]] = {
    HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Resource not found"},
}
ERROR_422: dict[int | str, dict[str, object]] = {
    HTTP_422_VALIDATION: {"model": ErrorResponse, "description": "Validation error"},
}
ERROR_400: dict[int | str, dict[str, object]] = {
    HTTP_400_BAD_REQUEST: {"model": ErrorResponse, "description": "Bad request"},
}
ERROR_503: dict[int | str, dict[str, object]] = {
    HTTP_503_UNAVAILABLE: {"model": ErrorResponse, "description": "Service unavailable"},
}
ERROR_409: dict[int | str, dict[str, object]] = {
    HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "Conflict"},
}
ERROR_413: dict[int | str, dict[str, object]] = {
    HTTP_413_TOO_LARGE: {"model": ErrorResponse, "description": "Payload too large"},
}


def _render(
    status_code: int,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(error=ErrorBody(status=status_code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=payload.model_dump(exclude_none=True))


async def _handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return _render(exc.status_code, message)


async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        ErrorDetail(location=".".join(str(p) for p in error["loc"]), message=error["msg"])
        for error in exc.errors()
    ]
    return _render(HTTP_422_VALIDATION, "Validation error", details)


async def _handle_unexpected(_: Request, __: Exception) -> JSONResponse:
    # Deliberately generic: never leak exception internals to the client.
    return _render(HTTP_500_INTERNAL, "Internal server error")


def register_error_handlers(app: FastAPI) -> None:
    """Install the standardized exception handlers on *app*."""
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _handle_unexpected)
