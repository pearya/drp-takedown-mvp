# ADR-0002: 使用渠道适配器模式，并将 Playwright 作为浏览器执行器

## Status
Accepted

## Context
当前业务已经有部分通过网页脚本完成的自动化，但存在以下问题：
- 脚本与业务规则耦合。
- 服务商多、渠道多，难以统一编排。
- 新客户、新话术、新材料加入时容易误改现有脚本。
- 同一责任商可能同时需要工单和邮件，缺乏统一抽象。

系统需要同时支持：
- 浏览器工单提交流程
- 邮件提交流程
- 后续可能出现的 HTTP API 直连
- 人工接管和验证码挂起

## Decision
采用“配置驱动 + 渠道适配器模式”：

1. 渠道规则和客户规则放在配置中心与数据库中。
2. 每个渠道声明自己的 `route_type`、`region`、`attachments`、`captcha_strategy`、`executor`。
3. 浏览器型渠道统一通过 Playwright Executor 执行。
4. 邮件型渠道统一通过 Email Executor 执行。
5. OpenClaw 只负责编排和调用工具，不直接保存渠道配置和客户资产。

## Consequences

### Positive
- 新增渠道不必重构全局逻辑。
- 新增客户主要是录入配置和材料，不必修改脚本主流程。
- 可以并行支持工单、邮件、人工接管等不同执行方式。
- Playwright 的能力被限制在最合适的边界内。

### Negative
- 初始设计成本高于单脚本堆叠。
- 需要设计统一的适配器接口和运行时上下文。
- 需要维护配置校验、版本控制和回归测试。

### Neutral
- Playwright 仍然重要，但变成执行层而不是系统核心。

## Alternatives Considered

### 方案 A：所有渠道都直接写成独立 Playwright 脚本
Rejected。短期快，长期不可维护，且难以做隔离和统一编排。

### 方案 B：完全靠 OpenClaw Prompt 和 Skill 驱动所有逻辑
Rejected。高风险业务数据不应主要存在 Prompt 中，难审计且难隔离。

### 方案 C：只做邮件，不做工单自动化
Rejected。不满足业务目标。

## References
- https://playwright.dev/docs/auth
- https://playwright.dev/docs/input
- https://docs.openclaw.ai/tools/browser-login
