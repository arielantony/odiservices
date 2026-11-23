"""The extraction of a statement PDF (BE-03), with no database and no network. The
session, the blob functions and the status write are fakes; the answer is the
canonical fixture; the SDK is a stub that raises the SDK's own error classes."""

import json
import re
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

import server.extraction as extraction
from server.extraction import (
    PROMPT_PATH,
    AnthropicExtractor,
    ExtractionError,
    build_schema,
    get_extraction_client,
    load_prompt,
    parse_extraction,
    run_extraction,
)
from server.settings import Settings
from server.uploads import UploadError

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "app" / "fixtures" / "statement-example-2026-09.json"
STATEMENT_ID = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
NAME = "Fatura Cartão Exemplo, set/2026"
PDF = b"%PDF-1.4\n% fictitious\n%%EOF\n"
# The ten codes of portal.categories, in the order of the prompt (fixture list).
TABLE_CODES = [
    "FORNECEDOR",
    "OPERACIONAL",
    "MARKETING/COMERCIAL",
    "INVESTIMENTO",
    "DESPESA ADMINISTRATIVA",
    "FOLHA DE PAGAMENTO",
    "CUSTO DO CARRO",
    "DESPESAS FINANCEIRAS",
    "PESSOA FISICA",
    "OUTROS",
]


def fixture_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


class Store:
    """The state the fakes share: one statement row, one blob, the writes made."""

    def __init__(self, blob: bytes | None = PDF):
        self.row = SimpleNamespace(
            id=STATEMENT_ID, name=NAME, status="processing", failure_code=None,
            total_lanc_atuais=None,
        )
        self.blob = blob
        self.categories = list(TABLE_CODES)
        self.commits = 0
        self.rollbacks = 0
        self.inserted = 0
        self.wiped = False
        self.statuses: list[tuple[str, str | None, bool]] = []


class Result:
    rowcount = 1


class FakeSession:
    def __init__(self, store: Store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, model, key):
        row = self.store.row
        return row if row is not None and key == STATEMENT_ID else None

    def scalars(self, statement):
        return iter(self.store.categories)

    def execute(self, statement, params=None):
        if params is not None:
            self.store.inserted += len(params)
        return Result()

    def commit(self):
        self.store.commits += 1

    def rollback(self):
        self.store.rollbacks += 1


class FakeClient:
    def __init__(self, answer: str | None = None, error: str | None = None):
        self.answer = answer
        self.error = error
        self.calls: list[tuple[int, list[str]]] = []

    def extract(self, pdf: bytes, categories: list[str]) -> str:
        self.calls.append((len(pdf), list(categories)))
        if self.error is not None:
            raise ExtractionError(self.error)
        return self.answer


@pytest.fixture
def store(monkeypatch) -> Store:
    state = Store()

    def fake_load(session, statement_id, *, settings=None):
        if state.blob is None:
            raise UploadError("upload_missing")
        return state.blob

    def fake_wipe(session, statement_id):
        state.wiped = True
        state.blob = None
        return True

    def fake_set_status(session, statement_id, status, failure_code=None, *, expected=None, commit=True):
        state.statuses.append((status, failure_code, commit))
        state.row.status = status
        state.row.failure_code = failure_code
        if commit:
            session.commit()
        return True

    monkeypatch.setattr(extraction, "Session", lambda engine: FakeSession(state))
    monkeypatch.setattr(extraction, "load_upload", fake_load)
    monkeypatch.setattr(extraction, "wipe_upload", fake_wipe)
    monkeypatch.setattr(extraction, "set_status", fake_set_status)
    return state


def test_prompt_copy_is_the_root_prompt():
    assert PROMPT_PATH.read_bytes() == (REPO_ROOT / "prompt-pdf.md").read_bytes()


def test_prompt_categories_are_the_seeded_codes():
    match = re.search(
        r"^- `categoria`: exatamente um destes valores: (.+?)\.?\s*$",
        load_prompt(),
        re.M,
    )
    assert match is not None
    assert [code.strip() for code in match[1].split(",")] == TABLE_CODES


def test_fixture_parses_to_a_payload():
    payload = parse_extraction(fixture_text(), NAME)

    assert payload.name == NAME
    assert len(payload.lancamentos) == 17
    assert payload.total_lanc_atuais == Decimal("11906.35")


def test_bad_json_is_extraction_invalid():
    with pytest.raises(ExtractionError) as info:
        parse_extraction("isto não é JSON", NAME)

    assert info.value.code == "extraction_invalid"


def test_schema_violation_is_extraction_invalid():
    data = json.loads(fixture_text())
    data["campo_extra"] = 1

    with pytest.raises(ExtractionError) as info:
        parse_extraction(json.dumps(data), NAME)

    assert info.value.code == "extraction_invalid"


def test_schema_has_the_categories_of_the_table():
    schema = build_schema(TABLE_CODES)

    categoria = schema["properties"]["lancamentos"]["items"]["properties"]["categoria"]
    assert categoria["enum"] == TABLE_CODES


class StubStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


def stub_extractor(raises=None, message=None) -> AnthropicExtractor:
    extractor = AnthropicExtractor("sk-fictitious-test-key", "claude-test", timeout=1)

    def stream(**kwargs):
        if raises is not None:
            raise raises
        return StubStream(message)

    extractor._client = SimpleNamespace(messages=SimpleNamespace(stream=stream))
    return extractor


def sdk_error(cls):
    request = httpx2.Request("POST", "https://api.anthropic.test/v1/messages")
    if cls is anthropic.APIStatusError or cls.__name__ in ("AuthenticationError", "RateLimitError"):
        response = httpx2.Response(401, request=request)
        return cls("mensagem secreta do provedor", response=response, body=None)
    return cls(request=request)


def test_sdk_errors_map_to_codes():
    expected = {
        anthropic.AuthenticationError: "extraction_unavailable",
        anthropic.RateLimitError: "extraction_unavailable",
        anthropic.APIConnectionError: "extraction_unavailable",
        anthropic.APITimeoutError: "extraction_timeout",
    }
    for cls, code in expected.items():
        with pytest.raises(ExtractionError) as info:
            stub_extractor(raises=sdk_error(cls)).extract(PDF, TABLE_CODES)
        assert info.value.code == code
        assert "mensagem secreta" not in str(info.value)


def test_refusal_and_truncation_map_to_codes():
    refused = SimpleNamespace(stop_reason="refusal", content=[])
    truncated = SimpleNamespace(stop_reason="max_tokens", content=[])

    with pytest.raises(ExtractionError) as info:
        stub_extractor(message=refused).extract(PDF, TABLE_CODES)
    assert info.value.code == "extraction_refused"

    with pytest.raises(ExtractionError) as info:
        stub_extractor(message=truncated).extract(PDF, TABLE_CODES)
    assert info.value.code == "extraction_truncated"


def test_run_extraction_success_stores_and_wipes(store):
    client = FakeClient(answer=fixture_text())

    run_extraction(None, STATEMENT_ID, client, "claude-test")

    assert store.row.status == "ready"
    assert store.inserted == 17
    assert store.wiped is True
    assert store.commits == 1
    assert client.calls == [(len(PDF), TABLE_CODES)]


def test_run_extraction_total_mismatch_is_failed_and_keeps_blob(store):
    answer = fixture_text().replace('"valor": 1250.0,', '"valor": 1250.01,', 1)
    assert answer != fixture_text()

    run_extraction(None, STATEMENT_ID, FakeClient(answer=answer), "claude-test")

    assert store.row.status == "failed"
    assert store.row.failure_code == "total_mismatch"
    assert store.inserted == 0
    assert store.wiped is False
    assert store.blob == PDF


def test_run_extraction_unknown_category_is_failed(store):
    answer = fixture_text().replace('"categoria": "FORNECEDOR"', '"categoria": "XYZ"', 1)

    run_extraction(None, STATEMENT_ID, FakeClient(answer=answer), "claude-test")

    assert store.row.status == "failed"
    assert store.row.failure_code == "unknown_category"
    assert store.blob == PDF


def test_run_extraction_error_is_failed_with_code(store):
    run_extraction(None, STATEMENT_ID, FakeClient(error="extraction_timeout"), "claude-test")

    assert store.row.status == "failed"
    assert store.row.failure_code == "extraction_timeout"
    assert store.blob == PDF


def test_missing_blob_is_interrupted(store):
    store.blob = None
    client = FakeClient(answer=fixture_text())

    run_extraction(None, STATEMENT_ID, client, "claude-test")

    assert store.row.status == "failed"
    assert store.row.failure_code == "upload_not_available"
    assert client.calls == []


def test_no_key_is_unavailable(store):
    no_key = Settings(_env_file=None, env="dev")
    assert get_extraction_client(no_key) is None

    run_extraction(None, STATEMENT_ID, None, "claude-test")

    assert store.row.status == "failed"
    assert store.row.failure_code == "extraction_unavailable"
    assert store.blob == PDF


def test_job_ends_quietly_when_the_row_is_gone(store, capsys):
    store.row = None
    client = FakeClient(answer=fixture_text())

    run_extraction(None, STATEMENT_ID, client, "claude-test")

    assert client.calls == []
    assert store.statuses == []
    assert store.commits == 0
    assert capsys.readouterr().out == ""


def test_logs_carry_no_values(store, capsys):
    answer = fixture_text().replace(
        '"descricao": "Distribuidora Exemplo Ltda"',
        '"descricao": "Lançamento Planted Secreto"',
        1,
    ).replace('"categoria": "FORNECEDOR"', '"categoria": "CATEGORIA SECRETA"', 1)

    run_extraction(None, STATEMENT_ID, FakeClient(answer=answer), "claude-test")

    output = capsys.readouterr()
    logged = output.out + output.err
    assert "Lançamento Planted Secreto" not in logged
    assert "CATEGORIA SECRETA" not in logged
    assert "extraction_finished" in logged
