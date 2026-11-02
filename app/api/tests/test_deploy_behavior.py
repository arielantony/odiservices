"""Runs deploy.sh with fake sudo, docker, git and curl, to see what it does."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2]

STUBS = {
    "sudo": r"""#!/usr/bin/env bash
echo "sudo $*" >> "$FAKE_LOG"
if [ "$1" = sha256sum ]; then echo "$FAKE_HASH  $2"; exit 0; fi
if [ "$1" = env ]; then
  shift; tag=""
  while [[ "$1" == *=* ]]; do [[ "$1" == DEPLOY_TAG=* ]] && tag="${1#DEPLOY_TAG=}"; shift; done
  [ "$1" = docker ] && [ -n "$FAKE_COMPOSE_FAILS" ] && [ "$tag" = "$FAKE_COMPOSE_FAILS" ] && exit 1
fi
exit 0
""",
    "docker": r"""#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_LOG"
case "$1" in
  inspect) echo "odiservices-web:$FAKE_PREVIOUS" ;;
  images) printf '%s\n' $FAKE_IMAGES ;;
esac
exit 0
""",
    "git": r"""#!/usr/bin/env bash
case "$1" in
  status) ;;
  rev-parse) echo "$FAKE_TAG_UNDER_TEST" ;;
esac
exit 0
""",
    "curl": "#!/usr/bin/env bash\nexit 0\n",
}


@pytest.fixture
def run_deploy(tmp_path):
    root = tmp_path / "app"
    (root / "deploy").mkdir(parents=True)
    shutil.copy(APP / "deploy" / "deploy.sh", root / "deploy" / "deploy.sh")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in STUBS.items():
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "log"

    def run(tag="new1", previous="old1", env_hash="aaa", images="", fails=""):
        log.write_text("")
        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_LOG": str(log),
            "FAKE_HASH": env_hash,
            "FAKE_TAG_UNDER_TEST": tag,
            "FAKE_PREVIOUS": previous,
            "FAKE_IMAGES": images,
            "FAKE_COMPOSE_FAILS": fails,
        }
        result = subprocess.run(
            ["bash", str(root / "deploy" / "deploy.sh"), "main"],
            env=env, capture_output=True, text=True, timeout=30,
        )
        return result, log.read_text().splitlines()

    return run


def compose_lines(lines):
    return [line for line in lines if "docker compose" in line]


def test_env_hash_reaches_compose(run_deploy):
    result, lines = run_deploy(env_hash="abc123")

    assert result.returncode == 0, result.stderr
    assert "deployed new1" in result.stdout
    assert any("ENV_SHA256=abc123" in line for line in compose_lines(lines))


def test_a_different_env_file_gives_a_different_hash(run_deploy):
    _, first = run_deploy(tag="same", previous="same", env_hash="aaa")
    _, second = run_deploy(tag="same", previous="same", env_hash="bbb")

    assert compose_lines(first) != compose_lines(second)


def test_prune_never_removes_the_tag_in_use_or_the_previous(run_deploy):
    images = "current new1 n2 n3 n4 old1 n6 n7 local"
    result, lines = run_deploy(images=images)

    removed = {line.split(":")[-1] for line in lines if " rmi " in line}
    assert result.returncode == 0, result.stderr
    assert removed == {"n6", "n7"}
    assert "new1" not in removed and "old1" not in removed
    assert "current" not in removed and "local" not in removed


def test_prune_keeps_an_old_tag_deployed_again(run_deploy):
    # An old commit deployed again sorts last in `docker images`.
    images = "n1 n2 n3 n4 n5 oldtag"
    _, lines = run_deploy(tag="oldtag", previous="n1", images=images)

    removed = {line.split(":")[-1] for line in lines if " rmi " in line}
    assert "oldtag" not in removed and "n1" not in removed
    assert removed == {"n5"}


def test_failed_deploy_rolls_back_and_does_not_prune(run_deploy):
    result, lines = run_deploy(tag="bad1", previous="old1", fails="bad1", images="a b c d e")

    assert result.returncode == 1
    assert "rolling back to old1" in result.stderr
    assert any("DEPLOY_TAG=old1" in line for line in compose_lines(lines))
    assert not any(" rmi " in line for line in lines)
