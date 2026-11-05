# 搭建与规则

先用 feishu-agent-setup 检查所选 profile 的公共能力；已有 todo/draw 可用时复用，不重复初始化应用。需要 lark-cli、Python 3.11+、sqlite3、zoneinfo、fcntl；除部分环境缺 IANA 时区库需 tzdata 外只用标准库。当前附带部署方式面向 Linux，运行不需要 Codex/大模型服务或业务文档权限。

## 权限和消息

- bot：接收本人私聊事件 im.message.receive_v1，主动发送及回复本人；精确 scope 按当前 help/schema 和 lark-shared 核对。
- user：新配置时用于验证真实本人 open_id；运行中只校验绑定，不读写用户业务文档。
- 菜单：application:app_slash_command:read / :write。

事件监听按 lark-event：ready 后读取 stdout；使用 --timeout 24h 避免 systemd 下 stdin EOF 导致立即退出；多个消费者共用总线。取消依赖紧邻被回复消息的 reply_to（兼容 parent_id），不拿 root_id 推断。先查看当前 event schema，内容已是解码文本，不再 fromjson。

## 新实例

在本机执行，替换所有占位符为实际路径和核实的 profile：

```text
python <SKILL_DIR>/scripts/setup.py configure --profile <PROFILE> --instance personal --cli <CLI_PATH> --runtime-dir <NEW_RUNTIME_DIR>
python <SKILL_DIR>/scripts/setup.py service --config <NEW_RUNTIME_DIR>/config.json --name feishu-remind-personal
```

configure 要求新的空目录，拒绝覆盖已有配置；默认运行目录为 XDG_DATA_HOME（未设置用 ~/.local/share）下 feishu-remind/<instance>。不把运行数据放在 Skills 内。配置含 schema_version、instance、cli_path、profile、app_id、owner_open_id、timezone、state_dir，无 Secret/token。

service 只生成文件，接[运维](operations.md)安装启动。旧实例不要重新 configure：先查实际 config/服务绑定，按升级流程保留数据和服务名。`--check` 会建库；若要恢复旧数据先导入再检查。

## 原生菜单

先核对 CLI application 子命令 help，指定同 profile list。不存在才 create；已存在需要修改时 update 原 command_id，先读出并保留其他语言描述。配置示例：

```text
lark-cli --profile <PROFILE> application +slash-command-list --as bot
lark-cli --profile <PROFILE> application +slash-command-create --as bot --command remind --description "设置定时提醒，例如 /remind 明天下午3点 约会议室" --description-i18n zh_cn="设置定时提醒，例如 /remind 明天下午3点 约会议室"
```

不改 todo/draw，当前 CLI 没有排序参数，不保证客户端排序或通过重建菜单改变顺序。服务端注册后客户端可能缓存约5分钟，需在飞书输入 / 检查，手打命令可用。

## 规则范围

时间在前、事项在后，中间有空格；全角数字与冒号可识别，事项正文保留。规则详情以 time_rules.py 为准。

| 类型 | 示例与边界 |
| --- | --- |
| 相对时长 | 30分钟后、半小时后、两小时后、1天2小时3分钟后；也支持秒，时长大于0且不超过3650天 |
| 日期 | 今天、明天、后天、大后天、周五、本周五、下周一、2026-12-01、12月1日；未写日期用今天，月日未写年份用消息当年，过去/不存在日期拒绝 |
| 时刻 | 15:00、15点、下午3点、晚上八点半、九点一刻、三十分；1～12点未写早晚拒绝，08:00明确为24小时制；“晚上12点”要求明确日期00:00 |
| 重复 | 每天、每周五、每月1日、工作日/周一到周五；工作日固定周一至五，不识别法定节假日或调休；每月29/30/31遇无该日期时跳过 |
| 未支持 | 每隔两天、多周几组合、一天多个时刻、截止日期等；不要声称能解析，分条设置或按用户需要扩展 |

单独 /remind 查看；/remind 取消 R012 用实际编号。普通“取消”只处理直接回复的已知提醒，不匹配事项名称、不猜最接近的一条、不维护下一条消息补全模式。重复取消停止全部后续；无按钮。
