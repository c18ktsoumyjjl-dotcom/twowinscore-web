/* v1: BGM 재생 중 페이지 이동 시 음악이 끊기지 않도록 본문만 교체(PJAX). 음악이 꺼져 있으면 일반 이동. */
(function(){
if(window.TWnav||!window.history||!window.fetch)return;
const W=window,D=document,N={st:W.setTimeout.bind(W),si:W.setInterval.bind(W),ct:W.clearTimeout.bind(W),ci:W.clearInterval.bind(W),raf:W.requestAnimationFrame&&W.requestAnimationFrame.bind(W),fetch:W.fetch.bind(W),ae:EventTarget.prototype.addEventListener,re:EventTarget.prototype.removeEventListener};
W.__TWN=N;let gen=0;const T=new Set(),I=new Set(),L=[],O=[];
const keep=()=>/bgm\.js/.test(new Error().stack||'');
W.setTimeout=function(f,ms,...a){if(typeof f!=='function'||keep())return N.st(f,ms,...a);const g=gen;const id=N.st(()=>{T.delete(id);if(g===gen)f(...a)},ms);T.add(id);return id};
W.setInterval=function(f,ms,...a){if(typeof f!=='function'||keep())return N.si(f,ms,...a);const g=gen;const id=N.si(()=>{if(g===gen)f(...a)},ms);I.add(id);return id};
if(N.raf)W.requestAnimationFrame=function(f){const g=gen;return N.raf(t=>{if(g===gen)f(t)})};
W.fetch=function(){const g=gen;return N.fetch.apply(W,arguments).then(r=>g===gen?r:new Promise(()=>{}),e=>g===gen?Promise.reject(e):new Promise(()=>{}))};
const tracked=t=>t===W||t===D||t===D.documentElement||t===D.body||(W.MediaQueryList&&t instanceof MediaQueryList)||(W.visualViewport&&t===W.visualViewport);
EventTarget.prototype.addEventListener=function(ty,fn,o){if(tracked(this)&&!keep())L.push([this,ty,fn,o]);return N.ae.call(this,ty,fn,o)};
if(MediaQueryList&&MediaQueryList.prototype.addListener){const al=MediaQueryList.prototype.addListener;MediaQueryList.prototype.addListener=function(fn){L.push([this,'change',fn]);return al.call(this,fn)}}
['MutationObserver','ResizeObserver','IntersectionObserver'].forEach(k=>{const C=W[k];if(!C)return;W[k]=class extends C{constructor(cb,o){super(cb,o);if(!keep())O.push(this)}}});
function cleanup(){gen++;T.forEach(N.ct);I.forEach(N.ci);T.clear();I.clear();L.splice(0).forEach(([t,ty,fn,o])=>{try{N.re.call(t,ty,fn,o)}catch(e){}});O.splice(0).forEach(o=>{try{o.disconnect()}catch(e){}})}
const playing=()=>{const b=W.TWBgm;return !!(b&&b.el&&!b.el.paused)};
const bad=u=>/^\/(admin|logout|login|signup|api|static|media|sw\.js|manifest)/.test(u.pathname)||/\.(png|jpe?g|webp|gif|pdf|mp3|zip|csv|xlsx)$/i.test(u.pathname);
function run(scripts){return scripts.reduce((p,s)=>p.then(()=>new Promise(res=>{const n=D.createElement('script');for(const a of s.attributes)if(a.name!=='defer'&&a.name!=='async')n.setAttribute(a.name,a.value);
 if(s.src){n.onload=n.onerror=()=>res();n.async=false;D.body.appendChild(n)}else{n.textContent='{'+s.textContent+'\n}';try{D.body.appendChild(n)}catch(e){}res()}})),Promise.resolve())}
let busy=false,pend=null;
async function go(url,push,sy){const t=N.st(()=>{location.href=url},5000);try{await go0(url,push,sy)}catch(e){location.href=url}finally{N.ct(t)}}
async function go0(url,push,sy){if(busy){pend=[url,push,sy];return}busy=true;let r,h;try{const ac=new AbortController();N.st(()=>ac.abort(),5000);r=await N.fetch(url,{signal:ac.signal,credentials:'same-origin',headers:{'X-TW-Nav':'1'}});h=await r.text()}catch(e){location.href=url;return}
 if(!r.ok||!/text\/html/.test(r.headers.get('content-type')||'')||new URL(r.url).origin!==location.origin){location.href=url;return}
 const nd=new DOMParser().parseFromString(h,'text/html');if(!nd.body||nd.querySelector('body.adm')){location.href=url;return}
 const V=d=>{const m={};d.querySelectorAll('link[rel=stylesheet][href^="/static/"],script[src^="/static/"]').forEach(x=>{const u=(x.getAttribute('href')||x.getAttribute('src')).split('?');m[u[0]]=u[1]||''});return m};{const a=V(nd),c=V(document);if(Object.keys(a).some(k=>k in c&&c[k]!==a[k])){location.href=url;return}}
 if(push){history.replaceState(Object.assign({},history.state,{tw:1,y:scrollY}),'');history.pushState({tw:1,y:0},'',r.url)}
 cleanup();
 D.title=nd.title;['description','theme-color','robots'].forEach(k=>{const a=D.querySelector('meta[name="'+k+'"]'),b=nd.querySelector('meta[name="'+k+'"]');if(a&&b&&k!=='theme-color')a.content=b.content});
 nd.head.querySelectorAll('link[rel=stylesheet]').forEach(l=>{if(!D.head.querySelector('link[href="'+l.getAttribute('href')+'"]'))D.head.appendChild(l.cloneNode())});D.head.querySelectorAll('style[data-tw-page]').forEach(s=>s.remove());nd.head.querySelectorAll('style').forEach(s=>{const n=s.cloneNode(true);n.setAttribute('data-tw-page','1');D.head.appendChild(n)});
 const nb=nd.body,sc=[...nb.querySelectorAll('script')];sc.forEach(s=>s.remove());
 const keepEl=[...D.body.children].filter(e=>e.id==='bgmPop');
 for(const a of [...D.body.attributes])D.body.removeAttribute(a.name);for(const a of nb.attributes)D.body.setAttribute(a.name,a.value);
 D.body.replaceChildren(...nb.childNodes);keepEl.forEach(e=>D.body.appendChild(e));
 scrollTo(0,sy||0);
 const first=sc.filter(s=>!s.defer),late=sc.filter(s=>s.defer);
 await run(first);await run(late);
 D.dispatchEvent(new Event('DOMContentLoaded'));if(W.TWBgm&&W.TWBgm.mount)W.TWBgm.mount();
 if(sy)N.st(()=>scrollTo(0,sy),60);busy=false;if(pend){const q=pend;pend=null;go(...q)}}
N.ae.call(D,'click',e=>{if(e.defaultPrevented||e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;const a=e.target.closest&&e.target.closest('a[href]');if(!a||a.target&&a.target!=='_self'||a.hasAttribute('download'))return;
 const u=new URL(a.href,location.href);if(u.origin!==location.origin||bad(u)||(u.pathname===location.pathname&&u.search===location.search&&u.hash))return;if(!playing())return;e.preventDefault();go(u.href,true)});
N.ae.call(W,'popstate',e=>{if(e.state&&e.state.tw&&playing())go(location.href,false,e.state.y||0);else if(e.state&&e.state.tw)location.reload()});
history.replaceState(Object.assign({},history.state,{tw:1}),'');
W.TWnav=u=>{const x=new URL(u,location.href);if(playing()&&x.origin===location.origin&&!bad(x))go(x.href,true);else location.href=u};
})();
