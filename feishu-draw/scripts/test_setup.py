import argparse
import contextlib
import io
import json
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch
import setup


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.runtime = self.base / 'runtime with spaces'
        self.sharp = self.base / 'sharp'
        self.sharp.mkdir()
        self.args = argparse.Namespace(runtime_dir=str(self.runtime), instance='personal',
                                       cli='lark-cli', codex='codex', node='node',
                                       doc='https://example.feishu.cn/wiki/node#block', profile='example',
                                       sharp_module=str(self.sharp), timezone='Asia/Shanghai',
                                       model=None, reasoning_effort='high')
        self.calls = []

    def fake_run(self, argv):
        self.calls.append(argv)
        if 'auth' in argv:
            return json.dumps(dict(appId='cli_example', identities=dict(
                user=dict(openId='ou_example', available=True, verified=True),
                bot=dict(available=True, verified=True))))
        if '+fetch' in argv:
            return json.dumps(dict(ok=True, data=dict(document=dict(document_id='doc_actual'))))
        if 'status' in argv:
            return 'Logged in'
        Path(argv[-1]).write_bytes(b'nonempty-rendered-image')
        return ''

    def configure(self):
        with patch.object(setup, 'binary', side_effect=lambda value: '/fake/' + value), \
                patch.object(setup, 'run', side_effect=self.fake_run), contextlib.redirect_stdout(io.StringIO()):
            setup.configure(self.args)

    def test_config_uses_verified_identity_and_real_document_without_remote_writes(self):
        self.configure()
        config = json.loads((self.runtime / 'config.json').read_text())
        self.assertEqual(config['app_id'], 'cli_example')
        self.assertEqual(config['owner_open_id'], 'ou_example')
        self.assertEqual(config['archive_document_id'], 'doc_actual')
        self.assertEqual(config['archive_document_url'], 'https://example.feishu.cn/wiki/node')
        self.assertEqual(config['state_dir'], str(self.runtime / 'state'))
        self.assertNotIn('model', config)
        self.assertEqual({p.name for p in self.runtime.iterdir()}, set(setup.RUNTIME_FILES) | {'config.json'})
        remote = [argv for argv in self.calls if argv[0].endswith('lark-cli')]
        self.assertEqual(len(remote), 2)
        self.assertIn('--verify', remote[0])
        self.assertIn('+fetch', remote[1])

    def test_existing_runtime_cannot_be_overwritten_or_rebound(self):
        self.configure()
        before = (self.runtime / 'config.json').read_bytes()
        with patch.object(setup, 'run') as run:
            with self.assertRaises(ValueError):
                setup.configure(self.args)
            run.assert_not_called()
        self.assertEqual((self.runtime / 'config.json').read_bytes(), before)

    def test_failed_dependency_check_leaves_no_runtime(self):
        with patch.object(setup, 'binary', side_effect=lambda value: '/fake/' + value), \
                patch.object(setup, 'run', side_effect=ValueError('not authenticated')):
            with self.assertRaises(ValueError):
                setup.configure(self.args)
        self.assertFalse(self.runtime.exists())

    def test_runtime_inside_skill_is_rejected_before_any_check(self):
        self.args.runtime_dir = str(setup.HERE.parent / 'private-runtime')
        with patch.object(setup, 'run') as run:
            with self.assertRaises(ValueError):
                setup.configure(self.args)
            run.assert_not_called()

    def test_service_generation_preserves_paths_and_does_not_install(self):
        self.configure()
        config = self.runtime / 'config.json'
        args = argparse.Namespace(config=str(config), kind='launchd', output_dir=None)
        with patch.object(setup, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            setup.service(args)
            path = self.runtime / 'service' / 'local.feishu-draw-personal.plist'
            service = plistlib.loads(path.read_bytes())
            self.assertEqual(service['ProgramArguments'], [str(Path(sys.executable).resolve()),
                             str(self.runtime / 'draw_bot.py'), '--config', str(config)])
            args.kind = 'systemd'
            setup.service(args)
            text = (self.runtime / 'service' / 'feishu-draw-personal.service').read_text()
            self.assertIn('WorkingDirectory=' + setup.systemd_quote(str(self.runtime)), text)
            self.assertIn('KillMode=control-group', text)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
