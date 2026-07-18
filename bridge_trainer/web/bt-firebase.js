// Firebase layer for the trainer, exposed as a single global `window.BT` so
// the (classic, non-module) page scripts can call it without imports. It
// provides: guest-friendly Google sign-in (as an action, not a wall), the
// problem pool read from Firestore (index doc + per-problem docs), and the
// per-user attempt (measurement) stream. Guests use the app fully with
// attempts saved to localStorage; signing in migrates guest data to
// Firestore. Loaded as a module; dispatches `bt-ready` once window.BT is set,
// and `bt-user-changed` whenever the signed-in/guest state flips.
import { initializeApp }
  from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import {
  getAuth, GoogleAuthProvider, signInWithPopup, signInWithRedirect,
  signOut, onAuthStateChanged,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";
import {
  getFirestore, doc, getDoc, getDocs, collection, addDoc, writeBatch,
  serverTimestamp,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js";
import { firebaseConfig, isConfigured } from "./firebase-config.js";

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);
const provider = new GoogleAuthProvider();

const GUEST_KEY = "bt_guest_attempts";

let USER = null;
let ATTEMPTS = {};   // {problemId: record} — mirrors the old localStorage shape
let migrating = false;   // guard against double-migration on sign-in

function tsMillis(a) {
  if (!a || !a.ts) return 0;
  if (typeof a.ts.toMillis === "function") return a.ts.toMillis();
  if (a.ts.seconds) return a.ts.seconds * 1000;
  if (typeof a.ts === "number") return a.ts;
  return 0;
}

// ---- guest (localStorage) store --------------------------------------
function readGuest() {
  try {
    const raw = localStorage.getItem(GUEST_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch (e) {
    console.error("could not read guest attempts", e);
    return [];
  }
}
function writeGuest(arr) {
  try { localStorage.setItem(GUEST_KEY, JSON.stringify(arr)); }
  catch (e) { console.error("could not save guest attempts", e); }
}
function clearGuest() {
  try { localStorage.removeItem(GUEST_KEY); }
  catch (e) { console.error("could not clear guest attempts", e); }
}

// Build the {problemId: firstAttempt} cache from a flat array of records,
// keeping the earliest attempt per problemId (by ts).
function firstAttemptCache(all) {
  const sorted = [...all].sort((a, b) => tsMillis(a) - tsMillis(b));
  const cache = {};
  for (const a of sorted) if (!cache[a.problemId]) cache[a.problemId] = a;
  return cache;
}

// ---- setup gate (unconfigured only) ----------------------------------
function gate(mode) {
  let g = document.getElementById("bt-gate");
  if (!g) {
    g = document.createElement("div");
    g.id = "bt-gate";
    g.dir = "rtl";
    g.lang = "he";
    g.style.cssText =
      "position:fixed;inset:0;z-index:9999;display:flex;align-items:center;" +
      "justify-content:center;text-align:center;padding:1.5em;direction:rtl;" +
      "background:var(--felt-deep,#0B1A13);color:var(--on-felt,#fff);";
    document.body.appendChild(g);
  }
  if (mode === "setup") {
    g.innerHTML =
      "<div style='max-width:32em;line-height:1.6'><h1>נדרשת הגדרה</h1>" +
      "<p>‏Firebase עדיין לא הוגדר. יש למלא את הקובץ <code>firebase-config.js</code> " +
      "בפרטי ההגדרה של הפרויקט שלך, ואז לטעון מחדש את הדף.</p></div>";
    return;
  }
}

async function preloadAttempts(uid) {
  const snap = await getDocs(collection(db, "users", uid, "attempts"));
  const all = snap.docs.map((d) => d.data());
  ATTEMPTS = firstAttemptCache(all);
}

// ---- migration on sign-in --------------------------------------------
async function migrateGuest(uid) {
  if (migrating) return;
  const guest = readGuest();
  if (!guest.length) return;
  migrating = true;
  try {
    for (const rec of guest) {
      try {
        await addDoc(collection(db, "users", uid, "attempts"),
                     { ...rec, ts: serverTimestamp() });
      } catch (e) { console.error("could not migrate guest attempt", e); }
    }
    clearGuest();
  } finally {
    migrating = false;
  }
}

// ---- grading (compute the stored measurement from the verdict) --------
function meta(P) {
  const cls = P.classification || {};
  return {
    problemId: P.id,
    problemVersion: P.created_at || "",
    scoringForm: P.scoring_form || "IMPs",
    kind: P.kind || "bidding",
    type: cls.type || P.type || null,
    difficultyLevel: cls.difficulty_level || null,
  };
}

function gradeBidding(P, action) {
  const v = P.verdict;
  const accepted = v.accepted || [];
  const best = v.best || accepted[0] ||
    (v.corrected && v.corrected[0] && v.corrected[0].bid);
  const dead = (v.dead_options || []).map((d) => d.bid || d);
  const row = (v.corrected || []).find((r) => r.bid === action);
  const correct = accepted.includes(action);
  let gradedCost = 0;
  if (row && !correct) gradedCost = Math.max(0, -(+row.ev));
  let outcomeClass = "suboptimal";
  if (action === best) outcomeClass = "winner";
  else if (correct) outcomeClass = "accepted-alt";
  else if (dead.includes(action)) outcomeClass = "dead";
  return { ...meta(P), answer: action, chosenCall: action, correct,
           outcomeClass, gradedCost, acceptedSet: accepted };
}

function gradeLead(P, card) {
  const v = P.verdict;
  const accepted = v.accepted || [];
  const correct = accepted.includes(card);
  const row = (v.table || []).find((r) => r.card === card);
  let gradedCost = 0;
  if (row && !correct && row.vs_best !== undefined)
    gradedCost = Math.max(0, -(+row.vs_best));   // defensive tricks below best
  return { ...meta(P), answer: card, chosenCall: card, correct,
           outcomeClass: correct ? "winner" : "suboptimal",
           gradedCost, acceptedSet: accepted };
}

// ---- public API -------------------------------------------------------
const BT = {
  user: () => USER,
  isGuest: () => !USER,
  attempts: () => {
    if (USER) return ATTEMPTS;          // Firestore-preloaded cache
    return firstAttemptCache(readGuest());
  },
  gradeBidding, gradeLead,

  signIn() {
    return signInWithPopup(auth, provider).catch((e) => {
      console.error("popup sign-in failed, falling back to redirect", e);
      return signInWithRedirect(auth, provider)
        .catch((e2) => console.error("redirect sign-in failed", e2));
    });
  },
  signOut() {
    return signOut(auth).catch((e) => console.error("sign-out failed", e));
  },

  async fetchIndex() {
    const s = await getDoc(doc(db, "meta", "index"));
    if (!s.exists()) throw new Error("no pool index");
    return s.data();
  },
  async getProblem(id) {
    const s = await getDoc(doc(db, "problems", id));
    return s.exists() ? s.data() : null;
  },
  async allAttempts() {
    if (!USER) return readGuest();
    const snap = await getDocs(collection(db, "users", USER.uid, "attempts"));
    return snap.docs.map((d) => d.data());
  },
  async record(problemId, rec) {
    if (!USER) {
      const arr = readGuest();
      const existing = arr.some((a) => a.problemId === problemId);
      const full = { ...rec, problemId,
                     isFirstAttempt: !existing,
                     attemptNo: 1,
                     ts: Date.now() };
      arr.push(full);
      writeGuest(arr);
      ATTEMPTS = firstAttemptCache(arr);       // keep sync cache consistent
      return;
    }
    const full = { ...rec, problemId,
                   isFirstAttempt: !ATTEMPTS[problemId],
                   attemptNo: 1 };
    ATTEMPTS[problemId] = full;              // update the sync cache now
    try {
      await addDoc(collection(db, "users", USER.uid, "attempts"),
                   { ...full, ts: serverTimestamp() });
    } catch (e) { console.error("could not save attempt", e); }
  },
  async resetAll() {
    if (!USER) {
      clearGuest();
      ATTEMPTS = {};
      return;
    }
    const snap = await getDocs(collection(db, "users", USER.uid, "attempts"));
    let batch = writeBatch(db), n = 0;
    for (const d of snap.docs) {
      batch.delete(d.ref);
      if (++n >= 400) { await batch.commit(); batch = writeBatch(db); n = 0; }
    }
    if (n) await batch.commit();
    ATTEMPTS = {};
  },

  // Render immediately for a guest, then track auth state. No sign-in wall.
  start(ready) {
    if (!isConfigured) { gate("setup"); return; }

    // Guest mode: render the app right away.
    let handedOff = false;
    ready(null);
    handedOff = true;

    onAuthStateChanged(auth, async (u) => {
      if (u) {
        USER = u;
        try { await migrateGuest(u.uid); } catch (e) { console.error(e); }
        try { await preloadAttempts(u.uid); } catch (e) { console.error(e); }
      } else {
        USER = null;
        ATTEMPTS = firstAttemptCache(readGuest());
      }
      // Signal the page nav to refresh account UI / re-render.
      window.dispatchEvent(new Event("bt-user-changed"));
      // `ready` already ran once for the guest; only re-invoke if the very
      // first auth callback arrived before we handed off (defensive).
      if (!handedOff) { handedOff = true; ready(USER); }
    });
  },
};

window.BT = BT;
window.dispatchEvent(new Event("bt-ready"));
