"""결제 연결 자리(아직 결제사 없음).
결제사를 붙일 때:
 1) ready() 가 True 를 돌려주게 하고
 2) start_charge(member_id, amount) 에서 결제창 URL 을 만들어 돌려주고 (주문번호 order_id 를 만들어 저장)
 3) 결제사 웹훅/리턴 라우트에서 서명·금액을 검증한 뒤 on_paid(member_id, amount, order_id) 를 부르면
    스코어캐시가 1원=1캐시로 충전되고 원장(cash_log)에 남아요. 같은 order_id 는 한 번만 충전돼요.
"""
PROVIDER = None


def ready():
    return PROVIDER is not None


def start_charge(member_id, amount, items=None):
    """items: [(패키지 캐시, 수량), ...] · amount: 합계(원)"""
    if not ready():
        return None
    raise NotImplementedError


def on_paid(member_id, amount, order_id):
    import vip
    return vip.cash_change(member_id, int(amount), "charge", f"충전 {int(amount):,}원", ref="pay:" + str(order_id))
