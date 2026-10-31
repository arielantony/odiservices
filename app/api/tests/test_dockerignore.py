from pathlib import Path

DOCKERIGNORE = Path(__file__).resolve().parents[2] / ".dockerignore"
FORBIDDEN = (".env", "input", "outputs", "fixtures", "legacy", "tests", ".pdf")


def rules() -> list[str]:
    lines = DOCKERIGNORE.read_text().splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def test_ignores_everything_by_default():
    assert rules()[0] == "*"


def test_never_allows_sensitive_paths():
    allowed = [rule[1:] for rule in rules() if rule.startswith("!")]
    leaks = [rule for rule in allowed if any(word in rule for word in FORBIDDEN)]
    assert not leaks, f"re-allowed sensitive paths: {leaks}"


def test_blocks_env_and_pdf_anywhere():
    assert {"**/.env", "**/.env.*", "**/*.pdf"} <= set(rules())


def test_allows_what_the_build_needs():
    needed = {
        "!api/requirements.txt",
        "!api/server/",
        "!web/package.json",
        "!web/yarn.lock",
        "!web/src/",
    }
    assert needed <= set(rules())
