/* v1: 모바일 경기 상세 – 상단 고정 점수판 + 전체 높이 채팅 + 하단 입력바 + 응원 */
(function(){
var M=matchMedia('(max-width:1023px)'),b=document.body,R=document.documentElement,top=document.getElementById('gm7');
if(!top)return;
var room=top.dataset.room,mode='chat';
b.classList.add('gm7on');
function list(){return document.querySelector('#gamechat .ch-list')}
function toBottom(){var l=list();if(l)l.scrollTop=l.scrollHeight}
var lastH=-1;function meas(){var h=top.offsetHeight;if(h!==lastH){lastH=h;R.style.setProperty('--mth',h+'px')}}
if(window.ResizeObserver)new ResizeObserver(meas).observe(top);addEventListener('resize',meas);
function setMode(m){mode=m;var chat=m==='chat'&&M.matches;b.classList.toggle('gm7c',chat);
 top.querySelectorAll('#gm7tab button').forEach(function(x){x.classList.toggle('on',x.dataset.m===m)});
 if(chat){scrollTo(0,0);setTimeout(toBottom,0)}
 else if(M.matches){var t=document.getElementById(m==='plays'?'sec-plays':'hero');if(t)scrollTo({top:Math.max(0,t.getBoundingClientRect().top+scrollY-(lastH||0)-8)})}}
document.getElementById('gm7tab').onclick=function(e){var x=e.target.closest('button');if(x)setMode(x.dataset.m)};
M.addEventListener('change',function(){setMode(mode)});
/* 키보드: 바닥에 붙어 있었으면 계속 최신 메시지 보이게 */
var vv=window.visualViewport;if(vv){var wasB=true;vv.addEventListener('resize',function(){if(wasB)setTimeout(toBottom,30)});
 document.addEventListener('scroll',function(){},{passive:true});
 setInterval(function(){var l=list();if(l)wasB=l.scrollHeight-l.scrollTop-l.clientHeight<60},500);
 /* 페이지 점프 방지: 채팅 모드에서 iOS가 문서를 밀어 올리면 되돌림 */
 addEventListener('scroll',function(){if(b.classList.contains('gm7c')&&scrollY!==0)scrollTo(0,0)},{passive:true})}
var esc=function(s){return String(s==null?'':s).replace(/[&<>"']/g,'')};
window.TWGM={mode:setMode,
 score:function(l,r){var a=document.getElementById('mL'),c=document.getElementById('mR');if(a)a.textContent=l==null?'':l;if(c)c.textContent=r==null?'':r},
 badge:function(t){var x=document.getElementById('mB');if(x)x.textContent=esc(t)}};
/* 이닝/쿼터 줄 점수 갱신 (진행 중일 때만, 20초) */
if(top.dataset.live==='1'&&document.getElementById('gm7ls'))setInterval(function(){if(document.hidden||!M.matches)return;
 fetch(location.pathname+location.search,{cache:'no-store'}).then(function(r){return r.text()}).then(function(h){var d=new DOMParser().parseFromString(h,'text/html'),n=d.getElementById('gm7ls'),o=document.getElementById('gm7ls');if(n&&o&&n.innerHTML!==o.innerHTML)o.innerHTML=n.innerHTML}).catch(function(){})},20000);
/* 응원 바 */
var U=function(){return matchMedia('(max-width:1023px)').matches};
function cheer(){var box=document.getElementById('gamechat');if(!box||!room)return;var err=box.querySelector('.ch-err');if(!err||box.querySelector('.gm7ch'))return;
 var nm=top.querySelectorAll('.gm7t b'),lg=top.querySelectorAll('.gm7t img');
 var el=document.createElement('div');el.className='gm7ch';
 el.innerHTML='<button data-s="L" class="L"><span class="nm"></span>응원 <b>0</b></button><button data-s="R" class="R"><b>0</b> 응원<span class="nm"></span></button>';
 el.querySelector('.L .nm').textContent=nm[0]?nm[0].textContent:'';el.querySelector('.R .nm').textContent=nm[1]?nm[1].textContent:'';
 box.insertBefore(el,err);
 var url='/api/cheer/'+encodeURIComponent(room),bL=el.querySelector('.L b'),bR=el.querySelector('.R b');
 var nt=document.createElement('div');nt.className='gm7cn';nt.hidden=true;box.insertBefore(nt,err);
 function show(j){if(j&&typeof j.L==='number'){bL.textContent=j.L.toLocaleString();bR.textContent=j.R.toLocaleString()}
  if(U()){el.classList.remove('off');el.querySelectorAll('button').forEach(function(b){b.disabled=false});
   if(j&&j.mmine&&!window.TWCS){window.TWCS=j.mmine;dispatchEvent(new Event('twcs'))}
   el.querySelectorAll('button').forEach(function(b){b.classList.toggle('on',!!window.TWCS&&b.dataset.s===window.TWCS)});nt.hidden=false;
   if(j&&j.mem===0||!window.TW_ME){nt.hidden=true;var lp=document.querySelector('#gamechat .ch-lgp');if(lp&&j&&j.mem===0&&j!==null&&j.tap){lp.classList.remove('nudge');void lp.offsetWidth;lp.classList.add('nudge')}return}
   nt.textContent=window.TWCS?'메시지를 보낼 때마다 응원 +1 · 3초마다':'응원할 팀을 고른 뒤 응원 메시지를 보내세요';return}
  if(j&&typeof j.left==='number'){var off=j.left<=0;el.classList.toggle('off',off);el.querySelectorAll('button').forEach(function(b){b.disabled=off;b.classList.toggle('on',!!j.mine&&b.dataset.s===j.mine)});nt.hidden=false;nt.textContent=off?'✓ 이미 응원했어요':'경기당 한 번 응원할 수 있어요'}}
 function get(){if(document.hidden||!M.matches)return;fetch(url,{cache:'no-store'}).then(function(r){return r.json()}).then(show).catch(function(){})}
 addEventListener('twcheer',function(ev){var d=ev.detail||{};if(typeof d.L==='number'){bL.textContent=d.L.toLocaleString();bR.textContent=d.R.toLocaleString()}if(d.cd){el.classList.add('cd');nt.textContent=Math.ceil(d.cd)+'초 뒤에 다시 응원할 수 있어요';clearTimeout(el._t);el._t=setTimeout(function(){el.classList.remove('cd');show({})},d.cd*1000)}});
 var busy=false;el.onclick=function(e){var x=e.target.closest('button');if(x&&U()){e.preventDefault();if(window.TW_ME){window.TWCS=x.dataset.s;dispatchEvent(new Event('twcs'));show({})}sheet(x.dataset.s,x.querySelector('.nm').textContent);return}if(!x||busy||x.disabled)return;busy=true;x.classList.remove('pop');void x.offsetWidth;x.classList.add('pop');var u=U();
  fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(u?{side:x.dataset.s,u:1}:{side:x.dataset.s})}).then(function(r){return r.json()}).then(show).catch(function(){}).then(function(){setTimeout(function(){busy=false},u?300:1000)})};
 get();setInterval(get,15000)}
var SH=null;
function sheet(sd,name){if(!SH){SH=document.createElement('div');SH.className='csh';SH.innerHTML='<div class="csh-bg"></div><form class="csh-p" autocomplete="off"><div class="csh-h"><i class="csh-tm"></i><b class="csh-tt"></b><button type="button" class="csh-x" aria-label="닫기">✕</button></div><div class="csh-f"><input maxlength="200" enterkeyhint="send"><button class="csh-s">보내기</button></div><p class="csh-n"></p></form>';document.body.appendChild(SH);
  SH.querySelector('.csh-bg').onclick=closeSheet;SH.querySelector('.csh-x').onclick=closeSheet;SH.querySelector('form').onsubmit=sendSheet;
  if(window.visualViewport){var vv=visualViewport,f=function(){if(!SH.classList.contains('on'))return;SH.querySelector('.csh-p').style.bottom=Math.max(0,innerHeight-vv.height-vv.offsetTop)+'px'};vv.addEventListener('resize',f);vv.addEventListener('scroll',f)}}
 var p=SH.querySelector('.csh-p'),inp=SH.querySelector('input'),n=SH.querySelector('.csh-n');p.dataset.s=sd;n.textContent='';
 SH.querySelector('.csh-tm').textContent=name.trim().split(/\s+/)[0];
 if(window.TW_ME){p.classList.remove('lg');SH.querySelector('.csh-tt').textContent='응원 메시지';inp.placeholder=name.trim()+' 응원 메시지';inp.value='';n.textContent='보낼 때마다 응원 +1 · 3초마다'}
 else{p.classList.add('lg');SH.querySelector('.csh-tt').textContent='응원은 회원만 할 수 있어요';n.innerHTML='<a class="csh-lgb" href="/login?next='+encodeURIComponent(location.pathname+location.search)+'">로그인하고 응원하기</a>'}
 SH.classList.add('on');document.documentElement.classList.add('csh-open');if(window.TW_ME)inp.focus()}
function closeSheet(){if(!SH)return;SH.classList.remove('on');document.documentElement.classList.remove('csh-open');var i=SH.querySelector('input');i.blur();SH.querySelector('.csh-p').style.bottom=''}
function sendSheet(e){e.preventDefault();var inp=SH.querySelector('input'),t=inp.value.trim(),n=SH.querySelector('.csh-n'),b=SH.querySelector('.csh-s');if(!t||!window.TW_ME)return;
 var mf=document.querySelector('#gamechat .ch-form'),ci=mf&&mf.querySelector('input');if(!ci)return;window.TWCS=SH.querySelector('.csh-p').dataset.s;dispatchEvent(new Event('twcs'));
 ci.disabled=false;ci.value=t;b.disabled=true;var done=false,h=function(ev){var d=ev.detail||{};done=true;removeEventListener('twcheer',h);b.disabled=false;if(d.cd){n.textContent=Math.ceil(d.cd)+'초 뒤에 다시 응원할 수 있어요'}else{inp.value='';closeSheet()}};addEventListener('twcheer',h);
 if(mf.requestSubmit)mf.requestSubmit();else mf.dispatchEvent(new Event('submit',{cancelable:true}));
 setTimeout(function(){if(done)return;removeEventListener('twcheer',h);b.disabled=false;var er=document.querySelector('#gamechat .ch-err');n.textContent=(er&&er.textContent)||'보내지 못했어요. 다시 시도해 주세요.'},4000)}
function init(){meas();setMode(M.matches?'chat':'info');cheer()}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else setTimeout(init,0);
})();
