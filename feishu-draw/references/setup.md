# 搭建

## 公共前置检查

先按 [feishu-agent-setup](../../feishu-agent-setup/SKILL.md) 检查指定 profile 的 CLI/Python、真实 user/bot、机器人可用范围、私聊事件与发布状态；缺失时补齐，已有可用环境直接继续。不重复创建应用或重新授权。

## 绘图专属依赖与权限

安装或定位 lark-doc、lark-whiteboard 的完整 Skill 目录；公共依赖由 feishu-agent-setup 检查。需要 fcntl、Codex CLI 登录、Node.js、sharp、中文字体（按 Noto Sans CJK SC 排版）。桌面环境可用 load_workspace_dependencies 定位捆绑 Node/sharp；其他环境在本机依赖目录安装，不把 node_modules 放进 Skill。

源码在 lark-cli 1.0.98、Codex CLI 0.159.2 验证过；新环境核对 help。Codex 调用使用 JSON schema、图片、临时执行、只读沙箱，禁 shell/plugins/web；不能为兼容旧 CLI 静默去掉隔离选项。模型取目标机实际可用值。

在公共身份检查之上补绘图能力：

| 操作 | 检查 |
| --- | --- |
| 文档、白板读写，Wiki 实体解析 | user，实际文档/白板权限与所需 docs/drive 域 |
| 接收私聊、读取原消息、下载图片 | bot，相应消息和资源能力 |
| 回复、上传预览图 | bot，发送/回复及图片上传能力 |
| 原生斜杠 | bot，应用斜杠命令读取/写入能力 |

精确 scope 看当前 CLI schema、missing_scopes 和后台；缺失时按公共 Skill 的授权路由补齐，不预先申请 todo 等其他功能的权限。

## 文档与配置

已有档案用 lark-doc 读取 URL 得真实 document_id，不把 Wiki token 当 docx ID。无档案时按其创建工作流在个人空间建“个人绘图文档”，简述用法即可，不预塞测试图或空日期标题。保留用户已有标题和介绍。

参数换成本机实值，运行目录在 Skill 仓库外：

```text
python3 <SKILL_DIR>/scripts/setup.py configure --profile <PROFILE> --doc <REAL_DOC_URL> --runtime-dir <NEW_RUNTIME_DIR> --cli <LARK_CLI> --codex <CODEX_CLI> --node <NODE_BINARY> --sharp-module <ABSOLUTE_SHARP_MODULE_DIR> --timezone Asia/Shanghai
```

脚本验证本人/App/文档、Codex 登录并试渲染小型 SVG，仅写本地配置及运行源码。默认不指定模型；保留已有部署选择或用户指定时加 --model 和 --reasoning-effort。不在通用 Skill 中硬编码个人路径、账号或模型。

配置包含 cli_path、profile、app_id、owner_open_id、archive_document_id、archive_document_url、state_dir、timezone、codex_path、node_path、sharp_module、reasoning_effort、generation_timeout、max_images，可选 model。账号和文档由验证结果解析；配置不含 Secret/token，仍属于个人部署资料。

```text
python3 <RUNTIME_DIR>/draw_bot.py --config <RUNTIME_DIR>/config.json --check
```

此检查不代表上传、白板写入已验收。setup 拒绝覆盖已有 config；更新既有实例见 operations.md。

## 菜单与输入

同 profile 先 list；已有 draw 则 update 保留 command_id，缺少再 create，先核对当前 help，不动 todo 等其他命令。

```text
lark-cli --profile <PROFILE> application +slash-command-list --as bot
lark-cli --profile <PROFILE> application +slash-command-create --as bot --command draw --description "根据本条文字与图片绘制白板，例如 /draw 画报销流程图" --description-i18n zh_cn="根据本条文字与图片绘制白板，例如 /draw 画报销流程图"
```

描述不加“归档并返回预览”。服务端成功后客户端可能需等缓存刷新，仍可直接手打 /draw；不每次启动重复注册。

从零绘图可提供对象、关系、布局和关键文本，例如：

```text
/draw 画一张报销流程图，标题“员工报销流程”。员工提交→主管审批；不通过退回修改，通过后财务审核，审核通过后付款。横向布局，审批用菱形、步骤用圆角矩形，蓝青配色，退回箭头用虚线，标注“通过/退回”。
```

有参考图时，同一条图文消息写 `/draw 参考附件的配色和阶段分栏，按以下业务内容重画：……` 并附图。正文决定内容，图片提供风格，不将整张参考图贴成白板。

继续修改可回复任一机器人输出：`把财务审核放到主管审批下面，退回箭头改成橙色，其余保持不变。`

接 [运维与排障](operations.md)。
