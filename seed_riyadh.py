"""
seed_riyadh.py — بيانات تجريبية لمدينة الرياض
يولّد مستخدمين وإعلانات عربية بإحداثيات موزّعة جغرافياً على الرياض لاختبار الخريطة.

خطة الإحداثيات (اختبار الخريطة / bounds / التكبير):
  - لا تُجمّع كل الإعلانات في منطقة واحدة؛ تُوزّع على 5 مناطق عريضة: شمال، جنوب، شرق، غرب، وسط.
  - كل منطقة لها صندوق إحداثيات (bounding box) داخل نطاق الرياض؛ يُولَّد داخلها موقع عشوائي + jitter خفيف.
  - الحد الأقصى/الأدنى النهائي يُثبَّت ضمن مغلف الرياض حتى لا تخرج النقاط خارج المدينة.
  - يُحسب تقرير جغرافي في النهاية: عدد لكل منطقة، min/max lat/lon.

الاستخدام:
    cd backend
    python seed_riyadh.py
    python seed_riyadh.py --count 250

ملاحظة: يعمل فقط في بيئة التطوير. لا تشغّله في الإنتاج.
"""

import random
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

SEED_PASSWORD = "dev123"

# ── مغلف الرياض (حدود تقريبية للمدينة — كل الإحداثيات تُقصّ داخله) ─────────────
RIYADH_BOUNDS = {
    "min_lat": 24.42,
    "max_lat": 24.92,
    "min_lon": 46.48,
    "max_lon": 46.92,
}

# ── مناطق عريضة لاختبار الخريطة (صناديق داخل المغلف؛ تداخل طفيف عند الحواف مقبول) ─
# المعرّفات للتصحيح فقط وليست حقولاً في قاعدة البيانات.
RIYADH_ZONES = [
    {
        "id": "north",
        "label_en": "North Riyadh",
        "label_ar": "شمال الرياض",
        "min_lat": 24.76,
        "max_lat": 24.90,
        "min_lon": 46.54,
        "max_lon": 46.82,
    },
    {
        "id": "south",
        "label_en": "South Riyadh",
        "label_ar": "جنوب الرياض",
        "min_lat": 24.48,
        "max_lat": 24.62,
        "min_lon": 46.56,
        "max_lon": 46.84,
    },
    {
        "id": "east",
        "label_en": "East Riyadh",
        "label_ar": "شرق الرياض",
        "min_lat": 24.56,
        "max_lat": 24.80,
        "min_lon": 46.74,
        "max_lon": 46.90,
    },
    {
        "id": "west",
        "label_en": "West Riyadh",
        "label_ar": "غرب الرياض",
        "min_lat": 24.56,
        "max_lat": 24.80,
        "min_lon": 46.48,
        "max_lon": 46.66,
    },
    {
        "id": "central",
        "label_en": "Central Riyadh",
        "label_ar": "وسط الرياض",
        "min_lat": 24.63,
        "max_lat": 24.76,
        "min_lon": 46.62,
        "max_lon": 46.76,
    },
]

# تشتت إضافي داخل المنطقة (درجات تقريبية ~±400m) لتفادي تطابق النقاط
_JITTER_LAT = 0.004
_JITTER_LON = 0.004
# تشتت إضافي بين موقع المستخدم وإعلانه (أصغر قليلاً)
_LISTING_JITTER = 0.012


def clamp_to_riyadh(lat: float, lon: float) -> tuple[float, float]:
    b = RIYADH_BOUNDS
    return (
        max(b["min_lat"], min(b["max_lat"], lat)),
        max(b["min_lon"], min(b["max_lon"], lon)),
    )


def random_point_in_zone(zone: dict, rng: random.Random) -> tuple[float, float, str]:
    """يولّد نقطة داخل صندوق المنطقة + jitter عشوائي، ثم يقصّها ضمن مغلف الرياض."""
    lat = rng.uniform(zone["min_lat"], zone["max_lat"])
    lon = rng.uniform(zone["min_lon"], zone["max_lon"])
    lat += rng.uniform(-_JITTER_LAT, _JITTER_LAT)
    lon += rng.uniform(-_JITTER_LON, _JITTER_LON)
    lat, lon = clamp_to_riyadh(lat, lon)
    return round(lat, 6), round(lon, 6), zone["id"]


def allocate_counts_across_zones(total: int, n_zones: int) -> list[int]:
    """توزيع متوازن قدر الإمكان (مثلاً 202 → 41+41+40+40+40)."""
    base = total // n_zones
    rem = total % n_zones
    return [base + (1 if i < rem else 0) for i in range(n_zones)]


def build_zone_assignment_queue(counts: list[int], rng: random.Random) -> list[dict]:
    """قائمة مناطق بطول إجمالي المستخدمين؛ تُخلط لتوزيع ترتيب الإنشاء على الخريطة."""
    queue: list[dict] = []
    for zi, n in enumerate(counts):
        queue.extend([RIYADH_ZONES[zi]] * n)
    rng.shuffle(queue)
    return queue

# ── بيانات المستخدمين ────────────────────────────────────────────────────────
ARABIC_FIRST_NAMES = [
    "محمد", "أحمد", "عبدالله", "عمر", "خالد", "سعد", "فيصل", "ناصر", "علي",
    "إبراهيم", "عبدالرحمن", "يوسف", "سلطان", "بندر", "تركي", "وليد", "رائد",
    "زياد", "هاني", "نواف", "مشعل", "طلال", "صالح", "سامي", "راشد",
    "مريم", "نورة", "ريم", "سارة", "هند", "لمياء", "منى", "شيماء", "رنا", "هيا",
]

ARABIC_LAST_NAMES = [
    "العتيبي", "الغامدي", "القحطاني", "الشهري", "الزهراني", "الدوسري",
    "المطيري", "الرشيدي", "الحربي", "العنزي", "السلمي", "الأحمدي",
    "البقمي", "الشمري", "الجهني", "العسيري", "السبيعي", "الوادعي",
    "الحميدي", "المالكي", "الصقري", "الشريف", "العواجي", "العمري",
]

# ── قوالب الإعلانات بالعربي (أصناف متنوعة) ───────────────────────────────────
LISTING_TEMPLATES = [
    # أثاث
    {
        "domain": "item", "type": "sale", "category": "Furniture",
        "condition": "good",
        "titles": [
            "طاولة خشبية مستعملة للبيع",
            "كنب زاوية كبير بحالة ممتازة",
            "غرفة نوم كاملة للبيع",
            "مكتب دراسة بحالة جيدة",
            "رف كتب خشبي للبيع",
        ],
        "descriptions": [
            "طاولة خشبية بحالة جيدة جداً، الأبعاد 120×60 سم، مناسبة للمكتب أو المطبخ. السبب في البيع الانتقال لمنزل جديد. بدون تفاوض على السعر.",
            "كنب زاوية كبير مقاس L بحالة ممتازة، لونه رمادي فاتح، نسيج قماش عالي الجودة. استخدام سنة ونصف فقط. يتحمل الوزن الزائد.",
            "غرفة نوم كاملة تتكون من سرير كبير، خزانة ملابس أربعة أبواب، تسريحة، كوميدينو. الخشب من نوع MDF عالي الجودة.",
            "مكتب دراسة باللون الأبيض، به درجان للتخزين، مناسب للأطفال والكبار. الطول 140 سم. يصلح للعمل من المنزل.",
            "رف كتب خشبي 5 طوابق، اللون البني الداكن، الحالة ممتازة. يتسع لعدد كبير من الكتب والمجلدات.",
        ],
        "tags": ["أثاث", "للبيع", "بحالة-جيدة"],
        "price_range": (200, 2500),
    },
    # إلكترونيات
    {
        "domain": "item", "type": "sale", "category": "Electronics",
        "condition": "like_new",
        "titles": [
            "آيباد برو للبيع بحالة ممتازة",
            "لابتوب ديل i7 مستعمل بحالة جيدة",
            "شاشة سامسونج 27 بوصة للبيع",
            "سماعة سوني لاسلكية للبيع",
            "كاميرا كانون احترافية للبيع",
        ],
        "descriptions": [
            "آيباد برو 12.9 إنش الجيل الثالث، سعة 256 جيجا، لون رمادي فلكي. معه الكيبورد الأصلي والقلم. لا توجد خدوش. البيع للحاجة للسيولة فقط.",
            "لابتوب ديل XPS، معالج i7 الجيل الحادي عشر، رام 16 جيجا، SSD 512. يعمل بكفاءة عالية جداً. يصلح للبرمجة والتصميم.",
            "شاشة سامسونج 27 بوصة QHD، دقة عالية جداً، مثالية للعمل والألعاب. الحالة ممتازة لا توجد أي مشاكل. كيبل الشحن موجود.",
            "سماعة سوني WH-1000XM4 لاسلكية، خاصية إلغاء الضوضاء. الحالة شبه جديدة، استخدام 3 أشهر فقط. البطارية تدوم 30 ساعة.",
            "كاميرا كانون EOS R50 مع عدسة 18-55 ملم الأصلية. استخدمتها لمدة 6 أشهر فقط للتصوير الشخصي. مع الحقيبة الأصلية وبطاريتين.",
        ],
        "tags": ["إلكترونيات", "للبيع", "شبه-جديد"],
        "price_range": (500, 4500),
    },
    # أجهزة منزلية
    {
        "domain": "item", "type": "sale", "category": "Appliances",
        "condition": "good",
        "titles": [
            "غسالة سامسونج 7 كيلو للبيع",
            "ثلاجة إل جي 500 لتر للبيع",
            "مكيف سبليت 2 طن للبيع",
            "فرن كهربائي ديجيتال للبيع",
            "مغسلة توشيبا بحالة ممتازة",
        ],
        "descriptions": [
            "غسالة سامسونج فل أوتوماتيك 7 كيلو، تعمل بكفاءة عالية. الحالة جيدة جداً. السبب في البيع الانتقال لشقة مفروشة. تصلح للعائلة الصغيرة.",
            "ثلاجة إل جي نوع فرنش دور، سعة 500 لتر، لونها فضي. لها 3 سنوات من الاستخدام وتعمل بشكل ممتاز. بدون خدوش ظاهرة.",
            "مكيف سبليت 2 طن ماركة كاريير. يعمل بشكل مثالي. تمت صيانته العام الماضي. مع ريموت أصلي. السبب في البيع التنقل.",
            "فرن كهربائي ديجيتال 90 لتر، 6 وظائف، مع دوار للشواء. الحالة جيدة جداً. استخدمته 2 سنة فقط.",
            "مغسلة توشيبا أتوماتيك 9 كيلو، برامج متعددة، موفرة للماء. الحالة ممتازة. مع خرطوم الصرف الأصلي.",
        ],
        "tags": ["أجهزة-منزلية", "للبيع"],
        "price_range": (300, 2000),
    },
    # ملابس وأحذية
    {
        "domain": "item", "type": "sale", "category": "Clothing",
        "condition": "like_new",
        "titles": [
            "عباية فاخرة بحالة ممتازة",
            "حذاء أديداس مقاس 43 للبيع",
            "جاكيت شتوي رجالي للبيع",
            "ساعة رجالي ماركة سيكو للبيع",
            "حقيبة نسائية جلد طبيعي للبيع",
        ],
        "descriptions": [
            "عباية من قماش الكريب الفاخر، لونها أسود مع تطريز ذهبي خفيف. المقاس 58. لبستها مرة واحدة فقط في مناسبة. الحالة ممتازة.",
            "حذاء أديداس Ultraboost مقاس 43، استخدام خفيف جداً. اللون أبيض. مناسب للرياضة والاستخدام اليومي. مع الصندوق الأصلي.",
            "جاكيت شتوي رجالي ماركة Zara، مقاس L، لونه كحلي. الحالة ممتازة، نظيف ومغسول. مناسب للطقس البارد.",
            "ساعة سيكو رجالي أوتوماتيك، مينا بيضاء، سوار جلد بني. الحالة ممتازة، مع كرتون وملحقاتها. اشتريتها هدية ولم أستخدمها.",
            "حقيبة نسائية من الجلد الطبيعي البني، ماركة Guess. الحالة شبه جديدة، مع سحاب داخلي وجيوب جانبية. واسعة ومريحة.",
        ],
        "tags": ["ملابس", "للبيع", "شبه-جديد"],
        "price_range": (100, 900),
    },
    # كتب ومقتنيات
    {
        "domain": "item", "type": "donation", "category": "Books",
        "condition": "good",
        "titles": [
            "مجموعة كتب علمية للتبرع",
            "كتب أدبية عربية للتبرع",
            "موسوعة علمية للأطفال هدية",
            "مراجع طبية للتبرع",
            "كتب دراسية جامعية مجانية",
        ],
        "descriptions": [
            "مجموعة من 15 كتاباً علمياً في مجالات الفيزياء والكيمياء والرياضيات. مناسبة لطلاب الثانوية والجامعة. الحالة جيدة ومقروءة.",
            "مجموعة روايات عربية وعالمية مترجمة، من أعمال نجيب محفوظ وغسان كنفاني وغيرهم. 20 رواية بحالة جيدة.",
            "موسوعة علمية للأطفال 12 مجلد، ملونة ومصورة، تشمل جميع المجالات. مناسبة للأعمار 8-15 سنة. الحالة ممتازة.",
            "كتب ومراجع طبية تخص طب الأسرة والداخلية. مناسبة لطلاب كليات الطب. من يريد التبرع للتواصل مباشرة.",
            "مراجع دراسية تخصص الهندسة الكهربائية، سنة 3 و4. جاهزة للاستلام. من يحتاجها يتواصل لترتيب الاستلام.",
        ],
        "tags": ["كتب", "تبرع", "مجاني"],
        "price_range": None,
    },
    # معدات رياضية
    {
        "domain": "item", "type": "sale", "category": "Sports & Outdoors",
        "condition": "good",
        "titles": [
            "جهاز مشي كهربائي للبيع",
            "دراجة رياضية للبيع",
            "معدات صالة منزلية للبيع",
            "طاولة بينج بونج للبيع",
            "معدات كرة القدم للبيع",
        ],
        "descriptions": [
            "جهاز مشي كهربائي ماركة Life Fitness، يعمل بشكل ممتاز. الحالة جيدة جداً. استخدام 18 شهراً. السبب ضيق المساحة. يوجد ضمان متبقي.",
            "دراجة رياضية هوائية 21 سرعة، إطار ألومنيوم خفيف. الحالة جيدة. مناسبة للرحلات والاستخدام اليومي. مع كرسي مريح وحامل بطارية.",
            "مجموعة معدات صالة منزلية: بار حديد وأثقال، حامل، حبل قفز. الحالة جيدة. سبب البيع الاشتراك بالنادي الرياضي.",
            "طاولة بينج بونج قابلة للطي، حالة جيدة. مع مجداف وكرات. مناسبة للاستخدام الداخلي والخارجي. السعر قابل للتفاوض.",
            "معدات كرة قدم: حارس مرمى أصلي، كرة ماركة Adidas، أحذية مقاس 42. كلها بحالة جيدة.",
        ],
        "tags": ["رياضة", "للبيع", "معدات"],
        "price_range": (200, 3000),
    },
    # خدمات منزلية
    {
        "domain": "service", "type": None, "category": "Plumber",
        "condition": None,
        "titles": [
            "سباك محترف متاح في الرياض",
            "خدمات السباكة والصرف الصحي",
            "فني سباكة لإصلاح التسربات",
            "سباك معتمد لأعمال السباكة",
            "أعمال سباكة فورية وموثوقة",
        ],
        "descriptions": [
            "سباك محترف بخبرة 10 سنوات في الرياض. أقوم بجميع أعمال السباكة: تمديد وإصلاح المواسير، تركيب الأحواض والصنابير، إصلاح تسربات المياه. متوفر 24/7.",
            "أتخصص في أعمال الصرف الصحي وتسليك المجاري. لديّ أجهزة حديثة للكشف عن التسربات دون تكسير. خدمة سريعة وأسعار مناسبة.",
            "فني سباكة معتمد وذو خبرة. أعالج جميع أنواع تسربات المياه سواء في الحوائط أو الأسقف أو تحت الأرض. ضمان على أعمالي.",
            "خبير في تركيب وصيانة خزانات المياه السطحية والأرضية. أيضاً صيانة الطلمبات ووحدات الضغط. أعمل في جميع أحياء الرياض.",
            "خدمات سباكة فورية وطوارئ على مدار الساعة. تشمل إصلاح الكسور، الانسداد، التسربات وأعمال التمديد الجديدة. أسعار تنافسية.",
        ],
        "tags": ["سباكة", "خدمات", "خبير"],
        "price_range": None,
        "service_fields": {"pricing_model": "negotiable", "service_mode": "at_client_location"},
    },
    # كهربائي
    {
        "domain": "service", "type": None, "category": "Electrician",
        "condition": None,
        "titles": [
            "كهربائي منازل محترف في الرياض",
            "خدمات الكهرباء المنزلية والتجارية",
            "تركيب وصيانة كاميرات المراقبة",
            "فني كهرباء لجميع الأعمال",
            "أعمال كهربائية احترافية",
        ],
        "descriptions": [
            "كهربائي محترف بخبرة 8 سنوات. أقدم خدمات: تركيب اللوحات الكهربائية، تمديد الأسلاك، إصلاح الأعطال، تركيب المحولات. ضمان على الأعمال.",
            "متخصص في الكهرباء التجارية والمنزلية. أتعامل مع جميع الأعطال الكهربائية. لديّ تأهيل من هيئة المهندسين. أعمل خلال ساعات وعطلة.",
            "فني متخصص في تركيب وصيانة كاميرات المراقبة وأجهزة الإنذار. أيضاً تركيب شاشات وأنظمة الصوت المنزلي. تركيب سريع وأسعار مناسبة.",
            "فني كهرباء لجميع الأعمال المنزلية: تركيب مخارج ومقابس، إصلاح الإضاءة، تركيب المراوح، الصيانة الدورية. خدمة سريعة وموثوقة.",
            "أعمال كهربائية متكاملة: مخططات كهربائية، تمديد، تركيب، صيانة. أستخدم مواد عالية الجودة. ضمان سنة على الأعمال.",
        ],
        "tags": ["كهرباء", "خدمات", "محترف"],
        "price_range": None,
        "service_fields": {"pricing_model": "hourly", "service_mode": "at_client_location"},
    },
    # حيوانات للتبني
    {
        "domain": "item", "type": "adoption", "category": "Cat",
        "condition": None,
        "titles": [
            "قطة صغيرة للتبني في الرياض",
            "قطة شيرازي للتبني",
            "قطط صغار مُحصّنة للتبني",
            "قط مين كون للتبني",
            "قطة مُلقّحة للتبني",
        ],
        "descriptions": [
            "قطة صغيرة عمر 3 أشهر، لونها أبيض مع نقاط رمادية. مُطعّمة وتأكل وجبات جافة. تحتاج منزلاً محباً. مع مستلزماتها.",
            "قطة شيرازي أنثى، عمر سنة، لونها بيج. هادئة ومؤدبة، لا تخدش. مُحصّنة ومُطعّمة بالكامل. السبب في التبني السفر الطويل.",
            "3 قطط صغار، عمر شهرين ونصف. مُحصّنة وتتغذى على الأكل الجاف والرطب. طيبة مع الأطفال. لمن يريد قطة واحدة أو أكثر.",
            "قط مين كون ذكر كبير، لونه بني شوكولاتة. ودود جداً ومُدجّن. مُطعّم وبصحة ممتازة. يحتاج منزلاً واسعاً.",
            "قطة مُلقّحة ومُعقّمة، عمر سنتين، لونها رمادي. ألفت البشر والأطفال. مع دفتر تطعيماتها الكامل. السبب في التبني حساسية أحد أفراد الأسرة.",
        ],
        "tags": ["قطط", "تبني", "ملقحة"],
        "price_range": None,
        "adoption_fields": {"animal_type": "Cat", "vaccinated_status": "vaccinated"},
    },
    # أدوات
    {
        "domain": "item", "type": "sale", "category": "Tools & Hardware",
        "condition": "good",
        "titles": [
            "مجموعة أدوات كهربائية للبيع",
            "مثقاب بوش احترافي للبيع",
            "صندوق أدوات متكامل للبيع",
            "مولد كهربائي للبيع",
            "مضخة مياه للبيع",
        ],
        "descriptions": [
            "مجموعة أدوات كهربائية تشمل مثقاب، منشار، مصنفرة. ماركة Makita. الحالة جيدة جداً. مع حقيبة الحفظ الأصلية. للاستفسار التواصل مباشرة.",
            "مثقاب بوش احترافي 18 فولت، شارجتين، حقيبة. الحالة ممتازة. يصلح للحفر في الجدران والحديد والخشب. مع مجموعة بنانير.",
            "صندوق أدوات فلاحي متكامل: مفاتيح، مقصات، مطارق، مسامير وبراغي. كل ما تحتاجه في منزلك. الحالة ممتازة.",
            "مولد كهربائي 5 كيلوواط، بنزين. الحالة جيدة، يعمل بكفاءة. مناسب للطوارئ والمواقع البعيدة عن الكهرباء.",
            "مضخة مياه كهربائية 1 حصان. تعمل بكفاءة عالية. مناسبة لملء الخزانات ورش الحدائق. الحالة جيدة مع إطار حماية.",
        ],
        "tags": ["أدوات", "للبيع", "كهربائي"],
        "price_range": (150, 1800),
    },
    # مستلزمات المطبخ
    {
        "domain": "item", "type": "sale", "category": "Kitchen & Dining",
        "condition": "like_new",
        "titles": [
            "طقم أواني طبخ للبيع",
            "ماكينة قهوة إسبريسو للبيع",
            "خلاط كهربائي قوي للبيع",
            "طقم صحون وأكواب للبيع",
            "فرن هواء للبيع",
        ],
        "descriptions": [
            "طقم أواني طبخ من الإستانلس ستيل 12 قطعة. ماركة Tefal. مقاومة للالتصاق. الحالة ممتازة، استخدام سنة فقط. مع الأغطية الزجاجية.",
            "ماكينة قهوة إسبريسو ديلونجي 15 بار. تصنع قهوة احترافية. مع مطحنة قهوة مجاناً. الحالة ممتازة. السبب الانتقال لمنزل به ماكينة.",
            "خلاط كهربائي Philips 2200 واط مع ملحقات متعددة. يصلح للعصائر والعجين والتقطيع. الحالة ممتازة.",
            "طقم صحون وأكواب لـ 12 شخص. بورسلان عالي الجودة، ديكور ذهبي خفيف. من مجموعة العروس. نظيف وكامل بدون كسر.",
            "فرن هواء ديجيتال 12 لتر، 8 وظائف. يقلي بدون زيت. الحالة شبه جديدة، استخدام شهرين فقط. مع التعليمات بالعربية.",
        ],
        "tags": ["مطبخ", "للبيع", "شبه-جديد"],
        "price_range": (100, 1200),
    },
]

# ── إنشاء بيانات المستخدمين ───────────────────────────────────────────────────
def generate_users(count: int, rng: random.Random) -> tuple[list[dict], dict[str, int]]:
    """
    يوزّع المستخدمين بالتساوي قدر الإمكان على مناطق الرياض الخمس.
    يُخزَّن _seed_zone داخلياً للتقرير فقط (لا يُكتب في قاعدة البيانات).
    """
    used_emails = set()
    users: list[dict] = []
    zone_stats: dict[str, int] = {z["id"]: 0 for z in RIYADH_ZONES}
    counts = allocate_counts_across_zones(count, len(RIYADH_ZONES))
    zone_queue = build_zone_assignment_queue(counts, rng)

    while len(users) < count:
        first = rng.choice(ARABIC_FIRST_NAMES)
        last = rng.choice(ARABIC_LAST_NAMES)
        idx = len(users) + 1
        email = f"user{idx:03d}@dev.riyadh.local"
        username = f"user_{idx:03d}"
        if email in used_emails:
            continue
        used_emails.add(email)

        zone = zone_queue[len(users)]
        lat, lon, zid = random_point_in_zone(zone, rng)
        zone_stats[zid] += 1

        users.append({
            "email": email,
            "username": username,
            "full_name": f"{first} {last}",
            "lat": lat,
            "lon": lon,
            "city": "الرياض",
            "_seed_zone": zid,
        })
    return users, zone_stats


def generate_listing(user: dict, idx: int, rng: random.Random) -> dict:
    template = LISTING_TEMPLATES[idx % len(LISTING_TEMPLATES)]

    title_list = template["titles"]
    desc_list = template["descriptions"]
    title = title_list[idx % len(title_list)]
    description = desc_list[idx % len(desc_list)]

    # تشتت عن موقع المستخدم مع إبقاء النقطة داخل الرياض
    lat = user["lat"] + rng.uniform(-_LISTING_JITTER, _LISTING_JITTER)
    lon = user["lon"] + rng.uniform(-_LISTING_JITTER, _LISTING_JITTER)
    lat, lon = clamp_to_riyadh(lat, lon)

    price = None
    if template.get("price_range"):
        lo, hi = template["price_range"]
        price = rng.randint(lo // 10, hi // 10) * 10  # يقرب لأقرب 10

    return {
        "title": title,
        "description": description,
        "domain": template["domain"],
        "type": template["type"],
        "category": template.get("category"),
        "condition": template.get("condition"),
        "tags": template.get("tags", []),
        "price": price,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "adoption_fields": template.get("adoption_fields"),
        "service_fields": template.get("service_fields"),
    }


def _log_geographic_seed_report(
    *,
    zone_stats_users: dict[str, int],
    zone_stats_listings: dict[str, int],
    item_lats: list[float],
    item_lons: list[float],
    total_listings: int,
) -> None:
    """ملخص جغرافي بعد الزرع — للتحقق من توزيع الخريطة دون تغيير المخطط."""
    b = RIYADH_BOUNDS
    log.info("--- Geographic seed report (Riyadh map testing) ---")
    log.info(
        "Listings use zone-balanced coordinates + jitter, clamped to the Riyadh envelope "
        "so Discover, pan/zoom, and bounds search can be tested across the city."
    )
    for z in RIYADH_ZONES:
        zid = z["id"]
        log.info(
            "  Zone %-9s (%s / %s): users=%d, listings=%d",
            zid,
            z["label_en"],
            z["label_ar"],
            zone_stats_users.get(zid, 0),
            zone_stats_listings.get(zid, 0),
        )
    if item_lats and item_lons:
        log.info(
            "  Item coordinates — lat min/max: %.6f / %.6f | lon min/max: %.6f / %.6f",
            min(item_lats),
            max(item_lats),
            min(item_lons),
            max(item_lons),
        )
    log.info(
        "  Riyadh clamp envelope used: lat [%.2f, %.2f], lon [%.2f, %.2f]",
        b["min_lat"],
        b["max_lat"],
        b["min_lon"],
        b["max_lon"],
    )
    log.info("--- End geographic report (total listings: %d) ---", total_listings)


# ── تنفيذ السيد ────────────────────────────────────────────────────────────────
def run(num_users: int = 250):
    from app.database import SessionLocal
    from app.models import User, Tag, ItemTag
    from app.models.item import Item, ItemStatus, AdoptionDetails, ServiceDetails
    from app.services.auth_service import hash_password

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email.like("%@dev.riyadh.local")).count()
        if existing > 0:
            log.info("بيانات الرياض التجريبية موجودة بالفعل (%d مستخدم). استخدم --force لإعادة التوليد.", existing)
            return

        log.info("جاري إنشاء %d مستخدم وإعلان في الرياض (توزيع جغرافي على 5 مناطق)…", num_users)
        hashed_pw = hash_password(SEED_PASSWORD)

        rng = random.Random()
        users_data, zone_stats_users = generate_users(num_users, rng)
        created_users = []

        for u in users_data:
            user = User(
                email=u["email"],
                username=u["username"],
                hashed_password=hashed_pw,
                latitude=u["lat"],
                longitude=u["lon"],
                city=u["city"],
            )
            db.add(user)
            db.flush()
            created_users.append((user, u))

        log.info("تم إنشاء %d مستخدم. جاري إنشاء الإعلانات…", len(created_users))

        items_created = 0
        zone_stats_listings: dict[str, int] = {z["id"]: 0 for z in RIYADH_ZONES}
        all_item_lats: list[float] = []
        all_item_lons: list[float] = []

        for idx, (user, user_data) in enumerate(created_users):
            listing = generate_listing(user_data, idx, rng)
            zid = user_data.get("_seed_zone")
            if zid in zone_stats_listings:
                zone_stats_listings[zid] += 1
            all_item_lats.append(listing["lat"])
            all_item_lons.append(listing["lon"])

            domain = listing["domain"]
            ltype = listing["type"]
            is_adoption = ltype == "adoption"
            is_service = domain == "service"
            condition = listing["condition"] or "good"
            status = ItemStatus.available.value

            item = Item(
                user_id=user.id,
                title=listing["title"],
                description=listing["description"],
                category=listing["category"],
                condition=None if (is_adoption or is_service) else condition,
                status=status,
                is_public=True,
                latitude=listing["lat"],
                longitude=listing["lon"],
                listing_domain=domain,
                listing_type=ltype,
                price=listing["price"],
                currency="SAR" if listing["price"] else None,
                allow_messages=True,
            )
            db.add(item)
            db.flush()

            # إضافة وسوم
            for tag_name in listing["tags"]:
                tag = db.query(Tag).filter(Tag.name == tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    db.add(tag)
                    db.flush()
                db.add(ItemTag(item_id=item.id, tag_id=tag.id))

            # تفاصيل التبني
            if is_adoption and listing.get("adoption_fields"):
                af = listing["adoption_fields"]
                db.add(AdoptionDetails(
                    item_id=item.id,
                    animal_type=af.get("animal_type", ""),
                    vaccinated_status=af.get("vaccinated_status", "unknown"),
                ))

            # تفاصيل الخدمة
            if is_service and listing.get("service_fields"):
                sf = listing["service_fields"]
                db.add(ServiceDetails(
                    item_id=item.id,
                    service_category=listing.get("category", ""),
                    pricing_model=sf.get("pricing_model", "negotiable"),
                    service_mode=sf.get("service_mode", "at_client_location"),
                ))

            items_created += 1
            if items_created % 50 == 0:
                log.info("  تم إنشاء %d إعلان…", items_created)

        db.commit()
        log.info("✅ تمّ بنجاح: %d مستخدم، %d إعلان في الرياض.", len(created_users), items_created)
        log.info("   كلمة المرور للجميع: %s", SEED_PASSWORD)
        log.info("   مثال للدخول: user_001@dev.riyadh.local / %s", SEED_PASSWORD)
        _log_geographic_seed_report(
            zone_stats_users=zone_stats_users,
            zone_stats_listings=zone_stats_listings,
            item_lats=all_item_lats,
            item_lons=all_item_lons,
            total_listings=items_created,
        )

    except Exception as e:
        log.exception("فشل إنشاء البيانات: %s", e)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


def purge():
    """حذف جميع بيانات التجريب (للتنظيف)."""
    from app.database import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        test_users = db.query(User).filter(User.email.like("%@dev.riyadh.local")).all()
        for u in test_users:
            db.delete(u)
        db.commit()
        log.info("تم حذف %d مستخدم تجريبي.", len(test_users))
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="بيانات تجريبية للرياض")
    parser.add_argument("--purge", action="store_true", help="حذف بيانات التجريب")
    parser.add_argument(
        "--count",
        type=int,
        default=250,
        help="عدد المستخدمين/الإعلانات (افتراضي 250 ≈50 لكل منطقة من 5؛ استخدم 200+ لاختبار الخريطة)",
    )
    args = parser.parse_args()

    if args.purge:
        purge()
    else:
        run(num_users=args.count)
