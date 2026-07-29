"""CLI 자동 계측 러너. 대상 스크립트는 한 글자도 수정하지 않는다.

사용:
    python3 -m macmon_apm.run <script.py> [args...]

계측 여부는 스크립트가 아니라 실행 환경에 달려 있다:
- MACMON_APM_PYTHON_ENABLE=1 이 없으면 대상 스크립트를 그냥 그대로 실행한다 (전송 없음, 오버헤드 없음).
  스크립트/실행 커맨드를 다른 PC에 복사해도, 그 PC 쉘 환경에 이 변수가 없으면 아무 일도 안 일어난다.
- MACMON_APM_PYTHON_ENABLE=1 인 PC에서만 스크립트 전체 실행을 트레이스 1개(kind="cli")로 감싸서
  macmon-server에 보낸다. 미처리 예외는 root span에 실려 나간다.

의도적으로 이 스위치는 MACMON_APM_DISABLE(테스트용 킬스위치)과 별개다:
MACMON_APM_DISABLE은 "이미 계측되는 프로세스를 잠깐 끄기" 용도이고,
MACMON_APM_PYTHON_ENABLE은 "이 러너를 통해 실행되는 스크립트를 계측할지 말지"를 결정하는 opt-in 스위치다.
"""
from __future__ import annotations

import os
import runpy
import sys
import threading


def _usage() -> None:
    print("usage: python3 -m macmon_apm.run <script.py> [args...]", file=sys.stderr)


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        _usage()
        raise SystemExit(2)

    script, script_args = argv[0], argv[1:]
    # 대상 스크립트 입장에서 sys.argv가 원래 실행과 동일하게 보이도록 맞춘다.
    sys.argv = [script] + script_args
    # `python script.py`와 동일하게 스크립트 디렉터리를 sys.path 맨 앞에 둔다.
    # runpy.run_path는 이걸 자동으로 안 해줘서, 스크립트가 같은 폴더의 형제 모듈을
    # import하는 경우(예: from helper import X) 이게 없으면 ModuleNotFoundError가 난다.
    sys.path.insert(0, os.path.dirname(os.path.abspath(script)))

    if os.environ.get("MACMON_APM_PYTHON_ENABLE") != "1":
        runpy.run_path(script, run_name="__main__")
        return

    import macmon_apm
    from macmon_apm import _agent
    from macmon_apm.span import Trace, TraceSpan, new_trace_id

    macmon_apm.start()
    agent = _agent.get()

    tid = threading.get_ident()
    trace = Trace(id=new_trace_id(tid), host=agent.config.host, service=agent.config.service)
    trace.root = TraceSpan(kind="cli", tid=tid, thread_name=threading.current_thread().name)

    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        if e.code not in (None, 0):
            trace.root.exception_type = "SystemExit"
            trace.root.exception_msg = str(e.code)[:500]
        raise
    except BaseException as e:
        trace.root.exception_type = type(e).__name__
        trace.root.exception_msg = str(e)[:500]
        raise
    finally:
        trace.finish()
        agent.exporter.submit_trace(trace.to_dict())


if __name__ == "__main__":
    main()
