from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.api.repositories import Repository
from apps.api.services.planning import PlanningService
from apps.api.services.provider_resolution import ProviderResolutionService, registered_domain, safe_hostname
from apps.api.services.verification import VerificationService


@dataclass
class OrchestrationService:
    repository: Repository
    provider_resolution_service: ProviderResolutionService
    planning_service: PlanningService
    execution_service: Any
    verification_service: VerificationService
    evidence_dir: Path

    def create_batch_from_urls(
        self,
        *,
        customer_id: str,
        urls: list[str],
        notes: str,
        auto_execute: bool,
        auto_verify: bool,
    ) -> dict[str, Any]:
        clean_urls = list(dict.fromkeys(url.strip() for url in urls if url.strip()))
        batch = self.repository.create_batch(customer_id=customer_id, notes=notes, total_urls=len(clean_urls))
        created_cases: list[dict[str, Any]] = []
        for url in clean_urls:
            hostname = safe_hostname(url)
            target_domain = registered_domain(hostname)
            evidence_path = self._write_placeholder_evidence(target_domain, url, notes)
            case_record = self.repository.create_case(
                customer_id=customer_id,
                target_url=url,
                target_domain=target_domain,
                evidence_path=str(evidence_path),
                notes=notes,
                batch_id=batch["id"],
            )
            self.process_case(case_record["id"], auto_execute=auto_execute, auto_verify=auto_verify)
            created_cases.append(self.repository.get_case(case_record["id"]))
        self.repository.update_batch_status_from_cases(batch["id"])
        return self.repository.get_batch_bundle(batch["id"])

    def process_case(self, case_id: int, *, auto_execute: bool, auto_verify: bool) -> dict[str, Any]:
        case_record = self.repository.get_case(case_id)
        resolution = self.provider_resolution_service.resolve(case_record["target_url"])
        self.repository.replace_provider_resolutions(case_id, resolution["providers"])
        providers = self.repository.list_provider_resolutions(case_id)
        actions = self.planning_service.plan(case_record=case_record, providers=providers)
        self.repository.replace_actions(case_id, actions)
        if auto_execute:
            self.execution_service.execute_case(case_id)
        if auto_verify:
            self.verify_case(case_id)
        return self.repository.get_case_bundle(case_id)

    def verify_case(self, case_id: int) -> dict[str, Any]:
        case_record = self.repository.get_case(case_id)
        result = self.verification_service.verify(case_record["target_url"])
        self.repository.add_verification(
            case_id=case_id,
            check_url=result["check_url"],
            verdict=result["verdict"],
            http_status=result["http_status"],
            detail=result["detail"],
        )
        return self.repository.get_case_bundle(case_id)

    def _write_placeholder_evidence(self, target_domain: str, target_url: str, notes: str) -> Path:
        path = self.evidence_dir / f"{target_domain.replace('.', '_')}-placeholder.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"案例截图占位文件\n目标 URL: {target_url}\n备注: {notes or '无'}\n",
            encoding="utf-8",
        )
        return path
