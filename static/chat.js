function pollHtml(p){return `<div class="ch-poll" data-room="${esc(p.room)}"><button type="button" data-s="L"><span>${esc(p.L)}</span><b>·</b></button><button type="button" data-s="R"><span>${esc(p.R)}</span><b>·</b></button></div>`}
function pollBind(d,p){const box=d.querySelector('.ch-poll');if(!/^game-[A-Za-z0-9-]{1,80}$/.test(p.room))return;const u='/api/cheer/'+encodeURIComponent(p.room);
 const show=j=>{if(j&&typeof j.L==='number'){const t=Math.max(1,j.L+j.R);box.querySelectorAll('button').forEach(b=>{const v=b.dataset.s==='L'?j.L:j.R;b.querySelector('b').textContent=v.toLocaleString()+' · '+Math.round(v*100/t)+'%';b.style.setProperty('--p',Math.round(v*100/t)+'%')})}};
 fetch(u).then(r=>r.json()).then(show).catch(()=>{});
 box.onclick=e=>{const b=e.target.closest('button');if(!b)return;fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({side:b.dataset.s})}).then(r=>r.json()).then(j=>{show(j);if(j.ok)b.classList.add('on');else if(j.msg){b.title=j.msg}}).catch(()=>{})}}
/* 투윈스코어 채팅: 가입 없음, 2.5초 폴링 */
(function(){
const LS='tw_nick',CID_K='tw_cid';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function cid(){let c=localStorage.getItem(CID_K);if(!c){c=Array.from(crypto.getRandomValues(new Uint8Array(8)),b=>b.toString(16).padStart(2,'0')).join('');localStorage.setItem(CID_K,c)}return c}
function me(){if(window.TW_ME)return {nick:window.TW_ME,tag:'회원',mem:1};try{return JSON.parse(localStorage.getItem(LS)||'null')}catch(e){return null}}
function hm(ts){const d=new Date(ts*1000);return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')}
function mount(el,room,opt){
 opt=opt||{};let last=0,timer=null,active=!opt.lazy,busy=false;
 el.classList.add('chat');
 el.innerHTML=`<div class="ch-head"><b>${esc(opt.title||'채팅')}</b><span class="ch-on"><i class="odot"></i><span class="n">-</span>명 접속</span>${opt.close?'<button class="ch-x" aria-label="닫기">✕</button>':''}</div>
 <div class="ch-pin" aria-live="polite"></div><div class="ch-list" aria-live="polite"><p class="ch-empty">첫 메시지를 남겨 보세요.</p></div>
 <div class="ch-err"></div>
 <form class="ch-nick"><input maxlength="12" placeholder="닉네임 (2~12자)" required><button>입장</button></form>
 <div class="ch-mgh">📣 확성기 모드 · 5분 동안 채팅방 맨 위에 고정돼요 (80자)</div><form class="ch-form"><span class="ch-me"></span>${window.TW_ME?'<button type="button" class="ch-mega" aria-label="확성기" title="확성기"><span>📣</span><small></small></button>':''}<input maxlength="200" placeholder="메시지 입력 (200자)" autocomplete="off"><button aria-label="보내기">보내기</button></form>
 <div class="ch-gl" hidden><p>비회원은 하루 5번까지 채팅할 수 있어요. 회원가입 후 계속 채팅하세요</p><div><a class="ch-glb" href="/login?next=${encodeURIComponent(location.pathname)}">로그인</a><a class="ch-glb pri" href="/signup">회원가입</a></div></div>
 <p class="ch-rule">링크·연락처·욕설·홍보는 자동 차단돼요.</p>`;
 const list=el.querySelector('.ch-list'),err=el.querySelector('.ch-err'),nf=el.querySelector('.ch-nick'),mf=el.querySelector('.ch-form');
 const showErr=t=>{err.textContent=t||'';err.style.display=t?'block':'none';if(t)setTimeout(()=>{if(err.textContent===t)showErr('')},4000)};
 function setMode(){const m=me();nf.style.display=m?'none':'flex';mf.style.display=m?'flex':'none';if(m)el.querySelector('.ch-me').innerHTML=`${esc(m.nick)}<small>#${esc(m.tag)}</small>`}
 setMode();
 el.querySelector('.ch-me').onclick=()=>{if(window.TW_ME){location.href='/me';return}if(confirm('닉네임을 바꿀까요?')){localStorage.removeItem(LS);setMode()}};
 nf.onsubmit=e=>{e.preventDefault();const v=nf.querySelector('input').value.trim();
  if(!/^[0-9A-Za-z가-힣_]{2,12}$/.test(v)){showErr('닉네임은 2~12자 한글·영문·숫자로 해 주세요.');return}
  localStorage.setItem(LS,JSON.stringify({nick:v,tag:String(Math.floor(1000+Math.random()*9000))}));setMode();mf.querySelector('input').focus()};
 function add(ms){if(!ms.length)return;const atBottom=list.scrollHeight-list.scrollTop-list.clientHeight<60;
  list.querySelector('.ch-empty')?.remove();const m0=me();
  for(const m of ms){if(list.querySelector(`[data-id="${m.id}"]`))continue;const mine=m0&&m.nick===m0.nick&&m.tag===m0.tag;
   const d=document.createElement('div');d.className='ch-m'+(mine?' mine':'');d.dataset.id=m.id;
   d.dataset.ts=m.ts;if(m.src==='tg')d.classList.add('tg');if(m.vip)d.classList.add('vip');
   if(m.src==='bot'){d.classList.add('cbot');d.innerHTML=`<span class="ch-n"><b class="ch-bot">BOT</b><b class="bnk">투윈스코어</b></span><span class="ch-t">${esc(m.text)}</span>`+(m.x&&m.x.poll?pollHtml(m.x.poll):'')+`<time>${hm(m.ts)}</time>`;list.appendChild(d);if(m.x&&m.x.poll)pollBind(d,m.x.poll);continue}d.innerHTML=(m.src==='tg'?`<span class="ch-n"><b class="ch-tg">TG</b>${esc(m.nick)}</span>`:`<span class="ch-n">${m.lv?(/^[0-4]$/.test(String(m.lv[2]))?`<img class="lvi" src="/static/tiers/t${m.lv[2]}_32.webp?v=1" srcset="/static/tiers/t${m.lv[2]}_64.webp?v=1 2x" width="17" height="17" alt="${esc(m.lv[0])}" title="${esc(m.lv[0])}">`:`<i class="lvb" style="--c:${/^#[0-9a-f]{6}$/i.test(m.lv[1])?m.lv[1]:'#8a94a6'}">${esc(m.lv[0])}</i> `):''}${m.vip?'<img class="vipi" src="/static/vip/vip_gem_32.webp?v=1" srcset="/static/vip/vip_gem_64.webp?v=1 2x" width="17" height="17" alt="VIP" title="VIP">':''}${m.vip?`<b class="nkv">${esc(m.nick)}</b>`:(m.lv&&/^[34]$/.test(String(m.lv[2])))?`<b class="nkp t${m.lv[2]}">${esc(m.nick)}</b>`:esc(m.nick)}<small>#${esc(m.tag)}</small>${m.vip?'<i class="vipt">👑 VIP 회원</i>':''}</span>`)+`<span class="ch-t">${esc(m.text)}</span><time>${hm(m.ts)}</time>`;list.appendChild(d)}
  if(opt.onNew&&last>0){const n=ms.filter(m=>!(m0&&m.nick===m0.nick&&m.tag===m0.tag)).length;if(n)opt.onNew(n)}
  while(list.children.length>200)list.firstChild.remove();
  if(atBottom||last===0)list.scrollTop=list.scrollHeight}
 const pinEl=el.querySelector('.ch-pin'),mgh=el.querySelector('.ch-mgh'),mgb=el.querySelector('.ch-mega');let pin=null,pinAt=0,mega=false;
 function mgc(){if(mgb)mgb.querySelector('small').textContent=window.TW_MEGA>0?(window.TW_MEGA>99?'99+':window.TW_MEGA):''}mgc();
 function lvImg(lv){return lv&&/^[0-4]$/.test(String(lv[2]))?`<img src="/static/tiers/t${lv[2]}_32.webp?v=1" width="16" height="16" alt="${esc(lv[0])}">`:''}
 function pinDraw(){if(!pin){pinEl.classList.remove('on');pinEl.innerHTML='';return}const left=Math.max(0,pin.left-Math.floor((Date.now()-pinAt)/1000));if(left<=0){pinEl.classList.remove('on');return}
  pinEl.classList.add('on');pinEl.innerHTML=`<div class="pn">${lvImg(pin.lv)}${pin.vip?'<img src="/static/vip/vip_gem_32.webp?v=1" width="16" height="16" alt="VIP">':''}<span class="${pin.vip?'nkv':''}">${esc(pin.nick)}</span></div><div class="pt">${esc(pin.text)}</div><span class="pl">${Math.floor(left/60)}:${String(left%60).padStart(2,'0')}</span>${pin.queue?`<div class="pq">대기 ${pin.queue}개${pin.mypos?` · 내 확성기 ${pin.mypos}번째`:''}</div>`:''}`}
 function setPin(p){pin=p||null;pinAt=Date.now();pinDraw()}
 setInterval(pinDraw,1000);
 if(mgb)mgb.onclick=()=>{mega=!mega;mf.classList.toggle('mg',mega);mgh.classList.toggle('on',mega);const i=mf.querySelector('input');i.maxLength=mega?80:200;i.placeholder=mega?`확성기 메시지 (80자) · 보유 ${window.TW_MEGA||0}개`:'메시지 입력 (200자)';i.focus()};
 async function sendMega(inp,t,b){if(!(window.TW_MEGA>0)){if(confirm('확성기가 없어요. 스코어샵으로 갈까요?'))location.href='/shop';return}
  if(!confirm(`확성기 1개를 써서 5분 동안 고정할까요? (보유 ${window.TW_MEGA}개)`))return;b.disabled=true;
  try{const r=await fetch(`/api/mega/${room}`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF':window.TW_CSRF||''},body:JSON.stringify({text:t})});const j=await r.json();
   if(j.ok){window.TW_MEGA=j.mega;mgc();inp.value='';mega=false;mf.classList.remove('mg');mgh.classList.remove('on');inp.maxLength=200;inp.placeholder='메시지 입력 (200자)';setPin(j.pin);if(j.pos>0)showErr(`확성기 대기 ${j.pos}번째예요. 앞 확성기가 끝나면 고정돼요.`)}else showErr(j.error||'쓰지 못했어요.')}catch(e){showErr('연결이 불안정해요.')}setTimeout(()=>b.disabled=false,1500)}
 function expire(){const cut=Date.now()/1000-600;for(const d of [...list.querySelectorAll('.ch-m')])if(+d.dataset.ts<cut)d.remove()}
 setInterval(expire,15000);
 async function poll(){expire();if(busy||document.hidden)return;busy=true;try{const r=await fetch(`/api/chat/${room}?since=${last}&cid=${cid()}`,{cache:'no-store'});const j=await r.json();
  add(j.messages);if(j.messages.length)last=Math.max(last,...j.messages.map(m=>m.id));
  (j.deleted||[]).forEach(id=>list.querySelector(`[data-id="${id}"]`)?.remove());
  setPin(j.pin);el.querySelector('.n').textContent=j.online;if(opt.onOnline)opt.onOnline(j.online)}catch(e){}busy=false}
 mf.onsubmit=async e=>{e.preventDefault();const inp=mf.querySelector('input'),t=inp.value.trim(),m=me();if(!t||!m)return;
  const b=mf.querySelector('button:not(.ch-mega)');if(mega){sendMega(inp,t,b);return}b.disabled=true;
  try{const r=await fetch(`/api/chat/${room}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nick:m.nick,tag:m.tag,text:t,cid:cid()})});
   const j=await r.json();if(j.ok){if(j.promo&&window.twPromo)twPromo(j.promo);if(j.message.tag!==m.tag){m.tag=j.message.tag;try{localStorage.setItem(LS,JSON.stringify(m))}catch(_){}setMode()}inp.value='';add([j.message]);last=Math.max(last,j.message.id);list.scrollTop=list.scrollHeight}else if(j.code==='guest_limit')guestLimit();else showErr(j.error||'보내지 못했어요.')}
  catch(e){showErr('연결이 불안정해요.')}setTimeout(()=>b.disabled=false,2000)};
 function guestLimit(){mf.style.display='none';nf.style.display='none';el.querySelector('.ch-gl').hidden=false}
 if(opt.close)el.querySelector('.ch-x').onclick=opt.close;
 function start(){active=true;poll();clearInterval(timer);timer=setInterval(poll,2500)}
 function stop(){active=false;clearInterval(timer)}
 if(active)start();
 return {start,stop}}
window.TWChat={mount,cid};
})();
