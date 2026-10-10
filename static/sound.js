/* 소리: 득점 알림음 + 입장 효과음. 휴대폰 호환을 위해 HTMLAudio 사용, 첫 탭(사용자 동작) 안에서 재생/잠금해제.
   모드(tw_snd): fav(기본) | all | off · 입장 효과음(tw_intro): on(기본) | off */
(function(){
const K='tw_snd',IK='tw_intro';
const mode=()=>localStorage.getItem(K)||'fav';
const introOn=()=>localStorage.getItem(IK)!=='off';
const mk=(src,vol)=>{const a=new Audio(src);a.preload='auto';a.volume=vol;a.setAttribute('playsinline','');return a};
const INTRO=mk('/static/intro.mp3?v=4',.6),CHIME=mk('/static/chime.mp3?v=1',.7);
let unlocked=false;
function hint(){const h=document.getElementById('sndHint');if(h)h.hidden=unlocked||mode()==='off'}
function playIntro(force){if(!force&&(sessionStorage.getItem('tw_intro_done')||mode()==='off'||!introOn()))return Promise.resolve();
 try{INTRO.currentTime=0}catch(e){}const p=INTRO.play();return p||Promise.resolve()}
INTRO.addEventListener('timeupdate',()=>{if(INTRO.currentTime>2)sessionStorage.setItem('tw_intro_done','1')});
function prime(){ // 알림음 요소도 사용자 동작 안에서 한 번 깨워 두면 이후 자동 재생 가능
 CHIME.muted=true;const p=CHIME.play();if(p)p.then(()=>{CHIME.pause();CHIME.currentTime=0;CHIME.muted=false}).catch(()=>{CHIME.muted=false})}
function onGesture(e){if(unlocked)return;if(e&&e.target&&e.target.closest&&e.target.closest('#sndBtn,#sndMenu,#sndHint'))return;
 prime();const p=playIntro(false);p.then(()=>{unlocked=true;hint()}).catch(()=>{hint()});unlocked=true;hint()}
['click','touchend','keydown'].forEach(ev=>addEventListener(ev,onGesture,{passive:true}));
function play(){if(mode()==='off')return;try{CHIME.currentTime=0}catch(e){}const p=CHIME.play();if(p)p.catch(()=>{unlocked=false;hint()})}
const LAB={fav:'🔔 즐겨찾기만',all:'🔔 전체 경기',off:'🔕 알림음 끔'};
const BON='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>';
const BOFF='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8.7 3A6 6 0 0 1 18 8a21.3 21.3 0 0 0 .6 5"/><path d="M17 17H3s3-2 3-9a4.67 4.67 0 0 1 .3-1.7"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/><path d="m2 2 20 20"/></svg>';
function paint(){const b=document.getElementById('sndBtn');if(b){b.innerHTML=mode()==='off'?BOFF:BON;b.classList.toggle('off',mode()==='off');b.title='알림음: '+LAB[mode()].slice(2).trim();b.setAttribute('aria-label',b.title)}
 const m=document.getElementById('sndMenu');if(m){m.querySelectorAll('button[data-m]').forEach(x=>x.classList.toggle('on',x.dataset.m===mode()));const ib=m.querySelector('[data-i]');if(ib)ib.textContent=(introOn()?'✅':'⬜')+' 입장 효과음'}hint()}
function test(){prime();unlocked=true;hint();playIntro(true).catch(()=>{unlocked=false;hint()})}
function init(){const b=document.getElementById('sndBtn'),m=document.getElementById('sndMenu');
 const h=document.getElementById('sndHint');if(h){h.textContent='🔊 소리 켜기';h.onclick=e=>{e.stopPropagation();test()}}
 if(b&&m){if(!m.querySelector('[data-i]'))m.insertAdjacentHTML('beforeend','<hr><button data-i="1"></button><button data-t="1">🔊 소리 테스트</button>');
  b.onclick=e=>{e.stopPropagation();m.hidden=!m.hidden};
  m.onclick=e=>{e.stopPropagation();const x=e.target.closest('button');if(!x)return;
   if(x.dataset.t){test();return}
   if(x.dataset.i){localStorage.setItem(IK,introOn()?'off':'on');paint();return}
   localStorage.setItem(K,x.dataset.m);m.hidden=true;paint();if(x.dataset.m!=='off'){prime();unlocked=true;setTimeout(play,60)}};
  document.addEventListener('click',e=>{if(!e.target.closest('#sndMenu'))m.hidden=true})}
 paint()}
document.readyState==='loading'?document.addEventListener('DOMContentLoaded',init):init();
window.TWSound={_a:INTRO,play,mode,test,want:fav=>mode()==='all'||(mode()==='fav'&&fav)};
})();
