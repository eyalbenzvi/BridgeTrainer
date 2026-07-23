// Firebase layer for the trainer, exposed as a single global `window.BT` so
// the (classic, non-module) page scripts can call it without imports. It
// provides: a Google sign-in gate (sign-in is REQUIRED — there is no guest
// mode), the problem pool read from Firestore (sharded index doc + per-problem
// docs), and the per-user attempt (measurement) stream. Loaded as a module;
// dispatches `bt-ready` once window.BT is set, and `bt-user-changed`
// whenever the signed-in state flips (so the page nav can refresh).
//
// Read-cost discipline (Firestore free tier = 50k reads/day, shared):
//   * a persistent IndexedDB cache is enabled so repeat doc reads across the
//     multi-page site are served locally, not re-billed;
//   * the pool index is read as a small pointer + shard docs, never the whole
//     problems collection;
//   * per-user attempts are synced INCREMENTALLY (only docs newer than the
//     last-seen timestamp), cached in localStorage, and attempts are stored
//     one-doc-per-problem so the collection can't grow without bound.
//
// Incremental sync only ADDS docs, so it never notices a doc that was DELETED
// on the server (e.g. an admin/data reset) — the cached copy would linger. To
// stay eventually-consistent with deletions without paying a full read on every
// page navigation, we also run a FULL reconcile (read the whole attempts
// collection and REPLACE the cache) at most once per FULL_SYNC_INTERVAL_MS, and
// always once when no full sync has ever been recorded. That bounds full reads
// to a few per day per user while guaranteeing deletions eventually propagate.
import { initializeApp }
  from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import {
  getAuth, GoogleAuthProvider, signInWithPopup, signInWithRedirect, signOut,
  onAuthStateChanged,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";
import {
  initializeFirestore, getFirestore, persistentLocalCache,
  persistentMultipleTabManager, doc, getDoc, getDocs, collection, setDoc,
  writeBatch, serverTimestamp, query, where, orderBy, increment,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js";
import { firebaseConfig, isConfigured } from "./firebase-config.js";

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);

// Persistent local cache: survives page navigations (the site is multi-page),
// so meta/index, already-seen problem docs, and attempts are not re-read from
// the server on every load. Falls back to the default in-memory client if the
// browser can't provide IndexedDB persistence.
let db;
try {
  db = initializeFirestore(app, {
    localCache: persistentLocalCache(
      { tabManager: persistentMultipleTabManager() }),
  });
} catch (e) {
  console.warn("persistent Firestore cache unavailable, using default", e);
  db = getFirestore(app);
}
const provider = new GoogleAuthProvider();

let USER = null;
let ATTEMPTS = {};   // {problemId: record}, preloaded at sign-in
let LAST_TS = 0;     // max attempt timestamp (ms) synced so far
let LAST_FULL_SYNC = 0;   // ms wall-clock of the last full reconcile

// How stale the cache may get before we do a full authoritative reconcile
// (which is the only thing that removes server-deleted docs from the cache).
const FULL_SYNC_INTERVAL_MS = 6 * 60 * 60 * 1000;   // 6 hours

function tsMillis(a) {
  if (!a || !a.ts) return 0;
  if (typeof a.ts.toMillis === "function") return a.ts.toMillis();
  if (a.ts.seconds) return a.ts.seconds * 1000;
  return 0;
}

// ---- per-user attempt cache in localStorage --------------------------
function cacheKey(uid) { return "bt_attempts_" + uid; }
function loadCache(uid) {
  try {
    const c = JSON.parse(localStorage.getItem(cacheKey(uid)));
    if (c && c.byId) return c;
  } catch (e) { /* ignore */ }
  return { byId: {}, lastTs: 0, lastFullSync: 0 };
}
function saveCache(uid) {
  try {
    localStorage.setItem(cacheKey(uid),
      JSON.stringify({ byId: ATTEMPTS, lastTs: LAST_TS,
                       lastFullSync: LAST_FULL_SYNC }));
  } catch (e) { /* quota/private-mode: cache is best-effort */ }
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
  const cache = loadCache(uid);
  ATTEMPTS = cache.byId || {};
  LAST_TS = cache.lastTs || 0;
  LAST_FULL_SYNC = cache.lastFullSync || 0;
  const coll = collection(db, "users", uid, "attempts");

  // Full reconcile: read the WHOLE collection and REPLACE the cache, so docs
  // deleted on the server drop out locally too. Runs when the cache has never
  // been fully synced (e.g. first load after this logic shipped) or has gone
  // stale past FULL_SYNC_INTERVAL_MS.
  if (!LAST_FULL_SYNC || Date.now() - LAST_FULL_SYNC > FULL_SYNC_INTERVAL_MS) {
    const snap = await getDocs(coll);
    const next = {};
    let maxTs = 0;
    for (const d of snap.docs) {
      const a = d.data();
      const ms = tsMillis(a);
      if (ms > maxTs) maxTs = ms;
      next[a.problemId || d.id] = a;   // one doc per problem
    }
    ATTEMPTS = next;
    LAST_TS = maxTs;
    LAST_FULL_SYNC = Date.now();
    saveCache(uid);
    return;
  }

  // Incremental sync: cheap add-only pass for the common case (recent full
  // reconcile), fetching just docs newer than the last-seen timestamp.
  let snap;
  try {
    snap = await getDocs(LAST_TS
      ? query(coll, where("ts", ">", new Date(LAST_TS)), orderBy("ts"))
      : query(coll, orderBy("ts")));
  } catch (e) {
    // missing index / offline / legacy docs without ts: one-time full read
    console.warn("incremental attempt sync failed, full read", e);
    snap = await getDocs(coll);
  }
  for (const d of snap.docs) {
    const a = d.data();
    const ms = tsMillis(a);
    if (ms > LAST_TS) LAST_TS = ms;
    ATTEMPTS[a.problemId || d.id] = a;   // one doc per problem
  }
  saveCache(uid);
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

function gradeLead(P, card, mode) {
  // mode-aware grading: MP grades against the expected-defensive-tricks
  // ranking, IMP against the expected-IMP ranking (verdict.by_mode). Legacy
  // records carry no per-mode data and are always graded as MP.
  const v = P.verdict;
  const trainingMode = mode === "IMP" ? "IMP" : "MP";
  const bm = (v.by_mode && v.by_mode[trainingMode]) || null;
  const accepted = (bm && bm.accepted && bm.accepted.length)
    ? bm.accepted : (v.accepted || []);
  const correct = accepted.includes(card);
  const row = (v.table || []).find((r) => r.card === card);
  const rankKey = trainingMode === "IMP" ? "rank_imp" : "rank_mp";
  let gradedCost = 0;
  if (row && !correct) {
    if (trainingMode === "IMP" && row.exp_imps !== undefined) {
      // IMPs below the mode's best lead
      const best = (v.table || []).find((r) => accepted.includes(r.card));
      if (best && best.exp_imps !== undefined)
        gradedCost = Math.max(0, +best.exp_imps - +row.exp_imps);
    } else if (row.vs_best !== undefined) {
      gradedCost = Math.max(0, -(+row.vs_best)); // def. tricks below best
    }
  }
  const primaryValue = row
    ? (trainingMode === "IMP" ? row.exp_imps : row.avg_def_tricks) : null;
  return { ...meta(P), answer: card, chosenCall: card, correct,
           trainingMode,
           rankingMetric: trainingMode === "IMP" ? "exp_imps"
                                                 : "exp_def_tricks",
           chosenRank: row && row[rankKey] !== undefined ? row[rankKey] : null,
           recommendedLead: (bm && bm.recommended) || accepted[0] || null,
           primaryValue: primaryValue === undefined ? null : primaryValue,
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

  // Read the sharded pool index: a small pointer doc lists shard doc ids;
  // each shard holds a slice of the problem rows. (Legacy single-doc indexes,
  // which carry `problems` inline, still work.)
  async fetchIndex() {
    const ptr = await getDoc(doc(db, "meta", "index"));
    if (!ptr.exists()) throw new Error("no pool index");
    const data = ptr.data();
    if (Array.isArray(data.problems)) return data;   // legacy single-doc
    const problems = [];
    for (const sid of (data.shards || [])) {
      const s = await getDoc(doc(db, "meta", sid));
      if (s.exists()) {
        const sd = s.data();
        if (Array.isArray(sd.problems)) problems.push(...sd.problems);
      }
    }
    return { ...data, problems };
  },
  async getProblem(id) {
    const s = await getDoc(doc(db, "problems", id));
    return s.exists() ? s.data() : null;
  },
  // Served from the in-memory cache preloaded/synced at sign-in — no extra
  // Firestore reads on the dashboard.
  async allAttempts() {
    return Object.values(ATTEMPTS);
  },
  async record(problemId, rec) {
    if (!USER) return;
    const ref = doc(db, "users", USER.uid, "attempts", problemId);
    const existing = ATTEMPTS[problemId];
    if (!existing) {
      // first attempt: one doc per problem, keyed by problemId (bounds the
      // collection size to distinct problems answered).
      const stored = { ...rec, problemId, isFirstAttempt: true,
                       attemptCount: 1, ts: serverTimestamp() };
      ATTEMPTS[problemId] = { ...rec, problemId, isFirstAttempt: true,
                             attemptCount: 1,
                             ts: { seconds: Math.floor(Date.now() / 1000) } };
      try { await setDoc(ref, stored); }
      catch (e) { console.error("could not save attempt", e); }
    } else {
      // re-answer: keep the first-attempt grading, just count it.
      ATTEMPTS[problemId].attemptCount = (existing.attemptCount || 1) + 1;
      try {
        await setDoc(ref, { attemptCount: increment(1),
                            lastTs: serverTimestamp() }, { merge: true });
      } catch (e) { console.error("could not update attempt", e); }
    }
    saveCache(USER.uid);
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
    ATTEMPTS = {}; LAST_TS = 0;
    try { localStorage.removeItem(cacheKey(USER.uid)); } catch (e) { /* */ }
  },

  // Sign-in is required. Gate the whole app until authenticated; preload the
  // user's attempts, then hand control back to the page and notify the nav.
  start(ready) {
    if (!isConfigured) { gate("setup"); return; }
    let handedOff = false;
    onAuthStateChanged(auth, async (u) => {
      if (!u) {
        USER = null; ATTEMPTS = {}; LAST_TS = 0;
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
