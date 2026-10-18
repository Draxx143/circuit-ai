# معماری نسخه نخست

## تصمیم‌ها

- **Streamlit محلی** برای رابط فارسی؛ منطق برنامه جدا از UI است و شبکه/حساب ابری لازم ندارد.
- **SQLite** با کلیدهای خارجی و مسیر پیش‌فرض XDG: `~/.local/share/circuit-ai/circuit_ai.sqlite3`. فایل شامل پرونده‌های کاربر است و عمداً وارد مخزن Git نمی‌شود.
- **JSON نسخه‌دار برای کاتالوگ اولیه** (`data/seed_catalog.json`)، **قوانین عمومی** (`data/diagnostic_rules/rules.json`) و **پروفایل‌های شرط کاری اختصاصیِ منبع‌دار** (`data/diagnostic_rules/component_ranges.json`). `init_db` آن‌ها را idempotent به جداول رابطه‌ای وارد می‌کند و داده‌های تعمیر را پاک نمی‌کند.
- **Schema نسخه 3** به‌صورت افزایشی؛ جدول `component_diagnostic_profiles` با شاخص روی `component_id`، مرجع بازه، نام‌های سیگنال، توضیح نقطه اندازه‌گیری و منبع را نگه می‌دارد.
- **موتور قطعی/قابل توضیح** در `core/`: محاسبات فیزیکی، مقایسه با مرجعِ واردشده، بارگذاری پروفایل شرط کاری از دادهٔ منبع‌دار و مسیرهای triage. پروفایلِ موجود هم فقط وضعیت کاری را مقایسه می‌کند؛ خرابی قطعه را اثبات نمی‌کند. در نبود اطلاعات کافی علت جعل نمی‌شود.
- **سرویس‌ها** در `services/`: persistence، نسخه پشتیبان/بازیابی، جست‌وجوی پرونده‌های مشابه و مدیریت بانک.
- **جمع‌آوری داده** از برنامه جدا است. `tools/source_intake.py` فقط manifest صریح کاربر را ممیزی/دانلود می‌کند؛ crawl یا جست‌وجوی وب پنهان ندارد؛ استخراج PDF اختیاری است و هیچ‌وقت خودکار تأیید نمی‌شود.

## ساختار

```text
electronics_diagnostic_ai/
├── app.py
├── run.sh
├── requirements.txt
├── pyproject.toml
├── config/settings.json
├── database/schema.sql
├── core/{diagnostic_engine.py,rules_engine.py,electrical_calculations.py,confidence.py}
├── services/{db.py,repair_service.py,component_service.py,knowledge_service.py,backup_service.py,settings_service.py}
├── ui/common.py
├── data/seed_catalog.json
├── data/diagnostic_rules/rules.json
├── data/diagnostic_rules/component_ranges.json
├── tools/{manage_data.py,source_intake.py}
├── docs/{ARCHITECTURE.md,SAFETY.md,DATA_ACQUISITION_REPORT.md,ROADMAP.md}
└── tests/
```

## مدل اعتبار

- `official_datasheet_reviewed`: مشخصه‌های ثبت‌شده با دیتاشیت رسمی تطبیق داده شده‌اند؛ نه آزمایشگاه.
- `needs_review`: مسیر triage/راهنمای عمومی یا داده ناقص، نیازمند بازبینی تعمیرکار.
- `experimental`، `conflicting` و `lab_tested` از وضعیت‌های مستندشده دیتابیس هستند؛ هیچ داده‌ای صرفاً با ورود کاربر رسمی تأیید نمی‌شود.
- پرونده‌های تعمیر با `unverified` شروع می‌شوند. تأیید نیازمند نام بازبین و توضیح شواهد است.

## محدودیت‌های شناخته‌شده

- بدون شماتیک/مدل برد، خروجی هدف، تلرانس، پایه میکروکنترلر یا سطح منطقی تعیین نمی‌شود.
- جست‌وجوی مشابه در نسخه اول lexical/علائم است، نه embedding یا ML.
- هیچ مدل زبانی، RAG، کنترل از راه دور، OCR یا ingest خودکار PDF به مشخصه قطعه وجود ندارد.
- پشتیبانی از فرمت پشتیبان در نسخه اول SQLite و JSON خروجی است؛ رمزگذاری سمت برنامه اضافه نشده است. فایل‌ها را با مجوزهای کاربری و پشتیبان رمزگذاری‌شده سیستم‌عامل محافظت کنید.
