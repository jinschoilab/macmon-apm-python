# macmon-apm-python — Claude 컨텍스트

Python APM 에이전트. **Step 0 스켈레톤 완료** — Java/Go APM과 동일한 wire format으로 macmon-server에 전송.

## 핵심 사실

- 외부 의존성 0개. `urllib`/`threading`/`gc`/`resource`만 사용
- Wire format은 서버의 `macmon-server/internal/storage/traces.go`의 `Trace`/`TraceSpan`과 동일. 키 이름이 정확히 일치해야 함 (`span.py`의 `to_dict()`)
- 데몬 스레드 + bounded queue (1024) 모델. 큐 가득 차면 드롭, 절대 앱을 막지 않음
- `start()`는 idempotent — 두 번 import 해도 안전
- 런타임 필드는 Step 0에서 Java용 `jvm_*` 필드를 재사용 (UI 그래프 호환). Step 1에서 서버 측 `py_*` 추가 예정

## 파일 가이드

- `__init__.py` — public API (start, stats, WSGIMiddleware)
- `_agent.py` — Agent 싱글턴 (Exporter + RuntimeSampler + StackSampler 묶음)
- `config.py` — 환경변수 → Config dataclass
- `span.py` — Trace/TraceSpan + `_now_ns()`(monotonic 기반) + `_wall_now()`(RFC3339 nano)
- `exporter.py` — bounded queue + 데몬 스레드 + atexit flush(1초 한도)
- `runtime.py` — 30초 주기. `_rss_kb()`는 macOS/Linux의 `ru_maxrss` 단위 차이 보정
- `stacksampler.py` — 5초 주기(기본) 전체 스레드 콜스택 스냅샷 → `POST /api/traces/stacks`. Trace와 무관하게 프로세스가 살아있는 동안 계속 나감 (Java `StackSampler`와 동일 개념)
- `wsgi.py` — `_IterWrapper`로 응답 close 시점까지 기다려 duration 측정
- `run.py` — `python -m macmon_apm.run <script> [args]`. 대상 스크립트 무수정 자동 계측. `MACMON_APM_PYTHON_ENABLE=1`이 없으면 완전 투명 passthrough (계측 여부는 스크립트가 아니라 실행 환경에 달림 — 스크립트 복사 배포 시 안전)

## 다음 단계 (Step 1) 우선순위

1. **DB 자식 스팬** — psycopg2/PyMySQL의 `cursor.execute` wrap. `wrapt.wrap_function_wrapper` 사용 시 의존성 1개 추가
2. **Outbound HTTP** — `requests`의 `Session.send` 패치 또는 `urllib3.connectionpool`
3. **ASGI 미들웨어** — `wsgi.py` 옆에 `asgi.py`. FastAPI/Starlette 대상
4. ~~자동 부착~~ — `run.py`로 완료
5. **서버 측 py_* 필드** — `macmon-server/internal/storage/apm_runtime.go`의 `APMRuntimeSample`에 `PyThreads`, `PyRSS`, `PyGCCounts` 등 추가. UI 분기는 lang="python"으로

## 주의

- `_BOOT_NS = time.monotonic_ns()` 모듈 로드 시점에 캡처. 멀티 프로세스(fork)에서도 부모/자식 모두 같은 값을 갖지 않으니 fork 후엔 새로 import해야 정확함 — Step 1에서 `os.register_at_fork` 처리 필요
- WSGI body 가 generator이면 `_IterWrapper`가 close까지 못 받는 케이스가 있을 수 있음 — Flask/Werkzeug는 정상 close, 일부 비표준 서버는 검증 필요
- 런타임 샘플의 첫 발송은 5초 지연(서비스명 안정화 시간). interval_sec 최소 5초로 클램프
- **`run.py`로 감싼 트레이스(`kind="cli"`)는 대상 스크립트가 종료해야만 나간다.** `n.py`처럼 명시적으로 안 끊는 한 안 끝나는 배치 스크립트는 트레이스가 영원히 안 나갈 수 있음 — 그런 경우 "지금 살아있고 뭘 하는지"는 트레이스가 아니라 StackSampler(Active Stack 화면)로 확인해야 함
- 이미 떠 있는 프로세스는 `pip install -e` 재설치나 코드 수정을 해도 core Python이 핫리로드를 안 하므로 반영 안 됨 — 새 기능을 적용하려면 프로세스를 재시작해야 함
