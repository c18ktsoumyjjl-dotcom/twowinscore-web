# 투윈스코어 (TwowinSCORE) 웹

야구·농구·배구 스포츠 정보 사이트 (KBO, MLB, NPB, KBL, WKBL, V리그, NBA). 베팅/배당 정보 없음.

## 로컬 실행
    pip install -r requirements.txt
    export API_SPORTS_KEY=...   # 환경변수로만
    gunicorn app:app --bind 0.0.0.0:8088 --workers 1 --threads 8

## Render
render.yaml 사용(또는 Procfile). 대시보드에서 API_SPORTS_KEY 를 비밀값으로 입력.
캐시는 CACHE_DIR(기본 /tmp/twowinscore-cache). 워커는 1개로 유지(API 호출 캐시·잠금 공유).

## API 호출
진행 중 경기 종목만 15초마다(사용량이 하루 한도 60% 넘으면 60초), 그 외 10분~3시간 캐시.
브라우저는 5초마다 서버 캐시만 조회.

## 추가 기능 (2026-10-13) — plus.py, static/plus.js, static/plus.css, templates/predict.html
- 추정 승리확률(경기 상세, `/api/wp/<key>`): 점수·진행 상황·경기 전 배당으로 계산하는 단순 모델. 구간 기록 합이 실제 점수와 다르거나 기록이 없으면 숨김. 배구·기타 리그 미표시.
- 지금 핫한 경기 TOP 3(`/api/hot`): 오늘 화면, 진행 중·점수 차 작은 경기만. 접전도·진행도·채팅 열기로 순위.
- 예측 리그(`/api/pred`, `/predict`): 로그인 회원, 시작 전까지. 적중 5점, 스코어 정확 +5점 → levels.add_pts. 5분마다 자동 정산.
- 3줄 경기 요약(`/api/summary/<key>`, `plus.summary_text(key)`): 종료 경기, 실제 기록만. 텔레그램 채널 자동 게시는 꺼져 있음(호출하는 쪽에서 결정).
- 즐겨찾기 팀 웹 푸시: 소리 메뉴의 "즐겨찾기 팀 알림 켜기"(옵트인). 득점·역전·막판 접전.
  Render 환경변수(이름만): `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` (P-256, base64url 원시값), 선택 `VAPID_SUBJECT` (mailto:…). 둘 다 없으면 알림 기능은 꺼진 상태로 동작.
