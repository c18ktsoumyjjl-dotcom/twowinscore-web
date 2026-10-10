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
function cheer(){var box=document.getElementById('gamechat');if(!box||!room)return;var err=box.querySelector('.ch-err');if(!err||box.querySelector('.gm7ch'))return;
 var nm=top.querySelectorAll('.gm7t b'),lg=top.querySelectorAll('.gm7t img');
 var el=document.createElement('div');el.className='gm7ch';
 el.innerHTML='<button data-s="L" class="L"><span class="nm"></span>응원 <b>0</b></button><button data-s="R" class="R"><b>0</b> 응원<span class="nm"></span></button>';
 el.querySelector('.L .nm').textContent=nm[0]?nm[0].textContent:'';el.querySelector('.R .nm').textContent=nm[1]?nm[1].textContent:'';
 box.insertBefore(el,err);
 var url='/api/cheer/'+encodeURIComponent(room),bL=el.querySelector('.L b'),bR=el.querySelector('.R b');
 function show(j){if(j&&typeof j.L==='number'){bL.textContent=j.L.toLocaleString();bR.textContent=j.R.toLocaleString()}}
 function get(){if(document.hidden||!M.matches)return;fetch(url,{cache:'no-store'}).then(function(r){return r.json()}).then(show).catch(function(){})}
 var busy=false;el.onclick=function(e){var x=e.target.closest('button');if(!x||busy)return;busy=true;x.classList.remove('pop');void x.offsetWidth;x.classList.add('pop');
  fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({side:x.dataset.s})}).then(function(r){return r.json()}).then(show).catch(function(){}).then(function(){setTimeout(function(){busy=false},1000)})};
 get();setInterval(get,15000)}
function init(){meas();setMode(M.matches?'chat':'info');cheer()}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else setTimeout(init,0);
})();
