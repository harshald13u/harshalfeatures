/* Shared EN/HI language switcher — inserts a control next to the theme toggle on any page.
   Idempotent (skips if a .lang-switch already exists, e.g. the baked homepage one).
   Extend HI_PAGES as more /hi/ pages are built so हिं links to the exact twin (else falls back to /hi/). */
(function(){
  if (document.querySelector('.lang-switch')) return;
  var path = location.pathname || '/';
  var isHi = (path === '/hi' || path.indexOf('/hi/') === 0);
  var HI_PAGES = ['/'];               // EN paths that currently have a Hindi version
  var enPath, hiPath;
  if (isHi) {
    enPath = path.replace(/^\/hi/, '') || '/';
    hiPath = path;
  } else {
    enPath = path;
    hiPath = (HI_PAGES.indexOf(path) !== -1) ? ('/hi' + path) : '/hi/';
  }
  var tog = document.querySelector('.mast-theme-toggle, .theme-toggle, .theme-toggle-btn, button[onclick*="oggleTheme"], button[aria-label*="heme"]');
  if (!tog || !tog.parentNode) return;
  if (!document.getElementById('lang-switch-css')) {
    var st = document.createElement('style'); st.id = 'lang-switch-css';
    st.textContent =
      '.lang-switch{display:inline-flex;align-items:center;gap:1px;border:1px solid var(--rule,rgba(128,128,128,.35));border-radius:999px;padding:2px;margin-right:8px;vertical-align:middle}'+
      '.lang-switch a{font:700 11px/1 "Inter",system-ui,sans-serif;letter-spacing:.4px;color:var(--ink-2,var(--espresso,#8a8a8a));text-decoration:none;padding:4px 7px;border-radius:999px}'+
      '.lang-switch a.lang-on{background:var(--accent,var(--gold,#c69a4a));color:var(--bg,var(--cream,#0e0c0a))}'+
      '.lang-switch a:not(.lang-on):hover{color:var(--accent,var(--gold,#c69a4a))}';
    document.head.appendChild(st);
  }
  var ls = document.createElement('span');
  ls.className = 'lang-switch'; ls.setAttribute('role','group'); ls.setAttribute('aria-label','Language');
  ls.innerHTML =
    '<a href="'+enPath+'"'+(!isHi ? ' class="lang-on" aria-current="true"' : ' hreflang="en" lang="en"')+'>EN</a>'+
    '<a href="'+hiPath+'"'+(isHi ? ' class="lang-on" aria-current="true"' : ' hreflang="hi" lang="hi"')+'>हिं</a>';
  try { ls.querySelectorAll('a').forEach(function(a){ a.addEventListener('click', function(){ try{ localStorage.setItem('hd-lang', this.textContent==='EN'?'en':'hi'); }catch(e){} }); }); } catch(e){}
  tog.parentNode.insertBefore(ls, tog);
})();
