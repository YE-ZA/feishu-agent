# 后台与定时

## 后台接收

无模式参数的bot.py监听消息。它使用24小时有界event consume，避免systemd空stdin触发CLI立即退出；到期内部重连。先用 `setup.py service --config <CONFIG> --kind systemd|launchd|windows`生成定义，返回路径/服务名及enabled=false，然后在已授权部署范围安装。

| 系统 | 安装和验证 |
| --- | --- |
| Linux | 生成.service复制到~/.config/systemd/user，daemon-reload，再enable --now返回服务名；用status/journalctl查ready。默认用户会话，若要求注销后运行再核实lingering及凭据可用性，不默认改系统策略 |
| macOS | 生成plist复制到~/Library/LaunchAgents；launchctl bootstrap gui/当前UID 完整plist路径，需要时kickstart；print对应label及stderr.log检查。不要为无人值守私自降级Keychain存储 |
| Windows | 生成XML以当前用户任务计划导入：schtasks /Create /TN 名称 /XML 路径，再/Run；先查同名任务，更新时才覆盖。模板用当前登录用户InteractiveToken及LeastPrivilege，不承诺注销后运行；核实任务状态及真实消息 |

运行文件含本机Python/CLI/config绝对路径，跨机重新生成。macOS/Windows只完成结构验证，目标机安装、凭据刷新和消息收发须实机验收。正常停止用服务管理器或SIGTERM；不要kill -9或停止别的CLI共享总线。总线最后consumer退出后可自行结束，systemd出现共享进程残留提示不等于任务已重复。

更新先停对应服务，从Skill复制scripts/bot.py到运行目录，保留config/state，check后重启。只改Skill不会自动部署副本。

## Codex定时（默认）

收件服务不依赖聊天窗口；定时发送由Codex自动化负责，需本机开机联网且Codex调度可运行，二者分别验收。

1. 读取openai-docs并确认当前automation_update；检查是否已有同用途任务，优先更新避免重复。
2. `setup.py automation-prompt --config <CONFIG>`生成用户可读正文，通过工具创建/更新heartbeat，绑定用户指定的当前对话。默认配置时区周一至五10:00，不复制旧automation/thread ID，不手写UI指令、不改内部数据库/TOML。
3. 正文运行部署的 `bot.py --config <CONFIG> --send-reminder`。模型不重写正文，脚本原生post发送。记录工具返回的自动化ID/当前对话/时区/启用状态到本机部署记录，不嵌入通用Skill。
4. 调度和手动共用render_reminder。脚本核对账号、周末跳过、同日success跳过。发送前写pending，API成功且有message_id才标success；pending拒绝自动重发，防止超时后重复。空清单也发“暂无未完成待办。”。手动/todo不占每日回执。

--send-reminder有副作用，不在只读自检中执行。旧实现当天已有成功回执时，不在迁移测试中再发送；核实message_id后迁入deliveries数据库或等下一个工作日。不根据聊天文字伪造success。

CLI需读配置、刷新并写凭据、写本实例state、联网。前台成功不等于Codex无人值守沙箱也允许；在用户授权范围按当前设置处理。禁止chmod777、sudo、复制令牌到工作区或改内部数据库绕过审批。分开报告只读检查、实际发送message_id、任务启用和到点成功，未到点就保留未验证事实。

无Codex定时工具时可先交付收件/手动功能，说明定时未安装。只有用户明确选择系统调度替代时，才用平台定时器调用同一--send-reminder，不与Codex同时启用，也不冒充对话定时任务。
