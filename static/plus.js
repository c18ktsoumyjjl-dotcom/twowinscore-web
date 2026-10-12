/* 투윈스코어 추가 기능: 추정 승리확률 차트 · 예측 리그 · 핫한 경기 TOP3 · 즐겨찾기 팀 푸시 */
(function(){
const $=s=>document.querySelector(s),E=s=>String(s==null?'':s).replace(/[<>&"']/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c]));
/* ---- 1) 추정 승리확률 ---- */
function wpDraw(w){const box=$('#wp5b'),sec=$('#wp5');if(!box||!w||!w.pts||w.pts.length<3){if(sec)sec.hidden=true;return}
 const L=sec.dataset.l,R=sec.dataset.r,P=w.pts,last=P[P.length-1],W=320,H=96,pad=4;
 const x=p=>pad+p*(W-2*pad),y=v=>pad+(100-v)/100*(H-2*pad);
 const d=P.map((q,i)=>(i?'L':'M')+x(q.p).toFixed(1)+' '+y(q.L).toFixed(1)).join(' ');
 const area=d+` L${x(last.p).toFixed(1)} ${y(0)} L${x(0)} ${y(0)} Z`;
 box.innerHTML=`<div class="wp5n"><span class="l">${E(L)} <b>${last.L}%</b></span>${w.draw?`<span class="c">무 ${last.D}%</span>`:'<span class="c">'+E(last.t)+'</span>'}<span class="r"><b>${last.R}%</b> ${E(R)}</span></div>`+
 `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${E(L)} 추정 승리확률 추이, 현재 ${last.L}%"><line class="ax" x1="${pad}" x2="${W-pad}" y1="${y(0)}" y2="${y(0)}"/><line class="mid" x1="${pad}" x2="${W-pad}" y1="${y(50)}" y2="${y(50)}"/><path class="ar" d="${area}"/><path class="ln" d="${d}" vector-effect="non-scaling-stroke"/><circle class="dt" cx="${x(last.p)}" cy="${y(last.L)}" r="3"/></svg><div class="wp5x"><span>시작</span><span>${w.live?'현재':'종료'}</span></div>`}
const wj=$('#wp5j');if(wj){try{wpDraw(JSON.parse(wj.textContent))}catch(e){}const s=$('#wp5');if(s&&s.dataset.live==='1')setInterval(async()=>{if(document.hidden)return;try{const j=await (await fetch('/api/wp/'+encodeURIComponent(s.dataset.k)+'?d='+s.dataset.d)).json();if(j.ok)wpDraw(j)}catch(e){}},60000)}
/* ---- 4) 예측 리그 ---- */
const pr=$('#pr5');
async function prLoad(){const D=pr.dataset,lh=D.lh==='1',draw=D.draw==='1',open=D.open==='1';let j;
 try{j=await (await fetch('/api/pred/'+encodeURIComponent(D.k),{cache:'no-store'})).json()}catch(e){return}
 if(!j.ok||(!open&&!j.mine)){pr.hidden=true;return}
 const sideToPick=s=>s==='D'?'D':((s==='L')===lh?'H':'A'),pickToSide=p=>p==='D'?'D':((p==='H')===lh?'L':'R');
 const c=j.counts||{},cl=c[lh?'H':'A']||0,cr=c[lh?'A':'H']||0,cd=c.D||0,tot=cl+cr+cd;
 const bar=tot>=5?`<div class="bar" title="참여 ${tot}명"><i style="width:${cl*100/tot}%"></i>${draw?`<i style="width:${cd*100/tot}%"></i>`:''}<i style="width:${cr*100/tot}%"></i></div><p class="msg">참여 ${tot}명 · ${E(D.l)} ${Math.round(cl*100/tot)}%${draw?` · 무 ${Math.round(cd*100/tot)}%`:''} · ${E(D.r)} ${Math.round(cr*100/tot)}%</p>`:'';
 const head='<h3>🎯 예측 리그 <small>무료 · 적중 시 등급 포인트</small><a class="more" href="/predict">시즌 순위 →</a></h3>';
 const m=j.mine,ms=m?pickToSide(m.pick):null,nm=s=>s==='L'?D.l+' 승':s==='R'?D.r+' 승':'무승부';
 if(!open){const r=m.res==='W'?`<b>적중! +${m.pts}점</b>`:m.res==='L'?'아쉽게 빗나갔어요':m.res==='X'?'경기 취소로 무효':'경기 종료 후 정산돼요';
  pr.innerHTML=head+`<p class="msg">내 예측: <b>${E(nm(ms))}</b>${m.ph!=null?` (${lh?m.ph:m.pa}:${lh?m.pa:m.ph})`:''} · ${r}</p>`+bar;pr.hidden=false;return}
 if(!j.login){pr.innerHTML=head+`<p class="msg">경기 시작 전까지 승패를 예측하고 맞히면 등급 포인트를 받아요. <a href="/login">로그인</a>하고 참여하세요.</p>`+bar;pr.hidden=false;return}
 const btn=s=>`<button type="button" data-s="${s}" class="${ms===s?'on':''}">${E(s==='D'?'무승부':(s==='L'?D.l:D.r)+' 승')}</button>`;
 const sl=m&&m.ph!=null?(lh?m.ph:m.pa):'',sr=m&&m.ph!=null?(lh?m.pa:m.ph):'';
 pr.innerHTML=head+`<div class="bt">${btn('L')}${draw?btn('D'):''}${btn('R')}</div><div class="sc"><span>스코어(선택)</span><input inputmode="numeric" maxlength="2" id="pr5l" value="${sl}" aria-label="${E(D.l)} 점수"> : <input inputmode="numeric" maxlength="2" id="pr5r" value="${sr}" aria-label="${E(D.r)} 점수"><button type="button" id="pr5s">${m?'수정':'예측하기'}</button></div><p class="msg" id="pr5m">${m?'예측 완료 · 경기 시작 전까지 바꿀 수 있어요':'승패 적중 '+5+'점, 스코어까지 맞히면 +5점'}</p>`+bar;pr.hidden=false;
 let sel=ms;pr.querySelectorAll('.bt button').forEach(b=>b.onclick=()=>{sel=b.dataset.s;pr.querySelectorAll('.bt button').forEach(x=>x.classList.toggle('on',x===b))});
 $('#pr5s').onclick=async()=>{const mm=$('#pr5m');if(!sel){mm.textContent='먼저 승패를 골라 주세요.';return}
  const a=$('#pr5l').value.trim(),b=$('#pr5r').value.trim();let ph=null,pa=null;
  if(a!==''||b!==''){const l=+a,r=+b;if(!/^\d{1,2}$/.test(a)||!/^\d{1,2}$/.test(b)){mm.textContent='스코어는 숫자로 넣어 주세요.';return}
   const ok=sel==='D'?l===r:(sel==='L'?l>r:r>l);if(!ok){mm.textContent='스코어가 고른 승패와 맞지 않아요.';return}ph=lh?l:r;pa=lh?r:l}
  try{const r=await fetch('/api/pred',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF':window.TW_CSRF||''},body:JSON.stringify({k:D.k,d:D.d,pick:sideToPick(sel),ph,pa})});const x=await r.json();
   if(x.ok)prLoad();else mm.textContent=x.error||'잠시 후 다시 시도해 주세요.'}catch(e){mm.textContent='잠시 후 다시 시도해 주세요.'}}}
if(pr)prLoad();
/* ---- 3) 지금 핫한 경기 TOP 3 ---- */
const hot=$('#hot5'),mds=$('#mds');
async function hotLoad(){if(!hot||document.hidden)return;if(mds&&mds.dataset.d!==mds.dataset.today){hot.hidden=true;return}
 let j;try{j=await (await fetch('/api/hot',{cache:'no-store'})).json()}catch(e){return}
 const gs=(j&&j.games)||[];if(!gs.length){hot.hidden=true;return}
 hot.innerHTML='<div class="ht">🔥 지금 핫한 경기</div>'+gs.map((g,i)=>`<a href="/game/${encodeURIComponent(g.k)}"><span class="r">${i+1}</span><span class="hl">${E(g.lg)}</span><span class="m">${E(g.L)}<b>${E(g.ls)}:${E(g.rs)}</b>${E(g.R)}</span><span class="t"><i>${E(g.b)}</i>${E(g.tags.join(' · '))}</span></a>`).join('');
 hotVis()}
function hotVis(){if(!hot||!hot.innerHTML)return;const f=$('#feat');hot.hidden=!!(f&&f.style.display==='none')}
if(hot){hotLoad();setInterval(hotLoad,30000);new MutationObserver(hotVis).observe($('#feat')||document.body,{attributes:true,attributeFilter:['style']})}
/* ---- 2) 즐겨찾기 팀 웹 푸시 (옵트인) ---- */
const PK='tw_push',favs=()=>{try{return JSON.parse(localStorage.getItem('tw_fav')||'[]')}catch(e){return[]}};
const can='serviceWorker' in navigator&&'PushManager' in window&&'Notification' in window;
const u8=b=>{const p='='.repeat((4-b.length%4)%4),s=atob((b+p).replace(/-/g,'+').replace(/_/g,'/'));return Uint8Array.from(s,c=>c.charCodeAt(0))};
async function sync(sub){const t=favs();await fetch('/api/push/sub',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sub:sub.toJSON(),teams:t})});localStorage.setItem(PK,JSON.stringify(t))}
async function pushOn(){if(!can){alert('이 브라우저는 알림을 지원하지 않아요. 아이폰은 홈 화면에 추가한 뒤 켤 수 있어요.');return false}
 const k=await (await fetch('/api/push/key')).json();if(!k.ok){alert('알림 기능을 준비 중이에요.');return false}
 if(await Notification.requestPermission()!=='granted'){alert('브라우저 설정에서 알림을 허용해 주세요.');return false}
 const reg=await navigator.serviceWorker.ready;const sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:u8(k.key)});await sync(sub);
 if(!favs().length)alert('알림을 켰어요. 팀 옆 ☆를 눌러 즐겨찾기한 팀의 득점·역전·막판 접전을 알려드려요.');return true}
async function pushOff(){try{const reg=await navigator.serviceWorker.ready,sub=await reg.pushManager.getSubscription();if(sub){await fetch('/api/push/unsub',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({endpoint:sub.endpoint})});await sub.unsubscribe()}}catch(e){}localStorage.removeItem(PK)}
const menu=$('#sndMenu');
if(menu&&can){const b=document.createElement('button');b.className='push5';b.type='button';const lab=()=>b.textContent=localStorage.getItem(PK)?'🔔 즐겨찾기 팀 알림 끄기':'🔔 즐겨찾기 팀 알림 켜기';lab();
 b.onclick=async e=>{e.stopPropagation();b.disabled=true;try{localStorage.getItem(PK)?await pushOff():await pushOn()}catch(x){alert('알림을 켜지 못했어요. 잠시 후 다시 시도해 주세요.')}b.disabled=false;lab()};menu.appendChild(b)}
if(can&&localStorage.getItem(PK)){const chk=async()=>{try{if(localStorage.getItem(PK)===JSON.stringify(favs()))return;const reg=await navigator.serviceWorker.ready,sub=await reg.pushManager.getSubscription();if(sub)await sync(sub);else localStorage.removeItem(PK)}catch(e){}};setTimeout(chk,3000);setInterval(chk,20000)}
})();
