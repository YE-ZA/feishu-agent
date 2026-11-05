# 迁移

| 内容 | 处理方式 |
| --- | --- |
| Skill整个目录、依赖Skills | 可复制，保留scripts/references/agents；也可从官方重装依赖 |
| 待办数据 | 在飞书文档；同账号同文档无需导出重建 |
| config、解释器、CLI路径、服务文件 | 新电脑重新生成并验证；config不是登录态 |
| state.sqlite3和deliveries.sqlite3 | 仅同App ID、owner open_id、document_id迁移；先停服务/调度，用SQLite backup避免漏WAL |
| Secret、OAuth令牌、device-code、凭据库 | 不进入Skill/迁移包，不整目录复制；目标电脑重新安全绑定和授权 |
| Codex自动化 | 用工具在新环境核实/重建，不能靠复制Skill恢复 |

## 同账号、同应用换电脑

1. 旧机记录非秘密绑定：profile/App/owner/document/URL/时区、服务名和自动化ID。不输出Secret或原始认证文件。
2. 新机按setup.md装依赖，用同应用安全绑定并重新授权同用户；缺App凭据时走官方取得/重置流程，不从旧库抠token。
3. 新机configure，确认三项绑定相同。profile改名或路径变化不代表换用户，但仍要核对App。
4. 切换前停止旧机对应监听和定时；不动无关bot。两台独立SQLite无法全局去重，旧机停不了时别同时开新监听。
5. 停止后备份SQLite，消息库用：

```text
python <SKILL_DIR>/scripts/setup.py import-state --config <NEW_CONFIG> --source <OLD_STATE_DB> --source-app-id <OLD_APP_ID> --source-owner-open-id <OLD_OWNER> --source-document-id <OLD_DOCUMENT>
```

脚本拒绝身份不匹配及目标已有库。新库metadata有二次校验；旧实现缺metadata时根据原配置显式确认来源。每日deliveries库也只在同绑定实例间、停调度后用SQLite backup迁移。当天pending先核对消息，不删除重发。

6. 新机生成服务、启动、验证真实/todo和文档交互，再通过工具恢复当前对话的定时，确保仅一台负责。跨时区核实实际UI时间。

## 换账号、租户或App

使用新instance/runtime-dir和空状态。open_id按App隔离，同名或同一个人不代表可以沿用旧ID。目标profile的用户和bot都要校验，不静默切全局profile。

新App需发布机器人/权限/事件和重新注册斜杠；同App换电脑只核对已有命令。决定新建台账还是继续用旧文档：目标用户必须真实拥有权限，填旧URL不等于迁移。

跨账号复制/共享旧数据必须有合法访问及用户授权，按lark-drive复制/共享或官方导入导出流程保留日期、checkbox状态与顺序。旧账号无法授权时不绕过访问，可建空文档并说明旧数据未迁。

对新profile/文档configure，解析新的App/owner/document，**不导入旧账号、旧App、旧文档的队列与每日回执**。停止旧部署中这套监听/调度，保留旧文档和备份。测试新账号收件、文档更新和到点提醒。脚本检测CLI身份变化会拒绝继续，不自动换收件人；状态绑定不符时不要删库“修复”，先确认是否应建新实例。

## 分发与跨系统

压缩包只含SKILL.md、agents、scripts、references；排除__pycache__、config.json、SQLite、日志及凭据。本机部署记录单独保存，不嵌入通用包。

跨Linux/macOS/Windows重新定位python/lark-cli、检查时区库并生成本机服务定义。目标机Keychain/凭据刷新、后台启动和斜杠菜单必须实测；Linux验证不能代替其他系统验收。复制Skill不等于完成安装、授权、启动和恢复自动化。
