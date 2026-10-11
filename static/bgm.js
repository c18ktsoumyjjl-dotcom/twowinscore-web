/* 사이트 BGM: 5곡 순서 재생·반복. 사용자가 🎵 버튼을 눌러야 시작(자동재생 정책). 켬/끔·곡·위치 localStorage 저장 → 페이지 이동 후 이어 재생.
   득점 알림음/입장 효과음과 겹치면 BGM 볼륨을 잠깐 낮춤(덕킹). */
(function(){
if(window.TWBgm){window.TWBgm.mount&&window.TWBgm.mount();return}
const TR=(Array.isArray(window.TW_BGM)&&window.TW_BGM.length?window.TW_BGM.map(x=>x.u):[1,2,3,4,5].map(n=>'/static/bgm/bgm'+n+'_v1.mp3'));
const K='tw_bgm',KS='tw_bgm_st',VOL=.3;
const on=()=>localStorage.getItem(K)!=='off'; // 기본 켬
let st;try{st=JSON.parse(localStorage.getItem(KS))||{}}catch(e){st={}}
let ctx=null,g=null;const WA=(window.AudioContext||window.webkitAudioContext)&&matchMedia('(pointer:coarse)').matches;
function av(){if(!a)return;const v=vol*duck;if(g){try{g.gain.setTargetAtTime(v,ctx.currentTime,.03)}catch(e){g.gain.value=v}a.volume=1}else a.volume=v}
function wa(){if(!WA||!a)return;try{if(!ctx){const C=window.AudioContext||window.webkitAudioContext;ctx=new C();g=ctx.createGain();ctx.createMediaElementSource(a).connect(g);g.connect(ctx.destination);av()}if(ctx.state!=='running')ctx.resume().catch(()=>{})}catch(e){g=null}}
['pointerdown','touchend','click'].forEach(v=>addEventListener(v,()=>{if(ctx&&ctx.state!=='running')ctx.resume().catch(()=>{})},{capture:true,passive:true}));
let idx=(st.i|0)%TR.length,vol=typeof st.v==='number'?st.v:VOL,duck=1,a=null,btn=null;
function save(){localStorage.setItem(KS,JSON.stringify({i:idx,t:a?Math.floor(a.currentTime||0):(st.t|0),v:vol}))}
function el(){if(a)return a;a=new Audio();a.crossOrigin='anonymous';a.preload='none';a.setAttribute('playsinline','');
 a.addEventListener('ended',()=>{idx=(idx+1)%TR.length;st.t=0;load(0);a.play().catch(()=>{});save();ui()});
 a.addEventListener('timeupdate',()=>{if(((a.currentTime|0)%3)===0)save()});
 addEventListener('pagehide',save);document.addEventListener('visibilitychange',save);return a}
function load(t){el();a.src=TR[idx];if(t>0){const f=()=>{try{a.currentTime=t}catch(e){}a.removeEventListener('loadedmetadata',f)};a.addEventListener('loadedmetadata',f)}}
function setDuck(d){duck=d;av()}
let dt;function duckFor(ms){setDuck(.25);clearTimeout(dt);dt=setTimeout(()=>setDuck(1),ms)}
function start(){el();wa();av();if(!a.src)load(st.t|0);const p=a.play();paint();if(p)p.then(paint,()=>{});return p?p.catch(()=>{arm()}):Promise.resolve()}
function stop(){if(a){save();a.pause()}paint()}
let ui=()=>{};
function setVol(v){vol=Math.round(Math.max(0,Math.min(1,v))*100)/100;av();save();paint();ui()}
function toggle0(){if(on()){localStorage.setItem(K,'off');stop()}else{localStorage.setItem(K,'on');start()}}
function toggle(){if(on()&&a&&a.paused&&!a.ended){start();return}
 if(on()){localStorage.setItem(K,'off');stop()}else{localStorage.setItem(K,'on');start()}}
const EV=['pointerdown','click','touchend','keydown'];let armed=false;function arm(){if(armed)return;armed=true;const g=e=>{if(e.target.closest&&e.target.closest('#bgmBtn'))return;
 EV.forEach(v=>removeEventListener(v,g,true));armed=false;if(on()&&(!a||a.paused))start()};
 EV.forEach(v=>addEventListener(v,g,true))}
const IC=x=>'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>'+(x?'<path d="m2 2 20 20"/>':'')+'</svg>';
function paint(){if(!btn)return;const o=on()&&vol>0;btn.innerHTML=IC(!o);btn.classList.toggle('on',o);btn.title=o?'BGM 끄기':'BGM 켜기';btn.setAttribute('aria-pressed',o);btn.setAttribute('aria-label',btn.title)}
function css(){const s=document.createElement('style');s.textContent='#bgmBtn svg{transition:opacity .15s}#bgmBtn:not(.on) svg{opacity:.5}'+
'#bgmPop{position:fixed;z-index:1001;width:232px;background:#14264f;border:1px solid #22386b;border-radius:14px;padding:12px 14px;box-shadow:0 10px 28px rgba(0,0,0,.45);color:#fff;font-size:13px;user-select:none;-webkit-user-select:none}'+
'#bgmPop[hidden]{display:none}#bgmPop .bh{display:flex;align-items:center;justify-content:space-between;font-weight:700;margin-bottom:12px}'+
'#bgmPop .sw{width:40px;height:22px;border-radius:11px;background:#2a3f72;border:0;position:relative;cursor:pointer;padding:0;transition:background .15s}#bgmPop .sw:after{content:"";position:absolute;top:3px;left:3px;width:16px;height:16px;border-radius:50%;background:#fff;transition:left .15s}#bgmPop .sw.on{background:#f07c15}#bgmPop .sw.on:after{left:21px}'+
'#bgmPop .vr{display:flex;align-items:center;gap:10px}#bgmPop .sl{flex:1;height:26px;position:relative;cursor:pointer;touch-action:none}#bgmPop .tk{position:absolute;left:0;right:0;top:11px;height:4px;border-radius:2px;background:#2a3f72}#bgmPop .fl{position:absolute;left:0;top:11px;height:4px;border-radius:2px;background:#f07c15}'+
'#bgmPop .th{position:absolute;top:5px;width:16px;height:16px;margin-left:-8px;border-radius:50%;background:#f07c15;box-shadow:0 0 0 3px rgba(240,124,21,.25)}#bgmPop .sl:active .th{box-shadow:0 0 0 5px rgba(240,124,21,.3)}#bgmPop .pc{width:38px;text-align:right;color:#a9b8db;font-variant-numeric:tabular-nums}'+
'#bgmPop .tr{display:flex;align-items:center;justify-content:space-between;margin-top:10px;color:#a9b8db;font-size:12px}#bgmPop .nx{background:#1b3166;border:1px solid #22386b;color:#fff;border-radius:8px;padding:4px 10px;font-size:12px;cursor:pointer}#bgmPop .nx:hover{background:#22386b}';document.head.appendChild(s)}
let pop=null,S0=null,openPop=()=>{},closePop=()=>{};
function mount(){const s=document.getElementById('sndBtn');const host=s?(s.closest('.snd')||s):null;
 if(btn&&btn.isConnected)return;btn=document.createElement('button');btn.id='bgmBtn';btn.className='theme';btn.type='button';
 if(host)host.parentNode.insertBefore(btn,host);else{btn.style.cssText='position:fixed;right:12px;bottom:76px;z-index:900';document.body.appendChild(btn)}
 btn.addEventListener('click',e=>{e.stopPropagation();if(on()&&(!a||a.paused))start();pop.hidden?openPop():closePop()});paint();
 if(!pop){pop=document.createElement('div');pop.id='bgmPop';pop.hidden=true;pop.setAttribute('role','dialog');pop.setAttribute('aria-label','BGM 설정');
 pop.innerHTML='<div class="bh"><span>배경음악</span><button class="sw" type="button" role="switch" aria-label="BGM 켜기/끄기"></button></div><div class="vr"><div class="sl" role="slider" tabindex="0" aria-label="볼륨" aria-valuemin="0" aria-valuemax="100"><div class="tk"></div><div class="fl"></div><div class="th"></div></div><span class="pc"></span></div><div class="tr"><span class="tn"></span><button class="nx" type="button">다음 곡 ▶</button></div>';
 }if(!pop.isConnected)document.body.appendChild(pop);if(pop._ok){hook();return}pop._ok=1;const sw=pop.querySelector('.sw'),sl=pop.querySelector('.sl'),fl=pop.querySelector('.fl'),th=pop.querySelector('.th'),pc=pop.querySelector('.pc'),tn=pop.querySelector('.tn');
 ui=()=>{const p=Math.round(vol*100);fl.style.width=p+'%';th.style.left=p+'%';pc.textContent=p+'%';sl.setAttribute('aria-valuenow',p);sw.classList.toggle('on',on());sw.setAttribute('aria-checked',on());tn.textContent=((window.TW_BGM&&TW_BGM[idx]&&TW_BGM[idx].t)?TW_BGM[idx].t+' · ':'')+(idx+1)+' / '+TR.length};
 const place=()=>{const r=btn.getBoundingClientRect(),W=innerWidth,w=232;let l=Math.round(r.left+r.width/2-w/2);l=Math.max(8,Math.min(l,W-w-8));pop.style.top=Math.round(r.bottom+8)+'px';pop.style.left=l+'px'};
 openPop=()=>{ui();pop.hidden=false;place()};closePop=()=>{pop.hidden=true};
 pop.addEventListener('click',e=>e.stopPropagation());pop.addEventListener('pointerdown',e=>e.stopPropagation());
 document.addEventListener('click',()=>closePop());addEventListener('keydown',e=>{if(e.key==='Escape')closePop()});addEventListener('resize',()=>{if(!pop.hidden)place()});addEventListener('scroll',()=>{if(!pop.hidden)place()},{passive:true});
 sw.onclick=()=>{toggle0();ui()};
 pop.querySelector('.nx').onclick=()=>{idx=(idx+1)%TR.length;st.t=0;if(a){load(0);if(on())a.play().catch(()=>{})}save();ui()};
 const setP=x=>{const r=sl.getBoundingClientRect();setVol((x-r.left)/r.width)};
 sl.addEventListener('pointerdown',e=>{e.preventDefault();sl.setPointerCapture(e.pointerId);setP(e.clientX);const mv=ev=>setP(ev.clientX),up=()=>{sl.removeEventListener('pointermove',mv);sl.removeEventListener('pointerup',up);sl.removeEventListener('pointercancel',up)};sl.addEventListener('pointermove',mv);sl.addEventListener('pointerup',up);sl.addEventListener('pointercancel',up)});
 sl.addEventListener('keydown',e=>{const d={ArrowRight:.05,ArrowUp:.05,ArrowLeft:-.05,ArrowDown:-.05}[e.key];if(d){e.preventDefault();setVol(vol+d)}});
 hook()}
function hook(){ // 효과음 연동: 알림음 재생 시 덕킹, 입장 효과음 재생 중엔 낮춤
 const S=window.TWSound;if(S&&S!==S0){S0=S;const p0=S.play;S.play=function(){if(a&&!a.paused)duckFor(2500);return p0.apply(this,arguments)};
  const I=S._a;if(I){I.addEventListener('play',()=>setDuck(.2));['ended','pause'].forEach(v=>I.addEventListener(v,()=>setDuck(1)))}}
}
function init(){css();mount(); if(on()){if(matchMedia('(pointer:coarse)').matches)arm();else if(document.readyState==='complete')setTimeout(start,800);else addEventListener('load',()=>setTimeout(start,800),{once:true})}}  // 첫 화면 다 그린 뒤에만 음악 받기  // 자동재생 시도, 막히면 첫 상호작용에 시작(arm)
document.readyState==='loading'?document.addEventListener('DOMContentLoaded',init):init();
window.TWBgm={mount,toggle,on,get idx(){return idx},get el(){return a},setVol,get vol(){return vol}};
})();
