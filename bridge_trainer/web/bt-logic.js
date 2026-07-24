// Side-effect-free logic helpers for the trainer's Firebase layer.
//
// This module has NO firebase imports and does NO module-level initialization,
// so it can be loaded under plain `node` and unit-tested directly (see
// tests/test_bt_logic.py), unlike bt-firebase.js which runs initializeApp() at
// import time. bt-firebase.js imports the helpers below and wires them to the
// live SDK. Keep this file import-free and pure.

// Classify a Firebase Auth sign-in error (the popup path) into the action the
// caller should take:
//   "redirect" — the popup was genuinely blocked; fall back to a full-page
//                redirect sign-in.
//   "cancel"   — the user dismissed/aborted the popup; this is a normal
//                cancellation, NOT an error to surface or to redirect on.
//   "error"    — a real failure (network, config, internal); the caller should
//                surface it to the user.
// NB: auth/operation-not-supported-in-this-environment is deliberately an
// "error", not "redirect" — signInWithRedirect needs the very same environment
// (http/https origin, web storage) the popup was refused for, so redirecting
// would fail too. Surface it instead.
export function classifySignInError(code) {
  const REDIRECT = new Set([
    "auth/popup-blocked",
  ]);
  const CANCEL = new Set([
    "auth/popup-closed-by-user",
    "auth/cancelled-popup-request",
    "auth/user-cancelled",
  ]);
  if (REDIRECT.has(code)) return "redirect";
  if (CANCEL.has(code)) return "cancel";
  return "error";
}

// ---- attempt-save reliability (T9) -----------------------------------------
// A first-attempt save that fails (rules/quota/offline) must NOT be dropped: it
// is queued in a local "pending" map and retried, and a full reconcile must not
// wipe it. These pure helpers keep that bookkeeping testable.

// Drop pending entries the server already has (they synced — here or on another
// device), so we don't keep retrying or double-writing them.
export function prunePending(pending, serverById) {
  const out = {};
  const p = pending || {}, s = serverById || {};
  for (const pid in p) if (!(pid in s)) out[pid] = p[pid];
  return out;
}

// Overlay still-pending (not-yet-synced) attempts on a fresh server snapshot so
// a full reconcile keeps a local answer that hasn't reached the server yet.
export function mergePending(serverById, pending) {
  const out = Object.assign({}, serverById || {});
  const p = pending || {};
  for (const pid in p) if (!(pid in out)) out[pid] = p[pid];
  return out;
}

// ---- pool-index cache staleness (T10) --------------------------------------
// The sharded index pointer carries a version stamp; the client caches the
// merged rows and only re-downloads the shards when the stamp changes. Bumping
// index_format (T12's per-kind split) invalidates any older cached shape.

export function indexStamp(ptr) {
  const p = ptr || {};
  return { updated_at: p.updated_at || null, count: p.count || 0,
           format: p.index_format || 0 };
}

export function sameStamp(a, b) {
  if (!a || !b) return false;
  return a.updated_at === b.updated_at && a.count === b.count
    && a.format === b.format;
}
