/* i18n.js — foundation for rolling the EN/HI switcher to more pages.
   Pages set <html lang>. Mark nodes with data-i18n="key"; this swaps text from /i18n/<lang>.json.
   (The homepage ships fully baked HI at /hi/index.html; this is for future pages.) */
(function(){
  var lang=(document.documentElement.lang||'en').slice(0,2);
  if(lang!=='hi') return;
  fetch('/i18n/hi.json').then(function(r){return r.json()}).then(function(d){
    document.querySelectorAll('[data-i18n]').forEach(function(el){
      var k=el.getAttribute('data-i18n'); if(d[k]) el.textContent=d[k];
    });
  }).catch(function(){});
})();