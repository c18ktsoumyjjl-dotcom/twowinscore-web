/* 야구 상세 라이브 필드: 네이버 문자중계(KBO)·MLB 공식. 바뀐 부분만 갱신 */
(function(){
const box=document.getElementById('fd9');if(!box)return;
const $=s=>box.querySelector(s);let built=false,timer=0,last='';
function build(){box.innerHTML=`<div class="fd9g"><div class="fd9cd" id="fdPC"></div><div class="fd9f"><span class="fd9i" id="fdInn"></span>
<svg viewBox="0 0 320 230" class="fd9s" aria-hidden="true"><defs>
<radialGradient id="fdG" cx="50%" cy="85%" r="85%"><stop offset="0" stop-color="#1f3a72"/><stop offset="1" stop-color="#0d1a38"/></radialGradient>
<linearGradient id="fdD" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ff8a3d" stop-opacity=".28"/><stop offset="1" stop-color="#ff8a3d" stop-opacity=".1"/></linearGradient>
<filter id="fdGl" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
<path d="M160 222 L18 80 A200 200 0 0 1 302 80 Z" fill="url(#fdG)" stroke="rgba(255,255,255,.08)"/>
<path d="M160 205 L230 135 L160 65 L90 135 Z" fill="url(#fdD)" stroke="rgba(255,170,110,.35)" stroke-width="1.2"/>
<path d="M160 205 L18 63 M160 205 L302 63" stroke="rgba(255,255,255,.18)" stroke-width="1"/>
<circle cx="160" cy="137" r="9" fill="rgba(255,138,61,.18)" stroke="rgba(255,170,110,.35)"/>
<g class="fdb" id="fdB2"><rect x="152" y="57" width="16" height="16" transform="rotate(45 160 65)"/></g>
<g class="fdb" id="fdB3"><rect x="82" y="127" width="16" height="16" transform="rotate(45 90 135)"/></g>
<g class="fdb" id="fdB1"><rect x="222" y="127" width="16" height="16" transform="rotate(45 230 135)"/></g>
<path d="M152 200 h16 v6 l-8 7 l-8 -7 z" fill="#fff" opacity=".9"/></svg>
<span class="fd9c" id="fdN2" style="left:50%;top:13%"></span><span class="fd9c" id="fdN3" style="left:28%;top:47%"></span><span class="fd9c" id="fdN1" style="left:72%;top:47%"></span>
<span class="fd9brk" id="fdBrk" hidden>공수 교대</span><div id="fdDef"></div></div><div class="fd9cd r" id="fdBC"></div></div>
<div class="fd9k"><span><b>B</b><u></u><u></u><u></u></span><span><b>S</b><u></u><u></u></span><span><b>O</b><u></u><u></u></span></div>
<div class="fd9v"><div class="fd9p" id="fdP"><small></small><b></b><em></em></div><span class="vs">VS</span><div class="fd9p r" id="fdT"><small></small><b></b><em></em></div></div>
<ul class="fd9l" id="fdL"></ul><small class="fd9src" id="fdS"></small>`;built=true}
const tx=(el,v)=>{v=v??'';if(el.textContent!==v)el.textContent=v};
function cnt(span,n,c){[...span.querySelectorAll('u')].forEach((i,k)=>{const on=k<n;if(i.classList.contains(c)!==on)i.classList.toggle(c,on)})}
function person(el,p){el.hidden=!p;if(!p)return;tx(el.querySelector('small'),p.sub);tx(el.querySelector('b'),p.name);tx(el.querySelector('em'),p.line)}
const POS={P:[50,59],C:[50,99],'1B':[71,52],'2B':[61,38],SS:[39,38],'3B':[29,52],LF:[20,22],CF:[50,9],RF:[80,22]};
const SIL='<svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="15" r="7" fill="#3a4f7f"/><path d="M6 38c1-9 7-13 14-13s13 4 14 13z" fill="#3a4f7f"/></svg>';
function card(el,c,role){if(!c){el.hidden=true;el._k='';return}el.hidden=false;const k=JSON.stringify(c);if(el._k===k)return;el._k=k;
 const e=t=>String(t??'').replace(/[&<>"]/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[x]));
 el.innerHTML=`<div class="ph">${c.photo?`<img src="${e(c.photo)}" alt="${e(c.name)}" onerror="this.replaceWith(document.createRange().createContextualFragment(window.TWSIL))">`:SIL}</div>
 <small class="rl">${e(c.sub||role)}</small><b class="nm">${c.no!=null&&c.no!==''?`<em>No.${e(c.no)}</em>`:''}${e(c.name)}</b>${c.hand?`<span class="hd">${e(c.hand)}</span>`:''}
 ${c.season?`<span class="ss">${e(c.season)}</span>`:''}${c.today?`<span class="td">${e(c.today)}</span>`:''}${c.pc!=null&&c.pc!==''?`<span class="pc">투구수 <b>${e(c.pc)}</b></span>`:''}${c.next?`<span class="nx">대기 ${e(c.next)}</span>`:''}`;
 el.classList.remove('chg');void el.offsetWidth;el.classList.add('chg')}
window.TWSIL=SIL;
function defs(list){const d=$('#fdDef');const k=JSON.stringify(list||[]);if(d._k===k)return;d._k=k;
 d.innerHTML=(list||[]).filter(x=>POS[x.pos]).map(x=>`<span class="fd9d" style="left:${POS[x.pos][0]}%;top:${POS[x.pos][1]}%">${String(x.name).replace(/[&<>]/g,'')}</span>`).join('')}
function apply(j){if(!built)build();box.hidden=false;
 tx($('#fdInn'),j.inn);$('#fdBrk').hidden=!j.between;
 [1,2,3].forEach(i=>{const r=j.bases[i-1],g=$('#fdB'+i),c=$('#fdN'+i),on=!!r;if(g.classList.contains('on')!==on)g.classList.toggle('on',on);const nm=typeof r==='string'?r:'';tx(c,nm);c.classList.toggle('on',!!nm)});
 const k=box.querySelectorAll('.fd9k span');cnt(k[0],j.b,'fb');cnt(k[1],j.s,'fs');cnt(k[2],j.o,'fo');
 const hasC=!!(j.pcard||j.bcard);box.classList.toggle('fdx',hasC);
 card($('#fdPC'),j.pcard,'투수');card($('#fdBC'),j.bcard?Object.assign({},j.bcard,j.next?{next:j.next}:{}):null,'타자');defs(j.def);
 $('.fd9v').hidden=hasC;if(!hasC){person($('#fdP'),j.pitcher);person($('#fdT'),j.batter)}
 const L=$('#fdL'),cur=[...L.children].map(li=>li.textContent);if(cur.join('\n')!==(j.plays||[]).join('\n')){const old=new Set(cur);L.innerHTML=(j.plays||[]).map((p,i)=>`<li class="${old.has(p)?'':'nw'}">${p.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}</li>`).join('')}
 tx($('#fdS'),'실시간 · '+j.src)}
async function load(){if(!document.body.contains(box)){clearInterval(timer);return}if(document.hidden)return;
 let j;try{j=await (await fetch('/api/field/'+encodeURIComponent(box.dataset.k)+'?d='+box.dataset.d)).json()}catch(e){return}
 if(!j.ok||!j.live){box.hidden=true;clearInterval(timer);return}const s=JSON.stringify(j);if(s===last)return;last=s;apply(j)}
load();timer=setInterval(load,12000);
})();
