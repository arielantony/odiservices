from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/session")
def session() -> JSONResponse:
    """Reached only with a valid Access token (the check is application-wide).

    It carries no data and no email. It lets a client, and the live check of
    BE-23, ask whether the session is alive.
    """
    return JSONResponse({"authenticated": True}, headers={"Cache-Control": "no-store"})
