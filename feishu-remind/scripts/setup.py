#!/usr/bin/env python3
"""Configure a new reminder runtime, generate a unit, or copy bound SQLite state."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys

SKILL_DIR = Path(__file__).resolve().parents[1]
RUNTIME_FILES = ('remind_bot.py', 'time_rules.py')


def env():
    return dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER='1', LARKSUITE_CLI_NO_SKILLS_NOTIFIER='1')


def binding(config):
    return [1, config['app_id'], config['owner_open_id'], config['timezone']]


def read_config(path):
    config = json.loads(Path(path).expanduser().read_text(encoding='utf-8'))
    for key in ('cli_path', 'profile', 'app_id', 'owner_open_id', 'timezone', 'state_dir'):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError('Missing configuration key: ' + key)
    if config.get('schema_version') != 1 or config['timezone'] != 'Asia/Shanghai':
        raise ValueError('Expected schema_version=1 and timezone=Asia/Shanghai')
    if not config['owner_open_id'].startswith('ou_'):
        raise ValueError('Invalid owner_open_id')
    return config


def configure(args):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', args.instance):
        raise ValueError('instance must be a lowercase name such as personal')
    cli = shutil.which(args.cli) or str(Path(args.cli).expanduser().resolve())
    if not Path(cli).is_file():
        raise ValueError('Install lark-cli or pass its executable path with --cli')
    proc = subprocess.run([cli, '--profile', args.profile, 'auth', 'status', '--json', '--verify'],
                          capture_output=True, text=True, timeout=60, env=env())
    try:
        status = json.loads(proc.stdout)
        user, bot = status['identities']['user'], status['identities']['bot']
        if proc.returncode or not user.get('verified') or not bot.get('verified'):
            raise ValueError()
        owner, app_id = user['openId'], status['appId']
        if not owner.startswith('ou_') or not app_id:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError('Verify user and bot identities in the specified profile first') from None
    data_root = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))).expanduser()
    runtime = (Path(args.runtime_dir).expanduser() if args.runtime_dir else data_root / 'feishu-remind' / args.instance).resolve()
    if runtime.is_relative_to(SKILL_DIR.parent) or runtime.is_relative_to(Path.home() / '.codex/skills'):
        raise ValueError('Keep the runtime and personal data outside the Skills directory')
    if runtime.exists() and any(runtime.iterdir()):
        raise ValueError('Runtime directory is not empty; preserve existing config/state and use the upgrade procedure')
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime.chmod(0o700)
    config = dict(schema_version=1, instance=args.instance, cli_path=str(Path(cli).resolve()),
                  profile=args.profile, app_id=app_id, owner_open_id=owner,
                  timezone='Asia/Shanghai', state_dir=str(runtime / 'state'))
    for name in RUNTIME_FILES:
        shutil.copy2(Path(__file__).with_name(name), runtime / name)
    destination = runtime / 'config.json'
    destination.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    destination.chmod(0o600)
    return {'config': str(destination), 'runtime': str(runtime), 'profile': args.profile,
            'app_id': app_id, 'owner_open_id': owner, 'service_started': False}


def quote_systemd(value, *, executable_argument=False):
    if any(c in value for c in ('\n', '\r', '\x00')):
        raise ValueError('Service paths may not contain newlines or NUL')
    value = value.replace('%', '%%')
    if executable_argument:
        value = value.replace('$', '$$')
    return json.dumps(value, ensure_ascii=False)


def systemd_directory(value):
    # WorkingDirectory parses a whole path, unlike ExecStart's quoted argument list.
    # Quoting the entire value makes the quote part of the path on systemd.
    if any(c in value for c in ('\n', '\r', '\x00')) or value != value.strip() or value.endswith('\\'):
        raise ValueError('Unsupported whitespace/control characters in service directory')
    return value.replace('%', '%%')


def service(args):
    config_path = Path(args.config).expanduser().resolve()
    config = read_config(config_path)
    runtime = config_path.parent
    name = args.name or 'feishu-remind-' + config.get('instance', 'personal')
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', name):
        raise ValueError('service name must contain lowercase letters, digits and hyphens, without .service')
    for filename in RUNTIME_FILES:
        if not (runtime / filename).is_file():
            raise ValueError('Runtime code missing: ' + filename)
    output = Path(args.output_dir).expanduser().resolve() if args.output_dir else runtime / 'service'
    output.mkdir(parents=True, exist_ok=True)
    argv = [str(Path(sys.executable).resolve()), str(runtime / 'remind_bot.py'), '--config', str(config_path)]
    text = ('[Unit]\nDescription=Feishu personal rule-based reminders\n'
            'After=network-online.target\nWants=network-online.target\n\n[Service]\nType=simple\n'
            + 'WorkingDirectory=' + systemd_directory(str(runtime)) + '\nExecStart='
            + ' '.join(quote_systemd(v, executable_argument=True) for v in argv)
            + '\nEnvironment=PYTHONUNBUFFERED=1\nRestart=always\nRestartSec=5\n'
            'KillMode=control-group\nTimeoutStopSec=65\nUMask=0077\n\n[Install]\nWantedBy=default.target\n')
    path = output / (name + '.service')
    path.write_text(text, encoding='utf-8')
    return {'service_file': str(path), 'name': name, 'installed': False, 'started': False}


def copy_state(config, source, target):
    """Copy an entire SQLite snapshot, preserving stable numbers and delivery receipts."""
    source, target = Path(source).expanduser().resolve(), Path(target).expanduser().resolve()
    if not source.is_file():
        raise ValueError('Source database not found')
    if any(Path(str(target) + suffix).exists() for suffix in ('', '-wal', '-shm')):
        raise ValueError('Target database already exists; never overwrite reminder state')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Check identity before creating a destination. Do not repair or rewrite a source binding.
    with contextlib.closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
        try:
            row = src.execute("SELECT value FROM metadata WHERE key='binding'").fetchone()
            if row is None or json.loads(row[0]) != binding(config):
                raise ValueError('Source database belongs to a different App, owner or timezone')
            if src.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Source database integrity check failed')
        except (sqlite3.DatabaseError, json.JSONDecodeError):
            raise ValueError('Source database is not a valid bound reminder snapshot') from None
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            with contextlib.closing(sqlite3.connect(target)) as dest:
                src.backup(dest)
                if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Copied database integrity check failed')
        except Exception:
            # This file was created exclusively by this call; an existing target is never removed.
            for suffix in ('', '-wal', '-shm'):
                Path(str(target) + suffix).unlink(missing_ok=True)
            raise
    return str(target)


def backup_state(args):
    config = read_config(args.config)
    source = Path(config['state_dir']).expanduser().resolve() / 'state.sqlite3'
    return {'backup': copy_state(config, source, args.output)}


def import_state(args):
    config = read_config(args.config)
    state_dir = Path(config['state_dir']).expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state_dir / 'runtime.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Stop this reminder service before importing') from None
        target = copy_state(config, args.source, state_dir / 'state.sqlite3')
    return {'imported': target, 'app_id': config['app_id'], 'owner_open_id': config['owner_open_id']}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    cmd = sub.add_parser('configure', help='Verify identity and write a new runtime; no messages or service start')
    cmd.add_argument('--profile', required=True)
    cmd.add_argument('--cli', default='lark-cli')
    cmd.add_argument('--instance', default='personal')
    cmd.add_argument('--runtime-dir')
    cmd.set_defaults(func=configure)
    cmd = sub.add_parser('service', help='Generate a systemd unit, without installing or starting it')
    cmd.add_argument('--config', required=True)
    cmd.add_argument('--name')
    cmd.add_argument('--output-dir')
    cmd.set_defaults(func=service)
    cmd = sub.add_parser('backup-state', help='Create a new consistent same-identity SQLite snapshot')
    cmd.add_argument('--config', required=True)
    cmd.add_argument('--output', required=True)
    cmd.set_defaults(func=backup_state)
    cmd = sub.add_parser('import-state', help='Import a same-identity snapshot into an empty, stopped instance')
    cmd.add_argument('--config', required=True)
    cmd.add_argument('--source', required=True)
    cmd.set_defaults(func=import_state)
    args = parser.parse_args()
    try:
        print(json.dumps(args.func(args), ensure_ascii=False))
    except Exception as exc:
        print(str(exc) if isinstance(exc, (ValueError, RuntimeError, FileNotFoundError)) else type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
