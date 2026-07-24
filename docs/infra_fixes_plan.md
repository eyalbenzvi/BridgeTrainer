# תוכנית ביצוע (v2) — 15 משימות תשתית נבחרות

מסמך זה מתכנן את ביצוע 15 המשימות שנבחרו. **מחוץ להיקף** (לא לפתח): 1 (גיבוי), 5 (XSS), 7 (App Check), 8 (מכסה), 19 (צבע פגיעוּת). גם `bridge_trainer/app/publish.py` (מחולל האתר האנגלי הנפרד, `trainer publish`, שאינו על נתיב הפריסה) — **מחוץ להיקף**; רק `trainer webapp` נפרס (`publish.yml:35`).

**v2** משקף ביקורת עמיתים אדוורסרית שבוצעה מול הקוד. שינויי המפתח מהביקורת מסומנים ⟹.

## מיפוי המשימות

| # | מזהה | תיאור | קבוצה |
|---|---|---|---|
| — | **T0** | ⟹ **חדש:** מודול לוגיקה נטול-side-effects (`bt-logic.js`) + harness בדיקות Node | 0 (תשתית) |
| 2 | ARCH-1 + PERF-F-4 | פיצול webapp.py לנכסים חיצוניים | D (refactor) |
| 3 | PERF-F-1 | preconnect + modulepreload | C |
| 4 | PERF-F-2 + PERF-D-3 | אי-חסימת רינדור על סנכרון attempts | A |
| 6 | DB-M-2 + SEC-C-3 | תיקון כלל size-cap + ולידציית סכמה | B |
| 9 | BUG-2 + DB-O-9 | אמינות שמירה | A |
| 10 | DB-M-4 + DB-O-1 + PERF-D-1 | cache אינדקס מבוסס-חותמת | A |
| 11 | DB-M-3 + DB-O-4 | עדכון meta/index טרנזקציוני | B |
| 12 | DB-O-2 | פיצול אינדקס לפי kind | B |
| 13 | BUG-1 | guard !INDEX | C |
| 14 | BUG-3 | redirect רק ב-popup-blocked | A |
| 15 | PERF-D-2 | prefetch לבעיה הבאה | A |
| 16 | UX-I-1 | טיפול בשגיאות טעינה | C |
| 17 | UX-I-3 | כפתור "נסה שוב" | C |
| 18 | UX-I-2 | תיקון "אורח" + חיווי שגיאה | A/C |
| 20 | UX-A-1 + UX-A-4 | ניגודיות | C |

## סדר ביצוע (מעודכן)

**גל 0:** T0 (תשתית — חובה ראשונה; T14/T9/T10/T4/T15 נשענים עליו לבדיקות)
**גל 1 (סיכון נמוך):** T14 → T13 → T3 → T20 → T16 → T17
**גל 2 (שכבת נתונים, חוזה משותף):** T9 → T4 → T18 → T10 → T15
**גל 3 (שרת/פורמט):** T6 → T11 → T12
**גל 4 (refactor מכני-למחצה, אחרון):** T2

---

## חוזים משותפים (מהביקורת — מוגדרים מראש)

### חוזה ATTEMPTS/אירועים (T9+T4+T15)
- `ATTEMPTS[pid]` מתעדכן **רק אחרי** `setDoc` מוצלח (T9). בכשל — רשומה נכנסת ל-retry queue (`bt_pending_<uid>`) ולא ל-`ATTEMPTS`.
- `start()` קורא `ready(u)` מיד אחרי טעינת cache מקומי; סנכרון רץ ברקע (T4) ומסתיים באירוע `bt-attempts-synced`.
- הדפים מאזינים ל-`bt-attempts-synced` ומחילים מחדש `reveal(prev)` (תשובה עשויה להגיע ממכשיר אחר) — וגם מבטלים prefetch שהתיישן (T15).
- full reconcile **לא מוחק** רשומות pending שטרם נשמרו לשרת.

### חוזה format-version לאינדקס (T10↔T12)
- ל-pointer של האינדקס יתווסף `index_format` (מספר). מפתח ה-cache של T10 יכלול אותו, כך שמעבר לפורמט T12 פוסל אוטומטית cache ישן. סדר פריסה: writer שכותב את שני הפורמטים / דגל, לפני client — יתועד ב-T12.

---

## פירוט משימות

### T0 — מודול לוגיקה נטול-side-effects + harness בדיקות ⟹ חדש
- **בעיה (ביקורת #6):** `bt-firebase.js` מריץ `initializeApp` ומייבא מ-URL של https ברמת-המודול (25-38), כך ש**אי-אפשר** לטעון אותו תחת Node. לכן לא ניתן ל-unit-test את הלוגיקה של T14/T9/T10/T4 כפי שנוסח.
- **גישה:** ליצור `bridge_trainer/web/bt-logic.js` — מודול **ללא** imports של firebase וללא side-effects, שמייצא פונקציות טהורות: `redirectDecision(code)`, `indexCacheDecision(ptr, cachedMeta)`, `mergeAttempts(...)`/`reconcile(...)`, `pendingQueueOps(...)`. `bt-firebase.js` מייבא ממנו וקורא לו. הבדיקות מריצות את `bt-logic.js` תחת Node עם fakes מוזרקים, בדיוק כמו `run_js` ב-`test_scoring_scale.py:63`.
- **packaging:** `bt-logic.js` כבר תפוס ע"י `web/*.js` ב-package-data. להוסיף ל-`_ASSET_FILES` (webapp.py:2985) ולהעתקה ב-`write_app`.
- **החלטת emulator (ביקורת #5):** אין בריפו `firebase.json`/`package.json`/`@firebase/rules-unit-testing`, ו-`publish.yml` מריץ רק `pytest`. **החלטה:** לא להוסיף תשתית emulator (דורשת firebase-tools + Java); T6/T11/T12 יסומנו **high-risk manual-verify**, וב-CI יורצו בדיקות סטטיות בלבד (פרסינג/סכימה) שאינן מאמתות סמנטיקת חוק. מסומן כנקודת החלטה למשתמש.
- **בדיקות:** `tests/test_bt_logic.py` שמריץ את הפונקציות תחת Node.
- **סיכון:** נמוך. **קוד ריוויו** בסיום.

### T14 — redirect רק ב-popup-blocked (BUG-3)
- **קובץ:** `bt-firebase.js:90-95` + `bt-logic.js` (T0).
- **גישה:** `redirectDecision(code)` ב-bt-logic מחזיר `true` רק ל-`auth/popup-blocked`/`auth/operation-not-supported-in-this-environment`. ב-`popup-closed-by-user`/`cancelled-popup-request` — לחזור בשקט. שגיאה אחרת — להחזיר error ל-T18.
- **בדיקות:** `test_bt_logic.py` — טבלת codes→decision.

### T13 — guard !INDEX (BUG-1)
- **קובץ:** `webapp.py` — `setScenario` (~1495), מאזין `.modecard` (~1517), `.scencard` (~1735).
- **גישה (ביקורת #12):** ה-guard **לא** יבוטל early-click בשקט: לשמור את ה-kind שנלחץ ל-localStorage (`SCEN_KEY`) **לפני** ה-guard, כך ש-`init()` (הקורא `SCEN` מ-localStorage ב-1487/1725) יחיל את הבחירה הנכונה כשיסיים; רק החלק שנוגע ב-`INDEX` (`resolveFilters`/`renderStats`) נחסם עד שנטען.
- **בדיקות:** בדיקת מחרוזת שה-guards קיימים + בדיקה ידנית בטעינה איטית.

### T3 — preconnect + modulepreload (PERF-F-1)
- **קובץ:** ראשי כל התבניות; helper `_head_preloads()`.
- **גישה:** `preconnect` ל-gstatic (עם `crossorigin`) ול-firestore.googleapis.com; `modulepreload` ל-3 מודולי ה-SDK **עם `crossorigin`** (ביקורת #20 — fetch מודול חוצה-מקור). הערה: התלויות הפנימיות של ה-SDK לא נטענות מראש → רווח חלקי. הכתובות נגזרות ממקור יחיד המשותף עם bt-firebase.js (בדיקת drift).
- **בדיקות:** כל דף מכיל את ה-links; הכתובות תואמות ל-bt-firebase.js.

### T20 — ניגודיות (UX-A-1, UX-A-4)
- **קובץ:** `webapp.py:_CSS`.
- **גישה:** טוקנים `--on-accent`/`--on-win` והחלפת `#fff` קשיח; תיקון hex שנכשלים ב-AA. (publish.py מחוץ להיקף — לא נוגעים ב-`#fff` שלו.)
- **בדיקות:** בדיקת פייתון שמחלצת זוגות צבע מ-`_CSS` ומחשבת יחס WCAG ≥4.5:1; ידני בשתי תמות.

### T16 — טיפול בשגיאות טעינה (UX-I-1)
- **קובץ:** `webapp.py` — init של p/lead + `#next`.
- **גישה:** try/catch סביב `getProblem`/`fetchIndex`; מצב `.state` עם הבחנה offline/שגיאה + כפתור "נסה שוב" שקורא שוב ל-`init()` (וגם מרנדר תרחישים; `updateScenCounts` מוגן ב-`!INDEX`). לתקן את הודעת "המאגר עדיין נבנה" שתבחין בין ריק לשגיאת רשת.
- **בדיקות:** בדיקת DOM עם getProblem שנכשל; ידני offline.

### T17 — כפתור "נסה שוב" (UX-I-3)
- **קובץ:** `webapp.py` — choose/commit/init/דשבורד.
- **גישה (ביקורת #14):** כפתור "נסה שוב (לא ישפיע על הציון)" שמאפס UI ומתעד דרך `BT.record` (attemptCount עולה, ציון ראשון נשמר). **חשוב:** ה-retry **לא** יקרא ל-`bumpSession` ולא ייצור רשומת session (למניעת ניפוח אגרגטים), ו-auto-reveal (2257) ייחסם ב-`?retry=1`.
- **בדיקות:** זרימת retry; אימות ציון-ראשון נשמר, attemptCount עולה, session לא גדל.

### T9 — אמינות שמירה (BUG-2, DB-O-9)
- **קובץ:** `bt-firebase.js:record`/`preloadAttempts` + `bt-logic.js`.
- **גישה:** ראה "חוזה ATTEMPTS". עדכון cache רק אחרי `setDoc`; retry queue `bt_pending_<uid>`; reconcile לא מוחק pending; אירוע `bt-save-failed` ל-toast. הלוגיקה הטהורה (החלטת reconcile/pending) ב-bt-logic.
- **בדיקות:** `test_bt_logic.py` — כשל setDoc לא מעדכן cache, pending נשמר/מנוסה, reconcile לא מוחק pending.

### T4 — אי-חסימת רינדור (PERF-F-2, PERF-D-3)
- **קובץ:** `bt-firebase.js:start`/`preloadAttempts`.
- **גישה:** ראה "חוזה ATTEMPTS". `ready(u)` מיד אחרי cache מקומי; סנכרון ברקע + `bt-attempts-synced`; full reconcile ב-`requestIdleCallback`. הדפים מחילים reveal מחדש על האירוע.
- **בדיקות:** רצף אירועים ב-bt-logic; ידני זמן-לבעיה.

### T18 — טקסט "אורח" + חיווי שגיאה (UX-I-2, חופף BUG-8)
- **היקף (ביקורת #— אושר):** (א) תיקון/הסרת `guestNote` (webapp.py:788) ויישור `BT.isGuest`; (ב) חיווי שגיאה בעברית בשער (נשען על T14) + retry; (ג) שורת תועלת/דוגמה בשער. **מחוץ להיקף:** מצב אורח מלא (localStorage) — סותר "sign-in required", high-risk; נקודת החלטה למשתמש.
- **בדיקות:** חיווי שגיאה; אין טקסט "אורח" מטעה.

### T10 — cache אינדקס מבוסס-חותמת (DB-M-4, DB-O-1, PERF-D-1)
- **קובץ:** `bt-firebase.js:fetchIndex` + `bt-logic.js`.
- **גישה:** לקרוא pointer בלבד (1 read), להשוות `updated_at`/`count`/`index_format` (חוזה format-version) ל-`bt_index_meta` ב-localStorage. ללא שינוי → אינדקס מ-`bt_index_cache`. שינוי → shards **במקביל** (`Promise.all`, כולל PERF-D-4) ושמירה. תאימות: single-doc legacy נתמך.
- **בדיקות:** `test_bt_logic.py` — pointer ללא שינוי→1 read; שינוי→shards; legacy→נתיב ישן.

### T15 — prefetch לבעיה הבאה (PERF-D-2)
- **קובץ:** `webapp.py` — `#next`/init.
- **גישה (ביקורת #13,15):** אחרי `BT.record` (post-record, כדי שהבעיה שנענתה תוחרג מ-`pickUnseen`), לבחור {nid, doc} עם **פילטרי ה-session** (אותו ענף כמו 2250-2252), לשמור ב-`sessionStorage`; `#next` **צורך את ה-nid השמור** במקום לחשב מחדש. אם ה-nid התיישן (נראה עקב סנכרון בין-מכשירי / `bt-attempts-synced`) — לבחור מחדש. הבהרה: `INDEX` הוא משתנה-דף; cache ה-BT (T10) הוא ב-localStorage — נפרדים.
- **בדיקות:** prefetch נשמר ונצרך; התיישנות → בחירה מחדש; ידני.

### T6 — כלל size-cap + ולידציה (DB-M-2, SEC-C-3) — high-risk manual-verify
- **קובץ:** `firestore.rules`, בדיקה סטטית ב-tests.
- **גישה (ביקורת #1-4):**
  - **למקד** את הוולידציה ב-`match /users/{uid}/attempts/{pid}` ולהשאיר כלל גנרי לשאר `/users/{uid}/{doc=**}` (לא לשבור מסמכים שאינם attempts).
  - **קבוצת השדות המלאה** (איחוד `meta()`+`gradeBidding`+`gradeLead`+`record()`): `problemId, problemVersion, scoringForm, kind, type, difficultyLevel, answer, chosenCall, correct, outcomeClass, gradedCost, score, acceptedSet, trainingMode, rankingMetric, chosenRank, recommendedLead, primaryValue, isFirstAttempt, attemptCount, ts, lastTs` — `keys().hasOnly([...])` על האיחוד (כולל `lastTs` שקיים רק ב-merge).
  - **בדיקות טיפוס** רק על שדות שלעולם אינם null: `answer is string`, `score is number`, `correct is bool`. לשאר: `!(field in data) || data[field] == null || data[field] is T`.
  - להחליף `request.resource.size()` (API לא-חוקי) ב-`request.resource.data.size() < 25` (ספירת שדות) + תקרות אורך מחרוזת (`answer.size() < 16`, `acceptedSet.size() < 40`, ...) נגד balloon-ing בבתים.
- **בדיקות:** בדיקה סטטית של תחביר/סכימת הכלל; **אימות ידני** מול emulator מקומי (מתועד). CI לא מאמת סמנטיקת חוק.

### T11 — עדכון meta/index טרנזקציוני (DB-M-3, DB-O-4) — high-risk manual-verify
- **קובץ:** `firestore_store.py:write_index`/`push_local_pool`/backfills.
- **גישה (ביקורת #17):** המרוץ ההיסטורי כבר מצומצם ברמת ה-workflow (`forge-leads.yml:58` `concurrency`); הסיכון הנותר הוא forge מול push/backfill ידני. פתרון: שדה `generation` מונוטוני על ה-pointer + optimistic-locking (סירוב+retry אם השתנה). shards ב-batch כרגיל, pointer מוחלף אחרון עם בדיקת generation (טרנזקציה לא מכסה >500 פעולות shard).
- **בדיקות:** אין תפר הזרקה/emulator → בדיקת יחידה על לוגיקת ה-generation-compare בלבד; אימות ידני. מסומן שהסיכון מצומצם.

### T12 — פיצול אינדקס לפי kind (DB-O-2) — high-risk
- **קובץ:** `firestore_store.py`, `store.py:index_from_entries`, `bt-firebase.js`/`bt-logic.js`, שימושי `INDEX.problems` ב-webapp.py.
- **גישה:** pointer עם `index_format` (חוזה T10↔T12) המפנה ל-shards per-kind + `meta/counts` קטן לספירות דף הבית; קליינט מוריד רק את פרוסת ה-kind. שדות רשומה מצומצמים. **תאימות:** קריאת פורמט ישן (single-doc + sharded אחיד) עד מיגרציה. **סדר פריסה** (מתועד): writer שכותב `index_format` + נתיב קריאה תואם-שני-פורמטים בקליינט מוטמע לפני המיגרציה.
- **בדיקות:** round-trip write→read בפייתון; קריאת פורמט חדש+ישן ב-bt-logic; ספירות `meta/counts` תואמות.

### T2 — פיצול webapp.py (ARCH-1, PERF-F-4) — מכני-למחצה, אחרון
- **קובץ:** `webapp.py` → `web/app.css`, `web/bt-shared.js`, `web/bt-score.js`, `web/bt-lead.js`, `web/bt-dashboard.js` + תבניות; `write_app`, `_ASSET_FILES`, `pyproject.toml`.
- **גישה (ביקורת #7,8,10):**
  - **עיתוי ריצה:** לא להשאיר קוד ספציפי-לדף inline (קלאסי, רץ בזמן parse) כשהפונקציות שהוא קורא עברו ל-`defer` חיצוני → ReferenceError. **להעביר גם את קוד הדף ל-defer/קובץ**, ולסמוך על ה-guard הקיים `if(window.BT) start(); else on('bt-ready')` (webapp.py:1807-1808) לסדר מול המודול. אימות ב**הרצת דפדפן אמיתית**, לא רק שקילות DOM.
  - **שימור קבועי Python:** `_SCORE_JS`/`_SHARED_JS` נשמרים כקבועים שנכתבים לקבצים, כדי ש-`run_js` (test_scoring_scale.py) עדיין ייבא אותם.
  - **בדיקות קיימות שיישברו ויתעדכנו:** `test_scoring_scale.py:189` (מחרוזת `btScoreBidding(...)` inline → יהפוך ל-src), `test_hebrew_ui.py:97` (חילוץ `<script>` inline → `node --check` על הקבצים החיצוניים).
  - **packaging (ביקורת #10):** להוסיף `web/*.css`, `web/*.html` ל-`pyproject.toml` package-data (כרגע רק `web/*.js`); להרחיב `_ASSET_FILES` ו-copy ב-`write_app`; בדיקה שמאמתת פתרון משאב **מותקן** (לא רק editable — `pip install -e` ממסך את הבאג).
- **בדיקות:** שקילות תוכן לוגי + כל `test_webapp_*`/`test_hebrew_ui`/`test_home_filters` עוברים; נכסים נכתבים ומקושרים; **הרצת דפדפן** של שלושת המסכים.

---

## נקודות החלטה למשתמש
1. **T18:** מצב אורח מלא (localStorage ללא התחברות)? כרגע מחוץ להיקף (סותר "sign-in required"). ברירת מחדל: לא.
2. **בדיקות T6/T11/T12:** אין תשתית emulator בריפו. ברירת מחדל: manual-verify מקומי + בדיקות סטטיות ב-CI, ללא הוספת תשתית firebase-tools/Java. אפשר להוסיף כמשימת-תשתית נפרדת אם תרצה כיסוי CI מלא.
3. **T12:** מיגרציית פורמט האינדקס דורשת ריצת push/backfill על ה-DB החי בתיאום עם פריסת הקליינט — סדר יתועד ויבוצע בזהירות.
