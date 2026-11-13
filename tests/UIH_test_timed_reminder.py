"""UIH · 定时提醒（TimedReminder）测试。"""
import datetime
import os

from qiyu_pet.core import PetConfig, TimedReminder


def _dt(h, m, day=1):
    return datetime.datetime(2026, 11, day, h, m, 0)


def _make(store_path=None):
    return TimedReminder(PetConfig(), store_path=store_path)


def test_UIH_timed_reminder_add_and_list():
    tr = _make()
    assert tr.add("14:30", "喝水") is True
    assert tr.add("9:05", "站一会") is True  # 个位数小时自动归一
    items = tr.items()
    assert [r["time"] for r in items] == ["09:05", "14:30"]  # 按时间排序
    assert items[1]["text"] == "喝水"


def test_UIH_timed_reminder_invalid_input():
    tr = _make()
    assert tr.add("25:00", "x") is False      # 小时越界
    assert tr.add("12:60", "x") is False      # 分钟越界
    assert tr.add("abc", "x") is False        # 非时间
    assert tr.add("12:30", "  ") is False     # 空内容
    assert tr.items() == []


def test_UIH_timed_reminder_same_time_overwrites():
    tr = _make()
    tr.add("08:00", "旧提醒")
    tr.add("08:00", "新提醒")
    items = tr.items()
    assert len(items) == 1
    assert items[0]["text"] == "新提醒"


def test_UIH_timed_reminder_fires_at_due_time():
    tr = _make()
    tr.add("14:30", "喝水")
    before = tr.check(_dt(14, 29))
    assert before == []                        # 还没到点
    fired = tr.check(_dt(14, 30))
    assert len(fired) == 1 and "喝水" in fired[0] and "定时提醒" in fired[0]


def test_UIH_timed_reminder_fires_once_per_day():
    tr = _make()
    tr.add("14:30", "喝水")
    assert tr.check(_dt(14, 31))               # 第 1 次（追补窗口内）
    assert tr.check(_dt(14, 40)) == []         # 同一天不再触发
    # 第二天 14:31（追补窗口内）重新触发
    again = tr.check(datetime.datetime(2026, 11, 2, 14, 31, 0))
    assert len(again) == 1


def test_UIH_timed_reminder_catchup_window():
    tr = _make()
    tr.add("09:00", "晨会")
    assert tr.check(_dt(9, 14)) != []          # 14 分钟内仍可追补
    tr2 = _make()
    tr2.add("09:00", "晨会")
    assert tr2.check(_dt(9, 20)) == []         # 超过窗口不补触发


def test_UIH_timed_reminder_future_time_not_fired():
    tr = _make()
    tr.add("18:00", "下班")
    assert tr.check(_dt(10, 0)) == []          # 未到点不触发


def test_UIH_timed_reminder_remove_and_clear():
    tr = _make()
    tr.add("08:00", "a")
    tr.add("09:00", "b")
    assert tr.remove("08:00") is True
    assert tr.remove("08:00") is False         # 已不存在
    assert [r["time"] for r in tr.items()] == ["09:00"]
    tr.clear()
    assert tr.items() == []


def test_UIH_timed_reminder_persists_to_json(tmp_path):
    store = str(tmp_path / "reminders.json")
    tr = _make(store)
    tr.add("07:30", "遛狗")
    tr2 = _make(store)                          # 模拟重启后重新加载
    assert [r["text"] for r in tr2.items()] == ["遛狗"]
    assert [r["time"] for r in tr2.items()] == ["07:30"]


def test_UIH_timed_reminder_corrupt_file_tolerated(tmp_path):
    store = tmp_path / "bad.json"
    store.write_text("{not valid json", encoding="utf-8")
    tr = _make(str(store))                      # 不抛异常，按空列表处理
    assert tr.items() == []
