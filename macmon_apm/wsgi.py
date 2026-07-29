"""WSGI 미들웨어. Flask/Django 등 WSGI 앱을 감싸 server 스팬을 자동 생성.

사용:
    from macmon_apm import start, WSGIMiddleware
    start()
    app.wsgi_app = WSGIMiddleware(app.wsgi_app)   # Flask
    application = WSGIMiddleware(application)     # Django

ASGI 미들웨어는 Step 1에서 추가.
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Iterable, List, Tuple

from . import _agent  # 사이드 이펙트 없음, 내부 싱글턴 접근용
from .span import Trace, TraceSpan, new_trace_id


def _extract_client_ip(environ: dict) -> str:
    # X-Forwarded-For 우선 (nginx/로드밸런서 뒤에 있는 흔한 배포 형태).
    # 프록시가 이 헤더를 검증/재작성하지 않으면 클라이언트가 임의로 스푸핑할 수 있음(알려진 한계).
    xff = environ.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    xri = environ.get("HTTP_X_REAL_IP", "")
    if xri:
        return xri.strip()
    return environ.get("REMOTE_ADDR", "") or ""


class WSGIMiddleware:
    def __init__(self, app: Callable) -> None:
        self.app = app

    def __call__(self, environ: dict, start_response: Callable) -> Iterable[bytes]:
        agent = _agent.get()
        if agent is None or agent.config.disabled:
            return self.app(environ, start_response)

        tid = threading.get_ident()
        thread_name = threading.current_thread().name
        method = environ.get("REQUEST_METHOD", "")
        path = environ.get("PATH_INFO", "") or "/"
        client_ip = _extract_client_ip(environ)

        trace = Trace(
            id=new_trace_id(tid),
            host=agent.config.host,
            service=agent.config.service,
        )
        root = TraceSpan(
            kind="server",
            tid=tid,
            thread_name=thread_name,
            http_method=method,
            http_path=path,
            client_ip=client_ip,
        )
        trace.root = root

        captured_status: List[int] = []

        def wrapped_start_response(status: str, headers: List[Tuple[str, str]], exc_info: Any = None) -> Any:
            try:
                code = int(status.split(" ", 1)[0])
            except (ValueError, IndexError):
                code = 0
            captured_status.append(code)
            return start_response(status, headers, exc_info)

        try:
            return _IterWrapper(self.app(environ, wrapped_start_response), trace, captured_status, agent)
        except Exception as e:
            root.exception_type = type(e).__name__
            root.exception_msg = str(e)[:500]
            trace.finish()
            agent.exporter.submit_trace(trace.to_dict())
            raise


class _IterWrapper:
    """WSGI body iterable을 감싸 close() 시점에 trace를 마감한다.

    WSGI는 응답 본문을 게으르게 생성하므로, app() 호출 직후에 끊으면 시간이
    실제 처리 시간보다 짧게 잡힌다. close()가 호출되는 시점이 진짜 끝.
    """

    def __init__(self, body: Iterable[bytes], trace: Trace, status: List[int], agent: Any) -> None:
        self._body = body
        self._trace = trace
        self._status = status
        self._agent = agent
        self._closed = False

    def __iter__(self) -> Iterable[bytes]:
        return iter(self._body)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # body가 close를 가질 수도 있음 (예: file iterator)
        body_close = getattr(self._body, "close", None)
        if callable(body_close):
            try:
                body_close()
            except Exception:  # noqa: BLE001
                pass
        if self._trace.root is not None and self._status:
            self._trace.root.http_status = self._status[0]
        self._trace.finish()
        self._agent.exporter.submit_trace(self._trace.to_dict())
