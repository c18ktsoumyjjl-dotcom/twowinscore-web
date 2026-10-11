(function(){const R=document.getElementById('soc');if(!R)return;const $=i=>document.getElementById(i);
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const H={'Content-Type':'application/json','X-CSRF':window.TW_CSRF||''};
const api=(u,b)=>fetch(u,b?{method:'POST',headers:H,body:JSON.stringify(b),credentials:'same-origin'}:{credentials:'same-origin',cache:'no-store'}).then(r=>r.json().catch(()=>({ok:false,error:'요청을 처리할 수 없어요.'})));
const lv=c=>(c.lv?`<small class="tnm t${esc(c.lv[2])}" style="color:${/^#[0-9a-f]{3,8}$/i.test(c.lv[1])?c.lv[1]:'inherit'}">${esc(c.lv[0])}</small>`:'')+(c.lv&&/^[0-4]$/.test(String(c.lv[2]))?`<img src="/static/tiers/t${c.lv[2]}_32.webp?v=1" width="16" height="16" alt="">`:'')+(c.vip?'<img src="/static/vip/vip_gem_32.webp?v=1" width="16" height="16" alt="VIP">':'');
const who=c=>`<span class="soc-who">${c.on!=null?`<i class="dot ${c.on?'on':''}"></i>`:''}${lv(c)}<b class="${c.vip?'vipn':''}">${esc(c.nick)}</b></span>`;
const fdl=c=>`<a class="soc-sm" href="/u/${encodeURIComponent(c.nick)}">피드</a>`;
const btn=(t,a,id,cls)=>`<button class="soc-sm ${cls||''}" data-a="${a}" data-id="${id}">${t}</button>`;
let tab=R.dataset.tab||'friends',peer=+R.dataset.peer||0,last=0,timer=0;
function show(t){tab=t;R.querySelectorAll('.soc-tabs button').forEach(b=>b.classList.toggle('on',b.dataset.t===t));R.querySelectorAll('.soc-p').forEach(p=>p.hidden=p.dataset.p!==t||!!peer);$('room').hidden=!peer;
 if(!peer){t==='dm'?loadConv():t==='find'?0:t==='noti'?loadNoti():loadFr()}}
const NX={u:x=>x.k==='dm'?'/friends?t=dm&peer='+x.a:x.k==='cmt'?'/u/'+encodeURIComponent(window.TW_ME||'')+'?p='+(String(x.b).split('|')[0]|0):'/u/'+encodeURIComponent(x.n),
 i:x=>x.k==='dm'?'💬':x.k==='cmt'?'💭':'👋',
 t:x=>x.k==='dm'?`<b>${esc(x.n)}</b> ${esc(x.b)}`:x.k==='cmt'?`<b>${esc(x.n)}</b>님이 회원님의 게시물에 댓글을 남겼어요: ${esc(String(x.b).split('|').slice(1).join('|'))}`:`<b>${esc(x.n)}</b>님이 회원님을 팔로우했어요`};
async function loadNoti(){const j=await api('/api/social/notifs');if(!j.ok)return;
 $('lNoti').innerHTML=j.items.map(x=>`<li class="nt ${x.rd?'':'un'}"><a href="${NX.u(x)}" data-nid="${x.id}"><i>${NX.i(x)}</i><span>${NX.t(x)}</span><small>${new Date(x.ts*1000).toLocaleString('ko-KR',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})}</small></a></li>`).join('')||empty('알림이 없어요.')}
function empty(t){return `<li class="soc-e">${t}</li>`}
const fbtn=c=>c.rel==='friend'?btn('맞팔로우 ✓','unfollow',c.id):c.rel==='sent'?btn('팔로잉 ✓','unfollow',c.id):btn(c.rel==='recv'?'맞팔로우':'팔로우','follow',c.id,'pri');
async function loadFr(){const j=await api('/api/social/friends');if(!j.ok)return;
 $('lFriends').innerHTML=j.following.map(c=>`<li>${who(c)}<span>${fdl(c)}${c.rel==='friend'?btn('대화','dm',c.id,'pri'):''}${fbtn(c)}</span></li>`).join('')||empty('아직 팔로우한 회원이 없어요. 회원검색이나 채팅 닉네임을 눌러 팔로우해 보세요.');
 $('lFollowers').innerHTML=j.followers.map(c=>`<li>${who(c)}<span>${fdl(c)}${fbtn(c)}${btn('삭제','decline',c.id)}</span></li>`).join('')||empty('아직 팔로워가 없어요.');
 $('lBlk').innerHTML=j.blocked.map(c=>`<li>${who(c)}<span>${btn('차단 해제','unblock',c.id)}</span></li>`).join('')||empty('차단한 회원이 없어요.');}
async function loadConv(){const j=await api('/api/social/convs');if(!j.ok)return;
 $('lConv').innerHTML=j.items.map(c=>`<li class="cv" data-a="dm" data-id="${c.id}">${who(c)}<span class="cvl">${c.mine?'나: ':''}${esc(c.last)}</span>${c.unread?`<i class="sb">${c.unread}</i>`:''}</li>`).join('')||empty('대화가 없어요. 맞팔로우한 회원과 \'대화\'를 눌러 시작하세요.');}
const relBtn=c=>(c.rel==='friend'?btn('대화','dm',c.id,'pri'):'')+fbtn(c);
$('fFind').onsubmit=async e=>{e.preventDefault();const v=$('qFind').value.trim();if(!v)return;const j=await api('/api/social/search?q='+encodeURIComponent(v));
 $('lFind').innerHTML=j.ok?(j.items.map(c=>`<li>${who(c)}<span>${fdl(c)}${relBtn(c)}</span></li>`).join('')||empty('검색 결과가 없어요.')):empty(esc(j.error||''))};
R.addEventListener('click',async e=>{const t=e.target.closest('.soc-tabs button');if(t){peer=0;show(t.dataset.t);return}
 const b=e.target.closest('[data-a]');if(!b)return;const a=b.dataset.a,id=+b.dataset.id;
 if(a==='dm'){open(id);return}
 if(a==='report'){if(!confirm('이 메시지를 신고할까요? 관리자가 확인해요.'))return;const j=await api('/api/social/report',{id,reason:'회원 신고'});alert(j.ok?'신고했어요.':(j.error||''));return}
 if(a==='unblock'){await api('/api/social/block',{id,on:0});loadFr();return}
 if((a==='unfollow'||a==='decline')&&!confirm(a==='unfollow'?'팔로우를 취소할까요?':'이 팔로워를 삭제할까요?'))return;
 const j=await api('/api/social/friend',{act:a,id});if(!j.ok)alert(j.error||'');
 if(tab==='find')$('fFind').requestSubmit();else loadFr()});
let PREAD=0,PEER=null;function msgHtml(m,head){return `<div class="dmsg ${m.me?'me':''}" data-mid="${m.id}">${!m.me&&head&&PEER?`<div class="dmhd">${lv(PEER)}<b class="${PEER.vip?'vipn':''}">${esc(PEER.nick)}</b></div>`:''}<div class="dmb">${m.me?`<i class="rd1" ${m.id<=PREAD?'hidden':''}>1</i>`:''}<p>${esc(m.text)}</p></div><small>${new Date(m.ts*1000).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit'})}${m.me?'':` · <a href="#" data-a="report" data-id="${m.id}">신고</a>`}</small></div>`}
async function pull(first){if(!peer)return;const j=await api('/api/social/msgs?peer='+peer+'&after='+last);if(!j.ok){$('rMsgs').innerHTML=`<p class="soc-e">${esc(j.error||'')}</p>`;return}
 $('rPeer').innerHTML=who(j.peer);$('rBlock').dataset.id=j.peer.id;$('rBlock').textContent=j.blocked?'차단 해제':'차단';$('rBlock').dataset.on=j.blocked?0:1;
 const box=$('rMsgs'),atEnd=box.scrollTop+box.clientHeight>=box.scrollHeight-40;if(first)box.innerHTML='';
 PEER=j.peer;PREAD=j.pread||0;j.items.forEach(m=>{if(!box.querySelector(`[data-mid="${m.id}"]`)){const pv=box.lastElementChild;box.insertAdjacentHTML('beforeend',msgHtml(m,!pv||!pv.classList.contains('dmsg')||pv.classList.contains('me')))}last=Math.max(last,m.id)});
 box.querySelectorAll('.dmsg.me').forEach(d=>{const i=d.querySelector('.rd1');if(i)i.hidden=+d.dataset.mid<=PREAD});
 if(first&&!j.items.length)box.innerHTML='<p class="soc-e">첫 메시지를 보내 보세요.</p>';if(first||atEnd)box.scrollTop=box.scrollHeight;
 $('rForm').hidden=j.rel!=='friend'||j.blocked}
function open(id){peer=id;window.TW_DMPEER=id;last=0;show('dm');history.replaceState(history.state,'','/friends?t=dm&peer='+id);pull(true);clearInterval(timer);timer=setInterval(()=>{if(!document.hidden)pull(false)},4000)}
$('rBack').onclick=()=>{peer=0;window.TW_DMPEER=0;clearInterval(timer);history.replaceState(history.state,'','/friends?t=dm');show('dm')};
$('rBlock').onclick=async()=>{const on=$('rBlock').dataset.on==='1';if(on&&!confirm('이 회원을 차단할까요? 서로의 팔로우도 끊어져요.'))return;await api('/api/social/block',{id:+$('rBlock').dataset.id,on:on?1:0});pull(true)};
$('rForm').onsubmit=async e=>{e.preventDefault();const v=$('rText').value.trim();if(!v)return;const j=await api('/api/social/send',{peer,text:v});const er=$('rErr');
 if(j.ok){$('rText').value='';er.hidden=true;const box=$('rMsgs');box.querySelector('.soc-e')?.remove();if(!box.querySelector(`[data-mid="${j.item.id}"]`))box.insertAdjacentHTML('beforeend',msgHtml(j.item,false));last=Math.max(last,j.item.id);box.scrollTop=box.scrollHeight}
 else{er.textContent=j.error||'보낼 수 없어요.';er.hidden=false}};
$('socHide').onchange=e=>api('/api/social/privacy',{hide:e.target.checked?1:0});
async function badges(){const j=await api('/api/social/badge');if(!j.ok)return;$('sbReq').textContent=j.req;$('sbReq').hidden=!j.req;$('sbDm').textContent=j.dm;$('sbDm').hidden=!j.dm;$('sbNt').textContent=j.noti;$('sbNt').hidden=!j.noti}
$('nAll').onclick=async()=>{await api('/api/social/notifs/read',{});loadNoti();badges();window.TWbadge&&TWbadge()};
R.addEventListener('click',e=>{const a=e.target.closest('[data-nid]');if(a)api('/api/social/notifs/read',{id:+a.dataset.nid})},true);
setInterval(()=>{if(!document.hidden){badges();if(!peer&&tab==='dm')loadConv()}},15000);badges();
if(peer)open(peer);else show(tab);if(location.search.includes('t=dm&peer'))0;})();
