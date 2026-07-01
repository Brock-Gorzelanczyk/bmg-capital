"""Regression: bot_heartbeat.last_scan_at must be written even when
scan_and_execute crashes.

2026-06-30 (evening) incident context: crypto_onchain's scheduler job is
correctly registered in bot_scheduler.py:370, yet its bot_heartbeat.last_scan_at
has been stuck at 2026-06-08T21:33 for 22 days. PR #48 (shipped morning of
2026-06-30) moved the heartbeat write out of the signal-fired conditional but
kept it INSIDE the try block wrapping scan_and_execute — meaning any scan
crash silently skipped the write. Result: we can't distinguish "scheduler
never fired" from "scheduler fired but scan crashed", masking the real bug.

Fix: heartbeat write moved to the outer `finally` block so it fires whether
scan_and_execute succeeds or raises. Ownership of database session close also
moves into the inner finally so heartbeat's own commit doesn't get
inadvertently dropped.

Structural guard (grep only — running the actual scheduler needs the full
service context).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"


def test_heartbeat_write_lives_in_finally_block():
    """The bot_heartbeat write must be reachable from the outer finally in
    _run_and_log so a scan_and_execute crash still updates the timestamp.
    """
    src = (BACKEND / "strategy_lab" / "bot_scheduler.py").read_text()
    # Locate _run_and_log
    fn_start = src.find("def _run_and_log(")
    assert fn_start > 0, "Could not locate _run_and_log"
    fn_end = src.find("\ndef ", fn_start + 1)
    fn_body = src[fn_start:fn_end]

    # There MUST be a finally block after the outer except (line matches "except Exception as exc:").
    outer_except = re.search(r"except Exception as exc:", fn_body)
    assert outer_except, "Outer exception handler missing"
    finally_after_outer = fn_body.find("finally:", outer_except.end())
    assert finally_after_outer > 0, (
        "_run_and_log must have a finally block after the outer except so the "
        "heartbeat write fires whether scan succeeds or crashes. Regression of "
        "2026-06-30 evening fix."
    )
    # The heartbeat write must be inside that finally block (before the next def).
    heartbeat_pos = fn_body.find("INSERT INTO bot_heartbeat", finally_after_outer)
    assert heartbeat_pos > 0, (
        "bot_heartbeat INSERT must live inside the outer finally block of "
        "_run_and_log so it fires on scan crash"
    )


def test_heartbeat_write_is_not_inside_scan_success_path():
    """The heartbeat write must NOT be conditional on scan_and_execute
    succeeding — that was the pre-fix behavior that silently skipped the
    write on crash. This test guards against reversion.
    """
    src = (BACKEND / "strategy_lab" / "bot_scheduler.py").read_text()
    fn_start = src.find("def _run_and_log(")
    fn_end = src.find("\ndef ", fn_start + 1)
    fn_body = src[fn_start:fn_end]

    # Find "result = scan_and_execute(" — the heartbeat write must NOT appear
    # in the code block that only runs after this call succeeds.
    scan_call = re.search(r"result\s*=\s*scan_and_execute\(", fn_body)
    assert scan_call, "scan_and_execute call missing from _run_and_log"

    # Find the FIRST `except` block after the scan call (marks end of success
    # code block). Heartbeat write must NOT appear between scan_call and that
    # except; it should be later in finally.
    except_after_scan = fn_body.find("except Exception as e:", scan_call.end())
    success_block = fn_body[scan_call.end():except_after_scan]
    assert "INSERT INTO bot_heartbeat" not in success_block, (
        "heartbeat INSERT is still in the success-only block after "
        "scan_and_execute — regression of the pre-fix bug where a scan crash "
        "silently skipped the heartbeat update"
    )
