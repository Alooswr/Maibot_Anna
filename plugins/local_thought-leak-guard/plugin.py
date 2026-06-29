"""Outbound thought-leak guard for MaiBot."""

from __future__ import annotations

import re
from typing import Any

from maibot_sdk import Field, HookHandler, MaiBotPlugin, PluginConfigBase
from maibot_sdk.types import ErrorPolicy, HookMode, HookOrder


_THINK_TAG_RE = re.compile(
    r"(?is)<\s*(think|thinking|analysis|reasoning)\b[^>]*>.*?<\s*/\s*\1\s*>"
)
_UNCLOSED_THINK_TAG_RE = re.compile(r"(?is)<\s*(think|thinking|analysis|reasoning)\b[^>]*>.*$")
_REJECT_TAG_RE = re.compile(r"(?is)<\s*(reject|veto)\b[^>]*>.*?<\s*/\s*\1\s*>")
_UNCLOSED_REJECT_TAG_RE = re.compile(r"(?is)<\s*(reject|veto)\b[^>]*>.*$")
_INTERNAL_FEEDBACK_RE = re.compile(r"(?is)【内部再审反馈[^】]*】.*$")
_INTERNAL_VETO_LINE_RE = re.compile(
    r"(?im)^\s*(?:回复器触发了再审|再审理由|规划器请勿原样重试|生成可见回复失败并非技术故障)\b.*$"
)
_FENCED_REASONING_RE = re.compile(
    r"(?is)```[ \t]*(?:think|thinking|analysis|reasoning|thought|思考|推理|分析)[^\n]*\n.*?```"
)
_REASONING_HEADING_RE = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?"
    r"(?:思考过程|思考|分析过程|分析|推理过程|推理|reasoning|analysis|thoughts?)\s*[:：]\s*"
)
_FINAL_HEADING_RE = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?"
    r"(?:最终回复|最终回答|最终答案|回复|回答|答案|输出|final answer|answer|response)\s*[:：]\s*"
)
_FINAL_INLINE_RE = re.compile(
    r"(?i)(?:最终回复|最终回答|最终答案|回复|回答|答案|输出|final answer|answer|response)\s*[:：]"
)


class PluginSectionConfig(PluginConfigBase):
    """Base plugin section."""

    __ui_label__ = "插件"
    __ui_icon__ = "shield"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(default="1.0.0", description="配置版本")


class GuardSectionConfig(PluginConfigBase):
    """Guard behavior."""

    __ui_label__ = "过滤"
    __ui_icon__ = "filter"
    __ui_order__ = 1

    abort_when_empty: bool = Field(default=True, description="清洗后没有正文时中止发送")
    log_detail: bool = Field(default=True, description="清洗出站消息时记录日志")


class ThoughtLeakGuardConfig(PluginConfigBase):
    """Plugin config."""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    guard: GuardSectionConfig = Field(default_factory=GuardSectionConfig)


class ThoughtLeakGuardPlugin(MaiBotPlugin):
    """Remove hidden reasoning text from outbound messages."""

    config_model = ThoughtLeakGuardConfig

    async def on_load(self) -> None:
        self.ctx.logger.info("思考流泄露保护插件已加载")

    async def on_unload(self) -> None:
        self.ctx.logger.info("思考流泄露保护插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, object], version: str) -> None:
        del scope, config_data, version
        self.ctx.logger.info("思考流泄露保护配置已更新")

    @HookHandler(
        "send_service.before_send",
        name="thought_leak_guard_before_send",
        description="发送前清洗出站消息中的思考流片段",
        mode=HookMode.BLOCKING,
        order=HookOrder.LATE,
        timeout_ms=3000,
        error_policy=ErrorPolicy.SKIP,
    )
    async def guard_outbound_message(self, message: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any] | None:
        del kwargs

        if not self.config.plugin.enabled or not isinstance(message, dict):
            return None

        cleaned_message, changed = self._clean_message(message)
        if not changed:
            return None

        if not self._has_sendable_body(cleaned_message):
            session_id = str(message.get("session_id") or "")
            if self.config.guard.log_detail:
                self.ctx.logger.warning("思考流清洗后消息为空，已中止发送: session=%s", session_id)
            if self.config.guard.abort_when_empty:
                return {"action": "abort"}

        if self.config.guard.log_detail:
            self.ctx.logger.warning(
                "已清洗出站消息中的思考流: session=%s preview=%s",
                str(message.get("session_id") or ""),
                self._preview(cleaned_message.get("processed_plain_text")),
            )
        return {"action": "continue", "modified_kwargs": {"message": cleaned_message}}

    def _clean_message(self, message: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        cleaned = dict(message)
        changed = False

        raw_message = cleaned.get("raw_message")
        if isinstance(raw_message, list):
            new_parts: list[dict[str, Any]] = []
            for part in raw_message:
                if not isinstance(part, dict):
                    new_parts.append(part)
                    continue
                if part.get("type") != "text":
                    new_parts.append(dict(part))
                    continue
                original_text = part.get("data")
                if not isinstance(original_text, str):
                    new_parts.append(dict(part))
                    continue
                cleaned_text, text_changed = strip_reasoning_text(original_text)
                changed = changed or text_changed
                if cleaned_text:
                    next_part = dict(part)
                    next_part["data"] = cleaned_text
                    new_parts.append(next_part)
            if changed:
                cleaned["raw_message"] = new_parts

        plain_text = cleaned.get("processed_plain_text")
        if isinstance(plain_text, str):
            cleaned_plain, plain_changed = strip_reasoning_text(plain_text)
            changed = changed or plain_changed
            if plain_changed:
                cleaned["processed_plain_text"] = cleaned_plain

        if changed and isinstance(cleaned.get("raw_message"), list):
            text_plain = self._text_from_raw(cleaned["raw_message"])
            if text_plain:
                cleaned["processed_plain_text"] = text_plain

        return cleaned, changed

    @staticmethod
    def _text_from_raw(raw_message: list[Any]) -> str:
        texts: list[str] = []
        for part in raw_message:
            if not isinstance(part, dict) or part.get("type") != "text":
                continue
            data = part.get("data")
            if isinstance(data, str) and data.strip():
                texts.append(data.strip())
        return " ".join(texts).strip()

    @staticmethod
    def _has_sendable_body(message: dict[str, Any]) -> bool:
        raw_message = message.get("raw_message")
        if not isinstance(raw_message, list):
            return bool(str(message.get("processed_plain_text") or "").strip())
        for part in raw_message:
            if not isinstance(part, dict):
                continue
            part_type = str(part.get("type") or "").strip()
            if part_type == "text":
                if str(part.get("data") or "").strip():
                    return True
                continue
            if part_type in {"image", "emoji", "voice", "forward", "at", "dict"}:
                return True
        return False

    @staticmethod
    def _preview(text: object, limit: int = 80) -> str:
        value = " ".join(str(text or "").split())
        return value if len(value) <= limit else value[:limit] + "..."


def strip_reasoning_text(text: str) -> tuple[str, bool]:
    """Strip common hidden reasoning formats from one text segment."""

    original = text
    value = text.replace("\r\n", "\n").replace("\r", "\n")

    value = _THINK_TAG_RE.sub("", value)
    value = _UNCLOSED_THINK_TAG_RE.sub("", value)
    value = _REJECT_TAG_RE.sub("", value)
    value = _UNCLOSED_REJECT_TAG_RE.sub("", value)
    value = _INTERNAL_FEEDBACK_RE.sub("", value)
    value = _INTERNAL_VETO_LINE_RE.sub("", value)
    value = _FENCED_REASONING_RE.sub("", value)

    value = _keep_after_final_marker(value)

    stripped = value.lstrip()
    if _REASONING_HEADING_RE.match(stripped):
        value = ""

    value = _strip_final_label(value)
    value = _normalize_blank_lines(value)

    return value, value != original


def _keep_after_final_marker(text: str) -> str:
    final_matches = list(_FINAL_HEADING_RE.finditer(text))
    if final_matches:
        last_final = final_matches[-1]
        if _REASONING_HEADING_RE.search(text[: last_final.start()]):
            return text[last_final.end() :]

    inline_matches = list(_FINAL_INLINE_RE.finditer(text))
    if inline_matches:
        last_inline = inline_matches[-1]
        if _REASONING_HEADING_RE.search(text[: last_inline.start()]):
            return text[last_inline.end() :]

    return text


def _strip_final_label(text: str) -> str:
    return _FINAL_HEADING_RE.sub("", text, count=1).strip()


def _normalize_blank_lines(text: str) -> str:
    lines = [line.rstrip() for line in text.split("\n")]
    value = "\n".join(lines).strip()
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value


def create_plugin() -> ThoughtLeakGuardPlugin:
    return ThoughtLeakGuardPlugin()
