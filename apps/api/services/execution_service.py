from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.api.repositories import Repository
from apps.executors.email.adapter import EmailExecutorAdapter
from apps.executors.playwright.adapter import PlaywrightExecutorAdapter


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ExecutionService:
    repository: Repository
    storage_dir: Path

    def __post_init__(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.email_executor = EmailExecutorAdapter()
        self.playwright_executor = PlaywrightExecutorAdapter()

    def execute_case(self, case_id: int) -> dict[str, Any]:
        actions = self.repository.list_actions(case_id)
        case_record = self.repository.get_case(case_id)
        results: list[dict[str, Any]] = []

        for action in actions:
            if action["status"] == "NO_ROUTE_DEFINED":
                continue

            self.repository.update_action_status(action["id"], "RUNNING")
            started_at = utc_now()
            execution_context = self._build_context(case_record, action)

            if action["executor"] == "email":
                output = self.email_executor.execute(action, execution_context)
            elif action["executor"] == "playwright":
                output = self.playwright_executor.execute(action, execution_context)
            else:
                output = {
                    "result": "FAILED",
                    "external_ticket_id": "",
                    "detail": {"message": f"Unsupported executor: {action['executor']}"},
                    "error_code": "UNSUPPORTED_EXECUTOR",
                }

            finished_at = utc_now()
            detail = dict(output.get("detail", {}))
            artifact_path = self._write_run_artifact(case_id, action["id"], detail)
            detail["artifact_path"] = str(artifact_path)

            run = self.repository.create_execution_run(
                action_id=action["id"],
                executor=action["executor"],
                result=output["result"],
                external_ticket_id=output.get("external_ticket_id", ""),
                started_at=started_at,
                finished_at=finished_at,
                detail=detail,
                error_code=output.get("error_code", ""),
            )
            self.repository.update_action_status(action["id"], output["result"])
            results.append(run)

        self.repository.update_case_status_from_actions(case_id)
        return {"case": self.repository.get_case(case_id), "runs": results}

    def _build_context(self, case_record: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        run_dir = self.storage_dir / f"case-{case_record['id']}" / f"action-{action['id']}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return {
            "case_id": case_record["id"],
            "action_id": action["id"],
            "channel_id": action["channel_id"],
            "customer_id": case_record["customer_id"],
            "target_domain": case_record["target_domain"],
            "target_url": case_record["target_url"],
            "evidence_path": case_record["evidence_path"],
            "payload": action["payload"],
            "captcha_strategy": action["captcha_strategy"],
            "run_dir": str(run_dir),
        }

    def _write_run_artifact(self, case_id: int, action_id: int, detail: dict[str, Any]) -> Path:
        case_dir = self.storage_dir / f"case-{case_id}"
        case_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = case_dir / f"action-{action_id}.json"
        artifact_path.write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
        return artifact_path
