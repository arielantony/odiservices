from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2]
FILES = {"api": APP / "api" / ".dockerignore", "web": APP / "web" / ".dockerignore"}
FORBIDDEN = (".env", "input", "outputs", "fixtures", "legacy", "tests", ".pdf")
NEEDED = {
    "api": {"!requirements.txt", "!server/"},
    "web": {"!package.json", "!yarn.lock", "!src/", "!nginx/"},
}


def rules(name: str) -> list[str]:
    lines = FILES[name].read_text().splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


@pytest.mark.parametrize("name", FILES)
def test_ignores_everything_by_default(name):
    assert rules(name)[0] == "*"


@pytest.mark.parametrize("name", FILES)
def test_never_allows_sensitive_paths(name):
    allowed = [rule[1:] for rule in rules(name) if rule.startswith("!")]
    leaks = [rule for rule in allowed if any(word in rule for word in FORBIDDEN)]
    assert not leaks, f"re-allowed sensitive paths: {leaks}"


@pytest.mark.parametrize("name", FILES)
def test_blocks_env_and_pdf_anywhere(name):
    assert {"**/.env", "**/.env.*", "**/*.pdf"} <= set(rules(name))


@pytest.mark.parametrize("name", FILES)
def test_allows_what_the_build_needs(name):
    assert NEEDED[name] <= set(rules(name))
