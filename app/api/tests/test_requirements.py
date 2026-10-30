from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent


def requirement_lines(name: str) -> list[str]:
    lines = (API_DIR / name).read_text().splitlines()
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith(("#", "-"))
    ]


def assert_all_pinned(name: str) -> None:
    lines = requirement_lines(name)
    assert lines, f"{name} has no requirements"
    unpinned = [line for line in lines if "==" not in line]
    assert not unpinned, f"{name} has unpinned requirements: {unpinned}"


def test_runtime_requirements_are_pinned():
    assert_all_pinned("requirements.txt")


def test_dev_requirements_are_pinned():
    assert_all_pinned("requirements-dev.txt")
