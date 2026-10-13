/* 야구 라인업 박스스코어: 원정(왼쪽) 먼저. 라이브 중 30초 폴링, 바뀐 행만 교체 */
(function(){
const box=document.getElementById('lu9');if(!box)return;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const v=x=>x==null||x===''?'-':esc(x);
const NM={away:'',home:''};
const bat=(b,live)=>`<td class="o">${b.sub?'':b.o}</td><td class="n${b.sub?' lsub':''}">${esc(b.name)}<small>${esc(b.pos)}</small></td><td>${v(b.avg)}</td>`+(live?['ab','r','h','rbi','bb','so','hr'].map(k=>`<td${k==='h'&&b.h>0||k==='hr'&&b.hr>0||k==='rbi'&&b.rbi>0?' class="hi"':''}>${v(b[k])}</td>`).join(''):'');
const pit=p=>`<td class="n">${esc(p.name)}${p.dec?`<small>${esc(p.dec)}</small>`:''}</td>`+['ip','h','r','er','bb','so','np','era'].map(k=>`<td>${v(p[k])}</td>`).join('');
function rows(tb,list,fn){const want=list.map(x=>String(x.id));const cur=[...tb.rows].map(r=>r.dataset.id);
 if(want.join('|')!==cur.join('|')){tb.innerHTML=list.map(x=>`<tr data-id="${esc(x.id)}">${fn(x)}</tr>`).join('');[...tb.rows].forEach(r=>r._h=r.innerHTML);return}
 list.forEach((x,i)=>{const h=fn(x),r=tb.rows[i];const t=document.createElement('tr');t.innerHTML=h;if(r._h!==t.innerHTML){r.innerHTML=h;r._h=r.innerHTML;r.classList.remove('chg');void r.offsetWidth;r.classList.add('chg')}})}
function team(side,t,name,live){let el=box.querySelector('.lu9t[data-s="'+side+'"]');
 if(!el||el.dataset.m!==String(live)){const H=live?'<th>타수</th><th>득점</th><th>안타</th><th>타점</th><th>볼넷</th><th>삼진</th><th>홈런</th>':'';
  el=el||document.createElement('div');el.className='lu9t';el.dataset.s=side;el.dataset.m=String(live);
  el.innerHTML=`<h4>${esc(name)} <small>${side==='away'?'원정':'홈'}</small></h4><div class="lu9w"><table><thead><tr><th class="o">#</th><th class="n">타자</th><th>타율</th>${H}</tr></thead><tbody class="b"></tbody></table></div><div class="lu9w p"><table><thead><tr><th class="n">투수</th><th>이닝</th><th>피안타</th><th>실점</th><th>자책</th><th>볼넷</th><th>삼진</th><th>투구수</th><th>ERA</th></tr></thead><tbody class="p"></tbody></table></div>`}
 rows(el.querySelector('tbody.b'),t.bat,b=>bat(b,live));el.querySelector('.lu9w.p').hidden=!t.pit.length;rows(el.querySelector('tbody.p'),t.pit,pit);return el}
const BC={min:'MIN',pts:'득점',reb:'리바',ast:'어시',to:'턴오버',stl:'스틸',blk:'블록',tpm:'3점'};
const bkrow=(p,cols)=>p.sep?`<td class="o"></td><td class="n sep" colspan="${cols.length+1}">벤치</td>`:`<td class="o">${p.no!=null?esc(p.no):''}</td><td class="n">${esc(p.name)}${p.pos?`<small>${esc(p.pos)}</small>`:''}</td>`+cols.map(k=>`<td${k==='pts'&&p.pts>=10?' class="hi"':''}>${v(p[k])}</td>`).join('');
function bk(j,b,s){const lh=box.dataset.lh==='1';const order=lh?['home','away']:['away','home'];
 if(!b.querySelector('.lu9g'))b.innerHTML='<div class="lu9g"></div>';const g=b.querySelector('.lu9g');
 order.forEach(side=>{const nm=side==='home'?box.dataset.home:box.dataset.away;let el=g.querySelector('.lu9t[data-s="'+side+'"]');const key=j.cols.join(',');
  if(!el||el.dataset.m!==key){el=el||document.createElement('div');el.className='lu9t';el.dataset.s=side;el.dataset.m=key;
   el.innerHTML=`<h4>${esc(nm)} <small>${side==='away'?'원정':'홈'}</small></h4><div class="lu9w"><table><thead><tr><th class="o">#</th><th class="n">주전</th>${j.cols.map(k=>`<th>${BC[k]}</th>`).join('')}</tr></thead><tbody class="b"></tbody></table></div>`;g.appendChild(el)}
  const ps=j[side],st=ps.filter(p=>p.st),bn=ps.filter(p=>!p.st);const list=st.concat(bn.length&&st.length?[{id:'sep',sep:1}]:[],bn);
  rows(el.querySelector('tbody.b'),list,p=>bkrow(p,j.cols))});
 s.textContent=(j.state==='live'?'실시간 · ':'')+j.src;if(j.state!=='live'&&j.state!=='scheduled')clearInterval(timer)}
let timer=0;
async function load(){if(!document.body.contains(box)){clearInterval(timer);return}
 let j;try{j=await (await fetch('/api/lineup/'+encodeURIComponent(box.dataset.k)+'?d='+box.dataset.d)).json()}catch(e){return}
 const b=document.getElementById('lu9b'),s=document.getElementById('lu9s');
 if(!j.ok){b.innerHTML='<p class="lu9e">라인업 정보 없음</p>';s.textContent='';clearInterval(timer);return}
 if(j.kind==='football'){if(j.none){b.innerHTML='<p class="lu9e">공식 라인업 발표 전이에요 (보통 킥오프 약 1시간 전 발표)</p>';s.textContent='';return}
  const lh=box.dataset.lh==='1',order=lh?['home','away']:['away','home'];
  const li=p=>`<tr><td class="o">${p.no!=null?esc(p.no):''}</td><td class="n">${esc(p.name)}${p.pos?`<small>${esc(p.pos)}</small>`:''}</td></tr>`;
  b.innerHTML='<div class="lu9g">'+order.map(sd=>{const t=j[sd],nm=sd==='home'?box.dataset.home:box.dataset.away;
   return `<div class="lu9t"><h4>${esc(nm)} <small>${sd==='away'?'원정':'홈'}${t.form?' · '+esc(t.form):''}</small></h4><div class="lu9w"><table><thead><tr><th class="o">#</th><th class="n">선발 11</th></tr></thead><tbody>${t.xi.map(li).join('')}${t.subs.length?`<tr><td class="o"></td><td class="n sep">교체 명단</td></tr>`+t.subs.map(li).join(''):''}</tbody></table></div>${t.coach?`<p class="lu9e">감독 ${esc(t.coach)}</p>`:''}</div>`}).join('')+'</div>';
  s.textContent=j.src;return}
 if(j.kind==='basketball'){bk(j,b,s);return}
 const pre=j.away.pre&&j.home.pre;
 if(pre&&!j.away.bat.length&&!j.home.bat.length){b.innerHTML='<p class="lu9e">라인업 발표 전</p>';s.textContent=j.src;return}
 if(!b.querySelector('.lu9g')){b.innerHTML='<div class="lu9g"></div>'}
 const g=b.querySelector('.lu9g');
 const nA=box.dataset.away||'원정',nH=box.dataset.home||'홈';
 const ea=team('away',j.away,nA,!j.away.pre),eh=team('home',j.home,nH,!j.home.pre);if(!ea.parentNode)g.appendChild(ea);if(!eh.parentNode)g.appendChild(eh);
 s.textContent=(pre?'발표 라인업 · ':j.state==='live'?'실시간 · ':'')+j.src;
 if(j.state!=='live'&&j.state!=='scheduled'){clearInterval(timer)}}
load();if(box.dataset.live==='1'||box.dataset.pre==='1')timer=setInterval(load,box.dataset.live==='1'?30000:120000);
})();
