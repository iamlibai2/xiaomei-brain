"""GestureRecognizer — 将触摸板原始事件帧识别为高层手势。

输入：capture() 返回的 events 列表
输出：已识别的手势列表，每个手势包含 type / zone / fingers / intensity

手势类型：
  tap, double_tap       — 轻点 / 双击
  long_press            — 长按
  hold_still            — 持续停留不动
  slide_up/down/left/right — 单方向滑动
  circle                — 画圈
  back_and_forth        — 来回
  two_finger_*, three_finger  — 多指变体

区域：
  upper  (y < 0.33)
  middle (0.33 <= y < 0.66)
  lower  (y >= 0.66)
"""

from __future__ import annotations

import math
import time


# 阈值
_TAP_MAX_DURATION = 200       # ms，短于这个算 tap
_TAP_MAX_DISPLACEMENT = 0.03  # 归一化距离，小于这个算点按
_DOUBLE_TAP_MAX_GAP = 800     # ms，两个 tap 间隔小于这个算双击
_LONG_PRESS_MIN_DURATION = 800  # ms，长于这个算长按
_SESSION_GAP = 350            # ms，两个事件间隔大于这个算新会话
_HOLD_EMIT_INTERVAL = 3.0     # 秒，持续接触时每隔多久 emit 一次 hold_still
_ACTIVE_EMIT_INTERVAL = 2.0   # 秒，持续活动手势（画圈/滑动）的 emit 间隔
_HOLD_DISPLACEMENT = 0.01     # hold_still 的最大位移
_CIRCLE_CURVE_RATIO = 1.8     # 路径/位移比值，大于这个算曲线
_BACK_AND_FORTH_REVERSALS = 2  # 方向反转次数阈值


class GestureRecognizer:
    """实时手势识别器。

    使用方式：
        recognizer = GestureRecognizer()
        for events in sensor_stream:      # events = capture()["events"]
            gestures = recognizer.feed(events)
            for g in gestures:
                print(g)  # {"gesture": "tap", "zone": "upper", ...}
    """

    def __init__(self) -> None:
        self._session: list[dict] = []       # 当前接触会话
        self._last_ts: int = 0               # 上一帧时间
        self._tap_history: list[dict] = []    # 记录最近几次 tap（用于双击检测）
        self._gesture_history: list[dict] = []  # 最近发出的手势（去重）
        self._last_hold_emit: float = 0.0     # 上次 emit hold_still 的 wall time
        self._last_active_emit: float = 0.0   # 上次 emit 活动手势的 wall time

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def feed(self, events: list[dict]) -> list[dict]:
        """输入一帧（或一批）事件，返回新识别的手势列表。"""
        gestures: list[dict] = []

        for e in events:
            ts = e["ts"]
            gap = ts - self._last_ts if self._last_ts else 0

            if self._session and gap > _SESSION_GAP:
                # 接触断开 → 分析当前会话
                g = self._analyze_session()
                if g:
                    gestures.append(g)
                    self._handle_tap_for_double(gestures, g)
                self._session = []

            self._session.append(e)
            self._last_ts = ts

        # 如果会话的最后一次接触已经过去足够久，自动 flush
        if self._session:
            last_session_ts = self._session[-1]["ts"]
            if self._last_ts - last_session_ts >= _SESSION_GAP:
                g = self._analyze_session()
                if g:
                    gestures.append(g)
                    self._handle_tap_for_double(gestures, g)
                self._session = []

        # 持续接触中 → 定期 emit
        if self._session:
            now = time.time()
            # 活动手势（画圈/滑动）：emit 当前状态
            if now - self._last_active_emit >= _ACTIVE_EMIT_INTERVAL:
                g = self._classify_current_session()
                if g and g["gesture"] not in ("hold_still", "tap"):
                    gestures.append(g)
                    self._last_active_emit = now
                    self._last_hold_emit = now  # 避免 hold 和 active 同时 emit
            # 静止手势：定期 emit hold_still
            if now - self._last_hold_emit >= _HOLD_EMIT_INTERVAL:
                g = self._make_hold_gesture()
                if g:
                    gestures.append(g)
                self._last_hold_emit = now

        # 清理旧的 tap 记录
        self._trim_tap_history()

        return gestures

    def flush(self) -> list[dict]:
        """强制分析当前会话（比如传感器关闭时），返回剩余手势。"""
        if not self._session:
            return []
        g = self._analyze_session()
        self._session = []
        return [g] if g else []

    # ------------------------------------------------------------------
    # 手势分类
    # ------------------------------------------------------------------

    def _classify_current_session(self) -> dict | None:
        """分类当前会话（不清空），用于持续手势的定期 emit。"""
        return self._classify(self._session)

    def _analyze_session(self) -> dict | None:
        return self._classify(self._session)

    def _classify(self, session: list[dict]) -> dict | None:
        if len(session) < 2:
            return None

        duration = session[-1]["ts"] - session[0]["ts"]
        xs = [f["x"] for f in session]
        ys = [f["y"] for f in session]

        start_x, start_y = xs[0], ys[0]
        end_x, end_y = xs[-1], ys[-1]
        total_displacement = math.hypot(end_x - start_x, end_y - start_y)

        # 累积路径长度
        cumulative_dist = 0.0
        for i in range(1, len(session)):
            cumulative_dist += math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1])

        fingers = max((f.get("fingers", 1) for f in session), default=1)
        avg_speed = sum(f.get("speed", 0) for f in session) / len(session)

        # 区域
        avg_y = sum(ys) / len(ys)
        if avg_y < 0.33:
            zone = "upper"
        elif avg_y < 0.66:
            zone = "middle"
        else:
            zone = "lower"

        # 分类
        if duration < _TAP_MAX_DURATION and total_displacement < _TAP_MAX_DISPLACEMENT \
                and cumulative_dist < _TAP_MAX_DISPLACEMENT * 2:
            base_gesture = "tap"
            intensity = "light"
        elif duration > _LONG_PRESS_MIN_DURATION and total_displacement < 0.03:
            base_gesture = "long_press"
            intensity = "firm" if avg_speed < 0.1 else "heavy"
        elif total_displacement < _HOLD_DISPLACEMENT and cumulative_dist < _HOLD_DISPLACEMENT * 2:
            base_gesture = "hold_still"
            intensity = "gentle"
        elif cumulative_dist > max(total_displacement * _CIRCLE_CURVE_RATIO, 0.05):
            # 路径远大于位移 → 画圈 / 曲线
            reversals = self._count_reversals(xs, ys)
            if reversals >= _BACK_AND_FORTH_REVERSALS:
                base_gesture = "back_and_forth"
            else:
                base_gesture = "circle"
            intensity = "slow" if avg_speed < 0.3 else "quick"
        else:
            # 线性滑动
            base_gesture = self._slide_direction(start_x, start_y, end_x, end_y)
            if avg_speed < 0.2:
                intensity = "slow"
            elif avg_speed > 0.6:
                intensity = "fast"
            else:
                intensity = "moderate"

        # 多指前缀
        if fingers >= 3:
            gesture = "three_finger"
        elif fingers == 2:
            gesture = f"two_finger_{base_gesture}" if not base_gesture.startswith("two_finger") else base_gesture
        else:
            gesture = base_gesture

        return {
            "gesture": gesture,
            "zone": zone,
            "fingers": fingers,
            "duration_ms": duration,
            "displacement": round(total_displacement, 4),
            "intensity": intensity,
            "avg_y": round(avg_y, 3),
            "avg_speed": round(avg_speed, 4),
        }

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _slide_direction(sx: float, sy: float, ex: float, ey: float) -> str:
        """根据起止点判断滑动方向。"""
        dx = ex - sx
        dy = ey - sy
        if abs(dy) > abs(dx):
            return "slide_down" if dy > 0 else "slide_up"
        else:
            return "slide_right" if dx > 0 else "slide_left"

    @staticmethod
    def _count_reversals(xs: list[float], ys: list[float]) -> int:
        """计算方向反转次数（用于识别来回/画圈）。"""
        reversals = 0
        prev_dx, prev_dy = 0.0, 0.0
        for i in range(1, len(xs)):
            dx = xs[i] - xs[i - 1]
            dy = ys[i] - ys[i - 1]
            if i > 1:
                # 方向点积为负 → 反转
                dot = dx * prev_dx + dy * prev_dy
                if dot < -0.0001:
                    reversals += 1
            prev_dx, prev_dy = dx, dy
        return reversals

    def _handle_tap_for_double(self, gestures: list[dict], g: dict) -> None:
        """检测双击：如果上一个手势也是 tap 且间隔短，合并为 double_tap。"""
        if g["gesture"] != "tap":
            self._tap_history = []
            return

        self._tap_history.append(g)
        if len(self._tap_history) < 2:
            return

        t1 = self._tap_history[-2]
        t2 = self._tap_history[-1]
        # timestamp of the session start (first event)
        ts1 = t1.get("_session_start", 0)
        ts2 = t2.get("_session_start", 0)
        if ts2 - ts1 < _DOUBLE_TAP_MAX_GAP and t1["zone"] == t2["zone"]:
            # 合并为双击
            gestures.pop()
            gestures.pop()
            gestures.append({
                "gesture": "double_tap",
                "zone": g["zone"],
                "fingers": g["fingers"],
                "duration_ms": ts2 - ts1 + g["duration_ms"],
                "displacement": g["displacement"],
                "intensity": "double",
                "avg_y": g["avg_y"],
                "avg_speed": g["avg_speed"],
            })
            self._tap_history.clear()

    def _trim_tap_history(self) -> None:
        """移除过期的 tap 记录。"""
        if not self._tap_history:
            return
        cutoff = time.time() - (_DOUBLE_TAP_MAX_GAP / 1000.0)
        self._tap_history = [
            t for t in self._tap_history
            if t.get("_session_start", 0) / 1000.0 > cutoff
        ]

    def _make_hold_gesture(self) -> dict | None:
        """为持续接触生成 hold_still 手势。"""
        if not self._session:
            return None
        ys = [f["y"] for f in self._session]
        avg_y = sum(ys) / len(ys)
        if avg_y < 0.33:
            zone = "upper"
        elif avg_y < 0.66:
            zone = "middle"
        else:
            zone = "lower"
        # 检查最近确实没移动
        recent = self._session[-10:]
        if len(recent) >= 2:
            xs = [f["x"] for f in recent]
            ys2 = [f["y"] for f in recent]
            disp = math.hypot(xs[-1] - xs[0], ys2[-1] - ys2[0])
            if disp > 0.02:
                return None  # 在移动，不 emit hold
        fingers = max((f.get("fingers", 1) for f in self._session), default=1)
        duration = self._session[-1]["ts"] - self._session[0]["ts"]
        return {
            "gesture": "hold_still",
            "zone": zone,
            "fingers": fingers,
            "duration_ms": duration,
            "displacement": 0.0,
            "intensity": "gentle" if fingers == 1 else "warm",
            "avg_y": round(avg_y, 3),
            "avg_speed": 0.0,
        }
