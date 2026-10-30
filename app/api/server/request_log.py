import json
import re
import sys
import time
import traceback as traceback_module
import uuid
from datetime import datetime, timezone

from starlette.datastructures import MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# A Cf-Ray value is hex plus an airport code. Anything else is not trusted
# as an id, so a client can't put arbitrary text in the log.
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def level_for(status: int) -> str:
    if status >= 500:
        return "ERROR"
    if status >= 400:
        return "WARNING"
    return "INFO"


def request_id_from(scope: Scope) -> str:
    for name, value in scope["headers"]:
        if name == b"cf-ray":
            candidate = value.decode("latin-1")
            if SAFE_REQUEST_ID.match(candidate):
                return candidate
    return str(uuid.uuid4())


class RequestLogMiddleware:
    """Writes one JSON line per request, with no personal data (BE-21).

    Only the method, the matched route template, the status and the timing
    are logged. Query strings, headers, bodies and client addresses never
    reach this module's output.
    """

    def __init__(self, app: ASGIApp, *, traceback: bool = False):
        self.app = app
        self.traceback = traceback

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = request_id_from(scope)
        started = time.perf_counter()
        status = 500
        response_started = False
        error: BaseException | None = None

        async def send_with_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                MutableHeaders(scope=message)["X-Request-Id"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            error = exc
            if response_started:
                self.write(scope, request_id, status, started, error)
                raise
            response = PlainTextResponse(
                "Internal Server Error",
                status_code=500,
                headers={"X-Request-Id": request_id},
            )
            await response(scope, receive, send)
            status = 500

        self.write(scope, request_id, status, started, error)

    def write(
        self,
        scope: Scope,
        request_id: str,
        status: int,
        started: float,
        error: BaseException | None,
    ) -> None:
        level = "ERROR" if error else level_for(status)
        route = scope.get("route")
        # A static file is logged by its path (BE-01 spec 3.1): a file path
        # carries no ids. Every other unmatched request stays "unmatched".
        logged_route = scope.get("log_route") or getattr(route, "path", None)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": level,
            "event": "request",
            "request_id": request_id,
            "method": scope["method"],
            # The raw path can carry ids; with no matched route, log none.
            "route": logged_route or "unmatched",
            "status": status,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        if error:
            entry["exception"] = type(error).__name__
            if self.traceback:
                entry["traceback"] = "".join(
                    traceback_module.format_exception(error)
                )
        sys.stdout.write(json.dumps(entry, ensure_ascii=False) + "\n")
        sys.stdout.flush()
