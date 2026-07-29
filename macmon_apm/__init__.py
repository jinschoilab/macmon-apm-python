"""macmon Python APM (Step 0).

기본 사용:
    import macmon_apm
    macmon_apm.start()                       # 환경변수에서 설정 로드 + 런타임 샘플러 시작

    from macmon_apm import WSGIMiddleware
    app.wsgi_app = WSGIMiddleware(app.wsgi_app)

환경변수: MACMON_APM_URL / MACMON_APM_SERVICE / MACMON_APM_HOST / MACMON_APM_DISABLE
서버: macmon-server (수집 포트 6600)의 POST /api/traces, POST /api/apm/runtime
와이어 포맷: macmon-server/internal/storage/traces.go의 Trace/TraceSpan과 동일
"""
from __future__ import annotations

from typing import Optional

from . import _agent
from .config import Config
from .span import Trace, TraceSpan, new_trace_id
from .wsgi import WSGIMiddleware

__all__ = ["start", "stats", "Config", "Trace", "TraceSpan", "WSGIMiddleware", "new_trace_id"]


def start(config: Optional[Config] = None) -> None:
    """에이전트 초기화 + 런타임 샘플러 기동. 두 번 호출 무해."""
    _agent.init(config)


def stats() -> dict:
    """디버깅용. 전송/실패/드랍 카운터."""
    a = _agent.get()
    if a is None:
        return {"started": False}
    return {"started": True, **a.exporter.stats()}
