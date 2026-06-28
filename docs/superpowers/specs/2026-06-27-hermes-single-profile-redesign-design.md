# Hermes Deployment Redesign — Single Profile, Asset-Class Separation, Clean Repo

**Date:** 2026-06-27
**Status:** Design approved (pending written-spec review) → implementation planning
**Author:** brainstormed with the user (Claude Code)
**Supersedes operationally:** the 8-profile kanban layout (PROJECT_STATUS 2026-06-11 "session 4c")

---

## 1. Context & problem

The trading package itself is healthy: 331 passing tests, working scanners, SOPs, MCP
tools, and a mature strategy-routing layer. The pain is entirely in the **Hermes
deployment / runtime-config layer**. Three reported problems, with evidence gathered
during diagnosis:

1. **"Can't do an actual run."** Not a package bug — three layers of per-profile
   runtime-config drift:
   - **Model auth dead:** `~/.hermes/profiles/*/auth.json` has only `xai-oauth`; the
     morning cron's last run died with `xAI OAuth state is missing access_token`. Every
     agent run fails here first.
   - **Gateway API server can't start:** `errors.log` shows
     `Refusing to start: API_SERVER_KEY is required` — failing every 5 minutes, 587
     consecutive retries. The orchestrator gateway has effectively been down.
   - **Delivery broken:** cron delivery fails with Discord `Unknown Channel (404)` —
     stale channel id `1467223060393361583`.

2. **Multi-profile confusion / fragile installs.** 8 trading profiles
   (`trading-system`, `-orchestrator`, `-research`, `-trader`, `-monitor`, `-risk`,
   `-eod`, `-backtest`), each carrying its **own** `auth.json`, `.env`, model, cron
   store, MCP registration, and Discord binding. Every failure above is multiplied ×8.
   `install.sh` copies *content* but never *reconciles runtime config*, so scheduling a
   cron lands in whatever profile was active, later edits re-create it elsewhere, and
   each reinstall produces fresh drift. The "lean worker" rationale is already dead:
   every worker profile has accreted **18–19 generic skills** (`apple`, `email`,
   `social-media`, `mlops`, …), so multi-profile buys no leanness today.

3. **Dirty repository.** Stale ideation at root (`idea-honing.md`, `rough-idea.md`,
   `summary.md`, `SCAN_FUNNEL_SUMMARY.md`), overlapping doc dirs (`design/`,
   `implementation/`, `research/`, `references/`, `exports/`, `_archive/`, `hermes/`
   vs `cron/`), an empty 0-byte root `trading.db`, and uncommitted report artifacts.

**Through-line:** the package is fine; deployment config is imperative, drifting, and
multiplied. The fix is *declarative, reconciled, single-surface* deployment.

### Research grounding (how Hermes intends multi-agent)

From the Nous docs, the Kanban RFC (#16102 / PR #16100), and community practice:

- Hermes' multi-agent model is **profile-per-worker OS processes** ("Every worker is a
  full OS process with its own identity"), *not* in-process subagents. The **dispatcher
  runs inside the gateway** every ~60s (reclaim stale → promote ready → claim+spawn),
  with a **circuit breaker** after 2 consecutive failures.
- **Multi-profile is recommended only for orchestrator + parallel specialists.**
  Explicitly: *"Single-profile users operate normally on the default board without
  configuring anything special."*
- `kanban swarm` is built for **parallel fan-out → gated verifier → synthesizer**, not a
  sequential pipeline.
- **`--idempotency-key`** (verified present in installed v0.17 `hermes kanban create`)
  lets a cron re-create the same task graph daily **without duplication**.
- `hermes kanban schedule` is a **status** ("parked"), *not* a timer — so timed phases
  must be driven by **cron**, which is genuinely time-based.
- The praised community pattern is exactly *"closed specialists running on cron from a
  backlog"* on one board.

**Conclusion:** the past failures were *kanban-used-wrong + too-many-profiles*, not
kanban-the-idea. Each specific pain has a native fix (table in §4).

---

## 2. Goals / non-goals

**Goals**
- One reproducible, idempotent deployment that converges to identical state on any
  machine and any session.
- Eliminate per-profile config drift (collapse 8 → 1 profile).
- Make runs fail **loudly and early** with actionable remediation, never silent retry
  loops.
- Provider-agnostic model config (one swappable knob) so switching providers later is
  trivial.
- Separate runs by **asset class** (equity, options now; crypto, prediction later),
  sharing role logic, with a clean seam to split into dedicated Hermes profiles later.
- A clean, conventional repository layout.

**Non-goals**
- No change to trading strategy logic, SOPs' numbers, scanners, or risk math.
- No new MCP tools beyond what reliability/asset-context requires.
- Not solving provider *choice* (user will switch later); only the *mechanism* must be
  resilient and swappable.
- Not building crypto/prediction packs now — only the seam that admits them.

---

## 3. Locked decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **One `trading` profile** is the sole runtime. | Kills the ×8 config-drift multiplier; Hermes supports single-profile boards natively. |
| D2 | **Orchestration = cron-triggered, idempotent kanban graph** + in-gateway dispatcher. | Hermes-native orchestrator-worker; durable + recoverable; `--idempotency-key` fixes duplication. |
| D3 | **Timed phases (monitor, EOD) run on cron**, not kanban scheduling. | `kanban schedule` is a status, not a timer. |
| D4 | **Drop the `*/5` kanban-tick cron.** | The gateway dispatcher replaces it; running both caused double-dispatch. |
| D5 | **Provider is one declarative knob** (`model:` + native `fallback_model:`). | Swappable; resilient via failover; no code change to switch. |
| D6 | **Preflight health-gate** runs before every cycle. | Converts silent runtime failures into early, actionable aborts. |
| D7 | **Separate along the asset-class axis, not the role axis.** | Roles are shared logic; asset classes hold the real differences (instruments, data, hours, SOPs). |
| D8 | **Equity & options run as separate runs now** (own board + own morning cron), sharing the core. | User intent; makes future per-profile split a no-op. |
| D9 | **Git is the deployment source of truth; secrets are machine-local.** | Reproducible across machines/sessions; no secrets in git. |
| D10 | **Repo cleanup = consolidate + archive**, delete only true junk, preserve runtime-referenced files. | Reversible, safe; git history retains everything. |

---

## 4. Architecture

### 4.1 Three-layer asset-class model

**Layer 1 — Shared core (one copy, asset-aware).** Role skills
(`skills/research`, `skills/trader`, `skills/monitor`, `skills/risk-manager`,
`skills/eod-review`), all MCP tools (`tools/`), the SQLite DB, the kill switch, the
global risk gate, and the mechanical monitor sentinel. These take asset/strategy as
*context*; they do not fork per asset.

**Layer 2 — Asset-class packs (per asset).** The parts that genuinely differ:
`sops/equity/`, `sops/options/` (and future `sops/crypto/`, `sops/prediction/`) —
entry/exit/sizing rules, scanner filter profiles, risk budget, market-hours schedule.

**Layer 3 — Run-unit bindings (declarative).** `deploy/runs/<asset>.yaml` maps an
asset's run to a kanban board, a cron schedule, its SOP/scanner pack, its risk budget,
and a **`profile:` target**. `install.sh` reads these to wire boards + crons.

```yaml
# deploy/runs/equity.yaml
asset: equity
board: equity
profile: trading            # future: trading-equity → physical separation, no code change
schedule: { morning: "35 6 * * 1-5" }   # PT
sops: sops/equity
scanner_profile: equity
phases: [risk, research, trade]         # monitor/eod/risk-state are shared (see 4.3)
```

```yaml
# deploy/runs/options.yaml
asset: options
board: options
profile: trading            # future: trading-options
schedule: { morning: "40 6 * * 1-5" }   # staggered 5 min after equity
sops: sops/options
scanner_profile: options
phases: [risk, research, trade]
```

The morning cron for each asset creates `risk → research → trade` on **its** board with
`--idempotency-key=<asset>-<YYYYMMDD>-<phase>`, `--parent` for dependency gating, and
`--skill <role>` to force-load the role skill. The asset specialization is carried in
the task **body** (templated from the run-unit: "run the EQUITY scan, use `sops/equity`,
`scanner_profile=equity`…"); the role skill stays generic and the worker calls the
asset-appropriate MCP tools.

### 4.2 What is shared vs separate

| Concern | Shared (Layer 1) | Per-asset (Layers 2–3) |
|---|---|---|
| Role skills (scan/DD/trade/monitor/risk/eod) | ✅ one copy, asset-aware | — |
| MCP tools, DB, kill switch, account | ✅ global | — |
| Risk budget & mode (NORMAL/DEFENSIVE/HALTED) | ✅ global state in DB | per-asset *eligibility* (regime → strategy ON/OFF) |
| Entry/exit/sizing rules | — | ✅ `sops/<asset>/` |
| Scanner filter profile | scanner *code* shared | ✅ per-asset thresholds |
| Morning scan→trade run (board + cron) | — | ✅ separate per asset |
| Monitor (sentinel + LLM) | ✅ one global, asset-agnostic; applies each position's exit profile | exit profile is asset-specific (already in monitor skill) |
| EOD review | ✅ one portfolio-wide | — |

**Why global risk/monitor/EOD now:** there is one Alpaca account, one DB, one kill
switch. Global risk and the kill switch must see *all* positions regardless of which run
opened them. When an asset is later split onto its own broker/account/profile, its
run-unit can grow to own the full stack (risk/monitor/EOD) — the run-unit model admits
both shapes.

### 4.3 Cron & board topology (single profile, now)

Per-asset (own board):
- `equity-morning` 6:35 PT weekdays → preflight gate, then build `equity` board graph.
- `options-morning` 6:40 PT weekdays → preflight gate, then build `options` board graph.

Shared portfolio services (no board; `--no-agent` scripts or single sessions):
- `trading-data-refresh` 6:15 PT — universe adjusted daily bars.
- `trading-iv-capture` 13:05 PT — options IV-rank accrual.
- `trading-monitor-sentinel` every min, market hours — mechanical, wakes LLM monitor
  only on trigger; watches all open positions.
- `trading-eod` 13:15 PT — portfolio-wide review.

Removed: `trading-kanban-tick` `*/5` (dispatcher in gateway replaces it),
`trading-morning` (old single-graph orchestrator), and all per-role profile crons.

### 4.4 Run-reliability layer

- **Provider knob:** `deploy/profile.yaml` carries `model:` + `fallback_model:`; the
  installer writes them into the one profile's `config.yaml`. Native `fallback_model`
  gives auto-failover on rate-limit/overload/connection failure. Switching providers
  later = edit one field + reinstall.
- **Preflight health-gate** (new mechanical script, run by each morning cron *before*
  graph creation; also runnable by hand). Checks, in order:
  1. Model auth resolves (provider token present/valid).
  2. Alpaca keys load and the account is reachable.
  3. Data freshness within tolerance.
  4. Kill-switch state.
  5. Delivery channel reachable (Discord/Slack).

  On any failure: **abort the cycle**, do not create the graph, and emit **one
  actionable message** (the exact remediation command, e.g. `hermes model` to re-auth)
  to the delivery channel and stdout. This replaces the silent 587-retry loop. It is a
  thin trading-specific wrapper over `hermes doctor` + MCP account/data checks.
- **The three concrete breakages:**
  - Missing `access_token` → caught by preflight; runbook documents `hermes model`.
  - `API_SERVER_KEY required` → installer sets it (or disables the unused API server)
    so the gateway — and therefore the dispatcher — starts.
  - Discord `Unknown Channel` → channel id moves to env/config (machine-local),
    validated by preflight; a stale channel fails loudly, not silently.

---

## 5. Repository reorganization

**New `deploy/`** — the single deployment source of truth:
```
deploy/
  profile.yaml          # declarative profile: model, fallback, MCP, Discord, API_SERVER_KEY, timezone
  runs/
    equity.yaml
    options.yaml
    _shared.yaml        # shared portfolio crons (data-refresh, iv-capture, monitor, eod)
  cron/                 # the *.sh scripts (moved from cron/), absolute-path-safe
  SOUL.md               # the single `trading` profile's orchestrator soul
  preflight.sh          # health-gate script
  README.md             # one-time per-machine secret setup + install runbook
```

**Consolidate docs under `docs/`:**
- `design/` → `docs/design/`; `implementation/` → `docs/implementation/`;
  `research/` → `docs/research/`.
- `references/trading-morning-cycle-examples.md` → `docs/runtime/` (or keep path) —
  **update the orchestrator skill that loads it in the same commit** (runtime-referenced).
- Superseded ideation → `docs/archive/`: `idea-honing.md`, `rough-idea.md`,
  `summary.md`, `SCAN_FUNNEL_SUMMARY.md`.

**Delete only true junk:** empty root `trading.db` (0 bytes), `_archive/misc/*.txt`
scraps.

**Reports:** gitignore generated `reports/*.md` (keep a `reports/README.md`); they are
daily artifacts, not source.

**Truth-ups:** `distribution.yaml` `hermes_requires` → `>=0.17`; clean `.gitignore`;
retire the old `hermes/profiles/*/SOUL.md` worker stubs (replaced by `deploy/SOUL.md` +
shared `skills/`).

**Root keeps:** `CLAUDE.md`, `PROJECT_STATUS.md`, `OPERATING_MANUAL.md`, `README.md`,
`config.yaml`, `distribution.yaml`, `install.sh`, `skills/`, `sops/`, `tools/`.

---

## 6. Migration & idempotent install

`install.sh hermes` rewritten to be idempotent + reconciling:

1. **Delete the 8 legacy profiles** (`trading-system`, `-orchestrator`, `-research`,
   `-trader`, `-monitor`, `-risk`, `-eod`, `-backtest`).
2. **Create/reconcile the single `trading` profile** from `deploy/profile.yaml`:
   model + `fallback_model`, MCP `trading-tools` (`TRADING_TOOL_GROUPS=all`), Discord
   channel, `API_SERVER_KEY`, timezone.
3. **Ensure kanban boards** `equity` and `options` exist.
4. **Install crons** from `deploy/runs/*` + `deploy/runs/_shared.yaml` into the profile
   (idempotent: remove-then-add by name).
5. **Deploy cron scripts** (absolute paths) to the profile `scripts/` dir + shared.
6. **Start/restart the gateway** (the dispatcher lives there).
7. **Run preflight** and print a green/red summary.

Re-running on any machine converges to identical state. Per-machine one-time setup
(documented in `deploy/README.md`): populate `.env` (Alpaca + delivery), `hermes auth` /
`hermes model` for the provider, then `./install.sh hermes`. `install.sh --dry-run`
prints the full reconcile plan without making changes.

**Future asset separation:** set `profile: trading-options` in `deploy/runs/options.yaml`
and reinstall — `install.sh` provisions `trading-options` from the same `profile.yaml`
template. No logic change.

---

## 7. Risks & mitigations

- **Deleting 8 profiles is destructive.** Mitigation: user has explicitly approved;
  `hermes backup` before deletion; state lives in the repo + the shared `tools/trading.db`
  (not in profile dirs).
- **Single profile exposes the full 29-tool MCP set to every session.** Accepted: a few
  KB of schemas; `TRADING_TOOL_GROUPS` remains available if scoping is ever needed.
- **Moving `trading-morning-cycle-examples.md` could break the skill that loads it.**
  Mitigation: move + update reference atomically in one commit; grep for all referencers
  first.
- **Provider still dies until the user switches.** Accepted: preflight makes it loud and
  actionable; `fallback_model` can be configured as an interim cushion.
- **Two morning crons both run preflight (~5 min apart).** Accepted: preflight is cheap
  and mechanical; staggering avoids collision.

---

## 8. Verification

- `install.sh --dry-run` shows the complete reconcile plan.
- Post-install **preflight** is the green/red gate.
- `hermes profile list` shows exactly one `trading` profile.
- `hermes cron list` shows the new cron set and **no** `trading-kanban-tick`.
- `hermes kanban boards` shows `equity` and `options`.
- The 331-test suite stays green for any `tools/` changes.
- A manual `hermes -p trading chat` plus one idempotent morning-graph creation
  (run twice → no duplicate tasks) smoke-tests the cycle.

---

## 9. Open questions (for the plan, not blockers)

- Exact preflight remediation copy and which delivery channel (Discord vs Slack) is
  primary. A: suing discord for now, current discord connect with default profile and trading-orchestrator profile
- Whether `_shared.yaml` services should be their own tiny board for visibility, or stay
  boardless cron sessions (default: boardless).
- Risk-budget split between equity and options run-units (defaults from `config.yaml`).
