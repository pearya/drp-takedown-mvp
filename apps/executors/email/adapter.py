from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


@dataclass
class EmailExecutorAdapter:
    def execute(self, action: dict, context: dict) -> dict:
        message_id = f"<{uuid4()}@drp-mvp.local>"
        implementation_status = action["payload"].get("implementation_status", "mock")
        detail = {
            "message": "邮件执行器已生成发送结果。",
            "send_to": action["payload"].get("send_to", "abuse@example.com"),
            "subject": action["payload"].get("subject", ""),
            "attachments": action["payload"].get("attachments", []),
            "target_domain": context["target_domain"],
            "implementation_status": implementation_status,
            "simulated": implementation_status != "real",
        }
        return {
            "result": "SUCCESS",
            "external_ticket_id": message_id,
            "detail": detail,
        }
