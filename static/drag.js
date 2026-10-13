/* 마우스(pointer:fine)용 드래그 스크롤 (모바일 레이아웃 1023px 이하에서만). 터치는 손대지 않음. */
(function(){if(!matchMedia('(pointer:fine)').matches)return;
const SKIP='input,textarea,select,[contenteditable],.nodrag,input[type=range]';
const sc=(el,ax)=>{for(;el&&el!==document.documentElement;el=el.parentElement){if(el.nodeType!==1)continue;const s=getComputedStyle(el);
 if(ax==='x'){if(/(auto|scroll)/.test(s.overflowX)&&el.scrollWidth>el.clientWidth+1)return el}
 else if(/(auto|scroll)/.test(s.overflowY)&&el.scrollHeight>el.clientHeight+1)return el}
 return ax==='y'?document.scrollingElement:null};
let st=null,moved=false;
addEventListener('pointerdown',e=>{moved=false;if(e.pointerType!=='mouse'||!matchMedia('(max-width:1023px)').matches||e.button!==0||e.target.closest(SKIP))return;
 st={x:e.clientX,y:e.clientY,hx:sc(e.target,'x'),vy:sc(e.target,'y'),ax:null,id:e.pointerId};moved=false;
 if(st.hx){st.sl=st.hx.scrollLeft}if(st.vy){st.stp=st.vy.scrollTop}},true);
addEventListener('pointermove',e=>{if(!st||e.pointerId!==st.id)return;const dx=e.clientX-st.x,dy=e.clientY-st.y;
 if(!st.ax){if(Math.abs(dx)<6&&Math.abs(dy)<6)return;st.ax=Math.abs(dx)>Math.abs(dy)&&st.hx?'x':(st.vy?'y':null);if(!st.ax){st=null;return}
  moved=true;document.documentElement.classList.add('tw-drag');getSelection&&getSelection().removeAllRanges()}
 if(st.ax==='x'){st.hx.style.scrollBehavior='auto';st.hx.scrollLeft=st.sl-dx}else{st.vy.scrollTop=st.stp-dy}e.preventDefault()},{passive:false,capture:true});
const end=()=>{if(st&&st.hx)st.hx.style.scrollBehavior='';st=null;document.documentElement.classList.remove('tw-drag')};
addEventListener('pointerup',end,true);addEventListener('pointercancel',end,true);
addEventListener('click',e=>{if(moved){moved=false;e.preventDefault();e.stopPropagation()}},true);
addEventListener('dragstart',e=>{if(st)e.preventDefault()},true);
})();
