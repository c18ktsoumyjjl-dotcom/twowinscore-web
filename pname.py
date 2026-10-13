"""선수 이름 한글 조회 훅 (단일 진입점). 다른 작업에서 추가하는 검증된 사전(API-Sports id 기준)이 있으면 그걸 쓰고, 없으면 원래 이름.
사전 위치 후보: player_ko.py 의 KO dict / lookup(sport,pid) 함수, 또는 data/player_ko.json {"football": {"123": "손흥민"}}."""
import json, os, time
_D, _t = None, 0


def _load():
    global _D, _t
    if _D is not None and time.time() - _t < 600:
        return _D
    d = {}
    try:
        import player_ko as m
        if hasattr(m, "lookup"):
            d = {"_fn": m.lookup}
        else:
            d = getattr(m, "KO", {}) or {}
    except Exception:
        pass
    if not d:
        try:
            with open(os.path.join(os.path.dirname(__file__), "data", "player_ko.json"), encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
    _D, _t = d, time.time()
    return d


def ko(sport, pid, fallback):
    """검증된 한글 이름이 있으면 반환, 없으면 fallback 그대로."""
    if pid is None:
        return fallback
    d = _load()
    try:
        if "_fn" in d:
            v = d["_fn"](sport, pid)
        else:
            s = d.get(sport) if isinstance(d.get(sport), dict) else d
            v = s.get(str(pid)) or s.get(pid)
    except Exception:
        v = None
    return v or fallback
