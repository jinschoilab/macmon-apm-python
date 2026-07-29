"""테스트용 Flask 앱.

실행:
    pip install flask
    pip install -e ..             # macmon_apm 로컬 설치
    MACMON_APM_SERVICE=testapp MACMON_APM_URL=http://127.0.0.1:6600 \
        python testapp/app.py

요청:
    curl localhost:8090/hello
    curl localhost:8090/slow
    curl localhost:8090/error
"""
from __future__ import annotations

import random
import time

from flask import Flask

import macmon_apm

macmon_apm.start()
app = Flask(__name__)
app.wsgi_app = macmon_apm.WSGIMiddleware(app.wsgi_app)


@app.route("/hello")
def hello() -> str:
    return "hello\n"


@app.route("/slow")
def slow() -> str:
    time.sleep(0.1 + random.random() * 0.2)
    return "ok\n"


@app.route("/error")
def err() -> str:
    raise RuntimeError("intentional")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8090)
