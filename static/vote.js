/* 팬 응원 투표 + AI 경기 포인트 + 오늘의 주목 경기 (기록 기반, 예측 아님) */
(function(){
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const mine=()=>{try{return JSON.parse(localStorage.getItem('tw_votes')||'{}')}catch(e){return{}}};
const setMine=(k,s)=>{const m=mine();m[k]=s;const ks=Object.keys(m);if(ks.length>300)delete m[ks[0]];localStorage.setItem('tw_votes',JSON.stringify(m))};
const C={};
function vhtml(o){/* o:{k,L,R,draw,open} */
 return `<div class="vt8" data-k="${esc(o.k)}" data-l="${esc(o.L)}" data-r="${esc(o.R)}" data-draw="${o.draw?1:0}" data-open="${o.open?1:0}"></div>`}
function paint(el){const k=el.dataset.k,c=C[k],my=mine()[k],open=el.dataset.open==='1',dr=el.dataset.draw==='1';
 const sides=[['L',el.dataset.l],...(dr?[['D','무승부']]:[]),['R',el.dataset.r]];
 const tot=c?c.L+c.R+(c.D||0):0;const show=(my||!open)&&c;
 let h=`<div class="vt8h"><b>📣 팬 응원</b><small>${show?`${tot.toLocaleString()}명 참여`:open?'응원하는 팀을 눌러주세요':'응원 마감'}</small></div><div class="vt8b">`;
 h+=sides.map(([s,n])=>{const p=tot?Math.round((c[s]||0)*100/tot):0;
  return show?`<div class="vt8r ${my===s?'me':''}"><span class="nm">${esc(n)}${my===s?' ✓':''}</span><span class="vbar"><span class="fill" style="width:${p}%"></span></span><b>${p}%</b></div>`
  :`<button class="vt8btn" data-s="${s}" ${open?'':'disabled'}>${esc(n)}</button>`}).join('');
 el.innerHTML=h+`</div><p class="vt8n">팬들의 응원 비율이며 경기 결과 예측이 아닙니다.${open&&!my?'':' 투표는 경기 시작 전까지 가능해요.'}</p>`}
async function scan(root,lazy){const els=[...(root||document).querySelectorAll('.vt8')];if(!els.length)return;
 const need=[...new Set(els.map(e=>e.dataset.k))].filter(k=>!lazy||!C[k]);if(!need.length){els.forEach(paint);return}
 try{const j=await (await fetch('/api/votes?k='+need.map(encodeURIComponent).join(','))).json();Object.assign(C,j)}catch(e){}
 els.forEach(paint)}
document.addEventListener('click',async e=>{const b=e.target.closest('.vt8btn');if(!b)return;e.preventDefault();e.stopPropagation();
 const el=b.closest('.vt8'),k=el.dataset.k,s=b.dataset.s;if(mine()[k])return;b.disabled=true;
 try{const r=await fetch('/api/vote?d='+(new URLSearchParams(location.search).get('d')||''),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({k,s})});const j=await r.json();
  if(j.counts){C[k]=j.counts;setMine(k,s)}else{alert(j.error||'잠시 뒤에 다시 시도해 주세요.');if(/마감/.test(j.error||''))el.dataset.open='0'}}catch(err){}
 document.querySelectorAll('.vt8[data-k="'+CSS.escape(k)+'"]').forEach(paint)},true);
function phtml(pts){if(!pts||!pts.length)return'';return `<div class="ap8"><h4>🤖 AI 경기 포인트</h4>${pts.map(p=>`<p>${esc(p)}</p>`).join('')}<small>기록 기반 자동 요약이며 경기 결과 예측이 아닙니다</small></div>`}
/* 주목 경기 */
function card(g){const sc=g.state!=='scheduled'&&g.L.score!=null;const lg=t=>t.logo?`<img src="${esc(t.logo)}" alt="" loading="lazy">`:'<i class="nologo"></i>';
 const st=g.state==='live'?`<em class="lv">● ${esc(g.badge)}</em>`:g.state==='scheduled'?`<em>${esc(g.time)}</em>`:`<em>${esc(g.badge)}</em>`;
 return `<div class="ft8c ${g.state}"><a class="ft8a" href="/game/${encodeURIComponent(g.key)}?d=${FD}"><div class="ft8t"><span>${g.emoji} ${esc(g.league)}</span>${st}</div>
 <div class="ft8m"><div class="ft8s">${lg(g.L)}<b>${esc(g.L.name)}</b></div><div class="ft8x">${sc?`${g.L.score}<i>:</i>${g.R.score}`:'<i>VS</i>'}</div><div class="ft8s">${lg(g.R)}<b>${esc(g.R.name)}</b></div></div>
 <div class="ft8g">${g.tags.map(t=>`<span>${esc(t)}</span>`).join('')}</div></a>${vhtml({k:g.key,L:g.L.name,R:g.R.name,draw:g.draw,open:g.vopen})}</div>`}
let FD='',FJ=null;
async function feat(d,box,ok){FD=d;try{FJ=await (await fetch('/api/featured?d='+d)).json();if(FJ.pending)setTimeout(()=>feat(d,box,ok),8000)}catch(e){}draw(box,ok)}
function draw(box,ok){if(!box)return;if(!FJ||!FJ.games.length||!ok){box.innerHTML='';box.hidden=true;return}box.hidden=false;
 box.innerHTML=`<h2 class="ft8h">⭐ ${FJ.today?'오늘의 ':''}주목 경기 <small>순위·연승·라이벌전 등 기록 기준</small></h2><div class="ft8l">${FJ.games.map(card).join('')}</div>`;scan(box)}
window.TWVote={html:vhtml,scan,points:phtml,feat,draw};
})();
