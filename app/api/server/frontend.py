from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

import server

# Resolved from the package location, never from the working directory.
DEFAULT_FRONTEND_DIR = Path(server.__file__).resolve().parents[2] / "web" / "dist"

NOT_BUILT = "Frontend não compilado. Use `make dev` ou `make build-web`."
NO_CACHE = {"Cache-Control": "no-cache"}
IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


def not_found_json() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "not_found", "message": "Recurso não encontrado."}},
        status_code=404,
    )


def install_frontend(app: FastAPI, frontend_dir: Path | None, env: str) -> None:
    """Serve the built React app with an SPA fallback (BE-01 spec 3.1, 3.2).

    Must be called after the API routers, so nothing shadows a route.
    """
    dist = (frontend_dir or DEFAULT_FRONTEND_DIR).resolve()
    built = (dist / "index.html").is_file()
    if not built and env == "prod":
        raise RuntimeError(
            f"Frontend build not found at {dist}. Run `make build-web` first."
        )

    @app.api_route(
        "/api/{rest:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        include_in_schema=False,
    )
    def unknown_api(rest: str, request: Request) -> JSONResponse:
        request.scope["log_route"] = "unmatched"
        return not_found_json()

    def file_in_dist(relative: str) -> Path | None:
        try:
            candidate = (dist / relative).resolve()
            if candidate.is_relative_to(dist) and candidate.is_file():
                return candidate
        except (ValueError, OSError):
            pass
        return None

    @app.api_route("/{path:path}", methods=["GET"], include_in_schema=False)
    def frontend(path: str, request: Request) -> Response:
        # Overridden below for a real file; a client route can carry ids.
        request.scope["log_route"] = "unmatched"
        if not built:
            return PlainTextResponse(NOT_BUILT, status_code=503)

        found = file_in_dist(path) if path else None
        if found:
            # A file path carries no ids, so it is logged as is (BE-21).
            request.scope["log_route"] = "/" + found.relative_to(dist).as_posix()
            if path.startswith("assets/"):
                return FileResponse(found, headers=IMMUTABLE)
            if found.name == "index.html":
                return FileResponse(found, headers=NO_CACHE)
            return FileResponse(found)

        last_segment = path.rsplit("/", 1)[-1]
        if path.startswith("assets/") or "." in last_segment:
            return PlainTextResponse("Not Found", status_code=404)
        return FileResponse(dist / "index.html", headers=NO_CACHE)
