"""技能源适配器基类。

所有技能源（URL、GitHub、skills-sh 等）都继承 BaseSourceAdapter，
产出统一的 SourceBundle。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SourceBundle:
    """统一技能包 — 所有 adapter 产出的标准格式。

    Attributes:
        content: SKILL.md 完整内容（YAML frontmatter + markdown body）
        source: 源类型标识（"url"、"github" 等）
        identifier: 用户输入的原始标识符
        resolved_url: 最终 fetch 的 URL
        metadata: 源特有元数据（如 GitHub 的 repo_owner、ref 等）
        files: 额外文件，文件名 → 内容（GitHub 目录中 SKILL.md 外的代码/资源）
    """

    content: str
    source: str
    identifier: str
    resolved_url: str
    metadata: dict[str, Any] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)


class BaseSourceAdapter(ABC):
    """技能源适配器抽象基类。

    每个 adapter 负责一类标识符（URL、GitHub shorthand 等）。
    install 流程通过 can_handle() 选择 adapter，然后调用 fetch()。

    Lifecycle::

        if adapter.can_handle(identifier):
            bundle = adapter.fetch(identifier)
    """

    @abstractmethod
    def can_handle(self, identifier: str) -> bool:
        """返回 True 表示此 adapter 可以处理该标识符。

        URL adapter 应优先于 GitHub adapter：
        https://github.com/... 不应被当成 owner/repo shorthand。
        """
        ...

    @abstractmethod
    def resolve(self, identifier: str) -> str:
        """将标识符解析为可 fetch 的具体 URL。

        URL adapter: 恒等映射。
        GitHub adapter: "owner/repo" → raw.githubusercontent.com/.../SKILL.md
        """
        ...

    @abstractmethod
    def fetch(self, identifier: str) -> SourceBundle:
        """获取技能并返回 SourceBundle。

        内部可调用 self.resolve()。失败时抛异常。
        """
        ...
