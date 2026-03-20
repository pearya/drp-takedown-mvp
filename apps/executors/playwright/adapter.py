from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1

from apps.executors.playwright.namesilo_channel import NameSiloPhishingChannel


@dataclass
class PlaywrightExecutorAdapter:
    def __post_init__(self) -> None:
        self.namesilo_channel = NameSiloPhishingChannel()

    def execute(self, action: dict, context: dict) -> dict:
        implementation_status = action["payload"].get("implementation_status", "mock")
        channel_id = action.get("channel_id", "")

        if implementation_status == "real" and channel_id == "namesilo-phishing-report":
            return self.namesilo_channel.execute(action, context)

        ticket_seed = f"{context['case_id']}:{channel_id}:{context['target_domain']}"
        ticket_id = f"TICKET-{sha1(ticket_seed.encode('utf-8')).hexdigest()[:10].upper()}"
        captcha_strategy = context["captcha_strategy"]

        if captcha_strategy == "manual_takeover":
            return {
                "result": "WAITING_HUMAN",
                "external_ticket_id": ticket_id,
                "detail": {
                    "message": "Manual takeover is required for this channel.",
                    "entry_url": action["payload"].get("entry_url", ""),
                    "attachments": action["payload"].get("attachments", []),
                    "captcha_strategy": captcha_strategy,
                    "implementation_status": implementation_status,
                    "simulated": implementation_status != "real",
                },
            }

        if captcha_strategy == "email_otp":
            otp_code = self._mock_otp(context["target_domain"])
            return {
                "result": "SUCCESS",
                "external_ticket_id": ticket_id,
                "detail": {
                    "message": "Playwright ticket workflow completed with mocked email OTP.",
                    "entry_url": action["payload"].get("entry_url", ""),
                    "otp_code": otp_code,
                    "attachments": action["payload"].get("attachments", []),
                    "implementation_status": implementation_status,
                    "simulated": implementation_status != "real",
                },
            }

        return {
            "result": "SUCCESS",
            "external_ticket_id": ticket_id,
            "detail": {
                "message": "Playwright workflow completed in MVP mock mode.",
                "entry_url": action["payload"].get("entry_url", ""),
                "attachments": action["payload"].get("attachments", []),
                "implementation_status": implementation_status,
                "simulated": implementation_status != "real",
            },
        }

    def _mock_otp(self, target_domain: str) -> str:
        digest = sha1(target_domain.encode("utf-8")).hexdigest()
        return str(int(digest[:8], 16))[:6].zfill(6)
