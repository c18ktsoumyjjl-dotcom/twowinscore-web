(function(){const R=document.getElementById('dmRight');if(!R)return;const S=document.querySelector('.dmsplit');
const base=location.pathname.replace(/\/dm(\/.*)?$/,'');let cur=null,timer=0;
function toast(t){const b=document.getElementById('toast');if(b){const e=document.createElement('div');e.className='ti';e.textContent=t;b.appendChild(e);setTimeout(()=>e.remove(),3500)}else alert(t)}
async function load(a,b,refresh){const box=R.querySelector('.dmlog'),atEnd=!box||box.scrollTop+box.clientHeight>=box.scrollHeight-40,st=box?box.scrollTop:0;
 const r=await fetch(`${base}/dm/${a}/${b}?part=1${refresh?'&r=1':''}`,{credentials:'same-origin',cache:'no-store'});if(!r.ok){if(!refresh)R.innerHTML='<p class="empty">불러오지 못했어요.</p>';return}
 const h=await r.text();if(cur!==a+'/'+b)return;R.innerHTML=h;const nb=R.querySelector('.dmlog');if(nb)nb.scrollTop=(!refresh||atEnd)?nb.scrollHeight:st}
function open(a,b,auto){cur=a+'/'+b;document.querySelectorAll('.dmrow').forEach(t=>t.classList.toggle('on',t.dataset.a==a&&t.dataset.b==b));if(!auto||!matchMedia('(max-width:900px)').matches)S.classList.add('show');R.innerHTML='<p class="empty">불러오는 중…</p>';load(a,b,false);
 clearInterval(timer);timer=setInterval(()=>{if(!document.hidden&&cur){const[x,y]=cur.split('/');load(x,y,true)}},10000)}
document.addEventListener('click',e=>{if(e.target.closest('.dmrf'))return;const t=e.target.closest('.dmrow,.dmopen');if(t&&!e.target.closest('.dmright')){e.preventDefault();open(t.dataset.a,t.dataset.b);return}
 if(e.target.closest('.dmback')){S.classList.remove('show')}});
R.addEventListener('submit',async e=>{const f=e.target;e.preventDefault();const sel=f.querySelector('select[name=act]');
 const label=sel?sel.options[sel.selectedIndex].text:'메시지 삭제';if(!confirm(label+' — 적용할까요?'))return;
 const r=await fetch(base+'/dm/act',{method:'POST',body:new FormData(f),credentials:'same-origin',headers:{'X-Fetch':'1'}});
 const j=await r.json().catch(()=>null);toast(j&&j.ok?j.msg:'처리하지 못했어요.');if(cur){const[x,y]=cur.split('/');load(x,y,true)}},true);
R.querySelectorAll('form').forEach(f=>f.removeAttribute('onsubmit'));
new MutationObserver(()=>R.querySelectorAll('form[onsubmit]').forEach(f=>f.removeAttribute('onsubmit'))).observe(R,{childList:true,subtree:true});
const first=document.querySelector('.dmrow');if(first)open(first.dataset.a,first.dataset.b,true);})();
