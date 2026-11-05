# Feishu Agent Skills

用于飞书个人自动化的可复用 Skills 集合。每个子目录是一项独立 Skill，包含操作说明、必要脚本和参考文档；后续功能继续以独立子目录加入。

| Skill | 用途 |
| --- | --- |
| [feishu-todo-reminders](feishu-todo-reminders/SKILL.md) | 通过机器人 `/todo` 维护文档勾选清单，手动查看未完成事项，并在工作日上午定时提醒；包含从零搭建、换账号与换电脑迁移流程。 |

## 使用

将需要的 Skill 子目录放入目标环境的 Codex Skills 目录，保留其 `SKILL.md`、`scripts/`、`references/` 和 `agents/`，再让 Codex 按该 Skill 的说明配置。

例如：`使用 $feishu-todo-reminders 帮我从零搭建飞书待办提醒。`

Skill 提供操作方法与运行脚本，并非包含全部依赖的一键安装包。Python、`lark-cli`、依赖的 `lark-*` Skills、本人飞书授权、后台服务及定时任务按各 Skill 的说明安装和验证。

## 配置与迁移

仓库不保存个人账号绑定、App Secret、访问令牌、登录凭据、运行状态或待办数据。本机配置和状态由部署流程在仓库外生成；换账号或换电脑时重新校验身份和路径，不复用其他人的收件人或授权。

当前后台服务在 Linux 验证过；macOS、Windows 提供配置生成与迁移说明，需在目标机器实测。

## 验证待办 Skill

在 `feishu-todo-reminders/scripts` 目录运行：

```bash
python3 -m unittest -v test_runtime.py test_setup.py
```

这些隔离测试不会访问飞书或发送消息。正式部署还需验证真实消息、文档读写及定时执行权限。
