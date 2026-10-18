// Which door served this page (ADR-0327 §11): the hosted listener, behind the sign-in
// edge. Served at `/door.js` by that listener alone, in place of `door.js`. The page
// then shows no bootstrap entry and mints its session by the exchange (§11:1), and
// says that it stays signed in for as long as the person's sign-in lasts (§11:7).
"use strict";

document.documentElement.dataset.door = "hosted";
