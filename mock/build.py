import json,re,html
g=json.load(open('games.json'));G=g['games']
E=html.escape
def tm(t,side):
    lg=f'<img src="{t["logo"]}">' if t.get('logo') else '<i class="nl"></i>'
    return f'<div class="tm {side}">{lg}<span>{E(t["name"])}</span></div>'
def row(x,fav=False):
    st=x['state'];L,R=x['L'],x['R']
    # baseball: away left, home right (data already); others: home left
    if st=='scheduled': mid='<b class="vs">VS</b>'
    else:
        a,b=L.get('score'),R.get('score')
        mid=f'<b class="{"w" if L.get("win") else ""}">{a}</b><em>:</em><b class="{"w" if R.get("win") else ""}">{b}</b>'
    if st=='live': s=f'<span class="lv"><i class="pl"></i>{E(x["badge"])}</span>'
    elif st=='final': s='<span class="fn">종료</span>'
    elif st=='postponed': s='<span class="fn">연기</span>'
    else: s=f'<span class="tt">{x["time"]}</span>'
    return f'<div class="gr {st}"><div class="st">{s}</div>{tm(L,"l")}<div class="sc">{mid}</div>{tm(R,"r")}<div class="fv{" on" if fav else ""}">★</div></div>'
order={'live':0,'scheduled':1,'final':2,'postponed':3}
leagues={}
for x in G: leagues.setdefault((x['sport'],x['league'],x['emoji']),[]).append(x)
lk=sorted(leagues,key=lambda k:(min(order[x['state']] for x in leagues[k]),-sum(x['state']=='live' for x in leagues[k])))
body=''
n=0
for k in lk[:7]:
    gs=sorted(leagues[k],key=lambda x:(order[x['state']],x['time']))
    nl=sum(x['state']=='live' for x in gs)
    body+=f'<div class="lg"><span>{k[2]} {E(k[1])}</span><small>{len(gs)}경기{f" · <i>LIVE {nl}</i>" if nl else ""}</small><b>›</b></div>'
    for i,x in enumerate(gs[:5]): body+=row(x,fav=(n==1));n+=1
nlive=sum(x['state']=='live' for x in G)
CSS=open('app.css').read()
TAB=lambda a:f'''<nav class="tab">{"".join(f'<a class="{"on" if a==i else ""}"><svg viewBox="0 0 24 24">{p}</svg>{t}</a>' for i,(t,p) in enumerate([("스코어",'<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M12 5v14M3 12h4M17 12h4"/>'),("순위",'<path d="M5 20V11M12 20V5M19 20v-6"/>'),("즐겨찾기",'<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>'),("고객센터",'<path d="M21 4L3 11l6 2 2 6 3-4 5 4z"/>')]))}</nav>'''
HEAD='<header class="hd"><div class="top"><div class="logo"><span class="w">Twowin</span><span class="s">SCORE</span></div><div class="ic"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg><svg viewBox="0 0 24 24"><path d="M6 16V11a6 6 0 0112 0v5l2 2H4z"/><path d="M10 21h4"/></svg><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 010 16z" fill="currentColor"/></svg></div></div>'
dates=''.join(f'<a class="{"on" if l=="오늘" else ""}"><small>{l}</small><b>{d}</b></a>' for l,d in [("목","10.08"),("어제","10.09"),("오늘","10.10"),("내일","10.11"),("월","10.12"),("화","10.13")])
sports=['전체','야구','축구','농구','배구','아이스하키']
cnt={s:sum(x['sport']==s for x in G) for s in sports}
chips=''.join(f'<a class="{"on" if s=="전체" else ""}">{s}<i>{len(G) if s=="전체" else cnt[s]}</i></a>' for s in sports)
home=f'''{HEAD}<div class="ds">{dates}</div><div class="ch"><a class="lvc"><i class="pl"></i>LIVE {nlive}</a>{chips}</div></header><main class="ls">{body}</main>{TAB(0)}'''
# standings
h=open('st.html').read();t=re.search(r'<table.*?</table>',h,re.S).group(0)
tabs=''.join(f'<a class="{"on" if s=="KBO" else ""}">{s}</a>' for s in ['KBO','NPB 센트럴','NPB 퍼시픽','MLB','K리그1','EPL'])
stand=f'''{HEAD}<div class="ch">{tabs}</div></header><main class="sw"><div class="sth"><b>2026 KBO 정규시즌</b><small>10.10 기준</small></div>{t}</main>{TAB(1)}'''
def page(b,n): open(f'{n}.html','w').write(f'<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width"><style>{CSS}</style><body>{b}</body>')
page(home,'home');page(stand,'standings')
