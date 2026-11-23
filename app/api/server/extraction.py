"""The extraction of a statement PDF (BE-03): the client seam, the real Anthropic
client, the parsing of the model's answer, and the background job that stores
the lines. The PDF is sent once, in memory, and its bytes are dropped after the
call. No message carries a value from the PDF or from the model's answer.
"""

import base64
import json
import time
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from uuid import UUID

import anthropic
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from server.db import Category, Statement
from server.settings import Settings
from server.statements import (
    StatementPayload,
    StatementRefused,
    check_payload,
    set_status,
    store_lines,
)
from server.uploads import UploadError, load_upload, wipe_upload
from server.users import log_event

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "prompt-pdf.md"
MAX_TOKENS = 64000
REQUEST_TIMEOUT = 600

# The failure code of a blob that cannot be used (BE-07, spec 3.4): the file is
# gone, unreadable or cannot be opened with the key.
UPLOAD_NOT_AVAILABLE = "upload_not_available"


class ExtractionError(Exception):
    """A failed extraction. `code` is one of the failure codes of BE-07; `cause`
    is the class name of the exception behind it, for the log only."""

    def __init__(self, code: str, cause: str = "none"):
        super().__init__(code)
        self.code = code
        self.cause = cause


class ExtractionClient(Protocol):
    def extract(self, pdf: bytes, categories: list[str]) -> str: ...


def build_schema(categories: list[str]) -> dict:
    """The JSON schema of the answer (ask_pdf.py), with the categories of the table
    as the enum of `categoria` (spec 6, question 5)."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["total_lanc_atuais", "lancamentos"],
        "properties": {
            "total_lanc_atuais": {"type": "number"},
            "lancamentos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "id", "secao", "data", "descricao", "valor", "categoria", "duvida",
                    ],
                    "properties": {
                        "id": {"type": "integer"},
                        "secao": {
                            "type": "string",
                            "enum": ["compras", "internacional", "produtos"],
                        },
                        "data": {"type": "string"},
                        "descricao": {"type": "string"},
                        "valor": {"type": "number"},
                        "categoria": {"type": "string", "enum": categories},
                        "duvida": {"type": "boolean"},
                    },
                },
            },
        },
    }


@lru_cache
def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


class AnthropicExtractor:
    """The real client. The key is passed in code and never printed."""

    def __init__(self, api_key: str, model: str, timeout: float = REQUEST_TIMEOUT):
        self._model = model
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)

    def extract(self, pdf: bytes, categories: list[str]) -> str:
        content = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(pdf).decode("ascii"),
                },
            },
            {"type": "text", "text": load_prompt()},
        ]
        try:
            with self._client.messages.stream(
                model=self._model,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": content}],
                output_config={
                    "format": {"type": "json_schema", "schema": build_schema(categories)}
                },
            ) as stream:
                message = stream.get_final_message()
        # APITimeoutError is a subclass of APIConnectionError: it is named first.
        except anthropic.APITimeoutError as exc:
            raise ExtractionError("extraction_timeout", type(exc).__name__) from None
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
            raise ExtractionError("extraction_unavailable", type(exc).__name__) from None

        if message.stop_reason == "refusal":
            raise ExtractionError("extraction_refused")
        if message.stop_reason == "max_tokens":
            raise ExtractionError("extraction_truncated")
        text = next((block.text for block in message.content if block.type == "text"), None)
        if text is None:
            raise ExtractionError("extraction_invalid")
        return text


def parse_extraction(text: str, name: str) -> StatementPayload:
    """The model's answer as a StatementPayload (BE-05), with the statement's name.
    Numbers are Decimal (parse_float). Any failure is extraction_invalid, and the
    message of the failure is not kept."""
    try:
        data = json.loads(text, parse_float=Decimal)
    except (ValueError, RecursionError):
        raise ExtractionError("extraction_invalid") from None
    if not isinstance(data, dict):
        raise ExtractionError("extraction_invalid")
    data["name"] = name
    try:
        return StatementPayload.model_validate(data)
    except ValueError:  # pydantic's ValidationError is a ValueError
        raise ExtractionError("extraction_invalid") from None


def get_extraction_client(settings: Settings) -> ExtractionClient | None:
    """The real client, or None when no key is set (uploads then answer 503)."""
    if settings.anthropic_api_key is None:
        return None
    return AnthropicExtractor(
        settings.anthropic_api_key.get_secret_value(), settings.anthropic_model
    )


def _fail(engine: Engine, statement_id: UUID, code: str, cause: str) -> None:
    """Set `failed` with `code` in a new transaction. The blob stays."""
    log_event("WARNING", "extraction_error", error=cause, statement_id=str(statement_id))
    with Session(engine) as session:
        try:
            set_status(session, statement_id, "failed", code)
        except DBAPIError as exc:
            session.rollback()
            log_event(
                "ERROR", "extraction_error", error=type(exc).__name__,
                statement_id=str(statement_id),
            )


def _finish(engine: Engine, statement_id: UUID, started: float, status: str, code: str | None, count: int) -> None:
    log_event(
        "INFO",
        "extraction_finished",
        statement_id=str(statement_id),
        status=status,
        failure_code=code or "none",
        transaction_count=str(count),
        duration_ms=str(round((time.monotonic() - started) * 1000)),
    )


def run_extraction(
    engine: Engine,
    statement_id: UUID,
    client: ExtractionClient | None,
    model: str,
) -> None:
    """The background job (spec 3.6). Plain def: Starlette runs it in the threadpool.
    `model` is kept for the spec's signature: the client carries the model.
    It never raises: every outcome is a status written, or a log line."""
    started = time.monotonic()
    with Session(engine) as session:
        try:
            statement = session.get(Statement, statement_id)
            if statement is None:  # deleted while queued (BE-15): end quietly
                return
            name = statement.name
            categories = list(
                session.scalars(select(Category.code).order_by(Category.position))
            )
            session.rollback()
            pdf = load_upload(session, statement_id)
        except UploadError as exc:
            session.rollback()
            if exc.code == "database_unavailable":
                log_event("ERROR", "extraction_error", error="UploadError", statement_id=str(statement_id))
                return
            _fail(engine, statement_id, UPLOAD_NOT_AVAILABLE, "UploadError")
            return
        except DBAPIError as exc:
            session.rollback()
            log_event("ERROR", "extraction_error", error=type(exc).__name__, statement_id=str(statement_id))
            return
        except Exception as exc:
            session.rollback()
            _fail(engine, statement_id, "unknown", type(exc).__name__)
            return
        session.rollback()

    try:
        if client is None:
            raise ExtractionError("extraction_unavailable")
        text = client.extract(pdf, categories)
        pdf = b""  # the bytes are dropped once the call has returned
        payload = parse_extraction(text, name)
        with Session(engine) as session:
            check_payload(session, payload)
    except DBAPIError as exc:
        log_event("ERROR", "extraction_error", error=type(exc).__name__, statement_id=str(statement_id))
        return
    except ExtractionError as exc:
        _fail(engine, statement_id, exc.code, exc.cause)
        _finish(engine, statement_id, started, "failed", exc.code, 0)
        return
    except StatementRefused as exc:
        _fail(engine, statement_id, exc.refusal[1], "StatementRefused")
        _finish(engine, statement_id, started, "failed", exc.refusal[1], 0)
        return
    except Exception as exc:
        _fail(engine, statement_id, "unknown", type(exc).__name__)
        _finish(engine, statement_id, started, "failed", "unknown", 0)
        return

    with Session(engine) as session:
        try:
            statement = session.get(Statement, statement_id)
            if statement is None:
                session.rollback()
                return
            imported = store_lines(session, statement, payload)
            set_status(session, statement_id, "ready", commit=False)
            wipe_upload(session, statement_id)
            session.commit()
        except DBAPIError as exc:
            session.rollback()
            log_event("ERROR", "extraction_error", error=type(exc).__name__, statement_id=str(statement_id))
            return
        except Exception as exc:
            session.rollback()
            _fail(engine, statement_id, "unknown", type(exc).__name__)
            _finish(engine, statement_id, started, "failed", "unknown", 0)
            return
    _finish(engine, statement_id, started, "ready", None, imported.transaction_count)
