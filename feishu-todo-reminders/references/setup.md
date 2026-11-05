# 从零搭建

## 依赖安装

检查 `lark-cli --version`、Python版本和必要命令help。需要Python 3.11+、其标准库SQLite及IANA时区数据。Windows若ZoneInfo失败，在所用Python环境安装tzdata。Node.js/npm/npx只用于所选安装方式，不是机器人运行依赖。

CLI官方来源：[larksuite/cli](https://github.com/larksuite/cli)。当前可用 `npx @larksuite/cli@latest install`，新环境先核对官方安装说明和系统架构，勿重复安装已有程序。检查docs +fetch/+update、im +messages-send/+messages-reply、event schema im.message.receive_v1、application +slash-command-create的help是否可用。

安装或定位lark-shared、lark-doc、lark-im、lark-event的完整Skill目录，保留references。CLI的 `skills list/read` 可以查看内置说明，但不代表Codex已经发现这些Skill。可按官方提供的 `npx skills add larksuite/cli -g -y` 安装或使用环境的skill-installer，并检查当前Codex能发现依赖。配置定时任务时再用openai-docs。

## 应用、profile与身份

先读lark-shared和config-init / identity-and-permissions参考。

1. 已有应用优先复用，`lark-cli profile list`确认真实profile；不静默切换全局默认profile。
2. 无应用时按 `lark-cli config init --new`流程建立/绑定应用，启用机器人、本人可用范围并发布。授权/控制台URL按lark-shared原样展示并配CLI二维码。
3. 多个应用用独立profile。`profile add --name ... --app-id ... --app-secret-stdin`前先查help；Secret走安全stdin或官方绑定流程，不写脚本、参数、聊天或shell历史。
4. 用户身份用于本人文档，bot身份用于收私聊、发送/回复。bot缺scope去后台开通并发布，不能用用户OAuth替代。
5. 用户按文档需要授权docs域，必要时加drive解析wiki。例：指定profile后 `auth login --domain docs --domain drive --no-wait --json`。不要默认申请all。按split-flow展示授权链接和二维码、交还控制，用户完成后再由agent用device-code完成；过期就新建，不复制旧令牌/链接。

| 行为 | 身份和能力 |
| --- | --- |
| 读、创建、编辑台账，解析wiki | user，文档内容读写/创建与相应节点权限，且账号本身能访问文档 |
| 接收本人私聊 | bot，im:message.p2p_msg:readonly，订阅im.message.receive_v1 |
| 主动发送/回复 | bot，im:message:send_as_bot，已发布且本人在可用范围 |
| 原生斜杠注册 | bot，application:app_slash_command:read及:write |

精确最小scope依当前CLI schema、missing_scopes和官方后台确定，勿盲目扩大。事件与回调配置长连接接收及“接收消息”，新增权限/订阅后按飞书要求发布。不需要card.action.trigger。

## 文档与本机配置

复用已有URL，先 `docs +fetch --as user --detail full`取得真实document_id；不把wiki token猜成docx ID。无台账时读lark-doc创建参考，空台账可以只有标题和“暂无待办。”，不放示例事项或空日期标题；语义创作遵循其创建工作流。任务结构：日期标题→原生checkbox，完成done=true，取消直接删除。周报区可选，标题包含“周报”后不收集任务。

以下示例参数由agent替换为本机实值，勿照抄他人账号：

```text
python <SKILL_DIR>/scripts/setup.py configure --profile <PROFILE_NAME> --doc <REAL_DOCUMENT_URL> --instance personal --timezone Asia/Shanghai
```

CLI不在PATH时加 `--cli <ABSOLUTE_CLI_PATH>`；自定义目录加 `--runtime-dir <ABSOLUTE_RUNTIME_DIR>`。不同账号、App或文档用新instance。脚本只读验证user/bot和文档，自动解析实际绑定，不创建远端资源、不发送、不启动。

默认运行目录：Linux `$XDG_DATA_HOME/feishu-todo-reminders/<instance>`（XDG默认~/.local/share）；macOS `~/Library/Application Support/feishu-todo-reminders/<instance>`；Windows `%LOCALAPPDATA%/feishu-todo-reminders/<instance>`。

config字段：schema_version、instance、cli_path、profile、app_id、owner_open_id、document_id、document_url、document_title、timezone、reminder_title、state_dir。没有Secret或token。收件人固定为已验证登录本人，不自动扩展到他人。

```text
python <RUNTIME_DIR>/bot.py --config <RUNTIME_DIR>/config.json --check
python <RUNTIME_DIR>/bot.py --config <RUNTIME_DIR>/config.json --render-reminder
```

均不发消息、不改文档。前者成功不等于主动发送或定时已成功。

## 原生斜杠菜单

指定同profile先list，缺少才create，已有则update保留command_id。不覆盖/删除别的功能。

```text
lark-cli --profile <PROFILE_NAME> application +slash-command-list --as bot
lark-cli --profile <PROFILE_NAME> application +slash-command-create --as bot --command todo --description "将本条消息中的事项记为待办，例如 /todo 写周报" --description-i18n zh_cn="将本条消息中的事项记为待办，例如 /todo 写周报"
```

服务端注册成功不等于客户端面板成功。等约5分钟缓存刷新或重开客户端，在该bot私聊空白框输入英文`/`验证；平台/版本差异须实际检查。手打/todo仍是同一协议。无需每次启动重复注册。

接[后台与定时](operations.md)。正式启动前确认旧实例停止。端到端用用户认可的真实事项验证：/todo添加→文档对应日期checkbox→下一条普通聊天不新增→空/todo显示清单→手动勾选/删除后不再出现。不偷偷往生产文档塞测试项。
