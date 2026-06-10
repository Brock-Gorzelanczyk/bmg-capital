"""
Backend Fixer Agent — generates and submits PRs for safe Python backend issues.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from sentinel.db.session import SessionLocal
from sentinel.settings import settings
from sentinel.guardrails import validate_fix_request
from sentinel.cost_tracker import trip_file_loop_breaker

logger = logging.getLogger(__name__)

SONNET = "claude-sonnet-4-6"

BACKEND_WHITELIST = {
    "missing_python_dependency",
    "import_path_error",
    "typing_annotation_error",
    "missing_return_statement",
    "syntax_error_simple",
}


def _post_discord(msg: str) -> None:
    if not settings.discord_sentinel_channel_id:
        return
    try:
        httpx.post(
            f"https://discord.com/api/v10/channels/{settings.discord_sentinel_channel_id}/messages",
            json={"content": msg},
            headers={"Authorization": f"Bot {settings.discord_bot_token}"},
            timeout=10,
        )
    except Exception as e:
        logger.warning("[backend-fixer] Discord post failed: %s", e)


class BackendFixerAgent:
    def handle(self, event_id: int, payload: dict) -> None:
        category = payload.get("category", "")
        file_path = payload.get("file", "")
        error_text = payload.get("error_text") or payload.get("error_block", "")

        if category not in BACKEND_WHITELIST:
            self._escalate(event_id, f"Category '{category}' not in backend whitelist")
            return

        allowed, reason = validate_fix_request(category, file_path)
        if not allowed:
            logger.info("[backend-fixer] Guardrail blocked event #%d: %s", event_id, reason)
            self._mark_failed(event_id, reason)
            return

        workdir = tempfile.mkdtemp(prefix=f"sentinel-be-{event_id}-")
        branch = f"sentinel-fix-{event_id}"

        try:
            self._run(event_id, payload, file_path, error_text, workdir, branch)
        except Exception as e:
            logger.error("[backend-fixer] Failed event #%d: %s", event_id, e, exc_info=True)
            trip_file_loop_breaker(SessionLocal(), file_path, str(e))
            self._mark_failed(event_id, str(e))
            self._escalate(event_id, f"Backend fixer exception: {e}")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _run(
        self,
        event_id: int,
        payload: dict,
        file_path: str,
        error_text: str,
        workdir: str,
        branch: str,
    ) -> None:
        repo_url = f"https://{settings.github_token}@github.com/{settings.github_repo}.git"

        _sh(["git", "clone", "--depth=1", repo_url, workdir])
        _sh(["git", "checkout", "-b", branch], cwd=workdir)

        abs_path = Path(workdir) / file_path
        if not abs_path.exists():
            raise ValueError(f"File not found: {file_path}")
        original_content = abs_path.read_text()

        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        prompt = (
            f"You are a precise code fixer for the BMG Capital Python backend.\n"
            f"Error: {error_text[:1500]}\n\n"
            f"File: {file_path}\n"
            f"Content:\n{original_content[:4000]}\n\n"
            "Produce the SMALLEST possible unified diff to fix this specific error.\n"
            "Do NOT modify any trading, strategy, bot, or execution logic.\n"
            "Do NOT touch files in strategy_lab/.\n"
            "Output ONLY the unified diff, nothing else."
        )
        response = client.messages.create(
            model=SONNET,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        diff_text = response.content[0].text.strip()
        cost = (response.usage.input_tokens * 3e-6) + (response.usage.output_tokens * 15e-6)

        if not diff_text or "---" not in diff_text:
            raise ValueError("LLM produced no valid diff")

        # Apply diff
        diff_file = Path(workdir) / "sentinel.patch"
        diff_file.write_text(diff_text)
        result = subprocess.run(
            ["patch", "-p1", "--dry-run", "-i", str(diff_file)],
            cwd=workdir, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise ValueError(f"Patch dry-run failed: {result.stderr[:300]}")
        _sh(["patch", "-p1", "-i", str(diff_file)], cwd=workdir)

        # Python syntax check on touched file
        abs_patched = Path(workdir) / file_path
        if abs_patched.suffix == ".py":
            check = subprocess.run(
                ["python", "-m", "py_compile", str(abs_patched)],
                capture_output=True, text=True
            )
            if check.returncode != 0:
                raise ValueError(f"py_compile failed after patch: {check.stderr[:200]}")

        _sh(["git", "config", "user.email", "sentinel@bmgcapital.app"], cwd=workdir)
        _sh(["git", "config", "user.name", "BMG Sentinel"], cwd=workdir)
        _sh(["git", "add", "-A"], cwd=workdir)
        _sh(["git", "commit", "-m", f"fix(sentinel): {payload.get('category','fix')} in {file_path}"], cwd=workdir)
        _sh(["git", "push", "origin", branch], cwd=workdir)

        pr = self._create_pr(branch, event_id, payload, diff_text)
        pr_number = pr.get("number")
        pr_url = pr.get("html_url", "")

        db = SessionLocal()
        try:
            from sqlalchemy import text
            db.execute(text("""
                INSERT INTO agent_fixes
                  (event_id, fixer_agent, pr_number, pr_url, files_changed, diff_summary, llm_model, cost_usd, status)
                VALUES (:eid, 'backend-fixer', :prn, :pru, :files, :diff, :model, :cost, 'proposed')
            """), {
                "eid": event_id, "prn": pr_number, "pru": pr_url,
                "files": [file_path], "diff": diff_text[:500],
                "model": SONNET, "cost": cost,
            })
            db.execute(text("UPDATE agent_events SET state = 'fix-proposed' WHERE id = :id"), {"id": event_id})
            db.commit()
        finally:
            db.close()

        _post_discord(f"🤖 PR #{pr_number} proposed for `{payload.get('category')}` — review at {pr_url}")
        logger.info("[backend-fixer] PR #%d created for event #%d", pr_number or 0, event_id)

    def _create_pr(self, branch: str, event_id: int, payload: dict, diff: str) -> dict:
        resp = httpx.post(
            f"https://api.github.com/repos/{settings.github_repo}/pulls",
            json={
                "title": f"Sentinel: fix {payload.get('category', 'error')} (event #{event_id})",
                "head": branch,
                "base": "main",
                "body": (
                    f"**Auto-generated by BMG Sentinel (backend)**\n\n"
                    f"Event ID: #{event_id}\n"
                    f"Category: `{payload.get('category')}`\n"
                    f"File: `{payload.get('file', 'unknown')}`\n\n"
                    f"**Error:**\n```\n{payload.get('error_text', '')[:500]}\n```\n\n"
                    f"**Diff:**\n```diff\n{diff[:800]}\n```\n\n"
                    f"> ⚠️ py_compile check passed. Review before merging."
                ),
            },
            headers={
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _escalate(self, event_id: int, reason: str) -> None:
        from sentinel.agents.escalator import EscalatorAgent
        EscalatorAgent().handle(event_id, reason)

    def _mark_failed(self, event_id: int, reason: str) -> None:
        db = SessionLocal()
        try:
            from sqlalchemy import text
            db.execute(text("""
                INSERT INTO agent_fixes (event_id, fixer_agent, diff_summary, status)
                VALUES (:eid, 'backend-fixer', :reason, 'failed')
            """), {"eid": event_id, "reason": reason[:200]})
            db.commit()
        finally:
            db.close()


def _sh(cmd: list[str], cwd: str | None = None) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"Command {cmd[0]} failed: {result.stderr[:300]}")
    return result.stdout
