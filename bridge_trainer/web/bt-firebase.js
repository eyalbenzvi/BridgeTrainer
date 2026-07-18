// Firebase layer for the trainer, exposed as a single global `window.BT` so
// the (classic, non-module) page scripts can call it without imports. It
// provides: a Google sign-in gate (sign-in is REQUIRED — there is no guest
// mode), the problem pool read from Firestore (index doc + per-problem
// docs), and the per-user attempt (measurement) stream. Loaded as a module;
// dispatches `bt-ready` once window.BT is set, and `bt-user-changed`
// whenever the signed-in state flips (so the page nav can refresh).
import { initializeApp }
  from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import {
  getAuth, GoogleAuthProvider, signInWithPopup, signInWithRedirect, signOut,
  onAuthStateChanged,
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
let ATTEMPTS = {};   // {problemId: record}, preloaded at sign-in

function tsMillis(a) {
  if (!a || !a.ts) return 0;
  if (typeof a.ts.toMillis === "function") return a.ts.toMillis();
  if (a.ts.seconds) return a.ts.seconds * 1000;
  return 0;
}

function doSignIn() {
  return signInWithPopup(auth, provider).catch((e) => {
    console.error("popup sign-in failed, falling back to redirect", e);
    return signInWithRedirect(auth, provider);
  });
}

// ---- full-screen auth gate (Hebrew, RTL) ------------------------------
function gate(mode) {
  let g = document.getElementById("bt-gate");
  if (!g) {
    g = document.createElement("div");
    g.id = "bt-gate";
    g.dir = "rtl";
    g.style.cssText =
      "position:fixed;inset:0;z-index:9999;display:flex;align-items:center;" +
      "justify-content:center;text-align:center;padding:1.5em;" +
      "background:var(--felt-deep,#0B1A13);color:var(--on-felt,#fff);";
    document.body.appendChild(g);
  }
  if (mode === "setup") {
    g.innerHTML =
      "<div style='max-width:32em;line-height:1.6'><h1>נדרשת הגדרה</h1>" +
      "<p>Firebase עדיין לא מוגדר. מלא את <code>firebase-config.js</code> " +
      "בפרטי הפרויקט שלך, ואז טען מחדש.</p></div>";
    return;
  }
  g.innerHTML =
    "<div><h1 style='color:inherit'>&spades; Bridge Trainer</h1>" +
    "<p>התחבר כדי לשמור ולעקוב אחר ההתקדמות שלך.</p>" +
    "<button id='bt-signin' style='font-size:17px;font-weight:700;" +
    "padding:14px 22px;border:0;border-radius:12px;background:#EAB84C;" +
    "color:#2A2410;cursor:pointer'>התחבר עם Google</button></div>";
  document.getElementById("bt-signin").onclick = () => doSignIn();
}
function ungate() { const g = document.getElementById("bt-gate"); if (g) g.remove(); }

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
  isGuest: () => !USER,
  attempts: () => ATTEMPTS,
  gradeBidding, gradeLead,
  signIn: () => doSignIn(),
  signOut: () => signOut(auth).catch((e) => console.error(e)),

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
    if (!USER) return;
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

  // Sign-in is required. Gate the whole app until authenticated; preload the
  // user's attempts, then hand control back to the page and notify the nav.
  start(ready) {
    if (!isConfigured) { gate("setup"); return; }
    let handedOff = false;
    onAuthStateChanged(auth, async (u) => {
      if (!u) {
        USER = null; ATTEMPTS = {};
        window.dispatchEvent(new Event("bt-user-changed"));
        gate("signin");
        return;
      }
      USER = u; ungate();
      try { await preloadAttempts(u.uid); } catch (e) { console.error(e); }
      window.dispatchEvent(new Event("bt-user-changed"));
      if (!handedOff) { handedOff = true; ready(u); }
    });
  },
};

window.BT = BT;
window.dispatchEvent(new Event("bt-ready"));
