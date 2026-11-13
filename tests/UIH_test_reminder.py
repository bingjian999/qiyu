"""UIH · 久坐提醒（BreakSettings + BreakScheduler）测试。

覆盖需求要点：
- 45 分钟久坐 + 3 分钟活动两阶段节奏
- 快到点（≤120 秒）橙色警示标记
- 到点 sit_due 只触发一次；稍后 5 分钟推迟
- 我已起身 → 进入活动倒计时并计入起身统计
- 离座识别：闲置超 10 分钟视为已起身，自动重新计时
- 预设节奏（45/3、60/5、30/2）与自定义时长（含边界钳制）
- 设置 + 统计 JSON 持久化，跨天清零当日计数
"""
import datetime
import json
import os
import tempfile

import pytest

from qiyu_pet.core import BreakScheduler, BreakSettings


T0 = 1_000_000_000.0  # 固定起始时间戳


def make_settings(tmp_path=None, **kw):
    store = os.path.join(str(tmp_path), "break.json") if tmp_path else None
    s = BreakSettings(store_path=store)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_UIH_break_defaults_45_3():
    s = make_settings()
    assert (s.sit_min, s.activity_min) == (45, 3)
    assert s.preset == "45/3"
    assert s.sound_enabled is True
    assert s.fullscreen_mode is False
    assert s.idle_away_min == 10


def test_UIH_break_presets():
    s = make_settings()
    for key, (sit, act) in BreakSettings.PRESETS.items():
        assert s.apply_preset(key) is True
        assert (s.sit_min, s.activity_min) == (sit, act)
        assert s.preset == key
    assert s.apply_preset("99/9") is False


def test_UIH_break_custom_clamped():
    s = make_settings()
    s.set_custom(90, 5)
    assert (s.sit_min, s.activity_min, s.preset) == (90, 5, "custom")
    # 边界钳制：久坐 1~180，活动 1~60
    s.set_custom(0, 999)
    assert (s.sit_min, s.activity_min) == (1, 60)
    s.set_custom(500, 0)
    assert (s.sit_min, s.activity_min) == (180, 1)
    # 恰好等于预设组合时标记回预设
    s.set_custom(60, 5)
    assert s.preset == "60/5"


def test_UIH_break_sitting_countdown_and_warning(tmp_path):
    s = make_settings(tmp_path, sit_min=5, activity_min=1)
    clock = [T0]
    b = BreakScheduler(s, time_fn=lambda: clock[0])
    st = b.tick(now=T0 + 10)
    assert st["phase"] == "sitting"
    assert st["seconds_left"] == 290
    assert 0 < st["progress"] < 1
    assert st["warning"] is False
    assert st["events"] == []
    # 剩 100 秒内 → 橙色警示
    st = b.tick(now=T0 + 5 * 60 - 100)
    assert st["seconds_left"] == 100
    assert st["warning"] is True
    assert st["events"] == []


def test_UIH_break_sit_due_once(tmp_path):
    s = make_settings(tmp_path, sit_min=1, activity_min=1)
    b = BreakScheduler(s, time_fn=lambda: T0)
    st = b.tick(now=T0 + 61)
    assert "sit_due" in st["events"]
    assert st["seconds_left"] == 0
    # 到点后持续 tick 不重复触发
    for _ in range(3):
        assert b.tick(now=T0 + 62)["events"] == []


def test_UIH_break_snooze(tmp_path):
    s = make_settings(tmp_path, sit_min=1, activity_min=1)
    b = BreakScheduler(s, time_fn=lambda: T0)
    b.tick(now=T0 + 61)  # sit_due
    b.snooze(5)
    st = b.tick(now=T0 + 61)
    assert st["events"] == []
    assert st["seconds_left"] == 5 * 60 - 1
    # 5 分钟后再次到点，可再触发一次
    st = b.tick(now=T0 + 61 + 5 * 60)
    assert "sit_due" in st["events"]


def test_UIH_break_rise_then_activity_done(tmp_path):
    s = make_settings(tmp_path, sit_min=5, activity_min=3)
    clock = [T0]
    b = BreakScheduler(s, time_fn=lambda: clock[0])
    clock[0] = T0 + 301
    assert "sit_due" in b.tick()["events"]
    clock[0] = T0 + 320
    b.start_activity()  # 我已起身 → 活动倒计时 3 分钟 + 计起身
    st = b.tick()
    assert st["phase"] == "activity"
    assert st["seconds_left"] == 180
    assert st["warning"] is False
    assert s.stats["today"] == 1  # 起身计入统计
    # 活动结束 → 自动进入下一轮久坐（本轮设置 sit_min=5 分钟）
    clock[0] = T0 + 320 + 181
    st = b.tick()
    assert "activity_done" in st["events"]
    assert st["phase"] == "sitting"
    assert st["seconds_left"] == 5 * 60


def test_UIH_break_away_reset(tmp_path):
    """闲置超 10 分钟视为已起身：away_reset + 重新计时 + 计数。"""
    s = make_settings(tmp_path)  # 默认 idle_away_min=10
    b = BreakScheduler(s, time_fn=lambda: T0)
    b.tick(now=T0 + 100, idle_sec=60)  # 闲置不足，正常倒计时
    st = b.tick(now=T0 + 200, idle_sec=10 * 60 + 1)
    assert "away_reset" in st["events"]
    assert st["phase"] == "sitting"
    assert st["seconds_left"] == 45 * 60
    assert s.stats["today"] == 1


def test_UIH_break_stats_rollover(tmp_path):
    s = make_settings(tmp_path)
    s.bump_standup(datetime.datetime(2026, 11, 10, 9, 0, 0))
    s.bump_standup(datetime.datetime(2026, 11, 10, 15, 0, 0))
    assert s.stats == {"date": "2026-11-10", "today": 2, "total": 2}
    # 跨天：today 清零，total 累计
    s.bump_standup(datetime.datetime(2026, 11, 11, 8, 0, 0))
    assert s.stats["date"] == "2026-11-11"
    assert s.stats["today"] == 1
    assert s.stats["total"] == 3


def test_UIH_break_persistence_roundtrip(tmp_path):
    store = os.path.join(str(tmp_path), "break.json")
    s1 = BreakSettings(store_path=store)
    s1.apply_preset("30/2")
    s1.sound_enabled = False
    s1.fullscreen_mode = True
    s1.idle_away_min = 15
    s1.bump_standup(datetime.datetime(2026, 11, 11, 10, 0, 0))
    assert os.path.exists(store)
    s2 = BreakSettings(store_path=store)
    assert s2.sit_min == 30 and s2.activity_min == 2 and s2.preset == "30/2"
    assert s2.sound_enabled is False
    assert s2.fullscreen_mode is True
    assert s2.idle_away_min == 15
    assert s2.stats["today"] == 1 and s2.stats["total"] == 1


def test_UIH_break_persistence_survives_corrupt_file(tmp_path):
    store = os.path.join(str(tmp_path), "break.json")
    with open(store, "w", encoding="utf-8") as f:
        f.write("{broken json!!")
    s = BreakSettings(store_path=store)
    assert s.sit_min == 45 and s.activity_min == 3  # 损坏时回退默认值


def test_UIH_break_no_store_no_crash(tmp_path):
    s = make_settings()  # store_path=None
    s.apply_preset("60/5")
    s.bump_standup()
    assert s.sit_min == 60
    assert s.stats["total"] == 1


def test_UIH_break_restart_applies_new_settings(tmp_path):
    """易用性关键：面板改节奏后必须立即生效，而不是仍按旧 45 分钟走。"""
    s = make_settings(tmp_path)
    clock = [T0]
    b = BreakScheduler(s, time_fn=lambda: clock[0])
    clock[0] = T0 + 100  # 已坐了 100 秒
    s.set_custom(1, 1)   # 用户在面板改成 1 分钟
    b.restart()          # 面板回调触发
    st = b.tick()
    assert st["phase"] == "sitting"
    assert st["seconds_left"] == 60  # 按新节奏重新计时
    clock[0] = T0 + 100 + 61
    assert "sit_due" in b.tick()["events"]  # 1 分钟后到点弹窗


def test_UIH_break_away_counted_once_per_episode(tmp_path):
    """一段离座只记一次起身，离座期间久坐计时持续顺延。"""
    s = make_settings(tmp_path)  # idle_away_min=10
    clock = [T0]
    b = BreakScheduler(s, time_fn=lambda: clock[0])
    clock[0] = T0 + 601
    st = b.tick(idle_sec=601)
    assert "away_reset" in st["events"]
    assert s.stats["today"] == 1
    # 持续离座 5 分钟：不再重复计数/报事件，但截止时间不断顺延
    for i in range(5):
        clock[0] = T0 + 601 + (i + 1) * 60
        st = b.tick(idle_sec=601 + (i + 1) * 60)
        assert st["events"] == []
        assert st["seconds_left"] == 45 * 60
    assert s.stats["today"] == 1
    # 回来活动一会儿（闲置 < 阈值），再次离座会重新计一次
    clock[0] += 60
    b.tick(idle_sec=30)
    clock[0] += 60
    st = b.tick(idle_sec=601)
    assert "away_reset" in st["events"]
    assert s.stats["today"] == 2
