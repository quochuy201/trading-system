# Change: dead-config cleanup (Phase 2A)

- **Slug:** `dead-config-cleanup` · **Branch:** `refactor/dead-config-cleanup` · **Date:** 2026-10-07
- **Kind:** refactor/cleanup of existing config. No trading behaviour changes.

## What changes and why

CLAUDE.md RULE 3 ("one value, one home") lists config that looks authoritative but that nothing
reads. Each is a trap: a future session edits it, believes the system changed, and nothing did.
Every item below was checked by command on 2026-10-07 before being put in scope.

| # | Change | Evidence it is safe |
|---|---|---|
| 1 | Delete the `mcp_tools:` block from `setup/deploy/profile.yaml` | `grep -rn mcp_tools` → only `profile.yaml:8` defines it; nothing reads it. Hermes keys MCP servers under `mcp_servers:` — that is what the repo's own `mcp_probe.py:164-171` and `verify.sh:85` read from a deployed config. Its patterns (`analysis/*`, `broker/*`…) match no tool name. |
| 2 | Delete the `risk_budget:` blocks from `setup/deploy/runs/equity.yaml` and `runs/options.yaml` | `grep -rn risk_budget` → only those two definitions; the hits in `skills/trader` and `skills/backtest` are a local variable in a sizing formula, not this key. The only code reading `runs/*.yaml` is `verify.sh:249-258`, and it reads `board` only. Their values (8 / 5 positions, 1.5% / 2.0% risk) disagree with `config.yaml` — a 4th, silent risk source. |
| 3 | Make "a tool in no group" an explicit, tested decision. Add `reset_tuning_config` to the `eod` group. Keep `capture_iv_universe` out of every group, but name it in a new `UNGROUPED_BY_DESIGN` set in `server.py`. Add a test: every registered tool is in a group or in that set. | `reset_tuning_config` (`server.py:2903`) is referenced by no skill and no group, so no role-scoped profile can call it. Its siblings `generate_tuning_config`/`get_tuning_config` are in `eod`, and resetting grants no power `generate` doesn't already have. `capture_iv_universe` is called mechanically by cron (`trading-iv-capture.sh:6` does `from server import capture_iv_universe`), not by an agent, so it needs no group. The test guards the bug class that hid 5 options tools for 34 sessions. |
| 4 | Correct the docs that describe these items: `CLAUDE.md:67`, `:251`, `:252`. | `CLAUDE.md:251` claims `mcp.json` has `mcp_tools:` namespaces — `cat setup/deploy/mcp.json` shows it has none (the block was only ever in `profile.yaml`). |

## Worked examples

1. **Refactor — whole suite.** Before: `538 passed, 10 deselected`. After: the same 538, plus the new
   tests, all pass. The 10 deselected tests are the deploy-script tests that fail on this machine
   for environmental reasons (empty `price_data` DB, no `hermes` CLI).
2. **Profile config.** Input: `yaml.safe_load(setup/deploy/profile.yaml)`. Today: has key
   `mcp_tools`. After: no `mcp_tools` key; every other key unchanged.
3. **Run configs.** Input: each `setup/deploy/runs/*.yaml` (not starting with `_`). Today: `equity`
   and `options` have a `risk_budget` key. After: none has `risk_budget`; `board` is still
   present in each (`verify.sh` check 6 still finds `equity` and `options`).
4. **Tool groups.** Input: the set of registered MCP tools vs the union of `TOOL_GROUPS`. Today:
   `{capture_iv_universe, reset_tuning_config}` are in no group, and nothing says whether that is
   intended. After: registered − grouped == `UNGROUPED_BY_DESIGN` == `{capture_iv_universe}`;
   `reset_tuning_config` is in `TOOL_GROUPS["eod"]`. Total tool count stays **63**.

## Out of scope (checked, deliberately not changed)

- **`config.yaml scanner.universe`** — *not* dead. `tools/scripts/load_backtest_week.py:55` reads
  `cfg["scanner"]["universe"]`; deleting it breaks that script. Retiring it means repointing the
  script at `universe_backtest.json` — a separate change.
- **`max_open_positions` (5 in code vs 10 ratified).** `risk/checks.py:8` defaults to 5 and
  `check_portfolio_risk` uses it unless EOD tuning overrides it; `config.yaml:17` and
  `OPERATING_MANUAL.md:66` say 10 (human-ratified 2026-06-11); `skills/risk-manager/SKILL.md:101`
  says "default 5". Fixing it **loosens a live risk check from 5 to 10**, and the repo-root
  `config.yaml` may not exist in the deployed runtime. D2 already designs the real home
  (`risk_limits.{dev,live}.yaml`, fail-safe to dev) under `governance-gate`. Deferred there.
- `setup/deploy/mcp.json` itself — not read by Hermes (PROJECT_STATUS 2026-06-11 entry), but
  `install.sh:270` points Kermes users at it. Kept.
- Everything under `docs/_archive/`.

## Tests

- New file `tools/tests/test_deploy_config.py` — examples 2 and 3.
- `tools/tests/test_tool_groups.py` — example 4.
- One file: `cd tools && .venv/bin/python -m pytest tests/<file> -v -p no:cacheprovider`

## Project facts

- **Specs folder:** feature specs live in `docs/product/features/<slug>/` (CLAUDE.md "How to
  develop"), limited to exactly three files per feature. A change note is not a feature, so it
  goes in `docs/product/changes/<slug>/` — a new folder, flagged to the owner.
- **How work lands:** local `git merge` into `main` after owner confirms (personal repo;
  `git-discipline.md`). Pushing to the public remote needs a separate yes.
- **Commands:** all tests — see `acceptance.json` A1 (whole suite, the 10 environmental deploy
  failures deselected by node id). Lint: none configured (`tools/pyproject.toml` has no linter).
  Build: none.
- **Commands that write:** none (`-p no:cacheprovider`; `__pycache__/` is in `.gitignore:8`).
- **Baseline (2026-10-07):** `538 passed, 10 deselected`, `git status` clean.
- **Fix cap:** 5 (no project number). **Timeout:** 120 s (suite runs in ~45 s).
- **Gate:** `task-gate` from claude-sync's `bin/`. `doctor` reports
  the hooks are **not registered** on this machine, so tests are not locked and the check is not
  enforced automatically — `task-gate check` is run by hand before every stop and commit.
- **What the user allowed:** CLAUDE.md standing policy (paper-only, kill switch never weakened).
  No standing push permission.

## Record

- **Note approved 2026-10-07.** Owner direction: "clean up config, stale document and claude.md".
  The two open choices took the recommended defaults: `max_open_positions` deferred to D2
  (`governance-gate`), and `reset_tuning_config` joins the `eod` group. Stale-doc and CLAUDE.md
  cleanup is a separate unit on its own branch, after this one.
- Accepted first time: _pending_
- Owner corrections: _none yet_
