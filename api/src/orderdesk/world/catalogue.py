"""Saffron Lane's catalogue: product families expanded into SKUs with pack sizes, prices and barcodes.

All brands are invented. Sizes, pack counts and wholesale prices are written to be plausible for a Dubai
FMCG distributor in 2026. A family is "what the shopkeeper names" (Nawa Cola Diet); a SKU is a family
in one size (Nawa Cola Diet 330 ml can). Every SKU has a base unit (the thing on the shelf: a can, a
bag, a tray) and optionally a pack and a carton made of base units.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

# size key -> (label, arabic label, size class used by size words, pack size or 0, carton size, price fils/piece)
Size = tuple[str, str, str, int, int, int]


@dataclass(frozen=True)
class Family:
    key: str
    brand: str
    name_en: str
    name_ar: str
    category: str
    sizes: dict[str, Size]
    base_unit: str = "piece"  # piece | bag | tray | bottle | box | roll-pack


@dataclass
class Sku:
    id: str
    family: str
    size: str
    name_en: str
    name_ar: str
    brand: str
    category: str
    size_label: str
    size_class: str
    base_unit: str
    pack_size: int  # base units per pack (0 = no pack level)
    carton_size: int  # base units per carton
    price_fils: int  # list price per base unit, before customer discounts
    barcode: str
    aliases: list[str] = field(default_factory=list)  # official names only; street names live in lexicon.py

    def to_dict(self) -> dict:
        return asdict(self)


def _can(price: int) -> dict[str, Size]:
    return {
        "150c": ("150 ml can", "علبة ١٥٠ مل", "can_small", 6, 30, price - 45),
        "250c": ("250 ml can", "علبة ٢٥٠ مل", "can", 6, 24, price - 15),
        "330c": ("330 ml can", "علبة ٣٣٠ مل", "can", 6, 24, price),
        "500p": ("500 ml bottle", "قنينة ٥٠٠ مل", "bottle_small", 6, 24, price + 20),
        "1250p": ("1.25 L bottle", "قنينة ١٫٢٥ لتر", "bottle_mid", 0, 12, price + 140),
        "2250p": ("2.25 L bottle", "قنينة ٢٫٢٥ لتر", "bottle_big", 0, 6, price + 260),
    }


def _water(price_small: int) -> dict[str, Size]:
    return {
        "200cup": ("200 ml cup", "كوب ٢٠٠ مل", "cup", 0, 48, price_small - 20),
        "330p": ("330 ml bottle", "قنينة ٣٣٠ مل", "bottle_tiny", 6, 24, price_small),
        "500p": ("500 ml bottle", "قنينة ٥٠٠ مل", "bottle_small", 6, 24, price_small + 10),
        "1500p": ("1.5 L bottle", "قنينة ١٫٥ لتر", "bottle_mid", 6, 12, price_small + 55),
        "5000p": ("5 L bottle", "قنينة ٥ لتر", "bottle_big", 0, 4, price_small + 330),
        "18900g": ("4 gallon (18.9 L)", "جالون ١٨٫٩ لتر", "gallon", 0, 1, 1200),
    }


def _juice() -> dict[str, Size]:
    return {
        "200t": ("200 ml pack", "علبة ٢٠٠ مل", "tetra_small", 6, 27, 95),
        "1000t": ("1 L pack", "علبة ١ لتر", "tetra_big", 0, 12, 520),
    }


def _milk(fresh: bool) -> dict[str, Size]:
    s = {
        "250": ("250 ml", "٢٥٠ مل", "tetra_small", 0, 24, 165),
        "1000": ("1 L", "١ لتر", "litre", 0, 12, 640),
        "2000": ("2 L", "٢ لتر", "litre_big", 0, 6, 1190),
    }
    if not fresh:
        s.pop("2000")
    return s


FAMILIES: list[Family] = []


def _add(f: Family) -> None:
    FAMILIES.append(f)


# ---- beverages ----------------------------------------------------------------------------------
for key, en, ar, price in [
    ("nawa_cola", "Nawa Cola", "نوا كولا", 115),
    ("nawa_diet", "Nawa Cola Diet", "نوا كولا دايت", 115),
    ("nawa_zero", "Nawa Cola Zero", "نوا كولا زيرو", 120),
    ("sparkle_up", "Sparkle Up Lemon-Lime", "سباركل أب ليمون", 110),
    ("sparkle_up_diet", "Sparkle Up Diet", "سباركل أب دايت", 110),
    ("mirage_orange", "Mirage Orange", "ميراج برتقال", 110),
    ("mirage_citrus", "Mirage Citrus", "ميراج حمضيات", 110),
]:
    brand = {"sparkle_up": "Sparkle Up", "sparkle_up_diet": "Sparkle Up"}.get(key, en.split()[0])
    _add(Family(key, brand, en, ar, "soft_drinks", _can(price)))
_add(Family("fizz_soda", "Fizz", "Fizz Soda Water", "فيز صودا", "soft_drinks",
            {"330c": ("330 ml can", "علبة ٣٣٠ مل", "can", 6, 24, 95), "1250p": ("1.25 L bottle", "قنينة ١٫٢٥ لتر", "bottle_mid", 0, 12, 230)}))  # fmt: skip
for key, en, ar in [
    ("volt", "Volt Energy", "فولت طاقة"),
    ("volt_sf", "Volt Energy Sugar Free", "فولت طاقة بدون سكر"),
]:
    _add(Family(key, "Volt", en, ar, "energy",
                {"250c": ("250 ml can", "علبة ٢٥٠ مل", "can", 0, 24, 390), "500c": ("500 ml can", "علبة ٥٠٠ مل", "can_big", 0, 24, 610)}))  # fmt: skip

# ---- water --------------------------------------------------------------------------------------
_add(Family("al_wadi", "Al Wadi", "Al Wadi Water", "مياه الوادي", "water", _water(55)))
_add(
    Family("crystal_oasis", "Crystal Oasis", "Crystal Oasis Water", "مياه كريستال واحة", "water", _water(50))
)
_add(Family("al_wadi_sparkling", "Al Wadi", "Al Wadi Sparkling Water", "مياه الوادي غازية", "water",
            {"330g": ("330 ml glass", "زجاجة ٣٣٠ مل", "glass", 0, 24, 260), "750g": ("750 ml glass", "زجاجة ٧٥٠ مل", "glass_big", 0, 12, 520)}))  # fmt: skip

# ---- juice --------------------------------------------------------------------------------------
for flav, ar in [("orange", "برتقال"), ("apple", "تفاح"), ("mango", "مانجو"), ("mixed_fruit", "كوكتيل فواكه"), ("guava", "جوافة")]:  # fmt: skip
    _add(Family(f"sunfield_{flav}", "Sunfield", f"Sunfield {flav.replace('_', ' ').title()} Juice", f"عصير صن فيلد {ar}", "juice", _juice()))  # fmt: skip

# ---- dairy --------------------------------------------------------------------------------------
for key, en, ar, fresh in [
    ("barari_milk_full", "Barari Fresh Milk Full Fat", "حليب براري كامل الدسم", True),
    ("barari_milk_low", "Barari Fresh Milk Low Fat", "حليب براري قليل الدسم", True),
    ("barari_milk_skim", "Barari Fresh Milk Skimmed", "حليب براري خالي الدسم", True),
    ("barari_laban_full", "Barari Laban Full Fat", "لبن براري كامل الدسم", True),
    ("barari_laban_low", "Barari Laban Low Fat", "لبن براري قليل الدسم", True),
    ("barari_uht", "Barari Long Life Milk", "حليب براري طويل الأجل", False),
]:
    _add(Family(key, "Barari", en, ar, "dairy", _milk(fresh), base_unit="bottle" if fresh else "piece"))
for key, en, ar, sizes in [
    ("barari_yoghurt_full", "Barari Yoghurt Full Fat", "زبادي براري كامل الدسم",
     {"170": ("170 g", "١٧٠ غ", "cup", 6, 24, 140), "1000": ("1 kg", "١ كغ", "tub", 0, 6, 720)}),
    ("barari_yoghurt_low", "Barari Yoghurt Low Fat", "زبادي براري قليل الدسم",
     {"170": ("170 g", "١٧٠ غ", "cup", 6, 24, 140), "1000": ("1 kg", "١ كغ", "tub", 0, 6, 720)}),
    ("barari_labneh", "Barari Labneh", "لبنة براري",
     {"200": ("200 g", "٢٠٠ غ", "tub_small", 0, 12, 620), "400": ("400 g", "٤٠٠ غ", "tub", 0, 12, 1090)}),
    ("barari_cheese_slices", "Barari Cheese Slices", "شرائح جبن براري",
     {"200": ("10 slices 200 g", "١٠ شرائح ٢٠٠ غ", "pack", 0, 24, 780), "400": ("20 slices 400 g", "٢٠ شريحة ٤٠٠ غ", "pack_big", 0, 12, 1450)}),
    ("barari_cream_cheese", "Barari Cream Cheese Jar", "جبنة كريمية براري",
     {"240": ("240 g jar", "برطمان ٢٤٠ غ", "jar_small", 0, 24, 840), "500": ("500 g jar", "برطمان ٥٠٠ غ", "jar", 0, 12, 1490)}),
]:  # fmt: skip
    _add(Family(key, "Barari", en, ar, "dairy", sizes))
_add(Family("farm_eggs_white", "Farm Fresh", "Farm Fresh White Eggs", "بيض فارم فريش أبيض", "eggs",
            {"30": ("tray of 30", "طبق ٣٠", "tray", 0, 12, 1350), "15": ("tray of 15", "طبق ١٥", "tray_small", 0, 12, 720)}, "tray"))  # fmt: skip
_add(Family("farm_eggs_brown", "Farm Fresh", "Farm Fresh Brown Eggs", "بيض فارم فريش بني", "eggs",
            {"30": ("tray of 30", "طبق ٣٠", "tray", 0, 12, 1550)}, "tray"))  # fmt: skip

# ---- bakery -------------------------------------------------------------------------------------
for key, en, ar, sizes in [
    ("tannour_arabic_bread", "Tannour Arabic Bread", "خبز عربي تنور",
     {"small": ("small, pack of 6", "صغير ٦ حبات", "bread_small", 0, 20, 300), "large": ("large, pack of 6", "كبير ٦ حبات", "bread_big", 0, 20, 450)}),
    ("tannour_white_loaf", "Tannour White Sliced Bread", "خبز توست أبيض تنور",
     {"600": ("600 g loaf", "رغيف ٦٠٠ غ", "loaf", 0, 12, 550)}),
    ("tannour_brown_loaf", "Tannour Brown Sliced Bread", "خبز توست أسمر تنور",
     {"600": ("600 g loaf", "رغيف ٦٠٠ غ", "loaf", 0, 12, 600)}),
]:  # fmt: skip
    _add(Family(key, "Tannour", en, ar, "bakery", sizes, "pack"))

# ---- snacks -------------------------------------------------------------------------------------
for flav, ar in [("salted", "مملح"), ("chilli", "حار"), ("cheese", "جبنة"), ("ketchup", "كاتشب"), ("salt_vinegar", "ملح وخل")]:  # fmt: skip
    _add(Family(f"crunchos_{flav}", "Crunchos", f"Crunchos {flav.replace('_', ' & ').title()} Chips", f"شيبس كرانشوز {ar}", "snacks",
                {"15": ("15 g", "١٥ غ", "chips_small", 21, 168, 45), "45": ("45 g", "٤٥ غ", "chips_mid", 0, 24, 160), "160": ("160 g", "١٦٠ غ", "chips_big", 0, 12, 590)}))  # fmt: skip
for key, en, ar, sizes in [
    ("biskito_digestive", "Biskito Digestive", "بسكيتو دايجستف",
     {"40": ("40 g", "٤٠ غ", "biscuit_small", 12, 96, 70), "250": ("250 g", "٢٥٠ غ", "biscuit_big", 0, 24, 520)}),
    ("biskito_cream_choc", "Biskito Chocolate Cream", "بسكيتو كريمة شوكولاتة",
     {"40": ("40 g", "٤٠ غ", "biscuit_small", 12, 96, 70), "180": ("180 g", "١٨٠ غ", "biscuit_big", 0, 24, 410)}),
    ("biskito_cream_vanilla", "Biskito Vanilla Cream", "بسكيتو كريمة فانيلا",
     {"40": ("40 g", "٤٠ غ", "biscuit_small", 12, 96, 70), "180": ("180 g", "١٨٠ غ", "biscuit_big", 0, 24, 410)}),
    ("choco_dune", "Choco Dune Wafer Bar", "شوكو ديون ويفر",
     {"38": ("38 g bar", "لوح ٣٨ غ", "bar", 24, 288, 120)}),
    ("salty_bites_popcorn", "Salty Bites Popcorn", "فشار سولتي بايتس",
     {"23": ("23 g", "٢٣ غ", "chips_small", 24, 192, 60)}),
]:  # fmt: skip
    brand = {"choco_dune": "Choco Dune", "salty_bites_popcorn": "Salty Bites"}.get(key, en.split()[0])
    _add(Family(key, brand, en, ar, "snacks", sizes))

# ---- rice, flour, sugar, staples ------------------------------------------------------------------
for key, en, ar, sizes in [
    ("royale_basmati", "Royale Basmati Rice", "أرز بسمتي رويال",
     {"1": ("1 kg", "١ كغ", "bag_1", 0, 10, 790), "5": ("5 kg", "٥ كغ", "bag_5", 0, 4, 3750), "10": ("10 kg", "١٠ كغ", "bag_10", 0, 2, 7200), "20": ("20 kg", "٢٠ كغ", "bag_20", 0, 1, 13900)}),
    ("royale_sella", "Royale Golden Sella Basmati", "أرز سيلا ذهبي رويال",
     {"5": ("5 kg", "٥ كغ", "bag_5", 0, 4, 3400), "10": ("10 kg", "١٠ كغ", "bag_10", 0, 2, 6500), "39": ("39 kg", "٣٩ كغ", "bag_39", 0, 1, 24500)}),
    ("royale_calrose", "Royale Calrose Rice", "أرز كالروز رويال",
     {"2": ("2 kg", "٢ كغ", "bag_2", 0, 10, 1050), "5": ("5 kg", "٥ كغ", "bag_5", 0, 4, 2450)}),
    ("pure_sweet_sugar", "Pure Sweet White Sugar", "سكر بيور سويت أبيض",
     {"1": ("1 kg", "١ كغ", "bag_1", 0, 10, 420), "2": ("2 kg", "٢ كغ", "bag_2", 0, 10, 820), "10": ("10 kg", "١٠ كغ", "bag_10", 0, 1, 3900)}),
    ("chakki_atta", "Chakki Fresh Whole Wheat Atta", "طحين أتا تشاكي فريش",
     {"2": ("2 kg", "٢ كغ", "bag_2", 0, 6, 640), "5": ("5 kg", "٥ كغ", "bag_5", 0, 4, 1480), "10": ("10 kg", "١٠ كغ", "bag_10", 0, 2, 2850)}),
    ("chakki_maida", "Chakki Fresh All Purpose Flour", "طحين متعدد الاستعمال تشاكي",
     {"1": ("1 kg", "١ كغ", "bag_1", 0, 10, 390), "2": ("2 kg", "٢ كغ", "bag_2", 0, 6, 740)}),
    ("sea_salt", "Bahr Fine Salt", "ملح بحر ناعم",
     {"700": ("700 g", "٧٠٠ غ", "jar", 0, 24, 190), "1": ("1 kg bag", "كيس ١ كغ", "bag_1", 0, 20, 220)}),
]:  # fmt: skip
    brand = {"pure_sweet_sugar": "Pure Sweet"}.get(key, en.split()[0])
    _add(Family(key, brand, en, ar, "staples", sizes, "bag"))
for lentil, en, ar in [("toor", "Toor Dal", "دال تور"), ("moong", "Moong Dal", "دال مونج"), ("masoor", "Masoor Dal", "عدس أحمر"), ("chana", "Chana Dal", "دال شانا"), ("kabuli", "Kabuli Chickpeas", "حمص حب")]:  # fmt: skip
    _add(Family(f"royale_{lentil}", "Royale", f"Royale {en}", f"{ar} رويال", "pulses",
                {"1": ("1 kg", "١ كغ", "bag_1", 0, 10, 690), "5": ("5 kg", "٥ كغ", "bag_5", 0, 4, 3200)}, "bag"))  # fmt: skip

# ---- oil, tea, coffee ---------------------------------------------------------------------------
for key, en, ar, sizes in [
    ("sunola_sunflower", "Sunola Sunflower Oil", "زيت دوار الشمس صنولا",
     {"750": ("750 ml", "٧٥٠ مل", "oil_small", 0, 12, 790), "1500": ("1.5 L", "١٫٥ لتر", "oil_mid", 0, 12, 1390), "1800": ("1.8 L", "١٫٨ لتر", "oil_mid2", 0, 6, 1590), "5000": ("5 L", "٥ لتر", "oil_big", 0, 4, 3990)}),
    ("sunola_corn", "Sunola Corn Oil", "زيت ذرة صنولا",
     {"1500": ("1.5 L", "١٫٥ لتر", "oil_mid", 0, 12, 1490), "5000": ("5 L", "٥ لتر", "oil_big", 0, 4, 4390)}),
    ("sunola_vegetable", "Sunola Vegetable Oil", "زيت نباتي صنولا",
     {"1800": ("1.8 L", "١٫٨ لتر", "oil_mid2", 0, 6, 1290), "17000": ("17 L tin", "تنكة ١٧ لتر", "oil_tin", 0, 1, 10900)}),
    ("ghee_gold", "Golden Cow Pure Ghee", "سمن بقرة ذهبية",
     {"500": ("500 g tin", "علبة ٥٠٠ غ", "tin_small", 0, 24, 1690), "1000": ("1 kg tin", "علبة ١ كغ", "tin", 0, 12, 3190)}),
    ("chaipur_tea_bags", "Chaipur Black Tea Bags", "شاي تشايبور أكياس",
     {"25": ("25 bags", "٢٥ كيس", "teabag_small", 0, 48, 390), "100": ("100 bags", "١٠٠ كيس", "teabag_big", 0, 24, 1190)}),
    ("chaipur_loose", "Chaipur Loose Black Tea", "شاي تشايبور ناعم",
     {"225": ("225 g", "٢٢٥ غ", "tea_small", 0, 24, 990), "450": ("450 g", "٤٥٠ غ", "tea_big", 0, 12, 1890)}),
    ("karak_premix", "Chaipur Karak Premix", "كرك تشايبور جاهز",
     {"10": ("10 sachets", "١٠ أكياس", "sachet_box", 0, 24, 990)}),
    ("dune_coffee", "Dune Instant Coffee", "قهوة ديون سريعة الذوبان",
     {"50": ("50 g jar", "برطمان ٥٠ غ", "jar_small", 0, 12, 1390), "200": ("200 g jar", "برطمان ٢٠٠ غ", "jar", 0, 12, 4290)}),
    ("dune_3in1", "Dune Coffee 3-in-1", "قهوة ديون ٣ في ١",
     {"30": ("30 sachets", "٣٠ كيس", "sachet_box", 0, 12, 2190)}),
]:  # fmt: skip
    brand = {"ghee_gold": "Golden Cow"}.get(key, en.split()[0])
    _add(Family(key, brand, en, ar, "oil_tea_coffee", sizes))

# ---- canned and jars ------------------------------------------------------------------------------
for key, en, ar, sizes in [
    ("bahr_tuna_oil", "Bahr Tuna in Sunflower Oil", "تونة بحر بزيت دوار الشمس",
     {"85": ("85 g", "٨٥ غ", "tin_small", 4, 48, 330), "170": ("170 g", "١٧٠ غ", "tin", 0, 48, 590)}),
    ("bahr_tuna_water", "Bahr Tuna in Water", "تونة بحر بالماء",
     {"170": ("170 g", "١٧٠ غ", "tin", 0, 48, 590)}),
    ("rosso_tomato_paste", "Rosso Tomato Paste", "معجون طماطم روسو",
     {"70": ("70 g", "٧٠ غ", "tin_tiny", 8, 100, 85), "135": ("135 g", "١٣٥ غ", "tin_small", 0, 50, 150), "400": ("400 g", "٤٠٠ غ", "tin", 0, 24, 360)}),
    ("rosso_foul", "Rosso Foul Medames", "فول مدمس روسو",
     {"400": ("400 g", "٤٠٠ غ", "tin", 0, 24, 290)}),
    ("rosso_chickpeas", "Rosso Chickpeas", "حمص روسو",
     {"400": ("400 g", "٤٠٠ غ", "tin", 0, 24, 270)}),
    ("rosso_sweetcorn", "Rosso Sweet Corn", "ذرة حلوة روسو",
     {"340": ("340 g", "٣٤٠ غ", "tin", 0, 24, 380)}),
    ("rosso_ketchup", "Rosso Tomato Ketchup", "كاتشب روسو",
     {"340": ("340 g bottle", "قنينة ٣٤٠ غ", "sauce_small", 0, 24, 450), "4000": ("4 kg jug", "جالون ٤ كغ", "sauce_big", 0, 4, 2690)}),
    ("rosso_mayo", "Rosso Mayonnaise", "مايونيز روسو",
     {"473": ("473 ml jar", "برطمان ٤٧٣ مل", "jar", 0, 12, 890), "3780": ("3.78 L jar", "برطمان ٣٫٧٨ لتر", "jar_big", 0, 4, 3690)}),
]:  # fmt: skip
    _add(Family(key, en.split()[0], en, ar, "canned", sizes))

# ---- cleaning and tissue --------------------------------------------------------------------------
for key, en, ar, sizes in [
    ("shimmer_dish_lemon", "Shimmer Dishwash Lemon", "سائل جلي شيمر ليمون",
     {"500": ("500 ml", "٥٠٠ مل", "liquid_small", 0, 24, 390), "1000": ("1 L", "١ لتر", "liquid_mid", 0, 12, 690), "4000": ("4 L", "٤ لتر", "liquid_big", 0, 4, 2190)}),
    ("shimmer_dish_original", "Shimmer Dishwash Original", "سائل جلي شيمر أصلي",
     {"500": ("500 ml", "٥٠٠ مل", "liquid_small", 0, 24, 390), "1000": ("1 L", "١ لتر", "liquid_mid", 0, 12, 690)}),
    ("klenzo_bleach", "Klenzo Bleach", "مبيض كلينزو",
     {"1000": ("1 L", "١ لتر", "liquid_mid", 0, 12, 450), "2000": ("2 L", "٢ لتر", "liquid_mid2", 0, 6, 790), "3780": ("3.78 L", "٣٫٧٨ لتر", "liquid_big", 0, 4, 1290)}),
    ("brite_powder", "Brite Laundry Powder", "مسحوق غسيل برايت",
     {"500": ("500 g", "٥٠٠ غ", "powder_small", 0, 24, 590), "1000": ("1 kg", "١ كغ", "powder_mid", 0, 12, 1090), "3000": ("3 kg", "٣ كغ", "powder_big", 0, 4, 2890)}),
    ("brite_liquid", "Brite Laundry Liquid", "سائل غسيل برايت",
     {"1000": ("1 L", "١ لتر", "liquid_mid", 0, 12, 1390), "3000": ("3 L", "٣ لتر", "liquid_big", 0, 4, 3490)}),
    ("fresh_floor_pine", "Fresh Floor Cleaner Pine", "منظف أرضيات فريش صنوبر",
     {"1000": ("1 L", "١ لتر", "liquid_mid", 0, 12, 590), "3000": ("3 L", "٣ لتر", "liquid_big", 0, 4, 1490)}),
    ("softa_facial", "Softa Facial Tissue", "مناديل سوفتا",
     {"150": ("box of 150", "علبة ١٥٠", "tissue_box", 5, 30, 320), "200": ("box of 200", "علبة ٢٠٠", "tissue_box_big", 5, 30, 390)}),
    ("softa_toilet", "Softa Toilet Rolls", "ورق حمام سوفتا",
     {"10": ("10 rolls", "١٠ لفات", "roll_pack", 0, 4, 1290), "20": ("20 rolls", "٢٠ لفة", "roll_pack_big", 0, 2, 2390)}),
    ("softa_kitchen", "Softa Kitchen Towels", "مناديل مطبخ سوفتا",
     {"2": ("2 rolls", "لفتان", "roll_pack_small", 0, 12, 590), "4": ("4 rolls", "٤ لفات", "roll_pack", 0, 6, 1090)}),
    ("garbage_bags", "Strong Garbage Bags", "أكياس قمامة قوية",
     {"30": ("roll of 30, 65x95", "لفة ٣٠ كيس", "roll", 0, 20, 690)}),
]:  # fmt: skip
    brand = {"garbage_bags": "Strong", "fresh_floor_pine": "Fresh Floor"}.get(key, en.split()[0])
    _add(Family(key, brand, en, ar, "household", sizes))


def ean13(seed: str) -> str:
    """A valid EAN-13 in the 629 (UAE GS1) prefix range, derived from a string. Fictional."""
    digits = "629" + str(int(hashlib.sha256(seed.encode()).hexdigest(), 16))[:9]
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(digits))
    return digits + str((10 - total % 10) % 10)


def build_skus() -> list[Sku]:
    out: list[Sku] = []
    n = 10000
    for f in FAMILIES:
        for size_key, (label, label_ar, size_class, pack, carton, price) in f.sizes.items():
            n += 7
            out.append(
                Sku(
                    id=f"SL-{n}",
                    family=f.key,
                    size=size_key,
                    name_en=f"{f.name_en} {label}",
                    name_ar=f"{f.name_ar} {label_ar}",
                    brand=f.brand,
                    category=f.category,
                    size_label=label,
                    size_class=size_class,
                    base_unit=f.base_unit,
                    pack_size=pack,
                    carton_size=carton,
                    price_fils=price,
                    barcode=ean13(f"{f.key}/{size_key}"),
                    aliases=[f.name_en, f.name_ar, f.brand],
                )
            )
    return out
