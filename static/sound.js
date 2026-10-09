/* 득점 알림음 (WebAudio, 파일 없음). 모드: fav(기본)/all/off */
(function(){
let ctx=null;const K='tw_snd';
const mode=()=>localStorage.getItem(K)||'fav';
function ac(){if(!ctx){const C=window.AudioContext||window.webkitAudioContext;if(C)ctx=new C()}return ctx}
function unlock(){const c=ac();if(c&&c.state==='suspended')c.resume().then(hint);hint()}
['pointerdown','keydown','touchstart'].forEach(e=>addEventListener(e,unlock,{passive:true}));
function hint(){const h=document.getElementById('sndHint');if(!h)return;h.hidden=!(mode()!=='off'&&(!ctx||ctx.state!=='running'))}
function play(){if(mode()==='off')return;const c=ac();if(!c||c.state!=='running'){hint();return}
 const t=c.currentTime;[[880,0],[1318.5,.12]].forEach(([f,d])=>{const o=c.createOscillator(),g=c.createGain();o.type='sine';o.frequency.value=f;
  g.gain.setValueAtTime(0,t+d);g.gain.linearRampToValueAtTime(.25,t+d+.02);g.gain.exponentialRampToValueAtTime(.001,t+d+.45);o.connect(g).connect(c.destination);o.start(t+d);o.stop(t+d+.5)})}
const LAB={fav:'🔔 즐겨찾기만',all:'🔔 전체 경기',off:'🔕 알림음 끔'};
function paint(){const b=document.getElementById('sndBtn');if(b){b.textContent=LAB[mode()].split(' ')[0];b.title='알림음: '+LAB[mode()].slice(2);b.setAttribute('aria-label',b.title)}
 const m=document.getElementById('sndMenu');if(m)m.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x.dataset.m===mode()));hint()}
function init(){const b=document.getElementById('sndBtn'),m=document.getElementById('sndMenu');if(!b)return;
 b.onclick=e=>{e.stopPropagation();m.hidden=!m.hidden};
 m.onclick=e=>{const x=e.target.closest('button');if(!x)return;localStorage.setItem(K,x.dataset.m);m.hidden=true;paint();if(x.dataset.m!=='off'){unlock();setTimeout(play,80)}};
 document.addEventListener('click',e=>{if(!e.target.closest('#sndMenu'))m.hidden=true});
 const h=document.getElementById('sndHint');if(h)h.onclick=()=>{unlock();setTimeout(play,80)};paint()}
document.readyState==='loading'?document.addEventListener('DOMContentLoaded',init):init();
window.TWSound={play,mode,want:fav=>mode()==='all'||(mode()==='fav'&&fav)};
})();
