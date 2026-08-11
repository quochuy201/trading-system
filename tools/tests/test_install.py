"""Tests for `./install.sh` — what the Hermes install actually deploys.

Why this file exists: the installer copied `profile.yaml`, `SOUL.md`,
`OPERATING_MANUAL.md`, `scripts/` and `sops/` — but never `skills/`. A fresh
install therefore reported success and produced a profile with **no agent
behaviour at all**, which `verify.sh` check 4 caught on its first live run
(2026-08-09). The presence of an installer is not evidence that it installs the
payload; these tests are.

Isolation — this suite must never touch the live runtime:
  * the installer runs with `--dry-run`, so every mutation goes through `run()`,
    which echoes instead of executing;
  * `HOME` and `HERMES_HOME` both point into `tmp_path`, so any leak lands in a
    throwaway directory;
  * a stub `hermes` is placed first on `PATH` and records every invocation, and
    `test_dry_run_invokes_no_hermes_command` asserts the record is empty. That
    turns "dry-run is inert" from an assumption into an assertion — if a future
    step escapes the guard, this suite fails instead of the runtime changing.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL = REPO_ROOT / "install.sh"

# Records every `hermes ...` invocation the installer attempts, one per line.
_SHIM = """#!/usr/bin/env bash
echo "$@" >> "$HERMES_SHIM_LOG"
exit 0
"""


@pytest.fixture()
def dry_run(tmp_path: Path):
    """Run the installer in dry-run mode against a throwaway HERMES_HOME.

    Returns:
        Tuple of (plan, calls): `plan` is the installer's combined output, where
        every intended mutation appears as a `[dry-run] ...` line; `calls` is the
        list of `hermes` invocations that actually executed (expected: empty).

    Raises:
        AssertionError: the installer exited non-zero. For a dry run that means
            path resolution failed, so the plan itself is unusable.
    """
    home = tmp_path / "hermes-home"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "hermes-calls.log"
    shim = bindir / "hermes"
    shim.write_text(_SHIM)
    shim.chmod(0o755)

    def _run(platform: str = "hermes") -> tuple[str, list[str]]:
        proc = subprocess.run(
            [str(INSTALL), platform, "--dry-run"],
            capture_output=True, text=True,
            env={
                "HOME": str(home),
                "HERMES_HOME": str(home),
                "HERMES_SHIM_LOG": str(log),
                "PATH": f"{bindir}:/usr/bin:/bin:/usr/sbin:/sbin",
            },
        )
        assert proc.returncode == 0, (
            f"dry run failed (exit {proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
        )
        calls = log.read_text().splitlines() if log.exists() else []
        return proc.stdout + proc.stderr, calls

    return _run


def test_dry_run_invokes_no_hermes_command(dry_run) -> None:
    """A dry run must plan, never act — nothing may reach the `hermes` CLI."""
    _, calls = dry_run()
    assert calls == [], "dry run executed hermes commands: " + "; ".join(calls)


def test_install_deploys_skills_into_the_profile(dry_run) -> None:
    """The repo's skills must reach `<profile>/skills/`.

    This is the defect `verify.sh` check 4 found: without this copy the agent has
    no behaviour to follow, and the install still claims success.
    """
    plan, _ = dry_run()
    copies = [ln for ln in plan.splitlines() if " cp " in ln and "skills" in ln]
    assert copies, f"installer plans no skills copy at all:\n{plan}"
    assert any("profiles/trading/skills" in ln for ln in copies), (
        "skills copy does not target the profile's skills dir:\n" + "\n".join(copies)
    )


def test_install_merges_skills_rather_than_replacing_the_dir(dry_run) -> None:
    """Hermes's own built-in skills share that directory and are not ours.

    `verify.sh` check 9 reports runtime-only skills as a warning and never
    deletes them; the installer holds the same line, so no step may remove or
    wholesale-overwrite the profile's skills directory.
    """
    plan, _ = dry_run()
    destructive = [
        ln for ln in plan.splitlines()
        if "skills" in ln and ("rm " in ln or ("rsync" in ln and "--delete" in ln))
    ]
    assert not destructive, (
        "installer would delete skills it does not own:\n" + "\n".join(destructive)
    )


def test_install_copies_the_whole_skills_tree(dry_run) -> None:
    """A per-skill allowlist would silently skip any skill added later.

    Asserts the copy is directory-wide (`skills/.`) rather than naming skills
    one by one, so adding a skill needs no installer edit.
    """
    plan, _ = dry_run()
    assert any(
        " cp " in ln and "/skills/." in ln for ln in plan.splitlines()
    ), "expected a directory-wide skills copy (skills/.), not a per-skill list"
