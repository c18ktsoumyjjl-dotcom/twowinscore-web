/* 모바일 상세 상단: 뒤로가기, 배당·볼카운트(비동기), 실제 이벤트가 새로 들어올 때만 짧은 연출 */
(function(){const S=document.querySelector('.tp');if(!S)return;document.body.classList.add('tpon');
const kind0=S.dataset.kind,K=S.dataset.k,Q=location.search,esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function goBack(e){if(e)e.preventDefault();const r=document.referrer;let same=false;try{same=r&&new URL(r).origin===location.origin}catch(x){}
 const d=new URLSearchParams(Q).get('d'),home='/'+(d?'?d='+encodeURIComponent(d):'');let left=false;addEventListener('pagehide',()=>{left=true},{once:true});
 const nav=u=>{if(window.TWnav)TWnav(u);else location.href=u};const bgm=!!(window.TWBgm&&TWBgm.el&&!TWBgm.el.paused);
 if(history.length>1&&same){const p0=location.href;history.back();setTimeout(()=>{if(!left&&location.href===p0)nav(home)},bgm?2500:700)}else nav(home)}
const bk=document.getElementById('tpbk');if(bk)bk.addEventListener('click',goBack);
function tgBack(){try{const tg=window.Telegram&&Telegram.WebApp;if(tg&&tg.BackButton&&(tg.initData||tg.platform&&tg.platform!=='unknown')){tg.BackButton.show();tg.BackButton.onClick(()=>goBack())}}catch(e){}}
const inTg=window.TelegramWebviewProxy||/tgWebApp/.test(location.hash)||/tgWebApp/.test(sessionStorage.getItem('tw_tg')||'');if(/tgWebApp/.test(location.hash))try{sessionStorage.setItem('tw_tg','tgWebApp')}catch(e){}
if(window.Telegram&&Telegram.WebApp)tgBack();else if(inTg){const sc=document.createElement('script');sc.src='https://telegram.org/js/telegram-web-app.js';sc.onload=tgBack;document.head.appendChild(sc)}
fetch('/api/odds?k='+encodeURIComponent(K)+'&d='+(new URLSearchParams(Q).get('d')||'')).then(r=>r.json()).then(j=>{const o=j[K];if(!o||o.L==null||o.R==null)return;const mv=o.mv||{};
 const c=(k,v,m)=>`<span class="c"><small>${k}</small><b class="${m>0?'up':m<0?'dn':''}">${Number(v).toFixed(2)}${m>0?'▲':m<0?'▼':''}</b></span>`;
 const lh=o.lh!==false;let h=`<span class="bk">${esc(o.bs||o.book||'')}</span>`+c(lh?'1':'원정',o.L,mv.L)+(o.D?c('X',o.D,mv.D):'')+c(lh?'2':'홈',o.R,mv.R);
 const x=o.x||{},ex=[];if(x.hc){const l=lh?x.hc.ln:-x.hc.ln;ex.push(`핸디 ${l>0?'+':''}${l}`)}if(x.ou)ex.push(`기준 ${x.ou.ln}`);if(ex.length)h+=`<span class="ex">${ex.join(' · ')}</span>`;
 const el=document.getElementById('tpod');el.innerHTML=h;el.hidden=false}).catch(()=>{});
const tk=document.getElementById('tptk');if(tk){const b=tk.querySelector('.tkb'),x=tk.querySelector('.tkx');b.onclick=()=>{const o=x.hidden;x.hidden=!o;b.setAttribute('aria-expanded',String(o));tk.classList.toggle('open',o);if(window.TWGMmeas)TWGMmeas()}}
const MQ=matchMedia('(max-width:1023px)');let spHome=null;
function placePlays(){const sp=document.getElementById('sec-plays');if(!sp)return;if(!spHome){spHome=document.createComment('sp');sp.before(spHome)}
 if(MQ.matches){const a=document.getElementById('lu9')||document.querySelector('.tmbar6');if(a&&a.nextElementSibling!==sp)a.after(sp)}else if(spHome.nextSibling!==sp)spHome.after(sp)}
placePlays();MQ.addEventListener('change',placePlays);
function setPla(j){if(!MQ.matches||!Array.isArray(j.pla))return;let sp=document.getElementById('sec-plays');if(!j.pla.length){if(sp)sp.hidden=true;return}
 if(!sp){sp=document.createElement('section');sp.className='box';sp.id='sec-plays';(document.getElementById('lu9')||document.querySelector('.tmbar6')||document.getElementById('hero')).after(sp)}
 sp.hidden=false;sp.innerHTML=`<h3>문자중계 <small>${esc(j.src||'')}</small></h3>`+j.pla.map(x=>`<p class="pl6 ${x.h?'hot':''}">${esc(x.t)}</p>`).join('');placePlays()}
function setPln(j){const e=document.querySelector('#tppl span');if(e&&typeof j.pln==='string'&&j.pln&&e.textContent!==j.pln){e.textContent=j.pln;e.classList.remove('nw');void e.offsetWidth;e.classList.add('nw')}}
function setVs(j){setPln(j);const o=document.getElementById('tpvs');if(o&&typeof j.vs==='string'&&j.vs)o.outerHTML=j.vs}
function setEv(pl){const e=document.getElementById('tpev');if(cxOn||!e||!Array.isArray(pl))return;if(!pl.length){e.hidden=true;return}if(e.textContent!==pl[0]){e.textContent=pl[0];e.classList.remove('nw');void e.offsetWidth;e.classList.add('nw')}e.hidden=false}
function setHot(ev){if(!Array.isArray(ev)||!ev.length)return;const x=ev[ev.length-1];if(x.t!=='goal'&&x.t!=='pen')return;S.querySelectorAll('.tph').forEach(h=>h.classList.toggle('on',h.classList.contains(x.t==='goal'?(x.s==='L'?'R':'L'):x.s)))}
function setPl(pl){setEv(pl);if(!tk||!Array.isArray(pl))return;if(!pl.length){tk.hidden=true;return}const l=tk.querySelector('.tkl');if(!cxOn&&l.textContent!==pl[0]){l.textContent=pl[0];l.classList.remove('nw');void l.offsetWidth;l.classList.add('nw')}tk.querySelector('.tkx').innerHTML=pl.map(t=>`<li>${esc(t)}</li>`).join('');tk.hidden=false}
/* 생생 문자중계: 서버(commentary.py)가 실제 기록으로 만든 문장(ev)과 상황 줄(ctx)을 받아, 새 이벤트는 즉시·순서대로, 없으면 실제 상황 줄을 돌려 보여 줌(직전 문장 반복 없음) */
let cxOn=false,cxFirst=true,cxLast='',cxT=0,cxPool=[];const cxSeen=new Set(),cxQ=[];
function cxShow(x){const t=x.t;if(!t)return;cxLast=t;const ls=[document.getElementById('tpev'),tk&&tk.querySelector('.tkl')];ls.forEach(e=>{if(!e)return;e.textContent=t;e.classList.toggle('hot',!!x.h);e.classList.remove('nw');void e.offsetWidth;e.classList.add('nw');if(e.id==='tpev')e.hidden=false});if(tk)tk.hidden=false}
function cxTick(){if(document.hidden)return;let x=cxQ.shift();if(!x){const c=cxPool.filter(y=>y.t&&y.t!==cxLast);if(!c.length)return;x=c[Math.floor(Math.random()*c.length)]}cxShow(x)}
function cxFeed(cx){if(!cx||!Array.isArray(cx.ev)||!(cx.ev.length||(cx.ctx||[]).length))return;cxOn=true;const nw=cx.ev.filter(x=>!cxSeen.has(x.k));nw.forEach(x=>cxSeen.add(x.k));
 if(cxFirst){cxFirst=false;if(cx.ev[0])cxQ.push(cx.ev[0])}else if(nw.length){cxQ.push(...nw.slice(0,4).reverse());cxQ.splice(0,Math.max(0,cxQ.length-4))}
 cxPool=[...(cx.ctx||[]).map(t=>({t,h:0})),...cx.ev.slice(0,3)];if(!cxT||nw.length&&!cxFirst){clearInterval(cxT);cxTick();cxT=setInterval(cxTick,6500)}}
if(S.dataset.live!=='1')return;
if(kind0!=='football'&&kind0!=='hockey'){const pp=async()=>{if(document.hidden)return;try{const j=await (await fetch('/api/top/'+encodeURIComponent(K)+Q,{cache:'no-store'})).json();const sb=S.querySelectorAll('.tpc .sc b');if(sb.length===2&&j.L!=null){sb[0].textContent=j.L;sb[1].textContent=j.R;sb[0].className=j.L>j.R?'ld':'';sb[1].className=j.R>j.L?'ld':''}cxFeed(j.cx);setPl(j.pl);setPla(j);setVs(j);const c=document.getElementById('tpclk');if(c&&j.period)c.textContent=j.period}catch(e){}};setInterval(pp,5000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)pp()})}
const bb=S.querySelector('.tpbb');
function bso(){if(!bb||document.hidden)return;fetch('/api/bso?k='+encodeURIComponent(K)+'&d='+(new URLSearchParams(Q).get('d')||'')).then(r=>r.json()).then(j=>{const b=j[K];if(!b||b.b==null)return;
 ['b1','b2','b3'].forEach((id,i)=>S.querySelector('#'+id).classList.toggle('on',!!(b.r||[])[i]));
 const dots=(n,m,c)=>Array.from({length:m},(_,i)=>`<i class="${i<n?c:''}"></i>`).join('');
 bb.querySelector('.bso').innerHTML=`B${dots(b.b,3,'B')} S${dots(b.s,2,'S')} O${dots(b.o,2,'O')}`;bb.hidden=false}).catch(()=>{})}
if(bb){bso();setInterval(bso,15000)}
const kind=S.dataset.kind;if(kind!=='football'&&kind!=='hockey'){return}
const fx=S.querySelector('.tpfx'),st=S.querySelector('.tpst'),seen=new Set();let first=true;
const NM={goal:'⚽ 골!',yel:'🟨 경고',red:'🟥 퇴장',sub:'🔁 교체',pen:'⏱ 페널티'};if(kind==='hockey')NM.goal='🏒 골!';
function show(e){const d=document.createElement('div');d.className='t '+e.t;d.textContent=`${NM[e.t]||''} ${e.lab} ${e.who||''}`.trim();fx.innerHTML='';fx.appendChild(d);if(e.t==='goal'){st.classList.remove('flash');void st.offsetWidth;st.classList.add('flash')}}
async function poll(){if(document.hidden)return;try{const j=await (await fetch('/api/top/'+encodeURIComponent(K)+Q,{cache:'no-store'})).json();
 setHot(j.ev);const nw=(j.ev||[]).filter(e=>{const k=e.t+e.s+e.m+e.lab+e.who;return !seen.has(k)&&seen.add(k)});if(!first&&nw.length)show(nw[nw.length-1]);first=false;
 const sb=S.querySelectorAll('.tpc .sc b');if(sb.length===2&&j.L!=null){sb[0].textContent=j.L;sb[1].textContent=j.R;sb[0].className=j.L>j.R?'ld':'';sb[1].className=j.R>j.L?'ld':''}
 cxFeed(j.cx);setPl(j.pl);setPla(j);setVs(j);const c=document.getElementById('tpclk');if(c&&j.period)c.textContent=j.period}catch(e){}}
poll();setInterval(poll,8000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll()})})();
