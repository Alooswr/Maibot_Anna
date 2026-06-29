"""Group dialogue target-awareness prompt injection for MaiBot."""

from __future__ import annotations

from typing import Any

from maibot_sdk import Field, HookHandler, MaiBotPlugin, PluginConfigBase
from maibot_sdk.types import ErrorPolicy, HookMode, HookOrder


_MARKER = "【群聊对象判断】"


class PluginSectionConfig(PluginConfigBase):
    """Base plugin settings."""

    __ui_label__ = "插件"
    __ui_icon__ = "messages-square"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(default="1.0.0", description="配置版本")


class TargetingSectionConfig(PluginConfigBase):
    """Group targeting prompt settings."""

    __ui_label__ = "对象判断"
    __ui_icon__ = "message-circle-question"
    __ui_order__ = 1

    group_only: bool = Field(default=True, description="只在检测到群聊 prompt 时注入")
    bot_names: list[str] = Field(default_factory=lambda: ["麦麦", "MaiBot"], description="麦麦可能被群友呼叫的名字")
    group_detection_keywords: list[str] = Field(
        default_factory=lambda: ["qq群", "群里正在聊", "群友", "group_id=", "qq_group_"],
        description="用于从 prompt 中识别群聊的关键词",
    )
    template: str = Field(
        default=(
            "【群聊对象判断】\n"
            "这是群聊，不是每一句话都在对你说。阅读最近聊天记录时，先在心里判断每条关键消息的："
            "发言人、可能对象、所属话题线、是否明确叫你。\n\n"
            "判断规则：\n"
            "1. 只有出现你的名字/昵称、明确 @ 你、回复引用你的消息、或内容明显在问你时，才把这句话优先理解为对你说。\n"
            "2. 如果一句话包含其他人的名字、@其他人、接着回答上一位群友、延续两个人之间的争论/玩笑/问答，"
            "优先认为是在对那个人或那条话题线说，不要默认是在对你说。\n"
            "3. 群聊里的“你”“你们”“这个”“刚才那个”通常指当前话题里的上一位发言者或被点名的人；"
            "除非上下文明确指向你，不要把“你”自动理解成你自己。\n"
            "4. “有人吗/大家/群里/有没有人/谁会”等公共问题可以视为公开话题；"
            "你可以在相关、自然、有帮助或有趣时简短加入。\n"
            "5. 如果当前消息明显是群友对群友说、找管理员、催别人、回答别人、吵架互怼或只是在抛表情包，"
            "不要抢答，不要把自己当成被询问对象。\n"
            "6. 回复时只接一个最合适的话题线；不要把多个群友的话混成一个人说的，也不要凭空替别人转述立场。\n"
            "7. 不要输出上述判断过程，只输出实际要发送到群里的自然回复。"
        ),
        description="注入到群聊模型请求中的对象判断提示",
    )


class GroupDialogueTargetingConfig(PluginConfigBase):
    """Plugin config."""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    targeting: TargetingSectionConfig = Field(default_factory=TargetingSectionConfig)


class GroupDialogueTargetingPlugin(MaiBotPlugin):
    """Inject group dialogue target-awareness rules into reply prompts."""

    config_model = GroupDialogueTargetingConfig

    async def on_load(self) -> None:
        self.ctx.logger.info("群聊对象判断提示插件已加载")

    async def on_unload(self) -> None:
        self.ctx.logger.info("群聊对象判断提示插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, object], version: str) -> None:
        del scope, config_data, version
        self.ctx.logger.info("群聊对象判断提示配置已更新")

    @HookHandler(
        "maisaka.replyer.before_model_request",
        name="inject_group_dialogue_targeting_prompt",
        description="向群聊模型请求注入群友发言对象判断提示",
        mode=HookMode.BLOCKING,
        order=HookOrder.LATE,
        timeout_ms=3000,
        error_policy=ErrorPolicy.SKIP,
    )
    async def inject_group_dialogue_targeting(self, messages: Any = None, **kwargs: Any) -> dict[str, Any] | None:
        if not self.config.plugin.enabled or not isinstance(messages, list):
            return None

        if self.config.targeting.group_only and not self._looks_like_group_chat(messages):
            return None

        prompt = self._render_prompt()
        new_messages = self._inject_prompt(messages, prompt)
        modified_kwargs = dict(kwargs)
        modified_kwargs["messages"] = new_messages
        return {"action": "continue", "modified_kwargs": modified_kwargs}

    def _render_prompt(self) -> str:
        bot_names = "、".join(name.strip() for name in self.config.targeting.bot_names if name.strip())
        prompt = str(self.config.targeting.template or "").strip()
        if bot_names:
            prompt = prompt.replace("你的名字/昵称", f"你的名字/昵称（{bot_names}）")
        return prompt or _MARKER

    def _looks_like_group_chat(self, messages: list[Any]) -> bool:
        text = "\n".join(
            str(message.get("content_text") or message.get("content") or "")
            for message in messages
            if isinstance(message, dict)
        )
        if not text.strip():
            return False
        keywords = [keyword for keyword in self.config.targeting.group_detection_keywords if str(keyword).strip()]
        return any(str(keyword).strip() in text for keyword in keywords)

    @staticmethod
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


def create_plugin() -> GroupDialogueTargetingPlugin:
    return GroupDialogueTargetingPlugin()
