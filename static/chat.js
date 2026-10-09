/* 투윈스코어 채팅: 가입 없음, 2.5초 폴링 */
(function(){
const LS='tw_nick',CID_K='tw_cid';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function cid(){let c=localStorage.getItem(CID_K);if(!c){c=Array.from(crypto.getRandomValues(new Uint8Array(8)),b=>b.toString(16).padStart(2,'0')).join('');localStorage.setItem(CID_K,c)}return c}
function me(){try{return JSON.parse(localStorage.getItem(LS)||'null')}catch(e){return null}}
function hm(ts){const d=new Date(ts*1000);return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')}
function mount(el,room,opt){
 opt=opt||{};let last=0,timer=null,active=!opt.lazy,busy=false;
 el.classList.add('chat');
 el.innerHTML=`<div class="ch-head"><b>${esc(opt.title||'채팅')}</b><span class="ch-on"><i class="odot"></i><span class="n">-</span>명 접속</span>${opt.close?'<button class="ch-x" aria-label="닫기">✕</button>':''}</div>
 <div class="ch-list" aria-live="polite"><p class="ch-empty">첫 메시지를 남겨 보세요.</p></div>
 <div class="ch-err"></div>
 <form class="ch-nick"><input maxlength="12" placeholder="닉네임 (2~12자)" required><button>입장</button></form>
 <form class="ch-form"><span class="ch-me"></span><input maxlength="200" placeholder="메시지 입력 (200자)" autocomplete="off"><button aria-label="보내기">보내기</button></form>
 <p class="ch-rule">링크·연락처·욕설·홍보는 자동 차단돼요.</p>`;
 const list=el.querySelector('.ch-list'),err=el.querySelector('.ch-err'),nf=el.querySelector('.ch-nick'),mf=el.querySelector('.ch-form');
 const showErr=t=>{err.textContent=t||'';err.style.display=t?'block':'none';if(t)setTimeout(()=>{if(err.textContent===t)showErr('')},4000)};
 function setMode(){const m=me();nf.style.display=m?'none':'flex';mf.style.display=m?'flex':'none';if(m)el.querySelector('.ch-me').innerHTML=`${esc(m.nick)}<small>#${m.tag}</small>`}
 setMode();
 el.querySelector('.ch-me').onclick=()=>{if(confirm('닉네임을 바꿀까요?')){localStorage.removeItem(LS);setMode()}};
 nf.onsubmit=e=>{e.preventDefault();const v=nf.querySelector('input').value.trim();
  if(!/^[0-9A-Za-z가-힣_]{2,12}$/.test(v)){showErr('닉네임은 2~12자 한글·영문·숫자로 해 주세요.');return}
  localStorage.setItem(LS,JSON.stringify({nick:v,tag:String(Math.floor(1000+Math.random()*9000))}));setMode();mf.querySelector('input').focus()};
 function add(ms){if(!ms.length)return;const atBottom=list.scrollHeight-list.scrollTop-list.clientHeight<60;
  list.querySelector('.ch-empty')?.remove();const m0=me();
  for(const m of ms){if(list.querySelector(`[data-id="${m.id}"]`))continue;const mine=m0&&m.nick===m0.nick&&m.tag===m0.tag;
   const d=document.createElement('div');d.className='ch-m'+(mine?' mine':'');d.dataset.id=m.id;
   d.innerHTML=`<span class="ch-n">${esc(m.nick)}<small>#${esc(m.tag)}</small></span><span class="ch-t">${esc(m.text)}</span><time>${hm(m.ts)}</time>`;list.appendChild(d)}
  while(list.children.length>200)list.firstChild.remove();
  if(atBottom||last===0)list.scrollTop=list.scrollHeight}
 async function poll(){if(busy||document.hidden)return;busy=true;try{const r=await fetch(`/api/chat/${room}?since=${last}&cid=${cid()}`,{cache:'no-store'});const j=await r.json();
  add(j.messages);if(j.messages.length)last=Math.max(last,...j.messages.map(m=>m.id));
  (j.deleted||[]).forEach(id=>list.querySelector(`[data-id="${id}"]`)?.remove());
  el.querySelector('.n').textContent=j.online;if(opt.onOnline)opt.onOnline(j.online)}catch(e){}busy=false}
 mf.onsubmit=async e=>{e.preventDefault();const inp=mf.querySelector('input'),t=inp.value.trim(),m=me();if(!t||!m)return;
  const b=mf.querySelector('button');b.disabled=true;
  try{const r=await fetch(`/api/chat/${room}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nick:m.nick,tag:m.tag,text:t,cid:cid()})});
   const j=await r.json();if(j.ok){inp.value='';add([j.message]);last=Math.max(last,j.message.id);list.scrollTop=list.scrollHeight}else showErr(j.error||'보내지 못했어요.')}
  catch(e){showErr('연결이 불안정해요.')}setTimeout(()=>b.disabled=false,2000)};
 if(opt.close)el.querySelector('.ch-x').onclick=opt.close;
 function start(){active=true;poll();clearInterval(timer);timer=setInterval(poll,2500)}
 function stop(){active=false;clearInterval(timer)}
 if(active)start();
 return {start,stop}}
window.TWChat={mount,cid};
})();
