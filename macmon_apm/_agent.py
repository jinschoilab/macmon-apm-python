"""에이전트 싱글턴 보관소. 멀티 import 안전."""
from __future__ import annotations

import threading
from typing import Optional

from .config import Config
from .exporter import Exporter
from .runtime import RuntimeSampler
from .stacksampler import StackSampler


class Agent:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.exporter = Exporter(config)
        self.runtime = RuntimeSampler(config, self.exporter)
        self.stacks = StackSampler(config, self.exporter)


_lock = threading.Lock()
_instance: Optional[Agent] = None


def get() -> Optional[Agent]:
    return _instance


def init(config: Optional[Config] = None) -> Agent:
    """idempotent: 두 번 호출해도 같은 인스턴스 반환."""
    global _instance
    with _lock:
        if _instance is not None:
            return _instance
        _instance = Agent(config or Config())
        _instance.runtime.start()
        _instance.stacks.start()
        return _instance
