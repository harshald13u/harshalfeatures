/* ============================================================
   Harshal Dasani — Tools: shared helpers (vanilla, no deps)
   Theme persistence (hd-theme), INR formatting, input syncing.
   ============================================================ */
(function () {
  /* ---- theme ---- */
  function applyTheme() {
    try {
      var t = localStorage.getItem('hd-theme');
      if (t === 'light' || t === 'dark') { document.documentElement.setAttribute('data-theme', t); return; }
    } catch (e) {}
    // default to system preference
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      document.documentElement.setAttribute('data-theme', 'dark');
    } else {
      document.documentElement.setAttribute('data-theme', 'light');
    }
  }
  applyTheme();
  window.addEventListener('pageshow', applyTheme);
  window.HDtoggleTheme = function () {
    var cur = document.documentElement.getAttribute('data-theme') || 'light';
    var next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('hd-theme', next); } catch (e) {}
  };
})();

/* ---- number formatting (Indian) ---- */
var _inr = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
function formatINR(n) {
  if (!isFinite(n)) return '—';
  return '₹' + _inr.format(Math.round(n));
}
/* abbreviate to ₹X.XX L / ₹X.XX Cr for big headline numbers */
function formatINRShort(n) {
  if (!isFinite(n)) return '—';
  var a = Math.abs(n), sign = n < 0 ? '−' : '';
  if (a >= 1e7) return sign + '₹' + (a / 1e7).toFixed(2) + ' Cr';
  if (a >= 1e5) return sign + '₹' + (a / 1e5).toFixed(2) + ' L';
  return sign + '₹' + _inr.format(Math.round(a));
}
function formatPct(n, dp) { if (!isFinite(n)) return '—'; return (n).toFixed(dp == null ? 2 : dp) + '%'; }
function escapeHTML(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

/* ---- keep a slider and a number box in sync; calls cb() on change ---- */
function bindInput(sliderId, numId, cb, opts) {
  var s = document.getElementById(sliderId), n = document.getElementById(numId);
  opts = opts || {};
  function clamp(v) {
    if (isNaN(v)) v = parseFloat(s ? s.value : 0) || 0;
    if (opts.min != null && v < opts.min) v = opts.min;
    if (opts.max != null && v > opts.max) v = opts.max;
    return v;
  }
  function fromSlider() { if (n) n.value = s.value; if (cb) cb(); }
  function fromNum() {
    var v = clamp(parseFloat(n.value));
    if (s) { var sv = v; if (opts.max != null) sv = Math.min(sv, +s.max); if (opts.min != null) sv = Math.max(sv, +s.min); s.value = sv; }
    if (cb) cb();
  }
  if (s) s.addEventListener('input', fromSlider);
  if (n) { n.addEventListener('input', cb || function () {}); n.addEventListener('change', fromNum); n.addEventListener('blur', fromNum); }
  return { value: function () { return clamp(parseFloat(n ? n.value : (s ? s.value : 0))); } };
}

/* ---- copy a result string to clipboard, with button feedback ---- */
function copyResult(text, btn) {
  function done() { if (!btn) return; var o = btn.textContent; btn.textContent = 'Copied ✓'; setTimeout(function () { btn.textContent = o; }, 1600); }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done, function () { fallback(); });
  } else { fallback(); }
  function fallback() {
    try { var ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); done(); } catch (e) {}
  }
}

/* ---- simple segmented control: data-seg buttons toggle data-panel sections ---- */
function initSegmented(rootSel) {
  var root = document.querySelector(rootSel); if (!root) return;
  var btns = root.querySelectorAll('[data-seg]');
  btns.forEach(function (b) {
    b.addEventListener('click', function () {
      btns.forEach(function (x) { x.classList.remove('is-active'); });
      b.classList.add('is-active');
      var target = b.getAttribute('data-seg');
      document.querySelectorAll('[data-panel]').forEach(function (p) {
        p.style.display = (p.getAttribute('data-panel') === target) ? '' : 'none';
      });
    });
  });
}
