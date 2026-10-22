/* the chosen theme before first paint, so nothing flashes. A file of
   its own: the page runs no inline script (CSP default-src 'self'). The
   same file, word for word, runs on spark.forgewright.ai. */
try {
  var t = localStorage.getItem("spark-theme");
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
} catch (e) {}
