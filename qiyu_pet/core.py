"""祁煜桌面伙伴 · 核心逻辑层（无 Qt 依赖，便于单测）。

祁煜是《恋与深空》中的人形角色——桌面上的他是"人"，不是宠物：
- 十个动作：待机 / 挥手 / 思考 / 散步 / 跑步 / 坐下 / 伸懒腰 / 休息 / 惊讶 / 鞠躬
- 互动：点击反应、双击拍拍肩、长按安静陪伴、请他吃甜品、连击、快捷键
- 他称你为「家慧」
- 心情系统（互动越频繁心情越高，影响自发行为）
- 时间感知行为（早/中/晚不同状态倾向）
- 久坐提醒 / 定时提醒 / 开机问候
"""

import datetime
import json
import os
import time as _time

CHARACTER_NAME = "祁煜"
MASTER_NAME = "家慧"

# 全部动作（10 种，全部为人的动作）
POSES = [
    "idle", "wave", "think", "walk", "run",
    "sit", "stretch", "sleep", "surprise", "bow",
]

# 状态 -> 动作文件名（单角色，一一对应）
STATE_TO_POSE = {p: p for p in POSES}

# 点击后随机触发的反应动作
CLICK_REACTIONS = ["wave", "think", "walk", "sit", "stretch", "surprise", "bow"]

# 各临时状态的持续秒数（sleep 不自动过期）
STATE_DURATION = {
    "wave": 2.5,
    "think": 4.0,
    "walk": 3.0,
    "run": 3.0,
    "sit": 4.0,
    "stretch": 2.0,
    "surprise": 2.5,
    "bow": 3.0,
}

# 双击 → 拍拍肩
SHOULDER_PAT_LINES = [
    "{name}：……家慧，打招呼可以好好说话。",
    "{name}：突然拍肩，吓我一跳。",
    "{name}：好吧，看在你的份上，不跟你计较。",
]

# 长按 → 安静陪伴
COMPANY_LINES = [
    "{name}：家慧，就这样安静待一会儿，也挺好。",
    "{name}：家慧今天，好像有点累。",
    "{name}：我在，别急。",
]

# 请他吃甜品
DESSERT_LINES = [
    "{name}：甜品？……既然是你特意准备的，家慧。",
    "{name}：下次换我请你，这家店我熟。",
    "{name}：你还记得我喜欢的口味。",
]

# 吃完甜品
DESSERT_DONE_LINE = "{name}：还不错。谢了，家慧。"

# 连击里程碑台词
COMBO_LINES = {
    5: "{name}：连着点这么多下……家慧，你有心事？",
    10: "{name}：十下了。说吧，找我什么事。",
    20: "{name}：二十下。好，我认真听着。",
}

# 各状态台词
SPEECHES = {
    "idle": "{name}：嗯？找我有事？",
    "wave": "{name}：家慧，你来了。",
    "think": "{name}：让我想想……",
    "walk": "{name}：走两步，透透气。",
    "run": "{name}：风正好，跑起来。",
    "sit": "{name}：坐一会儿，陪我聊聊天。",
    "stretch": "{name}：舒展一下，肩颈轻松多了。",
    "sleep": "{name}：Zzz……别吵醒我。",
    "surprise": "{name}：！怎么突然……",
    "bow": "{name}：请多指教。",
}

# 托盘菜单文案（角色化动词短语）
MENU = {
    "interact": "和他互动",
    "double_click": "拍拍肩（双击）",
    "long_press": "安静陪伴（长按）",
    "feed": "请他吃甜品",
    "wave": "看他挥手",
    "think": "看他思考",
    "walk": "陪他散步",
    "run": "约他跑步",
    "sit": "让他坐下歇会儿",
    "stretch": "看他伸懒腰",
    "surprise": "吓他一跳",
    "bow": "看他鞠躬",
    "sleep": "让他休息",
}


# 开机问候（按时间段）
def greeting_message(hour):
    if 6 <= hour < 11:
        return f"{CHARACTER_NAME}：早，{MASTER_NAME}。今天有什么安排？"
    elif 11 <= hour < 14:
        return f"{CHARACTER_NAME}：中午了，{MASTER_NAME}记得吃饭。"
    elif 14 <= hour < 18:
        return f"{CHARACTER_NAME}：下午好，{MASTER_NAME}。工作别太拼。"
    elif 18 <= hour < 22:
        return f"{CHARACTER_NAME}：晚上好，{MASTER_NAME}。今天辛苦了。"
    else:
        return f"{CHARACTER_NAME}：很晚了，{MASTER_NAME}早点休息。……我会在这里。"


class PetConfig:
    """祁煜的基本设定。"""

    def __init__(self):
        self.name = CHARACTER_NAME
        self.master = MASTER_NAME
        self.idle_to_sleep_sec = 120
        self.mood_decay_sec = 60       # 心情每 60 秒衰减 1 点
        self.mood_click_gain = 5       # 每次互动 +5 心情
        self.mood_max = 100

    @property
    def poses(self):
        return POSES

    @property
    def menu(self):
        return MENU

    def pose_file(self, state):
        """状态名 -> 动作文件名（单角色，一一对应）。"""
        return STATE_TO_POSE.get(state, state)


class PetFSM:
    """状态机 + 心情系统 + 互动入口。

    互动入口：on_click / on_double_click（拍拍肩） / on_pet（安静陪伴） /
    on_feed（请他吃甜品） / on_key
    每帧调用 tick 推进状态。
    """

    # 键盘快捷键 -> 动作
    KEY_MAP = {
        "space": "wave",   # 挥手问好
        "w": "walk",       # 散步
        "r": "run",        # 跑步
        "s": "sleep",      # 休息
        "f": "bow",        # 鞠躬
        "h": "think",      # 思考
        "y": "stretch",    # 伸懒腰
        "e": "sit",        # 坐下
    }

    def __init__(self, config=None, time_fn=None, rng=None, hour_fn=None):
        self.config = config or PetConfig()
        self.time_fn = time_fn or (lambda: 0.0)
        self.rng = rng or __import__("random").Random()
        self.hour_fn = hour_fn or (lambda: datetime.datetime.now().hour)
        self.state = "idle"
        self.last_interaction = self.time_fn()
        self.state_until = 0.0

        # 心情系统
        self.mood = 50
        self._last_mood_update = self.time_fn()
        self.interaction_count = 0
        self.combo_count = 0          # 连续点击计数
        self._last_click_time = 0.0

    # ---- 心情 ----
    def _update_mood(self, now):
        elapsed = now - self._last_mood_update
        decay = int(elapsed / self.config.mood_decay_sec)
        if decay > 0:
            self.mood = max(0, self.mood - decay)
            self._last_mood_update = now
        return self.mood

    def _gain_mood(self, amount):
        self.mood = min(self.config.mood_max, self.mood + amount)

    def mood_label(self):
        if self.mood >= 75:
            return "开心"
        elif self.mood >= 40:
            return "平静"
        elif self.mood >= 15:
            return "无聊"
        else:
            return "想睡觉"

    # ---- 互动入口 ----
    def on_click(self, now=None):
        """单击：随机反应 + 连击计数。"""
        if now is None:
            now = self.time_fn()
        self.last_interaction = now
        self._update_mood(now)
        self._gain_mood(self.config.mood_click_gain)
        self.interaction_count += 1

        # 连击计数（2 秒内连续点击）
        if now - self._last_click_time < 2.0:
            self.combo_count += 1
        else:
            self.combo_count = 1
        self._last_click_time = now

        # 连击里程碑
        combo_speech = ""
        if self.combo_count in COMBO_LINES:
            combo_speech = COMBO_LINES[self.combo_count].format(name=self.config.name)

        self.state = self.rng.choice(self.config.click_reactions
                                     if hasattr(self.config, "click_reactions")
                                     else CLICK_REACTIONS)
        dur = STATE_DURATION.get(self.state, 3.0)
        self.state_until = now + dur

        speech = self.speech(self.state)
        if combo_speech:
            speech = combo_speech
        return self.state, speech

    def on_double_click(self, now=None):
        """双击 → 拍拍肩（惊讶 + 台词）。"""
        if now is None:
            now = self.time_fn()
        self.last_interaction = now
        self._update_mood(now)
        self._gain_mood(self.config.mood_click_gain + 3)
        self.interaction_count += 1
        self.state = "surprise"
        self.state_until = now + STATE_DURATION["surprise"]
        speech = self.rng.choice(SHOULDER_PAT_LINES).format(name=self.config.name)
        return self.state, speech

    def on_pet(self, now=None):
        """长按 → 安静陪伴（思考 + 台词）。"""
        if now is None:
            now = self.time_fn()
        self.last_interaction = now
        self._update_mood(now)
        self._gain_mood(self.config.mood_click_gain + 2)
        self.interaction_count += 1
        self.state = "think"
        self.state_until = now + STATE_DURATION["think"]
        speech = self.rng.choice(COMPANY_LINES).format(name=self.config.name)
        return self.state, speech

    def on_feed(self, now=None):
        """请他吃甜品 → 鞠躬（谢意）。"""
        if now is None:
            now = self.time_fn()
        self.last_interaction = now
        self._update_mood(now)
        self._gain_mood(self.config.mood_click_gain + 5)
        self.interaction_count += 1
        self.state = "bow"
        self.state_until = now + STATE_DURATION["bow"]
        speech = self.rng.choice(DESSERT_LINES).format(name=self.config.name)
        return self.state, speech

    def on_key(self, key, now=None):
        """键盘快捷键。"""
        key = key.lower()
        target = self.KEY_MAP.get(key)
        if target is None:
            return self.state, ""
        if now is None:
            now = self.time_fn()
        self.last_interaction = now
        self._update_mood(now)
        self._gain_mood(self.config.mood_click_gain)
        self.interaction_count += 1
        self.state = target
        if target == "sleep":
            self.state_until = 0  # sleep 不自动过期
        else:
            self.state_until = now + STATE_DURATION.get(target, 3.0)
        return self.state, self.speech(target)

    # ---- 台词 ----
    def speech(self, state):
        line = SPEECHES.get(state, "")
        if line:
            return line.format(name=self.config.name)
        return line

    # ---- 时间感知 ----
    def time_aware_state(self):
        """根据当前时间段返回建议动作（用于自发行为）。"""
        hour = self.hour_fn()
        if 6 <= hour < 11:
            return self.rng.choice(["wave", "walk", "stretch"])
        elif 11 <= hour < 14:
            return self.rng.choice(["sit", "stretch", "think"])
        elif 14 <= hour < 18:
            return self.rng.choice(["walk", "run", "think"])
        elif 18 <= hour < 22:
            return self.rng.choice(["think", "sit", "wave"])
        else:
            return "sleep"

    # ---- 每帧推进 ----
    def tick(self, now=None):
        if now is None:
            now = self.time_fn()
        prev = self.state
        self._update_mood(now)

        # 临时动作到期回到 idle（sleep 特殊：不自动过期）
        if (self.state not in ("idle", "sleep")
                and self.state_until
                and now >= self.state_until):
            self.state = "idle"
        # 休息中被互动打断
        if self.state == "sleep" and (now - self.last_interaction) < 2.0:
            self.state = "idle"
        # idle 闲置逻辑：超时休息（心情低时更容易休息）
        if self.state == "idle":
            sleep_threshold = self.config.idle_to_sleep_sec
            if self.mood < 20:
                sleep_threshold = max(30, sleep_threshold // 3)
            if (now - self.last_interaction) > sleep_threshold:
                self.state = "sleep"
        return self.state, (self.state != prev)

    def pose(self):
        return self.config.pose_file(self.state)


class BreakSettings:
    """久坐提醒设置 + 起身统计（JSON 持久化，无 Qt 依赖）。

    - 预设节奏：45/3、60/5、30/2（久坐分钟/活动分钟），也可自定义
    - sound_enabled：到点提示音；fullscreen_mode：全屏强制提醒（默认关）
    - idle_away_min：离座判定阈值（闲置超此分钟视为已起身，自动重新计时）
    - stats：今日/累计起身次数，跨天自动清零当日计数
    - 设置与统计自动保存，下次打开记忆生效
    """

    PRESETS = {"45/3": (45, 3), "60/5": (60, 5), "30/2": (30, 2)}

    def __init__(self, store_path=None):
        self.store_path = store_path  # None 时不持久化
        self.sit_min = 45
        self.activity_min = 3
        self.sound_enabled = True
        self.fullscreen_mode = False
        self.idle_away_min = 10
        self.preset = "45/3"
        self.stats = {"date": "", "today": 0, "total": 0}
        self.load()

    def apply_preset(self, key):
        if key in self.PRESETS:
            self.sit_min, self.activity_min = self.PRESETS[key]
            self.preset = key
            self.save()
            return True
        return False

    def set_custom(self, sit_min, activity_min):
        """自定义节奏（限 1~180 / 1~60 分钟），非预设组合标记为 custom。"""
        self.sit_min = min(180, max(1, int(sit_min)))
        self.activity_min = min(60, max(1, int(activity_min)))
        self.preset = f"{self.sit_min}/{self.activity_min}" \
            if (self.sit_min, self.activity_min) in self.PRESETS.values() else "custom"
        self.save()

    def bump_standup(self, now=None):
        """记一次起身（「我已起身」或离座自动识别）。"""
        now = now or datetime.datetime.now()
        today = now.strftime("%Y-%m-%d")
        if self.stats.get("date") != today:
            self.stats = {"date": today, "today": 0,
                          "total": self.stats.get("total", 0)}
        self.stats["today"] += 1
        self.stats["total"] += 1
        self.save()

    # ---- 持久化 ----
    def _payload(self):
        return {"settings": {
                    "sit_min": self.sit_min, "activity_min": self.activity_min,
                    "sound_enabled": self.sound_enabled,
                    "fullscreen_mode": self.fullscreen_mode,
                    "idle_away_min": self.idle_away_min, "preset": self.preset},
                "stats": dict(self.stats)}

    def save(self):
        if not self.store_path:
            return
        try:
            d = os.path.dirname(self.store_path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump(self._payload(), f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    def load(self):
        if not self.store_path or not os.path.exists(self.store_path):
            return
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            s = data.get("settings", {})
            self.sit_min = s.get("sit_min", 45)
            self.activity_min = s.get("activity_min", 3)
            self.sound_enabled = s.get("sound_enabled", True)
            self.fullscreen_mode = s.get("fullscreen_mode", False)
            self.idle_away_min = s.get("idle_away_min", 10)
            self.preset = s.get("preset", "45/3")
            st = data.get("stats", {})
            if isinstance(st, dict):
                self.stats = {"date": st.get("date", ""),
                              "today": st.get("today", 0),
                              "total": st.get("total", 0)}
        except (OSError, ValueError):
            pass  # 文件损坏时按默认值处理


class BreakScheduler:
    """久坐/活动两阶段调度（环形倒计时等 UI 的数据源，无 Qt 依赖）。

    - sitting：久坐计时，到点产生一次 "sit_due" 事件（等弹窗处理：
      我已起身 / 稍后 5 分钟，自动推迟由界面层负责）
    - activity：休息倒计时，结束产生 "activity_done" 并自动进入下一轮久坐
    - 离座识别：sitting 阶段闲置超过 idle_away_min 分钟 → 视为已起身，
      产生 "away_reset" 事件、计入起身次数并重新计时
    - tick 返回 {phase, seconds_left, progress, warning, events}：
      progress 为已流逝比例（环形填充），warning=快到点（橙色警示）
    """

    WARN_SIT_SEC = 120  # 久坐快到点（橙色警示）阈值

    def __init__(self, settings, time_fn=None):
        self.settings = settings
        self.time_fn = time_fn or (lambda: _time.time())
        self.phase = "sitting"
        self.sit_deadline = self.time_fn() + settings.sit_min * 60
        self.activity_deadline = 0.0
        self.due_reported = False
        self.away_reported = False  # 一段离座期间只记一次起身/报一次事件

    def _now(self):
        return self.time_fn()

    def snooze(self, minutes):
        """稍后提醒：从当前时间起再等 minutes 分钟。"""
        now = self._now()
        self.sit_deadline = max(self.sit_deadline, now) + minutes * 60
        self.due_reported = False

    def start_activity(self):
        """我已起身 → 进入活动倒计时，并计入起身次数。"""
        now = self._now()
        self.phase = "activity"
        self.activity_deadline = now + self.settings.activity_min * 60
        self.due_reported = False
        self.settings.bump_standup(datetime.datetime.fromtimestamp(now))

    def _reset_sit(self, now):
        self.phase = "sitting"
        self.sit_deadline = now + self.settings.sit_min * 60
        self.due_reported = False

    def restart(self):
        """设置变更后立即生效：按当前节奏重新计时。"""
        self._reset_sit(self._now())
        self.away_reported = False

    def _state(self, phase, seconds_left, events):
        total = (self.settings.sit_min if phase == "sitting"
                 else self.settings.activity_min) * 60
        seconds_left = max(0, int(round(seconds_left)))
        progress = min(1.0, max(0.0, 1.0 - seconds_left / total))
        warning = phase == "sitting" and 0 < seconds_left <= self.WARN_SIT_SEC
        return {"phase": phase, "seconds_left": seconds_left,
                "progress": progress, "warning": warning, "events": events}

    def tick(self, now=None, idle_sec=0.0):
        events = []
        if now is None:
            now = self._now()
        if self.phase == "sitting":
            if idle_sec >= self.settings.idle_away_min * 60:
                # 离座期间持续顺延计时（回来后重新计），但起身只记一次
                if not self.away_reported:
                    self.away_reported = True
                    self.settings.bump_standup(datetime.datetime.fromtimestamp(now))
                    events.append("away_reset")
                self._reset_sit(now)
                return self._state("sitting", self.sit_deadline - now, events)
            self.away_reported = False
            left = self.sit_deadline - now
            if left <= 0:
                if not self.due_reported:
                    self.due_reported = True
                    events.append("sit_due")
                return self._state("sitting", 0, events)
            return self._state("sitting", left, events)
        # activity 阶段
        left = self.activity_deadline - now
        if left <= 0:
            self._reset_sit(now)
            events.append("activity_done")
            return self._state("sitting", self.sit_deadline - now, events)
        return self._state("activity", left, events)


class TimedReminder:
    """定时提醒：用户自定义 HH:MM + 提醒内容，每天到点触发一次。

    - 同一时间的旧提醒会被新提醒覆盖
    - 每条提醒每天最多触发一次（按日期去重）
    - 触发后有 CATCHUP_MIN 分钟追补窗口（应用刚启动时不会漏掉刚过的点）
    - 提醒列表持久化到 JSON 文件，重启后保留
    """

    CATCHUP_MIN = 15  # 追补窗口（分钟）

    def __init__(self, config, time_fn=None, store_path=None):
        self.config = config
        self.time_fn = time_fn or (lambda: _time.time())
        self.store_path = store_path  # None 时不持久化
        self.reminders = []  # [{"time": "HH:MM", "text": str, "last_fired": "YYYY-MM-DD"}]
        self.load()

    # ---- 增删查 ----
    @staticmethod
    def _norm_hhmm(hhmm):
        """归一化时间字符串，合法返回 'HH:MM'，否则返回 None。"""
        if not isinstance(hhmm, str):
            return None
        s = hhmm.strip().replace("：", ":")
        for sep in (":",):
            parts = s.split(sep)
            if len(parts) != 2:
                continue
            try:
                h, m = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            if 0 <= h <= 23 and 0 <= m <= 59:
                return f"{h:02d}:{m:02d}"
        return None

    def add(self, hhmm, text):
        """添加（或覆盖同一时间的）提醒。成功返回 True。"""
        t = self._norm_hhmm(hhmm)
        text = (text or "").strip()
        if t is None or not text:
            return False
        self.remove(t)
        self.reminders.append({"time": t, "text": text, "last_fired": ""})
        self.reminders.sort(key=lambda r: r["time"])
        self.save()
        return True

    def remove(self, hhmm):
        """删除指定时间的提醒，返回是否删除了至少一条。"""
        t = self._norm_hhmm(hhmm) or hhmm
        before = len(self.reminders)
        self.reminders = [r for r in self.reminders if r["time"] != t]
        changed = len(self.reminders) < before
        if changed:
            self.save()
        return changed

    def clear(self):
        self.reminders = []
        self.save()

    def items(self):
        return [dict(r) for r in self.reminders]

    # ---- 触发检查 ----
    def check(self, now=None):
        """返回本轮触发的提醒文本列表（已标记当天已触发）。"""
        if now is None:
            now = self._now()
        elif isinstance(now, (int, float)):
            now = datetime.datetime.fromtimestamp(now)
        today = now.strftime("%Y-%m-%d")
        fired = []
        for r in self.reminders:
            if r.get("last_fired") == today:
                continue
            try:
                rt = datetime.datetime.strptime(r["time"], "%H:%M").time()
            except ValueError:
                continue
            due_dt = now.replace(hour=rt.hour, minute=rt.minute, second=0, microsecond=0)
            delta_min = (now - due_dt).total_seconds() / 60.0
            if 0 <= delta_min <= self.CATCHUP_MIN:
                r["last_fired"] = today
                fired.append(f"⏰ {self.config.name}的定时提醒：{r['text']}")
        if fired:
            self.save()
        return fired

    # ---- 持久化 ----
    def save(self):
        if not self.store_path:
            return
        try:
            d = os.path.dirname(self.store_path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump(self.reminders, f, ensure_ascii=False, indent=1)
        except OSError:
            pass  # 持久化失败不影响运行

    def load(self):
        if not self.store_path or not os.path.exists(self.store_path):
            return
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self.reminders = [
                    {"time": r.get("time", ""), "text": r.get("text", ""),
                     "last_fired": r.get("last_fired", "")}
                    for r in data if isinstance(r, dict)
                ]
        except (OSError, ValueError):
            pass  # 文件损坏时忽略，按空列表处理
