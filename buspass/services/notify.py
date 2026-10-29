"""In-app notifications (stored, shown in the rider app) and OTP delivery.

Delivery of OTPs goes through `send_otp`, which only logs in this build. Swap it for an SMS (e.g. Twilio,
Vonage, an Egyptian SMS gateway) or email (SES, SendGrid) adapter in production.
"""

import logging

from .. import repositories as repo
from ..models import Notification

log = logging.getLogger(__name__)

MESSAGES = {
    "payment_success": {
        "en": ("Payment successful", "{what} — {amount}. Your receipt is in the app."),
        "ar": ("تم الدفع بنجاح", "{what} — {amount}. الإيصال متاح في التطبيق."),
    },
    "pass_active": {
        "en": ("Your pass is ready", "{product} on route {route} is active until {until}."),
        "ar": ("اشتراكك جاهز", "{product} على خط {route} ساري حتى {until}."),
    },
    "pass_expiring": {
        "en": ("Pass expires today", "Your {product} on route {route} expires today. Renew to keep riding."),
        "ar": ("الاشتراك ينتهي اليوم", "اشتراك {product} على خط {route} ينتهي اليوم. جدّده لتكمل رحلاتك."),
    },
    "pass_renewed": {
        "en": ("Pass renewed", "Your {product} on route {route} was renewed until {until}."),
        "ar": ("تم تجديد الاشتراك", "تم تجديد {product} على خط {route} حتى {until}."),
    },
    "renew_failed": {
        "en": (
            "Auto-renew failed",
            "Not enough wallet balance to renew your {product} on route {route}. Top up and renew manually.",
        ),
        "ar": (
            "فشل التجديد التلقائي",
            "رصيد المحفظة غير كافٍ لتجديد {product} على خط {route}. اشحن المحفظة وجدّد يدويًا.",
        ),
    },
    "delay": {
        "en": ("Service update: route {route}", "{message}"),
        "ar": ("تحديث الخدمة: خط {route}", "{message}"),
    },
    "verification": {
        "en": ("Discount verification {status}", "Your {kind} discount request was {status}."),
        "ar": ("نتيجة التحقق من الخصم", "تم {status} طلب خصم {kind}."),
    },
    "refund": {
        "en": ("Refund issued", "{amount} was refunded to your {target}."),
        "ar": ("تم الاسترداد", "تم رد {amount} إلى {target}."),
    },
    "support": {
        "en": ("We got your message", "Ticket #{id} is open. Our team replies within 24 hours."),
        "ar": ("وصلتنا رسالتك", "تم فتح التذكرة رقم {id}. سيرد فريقنا خلال 24 ساعة."),
    },
    "welcome": {
        "en": ("Welcome to CloudBus Pass", "Buy a pass or top up your wallet to start riding."),
        "ar": ("أهلاً بك في كلاود باص", "اشترِ اشتراكًا أو اشحن محفظتك لتبدأ رحلاتك."),
    },
}


def notify(user, kind, key, **params):
    lang = user.language if user.language in ("en", "ar") else "en"
    title, body = MESSAGES[key][lang]
    params = {k: (v.get(lang, v.get("en")) if isinstance(v, dict) else v) for k, v in params.items()}
    return repo.add(Notification(user_id=user.id, kind=kind, title=title.format(**params), body=body.format(**params)))


def send_otp(target, code, purpose):
    log.info("otp_sent", extra={"target": _mask(target), "purpose": purpose, "delivery": "console"})


def _mask(target):
    return target[:3] + "***" + target[-2:] if len(target) > 6 else "***"
