"""UIH · 祁煜角色设定测试（人物化、称呼家慧）。"""
import random

from qiyu_pet.core import (
    PetConfig, PetFSM, POSES, CLICK_REACTIONS, STATE_DURATION, MENU,
    SPEECHES, STATE_TO_POSE, CHARACTER_NAME, MASTER_NAME, greeting_message,
)


def test_UIH_character_name():
    cfg = PetConfig()
    assert cfg.name == CHARACTER_NAME == "祁煜"


def test_UIH_master_name():
    cfg = PetConfig()
    assert cfg.master == MASTER_NAME == "家慧"


def test_UIH_ten_human_poses():
    expected = {
        "idle", "wave", "think", "walk", "run",
        "sit", "stretch", "sleep", "surprise", "bow",
    }
    assert set(POSES) == expected


def test_UIH_state_to_pose_identity():
    for s in POSES:
        assert STATE_TO_POSE[s] == s


def test_UIH_click_reactions_subset():
    assert set(CLICK_REACTIONS) <= set(POSES)
    assert "sleep" not in CLICK_REACTIONS  # 点一下不会把他点睡着


def test_UIH_all_temp_states_have_duration():
    for s in CLICK_REACTIONS:
        assert s in STATE_DURATION, f"{s} 应有持续秒数"


def _fsm(t0=0.0, seed=7):
    t = {"v": t0}
    return PetFSM(PetConfig(), time_fn=lambda: t["v"], rng=random.Random(seed)), t


def test_UIH_click_returns_reaction_and_speech():
    fsm, t = _fsm()
    state, speech = fsm.on_click(now=1.0)
    assert state in CLICK_REACTIONS
    assert "祁煜" in speech


def test_UIH_all_speeches_contain_name_and_humanized():
    """每句台词都含名字，且无宠物化字眼。"""
    for state, line in SPEECHES.items():
        text = line.format(name=CHARACTER_NAME)
        assert "祁煜" in text, f"{state} 台词应含名字"
        for bad in ("喵", "主人", "宠物", "挠", "舔毛", "喂食"):
            assert bad not in text, f"{state} 台词出现宠物化字眼：{bad}"


def test_UIH_master_called_jiahui_in_lines():
    """互动/台词中称用户为家慧，不称主人。"""
    from qiyu_pet.core import (
        SHOULDER_PAT_LINES, COMPANY_LINES, DESSERT_LINES, COMBO_LINES,
    )
    for lines in (SHOULDER_PAT_LINES, COMPANY_LINES, DESSERT_LINES,
                 list(COMBO_LINES.values())):
        for ln in lines:
            text = ln.format(name=CHARACTER_NAME)
            assert "主人" not in text
            if ("家慧" not in text and "你" not in text
                    and "我" not in text):
                raise AssertionError(f"台词未称呼家慧：{text}")
    # 至少一句明确叫出「家慧」
    assert any("家慧" in ln.format(name=CHARACTER_NAME) for ln in
               SHOULDER_PAT_LINES + COMPANY_LINES + DESSERT_LINES)


def test_UIH_greetings_call_master_jiahui():
    for hour in range(24):
        msg = greeting_message(hour)
        assert "祁煜" in msg
        assert "家慧" in msg
        assert "主人" not in msg
        assert "喵" not in msg


def test_UIH_menu_humanized():
    assert MENU["feed"] == "请他吃甜品"
    assert MENU["long_press"] == "安静陪伴（长按）"
    assert MENU["double_click"] == "拍拍肩（双击）"
    for k in ("wave", "think", "walk", "run", "sit", "stretch",
              "surprise", "bow", "sleep"):
        assert k in MENU
    for text in MENU.values():
        assert "喵" not in text and "主人" not in text and "喂食" not in text


def test_UIH_no_tail_no_pet_words_in_config():
    cfg = PetConfig()
    assert not hasattr(cfg, "no_tail")  # 人形角色无此设定
    assert cfg.poses == POSES
    assert cfg.menu == MENU


def test_UIH_double_click_shoulder_pat():
    fsm, t = _fsm()
    state, speech = fsm.on_double_click(now=1.0)
    assert state == "surprise"
    assert "祁煜" in speech


def test_UIH_long_press_company():
    fsm, t = _fsm()
    state, speech = fsm.on_pet(now=1.0)
    assert state == "think"
    assert "祁煜" in speech


def test_UIH_feed_dessert():
    fsm, t = _fsm()
    state, speech = fsm.on_feed(now=1.0)
    assert state == "bow"
    assert "祁煜" in speech


def test_UIH_key_map_human_actions():
    fsm, _ = _fsm()
    assert fsm.KEY_MAP["space"] == "wave"
    assert fsm.KEY_MAP["w"] == "walk"
    assert fsm.KEY_MAP["h"] == "think"
    assert fsm.KEY_MAP["f"] == "bow"
    for target in fsm.KEY_MAP.values():
        assert target in POSES


def test_UIH_time_aware_states_valid():
    fsm, _ = _fsm()
    for hour in range(24):
        fsm.hour_fn = lambda h=hour: h
        assert fsm.time_aware_state() in POSES


def test_UIH_pose_output_always_valid():
    fsm, t = _fsm()
    for state in POSES:
        fsm.state = state
        assert fsm.pose() in POSES


def test_UIH_temp_states_expire_to_idle():
    """所有临时动作到期后回到 idle（回归测试）。"""
    for state in CLICK_REACTIONS:
        fsm, _ = _fsm()
        fsm.state = state
        fsm.state_until = 1.0
        fsm.last_interaction = 0.0
        s, _changed = fsm.tick(now=1.5)
        assert s == "idle", f"{state} 到期应回 idle"


def test_UIH_sleep_not_expired_by_tick():
    fsm, _ = _fsm()
    fsm.state = "sleep"
    fsm.state_until = 1.0
    fsm.last_interaction = 0.0
    s, _ = fsm.tick(now=10.0)
    assert s == "sleep"


def test_UIH_combo_milestones():
    fsm, t = _fsm()
    for i in range(5):
        state, speech = fsm.on_click(now=i * 0.5)
    assert "家慧" in speech or "十" not in speech


def test_UIH_combo_ten_calls_master():
    fsm, t = _fsm()
    for i in range(10):
        state, speech = fsm.on_click(now=i * 0.5)
    assert "十下" in speech


def test_UIH_mood_ranges():
    fsm, _ = _fsm()
    fsm.mood = 80
    assert fsm.mood_label() == "开心"
    fsm.mood = 10
    assert fsm.mood_label() == "想睡觉"


def test_UIH_sprite_files_on_disk():
    import os
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "qiyu_pet", "sprites", "qiyu")
    for p in POSES:
        assert os.path.exists(os.path.join(base, f"{p}.png")), f"缺 {p}.png"
