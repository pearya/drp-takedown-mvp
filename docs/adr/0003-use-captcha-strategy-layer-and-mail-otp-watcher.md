# ADR-0003: 将验证码能力设计为独立策略层，并优先实现邮箱 OTP 监听

## Status
Accepted

## Context
部分渠道的工单提交流程包含验证码或二次校验，当前已知场景包括：
- Google 类人机验证
- 邮箱验证码

如果把验证码处理直接写死在 Playwright 脚本里，会导致：
- 逻辑耦合严重
- 不同验证码类型难以扩展
- 无法灵活切换人工、自动或第三方方案

## Decision
验证码处理采用独立策略层，最少支持以下策略：

- `none`
- `manual_takeover`
- `third_party_solver`
- `email_otp`
- `totp`

并采用如下实现原则：

1. 邮箱验证码优先由邮件协议/API 监听器处理，不通过浏览器登录邮箱页面读取。
2. 页面验证码默认使用人工接管方案。
3. 第三方打码平台作为可选能力，由合规审批后按渠道开启。
4. 如果“Google 2FA”实际属于 TOTP，则单独按 `totp` 处理，不归类为页面验证码。

## Consequences

### Positive
- 各类验证码有清晰边界。
- 邮箱 OTP 的自动化收益高且相对稳定。
- 页面验证码不会阻塞系统主架构设计。
- 后续接第三方服务或人工协作更容易。

### Negative
- 初期不能承诺“所有验证码全自动解决”。
- 需要额外建设邮箱接入与任务挂起机制。
- 人工接管会引入运营流程要求。

### Neutral
- Playwright 仍参与验证码流程，但不是验证码解决器本身。

## Alternatives Considered

### 方案 A：全部依赖 Playwright 自动解决验证码
Rejected。技术和合规风险都过高。

### 方案 B：全部交由人工处理
Rejected。效率提升有限，不能满足自动化目标。

### 方案 C：一开始就接所有第三方打码平台
Rejected。合规和维护成本过高，应按渠道逐步启用。

## References
- https://docs.openclaw.ai/automation/gmail-pubsub
- https://developers.google.com/recaptcha/docs/faq
