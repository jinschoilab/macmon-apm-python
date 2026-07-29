"""스레드 스택 샘플러 — Java APM의 StackSampler(Active Stack)와 동일한 개념.

Trace(트랜잭션)와 완전히 무관하게, 프로세스의 살아있는 스레드 전체 콜스택을
주기적으로 찍어 POST /api/traces/stacks 로 보낸다.

트레이스는 실행이 "끝나야" 나가지만(Trace.finish() 이후 1건), 이 스냅샷은
프로세스가 살아있는 동안 계속 나간다. 그래서 n.py처럼 명시적으로 끊기 전까지
종료되지 않는 배치/크롤러 스크립트도 macmon UI의 Active Stack 화면에서
"지금 어느 함수에서 멈춰 있는지"가 실시간으로 보인다 — 트랜잭션 단위 트레이싱이
안 되는 대신, 최소한 살아있다는 것과 어디서 도는지는 항상 보여준다.

서버 측 스키마: macmon-server/internal/storage/traces.go의 StackSnapshot/StackThread.
필드 이름이 정확히 일치해야 한다.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from typing import Any, Dict, List

from .config import Config
from .exporter import Exporter

_log = logging.getLogger("macmon_apm.stacksampler")

_MAX_FRAMES = 32


def _wall_now_iso() -> str:
    t = time.gmtime()
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"


def _capture_threads(skip_ident: int) -> List[Dict[str, Any]]:
    frames = sys._current_frames()
    threads: List[Dict[str, Any]] = []
    for t in threading.enumerate():
        if t.ident == skip_ident:
            continue  # 샘플러 자기 자신은 제외 (Java StackSampler와 동일한 필터링)
        frame = frames.get(t.ident) if t.ident is not None else None
        stack: List[str] = []
        if frame is not None:
            for filename, lineno, func, _ in traceback.extract_stack(frame, limit=_MAX_FRAMES):
                stack.append(f"{filename}:{lineno} in {func}")
        threads.append(
            {
                "name": t.name,
                "id": t.ident or 0,
                "state": "alive" if t.is_alive() else "dead",
                "stack": stack,
            }
        )
    return threads


class StackSampler:
    def __init__(self, cfg: Config, exporter: Exporter) -> None:
        self.cfg = cfg
        self.exporter = exporter
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None

    def start(self) -> None:
        if self.cfg.disabled or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="macmon-apm-stacksampler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        interval = max(2.0, self.cfg.stack_interval_sec)
        my_ident = threading.get_ident()
        while not self._stop.is_set():
            try:
                self.exporter.submit_stacks(self._sample(my_ident))
            except Exception as e:  # noqa: BLE001 — 샘플러 죽으면 안 됨
                _log.debug("stack sample failed: %s", e)
            if self._stop.wait(interval):
                return

    def _sample(self, my_ident: int) -> Dict[str, Any]:
        return {
            "sampled_at": _wall_now_iso(),
            "host": self.cfg.host,
            "service": self.cfg.service,
            "lang": "python",
            "threads": _capture_threads(my_ident),
        }
