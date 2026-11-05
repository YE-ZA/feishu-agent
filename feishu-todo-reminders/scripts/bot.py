#!/usr/bin/env python3
"""Personal Feishu inbox -> date-grouped document checkboxes. No model or shell eval."""
import datetime as dt
import contextlib
import hashlib
import html
import json
import logging
import os
from pathlib import Path
import re
import queue
import signal
import sqlite3
import subprocess
import shutil
import sys
import threading
import time
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

CLI = shutil.which('lark-cli') or 'lark-cli'
OWNER = ''
DOC = ''
URL = ''
APP_ID = ''
PROFILE = ''
TITLE = '今日待办提醒⏰'
DOCUMENT_TITLE = '每日待办与工作记录'
CONFIG_PATH = None
BASE = Path.home() / '.local/share/feishu-todo-reminders/unconfigured'
TZ = ZoneInfo('Asia/Shanghai')


def configure(path):
    global CLI, OWNER, DOC, URL, APP_ID, PROFILE, TITLE, DOCUMENT_TITLE, CONFIG_PATH, BASE, TZ
    CONFIG_PATH = Path(path).expanduser().resolve()
    data = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    for key in ('cli_path', 'profile', 'app_id', 'owner_open_id', 'document_id', 'document_url', 'state_dir', 'timezone'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError('Missing configuration key: ' + key)
    if data.get('schema_version') != 1:
        raise ValueError('Unsupported configuration schema')
    CLI = str(Path(data['cli_path']).expanduser().resolve())
    if not Path(CLI).is_file():
        raise ValueError('CLI not found; configure its path on this computer')
    PROFILE, APP_ID, OWNER, DOC, URL = (data[k] for k in ('profile', 'app_id', 'owner_open_id', 'document_id', 'document_url'))
    if not URL.startswith('https://'):
        raise ValueError('Document URL must use HTTPS')
    BASE = Path(data['state_dir']).expanduser().resolve()
    BASE.mkdir(parents=True, exist_ok=True)
    TZ = ZoneInfo(data['timezone'])
    TITLE = data.get('reminder_title', '今日待办提醒⏰')
    DOCUMENT_TITLE = data.get('document_title', '每日待办与工作记录')
    return data


def cli_argv(*args):
    return [CLI, *(['--profile', PROFILE] if PROFILE else []), *args]


def cli_env():
    return dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER='1', LARKSUITE_CLI_NO_SKILLS_NOTIFIER='1')


def verify_identity(remote=True):
    args = ['auth', 'status', '--json'] + (['--verify'] if remote else [])
    p = subprocess.run(cli_argv(*args), capture_output=True, text=True, timeout=45, env=cli_env())
    try:
        data = json.loads(p.stdout)
        user = data['identities']['user']
        bot = data['identities']['bot']
        if p.returncode or data['appId'] != APP_ID or user.get('openId') != OWNER:
            raise ValueError('CLI account/app differs from the configured owner')
        if not user.get('available') or not bot.get('available'):
            raise ValueError('CLI user or bot login is unavailable')
        if remote and not (user.get('verified') and bot.get('verified')):
            raise ValueError('CLI identity verification failed')
    except (ValueError, KeyError, TypeError):
        raise RuntimeError('账号校验失败：检查指定 profile 的应用、用户和登录状态；不会向其他账号发送') from None
    return {'app_id': APP_ID, 'owner_open_id': OWNER, 'profile': PROFILE}


def binding():
    return json.dumps([APP_ID, OWNER, DOC], separators=(',', ':'))


def call(*args):
    # Background services do not need update discovery on each API request.
    env = cli_env()
    started = time.monotonic()
    try:
        p = subprocess.run(cli_argv(*args), capture_output=True, text=True, timeout=90, env=env)
    finally:
        logging.info('CLI step=%s elapsed_ms=%d', ' '.join(args[:2]), (time.monotonic() - started) * 1000)
    try:
        out = json.loads(p.stdout if p.returncode == 0 else p.stderr)
    except (ValueError, TypeError):
        raise RuntimeError('CLI 返回异常，操作结果待确认') from None
    if p.returncode or out.get('ok') is not True:
        err = out.get('error', {})
        raise RuntimeError('CLI 调用失败：' + str(err.get('subtype', err.get('type', 'unknown'))))
    data = out.get('data', {})
    if data.get('result') in ('failed', 'partial_success') or data.get('warnings'):
        raise RuntimeError('文档写入未完全成功，需检查')
    return data


def text(node):
    return ''.join(node.itertext()).strip()


def parse_document(data):
    doc = data['document']
    if doc.get('tips'):
        raise RuntimeError('文档读取提示需人工检查')
    root = ET.fromstring('<root>' + doc['content'] + '</root>')
    return root, doc['revision_id']


def fetch():
    return parse_document(call('docs', '+fetch', '--doc', DOC, '--detail', 'full', '--as', 'user'))


def patch(revision, command, **kw):
    args = ['docs', '+update', '--doc', DOC, '--as', 'user', '--revision-id', str(revision), '--command', command]
    for k, v in kw.items():
        args.extend(['--' + k.replace('_', '-'), str(v)])
    return call(*args)


def tasks(root):
    result = []
    date = ''
    for block in root:
        if re.fullmatch(r'h[1-9]', block.tag):
            if '周报' in text(block):
                break
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text(block)):
                date = text(block)
        for item in block.iter('checkbox'):
            if text(item):
                result.append((date, item))
    return result


def is_open(item):
    return item.get('done', 'false').lower() != 'true'


def parse_command(value):
    value = value.strip()
    if value == '/todo':
        return 'list', ''
    prefix = re.match(r'^/todo\s+', value)
    if not prefix:
        return 'ignore', ''
    return 'add', value[prefix.end():].strip()


def render_reminder(root):
    """Shared body for scheduled delivery and an explicit /todo request."""
    values = [text(item) for _, item in tasks(root) if is_open(item)]
    rows = [[{'tag': 'text', 'text': '☐ ' + value}] for value in values]
    if not rows:
        rows = [[{'tag': 'text', 'text': '暂无未完成待办。'}]]
    rows.append([{'tag': 'text', 'text': '\n'}])
    rows.append([{'tag': 'text', 'text': '文档：'},
                 {'tag': 'a', 'text': DOCUMENT_TITLE, 'href': URL}])
    # Native rich-text title renders as the prominent, bold message heading.
    return {'zh_cn': {'title': TITLE, 'content': rows}}


def date_for(event):
    return dt.datetime.fromtimestamp(int(event['create_time']) / 1000, TZ).date().isoformat()


def insertion(root, date, value):
    checkbox = '<checkbox done="false">' + html.escape(value).replace('\n', '<br/>') + '</checkbox>'
    blocks = list(root)
    for i, block in enumerate(blocks):
        if re.fullmatch(r'h[1-9]', block.tag) and text(block) == date:
            anchor = block
            for b in blocks[i+1:]:
                if re.fullmatch(r'h[1-9]', b.tag):
                    break
                anchor = b
            return anchor.attrib['id'], checkbox
    # New dates sit above older dates; never insert inside the weekly report.
    return blocks[0].attrib['id'], '<h1>' + date + '</h1>' + checkbox


class Bot:
    def __init__(self, db_path=None):
        self.db = sqlite3.connect(db_path or BASE / 'state.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS runtime_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        old = self.db.execute("SELECT value FROM runtime_metadata WHERE key='binding'").fetchone()
        has_data = self.db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='messages'").fetchone()[0]
        if old and old[0] != binding():
            self.db.close()
            raise RuntimeError('State database belongs to another app/account/document; use a separate runtime directory')
        if not old and has_data and self.db.execute('SELECT count(*) FROM messages').fetchone()[0]:
            self.db.close()
            raise RuntimeError('Legacy database requires explicit import-state with its original identity')
        self.db.execute("INSERT OR IGNORE INTO runtime_metadata VALUES ('binding', ?)", (binding(),))
        self.db.execute('CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, state TEXT, payload TEXT, reply TEXT, replied INTEGER DEFAULT 0)')
        self.db.execute('CREATE TABLE IF NOT EXISTS inbox (id TEXT PRIMARY KEY, event TEXT, done INTEGER DEFAULT 0)')
        self.db.commit()

    def enqueue(self, event):
        if event.get('sender_id') == OWNER and event.get('sender_type') == 'user' and event.get('chat_type') == 'p2p' and event.get('message_id', '').startswith('om_'):
            try:
                logging.info('event delivery_ms=%d', time.time() * 1000 - int(event['create_time']))
            except (ValueError, KeyError):
                pass
            self.db.execute('INSERT OR IGNORE INTO inbox(id,event) VALUES(?,?)', (event['message_id'], json.dumps(event, ensure_ascii=False)))
            self.db.commit()

    def drain(self):
        for mid, raw in self.db.execute('SELECT id,event FROM inbox WHERE done=0 ORDER BY rowid').fetchall():
            started = time.monotonic()
            try:
                self.handle(json.loads(raw))
                self.db.execute('UPDATE inbox SET done=1 WHERE id=?', (mid,))
                self.db.commit()
                logging.info('message processed elapsed_ms=%d', (time.monotonic() - started) * 1000)
            except Exception as exc:
                logging.error('processing failed (%s); will reconcile before retry', type(exc).__name__)

    def save(self, mid, state, payload=None, reply=''):
        if isinstance(reply, dict):
            reply = json.dumps(reply, ensure_ascii=False)
        self.db.execute('INSERT INTO messages(id,state,payload,reply) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,payload=excluded.payload,reply=excluded.reply',
                        (mid, state, json.dumps(payload, ensure_ascii=False), reply))
        self.db.commit()

    def respond(self, mid, reply):
        # Old receipts contain plain text; new reminder receipts contain native post JSON.
        if isinstance(reply, str) and reply.startswith('{'):
            try:
                candidate = json.loads(reply)
                if isinstance(candidate, dict) and 'zh_cn' in candidate:
                    reply = candidate
            except ValueError:
                pass
        content_args = (['--msg-type', 'post', '--content', json.dumps(reply, ensure_ascii=False)]
                        if isinstance(reply, dict) else ['--text', reply])
        call('im', '+messages-reply', '--as', 'bot', '--message-id', mid,
             *content_args, '--idempotency-key', 'todo-' + hashlib.sha256(mid.encode()).hexdigest()[:40])
        self.db.execute('UPDATE messages SET replied=1 WHERE id=?', (mid,))
        self.db.commit()

    def handle(self, event):
        if event.get('sender_id') != OWNER or event.get('sender_type') != 'user' or event.get('chat_type') != 'p2p':
            return
        mid = event.get('message_id', '')
        if not mid.startswith('om_'):
            return
        if CONFIG_PATH:
            verify_identity(remote=False)
        row = self.db.execute('SELECT state,payload,reply,replied FROM messages WHERE id=?', (mid,)).fetchone()
        if row:
            if row[0] == 'pending':
                self.recover(mid, json.loads(row[1]))
            elif row[2] and not row[3]:
                self.respond(mid, row[2])
            return
        if event.get('message_type') != 'text':
            self.save(mid, 'ignored')
            return
        action, value = parse_command(event.get('content', ''))
        if action == 'ignore':
            self.save(mid, 'ignored')
            return
        if len(value) > 4000:
            self.finish(mid, '事项太长，请缩短到 4000 字以内。')
            return
        root, revision = fetch()
        if action == 'list':
            self.finish(mid, render_reminder(root))
            return
        items = tasks(root)
        date = date_for(event)
        anchor, content = insertion(root, date, value)
        payload = dict(action=action, value=value, date=date, before=[i.get('id') for _, i in items])
        self.save(mid, 'pending', payload)
        patch(revision, 'block_insert_after', block_id=anchor, content=content)
        self.recover(mid, payload)

    def finish(self, mid, reply):
        self.save(mid, 'done', reply=reply)
        self.respond(mid, reply)

    def recover(self, mid, payload):
        # Re-read after writes (including ambiguous network failures). Never blindly replay writes.
        root, revision = fetch()
        items = tasks(root)
        action, value = payload['action'], payload['value']
        found = [i for d, i in items if d == payload['date'] and text(i) == value and i.get('id') not in payload['before']]
        if len(found) != 1:
            self.finish(mid, '这条操作的写入结果未能确认，为避免重复记录，没有自动重试。请先查看文档。\n' + URL)
            return
        reply = '已添加：' + value
        # Remove an empty-state notice only after a real checkbox has been verified.
        for b in root:
            if b.tag == 'p' and text(b) == '暂无待办。':
                patch(revision, 'block_delete', block_id=b.attrib['id'])
                break
        reply += '\n创建日期：' + payload['date']
        self.finish(mid, reply + '\n' + URL + '#' + found[0].attrib['id'])


def run():
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    bot = Bot()
    stop = threading.Event()
    child = None

    def shutdown(*_):
        stop.set()
        if child and child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    while not stop.is_set():
        ready = threading.Event()
        # A bounded session ignores stdin EOF; rotate periodically to recover dropped connections.
        child = subprocess.Popen(cli_argv('event', 'consume', 'im.message.receive_v1', '--as', 'bot', '--timeout', '24h'),
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, env=cli_env())

        def diagnostics(proc):
            for line in proc.stderr:
                if '[event] ready event_key=' in line:
                    ready.set()
                    logging.info('listener ready')
                elif any(word in line for word in ('connected', 'WARN', 'error', 'exited')):
                    # Do not log event payloads, credentials, or raw CLI envelopes.
                    logging.info('listener diagnostic: %s', line.strip() if line.startswith(('[event]', '[source]')) else 'check CLI connection')

        t = threading.Thread(target=diagnostics, args=(child,), daemon=True)
        t.start()
        if not ready.wait(45):
            logging.error('listener did not become ready')
            child.terminate()
        else:
            lines = queue.Queue()

            def read_events(proc):
                for line in proc.stdout:
                    lines.put(line)
                lines.put(None)

            reader = threading.Thread(target=read_events, args=(child,), daemon=True)
            reader.start()
            last_retry = 0
            while not stop.is_set():
                try:
                    line = lines.get(timeout=5)
                    if line is None:
                        break
                    bot.enqueue(json.loads(line))
                    bot.drain()
                except queue.Empty:
                    if time.monotonic() - last_retry > 60:
                        bot.drain()
                        last_retry = time.monotonic()
                except ValueError:
                    logging.error('invalid event JSON')
        child.wait()
        t.join(timeout=2)
        stop.wait(10)


def send_scheduled():
    """One scheduled delivery per local weekday; ambiguous sends require reconciliation."""
    now = dt.datetime.now(TZ)
    if now.weekday() >= 5:
        return {'status': 'skipped_weekend'}
    # Validate state ownership even when only the schedule is being used.
    store = Bot()
    store.db.close()
    with contextlib.closing(sqlite3.connect(BASE / 'deliveries.sqlite3', timeout=30)) as receipt:
        return _send_scheduled_with_receipt(receipt, now)


def _send_scheduled_with_receipt(receipt, now):
    receipt.execute('CREATE TABLE IF NOT EXISTS deliveries (day TEXT PRIMARY KEY, status TEXT, message_id TEXT)')
    day = now.date().isoformat()
    receipt.execute('BEGIN IMMEDIATE')
    old = receipt.execute('SELECT status,message_id FROM deliveries WHERE day=?', (day,)).fetchone()
    if old:
        receipt.rollback()
        if old[0] == 'success':
            return {'status': 'already_sent', 'message_id': old[1]}
        raise RuntimeError('已有结果待确认的发送记录；先核对飞书消息，禁止自动重复发送')
    root, _ = fetch()
    body = render_reminder(root)
    receipt.execute('INSERT INTO deliveries VALUES (?, ?, ?)', (day, 'pending', None))
    receipt.commit()
    key = 'todo-' + hashlib.sha256(binding().encode()).hexdigest()[:16] + '-' + day
    result = call('im', '+messages-send', '--as', 'bot', '--user-id', OWNER, '--msg-type', 'post',
                  '--content', json.dumps(body, ensure_ascii=False), '--idempotency-key', key)
    mid = result.get('message_id')
    if not mid:
        raise RuntimeError('发送回执缺少 message_id；记录保留为待确认')
    receipt.execute('UPDATE deliveries SET status=?,message_id=? WHERE day=?', ('success', mid, day))
    receipt.commit()
    return {'status': 'sent', 'message_id': mid}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=os.environ.get('FEISHU_TODO_CONFIG', str(Path(__file__).with_name('config.json'))))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--render-reminder', action='store_true', help='Read-only: output native post JSON')
    modes.add_argument('--send-reminder', action='store_true', help='Send the scheduled weekday reminder, with daily deduplication')
    modes.add_argument('--check', action='store_true', help='Verify identity, document read and local state permissions; no messages or document writes')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        configure(args.config)
        verify_identity()
        if args.render_reminder or args.check:
            root, _ = fetch()
            if args.check:
                instance = Bot()
                instance.db.close()
                print(json.dumps(dict(status='ok', profile=PROFILE, app_id=APP_ID, owner_open_id=OWNER,
                                      document_id=DOC, open_tasks=sum(is_open(n) for _, n in tasks(root))), ensure_ascii=False))
            else:
                print(json.dumps(render_reminder(root), ensure_ascii=False))
        elif args.send_reminder:
            print(json.dumps(send_scheduled(), ensure_ascii=False))
        else:
            run()
    except Exception as exc:
        print(str(exc) if isinstance(exc, (RuntimeError, ValueError, FileNotFoundError)) else type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
