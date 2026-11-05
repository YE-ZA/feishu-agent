#!/usr/bin/env python3
"""Verify dependencies and generate an isolated draw runtime; no remote mutations."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
RUNTIME_FILES = ('draw_bot.py', 'render.js', 'output-schema.json', 'review-schema.json')


def binary(value):
    path = shutil.which(value) or str(Path(value).expanduser().resolve())
    if not Path(path).is_file() or not os.access(path, os.X_OK):
        raise ValueError('Executable unavailable: ' + value)
    return str(Path(path).resolve())


def run(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=90,
                            env=dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER='1',
                                     LARKSUITE_CLI_NO_SKILLS_NOTIFIER='1'))
    if result.returncode:
        # Do not print authentication output or credential-store diagnostics.
        raise ValueError('Dependency or read-only verification failed: ' + Path(argv[0]).name)
    return result.stdout


def configure(args):
    if os.name != 'posix':
        raise ValueError('Current draw runtime requires POSIX fcntl (Linux/macOS)')
    runtime = Path(args.runtime_dir).expanduser().resolve()
    skill = HERE.parent
    if runtime == skill or runtime.is_relative_to(skill) or skill.is_relative_to(runtime):
        raise ValueError('Choose a dedicated runtime outside the Skill directory')
    if runtime.exists() and any(runtime.iterdir()):
        raise ValueError('Runtime directory must be new or empty; use operations.md to upgrade')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,39}', args.instance):
        raise ValueError('Instance must be 1-40 lowercase letters/digits/hyphens')
    parsed = urlsplit(args.doc)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Pass the real HTTPS document URL without embedded credentials')
    ZoneInfo(args.timezone)
    cli, codex, node = map(binary, (args.cli, args.codex, args.node))
    sharp = Path(args.sharp_module).expanduser().resolve()
    if not sharp.exists():
        raise ValueError('sharp module path not found')
    prefix = [cli, '--profile', args.profile]
    status = json.loads(run(prefix + ['auth', 'status', '--json', '--verify']))
    try:
        user, bot = status['identities']['user'], status['identities']['bot']
        if not user['verified'] or not bot['verified'] or not user['available'] or not bot['available']:
            raise KeyError('unverified')
        owner, app_id = user['openId'], status['appId']
        if not owner or not app_id:
            raise KeyError('missing binding')
    except KeyError:
        raise ValueError('Verify both user and bot in the specified profile') from None
    response = json.loads(run(prefix + ['docs', '+fetch', '--doc', args.doc, '--scope', 'outline', '--as', 'user']))
    if response.get('ok') is not True:
        raise ValueError('Document read verification failed')
    doc = response['data']['document']['document_id']
    if not doc:
        raise ValueError('Document ID unavailable')
    run([codex, 'login', 'status'])
    # Exercise the actual renderer rather than only checking that paths exist.
    with tempfile.TemporaryDirectory(prefix='feishu-draw-check-') as tmp:
        source, output = Path(tmp) / 'check.svg', Path(tmp) / 'check.png'
        source.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200"><rect width="400" height="200" fill="white"/><text x="20" y="80" font-family="Noto Sans CJK SC" font-size="24">绘图检查</text></svg>', encoding='utf-8')
        run([node, str(HERE / 'render.js'), str(sharp), str(source), str(output)])
        if not output.is_file() or not output.stat().st_size:
            raise ValueError('Renderer produced no image')
    config = dict(schema_version=1, instance=args.instance, cli_path=cli, profile=args.profile,
                  app_id=app_id, owner_open_id=owner, archive_document_id=doc,
                  archive_document_url=args.doc.split('#', 1)[0], state_dir=str(runtime / 'state'),
                  timezone=args.timezone, codex_path=codex, node_path=node, sharp_module=str(sharp),
                  reasoning_effort=args.reasoning_effort, generation_timeout=900, max_images=6)
    if args.model:
        config['model'] = args.model
    runtime.mkdir(parents=True, exist_ok=True)
    runtime.chmod(0o700)
    for name in RUNTIME_FILES:
        shutil.copy2(HERE / name, runtime / name)
    config_path = runtime / 'config.json'
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    config_path.chmod(0o600)
    print(json.dumps(dict(config=str(config_path), runtime=str(runtime), configured=True, started=False), ensure_ascii=False))


def systemd_quote(value):
    if any(c in value for c in '\n\r\0'):
        raise ValueError('Invalid service path')
    return json.dumps(value.replace('%', '%%').replace('$', '$$'), ensure_ascii=False)


def service(args):
    config_path = Path(args.config).expanduser().resolve()
    config = json.loads(config_path.read_text(encoding='utf-8'))
    runtime = config_path.parent
    if not all((runtime / name).is_file() for name in RUNTIME_FILES):
        raise ValueError('Runtime files missing beside config')
    instance = config.get('instance', 'personal')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,39}', instance):
        raise ValueError('Invalid instance name')
    name = 'feishu-draw-' + instance
    output = Path(args.output_dir).expanduser().resolve() if args.output_dir else runtime / 'service'
    output.mkdir(parents=True, exist_ok=True)
    argv = [str(Path(sys.executable).resolve()), str(runtime / 'draw_bot.py'), '--config', str(config_path)]
    if args.kind == 'systemd':
        path = output / (name + '.service')
        path.write_text('[Unit]\nDescription=Feishu personal drawing inbox\nAfter=network-online.target\nWants=network-online.target\n\n[Service]\nType=simple\nWorkingDirectory='
                        + systemd_quote(str(runtime)) + '\nExecStart=' + ' '.join(map(systemd_quote, argv))
                        + '\nEnvironment=PYTHONUNBUFFERED=1\nRestart=always\nRestartSec=10\nKillMode=control-group\nTimeoutStopSec=20\nUMask=0077\n\n[Install]\nWantedBy=default.target\n', encoding='utf-8')
    else:
        path = output / ('local.' + name + '.plist')
        with path.open('wb') as stream:
            plistlib.dump(dict(Label='local.' + name, ProgramArguments=argv, RunAtLoad=True,
                              KeepAlive=True, WorkingDirectory=str(runtime), ThrottleInterval=10,
                              StandardOutPath=str(runtime / 'stdout.log'),
                              StandardErrorPath=str(runtime / 'stderr.log')), stream)
    print(json.dumps(dict(service_file=str(path), name=name, installed=False, started=False), ensure_ascii=False))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    command = sub.add_parser('configure', help='Read-only verification and new local runtime')
    command.add_argument('--profile', required=True)
    command.add_argument('--doc', required=True)
    command.add_argument('--runtime-dir', required=True)
    command.add_argument('--cli', default='lark-cli')
    command.add_argument('--codex', default='codex')
    command.add_argument('--node', default='node')
    command.add_argument('--sharp-module', required=True)
    command.add_argument('--instance', default='personal')
    command.add_argument('--timezone', default='Asia/Shanghai')
    command.add_argument('--model')
    command.add_argument('--reasoning-effort', default='high')
    command.set_defaults(func=configure)
    command = sub.add_parser('service', help='Generate a service file without installing it')
    command.add_argument('--config', required=True)
    command.add_argument('--kind', choices=['systemd', 'launchd'], required=True)
    command.add_argument('--output-dir')
    command.set_defaults(func=service)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(str(exc)) from None
