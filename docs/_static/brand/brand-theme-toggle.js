/* ══════════════════════════════════════════════════════════════════════════
   L'interruttore delle due facce, per i manuali.

   Il marchio ha già una faccia chiara e una scura, e senza scelta esplicita
   segue l'impostazione di sistema di chi legge: è il comportamento giusto di
   default, perché la luce della stanza la conosce il lettore e non noi.
   Questo bottone serve a chi vuole decidere lo stesso — in trincea sotto il
   sole, o la sera con lo schermo troppo bianco.

   Tre stati in cerchio: chiaro → scuro → come il sistema. La scelta vive nel
   browser di chi legge (localStorage), quindi vale per tutti i manuali serviti
   dallo stesso dominio e non lascia traccia da nessun'altra parte.
   ══════════════════════════════════════════════════════════════════════════ */
(function () {
  var KEY = "sg-theme";
  var root = document.documentElement;

  function read() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function write(v) {
    try { v ? localStorage.setItem(KEY, v) : localStorage.removeItem(KEY); } catch (e) {}
  }
  function apply(v) {
    if (v === "light" || v === "dark") root.setAttribute("data-sg-theme", v);
    else root.removeAttribute("data-sg-theme");
  }

  var current = read();
  apply(current);   // subito, prima che la pagina si disegni

  var SVG = {
    light: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4"/></svg>',
    dark:  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/></svg>',
    auto:  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="8.5"/><path d="M12 3.5v17"/><path d="M12 3.5a8.5 8.5 0 0 1 0 17z" fill="currentColor" stroke="none"/></svg>'
  };
  var WORDS = {
    light: "Light",
    dark:  "Dark",
    auto:  "System"
  };
  var TITLES = {
    light: "Theme: light — click for dark",
    dark:  "Theme: dark — click to follow the system",
    auto:  "Theme: follows your system — click for light"
  };

  function stateName(v) { return v === "light" ? "light" : v === "dark" ? "dark" : "auto"; }

  document.addEventListener("DOMContentLoaded", function () {
    var host = document.querySelector(".wy-side-nav-search");
    if (!host) return;                       // un tema diverso: niente bottone
    var b = document.createElement("button");
    b.type = "button";
    b.className = "sg-theme-toggle";

    function render() {
      var n = stateName(current);
      b.innerHTML = SVG[n] + '<span>' + WORDS[n] + '</span>';
      b.title = TITLES[n];
      b.setAttribute("aria-label", TITLES[n]);
    }
    b.addEventListener("click", function () {
      current = current === "light" ? "dark" : current === "dark" ? null : "light";
      write(current);
      apply(current);
      render();
    });
    render();
    host.appendChild(b);
  });
})();
