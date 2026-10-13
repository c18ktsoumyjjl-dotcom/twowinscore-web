"""팀 이름 안전장치: 한글 매핑이 확인된 영문 원본명(team_en.json)과 현재 업스트림 이름이 다르면
(팀 ID 재사용·매각·리브랜딩 등) 틀린 한글명 대신 업스트림 이름을 그대로 보여줘요."""
import json, os, re, logging
_P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "team_en.json")
try:
    BASE = json.load(open(_P, encoding="utf-8"))
except Exception:
    BASE = {}
_warned = set()
_n = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())


def ok(kind, tid, en):
    """매핑을 써도 되면 True. 기준 영문명이 없거나 업스트림 이름이 없으면 판단 불가 → True."""
    b = BASE.get(f"{kind}:{tid}")
    if not b or not en or _n(b) == _n(en):
        return True
    if (kind, tid) not in _warned:
        _warned.add((kind, tid))
        logging.getLogger("nameguard").warning("team name mismatch %s:%s base=%r upstream=%r", kind, tid, b, en)
    return False
