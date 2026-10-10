/* 사이트 BGM: 5곡 순서 재생·반복. 사용자가 🎵 버튼을 눌러야 시작(자동재생 정책). 켬/끔·곡·위치 localStorage 저장 → 페이지 이동 후 이어 재생.
   득점 알림음/입장 효과음과 겹치면 BGM 볼륨을 잠깐 낮춤(덕킹). */
(function(){
if(window.TWBgm)return;
const TR=[1,2,3,4,5].map(n=>'/static/bgm/bgm'+n+'_v1.mp3');
const K='tw_bgm',KS='tw_bgm_st',VOL=.3;
const on=()=>localStorage.getItem(K)==='on';
let st;try{st=JSON.parse(localStorage.getItem(KS))||{}}catch(e){st={}}
let idx=(st.i|0)%TR.length,vol=typeof st.v==='number'?st.v:VOL,duck=1,a=null,btn=null;
function save(){if(!a)return;localStorage.setItem(KS,JSON.stringify({i:idx,t:Math.floor(a.currentTime||0),v:vol}))}
function el(){if(a)return a;a=new Audio();a.preload='none';a.setAttribute('playsinline','');a.volume=vol*duck;
 a.addEventListener('ended',()=>{idx=(idx+1)%TR.length;st.t=0;load(0);a.play().catch(()=>{});save()});
 a.addEventListener('timeupdate',()=>{if(((a.currentTime|0)%3)===0)save()});
 addEventListener('pagehide',save);document.addEventListener('visibilitychange',save);return a}
function load(t){el();a.src=TR[idx];if(t>0){const f=()=>{try{a.currentTime=t}catch(e){}a.removeEventListener('loadedmetadata',f)};a.addEventListener('loadedmetadata',f)}}
function setDuck(d){duck=d;if(a)a.volume=vol*duck}
let dt;function duckFor(ms){setDuck(.25);clearTimeout(dt);dt=setTimeout(()=>setDuck(1),ms)}
function start(){el();if(!a.src)load(st.t|0);const p=a.play();paint();return p?p.catch(()=>{arm()}):Promise.resolve()}
function stop(){if(a){save();a.pause()}paint()}
function toggle(){if(on()){localStorage.setItem(K,'off');stop()}else{localStorage.setItem(K,'on');start()}}
let armed=false;function arm(){if(armed)return;armed=true;const g=e=>{if(e.target.closest&&e.target.closest('#bgmBtn'))return;
 ['click','touchend','keydown'].forEach(v=>removeEventListener(v,g,true));armed=false;if(on()&&(!a||a.paused))start()};
 ['click','touchend','keydown'].forEach(v=>addEventListener(v,g,true))}
function paint(){if(!btn)return;const o=on();btn.classList.toggle('on',o);btn.title=o?'BGM 끄기':'BGM 켜기';btn.setAttribute('aria-pressed',o);btn.setAttribute('aria-label',btn.title)}
function css(){const s=document.createElement('style');s.textContent='#bgmBtn{font-size:15px;line-height:1;opacity:.55;transition:background .15s,opacity .15s}#bgmBtn.on{opacity:1;background:#e8740c!important;border-color:#c9600a!important;color:#fff!important;outline:none;box-shadow:none!important}#bgmBtn:focus{outline:none}#bgmBtn:focus-visible{box-shadow:0 0 0 2px rgba(232,116,12,.45)!important}.mic #bgmBtn.on{background:#e8740c!important}';document.head.appendChild(s)}
function init(){css();const s=document.getElementById('sndBtn');const host=s?(s.closest('.snd')||s):null;
 btn=document.createElement('button');btn.id='bgmBtn';btn.className='theme';btn.type='button';btn.textContent='🎵';
 if(host)host.parentNode.insertBefore(btn,host);else{btn.style.cssText='position:fixed;right:12px;bottom:76px;z-index:900';document.body.appendChild(btn)}
 btn.addEventListener('click',e=>{e.stopPropagation();toggle()});paint();
 // 효과음 연동: 알림음 재생 시 덕킹, 입장 효과음 재생 중엔 낮춤
 const S=window.TWSound;if(S){const p0=S.play;S.play=function(){if(a&&!a.paused)duckFor(2500);return p0.apply(this,arguments)};
  const I=S._a;if(I){I.addEventListener('play',()=>setDuck(.2));['ended','pause'].forEach(v=>I.addEventListener(v,()=>setDuck(1)))}}
 if(on()){start()}}
document.readyState==='loading'?document.addEventListener('DOMContentLoaded',init):init();
window.TWBgm={toggle,on,get idx(){return idx},get el(){return a},setVol:v=>{vol=Math.max(0,Math.min(1,v));if(a)a.volume=vol*duck;save()}};
})();
