/* The hero demonstration's control.
 *
 * The warp itself is CSS. A scroll-driven animation moves --travel, so the page
 * demonstrates the effect with scripting switched off, and browsers with no
 * scroll timelines get a part-closed still. This file does two jobs on top of
 * that: keep the readout honest about whatever is currently driving the warp,
 * and hand the warp over to the slider once someone touches it.
 */

(function () {
  "use strict";

  var stage = document.getElementById("stage");
  var screen = document.getElementById("screen");
  var input = document.getElementById("travel");
  var readout = document.getElementById("travel-readout");
  var note = document.getElementById("stage-note");

  if (!stage || !screen || !input || !readout) return;

  var quiet = window.matchMedia("(prefers-reduced-motion: reduce)");
  var held = false;

  function show(value) {
    readout.textContent = Math.round(value) + "\u00B0";
  }

  function apply(value) {
    screen.style.setProperty("--travel", String(value));
    show(value);
  }

  /* Read whatever the scroll timeline has put on the element. Registered
   * through @property, so this comes back as a plain number. */
  function driven() {
    var raw = getComputedStyle(screen).getPropertyValue("--travel");
    var value = parseFloat(raw);
    return isNaN(value) ? 0 : value;
  }

  /* Hand control to the slider, once and for good. Passing it back and forth
   * would mean the page fought the reader for the same element. */
  function take() {
    if (held) return;
    held = true;
    stage.dataset.held = "true";
    if (note) note.remove();
  }

  input.addEventListener("input", function () {
    take();
    apply(parseFloat(input.value));
  });

  input.addEventListener("pointerdown", take);
  input.addEventListener("keydown", function (event) {
    /* Tab and Shift-Tab are moving through the page, not using the control. */
    if (event.key !== "Tab") take();
  });

  if (quiet.matches) {
    input.value = "38";
    take();
    apply(38);
    return;
  }

  /* Mirror the scroll-driven value into the readout and the slider, so the
   * number and the thumb always agree with what is on screen. */
  var last = -1;

  function follow() {
    if (!held) {
      var value = driven();
      if (Math.abs(value - last) > 0.25) {
        last = value;
        show(value);
        input.value = String(value);
      }
    }
    requestAnimationFrame(follow);
  }

  requestAnimationFrame(follow);
})();
