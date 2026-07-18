// Firebase layer for the trainer, exposed as a single global `window.BT` so
// the (classic, non-module) page scripts can call it without imports. It
// provides: a Google sign-in gate, the problem pool read from Firestore
// (index doc + per-problem docs), and the per-user attempt (measurement)
// stream. Loaded as a module; dispatches `bt-ready` once window.BT is set.
import { initializeApp }
  from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import {
  getAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged,
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

let USER = null;
let ATTEMPTS = {};   // {problemId: record} — mirrors the old localStorage shape

function tsMillis(a) {
  if (!a || !a.ts) return 0;
  if (typeof a.ts.toMillis === "function") return a.ts.toMillis();
  if (a.ts.seconds) return a.ts.seconds * 1000;
  return 0;
}

// ---- auth gate + account chip ----------------------------------------
function gate(mode) {
  let g = document.getElementById("bt-gate");
  if (!g) {
    g = document.createElement("div");
    g.id = "bt-gate";
    g.style.cssText =
      "position:fixed;inset:0;z-index:9999;display:flex;align-items:center;" +
      "justify-content:center;text-align:center;padding:1.5em;" +
      "background:var(--felt-deep,#0B1A13);color:var(--on-felt,#fff);";
    document.body.appendChild(g);
  }
  if (mode === "setup") {
    g.innerHTML =
      "<div style='max-width:32em;line-height:1.5'><h1>Setup needed</h1>" +
      "<p>Firebase isn't configured yet. Fill in <code>firebase-config.js</code> " +
      "with your project's web config, then reload.</p></div>";
    return;
  }
  g.innerHTML =
    "<div><h1 style='color:inherit'>♠ Bridge Trainer</h1>" +
    "<p>Sign in to save and track your progress.</p>" +
    "<button id='bt-signin' style='font-size:17px;font-weight:700;padding:14px 22px;" +
    "border:0;border-radius:12px;background:#EAB84C;color:#2A2410;cursor:pointer'>" +
    "Sign in with Google</button></div>";
  document.getElementById("bt-signin").onclick = () =>
    signInWithPopup(auth, provider).catch((e) => alert("Sign-in failed: " + e.message));
}
function ungate() { const g = document.getElementById("bt-gate"); if (g) g.remove(); }

function mountChip(user) {
  let c = document.getElementById("bt-account");
  if (!c) {
    c = document.createElement("div");
    c.id = "bt-account";
    c.style.cssText =
      "position:fixed;top:8px;right:10px;z-index:100;display:flex;gap:8px;" +
      "align-items:center;font-size:12px;color:var(--on-felt-muted,#9FB4A8);";
    document.body.appendChild(c);
  }
  const name = user.displayName || user.email || "signed in";
  c.innerHTML =
    (user.photoURL
      ? "<img src='" + user.photoURL + "' referrerpolicy='no-referrer' " +
        "style='width:24px;height:24px;border-radius:50%'>" : "") +
    "<span>" + name + "</span>" +
    "<a href='#' id='bt-signout' style='color:var(--on-felt,#fff)'>sign out</a>";
  document.getElementById("bt-signout").onclick = (e) => {
    e.preventDefault(); signOut(auth);
  };
}

async function preloadAttempts(uid) {
  const snap = await getDocs(collection(db, "users", uid, "attempts"));
  const all = snap.docs.map((d) => d.data()).sort((a, b) => tsMillis(a) - tsMillis(b));
  ATTEMPTS = {};
  for (const a of all) if (!ATTEMPTS[a.problemId]) ATTEMPTS[a.problemId] = a;
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
  attempts: () => ATTEMPTS,
  gradeBidding, gradeLead,

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
    if (!USER) return [];
    const snap = await getDocs(collection(db, "users", USER.uid, "attempts"));
    return snap.docs.map((d) => d.data());
  },
  async record(problemId, rec) {
    const full = { ...rec, problemId,
                   isFirstAttempt: !ATTEMPTS[problemId],
                   attemptNo: 1 };
    ATTEMPTS[problemId] = full;              // update the sync cache now
    if (!USER) return;
    try {
      await addDoc(collection(db, "users", USER.uid, "attempts"),
                   { ...full, ts: serverTimestamp() });
    } catch (e) { console.error("could not save attempt", e); }
  },
  async resetAll() {
    if (!USER) return;
    const snap = await getDocs(collection(db, "users", USER.uid, "attempts"));
    let batch = writeBatch(db), n = 0;
    for (const d of snap.docs) {
      batch.delete(d.ref);
      if (++n >= 400) { await batch.commit(); batch = writeBatch(db); n = 0; }
    }
    if (n) await batch.commit();
    ATTEMPTS = {};
  },

  // auth gate + attempt preload, then hand control back to the page
  start(ready) {
    if (!isConfigured) { gate("setup"); return; }
    onAuthStateChanged(auth, async (u) => {
      if (!u) { gate("signin"); return; }
      USER = u; ungate(); mountChip(u);
      try { await preloadAttempts(u.uid); } catch (e) { console.error(e); }
      ready(u);
    });
  },
};

window.BT = BT;
window.dispatchEvent(new Event("bt-ready"));
