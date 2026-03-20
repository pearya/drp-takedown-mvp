from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.api.services.config_loader import ConfigLoader


@dataclass
class PlanningService:
    config_loader: ConfigLoader

    def plan(
        self,
        *,
        case_record: dict[str, Any],
        providers: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        customer = self.config_loader.get_customer(case_record["customer_id"])
        namesilo_settings = self.config_loader.get_namesilo_settings()
        actions: list[dict[str, Any]] = []

        for provider in providers:
            channels = self.config_loader.channels_for(provider["provider_key"], provider["role"])
            if not channels:
                actions.append(
                    {
                        "provider_role": provider["role"],
                        "provider_key": provider["provider_key"],
                        "provider_name": provider["provider_name"],
                        "channel_id": f"{provider['provider_key']}-no-route",
                        "route_type": "no_route",
                        "executor": "system",
                        "region": "UNKNOWN",
                        "language": "zh-CN",
                        "status": "NO_ROUTE_DEFINED",
                        "captcha_strategy": "none",
                        "requires_login": False,
                        "payload": {
                            "summary": f"{provider['provider_name']} no channel configured",
                            "attachments": [],
                            "preview_body": "No configured ticket/email channel for this provider yet.",
                            "entry_url": "",
                            "reporter_email": customer.get("reporter_email", "") or customer.get("contact_email", ""),
                            "real_website": customer.get("official_website", ""),
                            "phishing_website": case_record["target_url"],
                        },
                    }
                )
                continue

            for channel in channels:
                language = "zh-CN" if channel["region"] == "CN" else "en"
                context = self._build_context(case_record, customer, provider, language)
                rendered = self.config_loader.render_template(language, channel["template_key"], context)
                attachments = self._resolve_attachments(case_record, customer, channel)
                reporter_email = (
                    customer.get("reporter_email")
                    or channel.get("reporter_email")
                    or namesilo_settings.get("default_reporter_email")
                    or customer.get("contact_email", "")
                )
                actions.append(
                    {
                        "provider_role": provider["role"],
                        "provider_key": provider["provider_key"],
                        "provider_name": provider["provider_name"],
                        "channel_id": channel["channel_id"],
                        "route_type": channel["route_type"],
                        "executor": channel["executor"],
                        "region": channel["region"],
                        "language": language,
                        "status": "PLANNED",
                        "captcha_strategy": channel.get("captcha_strategy", "none"),
                        "requires_login": bool(channel.get("requires_login", False)),
                        "payload": {
                            "entry_url": channel.get("entry_url", ""),
                            "subject": rendered["subject"],
                            "preview_body": rendered["body"],
                            "attachments": attachments,
                            "auth_profile": channel.get("auth_profile", ""),
                            "send_to": channel.get("send_to", ""),
                            "implementation_status": channel.get("implementation_status", "mock"),
                            "reporter_email": reporter_email,
                            "real_website": customer.get("official_website", ""),
                            "phishing_website": case_record["target_url"],
                            "brand_name": context["brand_name"],
                        },
                    }
                )
        return actions

    def _build_context(
        self,
        case_record: dict[str, Any],
        customer: dict[str, Any],
        provider: dict[str, Any],
        language: str,
    ) -> dict[str, Any]:
        is_cn = language == "zh-CN"
        return {
            "brand_name": customer["brand_name_cn"] if is_cn else customer["brand_name_en"],
            "brand_name_cn": customer["brand_name_cn"],
            "brand_name_en": customer["brand_name_en"],
            "legal_entity": customer["legal_entity_cn"] if is_cn else customer["legal_entity_en"],
            "target_domain": case_record["target_domain"],
            "target_url": case_record["target_url"],
            "provider_name": provider["provider_name"],
            "violation_type": "仿冒钓鱼网站" if is_cn else "phishing and impersonation website",
            "contact_email": customer["contact_email"],
            "official_website": customer.get("official_website", ""),
            "evidence_summary": case_record["notes"]
            or ("初始工单录入截图已附上。" if is_cn else "Initial evidence was attached."),
            "signature_cn": customer.get("signature_cn", ""),
            "signature_en": customer.get("signature_en", ""),
        }

    def _resolve_attachments(
        self,
        case_record: dict[str, Any],
        customer: dict[str, Any],
        channel: dict[str, Any],
    ) -> list[dict[str, Any]]:
        attachments: list[dict[str, Any]] = []
        attachment_rules = channel.get("attachments", {})
        for item_type in attachment_rules.get("required", []):
            attachments.append(self._attachment_for_type(item_type, case_record, customer, required=True))
        for item_type in attachment_rules.get("optional", []):
            attachment = self._attachment_for_type(item_type, case_record, customer, required=False)
            if attachment.get("path"):
                attachments.append(attachment)
        return attachments

    def _attachment_for_type(
        self,
        item_type: str,
        case_record: dict[str, Any],
        customer: dict[str, Any],
        *,
        required: bool,
    ) -> dict[str, Any]:
        if item_type == "phishing_screenshot":
            return {
                "type": item_type,
                "label": "Phishing screenshot",
                "path": case_record["evidence_path"],
                "required": required,
            }
        label_map = {
            "business_license": "Business license",
            "trademark_certificate": "Trademark certificate",
        }
        return {
            "type": item_type,
            "label": label_map.get(item_type, item_type),
            "path": customer.get("assets", {}).get(item_type, ""),
            "required": required,
        }
