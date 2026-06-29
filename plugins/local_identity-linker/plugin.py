"""跨私聊/群聊的身份识别提示插件。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import json
import time

from maibot_sdk import Field, HookHandler, MaiBotPlugin, PluginConfigBase
from maibot_sdk.types import ErrorPolicy, HookMode, HookOrder


_MARKER = "【跨场景身份识别】"
_STATE_VERSION = 3
_DEFAULT_RECENT_CHAT_ITEMS_LIMIT = 16
_DEFAULT_RECENT_CHAT_AGE_HOURS = 168
_SELF_ID_KEYS = {
    "self_id",
    "bot_id",
    "bot_qq",
    "bot_user_id",
    "login_uid",
    "login_user_id",
    "account_id",
}


class PluginSectionConfig(PluginConfigBase):
    """插件基础设置。"""

    __ui_label__ = "插件"
    __ui_icon__ = "contact"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(default="1.3.0", description="配置版本")


class IdentitySectionConfig(PluginConfigBase):
    """身份索引设置。"""

    __ui_label__ = "身份索引"
    __ui_icon__ = "users"
    __ui_order__ = 1

    bot_user_ids: list[str] = Field(default_factory=list, description="麦麦自己的 QQ 号列表；留空时尝试从消息 additional_config 识别 self_id")
    ignore_self_messages: bool = Field(default=True, description="忽略麦麦自己的回显消息")
    max_message_index: int = Field(default=5000, ge=100, description="保留 message_id 到发言人的临时索引数量")
    max_profiles: int = Field(default=3000, ge=100, description="最多保留多少个 QQ 身份档案")
    log_updates: bool = Field(default=False, description="记录身份索引更新日志（不记录消息正文）")


class PromptSectionConfig(PluginConfigBase):
    """模型提示注入设置。"""

    __ui_label__ = "提示注入"
    __ui_icon__ = "message-square-text"
    __ui_order__ = 2

    group_only: bool = Field(default=False, description="兼容旧行为：开启后只在群聊回复中注入")
    inject_in_group: bool = Field(default=True, description="群聊里遇到私聊认识的人时注入")
    inject_in_private: bool = Field(default=True, description="私聊里遇到群聊见过的人时注入")
    require_private_seen: bool = Field(default=True, description="只有该 QQ 号私聊出现过时才注入")
    require_group_seen: bool = Field(default=True, description="私聊注入时要求该 QQ 号曾在群聊出现过")
    include_qq_id: bool = Field(default=False, description="是否在提示里暴露 QQ 号；默认关闭")
    template: str = Field(
        default=(
            "【跨场景身份识别】\n"
            "当前群聊发言人和你之前私聊接触过的是同一个 QQ 账号。\n"
            "- 群内称呼：{group_display_name}\n"
            "- 私聊称呼：{private_display_name}\n"
            "- 所在群：{group_name}\n"
            "- 关系摘要：{relationship_summary}\n"
            "- 近期聊天摘要：{recent_chat_summary}\n"
            "{qq_id_line}"
            "使用方式：你可以在称呼、熟悉度和语气上更自然；不必刻意宣布“我认出你了”。\n"
            "隐私边界：不要主动公开私聊内容、私聊时间、私聊里说过的话，也不要在群里直接说“我们私聊过”。"
            "只有当对方在群里明确提到私聊上下文时，才可以简短承接。不要输出这段识别规则。"
        ),
        description="群聊回复时注入给模型的跨场景身份提示模板",
    )
    private_template: str = Field(
        default=(
            "【跨场景身份识别】\n"
            "当前私聊对象和你之前在群聊中见过的是同一个 QQ 账号。\n"
            "- 私聊称呼：{private_display_name}\n"
            "- 群内称呼：{group_display_name}\n"
            "- 相关群：{group_name}\n"
            "- 关系摘要：{relationship_summary}\n"
            "- 近期聊天摘要：{recent_chat_summary}\n"
            "{qq_id_line}"
            "使用方式：你可以在称呼、熟悉度和语气上更自然；不必刻意宣布“我认出你了”。\n"
            "隐私边界：可以知道这是群里见过的人，但不要主动转述群聊内容、群聊争论、群友评价或其他人的发言。"
            "只有当对方主动提到群聊上下文时，才可以简短承接。不要输出这段识别规则。"
        ),
        description="私聊回复时注入给模型的跨场景身份提示模板",
    )


class SummarySectionConfig(PluginConfigBase):
    """近期聊天摘要设置。"""

    __ui_label__ = "近期摘要"
    __ui_icon__ = "history"
    __ui_order__ = 3

    enabled: bool = Field(default=True, description="是否为身份档案保存近期聊天摘要片段")
    max_items_per_profile: int = Field(default=16, ge=1, description="每个 QQ 最多保存多少条近期片段")
    max_chars_per_message: int = Field(default=60, ge=10, description="单条发言片段最多保留多少字")
    max_prompt_chars: int = Field(default=360, ge=80, description="注入 prompt 的近期摘要最长字数")
    max_age_hours: int = Field(default=168, ge=1, description="近期摘要保留窗口，默认 7 天")
    include_private_when_group: bool = Field(default=True, description="群聊中是否注入该人的近期私聊摘要")
    include_group_when_private: bool = Field(default=True, description="私聊中是否注入该人的近期群聊摘要")


class IdentityLinkerConfig(PluginConfigBase):
    """插件配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    identity: IdentitySectionConfig = Field(default_factory=IdentitySectionConfig)
    prompt: PromptSectionConfig = Field(default_factory=PromptSectionConfig)
    summary: SummarySectionConfig = Field(default_factory=SummarySectionConfig)


class IdentityLinkerPlugin(MaiBotPlugin):
    """记录 QQ 身份在私聊/群聊中的出现，并在群聊回复前注入识别提示。"""

    config_model = IdentityLinkerConfig

    async def on_load(self) -> None:
        self._ensure_state()
        self.ctx.logger.info("跨场景身份识别插件已加载")

    async def on_unload(self) -> None:
        self._save_state()
        self.ctx.logger.info("跨场景身份识别插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, object], version: str) -> None:
        del scope, config_data, version
        self.ctx.logger.info("跨场景身份识别配置已更新")

    @HookHandler(
        "chat.receive.after_process",
        name="identity_linker_record_inbound",
        description="记录入站消息的 QQ 身份在私聊/群聊中的出现",
        mode=HookMode.BLOCKING,
        order=HookOrder.LATE,
        timeout_ms=3000,
        error_policy=ErrorPolicy.SKIP,
    )
    async def remember_identity(self, message: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any] | None:
        del kwargs

        if not self.config.plugin.enabled or not isinstance(message, dict):
            return None
        if bool(message.get("is_notify")):
            return None

        identity = _extract_identity(message)
        if identity is None:
            return None
        if self.config.identity.ignore_self_messages and self._is_self_identity(message, identity["qq_id"]):
            return None
        identity["message_excerpt"] = _extract_message_excerpt(
            message,
            int(self.config.summary.max_chars_per_message),
        )

        self._ensure_state()
        self._remember_identity(identity)
        self._save_state()
        if self.config.identity.log_updates:
            self.ctx.logger.info(
                "身份索引已更新: user=%s session=%s group=%s private_seen=%s",
                _mask_id(identity["qq_id"]),
                identity["session_id"],
                identity["is_group"],
                self._profile_for(identity["qq_id"]).get("private_count", 0) > 0,
            )
        return None

    @HookHandler(
        "maisaka.replyer.before_model_request",
        name="identity_linker_inject_prompt",
        description="在群聊回复前注入跨私聊/群聊身份识别提示",
        mode=HookMode.BLOCKING,
        order=HookOrder.LATE,
        timeout_ms=3000,
        error_policy=ErrorPolicy.SKIP,
    )
    async def inject_identity_context(self, messages: Any = None, **kwargs: Any) -> dict[str, Any] | None:
        if not self.config.plugin.enabled or not isinstance(messages, list):
            return None

        self._ensure_state()
        session_id = _clean_text(kwargs.get("session_id"), 120)
        reply_message_id = _clean_text(kwargs.get("reply_message_id"), 120)
        context = self._resolve_identity_context(session_id, reply_message_id)
        if context is None:
            return None

        prompt = self._render_prompt(context)
        new_messages = _inject_prompt(messages, prompt)
        modified_kwargs = dict(kwargs)
        modified_kwargs["messages"] = new_messages
        return {"action": "continue", "modified_kwargs": modified_kwargs}

    def _ensure_state(self) -> None:
        if hasattr(self, "_state") and isinstance(self._state, dict):
            return

        state_path = Path(__file__).resolve().parent / "data" / "identity_index.json"
        self._state_path = state_path
        self._state = _load_state(state_path)

    def _save_state(self) -> None:
        self._ensure_state()
        state_path = self._state_path
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = state_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(state_path)

    def _is_self_identity(self, message: dict[str, Any], qq_id: str) -> bool:
        configured = {_normalize_id(item) for item in self.config.identity.bot_user_ids}
        configured.discard("")
        if qq_id in configured:
            return True

        info = message.get("message_info")
        additional_config = {}
        if isinstance(info, dict) and isinstance(info.get("additional_config"), dict):
            additional_config = info["additional_config"]
        return qq_id in _extract_self_ids(additional_config)

    def _remember_identity(self, identity: dict[str, Any]) -> None:
        now = identity["ts"]
        state = self._state
        profiles = state.setdefault("profiles", {})
        profile = profiles.setdefault(identity["qq_id"], _new_profile(identity["qq_id"], now))

        profile["last_seen"] = now
        profile["latest_nickname"] = identity["nickname"]
        profile["latest_cardname"] = identity["cardname"]
        profile["latest_display_name"] = identity["display_name"]

        if identity["is_group"]:
            profile["group_count"] = int(profile.get("group_count") or 0) + 1
            profile["last_group_seen"] = now
            group_sessions = profile.setdefault("group_sessions", {})
            group_sessions[identity["session_id"]] = {
                "session_id": identity["session_id"],
                "group_id": identity["group_id"],
                "group_name": identity["group_name"],
                "display_name": identity["display_name"],
                "nickname": identity["nickname"],
                "cardname": identity["cardname"],
                "last_seen": now,
            }
        else:
            profile["private_count"] = int(profile.get("private_count") or 0) + 1
            profile["last_private_seen"] = now
            profile["private_nickname"] = identity["nickname"] or profile.get("private_nickname", "")
            profile["private_display_name"] = identity["display_name"] or profile.get("private_display_name", "")
            private_sessions = list(profile.get("private_session_ids") or [])
            if identity["session_id"] and identity["session_id"] not in private_sessions:
                private_sessions.append(identity["session_id"])
            profile["private_session_ids"] = private_sessions[-20:]

        if identity["message_id"]:
            state.setdefault("message_to_user", {})[identity["message_id"]] = {
                "qq_id": identity["qq_id"],
                "session_id": identity["session_id"],
                "is_group": identity["is_group"],
                "ts": now,
            }
        if identity["session_id"]:
            state.setdefault("session_last_user", {})[identity["session_id"]] = {
                "qq_id": identity["qq_id"],
                "is_group": identity["is_group"],
                "ts": now,
            }
        profile["relationship_summary"] = _build_relationship_summary(profile)
        profile["relationship_summary_updated_at"] = now
        if self.config.summary.enabled:
            _remember_recent_chat_item(profile, identity, self.config.summary)
            profile["recent_chat_summary"] = _build_recent_chat_summary(
                profile,
                include_private=True,
                include_group=True,
                max_prompt_chars=int(self.config.summary.max_prompt_chars),
                max_age_hours=int(self.config.summary.max_age_hours),
            )
            profile["recent_chat_summary_updated_at"] = now
        state["updated_at"] = now
        self._prune_state()

    def _prune_state(self) -> None:
        state = self._state
        message_to_user = state.setdefault("message_to_user", {})
        max_message_index = int(self.config.identity.max_message_index)
        if len(message_to_user) > max_message_index:
            ordered = sorted(message_to_user.items(), key=lambda item: float(item[1].get("ts") or 0))
            state["message_to_user"] = dict(ordered[-max_message_index:])

        profiles = state.setdefault("profiles", {})
        max_profiles = int(self.config.identity.max_profiles)
        if len(profiles) > max_profiles:
            ordered_profiles = sorted(profiles.items(), key=lambda item: float(item[1].get("last_seen") or 0))
            state["profiles"] = dict(ordered_profiles[-max_profiles:])

    def _profile_for(self, qq_id: str) -> dict[str, Any]:
        return self._state.setdefault("profiles", {}).setdefault(qq_id, _new_profile(qq_id, time.time()))

    def _resolve_identity_context(self, session_id: str, reply_message_id: str) -> dict[str, Any] | None:
        state = self._state
        current = None
        if reply_message_id:
            current = state.get("message_to_user", {}).get(reply_message_id)
        if current is None and session_id:
            current = state.get("session_last_user", {}).get(session_id)
        if not isinstance(current, dict):
            return None

        current_is_group = bool(current.get("is_group"))

        qq_id = _normalize_id(current.get("qq_id"))
        if not qq_id:
            return None
        profile = state.get("profiles", {}).get(qq_id)
        if not isinstance(profile, dict):
            return None
        private_count = int(profile.get("private_count") or 0)
        group_count = int(profile.get("group_count") or 0)

        if current_is_group:
            if not self.config.prompt.inject_in_group:
                return None
            if self.config.prompt.require_private_seen and private_count <= 0:
                return None
        else:
            if self.config.prompt.group_only or not self.config.prompt.inject_in_private:
                return None
            if self.config.prompt.require_group_seen and group_count <= 0:
                return None

        if private_count <= 0 and group_count <= 0:
            return None

        group_session = {}
        group_sessions = profile.get("group_sessions")
        if isinstance(group_sessions, dict):
            if current_is_group:
                group_session = group_sessions.get(session_id) if isinstance(group_sessions.get(session_id), dict) else {}
            if not group_session:
                group_session = _latest_group_session(profile)

        return {
            "is_group": current_is_group,
            "qq_id": qq_id,
            "private_display_name": _first_non_empty(
                profile.get("private_display_name"),
                profile.get("private_nickname"),
                profile.get("latest_display_name"),
                "这个人",
            ),
            "group_display_name": _first_non_empty(
                group_session.get("display_name") if isinstance(group_session, dict) else "",
                profile.get("latest_display_name"),
                profile.get("latest_nickname"),
                "这位群友",
            ),
            "group_name": _first_non_empty(
                group_session.get("group_name") if isinstance(group_session, dict) else "",
                "当前群聊",
            ),
            "relationship_summary": _first_non_empty(
                profile.get("relationship_summary"),
                _build_relationship_summary(profile),
                "这是你在不同聊天场景里见过的人；保持自然熟悉，但不要主动提私聊内容。",
            ),
            "recent_chat_summary": self._resolve_recent_chat_summary(profile, current_is_group),
        }

    def _render_prompt(self, context: dict[str, Any]) -> str:
        qq_id_line = f"- QQ 号：{context['qq_id']}\n" if self.config.prompt.include_qq_id else ""
        raw_template = self.config.prompt.template if context["is_group"] else self.config.prompt.private_template
        template = str(raw_template or "").strip() or _MARKER
        return template.format(
            group_display_name=context["group_display_name"],
            private_display_name=context["private_display_name"],
            group_name=context["group_name"],
            relationship_summary=context["relationship_summary"],
            recent_chat_summary=context["recent_chat_summary"],
            qq_id_line=qq_id_line,
        )

    def _resolve_recent_chat_summary(self, profile: dict[str, Any], current_is_group: bool) -> str:
        if not self.config.summary.enabled:
            return "暂无可用的近期聊天摘要。"
        include_private = (not current_is_group) or self.config.summary.include_private_when_group
        include_group = current_is_group or self.config.summary.include_group_when_private
        summary = _build_recent_chat_summary(
            profile,
            include_private=include_private,
            include_group=include_group,
            max_prompt_chars=int(self.config.summary.max_prompt_chars),
            max_age_hours=int(self.config.summary.max_age_hours),
        )
        return summary or "暂无可用的近期聊天摘要。"


def _empty_state() -> dict[str, Any]:
    return {
        "version": _STATE_VERSION,
        "profiles": {},
        "message_to_user": {},
        "session_last_user": {},
        "updated_at": 0,
    }


def _load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return _empty_state()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_state()
    if not isinstance(loaded, dict):
        return _empty_state()
    state = _empty_state()
    state.update({key: value for key, value in loaded.items() if key in state})
    if not isinstance(state.get("profiles"), dict):
        state["profiles"] = {}
    if not isinstance(state.get("message_to_user"), dict):
        state["message_to_user"] = {}
    if not isinstance(state.get("session_last_user"), dict):
        state["session_last_user"] = {}
    for profile in state["profiles"].values():
        if not isinstance(profile, dict):
            continue
        if not _clean_text(profile.get("relationship_summary"), 300):
            profile["relationship_summary"] = _build_relationship_summary(profile)
        if "relationship_summary_updated_at" not in profile:
            profile["relationship_summary_updated_at"] = 0
        if not isinstance(profile.get("recent_chat_items"), list):
            profile["recent_chat_items"] = []
        else:
            profile["recent_chat_items"] = _normalize_recent_chat_items(
                profile.get("recent_chat_items"),
                max_items=_DEFAULT_RECENT_CHAT_ITEMS_LIMIT,
                max_age_hours=_DEFAULT_RECENT_CHAT_AGE_HOURS,
            )
        if not _clean_text(profile.get("recent_chat_summary"), 500):
            profile["recent_chat_summary"] = _build_recent_chat_summary(
                profile,
                include_private=True,
                include_group=True,
                max_prompt_chars=360,
                max_age_hours=_DEFAULT_RECENT_CHAT_AGE_HOURS,
            )
        if "recent_chat_summary_updated_at" not in profile:
            profile["recent_chat_summary_updated_at"] = 0
    state["version"] = _STATE_VERSION
    return state


def _new_profile(qq_id: str, now: float) -> dict[str, Any]:
    return {
        "qq_id": qq_id,
        "first_seen": now,
        "last_seen": now,
        "latest_nickname": "",
        "latest_cardname": "",
        "latest_display_name": "",
        "private_nickname": "",
        "private_display_name": "",
        "private_session_ids": [],
        "private_count": 0,
        "last_private_seen": 0,
        "group_sessions": {},
        "group_count": 0,
        "last_group_seen": 0,
        "relationship_summary": "",
        "relationship_summary_updated_at": 0,
        "recent_chat_items": [],
        "recent_chat_summary": "",
        "recent_chat_summary_updated_at": 0,
    }


def _build_relationship_summary(profile: dict[str, Any]) -> str:
    private_count = int(profile.get("private_count") or 0)
    group_count = int(profile.get("group_count") or 0)
    private_name = _first_non_empty(profile.get("private_display_name"), profile.get("private_nickname"))
    latest_name = _first_non_empty(profile.get("latest_display_name"), profile.get("latest_nickname"))
    group_names = _recent_group_names(profile)

    parts: list[str] = []
    if private_count > 0 and group_count > 0:
        parts.append(f"私聊里{_count_label(private_count)}，群聊里也{_count_label(group_count)}")
    elif private_count > 0:
        parts.append(f"主要来自私聊，已{_count_label(private_count)}")
    elif group_count > 0:
        parts.append(f"主要来自群聊，已{_count_label(group_count)}")
    else:
        parts.append("刚建立身份档案")

    if private_name and latest_name and private_name != latest_name:
        parts.append(f"私聊称呼偏向“{private_name}”，当前场景称呼偏向“{latest_name}”")
    elif private_name:
        parts.append(f"常见称呼是“{private_name}”")
    elif latest_name:
        parts.append(f"常见称呼是“{latest_name}”")

    if group_names:
        parts.append(f"群聊场景包括{_join_names(group_names)}")

    parts.append("可按熟人语气自然回应，但不要主动提私聊内容")
    return "；".join(parts)


def _recent_group_names(profile: dict[str, Any], limit: int = 2) -> list[str]:
    group_sessions = profile.get("group_sessions")
    if not isinstance(group_sessions, dict):
        return []
    rows = [
        item
        for item in group_sessions.values()
        if isinstance(item, dict) and _clean_text(item.get("group_name"), 80)
    ]
    rows.sort(key=lambda item: float(item.get("last_seen") or 0), reverse=True)
    result: list[str] = []
    for item in rows:
        name = _clean_text(item.get("group_name"), 80)
        if name and name not in result:
            result.append(name)
        if len(result) >= limit:
            break
    return result


def _latest_group_session(profile: dict[str, Any]) -> dict[str, Any]:
    group_sessions = profile.get("group_sessions")
    if not isinstance(group_sessions, dict):
        return {}
    rows = [item for item in group_sessions.values() if isinstance(item, dict)]
    if not rows:
        return {}
    rows.sort(key=lambda item: float(item.get("last_seen") or 0), reverse=True)
    return rows[0]


def _remember_recent_chat_item(
    profile: dict[str, Any],
    identity: dict[str, Any],
    summary_config: SummarySectionConfig,
) -> None:
    excerpt = _clean_text(identity.get("message_excerpt"), int(summary_config.max_chars_per_message))
    if not excerpt:
        return

    item = {
        "ts": float(identity["ts"]),
        "scope": "group" if identity["is_group"] else "private",
        "session_id": identity["session_id"],
        "place": identity["group_name"] if identity["is_group"] else "私聊",
        "excerpt": excerpt,
    }
    profile["recent_chat_items"] = _normalize_recent_chat_items(
        list(profile.get("recent_chat_items") or []) + [item],
        max_items=int(summary_config.max_items_per_profile),
        max_age_hours=int(summary_config.max_age_hours),
    )


def _normalize_recent_chat_items(value: Any, *, max_items: int, max_age_hours: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    cutoff = time.time() - max_age_hours * 3600 if max_age_hours > 0 else 0
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        ts = _safe_float(item.get("ts"), 0)
        excerpt = _clean_text(item.get("excerpt"), 160)
        if ts <= 0 or not excerpt:
            continue
        if cutoff and ts < cutoff:
            continue
        scope = "group" if str(item.get("scope") or "") == "group" else "private"
        result.append(
            {
                "ts": ts,
                "scope": scope,
                "session_id": _clean_text(item.get("session_id"), 160),
                "place": _clean_text(item.get("place"), 120) or ("群聊" if scope == "group" else "私聊"),
                "excerpt": excerpt,
            }
        )
    result.sort(key=lambda row: float(row["ts"]))
    return result[-max(1, int(max_items)) :]


def _build_recent_chat_summary(
    profile: dict[str, Any],
    *,
    include_private: bool,
    include_group: bool,
    max_prompt_chars: int,
    max_age_hours: int,
) -> str:
    items = _normalize_recent_chat_items(
        profile.get("recent_chat_items"),
        max_items=32,
        max_age_hours=max_age_hours,
    )
    if not items:
        return ""

    filtered: list[dict[str, Any]] = []
    for item in reversed(items):
        if item["scope"] == "private" and not include_private:
            continue
        if item["scope"] == "group" and not include_group:
            continue
        filtered.append(item)
        if len(filtered) >= 8:
            break
    if not filtered:
        return ""

    segments: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for item in filtered:
        key = (item["scope"], item["place"], item["excerpt"])
        if key in seen:
            continue
        seen.add(key)
        segments.append(_format_recent_chat_item(item))
    return _truncate_text("；".join(segments), max_prompt_chars)


def _format_recent_chat_item(item: dict[str, Any]) -> str:
    time_text = _format_ts(item["ts"])
    if item["scope"] == "group":
        return f"{time_text} 在群聊“{item['place']}”提到：“{item['excerpt']}”"
    return f"{time_text} 在私聊提到：“{item['excerpt']}”"


def _format_ts(value: Any) -> str:
    ts = _safe_float(value, 0)
    if ts <= 0:
        return "时间未知"
    return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


def _extract_message_excerpt(message: dict[str, Any], limit: int) -> str:
    text = _clean_text(message.get("processed_plain_text"), max(limit * 3, limit))
    if not text:
        text = _extract_text_from_raw_message(message.get("raw_message"))
    return _truncate_text(text, limit)


def _extract_text_from_raw_message(raw_message: Any) -> str:
    if not isinstance(raw_message, list):
        return ""
    texts: list[str] = []
    for part in raw_message:
        if not isinstance(part, dict) or part.get("type") != "text":
            continue
        data = part.get("data")
        if isinstance(data, str):
            text = _clean_text(data, 200)
            if text:
                texts.append(text)
    return " ".join(texts)


def _truncate_text(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(0, int(limit) - 1)].rstrip() + "…"


def _count_label(count: int) -> str:
    if count <= 1:
        return "有过一次接触"
    if count < 5:
        return "有过几次接触"
    return "有过多次接触"


def _join_names(names: list[str]) -> str:
    quoted = [f"“{name}”" for name in names if name]
    return "、".join(quoted)


def _extract_identity(message: dict[str, Any]) -> dict[str, Any] | None:
    info = message.get("message_info")
    if not isinstance(info, dict):
        return None
    user_info = info.get("user_info")
    if not isinstance(user_info, dict):
        return None
    qq_id = _normalize_id(user_info.get("user_id"))
    if not qq_id:
        return None

    group_info = info.get("group_info")
    is_group = isinstance(group_info, dict) and bool(_clean_text(group_info.get("group_id"), 80))
    nickname = _clean_text(user_info.get("user_nickname"), 80)
    cardname = _clean_text(user_info.get("user_cardname"), 80)
    display_name = _first_non_empty(cardname, nickname, qq_id)
    ts = _safe_float(message.get("timestamp"), time.time())

    return {
        "qq_id": qq_id,
        "message_id": _clean_text(message.get("message_id"), 120),
        "session_id": _clean_text(message.get("session_id"), 160),
        "platform": _clean_text(message.get("platform"), 40),
        "nickname": nickname,
        "cardname": cardname,
        "display_name": display_name,
        "is_group": is_group,
        "group_id": _clean_text(group_info.get("group_id"), 80) if isinstance(group_info, dict) else "",
        "group_name": _clean_text(group_info.get("group_name"), 120) if isinstance(group_info, dict) else "",
        "ts": ts,
    }


def _inject_prompt(messages: list[Any], prompt: str) -> list[Any]:
    updated: list[Any] = []
    for item in messages:
        if not isinstance(item, dict):
            updated.append(item)
            continue
        content = str(item.get("content_text") or item.get("content") or "")
        if str(item.get("role") or "").lower() == "system" and _MARKER in content:
            continue
        updated.append(dict(item))

    insert_pos = 0
    for index, item in enumerate(updated):
        if isinstance(item, dict) and item.get("role") == "system":
            insert_pos = index + 1
        else:
            break

    updated.insert(insert_pos, {"role": "system", "content": prompt, "content_text": prompt})
    return updated


def _extract_self_ids(value: Any, depth: int = 0) -> set[str]:
    if depth > 5:
        return set()
    result: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key or "").strip().lower()
            if key_text in _SELF_ID_KEYS:
                normalized = _normalize_id(item)
                if normalized:
                    result.add(normalized)
            result.update(_extract_self_ids(item, depth + 1))
    elif isinstance(value, list):
        for item in value:
            result.update(_extract_self_ids(item, depth + 1))
    return result


def _normalize_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return "".join(ch for ch in text if ch.isdigit()) or text[:80]


def _clean_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = _clean_text(value, 120)
        if text:
            return text
    return ""


def _mask_id(value: str) -> str:
    if len(value) <= 4:
        return "****"
    return value[:2] + "***" + value[-2:]


def create_plugin() -> IdentityLinkerPlugin:
    return IdentityLinkerPlugin()
