"""
Railway Watcher Agent — polls Railway API every 30s for failed deployments.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

import httpx

from sentinel.db.session import SessionLocal
from sentinel.orchestrator import insert_event, route_event, mark_resolved
from sentinel.settings import settings

logger = logging.getLogger(__name__)

RAILWAY_API = "https://backboard.railway.app/graphql/v2"

DEPLOYMENTS_QUERY = """
query Deployments($projectId: String!, $serviceId: String!) {
  deployments(
    input: { projectId: $projectId, serviceId: $serviceId }
    last: 20
  ) {
    edges {
      node {
        id
        status
        createdAt
        meta {
          commitMessage
          commitHash
        }
      }
    }
  }
}
"""

BUILD_LOGS_QUERY = """
query BuildLogs($deploymentId: String!) {
  buildLogs(deploymentId: $deploymentId, limit: 200) {
    message
    severity
    timestamp
  }
}
"""


def _fingerprint(deploy_id: str, first_error_line: str) -> str:
    raw = f"railway:{deploy_id}:{first_error_line[:120]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _gql(query: str, variables: dict) -> dict:
    resp = httpx.post(
        RAILWAY_API,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {settings.railway_api_token}"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def _classify_error(error_block: str) -> dict:
    """Use Haiku to classify a build error."""
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        system=(
            "You classify Railway build errors for an automated fix system. "
            "Output ONLY valid JSON with keys: category, file, line, suggested_fix_type. "
            "category must be one of: typescript_missing_property, missing_npm_dependency, "
            "missing_python_dependency, syntax_error_simple, eslint_warning, broken_image_url, "
            "dead_link, css_class_typo, import_path_wrong, other. "
            "file is the offending file path or empty string. line is int or 0."
        ),
        messages=[{"role": "user", "content": f"Build error:\n{error_block[:2000]}"}],
    )
    import json
    try:
        return json.loads(msg.content[0].text)
    except Exception:
        return {"category": "other", "file": "", "line": 0, "suggested_fix_type": "unknown"}


def _extract_error_block(logs: list[dict]) -> str:
    """Find the first 50 lines around the first 'error' keyword."""
    lines = [l.get("message", "") for l in logs]
    for i, line in enumerate(lines):
        if "error" in line.lower():
            start = max(0, i - 5)
            end = min(len(lines), i + 45)
            return "\n".join(lines[start:end])
    return "\n".join(lines[:50])


class RailwayWatcher:
    def run(self) -> None:
        if not settings.sentinel_enabled:
            return
        if not settings.railway_api_token:
            logger.debug("[railway-watcher] No token configured, skipping")
            return
        try:
            self._check_deployments()
        except Exception as e:
            logger.error("[railway-watcher] Error: %s", e, exc_info=True)

    def _check_deployments(self) -> None:
        data = _gql(DEPLOYMENTS_QUERY, {
            "projectId": settings.railway_project_id,
            "serviceId": settings.railway_service_id,
        })
        edges = data.get("data", {}).get("deployments", {}).get("edges", [])

        for edge in edges:
            node = edge["node"]
            status = node.get("status", "")
            deploy_id = node["id"]

            if status == "FAILED":
                self._handle_failed(node)
            elif status == "SUCCESS":
                # Resolve any open events for this deploy fingerprint
                first_error_line = node.get("meta", {}).get("commitMessage", deploy_id)
                fp = _fingerprint(deploy_id, first_error_line)
                mark_resolved(fp)

    def _handle_failed(self, node: dict) -> None:
        deploy_id = node["id"]
        try:
            logs_data = _gql(BUILD_LOGS_QUERY, {"deploymentId": deploy_id})
            logs = logs_data.get("data", {}).get("buildLogs", [])
        except Exception as e:
            logger.warning("[railway-watcher] Could not fetch logs for %s: %s", deploy_id, e)
            logs = []

        error_block = _extract_error_block(logs)
        first_line = error_block.split("\n")[0] if error_block else deploy_id
        fp = _fingerprint(deploy_id, first_line)

        classification = _classify_error(error_block)
        category = classification.get("category", "other")
        file_path = classification.get("file", "")

        payload = {
            "deploy_id": deploy_id,
            "error_block": error_block[:3000],
            "file": file_path,
            "line": classification.get("line", 0),
            "suggested_fix_type": classification.get("suggested_fix_type", ""),
            "commit_message": node.get("meta", {}).get("commitMessage", ""),
        }

        db = SessionLocal()
        try:
            event_id = insert_event(
                db=db,
                agent_id="railway-watcher",
                severity="critical",
                category=category,
                fingerprint=fp,
                payload=payload,
            )
        finally:
            db.close()

        if event_id:
            route_event(event_id, category, payload)
