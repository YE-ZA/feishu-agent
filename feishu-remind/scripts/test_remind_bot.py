import datetime as dt
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from remind_bot import Bot, DeliveryError, RETRY_WINDOW, milliseconds
from time_rules import ParseError, confirmation, next_occurrence, number, parse_reminder


TZ = ZoneInfo('Asia/Shanghai')
BASE = dt.datetime(2026, 11, 5, 14, 0, tzinfo=TZ)  # Thursday


class RuleTests(unittest.TestCase):
    def test_relative_durations(self):
        for expression, seconds in [('30分钟后', 1800), ('半小时后', 1800), ('两小时后', 7200),
                                    ('1小时30分钟后', 5400), ('1天2小时3分钟4秒后', 93784), ('10秒钟后', 10)]:
            with self.subTest(expression=expression):
                spec = parse_reminder(expression + ' 检查训练结果', BASE)
                self.assertEqual(spec.due, BASE + dt.timedelta(seconds=seconds))
                self.assertEqual(spec.rule, {'kind': 'once'})

    def test_absolute_dates_and_chinese_clock(self):
        for expression, expected in [
                ('明天下午三点', (2026, 11, 6, 15, 0)),
                ('后天晚上八点半', (2026, 11, 7, 20, 30)),
                ('大后天早上九点一刻', (2026, 11, 8, 9, 15)),
                ('下周一上午10点', (2026, 11, 9, 10, 0)),
                ('周五17:30', (2026, 11, 6, 17, 30)),
                ('2027-01-02 08:00', (2027, 1, 2, 8, 0)),
                ('十二月一日上午十点三十分', (2026, 12, 1, 10, 30)),
                ('2027年1月2号凌晨0点', (2027, 1, 2, 0, 0)),
                ('今天１５：３０', (2026, 11, 5, 15, 30))]:
            with self.subTest(expression=expression):
                spec = parse_reminder(expression + ' 检查设备', BASE)
                self.assertEqual(spec.due, dt.datetime(*expected, tzinfo=TZ))

    def test_title_is_not_normalized_or_interpreted(self):
        title = '检查 ２号设备：每周日志\n$(touch /tmp/should-not-exist) `echo secret`'
        spec = parse_reminder('明天15:00 ' + title, BASE)
        self.assertEqual(spec.title, title)

    def test_daily_and_weekly(self):
        daily = parse_reminder('每天晚上10点 备份代码', BASE)
        self.assertEqual(daily.due, BASE.replace(hour=22))
        self.assertEqual(next_occurrence(daily.rule, daily.due), daily.due + dt.timedelta(days=1))
        weekly = parse_reminder('每周五下午5点 整理周报', BASE)
        self.assertEqual(weekly.due, dt.datetime(2026, 11, 6, 17, tzinfo=TZ))
        self.assertEqual(next_occurrence(weekly.rule, weekly.due), weekly.due + dt.timedelta(days=7))

    def test_weekdays_skip_weekend_and_explain_holidays(self):
        friday = dt.datetime(2026, 11, 6, 20, tzinfo=TZ)
        for prefix in ('工作日', '每个工作日', '周一到周五', '每周一至周五'):
            spec = parse_reminder(prefix + '上午9点 检查设备', friday)
            self.assertEqual(spec.due, dt.datetime(2026, 11, 9, 9, tzinfo=TZ))
            self.assertIn('不按法定节假日或调休调整', confirmation(spec))

    def test_monthly_skips_nonexistent_dates(self):
        base = dt.datetime(2026, 1, 31, 20, tzinfo=TZ)
        spec = parse_reminder('每月31日18:00 检查账单', base)
        self.assertEqual(spec.due, dt.datetime(2026, 3, 31, 18, tzinfo=TZ))
        self.assertIn('无此日期时跳过', confirmation(spec))

    def test_year_boundary_and_leap_date(self):
        dec = dt.datetime(2026, 12, 31, 20, tzinfo=TZ)
        self.assertEqual(parse_reminder('明天08:00 开工', dec).due.year, 2027)
        self.assertEqual(parse_reminder('2028-02-29 08:00 检查', BASE).due.day, 29)

    def test_invalid_and_ambiguous_inputs_are_rejected(self):
        for body in ('', 'list', '取消', '明天下午 检查', '明天8点 检查', '明天晚上12点 检查',
                     '今天13:00 检查', '本周一15:00 检查', '2026-02-30 15:00 检查',
                     '每月32日15:00 检查', '明天25:00 检查', '明天15:60 检查',
                     '0分钟后 检查', '1小时1小时后 检查', '1分钟1小时后 检查',
                     '明天15:00', '明天15:00检查', '明天早上13点 检查',
                     '每隔两天晚上8点 检查', '每天下午3点和5点 检查', '明天15:00:30 检查'):
            with self.subTest(body=body), self.assertRaises(ParseError):
                parse_reminder(body, BASE)

    def test_chinese_numbers(self):
        for value, expected in [('两', 2), ('十', 10), ('十二', 12), ('二十三', 23), ('一百零二', 102), ('两千', 2000)]:
            self.assertEqual(number(value), expected)
        for value in ('一二十', '百十', '一百一', '十十', '二三'):
            with self.subTest(value=value), self.assertRaises(ParseError):
                number(value)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = {'schema_version': 1, 'cli_path': '/usr/bin/true', 'profile': 'test-profile',
                       'app_id': 'cli_test', 'owner_open_id': 'ou_owner',
                       'timezone': 'Asia/Shanghai', 'state_dir': self.temp.name}
        self.bot = Bot(self.config)

    def tearDown(self):
        self.temp.cleanup()

    def event(self, content='/remind 30分钟后 检查训练结果', **changes):
        result = {'message_id': 'om_test', 'sender_id': 'ou_owner', 'sender_type': 'user',
                  'chat_type': 'p2p', 'message_type': 'text', 'content': content,
                  'create_time': str(milliseconds(dt.datetime.now(TZ)))}
        result.update(changes)
        return result

    def rows(self, table):
        with self.bot.db() as db:
            return db.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall()

    def create_due(self, body='30秒后 功能测试'):
        event = self.event('/remind ' + body, create_time=str(int((time.time() - 3600) * 1000)))
        self.bot.accept(event)
        self.bot.process_inbox()
        self.bot.enqueue_due(dt.datetime.now(TZ))

    def test_only_configured_owner_private_command_is_accepted(self):
        for changes in ({'sender_id': 'ou_other'}, {'sender_type': 'bot'}, {'chat_type': 'group'},
                        {'message_type': 'image'}, {'message_id': 'bad'}, {'content': '/todo 明天买菜'},
                        {'content': '/draw 画图'}, {'content': '普通聊天'}, {'content': '/reminder 明天15:00 检查'}):
            self.assertFalse(self.bot.accept(self.event(**changes)))
        self.assertEqual(len(self.rows('inbox')), 0)

    def test_post_command_accepted(self):
        self.assertTrue(self.bot.accept(self.event(message_type='post')))

    def test_duplicate_events_and_restart_do_not_create_duplicate_reminders(self):
        event = self.event()
        self.assertTrue(self.bot.accept(event))
        self.assertFalse(self.bot.accept(event))
        self.bot = Bot(self.config)
        self.bot.process_inbox()
        self.bot.process_inbox()
        self.assertEqual(len(self.rows('reminders')), 1)
        self.assertEqual(len(self.rows('outbox')), 1)
        self.assertIn('已设置提醒', self.rows('outbox')[0]['content'])

    def test_relative_time_uses_send_timestamp_even_after_offline_period(self):
        self.create_due()
        reminder = self.rows('reminders')[0]
        self.assertLess(reminder['next_due'], int(time.time() * 1000))
        self.assertIn('补发提醒', self.rows('outbox')[1]['content'])

    def test_parse_error_only_replies_does_not_schedule(self):
        self.bot.accept(self.event('/remind 明天8点 检查'))
        self.bot.process_inbox()
        self.assertEqual(len(self.rows('reminders')), 0)
        self.assertIn('未设置提醒', self.rows('outbox')[0]['content'])

    def test_missing_timestamp_does_not_guess(self):
        event = self.event()
        del event['create_time']
        self.bot.accept(event)
        self.bot.process_inbox()
        self.assertEqual(len(self.rows('reminders')), 0)
        self.assertIn('消息时间无法确认', self.rows('outbox')[0]['content'])

    def test_state_binding_prevents_wrong_account(self):
        with self.assertRaises(ValueError):
            Bot(dict(self.config, owner_open_id='ou_other'))

    def test_due_delivery_survives_restart_and_records_receipt(self):
        self.create_due()
        self.bot = Bot(self.config)
        with patch.object(self.bot, 'check_identity'), patch.object(self.bot, 'call', return_value={'message_id': 'om_sent'}) as call:
            self.bot.deliver(dt.datetime.now(TZ))
            self.bot.enqueue_due(dt.datetime.now(TZ))
            self.bot.deliver(dt.datetime.now(TZ))
        self.assertEqual(call.call_count, 2)  # one confirmation, one due message
        self.assertEqual([row['state'] for row in self.rows('outbox')], ['sent', 'sent'])
        self.assertEqual(self.rows('reminders')[0]['status'], 'done')
        self.assertIn('+messages-reply', call.call_args_list[0].args)
        self.assertIn('+messages-send', call.call_args_list[1].args)
        self.assertIn('ou_owner', call.call_args_list[1].args)

    def test_network_retry_preserves_idempotency_key(self):
        self.bot.accept(self.event())
        self.bot.process_inbox()
        with patch.object(self.bot, 'check_identity'), patch.object(self.bot, 'call', side_effect=[DeliveryError('timeout'), {'message_id': 'om_sent'}]) as call:
            self.bot.deliver(dt.datetime.now(TZ))
            with self.bot.db() as db:
                db.execute('UPDATE outbox SET retry_at=0')
            self.bot.deliver(dt.datetime.now(TZ))
        self.assertEqual(call.call_args_list[0], call.call_args_list[1])
        self.assertEqual(self.rows('outbox')[0]['state'], 'sent')

    def test_ambiguous_send_is_not_retried_after_idempotency_window(self):
        self.create_due()
        with self.bot.db() as db:
            db.execute("UPDATE outbox SET state='sent' WHERE kind='ack'")
            db.execute("UPDATE outbox SET first_attempt=? WHERE kind='due'", (time.time() - RETRY_WINDOW - 1,))
        with patch.object(self.bot, 'call') as call:
            self.bot.deliver(dt.datetime.now(TZ))
        call.assert_not_called()
        self.assertEqual(self.rows('outbox')[1]['state'], 'uncertain')
        self.assertEqual(self.rows('reminders')[0]['status'], 'uncertain')

    def test_missing_receipt_does_not_report_success(self):
        self.bot.accept(self.event())
        self.bot.process_inbox()
        with patch.object(self.bot, 'check_identity'), patch.object(self.bot, 'call', return_value={}):
            self.bot.deliver(dt.datetime.now(TZ))
        self.assertEqual(self.rows('outbox')[0]['state'], 'pending')

    def test_identity_mismatch_prevents_sending(self):
        self.bot.accept(self.event())
        self.bot.process_inbox()
        with patch.object(self.bot, 'check_identity', side_effect=DeliveryError('mismatch')), patch.object(self.bot, 'call') as call:
            self.bot.deliver(dt.datetime.now(TZ))
        call.assert_not_called()

    def test_repeating_backlog_sends_once_then_advances_beyond_now(self):
        self.create_due('每天上午9点 检查')
        # Force a three-day offline interval, without editing the recurrence itself.
        with self.bot.db() as db:
            db.execute('UPDATE reminders SET next_due=?', (int((time.time() - 3 * 86400) * 1000),))
        self.bot.enqueue_due(dt.datetime.now(TZ))
        with patch.object(self.bot, 'check_identity'), patch.object(self.bot, 'call', return_value={'message_id': 'om_sent'}) as call:
            self.bot.deliver(dt.datetime.now(TZ))
            self.bot.enqueue_due(dt.datetime.now(TZ))
        self.assertEqual(call.call_count, 2)
        self.assertGreater(self.rows('reminders')[0]['next_due'], int(time.time() * 1000))
        self.assertEqual(self.rows('reminders')[0]['status'], 'active')

    def request(self, content, mid, **changes):
        self.bot.accept(self.event(content, message_id=mid, **changes))
        self.bot.process_inbox()

    def code(self, reminder_id=None):
        if reminder_id is None:
            reminder_id = self.rows('reminders')[0]['id']
        with self.bot.db() as db:
            return self.bot.reminder_code(db, reminder_id)

    def test_bare_command_lists_empty_without_creating_reminder(self):
        self.request('/remind', 'om_list')
        self.assertEqual(self.rows('reminders'), [])
        self.assertEqual(self.rows('outbox')[0]['kind'], 'list')
        self.assertIn('当前暂无有效提醒', self.rows('outbox')[0]['content'])

    def test_codes_survive_restart_and_are_never_reused(self):
        self.request('/remind 2小时后 第一条', 'om_first')
        first_id = self.rows('reminders')[0]['id']
        self.request('/remind 1小时后 第二条', 'om_second')
        second_id = self.rows('reminders')[1]['id']
        self.assertEqual(self.code(first_id), 'R001')
        self.assertEqual(self.code(second_id), 'R002')
        self.request('/remind 取消 R001', 'om_cancel')
        self.bot = Bot(self.config)
        self.request('/remind 3小时后 第三条', 'om_third')
        self.assertEqual(self.code(second_id), 'R002')
        self.assertEqual(self.code(self.rows('reminders')[2]['id']), 'R003')
        self.request('/remind', 'om_list')
        listing = self.rows('outbox')[-1]['content']
        self.assertNotIn('第一条', listing)
        self.assertIn('R002 · 第二条', listing)
        self.assertIn('R003 · 第三条', listing)

    def test_legacy_database_backfills_numbers_and_preserves_receipts(self):
        self.request('/remind 每天晚上10点 老提醒', 'om_legacy')
        original = dict(self.rows('reminders')[0])
        with self.bot.db() as db:
            db.execute("UPDATE outbox SET state='sent',remote_id='om_old_ack',content='旧版无编号确认'")
            db.execute('DROP TABLE reminder_numbers')
        self.bot = Bot(self.config)
        self.assertEqual(dict(self.rows('reminders')[0]), original)
        self.assertEqual(self.code(), 'R001')
        self.request('取消', 'om_reply', reply_to='om_old_ack')
        self.assertEqual(self.rows('reminders')[0]['status'], 'cancelled')
        self.assertEqual(self.rows('outbox')[0]['remote_id'], 'om_old_ack')
        self.assertIn('已取消后续所有提醒', self.rows('outbox')[-1]['content'])

    def test_cancellation_by_code_suppresses_queued_ack_and_due(self):
        self.create_due()
        self.request('/remind 取消 r001', 'om_cancel')
        self.assertEqual(self.rows('reminders')[0]['status'], 'cancelled')
        self.assertIsNone(self.rows('reminders')[0]['next_due'])
        self.assertEqual([row['state'] for row in self.rows('outbox')], ['cancelled', 'cancelled', 'pending'])
        with patch.object(self.bot, 'check_identity'), patch.object(self.bot, 'call', return_value={'message_id': 'om_cancelled'}) as call:
            self.bot.tick()
        self.assertEqual(call.call_count, 1)
        self.assertIn('已取消提醒', call.call_args.args[call.call_args.args.index('--text') + 1])

    def test_reply_cancellation_resolves_ack_due_original_and_parent_alias(self):
        parents = [('reply_to', 'om_ack'), ('reply_to', 'om_due'), ('reply_to', 'om_original'), ('parent_id', 'om_ack')]
        for index, (field, parent) in enumerate(parents):
            source = f'om_original_{index}'
            self.request('/remind 每天晚上10点 重复事项', source)
            reminder_id = self.rows('reminders')[-1]['id']
            with self.bot.db() as db:
                db.execute("UPDATE outbox SET state='sent',remote_id=? WHERE reminder_id=?", (f'om_ack_{index}', reminder_id))
                self.bot.queue_message(db, f'fake-due-{index}', source, '已发送的到点消息',
                                       reminder_id=reminder_id, kind='due', mode='send')
                db.execute("UPDATE outbox SET state='sent',remote_id=? WHERE id=?", (f'om_due_{index}', f'fake-due-{index}'))
            actual_parent = source if parent == 'om_original' else parent + '_' + str(index)
            self.request('取消', f'om_cancel_{index}', **{field: actual_parent})
            self.assertEqual(self.rows('reminders')[-1]['status'], 'cancelled')
            self.assertIn('已取消后续所有提醒', self.rows('outbox')[-1]['content'])

    def test_plain_cancellation_without_related_direct_reply_does_nothing(self):
        self.request('/remind 1小时后 保留', 'om_original')
        self.assertFalse(self.bot.accept(self.event('取消', message_id='om_plain')))
        self.assertFalse(self.bot.accept(self.event('取消', message_id='om_root_only', root_id='om_original')))
        self.request('取消', 'om_unrelated', reply_to='om_draw_message', root_id='om_original')
        self.assertEqual(self.rows('reminders')[0]['status'], 'active')
        self.assertEqual(len(self.rows('outbox')), 1)

    def test_unknown_code_and_bad_cancel_syntax_never_guess(self):
        self.request('/remind 1小时后 约会议室', 'om_original')
        for index, body in enumerate(('取消 R099', '取消 约会议室', '取消 R001 R002', '取消 R999999999999999999999', '取消')):
            self.request('/remind ' + body, f'om_invalid_{index}')
        self.assertEqual(self.rows('reminders')[0]['status'], 'active')
        self.assertIn('未找到编号', self.rows('outbox')[1]['content'])

    def test_replayed_cancel_only_queues_one_response(self):
        self.request('/remind 1小时后 检查', 'om_original')
        event = self.event('/remind 取消 R001', message_id='om_cancel')
        self.bot.accept(event)
        self.bot.process_inbox()
        self.bot.accept(event)
        self.bot.process_inbox()
        self.assertEqual(len([x for x in self.rows('outbox') if x['kind'] == 'cancel']), 1)
        self.request('/remind 取消 R001', 'om_cancel_again')
        self.assertIn('已经取消', self.rows('outbox')[-1]['content'])

    def test_completed_once_reports_no_pending_reminder(self):
        self.request('/remind 1小时后 检查', 'om_original')
        with self.bot.db() as db:
            db.execute("UPDATE reminders SET status='done',next_due=NULL")
        self.request('/remind 取消 R001', 'om_cancel')
        self.assertEqual(self.rows('reminders')[0]['status'], 'done')
        self.assertIn('已经完成', self.rows('outbox')[-1]['content'])

    def test_cancel_queued_during_previous_api_call_is_applied_before_due_send(self):
        self.create_due()
        def send(*args):
            self.bot.accept(self.event('/remind 取消 R001', message_id='om_cancel'))
            return {'message_id': 'om_ack'}
        with patch.object(self.bot, 'check_identity'), patch.object(self.bot, 'call', side_effect=send) as call:
            self.bot.deliver(dt.datetime.now(TZ))
        self.assertEqual(call.call_count, 1)
        self.assertEqual(self.rows('outbox')[1]['state'], 'cancelled')
        self.assertEqual(self.rows('reminders')[0]['status'], 'cancelled')

    def test_in_flight_send_completion_cannot_reactivate_cancelled_repeat(self):
        self.create_due('每天上午9点 检查')
        with self.bot.db() as db:
            db.execute('UPDATE reminders SET next_due=?', (int((time.time() - 600) * 1000),))
            db.execute("UPDATE outbox SET state='sent',remote_id='om_ack' WHERE kind='ack'")
        self.bot.enqueue_due(dt.datetime.now(TZ))
        def send(*args):
            with self.bot.db() as db:
                item = db.execute('SELECT * FROM reminders').fetchone()
                self.bot.cancel(db, item)
            return {'message_id': 'om_in_flight'}
        with patch.object(self.bot, 'check_identity'), patch.object(self.bot, 'call', side_effect=send):
            self.bot.deliver(dt.datetime.now(TZ))
        self.assertEqual(self.rows('reminders')[0]['status'], 'cancelled')
        self.assertIsNone(self.rows('reminders')[0]['next_due'])

    def test_reply_can_cancel_creation_not_yet_processed(self):
        self.bot.accept(self.event('/remind 1小时后 检查', message_id='om_original'))
        self.bot.accept(self.event('取消', message_id='om_cancel', reply_to='om_original'))
        self.bot.process_inbox()
        self.assertEqual(self.rows('reminders')[0]['status'], 'cancelled')
        self.assertEqual(self.rows('outbox')[0]['state'], 'cancelled')

    def test_list_chunks_are_complete_and_bound_to_stable_codes(self):
        for index in range(5):
            self.request('/remind 1小时后 ' + ('设备检查' * 480) + str(index), f'om_large_{index}')
        self.request('/remind', 'om_list')
        pages = [row['content'] for row in self.rows('outbox') if row['kind'] == 'list']
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(page.encode('utf-8')) <= 12000 for page in pages))
        for index in range(5):
            self.assertIn(f'R{index + 1:03d} · ', '\n'.join(pages))
        self.request('/remind', 'om_list')  # replay should not produce more pages
        self.assertEqual(len([row for row in self.rows('outbox') if row['kind'] == 'list']), len(pages))

    def test_uncertain_reminder_is_visible_and_can_be_cancelled(self):
        self.request('/remind 每天晚上10点 检查', 'om_original')
        with self.bot.db() as db:
            db.execute("UPDATE reminders SET status='uncertain'")
        self.request('/remind', 'om_list')
        self.assertIn('已暂停自动发送', self.rows('outbox')[-1]['content'])
        self.request('/remind 取消 R001', 'om_cancel')
        self.assertEqual(self.rows('reminders')[0]['status'], 'cancelled')

    def test_other_users_cannot_cancel_by_code_or_reply(self):
        self.request('/remind 1小时后 检查', 'om_original')
        for content in ('/remind 取消 R001', '取消'):
            self.assertFalse(self.bot.accept(self.event(content, message_id='om_other', sender_id='ou_other', reply_to='om_original')))
        self.bot.process_inbox()
        self.assertEqual(self.rows('reminders')[0]['status'], 'active')

    def test_explicit_code_wins_over_unrelated_reply_context(self):
        self.request('/remind 1小时后 第一条', 'om_first')
        self.request('/remind 1小时后 第二条', 'om_second')
        self.request('/remind 取消 R002', 'om_cancel', reply_to='om_first')
        self.assertEqual([row['status'] for row in self.rows('reminders')], ['active', 'cancelled'])


if __name__ == '__main__':
    unittest.main()
