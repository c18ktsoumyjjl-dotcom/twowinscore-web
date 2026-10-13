"""생생한 문자중계 생성기 — 실제 데이터(이벤트·점수 변화·공식 기록)만으로 문장을 만든다.
지어내지 않는다: 패스 경로, 위치, 일어나지 않은 플레이는 절대 쓰지 않는다.
- 이벤트별 문장 10개 이상, 같은 종류가 연달아 같은 문장이 되지 않게 고른다(결정적, 폴링마다 바뀌지 않음).
- 점수 흐름(연속 득점·동점·역전·접전·대승·세트/매치 포인트·막판·연장)을 실제 점수로만 감지.
- ctx: 새 이벤트가 없을 때 돌려 보여 줄 실제 상황 줄(점수, 진행 시간, 흐름, 기록).
"""
import re, time, zlib, threading

_hist = {}      # 게임키 -> [(ts, period, h, a)]  (점수 변화가 있을 때만 추가)
_stats = {}     # 축구 기록 스냅샷
_lock = threading.Lock()

# ---------------------------------------------------------------- 문장 은행
T = {
 # ⚽ 축구
 "fb_goal": [
  "⚽🔥 {m} 골!! {t} {p}, 마침내 골망을 흔듭니다!",
  "⚽ {m} 들어갔어요! {t} {p} 득점! 경기장이 뒤집어집니다",
  "⚽🔥 {m} {p}! {t}에 귀중한 한 골을 선물합니다",
  "⚽ {m} 골~~! {t} {p}, 이 순간을 기다렸어요",
  "⚽💥 {m} {t} 득점! 주인공은 {p}!",
  "⚽ {m} {p}의 한 방! {t}가 점수를 올립니다",
  "⚽🔥 {m} 터졌습니다! {t} {p} 골!!",
  "⚽ {m} 골문이 열렸어요! {t} {p} 득점 성공",
  "⚽ {m} {t} {p}, 해냈습니다! 골!",
  "⚽💥 {m} 이게 축구죠! {t} {p} 골!!",
  "⚽ {m} 스코어보드가 바뀝니다 — {t} {p} 득점!",
  "⚽🔥 {m} {p} 골! {t}에 아주 큰 한 골"],
 "fb_pgoal": [
  "⚽🎯 {m} 페널티킥 성공! {t} {p}, 침착했어요",
  "⚽🎯 {m} {p}, 11m 앞에서 흔들림 없이 성공!",
  "⚽ {m} PK 골! {t} {p} 가볍게 마무리합니다",
  "⚽🎯 {m} 키커 {p}, 골! {t} 득점",
  "⚽ {m} 강심장 {p}! 페널티킥 성공",
  "⚽🎯 {m} {t} 페널티 골! {p}의 냉정한 마무리",
  "⚽ {m} {p} PK 성공, {t}가 웃습니다",
  "⚽🎯 {m} 부담감 따위! {p} 페널티킥 골",
  "⚽ {m} {t} {p}, 페널티 스폿에서 득점!",
  "⚽🎯 {m} 골키퍼와의 승부, {p}가 이겼어요!"],
 "fb_og": [
  "😱 {m} 자책골! {t} 쪽으로 점수가 올라갑니다",
  "😱 {m} 아이고… 자책골, {t}가 행운의 득점",
  "😵 {m} 이런! 자책골로 {t} 득점",
  "😱 {m} 예상 못 한 장면, 자책골! ({t} 득점)",
  "😵 {m} 불운의 자책골 — {t}에게 한 점",
  "😱 {m} 자책골이 나왔어요! {t} 득점 인정",
  "😵 {m} 이건 너무 아쉽네요, 자책골 ({t} 득점)",
  "😱 {m} 공이 자기 골문으로… {t} 득점",
  "😵 {m} 자책골! 스코어가 바뀝니다 ({t})",
  "😱 {m} 뜻밖의 득점, 자책골로 {t}가 한 골"],
 "fb_pmiss": [
  "😱 {m} 페널티킥 실축! {t} {p}, 믿기지 않아요",
  "😱 {m} 놓쳤어요! {p}의 PK가 들어가지 않습니다",
  "🧤 {m} PK 실패! {t} 절호의 기회를 날립니다",
  "😱 {m} 아~ {p}! 페널티킥 실축",
  "😱 {m} 이럴 수가, {t} PK 무산",
  "🧤 {m} 페널티킥이 막히거나 빗나갔어요 — {p} 실축",
  "😱 {m} {t} {p}, 고개를 숙입니다. PK 실축",
  "😱 {m} 들어갔다면… {p} 페널티 실축!",
  "🧤 {m} 승부의 분수령, {t} PK 실패",
  "😱 {m} {p} 실축! 경기장에 탄식이 흐릅니다"],
 "fb_yel": [
  "🟨 {m} {t} {p}, 옐로카드",
  "🟨 {m} 주심이 카드를 꺼냅니다 — {p} 경고",
  "🟨 {m} {p} 경고! 이제 조심해야 해요",
  "🟨 {m} {t} {p}에게 옐로카드",
  "🟨 {m} 경고 누적 주의보, {p} 옐로",
  "🟨 {m} {p}, 카드 받았어요 ({t})",
  "🟨 {m} 거칠었다는 판정, {p} 경고",
  "🟨 {m} {t} 경고 하나 추가 — {p}",
  "🟨 {m} 주심 단호합니다, {p} 옐로카드",
  "🟨 {m} {p} 옐로! 남은 시간 더 신중해야겠네요"],
 "fb_red": [
  "🟥 {m} 퇴장!! {t} {p}, 레드카드",
  "🟥 {m} 레드카드! {t}가 수적 열세에 놓입니다",
  "🟥 {m} {p} 퇴장! 경기 흐름이 요동칩니다",
  "🟥 {m} 주심 레드카드 선언 — {p}",
  "🟥 {m} {t} 한 명이 줄어듭니다, {p} 퇴장",
  "🟥 {m} 이건 큽니다! {p} 레드카드",
  "🟥 {m} {p}, 그라운드를 떠납니다 (퇴장)",
  "🟥 {m} 퇴장 변수! {t} 비상",
  "🟥 {m} {t} {p} 레드! 남은 시간 10명으로",
  "🟥 {m} 경기의 판도를 흔드는 퇴장, {p}"],
 "fb_sub": [
  "🔁 {m} {t} 교체 · {p} ↔ {a}",
  "🔁 {m} {t} 벤치가 움직입니다 ({p} ↔ {a})",
  "🔁 {m} 승부수! {t} 교체 카드 ({p} ↔ {a})",
  "🔁 {m} {t} 카드 꺼냈어요 — {p} ↔ {a}",
  "🔁 {m} {t} 변화를 줍니다: {p} ↔ {a}",
  "🔁 {m} 감독의 선택, {t} 교체 ({p} ↔ {a})",
  "🔁 {m} {t} 선수 교체 · {p} ↔ {a}",
  "🔁 {m} 새 에너지 투입, {t} ({p} ↔ {a})",
  "🔁 {m} {t} 교체로 흐름 바꾸기 ({p} ↔ {a})",
  "🔁 {m} {t} 라인업 변화 — {p} ↔ {a}"],
 "fb_var": [
  "📺 {m} VAR 체크 중… {x}",
  "📺 {m} 비디오 판독 결과: {x}",
  "📺 {m} 모니터 앞의 주심, 판정은 {x}",
  "📺 {m} VAR 개입! {x}",
  "📺 {m} 다시 보니… {x}",
  "📺 {m} 판독 끝, {x}",
  "📺 {m} VAR 판정: {x} ({t})",
  "📺 {m} 경기장이 숨죽였어요 — {x}",
  "📺 {m} 기술이 결정했습니다: {x}",
  "📺 {m} VAR 리뷰 결과 {x}"],
 "fb_corner": [
  "🚩 {m} 무렵 {t} 코너킥 (이번 경기 {n}번째)",
  "🚩 {m} 무렵 {t}, 코너킥 기회! ({n}개째)",
  "🚩 {m} 무렵 {t} 세트피스 찬스 — 코너킥 {n}개",
  "🚩 {m} 무렵 코너 플래그 앞에 {t}! (코너킥 {n})",
  "🚩 {m} 무렵 {t} 코너킥 추가, 누적 {n}개",
  "🚩 {m} 무렵 {t} 코너킥! 골문 앞이 붐빕니다",
  "🚩 {m} 무렵 또 코너킥, {t} {n}번째",
  "🚩 {m} 무렵 {t} 공격이 이어져 코너킥 ({n})",
  "🚩 {m} 무렵 {t} 코너킥 획득 — 오늘 {n}개",
  "🚩 {m} 무렵 {t}, 세트피스로 노립니다 (코너 {n})"],
 "fb_sot": [
  "🎯 {m} 무렵 {t} 유효 슈팅! (유효 {n}개째)",
  "🎯 {m} 무렵 {t}, 골문으로 향하는 슈팅 기록 ({n})",
  "🧤 {m} 무렵 {t} 유효 슈팅 추가 — 골키퍼가 바빠요",
  "🎯 {m} 무렵 {t} 골문을 두드립니다, 유효 {n}",
  "🎯 {m} 무렵 {t} 유효 슈팅 {n}개째!",
  "🧤 {m} 무렵 {t} 슈팅이 골문으로! 누적 유효 {n}",
  "🎯 {m} 무렵 {t} 위협적인 장면, 유효 슈팅 기록",
  "🎯 {m} 무렵 {t} 다시 한번 유효 슈팅 ({n})",
  "🧤 {m} 무렵 골키퍼를 시험하는 {t}, 유효 {n}",
  "🎯 {m} 무렵 {t} 유효 슈팅 추가요!"],
 "fb_shot": [
  "💨 {m} 무렵 {t} 슈팅! (전체 {n}개째)",
  "💨 {m} 무렵 {t}가 때려 봅니다, 슈팅 {n}",
  "💨 {m} 무렵 {t} 슈팅 기록 추가 ({n})",
  "💨 {m} 무렵 {t} 과감한 슈팅 시도!",
  "💨 {m} 무렵 {t} 또 슈팅, 오늘 {n}개째",
  "💨 {m} 무렵 {t} 슈팅 — 계속 노립니다",
  "💨 {m} 무렵 {t} 공격 마무리는 슈팅 ({n})",
  "💨 {m} 무렵 {t} 슈팅 하나 더 추가",
  "💨 {m} 무렵 {t}, 골문을 겨냥한 시도 ({n})",
  "💨 {m} 무렵 {t} 슈팅! 계속 두드립니다"],
 # 🏒 하키
 "hk_goal": [
  "🏒🔥 {m} 골!! {t} {p}",
  "🏒 {m} 퍽이 그물을 흔듭니다! {t} 득점 ({p})",
  "🏒🔥 {m} {t} 골! 주인공 {p}",
  "🏒 {m} 링크가 들썩여요 — {t} {p} 골",
  "🏒💥 {m} {p}의 한 방! {t} 득점",
  "🏒 {m} 골라인을 넘었습니다! {t} 골",
  "🏒🔥 {m} {t} 득점 성공! {p}",
  "🏒 {m} 골리도 어쩔 수 없었어요, {t} {p} 골",
  "🏒💥 {m} 터졌다! {t} {p}",
  "🏒 {m} 스코어 변동! {t} {p} 득점",
  "🏒🔥 {m} {p} 골! {t} 벤치 환호"],
 "hk_pen": [
  "⏱ {m} {t} 페널티 — {p} 페널티 박스로",
  "⏱ {m} 반칙 판정, {t} {p} 페널티",
  "⏱ {m} {t} 페널티! 잠시 버텨야 해요",
  "⏱ {m} {p}, 페널티 박스행 ({t})",
  "⏱ {m} 심판 휘슬! {t} {p} 페널티",
  "⏱ {m} {t} 휘슬 — {p} 페널티",
  "⏱ {m} {p} 페널티, {t} 버텨야 해요",
  "⏱ {m} {t} 반칙 — {p}",
  "⏱ {m} 페널티 선언 ({t} {p})",
  "⏱ {m} {t} {p}, 잠시 쉬어 갑니다 (페널티)"],
 # 득점 흐름 공통
 "equal": [
  "🤝 동점!! 원점으로 돌아갑니다 — {sc}",
  "🤝 따라잡았어요! {t} 동점 성공 ({sc})",
  "🤝 승부는 다시 처음부터! {sc}",
  "🤝 {t}의 추격 완성, 동점! {sc}",
  "🤝 균형을 맞춥니다! {sc}",
  "🤝 이래서 끝까지 봐야 해요, 동점 {sc}",
  "🤝 {t} 포기하지 않았어요! {sc}",
  "🤝 스코어 타이! {sc}",
  "🤝 다시 팽팽해졌습니다 — {sc}",
  "🤝 {t} 동점 만들어 냅니다! {sc}"],
 "lead": [
  "🔄 역전!! {t}가 앞서 나갑니다 ({sc})",
  "🔄 뒤집었어요! {t} 리드 ({sc})",
  "🔄 판이 바뀝니다 — {t} 역전 ({sc})",
  "🔄 {t} 역전 성공! {sc}",
  "🔄 이 경기 주인이 바뀌었어요, {t} 리드 {sc}",
  "🔄 대역전 드라마의 시작? {t} 앞서요 ({sc})",
  "🔄 {t}가 경기를 뒤집습니다! {sc}",
  "🔄 리드 체인지! {t} {sc}",
  "🔄 {t}, 드디어 앞으로 치고 나갑니다 ({sc})",
  "🔄 흐름 반전! {t} 역전 {sc}"],
 "first": [
  "🥇 선취점! {t}가 먼저 웃습니다 ({sc})",
  "🥇 균형이 깨졌어요 — {t} 선제 득점 {sc}",
  "🥇 {t} 먼저 앞서 나갑니다! {sc}",
  "🥇 첫 득점은 {t}! {sc}",
  "🥇 {t} 기선 제압! {sc}",
  "🥇 0의 균형을 {t}가 깹니다 ({sc})",
  "🥇 {t} 리드 잡았어요, {sc}",
  "🥇 먼저 터뜨린 쪽은 {t}! {sc}",
  "🥇 {t} 선제골, 분위기 가져갑니다 {sc}",
  "🥇 경기의 첫 장면 주인공은 {t} ({sc})"],
 "ahead": [
  "⬆️ 균형 깨졌어요! {t} 다시 앞서갑니다 ({sc})",
  "⬆️ {t} 리드 되찾습니다 — {sc}",
  "⬆️ 동점 깨는 {t}! {sc}",
  "⬆️ {t}, 한 발 앞으로! {sc}",
  "⬆️ 팽팽하던 승부, {t} 쪽으로 기울어요 ({sc})",
  "⬆️ {t} 앞서 나갑니다! {sc}",
  "⬆️ 다시 리드! {t} {sc}",
  "⬆️ {t} 결정적일 수 있는 득점 ({sc})",
  "⬆️ 균형추가 {t} 쪽으로 ({sc})",
  "⬆️ {t} 리드 탈환! {sc}"],
 "late": [
  "⏰ 막판 득점!! {t}, 이 시간에 해냅니다 ({sc})",
  "⏰ 극장 분위기! {t} 늦은 시간 득점 {sc}",
  "⏰ 경기 막바지 {t}의 한 방! {sc}",
  "⏰ 시계가 얼마 안 남았는데… {t} 득점! {sc}",
  "⏰ 클러치 타임 {t}! {sc}",
  "⏰ 끝날 때까지 끝난 게 아니에요, {t} {sc}",
  "⏰ 종료 직전 {t} 득점! {sc}",
  "⏰ 극적인 순간, {t}! {sc}",
  "⏰ 마지막에 웃는 건 {t}일까요? {sc}",
  "⏰ 막판 스코어 변동, {t}! {sc}"],
 "brace": [
  "✌️ {p} 멀티골! 오늘 {n}골째",
  "✌️ {p}, 오늘 날아다녀요 — {n}번째 골",
  "✌️ 또 {p}! 이 경기 {n}골",
  "🎩 {p} {n}골째! 오늘의 주인공",
  "✌️ {p} 득점 행진, 벌써 {n}골",
  "✌️ {t} {p}, 오늘 {n}골 폭발",
  "🎩 {p}가 또 해냈어요 ({n}골)",
  "✌️ 멈추지 않는 {p}, {n}골째",
  "✌️ {p} 원맨쇼! {n}골",
  "🎩 {p}의 날! 벌써 {n}번째 득점"],
 "run": [
  "🔥 {t} {n}연속 득점! 흐름 완전히 가져갑니다 ({sc})",
  "🔥 {t} 질주! 최근 {n}점 연속 ({sc})",
  "🔥 멈추지 않는 {t}, {n}점째 연속 득점 {sc}",
  "🔥 {t} 런 진행 중 — {n}:0 ({sc})",
  "🔥 상대가 막지 못해요, {t} {n}연속 득점",
  "🔥 {t} 분위기 최고조! {n}점 연속 {sc}",
  "🔥 {t} 쓸어 담습니다, {n}연속 ({sc})",
  "🔥 {t}의 시간! 연속 {n}점",
  "🔥 흐름은 {t} 쪽으로, {n}점 연속 {sc}",
  "🔥 {t} 몰아칩니다 — {n}-0 런",
  "🔥 {t} {n}연속! 상대 벤치 타임아웃 고민될 듯 ({sc})"],
 "blow": [
  "📈 {t} {n}점 차까지 벌립니다 ({sc})",
  "📈 점수 차가 커져요 — {t} +{n}",
  "📈 {t} 독주 체제, {n}점 차 {sc}",
  "📈 {t} 여유 있는 리드, {n}점 차",
  "📈 격차 {n}점! {t} 쭉쭉 달아납니다",
  "📈 {t} 압도 중, {sc}",
  "📈 {t} 리드 {n}점으로 확대",
  "📈 {t} 승리에 한 걸음 더, {n}점 차",
  "📈 {t} 무서운 기세, {n}점 앞서요",
  "📈 따라가기 벅찬 격차, {t} +{n}"],
 # 🏀 농구
 "bb_q": [
  "🏀 {q} 종료! 이번 쿼터 {qs} · 전체 {sc}",
  "🏀 {q} 끝, 쿼터 스코어 {qs} ({sc})",
  "🏀 {q} 마무리 — {w} 쿼터 우세 ({qs})",
  "🏀 {q} 결과 {qs}, 누적 {sc}",
  "🏀 {q} 종료 휘슬, {w}가 쿼터를 가져갔어요 ({qs})",
  "🏀 {q} 정리: {qs} · 합계 {sc}",
  "🏀 {q} 끝났어요! {w} 쿼터 승 ({qs})",
  "🏀 숨 고르기, {q} 스코어 {qs}",
  "🏀 {q} 종료 — 전체 스코어 {sc}",
  "🏀 {q}는 {w}의 몫, {qs}"],
 "bb_qt": [
  "🏀 {q} 종료, 쿼터 동점 {qs} ({sc})",
  "🏀 {q} 팽팽하게 끝! {qs}",
  "🏀 {q} 무승부 쿼터 {qs}, 누적 {sc}",
  "🏀 {q} 우열을 못 가렸어요 ({qs})",
  "🏀 {q} 동점으로 마무리 — {sc}",
  "🏀 {q} 결과 {qs}, 완벽한 균형",
  "🏀 {q} 끝, 똑같이 주고받았어요 {qs}",
  "🏀 {q} 무승부, 다음 쿼터가 승부처",
  "🏀 {q} 동률 {qs} · 전체 {sc}",
  "🏀 {q} 접전 그대로 종료 ({qs})"],
 "bb_score": [
  "🏀 {t} {n}점 추가! {sc}",
  "🏀 {t} 득점, {sc}",
  "🏀 {t} 림을 가릅니다 (+{n}) {sc}",
  "🏀 {t} 점수 쌓아요 +{n} · {sc}",
  "🏀 깔끔하게 {t} +{n}, {sc}",
  "🏀 {t} 응답합니다! +{n} ({sc})",
  "🏀 {t} 득점 성공 · {sc}",
  "🏀 {t} +{n}! 스코어 {sc}",
  "🏀 {t} 공격 성공, {sc}",
  "🏀 점수판 움직여요 — {t} +{n} ({sc})"],
 "bb_three": [
  "🏀 {t} 3점 추가! ({sc})", "🏀 {t} 한 번에 +3 · {sc}", "🏀 {t} +3, 분위기 올라옵니다 ({sc})",
  "🏀 {t} 3점 적립 · {sc}", "🏀 {t} 단숨에 3점! {sc}", "🏀 {t} 점수판 +3 ({sc})",
  "🏀 {t} 3점 보태요 · {sc}", "🏀 {t} 쭉 3점 ({sc})", "🏀 {t} +3 성공! {sc}", "🏀 {t} 3점 획득 · {sc}"],
 "clutch": [
  "⏰ 클러치 타임! {p} · {sc}, 한 골 싸움",
  "⏰ {p}, 아직 몰라요 — {sc}",
  "⏰ 손에 땀 쥐는 {p} 접전 {sc}",
  "⏰ {p} 승부처! 점수 차 {n}",
  "⏰ 끝까지 간다! {p} {sc}",
  "⏰ 한 번의 공격이 승부를 가를 {p} ({sc})",
  "⏰ {p} 숨 막히는 {n}점 차",
  "⏰ 집중력 싸움, {p} {sc}",
  "⏰ 막판 접전 — {sc}",
  "⏰ {p} 마지막까지 알 수 없는 승부 ({sc})"],
 # 🏐 배구
 "vb_set": [
  "🏐 {q} {w} 가져갑니다! ({qs}) · 세트 {ss}",
  "🏐 {q} 종료 — {w} {qs} 승, 세트 스코어 {ss}",
  "🏐 {w}, {q} 따냈어요! {qs}",
  "🏐 {q}는 {w}의 몫 ({qs}) · {ss}",
  "🏐 {q} 마무리, {w} 세트 승! 세트 {ss}",
  "🏐 {w} {q} 획득 ({qs}), 세트 스코어 {ss}",
  "🏐 {q} 끝! {w}가 웃어요 {qs}",
  "🏐 {w}, {q}를 손에 넣습니다 · {ss}",
  "🏐 {q} 결과 {qs}, 세트 {ss}",
  "🏐 {q} 승자는 {w}! ({qs})"],
 "vb_sp": [
  "🔔 {t} 세트 포인트! ({qs})",
  "🔔 {t}, {q}까지 한 점! {qs}",
  "🔔 세트 포인트 {t}! 마무리할까요? {qs}",
  "🔔 {t} 세트 눈앞 ({qs})",
  "🔔 {q} 세트 포인트, {t} {qs}",
  "🔔 {t} 한 점이면 {q} 끝! {qs}",
  "🔔 숨죽이는 순간 — {t} 세트 포인트",
  "🔔 {t} 세트 포인트 잡았어요 ({qs})",
  "🔔 {q} 고지가 보입니다, {t} {qs}",
  "🔔 {t}, 세트까지 마지막 한 점! {qs}"],
 "vb_mp": [
  "🏆 매치 포인트!! {t}, 승리까지 한 점 ({qs})",
  "🏆 {t} 매치 포인트! 끝낼 수 있을까요? {qs}",
  "🏆 경기 끝까지 한 점, {t} ({qs})",
  "🏆 {t} 챔피언십 모먼트, 매치 포인트!",
  "🏆 승리 눈앞! {t} 매치 포인트 {qs}",
  "🏆 {t}, 마지막 한 점만 남았어요 ({qs})",
  "🏆 매치 포인트 {t}! 상대는 버틸 수 있을까",
  "🏆 {t} 경기 마무리 직전! {qs}",
  "🏆 체육관이 숨죽입니다 — {t} 매치 포인트",
  "🏆 {t} 승리까지 단 1점! ({qs})"],
 "vb_deuce": [
  "⚖️ 듀스!! {qs}, 끝까지 갑니다",
  "⚖️ {q} 듀스 승부! {qs}",
  "⚖️ 한 치 양보 없는 듀스 ({qs})",
  "⚖️ 듀스 돌입, {q} 진짜 승부는 지금부터",
  "⚖️ {qs} 듀스! 두 점 차를 먼저 만드는 쪽이 승자",
  "⚖️ 또 듀스! {qs}",
  "⚖️ {q} 피 말리는 듀스 {qs}",
  "⚖️ 듀스 상황, 집중력 싸움 ({qs})",
  "⚖️ 끝나지 않는 {q}, {qs} 듀스",
  "⚖️ {q} 듀스! 체육관이 뜨거워요"],
 "vb_pt": [
  "🏐 {t} 득점! {q} {qs}",
  "🏐 {t} 한 점 추가 ({qs})",
  "🏐 {t} 포인트! {qs}",
  "🏐 {t} 점수 가져갑니다 · {qs}",
  "🏐 {t} 득점 성공, {q} {qs}",
  "🏐 {t} +1! {qs}",
  "🏐 {t} 점수판 올립니다 ({qs})",
  "🏐 {t} 랠리 승리! {qs}",
  "🏐 {t} 한 점, {q} {qs}",
  "🏐 {t} 응수! {qs}"],
 # 🏒 하키 피리어드
 "hk_p": [
  "🏒 {q} 종료 — 피리어드 {qs} · 전체 {sc}",
  "🏒 {q} 끝, {sc}",
  "🏒 {q} 마무리, 이번 피리어드 {qs}",
  "🏒 {q} 휴식 들어갑니다 ({sc})",
  "🏒 {q} 결과 {qs}, 누적 {sc}",
  "🏒 {q} 종료 휘슬! {sc}",
  "🏒 링크 정비 시간, {q} 스코어 {qs}",
  "🏒 {q} 끝났어요 — 전체 {sc}",
  "🏒 {q} 정리: {qs} / 합계 {sc}",
  "🏒 {q} 종료 — 스코어 {sc}"],
 # ⚾ 야구
 "bs_hr": [
  "💣 {i} {t} {p} 홈런!! 담장을 넘깁니다 {x}",
  "💣 {i} 넘어갔어요! {p}의 {x} ({t})",
  "💣 {i} {t} {p}, 큰 거 한 방! {x}",
  "💣 {i} 홈런!! {p}, 다이아몬드를 돕니다 {x}",
  "💣 {i} {p} 쾅! {t} {x}",
  "💣 {i} 그대로 담장 밖으로! {t} {p} {x}",
  "💣 {i} {t} 장타 폭발, {p} 홈런 {x}",
  "💣 {i} {p}가 해냈어요, 홈런! {x}",
  "💣 {i} 하늘 높이 날아간 공, {p} 홈런 {x}",
  "💣 {i} {t} {p}! 이게 야구죠, 홈런 {x}"],
 "bs_hit": [
  "⚾ {i} {t} {p} {x}",
  "⚾ {i} {p}, {x}로 출루",
  "⚾ {i} {t} {p} {x}! 찬스 이어 갑니다",
  "⚾ {i} {p} 방망이가 돌았어요, {x}",
  "⚾ {i} {t} 출루 — {p} {x}",
  "⚾ {i} {p} {x}! 좋아요",
  "⚾ {i} {t} {p}, 깔끔한 {x}",
  "⚾ {i} 타격 성공, {p} {x}",
  "⚾ {i} {p} {x}로 살아 나갑니다",
  "⚾ {i} {t} {p} {x} 기록"],
 "bs_rbi": [
  "🔥 {i} {t} {p} {x} — 득점! {n}타점 ({sc})",
  "🔥 {i} {p}, {n}점을 만들어 냅니다! ({sc})",
  "🔥 {i} 홈을 밟습니다! {t} {p} {n}타점 {sc}",
  "🔥 {i} {p}, 주자를 불러들여요 ({n}타점) {sc}",
  "🔥 {i} {t} 점수 올립니다 — {p} {x} ({sc})",
  "🔥 {i} 해결사 {p}! {n}타점 {sc}",
  "🔥 {i} {t} {p}가 득점을 만들어 냅니다 {sc}",
  "🔥 {i} {p} {x}로 {n}점! {sc}",
  "🔥 {i} 찬스를 살렸어요, {t} {p} ({sc})",
  "🔥 {i} {t} 득점 성공! {p} {x} {sc}"],
 "bs_score": [
  "🔥 {i} {t} 득점! {p} {x} ({sc})",
  "🔥 {i} {t} 점수 납니다 — {x} ({sc})",
  "🔥 {i} 홈인! {t} 한 점 ({sc})",
  "🔥 {i} {t}, {x}로 득점 ({sc})",
  "🔥 {i} 스코어 변동, {t} ({sc})",
  "🔥 {i} {t} 득점 기록 · {x} ({sc})",
  "🔥 {i} {t} 점수 추가! ({sc})",
  "🔥 {i} 주자 홈으로! {t} ({sc})",
  "🔥 {i} {t} 소중한 득점 ({sc})",
  "🔥 {i} {t} 한 점 냅니다, {x} ({sc})"],
 "bs_k": [
  "🔥 {i} {f} {q}, {p} 삼진!",
  "🔥 {i} 삼진! {q}가 {p}를 돌려세웁니다",
  "🔥 {i} {q} 탈삼진, {p} 아웃",
  "🔥 {i} {p} 헛방망이… 삼진 ({q})",
  "🔥 {i} {f} 마운드 위 {q}, 삼진 하나 추가",
  "🔥 {i} {q} 구위가 살아 있어요, {p} 삼진",
  "🔥 {i} K! {q} vs {p}, 투수 승리",
  "🔥 {i} {p} 삼진 아웃, {q} 위기 관리",
  "🔥 {i} {q} 삼진 잡았습니다 ({p})",
  "🔥 {i} 꼼짝 못 했어요, {p} 삼진 ({q})"],
 "bs_bb": [
  "👀 {i} {t} {p} {x}로 출루",
  "👀 {i} {p} 골라 나갑니다 ({x})",
  "👀 {i} 선구안 좋아요, {p} {x}",
  "👀 {i} {t} 주자 추가 — {p} {x}",
  "👀 {i} {p} {x}, 1루로 걸어갑니다",
  "👀 {i} 투수 흔들리나? {p} {x}",
  "👀 {i} {t} {p}, {x} 얻어 냅니다",
  "👀 {i} {x}! {p} 출루",
  "👀 {i} {p} 끈질긴 승부 끝에 {x}",
  "👀 {i} {t} 출루 성공, {p} {x}"],
 "bs_dp": [
  "😩 {i} {x}! {f} 수비가 한 번에 두 개 잡아요 ({p})",
  "😩 {i} {p} {x}… 찬스가 사라집니다",
  "😩 {i} {f} 깔끔한 {x} 처리",
  "😩 {i} {x}, {t} 공격 맥이 끊겨요 ({p})",
  "😩 {i} {p} 타구가 {x}로 이어집니다",
  "😩 {i} {f} 수비 집중력! {x}",
  "😩 {i} 아쉬운 {x}, {p}",
  "😩 {i} {f}, 투아웃 한 번에! ({x})",
  "😩 {i} {t} {p} {x}",
  "😩 {i} {x}로 이닝 흐름이 바뀌어요 ({p})"],
 "bs_misc": [
  "⚾ {i} {t} {p} {x}",
  "⚾ {i} {x} — {p} ({t})",
  "⚾ {i} {t}, {x} 기록 ({p})",
  "⚾ {i} {x}! {p}",
  "⚾ {i} 기록지에 {x}, {p}",
  "⚾ {i} {p} {x}",
  "⚾ {i} {t} {x} 장면 ({p})",
  "⚾ {i} 이번 타석 {x} — {p}",
  "⚾ {i} {x} 나옵니다, {p}",
  "⚾ {i} {t} {p}, {x}"],
 "bs_pc": [
  "🔁 {i} {f} 투수 교체 · {p} 등판",
  "🔁 {i} {f} 마운드에 변화, {p} 올라옵니다",
  "🔁 {i} {f} 불펜 가동! {p}",
  "🔁 {i} {p} 등판, {f} 승부수",
  "🔁 {i} {f} 투수 바꿉니다 — {p}",
  "🔁 {i} 새 투수 {p} ({f})",
  "🔁 {i} {f} 벤치가 움직였어요, {p} 투입",
  "🔁 {i} {f} {p}에게 공을 맡깁니다",
  "🔁 {i} 마운드 주인이 바뀝니다, {p}",
  "🔁 {i} {f} 교체 카드 {p}"],
 "bs_inn": [
  "⚾ {i} {t} {n}점! ({sc})",
  "⚾ {i} {t} 점수 냅니다, {n}점 ({sc})",
  "⚾ {i} {t} 공격 성공 — {n}점 ({sc})",
  "⚾ {i} {t} {n}점 추가 · {sc}",
  "⚾ {i} {t} 득점 이닝! {n}점",
  "⚾ {i} {t}, 이번 이닝 {n}점 ({sc})",
  "⚾ {i} {t} 방망이 터졌어요 {n}점 ({sc})",
  "⚾ {i} {t} {n}점 수확 ({sc})",
  "⚾ {i} {t} 점수판에 {n} 적습니다 ({sc})",
  "⚾ {i} {t} {n}득점! {sc}"],
 "bs_big": [
  "🔥🔥 {i} {t} 빅이닝! {n}점 폭발 ({sc})",
  "🔥🔥 {i} {t} 대량 득점, 무려 {n}점! {sc}",
  "🔥🔥 {i} 타선 대폭발! {t} {n}점",
  "🔥🔥 {i} {t} 쉬지 않고 몰아칩니다 {n}점 ({sc})",
  "🔥🔥 {i} {t} {n}점 빅이닝, 분위기 장악",
  "🔥🔥 {i} 멈추지 않는 {t}, {n}점 ({sc})",
  "🔥🔥 {i} {t} 한 이닝 {n}점! {sc}",
  "🔥🔥 {i} 경기 흐름 흔드는 {n}점, {t}",
  "🔥🔥 {i} {t} 화력 쇼 {n}점 ({sc})",
  "🔥🔥 {i} {t} 빅이닝 완성! {sc}"],
 "end": [
  "🏁 경기 종료! {w} 승리 · {sc}",
  "🏁 경기 끝! 최종 {sc}, {w} 웃었어요",
  "🏁 종료 휘슬 — {w} 승 ({sc})",
  "🏁 {w}, 승리를 확정합니다 {sc}",
  "🏁 최종 스코어 {sc} · 승자는 {w}",
  "🏁 수고했습니다! {w} 승리 {sc}",
  "🏁 경기 마무리, {w}가 가져갑니다 ({sc})",
  "🏁 끝났어요! {sc}, {w} 승",
  "🏁 오늘의 승자 {w}! {sc}",
  "🏁 경기 종료 · {sc} ({w} 승)"],
 "end_d": [
  "🏁 경기 종료! 무승부 {sc}", "🏁 승부 가리지 못하고 끝, {sc}", "🏁 무승부로 마무리 — {sc}",
  "🏁 경기 끝, 사이좋게 무승부 {sc}", "🏁 종료 · 최종 {sc} 무승부", "🏁 승점 나눠 갖습니다 ({sc})",
  "🏁 팽팽한 승부, 무승부 {sc}", "🏁 끝까지 균형, {sc}", "🏁 경기 종료, 결과는 무승부 ({sc})", "🏁 최종 {sc} — 무승부"],
}
# 상황 줄(새 이벤트 없을 때 돌려 보기). 모두 실제 점수·시간·기록에서만.
C = {
 "lead": ["📊 {p} · {t} {n}점 앞서 있어요 ({sc})", "📊 {p} 현재 {sc}, {t} 리드", "📊 {t} 리드 지키는 중 — {sc} ({p})",
          "📊 {p} {o} 추격 중, {sc}", "📊 지금 {sc} · {t} +{n}", "📊 {p} 스코어 {sc}"],
 "tie":  ["📊 {p} 아직 팽팽! {sc}", "📊 {p} 균형 유지 중 ({sc})", "📊 {sc}, 누가 먼저 앞서갈까요? ({p})",
          "📊 {p} 동점 상황 {sc}", "📊 승부는 원점, {sc} ({p})", "📊 {p} 한 치 양보 없는 {sc}"],
}

_last = {}


def _uk(k, used):
    n, k0 = 1, k
    while k in used:
        n += 1; k = f"{k0}#{n}"
    used.add(k)
    return k


def _pick(key, kind, state):
    lst = T[kind]
    i = zlib.crc32(key.encode()) % len(lst)
    if state.get(kind) == i:
        i = (i + 1) % len(lst)
    state[kind] = i
    return lst[i]


def _jo(w, a, b):
    """받침 있으면 a(이/은/을/과), 없으면 b."""
    w = str(w or "").rstrip()
    c = w[-1:] if w else ""
    if "가" <= c <= "힣":
        return a if (ord(c) - 0xAC00) % 28 else b
    if c.isdigit():
        return a if c in "013678" else b
    return b


JO = (("가", "이", "가"), ("는", "은", "는"), ("를", "을", "를"), ("와", "과", "와"))


def _fmt(tpl, **kw):
    s = tpl
    for k, v in kw.items():
        for j, a, b in JO:
            s = s.replace("{" + k + "}" + j, (str(v) if v is not None else "") + _jo(v, a, b))
    for k, v in kw.items():
        s = s.replace("{" + k + "}", str(v) if v is not None else "")
    s = re.sub(r"\{[a-z]+\}", "", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\s+([,!)])", r"\1", s)
    s = s.replace(" — ,", " —").replace("  ", " ").replace(" ,", ",").strip()
    return s


def _sc(g, h, a):
    """점수 표기: 야구는 원정 왼쪽·홈 오른쪽, 그 외 홈 왼쪽."""
    if g["kind"] == "baseball":
        return f"{g['away']} {a} : {h} {g['home']}"
    return f"{g['home']} {h} : {a} {g['away']}"


def _flow(g, out, st, key, side, h, a, ph, pa, late, unit_first=True):
    """득점 후 흐름 이벤트(선취·동점·역전·막판). side: 'h'/'a' 득점 쪽."""
    t = g["home"] if side == "h" else g["away"]
    sc = _sc(g, h, a)
    if ph == pa == 0 and unit_first:
        out.append({"k": key + ":f", "t": _fmt(_pick(key + ":f", "first", st), t=t, sc=sc), "hot": True})
    elif h == a:
        out.append({"k": key + ":e", "t": _fmt(_pick(key + ":e", "equal", st), t=t, sc=sc), "hot": True})
    elif (ph - pa) * (h - a) < 0 or (ph == pa and False):
        out.append({"k": key + ":l", "t": _fmt(_pick(key + ":l", "lead", st), t=t, sc=sc), "hot": True})
    elif late and abs(h - a) <= 1:
        out.append({"k": key + ":t", "t": _fmt(_pick(key + ":t", "late", st), t=t, sc=sc), "hot": True})
    elif ph == pa:
        out.append({"k": key + ":g", "t": _fmt(_pick(key + ":g", "ahead", st), t=t, sc=sc), "hot": True})
    # 역전: 동점→리드 아닌, 열세→리드
    if ph != pa and (ph - pa) * (h - a) < 0:
        pass


# ---------------------------------------------------------------- 축구
def _min(e):
    tm = e.get("time") or {}
    return f"{tm.get('elapsed')}'" + (f"+{tm['extra']}" if tm.get("extra") else ""), int(tm.get("elapsed") or 0)


def _football(g, rows):
    from teams_ko import ko
    st, out, h, a, scorer, used = {}, [], 0, 0, {}, set()
    hid = g.get("home_id")
    mm = 0
    for i, e in enumerate(rows or []):
        for x in out:
            x.setdefault("_m", mm)
        m, mm = _min(e)
        tid = (e.get("team") or {}).get("id")
        t = g["home"] if tid == hid else g["away"] if tid == g.get("away_id") else ko("football", tid, (e.get("team") or {}).get("name") or "")[0]
        p = (e.get("player") or {}).get("name") or ""
        ast = (e.get("assist") or {}).get("name") or ""
        typ, det = e.get("type"), e.get("detail") or ""
        key = _uk(f"fb:{g['id']}:{typ}:{det}:{m}:{p}", used)
        if typ == "Goal":
            if "Missed" in det:
                out.append({"k": key, "t": _fmt(_pick(key, "fb_pmiss", st), m=m, t=t, p=p), "hot": True}); continue
            if "Shootout" in str(e.get("comments") or ""):
                out.append({"k": key, "t": f"🥅 승부차기 {t} {p} 성공!", "hot": True}); continue
            kind = "fb_og" if "Own" in det else "fb_pgoal" if "Penalty" in det else "fb_goal"
            # 자책골: API는 실점 팀이 아닌 득점 인정 팀으로 team을 준다
            side = "h" if tid == hid else "a"
            ph, pa = h, a
            if side == "h": h += 1
            else: a += 1
            line = _fmt(_pick(key, kind, st), m=m, t=t, p=p)
            if ast and kind == "fb_goal":
                line += f" (도움 {ast})"
            out.append({"k": key, "t": line + f"  {_sc(g, h, a)}", "hot": True})
            if kind != "fb_og" and p:
                scorer[p] = scorer.get(p, 0) + 1
                if scorer[p] >= 2:
                    out.append({"k": key + ":b", "t": _fmt(_pick(key + ":b", "brace", st), p=p, t=t, n=scorer[p]), "hot": True})
            _flow(g, out, st, key, side, h, a, ph, pa, mm >= 85)
        elif typ == "Card":
            red = "Red" in det
            out.append({"k": key, "t": _fmt(_pick(key, "fb_red" if red else "fb_yel", st), m=m, t=t, p=p), "hot": red})
        elif typ == "subst":
            # API-Sports: player=나간 선수, assist=들어온 선수 (리그에 따라 반대) → 둘 다 실명 그대로
            out.append({"k": key, "t": _fmt(_pick(key, "fb_sub", st), m=m, t=t, p=ast or p, a=p if ast else ""), "hot": False})
        elif typ == "Var" and det:
            x = {"Goal cancelled": "골 취소", "Goal Disallowed": "골 취소", "Penalty confirmed": "페널티 확정",
                 "Penalty cancelled": "페널티 취소", "Card upgrade": "카드 상향", "Goal confirmed": "골 인정"}.get(det, det)
            out.append({"k": key, "t": _fmt(_pick(key, "fb_var", st), m=m, x=x, t=t), "hot": "취소" in x or "확정" in x})
    for x in out:
        x.setdefault("_m", mm)
    return out, st


def _fb_stats(g):
    """실제 경기 기록(슈팅·유효·코너) 누적 → 증가분을 감지 시각 기준 이벤트로."""
    import plays, sports2
    r = plays._cached("fbstat:" + str(g["id"]), 45, lambda: sports2.get("football", "/fixtures/statistics", {"fixture": g["id"]}))
    if not r:
        return None
    cur = {}
    for x in r:
        side = "h" if (x.get("team") or {}).get("id") == g.get("home_id") else "a"
        cur[side] = {s.get("type"): s.get("value") for s in x.get("statistics") or []}
    return cur


def _num(v):
    try:
        return int(str(v).rstrip("%"))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 공통: 스냅샷 기반 득점 흐름
def _snap(g):
    k = g["key"]
    h, a = g.get("home_score"), g.get("away_score")
    if h is None or a is None:
        return _hist.get(k, [])
    with _lock:
        hs = _hist.setdefault(k, [])
        lines = [tuple(x) for x in (g.get("lines") or [])]
        if not hs or (hs[-1][2], hs[-1][3], hs[-1][4]) != (h, a, lines):
            hs.append((time.time(), g.get("period") or "", h, a, lines))
            del hs[:-200]
        if len(_hist) > 400:
            for kk in list(_hist)[:100]:
                _hist.pop(kk, None)
        return list(hs)


def _deltas(hs):
    """연속 스냅샷 사이 점수 변화 [(i, period, dh, da, h, a, ph, pa)]."""
    out = []
    for i in range(1, len(hs)):
        _, per, h, a, _l = hs[i]
        ph, pa = hs[i - 1][2], hs[i - 1][3]
        if (h, a) != (ph, pa) and h >= ph and a >= pa:
            out.append((i, per, h - ph, a - pa, h, a, ph, pa))
    return out


def _runs(g, ds, st, thr, step):
    """한쪽만 연속 득점한 구간: 임계 넘을 때마다 1건."""
    out, side, n, start = [], None, 0, 0
    for (i, per, dh, da, h, a, ph, pa) in ds:
        s = "h" if dh and not da else "a" if da and not dh else None
        if s is None or s != side:
            side, n, start = s, 0, f"{ph}-{pa}"
        if s:
            n += dh or da
            tier = (n - thr) // step if n >= thr else -1
            if tier >= 0:
                key = f"run:{g['key']}:{start}:{tier}"
                if not out or out[-1]["k"] != key:
                    out.append({"k": key, "t": _fmt(_pick(key, "run", st), t=g["home"] if s == "h" else g["away"], n=n, sc=_sc(g, h, a)), "hot": True, "_i": i})
    return out


def _po(p):
    p = str(p).upper()
    return int(p[1:]) if p[1:].isdigit() else 4 if "OT" in p else 5 if "P" == p[:1] or "SO" in p else 4


def _qname(k, lab):
    lab = str(lab)
    if lab.isdigit():
        return f"{lab}쿼터" if k == "basketball" else f"{lab}세트" if k == "volleyball" else f"{lab}피리어드"
    return lab


# ---------------------------------------------------------------- 메인
def build(g, base_items=None):
    """→ {"items": [{t,hot}] 최신순, "ctx": [상황 줄]}  (실패 시 None)"""
    k, live = g["kind"], g["state"] == "live"
    if g["state"] not in ("live", "final"):
        return None
    hs = _snap(g) if live else []
    items, st = [], {}
    H, A = g.get("home_score") or 0, g.get("away_score") or 0
    per = g.get("period") or ""
    if k == "football":
        import plays, sports2
        rows = plays._cached("fbraw:" + str(g["id"]), 60 if live else 6 * 3600, lambda: sports2.raw_events(g)) or []
        items, st = _football(g, rows)
        if live:
            cur = _fb_stats(g)
            if cur:
                with _lock:
                    prev = _stats.get(g["key"])
                    _stats[g["key"]] = (cur, per, prev[2] if prev else [])
                    acc = _stats[g["key"]][2]
                    if prev:
                        for side in ("h", "a"):
                            for typ, kind in (("Corner Kicks", "fb_corner"), ("Shots on Goal", "fb_sot"), ("Total Shots", "fb_shot")):
                                n1, n0 = _num((cur.get(side) or {}).get(typ)), _num(((prev[0] or {}).get(side) or {}).get(typ))
                                if n1 is not None and n0 is not None and n1 > n0:
                                    if kind == "fb_shot" and _num((cur.get(side) or {}).get("Shots on Goal") or 0) != _num(((prev[0] or {}).get(side) or {}).get("Shots on Goal") or 0):
                                        continue  # 유효 슈팅으로 이미 표시
                                    acc.append((kind, side, n1, per))
                    del acc[:-30]
                    acc = list(acc)
                mins = [x for x in items]
                for j, (kind, side, n1, p0) in enumerate(acc):
                    key = f"st:{g['key']}:{kind}:{side}:{n1}"
                    m = re.sub(r"^(전반|후반|연장)\s*", "", p0)
                    mm = re.search(r"(\d+)'", p0)
                    items.append({"k": key, "t": _fmt(_pick(key, kind, st), m=m or p0, t=g["home"] if side == "h" else g["away"], n=n1), "hot": False, "_m": int(mm.group(1)) + 0.5 if mm else 999})
                items.sort(key=lambda x: x.get("_m", 0))
                # 기록 이벤트는 시간 이벤트 뒤에 들어오므로 감지 시각 순서를 유지(최신 = 맨 뒤)
    elif k == "hockey":
        import plays, sports2
        rows = plays._cached("hkraw:" + str(g["id"]), 60 if live else 6 * 3600, lambda: sports2.get("hockey", "/games/events", {"game": g["id"]})) or []
        h = a = 0
        used = set()
        for i, e in enumerate(rows):
            p = str(e.get("period") or "")
            tid = (e.get("team") or {}).get("id")
            t = g["home"] if tid == g.get("home_id") else g["away"]
            who = ", ".join(e.get("players") or [])
            m = (f"{p[1:]}P {e.get('minute')}'" if p[1:].isdigit() else f"{p} {e.get('minute') or ''}'").strip()
            key = _uk(f"hk:{g['id']}:{e.get('type')}:{p}:{e.get('minute')}:{who}", used)
            cm_ = _po(p) * 100 + int(str(e.get("minute") or 0).strip("'") or 0)
            if e.get("type") == "goal":
                side = "h" if tid == g.get("home_id") else "a"
                ph, pa = h, a
                if side == "h": h += 1
                else: a += 1
                items.append({"k": key, "t": _fmt(_pick(key, "hk_goal", st), m=m, t=t, p=who) + f"  {_sc(g, h, a)}", "hot": True})
                late = p in ("P3", "OT") and int(e.get("minute") or 0) >= 17 or p == "OT"
                _flow(g, items, st, key, side, h, a, ph, pa, late)
            elif e.get("type") == "penalty":
                items.append({"k": key, "t": _fmt(_pick(key, "hk_pen", st), m=m, t=t, p=who), "hot": False})
            for x in items:
                x.setdefault("_m", cm_)
        last_m = _po(str((rows[-1] if rows else {}).get("period") or "")) * 100 + 60
        for x in items:
            x.setdefault("_m", last_m)
        # 끝난 피리어드
        lines = g.get("lines") or []
        th = ta = 0
        for i, (lab, x, y) in enumerate(lines):
            th, ta = th + x, ta + y
            if live and i == len(lines) - 1:
                break
            key = f"hkp:{g['key']}:{lab}"
            items.append({"k": key, "t": _fmt(_pick(key, "hk_p", st), q=_qname(k, lab), qs=f"{x}-{y}", sc=_sc(g, th, ta)), "hot": False, "_m": (i + 1) * 100 + 99})
        items.sort(key=lambda x: x.get("_m", 0))
    elif k == "baseball" and g.get("league") == 1:
        items, st = _mlb(g)
    if k == "baseball" and not items:
        items, st = _innings(g)
    if k in ("basketball", "volleyball"):
        items, st = _lined(g, live)
    # 스냅샷 기반 흐름(농구·배구·하키·KBO 등): 연속 득점·동점·역전·대승
    if live and k in ("basketball", "volleyball"):
        ds = _deltas(hs)
        thr, step = {"basketball": (8, 4), "volleyball": (3, 1)}[k]
        if k == "basketball":
            for (i, p0, dh, da, h, a, ph, pa) in ds[-40:]:
                key = f"bs:{g['key']}:{h}:{a}"
                if dh and da:
                    items.append({"k": key, "t": f"🏀 양 팀 주고받아요 · {_sc(g, h, a)}", "hot": False}); continue
                side = "h" if dh else "a"
                nn = dh or da
                kind = "bb_three" if nn == 3 else "bb_score"
                items.append({"k": key, "t": _fmt(_pick(key, kind, st), t=g["home"] if side == "h" else g["away"], n=nn, sc=_sc(g, h, a)), "hot": False})
                if (ph - pa) * (h - a) < 0:
                    items.append({"k": key + ":l", "t": _fmt(_pick(key + ":l", "lead", st), t=g["home"] if side == "h" else g["away"], sc=_sc(g, h, a)), "hot": True})
                elif h == a and ph != pa:
                    items.append({"k": key + ":e", "t": _fmt(_pick(key + ":e", "equal", st), t=g["home"] if side == "h" else g["away"], sc=_sc(g, h, a)), "hot": True})
                gap = abs(h - a)
                if gap >= 15 and abs(ph - pa) < gap and gap % 5 == 0:
                    items.append({"k": key + ":w", "t": _fmt(_pick(key + ":w", "blow", st), t=g["home"] if h > a else g["away"], n=gap, sc=_sc(g, h, a)), "hot": False})
        for r in _runs(g, ds, st, thr, step):
            items.append(r)
    if g["state"] == "final":
        key = f"end:{g['key']}"
        w = g["home"] if H > A else g["away"] if A > H else None
        items.append({"k": key, "t": _fmt(_pick(key, "end" if w else "end_d", st), w=w, sc=_sc(g, H, A)), "hot": True})
    if not items and base_items:
        return {"items": [], "ctx": _ctx(g, hs) if live else []}
    items = list(reversed(items))
    return {"items": [{"t": x["t"], "hot": bool(x.get("hot")), "k": x["k"]} for x in items if x.get("t")], "ctx": _ctx(g, hs) if live else []}


def _lined(g, live):
    """농구 쿼터·배구 세트 진행(실제 라인 점수)."""
    k, st, out = g["kind"], {}, []
    lines = g.get("lines") or []
    th = ta = sh = sa = 0
    curv = None
    for i, (lab, x, y) in enumerate(lines):
        cur = live and i == len(lines) - 1
        q = _qname(k, lab)
        if k == "volleyball":
            if cur:
                curv = (lab, x, y, q, sh, sa)
                continue
            w = g["home"] if x > y else g["away"]
            sh, sa = sh + (x > y), sa + (y > x)
            key = f"vbs:{g['key']}:{lab}"
            out.append({"k": key, "t": _fmt(_pick(key, "vb_set", st), q=q, w=w, qs=f"{x}-{y}", ss=f"{g['home']} {sh}-{sa} {g['away']}"), "hot": abs(x - y) <= 2})
        else:
            ph, pa = th, ta
            th, ta = th + x, ta + y
            if cur:
                continue
            key = f"bbq:{g['key']}:{lab}"
            if x == y:
                out.append({"k": key, "t": _fmt(_pick(key, "bb_qt", st), q=q, qs=f"{x}-{y}", sc=_sc(g, th, ta)), "hot": False})
            else:
                out.append({"k": key, "t": _fmt(_pick(key, "bb_q", st), q=q, qs=f"{x}-{y}", w=g["home"] if x > y else g["away"], sc=_sc(g, th, ta)), "hot": abs(x - y) >= 10})
            if (ph - pa) * (th - ta) < 0:
                out.append({"k": key + ":l", "t": _fmt(_pick(key + ":l", "lead", st), t=g["home"] if th > ta else g["away"], sc=_sc(g, th, ta)), "hot": True})
    if live and k == "volleyball" and lines:
        # 진행 중 세트 실시간 득점(스냅샷 기반: 실제 점수 변화)
        hs = _hist.get(g["key"], [])
        for i in range(max(1, len(hs) - 30), len(hs)):
            l1, l0 = hs[i][4], hs[i - 1][4]
            if l1 and l0 and len(l1) == len(l0) and l1[-1][0] == l0[-1][0]:
                dx, dy = l1[-1][1] - l0[-1][1], l1[-1][2] - l0[-1][2]
                if (dx > 0) != (dy > 0) and dx >= 0 and dy >= 0:
                    key = f"vbp:{g['key']}:{l1[-1][0]}:{l1[-1][1]}:{l1[-1][2]}"
                    out.insert(len(out), {"k": key, "t": _fmt(_pick(key, "vb_pt", st), t=g["home"] if dx else g["away"], q=_qname(k, l1[-1][0]), qs=f"{l1[-1][1]}-{l1[-1][2]}"), "hot": False})
    if live and k == "volleyball" and lines and curv:
        lab, x, y, q, sh, sa = curv
        tgt = 15 if str(lab) == "5" else 25
        key0 = f"vb:{g['key']}:{lab}:{x}:{y}"
        need = 3 if len(lines) <= 5 and str(lab) != "5" else 3
        for side, me, op, ms in (("h", x, y, sh), ("a", y, x, sa)):
            if me >= tgt - 1 and me - op >= 1:
                t = g["home"] if side == "h" else g["away"]
                mp = ms == 2
                kk = key0 + side
                out.append({"k": kk, "t": _fmt(_pick(kk, "vb_mp" if mp else "vb_sp", st), t=t, q=q, qs=f"{x}-{y}"), "hot": True})
        if x == y and x >= tgt - 1:
            out.append({"k": key0 + "d", "t": _fmt(_pick(key0 + "d", "vb_deuce", st), q=q, qs=f"{x}-{y}"), "hot": True})
    return out, st


def _innings(g):
    inn, st, out = g.get("innings"), {}, []
    if not inn:
        return out, st
    a = h = 0
    keys = sorted({int(x) for s in ("home", "away") for x in inn[s]["inn"] if str(x).isdigit()})
    for n in keys:
        for side, half in (("away", "초"), ("home", "말")):
            r = inn[side]["inn"].get(str(n))
            try:
                r = int(r)
            except (TypeError, ValueError):
                continue
            pa, ph = a, h
            if side == "away": a += r
            else: h += r
            if r > 0:
                t = g["away"] if side == "away" else g["home"]
                key = f"inn:{g['key']}:{n}{side}"
                out.append({"k": key, "t": _fmt(_pick(key, "bs_big" if r >= 3 else "bs_inn", st), i=f"{n}회{half}", t=t, n=r, sc=_sc(g, h, a)), "hot": r >= 3})
                _flow(g, out, st, key, "h" if side == "home" else "a", h, a, ph, pa, n >= 8)
    return out, st


def _mlb(g):
    import plays
    pk = plays._mlb_pk(g)
    st, out = {}, []
    if not pk:
        return out, st
    feed = plays._cached(f"mlbfeed:{pk}", 30 if g["state"] == "live" else 6 * 3600, lambda: plays._get(f"https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live"))
    if not feed:
        return out, st
    side = {"top": g["away"], "bottom": g["home"]}
    pa_ = ph_ = 0
    for j, p in enumerate(((feed.get("liveData") or {}).get("plays") or {}).get("allPlays") or []):
        res, ab, mu = p.get("result") or {}, p.get("about") or {}, p.get("matchup") or {}
        ev = res.get("eventType")
        inn = f"{ab.get('inning')}회{'초' if ab.get('halfInning') == 'top' else '말'}"
        t = side.get(ab.get("halfInning"), "")
        f = side.get("bottom" if ab.get("halfInning") == "top" else "top", "")
        bat, pit = (mu.get("batter") or {}).get("fullName") or "", (mu.get("pitcher") or {}).get("fullName") or ""
        key = f"mlb:{pk}:{j}"
        for q, pe in enumerate(p.get("playEvents") or []):
            d = pe.get("details") or {}
            if pe.get("type") == "action" and d.get("eventType") == "pitching_substitution":
                m = re.search(r":\s*(.+?)\s+replaces", d.get("description") or "")
                if m:
                    kk = f"{key}:pc{q}"
                    out.append({"k": kk, "t": _fmt(_pick(kk, "bs_pc", st), i=inn, f=f, p=m.group(1)), "hot": False})
        if not ev:
            continue
        nm = plays.EV_KO.get(ev, (None,))[0]
        rbi, scoring = res.get("rbi") or 0, ab.get("isScoringPlay")
        a, h = res.get("awayScore"), res.get("homeScore")
        sc = _sc(g, h, a) if a is not None else ""
        if ev == "home_run":
            x = "만루 홈런" if rbi == 4 else f"{rbi}점 홈런" if rbi > 1 else "솔로 홈런"
            out.append({"k": key, "t": _fmt(_pick(key, "bs_hr", st), i=inn, t=t, p=bat, x=x) + f"  ({sc})", "hot": True})
        elif scoring and rbi and nm:
            out.append({"k": key, "t": _fmt(_pick(key, "bs_rbi", st), i=inn, t=t, p=bat, x=nm, n=rbi, sc=sc), "hot": True})
        elif scoring:
            out.append({"k": key, "t": _fmt(_pick(key, "bs_score", st), i=inn, t=t, p=bat, x=nm or "득점", sc=sc), "hot": True})
        elif ev in ("single", "double", "triple"):
            out.append({"k": key, "t": _fmt(_pick(key, "bs_hit", st), i=inn, t=t, p=bat, x=nm), "hot": ev == "triple"})
        elif ev in ("strikeout", "strikeout_double_play"):
            out.append({"k": key, "t": _fmt(_pick(key, "bs_k", st), i=inn, f=f, q=pit, p=bat), "hot": False})
        elif ev in ("walk", "intent_walk", "hit_by_pitch"):
            out.append({"k": key, "t": _fmt(_pick(key, "bs_bb", st), i=inn, t=t, p=bat, x=nm), "hot": False})
        elif ev in ("grounded_into_double_play", "double_play", "triple_play"):
            out.append({"k": key, "t": _fmt(_pick(key, "bs_dp", st), i=inn, t=t, f=f, p=bat, x=nm), "hot": ev == "triple_play"})
        elif ev in ("field_error", "wild_pitch", "passed_ball", "balk", "sac_fly", "sac_bunt"):
            out.append({"k": key, "t": _fmt(_pick(key, "bs_misc", st), i=inn, t=t, p=bat, x=nm), "hot": False})
        if scoring and a is not None:
            sd = "a" if ab.get("halfInning") == "top" else "h"
            _flow(g, out, st, key, sd, h, a, ph_, pa_, (ab.get("inning") or 0) >= 8)
            ph_, pa_ = h, a
    return out, st


def _ctx(g, hs):
    """새 이벤트 없을 때 돌려 볼 실제 상황 줄."""
    k = g["kind"]
    H, A = g.get("home_score"), g.get("away_score")
    if H is None or A is None:
        return []
    per = g.get("period") or ""
    p = per or "진행 중"
    sc = _sc(g, H, A)
    out = []
    lead = g["home"] if H > A else g["away"] if A > H else None
    lst = C["lead" if lead else "tie"]
    i = int(time.time() // 30) % len(lst)
    out.append(_fmt(lst[i], p=p, t=lead, o=(g["away"] if lead == g["home"] else g["home"]) if lead else "", n=abs(H - A), sc=sc))
    lines = g.get("lines") or []
    if k == "volleyball" and lines:
        lab, x, y = lines[-1]
        sh = sum(1 for l in lines[:-1] if l[1] > l[2]); sa = sum(1 for l in lines[:-1] if l[2] > l[1])
        out = [f"🏐 {_qname(k, lab)} 진행 중 · {g['home']} {x} : {y} {g['away']}", f"📊 세트 스코어 {g['home']} {sh} : {sa} {g['away']}"]
        tgt = 15 if str(lab) == "5" else 25
        me, op = max(x, y), min(x, y)
        if me >= tgt - 5 and x != y:
            out.append(f"⏳ {g['home'] if x > y else g['away']}, {_qname(k, lab)}까지 {max(tgt - me, op + 2 - me, 1)}점 남았어요")
        elif x == y:
            out.append(f"⚖️ {_qname(k, lab)} {x}-{y} 동점, 팽팽한 랠리 싸움")
    elif k == "basketball" and lines:
        lab, x, y = lines[-1]
        out.append(f"🏀 {_qname(k, lab)} 점수 {g['home']} {x} : {y} {g['away']}")
        out.append(f"🏀 두 팀 합계 {H + A}점 · {sc}")
        q = re.sub(r"\D", "", str(lab))
        if (q == "4" or re.search(r"OT|연장", f"{lab} {per}", re.I)) and abs(H - A) <= 6:
            out.append(_fmt(T["clutch"][int(time.time() // 30) % len(T["clutch"])], p=p, sc=sc, n=abs(H - A)))
    elif k == "hockey":
        out.append(f"🏒 {p} · {sc}")
        if lines:
            lab, x, y = lines[-1]
            out.append(f"🏒 {_qname(k, lab)} 스코어 {g['home']} {x} : {y} {g['away']}")
    elif k == "football":
        s = (_stats.get(g["key"]) or (None,))[0]
        if s and s.get("h") and s.get("a"):
            def v(side, typ):
                return (s.get(side) or {}).get(typ)
            if v("h", "Ball Possession") and v("a", "Ball Possession"):
                out.append(f"⚽ 점유율 {g['home']} {v('h', 'Ball Possession')} : {v('a', 'Ball Possession')} {g['away']}")
            if v("h", "Total Shots") is not None:
                out.append(f"💨 슈팅 {g['home']} {v('h', 'Total Shots') or 0} (유효 {v('h', 'Shots on Goal') or 0}) : {v('a', 'Total Shots') or 0} (유효 {v('a', 'Shots on Goal') or 0}) {g['away']}")
            if v("h", "Corner Kicks") is not None:
                out.append(f"🚩 코너킥 {g['home']} {v('h', 'Corner Kicks') or 0} : {v('a', 'Corner Kicks') or 0} {g['away']}")
            if v("h", "Goalkeeper Saves") is not None and (v("h", "Goalkeeper Saves") or v("a", "Goalkeeper Saves")):
                out.append(f"🧤 골키퍼 선방 {g['home']} {v('h', 'Goalkeeper Saves') or 0} : {v('a', 'Goalkeeper Saves') or 0} {g['away']}")
        m = re.search(r"(\d+)'", per)
        if m:
            mm = int(m.group(1))
            if mm >= 85 and "연장" not in per:
                out.append(f"⏰ {per}, 정규 시간 막바지! {sc}")
            elif mm >= 90:
                out.append(f"⏰ {per} · 연장 승부 {sc}")
    elif k == "baseball":
        inn = g.get("innings") or {}
        out.append(f"⚾ {p} · {sc}")
    # 흐름: 최근 스냅샷의 점수 변화 합(실제)
    ds = _deltas(hs)
    if k in ("basketball", "volleyball") and len(ds) >= 4:
        rec = ds[-8:]
        dh, da = sum(x[2] for x in rec), sum(x[3] for x in rec)
        if dh != da:
            out.append(f"📈 최근 득점 흐름 {g['home']} {dh} : {da} {g['away']}")
    return [x for x in out if x]
