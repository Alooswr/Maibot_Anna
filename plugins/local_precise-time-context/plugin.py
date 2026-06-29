"""Precise current-time context injection for MaiBot."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from maibot_sdk import Field, HookHandler, MaiBotPlugin, PluginConfigBase
from maibot_sdk.types import ErrorPolicy, HookMode, HookOrder


_WEEKDAY_ZH = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
_MARKER = "【当前精确时间】"


class PluginSectionConfig(PluginConfigBase):
    """Base plugin settings."""

    __ui_label__ = "插件"
    __ui_icon__ = "clock"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(default="1.0.0", description="配置版本")


class TimeSectionConfig(PluginConfigBase):
    """Time injection settings."""

    __ui_label__ = "时间注入"
    __ui_icon__ = "clock-3"
    __ui_order__ = 1

    timezone: str = Field(default="Asia/Shanghai", description="计算当前时间所用的时区（IANA 名称）")
    time_format: str = Field(default="%Y-%m-%d %H:%M", description="时间格式（strftime），默认精确到分钟")
    include_seconds: bool = Field(default=False, description="是否额外显示秒；开启后上下文每秒变化")
    include_timezone: bool = Field(default=True, description="是否显示时区和 UTC 偏移")
    include_period: bool = Field(default=True, description="是否显示清晨/上午/中午/下午/晚上/深夜等时段")
    include_relative_rule: bool = Field(default=True, description="是否提醒模型相对时间判断必须以当前时间为准")
    template: str = Field(
        default="【当前精确时间】现在是 {datetime}{seconds}（{timezone_text}{weekday}{period}）。{relative_rule}",
        description="注入文本模板，可使用 {datetime} {seconds} {timezone_text} {weekday} {period} {relative_rule}",
    )


class PreciseTimeContextConfig(PluginConfigBase):
    """Plugin config."""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    time: TimeSectionConfig = Field(default_factory=TimeSectionConfig)


class PreciseTimeContextPlugin(MaiBotPlugin):
    """Inject current time into Maisaka model requests."""

    config_model = PreciseTimeContextConfig

    async def on_load(self) -> None:
        self.ctx.logger.info("精确时间上下文插件已加载")

    async def on_unload(self) -> None:
        self.ctx.logger.info("精确时间上下文插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, object], version: str) -> None:
        del scope, config_data, version
        self.ctx.logger.info("精确时间上下文配置已更新")

    @HookHandler(
        "maisaka.replyer.before_model_request",
        name="inject_precise_time_context",
        description="向模型请求注入当前精确时间/时区/星期/时段上下文",
        mode=HookMode.BLOCKING,
        order=HookOrder.LATE,
        timeout_ms=3000,
        error_policy=ErrorPolicy.SKIP,
    )
    async def inject_precise_time(self, messages: Any = None, **kwargs: Any) -> dict[str, Any] | None:
        if not self.config.plugin.enabled or not isinstance(messages, list):
            return None

        context_text = self._build_context_text()
        new_messages = [
            msg
            for msg in messages
            if not (
                isinstance(msg, dict)
                and msg.get("role") == "system"
                and str(msg.get("content") or "").startswith(_MARKER)
            )
        ]

        insert_pos = 0
        for index, msg in enumerate(new_messages):
            if isinstance(msg, dict) and msg.get("role") == "system":
                insert_pos = index + 1
            else:
                break
        new_messages.insert(insert_pos, {"role": "system", "content": context_text})

        modified_kwargs = dict(kwargs)
        modified_kwargs["messages"] = new_messages
        return {"action": "continue", "modified_kwargs": modified_kwargs}

    def _build_context_text(self) -> str:
        time_config = self.config.time
        now = datetime.now(self._load_timezone(time_config.timezone))

        datetime_text = now.strftime(time_config.time_format)
        seconds_text = self._build_seconds_text(now, time_config.time_format, time_config.include_seconds)
        timezone_text = self._build_timezone_text(now, time_config.timezone) if time_config.include_timezone else ""
        weekday_text = _WEEKDAY_ZH[now.weekday()]
        period_text = f"，当前时段：{_period_for_hour(now.hour)}" if time_config.include_period else ""
        relative_rule = (
            "回复中涉及当前时间、刚才、等会儿、今天/明天、上午/下午/晚上、作息或是否已经过了某个时间点时，必须以此时间为准。"
            if time_config.include_relative_rule
            else ""
        )

        return time_config.template.format(
            datetime=datetime_text,
            seconds=seconds_text,
            timezone_text=timezone_text,
            weekday=weekday_text,
            period=period_text,
            relative_rule=relative_rule,
        )

    def _load_timezone(self, timezone_name: str) -> ZoneInfo:
        try:
            return ZoneInfo(str(timezone_name or "Asia/Shanghai").strip() or "Asia/Shanghai")
        except ZoneInfoNotFoundError:
            self.ctx.logger.warning("无效时区 %r，已回退到 Asia/Shanghai", timezone_name)
            return ZoneInfo("Asia/Shanghai")

    @staticmethod
    def _build_timezone_text(now: datetime, timezone_name: str) -> str:
        offset = now.strftime("%z")
        offset_text = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset
        label = str(timezone_name or "").strip() or str(now.tzinfo or "")
        return f"{label}，UTC{offset_text}，"

    @staticmethod
    def _build_seconds_text(now: datetime, time_format: str, include_seconds: bool) -> str:
        if not include_seconds or "%S" in time_format:
            return ""
        return now.strftime(":%S")


def _period_for_hour(hour: int) -> str:
    if 0 <= hour < 5:
        return "深夜"
    if hour < 8:
        return "清晨"
    if hour < 12:
        return "上午"
    if hour < 14:
        return "中午"
    if hour < 18:
        return "下午"
    if hour < 22:
        return "晚上"
    return "深夜"


def create_plugin() -> PreciseTimeContextPlugin:
    return PreciseTimeContextPlugin()
