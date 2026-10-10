/* 모바일 앱 화면(<1024px): 헤더 정리, 날짜 띠, 좌우 스와이프로 날짜 이동, 당겨서 새로고침, 서비스워커 등록 */
(function(){
if('serviceWorker' in navigator)addEventListener('load',()=>navigator.serviceWorker.register('/sw.js').catch(()=>{}));
const MQ=matchMedia('(max-width:1023px)'),B=document.body,mh=document.getElementById('mh'),mic=document.getElementById('mic');
if(!mh)return;
const snd=document.getElementById('sndBtn'),sndw=snd&&snd.closest('.snd'),th=document.getElementById('theme'),sports=document.getElementById('sports'),srch=document.querySelector('.search5'),mds=document.getElementById('mds'),msq=document.getElementById('msq');
const home=[];[sndw,th,sports,srch].forEach(n=>{if(n)home.push([n,n.parentNode,n.nextSibling])});
function place(){const m=MQ.matches&&!B.classList.contains('detail6');B.classList.toggle('mapp',m);
 if(m){if(sndw)mic.appendChild(sndw);if(th)mic.appendChild(th);if(mds)mh.appendChild(mds);if(srch){srch.classList.add('msrch');mh.appendChild(srch)}if(sports)mh.appendChild(sports);if(msq)msq.hidden=!srch}
 else home.forEach(([n,p,nx])=>{if(nx&&nx.parentNode===p)p.insertBefore(n,nx);else p.appendChild(n)})}
place();MQ.addEventListener('change',place);
if(msq&&srch)msq.onclick=()=>{const o=B.classList.toggle('msq');const i=srch.querySelector('input');if(o)i.focus();else if(i.value){i.value='';i.dispatchEvent(new Event('input'))}};
/* 날짜 띠 */
let days=[];
if(mds){const p=s=>{const[a,b,c]=s.split('-').map(Number);return new Date(Date.UTC(a,b-1,c))},f=d=>d.toISOString().slice(0,10);
 const cur=mds.dataset.d,td=p(mds.dataset.today),mn=p(mds.dataset.min),mx=p(mds.dataset.max),W='일월화수목금토';
 for(let d=new Date(mn);d<=mx;d=new Date(d.getTime()+864e5))days.push(f(d));
 if(!days.includes(cur))days.push(cur),days.sort();
 mds.innerHTML=days.map(s=>{const d=p(s),df=Math.round((d-td)/864e5),lb=df===0?'오늘':df===-1?'어제':df===1?'내일':W[d.getUTCDay()];
  return `<a href="/?d=${s}" class="${s===cur?'on':''} ${df===0?'td':''}"><small>${lb}</small><b>${String(d.getUTCMonth()+1).padStart(2,'0')}.${String(d.getUTCDate()).padStart(2,'0')}</b></a>`}).join('');
 const on=mds.querySelector('.on');if(on)mds.scrollLeft=on.offsetLeft-(mds.clientWidth-on.offsetWidth)/2;
 /* 목록 좌우 스와이프 → 전날/다음날 */
 const list=document.getElementById('list'),i=days.indexOf(cur);let s0=null;
 list&&list.addEventListener('touchstart',e=>{if(!MQ.matches||e.touches.length>1||e.target.closest('.lsw,table,input'))return s0=null;s0={x:e.touches[0].clientX,y:e.touches[0].clientY,t:Date.now()}},{passive:true});
 list&&list.addEventListener('touchmove',e=>{if(!s0)return;const dx=e.touches[0].clientX-s0.x,dy=e.touches[0].clientY-s0.y;if(Math.abs(dy)>Math.abs(dx)&&Math.abs(dy)>12){s0=null;list.style.transform='';return}if(Math.abs(dx)>12)list.style.transform=`translateX(${dx*.35}px)`},{passive:true});
 list&&list.addEventListener('touchend',e=>{if(!s0)return;const dx=e.changedTouches[0].clientX-s0.x;list.style.transform='';const q=s0;s0=null;
  if(Math.abs(dx)>80&&Date.now()-q.t<800){const n=days[i+(dx<0?1:-1)];if(n){list.classList.add(dx<0?'gol':'gor');location.href='/?d='+n}}},{passive:true});}
/* 당겨서 새로고침 */
const pt=document.getElementById('mptr');let y0=null,pd=0;
addEventListener('touchstart',e=>{if(!MQ.matches||B.classList.contains('detail6')||scrollY>0||e.touches.length>1)return y0=null;y0=e.touches[0].clientY;pd=0},{passive:true});
addEventListener('touchmove',e=>{if(y0==null)return;pd=Math.max(0,Math.min(110,(e.touches[0].clientY-y0)*.5));pt.style.transform=`translate(-50%,${pd-44}px) rotate(${pd*3}deg)`;pt.classList.toggle('rdy',pd>=60)},{passive:true});
addEventListener('touchend',async()=>{if(y0==null)return;y0=null;if(pd>=60){pt.classList.add('spin');pt.style.transform='translate(-50%,18px)';try{if(window.TWload)await window.TWload();else{location.reload();return}}catch(e){}setTimeout(()=>{pt.classList.remove('spin','rdy');pt.style.transform=''},350)}else{pt.style.transform='';pt.classList.remove('rdy')}},{passive:true});
})();
