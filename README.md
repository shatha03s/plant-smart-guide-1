# المرشد الذكي للنباتات

مشروع Flask عربي RTL يحتوي على:
- مكتبة نباتات محلية 1000 سجل من `data/plants_seed.json`
- SQLite يتم إنشاؤها تلقائيًا داخل `instance/plant_guide.db`
- RAG محلي قبل OpenAI لتقليل الاستهلاك
- OpenAI اختياري للردود المركبة وتحليل الصور
- رفع/تصوير صورة من الجوال

## التشغيل المحلي
```bash
pip install -r requirements.txt
copy .env.example .env
python app.py
```
ثم افتح:
```text
http://127.0.0.1:5000/
```

## مهم
إذا عدلت ملف الداتا احذف قاعدة البيانات القديمة:
```bash
del instance\plant_guide.db
python app.py
```

## متغيرات البيئة
```env
OPENAI_API_KEY=sk-xxxx
OPENAI_MODEL=gpt-4o-mini
ENABLE_OPENAI=1
ENABLE_VISION=1
```
