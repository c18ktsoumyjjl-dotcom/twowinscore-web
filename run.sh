#!/bin/bash
# 투윈스코어 웹 시험판. API_SPORTS_KEY 는 환경변수에서 읽는다(출력 안 함).
cd /workspace/score-web
exec .venv/bin/python app.py
