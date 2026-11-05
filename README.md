# Feishu Agent Skills

用于飞书个人自动化的可复用 Skills 集合。公共搭建与功能 Skill 平级组织：公共搭建维护机器人接入流程，各功能维护自己的业务操作、脚本、配置和状态；后续功能继续以独立子目录加入并复用公共搭建。

| Skill | 用途 |
| --- | --- |
| [feishu-agent-setup](feishu-agent-setup/SKILL.md) | 检查和补齐 CLI/Python、应用与 profile、user/bot 身份、机器人私聊事件与发布；优先复用已有环境，认证细节复用 lark-shared。 |
| [feishu-todo](feishu-todo/SKILL.md) | 通过机器人 `/todo` 维护文档勾选清单，手动查看未完成事项，并在工作日上午定时提醒；包含从零搭建、换账号与换电脑迁移流程。 |
| [feishu-draw](feishu-draw/SKILL.md) | 通过机器人 `/draw` 将描述和同消息参考图生成白板，回复任意绘图输出继续修改原图，按日期保存白板与折叠的提示词历史；包含搭建、运维和迁移。 |
| [feishu-remind](feishu-remind/SKILL.md) | 通过机器人 `/remind` 设置单次/重复提醒，查看有效提醒，按固定编号或回复相关消息取消；规则解析，不使用大模型和业务文档，包含搭建、运维、备份和迁移。 |

## 使用

将 `feishu-agent-setup` 与需要的功能子目录一起放入目标环境的 Codex Skills 目录，保留各目录中实际存在的 `SKILL.md`、`scripts/`、`references/` 和 `agents/`。公共与功能 Skill 保持平级；安装任何功能时都需安装公共搭建 Skill，不要求同时安装其他功能。

例如只安装待办时，目录为：

```text
<SKILLS_DIR>/
├── feishu-agent-setup/
└── feishu-todo/
```

此外按声明安装所需 lark-* Skills。依赖声明不会替代安装与实际发现检查。

例如：`使用 $feishu-todo 帮我从零搭建飞书待办提醒。`、`使用 $feishu-draw 帮我配置飞书画图机器人。` 或 `使用 $feishu-remind 帮我搭建定时提醒。` 功能 Skill 先检查公共前置，缺失时补齐，已有可用环境直接继续。也可单独使用 `$feishu-agent-setup` 配置公共接入环境。

Skill 提供操作方法与运行脚本，并非包含全部依赖的一键安装包。Python、`lark-cli`、应用与身份授权、消息事件按公共 Skill 检查；功能依赖、业务文档、具体斜杠菜单、后台服务及定时任务按对应功能 Skill 安装和验证。

draw、todo 和 remind 可共用 App/profile，各自保留配置、运行副本与状态库。公共 Skill 不引入共享 Python 模块或统一服务，不因接入一个功能覆盖另一个功能的菜单或服务。

## 配置与迁移

仓库不保存个人账号绑定、App Secret、访问令牌、登录凭据、运行状态或待办数据。本机配置和状态由部署流程在仓库外生成；换账号或换电脑先做公共迁移检查，再处理各功能的数据、状态与自动化。

当前后台服务在 Linux 验证过；待办支持生成 macOS/Windows 配置，绘图支持生成 macOS 配置但尚需目标机实测，绘图的 Windows 运行方式需先适配。
定时提醒当前只附带 systemd 生成器，runtime 使用 fcntl；macOS 需目标机验证后台方式，Windows 需先适配。

## 验证待办 Skill

在 `feishu-todo/scripts` 目录运行：

```bash
python3 -m unittest -v test_runtime.py test_setup.py
```

这些隔离测试不会访问飞书或发送消息。正式部署还需验证真实消息、文档读写及定时执行权限。

绘图 Skill 在 `feishu-draw/scripts` 目录运行 `python3 -m unittest -v test_draw_bot.py test_setup.py`；同样不访问飞书。

定时提醒 Skill 在 `feishu-remind/scripts` 目录运行 `python3 -m unittest -v test_remind_bot.py test_setup.py`；覆盖规则、固定编号、取消、重启恢复和配置/备份迁移，不访问飞书。
