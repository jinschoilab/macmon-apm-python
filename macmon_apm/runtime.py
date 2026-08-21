"""런타임 샘플러. 30초 주기로 GC/threading/메모리 데이터를 모은다.

서버 측 APMRuntimeSample 스키마는 Go/Java 필드가 섞여 있고 모두 omitempty.
Python에서는 다음만 채운다:
- service / host / lang ("python")
- jvm_thread_count : 활성 스레드 수 (서버 UI가 이미 이 키를 표시하므로 재활용)
- jvm_heap_used_kb : RSS (psutil 없이 resource.getrusage로 추정)
- jvm_heap_max_kb  : 0 (Python에는 max heap 개념 없음)
- jvm_gc_count     : gc.get_count() 합 (gen 0+1+2 누적)

키 매핑은 step 1에서 서버에 python 전용 필드(py_*)를 추가하면서 정리할 예정.
지금은 UI가 이미 jvm_* 를 그래프로 보여주므로 거기에 묻어가는 형태.
"""
from __future__ import annotations

import gc
import logging
import resource
import sys
import threading
import time
from typing import Any, Dict

from .config import Config
from .exporter import Exporter

_log = logging.getLogger("macmon_apm.runtime")


def _wall_now_iso() -> str:
    # 서버는 wall_at을 RFC3339로 받음. JSON encoder가 datetime을 모르므로 문자열로.
    sec = time.time()
    t = time.gmtime(sec)
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"


def _rss_kb() -> int:
    """프로세스 RSS in kB. macOS는 byte, Linux는 kB로 반환되는 차이 보정."""
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return int(ru // 1024)
    return int(ru)


class RuntimeSampler:
    def __init__(self, cfg: Config, exporter: Exporter) -> None:
        self.cfg = cfg
        self.exporter = exporter
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None

    def start(self) -> None:
        if self.cfg.disabled or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop,
            name="macmon-apm-runtime",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # 첫 샘플은 5초 후 — 서비스명·환경 안정화 시간 확보.
        if self._stop.wait(5.0):
            return
        interval = max(5.0, self.cfg.runtime_interval_sec)
        while not self._stop.is_set():
            try:
                self.exporter.submit_runtime(self._sample())
            except Exception as e:  # noqa: BLE001 — 샘플러 죽으면 안 됨
                _log.debug("runtime sample failed: %s", e)
            if self._stop.wait(interval):
                return

    def _sample(self) -> Dict[str, Any]:
        gc_counts = gc.get_count()
        thread_count = threading.active_count()
        sample: Dict[str, Any] = {
            "wall_at": _wall_now_iso(),
            "host": self.cfg.host,
            "agent_id": self.cfg.agent_id,
            "service": self.cfg.service,
            "lang": "python",
            "jvm_thread_count": thread_count,
            "jvm_heap_used_kb": _rss_kb(),
            "jvm_gc_count": int(sum(gc_counts)),
        }
        return sample
