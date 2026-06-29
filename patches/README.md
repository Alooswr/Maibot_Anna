# Upstream Plugin Patches

这个目录用于记录线上部署中改过的第三方插件补丁。

## Emilia-awa_maibot-mimotts-voice

- Patch: `emilia-mimotts-default-style.patch`
- 作用：给 `send_voice_reply` 固定一个稳定的默认少女感声音基底，并把每轮 `style_instruction` 限制为轻量情绪补充，避免每次语音风格漂移。
- 应用方式：在对应插件目录中备份 `plugin.py` 后执行：

```bash
patch -p0 < /path/to/emilia-mimotts-default-style.patch
```

## com_0-hz_maibot-corpus-callosum

线上版本做过安全修正：不再让 `<reject>` / `<veto>` 这类内部控制标记穿透到可见回复路径，并在连续 veto 场景下清理响应。

当前仓库在 `repairs/com_0-hz_maibot-corpus-callosum/plugin.py` 提供修复后的单文件替换版。

## MaiBot-Napcat-Adapter

线上版本修过私聊自身回显过滤：判断自身消息时不能只看顶层 `payload.user_id`，还要比较 `sender.user_id`、`sender.uin` 和当前 `self_id`。

当前仓库在 `repairs/MaiBot-Napcat-Adapter/runtime/router.py` 提供修复后的单文件替换版。

如果要把这两项整理成上游 PR，建议单独 fork 对应上游插件仓库，从上游当前版本重新生成最小 diff。
