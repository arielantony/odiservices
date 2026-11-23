"""POST /api/statements/upload: a card statement PDF sent by the person (BE-03).
The request is read in memory and parsed with python-multipart's low-level
parser, so no byte is spooled to disk (Starlette's form parser spools file parts
over 1 MB). The statement is created in `processing`, the PDF is stored as an
encrypted blob (BE-04), and the extraction runs in the background (run_extraction).
"""

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from server.access import AccessError
from server.db import Statement, User
from server.db.session import DATABASE_UNAVAILABLE, get_session
from server.extraction import ExtractionClient, get_extraction_client, run_extraction
from server.settings import Settings
from server.statements import StatementRefused, refusal_response
from server.uploads import UploadError, store_upload
from server.uploads_limits import check_processing_limit
from server.users import current_user, log_event

router = APIRouter()

# The multipart envelope is allowed on top of the PDF's own limit (spec 3.1).
ENVELOPE_SLACK = 64 * 1024
TIMEZONE = ZoneInfo("America/Sao_Paulo")

REFUSED_PAYLOAD_TOO_LARGE = (413, "payload_too_large", "O arquivo é maior que 10 MB.")
REFUSED_UNSUPPORTED_TYPE = (415, "unsupported_file_type", "Envie um arquivo PDF.")
REFUSED_INVALID_UPLOAD = (422, "invalid_upload", "O envio não tem um arquivo PDF.")
REFUSED_PDF_ENCRYPTED = (
    422,
    "pdf_encrypted",
    "O PDF está protegido por senha. Envie uma cópia sem senha.",
)
REFUSED_EXTRACTION_UNAVAILABLE = (
    503,
    "extraction_unavailable",
    "A classificação não está disponível agora. Tente de novo mais tarde.",
)


class Refused(Exception):
    """A refusal raised while the request is read. The route answers it."""

    def __init__(self, refusal: tuple[int, str, str]):
        super().__init__(refusal[1])
        self.refusal = refusal


def app_settings(request: Request) -> Settings:
    return request.app.state.settings


def upload_extractor(settings: Settings = Depends(app_settings)) -> ExtractionClient | None:
    """The extraction client of the route (tests override this dependency)."""
    return get_extraction_client(settings)


class _PdfPart:
    """Collects the parts of one multipart body, in memory, with the callbacks of
    python-multipart. Every part's data is kept in a bytearray."""

    def __init__(self, limit: int):
        self.limit = limit
        self.parts: list[dict] = []
        self.current: dict = {}
        self.field = bytearray()
        self.value = bytearray()

    def on_part_begin(self) -> None:
        self.current = {"headers": {}, "data": bytearray()}

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self.field += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self.value += data[start:end]

    def on_header_end(self) -> None:
        self.current["headers"][bytes(self.field).lower()] = bytes(self.value)
        self.field = bytearray()
        self.value = bytearray()

    def on_headers_finished(self) -> None:
        _, params = parse_options_header(self.current["headers"].get(b"content-disposition"))
        self.parts.append(
            {
                "name": params.get(b"name"),
                "content_type": self.current["headers"].get(b"content-type"),
                "data": self.current["data"],
            }
        )

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        buffer = self.current["data"]
        buffer += data[start:end]
        if len(buffer) > self.limit:
            raise Refused(REFUSED_PAYLOAD_TOO_LARGE)


def parse_pdf(body: bytes, content_type: str | None, limit: int) -> bytes:
    """The one PDF part of the body (spec 3.1, checks 4 to 6). Raises Refused."""
    media, params = parse_options_header(content_type)
    boundary = params.get(b"boundary")
    if media.lower() != b"multipart/form-data" or not boundary:
        raise Refused(REFUSED_INVALID_UPLOAD)

    collector = _PdfPart(limit)
    parser = MultipartParser(
        boundary,
        {
            "on_part_begin": collector.on_part_begin,
            "on_header_field": collector.on_header_field,
            "on_header_value": collector.on_header_value,
            "on_header_end": collector.on_header_end,
            "on_headers_finished": collector.on_headers_finished,
            "on_part_data": collector.on_part_data,
        },
    )
    try:
        parser.write(body)
        parser.finalize()
    except MultipartParseError:
        raise Refused(REFUSED_INVALID_UPLOAD) from None

    if len(collector.parts) != 1 or collector.parts[0]["name"] != b"file":
        raise Refused(REFUSED_INVALID_UPLOAD)
    part = collector.parts[0]
    media, _ = parse_options_header(part["content_type"])
    if media.lower() != b"application/pdf":
        raise Refused(REFUSED_UNSUPPORTED_TYPE)
    data = bytes(part["data"])
    if not data.startswith(b"%PDF-"):
        raise Refused(REFUSED_UNSUPPORTED_TYPE)
    if b"/Encrypt" in data:
        raise Refused(REFUSED_PDF_ENCRYPTED)
    return data


async def read_pdf(request: Request, limit: int) -> bytes:
    """The PDF of the request, read with a byte counter so a body without a
    Content-Length is bounded too (spec 3.1, check 3)."""
    cap = limit + ENVELOPE_SLACK
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            size = int(declared)
        except ValueError:
            raise Refused(REFUSED_INVALID_UPLOAD) from None
        if size > cap:
            raise Refused(REFUSED_PAYLOAD_TOO_LARGE)
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > cap:
            raise Refused(REFUSED_PAYLOAD_TOO_LARGE)
    return parse_pdf(bytes(body), request.headers.get("content-type"), limit)


def statement_name(now: datetime) -> str:
    return f"Fatura enviada em {now.astimezone(TIMEZONE):%d/%m/%Y}"


def accept_upload(session: Session, user: User, pdf: bytes, settings: Settings) -> UUID:
    """The limit, then the statement row and its blob in one transaction (spec
    3.1, checks 7 and 8). Plain def: runs in the threadpool."""
    check_processing_limit(session, user, settings=settings)
    try:
        statement = Statement(
            user_id=user.id,
            name=statement_name(datetime.now(TIMEZONE)),
            status="processing",
        )
        session.add(statement)
        session.flush()
        statement_id = statement.id
        store_upload(session, statement_id, pdf, settings=settings)
        session.commit()
    except UploadError as exc:
        session.rollback()
        if exc.code == "database_unavailable":
            raise AccessError(*DATABASE_UNAVAILABLE) from None
        raise StatementRefused(REFUSED_EXTRACTION_UNAVAILABLE) from None
    except DBAPIError as exc:
        session.rollback()
        if isinstance(exc, IntegrityError):
            raise
        # The class name only: a driver message can hold the host.
        log_event("WARNING", "database_error", error=type(exc).__name__)
        raise AccessError(*DATABASE_UNAVAILABLE) from None
    return statement_id


def refuse(refusal: tuple[int, str, str]) -> JSONResponse:
    log_event("INFO", "statement_upload_refused", code=refusal[1])
    return refusal_response(refusal)


@router.post("/api/statements/upload", status_code=202)
async def upload_statement(
    request: Request,
    background: BackgroundTasks,
    settings: Settings = Depends(app_settings),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    client: ExtractionClient | None = Depends(upload_extractor),
) -> JSONResponse:
    # Check 2: both keys are needed. Nothing is read and no row is made without them.
    if client is None or settings.upload_encryption_key is None:
        return refuse(REFUSED_EXTRACTION_UNAVAILABLE)
    try:
        pdf = await read_pdf(request, settings.statement_max_bytes)
    except Refused as exc:
        return refuse(exc.refusal)
    try:
        statement_id = await run_in_threadpool(accept_upload, session, user, pdf, settings)
    except StatementRefused as exc:
        return refuse(exc.refusal)
    log_event("INFO", "statement_upload_accepted", statement_id=str(statement_id))
    background.add_task(
        run_extraction, request.app.state.engine, statement_id, client, settings.anthropic_model
    )
    return JSONResponse(
        {"id": str(statement_id), "status": "processing"},
        status_code=202,
        headers={"Cache-Control": "no-store"},
    )
