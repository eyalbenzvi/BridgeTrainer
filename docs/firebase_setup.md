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

> ⚠️ `push` rebuilds `meta/index` from the **local** `data/` pool, and the app
> reads that one index doc. Always push the *complete* pool (existing +
> new), never a partial directory, or the index will shrink to only what you
> pushed. The generated problem docs left behind in the collection would
> become orphans the app can't see.

## 8b. Generating a batch inside a Claude Code session (repeatable)

This is the intended way to grow the pool: it runs entirely on Claude Code
servers, no CI. Three steps — **generate → classify → push** — because a
problem's `type` (the taxonomy label the app filters on) is assigned by the
`claude` CLI, which is only available inside a Claude Code session.

```bash
# one-time per session: Ben engine (TensorFlow + models, ~3 GB)
scripts/setup_ben.sh ~/ben ~/benv
~/benv/bin/pip install 'firebase-admin>=6' 'protobuf==5.29.5'   # push deps

# 1. generate N bidding problems into data/ (pick a seed above the highest
#    already used — ids are ben1-<seed hex>, so a fresh range avoids clashes)
BEN_HOME=~/ben ~/benv/bin/trainer ben-forge \
    --count N --pool data --seed <fresh> --workers 4

# 2. classify: the claude CLI adds classification.type to the new bidding
#    problems (idempotent — already-classified problems are skipped; lead
#    problems fail fast and harmlessly, they carry no bidding type)
python3 scripts/classify_pool.py data

# 3. push the whole pool to Firestore, then commit data/ to git
~/benv/bin/trainer pool push --pool data --key /path/to/sa-key.json
git add data/ && git commit -m "generate N bidding problems"
```

Firestore + TensorFlow disagree on the protobuf version; if you hit an import
error, do the push from a **separate venv** that has `firebase-admin` but not
TensorFlow — generation and push only share the `data/` directory, never a
process.

### Where to put the service-account key
The key is a secret — never commit it. In a Claude Code session, either:
- **attach the JSON to the session** and pass its path to `--key` (simplest;
  nothing persisted), or
- for unattended/scheduled runs, set it as an **environment secret** in the
  Claude Code environment config and export
  `GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json` (the push falls back to
  that env var when `--key` is omitted).

Rotate the key (Firebase console → Service accounts → *Generate new private
key*, then delete the old one) if it is ever exposed.

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
