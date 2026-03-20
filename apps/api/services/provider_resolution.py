from __future__ import annotations

import socket
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import dns.resolver
import httpx
import tldextract

from apps.api.services.config_loader import ConfigLoader


def safe_hostname(target_url: str) -> str:
    candidate = target_url if "://" in target_url else f"https://{target_url}"
    parsed = urlparse(candidate)
    return (parsed.hostname or "").lower()


def registered_domain(hostname: str) -> str:
    extractor = tldextract.TLDExtract(suffix_list_urls=None)
    parts = extractor(hostname)
    if not parts.domain or not parts.suffix:
        return hostname
    return ".".join([parts.domain, parts.suffix]).lower()


def first_non_empty(items: list[str]) -> str | None:
    for item in items:
        if item:
            return item
    return None


def slugify_name(value: str) -> str:
    sanitized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return sanitized or "unknown-provider"


@dataclass
class ProviderResolutionService:
    config_loader: ConfigLoader

    def resolve(self, target_url: str) -> dict[str, Any]:
        hostname = safe_hostname(target_url)
        domain = registered_domain(hostname)
        if not domain:
            raise ValueError("无法从输入中提取有效域名")

        providers: list[dict[str, Any]] = []
        rdap_payload = self._fetch_json(f"https://rdap.org/domain/{domain}")

        registrar = self._extract_registrar(rdap_payload)
        if registrar:
            providers.append(
                {
                    "role": "registrar",
                    "provider_key": registrar.get("provider_key", "unknown"),
                    "provider_name": registrar["provider_name"],
                    "confidence": registrar.get("confidence", 0.72),
                    "source": ["rdap"],
                    "metadata": {"domain": domain},
                }
            )

        registry = self._lookup_registry(domain)
        if registry:
            providers.append(
                {
                    "role": "registry",
                    "provider_key": registry["provider_key"],
                    "provider_name": registry["provider_name"],
                    "confidence": 0.88,
                    "source": ["tld_registry_map"],
                    "metadata": {"tld": domain.split(".")[-1]},
                }
            )

        nameservers = self._resolve_nameservers(domain)
        dns_provider = self.config_loader.find_provider_by_nameservers(nameservers)
        if dns_provider:
            providers.append(
                {
                    "role": "dns",
                    "provider_key": dns_provider["provider_key"],
                    "provider_name": dns_provider["display_name"],
                    "confidence": 0.9,
                    "source": ["nameserver_fingerprint"],
                    "metadata": {"nameservers": nameservers},
                }
            )

        ips = self._resolve_ips(hostname)
        ip_provider = self._resolve_ip_provider(ips)
        if ip_provider:
            providers.append(
                {
                    "role": "ip_hosting",
                    "provider_key": ip_provider["provider_key"],
                    "provider_name": ip_provider["provider_name"],
                    "confidence": ip_provider["confidence"],
                    "source": ip_provider["source"],
                    "metadata": {"ips": ips},
                }
            )

        unique: dict[tuple[str, str], dict[str, Any]] = {}
        for provider in providers:
            unique[(provider["role"], provider["provider_key"])] = provider

        return {
            "target_url": target_url,
            "target_domain": domain,
            "hostname": hostname,
            "providers": list(unique.values()),
            "dns_nameservers": nameservers,
            "resolved_ips": ips,
        }

    def _fetch_json(self, url: str) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
            return response.json()
        except Exception:
            return {}

    def _extract_registrar(self, rdap_payload: dict[str, Any]) -> dict[str, Any] | None:
        entities = rdap_payload.get("entities", [])
        for entity in entities:
            if "registrar" not in entity.get("roles", []):
                continue
            provider_name = self._extract_vcard_name(entity.get("vcardArray", []))
            if not provider_name:
                provider_name = first_non_empty([entity.get("handle", ""), entity.get("objectClassName", "")])
            if provider_name:
                matched = self.config_loader.find_provider_by_text(provider_name, role="registrar")
                return {
                    "provider_key": matched["provider_key"] if matched else slugify_name(provider_name),
                    "provider_name": matched["display_name"] if matched else provider_name,
                    "confidence": 0.95 if matched else 0.78,
                }
        registrar_name = rdap_payload.get("registrarName")
        if registrar_name:
            matched = self.config_loader.find_provider_by_text(registrar_name, role="registrar")
            return {
                "provider_key": matched["provider_key"] if matched else slugify_name(registrar_name),
                "provider_name": matched["display_name"] if matched else registrar_name,
                "confidence": 0.82,
            }
        return None

    def _extract_vcard_name(self, vcard_array: list[Any]) -> str | None:
        if len(vcard_array) != 2:
            return None
        for item in vcard_array[1]:
            if not item or len(item) < 4:
                continue
            if item[0] in {"fn", "org"}:
                value = item[3]
                if isinstance(value, list):
                    return " ".join(str(part) for part in value if part)
                return str(value)
        return None

    def _lookup_registry(self, domain: str) -> dict[str, Any] | None:
        tld = domain.split(".")[-1]
        registry_map = self.config_loader.registry_mapping()
        return registry_map.get(tld)

    def _resolve_nameservers(self, domain: str) -> list[str]:
        try:
            answers = dns.resolver.resolve(domain, "NS")
            return sorted({str(answer.target).rstrip(".").lower() for answer in answers})
        except Exception:
            return []

    def _resolve_ips(self, hostname: str) -> list[str]:
        try:
            results = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return []
        ips = {result[4][0] for result in results if result[4]}
        return sorted(ips)

    def _resolve_ip_provider(self, ips: list[str]) -> dict[str, Any] | None:
        for ip_address in ips:
            payload = self._fetch_json(f"https://rdap.org/ip/{ip_address}")
            text_haystack = self._rdap_ip_text(payload)
            matched = self.config_loader.find_provider_by_text(text_haystack, role="ip_hosting")
            if matched:
                return {
                    "provider_key": matched["provider_key"],
                    "provider_name": matched["display_name"],
                    "confidence": 0.84,
                    "source": ["ip_rdap"],
                }
            network_name = first_non_empty(
                [payload.get("name", ""), payload.get("handle", ""), payload.get("startAddress", "")]
            )
            if network_name:
                return {
                    "provider_key": slugify_name(network_name),
                    "provider_name": network_name,
                    "confidence": 0.58,
                    "source": ["ip_rdap_heuristic"],
                }
        return None

    def _rdap_ip_text(self, payload: dict[str, Any]) -> str:
        parts: list[str] = [str(payload.get("name", "")), str(payload.get("handle", ""))]
        for entity in payload.get("entities", []):
            parts.append(str(entity.get("handle", "")))
            vcard = self._extract_vcard_name(entity.get("vcardArray", []))
            if vcard:
                parts.append(vcard)
        return " ".join(parts).lower()
