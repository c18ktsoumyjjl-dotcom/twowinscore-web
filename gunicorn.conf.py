# 서버 종류(gunicorn) 노출 방지: Server 헤더를 일반 값으로
import gunicorn.http.wsgi as _w
_w.SERVER = "web"
