"""Deterministic Chinese reminder grammar; no model, network, or shell execution."""
import datetime as dt
import re
from dataclasses import dataclass


class ParseError(ValueError):
    pass


NUM = r'[0-9零〇一二两三四五六七八九十百千]+'
DAY_NAMES = '一二三四五六日'
TRANSLATION = str.maketrans('０１２３４５６７８９：', '0123456789:')
HELP = ('用法：/remind 时间 事项（北京时间）\n'
        '查看当前提醒：/remind\n取消提醒：/remind 取消 R012，或回复相关提醒消息发送“取消”。\n'
        '例如：\n/remind 30分钟后 检查训练结果\n'
        '/remind 明天下午3点 约会议室\n'
        '/remind 每天晚上10点 备份代码\n'
        '/remind 每周五下午5点 整理周报\n'
        '也支持：后天、下周一、2026-12-01、12月1日、每月1日、周一到周五。\n'
        '请写明确时刻；“8点”请改为“上午8点”“晚上8点”或“08:00”。')


def number(value):
    if value.isascii() and value.isdigit():
        return int(value)
    digits = dict(zip('零〇一二两三四五六七八九', [0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9]))
    if all(c in digits for c in value):
        if len(value) != 1:
            raise ParseError('数字请使用阿拉伯数字，例如 30。')
        return digits[value]
    result = digit = 0
    previous_unit = 10000
    for char in value:
        if char in digits:
            digit = digits[char]
        elif char in '十百千':
            unit = {'十': 10, '百': 100, '千': 1000}[char]
            if unit >= previous_unit:
                raise ParseError('数字格式不明确，请改用阿拉伯数字。')
            result += (digit or 1) * unit
            digit, previous_unit = 0, unit
        else:
            raise ParseError('数字格式不明确，请改用阿拉伯数字。')
    result += digit
    # Reject malformed or abbreviated numerals instead of silently guessing.
    if not 0 < result <= 9999:
        raise ParseError('数字格式不明确，请改用阿拉伯数字。')
    canonical = ''
    pending_zero = False
    for unit, label in ((1000, '千'), (100, '百'), (10, '十'), (1, '')):
        part = result // unit % 10
        if part:
            if pending_zero:
                canonical += '零'
            canonical += '零一二三四五六七八九'[part] + label
            pending_zero = False
        elif canonical:
            pending_zero = True
    if canonical.startswith('一十'):
        canonical = canonical[1:]
    normalized = value.replace('两', '二').replace('〇', '零')
    if normalized not in (canonical, '一' + canonical if canonical.startswith('十') else canonical):
        raise ParseError('数字格式不明确，请改用阿拉伯数字。')
    return result


@dataclass(frozen=True)
class Reminder:
    title: str
    due: dt.datetime
    rule: dict


def recurrence_label(rule):
    kind = rule['kind']
    if kind == 'once':
        return '不重复'
    if kind == 'daily':
        return '每天'
    if kind == 'monthly':
        return f"每月{rule['day']}日（当月无此日期时跳过）"
    if rule['weekdays'] == [0, 1, 2, 3, 4]:
        return '周一至周五（不按法定节假日或调休调整）'
    return '每周' + '、'.join(DAY_NAMES[n] for n in rule['weekdays'])


def next_occurrence(rule, after):
    """First occurrence strictly after `after`; skip nonexistent monthly dates."""
    if rule['kind'] == 'once':
        return None
    for offset in range(1831):
        day = after.date() + dt.timedelta(days=offset)
        if rule['kind'] == 'weekly' and day.weekday() not in rule['weekdays']:
            continue
        if rule['kind'] == 'monthly' and day.day != rule['day']:
            continue
        candidate = dt.datetime.combine(day, dt.time(rule['hour'], rule['minute']), after.tzinfo)
        if candidate > after:
            return candidate
    raise ParseError('未能计算下一次提醒时间。')


def parse_clock(value):
    """Return (hour, minute, consumed characters); require an unambiguous clock."""
    period_match = re.match(r'^(凌晨|早上|早晨|上午|中午|下午|傍晚|晚上|晚间|夜里)?\s*', value)
    period = period_match[1]
    offset = period_match.end()
    rest = value[offset:]
    clock = re.match(r'^(\d{1,2}):(\d{2})(?![\d:])', rest)
    if clock:
        hour, minute = int(clock[1]), int(clock[2])
    else:
        clock = re.match(rf'^({NUM})[点时](?:(半|一刻|三刻)|({NUM})分)?', rest)
        if not clock:
            raise ParseError('请写具体时刻，例如“明天下午3点”或“明天15:00”。')
        hour = number(clock[1])
        minute = {'半': 30, '一刻': 15, '三刻': 45}.get(clock[2], 0)
        if clock[3]:
            minute = number(clock[3])
        if not period and 1 <= hour <= 12:
            raise ParseError('早晚不明确，请改用“上午8点”“晚上8点”或“08:00”这样的写法。')
    if not 0 <= minute <= 59:
        raise ParseError('分钟应为 0～59。')
    if period:
        if period in ('下午', '傍晚', '晚上', '晚间', '夜里'):
            if 1 <= hour <= 11:
                hour += 12
            elif not 12 <= hour <= 23:
                raise ParseError('这个时刻不明确，请改用24小时制，例如 22:00。')
            if period in ('晚上', '晚间', '夜里') and hour == 12:
                raise ParseError('“晚上12点”日期不明确，请明确写“明天00:00”等日期和时刻。')
        elif period == '中午':
            if hour in (1, 2):
                hour += 12
            if not 11 <= hour <= 14:
                raise ParseError('中午时刻请用 11:00～14:59。')
        elif not 0 <= hour <= 11:
            raise ParseError('上午/凌晨时刻请用 00:00～11:59；中午12点请写 12:00。')
    if not 0 <= hour <= 23:
        raise ParseError('小时应为 0～23。')
    return hour, minute, offset + clock.end()


def take_title(original, consumed):
    remaining = original[consumed:]
    if not remaining or not re.match(r'^[\s，,:：]', remaining):
        raise ParseError('请在时间与事项之间加一个空格，例如“明天下午3点 检查设备”。')
    title = remaining.lstrip(' \t\r\n，,:：').strip()
    if not title:
        raise ParseError('请在时间后写要提醒的事项。')
    if len(title) > 2000:
        raise ParseError('提醒事项请控制在2000字以内。')
    return title


def parse_reminder(body, sent_at):
    if sent_at.tzinfo is None:
        raise ValueError('sent_at must include a timezone')
    original = body.strip()
    if not original:
        raise ParseError(HELP)
    if len(original) > 2500:
        raise ParseError('消息太长，提醒事项请控制在2000字以内。')
    value = original.translate(TRANSLATION)
    # Relative durations, including compound forms such as 1小时30分钟后.
    relative = re.match(rf'^(半小时|(?:{NUM}(?:天|小时|分钟|秒钟|秒))+)(?:之)?后', value)
    if relative:
        duration = relative[1]
        if duration == '半小时':
            seconds = 1800
        else:
            pieces = re.findall(rf'({NUM})(天|小时|分钟|秒钟|秒)', duration)
            units = [unit for _, unit in pieces]
            ranks = {'天': 0, '小时': 1, '分钟': 2, '秒钟': 3, '秒': 3}
            if [ranks[u] for u in units] != sorted(set(ranks[u] for u in units)):
                raise ParseError('时长请按“天、小时、分钟、秒”的顺序书写，每个单位只写一次。')
            seconds = sum(number(n) * {'天': 86400, '小时': 3600, '分钟': 60, '秒钟': 1, '秒': 1}[u]
                          for n, u in pieces)
        if not 0 < seconds <= 3650 * 86400:
            raise ParseError('相对提醒时长应大于0，且不超过3650天。')
        return Reminder(take_title(original, relative.end()), sent_at + dt.timedelta(seconds=seconds), {'kind': 'once'})

    rule = {'kind': 'once'}
    offset = 0
    day = sent_at.date()
    match = re.match(r'^(?:每个工作日|每工作日|工作日|(?:每)?周一(?:到|至)周五)', value)
    if match:
        rule = {'kind': 'weekly', 'weekdays': [0, 1, 2, 3, 4]}
        offset = match.end()
    elif value.startswith(('每天', '每日')):
        rule, offset = {'kind': 'daily'}, 2
    elif (match := re.match(r'^每(?:周|星期)([一二三四五六日天1-7])', value)):
        weekday = '一二三四五六日'.find(match[1].replace('天', '日')) if not match[1].isdigit() else int(match[1]) - 1
        rule, offset = {'kind': 'weekly', 'weekdays': [weekday]}, match.end()
    elif (match := re.match(rf'^每月({NUM})[日号]', value)):
        month_day = number(match[1])
        if not 1 <= month_day <= 31:
            raise ParseError('每月的日期应为1～31日。')
        rule, offset = {'kind': 'monthly', 'day': month_day}, match.end()
    elif (match := re.match(r'^(今天|明天|后天|大后天)', value)):
        day += dt.timedelta(days={'今天': 0, '明天': 1, '后天': 2, '大后天': 3}[match[1]])
        offset = match.end()
    elif (match := re.match(r'^(本周|这周|下周|周|星期)([一二三四五六日天1-7])', value)):
        weekday = '一二三四五六日'.find(match[2].replace('天', '日')) if not match[2].isdigit() else int(match[2]) - 1
        if match[1] == '下周':
            days = 7 - day.weekday() + weekday
        elif match[1] in ('本周', '这周'):
            days = weekday - day.weekday()
        else:
            days = (weekday - day.weekday()) % 7
        day += dt.timedelta(days=days)
        offset = match.end()
    else:
        match = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)', value)
        chinese_date = re.match(rf'^(?:(\d{{4}})年)?({NUM})月({NUM})[日号]', value)
        try:
            if match:
                day = dt.date(*map(int, match.groups()))
                offset = match.end()
            elif chinese_date:
                day = dt.date(int(chinese_date[1] or sent_at.year), number(chinese_date[2]), number(chinese_date[3]))
                offset = chinese_date.end()
        except ValueError:
            raise ParseError('这个日期不存在，请检查年月日。') from None

    hour, minute, used = parse_clock(value[offset:])
    title = take_title(original, offset + used)
    if rule['kind'] != 'once':
        rule.update(hour=hour, minute=minute)
        due = next_occurrence(rule, sent_at)
    else:
        due = dt.datetime.combine(day, dt.time(hour, minute), sent_at.tzinfo)
        if due <= sent_at:
            raise ParseError('这个时间已经过去了，请明确写未来的日期和时间，例如“明天下午3点”。')
    return Reminder(title, due, rule)


def format_time(value):
    # Seconds are meaningful for relative reminders and delivery verification.
    clock = value.strftime('%H:%M:%S' if value.second else '%H:%M')
    return f"{value:%Y-%m-%d}（周{DAY_NAMES[value.weekday()]}）{clock}"


def confirmation(reminder):
    return (f'⏰ 已设置提醒\n事项：{reminder.title}\n'
            f'时间：{format_time(reminder.due)}（北京时间）\n'
            f'重复：{recurrence_label(reminder.rule)}')
