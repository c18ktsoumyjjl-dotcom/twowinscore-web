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
