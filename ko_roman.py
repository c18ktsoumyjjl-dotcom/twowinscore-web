"""한글 이름 ↔ 영문(로마자) 이름 대조. 선수마다 이름 자체로 확인될 때만 한글 이름을 붙이기 위한 용도.
여러 표기(성 관용 표기, 자음·모음 변이)를 후보로 만들고, 영문 이름 토큰과 정확히 같을 때만 일치로 봄. 약어(S. Hong)는 확인 불가 → 불일치."""
import itertools, re

_I = [["g", "k"], ["kk", "gg"], ["n"], ["d", "t"], ["tt", "dd"], ["r", "l"], ["m"], ["b", "p"], ["pp", "bb"], ["s", "sh"], ["ss"], [""],
      ["j", "ch"], ["jj"], ["ch"], ["k"], ["t"], ["p"], ["h"]]
_V = [["a"], ["ae"], ["ya"], ["yae"], ["eo", "u", "o"], ["e"], ["yeo", "yu", "yo"], ["ye"], ["o"], ["wa"], ["wae"], ["oe", "oi", "we"], ["yo"],
      ["u", "oo"], ["wo"], ["we"], ["wi"], ["yu", "yoo"], ["eu", "u"], ["ui", "eui", "i", "ee"], ["i", "ee"]]
_F = [[""], ["k", "g"], ["k"], ["k"], ["n"], ["n"], ["n"], ["t", "d"], ["l", "r"], ["k"], ["m"], ["l"], ["l"], ["l"], ["p"], ["l"], ["m"],
      ["p", "b"], ["p"], ["t", "s"], ["t"], ["ng"], ["t"], ["t"], ["k"], ["t"], ["p"], ["t"]]
SUR = {"이": ["lee", "yi", "rhee", "i"], "박": ["park", "pak", "bak"], "김": ["kim", "gim"], "정": ["jeong", "jung", "chung"], "최": ["choi", "choe"],
       "조": ["jo", "cho"], "강": ["kang", "gang"], "윤": ["yoon", "yun"], "장": ["jang", "chang"], "임": ["lim", "im"], "림": ["lim", "rim"],
       "오": ["oh", "o"], "서": ["seo", "suh"], "신": ["shin", "sin"], "권": ["kwon", "gwon"], "안": ["ahn", "an"], "유": ["yoo", "yu", "ryu"],
       "류": ["ryu", "yoo", "yu"], "전": ["jeon", "jun", "chun"], "고": ["ko", "go"], "문": ["moon", "mun"], "백": ["baek", "paik", "back"],
       "허": ["heo", "huh"], "노": ["noh", "no", "roh"], "곽": ["kwak", "gwak"], "성": ["sung", "seong"], "주": ["joo", "ju"], "우": ["woo", "u"],
       "구": ["koo", "gu", "ku"], "엄": ["eom", "um"], "천": ["cheon", "chun"], "변": ["byun", "byeon"], "염": ["yeom"], "여": ["yeo"], "추": ["choo", "chu"],
       "석": ["seok", "suk"], "설": ["seol", "sul"], "기": ["ki", "gi"], "국": ["kook", "guk"], "육": ["yook", "yuk"], "황": ["hwang"], "한": ["han"],
       "송": ["song"], "홍": ["hong"], "양": ["yang"], "손": ["son"], "배": ["bae"], "남": ["nam"], "심": ["sim", "shim"], "하": ["ha"], "차": ["cha"],
       "민": ["min"], "진": ["jin"], "나": ["na", "ra"], "지": ["ji"], "채": ["chae"], "원": ["won"], "방": ["bang"], "공": ["kong", "gong"],
       "현": ["hyun", "hyeon"], "함": ["ham"], "도": ["do"], "명": ["myung", "myeong"], "왕": ["wang"], "탁": ["tak"], "편": ["pyun", "pyeon"],
       "제": ["je"], "길": ["gil", "kil"], "연": ["yeon"], "위": ["wi"], "표": ["pyo"], "모": ["mo"], "금": ["geum", "keum"], "봉": ["bong"], "인": ["in"]}


def _syl(ch):
    c = ord(ch) - 0xAC00
    if not 0 <= c < 11172:
        return None
    i, v, f = c // 588, (c % 588) // 28, c % 28
    r = {a + b + z for a in _I[i] for b in _V[v] for z in _F[f]}
    if i == 11 and v == 13:   # 우 → woo/wu 관용
        r |= {"woo" + z for z in _F[f]} | {"wu" + z for z in _F[f]}
    return sorted(r)


def _norm(s):
    return re.sub(r"[^a-z ]", "", re.sub(r"[-'’.]", "", (s or "").lower())).split()


def candidates(ko):
    ko = (ko or "").strip()
    if not re.fullmatch(r"[가-힣]{2,4}", ko):
        return set()
    sur = SUR.get(ko[0]) or _syl(ko[0])
    gv = [_syl(c) for c in ko[1:]]
    if not sur or any(x is None for x in gv) or len(gv) > 3:
        return set()
    given = {"".join(p) for p in itertools.product(*gv)}
    out = set()
    for s in sur:
        for g in given:
            out.add((s, g))
    return out


def match(ko, en):
    """영문 이름이 성+이름(순서 무관, 하이픈·띄어쓰기 무관)으로 한글 이름의 표기 후보와 정확히 같으면 True. 약어·한 단어 이름은 False."""
    t = _norm(en)
    if len(t) < 2 or any(len(x) < 2 for x in t):
        return False
    c = candidates(ko)
    if not c:
        return False
    for i in range(len(t)):
        s = t[i]
        rest = "".join(t[:i] + t[i + 1:])
        if (s, rest) in c:
            return True
    return False


def looks_korean(en):
    t = _norm(en)
    surs = {x for v in SUR.values() for x in v}
    return len(t) >= 2 and any(x in surs for x in t) and all(len(x) >= 2 for x in t)


def close(ko, en):
    """약한 유사도(표기 변이 허용). 한국식 영문 이름인데 이 값이 낮으면 다른 사람."""
    import difflib
    t = _norm(en)
    if not t:
        return 0
    best = 0
    for s, g in candidates(ko):
        for i in range(len(t)):
            a = s + "".join(t[:i] + t[i + 1:]) if False else None
            best = max(best, difflib.SequenceMatcher(None, s + g, t[i] + "".join(t[:i] + t[i + 1:])).ratio())
    return best
