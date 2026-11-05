#!/usr/bin/env python3
"""Create local configuration, portable runtime and service definitions; never stores secrets."""
import argparse
import getpass
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET
import bot


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    path.chmod(0o600)


def runtime_default(instance):
    if sys.platform == 'win32':
        root = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local')))
    elif sys.platform == 'darwin':
        root = Path.home() / 'Library/Application Support'
    else:
        root = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    return root / 'feishu-todo-reminders' / instance


def configure(args):
    cli = shutil.which(args.cli) or str(Path(args.cli).expanduser().resolve())
    if not Path(cli).is_file():
        raise ValueError('Install lark-cli or pass --cli with its executable path')
    cli = str(Path(cli).resolve())
    p = subprocess.run([cli, '--profile', args.profile, 'auth', 'status', '--json', '--verify'],
                       capture_output=True, text=True, timeout=60, env=bot.cli_env())
    try:
        status = json.loads(p.stdout)
        owner = status['identities']['user']
        app = status['identities']['bot']
        if p.returncode or not owner.get('verified') or not app.get('verified'):
            raise ValueError()
        owner_id, app_id = owner['openId'], status['appId']
    except (KeyError, ValueError):
        raise ValueError('Verify user and bot login in the specified profile before configuring') from None
    bot.CLI, bot.PROFILE = cli, args.profile
    document = bot.call('docs', '+fetch', '--doc', args.doc, '--detail', 'full', '--as', 'user')['document']
    document_id = document['document_id']
    url = args.document_url or (args.doc if args.doc.startswith('https://') else None)
    if not url:
        raise ValueError('Pass a real document URL via --doc or --document-url; do not guess tenant domains')
    root = ET.fromstring('<root>' + document['content'] + '</root>')
    title = root.find('title')
    name = bot.text(title) if title is not None else '每日待办与工作记录'
    runtime = Path(args.runtime_dir).expanduser().resolve() if args.runtime_dir else runtime_default(args.instance).resolve()
    dest = runtime / 'config.json'
    if dest.exists():
        previous = json.loads(dest.read_text(encoding='utf-8'))
        if [previous.get(k) for k in ('app_id', 'owner_open_id', 'document_id')] != [app_id, owner_id, document_id]:
            raise ValueError('This instance belongs to another account/app/document; use a NEW --instance or --runtime-dir')
    config = dict(schema_version=1, instance=args.instance, cli_path=cli, profile=args.profile,
                  app_id=app_id, owner_open_id=owner_id, document_id=document_id, document_url=url,
                  document_title=name, timezone=args.timezone, reminder_title='今日待办提醒⏰',
                  state_dir=str(runtime / 'state'))
    bot.ZoneInfo(args.timezone)  # Fail before writing when timezone data is unavailable.
    runtime.mkdir(parents=True, exist_ok=True)
    runtime.chmod(0o700)
    shutil.copy2(Path(__file__).with_name('bot.py'), runtime / 'bot.py')
    write_json(dest, config)
    print(json.dumps(dict(config=str(dest), runtime=str(runtime), profile=args.profile,
                          app_id=app_id, owner_open_id=owner_id, document_id=document_id), ensure_ascii=False))


def quote_systemd(value):
    if '\n' in value or '\r' in value:
        raise ValueError('Service paths must not contain newlines')
    return json.dumps(value.replace('%', '%%').replace('$', '$$'), ensure_ascii=False)


def service(args):
    config = bot.configure(args.config)
    runtime = bot.CONFIG_PATH.parent
    python = str(Path(sys.executable).resolve())
    program = str(runtime / 'bot.py')
    argv = [python, program, '--config', str(bot.CONFIG_PATH)]
    instance = config.get('instance', 'personal')
    name = 'feishu-todo-reminders-' + instance
    output = Path(args.output_dir).expanduser().resolve() if args.output_dir else runtime / 'service'
    output.mkdir(parents=True, exist_ok=True)
    if args.kind == 'systemd':
        path = output / (name + '.service')
        path.write_text('[Unit]\nDescription=Feishu personal todo inbox\nAfter=network-online.target\nWants=network-online.target\n\n[Service]\nType=simple\n'
                        + 'WorkingDirectory=' + quote_systemd(str(runtime)) + '\nExecStart='
                        + ' '.join(quote_systemd(v) for v in argv)
                        + '\nEnvironment=PYTHONUNBUFFERED=1\nRestart=always\nRestartSec=10\nKillMode=process\nTimeoutStopSec=20\nUMask=0077\n\n[Install]\nWantedBy=default.target\n', encoding='utf-8')
    elif args.kind == 'launchd':
        path = output / ('local.' + name + '.plist')
        with path.open('wb') as f:
            plistlib.dump(dict(Label='local.' + name, ProgramArguments=argv, RunAtLoad=True, KeepAlive=True,
                              WorkingDirectory=str(runtime), StandardOutPath=str(runtime / 'stdout.log'),
                              StandardErrorPath=str(runtime / 'stderr.log'), ThrottleInterval=10), f)
    else:
        ns = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
        ET.register_namespace('', ns)
        def node(parent, tag, value=None, **attrs):
            e = ET.SubElement(parent, '{' + ns + '}' + tag, attrs)
            e.text = value
            return e
        task = ET.Element('{' + ns + '}Task', version='1.2')
        trigger = node(node(task, 'Triggers'), 'LogonTrigger')
        node(trigger, 'Enabled', 'true')
        principal = node(node(task, 'Principals'), 'Principal', id='Author')
        node(principal, 'UserId', getpass.getuser())
        node(principal, 'LogonType', 'InteractiveToken')
        node(principal, 'RunLevel', 'LeastPrivilege')
        settings = node(task, 'Settings')
        node(settings, 'MultipleInstancesPolicy', 'IgnoreNew')
        node(settings, 'DisallowStartIfOnBatteries', 'false')
        node(settings, 'StopIfGoingOnBatteries', 'false')
        node(settings, 'ExecutionTimeLimit', 'PT0S')
        node(settings, 'Enabled', 'true')
        restart = node(settings, 'RestartOnFailure')
        node(restart, 'Interval', 'PT1M')
        node(restart, 'Count', '3')
        executable = node(node(task, 'Actions', Context='Author'), 'Exec')
        node(executable, 'Command', python)
        node(executable, 'Arguments', subprocess.list2cmdline(argv[1:]))
        node(executable, 'WorkingDirectory', str(runtime))
        path = output / (name + '.xml')
        ET.ElementTree(task).write(path, encoding='utf-16', xml_declaration=True)
    print(json.dumps(dict(service_file=str(path), name=name, enabled=False), ensure_ascii=False))


def import_state(args):
    config = bot.configure(args.config)
    expected = [args.source_app_id, args.source_owner_open_id, args.source_document_id]
    actual = [bot.APP_ID, bot.OWNER, bot.DOC]
    if expected != actual:
        raise ValueError('State can only be imported for the SAME app, owner and document')
    target = bot.BASE / 'state.sqlite3'
    if target.exists():
        raise ValueError('Target state already exists; stop the service and use a fresh instance directory')
    source = Path(args.source).expanduser().resolve()
    if not source.is_file():
        raise ValueError('Source state file not found')
    src = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    has_metadata = src.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='runtime_metadata'").fetchone()[0]
    if has_metadata:
        old = src.execute("SELECT value FROM runtime_metadata WHERE key='binding'").fetchone()
        if old and old[0] != bot.binding():
            raise ValueError('Source database identity does not match')
    dest = sqlite3.connect(target)
    src.backup(dest)
    dest.execute('CREATE TABLE IF NOT EXISTS runtime_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    dest.execute("INSERT OR REPLACE INTO runtime_metadata VALUES ('binding',?)", (bot.binding(),))
    dest.commit()
    src.close()
    dest.close()
    target.chmod(0o600)
    print(json.dumps(dict(imported=str(target), app_id=config['app_id']), ensure_ascii=False))


def automation_prompt(args):
    config = bot.configure(args.config)
    argv = [str(Path(sys.executable).resolve()), str(bot.CONFIG_PATH.parent / 'bot.py'), '--config', str(bot.CONFIG_PATH), '--send-reminder']
    print('每周一至周五 ' + config['timezone'] + ' 上午10:00执行。用户已授权应用机器人向配置中的本人发送待办提醒。'
          + '用exec_command或等效命令工具执行以下argv所表示的命令（安全传参，不通过正文拼接shell）：' + json.dumps(argv, ensure_ascii=False)
          + '。脚本校验绑定账号，读取最新文档，发送原生富文本提醒，并持久化每日去重回执；周末、同日已成功发送会静默跳过。'
          + '脚本返回sent且有message_id才视为成功；already_sent或skipped_weekend不重复发消息。非零退出码或pending结果待确认时报告失败，不得当成暂无待办，不自动清除去重记录重发。'
          + '手动/todo独立，不消耗每日回执。不改任务、不输出密钥；正常发送后在Codex简短或静默。运行需要能写CLI凭据目录、状态目录并联网；遇到沙箱禁止时报告限制，不绕过审批。')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('configure', help='Read-only Feishu verification; writes only local runtime/config')
    p.add_argument('--profile', required=True)
    p.add_argument('--doc', required=True)
    p.add_argument('--document-url')
    p.add_argument('--runtime-dir')
    p.add_argument('--cli', default='lark-cli')
    p.add_argument('--instance', default='personal')
    p.add_argument('--timezone', default='Asia/Shanghai')
    p.set_defaults(func=configure)
    p = sub.add_parser('service', help='Generate a service file; does not install or start it')
    p.add_argument('--config', required=True)
    p.add_argument('--kind', required=True, choices=['systemd', 'launchd', 'windows'])
    p.add_argument('--output-dir')
    p.set_defaults(func=service)
    p = sub.add_parser('import-state', help='Import a stopped legacy/same-account state DB using SQLite backup')
    p.add_argument('--config', required=True)
    p.add_argument('--source', required=True)
    p.add_argument('--source-app-id', required=True)
    p.add_argument('--source-owner-open-id', required=True)
    p.add_argument('--source-document-id', required=True)
    p.set_defaults(func=import_state)
    p = sub.add_parser('automation-prompt', help='Print a user-readable prompt for the Codex automation tool')
    p.add_argument('--config', required=True)
    p.set_defaults(func=automation_prompt)
    args = parser.parse_args()
    if hasattr(args, 'instance') and not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', args.instance):
        parser.error('--instance must be a lowercase name such as personal or work')
    try:
        args.func(args)
    except Exception as exc:
        print(str(exc) if isinstance(exc, (ValueError, RuntimeError, FileNotFoundError)) else type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
