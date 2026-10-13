# top.css 의 모바일(≤1023px) 경기장 스트립 규칙을 PC(≥1024px)용 .tp.pcv 범위로 복제해 static/pcv.css 생성
import re
src=open("static/top.css").read()
def blocks(s):
    i=0;out=[]
    while i<len(s):
        j=s.find("{",i)
        if j<0:break
        head=s[i:j].strip();d=1;k=j+1
        while d:
            d+= {"{":1,"}":-1}.get(s[k],0);k+=1
        out.append((re.sub(r"/\*.*?\*/","",head,flags=re.S).strip(),s[j+1:k-1]));i=k
    return out
SKIP=re.compile(r"tprow|tpvs|tpinfo|tppl|tpbk|tptk|tpod|tkb|tkx|gm7|dmain|ch-|vt8|cs8")
TP=re.compile(r"\.tp(st|sh|g|h|t|c|tag|ev|fx|bb|sb)?(?![\w-])")
rules=[]
for h,b in blocks(src):
    if not(h.startswith("@media") and "max-width:1023px" in h.replace(" ","")):continue
    for sel,body in blocks(b):
        if sel.startswith("@keyframes"):rules.append(f"{sel}{{{body}}}");continue
        if sel.startswith("@"):continue
        out=[]
        for s in sel.split(","):
            s=s.strip()
            if SKIP.search(s) or not TP.search(s):continue
            if re.search(r"\.tp(?![\w-])",s):s=re.sub(r"\.tp(?![\w-])",".tp.pcv",s,count=1)
            else:
                m=TP.search(s);s=s[:m.start()]+".pcv "+s[m.start():]
            out.append(s)
        if out:rules.append(",".join(out)+"{"+body+"}")
PC=""".tp.pcv{padding:0;margin:0 0 12px;background:none}
.tp.pcv .tprow,.tp.pcv .tpod{display:none!important}
.tp.pcv .tpst{height:220px;margin:0;border-radius:18px}
.tp.pcv .tpsb{left:14px;right:14px;top:12px;padding:8px 18px;border-radius:14px}
.tp.pcv .tpt img{width:36px;height:36px}
.tp.pcv .tpt b{font-size:17px}
.tp.pcv .tpc .sc{font-size:34px}.tp.pcv .tpc .sc i{font-size:24px}
.tp.pcv .tpc .clk{font-size:12px;margin-top:3px;padding:1px 9px}
.tp.pcv .tptag{left:16px;right:16px;bottom:12px;font-size:12px;height:22px}
.tp.pcv .tptag .lg{max-width:45%}
.tp.pcv .tpev,.tp.pcv .tpbb{bottom:46px}.tp.pcv .tpev{font-size:13.5px;padding:6px 16px}
.tp.pcv .tpbb{transform:scale(1.25);transform-origin:right bottom;right:16px}
.tp.pcv .tpfx{padding-top:80px}.tp.pcv .tpfx .t{font-size:15px}
.tp.pcv.k-football .tpev{display:none}
.dmain:has(>.tp.pcv) #hero{display:flex;align-items:center;justify-content:center;gap:12px;padding:9px 18px;min-height:0}
.dmain:has(>.tp.pcv) #hero .lg6{margin:0}
.dmain:has(>.tp.pcv) #hero .gt6{display:block;min-height:0;margin:0;padding:0}
.dmain:has(>.tp.pcv) #hero .t6,.dmain:has(>.tp.pcv) #hero .score5{display:none}
.dmain:has(>.tp.pcv) #hero .m6{display:block;margin:0;padding:0}
.dmain:has(>.tp.pcv) #hero .m6>span{margin:0}"""
open("static/pcv.css","w").write("/* 자동 생성(ops/gen_pcv.py): PC 상세 경기장 스트립 = 모바일 E안과 동일한 모양. 모바일엔 영향 없음 */\n@media (min-width:1024px){\n"+"\n".join(rules)+"\n"+PC+"\n}\n")
print(len(rules))
