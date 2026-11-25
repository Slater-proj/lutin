// The script of the frame that draws diagrams (ADR 0011). It is written into the page by lutin.web_app.diagram_page, after Mermaid.
// The frame is sandboxed: it has no origin, no cookie, no token and no network. It receives the text of a diagram from the interface
// and answers with the text of a drawing (SVG), which the interface only ever shows as an image.
(function () {
  "use strict";
  var home = new URL(location.href).origin; // the interface that holds this frame: the only one listened to, the only one answered
  var count = 0;

  function answer(message) {
    parent.postMessage(message, home);
  }

  function reason(error) {
    return String((error && error.message) || error || "").slice(0, 300);
  }

  window.addEventListener("message", function (event) {
    if (event.source !== parent || event.origin !== home) return;
    var data = event.data || {};
    if (data.type !== "draw" || typeof data.id !== "string" || typeof data.source !== "string") return;
    if (typeof mermaid === "undefined") return answer({ type: "failed", id: data.id, error: "no renderer" });
    count += 1;
    try {
      // Labels are drawn as SVG text, never as HTML: the drawing stays a well-formed image whatever a label holds.
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: data.dark ? "dark" : "default",
        htmlLabels: false,
        flowchart: { htmlLabels: false },
        suppressErrorRendering: true,
        fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
      });
      mermaid.render("diagram" + count, data.source).then(
        function (result) {
          answer({ type: "drawn", id: data.id, svg: String(result.svg) });
        },
        function (error) {
          answer({ type: "failed", id: data.id, error: reason(error) });
        }
      );
    } catch (error) {
      answer({ type: "failed", id: data.id, error: reason(error) });
    }
  });

  answer({ type: "ready" });
})();
