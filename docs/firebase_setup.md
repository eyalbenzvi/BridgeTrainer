# Firebase setup

The web app uses Firebase for three things: **Google sign-in**, the
**problem pool** (`problems` collection), and **per-user measurements**
(`users/{uid}/attempts`). Everything runs client-side on GitHub Pages — no
server. This is a one-time setup on your own Google account.

## 1. Create the project
1. https://console.firebase.google.com → **Add project**.
2. Analytics is optional; you can skip it.

## 2. Enable Google sign-in
Authentication → **Get started** → Sign-in method → **Google** → Enable →
save. (Google is the only provider we use.)

## 3. Create Firestore
Firestore Database → **Create database** → start in production mode → pick a
region. We install real rules in step 6.

## 4. Get the web config and paste it in
Project settings (gear) → **General** → *Your apps* → add a **Web app**
(`</>`) if you don't have one → copy the `firebaseConfig` values into
[`bridge_trainer/web/firebase-config.js`](../bridge_trainer/web/firebase-config.js),
replacing the `REPLACE_ME` placeholders. These values are **public by
design** — they ship in the client; access is controlled by the rules, not
by hiding them. Commit the file.

## 5. Authorize your site's domain
Authentication → Settings → **Authorized domains** → Add your Pages domain
(e.g. `youruser.github.io`). Without this, Google sign-in silently fails.
(`localhost` is authorized by default for local testing.)

## 6. Install the security rules
Copy [`firestore.rules`](../firestore.rules) into Firestore → Rules → publish
(or `firebase deploy --only firestore:rules` with the Firebase CLI). They
allow signed-in users to read problems and to read/write only their own data.

## 7. Service-account key (to upload problems)
Project settings → **Service accounts** → **Generate new private key** → save
the JSON **locally** (do not commit it — it's already covered by common
gitignore patterns; keep it out of the repo). This lets the generator write
to Firestore.

## 8. Populate the problem pool
Generate locally, then push to Firestore:

```bash
pip install -e '.[firestore]'
trainer pool add --count 10                 # generate into data/ (needs Ben)
trainer pool push --key /path/to/sa-key.json  # upload data/ -> Firestore
```

`push` skips problems already present; pass `--overwrite` to replace them.
To migrate the existing repo pool, just run `push` against the current
`data/` directory.

## 9. Deploy the app shell
Push to `main`; the `Deploy app` workflow builds the static shell with
`trainer webapp` and deploys it to GitHub Pages. The shell reads problems and
your progress from Firestore at runtime.

## Data model
```
problems/{id}                     generated problem docs (read-only to clients)
users/{uid}/attempts/{attemptId}  one doc per answered deal (the raw metrics)
```
(There is no `users/{uid}` profile document — the client only ever writes the
`attempts` subtree, and the security rules allow nothing else, DB-M-9/SEC-A-6.)
Per-user metrics on the dashboard are derived on read from `attempts` — no
aggregation backend, no Cloud Functions, stays on the free tier.

## 10. Monitoring & alerts (required) — DB-O-7
The app runs on the Spark free tier (≈50k reads/day, ≈20k writes/day, ≈10 GiB
egress/month), shared across all users. Without alerts, exhausting a quota only
shows up when the app stops working. Set these up once, in the Google Cloud
console for the Firebase project:

1. **Cloud Monitoring alert on Firestore usage.** Create an alerting policy on
   the metrics `firestore.googleapis.com/document/read_count` and
   `.../document/write_count` (aligned as a daily sum), threshold ≈70% of the
   daily quota, notification channel = your email. This warns before the quota
   is hit, not after.
2. **Budget alert.** Billing → Budgets & alerts → create a budget (even a $0
   budget on Spark) with email alerts at 50/90/100%. If/when you move to Blaze,
   this plus a hard cap keeps a traffic spike from silently running up cost.
3. **Forge workflow failure.** `.github/workflows/forge-leads.yml` already
   opens/updates a GitHub issue on any failed run (`Notify on failure` step,
   `issues: write`), so a stalled pool is surfaced within the hour instead of
   going unnoticed for days. Watch the repo (or the `forge` label) to receive
   those notifications.

These are configuration, not code: keep them in place after any project or
billing change.
