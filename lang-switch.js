/* Shared EN/HI language dropdown — sits at the far right, just after the theme toggle, on every page.
   Idempotent. Extend HI_PAGES as more /hi/ pages are built so हिं links to the exact twin (else /hi/ home). */
(function(){
  if (document.querySelector('.lang-dd')) return;
  function build(){
    if (document.querySelector('.lang-dd')) return;
    var path = location.pathname || '/';
    var isHi = (path === '/hi' || path.indexOf('/hi/') === 0);
    var HI_PAGES = ['/'];                       // EN paths that currently have a Hindi version
    var enPath, hiPath;
    if (isHi){ enPath = path.replace(/^\/hi/, '') || '/'; hiPath = path; }
    else { enPath = path; hiPath = (HI_PAGES.indexOf(path) !== -1) ? ('/hi'+path) : '/hi/'; }
    var tog = document.querySelector('.mast-theme-toggle, .theme-toggle, .theme-toggle-btn, button[onclick*="oggleTheme"], button[aria-label*="heme"]');
    if (!tog || !tog.parentNode) return;

    if (!document.getElementById('lang-dd-css')){
      var st=document.createElement('style'); st.id='lang-dd-css';
      st.textContent=
        '.lang-dd{position:relative;display:inline-flex;vertical-align:middle;margin-left:8px;font-family:"Inter",system-ui,sans-serif}'+
        '.lang-dd-btn{display:inline-flex;align-items:center;gap:4px;height:32px;padding:0 10px;border:1px solid var(--rule,rgba(128,128,128,.4));border-radius:999px;background:transparent;color:var(--ink-2,var(--espresso,#9a9a9a));font:700 11px/1 "Inter",system-ui,sans-serif;letter-spacing:.5px;cursor:pointer}'+
        '.lang-dd-btn:hover{color:var(--accent,var(--gold,#c69a4a));border-color:var(--accent,var(--gold,#c69a4a))}'+
        '.lang-dd-cv{font-size:9px;opacity:.8}'+
        '.lang-dd-menu{position:absolute;top:calc(100% + 6px);right:0;min-width:120px;background:var(--bg-2,var(--cream,#15131f));border:1px solid var(--rule,rgba(128,128,128,.4));border-radius:10px;padding:4px;box-shadow:0 10px 26px rgba(0,0,0,.28);z-index:1002}'+
        '.lang-dd-menu[hidden]{display:none}'+
        '.lang-dd-menu a{display:block;padding:8px 12px;border-radius:7px;color:var(--ink,var(--espresso,#ddd));text-decoration:none;font:600 13px/1.2 "Inter",system-ui,sans-serif;white-space:nowrap}'+
        '.lang-dd-menu a:hover{background:var(--bg,rgba(128,128,128,.12))}'+
        '.lang-dd-menu a.on{color:var(--accent,var(--gold,#c69a4a));font-weight:800}';
      document.head.appendChild(st);
    }

    var cur = isHi ? 'हिं' : 'EN';
    var dd = document.createElement('div'); dd.className='lang-dd';
    dd.innerHTML =
      '<button class="lang-dd-btn" type="button" aria-haspopup="true" aria-expanded="false" aria-label="Choose language">'+
        '<span>'+cur+'</span><span class="lang-dd-cv" aria-hidden="true">▾</span></button>'+
      '<div class="lang-dd-menu" role="menu" hidden>'+
        '<a role="menuitem" href="'+enPath+'" hreflang="en" lang="en"'+(!isHi?' class="on" aria-current="true"':'')+'>English</a>'+
        '<a role="menuitem" href="'+hiPath+'" hreflang="hi" lang="hi"'+(isHi?' class="on" aria-current="true"':'')+'>हिंदी</a>'+
      '</div>';
    var btn = dd.querySelector('.lang-dd-btn'), menu = dd.querySelector('.lang-dd-menu');
    function close(){ menu.hidden=true; btn.setAttribute('aria-expanded','false'); }
    function open(){ menu.hidden=false; btn.setAttribute('aria-expanded','true'); }
    btn.addEventListener('click', function(e){ e.stopPropagation(); menu.hidden ? open() : close(); });
    document.addEventListener('click', function(e){ if(!dd.contains(e.target)) close(); });
    document.addEventListener('keydown', function(e){ if(e.key==='Escape') close(); });
    dd.querySelectorAll('a').forEach(function(a){ a.addEventListener('click', function(){ try{ localStorage.setItem('hd-lang', this.getAttribute('lang')); }catch(e){} }); });

    // Place at far right, beside the theme toggle
    var pos = (window.getComputedStyle(tog).position || '');
    if (pos === 'fixed'){
      var r = tog.getBoundingClientRect();
      dd.style.position='fixed';
      dd.style.top = Math.round(r.top + r.height/2) + 'px';
      dd.style.transform='translateY(-50%)';
      dd.style.right = Math.round(window.innerWidth - r.left + 8) + 'px';
      dd.style.zIndex='1001'; dd.style.marginLeft='0';
      document.body.appendChild(dd);
    } else {
      tog.parentNode.insertBefore(dd, tog.nextSibling);   // immediately right of the toggle
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
  else build();
})();
