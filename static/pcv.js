/* PC(≥1024px) 상세: 모바일 E안 경기장 스트립(.tp)을 점수 헤더 아래로 옮겨 그대로 사용. 모바일 화면은 손대지 않음 */
(function(){const S=document.querySelector('section.tp'),H=document.getElementById('hero');if(!S||!H)return;
const MQ=matchMedia('(min-width:1024px)'),home=document.createComment('tp'),svg=S.querySelector('svg.tpg'),vb0=svg&&svg.getAttribute('viewBox'),bg=svg&&svg.querySelector('rect'),bx=bg&&[bg.getAttribute('x'),bg.getAttribute('width')];S.before(home);
function fit(){if(!svg)return;if(!MQ.matches){svg.setAttribute('viewBox',vb0);if(bx){bx[0]==null?bg.removeAttribute('x'):bg.setAttribute('x',bx[0]);bg.setAttribute('width',bx[1])}return}
 const st=S.querySelector('.tpst'),w=st.clientWidth,h=st.clientHeight;if(!w||!h)return;const vw=Math.max(400,Math.round(146*w/h));svg.setAttribute('viewBox',`${(400-vw)/2} 0 ${vw} 146`);if(bg){bg.setAttribute('x',-1000);bg.setAttribute('width',2400)}}
function place(){if(MQ.matches){S.classList.add('pcv');if(H.nextElementSibling!==S)H.after(S)}else{S.classList.remove('pcv');if(home.nextSibling!==S)home.after(S)}fit()}
place();MQ.addEventListener('change',place);addEventListener('resize',fit)})();
