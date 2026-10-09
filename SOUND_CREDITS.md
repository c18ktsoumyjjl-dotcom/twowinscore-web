# 효과음 출처 (모두 CC0 1.0 퍼블릭 도메인)

## static/intro.mp3 (입장 효과음, 6.6초: 장내 아나운서 '투윈스코어!' → 호루라기 → 관중 함성)
- 아나운서 음성: MeloTTS (MyShell.ai) 한국어 모델로 직접 합성 — 코드·모델 가중치 MIT 라이선스(상업적 사용 가능)
  https://github.com/myshell-ai/MeloTTS · https://huggingface.co/myshell-ai/MeloTTS-Korean
  가공: 피치/포먼트 하향(남성 저음, 약 155Hz), 저역·고역 EQ, 컴프레서, 경기장 에코(다중 딜레이)
- 호루라기: "218318 splicesound referee-whistle-blow-gymnasium.wav" — SpliceSound — CC0 1.0
  https://commons.wikimedia.org/wiki/File:218318_splicesound_referee-whistle-blow-gymnasium.wav
- 관중 함성(실제 경기장 녹음, FC St. Pauli 밀러른토어 스타디움 29,546명 득점 반응):
  "CRWDReac-SOCCER_Millerntor Stadium Crowd Reaction Goal 01_PHILIPP FEIT_FCSP 29.546_Sound Of Sankt Pauli" — itmightgetloud — CC0 1.0
  https://freesound.org/people/itmightgetloud/sounds/829455/
- 편집: 아나운서 0s, 호루라기 1.55s, 2.25s부터 함성 0.25–4.6s 구간 겹침, 페이드인/아웃, 라우드니스 정규화(-19 LUFS), 모노 64kbps MP3.

## static/chime.mp3 (득점 알림음)
- ffmpeg 사인파로 직접 생성(880Hz + 1318.5Hz). 외부 소스 없음.
