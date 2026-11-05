#!/usr/bin/env python3
"""Owner-only /remind companion with durable schedules and a bounded retry outbox."""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import queue
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from zoneinfo import ZoneInfo

from time_rules import HELP, ParseError, confirmation, format_time, next_occurrence, parse_reminder, recurrence_label

COMMAND = re.compile(r'^/remind(?:\s+|$)')
RETRY_WINDOW = 50 * 60  # CLI's message idempotency window is one hour; leave margin.


class DeliveryError(RuntimeError):
    pass


def milliseconds(value):
    return int(value.timestamp() * 1000)


class Bot:
    def __init__(self, config):
        self.cfg = dict(config)
        for key in ('cli_path', 'profile', 'app_id', 'owner_open_id', 'state_dir', 'timezone'):
            if not isinstance(self.cfg.get(key), str) or not self.cfg[key].strip():
                raise ValueError('缺少配置：' + key)
        if self.cfg.get('schema_version') != 1 or self.cfg['timezone'] != 'Asia/Shanghai':
            raise ValueError('当前版本要求 schema_version=1、timezone=Asia/Shanghai')
        if not Path(self.cfg['cli_path']).is_file():
            raise ValueError('找不到配置的 lark-cli')
        if not self.cfg['owner_open_id'].startswith('ou_'):
            raise ValueError('owner_open_id 格式错误')
        self.tz = ZoneInfo(self.cfg['timezone'])
        self.stop = threading.Event()
        self.state_dir = Path(self.cfg['state_dir']).expanduser().resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path = self.state_dir / 'state.sqlite3'
        self.init_db()

    @contextlib.contextmanager
    def db(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def init_db(self):
        expected = json.dumps([1, self.cfg['app_id'], self.cfg['owner_open_id'], self.cfg['timezone']])
        with self.db() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            binding = db.execute("SELECT value FROM metadata WHERE key='binding'").fetchone()
            if binding and binding['value'] != expected:
                raise ValueError('状态库属于其他应用、用户或时区；请使用新的运行目录')
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('binding', ?)", (expected,))
            db.execute('''CREATE TABLE IF NOT EXISTS inbox (
                id TEXT PRIMARY KEY, event TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0)''')
            db.execute('''CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY, source TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
                rule TEXT NOT NULL, next_due INTEGER, status TEXT NOT NULL DEFAULT 'active')''')
            db.execute('''CREATE TABLE IF NOT EXISTS outbox (
                id TEXT PRIMARY KEY, reminder_id TEXT, kind TEXT NOT NULL, source TEXT NOT NULL,
                mode TEXT NOT NULL, content TEXT NOT NULL, scheduled_at INTEGER,
                state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                first_attempt REAL, retry_at REAL NOT NULL DEFAULT 0,
                remote_id TEXT, last_error TEXT)''')
            db.execute('CREATE INDEX IF NOT EXISTS reminders_due ON reminders(status,next_due)')
            db.execute('CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(state,retry_at)')
            # A separate mapping upgrades the original database without rewriting reminder IDs/receipts.
            db.execute('''CREATE TABLE IF NOT EXISTS reminder_numbers (
                number INTEGER PRIMARY KEY AUTOINCREMENT, reminder_id TEXT NOT NULL UNIQUE)''')
            db.execute('''INSERT INTO reminder_numbers(reminder_id)
                SELECT id FROM reminders WHERE id NOT IN (SELECT reminder_id FROM reminder_numbers)
                ORDER BY rowid''')

    def argv(self, *args):
        return [self.cfg['cli_path'], '--profile', self.cfg['profile'], *args]

    def env(self):
        return dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER='1', LARKSUITE_CLI_NO_SKILLS_NOTIFIER='1')

    def check_identity(self, remote=False):
        argv = self.argv('auth', 'status', '--json') + (['--verify'] if remote else [])
        proc = subprocess.run(argv, env=self.env(), capture_output=True, text=True, timeout=45)
        try:
            result = json.loads(proc.stdout)
            bot = result['identities']['bot']
            if (proc.returncode or result['appId'] != self.cfg['app_id']
                    or result['identities']['user']['openId'] != self.cfg['owner_open_id']
                    or not bot['available'] or (remote and not bot['verified'])):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise DeliveryError('应用或本人身份校验失败，暂停发送') from None

    def call(self, *args):
        proc = subprocess.run(self.argv(*args), env=self.env(), capture_output=True, text=True, timeout=40)
        try:
            result = json.loads(proc.stdout if proc.returncode == 0 else proc.stderr)
            if proc.returncode or result.get('ok') is not True:
                error = result.get('error', {})
                raise DeliveryError('CLI:' + str(error.get('subtype', error.get('type', 'unknown'))))
            return result['data']
        except (ValueError, KeyError, TypeError):
            raise DeliveryError('CLI返回结果不明确') from None

    def accept(self, event):
        if (event.get('sender_id') != self.cfg['owner_open_id'] or event.get('sender_type') != 'user'
                or event.get('chat_type') != 'p2p' or event.get('message_type') not in ('text', 'post')
                or not event.get('message_id', '').startswith('om_')):
            return False
        content = event.get('content', '').strip()
        # Plain cancellation is accepted only as a direct reply. Unknown targets stay silent.
        if not COMMAND.match(content) and not (content == '取消' and self.parent_message(event)):
            return False
        with self.db() as db:
            inserted = db.execute('INSERT OR IGNORE INTO inbox(id,event) VALUES(?,?)',
                                  (event['message_id'], json.dumps(event, ensure_ascii=False))).rowcount
        return bool(inserted)

    def add(self, db, source, spec, mode='reply'):
        reminder_id = hashlib.sha256(source.encode()).hexdigest()[:24]
        db.execute('INSERT OR IGNORE INTO reminders(id,source,title,rule,next_due) VALUES(?,?,?,?,?)',
                   (reminder_id, source, spec.title, json.dumps(spec.rule), milliseconds(spec.due)))
        db.execute('''INSERT INTO reminder_numbers(reminder_id)
            SELECT ? WHERE NOT EXISTS (SELECT 1 FROM reminder_numbers WHERE reminder_id=?)''',
                   (reminder_id, reminder_id))
        code = self.reminder_code(db, reminder_id)
        self.queue_message(db, 'ack-' + reminder_id, source,
                           confirmation(spec) + f'\n编号：{code}\n取消：回复本消息发送“取消”，或发送 /remind 取消 {code}', mode=mode,
                           reminder_id=reminder_id, kind='ack')
        return reminder_id

    @staticmethod
    def parent_message(event):
        # root_id can identify an unrelated message higher in a thread. Never guess from it.
        parent = event.get('reply_to') or event.get('parent_id')
        return parent if isinstance(parent, str) and parent.startswith('om_') else None

    @staticmethod
    def reminder_code(db, reminder_id):
        row = db.execute('SELECT number FROM reminder_numbers WHERE reminder_id=?', (reminder_id,)).fetchone()
        return f"R{row['number']:03d}"

    @staticmethod
    def reply_target(db, parent):
        if not parent:
            return None
        rows = db.execute('''SELECT DISTINCT r.* FROM reminders r WHERE r.source=? OR r.id IN (
            SELECT reminder_id FROM outbox WHERE remote_id=? AND kind IN ('ack','due'))''',
                          (parent, parent)).fetchall()
        return rows[0] if len(rows) == 1 else None

    def list_messages(self, db):
        rows = db.execute('''SELECT r.*,n.number FROM reminders r
            JOIN reminder_numbers n ON n.reminder_id=r.id
            WHERE r.status IN ('active','uncertain')
            ORDER BY CASE WHEN r.status='uncertain' THEN 1 ELSE 0 END,r.next_due,n.number''').fetchall()
        if not rows:
            return ['当前暂无有效提醒。\n\n添加示例：/remind 明天下午3点 约会议室\n'
                    '重复提醒：/remind 每天晚上10点 备份代码']
        header = '当前提醒（北京时间）：\n\n'
        footer = (f"\n\n取消示例：/remind 取消 R{rows[0]['number']:03d}\n"
                  '也可回复设置确认或到点消息，发送“取消”。')
        messages, entries = [], []
        for row in rows:
            rule = json.loads(row['rule'])
            clock = f"{rule['hour']:02d}:{rule['minute']:02d}" if rule['kind'] != 'once' else ''
            next_time = (format_time(dt.datetime.fromtimestamp(row['next_due'] / 1000, self.tz))
                         if row['next_due'] is not None else '待核查')
            entry = (f"R{row['number']:03d} · {row['title']}\n"
                     f"{recurrence_label(rule)}{(' ' + clock) if clock else ''}\n下次：{next_time}")
            if row['status'] == 'uncertain':
                entry += '\n状态：发送结果待核查，已暂停自动发送'
            if entries and len((header + '\n\n'.join(entries + [entry]) + footer).encode('utf-8')) > 12000:
                messages.append(header + '\n\n'.join(entries) + footer)
                entries = []
            entries.append(entry)
        if entries:
            messages.append(header + '\n\n'.join(entries) + footer)
        return messages

    def cancel(self, db, item):
        code = self.reminder_code(db, item['id'])
        details = f"\n编号：{code}\n事项：{item['title']}"
        if item['status'] == 'cancelled':
            return '这条提醒已经取消。' + details
        if item['status'] == 'done':
            return '这条提醒已经完成，没有待取消的提醒。' + details
        db.execute("UPDATE reminders SET status='cancelled',next_due=NULL WHERE id=?", (item['id'],))
        # Suppress both unsent confirmations and occurrences; keep sent receipts for future replies.
        db.execute("""UPDATE outbox SET state='cancelled' WHERE reminder_id=?
            AND kind IN ('ack','due') AND state IN ('pending','uncertain')""", (item['id'],))
        repeat = json.loads(item['rule'])['kind'] != 'once'
        return ('已取消后续所有提醒。' if repeat else '已取消提醒。') + details

    @staticmethod
    def queue_message(db, key, source, content, *, mode='reply', reminder_id=None, kind='ack', scheduled_at=None):
        db.execute('''INSERT OR IGNORE INTO outbox
            (id,reminder_id,kind,source,mode,content,scheduled_at) VALUES(?,?,?,?,?,?,?)''',
                   (key, reminder_id, kind, source, mode, content, scheduled_at))

    def process_inbox(self):
        with self.db() as db:
            pending = db.execute('SELECT id,event FROM inbox WHERE done=0 ORDER BY rowid LIMIT 20').fetchall()
        for row in pending:
            event = json.loads(row['event'])
            value = event['content'].strip()
            command = COMMAND.match(value)
            body = value[command.end():].strip() if command else value
            key = hashlib.sha256(row['id'].encode()).hexdigest()[:24]
            with self.db() as db:
                if command and not body:
                    for page, content in enumerate(self.list_messages(db)):
                        self.queue_message(db, f'list-{key}-{page}', row['id'], content, kind='list')
                    db.execute('UPDATE inbox SET done=1 WHERE id=?', (row['id'],))
                    continue
                if body == '取消' or (command and body.startswith('取消')):
                    match = re.fullmatch(r'取消\s+([Rr][0-9]{1,12})', body)
                    if match:
                        item = db.execute('''SELECT r.* FROM reminders r JOIN reminder_numbers n ON n.reminder_id=r.id
                            WHERE n.number=?''', (int(match[1][1:]),)).fetchone()
                        message = (self.cancel(db, item) if item else
                                   f'未找到编号 {match[1].upper()} 对应的提醒。发送 /remind 查看当前提醒。')
                    elif body == '取消':
                        item = self.reply_target(db, self.parent_message(event))
                        message = self.cancel(db, item) if item else None
                        if command and message is None:
                            message = '请回复设置确认或到点消息发送“取消”，或发送 /remind 取消 R012。发送 /remind 可查看编号。'
                    else:
                        message = '取消用法：/remind 取消 R012。发送 /remind 查看当前提醒和固定编号。'
                    if message:
                        self.queue_message(db, 'cancel-' + key, row['id'], message, kind='cancel')
                    db.execute('UPDATE inbox SET done=1 WHERE id=?', (row['id'],))
                    continue
            try:
                try:
                    timestamp = int(event['create_time']) / 1000
                    sent_at = dt.datetime.fromtimestamp(timestamp, self.tz)
                    if timestamp > time.time() + 300:
                        raise ValueError()
                except (KeyError, ValueError, OverflowError, OSError):
                    raise ParseError('消息时间无法确认，请重新发送这条 /remind。') from None
                spec = parse_reminder(body, sent_at)
                error = None
            except ParseError as exc:
                spec, error = None, str(exc)
            with self.db() as db:
                if spec:
                    self.add(db, row['id'], spec)
                else:
                    key = 'help-' + key
                    message = error if not body.strip() else '未设置提醒：' + error
                    self.queue_message(db, key, row['id'], message)
                db.execute('UPDATE inbox SET done=1 WHERE id=?', (row['id'],))

    def enqueue_due(self, now):
        with self.db() as db:
            pending = db.execute("SELECT * FROM reminders WHERE status='active' AND next_due<=? ORDER BY next_due LIMIT 20",
                                 (milliseconds(now),)).fetchall()
            for item in pending:
                scheduled = dt.datetime.fromtimestamp(item['next_due'] / 1000, self.tz)
                late = (now - scheduled).total_seconds() >= 60
                heading = '⏰ 补发提醒' if late else '⏰ 提醒时间到了'
                code = self.reminder_code(db, item['id'])
                content = (f"{heading}\n事项：{item['title']}\n原定时间：{format_time(scheduled)}（北京时间）"
                           f'\n编号：{code}\n取消：回复本消息发送“取消”，或发送 /remind 取消 {code}')
                key = hashlib.sha256(f"{item['id']}:{item['next_due']}".encode()).hexdigest()[:32]
                self.queue_message(db, 'due-' + key, item['source'], content, mode='send',
                                   reminder_id=item['id'], kind='due', scheduled_at=item['next_due'])

    def deliver(self, now):
        with self.db() as db:
            pending = db.execute("SELECT * FROM outbox WHERE state='pending' AND retry_at<=? ORDER BY rowid LIMIT 20",
                                 (now.timestamp(),)).fetchall()
        for job in pending:
            if self.stop.is_set():
                break
            # Receive cancellations queued while a previous API call was in flight.
            self.process_inbox()
            with self.db() as db:
                job = db.execute("SELECT * FROM outbox WHERE id=? AND state='pending'", (job['id'],)).fetchone()
                if job is None:
                    continue
                if job['kind'] == 'due':
                    reminder = db.execute('SELECT status FROM reminders WHERE id=?', (job['reminder_id'],)).fetchone()
                    if reminder is None or reminder['status'] != 'active':
                        continue
            clock = time.time()
            if job['first_attempt'] is not None and clock - job['first_attempt'] >= RETRY_WINDOW:
                with self.db() as db:
                    db.execute("UPDATE outbox SET state='uncertain',last_error='retry_window_expired' WHERE id=?", (job['id'],))
                    if job['kind'] == 'due':
                        db.execute("UPDATE reminders SET status='uncertain' WHERE id=?", (job['reminder_id'],))
                logging.error('delivery outcome uncertain; inspect receipts before manual recovery')
                continue
            try:
                self.check_identity()
                # Commit the first-attempt timestamp BEFORE the network request, including crash recovery.
                with self.db() as db:
                    db.execute('''UPDATE outbox SET attempts=attempts+1,
                        first_attempt=COALESCE(first_attempt,?) WHERE id=?''', (clock, job['id']))
                key = 'remind-' + hashlib.sha256(job['id'].encode()).hexdigest()[:40]
                target = (['+messages-reply', '--message-id', job['source']] if job['mode'] == 'reply'
                          else ['+messages-send', '--user-id', self.cfg['owner_open_id']])
                result = self.call('im', *target, '--as', 'bot', '--text', job['content'], '--idempotency-key', key)
                remote_id = result.get('message_id')
                if not isinstance(remote_id, str) or not remote_id.startswith('om_'):
                    raise DeliveryError('发送回执缺少message_id')
                with self.db() as db:
                    db.execute("UPDATE outbox SET state='sent',remote_id=?,last_error=NULL WHERE id=?", (remote_id, job['id']))
                    if job['kind'] == 'due':
                        item = db.execute('SELECT rule,next_due,status FROM reminders WHERE id=?', (job['reminder_id'],)).fetchone()
                        if item and item['status'] == 'active' and item['next_due'] == job['scheduled_at']:
                            next_due = next_occurrence(json.loads(item['rule']), dt.datetime.now(self.tz))
                            db.execute('UPDATE reminders SET next_due=?,status=? WHERE id=?',
                                       (milliseconds(next_due) if next_due else None, 'active' if next_due else 'done', job['reminder_id']))
                logging.info('message delivered kind=%s', job['kind'])
            except (DeliveryError, subprocess.TimeoutExpired, OSError) as exc:
                with self.db() as db:
                    retry_delay = min(300, 15 * 2 ** min(job['attempts'], 5))
                    db.execute('UPDATE outbox SET retry_at=?,last_error=? WHERE id=?',
                               (time.time() + retry_delay, type(exc).__name__, job['id']))
                logging.warning('delivery deferred exception=%s', type(exc).__name__)

    def tick(self):
        self.process_inbox()
        now = dt.datetime.now(self.tz)
        self.enqueue_due(now)
        self.deliver(now)

    def self_test(self):
        self.check_identity(remote=True)
        source = 'selftest-' + uuid.uuid4().hex
        spec = parse_reminder('30秒后 功能自检：/remind 定时提醒', dt.datetime.now(self.tz))
        with self.db() as db:
            reminder_id = self.add(db, source, spec, mode='send')
        return {'id': reminder_id, 'due': spec.due.isoformat(), 'status': 'queued',
                'note': '由已启动的服务发送一条自检确认及一条到点提醒'}


def listen(bot, stop):
    """A separate consumer shares lark-cli's local event bus with todo and draw."""
    while not stop.is_set():
        ready = threading.Event()
        try:
            child = subprocess.Popen(bot.argv('event', 'consume', 'im.message.receive_v1', '--as', 'bot', '--timeout', '24h'),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, bufsize=1, env=bot.env())
        except OSError:
            logging.error('listener process could not start')
            stop.wait(5)
            continue

        def diagnostics(proc, ready_marker):
            for line in proc.stderr:
                if '[event] ready event_key=im.message.receive_v1' in line:
                    ready_marker.set()
                    logging.info('remind listener ready')
                elif any(word in line for word in ('WARN', 'error', 'exited')):
                    logging.warning('remind listener connection diagnostic')

        diagnostics_thread = threading.Thread(target=diagnostics, args=(child, ready), daemon=True)
        diagnostics_thread.start()
        deadline = time.monotonic() + 45
        while not ready.is_set() and child.poll() is None and not stop.is_set() and time.monotonic() < deadline:
            ready.wait(0.2)
        if not ready.is_set():
            logging.error('remind listener startup failed')
        else:
            lines = queue.Queue()

            def read(proc, output):
                for line in proc.stdout:
                    output.put(line)
                output.put(None)

            threading.Thread(target=read, args=(child, lines), daemon=True).start()
            while not stop.is_set():
                try:
                    line = lines.get(timeout=1)
                    if line is None:
                        break
                    bot.accept(json.loads(line))
                except queue.Empty:
                    pass
                except Exception as exc:
                    logging.error('event rejected exception=%s', type(exc).__name__)
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logging.error('listener did not stop after SIGTERM')
            # Service KillMode=control-group and TimeoutStopSec handle stuck subprocesses.
            stop.set()
        diagnostics_thread.join(timeout=1)
        stop.wait(5)


def run(bot):
    with (bot.state_dir / 'runtime.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeliveryError('已有提醒服务正在使用这个状态库') from None
        bot.check_identity(remote=True)
        stop = bot.stop
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        listener = threading.Thread(target=listen, args=(bot, stop), daemon=True)
        listener.start()
        logging.info('remind scheduler started; interval_seconds=1')
        try:
            while not stop.is_set():
                bot.tick()
                stop.wait(1)
        finally:
            stop.set()
            listener.join(timeout=12)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.json')))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--check', action='store_true', help='Verify identity and local state; no messages')
    modes.add_argument('--parse', metavar='EXPRESSION', help='Preview a rule without scheduling or sending')
    modes.add_argument('--self-test', action='store_true', help='Queue a labeled 30-second test to the configured owner')
    args = parser.parse_args()
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    try:
        if args.parse is not None:
            print(confirmation(parse_reminder(args.parse, dt.datetime.now(ZoneInfo('Asia/Shanghai')))))
            return 0
        config = json.loads(Path(args.config).read_text(encoding='utf-8'))
        bot = Bot(config)
        if args.check:
            bot.check_identity(remote=True)
            print(json.dumps({'status': 'ok', 'app_id': config['app_id'], 'timezone': config['timezone']}, ensure_ascii=False))
        elif args.self_test:
            print(json.dumps(bot.self_test(), ensure_ascii=False))
        else:
            run(bot)
    except Exception as exc:
        print(str(exc) if isinstance(exc, (ValueError, DeliveryError)) else type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
