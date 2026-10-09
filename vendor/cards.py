"""웹 전용 스텁. 봇의 이미지 카드(cards.py)는 웹에서 쓰지 않는다. 텍스트만 필요한 함수는 빈 값을 돌려준다."""


def help_caption():
    return ""


def __getattr__(name):
    def _unused(*a, **k):
        raise RuntimeError(f"cards.{name} is not available in score-web")
    return _unused
