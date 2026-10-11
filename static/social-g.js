(function(){if(window.__socg)return;window.__socg=1;const D=document;
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function marks(){if(!window.TW_ME)return;D.querySelectorAll('.mpb,a[href="/me"]:not(.mpa)').forEach(a=>{if(!a.querySelector('.dmbg'))a.insertAdjacentHTML('beforeend','<i class="dmbg" hidden></i>')})}
const NX={u:x=>x.k==='dm'?'/friends?t=dm&peer='+x.a:x.k==='cmt'?'/u/'+encodeURIComponent(window.TW_ME||'')+'?p='+(String(x.b).split('|')[0]|0):'/u/'+encodeURIComponent(x.n),
 i:x=>x.k==='dm'?'💬':x.k==='cmt'?'💭':'👋',
 t:x=>x.k==='dm'?`<b>${esc(x.n)}</b> ${esc(x.b)}`:x.k==='cmt'?`<b>${esc(x.n)}</b>님이 회원님의 게시물에 댓글을 남겼어요: ${esc(String(x.b).split('|').slice(1).join('|'))}`:`<b>${esc(x.n)}</b>님이 회원님을 팔로우했어요`};
function toast(x){let w=D.getElementById('twnt');if(!w){w=D.createElement('div');w.id='twnt';D.body.appendChild(w)}
 const t=D.createElement('a');t.className='twnt '+x.k;t.href=NX.u(x);t.innerHTML=`<i>${NX.i(x)}</i><span>${NX.t(x)}</span><button type="button" aria-label="닫기">×</button>`;
 t.onclick=e=>{if(e.target.tagName==='BUTTON'){e.preventDefault();t.remove();return}rd(x.id)};w.appendChild(t);setTimeout(()=>t.classList.add('on'),20);setTimeout(()=>{t.classList.remove('on');setTimeout(()=>t.remove(),300)},7000);
 try{if(window.TWsnd&&TWsnd.on&&TWsnd.on()){}}catch(e){}}
function rd(id){fetch('/api/social/notifs/read',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF':window.TW_CSRF||''},body:JSON.stringify({id})}).catch(()=>{})}
const LK=()=>'tw_nl_'+(window.TW_ME||'');
let n=0;async function tick(){if(!window.TW_ME||D.hidden)return;try{const st=localStorage.getItem(LK());const after=st==null?'':('&after='+st);
 const j=await (await fetch('/api/social/badge?x=1'+after,{credentials:'same-origin',cache:'no-store'})).json();if(!j.ok)return;
 n=Math.max(j.noti||0,(j.dm||0)+(j.req||0));marks();const f=(j.dm||0)+(j.req||0),nt=j.noti||0,S=(b,v)=>{b.textContent=v>99?'99+':v;b.hidden=!v};D.querySelectorAll('.dmbg').forEach(b=>S(b,b.closest('.mpa')?(b.closest('.mpa').dataset.k==='nt'?nt:f):n));
 const cur=+(localStorage.getItem(LK())||-1);
 if(st!=null&&j.new){j.new.filter(x=>x.id>cur).reverse().slice(-3).forEach(x=>{if(x.k==='dm'&&String(window.TW_DMPEER||'')===String(x.a)){rd(x.id);return}toast(x)})}
 if(j.top>cur)localStorage.setItem(LK(),j.top);window.dispatchEvent(new CustomEvent('tw:badge',{detail:j}))}catch(e){}}
window.TWbadge=tick;
setTimeout(tick,1200);setInterval(tick,12000);D.addEventListener('visibilitychange',()=>{if(!D.hidden)tick()});
let card=null;function close(){if(card){card.remove();card=null}}
D.addEventListener('click',async e=>{if(card&&!card.contains(e.target))close();
 const nEl=e.target.closest('.ch-m .ch-n');if(!nEl||nEl.closest('.cbot')||nEl.querySelector('.ch-tg,.ch-bot'))return;
 const nick=[...nEl.childNodes].filter(x=>x.nodeType===3||(x.tagName&&!/IMG|I|SMALL/.test(x.tagName))).map(x=>x.textContent).join('').trim().replace(/#\d{4}$/,'').trim();if(!nick)return;
 e.preventDefault();e.stopPropagation();close();const r=nEl.getBoundingClientRect();
 card=D.createElement('div');card.className='pcard';card.innerHTML='<p class="pc-m">불러오는 중…</p>';D.body.appendChild(card);
 const place=()=>{const w=card.offsetWidth,h=card.offsetHeight;card.style.left=Math.max(8,Math.min(innerWidth-w-8,r.left))+'px';card.style.top=(r.bottom+h+8>innerHeight?Math.max(8,r.top-h-6):r.bottom+6)+'px'};place();
 let j;try{j=await (await fetch('/api/social/profile?nick='+encodeURIComponent(nick),{credentials:'same-origin'})).json()}catch(x){j={ok:false}}
 if(!card)return;if(!j.ok){card.innerHTML='<p class="pc-m">비회원이거나 찾을 수 없는 회원이에요.</p>';place();return}
 const p=j.p,lv=p.lv&&/^[0-4]$/.test(String(p.lv[2]))?`<img src="/static/tiers/t${p.lv[2]}_32.webp?v=1" width="18" height="18" alt="">`:'',vp=p.vip?'<img src="/static/vip/vip_gem_32.webp?v=1" width="18" height="18" alt="VIP">':'';
 const act=p.rel==='self'?'<p class="pc-m">내 프로필이에요.</p>':p.rel==='guest'?'<a class="pri" href="/login">로그인하고 팔로우</a>':p.rel==='friend'?`<a class="pri" href="/friends?t=dm&peer=${p.id}">대화하기</a>`:p.rel==='sent'?'<p class="pc-m">팔로잉 중 · 맞팔하면 대화할 수 있어요</p>':p.rel==='recv'?`<button class="pri" data-pa="follow">맞팔로우</button>`:`<button class="pri" data-pa="follow">팔로우</button>`;
 card.innerHTML=`<div class="pc-h">${lv}${vp}<span>${esc(p.nick)}</span>${p.lv?`<small class="pc-m">· ${esc(p.lv[0])}</small>`:''}</div><div class="pc-a">${act}${p.rel!=='guest'?`<a class="pc-fd" href="/u/${encodeURIComponent(p.nick)}">피드</a>`:''}</div>`;place();
 const b=card.querySelector('[data-pa]');if(b)b.onclick=async ev=>{ev.stopPropagation();b.disabled=true;let k;try{k=await (await fetch('/api/social/friend',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF':window.TW_CSRF||''},body:JSON.stringify({act:b.dataset.pa,id:p.id})})).json()}catch(x){k={ok:false}}
  if(card)card.querySelector('.pc-a').innerHTML=`<p class="pc-m">${k.ok?(k.rel==='friend'?'맞팔로우가 됐어요! 이제 대화할 수 있어요.':'팔로우했어요.'):esc(k.error||'요청을 처리할 수 없어요.')}</p>`}},true);
addEventListener('scroll',close,{passive:true});})();
;(function(){/* 히어로(overflow:hidden) 안의 마이페이지 드롭다운이 잘리지 않게 fixed 로 띄움 */
function fix(){if(document.body.classList.contains('mapp'))return;document.querySelectorAll('.hero5 .mpw').forEach(w=>{const p=w.querySelector('.mpp'),b=w.querySelector('.mpb');if(!p||!b)return;if(p.hidden){p.style.position='';return}
 const r=b.getBoundingClientRect();p.style.position='fixed';p.style.top=(r.bottom+8)+'px';p.style.right=Math.max(8,innerWidth-r.right-4)+'px';p.style.left='auto';p.style.maxHeight=(innerHeight-r.bottom-20)+'px';p.style.overflowY='auto'})}
document.addEventListener('click',e=>{if(e.target.closest('.mpb'))setTimeout(fix,0)});addEventListener('resize',fix);
addEventListener('scroll',()=>{document.querySelectorAll('.hero5 .mpp:not([hidden])').forEach(p=>{if(p.style.position==='fixed')fix()})},{passive:true});})();
