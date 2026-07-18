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
users/{uid}                       profile
users/{uid}/attempts/{attemptId}  one doc per answered deal (the raw metrics)
```
Per-user metrics on the dashboard are derived on read from `attempts` — no
aggregation backend, no Cloud Functions, stays on the free tier.
