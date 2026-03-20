# ADR-0001: 使用 RDAP-first 的责任商识别链路

## Status
Accepted

## Context
系统需要从仿冒网站中识别域名注册商、DNS 服务商、IP 服务商和顶级域名注册机构。原始 Whois 输出字段在不同注册商、不同 TLD 下差异较大，字段名不稳定，且文本格式缺乏统一结构。继续把正则作为核心识别方式，会导致识别不稳定、维护成本高、误判率高。

## Decision
责任商识别采用如下顺序：

1. 优先使用 RDAP 获取 Registrar / Registry 的结构化数据。
2. 使用 DNS 记录和 NS 指纹识别 DNS Provider。
3. 使用 A/AAAA 解析结果、ASN、IP WHOIS 识别 Hosting / IP Service Provider。
4. 仅在缺失场景下使用原始 Whois 作为兜底来源。
5. 原始 Whois 的解析采用键值映射、字段同义词词典和供应商知识库，不使用正则作为主方案。

## Consequences

### Positive
- 结构化数据优先，稳定性更高。
- 更容易解释识别来源和置信度。
- 更适合做统一数据模型和审计。
- 更适合扩展到海内外不同注册体系。

### Negative
- 需要维护更多数据源适配逻辑。
- 某些场景仍需回退到低质量的 Whois 数据。
- 需要补充 DNS、ASN、IP WHOIS 的供应商知识库。

### Neutral
- 系统会比“直接查 Whois 文本 + 正则”更复杂，但维护性显著更好。

## Alternatives Considered

### 方案 A：继续用原始 Whois + 正则
Rejected。格式差异太大，长期不可维护。

### 方案 B：完全依赖第三方商业情报 API
Rejected。虽然开发更快，但供应商锁定风险较高，且业务可解释性变差。

### 方案 C：仅使用 DNS/IP 推断，不查注册数据
Rejected。无法稳定覆盖 Registrar / Registry 角色。

## References
- https://www.icann.org/rdap/
- https://www.rfc-editor.org/rfc/rfc9083
