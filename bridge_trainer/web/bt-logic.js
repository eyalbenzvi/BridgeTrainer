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
export function classifySignInError(code) {
  const REDIRECT = new Set([
    "auth/popup-blocked",
    "auth/operation-not-supported-in-this-environment",
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
