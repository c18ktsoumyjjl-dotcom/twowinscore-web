/* 히어로 효과(가볍게): 성긴 비, 조명 반짝임, 관중석 플래시, 로고 샤인. 모션 줄이기 설정 존중 */
(function(){
const box=document.querySelector('.fxw');if(!box)return;
const still=matchMedia('(prefers-reduced-motion: reduce)').matches;if(still)return;
const mob=()=>innerWidth<=700;
// 관중석 플래시: 관중석 띠 영역에서 무작위 소수
const crowd=box.querySelector('.fx-crowd');
function flash(){if(document.hidden)return;const d=document.createElement('i');
 let x,y;do{x=3+Math.random()*94;y=(mob()?62:60)+Math.random()*(mob()?22:30)}while(x>28&&x<74&&y<78);
 d.style.left=x+'%';d.style.top=y+'%';d.style.animationDuration=(0.9+Math.random()*1.2)+'s';
 if(Math.random()<.25)d.className='w';crowd.appendChild(d);setTimeout(()=>d.remove(),2400)}
setInterval(()=>{if(Math.random()<.85)flash()},300);
// 조명 반짝임: 이미지에서 자동 검출한 밝은 점(static/lights.json)마다 각자 랜덤 타이밍
let LT=null,lastSet='';
function lights(){if(!LT)return;const k=mob()?'m':'d';if(k===lastSet)return;lastSet=k;box.querySelectorAll('.fx-p').forEach(e=>e.remove());
 for(const [x,y,t] of LT[k]){const e=document.createElement('span');e.className='fx-p '+(t==='L'?'lamp':'spot');e.style.left=x*100+'%';e.style.top=y*100+'%';
  e.style.animationDuration=(3+Math.random()*4).toFixed(2)+'s';e.style.animationDelay=(-Math.random()*7).toFixed(2)+'s';box.appendChild(e)}}
fetch('/static/lights.json?v=1').then(r=>r.json()).then(j=>{LT=j;lights()}).catch(()=>{});addEventListener('resize',lights);
// 비: 캔버스, 성기게
const cv=box.querySelector('.fx-rain'),cx=cv.getContext('2d');let drops=[],W=0,H=0;
function size(){const r=box.getBoundingClientRect(),dp=Math.min(devicePixelRatio||1,2);W=r.width;H=r.height;cv.width=W*dp;cv.height=H*dp;cx.setTransform(dp,0,0,dp,0,0);
 const n=Math.round(W/(mob()?14:18));drops=Array.from({length:n},()=>({x:Math.random()*W,y:Math.random()*H,l:8+Math.random()*12,v:5+Math.random()*4,a:.08+Math.random()*.14}))}
size();addEventListener('resize',size);
function tick(){if(!document.hidden){cx.clearRect(0,0,W,H);cx.lineWidth=1;
 for(const p of drops){cx.strokeStyle=`rgba(200,220,255,${p.a})`;cx.beginPath();cx.moveTo(p.x,p.y);cx.lineTo(p.x-p.l*.18,p.y+p.l);cx.stroke();
  p.y+=p.v;p.x-=p.v*.18;if(p.y>H){p.y=-p.l;p.x=Math.random()*W*1.1}}}
 requestAnimationFrame(tick)}
requestAnimationFrame(tick);
})();
