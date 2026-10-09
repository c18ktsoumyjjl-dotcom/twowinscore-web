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
function paint(){const b=document.getElementById('sndBtn');if(b){b.textContent=LAB[mode()].split(' ')[0];b.title='알림음: '+LAB[mode()].slice(2);b.setAttribute('aria-label',b.title)}
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
