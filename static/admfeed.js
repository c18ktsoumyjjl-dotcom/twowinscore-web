(function(){const R=document.getElementById('fdRight');if(!R)return;const S=document.querySelector('.fdsplit');
const base=location.pathname.replace(/\/feed(\/.*)?$/,'');let cur=0;
function toast(t){const b=document.getElementById('toast');if(b){const e=document.createElement('div');e.className='ti';e.textContent=t;b.appendChild(e);setTimeout(()=>e.remove(),3500)}else alert(t)}
async function load(id){const r=await fetch(`${base}/feed/${id}`,{credentials:'same-origin',cache:'no-store'});if(cur!==id)return;R.innerHTML=r.ok?await r.text():'<p class="empty">불러오지 못했어요.</p>'}
function open(id,auto){cur=id;document.querySelectorAll('.fdrow').forEach(t=>t.classList.toggle('on',t.dataset.pid==id));if(!auto||!matchMedia('(max-width:900px)').matches)S.classList.add('show');R.innerHTML='<p class="empty">불러오는 중…</p>';load(id)}
document.addEventListener('click',e=>{const t=e.target.closest('.fdrow');if(t){e.preventDefault();open(t.dataset.pid);return}if(e.target.closest('.dmback'))S.classList.remove('show')});
R.addEventListener('submit',async e=>{const f=e.target;e.preventDefault();const sel=f.querySelector('select[name=act]');const label=sel?sel.options[sel.selectedIndex].text:'댓글 삭제';if(!confirm(label+' — 적용할까요?'))return;
 const r=await fetch(base+'/feed/act',{method:'POST',body:new FormData(f),credentials:'same-origin',headers:{'X-Fetch':'1'}});const j=await r.json().catch(()=>null);toast(j&&j.ok?j.msg:'처리하지 못했어요.');
 if(j&&j.ok&&sel&&sel.value==='del'){const row=document.querySelector(`.fdrow[data-pid="${cur}"]`);if(row){const th=row.querySelector('.fdth');if(th)th.outerHTML='<span class="fdth fdtx">삭제</span>'}}if(cur)load(cur)},true);
const first=document.querySelector('.fdrow');if(first)open(first.dataset.pid,true);})();
