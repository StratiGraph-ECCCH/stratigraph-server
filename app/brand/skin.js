/* The reader's skin: set BEFORE the first paint (a classic script in <head>,
   not a module), so nobody sees one look flash into another. The choice lives
   in localStorage under `sg-skin` — a preference, not a secret — and it is the
   same key on every face of this origin: the room browser, the work and tools
   doors, the node console, StratiField. See `skins.css` for what each one is. */
(function () {
  var KEY = "sg-skin";
  var SKINS = ["em", "em-cool", "stratigraph"];
  var NAMES = {
    it: { label: "Aspetto", em: "EM · terra", "em-cool": "EM · chiaro", stratigraph: "StratiGraph" },
    en: { label: "Look", em: "EM · earth", "em-cool": "EM · light", stratigraph: "StratiGraph" }
  };
  function read() {
    var v = null;
    try { v = localStorage.getItem(KEY); } catch (e) {}
    return SKINS.indexOf(v) >= 0 ? v : "em";
  }
  function apply(v) { document.documentElement.setAttribute("data-sg-skin", v); }
  function set(v) {
    if (SKINS.indexOf(v) < 0) return;
    apply(v);
    try { localStorage.setItem(KEY, v); } catch (e) {}
  }
  function mount(select) {
    if (!select || select.dataset.skinMounted) return;
    select.dataset.skinMounted = "1";
    var lang = (document.documentElement.lang || "en").slice(0, 2);
    var n = NAMES[lang] || NAMES.en;
    select.innerHTML = "";
    select.setAttribute("aria-label", n.label);
    select.title = n.label;
    SKINS.forEach(function (s) {
      var o = document.createElement("option");
      o.value = s; o.textContent = n[s];
      if (s === read()) o.selected = true;
      select.appendChild(o);
    });
    select.addEventListener("change", function () { set(select.value); });
  }
  apply(read());
  window.SGSkin = { skins: SKINS, get: read, set: set, mount: mount };
  // the picker is a plain <select id="skin"> in the bar; mounted once the page
  // is parsed, and again after a language change rewrites <html lang>
  document.addEventListener("DOMContentLoaded", function () {
    var el = document.getElementById("skin");
    mount(el);
    new MutationObserver(function () {
      if (el) { delete el.dataset.skinMounted; mount(el); }
    }).observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
  });
})();
