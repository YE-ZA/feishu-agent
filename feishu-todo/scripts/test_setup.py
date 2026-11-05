import importlib.util
import json
from pathlib import Path
import plistlib
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import bot

spec = importlib.util.spec_from_file_location('todo_setup', Path(__file__).with_name('setup.py'))
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class PortableSetupTests(unittest.TestCase):
    def setUp(self):
        names = ['CLI', 'OWNER', 'DOC', 'URL', 'APP_ID', 'PROFILE', 'TITLE', 'DOCUMENT_TITLE', 'CONFIG_PATH', 'BASE', 'TZ']
        self.originals = {n: getattr(bot, n) for n in names}
        self.addCleanup(lambda: [setattr(bot, k, v) for k, v in self.originals.items()])

    def config(self, root):
        path = root / 'path with spaces' / 'config.json'
        path.parent.mkdir()
        path.write_text(json.dumps(dict(schema_version=1, instance='test', cli_path=sys.executable,
                                       profile='isolated', app_id='cli_test', owner_open_id='ou_test',
                                       document_id='doc_test', document_url='https://tenant.example/docx/doc_test',
                                       state_dir=str(root / 'state'), timezone='Asia/Shanghai')))
        return path

    def test_all_service_definitions_preserve_separate_arguments_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.config(root)
            for kind in ('systemd', 'launchd', 'windows'):
                output = root / kind
                with patch('builtins.print'):
                    setup.service(SimpleNamespace(config=config, output_dir=output, kind=kind))
            service = (root / 'systemd/feishu-todo-reminders-test.service').read_text()
            self.assertIn('path with spaces', service)
            self.assertIn('--config', service)
            with (root / 'launchd/local.feishu-todo-reminders-test.plist').open('rb') as f:
                plist = plistlib.load(f)
            self.assertEqual(plist['ProgramArguments'][-1], str(config))
            task = ET.parse(root / 'windows/feishu-todo-reminders-test.xml')
            ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
            self.assertEqual(task.find('.//t:Command', ns).text, str(Path(sys.executable).resolve()))
            self.assertIn('"', task.find('.//t:Arguments', ns).text)

    def test_import_refuses_different_account_and_preserves_existing_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.config(root)
            source = root / 'old.sqlite3'
            c = sqlite3.connect(source)
            c.execute('CREATE TABLE messages (id TEXT PRIMARY KEY, state TEXT, payload TEXT, reply TEXT, replied INTEGER DEFAULT 0)')
            c.execute("INSERT INTO messages VALUES('om_legacy','done','null','ok',1)")
            c.commit()
            c.close()
            args = SimpleNamespace(config=config, source=source, source_app_id='cli_test',
                                   source_owner_open_id='ou_wrong', source_document_id='doc_test')
            with self.assertRaises(ValueError):
                setup.import_state(args)
            self.assertFalse((root / 'state/state.sqlite3').exists())
            args.source_owner_open_id = 'ou_test'
            with patch('builtins.print'):
                setup.import_state(args)
            bot.configure(config)
            instance = bot.Bot()
            self.assertEqual(instance.db.execute('SELECT id FROM messages').fetchone()[0], 'om_legacy')
            instance.db.close()


if __name__ == '__main__':
    unittest.main()
