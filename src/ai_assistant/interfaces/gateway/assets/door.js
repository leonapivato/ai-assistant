// Which door served this page (ADR-0327 §11). This file is the one the loopback and
// remote browser listeners serve at `/door.js`; the hosted listener serves
// `door-hosted.js` at the same path instead, and that substitution is the whole of the
// difference between the two bundles. Read by `app.js` off the document element, and
// by nothing else: the gateway decides every admission itself, so a page that read
// the wrong door would show the wrong panel and be refused, never admitted.
"use strict";

document.documentElement.dataset.door = "local";
