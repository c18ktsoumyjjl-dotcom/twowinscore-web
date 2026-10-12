/* 투윈스코어 추가 기능: 추정 승리확률 차트 */
(function(){
const $=s=>document.querySelector(s),E=s=>String(s==null?'':s).replace(/[<>&"']/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c]));
/* ---- 1) 추정 승리확률 ---- */
function wpDraw(w){const box=$('#wp5b'),sec=$('#wp5');if(!box||!w||!w.pts||w.pts.length<2){if(sec)sec.hidden=true;return}
 const L=sec.dataset.l,R=sec.dataset.r,P=w.pts,last=P[P.length-1],W=320,H=96,pad=4;
 const x=p=>pad+p*(W-2*pad),y=v=>pad+(100-v)/100*(H-2*pad);
 const d=P.map((q,i)=>(i?'L':'M')+x(q.p).toFixed(1)+' '+y(q.L).toFixed(1)).join(' ');
 const area=d+` L${x(last.p).toFixed(1)} ${y(0)} L${x(0)} ${y(0)} Z`;
 box.innerHTML=`<div class="wp5n"><span class="l">${E(L)} <b>${last.L}%</b></span>${w.draw?`<span class="c">무 ${last.D}%</span>`:'<span class="c">'+E(last.t)+'</span>'}<span class="r"><b>${last.R}%</b> ${E(R)}</span></div>`+
 `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${E(L)} 추정 승리확률 추이, 현재 ${last.L}%"><line class="ax" x1="${pad}" x2="${W-pad}" y1="${y(0)}" y2="${y(0)}"/><line class="mid" x1="${pad}" x2="${W-pad}" y1="${y(50)}" y2="${y(50)}"/><path class="ar" d="${area}"/><path class="ln" d="${d}" vector-effect="non-scaling-stroke"/><circle class="dt" cx="${x(last.p)}" cy="${y(last.L)}" r="3"/></svg><div class="wp5x"><span>시작</span><span>${w.live?'현재':'종료'}</span></div>`}
const wj=$('#wp5j');if(wj){try{wpDraw(JSON.parse(wj.textContent))}catch(e){}const s=$('#wp5');if(s&&s.dataset.live==='1')setInterval(async()=>{if(document.hidden)return;try{const j=await (await fetch('/api/wp/'+encodeURIComponent(s.dataset.k)+'?d='+s.dataset.d)).json();if(j.ok)wpDraw(j)}catch(e){}},60000)}
})();
