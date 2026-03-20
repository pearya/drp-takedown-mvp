from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path
from typing import Any

from apps.executors.playwright.namesilo_phishing_report_recorder import RecorderInput, run_recording


def _pick_proof_image(attachments: list[dict[str, Any]], fallback: str) -> str:
    allowed = {".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff"}
    for item in attachments:
        path = (item or {}).get("path", "")
        if not path:
            continue
        suffix = Path(path).suffix.lower()
        if suffix in allowed and Path(path).exists():
            return str(Path(path).resolve())
    if fallback and Path(fallback).exists():
        suffix = Path(fallback).suffix.lower()
        if suffix in allowed:
            return str(Path(fallback).resolve())
    return ""


@dataclass
class NameSiloPhishingChannel:
    def execute(self, action: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        payload = action.get("payload", {})
        reporter_email = payload.get("reporter_email", "").strip()
        real_website = payload.get("real_website", "").strip()
        phishing_website = payload.get("phishing_website", "").strip() or context.get("target_url", "")
        report_text = payload.get("preview_body", "").strip()

        if not reporter_email or not real_website or not phishing_website or not report_text:
            return {
                "result": "FAILED",
                "external_ticket_id": "",
                "error_code": "MISSING_REQUIRED_FORM_FIELDS",
                "detail": {
                    "message": "NameSilo required fields are missing. Need email, real_website, phishing_website, report_text.",
                    "reporter_email": reporter_email,
                    "real_website": real_website,
                    "phishing_website": phishing_website,
                },
            }

        attachments = payload.get("attachments", [])
        proof_image = _pick_proof_image(attachments, context.get("evidence_path", ""))
        if not proof_image:
            return {
                "result": "FAILED",
                "external_ticket_id": "",
                "error_code": "MISSING_PHISHING_SCREENSHOT",
                "detail": {
                    "message": "NameSilo form requires one screenshot image (jpg/png/gif/tif).",
                    "attachments": attachments,
                },
            }

        run_dir = Path(context.get("run_dir", ".")).resolve()
        run_output_dir = run_dir / "namesilo"
        input_payload = RecorderInput(
            email=reporter_email,
            real_website=real_website,
            phishing_website=phishing_website,
            report_text=report_text,
            proof_image=proof_image,
        )

        try:
            # This executor intentionally does not solve CAPTCHA with third-party services.
            record_result = run_recording(
                page_url=payload.get("entry_url", "https://www.namesilo.com/phishing-report"),
                data=input_payload,
                two_captcha_api_key="",
                submit_form=True,
                skip_captcha=True,
                headless=False,
                min_captcha_token_length=100,
                output_dir=run_output_dir,
            )
        except Exception as exc:
            return {
                "result": "FAILED",
                "external_ticket_id": "",
                "error_code": "NAMESILO_EXECUTION_ERROR",
                "detail": {
                    "message": f"NameSilo execution failed: {exc}",
                    "entry_url": payload.get("entry_url", ""),
                    "proof_image": proof_image,
                    "run_dir": str(run_output_dir),
                },
            }

        ticket_seed = f"{context['case_id']}:{context['action_id']}:{context['target_domain']}"
        external_ticket_id = f"NAMESILO-{sha1(ticket_seed.encode('utf-8')).hexdigest()[:10].upper()}"
        artifacts = record_result.get("artifacts", {})
        submitted = bool(record_result.get("submitted"))
        submit_guard_reason = record_result.get("submit_guard_reason", "")

        if submitted:
            return {
                "result": "SUCCESS",
                "external_ticket_id": external_ticket_id,
                "detail": {
                    "message": "NameSilo form submitted.",
                    "entry_url": payload.get("entry_url", ""),
                    "reporter_email": reporter_email,
                    "real_website": real_website,
                    "phishing_website": phishing_website,
                    "artifacts": artifacts,
                    "submit_state": record_result,
                    "simulated": False,
                },
            }

        return {
            "result": "FAILED",
            "external_ticket_id": external_ticket_id,
            "error_code": "CAPTCHA_OR_SUBMIT_BLOCKED",
            "detail": {
                "message": "NameSilo form was filled but not submitted.",
                "entry_url": payload.get("entry_url", ""),
                "reporter_email": reporter_email,
                "real_website": real_website,
                "phishing_website": phishing_website,
                "submit_guard_reason": submit_guard_reason,
                "artifacts": artifacts,
                "submit_state": record_result,
                "simulated": False,
            },
        }
