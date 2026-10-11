(function(){if(window.__socg)return;window.__socg=1;const D=document;
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function marks(){if(!window.TW_ME)return;D.querySelectorAll('.mpb,a[href="/me"]:not(.mpa)').forEach(a=>{if(!a.querySelector('.dmbg'))a.insertAdjacentHTML('beforeend','<i class="dmbg" hidden></i>')})}
let n=0;async function tick(){if(!window.TW_ME||D.hidden)return;try{const j=await (await fetch('/api/social/badge',{credentials:'same-origin',cache:'no-store'})).json();if(!j.ok)return;n=(j.dm||0)+(j.req||0);marks();D.querySelectorAll('.dmbg').forEach(b=>{b.textContent=n>99?'99+':n;b.hidden=!n})}catch(e){}}
setTimeout(tick,1500);setInterval(tick,30000);D.addEventListener('visibilitychange',()=>{if(!D.hidden)tick()});
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
 const act=p.rel==='self'?'<p class="pc-m">내 프로필이에요.</p>':p.rel==='guest'?'<a class="pri" href="/login">로그인하고 친구추가</a>':p.rel==='friend'?`<a class="pri" href="/friends?t=dm&peer=${p.id}">대화하기</a>`:p.rel==='sent'?'<p class="pc-m">친구 요청을 보냈어요.</p>':p.rel==='recv'?`<button class="pri" data-pa="accept">친구 수락</button>`:`<button class="pri" data-pa="req">친구추가</button>`;
 card.innerHTML=`<div class="pc-h">${lv}${vp}<span>${esc(p.nick)}</span>${p.lv?`<small class="pc-m">· ${esc(p.lv[0])}</small>`:''}</div><div class="pc-a">${act}</div>`;place();
 const b=card.querySelector('[data-pa]');if(b)b.onclick=async ev=>{ev.stopPropagation();b.disabled=true;let k;try{k=await (await fetch('/api/social/friend',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF':window.TW_CSRF||''},body:JSON.stringify({act:b.dataset.pa,id:p.id})})).json()}catch(x){k={ok:false}}
  if(card)card.querySelector('.pc-a').innerHTML=`<p class="pc-m">${k.ok?(k.rel==='friend'?'친구가 됐어요!':'친구 요청을 보냈어요.'):esc(k.error||'요청을 처리할 수 없어요.')}</p>`}},true);
addEventListener('scroll',close,{passive:true});})();
;(function(){/* 히어로(overflow:hidden) 안의 마이페이지 드롭다운이 잘리지 않게 fixed 로 띄움 */
function fix(){if(document.body.classList.contains('mapp'))return;document.querySelectorAll('.hero5 .mpw').forEach(w=>{const p=w.querySelector('.mpp'),b=w.querySelector('.mpb');if(!p||!b)return;if(p.hidden){p.style.position='';return}
 const r=b.getBoundingClientRect();p.style.position='fixed';p.style.top=(r.bottom+8)+'px';p.style.right=Math.max(8,innerWidth-r.right-4)+'px';p.style.left='auto';p.style.maxHeight=(innerHeight-r.bottom-20)+'px';p.style.overflowY='auto'})}
document.addEventListener('click',e=>{if(e.target.closest('.mpb'))setTimeout(fix,0)});addEventListener('resize',fix);
addEventListener('scroll',()=>{document.querySelectorAll('.hero5 .mpp:not([hidden])').forEach(p=>{if(p.style.position==='fixed')fix()})},{passive:true});})();
