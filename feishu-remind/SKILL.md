---
name: feishu-remind
description: 搭建、维护和迁移飞书机器人 /remind 定时提醒：规则解析时间、单次与重复计划、固定编号、查看有效提醒、按编号或回复消息取消。原生任务和日历日程管理分别走 lark-task、lark-calendar。
metadata:
  requires:
    bins: [lark-cli, python3]
    skills: [feishu-agent-setup, lark-shared, lark-im, lark-event]
---

# 飞书定时提醒

个人机器人用规则解析消息，在本地 SQLite 保存提醒并到点发送私聊。不使用大模型、API Key、业务文档或飞书原生任务；运行机器须保持可用。

## 交互约定

- `/remind 时间 事项` 添加；时间与事项之间留空格。单独 `/remind` 查看有效提醒，不创建事项。
- 设置确认与到点消息带完整时间、重复规则（确认中）、固定编号及取消用法。编号如 R012，完成或取消后不复用；历史记录升级后保留计划和回执并补编号。
- `/remind 取消 R012` 取消指定事项；也可直接回复设置确认、到点消息或原始创建消息，发送“取消”。普通“取消”不生效；不从 root_id 猜目标。重复事项取消后续全部提醒，并回显结果；已完成/已取消则说明状态。
- 取消会停止未发送的排队消息和重试；已发出或已在网络途中的消息可能仍会到达。
- 查看按下次到期时间排序，排除完成/取消项，暂停待核查的计划注明状态；长清单自动分条。无取消按钮、额外顶层命令或持续会话模式。
- 默认北京时间，当前运行代码仅支持 Asia/Shanghai。相对时间以消息 create_time 为准，歧义或过去时间回复原因，要求带完整命令重发；不把下一条普通聊天作为补充。
- 菜单示例保持“设置定时提醒，例如 /remind 明天下午3点 约会议室”。修改菜单保留 command_id 和已有语言描述。

## 按需读取

- 公共前置：复用 [feishu-agent-setup](../feishu-agent-setup/SKILL.md) 核对 CLI、profile、App、本人身份、机器人私聊及事件；已有环境直接继续，不重建应用或重复授权。
- 从零配置、规则范围、菜单和依赖：读[搭建](references/setup.md)。
- 启动、升级、发送异常与取消排障：读[运维](references/operations.md)。
- 换电脑、账号/App、备份与恢复：读[迁移](references/migration.md)。

实际工具是 lark-cli；认证用 lark-shared、消息用 lark-im、事件用 lark-event。分发时安装完整依赖 Skills；声明依赖不等于安装或宿主已发现。

## 执行资源

- `scripts/setup.py configure`：验证指定 profile 的真实 user/bot，在新的运行目录复制代码并生成本机配置。不发消息、不改远端、不启动服务。
- `setup.py service`：生成 systemd 文件，不安装、不启动；已有实例使用原服务名。
- `setup.py backup-state` / `import-state`：用 SQLite backup 备份/导入同 App、owner、时区的状态，保留编号、原始消息和发送回执。导入拒绝覆盖已有库并检查运行锁。
- 运行副本 `remind_bot.py --check`：验证身份、初始化/升级本地状态，不发消息。恢复旧数据时先 import-state，再 --check，避免先建空库。
- `--parse '明天下午3点 约会议室'`：离线预览规则，不排程、不发消息。
- `--self-test`：给配置本人排入30秒自检，由已运行服务发送确认及到点消息，是实际发送，依用户授权范围执行。
- `scripts/test_remind_bot.py`、`scripts/test_setup.py`：隔离测试，不访问飞书。

Python 3.11+；runtime 使用 fcntl，仅 Linux 已实测，macOS 需目标机验证，Windows 需适配锁与后台方式。当前附带服务生成器只生成 systemd。

## 状态与验收

只处理绑定本人、指定 App 的私聊；与 todo/draw 分别维护运行副本、配置和状态，共用本地事件总线，不停止共享总线或覆盖其他功能。凭据由 CLI 管理，个人 config、SQLite、日志、回执和备份不进入 Skill 包。

每条用户消息按 message_id 去重；固定编号单调分配。取消及回复排队在事务中完成；发送前重读状态，成功回执不重新激活已取消计划。服务用文件锁防止同库重复运行。

离线错过的一次性提醒恢复后补发；重复积压只补发一条，成功后计算下一次。模糊发送以相同幂等键在首次尝试后50分钟内重试；超过窗口标记 uncertain，停止自动重发，到点消息不确定时暂停对应计划。先核查回执，不删库或盲目重发。

按范围验收：隔离测试 → 身份与配置 → 菜单服务端注册 → listener ready → 实际私聊创建/查看/两种取消 → 到点与重启恢复。自检发送不能冒充用户收件端到端验收；菜单客户端显示需实际检查。修改 Skill 源码后需另行部署并重启，才能声称线上行为更新。
