"""
Rich listing templates for seed_marketplace_dataset.py (local/staging only).
No lorem ipsum — short realistic Arabic/English marketplace copy.
"""

from __future__ import annotations

# --- Mixed name parts for 500+ unique combinations ---
AR_FIRST = (
    "محمد", "خالد", "فهد", "سعد", "تركي", "عبدالله", "راشد", "نايف", "ماجد", "فيصل",
    "عمر", "ياسر", "بندر", "سلطان", "نواف", "رائد", "زياد", "طلال", "صالح", "مشعل",
    "نورة", "سارة", "ريم", "هند", "منى", "لمياء", "شيماء", "أمل", "دانة", "لينا",
    "دانيا", "غادة", "هيا", "رنا", "وفاء", "أسماء", "مها", "العنود", "جود", "لطيفة",
)
AR_LAST = (
    "العتيبي", "القحطاني", "الشمري", "الدوسري", "الزهراني", "الغامدي", "المطيري",
    "العنزي", "الحربي", "السبيعي", "الرشيدي", "الجهني", "القحطاني", "الشهري", "العمري",
)
EN_FIRST = (
    "Omar", "Adam", "Khalid", "Noor", "Lina", "Sara", "Yousef", "Hassan", "Malik", "Rami",
    "Leena", "Dina", "Zaid", "Karim", "Samir", "Huda", "Maya", "Rania", "Tariq", "Faisal",
)
EN_LAST = (
    "Hassan", "Malik", "Noor", "Kareem", "Abbas", "Farid", "Salem", "Nasser", "Rahman", "Aziz",
)

# Service category keys must match app.domain.service_categories.SERVICE_CATEGORY_KEYS
SERVICE_CAT_KEYS = (
    "teacher",
    "delivery_driver",
    "electrician",
    "ac_technician",
    "plumber",
    "government_services",
    "babysitter",
    "carpenter",
    "construction",
    "security_guard",
    "events",
    "photographer",
    "barista",
    "other",
)


def display_name_for_index(i: int) -> str:
    """Arabic-heavy mix with English every few users."""
    af, al = AR_FIRST[i % len(AR_FIRST)], AR_LAST[i % len(AR_LAST)]
    if i % 4 == 0:
        ef, el = EN_FIRST[i % len(EN_FIRST)], EN_LAST[i % len(EN_LAST)]
        return f"{ef} {el}"
    if i % 4 == 1:
        return f"{af} {al}"
    if i % 4 == 2:
        return f"{af} · {EN_FIRST[i % len(EN_FIRST)]}"
    return f"{AR_FIRST[(i + 3) % len(AR_FIRST)]} {al}"


# --- Sale templates: category string for Item.category, condition, price range SAR ---
SALE_SPECS: list[dict] = [
    {
        "slug": "car_toyota",
        "category": "Vehicles",
        "condition": "good",
        "price": (32000, 118000),
        "title": "تويوتا كامري 2018 — للبيع",
        "description": (
            "كامري 2018، قير أوتوماتيك، ممشى تقريبي 145 ألف كم، صيانة دورية في الوكالة حتى 140 ألف. "
            "بدون حوادث مسجّلة، رشّ داخلي خفيف على الباب الخلفي. مكيف ممتاز، تواير جديدة من 6 أشهر. "
            "الموقع الرياض، المعاينة بأي وقت بعد التنسيق. جاهز للنقل الشخصي أو العائلي."
        ),
    },
    {
        "slug": "car_honda",
        "category": "Vehicles",
        "condition": "like_new",
        "price": (45000, 95000),
        "title": "هوندا أكورد 2020 للبيع",
        "description": (
            "أكورد 2020 فل كامل، لون أسود، داخل جلد بيج. السيارة للاستخدام الشخصي، لا تشكو من أعطال. "
            "استهلاك معقول، مناسبة للتنقل اليومي داخل الرياض. المشتري يفحص في أي مركز يختاره."
        ),
    },
    {
        "slug": "phone_iphone",
        "category": "Electronics",
        "condition": "like_new",
        "price": (1800, 4200),
        "title": "آيفون 14 برو — 256 جيجا",
        "description": (
            "جهاز شخصي، بطارية 92%، بدون كسر للشاشة، مع العلبة والشاحن الأصلي. "
            "Face ID يعمل، الكاميرات نظيفة. سبب البيع الترقية لجهاز أحدث."
        ),
    },
    {
        "slug": "phone_samsung",
        "category": "Electronics",
        "condition": "good",
        "price": (900, 2200),
        "title": "Samsung Galaxy S22 للبيع",
        "description": (
            "شاشة AMOLED بحالة ممتازة، حماية زجاجية منذ الشراء. يعمل على آخر تحديث متاح. "
            "معه كفر شفاف. لا يوجد طمس على الإطار."
        ),
    },
    {
        "slug": "sofa_corner",
        "category": "Furniture",
        "condition": "good",
        "price": (1200, 3500),
        "title": "كنب زاوية واسع — رمادي",
        "description": (
            "كنب زاوية مقاس كبير، قماش سهل التنظيف، إطار خشب قوي. تم التنظيف الجاف مؤخراً. "
            "التوصيل على المشتري داخل الرياض أو يمكن ترتيب سائق باتفاق."
        ),
    },
    {
        "slug": "desk_office",
        "category": "Furniture",
        "condition": "like_new",
        "price": (350, 950),
        "title": "مكتب عمل منزلي مع وحدات تخزين",
        "description": (
            "مكتب أبيض 140 سم مع رفوف جانبية، مناسب للعمل عن بُعد. تجميع بسيط، حالة شبه جديدة. "
            "البيع لعدم الحاجة بعد الانتقال لمكتب أصغر."
        ),
    },
    {
        "slug": "washer",
        "category": "Appliances",
        "condition": "good",
        "price": (800, 1900),
        "title": "غسالة فوق أوتوماتيك 9 كيلو",
        "description": (
            "غسالة موفرة للماء، برامج متعددة، تعمل بكفاءة. تمت صيانة بسيطة قبل أسبوعين. "
            "مناسبة لعائلة صغيرة أو شقة."
        ),
    },
    {
        "slug": "baby_stroller",
        "category": "Baby & Kids",
        "condition": "like_new",
        "price": (250, 750),
        "title": "عربة أطفال ثلاثية العجلات",
        "description": (
            "عربة خفيفة، قابلة للطي، مريحة للسفر. استخدام 8 أشهر فقط، نظيفة ومعقمة. "
            "معها كيس مطر وقبعة شمس."
        ),
    },
    {
        "slug": "tools_drill",
        "category": "Tools & Hardware",
        "condition": "good",
        "price": (150, 450),
        "title": "مثقاب كهربائي احترافي + مجموعة رؤوس",
        "description": (
            "مثقاب لاسلكي 18 فولت، بطاريتان، شاحن سريع. مناسب للأعمال المنزلية والخفيفة. "
            "مع حقيبة حمل."
        ),
    },
    {
        "slug": "tv_samsung",
        "category": "Electronics",
        "condition": "good",
        "price": (1100, 2800),
        "title": "تلفزيون سامسونج 55 بوصة سمارت",
        "description": (
            "دقة 4K، HDR، منافذ كافية. ريموت أصلي، لا بكسلات عالقة. سبب البيع ترقية لشاشة أكبر. "
            "التوصيل يُنسق حسب الاتفاق."
        ),
    },
]

DONATION_SPECS: list[dict] = [
    {
        "slug": "don_tv",
        "category": "Electronics",
        "title": "تلفزيون 43 بوصة — تبرع",
        "description": (
            "تلفزيون يعمل بدون مشاكل، مناسب لغرفة أو مطبخ صغير. أعطيه لمن يحتاجه فعلاً؛ "
            "الاستلام من الحي خلال أسبوع، أرجو الالتزام بالموعد."
        ),
    },
    {
        "slug": "don_sofa",
        "category": "Furniture",
        "title": "كنب ثلاثي للتبرع",
        "description": (
            "كنب قماش بني، بحالة مقبولة، يحتاج تنظيف بسيط. مجاناً لمن يستطيع النقل. "
            "لا أستطيع توصيله؛ يُرفع من الدور الأرضي."
        ),
    },
    {
        "slug": "don_desk",
        "category": "Furniture",
        "title": "مكتب دراسة للتبرع",
        "description": (
            "مكتب أبيض بسيط مع درج واحد، مناسب لطالب أو غرفة صغيرة. مجاني، الاستلام عند الاتفاق."
        ),
    },
    {
        "slug": "don_toys",
        "category": "Baby & Kids",
        "title": "ألعاب أطفال متنوعة — تبرع",
        "description": (
            "مجموعة ألعاب تعليمية وأحجية، لأعمار 3–7 سنوات، نظيفة. أود أن تذهب لعائلة محتاجة."
        ),
    },
    {
        "slug": "don_books",
        "category": "Books",
        "title": "كتب عربية وإنجليزية للتبرع",
        "description": (
            "حوالي 25 كتاباً روائيات وغير خيال، حالة جيدة. للطلاب أو المكتبات الصغيرة المجانية."
        ),
    },
    {
        "slug": "don_kitchen",
        "category": "Kitchen & Dining",
        "title": "أواني مطبخ وأطباق — تبرع",
        "description": (
            "طقم أواني ستانلس، أطباق سيراميك، بعض أكواب الزجاج. كلها صالحة للاستخدام؛ "
            "التبرع لعدم الحاجة بعد الانتقال."
        ),
    },
    {
        "slug": "don_fridge_small",
        "category": "Appliances",
        "title": "ثلاجة صغيرة تعمل — تبرع",
        "description": (
            "ثلاجة مكتبية، مناسبة للغرف أو المكتب. تعمل ببرودة جيدة. مجانية للمن يحتاجها ويستلمها."
        ),
    },
]

ADOPTION_SPECS: list[dict] = [
    {
        "slug": "adopt_cat",
        "category": "Cat",
        "animal_type": "Cat",
        "title": "قطة بالغة للتبني — هادئة",
        "description": (
            "أنثى، عمر تقريبي سنتان، مُعقمة ومُطعّمة. تتأقلم مع الشقة، هادئة ولطيفة. "
            "أبحث عن أسرة تلتزم بالرعاية والمتابعة البيطرية."
        ),
        "vaccinated_status": "vaccinated",
        "gender": "female",
    },
    {
        "slug": "adopt_kittens",
        "category": "Cat",
        "animal_type": "Cat",
        "title": "هريران للتبني المسؤول",
        "description": (
            "عمرهما شهران ونصف، يأكلان وجبات جافة ورطبة، نشيطان. أرجو تبنياً معاً إن أمكن. "
            "لا أسلّم لمن ليس جاداً."
        ),
        "vaccinated_status": "unknown",
        "gender": "unknown",
    },
    {
        "slug": "adopt_bird",
        "category": "Bird",
        "animal_type": "Bird",
        "title": "كناري صغير للتبني",
        "description": (
            "كناري صحي، يحتاج قفصاً واسعاً وهدوءاً. أتبرع به لضيق المساحة. معه الحبوب المتبقية."
        ),
        "vaccinated_status": "unknown",
        "gender": "unknown",
    },
    {
        "slug": "adopt_rabbit",
        "category": "Other",
        "animal_type": "Rabbit",
        "title": "أرنب صغير للتبني",
        "description": (
            "أرنب أليف، يأكل الخضار والعلف، يحتاج رعاية يومية. أبحث عن صاحب يفهم احتياجات الأرانب."
        ),
        "vaccinated_status": "unknown",
        "gender": "unknown",
    },
    {
        "slug": "adopt_dog",
        "category": "Dog",
        "animal_type": "Dog",
        "title": "كلب صغير للتبني — تدريب منزلي أساسي",
        "description": (
            "ذكر، عمر 10 أشهر، مُطعّم جزئياً. نشيط ويحتاج مشي يومي. أبحث عن بيت بحديقة أو شقة واسعة."
        ),
        "vaccinated_status": "vaccinated",
        "gender": "male",
    },
]


def service_title_and_description(cat_key: str) -> tuple[str, str]:
    """Rich copy per canonical service category."""
    t: dict[str, tuple[str, str]] = {
        "teacher": (
            "مدرس رياضيات وفيزياء — ثانوي",
            "خبرة 8 سنوات في التدريس الخصوصي داخل الرياض، أغطي المنهج السعودي والدولي. "
            "حصص أونلاين أو حضوري حسب الحي. أرسل مستوى الطالب والموعد المفضل.",
        ),
        "delivery_driver": (
            "توصيل طرود وأغراض داخل الرياض",
            "سائق مع سيارة بضائع صغيرة، أغطي شمال وجنوب الرياض حسب الاتفاق. "
            "أسعار حسب المسافة والوقت، استلام من الباب وتسليم مؤكد.",
        ),
        "electrician": (
            "كهربائي منازل — تركيب وصيانة",
            "فحص لوحات، تمديد مخارج، إصلاح تسربات بسيطة، تركيب إنارة LED. "
            "أعمال نظيفة مع ضمان قصير على التركيب. مواعيد مسائية متاحة.",
        ),
        "ac_technician": (
            "فني مكيفات — تنظيف وشحن غاز",
            "صيانة سبليت وشباك، تنظيف عميق، كشف تسرب غاز، استشارة قبل الصيف. "
            "أغطي معظم أحياء الوسط والشرق.",
        ),
        "plumber": (
            "سباك معتمد — تسربات وصرف",
            "إصلاح تسربات، تسليك مجاري، تركيب سيفونات وخلاطات. "
            "أستخدم مواد موثوقة، أسعار واضحة قبل البدء.",
        ),
        "government_services": (
            "مساعدة في إجراءات ووثائق (توجيه فقط)",
            "أوجّهك لخطوات بعض الخدمات الحكومية الإلكترونية والمواعيد؛ لست ممثلاً رسمياً. "
            "مناسب لمن يحتاج ترتيب ملفات أو مواعيد.",
        ),
        "babysitter": (
            "جليسة أطفال — مسائية وعطلة",
            "خبرة مع أعمار 1–8 سنوات، أولوية لمنزل هادئ. "
            "أتكلم العربية والإنجليزية، يمكن مراجع من عائلات سابقة عند الطلب.",
        ),
        "carpenter": (
            "نجار أثاث — تعديل وتركيب",
            "تعديل أبواب خزائن، تركيب أرفف، صيانة مفصلات. "
            "أعمل بمواد يختارها العميل أو أقترح بدائل اقتصادية.",
        ),
        "construction": (
            "مقاول صغير — تشطيبات وترميمات محدودة",
            "دهانات، معجون، تركيب سيراميك بسيط، إشراف على عمال باتفاق. "
            "مشاريع صغيرة داخل الرياض فقط.",
        ),
        "security_guard": (
            "حارس أمن لفعاليات صغيرة",
            "خبرة في تنظيم دخول وخروج، تعامل مع الجمهور، تنسيق مع المنظمين. "
            "متوفر لأيام محددة وليس دوام كامل إلا بالاتفاق.",
        ),
        "events": (
            "تنسيق فعاليات صغيرة — أعياد ميلاد وعائلي",
            "تنسيق بسيط، تنسيق طاولات، تنسيق مع موردين محليين. "
            "أركز على الفعاليات المنزلية وصالات صغيرة.",
        ),
        "photographer": (
            "تصوير منتجات وصور شخصية",
            "تصوير إضاءة طبيعية واستوديو خفيف، تسليم ملفات عالية الدقة. "
            "مناسب لمتاجر صغيرة وبروفايلات مهنية.",
        ),
        "barista": (
            "بارستا لفعاليات — قهوة مختصة",
            "تجهيز قهوة للمناسبات الصغيرة، معداتي أو معدات العميل. "
            "قائمة محدودة: إسبريسو وفلات وايت وبارد.",
        ),
        "other": (
            "خدمات منزلية متنوعة — حسب الطلب",
            "تنظيف عميق، ترتيب مخازن، مساعدة في الانتقال داخل البيت. "
            "نحدد النطاق والسعر قبل اليوم الأول.",
        ),
    }
    return t.get(cat_key, t["other"])
