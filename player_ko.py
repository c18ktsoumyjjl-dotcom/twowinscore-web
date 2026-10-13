"""검증된 한글 선수 이름 사전 조회 (ko_names/ko_names.json, ko_names/build.py로 갱신). 없으면 None → 원래 이름."""
import json, os
_P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ko_names", "ko_names.json")
_D, _m = {}, 0


def lookup(sport, pid):
    global _D, _m
    try:
        mt = os.path.getmtime(_P)
        if mt != _m:
            _D, _m = json.load(open(_P, encoding="utf-8")), mt
    except Exception:
        return None
    v = (_D.get(sport) or {}).get(str(pid))
    return v.get("ko") if isinstance(v, dict) else v
