import argparse
import contextlib
import fcntl
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import datetime as dt
from zoneinfo import ZoneInfo

import setup
from remind_bot import Bot
from time_rules import parse_reminder


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def args(self, **changes):
        values = dict(cli='/usr/bin/true', profile='test-profile', instance='personal', runtime_dir=str(self.root / 'runtime'))
        values.update(changes)
        return argparse.Namespace(**values)

    def verified(self):
        return argparse.Namespace(returncode=0, stdout=json.dumps({
            'appId': 'cli_test', 'secret': 'MUST_NOT_BE_COPIED', 'identities': {
                'user': {'verified': True, 'openId': 'ou_owner'}, 'bot': {'verified': True}}}))

    def configure(self, **changes):
        with patch.object(setup.subprocess, 'run', return_value=self.verified()):
            result = setup.configure(self.args(**changes))
        return Path(result['runtime']), Path(result['config'])

    def source_state(self):
        runtime, config_path = self.configure(runtime_dir=str(self.root / 'source'))
        bot = Bot(setup.read_config(config_path))
        now = dt.datetime.now(ZoneInfo('Asia/Shanghai'))
        with bot.db() as db:
            first = bot.add(db, 'om_first', parse_reminder('1小时后 检查', now))
            bot.add(db, 'om_second', parse_reminder('每天晚上10点 备份', now))
            db.execute("UPDATE outbox SET state='sent',remote_id='om_old_receipt' WHERE reminder_id=?", (first,))
            db.execute("UPDATE reminders SET status='done',next_due=NULL WHERE id=?", (first,))
        return runtime, config_path, bot

    def test_configure_copies_only_runtime_and_verified_binding(self):
        args = self.args()
        with patch.object(setup.subprocess, 'run', return_value=self.verified()) as run:
            result = setup.configure(args)
        runtime = Path(result['runtime'])
        self.assertEqual({p.name for p in runtime.iterdir()}, {'config.json', *setup.RUNTIME_FILES})
        config = setup.read_config(runtime / 'config.json')
        self.assertEqual(config['owner_open_id'], 'ou_owner')
        self.assertEqual(config['profile'], 'test-profile')
        self.assertNotIn('MUST_NOT_BE_COPIED', (runtime / 'config.json').read_text())
        self.assertEqual((runtime / 'config.json').stat().st_mode & 0o777, 0o600)
        self.assertIn('--verify', run.call_args.args[0])
        self.assertFalse((runtime / 'state/state.sqlite3').exists())
        for name in setup.RUNTIME_FILES:
            self.assertEqual((runtime / name).read_bytes(), (Path(setup.__file__).parent / name).read_bytes())

    def test_configure_rejects_existing_instance(self):
        runtime, config = self.configure()
        original = config.read_bytes()
        with patch.object(setup.subprocess, 'run', return_value=self.verified()), self.assertRaises(ValueError):
            setup.configure(self.args())
        self.assertEqual(config.read_bytes(), original)

    def test_configure_rejects_unverified_identity_before_writes(self):
        result = self.verified()
        result.stdout = result.stdout.replace('true', 'false')
        with patch.object(setup.subprocess, 'run', return_value=result), self.assertRaises(ValueError):
            setup.configure(self.args())
        self.assertFalse((self.root / 'runtime').exists())

    def test_configure_does_not_put_personal_data_inside_skill(self):
        runtime = setup.SKILL_DIR / 'runtime-must-not-be-created'
        with patch.object(setup.subprocess, 'run', return_value=self.verified()), self.assertRaises(ValueError):
            setup.configure(self.args(runtime_dir=str(runtime)))
        self.assertFalse(runtime.exists())

    def test_bad_instance_rejected_without_network(self):
        with patch.object(setup.subprocess, 'run') as run, self.assertRaises(ValueError):
            setup.configure(self.args(instance='../bad'))
        run.assert_not_called()

    def test_service_generation_is_local_and_does_not_initialize_state(self):
        runtime, config = self.configure(runtime_dir=str(self.root / 'runtime with $dollar %percent'))
        args = argparse.Namespace(config=str(config), name='feishu-remind-original', output_dir=None)
        with patch.object(setup.subprocess, 'run') as run:
            result = setup.service(args)
        run.assert_not_called()
        unit = Path(result['service_file']).read_text()
        self.assertIn('KillMode=control-group', unit)
        self.assertIn('TimeoutStopSec=65', unit)
        self.assertIn('WorkingDirectory=' + str(runtime).replace('%', '%%') + '\n', unit)
        self.assertIn('$$dollar', unit)
        self.assertFalse((runtime / 'state/state.sqlite3').exists())

    def test_service_rejects_unsafe_name(self):
        runtime, config = self.configure()
        with self.assertRaises(ValueError):
            setup.service(argparse.Namespace(config=str(config), name='../../todo', output_dir=None))

    def test_service_path_newlines_rejected(self):
        with self.assertRaises(ValueError):
            setup.quote_systemd('/tmp/unsafe\nExecStart=/bin/false')

    @unittest.skipUnless(shutil.which('systemd-analyze'), 'systemd tooling unavailable')
    def test_generated_unit_is_accepted_by_systemd(self):
        runtime, config = self.configure(runtime_dir=str(self.root / 'runtime with $dollar %percent'))
        result = setup.service(argparse.Namespace(config=str(config), name='feishu-remind-validation', output_dir=None))
        proc = subprocess.run(['systemd-analyze', 'verify', result['service_file']], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_backup_and_import_preserve_numbers_receipts_and_next_sequence(self):
        _, source_config, original = self.source_state()
        backup = self.root / 'snapshot.sqlite3'
        setup.backup_state(argparse.Namespace(config=str(source_config), output=str(backup)))
        _, new_config = self.configure(runtime_dir=str(self.root / 'destination'))
        setup.import_state(argparse.Namespace(config=str(new_config), source=str(backup)))
        restored = Bot(setup.read_config(new_config))
        with original.db() as src, restored.db() as dest:
            for table in ('reminders', 'outbox', 'reminder_numbers'):
                self.assertEqual([dict(row) for row in src.execute('SELECT * FROM ' + table)],
                                 [dict(row) for row in dest.execute('SELECT * FROM ' + table)])
            third = restored.add(dest, 'om_third', parse_reminder('1小时后 检查', dt.datetime.now(restored.tz)))
            self.assertEqual(restored.reminder_code(dest, third), 'R003')
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_import_different_owner_rejected_without_creating_database(self):
        _, source_config, original = self.source_state()
        runtime, new_config = self.configure(runtime_dir=str(self.root / 'destination'))
        cfg = setup.read_config(new_config)
        cfg['owner_open_id'] = 'ou_other'
        new_config.write_text(json.dumps(cfg))
        with self.assertRaises(ValueError):
            setup.import_state(argparse.Namespace(config=str(new_config), source=str(original.db_path)))
        self.assertFalse((runtime / 'state/state.sqlite3').exists())

    def test_import_refuses_existing_state(self):
        _, source_config, original = self.source_state()
        runtime, new_config = self.configure(runtime_dir=str(self.root / 'destination'))
        existing = Bot(setup.read_config(new_config))
        with self.assertRaises(ValueError):
            setup.import_state(argparse.Namespace(config=str(new_config), source=str(original.db_path)))
        with existing.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reminders').fetchone()[0], 0)

    def test_import_refuses_running_service_lock(self):
        _, _, original = self.source_state()
        runtime, new_config = self.configure(runtime_dir=str(self.root / 'destination'))
        state = runtime / 'state'
        state.mkdir()
        with (state / 'runtime.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(ValueError):
                setup.import_state(argparse.Namespace(config=str(new_config), source=str(original.db_path)))
        self.assertFalse((state / 'state.sqlite3').exists())

    def test_existing_backup_is_never_overwritten(self):
        _, config_path, _ = self.source_state()
        backup = self.root / 'existing.sqlite3'
        backup.write_bytes(b'preserve this file')
        with self.assertRaises(ValueError):
            setup.backup_state(argparse.Namespace(config=str(config_path), output=str(backup)))
        self.assertEqual(backup.read_bytes(), b'preserve this file')

    def test_unbound_database_rejected(self):
        runtime, config = self.configure()
        source = self.root / 'unbound.sqlite3'
        with contextlib.closing(sqlite3.connect(source)) as db:
            db.execute('CREATE TABLE unknown (id INTEGER)')
        with self.assertRaises(ValueError):
            setup.copy_state(setup.read_config(config), source, self.root / 'copy.sqlite3')
        self.assertFalse((self.root / 'copy.sqlite3').exists())

    def test_online_backup_includes_committed_wal_data(self):
        _, config, original = self.source_state()
        snapshot = self.root / 'online.sqlite3'
        with contextlib.closing(sqlite3.connect(original.db_path)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute("UPDATE reminders SET title='最新已提交记录'")
            writer.commit()
            self.assertTrue(Path(str(original.db_path) + '-wal').exists())
            setup.copy_state(setup.read_config(config), original.db_path, snapshot)
        with contextlib.closing(sqlite3.connect(snapshot)) as db:
            self.assertEqual(db.execute('SELECT DISTINCT title FROM reminders').fetchall(), [('最新已提交记录',)])


if __name__ == '__main__':
    unittest.main()
