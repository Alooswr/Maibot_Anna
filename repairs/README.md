# Repaired Third-Party Plugin Files

这里放的是 Anna 线上部署中修过的第三方插件单文件替换版。

这些文件不是原创插件仓库的完整发布版；使用前请先备份你自己的插件文件，再按路径覆盖。

## com_0-hz_maibot-corpus-callosum

文件：

```text
repairs/com_0-hz_maibot-corpus-callosum/plugin.py
```

修复点：

- 避免 `<reject>` / `<veto>` 一类内部控制标记穿透到最终可见回复。
- 连续 veto 达到上限后，不再继续向 replyer 注入再审协议，也不再让控制标记通过。
- 对 veto reason 做清理和长度限制，避免内部审查文本进入对话上下文后再泄露。

安装：

```bash
cd /path/to/MaiBot/data/MaiMBot/plugins/com_0-hz_maibot-corpus-callosum
cp plugin.py plugin.py.backup.before-anna-repair
cp /path/to/Maibot_Anna/repairs/com_0-hz_maibot-corpus-callosum/plugin.py ./plugin.py
```

## MaiBot-Napcat-Adapter

文件：

```text
repairs/MaiBot-Napcat-Adapter/runtime/router.py
```

修复点：

- 修复私聊自身回显误判。
- 判断机器人自己的消息时，同时比较 `payload.user_id`、`sender.user_id`、`sender.uin` 和当前 `self_id`。
- 避免只看顶层 `user_id` 导致机器人把自己发出的私聊消息当成用户新消息。

安装：

```bash
cd /path/to/MaiBot/data/MaiMBot/plugins/MaiBot-Napcat-Adapter/runtime
cp router.py router.py.backup.before-anna-repair
cp /path/to/Maibot_Anna/repairs/MaiBot-Napcat-Adapter/runtime/router.py ./router.py
```

覆盖后重启 MaiBot core：

```bash
docker restart maim-bot-core
```

如果你的上游插件版本和 Anna 线上版本差异很大，不建议直接覆盖；应手工迁移上述修复点。
