"""Errors as application/problem+json (requirements S13.8.3), each with an id that is also in
the log (S13.7.8). An error never carries a stack trace, SQL, a host path or a secret."""

import logging
import secrets
from dataclasses import dataclass, field

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("moolakata.errors")

PROBLEM = "application/problem+json"

TITLES = {
    400: "Bad request",
    401: "Not signed in",
    403: "Not allowed",
    404: "Not found",
    405: "Method not allowed",
    409: "Conflict",
    412: "Changed since you loaded it",
    413: "Too large",
    415: "Unsupported type",
    422: "Not accepted",
    429: "Too many requests",
    500: "Server error",
    503: "Not available yet",
}


@dataclass
class FieldError:
    field: str | None
    code: str
    message: str
    id: str | None = None  # the record, in a save's refusals (S13.8.11.4)


@dataclass
class Problem(Exception):
    """Raised anywhere in a request to answer with a problem document."""

    status: int
    code: str
    detail: str
    errors: list[FieldError] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
    error_id: str | None = None  # one already in the log with the detail behind it


def refuse(field_name: str | None, code: str, message: str, status: int = 422) -> Problem:
    """One refusal at one field: the UI shows it at that field (requirements R3.7)."""
    return Problem(status, code, message, [FieldError(field_name, code, message)])


def new_error_id() -> str:
    return "err_" + secrets.token_hex(6)


def problem_response(
    status: int,
    code: str,
    detail: str,
    errors=(),
    headers=None,
    extra=None,
    error_id: str | None = None,
) -> JSONResponse:
    error_id = error_id or new_error_id()
    # Every problem is in the log by its id, with its status and code, refusals included, so
    # an admin can find what a user saw (S13.7.8); never its detail, which may name a value.
    log.log(
        logging.WARNING if status >= 500 else logging.INFO,
        "problem %s %s %s",
        error_id,
        status,
        code,
    )
    body = {
        "type": f"https://moolakata.invalid/problems/{code}",
        "title": TITLES.get(status, "Error"),
        "status": status,
        "detail": detail,
        "code": code,
        "errorId": error_id,
        "errors": [_field_error(e) for e in errors],
    }
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, headers=headers or {}, media_type=PROBLEM)


def _field_error(e: FieldError) -> dict:
    out = {"field": e.field, "code": e.code, "message": e.message}
    if e.id is not None:
        out["id"] = e.id
    return out


def install(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def on_problem(request: Request, exc: Problem):
        return problem_response(
            exc.status, exc.code, exc.detail, exc.errors, exc.headers, exc.extra, exc.error_id
        )

    @app.exception_handler(RequestValidationError)
    async def on_validation(request: Request, exc: RequestValidationError):
        errors = []
        for e in exc.errors():
            loc = [str(x) for x in e.get("loc", ()) if x not in ("body", "query", "path")]
            code = "invalid-" + str(e.get("type", "value")).replace("_", "-")
            errors.append(FieldError(".".join(loc) or None, code, str(e.get("msg", "invalid"))))
        malformed = any(e.code in ("invalid-json-invalid",) for e in errors)
        status = 400 if malformed else 422
        return problem_response(status, "invalid-request", "Some fields were not accepted.", errors)

    @app.exception_handler(StarletteHTTPException)
    async def on_http(request: Request, exc: StarletteHTTPException):
        code = {404: "not-found", 405: "method-not-allowed"}.get(exc.status_code, "http-error")
        return problem_response(
            exc.status_code,
            code,
            TITLES.get(exc.status_code, "Error"),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def on_error(request: Request, exc: Exception):
        error_id = new_error_id()
        log.exception("unhandled error %s on %s %s", error_id, request.method, request.url.path)
        return problem_response(
            500,
            "server-error",
            "Something went wrong. An admin can find it in the log by its error id.",
            error_id=error_id,
        )
