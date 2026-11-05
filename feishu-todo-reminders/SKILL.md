---
name: feishu-todo-reminders
description: 搭建、维护和迁移飞书机器人 /todo 待办日志与工作日提醒，包括文档勾选清单、原生斜杠菜单、后台收件、Codex定时推送及换账号/换电脑恢复。不替代通用飞书原生任务管理。
metadata:
  requires:
    bins: [lark-cli]
    skills: [lark-shared, lark-doc, lark-im, lark-event]
---

# 飞书待办提醒

本功能用云文档里的原生checkbox保存待办，不用飞书原生Task，不需要lark-task、大模型API或API Key。

## 行为约定

- `/todo 事项`添加一项，完整保留命令后的文字。一条消息一项，下一条普通聊天不记录。
- 单独`/todo`即时推送最新未完成清单，不新增任务、不占用当天定时提醒回执。
- 只处理配置中本人对该机器人发的私聊文字。没有持续模式、/exit、待办：、完成：、取消：文字入口或子指令。
- 文档按创建日期YYYY-MM-DD分节，新任务放在当天标题下，同一天复用标题，无新任务不创建空日期标题。默认Asia/Shanghai；完成直接勾选，取消直接删除，只按checkbox勾选状态过滤。
- 提醒按文档原顺序列出未勾选事项，不显示日期或分组。原生post标题为“今日待办提醒⏰”，图标前无空格；普通文字“文档：”与上方清单空一行，后接文档链接。
- 默认由Codex周一至周五上午10点提醒，不自动识别法定节假日/调休。用户要求另一日历时再扩展。

## 依赖与路由

lark-cli是实际执行工具；以下Skills是操作指令，不是运行服务。复制本Skill不等于安装CLI、依赖Skills或完成登录。

| 依赖 | 用途 / 何时读取 |
| --- | --- |
| Python 3.11+、sqlite3、zoneinfo | 附带脚本；除部分系统需tzdata外使用标准库 |
| lark-cli | profile、OAuth、文档、消息、事件、斜杠注册；1.0.98已验证，升级后核对help/schema |
| lark-shared | 初始化应用、身份、授权、scope和输出契约；接入/认证问题先读 |
| lark-doc | 文档创建/读取/编辑；按场景读fetch/update/XML或创建参考 |
| lark-im | 消息发送/回复；读send/reply参考，普通post不需交互卡片工作流 |
| lark-event | im.message.receive_v1长连接及ready、EOF、重连规则 |
| openai-docs（配置Codex定时任务时） | 当前定时工具、沙箱与权限；有automation_update时用工具管理 |
| lark-drive / lark-wiki（按需） | 找文档、共享或知识库结构；已有可访问URL时不必引入 |

- 从零安装、授权、文档与菜单：读[搭建流程](references/setup.md)。
- 换电脑、换账号/App、数据和状态迁移：读[迁移流程](references/migration.md)。
- Linux/macOS/Windows后台服务及Codex定时：读[后台与定时](references/operations.md)。
- 权限、重复、性能和不回复：读[排障](references/troubleshooting.md)。

## 执行资源

- `scripts/setup.py configure`：只读验证真实身份和文档，生成本机config及运行副本，不发消息、不改远端文档、不启服务。
- `setup.py service`：生成systemd/launchd/Windows任务文件，不自动安装。
- `setup.py import-state`：SQLite备份导入同App、同owner、同document的状态，拒绝跨账号混用。
- `setup.py automation-prompt`：生成交给automation_update的可读正文，不创建任务。
- 部署后`bot.py --check`：校验身份、文档读及本地状态写入，不发消息。
- `bot.py --render-reminder`：只读输出原生post JSON。
- `bot.py --send-reminder`：有副作用，发送当天工作日提醒并保存每日去重回执；仅在用户授权范围执行。
- `scripts/test_runtime.py`：隔离测试，不访问飞书。

所有调用固定使用本机真实绝对路径及指定profile。App ID、open_id、文档、时区和路径来自本机config，不能沿用过去机器的示例。config、状态库、日志、凭据不进入Skill分发包。运行代码更新后要部署副本并重启；不能只改Skill就声称服务生效。模板修改后同步已有自动化，手动与定时共用代码。

## 验收

依范围验证：CLI与依赖→指定profile身份→文档可读写→斜杠服务端注册及客户端可选→服务ready→真实/todo添加与空命令提醒→勾选/删除后更新→定时绑定、去重及无人值守到点成功。区分生成配置、服务活着、message_id回执和实际到点成功，没测到的不宣称已验证。普通聊天不得误入库。
