(function () {
  var SLOW = {
    offer_read: "Gemini is reading the offer. This can take up to a minute.",
    explain: "The agent is working on your question. This can take up to a minute.",
    upload: "Gemini is reading your receipt. This can take up to a minute."
  };
  var form = document.querySelector("form");
  var busy = document.getElementById("busy");
  var sent = false;
  function setButtons(disabled) {
    form.querySelectorAll("button").forEach(function (b) { b.disabled = disabled; });
  }
  if (form && busy) {
    form.addEventListener("submit", function (e) {
      if (sent) { e.preventDefault(); return; }
      sent = true;
      var s = e.submitter;
      var action = s ? (s.name === "question_chip" ? "explain" : s.value) : "";
      if (SLOW[action]) {
        document.getElementById("busy-text").textContent = SLOW[action];
        busy.hidden = false;
      }
      // Disabling the clicked button before the browser reads the form would drop its action, so wait a tick.
      setTimeout(function () { setButtons(true); }, 0);
    });
    window.addEventListener("pageshow", function (e) {
      if (e.persisted) { sent = false; busy.hidden = true; setButtons(false); }
    });
  }
  var copy = document.getElementById("copy-cart");
  if (copy) {
    copy.addEventListener("click", function () {
      var area = document.getElementById("cart-text");
      var done = function () { document.getElementById("copy-done").textContent = "Copied."; };
      var fallback = function () { area.select(); document.execCommand("copy"); done(); };
      if (navigator.clipboard) { navigator.clipboard.writeText(area.value).then(done, fallback); } else { fallback(); }
    });
  }
})();
