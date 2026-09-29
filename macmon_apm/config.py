"""환경변수 기반 설정.

Java/Go APM과 동일한 키 컨벤션:
- MACMON_APM_URL       : macmon-server 수집 포트 (기본 http://127.0.0.1:6600)
- MACMON_APM_KEY       : 테넌트/팀 API 키(mak_…). 기록이 그 테넌트로 격리된다
- MACMON_APM_SERVICE   : 서비스명. 미지정 시 sys.argv[0] 베이스네임으로 추정
- MACMON_APM_HOST      : 호스트 식별자. 미지정 시 socket.gethostname()
- MACMON_APM_AGENT_ID  : agent_id. 미지정 시 macmon-agent(Go)와 동일한 알고리즘으로
                         `.macmon-agent.id` 파일을 진입 스크립트 옆/$HOME에서 찾거나 생성
- MACMON_APM_DISABLE   : "1"이면 모든 전송 비활성 (테스트용)
- MACMON_APM_RUNTIME_INTERVAL_SEC : 런타임 샘플 주기 (기본 30)
- MACMON_APM_STACK_INTERVAL_SEC   : 스레드 스택 스냅샷 주기 (기본 5)
- MACMON_APM_SAMPLE_RATE : 0~100 정수, 헤드 샘플링 비율 (기본 100 = 전량).
                           Java APM(macmon.sample.rate)과 동일한 개념 — 100 미만이면
                           일부 요청은 Trace 객체 자체를 만들지 않고 그대로 통과시킨다.
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import uuid
from dataclasses import dataclass, field

_log = logging.getLogger("macmon_apm.config")

_AGENT_ID_FILENAME = ".macmon-agent.id"


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


def _agent_id_candidates() -> list:
    """macmon-agent(Go)의 loadOrCreateAgentID()와 동일한 탐색 순서.

    1) 진입 스크립트(sys.argv[0]) 디렉토리 옆 — _default_service()와 동일한 발상으로
       "이 프로세스를 실행한 진입점" 위치를 실행파일 대용으로 삼는다.
    2) $HOME — 하위 호환/폴백.
    """
    candidates = []
    argv0 = (sys.argv[0] or "").strip()
    if argv0:
        try:
            script_dir = os.path.dirname(os.path.abspath(argv0))
        except OSError:
            script_dir = ""
        if script_dir:
            candidates.append(os.path.join(script_dir, _AGENT_ID_FILENAME))
    home = os.path.expanduser("~")
    if home and home != "~":
        candidates.append(os.path.join(home, _AGENT_ID_FILENAME))
    return candidates


def _default_agent_id() -> str:
    """Go APM(macmon-agent)과 동일한 UUID 파일 영속화 알고리즘.

    파일 읽기/쓰기가 전부 실패해도(권한 없음, 읽기 전용 venv 등) 예외를 앱 밖으로
    내보내지 않는다 — 이 경우 메모리에만 유지한 UUID를 반환한다.
    """
    candidates = _agent_id_candidates()

    # 기존 파일에서 첫 번째로 발견한 값 사용.
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = f.read().strip()
            if existing:
                return existing
        except OSError:
            continue

    # 새 ID 생성 — 첫 번째로 쓰기 성공하는 후보에 저장.
    new_id = str(uuid.uuid4())
    for path in candidates:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_id + "\n")
            return new_id
        except OSError:
            continue

    _log.warning("agent ID 저장 실패 — 메모리에만 유지: %s", new_id)
    return new_id


@dataclass
class Config:
    url: str = field(default_factory=lambda: os.environ.get("MACMON_APM_URL", "http://127.0.0.1:6600"))
    # 테넌트/팀 API 키(mak_…). 서버가 이 키로 기록의 테넌트를 확정한다. 없으면 default 테넌트
    api_key: str = field(default_factory=lambda: os.environ.get("MACMON_APM_KEY", ""))
    service: str = field(default_factory=lambda: os.environ.get("MACMON_APM_SERVICE", "") or _default_service())
    host: str = field(default_factory=lambda: os.environ.get("MACMON_APM_HOST", "") or _default_host())
    agent_id: str = field(default_factory=lambda: os.environ.get("MACMON_APM_AGENT_ID", "") or _default_agent_id())
    disabled: bool = field(default_factory=lambda: os.environ.get("MACMON_APM_DISABLE") == "1")
    runtime_interval_sec: float = field(
        default_factory=lambda: float(os.environ.get("MACMON_APM_RUNTIME_INTERVAL_SEC", "30") or 30)
    )
    stack_interval_sec: float = field(
        default_factory=lambda: float(os.environ.get("MACMON_APM_STACK_INTERVAL_SEC", "5") or 5)
    )
    sample_rate: int = field(
        default_factory=lambda: min(100, max(0, int(os.environ.get("MACMON_APM_SAMPLE_RATE", "100") or 100)))
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
