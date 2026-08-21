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
  getCountFromServer, onSnapshot, deleteDoc,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js";
import { firebaseConfig, isConfigured } from "./firebase-config.js";
import { classifySignInError, mergePending, prunePending,
         indexStamp, sameStamp, unwrapFirestore,
         needsReconcile } from "./bt-logic.js";

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
// first-attempt saves that failed (rules/quota/offline), keyed by problemId,
// awaiting a retry. Persisted so they survive a page navigation. Stored WITHOUT
// the serverTimestamp() sentinel (not JSON-serializable) — it is re-added on
// flush. A full reconcile must not drop these (mergePending).
let PENDING = {};

// How stale the cache may get before we do a full authoritative reconcile
// (which is the only thing that removes server-deleted docs from the cache).
const FULL_SYNC_INTERVAL_MS = 6 * 60 * 60 * 1000;   // 6 hours
// resetAll delete-batch size (BUG-9): under Firestore's 500-writes-per-batch
// hard limit, with headroom.
const RESET_BATCH_LIMIT = 400;

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
// PERF-F-7: JSON.stringify-ing the whole ATTEMPTS map and writing it
// synchronously blocks the main thread — and it ran on EVERY answer, right as
// the verdict renders. Defer it to idle time and coalesce bursts. The answer is
// already in ATTEMPTS (memory) and written to Firestore, so a dropped deferred
// write only costs a cache refill on the next load; but a shared SYNCHRONOUS
// flush on pagehide/visibilitychange guarantees the last answer is persisted
// before this (multi-page) tab unloads on "next problem". NB: savePending stays
// synchronous — a failed first-attempt save must never be lost to a deferred
// write. `saveCache` itself stays available for the background sync paths.
let CACHE_DIRTY_UID = null, CACHE_FLUSH_SCHEDULED = false;
function flushCache() {
  CACHE_FLUSH_SCHEDULED = false;
  if (CACHE_DIRTY_UID) saveCache(CACHE_DIRTY_UID);
}
function scheduleSaveCache(uid) {
  CACHE_DIRTY_UID = uid;
  if (CACHE_FLUSH_SCHEDULED) return;
  CACHE_FLUSH_SCHEDULED = true;
  const ric = (typeof window !== "undefined" && window.requestIdleCallback)
    || ((f) => setTimeout(f, 0));
  ric(flushCache);
}
if (typeof window !== "undefined" && window.addEventListener) {
  // pagehide fires on navigation/unload; visibilitychange->hidden covers the
  // mobile "switch away" case. Both flush synchronously so nothing is lost.
  window.addEventListener("pagehide", flushCache);
  window.addEventListener("visibilitychange", () => {
    if (typeof document !== "undefined"
        && document.visibilityState === "hidden") flushCache();
  });
}

// ---- pending (unsynced) first-attempt saves --------------------------
function pendingKey(uid) { return "bt_pending_" + uid; }
function loadPending(uid) {
  try { return JSON.parse(localStorage.getItem(pendingKey(uid))) || {}; }
  catch (e) { return {}; }
}
function savePending(uid) {
  try { localStorage.setItem(pendingKey(uid), JSON.stringify(PENDING)); }
  catch (e) { /* best-effort */ }
}
// Retry every queued save. On success the entry leaves the queue; a still-
// failing entry stays for the next attempt. serverTimestamp() is re-added here.
let FLUSHING = false;
async function flushPending(uid) {
  if (FLUSHING) return;   // guard against overlapping runs (T4 backgrounds sync)
  FLUSHING = true;
  try {
    for (const pid of Object.keys(PENDING)) {
      const ref = doc(db, "users", uid, "attempts", pid);
      try {
        await setDoc(ref, { ...PENDING[pid], ts: serverTimestamp(),
                            firstTs: serverTimestamp() });
        delete PENDING[pid];
      } catch (e) { /* keep it queued */ }
    }
    savePending(uid);
  } finally { FLUSHING = false; }
}

// ---- pool-index cache (shared pool, not per-user) --------------------
// Caches the merged shard rows keyed by the pointer's version stamp so repeat
// navigations don't re-download the whole index. Best-effort: if it exceeds the
// localStorage quota the write is dropped and we simply re-fetch next time.
const INDEX_CACHE_KEY = "bt_index_cache";
function loadIndexCache() {
  try { return JSON.parse(localStorage.getItem(INDEX_CACHE_KEY)); }
  catch (e) { return null; }
}
// ~1.5 MB budget: a huge full-index cache would fight the ~5 MB localStorage
// quota and could starve the more important bt_attempts_<uid> cache (and fail
// setItem on every navigation, silently negating the win). If the index is
// bigger, skip caching — we simply re-fetch, as before. T12's per-kind split
// keeps the cached slice small.
const INDEX_CACHE_MAX = 1500000;
function saveIndexCache(stamp, problems) {
  try {
    const blob = JSON.stringify({ stamp, problems });
    if (blob.length > INDEX_CACHE_MAX) {
      localStorage.removeItem(INDEX_CACHE_KEY);   // don't keep a stale copy
      return;
    }
    localStorage.setItem(INDEX_CACHE_KEY, blob);
  } catch (e) { /* quota/private-mode: cache is best-effort */ }
}

function doSignIn() {
  return signInWithPopup(auth, provider).catch((e) => {
    const kind = classifySignInError(e && e.code);
    if (kind === "redirect") {
      // popup genuinely blocked (or unsupported here): full-page redirect.
      return signInWithRedirect(auth, provider);
    }
    if (kind === "cancel") {
      // user dismissed the popup — a normal cancellation, not a failure.
      return null;
    }
    // a real error (network/config/internal): let the caller surface it.
    console.error("sign-in failed", e);
    throw e;
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
    "<div style='max-width:30em;line-height:1.6'>" +
    "<h1 style='color:inherit'>&spades; Bridge Trainer</h1>" +
    "<p>מאמן הכרזה והובלה בברידג' — תרגול בעיות אמת עם משוב מיידי, " +
    "ניקוד 0–100 ומעקב התקדמות.</p>" +
    "<button id='bt-signin' style='font-size:17px;font-weight:700;" +
    "padding:14px 22px;border:0;border-radius:12px;background:#EAB84C;" +
    "color:#2A2410;cursor:pointer'>התחבר עם Google</button>" +
    "<p style='font-size:13px;opacity:.85;margin-top:10px'>" +
    "ההתקדמות נשמרת לחשבון שלך ומסתנכרנת בין המכשירים.</p>" +
    "<p id='bt-signin-err' role='alert' " +
    "style='color:#FFB4A8;min-height:1.2em;margin-top:6px'></p></div>";
  const btn = document.getElementById("bt-signin");
  btn.onclick = () => {
    const err = document.getElementById("bt-signin-err");
    if (err) err.textContent = "";
    btn.disabled = true;
    // doSignIn resolves quietly on user-cancel and rejects only on a real
    // failure (see classifySignInError); surface that instead of an
    // unhandled rejection, and re-enable the button to retry.
    doSignIn()
      .catch(() => { if (err) err.textContent =
        "ההתחברות נכשלה. בדוק את החיבור ונסה שוב."; })
      .finally(() => { btn.disabled = false; });
  };
}
function ungate() { const g = document.getElementById("bt-gate"); if (g) g.remove(); }

// Synchronous, no network: make the cached attempts + pending queue available
// instantly so the page can render before the authoritative sync runs (T4).
function loadCacheState(uid) {
  const cache = loadCache(uid);
  ATTEMPTS = cache.byId || {};
  LAST_TS = cache.lastTs || 0;
  LAST_FULL_SYNC = cache.lastFullSync || 0;
  PENDING = loadPending(uid);
}

// The authoritative background sync (full reconcile or incremental) + pending
// flush. Runs AFTER the page has already rendered from cache. Guarded against
// overlapping runs (onAuthStateChanged re-fires on token refresh).
let SYNCING = false;
async function syncAttempts(uid) {
  if (SYNCING) return;
  SYNCING = true;
  try {
    await _syncAttempts(uid);
  } finally { SYNCING = false; }
}
async function _syncAttempts(uid) {
  const coll = collection(db, "users", uid, "attempts");

  // Full reconcile: read the WHOLE collection and REPLACE the cache, so docs
  // deleted on the server drop out locally too. Runs when the cache has never
  // been fully synced (e.g. first load after this logic shipped) or has gone
  // stale past FULL_SYNC_INTERVAL_MS.
  if (!LAST_FULL_SYNC || Date.now() - LAST_FULL_SYNC > FULL_SYNC_INTERVAL_MS) {
    // A full reconcile exists to catch server-side DELETIONS. Before paying the
    // O(N) read, ask the server for a COUNT (one aggregation read): if it equals
    // what the cache expects the server to hold (cached attempts minus the
    // not-yet-synced pendings), nothing was deleted and we skip the full read
    // (DB-O-6). Count unavailable -> fall through and reconcile as before.
    let serverCount = null;
    try { serverCount = (await getCountFromServer(coll)).data().count; }
    catch (e) { /* aggregation unavailable/offline: do the full read */ }
    const expected = Object.keys(ATTEMPTS).length - Object.keys(PENDING).length;
    if (!needsReconcile(serverCount, expected)) {
      LAST_FULL_SYNC = Date.now();
      saveCache(uid);
      await flushPending(uid);
      return;
    }
    const before = new Set(Object.keys(ATTEMPTS));   // known before the read
    const snap = await getDocs(coll);
    const next = {};
    let maxTs = 0;
    for (const d of snap.docs) {
      const a = d.data();
      const ms = tsMillis(a);
      if (ms > maxTs) maxTs = ms;
      next[a.problemId || d.id] = a;   // one doc per problem
    }
    // keep answers RECORDED LOCALLY during the in-flight getDocs: a key that
    // wasn't known before the read and isn't in the snapshot is a fresh answer
    // (its write may have succeeded — so it left PENDING — but landed after the
    // snapshot). Distinguishing "new key" from "server-deleted key" is what
    // makes reconcile safe here (T4 review).
    for (const pid of Object.keys(ATTEMPTS))
      if (!before.has(pid) && !(pid in next)) next[pid] = ATTEMPTS[pid];
    // drop pendings the server already has, then keep the rest on top of the
    // fresh snapshot so an unsynced local answer is never wiped by reconcile.
    PENDING = prunePending(PENDING, next);
    ATTEMPTS = mergePending(next, PENDING);
    LAST_TS = maxTs;
    LAST_FULL_SYNC = Date.now();
    savePending(uid);
    saveCache(uid);
    await flushPending(uid);
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
    // Only a missing composite index (failed-precondition) justifies the
    // expensive whole-collection fallback. A transient/offline error must NOT
    // be masked behind the most expensive read (DB-O-6) — rethrow so this sync
    // cycle is skipped and retried on the next load. (Docs without a ts field
    // don't throw under orderBy("ts") — they're simply omitted and swept up by
    // the interval full reconcile.)
    if (e && e.code === "failed-precondition") {
      console.warn("incremental sync needs an index; one-time full read", e);
      snap = await getDocs(coll);
    } else {
      throw e;
    }
  }
  for (const d of snap.docs) {
    const a = d.data();
    const ms = tsMillis(a);
    if (ms > LAST_TS) LAST_TS = ms;
    const pid = a.problemId || d.id;
    ATTEMPTS[pid] = a;   // one doc per problem
    delete PENDING[pid];  // it's on the server now
  }
  savePending(uid);
  saveCache(uid);
  await flushPending(uid);   // retry any saves still queued
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
  // panel score (0-100): btScoreBidding lives in the pages' shared inline
  // script (docs/scoring_scale.md), which runs before this module. Guarded
  // so grading still works if a page omits it (score falls back to binary).
  const score = (typeof window !== "undefined" && window.btScoreBidding)
    ? window.btScoreBidding(P, action).score : (correct ? 100 : 0);
  return { ...meta(P), answer: action, chosenCall: action, correct,
           outcomeClass, gradedCost, score, acceptedSet: accepted };
}

function gradeLead(P, card, mode) {
  // mode-aware grading: MP grades against the expected-defensive-tricks
  // ranking, IMP against the expected-IMP ranking (verdict.by_mode). Legacy
  // records carry no per-mode data and are always graded as MP.
  const v = P.verdict;
  const trainingMode = mode === "IMP" ? "IMP" : "MP";
  const bm = (v.by_mode && v.by_mode[trainingMode]) || null;
  const stored = (bm && bm.accepted && bm.accepted.length)
    ? bm.accepted : (v.accepted || []);
  // btLeadAccepted is the scorer's own definition of the accepted set (it
  // applies the MP score-domain tie test), so `correct` and `score` agree
  const accepted = (typeof window !== "undefined" && window.btLeadAccepted)
    ? window.btLeadAccepted(P, trainingMode) : stored;
  const correct = accepted.includes(card);
  const row = (v.table || []).find((r) => r.card === card);
  const rankKey = trainingMode === "IMP" ? "rank_imp" : "rank_mp";
  // panel score (0-100); see gradeBidding for the window-boundary note
  const parts = (typeof window !== "undefined" && window.btScoreLead)
    ? window.btScoreLead(P, card, trainingMode) : null;
  const score = parts ? parts.score : (correct ? 100 : 0);
  let gradedCost = 0;
  if (row && !correct) {
    if (trainingMode === "IMP" && row.exp_imps !== undefined) {
      // IMPs below the mode's best lead
      const best = (v.table || []).find((r) => accepted.includes(r.card));
      if (best && best.exp_imps !== undefined)
        gradedCost = Math.max(0, +best.exp_imps - +row.exp_imps);
    } else if (parts && parts.cost !== undefined) {
      gradedCost = parts.cost;   // the gap the scorer charged, in tricks —
                                 // the trick gap, or the bigger score-domain
                                 // one put on the trick scale (_SCORE_JS)
    } else if (row.vs_best !== undefined) {
      gradedCost = Math.max(0, -(+row.vs_best)); // def. tricks below best
    }
  }
  const primaryValue = row
    ? (trainingMode === "IMP" ? row.exp_imps : row.avg_def_tricks) : null;
  return { ...meta(P), answer: card, chosenCall: card, correct, score,
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
  attempts: () => ATTEMPTS,
  // Answers whose write has not landed yet (queued in PENDING). They are real
  // history the SERVER has never seen, so `trainer pool regrade-attempts`
  // cannot repair their grades and no sync can refresh them — the dashboard
  // says so instead of presenting their snapshot as settled.
  pendingCount: () => Object.keys(PENDING).length,
  // The same set, by id, so a per-row view (the practice log) can mark the
  // exact rows the server has never seen instead of only counting them.
  pendingIds: () => Object.keys(PENDING),
  gradeBidding, gradeLead,
  signIn: () => doSignIn(),
  signOut: () => signOut(auth).catch((e) => console.error(e)),

  // Read the sharded pool index. `getDoc` is server-first when online, so the
  // old code re-downloaded every shard on EVERY page navigation (multi-page
  // site) — several MB and reads per visit. Now we read only the small pointer
  // (1 read), and if its version stamp is unchanged we return the shard rows
  // from a local cache; we re-download the shards (in PARALLEL) only when the
  // stamp changes. Legacy single-doc indexes (inline `problems`) still work.
  async fetchIndex() {
    const ptr = await getDoc(doc(db, "meta", "index"));
    if (!ptr.exists()) throw new Error("no pool index");
    const data = ptr.data();
    if (Array.isArray(data.problems)) return data;   // legacy single-doc
    const stamp = indexStamp(data);
    const cached = loadIndexCache();
    if (cached && sameStamp(cached.stamp, stamp)
        && Array.isArray(cached.problems)) {
      return { ...data, problems: cached.problems };   // no shard reads
    }
    const snaps = await Promise.all((data.shards || []).map(
      (sid) => getDoc(doc(db, "meta", sid))));
    const problems = [];
    for (const s of snaps) {
      if (s.exists()) {
        const sd = s.data();
        if (Array.isArray(sd.problems)) problems.push(...sd.problems);
      }
    }
    saveIndexCache(stamp, problems);
    return { ...data, problems };
  },
  async getProblem(id) {
    const s = await getDoc(doc(db, "problems", id));
    // reverse the producer's nested-array wrapping once, here, so no page has
    // to unwrap fields ad hoc (DB-M-8). unwrapFirestore is idempotent on
    // never-wrapped (static-file) records.
    return s.exists() ? unwrapFirestore(s.data()) : null;
  },
  // Served from the in-memory cache preloaded/synced at sign-in — no extra
  // Firestore reads on the dashboard.
  async allAttempts() {
    return Object.values(ATTEMPTS);
  },
  async record(problemId, rec) {
    if (!USER) return;
    const uid = USER.uid;
    const ref = doc(db, "users", uid, "attempts", problemId);
    const existing = ATTEMPTS[problemId];
    if (!existing) {
      // first attempt: one doc per problem, keyed by problemId (bounds the
      // collection size to distinct problems answered). Reflect it locally
      // immediately (optimistic UI), but if the write fails, QUEUE it so it is
      // retried and a full reconcile won't silently drop it (BUG-2/DB-O-9).
      // include a client ts so a reconcile overlay (and the dashboard's
      // recent/streak sort) keeps a timestamp; flushPending/setDoc override it
      // with serverTimestamp() on the actual write.
      // firstTs is the immutable first-attempt time the dashboard orders by;
      // ts also starts here but a re-answer bumps it so incremental sync
      // notices cross-device attemptCount updates (DB-M-9). Both start equal.
      const nowSec = Math.floor(Date.now() / 1000);
      const payload = { ...rec, problemId, isFirstAttempt: true,
                        attemptCount: 1, ts: { seconds: nowSec },
                        firstTs: { seconds: nowSec } };
      ATTEMPTS[problemId] = payload;
      scheduleSaveCache(uid);   // deferred; flushed on pagehide (PERF-F-7)
      try {
        await setDoc(ref, { ...payload, ts: serverTimestamp(),
                            firstTs: serverTimestamp() });
        delete PENDING[problemId];   // confirmed on the server
        savePending(uid);
      } catch (e) {
        console.error("could not save attempt", e);
        PENDING[problemId] = payload;   // retried on next load / flush
        savePending(uid);
        window.dispatchEvent(new Event("bt-save-failed"));
      }
    } else {
      // re-answer: keep the first-attempt grading, just count it.
      // NB: `existing` IS ATTEMPTS[problemId] (same object), so the pre-bump
      // first-attempt time is read out BEFORE anything below overwrites it —
      // both the local backfill and the server patch depend on it.
      const prevMs = tsMillis(existing);
      const hadFirstTs = !!existing.firstTs;
      ATTEMPTS[problemId].attemptCount = (existing.attemptCount || 1) + 1;
      // Reflect the activity time LOCALLY too (device clock, the same optimism
      // the first-attempt path already uses). ts/lastTs are otherwise advanced
      // only by serverTimestamp(), so until a sync pulled the doc back, a view
      // ordered by LAST ACTIVITY — the practice log — left the problem sitting
      // in its original day with no sign it had just been replayed (offline,
      // that is forever). The server's stamps overwrite these on the next sync,
      // and LAST_TS only ever advances from server snapshots, so an optimistic
      // local stamp cannot skew the incremental query.
      const nowSec = Math.floor(Date.now() / 1000);
      ATTEMPTS[problemId].ts = { seconds: nowSec };
      ATTEMPTS[problemId].lastTs = { seconds: nowSec };
      // a legacy doc has no firstTs, and its ts was the first attempt's — keep
      // that locally as well, or the bumped ts above would become its firstMs
      if (!hadFirstTs && prevMs)
        ATTEMPTS[problemId].firstTs = { seconds: Math.floor(prevMs / 1000) };
      scheduleSaveCache(uid);   // deferred; flushed on pagehide (PERF-F-7)
      if (PENDING[problemId]) {
        // the first attempt hasn't reached the server yet — bump the QUEUED
        // payload instead of a merge write, which would create a partial doc
        // (no score) that a full reconcile could let win, losing the first
        // attempt (T9 review). flushPending carries the full record.
        PENDING[problemId].attemptCount =
          (PENDING[problemId].attemptCount || 1) + 1;
        savePending(uid);
        return;
      }
      try {
        // bump ts (not just lastTs) so the incremental sync on ANOTHER device
        // (which filters on ts) picks up this re-answer's attemptCount; firstTs
        // preserves first-attempt ordering. LEGACY docs predate firstTs, so
        // backfill it here from the existing (first-attempt) ts — otherwise the
        // bumped ts would let firstMs reorder them on the dashboard (DB-M-9).
        const patch = { attemptCount: increment(1),
                        lastTs: serverTimestamp(), ts: serverTimestamp() };
        if (!hadFirstTs && prevMs) patch.firstTs = new Date(prevMs);
        await setDoc(ref, patch, { merge: true });
      } catch (e) {
        console.error("could not update attempt", e);
        window.dispatchEvent(new Event("bt-save-failed"));
      }
    }
  },
  async resetAll() {
    if (!USER) return;
    const snap = await getDocs(collection(db, "users", USER.uid, "attempts"));
    let batch = writeBatch(db), n = 0;
    for (const d of snap.docs) {
      batch.delete(d.ref);
      if (++n >= RESET_BATCH_LIMIT) {
        await batch.commit(); batch = writeBatch(db); n = 0;
      }
    }
    if (n) await batch.commit();
    ATTEMPTS = {}; LAST_TS = 0; PENDING = {};
    try { localStorage.removeItem(cacheKey(USER.uid)); } catch (e) { /* */ }
    try { localStorage.removeItem(pendingKey(USER.uid)); } catch (e) { /* */ }
  },

  // ---- bidding-analysis queue (analyze.html) --------------------------
  // The client only FILES requests; the GitHub Actions worker computes and
  // writes results back (see .github/workflows/analyze-requests.yml). The
  // page watches its own requests live, so the finished report appears
  // without polling. Shapes are validated by firestore.rules
  // (validAnalysisReq) and re-validated by the worker.
  async submitAnalysis(req) {
    if (!USER) throw new Error("not signed in");
    const reqRef = doc(collection(db, "analysis_requests"));
    await setDoc(reqRef, {
      uid: USER.uid, status: "pending",
      createdAt: serverTimestamp(), req,
    });
    return reqRef.id;
  },
  // Live view of MY analysis requests (rules admit the query only when it
  // filters on my uid). Sorted newest-first client-side — no orderBy, so no
  // composite index is needed. Returns the unsubscribe function.
  watchAnalyses(cb) {
    if (!USER) return () => {};
    const q = query(collection(db, "analysis_requests"),
                    where("uid", "==", USER.uid));
    return onSnapshot(q, (snap) => {
      const rows = snap.docs.map((d) => ({ id: d.id, ...d.data() }));
      rows.sort((a, b) => {
        const ta = (a.createdAt && a.createdAt.seconds) || 0;
        const tb = (b.createdAt && b.createdAt.seconds) || 0;
        return tb - ta;
      });
      cb(rows);
    }, (e) => console.error("watchAnalyses", e));
  },
  async getAnalysisReport(id) {
    const s = await getDoc(doc(db, "analysis_reports", id));
    return s.exists() ? s.data() : null;
  },
  async deleteAnalysis(id) {
    // the report doc may not exist (pending/error) — delete best-effort
    try { await deleteDoc(doc(db, "analysis_reports", id)); }
    catch (e) { /* no report yet, or already gone */ }
    await deleteDoc(doc(db, "analysis_requests", id));
  },

  // Sign-in is required. Gate the whole app until authenticated; preload the
  // user's attempts, then hand control back to the page and notify the nav.
  start(ready) {
    if (!isConfigured) { gate("setup"); return; }
    let handedOff = false;
    onAuthStateChanged(auth, (u) => {
      if (!u) {
        const prevUid = USER && USER.uid;
        USER = null; ATTEMPTS = {}; LAST_TS = 0; LAST_FULL_SYNC = 0; PENDING = {};
        // SEC-C-8: on a shared computer, don't leave the signed-out user's
        // attempt history + pending queue in localStorage for the next person.
        // (The pool-index cache is shared, not per-user, so it's left alone.)
        if (prevUid) {
          try { localStorage.removeItem(cacheKey(prevUid)); } catch (e) { /* */ }
          try { localStorage.removeItem(pendingKey(prevUid)); } catch (e) { /* */ }
        }
        // cancel any pending deferred cache write so a later pagehide flush
        // can't re-create the just-removed per-user key (SEC-C-8).
        CACHE_DIRTY_UID = null; CACHE_FLUSH_SCHEDULED = false;
        window.dispatchEvent(new Event("bt-user-changed"));
        gate("signin");
        return;
      }
      USER = u; ungate();
      // Render NOW from the local cache; do the authoritative sync in the
      // background so the first problem/stats don't wait on a network round
      // trip (T4). Pages listen for `bt-attempts-synced` to refresh once the
      // server state (incl. answers from another device) has landed.
      loadCacheState(u.uid);
      window.dispatchEvent(new Event("bt-user-changed"));
      if (!handedOff) { handedOff = true; ready(u); }
      const ric = window.requestIdleCallback || ((f) => setTimeout(f, 1));
      ric(() => syncAttempts(u.uid)
        .catch((e) => console.error(e))
        .finally(() => window.dispatchEvent(new Event("bt-attempts-synced"))));
    });
  },
};

window.BT = BT;
window.dispatchEvent(new Event("bt-ready"));
