/* PC 메인 목록(≥1024px): 경기 바를 눌러 펼치면 상세와 같은 경기장 스트립을 바로 아래에 표시. 펼친 경기 하나만 갱신. 모바일 영향 없음 */
(function(){const PC=matchMedia('(min-width:1024px)');const list=document.getElementById('list');if(!list||list.__ls)return;list.__ls=1;
let K=null,box=null,tm=null,kind='',live=false,ct=0,cf=true,cl='',cp=[];const cs=new Set(),cq=[];
function ctick(){const e=box&&box.querySelector('.tpev');if(!e||document.hidden)return;let x=cq.shift();if(!x){const c=cp.filter(y=>y.t&&y.t!==cl);if(!c.length)return;x=c[Math.floor(Math.random()*c.length)]}cl=x.t;e.textContent=x.t;e.classList.toggle('hot',!!x.h);e.classList.remove('nw');void e.offsetWidth;e.classList.add('nw');e.hidden=false}const D=new URLSearchParams(location.search).get('d')||'';
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function fit(){const st=box&&box.querySelector('.tpst'),svg=st&&st.querySelector('svg.tpg');if(!svg||!st.clientWidth)return;const vw=Math.max(400,Math.round(146*st.clientWidth/st.clientHeight));svg.setAttribute('viewBox',`${(400-vw)/2} 0 ${vw} 146`);const bg=svg.querySelector('rect');if(bg){bg.setAttribute('x',-1000);bg.setAttribute('width',2400)}}
function stop(){clearInterval(tm);tm=null;clearInterval(ct);ct=0;cf=true;cl='';cp=[];cq.length=0;cs.clear();K=null;if(box)box.remove();box=null}
async function poll(){if(!box||document.hidden||!live)return;const k=K;try{const j=await (await fetch('/api/top/'+encodeURIComponent(k)+(D?'?d='+D:''),{cache:'no-store'})).json();if(k!==K||!box)return;
 const S=box.querySelector('section.tp');const sb=S.querySelectorAll('.tpc .sc b');if(sb.length===2&&j.L!=null){sb[0].textContent=j.L;sb[1].textContent=j.R;sb[0].className=j.L>j.R?'ld':'';sb[1].className=j.R>j.L?'ld':''}
 const c=S.querySelector('.tpclk,#tpclk');if(c&&j.period)c.textContent=j.period;
 const cx=j.cx||{},ev=Array.isArray(cx.ev)?cx.ev:[],nw=ev.filter(x=>!cs.has(x.k));nw.forEach(x=>cs.add(x.k));if(cf){cf=false;if(ev[0])cq.push(ev[0])}else cq.push(...nw.slice(0,4).reverse());cq.splice(0,Math.max(0,cq.length-4));
 cp=[...(cx.ctx||[]).map(t=>({t,h:0})),...ev.slice(0,3)];if(!cp.length&&Array.isArray(j.pl))cp=j.pl.slice(0,3).map(t=>({t,h:0}));if(!ct||nw.length){clearInterval(ct);ctick();ct=setInterval(ctick,6500)}
 if(Array.isArray(j.ev)&&j.ev.length){const x=j.ev[j.ev.length-1];if(x.t==='goal'||x.t==='pen')S.querySelectorAll('.tph').forEach(h=>h.classList.toggle('on',h.classList.contains(x.t==='goal'?(x.s==='L'?'R':'L'):x.s)))}}catch(err){}}
async function open(k){stop();K=k;box=document.createElement('div');box.className='lsx';box.innerHTML='<p class="lsl">경기장 불러오는 중…</p>';mount();
 try{const j=await (await fetch('/api/strip/'+encodeURIComponent(k)+(D?'?d='+D:''))).json();if(K!==k)return;
  if(!j.html){box.innerHTML='';return}
  box.innerHTML=j.html+`<a class="lsmore" href="${esc(j.url)}">상세보기 ›</a>`;box.querySelectorAll('[id]').forEach(x=>{x.classList.add(x.id);x.removeAttribute('id')});
  kind=j.kind;live=!!j.live;fit();if(live){poll();tm=setInterval(poll,(kind==='football'||kind==='hockey')?8000:5000)}}catch(err){box.innerHTML=''}}
function mount(){const p=list.querySelector('.pv6.open');if(!PC.matches||!p){if(K)stop();return}const k=p.dataset.k;if(k!==K){open(k);return}
 if(box&&box.parentElement!==p){p.prepend(box);fit()}}
new MutationObserver(()=>mount()).observe(list,{childList:true,subtree:true,attributes:true,attributeFilter:['class']});
PC.addEventListener('change',mount);addEventListener('resize',fit);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll()});
window.TWls={mount};mount()})();
