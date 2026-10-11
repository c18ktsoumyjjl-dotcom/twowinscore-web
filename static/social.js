(function(){const R=document.getElementById('soc');if(!R)return;const $=i=>document.getElementById(i);
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const H={'Content-Type':'application/json','X-CSRF':window.TW_CSRF||''};
const api=(u,b)=>fetch(u,b?{method:'POST',headers:H,body:JSON.stringify(b),credentials:'same-origin'}:{credentials:'same-origin',cache:'no-store'}).then(r=>r.json().catch(()=>({ok:false,error:'요청을 처리할 수 없어요.'})));
const lv=c=>(c.lv&&/^[0-4]$/.test(String(c.lv[2]))?`<img src="/static/tiers/t${c.lv[2]}_32.webp?v=1" width="16" height="16" alt="">`:'')+(c.vip?'<img src="/static/vip/vip_gem_32.webp?v=1" width="16" height="16" alt="VIP">':'');
const who=c=>`<span class="soc-who">${c.on!=null?`<i class="dot ${c.on?'on':''}"></i>`:''}${lv(c)}<b class="${c.vip?'vipn':''}">${esc(c.nick)}</b></span>`;
const btn=(t,a,id,cls)=>`<button class="soc-sm ${cls||''}" data-a="${a}" data-id="${id}">${t}</button>`;
let tab=R.dataset.tab||'friends',peer=+R.dataset.peer||0,last=0,timer=0;
function show(t){tab=t;R.querySelectorAll('.soc-tabs button').forEach(b=>b.classList.toggle('on',b.dataset.t===t));R.querySelectorAll('.soc-p').forEach(p=>p.hidden=p.dataset.p!==t||!!peer);$('room').hidden=!peer;
 if(!peer){t==='dm'?loadConv():t==='find'?0:loadFr()}}
function empty(t){return `<li class="soc-e">${t}</li>`}
async function loadFr(){const j=await api('/api/social/friends');if(!j.ok)return;
 $('lFriends').innerHTML=j.friends.map(c=>`<li>${who(c)}<span>${btn('대화','dm',c.id,'pri')}${btn('삭제','remove',c.id)}</span></li>`).join('')||empty('아직 친구가 없어요. 회원검색이나 채팅 닉네임을 눌러 친구를 추가해 보세요.');
 $('lRecv').innerHTML=j.recv.map(c=>`<li>${who(c)}<span>${btn('수락','accept',c.id,'pri')}${btn('거절','decline',c.id)}</span></li>`).join('')||empty('받은 요청이 없어요.');
 $('lSent').innerHTML=j.sent.map(c=>`<li>${who(c)}<span>${btn('요청 취소','cancel',c.id)}</span></li>`).join('')||empty('보낸 요청이 없어요.');
 $('lBlk').innerHTML=j.blocked.map(c=>`<li>${who(c)}<span>${btn('차단 해제','unblock',c.id)}</span></li>`).join('')||empty('차단한 회원이 없어요.');}
async function loadConv(){const j=await api('/api/social/convs');if(!j.ok)return;
 $('lConv').innerHTML=j.items.map(c=>`<li class="cv" data-a="dm" data-id="${c.id}">${who(c)}<span class="cvl">${c.mine?'나: ':''}${esc(c.last)}</span>${c.unread?`<i class="sb">${c.unread}</i>`:''}</li>`).join('')||empty('대화가 없어요. 친구 목록에서 \'대화\'를 눌러 시작하세요.');}
const relBtn=c=>c.rel==='friend'?btn('대화','dm',c.id,'pri'):c.rel==='sent'?'<em class="mu">요청함</em>':c.rel==='recv'?btn('수락','accept',c.id,'pri'):btn('친구추가','req',c.id,'pri');
$('fFind').onsubmit=async e=>{e.preventDefault();const v=$('qFind').value.trim();if(!v)return;const j=await api('/api/social/search?q='+encodeURIComponent(v));
 $('lFind').innerHTML=j.ok?(j.items.map(c=>`<li>${who(c)}<span>${relBtn(c)}</span></li>`).join('')||empty('검색 결과가 없어요.')):empty(esc(j.error||''))};
R.addEventListener('click',async e=>{const t=e.target.closest('.soc-tabs button');if(t){peer=0;show(t.dataset.t);return}
 const b=e.target.closest('[data-a]');if(!b)return;const a=b.dataset.a,id=+b.dataset.id;
 if(a==='dm'){open(id);return}
 if(a==='report'){if(!confirm('이 메시지를 신고할까요? 관리자가 확인해요.'))return;const j=await api('/api/social/report',{id,reason:'회원 신고'});alert(j.ok?'신고했어요.':(j.error||''));return}
 if(a==='unblock'){await api('/api/social/block',{id,on:0});loadFr();return}
 if((a==='remove'||a==='decline')&&!confirm(a==='remove'?'친구를 삭제할까요?':'요청을 거절할까요?'))return;
 const j=await api('/api/social/friend',{act:a,id});if(!j.ok)alert(j.error||'');
 if(tab==='find')$('fFind').requestSubmit();else loadFr()});
function msgHtml(m){return `<div class="dmsg ${m.me?'me':''}" data-mid="${m.id}"><p>${esc(m.text)}</p><small>${new Date(m.ts*1000).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit'})}${m.me?'':` · <a href="#" data-a="report" data-id="${m.id}">신고</a>`}</small></div>`}
async function pull(first){if(!peer)return;const j=await api('/api/social/msgs?peer='+peer+'&after='+last);if(!j.ok){$('rMsgs').innerHTML=`<p class="soc-e">${esc(j.error||'')}</p>`;return}
 $('rPeer').innerHTML=who(j.peer);$('rBlock').dataset.id=j.peer.id;$('rBlock').textContent=j.blocked?'차단 해제':'차단';$('rBlock').dataset.on=j.blocked?0:1;
 const box=$('rMsgs'),atEnd=box.scrollTop+box.clientHeight>=box.scrollHeight-40;if(first)box.innerHTML='';
 j.items.forEach(m=>{if(!box.querySelector(`[data-mid="${m.id}"]`))box.insertAdjacentHTML('beforeend',msgHtml(m));last=Math.max(last,m.id)});
 if(first&&!j.items.length)box.innerHTML='<p class="soc-e">첫 메시지를 보내 보세요.</p>';if(first||atEnd)box.scrollTop=box.scrollHeight;
 $('rForm').hidden=j.rel!=='friend'||j.blocked}
function open(id){peer=id;last=0;show('dm');history.replaceState(history.state,'','/friends?t=dm&peer='+id);pull(true);clearInterval(timer);timer=setInterval(()=>{if(!document.hidden)pull(false)},4000)}
$('rBack').onclick=()=>{peer=0;clearInterval(timer);history.replaceState(history.state,'','/friends?t=dm');show('dm')};
$('rBlock').onclick=async()=>{const on=$('rBlock').dataset.on==='1';if(on&&!confirm('이 회원을 차단할까요? 친구에서도 삭제돼요.'))return;await api('/api/social/block',{id:+$('rBlock').dataset.id,on:on?1:0});pull(true)};
$('rForm').onsubmit=async e=>{e.preventDefault();const v=$('rText').value.trim();if(!v)return;const j=await api('/api/social/send',{peer,text:v});const er=$('rErr');
 if(j.ok){$('rText').value='';er.hidden=true;const box=$('rMsgs');box.querySelector('.soc-e')?.remove();if(!box.querySelector(`[data-mid="${j.item.id}"]`))box.insertAdjacentHTML('beforeend',msgHtml(j.item));last=Math.max(last,j.item.id);box.scrollTop=box.scrollHeight}
 else{er.textContent=j.error||'보낼 수 없어요.';er.hidden=false}};
$('socHide').onchange=e=>api('/api/social/privacy',{hide:e.target.checked?1:0});
async function badges(){const j=await api('/api/social/badge');if(!j.ok)return;$('sbReq').textContent=j.req;$('sbReq').hidden=!j.req;$('sbDm').textContent=j.dm;$('sbDm').hidden=!j.dm}
setInterval(()=>{if(!document.hidden){badges();if(!peer&&tab==='dm')loadConv()}},15000);badges();
if(peer)open(peer);else show(tab);})();
