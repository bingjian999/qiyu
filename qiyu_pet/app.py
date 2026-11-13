"""祁煜桌面伙伴 · Qt 界面层。

祁煜是《恋与深空》中的人形角色——桌面上的他是"人"：
- 单击互动、双击拍拍肩、长按安静陪伴、请他吃甜品
- 键盘快捷键、开机问候、心情显示
- 久坐提醒（环形倒计时 + 设置面板 + 到点弹窗）
- 定时提醒（HH:MM 自定义，每天到点触发）
"""

import os
import sys
import time
import datetime

from PySide6.QtCore import Qt, QTimer, QPoint, QRectF
from PySide6.QtGui import QPixmap, QFont, QCursor, QIcon, QColor, QPainter, QPen, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QWidget,
    QSystemTrayIcon,
    QMenu,
    QInputDialog,
    QDialog,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QSpinBox,
    QCheckBox,
    QRadioButton,
    QButtonGroup,
)

from .core import (
    PetConfig, PetFSM, TimedReminder, BreakSettings, BreakScheduler,
    POSES, STATE_DURATION,
    CHARACTER_NAME, MASTER_NAME, MENU, greeting_message,
    DESSERT_DONE_LINE,
)

SPRITE_DIR = os.path.join(os.path.dirname(__file__), "sprites")
# 显示尺寸：精灵原图为高分辨率，窗口缩小仅影响屏幕占位大小，
# SmoothTransformation 缩放下画质不受影响
PET_W, PET_H = 220, 324

# 祁煜精灵图已按 bbox 裁边（各图主体占比均为 1.0），无需归一系数
SPRITE_SCALE = {}


def _sprite_path(pose):
    """动作图片路径：sprites/qiyu/<pose>.png。"""
    return os.path.join(SPRITE_DIR, "qiyu", f"{pose}.png")


class SpeechBubble(QWidget):
    """祁煜头上的圆角台词气泡，自动消失。"""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet(
            "background: rgba(255,255,255,235);"
            "border-radius: 16px;"
            "padding: 10px 18px;"
            "color:#3a3050;"
            "border: 1px solid rgba(150,140,190,180);"
        )
        self.label.setFont(QFont("Microsoft YaHei", 10))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text, top_left, duration=4200):
        self.label.setText(text)
        self.label.adjustSize()
        w, h = self.label.width() + 4, self.label.height() + 4
        self.resize(w, h)
        self.label.setGeometry(0, 0, w, h)
        self.move(top_left)
        self.show()
        self.raise_()
        self._timer.start(duration)


class CountdownRing(QWidget):
    """环形进度倒计时小组件：久坐蓝 / 快到点橙 / 活动绿，点击打开设置面板。"""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(64, 64)
        self.setToolTip("久坐倒计时 · 点击打开设置")
        self.on_clicked = None
        self._phase = "sitting"
        self._seconds_left = 0
        self._progress = 0.0
        self._warning = False

    def update_state(self, phase, seconds_left, progress, warning):
        self._phase = phase
        self._seconds_left = seconds_left
        self._progress = progress
        self._warning = warning
        self.update()

    def mousePressEvent(self, e):
        if self.on_clicked:
            self.on_clicked()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(6.0, 6.0, 52.0, 52.0)
        # 底环
        p.setPen(QPen(QColor(255, 255, 255, 110), 6))
        p.drawEllipse(rect)
        # 进度环：久坐蓝 → 快到点橙；活动阶段绿
        if self._warning:
            color = QColor("#f39c12")
        elif self._phase == "activity":
            color = QColor("#27ae60")
        else:
            color = QColor("#5a6fd0")
        p.setPen(QPen(color, 6, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, 90 * 16, int(-360 * 16 * self._progress))
        # 中央剩余时间
        p.setPen(QColor("#3a3050"))
        p.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        m, s = divmod(int(self._seconds_left), 60)
        p.drawText(self.rect(), Qt.AlignCenter, f"{m:02d}:{s:02d}")
        p.end()


class BreakDialog(QWidget):
    """到点置顶提醒弹窗（可选全屏强制模式），60 秒未处理自动稍后 5 分钟。"""

    STYLE_WINDOW = """
        QWidget { background: rgba(250,250,255,250); border-radius: 14px;
                  border: 1px solid rgba(150,140,190,200); }
        QLabel#title { border: none; color:#3a3050; font-size:15px; font-weight:bold; }
        QLabel#count { border: none; color:#8a84a8; font-size:12px; }
        QPushButton { background:#5a6fd0; color:white; border:none;
                      border-radius:8px; padding:8px 16px; font-size:14px; }
        QPushButton#snooze { background:#9a94b8; }
    """
    STYLE_FULLSCREEN = """
        QWidget { background: rgba(24,22,36,235); }
        QLabel#title { border: none; color:#e9e6ff; font-size:32px; font-weight:bold; }
        QLabel#count { border: none; color:#9a94b8; font-size:18px; }
        QPushButton { background:#5a6fd0; color:white; border:none;
                      border-radius:10px; padding:14px 28px; font-size:20px; }
        QPushButton#snooze { background:#5a5a7a; }
    """

    def __init__(self, fullscreen=False):
        super().__init__()
        self._fullscreen = fullscreen
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        if fullscreen:
            self.setAttribute(Qt.WA_TranslucentBackground, False)
        else:
            self.setAttribute(Qt.WA_TranslucentBackground)
        self.on_rise = None
        self.on_snooze = None
        self._build_ui()
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._auto_snooze)
        self._count_timer = QTimer(self)
        self._count_timer.timeout.connect(self._tick_countdown)
        # 右上角关闭钮：等同「稍后 5 分钟」
        self._btn_close = QPushButton("×", self)
        self._btn_close.setFixedSize(28, 28)
        self._btn_close.setStyleSheet(
            "QPushButton { background: rgba(0,0,0,30); color:#8a84a8;"
            " border:none; border-radius:14px; font-size:16px; padding:0; }")
        self._btn_close.setToolTip("关闭（稍后 5 分钟再提醒）")
        self._btn_close.clicked.connect(self._on_snooze)

    def _build_ui(self):
        self.setStyleSheet(self.STYLE_FULLSCREEN if self._fullscreen
                           else self.STYLE_WINDOW)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)
        self._title = QLabel()
        self._title.setObjectName("title")
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setWordWrap(True)
        layout.addWidget(self._title)
        self._msg = QLabel()
        self._msg.setObjectName("count")
        self._msg.setAlignment(Qt.AlignCenter)
        self._msg.setWordWrap(True)
        layout.addWidget(self._msg)
        self._count = QLabel()
        self._count.setObjectName("count")
        self._count.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._count)
        row = QHBoxLayout()
        row.addStretch(1)
        btn_rise = QPushButton("我已起身")
        btn_rise.clicked.connect(self._on_rise)
        btn_snooze = QPushButton("稍后 5 分钟")
        btn_snooze.setObjectName("snooze")
        btn_snooze.clicked.connect(self._on_snooze)
        row.addWidget(btn_rise)
        row.addWidget(btn_snooze)
        row.addStretch(1)
        layout.addLayout(row)
        if self._fullscreen:
            self._title.setMinimumHeight(60)

    def popup(self, title, msg=""):
        self._title.setText(title)
        self._msg.setText(msg)
        self._msg.setVisible(bool(msg))
        self._left = 60
        self._count.setText("60 秒内不处理将自动稍后 5 分钟（60）")
        screen = QApplication.primaryScreen().availableGeometry()
        if self._fullscreen:
            self.setGeometry(screen)
        else:
            self.adjustSize()
            self.move(screen.center().x() - self.width() // 2,
                      screen.top() + 100)
        self.show()
        self.raise_()
        self.activateWindow()
        self._btn_close.move(self.width() - 34, 6)
        self._btn_close.raise_()
        self._btn_close.show()
        self._auto_timer.start(60000)
        self._count_timer.start(1000)

    def _tick_countdown(self):
        self._left -= 1
        if self._left > 0:
            self._count.setText(f"60 秒内不处理将自动稍后 5 分钟（{self._left}）")

    def _stop(self):
        self._auto_timer.stop()
        self._count_timer.stop()

    def _auto_snooze(self):
        self._on_snooze()

    def dismiss_without_action(self):
        """静默收起（离座自动重置时调用），不触发任何回调。"""
        self._stop()
        self.hide()

    def _on_rise(self):
        self._stop()
        self.hide()
        if self.on_rise:
            self.on_rise()

    def _on_snooze(self):
        self._stop()
        self.hide()
        if self.on_snooze:
            self.on_snooze()


class BreakSettingsPanel(QWidget):
    """久坐提醒设置面板（屏幕右侧弹出）：预设节奏 / 自定义 / 提示音 / 全屏模式 / 统计。"""

    STYLE = """
        QWidget { background: rgba(250,250,255,252); border-radius: 12px;
                  border: 1px solid rgba(150,140,190,200); color:#3a3050; }
        QLabel { border: none; font-size:13px; }
        QLabel#head { font-size:15px; font-weight:bold; }
        QPushButton { background:#9a94b8; color:white; border:none;
                      border-radius:6px; padding:4px 10px; font-size:12px; }
        QRadioButton, QCheckBox { border: none; font-size:13px; }
        QSpinBox { background: white; border:1px solid #9a94b8; border-radius:4px;
                   padding:2px; }
    """

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.on_settings_changed = None  # 节奏/阈值变更后的回调（重启调度）
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint
                            | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(self.STYLE)
        self.setFixedWidth(260)
        self._build_ui()

    def _build_ui(self):
        s = self.settings
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        head_row = QHBoxLayout()
        head = QLabel("久坐提醒设置")
        head.setObjectName("head")
        head_row.addWidget(head)
        head_row.addStretch(1)
        btn_close = QPushButton("×")
        btn_close.setFixedSize(24, 24)
        btn_close.setStyleSheet("padding:0; font-size:14px;")
        btn_close.setToolTip("关闭设置面板")
        btn_close.clicked.connect(self.hide)
        head_row.addWidget(btn_close)
        layout.addLayout(head_row)

        # 预设节奏
        row = QHBoxLayout()
        row.addWidget(QLabel("预设节奏"))
        self._preset_group = QButtonGroup(self)
        self._preset_buttons = {}
        for key in BreakSettings.PRESETS:
            rb = QRadioButton(key)
            rb.toggled.connect(lambda on, k=key: self._on_preset(k, on))
            self._preset_group.addButton(rb)
            row.addWidget(rb)
            self._preset_buttons[key] = rb
        row.addStretch(1)
        layout.addLayout(row)
        self._preset_buttons.get(s.preset).setChecked(True) \
            if s.preset in self._preset_buttons else None

        # 自定义时长
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("自定义"))
        row2.addWidget(QLabel("久坐"))
        self._sit_spin = QSpinBox()
        self._sit_spin.setRange(1, 180)
        self._sit_spin.setValue(s.sit_min)
        self._sit_spin.setSuffix(" 分")
        self._sit_spin.valueChanged.connect(self._on_custom)
        row2.addWidget(self._sit_spin)
        row2.addWidget(QLabel("活动"))
        self._act_spin = QSpinBox()
        self._act_spin.setRange(1, 60)
        self._act_spin.setValue(s.activity_min)
        self._act_spin.setSuffix(" 分")
        self._act_spin.valueChanged.connect(self._on_custom)
        row2.addWidget(self._act_spin)
        layout.addLayout(row2)

        # 离座判定
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("离座判定（闲置）"))
        self._away_spin = QSpinBox()
        self._away_spin.setRange(5, 60)
        self._away_spin.setValue(s.idle_away_min)
        self._away_spin.setSuffix(" 分")
        self._away_spin.valueChanged.connect(self._on_away)
        row3.addStretch(1)
        layout.addLayout(row3)

        # 开关
        self._sound_cb = QCheckBox("到点提示音")
        self._sound_cb.setChecked(s.sound_enabled)
        self._sound_cb.toggled.connect(self._on_sound)
        layout.addWidget(self._sound_cb)
        self._fs_cb = QCheckBox("全屏强制提醒模式（默认关）")
        self._fs_cb.setChecked(s.fullscreen_mode)
        self._fs_cb.toggled.connect(self._on_fullscreen)
        layout.addWidget(self._fs_cb)

        # 统计
        self._stats_label = QLabel()
        layout.addWidget(self._stats_label)
        self.refresh_stats()

    # ---- 事件 ----
    def _on_preset(self, key, on):
        if on:
            self.settings.apply_preset(key)
            sit, act = BreakSettings.PRESETS[key]
            self._sit_spin.blockSignals(True)
            self._act_spin.blockSignals(True)
            self._sit_spin.setValue(sit)
            self._act_spin.setValue(act)
            self._sit_spin.blockSignals(False)
            self._act_spin.blockSignals(False)
            self._notify_changed()

    def _on_custom(self):
        # 防止预设联动触发时重复写盘（值一致时无副作用）
        if (self._sit_spin.value() != self.settings.sit_min
                or self._act_spin.value() != self.settings.activity_min):
            self.settings.set_custom(self._sit_spin.value(), self._act_spin.value())
            key = self.settings.preset
            if key in self._preset_buttons:
                self._preset_buttons[key].setChecked(True)
            self._notify_changed()

    def _on_away(self):
        self.settings.idle_away_min = self._away_spin.value()
        self.settings.save()
        self._notify_changed()

    def _notify_changed(self):
        """设置变更 → 通知外层重启调度，让新节奏立即生效。"""
        if self.on_settings_changed:
            self.on_settings_changed()

    def _on_sound(self, on):
        self.settings.sound_enabled = on
        self.settings.save()

    def _on_fullscreen(self, on):
        self.settings.fullscreen_mode = on
        self.settings.save()

    # ---- 对外 ----
    def refresh_stats(self):
        s = self.settings.stats
        self._stats_label.setText(
            f"今日起身 {s.get('today', 0)} 次 · 累计 {s.get('total', 0)} 次")


class PetWindow(QWidget):
    def __init__(self, config=None):
        super().__init__()
        self.config = config or PetConfig()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(PET_W, PET_H)

        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setGeometry(0, 0, PET_W, PET_H)

        self.sprites = {}
        for p in POSES:
            pix = QPixmap(_sprite_path(p))
            if not pix.isNull():
                # 精灵图已按主体裁边，直接缩到窗口尺寸即可（预处理一次缓存）
                pix = pix.scaled(self.size(), Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation)
            self.sprites[p] = pix

        self.fsm = PetFSM(
            self.config,
            time_fn=time.time,
            hour_fn=lambda: datetime.datetime.now().hour,
        )
        # 久坐提醒：设置（持久化）+ 两阶段调度 + 环形倒计时 + 弹窗 + 设置面板
        self.break_settings = BreakSettings(
            store_path=os.path.join(os.path.expanduser("~"), ".qiyu_pet_break.json"))
        self.breaker = BreakScheduler(self.break_settings, time_fn=time.time)
        self.ring = CountdownRing()
        self.ring.on_clicked = self._toggle_break_panel
        self.ring.show()
        self.break_panel = BreakSettingsPanel(self.break_settings)
        self.break_panel.on_settings_changed = self._on_break_settings_changed
        self.break_dlg = BreakDialog(fullscreen=False)
        self.break_dlg_full = BreakDialog(fullscreen=True)
        for dlg in (self.break_dlg, self.break_dlg_full):
            dlg.on_rise = self._on_rise
            dlg.on_snooze = self._on_break_snooze
        self.timed = TimedReminder(
            self.config,
            time_fn=time.time,
            store_path=os.path.join(os.path.expanduser("~"), ".qiyu_pet_reminders.json"),
        )
        self.bubble = SpeechBubble()

        # 离座识别兜底：光标位置启发（Windows 上优先用系统最后输入时间）
        self._last_cursor_pos = None
        self._last_cursor_move = time.time()
        self._drag_offset = None
        self._press_time = 0.0
        self._press_pos = None
        self._dragged = False
        self._cur_pose = None
        self.set_pose("idle")

        # 单击/双击区分：release 后延迟 400ms 触发单击互动，
        # 期间若发生双击则取消（双击走拍拍肩）
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._do_interact)

        # 状态机推进
        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.on_tick)
        self.tick_timer.start(900)

        # 久坐提醒推进（1 秒一拍：环形倒计时 / 警示 / 到点弹窗 / 离座重置）
        self.break_timer = QTimer(self)
        self.break_timer.timeout.connect(self.on_break_tick)
        self.break_timer.start(1000)

        # 定时提醒检查（每 1 分钟一拍）
        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self.on_reminder_check)
        self.reminder_timer.start(60000)

        # 随机自发行为（每 2~5 分钟）
        self.romp_timer = QTimer(self)
        self.romp_timer.setSingleShot(True)
        self.romp_timer.timeout.connect(self.on_romp)
        self.romp_timer.start(120000)

        # 长按检测定时器（800ms → 安静陪伴）
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._on_hold)

        # 心情显示定时器（每 30 秒更新托盘 tooltip）
        self._mood_timer = QTimer(self)
        self._mood_timer.timeout.connect(self._update_mood_tooltip)
        self._mood_timer.start(30000)

        self._setup_tray()
        self._setup_shortcuts()
        self._place_bottom_right()
        self.show()

        # 开机问候
        QTimer.singleShot(800, self._greeting)

    # ---- 显示 ----
    def set_pose(self, pose):
        pix = self.sprites.get(pose)
        if pose == self._cur_pose:
            return
        self._cur_pose = pose
        if pix is None or pix.isNull():
            return
        self.label.setPixmap(pix)

    # ---- 状态机 / 提醒 ----
    def on_tick(self):
        state, changed = self.fsm.tick()
        if changed:
            self.set_pose(self.fsm.pose())

    def on_reminder_check(self):
        # 用户自定义定时提醒（每分钟检查一次）
        for text in self.timed.check():
            self._notify_reminder(text)

    # ---- 久坐提醒 ----
    def on_break_tick(self):
        idle = self._idle_seconds()
        st = self.breaker.tick(now=time.time(), idle_sec=idle)
        self.ring.update_state(st["phase"], st["seconds_left"], st["progress"], st["warning"])
        if "away_reset" in st["events"]:
            # 电脑闲置超阈值视为已起身：收起弹窗、刷新统计
            self.break_dlg.dismiss_without_action()
            self.break_dlg_full.dismiss_without_action()
            self.break_panel.refresh_stats()
            self.show_bubble("离开了一会儿，久坐计时重新开始了。")
        if "sit_due" in st["events"]:
            self._show_break_dialog()
        if "activity_done" in st["events"]:
            self.set_pose("wave")
            self.show_bubble("休息结束，继续加油。")
            self.break_panel.refresh_stats()

    def _idle_seconds(self):
        """离座识别：Windows 用系统最后输入时间；其他平台用光标位置变化兜底。"""
        if sys.platform == "win32":
            try:
                import ctypes

                class LASTINPUTINFO(ctypes.Structure):
                    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

                lii = LASTINPUTINFO()
                lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
                if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                    tick = ctypes.windll.kernel32.GetTickCount()
                    elapsed = (tick - lii.dwTime) / 1000.0
                    # GetTickCount 约 49.7 天回绕
                    if 0 <= elapsed < 49 * 24 * 3600:
                        return elapsed
            except Exception:
                pass
        # 兜底：光标位置长时间未变视为闲置
        try:
            pos = QCursor.pos()
        except Exception:
            return 0.0
        if pos != self._last_cursor_pos:
            self._last_cursor_pos = pos
            self._last_cursor_move = time.time()
        return max(0.0, time.time() - self._last_cursor_move)

    def _show_break_dialog(self):
        if self.break_settings.sound_enabled:
            QApplication.beep()
        title = "该起身活动啦！已连续久坐 {} 分钟".format(self.break_settings.sit_min)
        msg = "站起来活动 {} 分钟，舒展一下肩颈。".format(self.break_settings.activity_min)
        dlg = self.break_dlg_full if self.break_settings.fullscreen_mode else self.break_dlg
        dlg.popup(title, msg)
        self.set_pose("wave")
        self.show_bubble("家慧，该起身活动了。", duration=8000)
        # 双通道兜底：气泡可能一闪而过，托盘通知会留在系统通知中心
        if hasattr(self, "tray"):
            self.tray.showMessage(f"{self.config.name} · 久坐提醒", title + " " + msg,
                                  QSystemTrayIcon.Information, 8000)

    def _on_break_settings_changed(self):
        """面板改了节奏/阈值 → 立即按新设置重新计时，并给明确反馈。"""
        self.breaker.restart()
        s = self.break_settings
        self.show_bubble(
            "好，按 {} 分钟久坐 + {} 分钟活动重新计时。".format(s.sit_min, s.activity_min))

    def _on_rise(self):
        self.breaker.start_activity()
        self.break_panel.refresh_stats()
        self.set_pose("stretch")
        self.show_bubble("很好，动起来。活动 {} 分钟。".format(self.break_settings.activity_min))

    def _on_break_snooze(self):
        self.breaker.snooze(5)
        self.show_bubble("好，5 分钟后再提醒你。")

    def _toggle_break_panel(self):
        if self.break_panel.isVisible():
            self.break_panel.hide()
        else:
            self.break_panel.refresh_stats()
            geo = self.break_panel.frameGeometry()
            screen = QApplication.primaryScreen().availableGeometry()
            self.break_panel.move(screen.right() - geo.width() - 8,
                                  screen.bottom() - geo.height() - 8)
            self.break_panel.show()
            self.break_panel.raise_()

    def _place_ring(self):
        """把环形倒计时放到祁煜头顶右上方。"""
        geo = self.frameGeometry()
        self.ring.move(geo.x() + geo.width() + 2, geo.y() - 4)

    def on_romp(self):
        """自发行为：根据时间和心情选择动作。"""
        # 心情低 → 更可能伸展/休息
        if self.fsm.mood < 25:
            state = "stretch"
            speech = self.fsm.speech("stretch")
        else:
            state = self.fsm.time_aware_state()
            speech = self.fsm.speech(state)
        now = time.time()
        self.fsm.state = state
        self.fsm.last_interaction = now
        self.fsm.state_until = now + STATE_DURATION.get(state, 3.0)
        self.set_pose(state)
        self.show_bubble(speech)
        import random
        self.romp_timer.start(int(random.uniform(120, 300)) * 1000)

    # ---- 交互 ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_time = time.time()
            self._press_pos = e.globalPosition().toPoint()
            self._dragged = False
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            # 启动长按检测
            self._hold_timer.start(800)

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and (e.buttons() & Qt.LeftButton):
            # 移动超过 5px 算拖动，取消长按
            if (e.globalPosition().toPoint() - self._press_pos).manhattanLength() > 5:
                self._dragged = True
                self._hold_timer.stop()
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            self._place_ring()

    def mouseReleaseEvent(self, e):
        self._hold_timer.stop()
        if not self._dragged and self._press_time > 0:
            # 短按 → 延迟 400ms 判定单击（双击事件会取消此定时器）
            self._click_timer.start(400)
        self._drag_offset = None
        self._press_time = 0.0

    def mouseDoubleClickEvent(self, e):
        """双击 → 拍拍肩。"""
        if e.button() == Qt.LeftButton:
            self._hold_timer.stop()
            self._click_timer.stop()
            self._press_time = 0.0
            state, speech = self.fsm.on_double_click()
            self.set_pose(state)
            self.show_bubble(speech)

    def _on_hold(self):
        """长按 800ms → 安静陪伴。"""
        if not self._dragged:
            state, speech = self.fsm.on_pet()
            self.set_pose(state)
            self.show_bubble(speech)

    def contextMenuEvent(self, e):
        self._hold_timer.stop()
        # 更新动态菜单项
        self._act_mood.setText(f"心情：{self.fsm.mood_label()}({self.fsm.mood})")
        self._act_stats.setText(f"互动次数：{self.fsm.interaction_count}")
        self._menu.exec(e.globalPos())

    # ---- 气泡 / 快捷键 / 托盘 ----
    def show_bubble(self, text, duration=4200):
        """在祁煜头部上方显示台词气泡。"""
        if not text:
            return
        pt = self.mapToGlobal(QPoint(0, 0))
        bx = pt.x() + self.width() // 2 - 50
        by = pt.y() - 50
        self.bubble.show_message(text, QPoint(bx, by), duration)

    @staticmethod
    def _key_to_seq(key):
        """按键名 → QKeySequence 字符串。"""
        mapping = {
            "space": "Space",
            "w": "W", "r": "R", "s": "S", "f": "F",
            "h": "H", "y": "Y", "e": "E",
        }
        return mapping.get(key, key.capitalize())

    def _setup_shortcuts(self):
        """注册键盘快捷键。"""
        for key, target in self.fsm.KEY_MAP.items():
            seq = self._key_to_seq(key)
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(lambda t=target: self._do_key(t))
            setattr(self, f"_sc_{key}", sc)

    def _do_key(self, target):
        """键盘快捷键触发。"""
        state, speech = self.fsm.on_key(target)
        if state:
            self.set_pose(state)
            self.show_bubble(speech)

    def _greeting(self):
        """开机问候。"""
        self.show_bubble(greeting_message(self.fsm.hour_fn()), duration=5000)

    def _update_mood_tooltip(self):
        """更新托盘 tooltip 显示心情和互动次数。"""
        tip = f"{self.config.name} | 心情：{self.fsm.mood_label()}({self.fsm.mood}) | 互动：{self.fsm.interaction_count}次"
        if hasattr(self, "tray"):
            self.tray.setToolTip(tip)

    def _setup_tray(self):
        """创建系统托盘菜单。"""
        self.tray = QSystemTrayIcon(self)
        icon_path = os.path.join(SPRITE_DIR, "icon.ico")
        if os.path.exists(icon_path):
            self.tray.setIcon(QIcon(icon_path))
        else:
            # 无图标文件时用待机帧顶替，保证托盘可见
            pix = QPixmap(_sprite_path("idle"))
            if not pix.isNull():
                self.tray.setIcon(QIcon(pix.scaled(48, 48)))
        self.tray.setToolTip(f"{self.config.name} | 桌面伙伴")

        m = QMenu()

        # 互动组
        m.addAction(MENU["interact"]).triggered.connect(self._do_interact)
        m.addAction(MENU["double_click"]).triggered.connect(self._do_shoulder_pat)
        m.addAction(MENU["long_press"]).triggered.connect(self._do_pet)
        m.addAction(MENU["feed"]).triggered.connect(self._do_feed)
        m.addSeparator()

        # 动作组
        m.addAction(MENU["wave"]).triggered.connect(self._do_wave)
        m.addAction(MENU["think"]).triggered.connect(self._do_think)
        m.addAction(MENU["walk"]).triggered.connect(self._do_walk)
        m.addAction(MENU["run"]).triggered.connect(self._do_run)
        m.addAction(MENU["sit"]).triggered.connect(self._do_sit)
        m.addAction(MENU["stretch"]).triggered.connect(self._do_stretch)
        m.addAction(MENU["surprise"]).triggered.connect(self._do_surprise)
        m.addAction(MENU["bow"]).triggered.connect(self._do_bow)
        m.addSeparator()

        # 功能组
        m.addAction("久坐提醒设置").triggered.connect(self._toggle_break_panel)
        timed_menu = m.addMenu("定时提醒")
        timed_menu.addAction("添加提醒…").triggered.connect(self._add_timed_reminder)
        timed_menu.addAction("管理提醒…").triggered.connect(self._manage_timed_reminders)
        m.addAction("让他休息").triggered.connect(self._do_sleep)
        m.addSeparator()

        # 状态显示（动态）
        self._act_mood = m.addAction(f"心情：{self.fsm.mood_label()}({self.fsm.mood})")
        self._act_mood.setEnabled(False)
        self._act_stats = m.addAction(f"互动次数：{self.fsm.interaction_count}")
        self._act_stats.setEnabled(False)
        m.addSeparator()

        m.addAction("快捷键帮助").triggered.connect(self._show_help)
        m.addAction("退出").triggered.connect(self._do_quit)

        self.tray.setContextMenu(m)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        self._menu = m

    def _on_tray_activated(self, reason):
        """托盘图标左键点击 → 互动。"""
        if reason == QSystemTrayIcon.Trigger:
            self._do_interact()

    def _show_help(self):
        """显示快捷键帮助。"""
        help_text = (
            "祁煜快捷键：\n"
            "空格 — 挥手问好\n"
            "W — 散步\n"
            "R — 跑步\n"
            "S — 休息\n"
            "F — 鞠躬\n"
            "H — 思考\n"
            "Y — 伸懒腰\n"
            "E — 坐下\n"
            "\n双击 — 拍拍肩\n长按 — 安静陪伴\n"
            "托盘菜单可请他吃甜品、看各动作"
        )
        self.show_bubble(help_text, duration=6000)

    # ---- 菜单动作 ----
    def _do_interact(self):
        state, speech = self.fsm.on_click()
        self.set_pose(state)
        self.show_bubble(speech)

    def _do_shoulder_pat(self):
        state, speech = self.fsm.on_double_click()
        self.set_pose(state)
        self.show_bubble(speech)

    def _do_pet(self):
        state, speech = self.fsm.on_pet()
        self.set_pose(state)
        self.show_bubble(speech)

    def _do_feed(self):
        state, speech = self.fsm.on_feed()
        self.set_pose(state)
        self.show_bubble(speech)
        # 1.5 秒后吃完甜品
        QTimer.singleShot(1500, lambda: self._after_feed())

    def _after_feed(self):
        now = time.time()
        self.fsm.state = "wave"
        self.fsm.state_until = now + STATE_DURATION["wave"]
        self.set_pose("wave")
        self.show_bubble(DESSERT_DONE_LINE.format(name=self.config.name))

    def _set_temp_state(self, state):
        self.fsm.state = state
        self.fsm.state_until = time.time() + STATE_DURATION.get(state, 3.0)
        self.set_pose(state)
        self.show_bubble(self.fsm.speech(state))

    def _do_wave(self):
        self._set_temp_state("wave")

    def _do_think(self):
        self._set_temp_state("think")

    def _do_walk(self):
        self._set_temp_state("walk")

    def _do_run(self):
        self._set_temp_state("run")

    def _do_sit(self):
        self._set_temp_state("sit")

    def _do_stretch(self):
        self._set_temp_state("stretch")

    def _do_surprise(self):
        self._set_temp_state("surprise")

    def _do_bow(self):
        self._set_temp_state("bow")

    # ---- 定时提醒 ----
    def _notify_reminder(self, text):
        """定时提醒触发：鞠躬引起注意 + 气泡 + 系统托盘通知。"""
        self.set_pose("bow")
        self.show_bubble(text, duration=8000)
        if hasattr(self, "tray"):
            self.tray.showMessage(
                f"{self.config.name} · 定时提醒", text,
                QSystemTrayIcon.Information, 8000,
            )

    def _add_timed_reminder(self):
        """添加定时提醒：先输入 HH:MM，再输入内容。"""
        t, ok = QInputDialog.getText(
            self, "添加定时提醒",
            "提醒时间（24小时制，如 14:30）：",
        )
        if not ok:
            return
        if TimedReminder._norm_hhmm(t) is None:
            self.show_bubble("时间格式不对，要用 14:30 这样的格式。")
            return
        text, ok = QInputDialog.getText(self, "添加定时提醒", "提醒内容：")
        if not ok:
            return
        if not self.timed.add(t, text):
            self.show_bubble("提醒内容不能是空的。")
            return
        self.set_pose("wave")
        self.show_bubble(f"好，每天 {TimedReminder._norm_hhmm(t)} 我会提醒你。")

    def _manage_timed_reminders(self):
        """管理定时提醒：查看列表、删除选中、清空全部。"""
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{self.config.name}的定时提醒")
        dlg.setMinimumWidth(360)
        layout = QVBoxLayout(dlg)

        lst = QListWidget(dlg)
        items = self.timed.items()
        if not items:
            lst.addItem("（还没有定时提醒，去添加一个吧）")
        for r in items:
            lst.addItem(f"{r['time']}    {r['text']}")
        layout.addWidget(lst)

        btn_row = QHBoxLayout()
        btn_del = QPushButton("删除选中", dlg)
        btn_clear = QPushButton("清空全部", dlg)
        btn_close = QPushButton("关闭", dlg)
        btn_row.addWidget(btn_del)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        def _del_selected():
            row = lst.currentRow()
            if row < 0 or row >= len(items):
                return
            self.timed.remove(items[row]["time"])
            lst.takeItem(row)
            items.pop(row)

        def _clear_all():
            self.timed.clear()
            lst.clear()
            items.clear()
            lst.addItem("（还没有定时提醒，去添加一个吧）")

        btn_del.clicked.connect(_del_selected)
        btn_clear.clicked.connect(_clear_all)
        btn_close.clicked.connect(dlg.accept)
        dlg.exec()

    def _do_sleep(self):
        self.fsm.state = "sleep"
        self.fsm.state_until = 0
        self.set_pose("sleep")
        self.show_bubble("嘘……{0}闭目养神了。".format(self.config.name))

    def _do_quit(self):
        self.tray.hide()
        QApplication.quit()

    # ---- 初始位置 ----
    def _place_bottom_right(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - PET_W - 30
        y = screen.bottom() - PET_H - 10
        self.move(x, y)
        self._place_ring()


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setQuitOnLastWindowClosed(False)
    pet = PetWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
