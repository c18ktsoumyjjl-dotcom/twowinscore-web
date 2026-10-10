/* v40: 모바일 채팅 바텀시트 (드래그 30/50/85%, 접기 바) */
(function(){
var M=matchMedia('(max-width:1023px)'),b=document.body,R=document.documentElement,SN=[.3,.5,.85],cur=.5,un=0,bar=null,obs=null,lastEl=null;
function el(){return b.classList.contains('chat-open')?document.getElementById('lounge'):b.classList.contains('sheet')?document.getElementById('dchat'):null}
function vh(){return window.visualViewport?visualViewport.height:innerHeight}
function setH(px){R.style.setProperty('--sh',Math.round(px)+'px')}
function apply(){setH(vh()*cur)}
function kb(){var v=window.visualViewport;var k=v?Math.max(0,innerHeight-v.height-v.offsetTop):0;R.style.setProperty('--kb',k+'px');if(M.matches&&el())apply()}
if(window.visualViewport){visualViewport.addEventListener('resize',kb);visualViewport.addEventListener('scroll',kb)}addEventListener('resize',kb);
function mkBar(){if(bar)return;bar=document.createElement('div');bar.className='chbar';bar.innerHTML='<span class="cb-ic">💬</span><span class="cb-t">채팅 열기</span><span class="cb-n"></span><button class="cb-x" aria-label="닫기">✕</button>';
 document.body.appendChild(bar);bar.onclick=function(e){if(e.target.closest('.cb-x')){var x=lastEl&&lastEl.querySelector('.ch-x');b.classList.remove('chmin');x&&x.click();return}expand()}}
function setLast(){if(!bar||!lastEl)return;var ms=lastEl.querySelectorAll('.ch-m'),m=ms[ms.length-1];bar.querySelector('.cb-t').textContent=m?(m.querySelector('.ch-n').textContent+': '+m.querySelector('.ch-t').textContent):'채팅 열기';var n=bar.querySelector('.cb-n');n.textContent=un?(un>99?'99+':un):'';}
function collapse(){b.classList.add('chmin');un=0;setLast()}
function expand(){b.classList.remove('chmin');un=0;cur=.5;apply();setLast()}
function hook(e){if(e===lastEl)return;lastEl=e;mkBar();if(!e.querySelector('.grab')){var g=document.createElement('div');g.className='grab';e.insertBefore(g,e.firstChild)}
 obs&&obs.disconnect();var L=e.querySelector('.ch-list');if(L){obs=new MutationObserver(function(rs){var k=0;rs.forEach(function(r){r.addedNodes.forEach(function(n){if(n.classList&&n.classList.contains('ch-m')&&!n.classList.contains('mine'))k++})});if(b.classList.contains('chmin'))un+=k;setLast()});obs.observe(L,{childList:true})}
 var y0=null,h0=0,moved=false;
 e.addEventListener('touchstart',function(t){if(!M.matches||!t.target.closest('.grab,.ch-head')||t.target.closest('button'))return;y0=t.touches[0].clientY;h0=e.getBoundingClientRect().height;moved=false;e.classList.add('drag')},{passive:true});
 e.addEventListener('touchmove',function(t){if(y0==null)return;var d=t.touches[0].clientY-y0;if(Math.abs(d)>4)moved=true;setH(Math.max(80,Math.min(vh()*.92,h0-d)))},{passive:true});
 function end(t){if(y0==null)return;e.classList.remove('drag');var d=(t.changedTouches?t.changedTouches[0].clientY:y0)-y0;y0=null;var f=(h0-d)/vh();
  if(f<.2){apply();collapse();return}var best=SN[0];SN.forEach(function(s){if(Math.abs(s-f)<Math.abs(best-f))best=s});cur=best;apply()}
 e.addEventListener('touchend',end);e.addEventListener('touchcancel',end)}
function chk(){var e=el();if(e&&M.matches){hook(e);apply()}else{b.classList.remove('chmin');un=0}}
new MutationObserver(chk).observe(b,{attributes:true,attributeFilter:['class']});M.addEventListener('change',chk);chk();
window.TWSheet={collapse:collapse,expand:expand,snap:function(f){cur=f;b.classList.remove('chmin');apply()}};
})();
