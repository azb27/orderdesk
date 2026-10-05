"""Unit and number words the deterministic parts understand (written independently of the generator).

Product names are deliberately absent: those come from the catalogue's alias table, and from the model.
"""

from __future__ import annotations

from orderdesk.parse.normalize import norm

UNIT_WORDS = {
    "carton": ["ctn", "ctns", "carton", "cartons", "case", "cases", "cs", "box", "boxes", "peti", "petti", "pethi",
               "kartoon", "karton", "kartona", "krtn", "كرتون", "كراتين", "كرتونه", "bale", "bales"],
    "pack": ["pkt", "pkts", "pack", "packs", "packet", "packets", "shrink", "pk", "paketa", "baket", "shad",
             "باكيت", "ربطه", "شد"],
    "piece": ["pcs", "pc", "piece", "pieces", "nos", "no", "units", "unit", "nag", "adad", "7aba", "habba", "7abba",
              "حبه", "حبات", "قطعه", "عدد", "bag", "bags", "sack", "bori", "thaila", "kees", "akyas", "shwal",
              "كيس", "اكياس", "شوال", "tray", "trays", "tin", "tins", "jar", "jars", "bottle", "bottles", "roll"],
}  # fmt: skip
WORD_TO_UNIT = {norm(w): u for u, ws in UNIT_WORDS.items() for w in ws}

NUMBER_WORDS = {
    "one": 1, "a": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "twelve": 12, "dozen": 12, "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "panch": 5,
    "paanch": 5, "chhe": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10, "barah": 12, "darjan": 12,
    "wa7ad": 1, "wa7da": 1, "ithnain": 2, "2nain": 2, "thintain": 2, "thalath": 3, "talata": 3, "arba3": 4,
    "arba3a": 4, "5ams": 5, "khamsa": 5, "sit": 6, "sitta": 6, "3ashr": 10, "3ashara": 10,
    "واحد": 1, "وحده": 1, "اثنين": 2, "ثنتين": 2, "ثلاث": 3, "ثلاثه": 3, "اربع": 4, "اربعه": 4, "خمس": 5,
    "خمسه": 5, "ست": 6, "سته": 6, "عشر": 10, "عشره": 10,
}  # fmt: skip
NUMBER_WORDS = {norm(k): v for k, v in NUMBER_WORDS.items()}
