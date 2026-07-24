# תוכנית ביצוע — סבב 3 (26 ממצאים)

מסמך זה מתכנן את ביצוע 26 הממצאים שנבחרו לסבב השלישי, בהמשך ל-
`docs/website_infrastructure_review.md` (טבלת master) ולמוסכמות שהתגבשו ב-
`docs/infra_fixes_plan.md` (סבב 1) וב-`docs/infra_fixes_plan_round2.md` (סבב 2).
כל הפיתוח בברנץ' `claude/bridgetrainer-infra-fixes-round3-f6as7d`; זהו PR חדש.

## מיפוי הממצאים (לפי # בטבלה => מזהה => קבוצת ביצוע)

| # | מזהה | חומרה | קבוצה (גל) | תמצית |
|---|---|---|---|---|
| 56 | PERF-F-6 | בינוני | D | מבנה counts מחושב-מראש במקום ~5 סריקות אינדקס בכל הקשה |
| 57 | PERF-F-7 | בינוני | C | debounce/idle ל-saveCache |
| 58 | PERF-D-4 | בינוני | A | הורדת shards במקביל — **נותר צד ה-Python** (`read_index`) |
| 59 | PERF-D-5 | בינוני | — | אינדקס מצומצם + meta/counts — **נקודת החלטה** (מיגרציה) |
| 60 | PERF-D-6 | בינוני | A | `client_view()` בצד ה-producer: לא להעלות policy_trail ושדות מתים |
| 62 | UX-I-4 | בינוני | E | skeleton ב-lead.html + עקביות הנחיות (חופף 86) |
| 63 | UX-I-5 | בינוני | E | מניעת מבוי סתום "0 בעיות" אחרי "נקה" |
| 64 | UX-I-6 | בינוני | E | דליפת מנגנון "סבב" (startedAt/תפוגה + kind + סיכום) |
| 66 | UX-A-5 | בינוני | E | isolate LTR למספרים שליליים/EV בהקשר RTL |
| 67 | UX-A-6 | בינוני | E | VS15 (FE0E) לסמלי הסדרות |
| 68 | UX-A-7 | בינוני | E | radiogroup + כפתורים מקוננים בדף הבית (חופף 92) |
| 69 | UX-A-8 | בינוני | E | aria-pressed לבורר דרגת הקושי |
| 70 | UX-A-9 | בינוני | E | overflow-x לטבלאות רחבות + breakpoint למובייל |
| 71 | ARCH-10 | נמוך | A | פיצול cmd_pool ל-set_defaults; העברת `_PerBoardConstraintSampler` |
| 72 | ARCH-11 | נמוך | A | סקריפטים יציבים → תתי-פקודות CLI (pool classify/reexplain/backfill-notes) |
| 73 | BUG-8 | נמוך | D | קוד guest מת (refreshAcct + BT.isGuest) — **הטקסט כבר יושר בסבב 2** |
| 74 | BUG-9 | נמוך | D | ריכוז מספרי קסם לקבועים (NEAR_MIN=65, REVIEW_MIN=85, SESSION_SIZE=10, SCORE_MAX_NONBEST=94, BATCH_LIMIT=400) |
| 75 | BUG-10 | נמוך | D | מחיקת saveStore/it.correct מתים; איחוד .headline כפולה |
| 76 | DB-M-9 | נמוך | B | serverTimestamp בעדכון חוזר + סימון attempts יתומים בדשבורד |
| 80 | SEC-A-6 | נמוך | B | צמצום חוק users/{uid} + ולידציה; esc() על שדות attempt בדשבורד |
| 85 | SEC-C-8 | נמוך | B | ניקוי localStorage/IndexedDB בהתנתקות |
| 86 | PERF-F-8 | נמוך | E | skeleton + החלת theme ב-`<head>` (מיזוג עם 62) |
| 88 | PERF-D-8 | נמוך | — | reconcile מלא רק על מחיקה — **מכוסה ע"י DB-O-6 (סבב 2)** |
| 90 | PERF-D-10 | נמוך | A | דילוג על רינדור וריאנטים שלא השתנו ב-publish.py |
| 92 | UX-I-9 | נמוך | E | ניווט חצים + roving tabindex בבחירת תרחיש (מיזוג עם 68) |
| 93 | UX-A-10 | נמוך | E | איחוד/ניקוי טוקני תמה כפולים; שטח הקשה לכפתורי טקסט |

---

## עקרונות ומוסכמות (מסבבים 1-2, ממשיכים — תמצית)

- **מקורות אמת:** ה-JS/CSS המוטמעים הם קבועי הפייתון ב-`webapp.py`:
  `_SCORE_JS` (DOM-free, בר-בדיקה), `_SHARED_JS = _SCORE_JS + tail`
  (ה-tail מריץ `applyTheme()`/`initChrome()` — לא DOM-free), `_LEAD_JS`,
  `_DASHBOARD_JS`, `_CSS`, `_DASHBOARD_CSS`. גופי הדפים נבנים ב-f-string עם
  `{{`/`}}` כסוגריים ליטרליים. `write_app` פולט את הקבצים החיצוניים.
- **מפת קבועים בפועל (מאומת):** `_CSS` 56-646; `_SCORE_JS` 647-854;
  `_SHARED_JS` 855-1561; `_index_html` 1586-1992; `_problem_html` 1993-2539;
  `_LEAD_JS` 2540-2956; `_lead_html` 2957-2995; `_DASHBOARD_CSS` 2996-3040;
  `_DASHBOARD_JS` 3041-3332; `_dashboard_html` 3333-3350;
  `_ASSET_FILES` 3351; `write_app` 3354.
- **בדיקות JS (3 דפוסים קיימים לחיקוי):**
  - `run_js`/`run_score` (`test_scoring_scale.py`, `test_normalize_shapes.py`):
    מריץ **רק את `_SCORE_JS`** (DOM-free) ומעריך ביטויים. פונקציות טהורות
    חדשות → `_SCORE_JS` כדי שיהיו בר-בדיקה **וגם** יגיעו לכל דף.
  - `run_shared` (`test_terse_parity.py`, `test_auction_table.py`): מזריק
    DOM-stubs (`_DOM_STUB`) ואז מריץ את `_SHARED_JS` המלא — לפונקציות שב-tail.
  - `run_logic` (`test_bt_logic.py`): מריץ `web/bt-logic.js` (טהור, ללא firebase).
- **CI:** מריץ `pytest` (לא `python -m pytest`); ייבוא בין קבצי בדיקה בשם מודול
  חשוף (`from test_x import ...`), לא `from tests.test_x`. בדיקות node מסומנות
  `needs_node` ונדלגות אם אין node.
- **כלים לשימוש חוזר מסבב 2:** `esc()`/`safeNum()`/`pct()`/`normAccepted()` ב-
  `_SCORE_JS`; `bridge_trainer/app/htmlfmt.py`; `engine/batch_state.BatchState`;
  הזרקת `window.TAXONOMY_HE` (`_taxonomy_he_json`/`_taxonomy_script`);
  `tests/test_contrast.py` (WCAG — מחלץ פלטות מ-`html[data-theme]`).
- **אילוץ קריטי לבדיקת הניגודיות:** `test_contrast.py` תלוי בקיום הבלוקים
  `html[data-theme="light"] body {…}` ו-`html[data-theme="dark"] body {…}`
  ובכך שכל טוקן מופיע בהם כ-`#rrggbb`. כל שינוי ב-93 (איחוד טוקנים) **חייב לשמר
  את שני הבלוקים האלה** ואת נוכחות כל הטוקנים בתוכם.

---

## אימות היקף לממצאים החופפים (חובה לפי המשימה)

### 58 (PERF-D-4) — היקף נותר: צד ה-Python בלבד
- **בוצע (סבב 1):** המקבול בצד הקליינט קיים — `bt-firebase.js:426`
  `Promise.all((data.shards||[]).map(sid => getDoc(...)))`.
- **הנותר:** `firestore_store.py` `read_index` (253-258) קורא shards בלולאת
  `for` טורית. ה-backfills (`backfill_lead_training`/`backfill_lead_types`)
  משתמשים ב-`stream_records` (שאילתה אחת) — כבר לא-טורי, אין מה לתקן שם.
- **מסקנה:** לממש מקבול ל-`read_index` בלבד (ראו גל A).

### 59 (PERF-D-5) — נקודת החלטה: לא לממש שינוי סכימה הרסני
- **אימות:** הממצא זהה במהותו ל-T12/PERF-F-3 שנדחו בסבבים 1-2 — דורש כותב
  producer חדש ל-`meta/counts` **ומיגרציה מתואמת על ה-DB החי**, ועדיין אינו
  משחרר את דף הבית מהורדת האינדקס (הבית זקוק לו לבחירת בעיה אקראית ולספירת
  "ממתינות" פר-פילטר). ה-cache מבוסס-החותמת (T10) כבר חתך דרסטית את עלות הקריאה
  החוזרת.
- **המיקרו-אופטימיזציה ה"בטוחה" (שקלה ונדחתה):** השדה `difficulty` (float) ב-
  `index_entry` **אינו נקרא כלל בקליינט** (מאומת: הקליינט משתמש רק ב-
  `difficulty_level`), אך הסרתו עדיין משנה את תוכן האינדקס ואת החותמת ומהווה
  שינוי סכימה. עקבית עם דחיית שינוי-האינדקס בסבבים 1-2 — **לא מיושם**.
- **החלטה:** אין שינוי קוד ל-59. תיעוד כנקודת החלטה 1 (למטה).

### 62 + 86 (UX-I-4 + PERF-F-8) — מיזוג לפיתוח אחד
- **חופף:** שניהם נוגעים ב-`lead.html`. 62 = skeleton + עקביות הנחיות; 86 =
  skeleton + החלת theme ב-`<head>`. נעשים כפיתוח אחד (גל E). ראו פירוט למטה.

### 73 (BUG-8) — היקף נותר: הסרת קוד guest מת בלבד
- **בוצע (סבב 2, UX-I-2):** `guestNote` יושר ל"לא מחובר — התחבר כדי לשמור
  התקדמות" (webapp.py:913). הטקסט כבר לא מטעה.
- **הנותר:** `BT.isGuest` (bt-firebase.js:403) עדיין קיים ונקרא רק ב-`refreshAcct`
  (webapp.py:1525) — ענף `guest` שלמעשה מת (הדף גייטד כשלא מחוברים; `USER` תמיד
  מוגדר בזמן שהנאב אינטראקטיבי). לפשט את `refreshAcct` ולהסיר את `BT.isGuest`.
  ראו גל D.

### 88 (PERF-D-8) — מכוסה ע"י DB-O-6 (סבב 2)
- **אימות:** DB-O-6 (סבב 2) כבר ממש את מנגנון הדילוג היקר: `_syncAttempts`
  (bt-firebase.js:246-261) קורא `getCountFromServer` (קריאת aggregation אחת)
  ומדלג על ה-full reconcile כש-`needsReconcile(serverCount, expected)` שקרי
  (`bt-logic.js:82`). כמו כן ה-fallback צומצם ל-`failed-precondition` בלבד
  (bt-firebase.js:305). זו בדיוק המטרה של PERF-D-8 ("reconcile מלא רק כשבאמת
  נמחק"), במימוש ה-count (החלופה שהוצעה בממצא עצמו).
- **גישת ה-`resetAt` doc** שהוצעה בממצא היא חלופה נוספת לאותה מטרה — יתירה בהינתן
  ה-count-skip, ומוסיפה כתיבה בכל reset. לא מיושמת.
- **החלטה:** אין שינוי קוד ל-88 מעבר לאימות + תיעוד. תיעוד כנקודת החלטה 2.

---

## סדר ביצוע (גלים) ותלויות

הסדר נבחר לפי (א) הפרדת קבצים כדי למזער conflicts, (ב) תלויות פנימיות.

**גל A — Python producer/CLI (ללא נגיעה ב-JS/CSS):**
58(read_index parallel) → 60(client_view) → 90(publish skip) → 71(ARCH-10)
→ 72(ARCH-11)
> עצמאיים מכל שאר הגלים. 71 לפני 72 כי 72 מוסיף תתי-פקודות באותו `cmd_pool`
> המפוצל ב-71. 90 נוגע רק ב-publish.py (מחוץ לנתיב הפריסה — שינוי בטוח).

**גל B — firestore.rules + נתוני קליינט:**
80(SEC-A-6) → 76(DB-M-9) → 85(SEC-C-8)
> 80 מצמצם rules + esc בדשבורד; 76 מוסיף orphan-marking בדשבורד (סמוך ל-esc של
> 80 — נעשים ברצף) + `ts` בעדכון חוזר ב-bt-firebase.js; 85 נוגע בענף ה-sign-out
> ב-bt-firebase.js (סמוך ל-76). כולם קטנים.

**גל C — bt-firebase.js ביצועים:**
57(PERF-F-7 debounce saveCache)
> נוגע ב-`saveCache`/`record`/`_syncAttempts`. 88 כבר מכוסה — אימות בלבד.

**גל D — לוגיקת `_SCORE_JS`/`_SHARED_JS` + קבועים:**
74(BUG-9 קבועים) → 64(תלוי ב-SESSION_SIZE)† → 56(PERF-F-6) → 75(BUG-10)
→ 73(BUG-8)
> 74 ראשון כי הוא מגדיר קבועים ש-64/56 גוזרים מהם. († 64 עצמו בגל E כי הוא UX;
> אך תלוי לוגית ב-`SESSION_SIZE` מ-74 — לכן 74 קודם לכל.) 75 מנקה קוד מת. 73
> קטן ועצמאי.

**גל E — CSS/נגישות/RTL/UX (`_CSS` + גופי דפים):**
67(UX-A-6 suits) → 66(UX-A-5 LTR) → 69(UX-A-8 aria-pressed) →
68+92(radiogroup) → 70(UX-A-9 טבלאות+breakpoint) → 93(UX-A-10 טוקנים+מגע) →
62+86(lead skeleton+theme head) → 63(UX-I-5) → 64(UX-I-6)
> כולם נוגעים ב-`_CSS` ו/או גופי דפים — נעשים ברצף כדי למזער conflicts. 93
> (איחוד טוקנים) אחרי שאר שינויי ה-CSS כדי לראות את הצורה הסופית, **תוך שימור
> הבלוקים `html[data-theme]`** ש-test_contrast תלוי בהם.

> **תלות בין-גלית:** 74 (גל D) מגדיר `SESSION_SIZE` שבו משתמש 64 (גל E). לכן גל
> D מתבצע לפני החלק של 64 בגל E. בנוסף, 56 (גל D) משכתב את פונקציות ה-facet/stats
> ב-`_index_html` (`updateScenCounts` 1699, `facetCounts` 1740, `renderStats`
> 1815) שגם 69/63/64 (גל E) עורכים — לכן 69/63/64 **נכתבים על גבי** מבנה ה-`COUNTS`
> של 56 (גל D לפני גל E, כמתוכנן). שאר הגלים בלתי-תלויים.

---

## פירוט משימות

### גל A

#### 58 (PERF-D-4) — מקבול `read_index` בפייתון
- **מיקום:** `firestore_store.py` `read_index` (253-258).
- **גישה:** להחליף את לולאת ה-`for sid ... .get()` בקריאת אצווה
  `self._db.get_all([self._meta.document(sid) for sid in shards])`. `get_all`
  מחזיר snapshots ללא סדר מובטח — יש לשמר את **סדר ה-shards** לפי `data["shards"]`
  (למשל למפות `{snap.id: snap}` ואז לאסוף לפי הסדר). לשמר תאימות legacy single-doc
  (הענף `if "problems" in data`). `stream_records` בבקפילים כבר לא-טורי.
- **בדיקות:** `tests/test_index_cas.py` (או חדש `test_read_index_parallel.py`)
  עם fake `_db` שה-`get_all` שלו מקבל רשימת refs ומחזיר snapshots בסדר מעורבב —
  לוודא שהתוצאה זהה ובסדר ה-shards הנכון, וש-legacy single-doc עדיין עובד. יש
  תשתית fake ב-`test_index_cas.py` לחיקוי.
- **סיכון:** נמוך (אותן קריאות, במקביל).

#### 60 (PERF-D-6) — `client_view()` בנתיב ההעלאה
- **מיקום:** `firestore_store.py` `push_local_pool` (414 `writer.set(...
  _firestore_safe(rec))`). שדות מתים (מאומת ב-`maker.py:75-76`,
  `lead_maker.py:117,124`): `policy_trail`, `engine_auction_complete`; ומ-
  `quality` הקליינט קורא רק `quality.n_samples`/`quality.stakes`.
- **גישה:** פונקציה טהורה `client_view(rec)` ב-`firestore_store.py` (או ב-
  `store.py` כדי להיות בר-בדיקה בלי firebase) שמסירה `policy_trail` ו-
  `engine_auction_complete`, ומצמצמת את `quality` ל-`{n_samples, stakes}` בלבד
  (אם קיימים). מוחל **רק בנתיב ההעלאה**.
  **⚠ קריטי (ביקורת):** חובה לשמר את `_firestore_safe` — הוא עוטף מערכים מקוננים
  ל-`{items:[...]}` (חוקי ב-Firestore, מהופך ב-`unwrapFirestore` בקריאה). לכן
  הקריאה היא `writer.set(..., _firestore_safe(client_view(rec)))` — לא
  `client_view(rec)` לבד (זה יעלה מערכים מקוננים לא-חוקיים וישבור את הקריאה).
  הסדר: קודם `client_view` (מסיר שדות מתים, ביניהם `policy_trail` שהוא list-of-
  lists), ואז `_firestore_safe` על מה שנשאר. הפול המקומי שומר את הרשומה המלאה.
  לאמת: ה-backfills משתמשים ב-projection מפורש (firestore_store.py:474, 516)
  שאינו כולל את השדות המתים; `candidates` (maker.py:55) הוא שדה **נפרד** שהקליינט
  קורא (_SCORE_JS:710) — לא להסירו; `index_entry` לא נוגע בהם.
- **בדיקות:** `tests/test_client_view.py` — `client_view` על רשומת maker
  מדומה: `policy_trail`/`engine_auction_complete` הוסרו, `quality` צומצם,
  ושדות שהקליינט קורא (`verdict`, `classification`, `kind`, `contract`,
  `auction`, `created_at`, `schema`) נשמרו. + assert ש-`client_view` אידמפוטנטית.
- **סיכון:** נמוך.

#### 90 (PERF-D-10) — דילוג על וריאנטים שלא השתנו ב-publish.py
- **מיקום:** `publish.py` `publish` (333-378), הלולאה `for k in range(total)`.
- **גישה:** קבוע `TEMPLATE_VERSION` במודול (מוגדל ידנית בכל שינוי תבנית). לכל
  וריאנט לכתוב סימון (`vN/.stamp` או מטא-שורה מוטמעת ב-HTML) עם
  `f"{seed_k}:{TEMPLATE_VERSION}"`; לפני `run_problem`+רינדור, אם הקבצים קיימים
  והסימון תואם — לדלג (משתמש חוזר ב-`first`/entry מה-cache הקיים של הסימולציה).
  לתעד: שינוי תבנית מחייב הגדלת `TEMPLATE_VERSION` (אחרת HTML ישן "נקפא").
  `index.html` הראשי תמיד מרונדר מחדש.
- **בדיקות:** `tests/test_publish.py` (קיים) — ריצה שנייה על אותו out_dir לא
  משנה mtime של קובצי וריאנט קיימים (או: לוודא ש-`run_problem` לא נקרא לוריאנט
  קיים דרך monkeypatch/מונה). ריצה עם `TEMPLATE_VERSION` שונה → מרונדר מחדש.
- **סיכון:** נמוך (publish.py מחוץ לנתיב הפריסה; רק `trainer webapp` נפרס).

#### 71 (ARCH-10) — פיצול `cmd_pool` + העברת ה-sampler
- **מיקום:** `cli.py` `cmd_pool` (225-292), `_PerBoardConstraintSampler`
  (210-222), ורישום תתי-הפקודות (449-496 עם `set_defaults(func=cmd_pool)`).
- **גישה:** לפצל ל-`cmd_pool_ls`/`cmd_pool_rm`/`cmd_pool_add`/`cmd_pool_push`/
  `cmd_pool_backfill_training`/`cmd_pool_backfill_leads`, כל אחת עם
  `set_defaults(func=...)` משלה (הדפוס בשאר הקובץ). להעביר
  `_PerBoardConstraintSampler` ל-`engine/lead_samplers.py` (למשל כ-
  `ConstraintSampler.per_board()` classmethod או מחלקה `PerBoardConstraintSampler`),
  ו-`cmd_lead_calibration` ייבא משם.
- **בדיקות:** `tests/test_cli_pool.py` — הרצת `main(["pool","ls",...])` על פול
  זמני מנתבת ל-cmd הנכון (dispatch); import של ה-sampler ממקומו החדש עובד ו-
  `sampling_model` נשמר. בדיקות CLI קיימות (אם יש) עוברות.
- **סיכון:** אפסי (שינוי מבני).

#### 72 (ARCH-11) — סקריפטים יציבים → תתי-פקודות CLI
- **מיקום:** `scripts/classify_pool.py`, `scripts/reexplain_pool.py`,
  `scripts/backfill_bot_notes.py` (כל אחד עם `sys.path` hack + argparse משלו).
- **גישה:** להוסיף `trainer pool classify` / `pool reexplain` /
  `pool backfill-notes` כתתי-פקודות (על גבי הפיצול של 71), שקוראות ללוגיקת הליבה
  של הסקריפטים. גישה זהירה: לחלץ את הליבה של כל סקריפט לפונקציה שהן ה-CLI והן
  הסקריפט קוראים לה (לא לשבור שימוש קיים ב-`python scripts/...`), או להשאיר
  wrapper דק ב-`scripts/`. spikes חד-פעמיים (`spike_harvest.py`,
  `prune_obvious_leads.py`, `lead_before_after.py`, `migrate_schema.py`) נשארים
  ב-`scripts/`.
- **בדיקות:** `tests/test_cli_pool.py` — תתי-הפקודות רשומות ב-parser (dispatch);
  הפונקציה המשותפת שחולצה נבדקת על fixture קטן אם אפשר בלי סביבת Ben/Firestore.
- **סיכון:** נמוך-בינוני. **החלטה:** לבדוק אילו סקריפטים דורשים Ben/Firestore
  (לא בר-בדיקה ב-CI) ולתעד; ה-dispatch עצמו נבדק תמיד.

### גל B

#### 80 (SEC-A-6) — צמצום rules + esc בדשבורד
- **מיקום:** `firestore.rules` (32-89 — כבר עודכן חלקית בסבב 2/T6:
  `match /users/{uid}` מפורש + `attemptBounds`/`validCreate`/`validUpdate`);
  `_DASHBOARD_JS` miss-list (3250-3256).
- **אימות:** רוב עבודת ה-rules בוצעה בסבב 2 (T6/SEC-C-3). הנותר ל-SEC-A-6:
  1. **חוק ה-profile:** `match /users/{uid}` מתיר כתיבה ל-doc העליון
     (`allow write: if owner(uid) && request.resource.data.size() < 50`) עבור
     "profile עתידי". DB-M-9 (76) מאשר שאף קוד לא כותב אותו. **החלטה:** לצמצם —
     להסיר את `allow write` מ-`/users/{uid}` (להשאיר `allow read`), כך שכתיבה
     מותרת רק ל-`attempts/{pid}` המולידציה. `{pid}` יוגבל ל-regex בסיסי אם
     בטוח (לתעד: מזהי הבעיות אינם בפורמט קבוע יחיד — bidding מול lead1-… — ולכן
     regex רופף בלבד או ויתור עליו, מתועד).
  2. **esc בדשבורד:** `esc()` (קיים ב-`_SCORE_JS`, מגיע לדשבורד דרך bt-shared)
     על `m.chosenCall`, `m.outcomeClass` (בענף ה-fallback), ו-
     `m.acceptedSet.join(", ")` בבניית ה-miss-list (3252-3256).
- **בדיקות:** `tests/test_firestore_rules.py` (קיים) — אם בודק מחרוזת: להוסיף
  assert ש-`/users/{uid}` אינו מתיר `write` חופשי (אין `allow write` על ה-doc
  העליון). `_DASHBOARD_JS`: string-assert ש-`chosenCall`/`acceptedSet` עטופים
  ב-`esc(`. בדיקת DOM/`run_shared` אם esc זמין שם (esc ב-_SCORE_JS → כן).
- **סיכון:** נמוך-בינוני. **⚠ high-risk manual-verify** לחלק ה-rules (אין
  emulator ב-CI, כמו סבב 1). **קוד ריוויו** בסוף.

#### 76 (DB-M-9) — serverTimestamp בעדכון חוזר + orphan attempts
- **מיקום:** `bt-firebase.js` `record` re-answer (492-494) — כותב
  `{attemptCount: increment(1), lastTs: serverTimestamp()}` בלבד;
  `docs/firebase_setup.md:64-67` (profile מתועד אך לא קיים); `_DASHBOARD_JS`
  miss-list + `init` (3250, 3316).
- **גישה:**
  1. **multi-device (מתוקן לפי ביקורת — הימנעות מרגרסיית מיון):** **אסור** פשוט
     להזיז את `ts` בעדכון חוזר — כרגע `ts` = זמן הניסיון הראשון, והדשבורד ממיין
     *הכול* לפי `tsMillis(a)` (recent 3196, chrono 3208, streak 3197-3198, trend
     3210+, misses 3246 — כולם "ניסיון ראשון בלבד"). בימפ של `ts` יקפיץ בעיה
     שנענתה-מחדש ל"האחרון" וישבור streak/trend. **הפתרון (גישת ה-`firstTs`, כפי
     שהממצא עצמו מציע):** בניסיון ראשון לכתוב **גם** `firstTs` (= אותו ערך כמו
     `ts`); בעדכון חוזר לכתוב `ts: serverTimestamp()` (כדי שהסנכרון האינקרמנטלי
     `where("ts",">",...)` יתפוס אותו) **תוך שימור `firstTs`** (merge לא מוחקו).
     הדשבורד ימיין/יסנן לפי `firstTs || ts` (fallback ל-legacy שאין בו `firstTs`
     — נכון תמיד: legacy `ts` הוא זמן הניסיון הראשון). להוסיף `firstTs` ל-
     `attemptKeys()` ב-firestore.rules (אחרת `validCreate`/`validUpdate` יידחו).
  2. **orphan attempts:** ב-`init` של הדשבורד לקרוא את האינדקס (`fetchIndex`,
     זול — cached ב-T10) ולבנות `Set` של ids חיים; להעביר ל-`render`. בבניית
     ה-miss-list, אם `m.problemId` אינו ב-Set → להציג "בעיה שהוסרה" (ללא קישור)
     במקום קישור שבור. ליפול בחן אם `fetchIndex` נכשל (להתייחס לכל ה-ids כחיים).
  3. **profile doc:** למחוק את אזכור ה-profile מ-`docs/firebase_setup.md`
     (סכמה מתה) — מתואם עם צמצום החוק ב-80.
- **בדיקות:** פונקציה טהורה `firstTsMillis(a)` ב-bt-logic + `run_logic` (fallback
  `firstTs||ts`); string-assert ש-record ניסיון-ראשון כותב `firstTs`, ושעדכון
  חוזר כותב `ts: serverTimestamp()`; string-assert שהדשבורד ממיין לפי firstTs.
  string-assert ש-`firstTs` ב-`attemptKeys()`. orphan: string-assert שה-miss-row
  מתנה על ה-liveIds set. בדיקת מחרוזת שה-doc אינו מזכיר profile.
- **סיכון:** נמוך-בינוני (נגיעה במיון הדשבורד — legacy fallback חובה). **קוד
  ריוויו** בסוף.

#### 85 (SEC-C-8) — ניקוי localStorage בהתנתקות
- **מיקום:** `bt-firebase.js` ענף sign-out ב-`onAuthStateChanged` (521-526).
- **גישה:** לפני איפוס ה-state לשמור את ה-uid הקודם, ובענף `!u` למחוק
  `localStorage.removeItem(cacheKey(prevUid))` ו-`pendingKey(prevUid)`
  (וכן `INDEX_CACHE_KEY` הוא משותף — **לא** למחוק, זה נתוני פול לא-פרטיים).
  לשקול `clearIndexedDbPersistence(db)` בהתנתקות **יזומה** בלבד (לא ב-callback
  של onAuthStateChanged, שם ה-db בשימוש) — או להסתפק במחיקת localStorage
  (הגישה הבטוחה, לפי הערת הממצא). **החלטה:** מחיקת localStorage בלבד (מחיקת
  IndexedDB דורשת ניתוק ה-db ומסבכת חיבור-מחדש; מתועד).
- **בדיקות:** קשה ל-unit-test ישירות (side-effect על localStorage אמיתי). לפצל
  את בחירת המפתחות למחיקה לפונקציה טהורה `keysToClearOnSignOut(uid)` ב-bt-logic
  ולבדוק אותה; + string-assert שענף ה-sign-out קורא `removeItem(cacheKey(...))`.
- **סיכון:** נמוך.

### גל C

#### 57 (PERF-F-7) — debounce/idle ל-saveCache
- **מיקום:** `bt-firebase.js` `saveCache` (91-97), נקרא ב-`record` (467, 481),
  `_syncAttempts` (258, 286, 321), `loadCacheState`.
- **גישה:** לעטוף את ה-`localStorage.setItem` של ה-cache ב-scheduler שדוחה ל-
  `requestIdleCallback`/`setTimeout(0)` עם debounce (כתיבה אחת לרצף). ATTEMPTS
  בזיכרון + הכתיבה ל-Firestore כבר מבטיחים שאין אובדן מידע.
  **⚠ גבול (ביקורת):** רק `saveCache` (91-97) נדחה. `savePending` (105-108)
  **חייב להישאר סינכרוני** — הוא רושם כתיבות ניסיון-ראשון שנכשלו שאסור ל-reconcile
  לאבד. **חובה flush סינכרוני
  על `visibilitychange`/`pagehide`** (כדי לא לאבד את הכתיבה האחרונה בסגירת טאב/
  ניווט — האתר multi-page!). הלוגיקה הטהורה של ה-debounce (מתי לכתוב) יכולה
  להיבדק, אך המימוש כאן קטן; לשמור על `saveCache` הסינכרוני כ-`flushCache`
  ולהוסיף `scheduleSaveCache` דוחה.
- **⚠ עדינות multi-page:** בניגוד ל-SPA, כאן כל ניווט = טעינת דף. debounce ללא
  flush ב-`pagehide` יאבד את השמירה. חובה לרשום `addEventListener("pagehide"/
  "visibilitychange", flush)`.
- **בדיקות:** קשה ל-node (תלוי localStorage/idle). string-assert:
  ש-`record`/`_syncAttempts` קוראים ל-scheduler הדוחה, ושקיים listener
  `pagehide`/`visibilitychange` שמבצע flush סינכרוני. פונקציה טהורה אם מחלצים
  לוגיקה.
- **סיכון:** נמוך-בינוני (סיכון אובדן שמירה אם ה-flush לא נכון — לכן ה-flush
  ב-pagehide קריטי). **קוד ריוויו** בסוף.

#### 88 (PERF-D-8) — אימות בלבד (מכוסה). אין שינוי קוד. ראו אימות היקף למעלה.

### גל D

#### 74 (BUG-9) — ריכוז מספרי קסם לקבועים
- **מיקום (מתוקן לפי ביקורת):** `_SCORE_JS` `SCORE_CAP=95` (653, **כבר קבוע**),
  הבנדים (668-670: `>=100` best, `>=85` near, `>=65` minor, + קצה `40`),
  clamp `1,94` (714,764,783); `_SHARED_JS` `bumpSession`/streak `>=100`
  (1415-1428, **אין בו `size:10`**); **`size: 10`** נמצא ב-`_index_html:1936**
  (blob יצירת הסבב); inline `sp.score>=65` ב-`_problem_html` (2142) ו-`_LEAD_JS`
  (2617); `_DASHBOARD_JS` `>=85` (3107) ו-`<85` misslist (3246) ו-"מתחת ל־85"
  (3248) וקצה `40` (3107, 3119), תוויות בנד קשיחות "85+/40–84/0–39" (3118-3120),
  `>=100` streak (3198), טקסט "תרגל 10" (3265); `resetAll` batch 400
  (bt-firebase.js:507). **החרגה:** `.slice(0, 10)` ב-3246 הוא מגבלת תצוגה של
  ה-misslist — **לא** לקשור ל-`SESSION_SIZE`.
- **גישה:** להגדיר ב-`_SCORE_JS` (DOM-free, בר-בדיקה + מגיע לכל דף):
  `NEAR_MIN=65`, `REVIEW_MIN=85`, `ERROR_MIN=40`, `SCORE_MAX_NONBEST=94`
  (`SCORE_CAP=95` כבר קיים). `SESSION_SIZE=10` — ב-`_SHARED_JS` (בתחום ה-
  `_index_html:1936`, שם `_SHARED_JS` בסקופ). לגזור: את בנדי `btBandOf`, את
  ה-clamps (`SCORE_MAX_NONBEST`), את `sp.score >= NEAR_MIN` בשני הדפים, את
  `>=REVIEW_MIN`/`ERROR_MIN` בדשבורד, את `size: SESSION_SIZE` ב-1936 ואת הטקסט
  "תרגל {SESSION_SIZE} כאלה". תוויות הבנד (3118-3120) — לגזור מהמספרים אם קריא;
  אחרת להשאיר כמחרוזת ולתעד. `BATCH_LIMIT=400` ב-bt-firebase.js (מודול נפרד) —
  קבוע מקומי `RESET_BATCH_LIMIT=400` עם הערה (מגבלת Firestore 500). לתעד יחס
  94↔95.
- **בדיקות:** `run_js` ש-`btBandOf` משתמש בספים הנכונים (100/85/65/40) וש-clamp
  לא עולה על `SCORE_MAX_NONBEST`; string-assert ש-inline `sp.score >= NEAR_MIN`;
  string-assert ש-`size: SESSION_SIZE` והטקסט בדשבורד נגזר מ-`SESSION_SIZE`.
  `test_scoring_scale.py` קיים עובר.
- **סיכון:** נמוך (ערכים זהים, רק שמות).

#### 56 (PERF-F-6) — counts מחושב-מראש
- **מיקום:** `_SHARED_JS` `poolFacets` (1073), `matchesFilters` (~1118);
  `_index_html` `facetCounts` (1740), `updateFacetCounts` (1754),
  `applyFilterUi` (1769), `persist` (1781), `renderStats` (1815),
  `updateScenCounts` (1699).
- **גישה:** פונקציה טהורה `buildCounts(index)` שסורקת את `index.problems`
  **פעם אחת** לאחר טעינה ובונה מבנה אגרגציה
  `{[kind]:{[mode]:{levels:{lvl:n}, types:{type:{total, byLevel:{lvl:n}}}}}}`
  (או דומה) המספיק לכל הספירות/פאסטים. לגזור מ-`buildCounts` את
  `poolFacets`/`facetCounts`/`updateScenCounts` ב-O(levels×types) במקום סריקות
  חוזרות. לשמור את התוצאה במשתנה-דף (`COUNTS`), לחשב מחדש רק כשהאינדקס משתנה.
  לעדכן טקסט עם `textContent` נקודתי (כבר נעשה חלקית ב-`updateFacetCounts`).
  **שימור התנהגות:** הפלט חייב להיות זהה למימוש הנוכחי — לבנות snapshot.
- **מיקום הפונקציה:** `buildCounts` + הגוזרים הטהורים ל-`_SHARED_JS` (הם צורכים
  `kindOf`/`targetModeOf`/`leadMode` שכבר שם). בדיקה דרך `run_shared`.
- **בדיקות:** `tests/test_home_counts.py` (`run_shared`) — `buildCounts` על index
  fixture, ואז השוואה שהספירות הנגזרות שוות למימוש ה"סורק" הישן על אותו fixture
  (parity). **הערה (ביקורת):** `TYPE_NAMES` = `window.TAXONOMY_HE || {}` (1363) —
  ה-harness חייב להזריק `window.TAXONOMY_HE` (או לבדוק ספירות types בלבד) אחרת
  ספירות ה-types יתמוטטו. `test_home_filters.py` קיים עובר.
- **סיכון:** נמוך-בינוני. **קוד ריוויו** בסוף.

#### 75 (BUG-10) — קוד מת + .headline כפולה
- **מיקום (מאומת חלקית):** `saveStore` no-op, `it.correct` ב-
  `renderSessionSummary`, הגדרות `.headline` כפולות ב-`_CSS`. לאמת מיקומים
  מדויקים בזמן המימוש (מספרי השורות בממצא מסבב לפני סבב 2).
- **גישה:** למחוק את `saveStore` ואת כל קריאותיה (grep מוודא 0 קריאות); לפשט
  `(it.correct ? 100 : 40)` ל-`typeof it.score === "number" ? it.score : 40`
  עם הערה; לאחד את הגדרות `.headline` ב-`_CSS`. **מתוקן לפי ביקורת:** יש **שלוש**
  הגדרות `font-size` ל-`.headline` — 288 (18px), 393 (22px), 402 (24px, שכבת ה-v2
  שהיא **המנצחת בפועל**). הכלל המאוחד חייב לשקף **24px + font-weight:800 +
  margin:4px 0** (הערכים האפקטיביים), לא 22px. לאחד גם את `.headline .ok/.no`
  הכפולות (289/394).
- **בדיקות:** string-assert שאין `saveStore` ב-webapp.py; שאין `it.correct`;
  שיש הגדרת `.headline` יחידה (regex count). בדיקות קיימות עוברות.
- **סיכון:** אפסי.

#### 73 (BUG-8) — הסרת קוד guest מת (ראו אימות היקף)
- **מיקום:** `bt-firebase.js` `isGuest` (403); `_SHARED_JS` `refreshAcct`
  (1524-1547).
- **גישה:** להסיר את `isGuest` מ-`BT`; לפשט את `refreshAcct` — הענף היחיד הוא
  "מחובר". להשאיר fallback דק בטוח: `const u = window.BT && window.BT.user();`
  ואם אין `u` (מצב טרום-מוכנות/התנתקות מעבר לגייט) — להציג את התווית הנייטרלית
  `HE.account`. **מתוקן לפי ביקורת:** `HE.guest` נמצא בשימוש גם כ-placeholder
  ההתחלתי ב-`webapp.py:1505` (`<span id="acct-name">' + HE.guest`) — לעדכן גם
  אותו ל-`HE.account` (אחרת נשאר placeholder "אורח" מיושן). בחלון הטרום-`bt-ready`
  יוצג רגעית `HE.account` במקום "התחבר" — מקובל.
- **בדיקות:** string-assert שאין `isGuest` ב-webapp.py/bt-firebase.js;
  `run_shared` שה-`refreshAcct` לא זורק כש-`window.BT.user()` מחזיר null.
- **סיכון:** אפסי-נמוך.

### גל E

#### 67 (UX-A-6) — VS15 לסמלי הסדרות
- **מיקום:** `_SHARED_JS` `SUITS` (1155); `_CSS` `.ss,.sh,.sd,.sc` (153-154).
- **גישה:** להוסיף `\\uFE0E` (VS15) אחרי כל גליף ב-`SUITS`
  (`S:["ss","\\u2660\\uFE0E"]` וכו'); להוסיף `font-variant-emoji: text;` ל-
  `.ss,.sh,.sd,.sc` כרשת ביטחון. לבדוק `fdcompass` (משתמש ב-N/E/S/W, לא בסדרות
  — לא רלוונטי).
- **בדיקות:** `run_shared`/string-assert ש-`suitHtml` פולט `\\uFE0E`; string-assert
  ש-`font-variant-emoji: text` ב-`_CSS`. פונקציה `suitHtml` נבדקת שלא נשברה.
- **סיכון:** אפסי.

#### 66 (UX-A-5) — isolate LTR ל-EV/מספרים חתומים
- **מיקום:** `_CSS` `.opt .ev` (322 `.opt .ev small`), `.barval` (386);
  `_problem_html` `evHtml`→`<span class="ev">` (2133); `_LEAD_JS`
  `fmtPrimary`→`.barval` (2693, 2702).
- **גישה:** להוסיף `.opt .ev { direction: ltr; unicode-bidi: isolate; }` ו-
  `.barval { direction: ltr; unicode-bidi: isolate; }` (עם התאמת יישור קיימת).
  `.ltr` כבר עוטף הרבה — כאן הכיסוי לשני האתרים שאינם עטופים. לאמת שאין רגרסיה
  ליישור (`.barval text-align:right`).
- **בדיקות:** הרחבת `test_hebrew_ui.py`/string-assert על `_CSS` ש-`.opt .ev` ו-
  `.barval` מקבלים `unicode-bidi: isolate`.
- **סיכון:** אפסי.

#### 69 (UX-A-8) — aria-pressed לבורר דרגת הקושי
- **מיקום:** `_index_html` `applyFilterUi` (1771-1772 — כרגע רק
  `classList.toggle("active")`); `diff-seg` נבנה ב-`renderStats`/`updateScenCounts`
  (1718-1726). `.typerow` כבר מקבל `aria-pressed` (1774).
- **גישה:** בבניית כפתורי `#diff-seg` להוסיף `aria-pressed`; ב-`applyFilterUi`
  להוסיף `b.setAttribute("aria-pressed", ...)` לצד ה-`active`. לחזק סימון חזותי
  (וי/מסגרת) שלא יישען על גוון בלבד — להוסיף כלל CSS ל-`#diff-seg
  button[aria-pressed="true"]`.
- **בדיקות:** string-assert ש-`applyFilterUi` קורא `setAttribute("aria-pressed"`
  על כפתורי diff-seg; `test_home_filters.py` עובר.
- **סיכון:** אפסי.

#### 68 + 92 (UX-A-7 + UX-I-9) — radiogroup תקין
- **מיקום:** `_index_html` markup (1596-1613: `scengrid` role=radiogroup, שני
  `scencard` role=radio tabindex=0, ו-`modecard` MP/IMP **מקוננים בתוך** כרטיס
  ה-lead); handlers (`setScenario` 1658, keydown 1735-1742, modecard onclick
  1686). `.scengrid`/`.scencard`/`.modepills` ב-`_CSS` (562-588).
- **גישה:**
  1. **הוצאת ה-modecard מהכרטיס:** להעביר את `#modes` (1607-1613) **וגם**
     `#modegoal` (1614) אל **מתחת** ל-`scengrid` (מחוץ ל-`role="radio"` שנפתח
     ב-1603 ונסגר ב-1615), מוצג רק כשתרחיש lead נבחר. **⚠ (ביקורת):** צימוד ה-
     `visibility:hidden` לשימור-גובה ב-`setScenario` יידרש לבדיקה מחדש אחרי
     ההעברה. כך אין אלמנט אינטראקטיבי בתוך widget אינטראקטיבי.
  2. **roving tabindex + חצים:** כרטיס נבחר `tabindex=0`, האחר `tabindex=-1`;
     טיפול ב-ArrowLeft/Right/Up/Down שמעביר בחירה+פוקוס; Enter/Space כבר קיים.
- **סיכון:** בינוני-נמוך (רגרסיית layout). **בדיקות:** `test_hebrew_ui.py`/
  string-assert על ה-markup (modecard מחוץ ל-`role="radio"`; roving tabindex);
  `node --check` על הדף. **קוד ריוויו** בסוף. **⚠ אימות ידני** בדפדפן מומלץ.

#### 70 (UX-A-9) — overflow-x לטבלאות + breakpoint
- **מיקום:** `_CSS` `table.plain`/`.fulldeal` (325-329, 197); הטבלאות
  `#ctable`/`#rtable` (problem), `#ltable` (lead).
- **גישה:** לעטוף כל טבלה רחבה ב-`<div style="overflow-x:auto">` **או** כלל CSS
  כללי `details > table, .card > table.plain { display:block; overflow-x:auto; }`.
  להוסיף `@media (max-width:380px)` שממקם ב-`.fulldeal` את W/E מתחת ל-N. זהו
  ה-`@media (max-width)` הראשון בקובץ — לוודא שלא מתנגש עם `prefers-color-scheme`.
- **בדיקות:** string-assert על `_CSS` (`overflow-x:auto` על הטבלאות; קיום
  `@media (max-width`); `node --check`/הדפים נבנים.
- **סיכון:** נמוך.

#### 93 (UX-A-10) — טוקנים + שטח מגע
- **מיקום:** `_CSS` `.alllink` (86-88), `.infot`/`.gloss` (554-562);
  ארבע פלטות טוקן (`body` 60-77, `@media dark` 78-…, `[data-theme="light"]` 405,
  `[data-theme="dark"]` 415); צבעים עוקפי-טוקן `#C8102E0A` (`.opt.mine` 274,
  `.barrow.mine` 356).
- **גישה:**
  1. **שטח מגע:** `min-height` ו-padding אנכי ל-`.alllink`/`.infot`/`.gloss`
     (או `::after` עם inset שלילי) — יעד ≥24px (WCAG 2.5.8).
  2. **עוקפי-טוקן:** להחליף `#C8102E0A` ב-`color-mix(in srgb, var(--loss) 4%,
     transparent)`. **מתוקן לפי ביקורת:** יש **שלושה** אתרים — `.opt.mine` (307),
     `table.plain tr.mine td` (308), `.barrow.mine` (391) — לא שניים. כולם מחוץ
     לבלוקי `html[data-theme] body` (test_contrast לא מושפע).
  3. **דדופ טוקנים — זהיר:** **לשמר** את הבלוקים `html[data-theme="light"] body`
     ו-`html[data-theme="dark"] body` (test_contrast תלוי בהם) ואת נוכחות כל
     הטוקנים בתוכם. הדדופ המעשי: לאחד את הכפילות בין `body` (light) ל-
     `[data-theme="light"]` ובין `@media dark` ל-`[data-theme="dark"]` **רק אם**
     אפשר בלי לפגוע בבדיקה — אחרת להסתפק ב-(1)+(2) ולתעד את הדדופ המלא כנקודת
     החלטה (סיכון רגרסיית תמה מול תועלת תחזוקה). **ברירת מחדל: לא לפרק את מבנה
     4-הבלוקים** (עלול לשבור test_contrast ואת קדימות ה-cascade של ה-toggle).
- **בדיקות:** `test_contrast.py` עובר (ללא שינוי מבנה הבלוקים); string-assert
  שאין `#C8102E0A` קשיח; string-assert ל-`min-height` על `.alllink`/`.infot`.
- **סיכון:** בינוני (תמה). **קוד ריוויו** בסוף.

#### 62 + 86 (UX-I-4 + PERF-F-8) — lead skeleton + theme בראש + עקביות
- **מיקום:** `_lead_html` (2957-2993 — `#modebanner`/`#problem` ריקים);
  `_problem_html` skeleton (2008-2010) ו-`_index_html` (1639-1641) כדוגמה;
  `applyTheme` (1400-1409) רץ ב-tail; ההנחיה בהובלה (`_LEAD_JS`).
- **גישה:**
  1. **skeleton:** להוסיף ל-`_lead_html` בלוק `.skl` בתוך `#modebanner`/
     `#problem` (העתקה מדפוס p.html).
  2. **theme בראש:** helper משותף `_theme_head_script()` — snippet inline זעיר
     שמחיל `data-theme`/`data-scale` מ-`localStorage` על `documentElement`
     **לפני** רינדור, ולהוסיפו ל-`<head>` של **כל ארבעת הדפים** (מונע FOUC בכולם;
     מיזעור drift — `applyTheme` ב-tail נשאר למקרה שינוי בהגדרות). *נימוק
     הרחבה לכל הדפים:* ה-FOUC קיים בכל הדפים (כולם מחילים theme ב-tail); PERF-F-8
     נוקב ב-lead.html אך התיקון הנכון הוא בראש כל דף. מתועד כאן במפורש.
  3. **עקביות הנחיות:** להוסיף את שורת ההנחיה ("הקש הכרזה לראות משמעות") גם
     ל-p.html, או להסיר משניהם אחרי תשובה ראשונה — לבחור עקביות. (חלק ה"כרטיס
     אישור בהובלה עם תוכן מועיל" — שיפור אופציונלי; לתעד אם נדחה מטעמי סיכון.)
- **בדיקות:** string-assert שב-`_lead_html` יש `class="skl"`; שכל דף מכיל את
  ה-snippet של `_theme_head_script` ב-`<head>` (לפני `bt-firebase.js`);
  `test_hebrew_ui.py`/`node --check`. אימות ש-`_theme_head_script` תחבירית תקין
  (הוא inline, לא מודול).
- **סיכון:** נמוך.

#### 63 (UX-I-5) — מבוי סתום "0 בעיות" אחרי "נקה"
- **מיקום:** `_index_html` "נקה" ל-levels/types (1803-1812), `persist`
  (1781-1786), `resolveFilters` (1097), CTA "בחר דרגת קושי וסוג" (1880).
- **גישה (מתוקן לפי ביקורת):** **לא לגעת** ב-persist↔resolveFilters —
  `resolveFilters` (1089-1113) **כבר** מרפא ציר ריק ל"הכל" בכוונה (pick מחזיר
  `all.slice()` על קבוצה ריקה, 1104-1105, מתועד) כדי למנוע את מבוי-הסתום בטעינה.
  שינוי זה יבטל את הריפוי המכוון. **הפער האמיתי הוא רק המצב הזמנִי בתוך-הסשן**
  (מיד אחרי "נקה", לפני רענון). לכן: להציג מיד בתוך הפאנל הפתוח שורת הנחיה
  "בחר לפחות דרגה אחת"/"בחר לפחות סוג אחד" כשנוצר מצב 0; ולהמיר את ה-CTA הכבוי
  `<a href="#">` ל-`<button disabled>`/`aria-disabled` (לא נגיש בפוקוס במצב מת).
- **בדיקות:** string-assert על שורת ההנחיה במצב 0 ועל ה-CTA הלא-נגיש;
  `test_home_filters.py` עובר (מאמת שה-self-heal של resolveFilters נשמר).
- **סיכון:** נמוך.

#### 64 (UX-I-6) — דליפת מנגנון ה"סבב"
- **מיקום:** `_SHARED_JS` `bumpSession` (1412-1426), `bt_session` blob;
  `_index_html` `renderSessionSummary` (~1944-1946, מוחק blob ברינדור),
  כניסת סיכום `?summary=1` (~1803-1806).
- **גישה:**
  1. `startedAt` ל-blob; לפסול סבב בן יותר מ-N שעות (קבוע `SESSION_TTL_MS`).
  2. ב-`bumpSession` לוודא התאמת `kind` (ה-blob כבר שומר `kind` — 1936) בין
     הבעיה לסבב; אם לא תואם — לא לספור.
  3. להציג את הסיכום גם בכניסה רגילה לדף הבית כשהסבב הושלם (`count>=SESSION_SIZE`),
     לא רק ב-`?summary=1`.
  4. למחוק את ה-blob רק אחרי אינטראקציה ("עוד סבב"/"סגור"), לא ברינדור — כך רענון
     דף הסיכום לא מעלים אותו.
- **תלות:** `SESSION_SIZE` מ-74 (גל D). לכן גל D לפני חלק זה.
- **בדיקות:** `run_shared` על פונקציה טהורה `sessionCountable(blob, kind, now)`
  (תפוגה + התאמת kind); string-assert שהמחיקה מותנית באינטראקציה.
- **סיכון:** נמוך.

---

## נקודות החלטה למשתמש (לסיכום שלב 5)
1. **PERF-D-5 (59) — נדחה:** אינדקס מצומצם + `meta/counts` דורש כותב producer
   חדש ומיגרציה מתואמת על ה-DB החי (זהה ל-T12/PERF-F-3 שנדחו). ה-cache (T10)
   כבר פותר את עלות הקריאה החוזרת. אין שינוי קוד. לאשר.
2. **PERF-D-8 (88) — מכוסה:** DB-O-6 (סבב 2) כבר ממש reconcile-on-delete דרך
   `getCountFromServer`. גישת ה-`resetAt` doc יתירה. אין שינוי קוד. לאשר.
3. **SEC-A-6 (80) rules + T6-style manual-verify:** אין emulator ב-CI; שינויי
   ה-rules נבדקים סטטית בלבד, אימות סמנטי ידני מול emulator מקומי. לאשר.
4. **UX-A-10 (93) דדופ טוקנים מלא — נדחה כברירת מחדל:** פירוק מבנה 4-הבלוקים
   עלול לשבור את `test_contrast` ואת קדימות ה-cascade של toggle התמה; מיושמים
   שטח-מגע + החלפת עוקפי-טוקן בלבד. לאשר/לבקש דדופ מלא כמשימה נפרדת.
5. **PERF-F-8 (86) theme-head בכל הדפים:** ה-snippet מוסף ל-`<head>` של כל 4
   הדפים (לא רק lead), כי ה-FOUC משותף. לאשר.

## בדיקות — סיכום מערך
כל ממצא מסתיים ב: (א) בדיקות ייעודיות עוברות; (ב) code review (subagent) לקבוצה
מלוכדת; (ג) commit תיאורי באנגלית. בסיום הכל — `.venv/bin/pytest -q` מלא. בדיקות
JS דורשות node (מסומנות `needs_node`, נדלגות אם חסר).
קבצי בדיקה חדשים צפויים: `test_read_index_parallel.py` (או הרחבת `test_index_cas`),
`test_client_view.py`, `test_cli_pool.py`, `test_home_counts.py`, והרחבות ל-
`test_publish.py`, `test_firestore_rules.py`, `test_scoring_scale.py`,
`test_bt_logic.py`, `test_home_filters.py`, `test_hebrew_ui.py`, `test_contrast.py`.
