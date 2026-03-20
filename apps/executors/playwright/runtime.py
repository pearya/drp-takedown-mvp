from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChannelAutomationStep:
    action: str
    selector: str = ""
    value: str = ""
    file_key: str = ""
    description: str = ""


@dataclass
class ChannelAutomationDefinition:
    channel_id: str
    entry_url: str
    requires_login: bool
    success_markers: list[str] = field(default_factory=list)
    ticket_extractors: list[str] = field(default_factory=list)
    steps: list[ChannelAutomationStep] = field(default_factory=list)


@dataclass
class PlaywrightRuntimePlan:
    channel_id: str
    implementation_status: str
    notes: list[str]
    next_actions: list[str]


class PlaywrightRealAutomationRuntime:
    """
    真实接入时的建议边界：
    1. 每个渠道声明自己的 definition，不把客户话术写死在脚本里。
    2. definition 只描述浏览器动作和成功标记。
    3. 登录态、验证码、附件、话术由上层注入。
    4. 真正执行时可在这里接入 Playwright，同步或异步都可以。
    """

    def build_plan(self, channel: dict[str, Any]) -> PlaywrightRuntimePlan:
        return PlaywrightRuntimePlan(
            channel_id=channel["channel_id"],
            implementation_status=channel.get("implementation_status", "mock"),
            notes=[
                "为该渠道建立独立 adapter。",
                "把登录态保存为 auth_profile 对应的 storage state。",
                "把验证码策略从页面脚本中拆出来。",
            ],
            next_actions=[
                "录制并整理首版选择器。",
                "加上成功断言和工单编号提取。",
                "回放 5 次以上确认稳定性。",
                "接入失败截图、trace 和人工接管。",
            ],
        )
