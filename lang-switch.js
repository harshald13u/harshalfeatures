/* GUARANTEE: every page that includes this script shows a dark/light toggle + EN/HI dropdown at the top-right.
   - If the page already has a theme toggle, the dropdown is placed beside it (pushed to the extreme right).
   - If the page has NO toggle, this creates a working one (flips html[data-theme] + persists hd-theme) in a
     fixed top-right cluster alongside the dropdown.
   Idempotent. Extend HI_PAGES as more /hi/ pages are built so HI links to the exact twin (else /hi/ home). */
(function(){
  function injectCSS(){
    if (document.getElementById('lang-dd-css')) return;
    var st=document.createElement('style'); st.id='lang-dd-css';
    st.textContent=
      '.lang-dd{position:relative;display:inline-flex;vertical-align:middle;margin-left:8px;line-height:1}'+
      '.lang-dd *{box-sizing:border-box}'+
      '.lang-dd a::before,.lang-dd a::after{content:none !important;margin:0 !important}'+
      '.lang-dd-btn{display:inline-flex;align-items:center;gap:5px;height:32px;padding:0 12px;border:1px solid var(--accent,var(--gold,#c69a4a));border-radius:999px;background:transparent;color:var(--accent,var(--gold,#c69a4a));font:700 11px/1 "Inter",system-ui,sans-serif;letter-spacing:.8px;text-transform:none;cursor:pointer}'+
      '.lang-dd-btn:hover{background:rgba(198,154,74,.12)}'+
      '.lang-dd-cv{font-size:9px;opacity:.75}'+
      '.lang-dd-menu{position:absolute;top:calc(100% + 6px);right:0;min-width:70px;background:var(--bg-2,var(--cream,#ffffff));border:1px solid var(--rule,rgba(128,128,128,.4));border-radius:10px;padding:5px;box-shadow:0 12px 28px rgba(0,0,0,.22);z-index:1002;display:flex;flex-direction:column;gap:2px}'+
      '.lang-dd-menu[hidden]{display:none}'+
      '.lang-dd-menu a{display:block !important;padding:7px 12px !important;margin:0 !important;border:0 !important;border-radius:7px;background:transparent !important;color:var(--ink,var(--espresso,#222)) !important;text-decoration:none !important;font:700 12px/1 "Inter",system-ui,sans-serif !important;letter-spacing:.6px !important;text-transform:none !important;text-align:left}'+
      '.lang-dd-menu a:hover{background:var(--bg,rgba(128,128,128,.12)) !important;color:var(--accent,var(--gold,#c69a4a)) !important}'+
      '.lang-dd-menu a.on{color:var(--accent,var(--gold,#c69a4a)) !important}'+
      '.hd-mk-toggle{width:32px;height:32px;border-radius:50%;border:1px solid var(--accent,var(--gold,#c69a4a));background:transparent;color:var(--accent,var(--gold,#c69a4a));font-size:14px;line-height:1;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;padding:0;vertical-align:middle}'+
      '.hd-mk-toggle:hover{background:rgba(198,154,74,.12)}';
    document.head.appendChild(st);
  }
  function makeToggle(){
    var b=document.createElement('button'); b.type='button'; b.className='hd-mk-toggle';
    b.setAttribute('aria-label','Toggle light/dark theme'); b.title='Toggle light/dark theme';
    function cur(){ return document.documentElement.getAttribute('data-theme')||'dark'; }
    function paint(){ b.textContent = cur()==='light' ? '☾' : '☀'; }   // ☾ in light, ☀ in dark
    paint();
    b.addEventListener('click', function(){
      var n = cur()==='light' ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', n);
      try{ localStorage.setItem('hd-theme', n); }catch(e){}
      paint();
    });
    return b;
  }
  function makeDropdown(){
    var path = location.pathname || '/';
    var isHi = (path === '/hi' || path.indexOf('/hi/') === 0);
    var HI_PAGES = ['/', '/tools/', '/ipo/', '/fii-dii/', '/tools/oil-impact-estimator/', '/tools/sip-calculator/', '/tools/returns-calculator/', '/tools/capital-gains-tax-calculator/', '/blog/', '/blog/posts/iran-israel-us-war-2026-explained/', '/blog/posts/rbi-mpc-june-2026-rate-pause/', '/blog/posts/crude-oil-india-markets-rupee-inflation/', '/blog/posts/indian-it-stocks-whats-breaking/'];
    var enPath, hiPath;
    if (isHi){ enPath = path.replace(/^\/hi/, '') || '/'; hiPath = path; }
    else { enPath = path; hiPath = (HI_PAGES.indexOf(path) !== -1) ? ('/hi'+path) : '/hi/'; }
    var cur = isHi ? 'HI' : 'EN';
    var dd = document.createElement('div'); dd.className='lang-dd';
    dd.innerHTML =
      '<button class="lang-dd-btn" type="button" aria-haspopup="true" aria-expanded="false" aria-label="Choose language">'+
        '<span>'+cur+'</span><span class="lang-dd-cv" aria-hidden="true">▾</span></button>'+
      '<div class="lang-dd-menu" role="menu" hidden>'+
        '<a role="menuitem" href="'+enPath+'" hreflang="en" lang="en"'+(!isHi?' class="on" aria-current="true"':'')+'>EN</a>'+
        '<a role="menuitem" href="'+hiPath+'" hreflang="hi" lang="hi"'+(isHi?' class="on" aria-current="true"':'')+'>HI</a>'+
      '</div>';
    var btn=dd.querySelector('.lang-dd-btn'), menu=dd.querySelector('.lang-dd-menu');
    function close(){ menu.hidden=true; btn.setAttribute('aria-expanded','false'); }
    function open(){ menu.hidden=false; btn.setAttribute('aria-expanded','true'); }
    btn.addEventListener('click', function(e){ e.stopPropagation(); menu.hidden?open():close(); });
    document.addEventListener('click', function(e){ if(!dd.contains(e.target)) close(); });
    document.addEventListener('keydown', function(e){ if(e.key==='Escape') close(); });
    dd.querySelectorAll('a').forEach(function(a){ a.addEventListener('click', function(){ try{ localStorage.setItem('hd-lang', this.getAttribute('lang')); }catch(e){} }); });
    return dd;
  }
  function build(){
    if (document.querySelector('.lang-dd')) return;
    injectCSS();
    var dd = makeDropdown();
    var tog = document.querySelector('.mast-theme-toggle, .theme-toggle, .theme-toggle-btn, button[onclick*="oggleTheme"], button[aria-label*="heme"]');
    if (tog && tog.parentNode){
      var pos = (window.getComputedStyle(tog).position || '');
      if (pos === 'fixed'){
        var r = tog.getBoundingClientRect();
        dd.style.position='fixed'; dd.style.top=Math.round(r.top+r.height/2)+'px';
        dd.style.transform='translateY(-50%)'; dd.style.right=Math.round(window.innerWidth-r.left+8)+'px';
        dd.style.zIndex='1001'; dd.style.marginLeft='0';
        document.body.appendChild(dd);
      } else {
        var p=tog.parentNode, cluster=document.createElement('span');
        cluster.style.cssText='display:inline-flex;align-items:center;gap:12px;margin-left:18px;vertical-align:middle';
        p.appendChild(cluster); tog.style.margin='0'; dd.style.marginLeft='0';
        cluster.appendChild(tog); cluster.appendChild(dd);
      }
    } else {
      // no theme toggle on this page — create one + dropdown in a fixed top-right cluster
      var corner=document.createElement('div');
      corner.style.cssText='position:fixed;top:14px;right:16px;z-index:1001;display:inline-flex;align-items:center;gap:10px';
      var mk=makeToggle(); dd.style.marginLeft='0';
      corner.appendChild(mk); corner.appendChild(dd);
      document.body.appendChild(corner);
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
  else build();
})();
