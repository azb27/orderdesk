"""How retailers actually write orders: street names for products, sizes, units and numbers in four styles.

Styles: en (Gulf shop English), ar (Arabic script), arabizi (Arabic in Latin letters with digits for
sounds: 3 = ع, 7 = ح, 2 = ء, 5 = خ, 6 = ط, 9 = ص/ق), roman (Hindi/Urdu in Latin letters, common among
South Asian shopkeepers in the UAE).

Circularity guard (SPEC §3): every product street term is assigned to `seen` or `heldout` by a stable
hash. Seen terms go into the alias table the parser can use; held-out terms only ever appear in eval
messages, so the eval can report how the parser does on names it has never been given.
"""

from __future__ import annotations

import hashlib
import re

from orderdesk.world.catalogue import FAMILIES, Family

STYLES = ("en", "ar", "arabizi", "roman")
HELDOUT_SHARE = 0.30

# ---- generic product concepts, per style --------------------------------------------------------
C: dict[str, dict[str, list[str]]] = {
    "cola": {"en": ["cola", "kola", "cola drink"], "ar": ["كولا", "مشروب كولا"], "arabizi": ["kola", "cola"], "roman": ["cola", "kola", "cold drink cola"]},
    "diet": {"en": ["diet", "light"], "ar": ["دايت", "لايت"], "arabizi": ["dayet", "diet", "lait"], "roman": ["diet", "dait"]},
    "zero": {"en": ["zero", "zero sugar"], "ar": ["زيرو"], "arabizi": ["zero", "ziro"], "roman": ["zero"]},
    "lemon_soda": {"en": ["lemon soda", "lemon drink", "white soda"], "ar": ["ليمون غازي", "مشروب ليمون"], "arabizi": ["laymoon", "lamoon soda"], "roman": ["nimbu soda", "lemon soda", "nimboo"]},
    "orange_soda": {"en": ["orange soda", "orange drink"], "ar": ["برتقال غازي", "مشروب برتقال"], "arabizi": ["burtu2al", "bortgal", "burtugal"], "roman": ["orange cold drink", "santra soda"]},
    "citrus_soda": {"en": ["citrus", "citrus soda"], "ar": ["حمضيات"], "arabizi": ["7amdiyat", "citrus"], "roman": ["citrus"]},
    "soda_water": {"en": ["soda", "soda water", "plain soda"], "ar": ["صودا", "ماء صودا"], "arabizi": ["soda", "9oda"], "roman": ["soda", "soda pani"]},
    "energy": {"en": ["energy drink", "energy"], "ar": ["مشروب طاقة", "طاقة"], "arabizi": ["6aqa", "energy"], "roman": ["energy drink", "energy"]},
    "sugar_free": {"en": ["sugar free", "sf"], "ar": ["بدون سكر"], "arabizi": ["bdoon sukkar", "sugar free"], "roman": ["sugar free", "bina cheeni"]},
    "water": {"en": ["water", "mineral water", "drinking water"], "ar": ["ماي", "مياه", "ماء"], "arabizi": ["mai", "mayy", "maya"], "roman": ["pani", "paani", "water"]},
    "sparkling_water": {"en": ["sparkling water", "gas water"], "ar": ["ماء غازي", "مياه فوارة"], "arabizi": ["mai ghazi", "may fawar"], "roman": ["sparkling pani", "gas wala pani"]},
    "juice_orange": {"en": ["orange juice", "oj"], "ar": ["عصير برتقال"], "arabizi": ["3aseer burtu2al", "3aseer bortgal"], "roman": ["orange juice", "santra juice"]},
    "juice_apple": {"en": ["apple juice"], "ar": ["عصير تفاح"], "arabizi": ["3aseer tuffa7", "3aseer tofa7"], "roman": ["apple juice", "seb juice"]},
    "juice_mango": {"en": ["mango juice"], "ar": ["عصير مانجو", "عصير منجا"], "arabizi": ["3aseer manga", "3aseer mango"], "roman": ["mango juice", "aam juice"]},
    "juice_mixed": {"en": ["mix fruit juice", "cocktail juice"], "ar": ["عصير كوكتيل", "كوكتيل فواكه"], "arabizi": ["cocktail", "3aseer cocktail"], "roman": ["mix fruit juice", "cocktail juice"]},
    "juice_guava": {"en": ["guava juice"], "ar": ["عصير جوافة"], "arabizi": ["3aseer jawafa", "jawafa"], "roman": ["guava juice", "amrood juice"]},
    "milk": {"en": ["milk", "fresh milk"], "ar": ["حليب", "حليب طازج"], "arabizi": ["7aleeb", "haleeb", "7alib"], "roman": ["doodh", "milk", "dudh"]},
    "full_fat": {"en": ["full fat", "full cream", "full"], "ar": ["كامل الدسم", "كامل"], "arabizi": ["kamil", "full"], "roman": ["full cream", "full"]},
    "low_fat": {"en": ["low fat", "light", "low"], "ar": ["قليل الدسم", "لايت"], "arabizi": ["lait", "qaleel"], "roman": ["low fat", "kam fat"]},
    "skim": {"en": ["skim", "skimmed", "fat free"], "ar": ["خالي الدسم"], "arabizi": ["5ali", "skim"], "roman": ["skim", "bina fat"]},
    "laban": {"en": ["laban", "buttermilk"], "ar": ["لبن", "لبن شرب"], "arabizi": ["laban", "leben"], "roman": ["laban", "chaas", "lassi laban"]},
    "uht": {"en": ["long life milk", "uht milk"], "ar": ["حليب طويل الأجل", "حليب معلب"], "arabizi": ["7aleeb tawil", "7aleeb 3elba"], "roman": ["long life doodh", "dabba doodh"]},
    "yoghurt": {"en": ["yoghurt", "yogurt", "curd"], "ar": ["زبادي", "روب"], "arabizi": ["zabadi", "rob"], "roman": ["dahi", "curd"]},
    "labneh": {"en": ["labneh", "labna"], "ar": ["لبنة"], "arabizi": ["labna", "lebne"], "roman": ["labneh", "labna"]},
    "cheese_slices": {"en": ["cheese slices", "slice cheese"], "ar": ["جبن شرائح", "جبنة سلايس"], "arabizi": ["jibin slice", "jebna sharayi7"], "roman": ["cheese slice", "slice paneer"]},
    "cream_cheese": {"en": ["cream cheese", "jar cheese"], "ar": ["جبنة كريمية", "جبنة برطمان"], "arabizi": ["jebna kreemiya", "jibna bar6aman"], "roman": ["cream cheese", "jar cheese"]},
    "eggs": {"en": ["eggs", "egg tray"], "ar": ["بيض", "طبق بيض"], "arabizi": ["bai6", "bayd", "6aba2 bai6"], "roman": ["ande", "anda", "egg"]},
    "white": {"en": ["white"], "ar": ["أبيض"], "arabizi": ["abya9", "abyad"], "roman": ["safed", "white"]},
    "brown": {"en": ["brown"], "ar": ["بني", "أسمر"], "arabizi": ["bunni", "asmar"], "roman": ["brown", "bhura"]},
    "arabic_bread": {"en": ["arabic bread", "khubz", "pita"], "ar": ["خبز عربي", "خبز"], "arabizi": ["5ubz", "khubz", "5obz 3arabi"], "roman": ["khubus", "arabic roti", "kuboos"]},
    "loaf": {"en": ["bread", "sandwich bread", "toast bread"], "ar": ["خبز توست", "توست"], "arabizi": ["toast", "5ubz toast"], "roman": ["double roti", "bread", "pav"]},
    "chips": {"en": ["chips", "crisps", "chipps"], "ar": ["شيبس", "بطاطس"], "arabizi": ["sheebs", "chips", "ba6a6is"], "roman": ["chips", "wafers", "wefar"]},
    "salted": {"en": ["salted", "plain", "salt"], "ar": ["مملح", "ملح"], "arabizi": ["mmala7", "mel7"], "roman": ["namkeen", "plain", "salted"]},
    "chilli": {"en": ["chilli", "chili", "spicy", "hot"], "ar": ["حار", "شطة"], "arabizi": ["7ar", "7aar"], "roman": ["masala", "teekha", "chilli"]},
    "cheese": {"en": ["cheese"], "ar": ["جبنة"], "arabizi": ["jebna", "jibin"], "roman": ["cheese"]},
    "ketchup_flav": {"en": ["ketchup", "tomato"], "ar": ["كاتشب", "طماطم"], "arabizi": ["ketchup", "6ama6em"], "roman": ["tomato", "ketchup"]},
    "vinegar": {"en": ["salt and vinegar", "vinegar"], "ar": ["ملح وخل", "خل"], "arabizi": ["5al", "mel7 w 5al"], "roman": ["vinegar", "sirka"]},
    "digestive": {"en": ["digestive", "digestive biscuit"], "ar": ["بسكويت دايجستف"], "arabizi": ["baskoot digestive", "daijestif"], "roman": ["digestive biscuit", "digestive"]},
    "choc_cream": {"en": ["chocolate biscuit", "choco cream biscuit"], "ar": ["بسكويت شوكولاتة"], "arabizi": ["baskoot chocolate", "shokolata baskoot"], "roman": ["chocolate biscuit", "choco biscuit"]},
    "vanilla_cream": {"en": ["vanilla biscuit", "vanilla cream"], "ar": ["بسكويت فانيلا"], "arabizi": ["baskoot vanilla", "vanilla"], "roman": ["vanilla biscuit"]},
    "wafer": {"en": ["wafer", "choco wafer", "wafer bar"], "ar": ["ويفر", "شوكولاتة ويفر"], "arabizi": ["wayfer", "wafer"], "roman": ["wafer", "chocolate wafer"]},
    "popcorn": {"en": ["popcorn", "pop corn"], "ar": ["فشار", "بوب كورن"], "arabizi": ["fashar", "popcorn"], "roman": ["popcorn", "makai pop"]},
    "basmati": {"en": ["basmati", "basmati rice", "rice"], "ar": ["أرز بسمتي", "عيش بسمتي", "رز"], "arabizi": ["ruz basmati", "3aish", "ruz"], "roman": ["chawal", "basmati chawal", "basmati"]},
    "sella": {"en": ["sella", "golden sella", "sella rice"], "ar": ["أرز سيلا", "عيش سيلا"], "arabizi": ["ruz sella", "3aish sella"], "roman": ["sella chawal", "sella"]},
    "calrose": {"en": ["calrose", "egyptian rice", "short rice"], "ar": ["أرز مصري", "رز قصير"], "arabizi": ["ruz masri", "3aish masri"], "roman": ["calrose", "chota chawal"]},
    "sugar": {"en": ["sugar", "white sugar"], "ar": ["سكر"], "arabizi": ["sukkar", "sokar"], "roman": ["cheeni", "chini", "shakkar"]},
    "atta": {"en": ["atta", "wheat flour", "chakki atta"], "ar": ["أتا", "طحين أسمر"], "arabizi": ["atta", "6a7een asmar"], "roman": ["atta", "gehun atta", "aata"]},
    "maida": {"en": ["maida", "flour", "all purpose flour"], "ar": ["طحين أبيض", "دقيق"], "arabizi": ["6a7een", "6a7een abya9"], "roman": ["maida", "maida atta"]},
    "salt": {"en": ["salt", "table salt"], "ar": ["ملح"], "arabizi": ["mel7", "mil7"], "roman": ["namak", "salt"]},
    "toor": {"en": ["toor dal", "tuvar dal", "arhar dal"], "ar": ["دال تور"], "arabizi": ["daal toor"], "roman": ["toor dal", "arhar dal", "tuvar"]},
    "moong": {"en": ["moong dal", "mung dal"], "ar": ["دال مونج"], "arabizi": ["daal moong"], "roman": ["moong dal", "mung"]},
    "masoor": {"en": ["masoor dal", "red lentils"], "ar": ["عدس أحمر", "عدس"], "arabizi": ["3adas", "3adas a7mar"], "roman": ["masoor dal", "lal dal"]},
    "chana_dal": {"en": ["chana dal", "bengal gram"], "ar": ["دال شانا"], "arabizi": ["daal chana"], "roman": ["chana dal", "chane ki dal"]},
    "kabuli": {"en": ["chickpeas", "kabuli chana"], "ar": ["حمص حب", "حمص ناشف"], "arabizi": ["7ummus 7ab", "7omos"], "roman": ["kabuli chana", "chole", "safed chana"]},
    "sunflower_oil": {"en": ["sunflower oil", "oil", "cooking oil"], "ar": ["زيت دوار الشمس", "زيت"], "arabizi": ["zait", "zayt shams"], "roman": ["tel", "sunflower tel", "oil"]},
    "corn_oil": {"en": ["corn oil"], "ar": ["زيت ذرة"], "arabizi": ["zait thura", "zayt dura"], "roman": ["corn oil", "makai tel"]},
    "veg_oil": {"en": ["vegetable oil", "veg oil"], "ar": ["زيت نباتي"], "arabizi": ["zait nabati"], "roman": ["veg oil", "vanaspati tel"]},
    "ghee": {"en": ["ghee", "samn"], "ar": ["سمن", "سمن بقر"], "arabizi": ["samn", "samin"], "roman": ["ghee", "desi ghee", "ghi"]},
    "tea_bags": {"en": ["tea bags", "tea bag"], "ar": ["شاي أكياس", "شاي فتلة"], "arabizi": ["chai akyas", "shai kees"], "roman": ["tea bag", "chai bag"]},
    "loose_tea": {"en": ["loose tea", "tea powder", "tea"], "ar": ["شاي ناعم", "شاي"], "arabizi": ["chai na3im", "shai"], "roman": ["chai patti", "chai powder", "patti"]},
    "karak": {"en": ["karak", "karak premix"], "ar": ["كرك", "شاي كرك"], "arabizi": ["karak", "chai karak"], "roman": ["karak", "karak chai"]},
    "instant_coffee": {"en": ["coffee", "instant coffee"], "ar": ["قهوة سريعة", "قهوة"], "arabizi": ["gahwa", "9ahwa"], "roman": ["coffee", "kaafi"]},
    "coffee_3in1": {"en": ["3 in 1", "three in one", "coffee mix"], "ar": ["ثلاثة في واحد", "قهوة ٣ في ١"], "arabizi": ["3 in 1", "thalatha fi wa7ed"], "roman": ["3 in 1", "teen in ek coffee"]},
    "tuna": {"en": ["tuna", "tuna fish"], "ar": ["تونة", "تونا"], "arabizi": ["toona", "tuna"], "roman": ["tuna", "tuna machli"]},
    "in_oil": {"en": ["in oil", "oil"], "ar": ["بالزيت"], "arabizi": ["bil zait"], "roman": ["tel wala", "oil"]},
    "in_water": {"en": ["in water", "water"], "ar": ["بالماء"], "arabizi": ["bil mai"], "roman": ["pani wala"]},
    "tomato_paste": {"en": ["tomato paste", "paste"], "ar": ["معجون طماطم", "صلصة"], "arabizi": ["ma3joon 6ama6em", "9al9a"], "roman": ["tomato paste", "tamatar paste"]},
    "foul": {"en": ["foul", "fava beans", "ful"], "ar": ["فول", "فول مدمس"], "arabizi": ["fool", "fool mudammas"], "roman": ["foul", "fool"]},
    "chickpeas_tin": {"en": ["chickpeas tin", "hummus tin"], "ar": ["حمص علب", "حمص معلب"], "arabizi": ["7ummus 3elba"], "roman": ["chole tin", "chana dabba"]},
    "sweetcorn": {"en": ["sweet corn", "corn"], "ar": ["ذرة حلوة", "ذرة"], "arabizi": ["thura", "dura 7elwa"], "roman": ["corn", "makai"]},
    "ketchup": {"en": ["ketchup", "tomato sauce"], "ar": ["كاتشب", "صوص طماطم"], "arabizi": ["ketchup", "ketshab"], "roman": ["ketchup", "tomato sauce"]},
    "mayo": {"en": ["mayo", "mayonnaise"], "ar": ["مايونيز", "مايونيز"], "arabizi": ["mayonez", "mayo"], "roman": ["mayo", "mayonez"]},
    "dishwash": {"en": ["dishwash", "dish liquid", "dish soap"], "ar": ["سائل جلي", "صابون صحون"], "arabizi": ["sa2il jali", "9aboon 9o7oon"], "roman": ["bartan sabun", "dish wash"]},
    "lemon": {"en": ["lemon"], "ar": ["ليمون"], "arabizi": ["laymoon"], "roman": ["nimbu", "lemon"]},
    "original": {"en": ["original", "regular"], "ar": ["عادي", "أصلي"], "arabizi": ["3adi", "a9li"], "roman": ["normal", "regular"]},
    "bleach": {"en": ["bleach", "chlorine"], "ar": ["كلور", "مبيض"], "arabizi": ["klor", "mubayed"], "roman": ["bleach", "phenyl bleach"]},
    "washing_powder": {"en": ["washing powder", "detergent", "powder"], "ar": ["مسحوق غسيل", "صابون غسيل"], "arabizi": ["mas7oo2 ghaseel", "powder"], "roman": ["kapde ka powder", "washing powder"]},
    "washing_liquid": {"en": ["washing liquid", "liquid detergent"], "ar": ["سائل غسيل"], "arabizi": ["sa2il ghaseel"], "roman": ["liquid detergent", "kapde ka liquid"]},
    "floor_cleaner": {"en": ["floor cleaner", "pine cleaner"], "ar": ["منظف أرضيات", "ديتول أرضيات"], "arabizi": ["munathif ar9iyat"], "roman": ["phenyl", "floor cleaner", "pocha liquid"]},
    "tissue": {"en": ["tissue", "tissue box", "facial tissue"], "ar": ["مناديل", "محارم"], "arabizi": ["manadeel", "ma7arim"], "roman": ["tissue", "tissue dabba"]},
    "toilet_roll": {"en": ["toilet roll", "toilet paper"], "ar": ["ورق حمام", "محارم حمام"], "arabizi": ["wara2 7ammam", "toilet"], "roman": ["toilet roll", "toilet paper"]},
    "kitchen_roll": {"en": ["kitchen roll", "kitchen towel"], "ar": ["مناديل مطبخ", "رول مطبخ"], "arabizi": ["manadeel matba5", "kitchen roll"], "roman": ["kitchen roll", "kitchen tissue"]},
    "garbage_bags": {"en": ["garbage bags", "trash bags", "black bags"], "ar": ["أكياس زبالة", "أكياس قمامة"], "arabizi": ["akyas zbala", "akyas zibala"], "roman": ["garbage bag", "kachra bag", "kachre ki thaili"]},
}  # fmt: skip

# Which concept words describe each family. A street term is one or two concepts joined, in one style.
FAMILY_CONCEPTS: dict[str, list[list[str]]] = {
    "nawa_cola": [["cola"]], "nawa_diet": [["cola", "diet"], ["diet"]], "nawa_zero": [["cola", "zero"], ["zero"]],
    "sparkle_up": [["lemon_soda"]], "sparkle_up_diet": [["lemon_soda", "diet"]],
    "mirage_orange": [["orange_soda"]], "mirage_citrus": [["citrus_soda"]], "fizz_soda": [["soda_water"]],
    "volt": [["energy"]], "volt_sf": [["energy", "sugar_free"]],
    "al_wadi": [["water"]], "crystal_oasis": [["water"]], "al_wadi_sparkling": [["sparkling_water"]],
    "sunfield_orange": [["juice_orange"]], "sunfield_apple": [["juice_apple"]], "sunfield_mango": [["juice_mango"]],
    "sunfield_mixed_fruit": [["juice_mixed"]], "sunfield_guava": [["juice_guava"]],
    "barari_milk_full": [["milk", "full_fat"], ["milk"]], "barari_milk_low": [["milk", "low_fat"]], "barari_milk_skim": [["milk", "skim"]],
    "barari_laban_full": [["laban", "full_fat"], ["laban"]], "barari_laban_low": [["laban", "low_fat"]], "barari_uht": [["uht"]],
    "barari_yoghurt_full": [["yoghurt", "full_fat"], ["yoghurt"]], "barari_yoghurt_low": [["yoghurt", "low_fat"]],
    "barari_labneh": [["labneh"]], "barari_cheese_slices": [["cheese_slices"]], "barari_cream_cheese": [["cream_cheese"]],
    "farm_eggs_white": [["eggs", "white"], ["eggs"]], "farm_eggs_brown": [["eggs", "brown"]],
    "tannour_arabic_bread": [["arabic_bread"]], "tannour_white_loaf": [["loaf", "white"], ["loaf"]], "tannour_brown_loaf": [["loaf", "brown"]],
    "crunchos_salted": [["chips", "salted"]], "crunchos_chilli": [["chips", "chilli"]], "crunchos_cheese": [["chips", "cheese"]],
    "crunchos_ketchup": [["chips", "ketchup_flav"]], "crunchos_salt_vinegar": [["chips", "vinegar"]],
    "biskito_digestive": [["digestive"]], "biskito_cream_choc": [["choc_cream"]], "biskito_cream_vanilla": [["vanilla_cream"]],
    "choco_dune": [["wafer"]], "salty_bites_popcorn": [["popcorn"]],
    "royale_basmati": [["basmati"]], "royale_sella": [["sella"]], "royale_calrose": [["calrose"]],
    "pure_sweet_sugar": [["sugar"]], "chakki_atta": [["atta"]], "chakki_maida": [["maida"]], "sea_salt": [["salt"]],
    "royale_toor": [["toor"]], "royale_moong": [["moong"]], "royale_masoor": [["masoor"]], "royale_chana": [["chana_dal"]], "royale_kabuli": [["kabuli"]],
    "sunola_sunflower": [["sunflower_oil"]], "sunola_corn": [["corn_oil"]], "sunola_vegetable": [["veg_oil"]], "ghee_gold": [["ghee"]],
    "chaipur_tea_bags": [["tea_bags"]], "chaipur_loose": [["loose_tea"]], "karak_premix": [["karak"]],
    "dune_coffee": [["instant_coffee"]], "dune_3in1": [["coffee_3in1"]],
    "bahr_tuna_oil": [["tuna", "in_oil"], ["tuna"]], "bahr_tuna_water": [["tuna", "in_water"]],
    "rosso_tomato_paste": [["tomato_paste"]], "rosso_foul": [["foul"]], "rosso_chickpeas": [["chickpeas_tin"]],
    "rosso_sweetcorn": [["sweetcorn"]], "rosso_ketchup": [["ketchup"]], "rosso_mayo": [["mayo"]],
    "shimmer_dish_lemon": [["dishwash", "lemon"], ["dishwash"]], "shimmer_dish_original": [["dishwash", "original"]],
    "klenzo_bleach": [["bleach"]], "brite_powder": [["washing_powder"]], "brite_liquid": [["washing_liquid"]],
    "fresh_floor_pine": [["floor_cleaner"]], "softa_facial": [["tissue"]], "softa_toilet": [["toilet_roll"]],
    "softa_kitchen": [["kitchen_roll"]], "garbage_bags": [["garbage_bags"]],
}  # fmt: skip

# Arabic-script spellings of brands (Latin brand names are used as-is in the Latin styles).
BRAND_AR = {"Nawa": "نوا", "Sparkle Up": "سباركل", "Mirage": "ميراج", "Fizz": "فيز", "Volt": "فولت", "Al Wadi": "الوادي",
            "Crystal Oasis": "كريستال", "Sunfield": "صن فيلد", "Barari": "براري", "Farm Fresh": "فارم فريش", "Tannour": "تنور",
            "Crunchos": "كرانشوز", "Biskito": "بسكيتو", "Choco Dune": "شوكو ديون", "Salty Bites": "سولتي", "Royale": "رويال",
            "Pure Sweet": "بيور سويت", "Chakki": "تشاكي", "Bahr": "بحر", "Sunola": "صنولا", "Golden Cow": "البقرة الذهبية",
            "Chaipur": "تشايبور", "Dune": "ديون", "Rosso": "روسو", "Shimmer": "شيمر", "Klenzo": "كلينزو", "Brite": "برايت",
            "Fresh Floor": "فريش", "Softa": "سوفتا", "Strong": "سترونج"}  # fmt: skip
# Arabizi spellings of brands (how they sound, written by Arabic speakers).
BRAND_ARABIZI = {"Nawa": "nawa", "Sparkle Up": "sparkel", "Mirage": "miraj", "Al Wadi": "elwadi", "Barari": "barari",
                 "Sunola": "sanola", "Royale": "royal", "Crunchos": "kranchos", "Tannour": "tannoor", "Softa": "softa",
                 "Shimmer": "shimer", "Klenzo": "klenzo", "Rosso": "roso", "Bahr": "ba7r", "Chaipur": "shaipur"}  # fmt: skip


def _hash01(s: str) -> float:
    return int(hashlib.sha256(s.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def is_heldout(term: str, family: str) -> bool:
    return _hash01(f"heldout|{family}|{term.lower()}") < HELDOUT_SHARE


def _join(style: str, a: str, b: str) -> str:
    # Arabic puts the qualifier after the noun; Latin styles mostly do too in shop speech ("milk low fat").
    return f"{a} {b}"


def street_terms(f: Family) -> dict[str, list[str]]:
    """Every street term for a family, by style (brand-based and concept-based). Deduplicated, lower-case Latin."""
    out: dict[str, list[str]] = {s: [] for s in STYLES}
    for combo in FAMILY_CONCEPTS[f.key]:
        for style in STYLES:
            heads = C[combo[0]][style]
            quals = [C[c][style] for c in combo[1:]]
            for h in heads:
                if not quals:
                    out[style].append(h)
                else:
                    for q in quals[0]:
                        out[style].append(_join(style, h, q))
    # brand-led terms: "nawa diet", "barari laban", "نوا كولا"
    lead = FAMILY_CONCEPTS[f.key][0]
    for style in STYLES:
        concept = C[lead[-1]][style][0] if len(lead) > 1 else C[lead[0]][style][0]
        if style == "ar":
            brand = BRAND_AR.get(f.brand, f.brand)
        elif style == "arabizi":
            brand = BRAND_ARABIZI.get(f.brand, f.brand.lower())
        else:
            brand = f.brand.lower()
        out[style].append(f"{brand} {concept}")
    return {s: sorted({t.lower() if s != "ar" else t for t in ts}) for s, ts in out.items()}


def split_terms() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(seen, heldout): family -> list of street terms (all styles). Seen terms feed the parser's alias table."""
    seen: dict[str, list[str]] = {}
    held: dict[str, list[str]] = {}
    for f in FAMILIES:
        terms = sorted({t for ts in street_terms(f).values() for t in ts})
        # the catalogue's own names and generic group words ("rice", "doodh") are never held out
        official = {f.name_en.lower(), f.name_ar, f.brand.lower()} | set(GENERIC)
        seen[f.key] = [t for t in terms if t in official or not is_heldout(t, f.key)]
        held[f.key] = [t for t in terms if t not in official and is_heldout(t, f.key)]
    return seen, held


# ---- sizes ----------------------------------------------------------------------------------------
# Words a shopkeeper uses for a size, by size class. Numeric forms are added from the label.
SIZE_WORDS: dict[str, dict[str, list[str]]] = {
    "can": {"en": ["can", "tin"], "ar": ["علبة", "علب"], "arabizi": ["3elba", "can"], "roman": ["can", "tin", "dabba"]},
    "can_small": {"en": ["small can", "mini can"], "ar": ["علبة صغيرة"], "arabizi": ["3elba 9ghayra"], "roman": ["chota can"]},
    "can_big": {"en": ["big can", "large can"], "ar": ["علبة كبيرة"], "arabizi": ["3elba kbeera"], "roman": ["bada can"]},
    "bottle_small": {"en": ["small bottle"], "ar": ["قنينة صغيرة", "بطل صغير"], "arabizi": ["bu6el 9gheer", "9gheer"], "roman": ["chota bottle", "chhoti bottle"]},
    "bottle_tiny": {"en": ["mini bottle", "small small"], "ar": ["صغير جدا"], "arabizi": ["9gheer wayed"], "roman": ["sabse chota"]},
    "bottle_mid": {"en": ["1.5", "litre and half", "medium"], "ar": ["لتر ونص"], "arabizi": ["litre w nu9", "1.5"], "roman": ["dedh litre", "1.5"]},
    "bottle_big": {"en": ["big bottle", "family size", "large"], "ar": ["كبير", "حجم عائلي"], "arabizi": ["kbeer", "kabeer"], "roman": ["bada", "badi bottle"]},
    "gallon": {"en": ["gallon", "big gallon", "4 gallon"], "ar": ["جالون", "قلن"], "arabizi": ["galon", "gallon"], "roman": ["gallon", "bada gallon"]},
    "cup": {"en": ["cup", "small cup"], "ar": ["كوب", "كاسة"], "arabizi": ["koob", "cup"], "roman": ["cup", "glass wala"]},
    "tetra_small": {"en": ["small pack", "small"], "ar": ["صغير"], "arabizi": ["9gheer"], "roman": ["chota"]},
    "tetra_big": {"en": ["1 litre", "big pack", "big"], "ar": ["لتر", "كبير"], "arabizi": ["litre", "kbeer"], "roman": ["litre wala", "bada"]},
    "litre": {"en": ["1 litre", "1L", "litre"], "ar": ["لتر"], "arabizi": ["litre"], "roman": ["ek litre", "litre"]},
    "litre_big": {"en": ["2 litre", "2L", "big"], "ar": ["لترين"], "arabizi": ["litrain", "2 litre"], "roman": ["do litre", "bada"]},
    "tray": {"en": ["tray", "30s"], "ar": ["طبق", "كرتون بيض"], "arabizi": ["6aba2", "tray"], "roman": ["tray", "peti"]},
    "tray_small": {"en": ["half tray", "15s"], "ar": ["نص طبق"], "arabizi": ["nu9 6aba2"], "roman": ["aadha tray"]},
}  # fmt: skip


def size_terms(sku_size_label: str, size_class: str, style: str) -> list[str]:
    """Ways to say this size: numbers from the label (style-neutral) plus class words in the style."""
    out: list[str] = []
    lab = sku_size_label.lower()
    m = re.search(r"([\d.]+)\s*(ml|l|g|kg)\b", lab)
    if m:
        num, unit = m.groups()
        out += [num, f"{num}{unit}", f"{num} {unit}"]
        if unit == "l":
            out += [f"{num} ltr", f"{num} litre"]
        if unit == "kg":
            out += [f"{num} kilo", f"{num}kg"]
    m2 = re.search(r"(\d+)\s*(bags|rolls|sachets|slices|sheets)", sku_size_label.lower())
    if m2:
        out += [f"{m2.group(1)} {m2.group(2)}", f"{m2.group(1)}s"]
    for kw in ("box of ", "tray of ", "roll of "):
        if kw in lab:
            n = re.match(r"\d+", lab.split(kw)[1])
            if n:
                out += [n.group(0), f"{n.group(0)}s"]
    if lab.startswith("small"):
        out += {"en": ["small"], "ar": ["صغير"], "arabizi": ["9gheer"], "roman": ["chota"]}[style]
    if lab.startswith("large"):
        out += {"en": ["big", "large"], "ar": ["كبير"], "arabizi": ["kbeer"], "roman": ["bada"]}[style]
    out += SIZE_WORDS.get(size_class, {}).get(style, [])
    if not out:
        out.append(lab)
    return list(dict.fromkeys(out))


# ---- units and quantities ---------------------------------------------------------------------------
UNIT_WORDS: dict[str, dict[str, list[str]]] = {
    "carton": {"en": ["ctn", "ctns", "carton", "cartons", "case", "cs"], "ar": ["كرتون", "كراتين", "كرتونة"], "arabizi": ["kartoon", "karton", "kartona", "krtn"], "roman": ["peti", "petti", "carton", "ctn"]},
    "pack": {"en": ["pkt", "pack", "packet", "shrink", "pk"], "ar": ["باكيت", "ربطة", "شد"], "arabizi": ["baket", "packet", "shad"], "roman": ["packet", "pkt", "paketa"]},
    "piece": {"en": ["pcs", "pc", "piece", "nos", "units"], "ar": ["حبة", "حبات", "قطعة"], "arabizi": ["7aba", "habba", "7abba"], "roman": ["piece", "pcs", "nag", "adad"]},
    "bag": {"en": ["bag", "bags", "sack"], "ar": ["كيس", "أكياس", "شوال"], "arabizi": ["kees", "akyas", "shwal"], "roman": ["bori", "bag", "thaila"]},
}  # fmt: skip
NUMBER_WORDS: dict[str, dict[int, list[str]]] = {
    "en": {1: ["one", "a"], 2: ["two"], 3: ["three"], 4: ["four"], 5: ["five"], 6: ["six", "half dozen"], 10: ["ten"], 12: ["twelve", "dozen", "a dozen"]},
    "ar": {1: ["واحد", "وحدة"], 2: ["اثنين", "ثنتين"], 3: ["ثلاث", "ثلاثة"], 4: ["أربع", "اربعة"], 5: ["خمس", "خمسة"], 6: ["ست", "ستة"], 10: ["عشر", "عشرة"]},
    "arabizi": {1: ["wa7ad", "wa7da"], 2: ["ithnain", "2nain", "thintain"], 3: ["thalath", "talata"], 4: ["arba3", "arba3a"], 5: ["5ams", "khamsa"], 6: ["sit", "sitta"], 10: ["3ashr", "3ashara"]},
    "roman": {1: ["ek"], 2: ["do"], 3: ["teen"], 4: ["char", "chaar"], 5: ["panch", "paanch"], 6: ["chhe", "che"], 10: ["das"], 12: ["barah", "darjan"]},
}  # fmt: skip
ARABIC_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")

GREETINGS = {
    "en": ["Hi", "Hello", "Good morning", "Salam", "Hi boss", "Dear", ""],
    "ar": ["السلام عليكم", "مرحبا", "صباح الخير", "هلا", ""],
    "arabizi": ["salam", "assalamu 3alaikum", "mar7aba", "9aba7 el 5air", "hala", ""],
    "roman": ["salam bhai", "assalam alaikum", "bhai", "namaste ji", "salam", ""],
}  # fmt: skip
OPENERS = {
    "en": ["Order:", "pls send", "Please send tomorrow", "need below", "order for tomorrow", ""],
    "ar": ["الطلب:", "ابي", "نبي بكرة", "ارسل لو سمحت", ""],
    "arabizi": ["abi", "nabi bukra", "order:", "law sama7t ersel", ""],
    "roman": ["ye bhejo", "kal subah bhejna", "order likho", "maal bhejo", ""],
}  # fmt: skip
CLOSINGS = {
    "en": ["thanks", "thank you", "tks", "pls confirm", "urgent", "🙏", ""],
    "ar": ["شكرا", "الله يعطيك العافية", "ضروري", ""],
    "arabizi": ["shukran", "yesalmo", "tayeb", "🙏", ""],
    "roman": ["shukriya", "jaldi bhejna", "thank you bhai", "🙏", ""],
}  # fmt: skip


# Generic words shopkeepers use for a whole group of families ("rice", "oil", "milk"). Only usable when the
# customer's own basket narrows the group to one family; otherwise the line is genuinely ambiguous.
GENERIC: dict[str, list[str]] = {
    "rice": ["royale_basmati", "royale_sella", "royale_calrose"], "ruz": ["royale_basmati", "royale_sella", "royale_calrose"],
    "chawal": ["royale_basmati", "royale_sella", "royale_calrose"], "3aish": ["royale_basmati", "royale_sella", "royale_calrose"],
    "رز": ["royale_basmati", "royale_sella", "royale_calrose"],
    "oil": ["sunola_sunflower", "sunola_corn", "sunola_vegetable"], "tel": ["sunola_sunflower", "sunola_corn", "sunola_vegetable"],
    "zait": ["sunola_sunflower", "sunola_corn", "sunola_vegetable"], "زيت": ["sunola_sunflower", "sunola_corn", "sunola_vegetable"],
    "milk": ["barari_milk_full", "barari_milk_low", "barari_milk_skim", "barari_uht"], "doodh": ["barari_milk_full", "barari_milk_low", "barari_milk_skim", "barari_uht"],
    "7aleeb": ["barari_milk_full", "barari_milk_low", "barari_milk_skim", "barari_uht"], "حليب": ["barari_milk_full", "barari_milk_low", "barari_milk_skim", "barari_uht"],
    "tea": ["chaipur_tea_bags", "chaipur_loose", "karak_premix"], "chai": ["chaipur_tea_bags", "chaipur_loose", "karak_premix"],
    "شاي": ["chaipur_tea_bags", "chaipur_loose", "karak_premix"],
    "chips": ["crunchos_salted", "crunchos_chilli", "crunchos_cheese", "crunchos_ketchup", "crunchos_salt_vinegar"],
    "wafers": ["crunchos_salted", "crunchos_chilli", "crunchos_cheese", "crunchos_ketchup", "crunchos_salt_vinegar"],
    "bread": ["tannour_white_loaf", "tannour_brown_loaf"], "laban": ["barari_laban_full", "barari_laban_low"],
    "yoghurt": ["barari_yoghurt_full", "barari_yoghurt_low"], "dahi": ["barari_yoghurt_full", "barari_yoghurt_low"],
    "zabadi": ["barari_yoghurt_full", "barari_yoghurt_low"], "eggs": ["farm_eggs_white", "farm_eggs_brown"],
    "ande": ["farm_eggs_white", "farm_eggs_brown"], "dishwash": ["shimmer_dish_lemon", "shimmer_dish_original"],
}  # fmt: skip
