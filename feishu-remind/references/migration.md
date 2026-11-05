# 备份、换电脑与换账号

先读 [公共迁移检查](../../feishu-agent-setup/references/migration.md) 验证 CLI/profile/App 与本人身份，业务状态由本功能管理。Skill 是代码和说明，不包含配置、凭据或个人提醒；复制 Skill 不等于服务已运行。

## 同 App、同 owner、同北京时间时区

1. 停止原提醒服务，保留 todo/draw 与共享总线；在原机用 SQLite backup 导出一致快照：

```text
python <SKILL_DIR>/scripts/setup.py backup-state --config <OLD_CONFIG> --output <NEW_BACKUP_FILE>
```

2. 新机器安装本 Skill、公共 Skill 和所需 lark-*，认证核实同一 App 与 owner。configure 到新目录，按本机路径生成 config 和服务文件。不要先运行 --check/服务，以免先建空状态库。
3. 将快照通过用户认可的方式复制到新机，导入：

```text
python <SKILL_DIR>/scripts/setup.py import-state --config <NEW_CONFIG> --source <BACKUP_FILE>
python <NEW_RUNTIME_DIR>/remind_bot.py --config <NEW_CONFIG> --check
```

导入校验源 binding=[1,app_id,owner_open_id,Asia/Shanghai]，拒绝不同身份或覆盖已有库；检查运行锁。完整数据库保留 inbox、outbox、提醒、原消息ID/远端回执、编号映射和自增计数。不能只抄提醒正文或单独复制 WAL 模式主文件。

4. 确认原机不再发同一批提醒，安装并启动新机服务，再验 ready、列表编号、回复旧消息取消、到点和重启。离线补发和 uncertain 处理按[运维](operations.md)执行。

backup-state 也可在在线库上做一致快照，但迁移最终快照前应停止旧服务，避免后续状态变化及两台机器重复发送。备份文件仅本人可读，不能放入 Skill 分发包。

## 更换账号或 App

open_id 按 App 隔离。重新验证真实身份，使用全新 instance/runtime/state，不导入旧库，不保留旧 owner、消息ID或修改 binding。若用户需要转移提醒内容，先读出必要事项给用户核对，再按新身份新建；编号、历史回复关系和回执不跨账号复用。迁移需求不自动授权向另一账号发送测试消息。

## 平台与现有实例

附带 runtime 用 fcntl，Linux 已验证；macOS 需适配后台服务并在目标机验收，Windows 先适配锁和服务。时区当前只允许 Asia/Shanghai，不能通过改配置静默转换。
现有实例升级保留其真实服务名与目录；setup.py 默认路径只用于新实例，不据默认值猜旧配置。Skill 文件、个人运行文件和数据库分别保存。
