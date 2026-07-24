# תוכנית ביצוע — סבב 2 (17 ממצאים)

מסמך זה מתכנן את הביצוע של 17 הממצאים שנבחרו לסבב השני, בעקבות
`docs/website_infrastructure_review.md` (טבלת master) והמוסכמות שהתגבשו ב-
`docs/infra_fixes_plan.md` (סבב 1). כל הפיתוח בברנץ' `claude/bridgetrainer-infra-fixes-round2-mc6v3v`.

## מיפוי הממצאים (לפי # בטבלה => מזהה)

| # | מזהה | קבוצה | תמצית |
|---|---|---|---|
| 39 | BUG-4 | JS-correctness | `.filter(Boolean)` על `v.accepted` — קריסת callHtml |
| 40 | BUG-5 | JS-correctness | `pct`/`safeNum` בטוחים — אין "NaN%" |
| 41 | BUG-6 | JS-correctness | ענף `pts` ל-`terse()` ב-JS (דריפט מ-Python) |
| 37 | ARCH-8 | JS-refactor | איחוד `auctionTableHtml`/`completeAuctionTableHtml` |
| 50 | SEC-A-2 | security | `esc()` שיטתי על שדות Firestore ב-innerHTML |
| 34 | ARCH-5 | single-source | תוויות טקסונומיה ממקור-אמת פייתון יחיד |
| 46 | DB-M-8 | client-data | `unwrapFirestore()` יחיד + תיקון הערת חוזה שגויה |
| 38 | ARCH-9 | client-data | ריכוז נורמליזציית סכמה בקליינט + סקריפט מיגרציה |
| 47 | DB-O-5 | firestore-store | `on_write_error` ב-BulkWriter |
| 43 | DB-M-5 | firestore-store | רישום אינדקס ב-success callback; `remove` מעדכן אינדקס |
| 45 | DB-M-7 | firestore-store | אכיפת schema version + `schema_min`/`schema_max` אמיתיים |
| 48 | DB-O-6 | client-cost | `getCountFromServer` לפני full reconcile |
| 35 | ARCH-6 | py-refactor | מודול `htmlfmt.py` משותף (publish.py/report.py) |
| 36 | ARCH-7 | py-refactor | `BatchState` בסיס משותף (maker/lead_maker) |
| 49 | DB-O-7 | ops | התראת כשל workflow + תיעוד Cloud Monitoring |
| 22 | PERF-F-3 | scope-verify | מקבול shards בוצע (T10); facets — אימות היקף |
| 28 | UX-I-2 | scope-verify | תת-קבוצה בוצעה (T18); guest mode — אימות היקף |

## עקרונות ומוסכמות (מסבב 1, ממשיכים)
- **מקורות אמת:** ה-JS/CSS המוטמעים הם קבועי הפייתון `_SHARED_JS`/`_SCORE_JS`/
  `_LEAD_JS`/`_DASHBOARD_JS`/`_CSS` ב-`webapp.py`. שינויים בהם הם השינוי; `write_app`
  פולט אותם לקבצים חיצוניים בזמן build.
- **בדיקות JS:** מריצות מחרוזות תחת `node` עם `needs_node` (skip אם אין node).
  שני דפוסים קיימים: (א) `run_js` ב-`test_scoring_scale.py` שמריץ את `_SCORE_JS`;
  (ב) `run_logic` ב-`test_bt_logic.py` שמריץ את `bt-logic.js` (ESM עם `export`
  שמופשט). פונקציות DOM-free נוספות ל-`_SHARED_JS` וניתנות לבדיקה באותו דפוס.
- **ייבוא בין קבצי בדיקה:** ה-CI מריץ `pytest` (לא `python -m pytest`), לכן ייבוא
  בין קבצי בדיקה חייב להיות בשם מודול חשוף: `from test_x import ...`, **לא**
  `from tests.test_x import ...`.
- **פרדיגמת בדיקת לוגיקה טהורה:** לוגיקה שאפשר להוציא לפונקציה טהורה עדיף שתיבדק
  ישירות (node), ולא רק בבדיקת-מחרוזת. שדות innerHTML שנבנים בגוף f-string של דף
  (`{{`/`}}`) נבדקים ב-string-assert + בדיקת התנהגות של ה-helper שהם קוראים.

---

## סדר ביצוע (גלים)

הסדר נבחר לפי תלויות ומיזעור התנגשויות עריכה באותם בלוקים.

**גל 1 — נכונות ובטיחות ב-JS של דף הבעיה (`_SHARED_JS` + גוף p.html/lead.html):**
BUG-5(40) → BUG-4(39) → BUG-6(41) → ARCH-8(37) → SEC-A-2(50)
> תלות: BUG-5 מוסיף `safeNum`/`pct` ל-`_SHARED_JS`; BUG-4/ARCH-8/SEC-A-2 נוגעים
> בבלוקים סמוכים. סדר זה ממזער conflicts ומאפשר ל-optRowHtml/chipsHtml לצרוך את
> ה-helpers החדשים. SEC-A-2 אחרון בגל כי הוא הרחב ביותר וצריך לראות את הצורה
> הסופית של auctionTable המאוחד (ARCH-8).

**גל 2 — מקור-אמת לטקסונומיה:** ARCH-5(34)
> עצמאי; נוגע ב-`classify.py`/`lead_classify.py`, הזרקת JSON ב-`write_app`, ו-
> `TYPE_NAMES` ב-`_SHARED_JS`.

**גל 3 — ריכוז צורת-הנתונים בקליינט:** DB-M-8(46) → ARCH-9(38)
> DB-M-8 מוסיף `unwrapFirestore()` ב-`getProblem`; ARCH-9 מרכז את נורמליזציית
> הסכמה (`normalize`/field-sniffing) לנקודה אחת ומספק סקריפט מיגרציה. סדר זה כי
> ARCH-9 בונה על נקודת הפירוק היחידה של DB-M-8.

**גל 4 — שכבת ה-Firestore (Python, `firestore_store.py`):**
DB-O-5(47) → DB-M-5(43) → DB-M-7(45)
> שלושתם נוגעים ב-`push_local_pool`/`write_index`/`add`. סדר: קודם לתפוס כשלי
> כתיבה (DB-O-5), אז לרשום אינדקס רק על הצלחה + `remove` (DB-M-5), אז אכיפת
> סכמה (DB-M-7). נעשים ברצף עם commit ובדיקות לכל אחד.

**גל 5 — עלות קריאה בקליינט:** DB-O-6(48)
> נוגע ב-`_syncAttempts` ב-`bt-firebase.js`; לוגיקת ההחלטה טהורה ב-`bt-logic.js`.

**גל 6 — refactor מבני ב-Python:** ARCH-6(35) → ARCH-7(36)
> עצמאיים זה מזה ומהשאר; אחרונים כי הם הגדולים והמכניים.

**גל 7 — תפעול/ניטור:** DB-O-7(49)
> workflow YAML + תיעוד; ללא שינוי קוד אפליקציה.

**גל 8 — אימות היקף (נקודות החלטה):** PERF-F-3(22) + UX-I-2(28)
> אימות מה שכבר בוצע, ותיעוד מה שנדחה במפורש. פירוט למטה.

---

## פירוט משימות

### BUG-4 (39) — `.filter(Boolean)` על `v.accepted`
- **מיקום:** `webapp.py` `normalize()` (~2305): `v.accepted = v.toss_up ?
  v.toss_up_set : [v.accepted]`. הצריכה: `reveal()` קורא `callHtml(v.accepted[0])`
  (~2109) ו-`callHtml` עושה `tok.slice(1)` → קריסה על `undefined`.
- **גישה:** ליישר עם `btScoreBidding` (שכבר עושה `.filter(Boolean)` ב-`_SCORE_JS`):
  `v.accepted = (v.toss_up ? v.toss_up_set : [v.accepted]).filter(Boolean);`
  ולהוסיף fallback ל-`v.corrected[0].bid` כשהתוצאה ריקה (כמו ב-`gradeBidding`
  ב-`bt-firebase.js:315-316`). כדי שיהיה בר-בדיקה טהורה: להוסיף helper קטן
  `normAccepted(v)` ל-`_SHARED_JS` ולקרוא לו מ-`normalize`.
- **בדיקות:** `tests/test_normalize_shapes.py` (חדש) — `run_js` על `normAccepted`
  עם: accepted מחרוזת, accepted חסר (מחזיר `[]` או fallback), toss_up_set,
  ורשומה שבה accepted ריק אך `corrected[0].bid` קיים → חוזר ה-bid. + assert
  שאין קריסה ב-callHtml על accepted מנורמל.
- **סיכון:** אפסי.

### BUG-5 (40) — `pct`/`safeNum` בטוחים
- **מיקום:** `optRowHtml` (~2069-2073) ו-`chipsHtml` (~2057) מחשבים
  `Math.round(row.p_gain*100)` ו-`width:${row.p_gain*100}%` ללא הגנה; `normalize`
  (~2332) `p_loss: Math.max(0, 1 - r.p_gain - r.p_push)` מחזיר NaN כש-`p_push`
  חסר. טבלת ההשוואה כבר מגדירה `pct` בטוח (~2043 בסבב הקודם).
- **גישה:** להוסיף ל-`_SHARED_JS` שתי פונקציות טהורות: `safeNum(x, d=0)` (מחזיר
  `d` אם `undefined`/`NaN`) ו-`pct(x)` (מחזיר `"—"` אם `undefined`/`NaN`, אחרת
  `Math.round(x*100)+"%"`). ב-`optRowHtml`/`chipsHtml` לעטוף כל `p_gain*100`/
  `p_loss*100` ב-`safeNum(...)` ל-width ולהשתמש ב-`pct(...)` להצגה + ל-aria-label.
  ב-`normalize` לחשב `p_loss` רק כשגם `p_gain` וגם `p_push` מוגדרים, אחרת
  `undefined` מפורש (לא NaN).
- **בדיקות:** `run_js` על `safeNum`/`pct` (undefined, NaN, 0, 0.5, 1); + string-
  assert ש-`optRowHtml`/`chipsHtml` קוראים `safeNum`/`pct`; + `normalize` לא
  מייצר NaN בשורה חסרת `p_push`.
- **סיכון:** נמוך (תצוגה בלבד).

### BUG-6 (41) — ענף `pts` ל-`terse()` ב-JS
- **מיקום:** `terse()` ב-`_SHARED_JS` (~1180-1185) — רק ענף `card.hcp`. `explain.py`
  `terse_meaning` (124-142) כולל fallback ל-`card["pts"]` עם אותו סף `_HCP_OPEN_TOP`.
- **גישה:** להוסיף ל-`terse` את הענף `else if (card.pts)` המשקף בדיוק את פייתון:
  `[lo,hi]=pts; hi>=25 ? (lo>0 && frags.push(lo+"+ pts")) : frags.push(lo+"-"+hi+" pts")`.
  לוודא שהסף (`_HCP_OPEN_TOP`) תואם — לבדוק את הערך ב-`explain.py`.
- **בדיקות:** (א) `run_js` על `terse({pts:[8,8]}, "P")` → `"8- pts"`-שקול,
  `terse({pts:[0,25]}, ...)` וכו'. (ב) בדיקת snapshot חוצה-שפה: להריץ
  `explain.terse_meaning` בפייתון ו-`terse` ב-node על אותה קבוצת cards ולוודא
  שוויון — תופס דריפט עתידי.
- **סיכון:** נמוך.

### ARCH-8 (37) — איחוד טבלת המכרז
- **מיקום:** `_SHARED_JS`: `auctionTableHtml` (~1231-1259) ו-
  `completeAuctionTableHtml` (~1267-1299).
- **גישה:** פונקציה אחת `auctionTable(p, notes, opts)` עם `opts`:
  `{pendingCell:bool, highlightFinal:bool, roleOf:(seat)=>labelOrNull}`.
  ההבדלים הממופים: (א) header — `roleOf(seat)` מחזיר את תווית התפקיד (you/partner
  מול leader/declarer/dummy); (ב) תא `?` בסוף (`pendingCell`); (ג) הדגשת `fin`
  על ה-bid האחרון (`highlightFinal`); (ד) תנאי ה-`expl` (בהכרזה `notes[j]`,
  בהובלה `notes[j].card || notes[j].text`) — יטופל ע"י `noteOf(notes[j])`
  ב-opts. שתי הקריאות הקיימות הופכות ל-wrappers דקים שקוראים ל-`auctionTable`.
  **שים לב:** לשמר את מיקום ה-`?` (בהכרזה יש תא `turn` נוסף לפני ה-padding).
- **בדיקות:** `run_js` שמרנדר את שני המצבים על אותו `p` ומוודא: מספר תאי ה-header,
  נוכחות/היעדר `td.turn`, נוכחות `.fin` רק במצב complete, וזהות מבנית לפלט
  הישן (אם אפשר — לשמור snapshot של הפלט הנוכחי לפני ה-refactor ולהשוות).
- **סיכון:** נמוך (ויזואלי). לצלם snapshot של שתי הפונקציות לפני, להשוות אחרי.

### SEC-A-2 (50) — `esc()` שיטתי
- **מיקום:** נקודות הזרקה של שדות מסמך ל-innerHTML ב-`_SHARED_JS`, גוף p.html,
  `_LEAD_JS`, גוף lead.html, `_DASHBOARD_JS`. נקודות ידועות: `s.teams`/`s.event`/
  `s.board` (~2151-2152), `NOTES[j]` (~2163, ~2411), `row.shows` (~2067),
  `P.explanations.note` (~2144), meanings/seat בהובלה, ושדות `P.source` דומים
  ב-lead.html. **לא לגעת** ב-helpers שמייצרים HTML בכוונה (`callHtml`, `suitHtml`,
  `handHtml`, `contractHtml`) — הם פלט מתוכנן, לא קלט משתמש.
- **גישה:** להוסיף `esc(s)` ל-`_SHARED_JS` (וכן לכל בלוק דף שאינו כולל את
  `_SHARED_JS` — לאמת אילו דפים כוללים אותו) : 
  `s => String(s==null?"":s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))`.
  לעטוף כל אינטרפולציה של **שדה טקסט חופשי ממסמך** ב-`esc(...)`. לתעד כלל קוד
  ("אין `${field}` ממסמך בתוך innerHTML ללא esc").
- **בדיקות:** (א) `run_js` על `esc('<img src=x onerror=alert(1)>')` → escaped.
  (ב) בדיקת DOM בסגנון `test_hebrew_ui.py`: להזריק שדה מסמך מדומה עם
  `<img onerror>` ולוודא שהמחרוזת המיוצרת מכילה `&lt;img` ולא `<img`.
  (ג) string-assert על נקודות ההזרקה המרכזיות שהן עוטפות ב-esc.
- **סיכון:** נמוך (הטקסטים prose ללא markup מכוון). **קוד ריוויו** בסוף.

### ARCH-5 (34) — מקור-אמת לטקסונומיה
- **מיקום:** `webapp.py` `TYPE_NAMES` (~1307-1336) מול `classify.py` `LABELS_HE`
  (76) ו-`lead_classify.py` `LEAD_LABELS_HE` (33). דריפט קיים: "ניסיון סלאם"
  מול "ניסיון סלם"; "החלטת כפל" מול "להכפיל או להכריז"; "סלאם" מול "סלם".
- **גישה:** מקור-אמת = מודולי הטקסונומיה. TYPE_NAMES מחזיק גם **תווית קצרה** וגם
  **טקסט tooltip** (שאלה בעברית). התוויות יבואו מ-`LABELS_HE`/`LEAD_LABELS_HE`.
  ל-tooltip: להוסיף עמודה חמישית "tooltip עברי" ל-`TAXONOMY`/`LEAD_TAXONOMY`
  (או dict `TOOLTIPS_HE`) בפייתון, ולהזריק ב-`write_app` את המילון המאוחד כ-
  JSON לתוך ה-JS (משתנה `TYPE_NAMES` נבנה מה-JSON המוזרק במקום literal). כך
  ה-drift נמנע מבנית.
  - יישום קונקרטי: `write_app` (או `_problem_html`/`_index_html`) יזריק
    `const TAXONOMY_HE = {...JSON...};` וה-`_SHARED_JS` יגזור ממנו את
    `TYPE_NAMES`. יש לוודא שהזרקה נעשית לפני השימוש בכל דף שמשתמש ב-TYPE_NAMES
    (p.html, index.html, dashboard, lead.html).
- **בדיקות:** `tests/test_taxonomy_single_source.py` — (א) מפתחות
  `LABELS_HE`+`LEAD_LABELS_HE` == מפתחות ה-JSON המוזרק; (ב) כל תווית ב-JSON
  == הערך ב-`LABELS_HE`/`LEAD_LABELS_HE` (אין דריפט); (ג) לכל type יש tooltip
  לא-ריק. הבדיקה תופסת קטגוריה חדשה שנוספה בפייתון אך לא ב-UI.
- **סיכון:** נמוך-בינוני (שינוי אופן בניית TYPE_NAMES). **קוד ריוויו** בסוף.

### DB-M-8 (46) — `unwrapFirestore()` יחיד
- **מיקום:** `firestore_store.py` `_firestore_safe` (44-68) — הערה (53) "None of
  these wrapped fields are read by the web client" **שקרית**: `webapp.py`
  `normalize` (~2337-2338) מפרק `top_contracts` (`x => (x&&x.items)?x.items:x`).
- **גישה:** להוסיף `unwrapFirestore(doc)` יחיד ב-`bt-firebase.js` (או ב-
  `bt-logic.js` כפונקציה טהורה, מיובאת ל-bt-firebase) — היפוך מדויק של
  `_firestore_safe`: מעבר רקורסיבי, כל `{items:[...]}` (מפה עם מפתח יחיד `items`
  שהוא מערך) → המערך הפנימי. להחיל ב-`getProblem` על התוצאה. **תאימות:** רשומות
  static-file (מבנה שטוח) נשארות ללא שינוי (unwrap אידמפוטנטי). לתקן/למחוק את
  ההערה השגויה ב-`_firestore_safe`. `normalize` יוכל להסתמך על שדות מפורקים
  (יטופל ב-ARCH-9); בשלב DB-M-8 להשאיר את ה-unwrap ב-normalize (אידמפוטנטי) כדי
  לא לשבור רשומות שלא עברו getProblem בטסטים.
- **בדיקות:** (א) `run_logic` (bt-logic) על `unwrapFirestore`: round-trip מול
  ייצוג של `_firestore_safe` — נבנה קלט עם `{items:[...]}` מקונן ונוודא שחוזר
  המבנה המקורי. (ב) בדיקת פייתון `tests/test_firestore_safe.py` (קיימת) —
  להוסיף בדיקה: `_firestore_safe(rec)` ואז unwrap (חיקוי הלוגיקה) ⇒ זהות.
  (ג) לוודא ש-`{items: [...]}` שהוא נתון לגיטימי (מפה עם מפתח items שאינו wrapper)
  לא נשבר — התנאי: unwrap רק כשהמפה בעלת **מפתח יחיד** `items` שערכו מערך, בתוך
  הקשר של איבר מערך (כפי ש-`_firestore_safe` יוצר). לתעד את המגבלה.
- **סיכון:** נמוך.

### ARCH-9 (38) — ריכוז נורמליזציה + מיגרציה
- **מיקום:** `webapp.py` `normalize()` (~2303), `btScoreBidding` (~640-653),
  `problemModes`/`targetModeOf` (~925-941); field-sniffing מפוזר.
- **גישה (שמרנית, ללא הרצה על DB חי):**
  1. **קליינט:** לרכז את זיהוי-הגרסאות לפונקציה אחת `canonProblem(P)` /
     `normalizeProblem(P)` ב-`_SHARED_JS` שמופעלת מוקדם (אחרי getProblem/
     unwrapFirestore, לפני normalize של הדף), ומייצרת צורה קנונית אחת. הענפים
     הקיימים (`v.table`/`v.corrected`/legacy) עוברים אליה; שאר הקוד קורא צורה
     אחת. **לא** למחוק ענפי legacy בקוד עד שהמיגרציה תרוץ בפועל — רק לרכז.
  2. **producer:** לספק סקריפט מיגרציה חד-פעמי `scripts/migrate_schema.py`
     (dry-run כברירת מחדל) שממיר רשומות לצורה קנונית ומעלה עם `pool push
     --overwrite`. **הסקריפט לא ירוץ על ה-DB החי** במסגרת ה-PR; הוא deliverable
     קוד + בדיקת יחידה על טרנספורמציית הרשומה.
- **הבהרת היקף:** מחיקת ענפי ה-legacy מה-JS דורשת שהמיגרציה תרוץ על production —
  זו נקודת החלטה למשתמש (כמו T12 בסבב 1). ה-PR מספק את התשתית (ריכוז + סקריפט +
  בדיקות) בלי הצעד ההרסני.
- **בדיקות:** `run_js` על `canonProblem` עם שלוש צורות הקלט (raw table, corrected,
  legacy authored) → אותה צורה קנונית; בדיקת פייתון על טרנספורמציית המיגרציה
  (record→canonical) עם fixtures.
- **סיכון:** נמוך לחלק הקוד; הרצת מיגרציה = נקודת החלטה.

### DB-O-5 (47) — `on_write_error` ב-BulkWriter
- **מיקום:** `firestore_store.py` `push_local_pool` (316-353) — `writer =
  remote._db.bulk_writer()` ללא `on_write_error`; `new_entries[pid]` נקבע ב-
  enqueue (326).
- **גישה:** לרשום `writer.on_write_error(handler)` שאוסף `pid` כושל לסט
  `failed`. אחרי `writer.close()`, להסיר את ה-pids הכושלים מ-`new_entries`
  (וממניין `uploaded`) לפני עדכון האינדקס, ולהחזיר בדוח שדה `failed`
  (רשימה/מספר). ה-CLI (`cmd_pool push`) יחזיר exit code שגוי כשיש כשלים כדי
  שה-workflow יאדים. הערה: ה-handler צריך להחזיר `False` (לא re-raise) כדי לא
  לעצור את שאר ה-batch, אבל כן לרשום את הכישלון. **מיפוי pid:** ה-error
  callback מקבל אובייקט עם `.document.path`/`.reference` — לחלץ ממנו את ה-pid
  (document id). לוודא מול ה-API של `bulk_writer` (google-cloud-firestore).
- **בדיקות:** להזריק fake writer (כמו שכבר עושים fake `remote`) ש-`.set` על pid
  מסוים "נכשל" (קורא ל-handler) — ולוודא: ה-pid הכושל **לא** באינדקס שנכתב,
  `uploaded` לא סופר אותו, והדוח מסמן failure. יש כבר תשתית fake ב-
  `test_index_cas.py` — לחקות.
- **סיכון:** נמוך. תלוי ב-DB-M-5 (מבנה `new_entries`); לעשות DB-O-5 קודם ולבנות
  את מנגנון ה-`failed`, אז DB-M-5 יחבר לזה את "רישום על הצלחה".

### DB-M-5 (43) — אינדקס על הצלחה; `remove` מעדכן אינדקס
- **מיקום:** `push_local_pool` (326) — `new_entries[pid]=index_entry(rec)` לפני
  אישור כתיבה. `FirestorePool.remove` (165-170) — מוחק בלי לגעת באינדקס.
- **גישה:**
  1. **push:** לבנות `new_entries` רק מ-pids שהצליחו. שילוב עם DB-O-5: אחרי
     `writer.close()`, `succeeded = enqueued - failed`; `new_entries` מוגבל ל-
     `succeeded`. (מימוש: לשמור `staged[pid]=index_entry(rec)` ב-enqueue, ואחרי
     close למחוק את הכושלים; זהה מבחינת התוצאה.)
  2. **remove:** לעדכן את האינדקס באותה פעולה — לקרוא pointer (read_index),
     לסנן את הרשומה, `write_index(...)` תחת ה-CAS הקיים (`expect_generation`).
     במקרה IndexConflict — retry קצר. `remove` יחזיר True רק אחרי מחיקת המסמך
     ועדכון האינדקס.
- **בדיקות:** (א) push עם pid כושל → אינו באינדקס (מכוסה גם ב-DB-O-5). (ב)
  `remove(pid)` → המסמך נמחק **וגם** האינדקס לא כולל את ה-pid; `remove` של pid
  לא-קיים מחזיר False ולא נוגע באינדקס. fake remote עם read_index/write_index.
- **סיכון:** נמוך.

### DB-M-7 (45) — אכיפת schema + `schema_min`/`schema_max`
- **מיקום:** `store.py` `index_from_entries` (56) כותב `schema: SCHEMA_VERSION`
  (=1) תמיד; `FirestorePool.add`/`add_unchecked`/`push_local_pool` כותבים dict
  כמות שהוא ללא בדיקת סכמה (בניגוד ל-`ProblemPool.add` שכן בודק).
- **גישה:**
  1. **אכיפה:** ב-`FirestorePool.add`/`add_unchecked` להוסיף
     `if record.get("schema") not in SUPPORTED_SCHEMAS: raise ValueError(...)`
     (כמו `store.ProblemPool.add`). ב-`push_local_pool` — הרשומות מגיעות מ-
     `ProblemPool` שכבר אוכף ב-add; להוסיף אכיפה גם בקריאה (הגנת עומק).
  2. **schema_min/max:** `index_entry` יכלול `schema: rec.get("schema", 1)`;
     `index_from_entries` יחשב `schema_min`/`schema_max` מהערכים בפועל במקום
     `schema` קבוע (לשמור `schema` לתאימות = schema_min). הקליינט לא בודק כרגע —
     אבל השדות יהיו אמיתיים ל-schema-3 עתידי.
- **בדיקות:** (א) `add`/`add_unchecked` עם schema לא-נתמך → ValueError. (ב)
  `index_from_entries` על ערבוב schema 1+2 → `schema_min=1, schema_max=2`.
  (ג) תאימות: `index_entry` ללא schema → ברירת מחדל 1.
- **סיכון:** נמוך. **שים לב:** לוודא ש-`index_entry` הנוסף (`schema`) לא שובר את
  `test_stats`/round-trip קיימים — לבדוק בדיקות אינדקס קיימות.

### DB-O-6 (48) — `getCountFromServer` לפני full reconcile
- **מיקום:** `bt-firebase.js` `_syncAttempts` (244-272) — full reconcile כל 6ש';
  fallback ל-full read על **כל** שגיאה (281-285).
- **גישה:**
  1. לפני `getDocs(coll)` המלא, לקרוא `getCountFromServer(coll)` (קריאה
     מצטברת אחת). אם הספירה == גודל המטמון (`Object.keys(ATTEMPTS).length`,
     בהתחשב ב-PENDING) → לדלג על ה-reconcile המלא, לעדכן `LAST_FULL_SYNC` ולצאt.
     אם יש פער — לבצע reconcile מלא כרגיל. לוגיקת ההחלטה טהורה ב-`bt-logic.js`:
     `needsReconcile(serverCount, cacheSize)`.
  2. להגביל את ה-fallback (283-284) לשגיאת `failed-precondition` בלבד
     (missing index), לא לכל error — כדי לא להסוות ניתוק רשת בקריאה יקרה.
  3. לייבא `getCountFromServer` מ-firestore SDK (imports בראש הקובץ).
- **בדיקות:** `run_logic` על `needsReconcile`: שווה→false, פער→true, cache ריק→
  true. + string-assert ש-`_syncAttempts` קורא `getCountFromServer` וש-fallback
  מותנה ב-`failed-precondition`.
- **סיכון:** נמוך (fallback לשרת נשמר). לאמת שם ה-import (`getCountFromServer`
  קיים ב-firestore-lite/full v10.12.2 — כן).

### ARCH-6 (35) — `htmlfmt.py` משותף
- **מיקום:** `publish.py:34,96-107` (`_SUIT_GLYPHS`,`_auction_html`,`_hand_html`)
  מול `report.py:14-21` (`_SUIT_GLYPHS`,`_hand_html`) — עותקים בפורמטים שונים.
- **גישה:** מודול חדש `bridge_trainer/app/htmlfmt.py` עם `SUIT_GLYPHS`,
  `hand_html(hand)`, `auction_html(problem)`. `publish.py` ו-`report.py`
  מייבאים ממנו. **החלטה על publish.py:** `trainer publish` אינו על נתיב הפריסה
  (רק `trainer webapp`), אבל אינו נמחק כאן (מחיקה = החלטת מוצר; נקודת החלטה).
  לכן ARCH-6 = **מיצוי helpers משותפים בלבד**, לא מחיקה. יש לשמר את הפורמט
  הקיים של כל צרכן (report.py משתמש ב-`<span class=red>` ללא מרכאות; publish.py
  עם מרכאות; מפריד `<br>` מול רווח) — הפונקציה המשותפת תקבל פרמטרים (מפריד,
  wrapper) או נבחר פורמט קנוני אחד ונעדכן את שני הצרכנים + בדיקותיהם.
- **בדיקות:** `tests/test_publish.py`/`test_render`(קיימות) עוברות; בדיקה חדשה
  `test_htmlfmt.py` על `hand_html`/`auction_html` (מבנה, escaping של html.escape).
- **סיכון:** נמוך. לאמת פלט זהה מול הקיים (snapshot לפני/אחרי).

### ARCH-7 (36) — `BatchState` בסיס משותף
- **מיקום:** `maker.py:289-388` (`_BatchState`, `forge_batch`) מול
  `lead_maker.py:330-437` (`_LeadBatchState`, `forge_lead_batch`).
- **גישה:** בסיס משותף — מודול חדש `engine/batch_state.py` עם `BatchState`
  (dedup, rejections, stage_totals, `rebuild_index`, `absorb` גנרי עם hook
  ל-quota/rejection-policy, `summary` בסיסי) ו-`run_forge_loop(engine,
  forge_fn, state, ...)`. `_BatchState`/`_LeadBatchState` יורשים ומספקים hooks
  (quotas, log-format: per-board מול every-5). לשמר בדיוק את ההתנהגות הנצפית
  (מכוסה ב-`test_forge_workflow.py`, `test_lead_forge_modes.py`).
- **בדיקות:** הבדיקות הקיימות של שני המסלולים עוברות ללא שינוי; להוסיף בדיקת
  יחידה ל-`BatchState.absorb` (dedup + stage_totals) אם אין.
- **סיכון:** נמוך-בינוני (נתיב ייצור ליבה). לעבוד בזהירות, להריץ את בדיקות
  ה-forge אחרי. **קוד ריוויו** מוקפד בסוף.

### DB-O-7 (49) — התראות ניטור + כשל workflow
- **מיקום:** `.github/workflows/forge-leads.yml` (job summary 141-160, אין
  notification על כשל); `docs/firebase_setup.md` (אין ניטור). `publish.yml`
  (deploy) — לבדוק אם צריך גם שם.
- **גישה:**
  1. **workflow:** להוסיף step "Notify on failure" (`if: failure()`) שפותח/מעדכן
     issue אוטומטי (`gh issue` דרך `GITHUB_TOKEN`, או actions/github-script)
     עם קישור לריצה. דורש `permissions: issues: write` (כרגע `contents: read`
     בלבד — להוסיף בזהירות, מינימלי). לחלופין, אם לא רוצים issues — לתעד את
     ההגדרה כ-notification דרך GitHub (watch/Actions email) ולהוסיף רק דגל.
     **החלטה:** step שיוצר issue הוא הפתרון הקונקרטי; לתעד.
  2. **docs:** להוסיף ל-`firebase_setup.md` סעיף "ניטור והתראות" — Cloud
     Monitoring alert על `document/read_count`/`write_count` (~70% מהמכסה) +
     budget alert, כשלב חובה. (הגדרת ה-alert עצמה בקונסולת GCP — תיעוד, לא קוד.)
- **בדיקות:** בדיקת lint/parse ל-YAML (אם יש דפוס קיים ב-repo); אחרת בדיקה
  שמאמתת שה-workflow מכיל step `if: failure()` ו-`issues: write` (קריאת קובץ +
  assert מחרוזת). תיעוד — ללא בדיקה אוטומטית.
- **סיכון:** אפסי לקוד האפליקציה. **שים לב:** לא להדליף secrets; ה-issue body
  לא יכלול את מפתח ה-service account.

### PERF-F-3 (22) — אימות היקף
- **בוצע:** מקבול ה-shards כבר ממומש (`bt-firebase.js:400` `Promise.all`), וה-
  cache מבוסס-stamp (T10) חתך את קריאות האינדקס דרסטית. אלה היו הליבה של הממצא.
- **הנותר (facets doc):** מסמך אגרגציה קטן (`meta/facets`) לעמוד הבית. **מסקנת
  אימות:** זהו למעשה אותו סיכון של T12 (שנדחה בסבב 1) — דורש כותב producer חדש
  ומיגרציה מתואמת על ה-DB החי, ועדיין **אינו** משחרר את דף הבית מהורדת האינדקס
  המלא (הבית זקוק לו לבחירת בעיה אקראית ולספירת "ממתינות" פר-פילטר). התועלת
  השולית מוגבלת בעוד ה-cache של T10 כבר פותר את עלות הקריאה החוזרת.
- **החלטה:** לא לממש את מסמך ה-facets ב-PR זה (מחוץ להיקף מעשי, כמו T12). לתעד
  כנקודת החלטה. אין שינוי קוד ל-22 מעבר לאימות + תיעוד.

### UX-I-2 (28) — אימות היקף
- **בוצע (T18, סבב 1):** `guestNote` תוקן ("לא מחובר — התחבר כדי לשמור התקדמות",
  webapp.py:865), חיווי שגיאה בעברית בשער + כפתור retry (`bt-firebase.js:198-212`),
  ושורת תועלת בשער (188-197). `isGuest` יושר (מחזיר `!USER`).
- **הנותר (guest mode מלא):** localStorage ללא התחברות. **מסקנת אימות:** סותר
  את מדיניות "sign-in required" המוצהרת מפורשות (`bt-firebase.js:2-3`) ואת מודל
  ה-Firestore (rules דורשים `request.auth != null`). זו הצעה high-risk שנדחתה
  במפורש בסבב 1 (נקודת החלטה 1, "ברירת מחדל: לא").
- **החלטה:** לא לממש guest mode מלא ב-PR זה. לתעד כנקודת החלטה. אין שינוי קוד
  ל-28 מעבר לאימות + תיעוד. (אם ירצה המשתמש guest mode — משימת מוצר נפרדת עם
  שינוי מדיניות אבטחה.)

---

## נקודות החלטה למשתמש (לסיכום שלב 5)
1. **PERF-F-3 facets doc** — נדחה (סיכון T12; תועלת שולית מול cache T10). לאשר.
2. **UX-I-2 guest mode מלא** — נדחה (סותר sign-in-required; high-risk). לאשר.
3. **ARCH-9 מיגרציה על production** — הקוד (ריכוז + סקריפט + בדיקות) נכלל; הרצת
   הסקריפט על ה-DB החי ומחיקת ענפי legacy מה-JS — צעד נפרד באישור.
4. **ARCH-6 מחיקת publish.py** — לא נמחק (החלטת מוצר); רק מיצוי helpers.
5. **DB-O-7 issue אוטומטי** — הוספת `issues: write` ל-forge workflow. לאשר.

## בדיקות — סיכום מערך
כל ממצא מסתיים ב: (א) בדיקות ייעודיות עוברות; (ב) code review (subagent); (ג)
commit. בסיום הכל — `pytest -q` מלא. בדיקות JS דורשות `node` (מסומנות
`needs_node`, נדלגות אם חסר). קבצי בדיקה חדשים צפויים: `test_normalize_shapes.py`,
`test_taxonomy_single_source.py`, `test_htmlfmt.py`, והרחבות ל-`test_bt_logic.py`,
`test_firestore_safe.py`, `test_index_cas.py`, `test_scoring_scale.py`/
`test_hebrew_ui.py` (esc), ובדיקת workflow ל-DB-O-7.
