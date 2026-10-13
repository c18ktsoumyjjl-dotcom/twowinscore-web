/* 텔레그램 미니앱: 아래로 끌면 앱이 닫히던 것을 막고(disableVerticalSwipes) 당겨서 새로고침. 일반 모바일 브라우저는 기본 동작 유지(음악 재생 중일 때만 커스텀으로 음악 유지). PC 영향 없음 */
(function(){
if(window.__twptr)return;window.__twptr=1;
var W=window,D=document,N=W.__TWN||{},ae=function(t,ty,f,o){(N.ae||EventTarget.prototype.addEventListener).call(t,ty,f,o)};
var M=matchMedia('(max-width:1023px)');
var tgHint=W.TelegramWebviewProxy||/tgWebApp/.test(location.hash)||/tgWebApp/.test((function(){try{return sessionStorage.getItem('tw_tg')||''}catch(e){return ''}})());
function tg(){var t=W.Telegram&&Telegram.WebApp;return t&&(t.initData||t.platform&&t.platform!=='unknown')?t:null}
function setupTg(){var t=tg();if(!t)return;try{t.ready&&t.ready();t.expand&&t.expand();if(t.disableVerticalSwipes&&(!t.isVersionAtLeast||t.isVersionAtLeast('7.7')))t.disableVerticalSwipes()}catch(e){}}
if(W.Telegram&&Telegram.WebApp)setupTg();else if(tgHint){var sc=D.createElement('script');sc.src='https://telegram.org/js/telegram-web-app.js';sc.onload=setupTg;D.head.appendChild(sc)}
var playing=function(){var b=W.TWBgm;return !!(b&&b.el&&!b.el.paused)};
var custom=function(){return M.matches&&(tg()||tgHint||playing())};
/* 일반 브라우저+음악 재생 중: 네이티브 새로고침(음악 끊김) 대신 커스텀 */
(N.si||setInterval)(function(){D.documentElement.style.overscrollBehaviorY=(M.matches&&(tg()||tgHint||playing()))?'contain':''},1500);
var ind=null;function mk(){if(ind)return ind;ind=D.createElement('div');ind.id='twptr';ind.innerHTML='<i></i>';D.documentElement.appendChild(ind);
 var st=D.createElement('style');st.textContent='#twptr{position:fixed;left:50%;top:0;z-index:2147483000;width:36px;height:36px;margin-left:-18px;border-radius:50%;background:#fff;box-shadow:0 2px 10px rgba(0,0,0,.2);display:flex;align-items:center;justify-content:center;transform:translateY(-48px);opacity:0;pointer-events:none;will-change:transform}#twptr i{width:18px;height:18px;border-radius:50%;border:2.5px solid #ff7a1a;border-right-color:transparent;display:block}#twptr.go i{animation:twptr .7s linear infinite}@keyframes twptr{to{transform:rotate(360deg)}}#twptr.back{transition:transform .25s,opacity .25s}';D.head.appendChild(st);return ind}
function scrolledAnc(el){for(;el&&el!==D.body&&el!==D.documentElement;el=el.parentElement){if(el.scrollTop>0){var s=getComputedStyle(el).overflowY;if(s==='auto'||s==='scroll')return true}}return false}
var y0=0,x0=0,on=false,dy=0,busy=false,TH=70;
ae(D,'touchstart',function(e){on=false;if(busy||e.touches.length!==1||!custom())return;if((W.scrollY||D.documentElement.scrollTop)>0)return;
 var t=e.target;if(t.closest&&t.closest('input,textarea,select,[contenteditable],.sheet,.dchat .ch-list'))return;if(scrolledAnc(t))return;
 y0=e.touches[0].clientY;x0=e.touches[0].clientX;dy=0;on=true},{passive:true});
ae(D,'touchmove',function(e){if(!on)return;var y=e.touches[0].clientY-y0,x=e.touches[0].clientX-x0;
 if(dy===0&&(y<=0||Math.abs(x)>Math.abs(y))){on=false;return}
 if((W.scrollY||D.documentElement.scrollTop)>0){on=false;return}
 dy=y;if(e.cancelable)e.preventDefault();var el=mk(),p=Math.min(dy*.5,90);el.classList.remove('back');el.style.opacity=Math.min(1,p/TH);el.style.transform='translateY('+(p-40)+'px) rotate('+(p*4)+'deg)'},{passive:false});
function done(){var el=mk();el.classList.add('back');el.classList.remove('go');el.style.opacity=0;el.style.transform='translateY(-48px)';busy=false}
ae(D,'touchend',function(){if(!on)return;on=false;var el=mk();if(dy*.5<TH){done();return}
 busy=true;el.classList.add('back','go');el.style.opacity=1;el.style.transform='translateY(20px)';
 var fin=function(){(N.st||setTimeout)(done,250)};
 try{if(typeof W.TWload==='function'&&D.body.dataset.page==='home'){Promise.resolve(W.TWload()).then(fin,fin);return}
  if(W.TWnav&&playing()){W.TWnav(location.href);(N.st||setTimeout)(done,1200);return}}catch(e){}
 location.reload()},{passive:true});
ae(D,'touchcancel',function(){if(on){on=false;done()}},{passive:true});
})();
