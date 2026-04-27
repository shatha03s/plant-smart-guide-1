from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import os
import json
import sqlite3
import difflib
import base64
from typing import List, Tuple, Optional

load_dotenv()

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(INSTANCE_DIR, "plant_guide.db")
JSON_PATH = os.path.join(DATA_DIR, "plants_seed.json")

os.makedirs(INSTANCE_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_DIR
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
ENABLE_OPENAI = os.getenv("ENABLE_OPENAI", "1").strip() == "1"
ENABLE_VISION = os.getenv("ENABLE_VISION", "1").strip() == "1"

try:
    if OPENAI_API_KEY and ENABLE_OPENAI:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
    else:
        client = None
except Exception as e:
    print("OPENAI INIT ERROR:", e)
    client = None

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


# -----------------------------
# Database
# -----------------------------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS plants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name_ar TEXT NOT NULL,
        name_en TEXT,
        scientific_name TEXT,
        category TEXT,
        watering TEXT,
        sunlight TEXT,
        soil TEXT,
        description TEXT,
        problems TEXT,
        care_tips TEXT,
        aliases TEXT,
        search_text TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_message TEXT,
        bot_reply TEXT,
        source TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS image_analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT,
        user_message TEXT,
        bot_reply TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    count = cur.execute("SELECT COUNT(*) FROM plants").fetchone()[0]
    conn.close()

    if count == 0:
        import_plants_json()


def import_plants_json():
    if not os.path.exists(JSON_PATH):
        print("WARNING: data/plants_seed.json غير موجود. المكتبة ستكون فارغة.")
        return

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    data = raw.get("plants", []) if isinstance(raw, dict) else raw

    rows = []
    seen = set()

    for item in data:
        if isinstance(item, str):
            item = {"name_ar": item}

        if not isinstance(item, dict):
            continue

        name_ar = str(item.get("name_ar", "")).strip()
        if not name_ar:
            continue

        key = normalize_arabic(name_ar)
        if key in seen:
            continue

        seen.add(key)

        name_en = str(item.get("name_en", "")).strip()
        scientific_name = str(item.get("scientific_name", "")).strip()
        category = str(item.get("category", "غير مصنف")).strip()
        watering = str(item.get("watering", "حسب حاجة النبات")).strip()
        sunlight = str(item.get("sunlight", "إضاءة مناسبة")).strip()
        soil = str(item.get("soil", "تربة جيدة التصريف")).strip()
        description = str(item.get("description", "")).strip()
        problems = str(item.get("problems", "")).strip()
        care_tips = str(item.get("care_tips", "")).strip()

        aliases = item.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [aliases]

        aliases_text = " | ".join([str(a).strip() for a in aliases if str(a).strip()])

        search_text = build_search_text(
            name_ar,
            name_en,
            scientific_name,
            category,
            watering,
            sunlight,
            soil,
            description,
            problems,
            care_tips,
            aliases_text
        )

        rows.append((
            name_ar,
            name_en,
            scientific_name,
            category,
            watering,
            sunlight,
            soil,
            description,
            problems,
            care_tips,
            aliases_text,
            search_text
        ))

    conn = db()
    cur = conn.cursor()

    cur.executemany("""
    INSERT INTO plants
    (
        name_ar,
        name_en,
        scientific_name,
        category,
        watering,
        sunlight,
        soil,
        description,
        problems,
        care_tips,
        aliases,
        search_text
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)

    conn.commit()
    conn.close()

    print(f"Imported {len(rows)} unique plants.")


# -----------------------------
# Normalization and Retrieval
# -----------------------------
def normalize_arabic(text: str) -> str:
    text = str(text or "").strip().lower()

    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ة": "ه",
        "ؤ": "و",
        "ئ": "ي",
        "ـ": "",
        "ً": "",
        "ٌ": "",
        "ٍ": "",
        "َ": "",
        "ُ": "",
        "ِ": "",
        "ّ": "",
        "ْ": ""
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return " ".join(text.split())


def build_search_text(*parts) -> str:
    return normalize_arabic(" ".join([str(p or "") for p in parts]))


def safe(row, key, default=""):
    try:
        value = row[key]
        return value if value is not None else default
    except Exception:
        return default


def tokenize(text: str) -> List[str]:
    return [
        t for t in normalize_arabic(text)
        .replace("،", " ")
        .replace(",", " ")
        .split()
        if len(t) > 1
    ]


def get_all_plants():
    conn = db()
    rows = conn.execute("SELECT * FROM plants").fetchall()
    conn.close()
    return rows


def local_rag_search(query: str, limit: int = 7) -> Tuple[List[sqlite3.Row], int]:
    q_norm = normalize_arabic(query)
    q_tokens = tokenize(query)
    rows = get_all_plants()
    scored = []

    for p in rows:
        name_ar = normalize_arabic(safe(p, "name_ar"))
        name_en = normalize_arabic(safe(p, "name_en"))
        scientific = normalize_arabic(safe(p, "scientific_name"))
        aliases = normalize_arabic(safe(p, "aliases"))

        text = safe(p, "search_text") or build_search_text(
            safe(p, "name_ar"),
            safe(p, "name_en"),
            safe(p, "scientific_name"),
            safe(p, "category"),
            safe(p, "watering"),
            safe(p, "sunlight"),
            safe(p, "soil"),
            safe(p, "description"),
            safe(p, "problems"),
            safe(p, "care_tips"),
            safe(p, "aliases")
        )

        score = 0

        if q_norm and q_norm in name_ar:
            score += 120
        if q_norm and q_norm in aliases:
            score += 115
        if q_norm and q_norm in name_en:
            score += 100
        if q_norm and q_norm in scientific:
            score += 95
        if q_norm and q_norm in text:
            score += 55

        for tok in q_tokens:
            if tok in name_ar or tok in aliases:
                score += 25
            elif tok in text:
                score += 8

        ratio = max(
            difflib.SequenceMatcher(None, q_norm, name_ar).ratio(),
            difflib.SequenceMatcher(None, q_norm, name_en).ratio(),
            difflib.SequenceMatcher(None, q_norm, scientific).ratio(),
            difflib.SequenceMatcher(None, q_norm, aliases).ratio() if aliases else 0
        )

        score += int(ratio * 70)

        if score > 35:
            scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)

    return [p for _, p in scored[:limit]], (scored[0][0] if scored else 0)


def problem_answer(message: str) -> Optional[str]:
    q = normalize_arabic(message)

    if any(w in q for w in ["اصفرار", "صفر", "اوراق صفراء", "الاوراق صفراء"]):
        return """🍃 اصفرار الأوراق غالبًا سببه واحد من هذه العوامل:
• زيادة الري أو سوء تصريف التربة.
• ضعف الإضاءة أو شمس مباشرة قوية جدًا.
• نقص عناصر غذائية مثل الحديد أو النيتروجين.

الإجراء المقترح:
افحصي رطوبة التربة، خففي الري، حسّني الإضاءة، وأزيلي الأوراق المتضررة."""

    if any(w in q for w in ["ذبول", "ذابل", "ذابله"]):
        return """🥀 الذبول له احتمالان متعاكسان: قلة ماء أو زيادة ماء.
افحصي التربة أولًا:
• إذا كانت جافة جدًا: اسقي تدريجيًا.
• إذا كانت رطبة جدًا: أوقفي الري مؤقتًا وحسّني التصريف.
• إذا كان النبات تحت شمس قوية: انقليه لإضاءة غير مباشرة."""

    if any(w in q for w in ["بقع", "بقعه", "حروق", "بنيه", "سوداء"]):
        return """🍂 البقع على الأوراق قد تكون بسبب حروق شمس، فطريات، أو رطوبة عالية.
حسّني التهوية، تجنبي رش الأوراق وقت الشمس، وأزيلي الأوراق المتضررة بشدة."""

    if any(w in q for w in ["ري", "اسقي", "اسقيه", "ماء", "كم مره"]):
        return """💧 قاعدة الري الذهبية:
لا تعتمدي على جدول ثابت فقط. افحصي أول 2 سم من التربة:
• جافة: اسقي.
• رطبة: انتظري.
النباتات الداخلية غالبًا تموت من زيادة الري أكثر من قلة الري."""

    return None


def format_plant_answer(p) -> str:
    return f"""🌿 {safe(p, 'name_ar')}

• الاسم الإنجليزي: {safe(p, 'name_en') or 'غير متوفر'}
• الاسم العلمي: {safe(p, 'scientific_name') or 'غير متوفر'}
• التصنيف: {safe(p, 'category') or 'غير مصنف'}
• الري: {safe(p, 'watering') or 'حسب حاجة النبات'}
• الإضاءة: {safe(p, 'sunlight') or 'إضاءة مناسبة'}
• التربة: {safe(p, 'soil') or 'تربة جيدة التصريف'}

📌 الوصف:
{safe(p, 'description') or 'لا يوجد وصف متاح.'}

✅ العناية:
{safe(p, 'care_tips') or 'راقبي الري والإضاءة وحالة التربة بشكل دوري.'}"""


def should_use_openai(message: str, results: List[sqlite3.Row], top_score: int) -> bool:
    if not client:
        return False

    if problem_answer(message):
        return False

    if results and top_score >= 95:
        return False

    if len(message.strip()) < 6:
        return False

    return True


def openai_rag_answer(message: str, context: List[sqlite3.Row]) -> str:
    if not client:
        if context:
            return format_plant_answer(context[0])
        return "🌿 لم أجد نتيجة واضحة. جرّبي كتابة الاسم بطريقة مختلفة أو ابحثي عنه في المكتبة."

    context_text = "\n\n".join([
        f"""النبات: {safe(p, 'name_ar')} / {safe(p, 'name_en')} / {safe(p, 'scientific_name')}
التصنيف: {safe(p, 'category')}
الري: {safe(p, 'watering')}
الإضاءة: {safe(p, 'sunlight')}
التربة: {safe(p, 'soil')}
الوصف: {safe(p, 'description')}
المشكلات: {safe(p, 'problems')}
العناية: {safe(p, 'care_tips')}"""
        for p in context[:5]
    ])

    prompt = f"""
أنت مرشد نباتات عربي رسمي وعملي.
اعتمد على بيانات المكتبة أولًا، ولا تذكر أنك تستخدم OpenAI أو RAG أو قاعدة بيانات.
إذا كانت البيانات غير كافية، أعط نصيحة آمنة واطلب توضيحًا بسيطًا.
لا تخترع معلومات خطرة أو مبالغ فيها.

بيانات من المكتبة:
{context_text}

سؤال المستخدم:
{message}
"""

    try:
        res = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "أنت مساعد مختص بالنباتات يجيب بالعربية بأسلوب واضح ورسمي."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.2,
            max_tokens=420
        )

        return res.choices[0].message.content.strip()

    except Exception as e:
        print("OPENAI CHAT ERROR:", e)

        if context:
            return format_plant_answer(context[0])

        return "🌿 تعذر التحليل حاليًا. اكتبي اسم النبات أو المشكلة بشكل أوضح."


# -----------------------------
# Image analysis
# -----------------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def encode_image(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def openai_vision_answer(path: str, message: str) -> str:
    if not client or not ENABLE_VISION:
        return "تم استلام الصورة 🌿 اكتبي اسم النبات أو المشكلة الظاهرة عليه لأعطيك إرشادات أدق."

    try:
        image_b64 = encode_image(path)

        res = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "أنت خبير نباتات. حلل الصورة بالعربية باختصار وبنقاط عملية."
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"حلل صورة النبات. اذكر النبات المحتمل، حالته، المشكلة الظاهرة، ونصائح العناية. سؤال المستخدم: {message or 'لا يوجد سؤال'}"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}"
                            }
                        }
                    ]
                }
            ],
            temperature=0.2,
            max_tokens=450
        )

        return res.choices[0].message.content.strip()

    except Exception as e:
        print("VISION ERROR:", e)
        return "تم استلام الصورة، لكن تعذر تحليلها تلقائيًا. اكتبي اسم النبات أو المشكلة الظاهرة."


# -----------------------------
# Routes
# -----------------------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/library")
def library():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()

    conn = db()
    cur = conn.cursor()

    if q:
        plants, _ = local_rag_search(q, limit=100)

        if category:
            plants = [p for p in plants if safe(p, "category") == category]
    else:
        sql = "SELECT * FROM plants WHERE 1=1"
        params = []

        if category:
            sql += " AND category = ?"
            params.append(category)

        sql += " ORDER BY name_ar ASC LIMIT 1000"
        plants = cur.execute(sql, params).fetchall()

    categories = cur.execute("""
        SELECT DISTINCT category
        FROM plants
        WHERE category IS NOT NULL AND category != ''
        ORDER BY category
    """).fetchall()

    total = cur.execute("SELECT COUNT(*) FROM plants").fetchone()[0]

    conn.close()

    return render_template(
        "library.html",
        plants=plants,
        categories=categories,
        selected_category=category,
        q=q,
        total=total
    )


@app.route("/api/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json(silent=True) or {}
        message = data.get("message", "").strip()

        if not message:
            return jsonify({"reply": "اكتبي اسم النبات أو المشكلة وسأساعدك."})

        local_problem = problem_answer(message)

        if local_problem:
            save_conversation(message, local_problem, "local_problem")
            return jsonify({"reply": local_problem})

        results, top_score = local_rag_search(message, limit=7)

        if results and not should_use_openai(message, results, top_score):
            reply = format_plant_answer(results[0])
            save_conversation(message, reply, "local_rag")
            return jsonify({"reply": reply})

        reply = openai_rag_answer(message, results)
        save_conversation(message, reply, "openai_rag" if client else "local_fallback")

        return jsonify({"reply": reply})

    except Exception as e:
        print("CHAT ERROR:", e)
        return jsonify({"reply": "حدث خطأ مؤقت. أعيدي المحاولة."}), 500


def save_conversation(user_message, bot_reply, source):
    try:
        conn = db()

        conn.execute(
            "INSERT INTO conversations (user_message, bot_reply, source) VALUES (?, ?, ?)",
            (user_message, bot_reply, source)
        )

        conn.commit()
        conn.close()

    except Exception as e:
        print("SAVE CONVERSATION ERROR:", e)


@app.route("/api/analyze-image", methods=["POST"])
def analyze_image():
    try:
        image = request.files.get("image")
        message = request.form.get("message", "").strip()

        if not image:
            return jsonify({"reply": "ارفعي صورة واضحة للنبات."}), 400

        if not allowed_file(image.filename):
            return jsonify({"reply": "صيغة الصورة غير مدعومة. استخدمي PNG أو JPG أو JPEG أو WEBP."}), 400

        filename = secure_filename(image.filename)
        path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        image.save(path)

        reply = openai_vision_answer(path, message)

        try:
            conn = db()

            conn.execute(
                "INSERT INTO image_analyses (filename, user_message, bot_reply) VALUES (?, ?, ?)",
                (filename, message, reply)
            )

            conn.commit()
            conn.close()

        except Exception as e:
            print("SAVE IMAGE ANALYSIS ERROR:", e)

        return jsonify({"reply": reply})

    except Exception as e:
        print("IMAGE ERROR:", e)
        return jsonify({"reply": "حدث خطأ أثناء معالجة الصورة."}), 500


@app.route("/api/library-search")
def api_library_search():
    q = request.args.get("q", "").strip()

    results, _ = local_rag_search(q, limit=10) if q else ([], 0)

    return jsonify({
        "results": [dict(r) for r in results]
    })


init_db()

if __name__ == "__main__":
    app.run()
