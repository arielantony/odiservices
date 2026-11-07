from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from server.db.models import User
from server.users import current_user

router = APIRouter()


@router.get("/api/me")
def me(user: User = Depends(current_user)) -> JSONResponse:
    """The person behind the token. The first call after a login creates the
    row (BE-24). It answers the id only: no email and no subject."""
    return JSONResponse({"id": str(user.id)}, headers={"Cache-Control": "no-store"})
