"""Negative tests for `setup/deploy/preflight.sh`.

Preflight gates a cycle that would do something harmful, so a check that
cannot fail is worse than no check: it reports health it never measured.

No check may name a vendor's credential. This file once asserted
DEEPSEEK_API_KEY while the profiles ran provider xai (whose credential is an
OAuth token in auth.json, not a key in .env), and DISCORD_BOT_TOKEN after
delivery had moved to Telegram. Check 1 therefore asks the runtime that owns
the credential — `hermes -z` — rather than guessing where it lives.

Every check here is broken deliberately and asserted to FAIL, naming the right
reason.

Isolation: each test builds a throwaway profile under `tmp_path` and passes it
via HERMES_HOME, with a stub `python` standing in for the tools layer. Nothing
here reads or writes the real `~/.hermes`, and no test makes a network call.
"""
from __future__ import annotations

import sqlite3
import subprocess
import textwrap
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = REPO_ROOT / "setup" / "deploy" / "preflight.sh"

ACCOUNT_JSON = '{"equity": 107371.21, "cash": 93354.34}'
KILL_SWITCH_OFF = '{"active": false, "triggered_at": null, "reason": null}'


def _stub(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + textwrap.dedent(body))
    path.chmod(0o755)
    return path


def build_profile(
    home: Path,
    *,
    profile: str = "trading",
    env_lines: str | None = None,
    last_bar_days_ago: int = 2,
    account_out: str = ACCOUNT_JSON,
    kill_switch_out: str = KILL_SWITCH_OFF,
) -> Path:
    """Build a profile that preflight should pass.

    Args:
        home: Fake HERMES_HOME root.
        env_lines: Contents of the profile `.env`; defaults to all keys present.
        last_bar_days_ago: Age of the newest `price_data` row, for check 3.
        account_out: What the stubbed tools layer prints for `get_account()`.
        kill_switch_out: Likewise for `check_kill_switch()`.

    Returns:
        Path to the profile directory.
    """
    profile = home / "profiles" / profile
    tools = profile / "tools"
    (profile / "scripts").mkdir(parents=True, exist_ok=True)
    tools.mkdir(parents=True, exist_ok=True)

    if env_lines is None:
        env_lines = "\n".join([
            "ALPACA_API_KEY=" + "k" * 8,
            "ALPACA_SECRET_KEY=" + "s" * 8,
        ])
    (profile / ".env").write_text(env_lines + "\n")

    db = tools / "trading.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE price_data (symbol TEXT, timestamp TEXT, timeframe TEXT)"
    )
    stamp = (datetime.now() - timedelta(days=last_bar_days_ago)).strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO price_data VALUES ('AAPL', ?, '1Day')",
        (f"{stamp}T00:00:00+00:00",),
    )
    conn.commit()
    conn.close()

    # Stand in for the tools-layer interpreter: preflight calls it as
    # `python -c "from server import X; print(X())"`, so branch on the snippet.
    venv_bin = tools / ".venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    _stub(venv_bin / "python", f"""
        case "$2" in
          *get_account*)      echo '{account_out}' ;;
          *check_kill_switch*) echo '{kill_switch_out}' ;;
          *) echo "unexpected snippet: $2" >&2; exit 3 ;;
        esac
    """)
    return profile


def run_preflight(home: Path, tmp_path: Path, hermes_body: str = 'echo ok\n'
                  ) -> subprocess.CompletedProcess:
    """Run preflight against a throwaway home with a stubbed `hermes` on PATH.

    Runs a *copy* under tmp_path: the script writes preflight.log beside
    itself, and tests must not dirty the repo. The stub goes on PATH rather
    than behind an env override, because the script calls `hermes` directly.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    _stub(bindir / "hermes", hermes_body)
    script = tmp_path / "preflight.sh"
    script.write_bytes(PREFLIGHT.read_bytes())
    return subprocess.run(
        ["bash", str(script)],
        capture_output=True, text=True,
        cwd=str(tmp_path),
        env={
            "PATH": f"{bindir}:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(tmp_path),
            "HERMES_HOME": str(home),
            "HERMES_PROFILE": "trading",
        },
    )


# --- the happy path, so a failing test below means the break, not the setup ---


def test_all_checks_pass(tmp_path):
    build_profile(tmp_path / "home")
    result = run_preflight(tmp_path / "home", tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All preflight checks passed" in result.stdout


# --- check 1: model auth asks the runtime, never a key name ---


def test_dead_provider_fails_check_1(tmp_path):
    """A revoked token / 403 must abort the cycle."""
    build_profile(tmp_path / "home")
    result = run_preflight(
        tmp_path / "home", tmp_path,
        hermes_body='echo "hermes -z: agent failed: 403 Forbidden" >&2\nexit 1\n',
    )
    assert result.returncode != 0
    assert "Model auth failed" in result.stdout
    assert "403" in result.stdout


def test_no_final_response_fails_check_1(tmp_path):
    """The recorded xAI failure mode: the run produces nothing at all.
    `hermes -z` exits 1 for that, not only for raised exceptions."""
    build_profile(tmp_path / "home")
    result = run_preflight(tmp_path / "home", tmp_path, hermes_body='exit 1\n')
    assert result.returncode != 0
    assert "Model auth failed" in result.stdout


def test_check_1_does_not_depend_on_any_key_name(tmp_path):
    """The regression that motivated the rewrite.

    A profile .env naming NO model-provider key must still pass when the agent
    answers — proving the check measures whether the model works, not whether
    a particular string exists. The old grep asserted DEEPSEEK_API_KEY while
    the profiles ran provider xai.
    """
    home = tmp_path / "home"
    build_profile(home)  # .env carries ALPACA keys only
    result = run_preflight(home, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Model authentication valid" in result.stdout


def test_check_1_is_scoped_to_the_profile(tmp_path):
    """The probe must run as the profile whose cycle is about to start."""
    home = tmp_path / "home"
    build_profile(home)
    run_preflight(home, tmp_path,
                  hermes_body='echo "$@" > "$(dirname "$0")/hermes.args"\necho ok\n')
    args = (tmp_path / "bin" / "hermes.args").read_text()
    assert "-p trading" in args
    assert "-z" in args


# --- check 2: Alpaca ---


def test_missing_alpaca_key_fails_check_2(tmp_path):
    home = tmp_path / "home"
    build_profile(home, env_lines="ALPACA_SECRET_KEY=ssss")
    result = run_preflight(home, tmp_path)
    assert result.returncode != 0
    assert "ALPACA_API_KEY missing" in result.stdout


def test_empty_alpaca_key_fails_check_2(tmp_path):
    """Present-but-empty is the shape a half-written .env actually takes."""
    home = tmp_path / "home"
    build_profile(
        home,
        env_lines="ALPACA_API_KEY=\nALPACA_SECRET_KEY=ssss",
    )
    result = run_preflight(home, tmp_path)
    assert result.returncode != 0
    assert "ALPACA_API_KEY missing" in result.stdout


def test_unreachable_account_fails_check_2(tmp_path):
    home = tmp_path / "home"
    build_profile(home, account_out='{"error": "unauthorized"}')
    result = run_preflight(home, tmp_path)
    assert result.returncode != 0
    assert "malformed" in result.stdout or "connection failed" in result.stdout


# --- check 3: data freshness ---


def test_stale_data_fails_check_3(tmp_path):
    home = tmp_path / "home"
    build_profile(home, last_bar_days_ago=9)
    result = run_preflight(home, tmp_path)
    assert result.returncode != 0
    assert "Market data is stale" in result.stdout


def test_four_day_old_data_still_passes(tmp_path):
    """Mon after a 3-day weekend plus a holiday — must not block trading."""
    home = tmp_path / "home"
    build_profile(home, last_bar_days_ago=4)
    result = run_preflight(home, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


# --- check 4: kill switch ---


def test_active_kill_switch_fails_check_4(tmp_path):
    home = tmp_path / "home"
    build_profile(home, kill_switch_out='{"active": true, "reason": "daily loss"}')
    result = run_preflight(home, tmp_path)
    assert result.returncode != 0
    assert "Kill switch is ACTIVE" in result.stdout


# --- check 0: prerequisites ---


def test_missing_tools_layer_fails_check_0(tmp_path):
    home = tmp_path / "home"
    (home / "profiles" / "trading").mkdir(parents=True)
    (home / "profiles" / "trading" / ".env").write_text("ALPACA_API_KEY=kkkk\n")
    result = run_preflight(home, tmp_path)
    assert result.returncode != 0
    assert "Tools layer missing" in result.stdout


def test_remediation_names_no_machine_specific_path():
    """Remediation must not hardcode one developer's checkout path."""
    source = PREFLIGHT.read_text()
    assert "/Users/" not in source
    assert "workplace/trading-system" not in source



def test_preflight_names_no_vendor_credential():
    """No check may assert a specific provider's key.

    This file asserted DEEPSEEK_API_KEY while the profiles ran provider xai,
    and DISCORD_BOT_TOKEN after delivery had already moved to Telegram. Both
    were dead controls that named a vendor -- and the vendor changes.
    """
    body = "\n".join(
        line for line in PREFLIGHT.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    for vendor_key in ("DEEPSEEK", "DISCORD", "TELEGRAM", "SLACK", "OPENAI",
                       "ANTHROPIC", "XAI", "INSTAGRAM"):
        assert vendor_key not in body, (
            f"{vendor_key} named in preflight -- vendor credentials change; "
            f"this check will rot into a lie"
        )


# --- which profile: location is the source of truth, and there is no default ---


@pytest.mark.parametrize("profile", ["trading", "trading-small", "trading-v2",
                                     "trading-strategiesA"])
def test_installed_copy_derives_its_own_profile(tmp_path, profile):
    """Scales to any number of profiles with no edit to the script.

    install.sh drops a copy in each profile's scripts/ dir, so each copy names
    its own profile from its own path.
    """
    home = tmp_path / "home"
    build_profile(home, profile=profile)
    scripts = home / "profiles" / profile / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    script = scripts / "preflight.sh"
    script.write_bytes(PREFLIGHT.read_bytes())

    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    _stub(bindir / "hermes", "echo ok\n")
    result = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, cwd=str(tmp_path),
        env={"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"(profile: {profile})" in result.stdout


def test_gateway_scoped_hermes_home_does_not_double_the_path(tmp_path):
    """The bug this guards: a profile gateway is launched with
    HERMES_HOME=~/.hermes/profiles/<name> (see its launchd plist), and cron
    resolves scripts from that home. Composing "$HERMES_HOME/profiles/$NAME"
    then yields ~/.hermes/profiles/trading/profiles/trading and EVERY cycle
    aborts at check 0.
    """
    home = tmp_path / "home"
    build_profile(home)
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    _stub(bindir / "hermes", "echo ok\n")
    script = tmp_path / "preflight.sh"
    script.write_bytes(PREFLIGHT.read_bytes())

    result = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, cwd=str(tmp_path),
        env={
            "PATH": f"{bindir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "HERMES_HOME": str(home / "profiles" / "trading"),  # as the gateway sets it
        },
    )
    assert "profiles/trading/profiles" not in result.stdout, "path doubled"
    assert result.returncode == 0, result.stdout + result.stderr


def test_refuses_to_guess_a_profile(tmp_path):
    """No default. Guessing means preflighting a different profile than the
    cycle about to run — silently, and more wrongly the more profiles exist."""
    script = tmp_path / "preflight.sh"
    script.write_bytes(PREFLIGHT.read_bytes())
    result = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, cwd=str(tmp_path),
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    assert result.returncode != 0
    assert "Cannot determine which profile" in result.stdout


def test_no_profile_name_is_hardcoded():
    body = "\n".join(
        line for line in PREFLIGHT.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    for literal in ('"trading"', "'trading'", '"trading-small"'):
        assert literal not in body, f"{literal} hardcoded as a profile name"
