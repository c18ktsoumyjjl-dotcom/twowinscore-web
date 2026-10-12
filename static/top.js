/* 상세 상단: 실제 이벤트가 새로 들어왔을 때만 짧게 연출. 데이터 없으면 조용한 화면 */
(function(){const S=document.querySelector('.tp');if(!S)return;document.body.classList.add('tpon');
const bb=S.querySelector('.tpbb');if(bb){const b=bb.dataset.bases.split(',');['b1','b2','b3'].forEach((id,i)=>{const r=S.querySelector('#'+id);if(r&&b[i]&&b[i]!=='None'&&b[i]!=='False')r.classList.add('on')})}
const wp=S.querySelector('.tpwp');if(wp){const p=JSON.parse(wp.dataset.wp),sv=wp.querySelector('svg');const pt=i=>p.map(x=>`${(x[0]*200).toFixed(1)},${(36-x[i]/100*34-1).toFixed(1)}`).join(' ');
 sv.innerHTML=`<line x1="0" y1="18" x2="200" y2="18" stroke="rgba(128,140,170,.35)" stroke-dasharray="3 3"/><polyline points="${pt(3)}" fill="none" stroke="#5a8cff" stroke-width="1.6" opacity=".8"/><polyline points="${pt(1)}" fill="none" stroke="#ff8a3d" stroke-width="2.2"/>`;
 const l=p[p.length-1];wp.querySelector('.v').textContent=`${l[1]}%${wp.dataset.draw==='1'?' · 무 '+l[2]+'%':''} · ${l[3]}%`}
if(S.dataset.live!=='1')return;const fx=S.querySelector('.tpfx'),st=S.querySelector('.tpst');
const seen=new Set([...S.querySelectorAll('.tptl .e')].map(e=>e.className+e.dataset.m+e.title));let first=true;
const NM={goal:'⚽ 골!',yel:'🟨 경고',red:'🟥 퇴장',sub:'🔁 교체',pen:'⏱ 페널티'};
function show(e){const d=document.createElement('div');d.className='t '+e.t;d.textContent=`${NM[e.t]||''} ${e.lab} ${e.who||''}`.trim();fx.innerHTML='';fx.appendChild(d);if(e.t==='goal'){st.classList.remove('flash');void st.offsetWidth;st.classList.add('flash')}}
async function poll(){if(document.hidden)return;try{const r=await fetch('/api/top/'+encodeURIComponent(S.dataset.k)+location.search,{cache:'no-store'});const j=await r.json();const nw=(j.ev||[]).filter(e=>{const k=e.t+' '+e.s+e.m+(e.lab+' '+e.who);return !seen.has(k)&&seen.add(k)});
 if(!first&&nw.length)show(nw[nw.length-1]);first=false;const sb=S.querySelectorAll('.tpc .sc b');if(sb.length===2&&j.L!=null&&j.R!=null){sb[0].textContent=j.L;sb[1].textContent=j.R;sb[0].className=j.L>j.R?'ld':'';sb[1].className=j.R>j.L?'ld':''}const c=document.getElementById('tpclk');if(c&&j.period)c.textContent=j.period}catch(e){}}
// 초기 마커의 키를 서버 형식과 맞춤
seen.clear();poll();setInterval(poll,20000)})();
