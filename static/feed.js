(function(){const R=document.getElementById('fd');if(!R)return;const D=document,$=i=>D.getElementById(i);
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const H={'X-CSRF':window.TW_CSRF||''},mid=+R.dataset.mid,see=R.dataset.see==='1',rel=R.dataset.rel,MAXN=+R.dataset.maxn||5,MAXC=+R.dataset.maxcap||500;
const api=(u,o)=>fetch(u,Object.assign({credentials:'same-origin',cache:'no-store'},o||{})).then(r=>r.json().catch(()=>({ok:false,error:'요청을 처리할 수 없어요.'})));
const post=(u,b)=>api(u,{method:'POST',headers:Object.assign({'Content-Type':'application/json'},H),body:JSON.stringify(b||{})});
const G=$('fdGrid');let more=false,last=0,loading=false;
function tile(it){if(!see)return `<div class="fd-c lk">${it.img?`<img src="${esc(it.img)}" alt="" loading="lazy">`:'<span class="fd-tt"></span>'}</div>`;
 return `<button type="button" class="fd-c" data-p="${it.id}" aria-label="게시물 보기">${it.img?`<img src="${esc(it.img)}" alt="" loading="lazy">`:`<span class="fd-tt"><span>${esc(it.t)}</span></span>`}${it.n>1?'<i class="fd-mul" aria-hidden="true"><svg viewBox="0 0 24 24" width="18" height="18"><path fill="none" stroke="currentColor" stroke-width="2" d="M8 8h11v11H8zM5 16V5h11"/></svg></i>':''}</button>`}
async function load(reset){if(loading)return;loading=true;const j=await api(`/api/feed/${mid}/posts`+(reset||!last?'':'?before='+last));loading=false;if(!j.ok)return;
 if(reset)G.innerHTML='';G.insertAdjacentHTML('beforeend',j.items.map(tile).join(''));if(j.items.length)last=j.items[j.items.length-1].id;more=j.more;
 if(!see&&!j.items.length)for(let i=0;i<6;i++)G.insertAdjacentHTML('beforeend','<div class="fd-c lk"><span class="fd-tt"></span></div>');
 $('fdEmpty').hidden=!!(G.children.length)}
load(true);
const io='IntersectionObserver' in window?new IntersectionObserver(es=>{if(es[0].isIntersecting&&more)load()}):null;if(io)io.observe($('fdEmpty'));
// 친구추가/수락
R.addEventListener('click',async e=>{const b=e.target.closest('[data-fa]');if(!b)return;b.disabled=true;const j=await post('/api/social/friend',{act:b.dataset.fa,id:mid});
 if(j.ok){if(j.rel==='friend')location.reload();else R.querySelectorAll('[data-fa]').forEach(x=>{x.outerHTML='<span class="fd-b ghost">친구 요청함</span>'})}else{b.disabled=false;alert(j.error||'요청을 처리할 수 없어요.')}});
// 게시물 보기
const V=$('fdView');let cur=null;
function who(w){const lv=w.lv&&/^[0-4]$/.test(String(w.lv[2]))?`<img src="/static/tiers/t${w.lv[2]}_32.webp?v=1" width="18" height="18" alt="">`:'';return `${lv}<b class="${w.vip?'vipn':''}">${esc(w.nick)}</b>${w.vip?'<img src="/static/vip/vip_gem_32.webp?v=1" width="15" height="15" alt="VIP">':''}`}
function car(imgs){if(!imgs.length)return '';return `<div class="fd-sl" tabindex="0">${imgs.map((u,i)=>`<div class="fd-s1"><img src="${esc(u)}" alt="사진 ${i+1}" ${i?'loading="lazy"':''}></div>`).join('')}</div>${imgs.length>1?`<button type="button" class="fd-nav p" aria-label="이전">‹</button><button type="button" class="fd-nav n" aria-label="다음">›</button><div class="fd-dots">${imgs.map((_,i)=>`<i class="${i?'':'on'}"></i>`).join('')}</div>`:''}`}
async function openPost(id,push){const j=await api('/api/feed/post/'+id);if(!j.ok){alert(j.error||'볼 수 없는 게시물이에요.');return}const p=j.p;cur=p;
 const c=$('pvCar');c.innerHTML=car(p.imgs);c.classList.toggle('txt',!p.imgs.length);if(!p.imgs.length)c.innerHTML=`<div class="fd-tbig"><p>${esc(p.body)}</p></div>`;
 $('pvWho').innerHTML=who(p.who);$('pvWho2').innerHTML=who(p.who);
 $('pvCap').innerHTML=p.imgs.length&&p.body?`<p><b>${esc(p.who.nick)}</b> ${esc(p.body)}</p>`:'';
 $('pvLikes').textContent='좋아요 '+p.likes+'개';$('pvLike').classList.toggle('on',p.liked);$('pvAt').textContent=p.ago;$('pvAt').title=p.at;
 $('pvMenu').innerHTML=$('pvMenu2').innerHTML=p.mine?'<button type="button" class="fd-sm" data-pa="del">삭제</button>':'<button type="button" class="fd-sm" data-pa="report">신고</button>';
 V.hidden=false;D.documentElement.classList.add('fd-lockscroll');if(push!==false)history.replaceState(history.state,'',location.pathname+'?p='+id);
 const sl=c.querySelector('.fd-sl');if(sl){const dots=c.querySelectorAll('.fd-dots i');sl.addEventListener('scroll',()=>{const k=Math.round(sl.scrollLeft/sl.clientWidth);dots.forEach((d,i)=>d.classList.toggle('on',i===k))},{passive:true})}}
function closeV(){V.hidden=true;cur=null;D.documentElement.classList.remove('fd-lockscroll');history.replaceState(history.state,'',location.pathname)}
G.addEventListener('click',e=>{const t=e.target.closest('[data-p]');if(t)openPost(+t.dataset.p)});
V.addEventListener('click',async e=>{if(e.target.closest('[data-x]')){closeV();return}
 const nv=e.target.closest('.fd-nav');if(nv){const sl=V.querySelector('.fd-sl');sl.scrollBy({left:(nv.classList.contains('n')?1:-1)*sl.clientWidth,behavior:'smooth'});return}
 if(e.target.closest('#pvLike')&&cur){const j=await post(`/api/feed/post/${cur.id}/like`);if(j.ok){$('pvLike').classList.toggle('on',j.liked);$('pvLikes').textContent='좋아요 '+j.likes+'개'}else alert(j.error||'');return}
 const a=e.target.closest('[data-pa]');if(a&&cur){if(a.dataset.pa==='del'){if(!confirm('이 게시물을 삭제할까요?'))return;const j=await post(`/api/feed/post/${cur.id}/del`);if(j.ok){closeV();location.reload()}else alert(j.error||'')}
  else{const r=prompt('신고 사유를 적어 주세요 (선택)','');if(r===null)return;const j=await post(`/api/feed/post/${cur.id}/report`,{reason:r});alert(j.ok?'신고했어요. 운영자가 확인할게요.':(j.error||''))}}});
D.addEventListener('keydown',function k(e){if(!D.body.contains(R)){D.removeEventListener('keydown',k);return}if(e.key==='Escape'){if(!V.hidden)closeV();if(!U.hidden)closeU()}});
if(+R.dataset.pid&&see)openPost(+R.dataset.pid,false);
// 업로드
const U=$('fdUp'),F=$('upFiles'),P=$('upPrev'),T=$('upText');let files=[];
function closeU(){U.hidden=true;D.documentElement.classList.remove('fd-lockscroll')}
const nb=$('fdNew');if(nb)nb.onclick=()=>{U.hidden=false;D.documentElement.classList.add('fd-lockscroll');$('upErr').textContent=''};
U.addEventListener('click',e=>{if(e.target.closest('[data-x]'))closeU();const r=e.target.closest('[data-rm]');if(r){files.splice(+r.dataset.rm,1);prev()}});
function prev(){P.innerHTML=files.map((f,i)=>`<div class="fd-pi"><img src="${f.u}" alt=""><button type="button" data-rm="${i}" aria-label="빼기">✕</button></div>`).join('');$('upPick').classList.toggle('full',files.length>=MAXN)}
async function shrink(f){if(f.size<=1.5*1024*1024&&/jpe?g|png|webp/i.test(f.type))return f;try{const bm=await createImageBitmap(f);const s=Math.min(1,2048/Math.max(bm.width,bm.height));const cv=D.createElement('canvas');cv.width=Math.round(bm.width*s);cv.height=Math.round(bm.height*s);cv.getContext('2d').drawImage(bm,0,0,cv.width,cv.height);
 const b=await new Promise(r=>cv.toBlob(r,'image/jpeg',.9));return b?new File([b],'p.jpg',{type:'image/jpeg'}):f}catch(e){return f}}
F&&(F.onchange=async()=>{$('upErr').textContent='';for(const f of [...F.files]){if(files.length>=MAXN){$('upErr').textContent=`사진은 ${MAXN}장까지예요.`;break}if(f.size>10*1024*1024){$('upErr').textContent='10MB가 넘는 사진은 뺐어요.';continue}const s=await shrink(f);files.push({f:s,u:URL.createObjectURL(s)})}F.value='';prev()});
T&&(T.oninput=()=>{$('upCnt').textContent=T.value.length+'/'+MAXC});
$('fdForm')&&($('fdForm').onsubmit=async e=>{e.preventDefault();const go=$('upGo');if(!files.length&&!T.value.trim()){$('upErr').textContent='사진이나 글을 넣어 주세요.';return}
 go.disabled=true;go.textContent='올리는 중…';const fd=new FormData();files.forEach(x=>fd.append('img',x.f,'p.'+(x.f.type.split('/')[1]||'jpg')));fd.append('body',T.value);
 const j=await api('/api/feed/post',{method:'POST',headers:H,body:fd});go.disabled=false;go.textContent='올리기';
 if(j.ok){files=[];prev();T.value='';closeU();location.href=location.pathname+'?p='+j.id}else $('upErr').textContent=j.error||'올리지 못했어요.'});
})();
