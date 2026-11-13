"""UIH · 配置与基本设定测试。"""
import os

from qiyu_pet.core import (
    PetConfig, BreakSettings, CHARACTER_NAME, MASTER_NAME, POSES, STATE_TO_POSE,
)


def test_UIH_pet_name_is_qiyu():
    cfg = PetConfig()
    assert cfg.name == CHARACTER_NAME == "祁煜"


def test_UIH_master_is_jiahui():
    cfg = PetConfig()
    assert cfg.master == MASTER_NAME == "家慧"


def test_UIH_all_poses_present():
    """十种人的动作齐备。"""
    expected = {
        "idle", "wave", "think", "walk", "run",
        "sit", "stretch", "sleep", "surprise", "bow",
    }
    assert set(POSES) == expected


def test_UIH_state_to_pose_complete():
    for s in POSES:
        assert STATE_TO_POSE[s] == s


def test_UIH_break_settings_defaults():
    """久坐提醒默认节奏：45 分钟久坐 + 3 分钟活动，全屏强制默认关。"""
    s = BreakSettings()
    assert s.sit_min == 45
    assert s.activity_min == 3
    assert s.preset == "45/3"
    assert s.fullscreen_mode is False
    assert s.sound_enabled is True
    assert s.idle_away_min == 10


def test_UIH_sprite_files_exist():
    here = os.path.dirname(os.path.abspath(__file__))
    sprite_dir = os.path.join(here, "..", "qiyu_pet", "sprites", "qiyu")
    for p in POSES:
        assert os.path.exists(os.path.join(sprite_dir, f"{p}.png")), f"缺少精灵图 {p}.png"
