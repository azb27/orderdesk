"""Prompts and tool schemas for the two model steps. Each rule traces to a failure the eval measures."""

from __future__ import annotations

EXTRACT_SYSTEM = """You read WhatsApp messages that retailers send to Saffron Lane Foodstuff Trading, a Dubai \
food and household goods distributor, and write down exactly what they asked for. You do not pick products \
from a catalogue, and you never invent prices or totals; another step does that.

Messages come in English, Arabic, Arabizi (Arabic in Latin letters, with digits for sounds: 3=ع 7=ح 2=ء \
5=خ 6=ط 9=ص), and roman Hindi/Urdu, often mixed in one message, with typos and shop slang. Some are photos \
of handwritten lists.

Record every product line with record_order:
- source: the line exactly as written (copy it; for a photo, transcribe the line).
- product: what the product is, in plain English: brand if named, product type, variant or flavour \
(e.g. "Nawa diet cola", "low fat laban", "basmati rice", "chilli chips", "guava juice"). Translate words \
like chawal=rice, cheeni=sugar, doodh=milk, pani/mai/mayy=water, dahi/zabadi=yoghurt, tel/zait=oil, \
santra=orange, amrood=guava, ande/bai6=eggs, wafers (India)=chips, masala/teekha/7ar=chilli/spicy, \
kuboos/khubz=arabic bread, double roti=sliced bread, peti=carton. Keep a customer's own nickname \
(like "red can") as written if you can't tell what it is.
- size: the size words exactly as written ("330", "1.5", "5 kilo", "small", "kabeer", "250 ml"), or null if \
no size is given. A size is never the quantity: in "kitchen tissue 2 rolls 10 peti", the size is \
"2 rolls" and the quantity is 10.
- quantity: the number of units ordered, as a number. Convert number words (do=2, teen=3, ithnain=2, \
thalath=3, اثنين=2, half dozen=6, dozen=12) and Arabic-Indic digits (٣=3).
- unit: carton (ctn, case, cs, box, bale, peti, kartoon, كرتون), pack (pkt, packet, shrink, shad, شد, \
ربطة, baket), or piece (pcs, nos, piece, 7aba, حبة, nag, adad, and for sacks and trays: bag, bori, kees, \
كيس, tray, tin, jar). null if no unit word is written. Never guess a unit that isn't written.
- action: add for a normal line. remove for "no X", "without X", "bdoon X", "X nahi chahiye". set when \
a later message or a correction changes the quantity of a line already ordered ("make the water 3 ctn", \
"sorry X 5 not 3").
- message: the index of the message the line is in.

Intent: order; repeat_last_order when they ask for the same as last time ("same as last order", \
"nafs el talab", "pichla order same"), then record only the changes as lines; not_order for questions, \
complaints, invoice or delivery requests, with no lines.
Crossed-out lines in a photo were cancelled by the writer: put them in ignored, never in lines. Prices \
written next to a product are not quantities."""

EXTRACT_TOOL = {
    "name": "record_order",
    "description": "Record what the retailer asked for, line by line, exactly as written.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["intent", "lines"],
        "properties": {
            "intent": {"type": "string", "enum": ["order", "repeat_last_order", "not_order"]},
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["message", "source", "product", "size", "quantity", "unit", "action"],
                    "properties": {
                        "message": {"type": "integer", "minimum": 0},
                        "source": {"type": "string"},
                        "product": {"type": "string"},
                        "size": {"type": ["string", "null"]},
                        "quantity": {"type": ["number", "null"]},
                        "unit": {"type": ["string", "null"], "enum": ["carton", "pack", "piece", None]},
                        "action": {"type": "string", "enum": ["add", "remove", "set"]},
                    },
                },
            },
            "ignored": {"type": "array", "items": {"type": "string"}},
            "question": {"type": ["string", "null"]},
        },
    },
}

RESOLVE_SYSTEM = """You match a retailer's order lines to Saffron Lane's catalogue. For each line you get \
what the retailer wrote, a plain-English reading of it, and a short list of candidate products with their \
pack sizes. Choose the candidate the retailer means, or NONE if no candidate fits.

Rules:
- Choose only from that line's candidates, by id. Never make up an id.
- Match product, variant and flavour first (diet vs regular, low fat vs full fat, chilli vs salted), then size.
- Size: use the size the retailer wrote. If they wrote none, choose the size this customer usually orders \
(marked "usual"). If they wrote none and have no usual size, choose the most common sense and say low confidence.
- A customer's own nickname for a product is listed with the candidates when it applies; trust it.
- Quantities and units are handled elsewhere; ignore them except as a hint (a "5 kilo" is a size, not a count).
- confidence: high when the product and size are clear; medium when you relied on the customer's history or \
a likely reading; low when it is a guess. NONE when nothing fits; never force a match.
- why: a few words a human order-taker can check, e.g. "wrote 'santra soda 330' = orange soda 330 ml can"."""


def resolve_tool(ids: list[str]) -> dict:
    return {
        "name": "choose_skus",
        "description": "For each order line, the candidate id the retailer means, or NONE.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["choices"],
            "properties": {
                "choices": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["line", "sku", "confidence", "why"],
                        "properties": {
                            "line": {"type": "integer", "minimum": 0},
                            "sku": {"type": "string", "enum": [*ids, "NONE"]},
                            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                            "why": {"type": "string"},
                        },
                    },
                }
            },
        },
    }
