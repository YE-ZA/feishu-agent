# 运维与排障

## 安装、升级和运行

service 命令只在运行目录的 service/ 生成 unit，安装前查看内容，核对本机 Python、CLI、config、工作目录和服务名。新实例示例：

```text
systemd-analyze --user verify <GENERATED_UNIT>
cp <GENERATED_UNIT> ~/.config/systemd/user/<SERVICE_NAME>.service
systemctl --user daemon-reload
systemctl --user enable --now <SERVICE_NAME>.service
journalctl --user -u <SERVICE_NAME>.service -n 30 --no-pager
```

这些命令由 agent 用真实本机路径执行。已有实例保留原服务名，不另启第二个服务，不因 Skill 改名搬运行目录。KillMode=control-group、TimeoutStopSec=65，正常使用 SIGTERM。不要停止 CLI 共享总线影响 todo/draw。

查看服务 active 之外还要看到本次启动的 remind listener ready；调度器每秒扫描，网络调用存在耗时，不承诺秒级准点。用户服务随登录启动；检查 loginctl 的 Linger，不能仅因 enable 就宣称无人登录或关机时也能提醒。

升级：隔离测试 → 停对应提醒服务 → backup-state → 将 Skill scripts/remind_bot.py、time_rules.py 复制到原运行目录 → --check → 启原服务 → 本次启动 ready → 按授权范围验证。保留 config、state、编号与回执，不重跑 configure 覆盖数据。只有 Skill 文件变化而未部署不代表线上已更新。

## 验证命令

```text
cd <SKILL_DIR>/scripts
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_remind_bot.py test_setup.py
python <RUNTIME_DIR>/remind_bot.py --parse '明天下午3点 约会议室'
python <RUNTIME_DIR>/remind_bot.py --config <CONFIG> --check
```

测试不联网；--parse 不排程；--check 会初始化/升级本地状态，不发消息。--self-test 会排入30秒真实提醒，需已运行的服务发送到配置本人；区分本地排入、API成功回执、远端回读和到点实际成功。它不模拟真实用户消息，不能代替收件验收。用户数据迁移先 import-state，后 --check。

私聊验收：创建确认带编号 → 单独 /remind 可见 → 按编号取消并回显 → 列表排除 → 原定时间不再发送。另测回复设置确认/到点消息“取消”、旧无编号确认、重复计划取消后续、重复事件去重及重启后状态不变；不用用户真实事项作破坏性测试。

## 定位问题

- 无响应：确认 profile/App/owner 一致、私聊、文字/以命令开头的富文本，检查事件 schema 和 ready。普通“取消”须直接回复已知提醒，列表消息不是单个提醒的取消目标。
- 解析失败：先 --parse，按支持语法重发完整命令；不要把下一条普通聊天当作补充。
- 编号变化/丢失：检查是否误用了新状态库。reminder_numbers 保留历史编号及 sqlite_sequence；不可只复制 active 事项重新编号。
- 取消后仍看到消息：检查远端回执和发送时间，可能请求已在途或取消前已发出。取消未发送 outbox，并检查取消事务及重读状态；不能承诺撤回已发消息。
- 发送失败：核对账号、权限、联网与 outbox。首次尝试后50分钟内相同幂等键退避重试，超过后 uncertain；到点消息不确定时暂停该计划。先查询已知 message_id 或本人私聊记录核实结果，再决定是否恢复。没有通用自动恢复脚本，不直接清 first_attempt、删行或重发。
- 离线错过：恢复后单次补发；重复只补发一条，发送成功后跳到当前时间之后。长期退出登录也可能停止用户服务。
- 身份变化：运行会拒绝不同 App/owner/时区状态；新账号用新实例，按迁移参考处理，不修改 binding 绕过。

日志只记录阶段/异常类型，个人正文保存在状态库；对外报告引用必要状态，不输出凭据或完整私聊数据。
