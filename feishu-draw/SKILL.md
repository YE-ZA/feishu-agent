---
name: feishu-draw
description: 搭建、维护和迁移飞书机器人 /draw 绘图功能：文字与同条消息参考图生成可编辑白板，回复机器人消息继续修改，并按日期归档白板与折叠的提示词记录。普通画板编辑走 lark-whiteboard。
metadata:
  requires:
    bins: [lark-cli, python3]
    skills: [feishu-agent-setup, lark-shared, lark-doc, lark-whiteboard, lark-im, lark-event]
---

# 飞书白板绘图

将自然语言描述与参考图变成飞书文档里的白板，机器人返回预览与直达链接。附带脚本复用本机 Codex CLI 登录，不要求另配大模型 API Key；需要可用额度。复制 Skill 后仍需安装依赖、授权及配置后台服务。

## 交互与归档约定

- 私聊 `/draw 描述` 新建图。参考图放在**同一条图文消息**，不借用之前单发的图片。单独 `/draw` 显示用法和档案链接。
- 回复该次绘图的收件确认、预览图、结果链接三条机器人消息中的任意一条，直接写修改要求，也可加 `/draw`。显式入口为 `/draw 修改 <白板直达链接> 修改要求`。文档含多张白板时，不根据无锚点链接猜目标。
- 修改直接更新原白板，保留 token 与直达链接；同一提示词代码块空一行追加 `修改：……`。新参考图一并记录。更新前导出当前节点与预览，写入前比对指纹，避免覆盖生成期间的并发编辑。
- 当前个人归档格式：日期 H1 → 每张图标题 H2 → 白板 → 默认收起的 H3“提示词与参考图” → 提示词代码块及参考图。图无标题时概括短标题；同一天复用日期，新图接在当天末尾。
- 折叠区直接放提示词内容，不再加“提示词”标签；图片 caption 为“参考图”。不显示具体时间、唯一编号、“生成白板”、图后说明或 SVG 附件。修改历史留在同一折叠区。
- 同一天后续 H2 以 `<br/>` 开头形成可见间隔；不能在前一个折叠 H3 内放空段落充当间隔，否则收起后消失。改图标题时保留前导软换行。以上是本人的显示约定，用户调整时同步代码和文档。

## 按需读取

- 公共前置：使用 [feishu-agent-setup](../feishu-agent-setup/SKILL.md) 检查指定 profile 的机器人、本人身份和消息事件；缺失时补齐，已有可用环境直接继续，不重复创建或授权。
- 绘图依赖、专属权限、配置、文档与斜杠菜单：读[搭建](references/setup.md)。
- 启动服务、升级运行副本、失败恢复：读[运维与排障](references/operations.md)。
- 换电脑、换账号/App、历史素材与状态：读[迁移](references/migration.md)。

实际工具是 lark-cli。公共接入由 feishu-agent-setup 组织，认证细节仍用 lark-shared；文档操作用 lark-doc；更新白板用 lark-whiteboard 并复用原 token；消息用 lark-im；收件用 lark-event。分发时同时安装公共 Skill 和所需 lark-* Skills；依赖声明不代替安装。配置 Codex 调用方式或更换模型时按需读 openai-docs 并核对本机 CLI，不能把旧版本参数当长期保证。

## 执行资源与边界

- `scripts/setup.py configure`：验证指定 profile 的真实 user/bot、文档、Codex 登录与本地渲染依赖，在**新运行目录**生成配置并复制源码。不改远端文档、不发消息、不启服务。
- `scripts/setup.py service`：生成 systemd/launchd 文件，不安装、不启动。runtime 使用 fcntl，Linux 已实测，macOS 需目标机验收，Windows 需先适配锁与后台方式。
- 部署后 `draw_bot.py --config <CONFIG> --check`：只读检查身份、文档与 Codex 登录，会初始化本地状态，不生成图、不发消息。
- `--self-test`：会生成真实白板并向配置本人发送消息；只在用户授权的测试范围内使用，不能与正式监听并行。
- `scripts/test_draw_bot.py`、`scripts/test_setup.py`：隔离测试，不访问飞书。

收件绑定配置本人、指定 App 的私聊。普通聊天和其他斜杠命令不进入绘图；可以与 todo 共用 App，不能覆盖其菜单、服务或状态。模型只产出结构化 SVG，禁用工具和网络；确定性代码校验、渲染、归档与发消息。

配置、个人绑定、凭据、SQLite、日志和绘图数据不进入 Skill 包。状态绑定 App、owner、档案文档；身份变化使用新实例，不能删去重库“修复”。模糊写入/发送先核查，不盲目重发或清回执。运行副本与 Skill 源码分开，修改 Skill 后需部署并重启才能声称生效。

## 验收

按范围验证：隔离测试 → 身份与依赖 → 服务 ready → 真实文字/同消息参考图 → 非空白板与机器人预览、链接 → 三种回复目标 → 原 token 更新且修改提示词只追加一次 → 折叠及可见间隔。只报告实测层级；复制 Skill 不等于重做了端到端测试。

SVG 导入不保证所有元素与连接绑定无损。原始 SVG 不反映后续手工编辑；页面默认导出 PNG/PDF。CLI 提供 SVG 导出入口，但已出现服务端失败，不能保证必定成功，见运维参考。
