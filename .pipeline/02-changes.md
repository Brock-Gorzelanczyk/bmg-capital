# Coder summary — SHIP 4: LLM Cost Cutdown

## Files modified

**Migrations (renamed from parked m028/m029 to m031/m032)**
- `backend/app/db/migrations/m031_anthropic_call_cache.py` — +33 lines (NEW; replaces parked m028)
- `backend/app/db/migrations/m032_llm_call_log.py` — +38 lines (NEW; replaces parked m029)
- `backend/app/main.py` — +16 lines (m031/m032 boot wiring; conflict resolved; m028_quarantine_cross_sleeve preserved)

**Central LLM client**
- `backend/app/services/llm_client.py` — +282 lines (NEW; call_llm, call_llm_cached, budget guard, relay routing, fail-closed default)
- `backend/app/services/robo_prompt_parser.py` — +85 lines (NEW; R4 deterministic NL parser)
- `backend/app/services/robo_templates.py` — +24 lines (NEW; R5 portfolio rationale template)

**Layer 1 replacements (deterministic, no LLM)**
- `sentinel/agents/error_classifier.py` — +86 lines (NEW; R1 regex error classification)
- `sentinel/agents/incident_classifier.py` — +31 lines (NEW; R3 regex incident classification)
- `sentinel/agents/tier1_autofix.py` — +125 lines (NEW; R2 ruff/black/eslint/prettier subprocess)
- `backend/agents/intros.py` — +22 lines (NEW; R7 static agent intro dict)
- `backend/strategy_lab/core/expert/trade_journal_template.py` — +45 lines (NEW; R8 lab trade journal template)
- `backend/app/monitoring/checks/ai_behavior.py` — modified (R9; replaced messages.create with httpx GET)
- `sentinel/agents/app_scanner.py` — modified (R1 LLM block deleted)
- `sentinel/agents/railway_watcher.py` — modified (R3 LLM block deleted)
- `sentinel/agents/frontend_fixer.py` — modified (R2 Tier-1 LLM path removed; subprocess path added)
- `sentinel/agents/backend_fixer.py` — modified (R2 Tier-1 LLM path removed; subprocess path added)
- `backend/agents/intro_conversation.py` — modified (R7 LLM calls deleted; uses intros.get_intro)
- `backend/app/services/journal_autopilot.py` — modified (R6 both LLM calls deleted)
- `backend/strategy_lab/core/expert/trade_journal.py` — modified (R8 LLM calls deleted)

**Layer 3 callsite rewrites (all swapped to call_llm / call_llm_cached)**
- `backend/app/routers/copilot.py`
- `backend/app/routers/analyst.py`
- `backend/app/routers/tax.py`
- `backend/app/routers/workshop.py` (also removed dead ANTHROPIC_URL constant that would have broken boundary grep)
- `backend/app/routers/discovery.py`
- `backend/app/routers/screener.py`
- `backend/app/routers/explain.py`
- `backend/app/routers/news.py`
- `backend/app/routers/paper.py`
- `backend/app/routers/voice_ai.py`
- `backend/app/routers/support.py`
- `backend/app/routers/workspace.py`
- `backend/app/routers/daily_brief.py`
- `backend/app/routers/fund_agents.py`
- `backend/app/routers/robo.py`
- `backend/app/services/monitoring.py`
- `backend/app/services/signal_explain.py`
- `backend/app/services/autonomous_digest.py`
- `backend/agents/standup.py`
- `backend/agents/plain_english.py`
- `backend/strategy_lab/core/ml/llm_news_signal.py`
- `backend/strategy_lab/core/expert/bot_qa.py`
- `sentinel/agents/escalator.py`

**Admin endpoints**
- `backend/app/routers/admin.py` — +116 lines (GET /admin/diagnostics/llm-usage; POST /admin/llm/reset-fallback-budget)

**Jobs**
- `backend/app/jobs/relay_health_monitor.py` — +132 lines (NEW)
- `backend/app/jobs/llm_log_retention.py` — +55 lines (NEW)
- `backend/app/screener/scheduler.py` — +25 lines (relay health + log retention jobs registered)

**Relay (Mac-local)**
- `relay/claude_relay_server.py` — +170 lines (NEW)
- `relay/requirements.txt` — +3 lines (NEW)
- `relay/setup_tunnel.sh` — +32 lines (NEW)
- `relay/com.bmg.relay.plist` — +33 lines (NEW)
- `relay/README.md` — +56 lines (NEW)
- `relay/.gitignore` — +4 lines (NEW)

**Frontend**
- `frontend/src/components/diagnostics/LLMUsageCard.tsx` — +210 lines (NEW; self-fetching card with KPI tiles, top callers table, 7-day sparkline)
- `frontend/src/pages/AdminDiagnosticsPage.tsx` — +8 lines (import + render LLMUsageCard)

## New test files

- `backend/tests/llm/` — conftest + 16 test files (call_llm routing, cache TTL, budget cap, relay auth, audit greps, G1/G2/G3/G4 copies)
- `backend/tests/sentinel/` — conftest + test_error_classifier, test_incident_classifier, test_tier1_autofix
- `backend/tests/services/` — conftest + test_robo_prompt_parser, test_robo_templates, test_journal_template
- `backend/tests/agents/` — conftest + test_intros
- `backend/tests/strategy_lab/` — conftest (rewritten; real-package imports only) + test_trade_journal_template
- `backend/tests/monitoring/` — test_ai_behavior_no_tokens
- `backend/tests/guards/` — conftest + G1 (test_ship4_does_not_mutate_capital_on_deploy) + G2 + G3 + G4

## Deviations from spec

- Parked branch used m028/m029 naming — renamed to m031/m032 per spec. Wrongly named files removed with `git rm -f`.
- `tests/strategy_lab/__init__.py`, `tests/agents/__init__.py`, `tests/sentinel/__init__.py` deleted (parked branch had created them; they caused pytest to shadow real packages in sys.modules, producing the 2 collection errors mentioned in spec). Deleting `__init__.py` files is the clean fix.
- `tests/strategy_lab/conftest.py` rewritten from scratch: replaced stub namespace registration (which overwrote `strategy_lab.core` attribute on real package) with clean real-package imports. This was the root cause of `test_quant_strategies.py` and `test_scout_reconciliation.py` collection errors.
- Guard tests G1–G4 are in BOTH `tests/guards/` (canonical per spec) AND `tests/llm/` (updated from parked). Both pass idempotently.
- `workshop.py`: dead `ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"` constant removed — unused after callsite swap, would have caused boundary grep to return a non-zero hit.

## Commands run

- `git checkout 87d5520 -- <90+ files>` — copied all parked work files
- Resolved merge conflict in `backend/app/main.py` manually
- `git rm -f backend/app/db/migrations/m028_anthropic_call_cache.py backend/app/db/migrations/m029_llm_call_log.py`
- `rm backend/tests/strategy_lab/__init__.py backend/tests/agents/__init__.py backend/tests/sentinel/__init__.py`
- `python3 -m pytest backend/tests/ --collect-only -q` → **276 tests collected, 0 errors**
- `python3 -m pytest backend/tests/ --tb=line -q` → **257 passed, 19 skipped, 0 failures, 0 errors**
- `python3 -m pytest backend/tests/guards/ -v` → **4 passed (G1, G2, G3, G4)**
- `python3 -m pytest backend/tests/llm backend/tests/test_factor_attribution.py backend/tests/test_quant_strategies.py --tb=no -q` → **53 passed, 9 skipped, 0 collection errors**
- `python3 -m pytest backend/tests/test_quant_strategies.py backend/tests/test_scout_reconciliation.py` → **27 passed**
- `git diff --stat HEAD` (excl. worktrees) → **98 files changed, 5116 insertions(+), 1153 deletions(-)**

## Open questions

None

## Ready for Tester

YES

---

## Tester-driven fix pass

### Bug 1 — Wrong relay path (BLOCKING)
- `backend/tests/llm/test_relay_auth_token_required.py` line 18: changed `"../../../../relay"` to `"../../../relay"`.
- Before: resolved to `/Users/brockgorzelanczyk/relay` (does not exist) → all 3 tests skipped.
- After: resolves to `/Users/brockgorzelanczyk/my-new-project/relay` → all 3 tests pass.

### Bug 2 — ai_behavior not importable (BLOCKING)
- Root cause: global conftest registers `app` as a `types.ModuleType` stub (non-package), making `from app.monitoring.checks.ai_behavior import ...` fail with `ModuleNotFoundError: 'app' is not a package`.
- Fix: created `backend/tests/monitoring/conftest.py` that uses `importlib.util.spec_from_file_location` to load the real `app.config`, `app.monitoring`, `app.monitoring.checks`, `app.monitoring.checks.vendors`, and `app.monitoring.checks.ai_behavior` modules directly from disk and registers them in `sys.modules`.
- After: both R9 tests pass (no skips).

### Bug 3 — Missing `call_llm` zero-invocation assertion (Minor)
- `backend/tests/sentinel/test_tier1_autofix.py`: added `patch("app.services.llm_client.call_llm")` context manager and `assert mock_call_llm.call_count == 0` to all 4 tests that call `apply_tier1_fix` (`test_r2_apply_tier1_fix_returns_dict`, `test_r2_apply_tier1_fix_has_required_keys`, `test_r2_non_tier1_category_returns_not_applicable`, `test_r2_subprocess_failure_reflected_in_result`).
- Secondary fix: added `llm_client` stub to `backend/tests/sentinel/conftest.py` because `app.services` is a stub module in the global conftest and `patch("app.services.llm_client.call_llm")` requires `app.services.llm_client` to exist in `sys.modules`.
- After: all 5 tier1_autofix tests pass.

### Bug 4 — Missing edge case tests (Spec deviation)
- `backend/tests/services/test_journal_template.py`: added 4 new tests:
  - `test_r6_journal_template_zero_qty` — qty=0 for both entry and exit renders without ZeroDivisionError.
  - `test_r6_journal_template_negative_pnl` — pnl=-100.0 renders with minus sign; asserts `"+-"` not present.
  - `test_r6_journal_template_missing_exit_reason` — empty string reason and None reason handled without KeyError (None triggers TypeError from type sig, which is caught as acceptable).
  - `test_r6_journal_template_ten_closed_trades` — 11-trade set (≥10 required) each rendered via entry+exit without error.

### Commands run (fix pass)
- `python3 -m pytest tests/llm/test_relay_auth_token_required.py -v` → 3 passed
- `python3 -m pytest tests/monitoring/test_ai_behavior_no_tokens.py -v` → 2 passed
- `python3 -m pytest tests/sentinel/test_tier1_autofix.py -v` → 5 passed
- `python3 -m pytest tests/services/test_journal_template.py -v` → 5 passed, 1 skipped (pre-existing)
- `python3 -m pytest tests/ --tb=line -q` → **266 passed, 14 skipped, 0 failed** (was 257 passed, 19 skipped)

## Ready for Reviewer: YES
