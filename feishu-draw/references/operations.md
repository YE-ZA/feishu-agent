# 运维与排障

## 后台与更新

运行代码是部署副本，Skill 是源。不要有两套相同 owner/App/档案的 draw 监听；todo 可以独立共存。

```text
python3 <SKILL_DIR>/scripts/setup.py service --config <RUNTIME_DIR>/config.json --kind systemd
```

Linux 将返回的文件装入用户 systemd 目录，daemon-reload 后启用/启动实际返回的服务名。--kind launchd 生成 macOS plist，需目标机验证。生成文件不代表安装完成；不要替换 todo 服务。后台必须能访问本人的 CLI/Codex 凭据、刷新授权、联网和写 state。需要登出后运行时再按用户要求处理 linger，不为打包 Skill 修改系统策略。

更新：从现有服务 WorkingDirectory 识别真实 runtime/config/state → 在 Skill scripts 下运行 `python3 -m unittest -v test_draw_bot.py test_setup.py` → 队列空闲后停 draw → 备份代码和状态 → 仅部署 draw_bot.py、render.js、output-schema.json、review-schema.json → --check → 重启原服务并确认 ready。配置结构变化时显式迁移，不覆盖账号绑定。必要时验收实际变更，无须每次都新画测试图。

--self-test 会生成真实图例、归档并发消息，须在用户授权的测试范围内使用。等待队列完成后停正式 draw，测试后恢复；不能删 worker.lock 绕过进程锁。

## 故障定位

| 症状 | 处理 |
| --- | --- |
| 不收件 | 检查 profile/App、owner open_id、私聊 text/post、事件订阅/发布、长连接 ready。普通聊天不触发是预期。 |
| 图片未作参考 | 图与文字必须在同一消息；按原 message_id 读内容和 image_key。默认最多 6 张，每张 20MB，文字 12000 字。 |
| 模型失败 | 查同用户 Codex 登录、额度、CLI 参数、模型与超时，不输出凭据。不把空 SVG 当成功。 |
| 渲染/布局失败 | 查 Node/sharp 路径、中文字体、任务目录 local-preview.png/review.json。内容太密可拆图；脚本失败后最多修正一版。 |
| 提示词有但白板没有/内容错 | 对照 job 阶段、archive.xml、写入返回值和实际 token；warnings/partial_success 不是成功。不拿参考图或另一张图冒充结果。 |
| appending 待确认 | 通过写前白板快照、返回 token 和实际文字认领；有多个新增图或文本不符则停止，不删除任务/回执强制重试。 |
| 回复修改找不到图 | 三条输出由 receipts.message_id 关联；漏迁移状态会丢关联。可改用具体白板链接，多图文档无锚点不能猜。 |
| 并发修改拒绝覆盖 | 节点指纹变化，重新基于最新白板请求；保留 edit-before-nodes.json 和预览。 |
| 更新或发送结果模糊 | 先核查实际白板/消息和 pending 回执，不盲目覆盖、重发或清回执。 |
| 折叠/间隔不对 | docx block PATCH update_text_style={style:{folded:true},fields:[3]}，GET 回读。标题范围决定折叠；下一 H2 前导换行负责可见间隔。 |

state/draw.sqlite3 保存 meta 绑定、jobs 阶段及 receipts；state/jobs/<job>/ 保存参考图、SVG、预览和节点备份。它们是个人数据和去重依据，排障只输出必要字段。

修改保留原 token，但 SVG 更新重建内部元素，可能改变节点 ID 和连接绑定。手工修改过时以当前白板预览为准，只有节点指纹匹配才复用旧 SVG。要求保留手工节点结构时另用 lark-whiteboard 原生编辑流程，不能承诺 SVG 重建无损。

## SVG 导出

页面通常提供 PNG/PDF；CLI 有以下入口，先核对 lark-whiteboard 当前导出参考与 help：

```text
lark-cli --profile <PROFILE> whiteboard +export --whiteboard-token <TOKEN> --output-type svg --output ./diagram.svg --as user
```

2026-11-05 在既有部署实测返回服务端错误 2891001，未获得文件；这是已知观察，不是所有白板永久不支持的结论。失败时保留 preview/raw 节点并说明失败。任务目录 diagram.svg 是生成源，不能当作包含后续手工编辑的最新导出。
