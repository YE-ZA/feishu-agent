---
name: feishu-agent-setup
description: 搭建和检查个人飞书机器人的公共接入环境，包括 CLI、应用与 profile、user/bot 身份、私聊事件和发布；供 feishu-draw、feishu-todo、feishu-remind 等功能复用。功能配置由对应 Skill 处理，通用 CLI 认证问题走 lark-shared。
metadata:
  requires:
    bins: [lark-cli, python3]
    skills: [lark-shared, lark-im, lark-event]
---

# 飞书机器人公共搭建

把指定应用配置到可供个人机器人功能接入的状态。优先检查并复用已有环境，只补缺失项；已有机器人可用时直接返回功能 Skill，不重复创建应用、授权或重配事件。

## 接入方式

调用方提供目标功能和已有 profile（如已知）。先确认实际 CLI 路径、profile、App 与本人身份，再检查机器人可用范围、私聊能力、事件订阅和发布状态。操作步骤见[公共搭建](references/setup.md)。多个可用应用且无法确定目标时询问用户，不静默切换全局默认 profile。

公共能力就绪后，把核实的绑定信息和未验证项交给功能 Skill：

- [feishu-draw](../feishu-draw/SKILL.md)：Codex、渲染、白板与归档文档、`/draw` 菜单和绘图服务。
- [feishu-todo](../feishu-todo/SKILL.md)：待办文档、`/todo` 菜单、收件服务和定时提醒。
- [feishu-remind](../feishu-remind/SKILL.md)：`/remind` 规则定时提醒、固定编号、查看与取消、独立调度服务。

不预先申请所有功能的权限，不创建业务文档、注册具体命令或启动功能服务。公共 Skill 不要求同时安装所有功能；只读取当前要接入的功能说明。

## 与底层 Skills 的分工

- `lark-shared`：CLI 初始化、认证、身份、scope 与输出契约的具体操作。遇到相应事项读取其指定参考，不在这里另维护一套登录流程。
- `lark-im`：私聊消息的读取、发送与回复。
- `lark-event`：消息事件长连接、ready、EOF 和重连约定。

依赖声明用于说明需要哪些资源，不代替实际安装与发现检查。缺少依赖时先定位或安装完整 Skill 目录，不能跳过其操作约定。

## 共享约定与交付

user 用于本人业务文档，bot 用于消息和事件；bot scope 缺失不能用用户 OAuth 替代。Secret、令牌和凭据库不进入 Skill、脚本或业务配置。个人绑定、状态和日志保存在各功能的运行目录中。

多个功能可共用 App/profile；保留已有命令、订阅和其他功能的服务。每个功能维护独立配置、状态库与运行副本，本 Skill 不引入共享运行模块或统一后台服务。

交付非秘密信息：CLI/Python 路径与版本、profile、App ID、已核实的 owner open_id、机器人/事件检查结果、缺失能力和未验收项。无需为交付保存额外配置文件。只读检查通过不代表消息收发或功能写入已验收；真实测试由功能 Skill 按用户授权范围完成。

换电脑、账号或 App 时先读[公共迁移检查](references/migration.md)，业务数据和状态迁移继续按功能 Skill 处理。
