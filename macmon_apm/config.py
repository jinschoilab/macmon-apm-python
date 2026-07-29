"""환경변수 기반 설정.

Java/Go APM과 동일한 키 컨벤션:
- MACMON_APM_URL       : macmon-server 수집 포트 (기본 http://127.0.0.1:6600)
- MACMON_APM_SERVICE   : 서비스명. 미지정 시 sys.argv[0] 베이스네임으로 추정
- MACMON_APM_HOST      : 호스트 식별자. 미지정 시 socket.gethostname()
- MACMON_APM_DISABLE   : "1"이면 모든 전송 비활성 (테스트용)
- MACMON_APM_RUNTIME_INTERVAL_SEC : 런타임 샘플 주기 (기본 30)
- MACMON_APM_STACK_INTERVAL_SEC   : 스레드 스택 스냅샷 주기 (기본 5)
"""
from __future__ import annotations

import os
import socket
import sys
from dataclasses import dataclass, field


def _default_service() -> str:
    argv0 = (sys.argv[0] or "").strip()
    if argv0:
        return os.path.basename(argv0).removesuffix(".py") or "python"
    return "python"


def _default_host() -> str:
    try:
        return socket.gethostname() or "unknown"
    except OSError:
        return "unknown"


@dataclass
class Config:
    url: str = field(default_factory=lambda: os.environ.get("MACMON_APM_URL", "http://127.0.0.1:6600"))
    service: str = field(default_factory=lambda: os.environ.get("MACMON_APM_SERVICE", "") or _default_service())
    host: str = field(default_factory=lambda: os.environ.get("MACMON_APM_HOST", "") or _default_host())
    disabled: bool = field(default_factory=lambda: os.environ.get("MACMON_APM_DISABLE") == "1")
    runtime_interval_sec: float = field(
        default_factory=lambda: float(os.environ.get("MACMON_APM_RUNTIME_INTERVAL_SEC", "30") or 30)
    )
    stack_interval_sec: float = field(
        default_factory=lambda: float(os.environ.get("MACMON_APM_STACK_INTERVAL_SEC", "5") or 5)
    )

    @property
    def trace_endpoint(self) -> str:
        return self.url.rstrip("/") + "/api/traces"

    @property
    def runtime_endpoint(self) -> str:
        return self.url.rstrip("/") + "/api/apm/runtime"

    @property
    def stacks_endpoint(self) -> str:
        return self.url.rstrip("/") + "/api/traces/stacks"
