"""进程级统一配置。

一个 agent 一个配置文件：~/.xiaomei-brain/{agent_id}/brain.yaml
包含 drive 和 consciousness 两大段。
"""

from .agent_config import AgentConfig, load_agent_config, save_agent_config

__all__ = ["AgentConfig", "load_agent_config", "save_agent_config"]
