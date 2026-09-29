"""HTTP exporter — 백그라운드 데몬 스레드 + bounded queue.

설계 메모:
- 표준 라이브러리만 사용 (http.client). requests 의존성 없음.
- 큐가 가득 차면 드롭 (앱을 막지 않는 게 우선).
- 실패한 요청은 재시도하지 않는다 (장기 버퍼링은 step 1에서 추가).
- 데몬 스레드라서 파이썬 인터프리터 종료 시 자동 정리. atexit으로 잔여 flush.
- 커넥션은 (scheme, host, port)별로 재사용한다. 전송 스레드가 단일 스레드로
  직렬 처리하므로 락 없이 dict만으로 충분하다. urllib.request.urlopen은 매
  호출마다 새 TCP(+TLS) 연결을 맺어 트레이스 1건당 핸드셰이크 비용이 붙는데,
  macmon-server가 항상 같은 host:port(:6600)이므로 keep-alive로 재사용하면
  그 비용이 사라진다. 실패 시 해당 커넥션만 버리고 다음 전송에서 재연결한다.
"""
from __future__ import annotations

import atexit
import http.client
import json
import logging
import queue
import threading
from typing import Any, Dict, Tuple
from urllib.parse import urlsplit

from .config import Config

_log = logging.getLogger("macmon_apm.exporter")


class Exporter:
    def __init__(self, cfg: Config, max_queue: int = 1024) -> None:
        self.cfg = cfg
        self._q: "queue.Queue[tuple[str, Dict[str, Any]]]" = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._dropped = 0
        self._sent = 0
        self._failed = 0
        # 전송 스레드 전용 — (scheme, host, port) -> HTTPConnection. 다른 스레드에서
        # 접근하지 않으므로 락 불필요.
        self._conns: Dict[Tuple[str, str, int], http.client.HTTPConnection] = {}

        if cfg.disabled:
            return

        self._thread = threading.Thread(
            target=self._loop,
            name="macmon-apm-exporter",
            daemon=True,
        )
        self._thread.start()
        atexit.register(self._on_exit)

    def submit_trace(self, trace_dict: Dict[str, Any]) -> None:
        self._submit(self.cfg.trace_endpoint, trace_dict)

    def submit_runtime(self, sample_dict: Dict[str, Any]) -> None:
        self._submit(self.cfg.runtime_endpoint, sample_dict)

    def submit_stacks(self, snapshot_dict: Dict[str, Any]) -> None:
        self._submit(self.cfg.stacks_endpoint, snapshot_dict)

    def _submit(self, endpoint: str, payload: Dict[str, Any]) -> None:
        if self.cfg.disabled:
            return
        try:
            self._q.put_nowait((endpoint, payload))
        except queue.Full:
            self._dropped += 1

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                endpoint, payload = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            self._post(endpoint, payload)

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> None:
        try:
            body = json.dumps(payload).encode("utf-8")
        except (TypeError, ValueError) as e:
            _log.debug("payload serialize failed: %s", e)
            self._failed += 1
            return

        parts = urlsplit(endpoint)
        host = parts.hostname or "127.0.0.1"
        port = parts.port or (443 if parts.scheme == "https" else 80)
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        key = (parts.scheme, host, port)

        conn = self._conns.get(key)
        if conn is None:
            conn = self._make_conn(parts.scheme, host, port)
            self._conns[key] = conn

        try:
            headers = {"Content-Type": "application/json"}
            if getattr(self.cfg, "api_key", ""):
                headers["X-API-Key"] = self.cfg.api_key
            conn.request("POST", path, body=body, headers=headers)
            resp = conn.getresponse()
            resp.read()
            self._sent += 1
        except (http.client.HTTPException, OSError) as e:
            self._failed += 1
            _log.debug("post %s failed: %s", endpoint, e)
            # 커넥션이 깨졌을 수 있으니 버리고 다음 전송에서 재연결한다.
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conns.pop(key, None)

    @staticmethod
    def _make_conn(scheme: str, host: str, port: int) -> http.client.HTTPConnection:
        cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        return cls(host, port, timeout=5.0)

    def _on_exit(self) -> None:
        # 종료 시 큐에 남은 항목을 짧게 flush. 데몬 스레드라 강제 종료될 수 있어
        # 무한정 기다리지 않고 1초만 시도.
        deadline = threading.Event()
        threading.Timer(1.0, deadline.set).start()
        while not deadline.is_set():
            try:
                endpoint, payload = self._q.get_nowait()
            except queue.Empty:
                break
            self._post(endpoint, payload)
        self._stop.set()

    def stats(self) -> Dict[str, int]:
        return {"sent": self._sent, "failed": self._failed, "dropped": self._dropped}
