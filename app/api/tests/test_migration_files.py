import ast
import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

API = Path(__file__).resolve().parents[1]
VERSIONS = API / "migrations" / "versions"
FILES = sorted(VERSIONS.glob("*.py"))


def script_directory() -> ScriptDirectory:
    config = Config(str(API / "alembic.ini"))
    config.set_main_option("script_location", str(API / "migrations"))
    return ScriptDirectory.from_config(config)


def test_single_head():
    # Zero heads until the baseline (step 2) arrives; never more than one.
    assert len(script_directory().get_heads()) <= 1


def test_revision_ids_are_sequential():
    ids = [path.name.split("_")[0] for path in FILES]
    assert ids == [f"{number:04d}" for number in range(1, len(FILES) + 1)]


def test_every_migration_has_a_downgrade():
    for path in FILES:
        tree = ast.parse(path.read_text())
        functions = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        assert "downgrade" in functions, path.name
        body = functions["downgrade"].body
        assert not (len(body) == 1 and isinstance(body[0], ast.Pass)), path.name


def test_no_password_literal():
    for path in FILES:
        text = path.read_text()
        assert not re.search(r"password\s+'", text, re.IGNORECASE), path.name
        assert not re.search(r"postgres(ql)?(\+psycopg)?://", text), path.name
