"""HTTP exporter — 백그라운드 데몬 스레드 + bounded queue.

설계 메모:
- 표준 라이브러리만 사용 (urllib). requests 의존성 없음.
- 큐가 가득 차면 드롭 (앱을 막지 않는 게 우선).
- 실패한 요청은 재시도하지 않는다 (장기 버퍼링은 step 1에서 추가).
- 데몬 스레드라서 파이썬 인터프리터 종료 시 자동 정리. atexit으로 잔여 flush.
"""
from __future__ import annotations

import atexit
import json
import logging
import queue
import threading
import urllib.error
import urllib.request
from typing import Any, Dict

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
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                resp.read()
                self._sent += 1
        except (urllib.error.URLError, OSError) as e:
            self._failed += 1
            _log.debug("post %s failed: %s", endpoint, e)

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
