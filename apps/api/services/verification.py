from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class VerificationService:
    timeout_seconds: float = 10.0

    def verify(self, target_url: str) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = client.get(target_url, headers={"User-Agent": "DRP-MVP-Verification/1.0"})
            status_code = response.status_code
            verdict = self._verdict_from_status(status_code)
            return {
                "check_url": str(response.url),
                "verdict": verdict,
                "http_status": str(status_code),
                "detail": {
                    "reason": "HTTP response received",
                    "final_url": str(response.url),
                    "content_type": response.headers.get("content-type", ""),
                },
            }
        except httpx.ConnectError as exc:
            return {
                "check_url": target_url,
                "verdict": "DOWN_CONFIRMED",
                "http_status": "",
                "detail": {"reason": "ConnectError", "message": str(exc)},
            }
        except httpx.TimeoutException as exc:
            return {
                "check_url": target_url,
                "verdict": "CHECK_TIMEOUT",
                "http_status": "",
                "detail": {"reason": "Timeout", "message": str(exc)},
            }
        except Exception as exc:
            return {
                "check_url": target_url,
                "verdict": "CHECK_ERROR",
                "http_status": "",
                "detail": {"reason": type(exc).__name__, "message": str(exc)},
            }

    def _verdict_from_status(self, status_code: int) -> str:
        if status_code in {404, 410, 451}:
            return "DOWN_CONFIRMED"
        if status_code == 403:
            return "ACCESS_BLOCKED"
        if 200 <= status_code < 400:
            return "LIVE"
        if 500 <= status_code < 600:
            return "UNSTABLE"
        return "CHECK_ERROR"
