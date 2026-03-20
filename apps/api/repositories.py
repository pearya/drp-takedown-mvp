from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from apps.api.database import Database


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def decode_json(payload: str) -> Any:
    return json.loads(payload) if payload else None


@dataclass
class Repository:
    database: Database

    def create_batch(self, *, customer_id: str, notes: str, total_urls: int) -> dict[str, Any]:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO batches (customer_id, notes, total_urls, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (customer_id, notes, total_urls, "NEW", now, now),
            )
            connection.commit()
            return self.get_batch(cursor.lastrowid)

    def get_batch(self, batch_id: int) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
        if row is None:
            raise KeyError(f"Batch {batch_id} not found")
        return dict(row)

    def list_batches(self) -> list[dict[str, Any]]:
        query = """
        SELECT
            b.*,
            (SELECT COUNT(*) FROM batch_case_map bcm WHERE bcm.batch_id = b.id) AS case_count,
            (
                SELECT COUNT(*)
                FROM batch_case_map bcm
                INNER JOIN cases c ON c.id = bcm.case_id
                WHERE bcm.batch_id = b.id AND c.status = 'SUCCESS'
            ) AS success_cases,
            (
                SELECT COUNT(*)
                FROM batch_case_map bcm
                INNER JOIN case_verifications cv ON cv.case_id = bcm.case_id
                WHERE bcm.batch_id = b.id
                  AND cv.id IN (
                    SELECT MAX(id) FROM case_verifications cv2 WHERE cv2.case_id = cv.case_id
                  )
                  AND cv.verdict IN ('DOWN_CONFIRMED', 'ACCESS_BLOCKED')
            ) AS takedown_positive_cases
        FROM batches b
        ORDER BY b.id DESC
        """
        with self.database.connect() as connection:
            rows = connection.execute(query).fetchall()
        return [dict(row) for row in rows]

    def attach_case_to_batch(self, batch_id: int, case_id: int) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO batch_case_map (batch_id, case_id) VALUES (?, ?)",
                (batch_id, case_id),
            )
            connection.commit()
        self.update_batch_status_from_cases(batch_id)

    def cases_for_batch(self, batch_id: int) -> list[dict[str, Any]]:
        query = """
        SELECT c.*
        FROM cases c
        INNER JOIN batch_case_map bcm ON bcm.case_id = c.id
        WHERE bcm.batch_id = ?
        ORDER BY c.id DESC
        """
        with self.database.connect() as connection:
            rows = connection.execute(query, (batch_id,)).fetchall()
        return [self._enrich_case_row(dict(row)) for row in rows]

    def create_case(
        self,
        *,
        customer_id: str,
        target_url: str,
        target_domain: str,
        evidence_path: str,
        notes: str,
        batch_id: int | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO cases (
                    customer_id,
                    target_url,
                    target_domain,
                    evidence_path,
                    notes,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    customer_id,
                    target_url,
                    target_domain,
                    evidence_path,
                    notes,
                    "NEW",
                    now,
                    now,
                ),
            )
            case_id = cursor.lastrowid
            if batch_id is not None:
                connection.execute(
                    "INSERT OR IGNORE INTO batch_case_map (batch_id, case_id) VALUES (?, ?)",
                    (batch_id, case_id),
                )
            connection.commit()
        if batch_id is not None:
            self.update_batch_status_from_cases(batch_id)
        return self.get_case(case_id)

    def set_case_status(self, case_id: int, status: str) -> None:
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE cases SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, case_id),
            )
            connection.commit()
        batch_id = self.batch_id_for_case(case_id)
        if batch_id is not None:
            self.update_batch_status_from_cases(batch_id)

    def batch_id_for_case(self, case_id: int) -> int | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT batch_id FROM batch_case_map WHERE case_id = ?", (case_id,)).fetchone()
        return int(row[0]) if row else None

    def get_case(self, case_id: int) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise KeyError(f"Case {case_id} not found")
        return self._enrich_case_row(dict(row))

    def list_cases(self) -> list[dict[str, Any]]:
        query = """
        SELECT c.*
        FROM cases c
        ORDER BY c.id DESC
        """
        with self.database.connect() as connection:
            rows = connection.execute(query).fetchall()
        return [self._enrich_case_row(dict(row)) for row in rows]

    def _enrich_case_row(self, case_row: dict[str, Any]) -> dict[str, Any]:
        case_id = case_row["id"]
        with self.database.connect() as connection:
            case_row["provider_count"] = connection.execute(
                "SELECT COUNT(*) FROM provider_resolutions WHERE case_id = ?",
                (case_id,),
            ).fetchone()[0]
            case_row["action_count"] = connection.execute(
                "SELECT COUNT(*) FROM channel_actions WHERE case_id = ?",
                (case_id,),
            ).fetchone()[0]
            case_row["run_count"] = connection.execute(
                """
                SELECT COUNT(*)
                FROM execution_runs er
                INNER JOIN channel_actions ca ON ca.id = er.action_id
                WHERE ca.case_id = ?
                """,
                (case_id,),
            ).fetchone()[0]
            latest_verification = connection.execute(
                """
                SELECT verdict, http_status, checked_at
                FROM case_verifications
                WHERE case_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (case_id,),
            ).fetchone()
            batch_row = connection.execute(
                "SELECT batch_id FROM batch_case_map WHERE case_id = ? LIMIT 1",
                (case_id,),
            ).fetchone()
        case_row["batch_id"] = int(batch_row[0]) if batch_row else None
        case_row["verification"] = dict(latest_verification) if latest_verification else None
        return case_row

    def replace_provider_resolutions(self, case_id: int, providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            connection.execute("DELETE FROM provider_resolutions WHERE case_id = ?", (case_id,))
            for provider in providers:
                connection.execute(
                    """
                    INSERT INTO provider_resolutions (
                        case_id,
                        role,
                        provider_key,
                        provider_name,
                        confidence,
                        sources_json,
                        metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case_id,
                        provider["role"],
                        provider["provider_key"],
                        provider["provider_name"],
                        provider["confidence"],
                        encode_json(provider.get("source", [])),
                        encode_json(provider.get("metadata", {})),
                    ),
                )
            connection.commit()
        self.set_case_status(case_id, "ENRICHED")
        return self.list_provider_resolutions(case_id)

    def list_provider_resolutions(self, case_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM provider_resolutions WHERE case_id = ? ORDER BY id ASC",
                (case_id,),
            ).fetchall()
        providers = [dict(row) for row in rows]
        for provider in providers:
            provider["source"] = decode_json(provider.pop("sources_json"))
            provider["metadata"] = decode_json(provider.pop("metadata_json"))
        return providers

    def replace_actions(self, case_id: int, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute(
                "DELETE FROM execution_runs WHERE action_id IN (SELECT id FROM channel_actions WHERE case_id = ?)",
                (case_id,),
            )
            connection.execute("DELETE FROM channel_actions WHERE case_id = ?", (case_id,))
            for action in actions:
                connection.execute(
                    """
                    INSERT INTO channel_actions (
                        case_id,
                        provider_role,
                        provider_key,
                        provider_name,
                        channel_id,
                        route_type,
                        executor,
                        region,
                        language,
                        status,
                        captcha_strategy,
                        requires_login,
                        payload_json,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case_id,
                        action["provider_role"],
                        action["provider_key"],
                        action["provider_name"],
                        action["channel_id"],
                        action["route_type"],
                        action["executor"],
                        action["region"],
                        action["language"],
                        action["status"],
                        action["captcha_strategy"],
                        1 if action["requires_login"] else 0,
                        encode_json(action["payload"]),
                        now,
                        now,
                    ),
                )
            connection.commit()
        self.set_case_status(case_id, "PLANNED")
        return self.list_actions(case_id)

    def list_actions(self, case_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM channel_actions WHERE case_id = ? ORDER BY id ASC",
                (case_id,),
            ).fetchall()
        actions = [dict(row) for row in rows]
        for action in actions:
            action["requires_login"] = bool(action["requires_login"])
            action["payload"] = decode_json(action.pop("payload_json"))
        return actions

    def update_action_status(self, action_id: int, status: str) -> None:
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE channel_actions SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, action_id),
            )
            connection.commit()

    def create_execution_run(
        self,
        *,
        action_id: int,
        executor: str,
        result: str,
        external_ticket_id: str,
        started_at: str,
        finished_at: str,
        detail: dict[str, Any],
        error_code: str = "",
    ) -> dict[str, Any]:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO execution_runs (
                    action_id,
                    executor,
                    result,
                    external_ticket_id,
                    started_at,
                    finished_at,
                    detail_json,
                    error_code
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    executor,
                    result,
                    external_ticket_id,
                    started_at,
                    finished_at,
                    encode_json(detail),
                    error_code,
                ),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM execution_runs WHERE id = ?", (cursor.lastrowid,)).fetchone()
        run = dict(row)
        run["detail"] = decode_json(run.pop("detail_json"))
        return run

    def list_runs_for_case(self, case_id: int) -> list[dict[str, Any]]:
        query = """
        SELECT er.*, ca.case_id, ca.channel_id, ca.provider_name, ca.provider_role
        FROM execution_runs er
        INNER JOIN channel_actions ca ON ca.id = er.action_id
        WHERE ca.case_id = ?
        ORDER BY er.id DESC
        """
        with self.database.connect() as connection:
            rows = connection.execute(query, (case_id,)).fetchall()
        runs = [dict(row) for row in rows]
        for run in runs:
            run["detail"] = decode_json(run.pop("detail_json"))
        return runs

    def add_verification(
        self,
        *,
        case_id: int,
        check_url: str,
        verdict: str,
        http_status: str,
        detail: dict[str, Any],
    ) -> dict[str, Any]:
        checked_at = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO case_verifications (case_id, check_url, verdict, http_status, checked_at, detail_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (case_id, check_url, verdict, http_status, checked_at, encode_json(detail)),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM case_verifications WHERE id = ?", (cursor.lastrowid,)).fetchone()
        verification = dict(row)
        verification["detail"] = decode_json(verification.pop("detail_json"))
        return verification

    def list_verifications(self, case_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM case_verifications WHERE case_id = ? ORDER BY id DESC",
                (case_id,),
            ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["detail"] = decode_json(item.pop("detail_json"))
        return items

    def latest_verification(self, case_id: int) -> dict[str, Any] | None:
        items = self.list_verifications(case_id)
        return items[0] if items else None

    def get_case_bundle(self, case_id: int) -> dict[str, Any]:
        return {
            "case": self.get_case(case_id),
            "providers": self.list_provider_resolutions(case_id),
            "actions": self.list_actions(case_id),
            "runs": self.list_runs_for_case(case_id),
            "verifications": self.list_verifications(case_id),
            "latest_verification": self.latest_verification(case_id),
        }

    def get_batch_bundle(self, batch_id: int) -> dict[str, Any]:
        return {
            "batch": self.get_batch(batch_id),
            "cases": self.cases_for_batch(batch_id),
        }

    def update_case_status_from_actions(self, case_id: int) -> str:
        actions = self.list_actions(case_id)
        if not actions:
            status = "NEW"
        else:
            states = {action["status"] for action in actions}
            if states == {"SUCCESS"}:
                status = "SUCCESS"
            elif "WAITING_HUMAN" in states:
                status = "WAITING_HUMAN"
            elif "FAILED" in states and states.issubset({"FAILED", "NO_ROUTE_DEFINED"}):
                status = "FAILED"
            elif "SUCCESS" in states or "WAITING_HUMAN" in states:
                status = "PARTIAL_SUCCESS"
            elif "RUNNING" in states:
                status = "RUNNING"
            else:
                status = "PLANNED"
        self.set_case_status(case_id, status)
        return status

    def update_batch_status_from_cases(self, batch_id: int) -> str:
        cases = self.cases_for_batch(batch_id)
        if not cases:
            status = "NEW"
        else:
            states = {case["status"] for case in cases}
            if states == {"SUCCESS"}:
                status = "SUCCESS"
            elif "WAITING_HUMAN" in states:
                status = "WAITING_HUMAN"
            elif "FAILED" in states and len(states) == 1:
                status = "FAILED"
            elif "SUCCESS" in states or "PARTIAL_SUCCESS" in states:
                status = "PARTIAL_SUCCESS"
            elif "RUNNING" in states:
                status = "RUNNING"
            else:
                status = "PLANNED"
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE batches SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, batch_id),
            )
            connection.commit()
        return status

    def stats(self) -> dict[str, Any]:
        with self.database.connect() as connection:
            total_cases = connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
            total_actions = connection.execute("SELECT COUNT(*) FROM channel_actions").fetchone()[0]
            total_runs = connection.execute("SELECT COUNT(*) FROM execution_runs").fetchone()[0]
            total_batches = connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0]
            latest_verdicts = connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT case_id, MAX(id) AS id
                    FROM case_verifications
                    GROUP BY case_id
                ) lv
                INNER JOIN case_verifications cv ON cv.id = lv.id
                WHERE cv.verdict IN ('DOWN_CONFIRMED', 'ACCESS_BLOCKED')
                """
            ).fetchone()[0]
        return {
            "total_cases": total_cases,
            "total_actions": total_actions,
            "total_runs": total_runs,
            "total_batches": total_batches,
            "positive_verifications": latest_verdicts,
        }
