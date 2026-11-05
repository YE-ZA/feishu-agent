# 从零搭建

## 公共前置检查

先按 [feishu-agent-setup](../../feishu-agent-setup/SKILL.md) 检查指定 profile 的 CLI/Python、真实 user/bot、机器人可用范围、私聊事件与发布状态；缺失时补齐，已有可用环境直接继续。不重复创建应用或重新授权。

## 待办专属依赖与权限

安装或定位 lark-doc 的完整 Skill 目录，保留 references。检查 docs +fetch/+update 和 application +slash-command-create 的当前 help；消息、事件和身份的公共依赖由 feishu-agent-setup 检查。配置 Codex 定时任务时再用 openai-docs。

在公共身份检查之上补待办能力：

| 行为 | 身份和能力 |
| --- | --- |
| 读、创建、编辑台账，解析wiki | user，文档内容读写/创建与相应节点权限，且账号本身能访问文档 |
| 主动提醒与命令回复 | bot，确认公共发送能力适用于当前本人私聊；主动发送仍需功能验收 |
| 原生斜杠注册 | bot，application:app_slash_command:read及:write |

精确 scope 看当前 CLI schema、missing_scopes 和后台；缺失时按公共 Skill 的授权路由补齐，不预先申请绘图等其他功能的权限。

## 文档与本机配置

复用已有URL，先 `docs +fetch --as user --detail full`取得真实document_id；不把wiki token猜成docx ID。无台账时读lark-doc创建参考，空台账可以只有标题和“暂无待办。”，不放示例事项或空日期标题；语义创作遵循其创建工作流。任务结构：日期标题→原生checkbox，完成done=true，取消直接删除。周报区可选，标题包含“周报”后不收集任务。

以下示例参数由agent替换为本机实值，勿照抄他人账号：

```text
python <SKILL_DIR>/scripts/setup.py configure --profile <PROFILE_NAME> --doc <REAL_DOCUMENT_URL> --instance personal --timezone Asia/Shanghai
```

CLI不在PATH时加 `--cli <ABSOLUTE_CLI_PATH>`；自定义目录加 `--runtime-dir <ABSOLUTE_RUNTIME_DIR>`。不同账号、App或文档用新instance。脚本只读验证user/bot和文档，自动解析实际绑定，不创建远端资源、不发送、不启动。

Skill 名为 `feishu-todo`；为兼容已有实例，默认运行目录与生成的服务名仍保留 `feishu-todo-reminders` 前缀，勿据技能改名搬动已有状态或重建服务。

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
