"""Templated replies to retailers, in the style they write in. Never free-form model text (CLAUDE.md rule 3)."""

from __future__ import annotations

from orderdesk.config import FILS_PER_AED

TEMPLATES = {
    "confirmed": {
        "en": "Order {ref} confirmed: {n} items, AED {total}. Delivery tomorrow. Thank you!",
        "ar": "تم تأكيد الطلب {ref}: {n} أصناف، {total} درهم. التوصيل بكرة إن شاء الله. شكراً!",
        "arabizi": "Tm ta2keed el talab {ref}: {n} a9naf, {total} dirham. El tawseel bukra. Shukran!",
        "roman": "Order {ref} confirm ho gaya: {n} items, AED {total}. Kal delivery hogi. Shukriya!",
    },
    "received": {
        "en": "Got your order, checking it now.",
        "ar": "وصل طلبك، جاري المراجعة.",
        "arabizi": "Wasal talabak, qa3deen nraji3a.",
        "roman": "Order mil gaya, check kar rahe hain.",
    },
    "rejected": {
        "en": "We couldn't process order {ref}. Our team will call you shortly.",
        "ar": "لم نتمكن من تنفيذ الطلب {ref}. سيتصل بك فريقنا قريباً.",
        "arabizi": "Ma gdarna nkammel el talab {ref}. El team bitta9el feek.",
        "roman": "Order {ref} process nahi ho paya. Hamari team aapko call karegi.",
    },
}


def lead_style(styles: dict[str, float] | None) -> str:
    if not styles:
        return "en"
    return max(styles, key=lambda k: styles[k])


def render(kind: str, styles: dict[str, float] | None, **kw: object) -> str:
    total = kw.get("total_fils")
    if isinstance(total, int):
        kw["total"] = f"{total / FILS_PER_AED:,.2f}"
    return TEMPLATES[kind][lead_style(styles)].format(**kw)
