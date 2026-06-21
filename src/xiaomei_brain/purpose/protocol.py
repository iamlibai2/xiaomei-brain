"""Purpose 层接口协议。

定义 Agent 需要的 Purpose 接口，用于跨层依赖的类型标注。
"""

from typing import Optional, Protocol

from .goal import Goal


class PurposeProtocol(Protocol):
    """Agent 需要的 Purpose 接口。

    Usage:
        def some_function(purpose: PurposeProtocol) -> None:
            current = purpose.get_current()
    """

    def get_current(self) -> Optional[Goal]: ...

    def get_state_summary(self) -> str: ...

    def complete_goal(self, goal_id: str) -> None: ...

    def get_next(self) -> Optional[Goal]: ...

    def get_next_sibling(self, goal_id: str) -> Optional[Goal]: ...
