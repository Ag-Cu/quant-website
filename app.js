// Compatibility entry point for any cached pages that still load /app.js.
// The application now runs as native ES Modules from /src/app.js.
(() => {
  const script = document.createElement("script");
  script.type = "module";
  script.src = "src/app.js";
  (document.currentScript || document.body).after(script);
})();
