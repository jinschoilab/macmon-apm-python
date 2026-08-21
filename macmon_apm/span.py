"""Wire format. Java/Go APM의 Trace/TraceSpan과 동일한 JSON 구조.

서버 측 정의: macmon-server/internal/storage/traces.go의 Trace, TraceSpan.

Python에서는 dataclass로 모델링하고 export 직전에 dict로 직렬화한다.
필드 이름은 서버 JSON 키와 정확히 일치해야 한다.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# 시작 시각을 기준으로 한 monotonic ns. 서버는 start_ns / duration_ns 만 본다.
_BOOT_NS = time.monotonic_ns()


def _now_ns() -> int:
    return time.monotonic_ns() - _BOOT_NS


def _wall_now() -> str:
    # RFC3339 nano. time.time_ns() → datetime.fromtimestamp 보다 직접 포맷이 정확.
    ns = time.time_ns()
    sec = ns // 1_000_000_000
    rem = ns - sec * 1_000_000_000
    t = time.gmtime(sec)
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}.{rem:09d}Z"


@dataclass
class TraceSpan:
    kind: str  # server | db | outbound | exception
    tid: int = field(default_factory=threading.get_ident)
    start_ns: int = field(default_factory=_now_ns)
    duration_ns: int = 0
    children: List["TraceSpan"] = field(default_factory=list)

    # HTTP server/outbound
    http_method: str = ""
    http_path: str = ""
    http_status: int = 0
    http_url: str = ""
    client_ip: str = ""

    # DB
    sql: str = ""
    row_count: int = 0

    # Exception
    exception_type: str = ""
    exception_msg: str = ""

    thread_name: str = ""

    def finish(self) -> None:
        self.duration_ns = _now_ns() - self.start_ns

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "kind": self.kind,
            "tid": self.tid,
            "start_ns": self.start_ns,
            "duration_ns": self.duration_ns,
        }
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        if self.thread_name:
            d["thread_name"] = self.thread_name
        if self.http_method:
            d["http_method"] = self.http_method
        if self.http_path:
            d["http_path"] = self.http_path
        if self.http_status:
            d["http_status"] = self.http_status
        if self.http_url:
            d["http_url"] = self.http_url
        if self.client_ip:
            d["client_ip"] = self.client_ip
        if self.sql:
            d["sql"] = self.sql
        if self.row_count:
            d["row_count"] = self.row_count
        if self.exception_type:
            d["exception_type"] = self.exception_type
        if self.exception_msg:
            d["exception_msg"] = self.exception_msg
        return d


@dataclass
class Trace:
    id: str
    host: str
    agent_id: str = ""
    pid: int = field(default_factory=os.getpid)
    comm: str = "python"
    service: str = ""
    wall_at: str = field(default_factory=_wall_now)
    start_ns: int = field(default_factory=_now_ns)
    duration_ns: int = 0
    root: Optional[TraceSpan] = None

    def finish(self) -> None:
        if self.root is not None:
            self.root.finish()
            self.duration_ns = self.root.duration_ns
        else:
            self.duration_ns = _now_ns() - self.start_ns

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "host": self.host,
            "pid": self.pid,
            "comm": self.comm,
            "wall_at": self.wall_at,
            "start_ns": self.start_ns,
            "duration_ns": self.duration_ns,
            "root_goid": 0,  # 서버 호환용 더미. Python은 goroutine 개념 없음.
        }
        if self.agent_id:
            d["agent_id"] = self.agent_id
        if self.service:
            d["service"] = self.service
        if self.root is not None:
            d["root"] = self.root.to_dict()
        return d


def new_trace_id(tid: int) -> str:
    """Java APM의 tx_<tid>_<wall_ns> 형식과 일치."""
    return f"tx_{tid}_{time.time_ns()}"
