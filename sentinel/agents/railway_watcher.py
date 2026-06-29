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
from sentinel.agents.incident_classifier import classify_incident

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


# _classify_error replaced by classify_incident() from incident_classifier.py (R3 — SHIP 3)


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

        classification = classify_incident(error_block)
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
