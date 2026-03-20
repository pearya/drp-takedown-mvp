from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def save_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


@dataclass
class ConfigLoader:
    root_dir: Path

    @property
    def config_dir(self) -> Path:
        return self.root_dir / "config"

    @property
    def templates_dir(self) -> Path:
        return self.root_dir / "templates" / "messages"

    @property
    def integrations_dir(self) -> Path:
        return self.config_dir / "integrations"

    @property
    def namesilo_settings_path(self) -> Path:
        return self.integrations_dir / "namesilo.yaml"

    def list_customers(self) -> list[dict[str, Any]]:
        customers_dir = self.config_dir / "customers"
        customers: list[dict[str, Any]] = []
        for path in sorted(customers_dir.glob("*/profile.yaml")):
            profile = load_yaml(path)
            profile["profile_path"] = str(path)
            customers.append(profile)
        return customers

    def get_customer(self, customer_id: str) -> dict[str, Any]:
        path = self.config_dir / "customers" / customer_id / "profile.yaml"
        profile = load_yaml(path)
        if not profile:
            raise KeyError(f"Customer {customer_id} not configured")
        profile["profile_path"] = str(path)
        return profile

    def upsert_customer(self, profile: dict[str, Any]) -> dict[str, Any]:
        customer_id = profile["customer_id"].strip().lower()
        assets_dir = self.config_dir / "customers" / customer_id / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        profile_path = self.config_dir / "customers" / customer_id / "profile.yaml"
        current = self.get_customer(customer_id) if profile_path.exists() else {}

        payload = {
            "customer_id": customer_id,
            "brand_name_cn": profile.get("brand_name_cn", current.get("brand_name_cn", "")),
            "brand_name_en": profile.get("brand_name_en", current.get("brand_name_en", "")),
            "legal_entity_cn": profile.get("legal_entity_cn", current.get("legal_entity_cn", "")),
            "legal_entity_en": profile.get("legal_entity_en", current.get("legal_entity_en", "")),
            "contact_email": profile.get("contact_email", current.get("contact_email", "")),
            "reporter_email": profile.get("reporter_email", current.get("reporter_email", "")),
            "official_website": profile.get("official_website", current.get("official_website", "")),
            "signature_cn": profile.get("signature_cn", current.get("signature_cn", "")),
            "signature_en": profile.get("signature_en", current.get("signature_en", "")),
            "assets": {
                "business_license": current.get("assets", {}).get(
                    "business_license", str(assets_dir / "business-license.txt")
                ),
                "trademark_certificate": current.get("assets", {}).get(
                    "trademark_certificate", str(assets_dir / "trademark-certificate.txt")
                ),
            },
        }
        save_yaml(profile_path, payload)
        return self.get_customer(customer_id)

    def save_customer_asset(self, customer_id: str, asset_key: str, filename: str, content: bytes) -> str:
        customer = self.get_customer(customer_id)
        assets_dir = self.config_dir / "customers" / customer_id / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix or ".bin"
        target_name = "business-license" if asset_key == "business_license" else "trademark-certificate"
        target_path = assets_dir / f"{target_name}{suffix}"
        target_path.write_bytes(content)
        customer["assets"][asset_key] = str(target_path)
        save_yaml(
            self.config_dir / "customers" / customer_id / "profile.yaml",
            {key: value for key, value in customer.items() if key != "profile_path"},
        )
        return str(target_path)

    def list_providers(self) -> list[dict[str, Any]]:
        providers_dir = self.config_dir / "providers"
        providers: list[dict[str, Any]] = []
        for path in sorted(providers_dir.glob("*.yaml")):
            if path.name == "registry_by_tld.yaml":
                continue
            config = load_yaml(path)
            config["path"] = str(path)
            providers.append(config)
        return providers

    def registry_mapping(self) -> dict[str, Any]:
        return load_yaml(self.config_dir / "providers" / "registry_by_tld.yaml").get("mappings", {})

    def list_channels(self) -> list[dict[str, Any]]:
        channels_dir = self.config_dir / "channels"
        channels: list[dict[str, Any]] = []
        for path in sorted(channels_dir.glob("*.yaml")):
            config = load_yaml(path)
            provider_key = config.get("provider_key", path.stem)
            for channel in config.get("channels", []):
                merged = dict(channel)
                merged["provider_key"] = provider_key
                merged["path"] = str(path)
                merged["implementation_status"] = channel.get("implementation_status", "mock")
                channels.append(merged)
        return channels

    def channels_for(self, provider_key: str, provider_role: str) -> list[dict[str, Any]]:
        return [
            channel
            for channel in self.list_channels()
            if channel["provider_key"] == provider_key and channel["provider_role"] == provider_role
        ]

    def find_provider_by_text(self, text: str, role: str | None = None) -> dict[str, Any] | None:
        candidate = text.lower()
        for provider in self.list_providers():
            roles = provider.get("roles", [])
            if role and role not in roles:
                continue
            haystacks = provider.get("aliases", []) + provider.get("entity_contains", [])
            for alias in haystacks:
                if alias.lower() in candidate:
                    return provider
        return None

    def find_provider_by_nameservers(self, nameservers: list[str]) -> dict[str, Any] | None:
        lowered = [name.lower() for name in nameservers]
        for provider in self.list_providers():
            if "dns" not in provider.get("roles", []):
                continue
            for suffix in provider.get("ns_suffixes", []):
                normalized_suffix = suffix.lower().lstrip(".")
                if any(server.endswith(normalized_suffix) for server in lowered):
                    return provider
        return None

    def list_templates(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for locale_dir in sorted(self.templates_dir.glob("*")):
            if not locale_dir.is_dir():
                continue
            for template_path in sorted(locale_dir.glob("*.md")):
                items.append(
                    {
                        "locale": locale_dir.name,
                        "template_key": template_path.stem,
                        "content": template_path.read_text(encoding="utf-8"),
                        "path": str(template_path),
                    }
                )
        return items

    def get_template(self, locale: str, template_key: str) -> dict[str, Any]:
        template_path = self.templates_dir / locale / f"{template_key}.md"
        if not template_path.exists():
            raise KeyError(f"Template {locale}/{template_key} not found")
        return {
            "locale": locale,
            "template_key": template_key,
            "content": template_path.read_text(encoding="utf-8"),
            "path": str(template_path),
        }

    def save_template(self, locale: str, template_key: str, content: str) -> dict[str, Any]:
        template_path = self.templates_dir / locale / f"{template_key}.md"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text(content, encoding="utf-8")
        return self.get_template(locale, template_key)

    def get_namesilo_settings(self) -> dict[str, Any]:
        settings = load_yaml(self.namesilo_settings_path)
        if not settings:
            return {
                "entry_url": "https://www.namesilo.com/phishing-report",
                "channel_id": "namesilo-phishing-report",
                "template_key": "namesilo_phishing_report",
                "default_reporter_email": "",
                "notes": "",
            }
        return {
            "entry_url": settings.get("entry_url", "https://www.namesilo.com/phishing-report"),
            "channel_id": settings.get("channel_id", "namesilo-phishing-report"),
            "template_key": settings.get("template_key", "namesilo_phishing_report"),
            "default_reporter_email": settings.get("default_reporter_email", ""),
            "notes": settings.get("notes", ""),
        }

    def save_namesilo_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_namesilo_settings()
        merged = {
            "entry_url": payload.get("entry_url", current["entry_url"]),
            "channel_id": payload.get("channel_id", current["channel_id"]),
            "template_key": payload.get("template_key", current["template_key"]),
            "default_reporter_email": payload.get("default_reporter_email", current["default_reporter_email"]),
            "notes": payload.get("notes", current["notes"]),
        }
        save_yaml(self.namesilo_settings_path, merged)
        return self.get_namesilo_settings()

    def render_template(self, language: str, template_key: str, context: dict[str, Any]) -> dict[str, str]:
        locale_dir = "zh_CN" if language == "zh-CN" else "en"
        template_path = self.templates_dir / locale_dir / f"{template_key}.md"
        body = template_path.read_text(encoding="utf-8")
        rendered = body
        for key, value in context.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
        subject = (
            f"Takedown request for {context['target_domain']}"
            if language != "zh-CN"
            else f"关于域名 {context['target_domain']} 的仿冒网站处置请求"
        )
        return {"subject": subject, "body": rendered}

    def automation_guide(self) -> dict[str, Any]:
        return {
            "openclaw_endpoint": "/api/tools/run_batch",
            "steps": [
                "输入 customer_id 和一批 URLs",
                "系统批量创建案例",
                "依次执行责任商识别、计划生成、渠道提交、站点验证",
                "返回每个案例的提交状态和站点存活验证结果",
            ],
            "real_automation_blueprint": [
                "每个渠道维护独立 adapter，不把变量写死在脚本里",
                "登录态复用 storage state，验证码走策略层",
                "配置中心维护字段映射、附件规则和区域语言",
                "提交成功后再做 URL 存活验证，区分提交成功和下线成功",
            ],
            "namesilo": self.get_namesilo_settings(),
        }

    def bootstrap(self) -> dict[str, Any]:
        customers = self.list_customers()
        providers = self.list_providers()
        channels = self.list_channels()
        templates = self.list_templates()
        return {
            "customers": [
                {
                    "customer_id": customer["customer_id"],
                    "brand_name_cn": customer.get("brand_name_cn", ""),
                    "brand_name_en": customer.get("brand_name_en", ""),
                    "official_website": customer.get("official_website", ""),
                    "reporter_email": customer.get("reporter_email", ""),
                }
                for customer in customers
            ],
            "provider_count": len(providers),
            "channel_count": len(channels),
            "customer_count": len(customers),
            "template_count": len(templates),
        }
