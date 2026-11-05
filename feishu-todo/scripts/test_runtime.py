import datetime as dt
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import bot


def document(body):
    return ET.fromstring('<root><title id="doc">待办</title>' + body + '<h1 id="weekly">周报草稿区</h1><p>尚未生成周报。</p></root>')


class TodoBotTests(unittest.TestCase):
    def setUp(self):
        self.globals = patch.multiple(bot, OWNER='ou_test', DOC='doc_test', APP_ID='cli_test', PROFILE='test-profile',
                                      URL='https://tenant.example/docx/doc_test', CONFIG_PATH=None)
        self.globals.start()
        self.addCleanup(self.globals.stop)

    def test_configuration_pins_profile_and_loads_local_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = dict(schema_version=1, cli_path=sys.executable, profile='new-profile', app_id='cli_test',
                          owner_open_id='ou_test', document_id='doc_test', document_url='https://tenant.example/docx/doc_test',
                          state_dir=str(Path(tmp) / 'state'), timezone='Asia/Shanghai')
            path = Path(tmp) / 'config.json'
            path.write_text(json.dumps(config))
            with patch.multiple(bot, CLI=bot.CLI, BASE=bot.BASE, TZ=bot.TZ, TITLE=bot.TITLE, DOCUMENT_TITLE=bot.DOCUMENT_TITLE):
                bot.configure(path)
                self.assertEqual(bot.cli_argv('docs', '+fetch')[:3], [str(Path(sys.executable).resolve()), '--profile', 'new-profile'])
                self.assertEqual(bot.BASE, Path(tmp) / 'state')

    def test_wrong_account_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.sqlite3'
            first = bot.Bot(path)
            first.db.close()
            with patch.object(bot, 'OWNER', 'ou_another_account'):
                with self.assertRaisesRegex(RuntimeError, 'another app/account/document'):
                    bot.Bot(path)

    def test_identity_change_is_rejected_without_using_new_recipient(self):
        status = dict(appId='cli_test', identities=dict(user=dict(openId='ou_someone_else', available=True, verified=True),
                                                       bot=dict(available=True, verified=True)))
        response = type('Response', (), dict(returncode=0, stdout=json.dumps(status)))()
        with patch.object(bot.subprocess, 'run', return_value=response):
            with self.assertRaises(RuntimeError):
                bot.verify_identity()

    def test_schedule_deduplicates_and_manual_render_does_not_consume_it(self):
        now = dt.datetime(2026, 11, 5, 10, tzinfo=bot.TZ)
        with tempfile.TemporaryDirectory() as tmp, patch.object(bot, 'BASE', Path(tmp)), patch.object(bot.dt, 'datetime') as clock:
            clock.now.return_value = now
            with patch.object(bot, 'fetch', return_value=(document(''), 1)), patch.object(bot, 'call', return_value={'message_id': 'om_success'}) as send:
                bot.render_reminder(document(''))
                self.assertEqual(bot.send_scheduled()['status'], 'sent')
                self.assertEqual(bot.send_scheduled()['status'], 'already_sent')
                self.assertEqual(send.call_count, 1)

    def test_ambiguous_scheduled_send_is_not_replayed(self):
        now = dt.datetime(2026, 11, 5, 10, tzinfo=bot.TZ)
        with tempfile.TemporaryDirectory() as tmp, patch.object(bot, 'BASE', Path(tmp)), patch.object(bot.dt, 'datetime') as clock:
            clock.now.return_value = now
            with patch.object(bot, 'fetch', return_value=(document(''), 1)), patch.object(bot, 'call', side_effect=RuntimeError('timeout')) as send:
                with self.assertRaises(RuntimeError):
                    bot.send_scheduled()
                with self.assertRaises(RuntimeError):
                    bot.send_scheduled()
                self.assertEqual(send.call_count, 1)

    def test_schedule_never_sends_on_weekend(self):
        now = dt.datetime(2026, 11, 7, 10, tzinfo=bot.TZ)
        with patch.object(bot.dt, 'datetime') as clock, patch.object(bot, 'call') as send:
            clock.now.return_value = now
            self.assertEqual(bot.send_scheduled()['status'], 'skipped_weekend')
            send.assert_not_called()

    def test_date_boundary_uses_message_time_in_shanghai(self):
        value = int(dt.datetime(2026, 11, 4, 16, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
        self.assertEqual(bot.date_for({'create_time': str(value)}), '2026-11-05')

    def test_first_item_is_atomic_heading_and_native_checkbox_and_escapes_xml(self):
        anchor, content = bot.insertion(document(''), '2026-11-04', '<今天> & 明天')
        self.assertEqual(anchor, 'doc')
        nodes = ET.fromstring('<r>' + content + '</r>')
        self.assertEqual([n.tag for n in nodes], ['h1', 'checkbox'])
        self.assertEqual(nodes[1].text, '<今天> & 明天')

    def test_reuse_date_stays_outside_weekly_report(self):
        root = document('<h1 id="date">2026-11-04</h1><checkbox id="a" done="false">一</checkbox>')
        anchor, content = bot.insertion(root, '2026-11-04', '二')
        self.assertEqual(anchor, 'a')
        self.assertNotIn('<h1>', content)

    def test_only_checkbox_state_controls_completion(self):
        root = document('<h1>2026-11-04</h1><checkbox id="a" done="false">待办</checkbox><checkbox id="b" done="true">已做</checkbox><checkbox id="c" done="false">已取消 · 不做</checkbox>')
        root.append(ET.fromstring('<checkbox done="false">周报示例</checkbox>'))
        self.assertEqual([bot.text(n) for _, n in bot.tasks(root) if bot.is_open(n)], ['待办', '已取消 · 不做'])

    def test_commands(self):
        self.assertEqual(bot.parse_command('待办：写周报'), ('ignore', ''))
        self.assertEqual(bot.parse_command('待办: 写周报'), ('ignore', ''))
        self.assertEqual(bot.parse_command('/todo 写周报'), ('add', '写周报'))
        self.assertEqual(bot.parse_command('写周报'), ('ignore', ''))
        self.assertEqual(bot.parse_command('添加待办：写周报'), ('ignore', ''))
        self.assertEqual(bot.parse_command('完成：写周报'), ('ignore', ''))
        self.assertEqual(bot.parse_command('/todo 完成：写周报'), ('add', '完成：写周报'))
        self.assertEqual(bot.parse_command('/todo 取消：写周报'), ('add', '取消：写周报'))
        self.assertEqual(bot.parse_command('/todo 查看待办'), ('add', '查看待办'))
        self.assertEqual(bot.parse_command('/todo'), ('list', ''))
        self.assertEqual(bot.parse_command('/todo   '), ('list', ''))
        self.assertEqual(bot.parse_command('/todo:写周报'), ('ignore', ''))
        self.assertEqual(bot.parse_command('/exit'), ('ignore', ''))
        self.assertEqual(bot.parse_command('/plan'), ('ignore', ''))
        self.assertEqual(bot.parse_command('/todos 写周报'), ('ignore', ''))

    def test_no_mode_can_capture_later_messages_or_other_features(self):
        with tempfile.TemporaryDirectory() as temp:
            db = temp + '/db'
            service = bot.Bot(db)

            def event(mid, content, chat='oc_self', timestamp='1000'):
                return dict(message_id=mid, content=content, chat_id=chat, create_time=timestamp,
                            sender_id=bot.OWNER, sender_type='user', chat_type='p2p', message_type='text')

            with patch.object(bot, 'call', return_value={}), patch.object(bot, 'fetch') as fetch, patch.object(bot, 'patch') as write:
                service.handle(event('om_normal', '普通聊天'))
                service.db.close()
                service = bot.Bot(db)
                service.handle(event('om_foreign', '另一会话的聊天', chat='oc_other'))
                service.handle(event('om_old', '延迟送达的旧聊天', timestamp='999'))
                service.handle(event('om_plan', '/plan', timestamp='1001'))
                service.handle(event('om_after', '退出后聊天', timestamp='1002'))
                fetch.assert_not_called()
                write.assert_not_called()

    def test_each_add_requires_its_own_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            service = bot.Bot(temp + '/db')
            empty = document('')
            added = document('<h1 id="date">2026-11-05</h1><checkbox id="new" done="false">写周报</checkbox>')
            def event(mid, content):
                return dict(message_id=mid, content=content, chat_id='oc_self', create_time='1793846400000',
                            sender_id=bot.OWNER, sender_type='user', chat_type='p2p', message_type='text')
            with patch.object(bot, 'call', return_value={}), patch.object(bot, 'fetch', side_effect=[(empty, 1), (added, 2)]) as fetch, patch.object(bot, 'patch', return_value={}) as write:
                service.handle(event('om_before', '不要记录这句'))
                service.handle(event('om_add', '/todo 写周报'))
                self.assertEqual(write.call_count, 1)
                self.assertIn('<checkbox', write.call_args.kwargs['content'])
                self.assertNotIn('/todo', write.call_args.kwargs['content'])
                service.handle(event('om_after', '下一句普通聊天不要记录'))
                self.assertEqual(fetch.call_count, 2)
            with patch.object(bot, 'call', return_value={}), patch.object(bot, 'fetch', side_effect=[(empty, 1), (added, 2)]), patch.object(bot, 'patch', return_value={}) as write:
                service.handle(event('om_one', '待办：写周报'))
                write.assert_not_called()

    def test_sender_and_duplicate_protection(self):
        with tempfile.TemporaryDirectory() as temp:
            service = bot.Bot(temp + '/db')
            event = dict(message_id='om_test', sender_id='someone_else', sender_type='user', chat_type='p2p', message_type='text', content='/todo')
            with patch.object(bot, 'call') as call:
                service.handle(event)
                call.assert_not_called()
            event['sender_id'] = bot.OWNER
            with patch.object(bot, 'call', return_value={}) as call, patch.object(bot, 'fetch', return_value=(document(''), 1)):
                service.handle(event)
                service.handle(event)
                self.assertEqual(call.call_count, 1)

    def test_bare_command_sends_shared_reminder_without_writes(self):
        root = document('<h1 id="day">2026-11-05</h1><checkbox id="open" done="false">写周报</checkbox><checkbox id="done" done="true">已做</checkbox><checkbox id="cancel" done="false">已取消 · 不做</checkbox>')
        with tempfile.TemporaryDirectory() as temp:
            service = bot.Bot(temp + '/db')
            event = dict(message_id='om_manual', sender_id=bot.OWNER, sender_type='user', chat_type='p2p', message_type='text', content='/todo')
            with patch.object(bot, 'fetch', return_value=(root, 1)), patch.object(bot, 'patch') as write, patch.object(service, 'respond') as reply:
                service.handle(event)
                self.assertEqual(reply.call_args.args[1], bot.render_reminder(root))
                body = json.dumps(reply.call_args.args[1], ensure_ascii=False)
                self.assertIn('写周报', body)
                self.assertNotIn('已做', body)
                self.assertIn('已取消 · 不做', body)
                write.assert_not_called()

    def test_empty_shared_reminder_is_explicit(self):
        body = json.dumps(bot.render_reminder(document('')), ensure_ascii=False)
        self.assertNotIn('2026-11-05', body)
        self.assertIn('暂无未完成待办', body)
        self.assertIn(bot.URL, body)

    def test_reminder_is_native_post_with_no_dates_and_document_order(self):
        root = document('<h1>2026-11-05</h1><checkbox done="false">二</checkbox><checkbox done="true">已做</checkbox><h1>2026-11-04</h1><checkbox done="false">一</checkbox>')
        body = bot.render_reminder(root)['zh_cn']
        self.assertEqual(body['title'], '今日待办提醒⏰')
        self.assertEqual([r[0]['text'] for r in body['content'][:-2]], ['☐ 二', '☐ 一'])
        self.assertEqual(body['content'][-2], [{'tag': 'text', 'text': '\n'}])
        self.assertEqual(body['content'][-1][0], {'tag': 'text', 'text': '文档：'})
        self.assertNotIn('2026-', json.dumps(body))

    def test_saved_reminder_retry_preserves_rich_text(self):
        with tempfile.TemporaryDirectory() as temp:
            service = bot.Bot(temp + '/db')
            rich = bot.render_reminder(document(''))
            service.save('om_retry', 'done', reply=rich)
            event = dict(message_id='om_retry', sender_id=bot.OWNER, sender_type='user', chat_type='p2p')
            with patch.object(bot, 'call', return_value={}) as call:
                service.handle(event)
                argv = call.call_args.args
                self.assertEqual(argv[argv.index('--msg-type')+1], 'post')
                self.assertEqual(json.loads(argv[argv.index('--content')+1]), rich)

    def test_ambiguous_write_is_reconciled_without_replaying(self):
        with tempfile.TemporaryDirectory() as temp:
            service = bot.Bot(temp + '/db')
            payload = dict(action='add', value='写周报', date='2026-11-04', before=['old'])
            service.save('om_test', 'pending', payload)
            root = document('<h1>2026-11-04</h1><checkbox id="old" done="false">写周报</checkbox><checkbox id="new" done="false">写周报</checkbox>')
            with patch.object(bot, 'fetch', return_value=(root, 1)), patch.object(bot, 'patch') as write, patch.object(bot, 'call', return_value={}) as call:
                service.handle(dict(message_id='om_test', sender_id=bot.OWNER, sender_type='user', chat_type='p2p'))
                write.assert_not_called()
                self.assertIn('已添加', call.call_args.args[call.call_args.args.index('--text')+1])


if __name__ == '__main__':
    unittest.main()
