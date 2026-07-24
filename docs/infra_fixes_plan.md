# תוכנית ביצוע — 15 משימות תשתית נבחרות

מסמך זה מתכנן את ביצוע 15 המשימות שנבחרו מתוך 20 החמורות. **מחוץ להיקף** (לא לפתח): 1 (גיבוי), 5 (XSS), 7 (App Check), 8 (מכסה), 19 (צבע פגיעוּת).

## מיפוי המשימות למזהי הממצאים

| # מקורי | מזהה ממצא | תיאור קצר | קבוצת עבודה |
|---|---|---|---|
| 2 | ARCH-1 + PERF-F-4 | פיצול webapp.py לנכסים חיצוניים | C (refactor) |
| 3 | PERF-F-1 | preconnect + modulepreload | C |
| 4 | PERF-F-2 + PERF-D-3 | לא לחסום רינדור על סנכרון attempts | A (data-layer) |
| 6 | DB-M-2 + SEC-C-3 | תיקון כלל size-cap + ולידציית סכמה | B (rules) |
| 9 | BUG-2 + DB-O-9 | אמינות שמירה — cache רק אחרי setDoc | A |
| 10 | DB-M-4 + DB-O-1 + PERF-D-1 | cache אינדקס מבוסס-חותמת | A |
| 11 | DB-M-3 + DB-O-4 | עדכון meta/index טרנזקציוני | B |
| 12 | DB-O-2 | פיצול אינדקס לפי kind | B |
| 13 | BUG-1 | guard !INDEX בכרטיסי תרחיש/מצב | A/C |
| 14 | BUG-3 | redirect רק ב-popup-blocked | A |
| 15 | PERF-D-2 | prefetch לבעיה הבאה | A |
| 16 | UX-I-1 | try/catch + מסך שגיאה/retry | C |
| 17 | UX-I-3 | כפתור "נסה שוב" בבעיה שנענתה | C |
| 18 | UX-I-2 | תיקון טקסט "אורח" + חיווי שגיאת התחברות | A/C |
| 20 | UX-A-1 + UX-A-4 | טוקני ניגודיות + תיקוני hex | C |

---

## עקרונות רוחביים

1. **תאימות לאחור לנתונים קיימים.** ה-DB החי מכיל רשומות schema-1/2 ואינדקס בפורמט single-doc/sharded. כל שינוי פורמט (12) חייב לקרוא גם את הפורמט הישן, וכל שינוי חוקים (6) חייב לא לשבור רשומות attempts קיימות.
2. **אין רגרסיית פלט לא-מכוונת.** במשימה 2, פלט ה-HTML של כל דף (מלבד חילוץ הנכסים) חייב להיות שקול תוכנית לגרסה הנוכחית; נוודא ע"י בדיקת שקילות.
3. **בדיקות לכל משימה** נכתבות לפני/במקביל לפיתוח ורצות בסיומה; `pytest -q` חייב לעבור לפני כל commit. בדיקות ה-JS רצות תחת Node כפי שכבר נהוג (`_SCORE_JS` נבדק כך).
4. **code review בסוף כל משימה** ע"י סוכן חיצוני; ממצאים מטופלים לפני מעבר למשימה הבאה.
5. **commit לכל משימה** בנפרד על הענף `claude/website-infrastructure-review-y4v7r8`, הודעה תיאורית. ללא מיזוג עד אישור.

---

## סדר ביצוע מומלץ (מהנמוך-סיכון לגבוה)

**גל 1 — תיקונים מבודדים (סיכון נמוך):** 14 → 13 → 3 → 20 → 16 → 17
**גל 2 — שכבת נתונים בקליינט:** 9 → 4 → 18 → 10 → 15
**גל 3 — צד שרת/פורמט (דורש תיאום client+writer):** 6 → 11 → 12
**גל 4 — refactor מבני (אחרון, מכני):** 2

הרציונל: 2 (פיצול webapp.py) אחרון כדי שכל תיקוני ההתנהגות ב-webapp.py כבר יהיו במקומם, וה-2 יישאר חילוץ מכני בלבד. 12 (פיצול אינדקס) אחרי 10/11 כי הוא נשען על מנגנון ה-cache והכתיבה הטרנזקציונית.

---

## פירוט משימות

### T14 — redirect רק ב-popup-blocked (BUG-3)
- **קובץ:** `bridge_trainer/web/bt-firebase.js:90-95`
- **גישה:** ב-`doSignIn`, לבדוק `e.code`. לבצע `signInWithRedirect` רק ב-`auth/popup-blocked` ו-`auth/operation-not-supported-in-this-environment`. ב-`auth/popup-closed-by-user`/`auth/cancelled-popup-request` — לחזור בשקט (לא redirect). שגיאה אחרת — להחזיר את ה-error כדי ש-T18 יציג חיווי.
- **סיכון:** נמוך. **בדיקות:** בדיקת Node שמדמה `doSignIn` עם provider מזויף שזורק codes שונים ומוודאת את הענף שנבחר (חילוץ הלוגיקה לפונקציה טהורה `redirectDecision(code)` הניתנת לייבוא/בדיקה).

### T13 — guard !INDEX (BUG-1)
- **קובץ:** `bridge_trainer/app/webapp.py` — `setScenario` (~1495), מאזין `.modecard` (~1517), מאזיני `.scencard` (~1735).
- **גישה:** בראש `setScenario` ובמאזין ה-modecard: `if (!INDEX) return;` (עקבי ל-`deal.onclick` הקיים ב-1751). לשמר את הבחירה ולהחילה כש-`init()` מסיים (דגל pending scenario) כדי שלחיצה מוקדמת לא תיבלע.
- **סיכון:** נמוך. **בדיקות:** בדיקת DOM תחת Node/jsdom או בדיקת מחרוזת שמאמתת שה-guards קיימים; בדיקה ידנית של תרחיש טעינה איטית.

### T3 — preconnect + modulepreload (PERF-F-1)
- **קובץ:** `webapp.py` — ראשי כל התבניות (`_index_html`, `_problem_html`, `_lead_html`, `_dashboard_html`).
- **גישה:** להוסיף ל-`<head>`: `<link rel="preconnect" href="https://www.gstatic.com" crossorigin>`, `<link rel="preconnect" href="https://firestore.googleapis.com">`, ו-3 `<link rel="modulepreload">` לקבצי ה-SDK הנעוצים (אותן כתובות מ-bt-firebase.js). לרכז ב-helper `_head_preloads()` כדי למנוע שכפול.
- **סיכון:** נמוך. **בדיקות:** בדיקה שכל דף מכיל את ה-links; בדיקה שהכתובות תואמות בדיוק לאלו שב-bt-firebase.js (בדיקה שמונעת דריפט).

### T20 — ניגודיות: טוקנים + hex (UX-A-1, UX-A-4)
- **קובץ:** `webapp.py` — `_CSS` (סביב 29-58 טוקנים, 470/541-544/589 שימושי #fff, 124/201/433-435 ערכי hex).
- **גישה:** להוסיף טוקנים `--on-accent`/`--on-win` (בהיר: #fff; כהה: כהה) ולהחליף `#fff` קשיח. לתקן ערכי hex שנכשלים ב-AA לפי הממצא (`--on-felt-muted`, `--win` בפסים, `--di`, `a.big.off`). כל שינוי מאומת מול יחס 4.5:1.
- **סיכון:** נמוך-בינוני (ויזואלי בשתי תמות). **בדיקות:** בדיקת יחידה בפייתון שמחשבת יחס ניגודיות WCAG על זוגות (טקסט/רקע) שחולצו מ-`_CSS` ומאמתת ≥4.5:1; בדיקה ידנית ויזואלית בשתי התמות.

### T16 — טיפול בשגיאות טעינת בעיה (UX-I-1)
- **קובץ:** `webapp.py` — `init()` של `_problem_html` (~2188) ו-`_lead_html` (~2499/2618), ומאזין `#next` (2246, 2586).
- **גישה:** לעטוף `getProblem`/`fetchIndex` ב-try/catch; לרנדר קומפוננטת `.state` קיימת עם הבחנה: `navigator.onLine===false` → "אין חיבור" + כפתור "נסה שוב" שקורא שוב ל-`init()`; שגיאה אחרת → הודעה כללית + קישור הביתה. לתקן את ההודעה המטעה בדף הבית ("המאגר עדיין נבנה") שתבחין בין ריק לבין שגיאת רשת.
- **סיכון:** נמוך. **תלות:** חופף ל-T17 (retry). **בדיקות:** בדיקת DOM שמזריקה `getProblem` שנכשל ומוודאת שמוצג מצב שגיאה + כפתור; ידני offline.

### T17 — כפתור "נסה שוב" בבעיה שנענתה (UX-I-3)
- **קובץ:** `webapp.py` — `choose`/`commit` (2092/2465), `init` reveal (2257), דשבורד (2887-2899); `bt-firebase.js:record` כבר תומך ב-`attemptCount`.
- **גישה:** בבעיה שנענתה להציג כפתור "נסה שוב (לא ישפיע על הציון)" שמאפס מצב UI (מסתיר verdict, משחרר כפתורים) ומתעד דרך `BT.record` (הניסיון החוזר לא מזהם סטטיסטיקה כי `isFirstAttempt` נשמר). קישור מהדשבורד עם `?retry=1` שמדלג על reveal אוטומטי.
- **סיכון:** נמוך-בינוני. **בדיקות:** בדיקת DOM לזרימת retry; אימות שהציון הראשון נשמר ו-attemptCount עולה.

### T9 — אמינות שמירה (BUG-2, DB-O-9)
- **קובץ:** `bt-firebase.js:record` (287-310), `preloadAttempts` (127-174).
- **גישה:** לעדכן את `ATTEMPTS`/`saveCache` **רק אחרי** `await setDoc` מוצלח. בכשל: לשמור רשומה ב-retry queue מקומי (`bt_pending_<uid>`) עם דגל `_dirty`, ולנסות שוב ב-`preloadAttempts`; לא לתת ל-full reconcile למחוק רשומות pending שטרם נשמרו. לפלוט אירוע `bt-save-failed` שהדפים יציגו כ-toast עדין.
- **סיכון:** בינוני (משנה סדר פעולות בנתיב חם). **בדיקות:** בדיקת Node עם `setDoc` מזויף שנכשל/מצליח, מוודאת: לא מתעדכן cache בכשל, pending נשמר ומנוסה שוב, reconcile לא מוחק pending.

### T4 — אי-חסימת רינדור על סנכרון (PERF-F-2, PERF-D-3)
- **קובץ:** `bt-firebase.js:start` (326-341), `preloadAttempts` (127-174).
- **גישה:** לטעון cache מ-localStorage סינכרונית ולקרוא `ready(u)` מיד; להריץ את הסנכרון (incremental/full) ברקע ולפלוט `bt-attempts-synced` שמרענן סטטיסטיקות/reveal. את ה-full reconcile להעביר ל-`requestIdleCallback`. הדפים: להחיל `reveal(prev)` גם על אירוע הסנכרון (כי ייתכן שהתשובה הגיעה ממכשיר אחר).
- **סיכון:** בינוני (ריצת מרוץ בין רינדור לסנכרון — טיפול ע"י re-apply). **בדיקות:** בדיקת Node לרצף האירועים; ידני: זמן-לבעיה-ראשונה.

### T18 — טקסט "אורח" + חיווי שגיאת התחברות (UX-I-2, חופף BUG-8)
- **היקף:** מיקוד בחלקים בטוחים ובעלי ערך: (א) תיקון/הסרת `guestNote` השקרי (webapp.py:788) ויישור `BT.isGuest`; (ב) חיווי שגיאה בעברית בתוך השער כששני מסלולי ההתחברות נכשלים (נשען על T14) + כפתור ניסיון חוזר; (ג) שורת תועלת/דוגמה בשער. **מחוץ להיקף:** מצב אורח מלא עם נתונים ב-localStorage — סותר החלטת עיצוב מפורשת ("sign-in is REQUIRED") ובסיכון גבוה; יידרש אישור מוצר נפרד (מסומן כשאלת החלטה בסיכום).
- **קובץ:** `bt-firebase.js` (gate 97-125, doSignIn 90-95, start 326-341), `webapp.py:788`.
- **סיכון:** נמוך. **בדיקות:** בדיקת Node לחיווי שגיאה; בדיקת מחרוזת שאין יותר טקסט "אורח" מטעה.

### T10 — cache אינדקס מבוסס-חותמת (DB-M-4, DB-O-1, PERF-D-1)
- **קובץ:** `bt-firebase.js:fetchIndex` (263-277).
- **גישה:** לקרוא קודם את מסמך ה-pointer בלבד (1 read) ולהשוות `updated_at`/`count` לחותמת ב-localStorage (`bt_index_meta`). אם לא השתנה — להחזיר אינדקס מ-cache מקומי (`bt_index_cache`) בלי קריאת shards. אם השתנה — להוריד shards (במקביל, `Promise.all` — כולל PERF-D-4 שנחוץ פונקציונלית) ולשמור. תאימות לאחור: single-doc legacy עדיין נתמך.
- **סיכון:** בינוני. **בדיקות:** בדיקת Node עם getDoc מזויף: pointer ללא שינוי → 1 read; שינוי → shards; legacy → נתיב ישן.

### T15 — prefetch לבעיה הבאה (PERF-D-2)
- **קובץ:** `webapp.py` — `#next` (2246, 2586), `init`.
- **גישה:** צעד ביניים זול (לא SPA מלא): מיד אחרי מענה, לבצע `getProblem(nid)` ברקע ולשמור ב-`sessionStorage`; לחיצת "הבא" תשתמש בו אם קיים. INDEX נשמר ב-sessionStorage (מ-T10) כך שהלחיצה לא ממתינה לרשת. בחירת ה-nid מ-`pickUnseen` הקיים.
- **סיכון:** נמוך-בינוני. **בדיקות:** בדיקת DOM/Node שמוודאת prefetch נשמר ונצרך; ידני.

### T6 — תיקון כלל size-cap + ולידציה (DB-M-2, SEC-C-3)
- **קובץ:** `firestore.rules:32-36`, בדיקות ב-`tests/test_firestore_safe.py`/חדש.
- **גישה:** לבדוק ב-emulator אם הכלל הנוכחי בכלל עובר. להחליף `request.resource.size()` ב-`request.resource.data.size() < N` (ספירת שדות) + ולידציה: `keys().hasOnly([...])`, בדיקות טיפוס (`answer is string`, `score is number`), ותקרת אורך למחרוזות. חובה לבדוק מול הרשומה שכותב `record()` ב-bt-firebase.js (השדות: problemId, answer, chosenCall, correct, outcomeClass, gradedCost, score, acceptedSet, trainingMode, ... + attemptCount, ts, lastTs, isFirstAttempt) ומול עדכון ה-merge, כדי לא לשבור כתיבות קיימות.
- **סיכון:** גבוה אם קפדני מדי (עלול לחסום שמירה). **בדיקות:** חבילת בדיקות emulator (`@firebase/rules-unit-testing`) — כתיבות תקינות עוברות, זדוניות/גדולות נחסמות, merge של re-answer עובר. אם emulator לא זמין בסביבה — לתעד ולהריץ מקומית + בדיקת סכימה סטטית.

### T11 — עדכון meta/index טרנזקציוני (DB-M-3, DB-O-4)
- **קובץ:** `firestore_store.py:write_index` (184-220), `push_local_pool` (234-269), backfills (308/347).
- **גישה:** לעטוף read-pointer→union→write בטרנזקציה של Admin SDK, או שדה `generation` מונוטוני עם optimistic-locking (סירוב כתיבה אם השתנה מאז הקריאה, retry). הכתיבה עצמה של shards גדולה מ-500 פעולות — טרנזקציה מוגבלת; לכן generation-guard על ה-pointer עדיף (shards נכתבים ב-batch כרגיל, pointer מוחלף אחרון עם בדיקת generation).
- **סיכון:** בינוני. **בדיקות:** בדיקת פייתון עם Firestore מדומה/emulator שמדמה שני כותבים מקבילים ומוודאת שאין אובדן רשומות.

### T12 — פיצול אינדקס לפי kind (DB-O-2)
- **קובץ:** `firestore_store.py:write_index/read_index`, `store.py:index_from_entries`, `bt-firebase.js:fetchIndex`, ושימושי `INDEX.problems` ב-webapp.py.
- **גישה:** פורמט אינדקס חדש: pointer שמפנה ל-shards לפי kind (`index_bidding_*`, `index_lead_*`), + מסמך `meta/counts` קטן לספירות דף הבית. הקליינט מוריד רק את פרוסת ה-kind הפעיל. שדות רשומה מצומצמים (השמטת `created_at`/`difficulty` מהרשומה, שמירה בפוינטר). **תאימות:** לתמוך בקריאת הפורמט הישן (single-doc + sharded אחיד) עד מיגרציה. נשען על T10 (cache) ו-T11 (כתיבה בטוחה).
- **סיכון:** גבוה (דורש דיפלוי מתואם client+writer + מיגרציה). **בדיקות:** round-trip write→read בפייתון; בדיקת Node לקריאת פורמט חדש+ישן; בדיקת פייתון שמוודאת ספירות `meta/counts` תואמות.

### T2 — פיצול webapp.py לנכסים חיצוניים (ARCH-1, PERF-F-4)
- **קובץ:** `webapp.py` כולו → קבצים תחת `bridge_trainer/web/` (`app.css`, `bt-shared.js`, `bt-score.js`, `bt-lead.js`, `bt-dashboard.js`) + תבניות HTML (מחרוזות דקות או קבצי `.html` עם placeholders). עדכון `write_app` ו-`_ASSET_FILES`, ו-`pyproject.toml` package-data.
- **גישה:** חילוץ מכני: להעביר את `_CSS`→app.css, `_SCORE_JS`/`_SHARED_JS`→bt-score.js/bt-shared.js, `_LEAD_JS`, `_DASHBOARD_JS`; התבניות יקשרו `<link rel="stylesheet">` ו-`<script defer src=...>`. **קריטי:** לשמר את סדר ההרצה המתועד (inline script הריץ `btScoreBidding` לפני המודול bt-firebase.js) — להשתמש ב-`defer` שמכבד סדר, ולוודא ש-`window.btScoreBidding` מוגדר לפני שה-grade נקרא. לבטל את תבנית ה-f-string (הכפלת `{{}}`) לטובת placeholder יחיד (`.replace`).
- **סיכון:** גבוה (הקובץ הגדול והשביר). **בדיקות:** בדיקת שקילות — רינדור הדפים והשוואת ה-DOM/התוכן הלוגי מול הגרסה הישנה; כל הבדיקות הקיימות (`test_webapp_*`, `test_hebrew_ui`, `test_home_filters`) חייבות לעבור; בדיקה שהנכסים החיצוניים נכתבים ומקושרים; הרצת האתר ובדיקה ידנית של שלושת המסכים.

---

## נקודות החלטה למשתמש (יוצגו בסיכום)
1. **T18:** האם לממש מצב אורח מלא (נתונים ב-localStorage ללא התחברות)? כרגע מחוץ להיקף — סותר "sign-in required". ברירת מחדל: לא.
2. **T6/T11/T12:** האם קיימת גישה ל-Firestore emulator בסביבת ה-CI/פיתוח? אם לא, בדיקות ה-rules/טרנזקציה יורצו מקומית ויתועדו, ובדיקות סטטיות ישמשו ב-CI.
3. **T12:** מיגרציית פורמט האינדקס דורשת ריצת push/backfill על ה-DB החי בתיאום עם פריסת הקליינט. סדר הפריסה יתועד.
