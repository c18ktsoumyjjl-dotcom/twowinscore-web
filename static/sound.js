/* 득점 알림음 (WebAudio, 파일 없음). 모드: fav(기본)/all/off */
(function(){
let ctx=null;const K='tw_snd';
const mode=()=>localStorage.getItem(K)||'fav';
function ac(){if(!ctx){const C=window.AudioContext||window.webkitAudioContext;if(C)ctx=new C()}return ctx}
function unlock(){const c=ac();if(c&&c.state==='suspended')c.resume().then(()=>{hint();intro()});else intro();hint()}
const IK='tw_intro';const introOn=()=>localStorage.getItem(IK)!=='off';
function intro(){try{if(sessionStorage.getItem('tw_intro_done')||mode()==='off'||!introOn())return;const c=ac();if(!c||c.state!=='running')return;
 sessionStorage.setItem('tw_intro_done','1');const t=c.currentTime+.05,out=c.createGain();out.gain.value=.18;out.connect(c.destination);
 // 호루라기: 짧게 '삐' + 길게 '이익' (떨림 있는 고음)
 [[0,.18],[.26,.62]].forEach(([d,len])=>{const o=c.createOscillator(),lfo=c.createOscillator(),lg=c.createGain(),g=c.createGain();
  o.type='sine';o.frequency.value=2900;lfo.frequency.value=38;lg.gain.value=90;lfo.connect(lg).connect(o.frequency);
  g.gain.setValueAtTime(0,t+d);g.gain.linearRampToValueAtTime(.5,t+d+.02);g.gain.setValueAtTime(.5,t+d+len-.06);g.gain.linearRampToValueAtTime(0,t+d+len);
  o.connect(g).connect(out);o.start(t+d);lfo.start(t+d);o.stop(t+d+len+.02);lfo.stop(t+d+len+.02)});
 // 관중 함성: 필터 노이즈, 서서히 커졌다 페이드아웃
 const len=2.6,sr=c.sampleRate,buf=c.createBuffer(2,sr*len,sr);for(let ch=0;ch<2;ch++){const a=buf.getChannelData(ch);for(let i=0;i<a.length;i++)a[i]=Math.random()*2-1}
 const n=c.createBufferSource();n.buffer=buf;const bp=c.createBiquadFilter();bp.type='bandpass';bp.frequency.value=900;bp.Q.value=.6;
 const lp=c.createBiquadFilter();lp.type='lowpass';lp.frequency.value=2600;const g=c.createGain(),s0=t+.8;
 g.gain.setValueAtTime(0,s0);g.gain.linearRampToValueAtTime(.55,s0+.5);g.gain.setValueAtTime(.55,s0+1.1);g.gain.exponentialRampToValueAtTime(.001,s0+len-.05);
 const am=c.createOscillator(),ag=c.createGain();am.frequency.value=5.5;ag.gain.value=.12;am.connect(ag).connect(g.gain);
 n.connect(bp).connect(lp).connect(g).connect(out);n.start(s0);am.start(s0);n.stop(s0+len);am.stop(s0+len)}catch(e){}}
['pointerdown','keydown','touchstart'].forEach(e=>addEventListener(e,unlock,{passive:true}));
function hint(){const h=document.getElementById('sndHint');if(!h)return;h.hidden=!(mode()!=='off'&&(!ctx||ctx.state!=='running'))}
function play(){if(mode()==='off')return;const c=ac();if(!c||c.state!=='running'){hint();return}
 const t=c.currentTime;[[880,0],[1318.5,.12]].forEach(([f,d])=>{const o=c.createOscillator(),g=c.createGain();o.type='sine';o.frequency.value=f;
  g.gain.setValueAtTime(0,t+d);g.gain.linearRampToValueAtTime(.25,t+d+.02);g.gain.exponentialRampToValueAtTime(.001,t+d+.45);o.connect(g).connect(c.destination);o.start(t+d);o.stop(t+d+.5)})}
const LAB={fav:'🔔 즐겨찾기만',all:'🔔 전체 경기',off:'🔕 알림음 끔'};
function paint(){const b=document.getElementById('sndBtn');if(b){b.textContent=LAB[mode()].split(' ')[0];b.title='알림음: '+LAB[mode()].slice(2);b.setAttribute('aria-label',b.title)}
 const m=document.getElementById('sndMenu');if(m){m.querySelectorAll('button[data-m]').forEach(x=>x.classList.toggle('on',x.dataset.m===mode()));const ib=m.querySelector('[data-i]');if(ib)ib.textContent=(introOn()?'✅':'⬜')+' 입장 효과음'}hint()}
function init(){const b=document.getElementById('sndBtn'),m=document.getElementById('sndMenu');if(!b)return;
 b.onclick=e=>{e.stopPropagation();m.hidden=!m.hidden};
 if(!m.querySelector('[data-i]'))m.insertAdjacentHTML('beforeend','<hr><button data-i="1"></button>');
 m.onclick=e=>{const x=e.target.closest('button');if(!x)return;if(x.dataset.i){localStorage.setItem(IK,introOn()?'off':'on');paint();return}localStorage.setItem(K,x.dataset.m);m.hidden=true;paint();if(x.dataset.m!=='off'){unlock();setTimeout(play,80)}};
 document.addEventListener('click',e=>{if(!e.target.closest('#sndMenu'))m.hidden=true});
 const h=document.getElementById('sndHint');if(h)h.onclick=()=>{unlock();setTimeout(play,80)};paint()}
document.readyState==='loading'?document.addEventListener('DOMContentLoaded',init):init();
window.TWSound={play,mode,want:fav=>mode()==='all'||(mode()==='fav'&&fav)};
})();
