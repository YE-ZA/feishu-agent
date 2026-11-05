# 公共搭建

## 程序与依赖 Skills

先检查现有 `lark-cli --version`、Python 版本、CLI 路径和必要命令的 help，避免重复安装。附带的 draw/todo/remind 脚本需要 Python 3.11+、标准库 sqlite3 和 zoneinfo；缺 IANA 时区数据时在所用 Python 环境补 tzdata。绘图和定时提醒另有 fcntl，绘图还需渲染依赖，按对应 Skill 检查平台支持。

CLI 官方来源：[larksuite/cli](https://github.com/larksuite/cli)。安装前核对当前官方安装说明、系统架构及目标环境；原有搭建流程使用 `npx @larksuite/cli@latest install`。Node/npm/npx 是否需要取决于安装方式，不是 todo 的运行依赖。现有功能脚本在 lark-cli 1.0.98 验证过，新版本核对 help/schema。

定位或安装 lark-shared、lark-im、lark-event 的完整 Skill 目录，保留 references；功能专属依赖由对应 Skill 声明。CLI 的 `skills list/read` 可查看内置说明，但不代表宿主已经发现这些 Skills。原有安装方式包括 `npx skills add larksuite/cli -g -y`，安装前核对官方说明；也可使用环境的 skill-installer。安装后检查依赖实际可被发现。

## 应用、profile 与身份

先读 lark-shared；应用初始化读其 `references/lark-shared-config-init.md`，身份、认证和 scope 读 `references/lark-shared-identity-and-permissions.md`。以这些参考及当前 CLI help 为具体操作依据。

1. 用 `lark-cli profile list` 检查已有 profile，优先复用用户指定或能够明确对应的应用；后续调用显式指定 profile，不静默切换默认值。
2. 无可用应用时按 lark-shared 的 `config init --new` 流程建立或绑定应用。启用机器人，设置本人可用范围，并完成发布。已有应用只补齐缺失配置。
3. 多应用使用独立 profile。需要 `profile add` 时先查 help，Secret 使用安全 stdin 或官方绑定流程，不放入命令参数、脚本、聊天或 shell 历史。
4. 核实该 profile 的真实 user 和 bot、App ID 及本人 open_id。user 用于本人业务文档；bot 用于接收私聊、读取消息资源、发送和回复。open_id 按 App 隔离，不能复用其他 App 或账号的绑定。
5. 根据当前功能按需授权用户业务域和 bot scope。文档功能通常需要 docs，必要时用 drive 解析 Wiki；不默认申请 all。精确权限按当前 CLI schema、missing_scopes 和后台核实。授权链接、二维码和 split-flow 按 lark-shared 执行，不在公共文档复制认证步骤。

## 私聊与消息事件

阅读 lark-event 的消息事件与长连接说明；涉及收发消息时读 lark-im 对应参考。

| 公共能力 | 检查内容 |
| --- | --- |
| 接收本人私聊 | bot 的私聊接收能力；当前流程使用 im:message.p2p_msg:readonly |
| 主动发送与回复 | bot 的发送/回复能力；当前流程使用 im:message:send_as_bot，且本人在应用可用范围 |
| 收件事件 | 长连接接收、订阅 im.message.receive_v1，并完成所需发布 |
| 原生斜杠菜单 | 接入斜杠功能时核实 application:app_slash_command:read / :write；具体命令在功能 Skill 注册 |

draw/todo/remind 不需要 card.action.trigger；保留其他功能已有的事件和权限。新增权限或订阅后按飞书要求发布，不整批覆盖已有配置。已有服务在收件时，不为公共检查另启长期消费者或停止共享总线；实际长连接 ready 和真实收发由目标功能服务验收。

## 返回功能流程

记录已核实的路径、profile、App、本人身份和能力缺口，不输出原始认证文件。进入目标功能的搭建参考，补业务权限、文档、菜单、配置和服务。公共检查无法验证的项目标为待验收，不把“应用已绑定”当成“功能已可用”。
