# macmon-apm-python

macmon Python APM 에이전트. **현재 Step 0 — 스켈레톤 + WSGI 미들웨어 + 런타임 샘플러.**

Java(JVMTI) / Go(eBPF) APM과 동일한 wire format(`Trace`/`TraceSpan` + `APMRuntimeSample`)을 사용해 기존 macmon-server 수집 인프라(`POST /api/traces`, `POST /api/apm/runtime`)에 그대로 붙는다.

## 설계 원칙

- **표준 라이브러리만 사용** — `urllib`/`threading`/`gc`/`resource`만으로 동작. 외부 의존성 없음
- **동기/멀티스레드 안전** — 모든 export는 데몬 스레드 + bounded queue를 통해 비차단으로 처리
- **Java/Go APM wire format 호환** — `macmon-server/internal/storage/traces.go`의 Trace 구조 그대로 직렬화
- **현재 한계** — WSGI 진입점 한 단계 스팬만. DB/outbound HTTP 자식 스팬은 step 1.

## Layout

```
macmon-apm-python/
├── macmon_apm/
│   ├── __init__.py     # public API: start(), stats(), WSGIMiddleware
│   ├── _agent.py       # 싱글턴 컨테이너 (Exporter + RuntimeSampler 보관)
│   ├── config.py       # 환경변수 → Config 데이터클래스
│   ├── span.py         # Trace, TraceSpan dataclass + JSON 직렬화 (서버 키와 일치)
│   ├── exporter.py     # 백그라운드 데몬 스레드 + bounded queue + urllib POST
│   ├── runtime.py      # 30초 주기 GC/threading/RSS 샘플러
│   └── wsgi.py         # WSGIMiddleware — server 스팬 자동 생성
├── testapp/
│   ├── app.py          # Flask /hello /slow /error
│   └── requirements.txt
├── pyproject.toml
└── README.md
```

## 사용

```python
import macmon_apm
macmon_apm.start()

# WSGI (Flask/Django/etc)
from macmon_apm import WSGIMiddleware
app.wsgi_app = WSGIMiddleware(app.wsgi_app)
```

### 환경변수

| 키 | 기본값 | 의미 |
|---|---|---|
| `MACMON_APM_URL` | `http://127.0.0.1:6600` | macmon-server 수집 포트 |
- `MACMON_APM_KEY` : 테넌트/팀 API 키(`mak_…`). 서버가 이 키로 기록의 테넌트를 확정한다. 없으면 default 테넌트
| `MACMON_APM_SERVICE` | argv[0] basename | 서비스명. UI에서 그룹 키 |
| `MACMON_APM_HOST` | `socket.gethostname()` | 호스트 식별자 |
| `MACMON_APM_DISABLE` | `0` | `1`이면 모든 전송 끔 (테스트용) |
| `MACMON_APM_RUNTIME_INTERVAL_SEC` | `30` | 런타임 샘플 주기 |

## CLI/배치 스크립트 자동 계측 (소스 수정 없음)

WSGI 앱이 아닌 일반 스크립트(크론잡, 배치, 스크래퍼 등)는 `-m macmon_apm.run`으로 감싸서 실행하면 대상 스크립트를 한 글자도 안 고치고 트레이스 1개(`kind="cli"`)로 전체 실행을 계측할 수 있다.

```bash
python3 -m macmon_apm.run my_script.py arg1 arg2
```

**opt-in 스위치**: `MACMON_APM_PYTHON_ENABLE=1`이 환경에 없으면 `run`은 대상 스크립트를 그냥 그대로 실행한다 (전송 없음, import 비용만 있음). 즉 계측 여부는 스크립트나 실행 커맨드가 아니라 **그 PC의 쉘 환경**에 달려 있다 — 스크립트를 다른 PC로 복사해도 그 PC의 `~/.zshrc` 등에 `MACMON_APM_PYTHON_ENABLE=1`이 없으면 아무 것도 안 보낸다. "이 PC에서 도는 것만 잡고 싶다" 같은 요구는 이 변수를 해당 PC의 쉘 프로필에만 심는 식으로 해결한다 (스크립트/저장소에는 절대 넣지 않는다).

```bash
# 이 PC의 ~/.zshrc 에만 추가 (naver 폴더 안에는 넣지 않음)
export MACMON_APM_PYTHON_ENABLE=1
```

## 테스트앱 실행

```bash
pip install -e .
pip install -r testapp/requirements.txt
MACMON_APM_SERVICE=testapp MACMON_APM_URL=http://127.0.0.1:6600 \
    python testapp/app.py

# 다른 터미널
curl localhost:8090/hello
curl localhost:8090/slow
curl localhost:8090/error || true

# macmon UI(/apm) 또는 macmon-server data/{host}/_apm/{YYYY-MM-DD}.jsonl 에서 트랜잭션 확인
```

## Wire format

`Trace` 객체는 다음 JSON으로 직렬화 (서버 `storage.Trace` 호환):

```json
{
  "id": "tx_<tid>_<ns>",
  "host": "macbook-01",
  "pid": 12345,
  "comm": "python",
  "service": "testapp",
  "wall_at": "2026-05-07T01:00:00.123456789Z",
  "start_ns": 12345678,
  "duration_ns": 23456789,
  "root_goid": 0,
  "root": {
    "kind": "server",
    "tid": 8675309,
    "thread_name": "MainThread",
    "start_ns": 12345678,
    "duration_ns": 23456789,
    "http_method": "GET",
    "http_path": "/hello",
    "http_status": 200,
    "children": []
  }
}
```

런타임 샘플은 `APMRuntimeSample`의 일부 필드만 채움. Step 0에서는 Java용 `jvm_*` 필드를 재사용 (UI가 이미 그래프로 표시하기 때문). Step 1에서 서버에 `py_*` 전용 필드 추가 후 정리 예정.

## 구현 상태 / 로드맵

| 단계 | 항목 | 상태 |
|---|---|---|
| 0 | pyproject + 패키지 골격 | ✅ |
| 0 | Wire format (Trace/TraceSpan dataclass) | ✅ |
| 0 | HTTP exporter (큐 + 데몬 스레드) | ✅ |
| 0 | 런타임 샘플러 (gc/threading/RSS) | ✅ |
| 0 | WSGI 미들웨어 (server 스팬) | ✅ |
| 0 | testapp(Flask) | ✅ |
| 1 | ASGI 미들웨어 (FastAPI/Starlette) | ⬜ |
| 1 | DB 자식 스팬 — psycopg2/PyMySQL/sqlalchemy 패치 | ⬜ |
| 1 | Outbound HTTP — requests/urllib3/httpx 패치 | ⬜ |
| 1 | Exception 스팬 — sys.excepthook + WSGI exc | ⬜ |
| 1 | 자동 부착 — `python -m macmon_apm.run <cmd>` | ✅ |
| 1 | 스레드 스택 스냅샷 (Active Stack, 끝나지 않는 프로세스용) | ✅ |
| 1 | 서버 측 `py_*` runtime 필드 추가 + UI 분기 | ⬜ |
| 2 | wrapt 기반 import hook으로 Django/Flask 자동 미들웨어 주입 | ⬜ |

## 끝나지 않는 배치 스크립트 (n.sh 같은 크론잡/크롤러)

`macmon_apm.run`으로 감싼 트레이스는 **대상 스크립트가 종료해야만** 나간다. 명시적으로 끊기 전까지 계속 도는 스크립트(크롤러, 워커 등)는 트레이스가 영원히 안 나갈 수 있다.

이런 경우를 위해 `start()`는 트레이스와 무관하게 5초(기본, `MACMON_APM_STACK_INTERVAL_SEC`)마다 살아있는 스레드 전체의 콜스택을 찍어 `POST /api/traces/stacks`로 보낸다 — Java APM의 Active Stack과 동일한 개념. 프로세스가 살아있는 한 계속 나가므로, macmon UI의 **Active Stack** 화면에서 "지금 어느 함수에서 멈춰 있는지"를 실시간으로 볼 수 있다. 트랜잭션 단위(사이트별 소요시간 등) 세분화는 안 되지만, 최소한 "살아있다 + 지금 뭘 하고 있다"는 코드 수정 없이 항상 보장된다.

## 주의사항

- `WSGIMiddleware`는 응답 본문 close 시점까지 기다려 duration을 잰다. 즉 streaming response의 경우 실제 처리 시간 + 클라이언트 수신 시간이 함께 들어감
- 런타임 샘플의 `jvm_heap_used_kb`는 실제로 프로세스 RSS. UI 차트에 그대로 묻어 보이지만 정확한 의미는 step 1에서 분리
- `start()`는 idempotent — 여러 번 import / 호출해도 한 번만 초기화
- 이미 실행 중인 프로세스는 코드를 고쳐도 핫리로드가 안 된다 — 새 기능(예: 스택 스냅샷)을 받으려면 프로세스 재시작 필요
