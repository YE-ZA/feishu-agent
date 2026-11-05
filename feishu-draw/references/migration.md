# 迁移

先按 [公共迁移检查](../../feishu-agent-setup/references/migration.md) 处理程序、应用绑定、身份授权和旧机切换，再按本文迁移绘图资料与状态。Linux 已实测；macOS 需验证，Windows 当前实现不能直接运行。

## 同账号、App、档案换电脑

1. 公共检查后补齐绘图依赖，重新登录 Codex，不复制其凭据库。记录档案 document_id/URL、时区和服务路径，与已核实的 App/owner 一起核对三项绑定。
2. setup.configure 生成新运行副本，重新定位解释器/Node/sharp/Codex。先不启新监听；旧机队列完成后停 draw，保留独立 todo。两台独立 SQLite 不能全局去重。
3. 备份整个 state/jobs 与 draw.sqlite3。停服务后用 Python sqlite3.Connection.backup 备份数据库，避免漏 WAL。receipts 支持回复旧消息，源 SVG/节点备份用于安全修改，不能只搬文档或只搬数据库。
4. 核对 SQLite meta.binding 的 [app_id, owner_open_id, archive_document_id] 与新 config 一致。任一不同则改用新实例空状态，不能删 binding 绕过。目标已有非空队列时不能覆盖。
5. 路径变化时，只重定位 jobs.payload 的 references/local_references 列表中确实位于旧 state/jobs 下的路径，映射新目录相同相对路径并检查文件存在；不全文替换提示词或数据库。event、文档/白板 token、message_id 原样保留。其余导出返回路径按实际使用点核查，不能声称复制配置就完成数据迁移。
6. 有未完成任务先按 operations 核查写入/发送阶段，不统一重置 queued。检查新机身份、渲染、历史回复定位和服务 ready，只启一台监听。

## 换账号、租户、App 或档案

公共接入检查后使用新 runtime/state，按 setup 补绘图权限并注册或核对 `/draw` 菜单。不导入旧 jobs/receipts。

沿用历史文档先确认新用户有实际权限；跨账号共享/复制需授权，走 lark-drive/lark-wiki 保真流程，不能凭旧 token 绕过访问。新空状态不能回复定位旧机器人消息，但可在有权限时用 `/draw 修改 <具体白板链接> …`，原文档提示词仍可读取追加。

## 分发与既有部署

分发时同时带上 feishu-agent-setup 和所需 lark-* Skills，保持公共与功能 Skill 平级。各 Skill 白名单打包 SKILL.md、agents、scripts、references（仅包含实际存在的目录）；排除 config/deployment、state、图片、SVG、日志、凭据、__pycache__ 和 node_modules。.gitignore 仅是补充。

创建 Skill 不会改变现有服务路径。维护实例从服务文件反查运行目录；修改 Skill 后明确部署运行副本才能声称线上已更新。
