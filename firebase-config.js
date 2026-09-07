// Firebase web config (public by design — access is controlled by Firestore
// security rules, not by keeping these secret). From the Firebase console:
// Project settings -> Your apps -> Web app -> SDK setup and configuration.
export const firebaseConfig = {
  apiKey: "AIzaSyAkA-8YywUNjsB-aSc1NzimyEPvCBzDaiI",
  authDomain: "bridgetrainer-3c759.firebaseapp.com",
  projectId: "bridgetrainer-3c759",
  storageBucket: "bridgetrainer-3c759.firebasestorage.app",
  messagingSenderId: "555589350422",
  appId: "1:555589350422:web:9f003a0c11bc491094b137",
};

export const isConfigured = !Object.values(firebaseConfig).some(
  (v) => typeof v === "string" && v.startsWith("REPLACE_ME"));
