# MaiBot Local Plugins

这里整理的是 Anna 这台 MaiBot 部署中可公开复用的本地插件副本。
猫猫牌创口贴，让您的麦麦不会轻易受伤~
修复了了一些小小小小小问题，疑似Anna的哈士奇在拆家？
小老鼠叼走了大猫咪————这可能是平行宇宙的代码掉到了麦麦的脑袋里

## 包含的插件

- `local_thought-leak-guard`: 发送前清理 `<think>`、`analysis`、`reasoning`、`<reject>` 等内部思考/控制片段，避免泄露到 QQ。
- `local_precise-time-context`: 在模型请求前注入当前 Asia/Shanghai 时间、星期和时段信息，减少时间判断错误。
- `local_group-dialogue-targeting`: 在群聊提示里强调“先判断谁在对谁说话”，降低机器人把群友之间的对话误判成对自己说话的概率。
- `local_identity-linker`: 用 QQ id 作为跨私聊/群聊的身份键，注入熟悉度提示，并带隐私边界约束，避免主动公开私聊内容。

## 我们修复过的第三方插件

见 `repairs/`：

- `com_0-hz_maibot-corpus-callosum/plugin.py`: 修复 `<reject>` / `<veto>` 等内部控制标记泄露风险。
- `MaiBot-Napcat-Adapter/runtime/router.py`: 修复私聊自身回显误判，避免机器人回复自己。

见 `patches/`：

- `emilia-mimotts-default-style.patch`: 给 MiMo TTS 插件固定默认少女感声音基底，降低每轮语音风格漂移。

## 安装

把需要的目录复制到 MaiBot 插件目录，例如：

```bash
cd /path/to/MaiBot/data/MaiMBot/plugins
cp -r /path/to/maibot-local-plugins/plugins/local_thought-leak-guard .
```

然后重启 MaiBot core：

```bash
docker restart maim-bot-core
```

## 配置

每个插件目录内都带有 `config.toml`。发布版配置不包含 Anna 服务器上的 QQ 号、群号、运行数据或日志。

`local_identity-linker` 使用前建议设置：

```toml
[identity]
bot_user_ids = ["你的机器人 QQ 号"]
```

不设置也能运行，但某些 NapCat 自身回显场景可能需要显式填写机器人自己的 QQ 号，才能更稳定过滤机器人自己的消息。

## 未直接打包的内容

第三方插件或上游插件的本地改动不直接混进本仓库，以免误把别人的项目当成原创发布。相关补丁如果需要，会放在 `patches/` 目录，并标明上游仓库和适用版本。

不建议把线上 WebUI 直接开放给群友看插件，因为 WebUI 可能暴露运行日志、配置、控制入口和隐私数据。公开 GitHub 仓库更安全。
