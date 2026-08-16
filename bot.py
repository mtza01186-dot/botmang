#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""بوت إدارة النشر والحسابات في تيليجرام.

لا تُضمَّن مفاتيح تيليجرام أو رموز البوت داخل هذا الملف. اضبطها في متغيرات
البيئة الموضحة في ملف .env.example قبل التشغيل.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

from flask import Flask, jsonify
from kvsqlite.sync import Client as KVClient
from waitress import serve
from telethon import Button, TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    MessageNotModifiedError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetParticipantRequest, JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

# ---------------------------------------------------------------------------
# الإعدادات
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
# في Railway اضبط BOT_DATA_DIR على مسار وحدة التخزين الدائمة، مثل /data.
DATA_DIR = Path(os.getenv("BOT_DATA_DIR", str(BASE_DIR / "database"))).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)


def env_int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


API_ID = env_int("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID = env_int("TELEGRAM_ADMIN_ID")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "").strip().lstrip("@")
PORT = env_int("PORT", 10000)

# تقلل الحدود الآتية احتمالات الحظر والنشر غير المقصود. يمكن ضبطها بيئيًا.
MIN_POST_INTERVAL = max(30, env_int("MIN_POST_INTERVAL", 60))
MAX_GROUPS_PER_CYCLE = max(1, min(50, env_int("MAX_GROUPS_PER_CYCLE", 15)))
MAX_GROUPS_TURBO = max(1, min(30, env_int("MAX_GROUPS_TURBO", 10)))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("telegram_bot")

app = Flask(__name__)
health_state = {"started_at": None, "bot_connected": False}


@app.get("/")
def healthcheck() -> Any:
    return jsonify({"ok": True, **health_state})


def run_health_server() -> None:
    # خادم WSGI بسيط لفحص الصحة في بيئات الإنتاج، من دون ملقم Flask التطويري.
    serve(app, host="0.0.0.0", port=PORT, threads=2)


# ---------------------------------------------------------------------------
# التخزين والحالة في الذاكرة
# ---------------------------------------------------------------------------
db = KVClient(str(DATA_DIR / "bot_data.ss"), "bot")
client = TelegramClient(str(DATA_DIR / "bot_session"), API_ID, API_HASH)

# الحالات التفاعلية مرتبطة بكل مستخدم لمنع التقاط رسالة من تدفق آخر.
pending_inputs: dict[int, dict[str, Any]] = {}
login_contexts: dict[int, dict[str, Any]] = {}
post_tasks: dict[tuple[int, str], asyncio.Task[Any]] = {}
auto_reply_tasks: dict[tuple[int, str], asyncio.Task[Any]] = {}
scheduled_tasks: dict[str, asyncio.Task[Any]] = {}

DEFAULT_ACCOUNT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "message": "مرحباً",
    "interval": MIN_POST_INTERVAL,
    "auto_reply_enabled": False,
    "auto_reply_text": "مرحباً، سنرد عليك في أقرب وقت.",
}


def init_db() -> None:
    defaults: dict[str, Any] = {
        "users": {},
        "accounts_settings": {},
        "memberships": {},
        "pending_requests": {},
        "bot_enabled": True,
        "user_stats": {},
        "collected_links": {},
        "scheduled_posts": {},
    }
    for key, value in defaults.items():
        if not db.exists(key):
            db.set(key, value)


def get_data(key: str, default: Any | None = None) -> Any:
    if db.exists(key):
        return db.get(key)
    return {} if default is None else default


def save_data(key: str, value: Any) -> None:
    db.set(key, value)


def account_key(user_id: int, phone: str) -> str:
    return f"acc_{user_id}_{phone}"


def get_account_settings(user_id: int, phone: str) -> dict[str, Any]:
    """يعيد الإعدادات ويهاجر تلقائيًا تنسيق النسخة القديمة إن وجد."""
    all_settings = get_data("accounts_settings", {})
    key = account_key(user_id, phone)
    settings = all_settings.get(key)

    # توافق مع الإصدار القديم الذي كان يستخدم acc_<phone> فقط.
    if settings is None:
        settings = all_settings.get(f"acc_{phone}", {})

    merged = DEFAULT_ACCOUNT_SETTINGS.copy()
    merged.update(settings or {})
    merged["interval"] = max(MIN_POST_INTERVAL, int(merged.get("interval", MIN_POST_INTERVAL)))
    return merged


def save_account_settings(user_id: int, phone: str, settings: dict[str, Any]) -> None:
    all_settings = get_data("accounts_settings", {})
    merged = DEFAULT_ACCOUNT_SETTINGS.copy()
    merged.update(settings)
    merged["interval"] = max(MIN_POST_INTERVAL, int(merged.get("interval", MIN_POST_INTERVAL)))
    all_settings[account_key(user_id, phone)] = merged
    save_data("accounts_settings", all_settings)


def ensure_user(user_id: int) -> dict[str, Any]:
    users = get_data("users", {})
    user = users.get(str(user_id))
    if user is None:
        user = {
            "accounts": [],
            "created_at": datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
        }
        users[str(user_id)] = user
        save_data("users", users)
    return user


def get_accounts(user_id: int) -> list[dict[str, str]]:
    return ensure_user(user_id).get("accounts", [])


def get_account(user_id: int, phone: str) -> dict[str, str] | None:
    return next((item for item in get_accounts(user_id) if item.get("phone") == phone), None)


def update_user_stats(user_id: int, stat_type: str, value: int = 1) -> None:
    stats = get_data("user_stats", {})
    user_stats = stats.get(str(user_id), {})
    user_stats[stat_type] = int(user_stats.get(stat_type, 0)) + value
    stats[str(user_id)] = user_stats
    save_data("user_stats", stats)


def get_user_stats(user_id: int) -> dict[str, Any]:
    user = ensure_user(user_id)
    accounts = user.get("accounts", [])
    stats = get_data("user_stats", {}).get(str(user_id), {})
    active = sum(1 for a in accounts if get_account_settings(user_id, a["phone"]).get("enabled"))
    scheduled = sum(
        1
        for job in get_data("scheduled_posts", {}).values()
        if job.get("user_id") == user_id and job.get("status") == "pending"
    )
    return {
        "total_accounts": len(accounts),
        "total_groups": int(stats.get("groups", 0)),
        "total_posts": int(stats.get("posts", 0)),
        "total_links": int(stats.get("links", 0)),
        "active_processes": active,
        "scheduled": scheduled,
        "created_at": user.get("created_at", "غير متاح"),
    }


def clean_phone(raw: str) -> str | None:
    phone = re.sub(r"\D", "", raw)
    return phone if 7 <= len(phone) <= 15 else None


def safe_error(exc: Exception) -> str:
    logger.exception("خطأ غير معالج في عملية البوت", exc_info=exc)
    return "تعذر تنفيذ العملية الآن. تحقق من الحساب أو الصلاحيات ثم حاول مجددًا."


# ---------------------------------------------------------------------------
# صلاحيات المستخدم وواجهة العرض
# ---------------------------------------------------------------------------
async def is_admin(user_id: int) -> bool:
    return bool(ADMIN_ID) and user_id == ADMIN_ID


async def check_subscription(user_id: int) -> bool:
    if await is_admin(user_id):
        return True
    memberships = get_data("memberships", {})
    membership = memberships.get(str(user_id), {})
    if not membership.get("active"):
        return False
    expiry = float(membership.get("expiry", 0))
    if expiry and time.time() > expiry:
        memberships.pop(str(user_id), None)
        save_data("memberships", memberships)
        return False
    return True


async def is_user_member(user_id: int) -> bool:
    if not REQUIRED_CHANNEL:
        return True
    try:
        channel = await client.get_entity(f"@{REQUIRED_CHANNEL}")
        await client(GetParticipantRequest(channel=channel, participant=user_id))
        return True
    except Exception as exc:
        # لا نرفع الاستثناء لأن عدم كون البوت مشرفًا بالقناة يجب ألا يسقط البوت كله.
        logger.warning("تعذر التحقق من اشتراك المستخدم %s بالقناة: %s", user_id, exc)
        return False


async def acknowledge(event: Any, text: str | None = None, alert: bool = False) -> None:
    try:
        await event.answer(text, alert=alert)
    except Exception:
        pass


async def safe_edit(event: Any, text: str, buttons: list[list[Button]] | None = None) -> bool:
    """يعدّل رسالة زر بشكل آمن دون ظهور MessageNotModifiedError في السجل."""
    try:
        await event.edit(text, buttons=buttons, parse_mode="md")
        await acknowledge(event)
        return True
    except MessageNotModifiedError:
        await acknowledge(event)
        return False
    except Exception as exc:
        logger.warning("تعذر تعديل رسالة الواجهة: %s", exc)
        await acknowledge(event, "تعذر تحديث الواجهة. حاول مرة أخرى.", alert=True)
        return False


async def respond(event: Any, text: str, buttons: list[list[Button]] | None = None) -> None:
    await event.respond(text, buttons=buttons, parse_mode="md")


WELCOME_MESSAGE = (
    "**بوت إدارة النشر والحسابات**\n\n"
    "للوصول إلى لوحة التحكم، اطلب اشتراكًا بعد الانضمام إلى القناة المطلوبة."
)

MAIN_BUTTONS: list[list[Button]] = [
    [Button.inline("📱 إدارة الأرقام", b"manage_accounts")],
    [Button.inline("🚀 محرك النشر", b"publish_engine")],
    [Button.inline("⚡ النشر السريع", b"turbo_publish")],
    [Button.inline("🔗 جلب الروابط", b"fetch_links")],
    [Button.inline("📂 انضمام لمجموعة", b"join_section")],
    [Button.inline("🔄 العمليات الجارية", b"running_processes")],
    [Button.inline("🤖 الرد التلقائي", b"auto_reply")],
    [Button.inline("📖 شرح البوت", b"help_bot")],
]


def copy_buttons(buttons: list[list[Button]]) -> list[list[Button]]:
    return [row[:] for row in buttons]


async def render_main(event: Any, user_id: int, *, edit: bool) -> None:
    stats = get_user_stats(user_id)
    text = (
        "**📊 لوحة المعلومات**\n\n"
        f"📱 إجمالي الأرقام: {stats['total_accounts']}\n"
        f"👥 المجموعات: {stats['total_groups']}\n"
        f"📨 المنشورات: {stats['total_posts']}\n"
        f"🔗 الروابط: {stats['total_links']}\n"
        f"⚡ عمليات النشر: {stats['active_processes']}\n"
        f"📅 منشورات مجدولة: {stats['scheduled']}\n"
        f"🗓 تاريخ الإنشاء: {stats['created_at']}"
    )
    buttons = copy_buttons(MAIN_BUTTONS)
    if await is_admin(user_id):
        buttons.append([Button.inline("👑 لوحة المشرف", b"admin_panel")])
    if edit:
        await safe_edit(event, text, buttons)
    else:
        await respond(event, text, buttons)


async def ensure_access(event: Any) -> bool:
    user_id = event.chat_id
    if not await is_user_member(user_id):
        buttons = [[Button.url("📢 الانضمام إلى القناة", f"https://t.me/{REQUIRED_CHANNEL}")]] if REQUIRED_CHANNEL else None
        await safe_edit(event, "⚠️ يجب الانضمام إلى القناة أولًا، ثم اضغط /start.", buttons)
        return False
    if not await check_subscription(user_id):
        await safe_edit(event, WELCOME_MESSAGE, [[Button.inline("💎 طلب اشتراك", b"request_sub")]])
        return False
    ensure_user(user_id)
    return True


async def set_input_state(user_id: int, kind: str, **data: Any) -> None:
    pending_inputs[user_id] = {"kind": kind, **data}


async def clear_input_state(user_id: int, *, close_login: bool = False) -> None:
    pending_inputs.pop(user_id, None)
    if close_login:
        context = login_contexts.pop(user_id, None)
        if context:
            try:
                await context["client"].disconnect()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# مهام الخلفية: النشر والرد التلقائي والجدولة
# ---------------------------------------------------------------------------
def start_task(store: dict[Any, asyncio.Task[Any]], key: Any, coroutine: Awaitable[Any], label: str) -> None:
    current = store.get(key)
    if current and not current.done():
        return
    task = asyncio.create_task(coroutine, name=label)
    store[key] = task

    def finished(done: asyncio.Task[Any]) -> None:
        if store.get(key) is done:
            store.pop(key, None)
        try:
            done.result()
        except asyncio.CancelledError:
            logger.info("ألغيت المهمة %s", label)
        except Exception:
            logger.exception("انتهت المهمة %s بخطأ", label)

    task.add_done_callback(finished)


async def disconnect_quietly(temp: TelegramClient | None) -> None:
    if temp is not None:
        try:
            await temp.disconnect()
        except Exception:
            pass


async def selected_groups(temp: TelegramClient, limit: int) -> list[Any]:
    dialogs = await temp.get_dialogs()
    groups = [dialog for dialog in dialogs if dialog.is_group]
    random.shuffle(groups)
    return groups[:limit]


async def publish_once(user_id: int, phone: str, message: str, *, limit: int) -> tuple[int, int]:
    account = get_account(user_id, phone)
    if not account:
        return 0, 1
    temp: TelegramClient | None = None
    success = failed = 0
    try:
        temp = TelegramClient(StringSession(account["session"]), API_ID, API_HASH)
        await temp.connect()
        if not await temp.is_user_authorized():
            raise RuntimeError("جلسة الحساب غير صالحة أو انتهت")
        for group in await selected_groups(temp, limit):
            try:
                await temp.send_message(group.entity, message)
                success += 1
                update_user_stats(user_id, "posts")
                await asyncio.sleep(random.uniform(2.0, 4.0))
            except FloodWaitError as exc:
                logger.warning("طلب تيليجرام انتظار %s ثانية للحساب %s", exc.seconds, phone)
                failed += 1
                break
            except Exception as exc:
                logger.info("فشل النشر في مجموعة للحساب %s: %s", phone, exc)
                failed += 1
    finally:
        await disconnect_quietly(temp)
    return success, failed


async def auto_post_loop(user_id: int, phone: str, session_string: str) -> None:
    logger.info("بدء النشر التلقائي: user=%s phone=%s", user_id, phone)
    while True:
        settings = get_account_settings(user_id, phone)
        if not get_data("bot_enabled", True) or not settings.get("enabled"):
            return
        try:
            await publish_once(
                user_id,
                phone,
                str(settings.get("message", "مرحباً")),
                limit=MAX_GROUPS_PER_CYCLE,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("فشل تكرار النشر التلقائي للحساب %s", phone)
        interval = max(MIN_POST_INTERVAL, int(settings.get("interval", MIN_POST_INTERVAL)))
        # نوم قابل للإلغاء بدل حجز جلسة تيليجرام بلا سبب.
        for _ in range(interval):
            await asyncio.sleep(1)
            if not get_account_settings(user_id, phone).get("enabled"):
                return


async def auto_reply_loop(user_id: int, phone: str, session_string: str) -> None:
    temp: TelegramClient | None = None
    try:
        temp = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await temp.connect()
        if not await temp.is_user_authorized():
            logger.warning("لا يمكن تشغيل الرد التلقائي؛ الجلسة غير صالحة: %s", phone)
            return

        @temp.on(events.NewMessage(incoming=True))
        async def reply_to_private(message_event: Any) -> None:
            if not message_event.is_private:
                return
            settings = get_account_settings(user_id, phone)
            if not settings.get("auto_reply_enabled"):
                return
            try:
                sender = await message_event.get_sender()
                if getattr(sender, "bot", False):
                    return
                await message_event.reply(str(settings.get("auto_reply_text", "")))
            except FloodWaitError as exc:
                logger.warning("الرد التلقائي للحساب %s متوقف %s ثانية", phone, exc.seconds)
            except Exception as exc:
                logger.info("فشل رد تلقائي للحساب %s: %s", phone, exc)

        while get_account_settings(user_id, phone).get("auto_reply_enabled"):
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("فشل الرد التلقائي للحساب %s", phone)
    finally:
        await disconnect_quietly(temp)


async def scheduled_publish_worker(job_id: str) -> None:
    jobs = get_data("scheduled_posts", {})
    job = jobs.get(job_id)
    if not job or job.get("status") != "pending":
        return
    delay = max(0.0, float(job["run_at"]) - time.time())
    await asyncio.sleep(delay)

    jobs = get_data("scheduled_posts", {})
    job = jobs.get(job_id)
    if not job or job.get("status") != "pending":
        return

    user_id = int(job["user_id"])
    phones = job["phones"]
    success = failed = 0
    for phone in phones:
        try:
            ok, bad = await publish_once(user_id, phone, job["message"], limit=MAX_GROUPS_PER_CYCLE)
            success += ok
            failed += bad
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("فشل النشر المجدول للحساب %s", phone)
            failed += 1

    jobs = get_data("scheduled_posts", {})
    if job_id in jobs:
        jobs[job_id]["status"] = "done"
        jobs[job_id]["completed_at"] = time.time()
        save_data("scheduled_posts", jobs)
    try:
        detail = "\nℹ️ إذا كان الفشل كاملًا، تأكد أن الحساب عضو في المجموعات ولديه صلاحية إرسال الرسائل." if success == 0 else ""
        await client.send_message(
            user_id,
            f"✅ اكتمل النشر المجدول.\n📨 نجح: {success}\n⚠️ فشل: {failed}{detail}",
        )
    except Exception:
        logger.exception("تعذر إرسال نتيجة الجدولة للمستخدم %s", user_id)


def schedule_post(user_id: int, phones: list[str], message: str, minutes: int) -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "user_id": user_id,
        "phones": phones,
        "message": message,
        "run_at": time.time() + (minutes * 60),
        "status": "pending",
        "created_at": time.time(),
    }
    jobs = get_data("scheduled_posts", {})
    jobs[job_id] = job
    save_data("scheduled_posts", jobs)
    start_task(scheduled_tasks, job_id, scheduled_publish_worker(job_id), f"scheduled:{job_id}")
    return job


async def restore_background_tasks() -> None:
    for user_id_text, user in get_data("users", {}).items():
        if not user_id_text.isdigit():
            continue
        user_id = int(user_id_text)
        for account in user.get("accounts", []):
            phone = account.get("phone")
            if not phone or not account.get("session"):
                continue
            settings = get_account_settings(user_id, phone)
            if settings.get("enabled"):
                start_task(
                    post_tasks,
                    (user_id, phone),
                    auto_post_loop(user_id, phone, account["session"]),
                    f"post:{user_id}:{phone}",
                )
            if settings.get("auto_reply_enabled"):
                start_task(
                    auto_reply_tasks,
                    (user_id, phone),
                    auto_reply_loop(user_id, phone, account["session"]),
                    f"reply:{user_id}:{phone}",
                )
    for job_id, job in get_data("scheduled_posts", {}).items():
        if job.get("status") == "pending":
            start_task(scheduled_tasks, job_id, scheduled_publish_worker(job_id), f"scheduled:{job_id}")


# ---------------------------------------------------------------------------
# الحسابات والواجهة العامة
# ---------------------------------------------------------------------------
@client.on(events.NewMessage(pattern=r"^/start(?:\s|$)", incoming=True))
async def start_cmd(event: Any) -> None:
    user_id = event.chat_id
    if not event.is_private:
        return
    if not await is_user_member(user_id):
        buttons = [[Button.url("📢 الانضمام إلى القناة", f"https://t.me/{REQUIRED_CHANNEL}")]] if REQUIRED_CHANNEL else None
        await respond(event, "⚠️ يجب الانضمام إلى القناة المطلوبة أولًا.", buttons)
        return
    if not await check_subscription(user_id):
        await respond(event, WELCOME_MESSAGE, [[Button.inline("💎 طلب اشتراك", b"request_sub")]])
        return
    ensure_user(user_id)
    await render_main(event, user_id, edit=False)


@client.on(events.CallbackQuery(data=b"request_sub"))
async def request_subscription(event: Any) -> None:
    user_id = event.chat_id
    if await is_admin(user_id):
        await acknowledge(event, "أنت المشرف.", alert=True)
        return
    if not await is_user_member(user_id):
        await acknowledge(event, "انضم للقناة المطلوبة أولًا.", alert=True)
        return
    pending = get_data("pending_requests", {})
    if str(user_id) in pending:
        await acknowledge(event, "طلبك قيد المراجعة بالفعل.", alert=True)
        return
    sender = await event.get_sender()
    pending[str(user_id)] = {
        "name": getattr(sender, "first_name", None) or "مستخدم",
        "username": getattr(sender, "username", None) or "لا يوجد",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_data("pending_requests", pending)
    try:
        await client.send_message(
            ADMIN_ID,
            f"🆕 **طلب اشتراك جديد**\n👤 {pending[str(user_id)]['name']}\n🆔 `{user_id}`",
            buttons=[[
                Button.inline("✅ قبول", f"accept_{user_id}".encode()),
                Button.inline("❌ رفض", f"reject_{user_id}".encode()),
            ]],
        )
    except Exception:
        logger.exception("تعذر إرسال طلب الاشتراك للمشرف")
        await safe_edit(event, "⚠️ تعذر إرسال الطلب إلى المشرف. حاول لاحقًا.")
        return
    await safe_edit(event, "✅ تم إرسال طلب اشتراكك للمشرف.")


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"accept_")))
async def accept_subscription(event: Any) -> None:
    if not await is_admin(event.chat_id):
        return
    try:
        target_id = int(event.data.decode().split("_", 1)[1])
    except (ValueError, IndexError):
        await acknowledge(event, "معرّف طلب غير صالح.", alert=True)
        return
    await set_input_state(event.chat_id, "admin_approve_days", target_id=target_id)
    await safe_edit(event, f"✅ قبول اشتراك `{target_id}`\nأرسل عدد أيام الاشتراك (1–3660).")


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"reject_")))
async def reject_subscription(event: Any) -> None:
    if not await is_admin(event.chat_id):
        return
    try:
        target_id = int(event.data.decode().split("_", 1)[1])
    except (ValueError, IndexError):
        await acknowledge(event, "معرّف طلب غير صالح.", alert=True)
        return
    pending = get_data("pending_requests", {})
    pending.pop(str(target_id), None)
    save_data("pending_requests", pending)
    try:
        await client.send_message(target_id, "❌ تم رفض طلب الاشتراك.")
    except Exception:
        logger.info("لا يمكن إخطار المستخدم %s برفض الاشتراك", target_id)
    await safe_edit(event, f"✅ تم رفض طلب `{target_id}`.")


@client.on(events.CallbackQuery(data=b"back_main"))
async def back_main(event: Any) -> None:
    await clear_input_state(event.chat_id, close_login=True)
    if await ensure_access(event):
        await render_main(event, event.chat_id, edit=True)


@client.on(events.CallbackQuery(data=b"cancel"))
async def cancel_flow(event: Any) -> None:
    await clear_input_state(event.chat_id, close_login=True)
    await acknowledge(event, "أُلغيت العملية.")
    if await ensure_access(event):
        await render_main(event, event.chat_id, edit=True)


@client.on(events.CallbackQuery(data=b"manage_accounts"))
async def manage_accounts(event: Any) -> None:
    if not await ensure_access(event):
        return
    accounts = get_accounts(event.chat_id)
    if not accounts:
        await safe_edit(
            event,
            "📱 **إدارة الأرقام**\n\nلا توجد أرقام مضافة.",
            [[Button.inline("➕ إضافة رقم", b"add_account")], [Button.inline("🔙 رجوع", b"back_main")]],
        )
        return
    buttons: list[list[Button]] = []
    for account in accounts:
        phone = account["phone"]
        status = "✅" if get_account_settings(event.chat_id, phone).get("enabled") else "⏸️"
        buttons.append([Button.inline(f"{status} +{phone}", f"manage_acc_{phone}".encode())])
    buttons += [[Button.inline("➕ إضافة رقم جديد", b"add_account")], [Button.inline("🔙 رجوع", b"back_main")]]
    await safe_edit(event, f"📱 **إدارة الأرقام**\nلديك {len(accounts)} رقم.", buttons)


@client.on(events.CallbackQuery(data=b"add_account"))
async def add_account(event: Any) -> None:
    if not await ensure_access(event):
        return
    await set_input_state(event.chat_id, "add_phone")
    await safe_edit(
        event,
        "📱 أرسل رقم الهاتف بصيغة دولية، مثال: `+966512345678`\n\nاستخدم /cancel للإلغاء.",
        [[Button.inline("إلغاء", b"cancel")]],
    )


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"manage_acc_")))
async def manage_single_account(event: Any) -> None:
    if not await ensure_access(event):
        return
    phone = event.data.decode().split("_", 2)[2]
    if not get_account(event.chat_id, phone):
        await acknowledge(event, "الحساب غير موجود.", alert=True)
        return
    settings = get_account_settings(event.chat_id, phone)
    status = "✅ مفعل" if settings["enabled"] else "⏸️ معطل"
    text = (
        f"📱 **+{phone}**\n"
        f"📊 النشر التلقائي: {status}\n"
        f"⏱ الفاصل: {settings['interval']} ثانية\n"
        f"🤖 الرد التلقائي: {'مفعل' if settings['auto_reply_enabled'] else 'معطل'}"
    )
    buttons = [
        [Button.inline("📋 جلب المجموعات", f"get_groups_{phone}".encode())],
        [Button.inline("✏️ كليشة النشر", f"set_msg_{phone}".encode())],
        [Button.inline("⏱ تغيير الفاصل", f"set_int_{phone}".encode())],
        [Button.inline("🔄 تفعيل/إيقاف النشر", f"toggle_{phone}".encode())],
        [Button.inline("🗑 حذف الحساب", f"delete_acc_{phone}".encode())],
        [Button.inline("🔙 رجوع", b"manage_accounts")],
    ]
    await safe_edit(event, text, buttons)


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"get_groups_")))
async def get_groups(event: Any) -> None:
    if not await ensure_access(event):
        return
    phone = event.data.decode().split("_", 2)[2]
    account = get_account(event.chat_id, phone)
    if not account:
        await acknowledge(event, "الحساب غير موجود.", alert=True)
        return
    await safe_edit(event, "🔄 جارٍ جلب المجموعات…")
    temp: TelegramClient | None = None
    try:
        temp = TelegramClient(StringSession(account["session"]), API_ID, API_HASH)
        await temp.connect()
        if not await temp.is_user_authorized():
            raise RuntimeError("جلسة الحساب غير صالحة")
        groups = await selected_groups(temp, 10_000)
        update_user_stats(event.chat_id, "groups", len(groups))
        if not groups:
            await safe_edit(event, "⚠️ لا توجد مجموعات في هذا الحساب.", [[Button.inline("🔙 رجوع", f"manage_acc_{phone}".encode())]])
            return
        lines = [f"{index}. {group.name or 'بدون اسم'} | {group.id}" for index, group in enumerate(groups, 1)]
        file_path = BASE_DIR / f"groups_{event.chat_id}_{phone}_{int(time.time())}.txt"
        file_path.write_text("\n".join(lines), encoding="utf-8")
        try:
            await client.send_file(event.chat_id, file_path, caption=f"📋 مجموعات الحساب +{phone}: {len(groups)}")
        finally:
            file_path.unlink(missing_ok=True)
        preview = "\n".join(lines[:15])
        more = f"\n… وأُرسل ملف كامل يضم {len(groups)} مجموعة." if len(groups) > 15 else ""
        await safe_edit(event, f"📋 **المجموعات: {len(groups)}**\n\n{preview}{more}", [[Button.inline("🔙 رجوع", f"manage_acc_{phone}".encode())]])
    except Exception as exc:
        await safe_edit(event, f"❌ {safe_error(exc)}", [[Button.inline("🔙 رجوع", f"manage_acc_{phone}".encode())]])
    finally:
        await disconnect_quietly(temp)


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"set_msg_")))
async def set_message(event: Any) -> None:
    if not await ensure_access(event):
        return
    phone = event.data.decode().split("_", 2)[2]
    if not get_account(event.chat_id, phone):
        await acknowledge(event, "الحساب غير موجود.", alert=True)
        return
    await set_input_state(event.chat_id, "set_post_message", phone=phone)
    await safe_edit(event, "✏️ أرسل كليشة النشر الجديدة.\n\nاستخدم /cancel للإلغاء.", [[Button.inline("إلغاء", b"cancel")]])


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"set_int_")))
async def set_interval(event: Any) -> None:
    if not await ensure_access(event):
        return
    phone = event.data.decode().split("_", 2)[2]
    if not get_account(event.chat_id, phone):
        await acknowledge(event, "الحساب غير موجود.", alert=True)
        return
    await set_input_state(event.chat_id, "set_interval", phone=phone)
    await safe_edit(event, f"⏱ أرسل الفاصل بالثواني ({MIN_POST_INTERVAL}–3600).", [[Button.inline("إلغاء", b"cancel")]])


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"toggle_") and not data.startswith(b"toggle_reply_")))
async def toggle_post(event: Any) -> None:
    if not await ensure_access(event):
        return
    phone = event.data.decode().split("_", 1)[1]
    account = get_account(event.chat_id, phone)
    if not account:
        await acknowledge(event, "الحساب غير موجود.", alert=True)
        return
    settings = get_account_settings(event.chat_id, phone)
    settings["enabled"] = not bool(settings.get("enabled"))
    save_account_settings(event.chat_id, phone, settings)
    key = (event.chat_id, phone)
    if settings["enabled"]:
        start_task(post_tasks, key, auto_post_loop(event.chat_id, phone, account["session"]), f"post:{event.chat_id}:{phone}")
        await acknowledge(event, "تم تفعيل النشر التلقائي.")
    else:
        task = post_tasks.get(key)
        if task and not task.done():
            task.cancel()
        await acknowledge(event, "تم إيقاف النشر التلقائي.")
    await manage_single_account(event)


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"delete_acc_")))
async def delete_account(event: Any) -> None:
    if not await ensure_access(event):
        return
    phone = event.data.decode().split("_", 2)[2]
    if not get_account(event.chat_id, phone):
        await acknowledge(event, "الحساب غير موجود.", alert=True)
        return
    await safe_edit(
        event,
        f"⚠️ هل تريد حذف الحساب `+{phone}`؟ سيوقف ذلك مهام النشر والرد التلقائي.",
        [[Button.inline("🗑 تأكيد الحذف", f"confirm_delete_{phone}".encode())], [Button.inline("إلغاء", f"manage_acc_{phone}".encode())]],
    )


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"confirm_delete_")))
async def confirm_delete_account(event: Any) -> None:
    if not await ensure_access(event):
        return
    phone = event.data.decode().split("_", 2)[2]
    user_id = event.chat_id
    users = get_data("users", {})
    user = users.get(str(user_id), {})
    before = user.get("accounts", [])
    user["accounts"] = [account for account in before if account.get("phone") != phone]
    if len(user["accounts"]) == len(before):
        await acknowledge(event, "الحساب غير موجود.", alert=True)
        return
    users[str(user_id)] = user
    save_data("users", users)
    settings = get_account_settings(user_id, phone)
    settings["enabled"] = False
    settings["auto_reply_enabled"] = False
    save_account_settings(user_id, phone, settings)
    for store in (post_tasks, auto_reply_tasks):
        task = store.get((user_id, phone))
        if task and not task.done():
            task.cancel()
    await acknowledge(event, "تم حذف الحساب.")
    await manage_accounts(event)


# ---------------------------------------------------------------------------
# محرك النشر والنشر السريع والجدولة
# ---------------------------------------------------------------------------
@client.on(events.CallbackQuery(data=b"publish_engine"))
async def publish_engine(event: Any) -> None:
    if not await ensure_access(event):
        return
    await safe_edit(
        event,
        "🚀 **محرك النشر**\n\nاختر العملية المطلوبة:",
        [
            [Button.inline("📤 نشر عادي", b"normal_publish")],
            [Button.inline("📅 نشر مجدول", b"schedule_publish")],
            [Button.inline("🔄 النشر التلقائي", b"auto_publish")],
            [Button.inline("🔙 رجوع", b"back_main")],
        ],
    )


@client.on(events.CallbackQuery(data=b"normal_publish"))
async def normal_publish(event: Any) -> None:
    if not await ensure_access(event):
        return
    if not get_accounts(event.chat_id):
        await acknowledge(event, "أضف حسابًا أولًا.", alert=True)
        return
    await set_input_state(event.chat_id, "normal_message")
    await safe_edit(event, "📝 أرسل رسالة النشر الآن.\n\nاستخدم /cancel للإلغاء.", [[Button.inline("إلغاء", b"cancel")]])


async def show_publish_account_choices(event: Any, user_id: int, state_name: str) -> None:
    """يرسل اختيار الحساب كرسالة جديدة لأن event هنا رسالة واردة من المستخدم.

    محاولة event.edit على رسالة المستخدم لا تعمل في Telethon، وكانت تمنع
    تدفقي النشر العادي والمجدول من إظهار أزرار اختيار الحساب.
    """
    accounts = get_accounts(user_id)
    if not accounts:
        await respond(event, "❌ لا توجد حسابات مضافة.", [[Button.inline("🔙 رجوع", b"back_main")]])
        return
    prefix = "normal_to" if state_name == "normal_message_ready" else "schedule_to"
    buttons = [[Button.inline(f"📱 +{account['phone']}", f"{prefix}_{account['phone']}".encode())] for account in accounts]
    if len(accounts) > 1:
        buttons.append([Button.inline("📤 جميع الحسابات", f"{prefix}_all".encode())])
    buttons.append([Button.inline("إلغاء", b"cancel")])
    await respond(event, "📱 اختر الحساب المستهدف للنشر:", buttons)


async def normal_publish_task(user_id: int, phones: list[str], message: str) -> None:
    success = failed = 0
    for phone in phones:
        try:
            ok, bad = await publish_once(user_id, phone, message, limit=MAX_GROUPS_PER_CYCLE)
            success += ok
            failed += bad
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("فشل النشر العادي للحساب %s", phone)
            failed += 1
    detail = "\nℹ️ إذا كان الفشل كاملًا، تأكد أن الحساب عضو في المجموعات ولديه صلاحية إرسال الرسائل." if success == 0 else ""
    try:
        await client.send_message(
            user_id,
            f"✅ اكتمل النشر العادي.\n📨 نجح: {success}\n⚠️ فشل: {failed}{detail}",
            buttons=[[Button.inline("🔙 القائمة الرئيسية", b"back_main")]],
        )
    except Exception:
        logger.exception("تعذر إرسال نتيجة النشر العادي للمستخدم %s", user_id)


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"normal_to_")))
async def normal_publish_to_account(event: Any) -> None:
    if not await ensure_access(event):
        return
    state = pending_inputs.get(event.chat_id, {})
    if state.get("kind") != "normal_message_ready":
        await acknowledge(event, "أرسل رسالة النشر أولًا.", alert=True)
        return
    choice = event.data.decode().split("_", 2)[2]
    phones = [account["phone"] for account in get_accounts(event.chat_id)] if choice == "all" else [choice]
    if not phones or any(not get_account(event.chat_id, phone) for phone in phones):
        await acknowledge(event, "الحساب غير موجود.", alert=True)
        return
    message = state["message"]
    user_id = event.chat_id
    await clear_input_state(user_id)
    await acknowledge(event, "🔄 بدأت عملية النشر العادي. ستصلك النتيجة عند اكتمالها.")
    start_task(
        scheduled_tasks,
        f"normal:{user_id}:{time.time_ns()}",
        normal_publish_task(user_id, phones, message),
        f"normal:{user_id}",
    )


@client.on(events.CallbackQuery(data=b"schedule_publish"))
async def schedule_publish(event: Any) -> None:
    if not await ensure_access(event):
        return
    if not get_accounts(event.chat_id):
        await acknowledge(event, "أضف حسابًا أولًا.", alert=True)
        return
    await set_input_state(event.chat_id, "schedule_message")
    await safe_edit(event, "📝 أرسل رسالة النشر المجدول.\n\nاستخدم /cancel للإلغاء.", [[Button.inline("إلغاء", b"cancel")]])


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"schedule_to_")))
async def schedule_publish_to_account(event: Any) -> None:
    if not await ensure_access(event):
        return
    state = pending_inputs.get(event.chat_id, {})
    if state.get("kind") != "schedule_account_ready":
        await acknowledge(event, "ابدأ من النشر المجدول أولًا.", alert=True)
        return
    choice = event.data.decode().split("_", 2)[2]
    phones = [account["phone"] for account in get_accounts(event.chat_id)] if choice == "all" else [choice]
    if not phones or any(not get_account(event.chat_id, phone) for phone in phones):
        await acknowledge(event, "الحساب غير موجود.", alert=True)
        return
    job = schedule_post(event.chat_id, phones, state["message"], int(state["minutes"]))
    await clear_input_state(event.chat_id)
    run_at = datetime.fromtimestamp(job["run_at"]).strftime("%Y-%m-%d %H:%M")
    await safe_edit(event, f"✅ جُدول النشر في **{run_at}** للحسابات المحددة.", [[Button.inline("🔙 القائمة الرئيسية", b"back_main")]])


@client.on(events.CallbackQuery(data=b"auto_publish"))
async def auto_publish(event: Any) -> None:
    if not await ensure_access(event):
        return
    accounts = get_accounts(event.chat_id)
    if not accounts:
        await safe_edit(event, "❌ لا توجد حسابات. أضف حسابًا أولًا.", [[Button.inline("📱 إضافة حساب", b"add_account")], [Button.inline("🔙 رجوع", b"publish_engine")]])
        return
    buttons = [[Button.inline(f"إدارة +{account['phone']}", f"manage_acc_{account['phone']}".encode())] for account in accounts]
    buttons.append([Button.inline("🔙 رجوع", b"publish_engine")])
    await safe_edit(event, "🔄 من صفحة الحساب تستطيع تحديد الكليشة والفاصل، ثم تفعيل النشر التلقائي أو إيقافه.", buttons)


@client.on(events.CallbackQuery(data=b"turbo_publish"))
async def turbo_publish(event: Any) -> None:
    if not await ensure_access(event):
        return
    if not get_accounts(event.chat_id):
        await acknowledge(event, "أضف حسابًا أولًا.", alert=True)
        return
    await set_input_state(event.chat_id, "turbo_message")
    await safe_edit(event, "⚡ أرسل رسالة النشر السريع. سيستخدم أول ثلاثة حسابات بحد أقصى.", [[Button.inline("إلغاء", b"cancel")]])


# ---------------------------------------------------------------------------
# جلب الروابط وتصديرها والانضمام
# ---------------------------------------------------------------------------
@client.on(events.CallbackQuery(data=b"fetch_links"))
async def fetch_links(event: Any) -> None:
    if not await ensure_access(event):
        return
    accounts = get_accounts(event.chat_id)
    if not accounts:
        await acknowledge(event, "لا توجد حسابات مضافة.", alert=True)
        return
    buttons = [[Button.inline(f"📱 +{account['phone']}", f"fetch_from_{account['phone']}".encode())] for account in accounts]
    buttons.append([Button.inline("🔙 رجوع", b"back_main")])
    await safe_edit(event, "🔗 اختر حسابًا لجلب الروابط العامة من رسائله:", buttons)


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"fetch_from_")))
async def fetch_from_account(event: Any) -> None:
    if not await ensure_access(event):
        return
    phone = event.data.decode().split("_", 2)[2]
    account = get_account(event.chat_id, phone)
    if not account:
        await acknowledge(event, "الحساب غير موجود.", alert=True)
        return
    await safe_edit(event, f"🔄 جارٍ جلب الروابط من +{phone}…")
    temp: TelegramClient | None = None
    try:
        temp = TelegramClient(StringSession(account["session"]), API_ID, API_HASH)
        await temp.connect()
        if not await temp.is_user_authorized():
            raise RuntimeError("جلسة الحساب غير صالحة")
        combined = re.compile(r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|wa\.me|chat\.whatsapp\.com)/[^\s<>]+", re.IGNORECASE)
        found_links: set[str] = set()
        for dialog in await temp.get_dialogs():
            if not (dialog.is_group or dialog.is_channel):
                continue
            try:
                async for message in temp.iter_messages(dialog.entity, limit=100):
                    if message.text:
                        for link in combined.findall(message.text):
                            link = link.rstrip('.,;:!?)]}"')
                            found_links.add(link if link.startswith("http") else f"https://{link}")
            except Exception as exc:
                logger.info("تخطّي حوار أثناء جلب الروابط: %s", exc)
        links = sorted(found_links)
        links_data = get_data("collected_links", {})
        per_user = links_data.get(str(event.chat_id), {})
        per_user[phone] = links
        links_data[str(event.chat_id)] = per_user
        save_data("collected_links", links_data)
        update_user_stats(event.chat_id, "links", len(links))
        if not links:
            await safe_edit(event, "⚠️ لم تُعثر على روابط مطابقة.", [[Button.inline("🔙 رجوع", b"back_main")]])
            return
        preview = "\n".join(f"{index}. {link}" for index, link in enumerate(links[:15], 1))
        suffix = f"\n… و{len(links) - 15} رابطًا آخر." if len(links) > 15 else ""
        await safe_edit(
            event,
            f"🔗 **روابط +{phone}: {len(links)}**\n\n{preview}{suffix}",
            [[Button.inline("📥 تصدير الكل", f"export_links_{phone}".encode())], [Button.inline("🔙 رجوع", b"back_main")]],
        )
    except Exception as exc:
        await safe_edit(event, f"❌ {safe_error(exc)}", [[Button.inline("🔙 رجوع", b"back_main")]])
    finally:
        await disconnect_quietly(temp)


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"export_links_")))
async def export_links(event: Any) -> None:
    if not await ensure_access(event):
        return
    phone = event.data.decode().split("_", 2)[2]
    links = get_data("collected_links", {}).get(str(event.chat_id), {}).get(phone, [])
    if not links:
        await acknowledge(event, "لا توجد روابط محفوظة لهذا الحساب.", alert=True)
        return
    path = BASE_DIR / f"links_{event.chat_id}_{phone}_{int(time.time())}.txt"
    try:
        header = f"روابط الحساب +{phone}\nالتاريخ: {datetime.now():%Y-%m-%d %H:%M:%S}\nالعدد: {len(links)}\n" + ("=" * 40) + "\n\n"
        path.write_text(header + "\n".join(links), encoding="utf-8")
        await client.send_file(event.chat_id, path, caption=f"📁 روابط الحساب +{phone}")
        await acknowledge(event, "أُرسل الملف.")
    except Exception as exc:
        logger.exception("فشل تصدير الروابط")
        await acknowledge(event, f"❌ {safe_error(exc)}", alert=True)
    finally:
        path.unlink(missing_ok=True)


@client.on(events.CallbackQuery(data=b"join_section"))
async def join_section(event: Any) -> None:
    if not await ensure_access(event):
        return
    accounts = get_accounts(event.chat_id)
    if not accounts:
        await acknowledge(event, "لا توجد حسابات مضافة.", alert=True)
        return
    buttons = [[Button.inline(f"📱 +{account['phone']}", f"join_with_{account['phone']}".encode())] for account in accounts]
    buttons.append([Button.inline("🔙 رجوع", b"back_main")])
    await safe_edit(event, "📂 اختر الحساب الذي سينضم إلى الروابط:", buttons)


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"join_with_")))
async def join_with_account(event: Any) -> None:
    if not await ensure_access(event):
        return
    phone = event.data.decode().split("_", 2)[2]
    if not get_account(event.chat_id, phone):
        await acknowledge(event, "الحساب غير موجود.", alert=True)
        return
    await set_input_state(event.chat_id, "join_links", phone=phone)
    await safe_edit(event, "🔗 أرسل روابط تيليجرام، كل رابط في سطر.\n\nاستخدم /cancel للإلغاء.", [[Button.inline("إلغاء", b"cancel")]])


async def join_groups_task(user_id: int, phone: str, links: list[str], wait_seconds: int) -> None:
    account = get_account(user_id, phone)
    if not account:
        await client.send_message(user_id, "❌ الحساب المحدد غير موجود.")
        return
    temp: TelegramClient | None = None
    success = failed = 0
    last_error = ""
    try:
        temp = TelegramClient(StringSession(account["session"]), API_ID, API_HASH)
        await temp.connect()
        if not await temp.is_user_authorized():
            raise RuntimeError("جلسة الحساب غير صالحة أو منتهية")
        for link in links:
            try:
                normalized = link.strip()
                if "t.me/+" in normalized or "t.me/joinchat/" in normalized:
                    invite_hash = normalized.rstrip("/").split("/")[-1].split("?")[0].lstrip("+")
                    await temp(ImportChatInviteRequest(invite_hash))
                else:
                    username = normalized.split("t.me/")[-1].split("?")[0].strip("/@") if "t.me/" in normalized else normalized.strip("/@")
                    if not username or username.startswith(("+", "joinchat")):
                        raise ValueError("رابط دعوة غير صالح")
                    await temp(JoinChannelRequest(username))
                success += 1
                await asyncio.sleep(wait_seconds)
            except FloodWaitError as exc:
                failed += 1
                last_error = f"حد تيليجرام للانتظار {exc.seconds} ثانية"
                logger.warning("حد انتظار عند الانضمام: %s ثانية", exc.seconds)
                break
            except Exception as exc:
                failed += 1
                last_error = type(exc).__name__
                logger.info("فشل الانضمام إلى %s: %s", link, exc)
                await asyncio.sleep(max(1, wait_seconds // 2))
    except Exception as exc:
        failed = max(failed, len(links) - success)
        last_error = type(exc).__name__
        logger.exception("تعذرت مهمة الانضمام للمستخدم %s", user_id)
    finally:
        await disconnect_quietly(temp)
    try:
        detail = f"\nℹ️ آخر سبب للفشل: {last_error}" if last_error and failed else ""
        await client.send_message(user_id, f"✅ اكتملت محاولة الانضمام.\n✅ نجح: {success}\n⚠️ فشل: {failed}{detail}")
    except Exception:
        logger.exception("تعذر إرسال تقرير الانضمام")


# ---------------------------------------------------------------------------
# الرد التلقائي والحالة والمساعدة
# ---------------------------------------------------------------------------
@client.on(events.CallbackQuery(data=b"running_processes"))
async def running_processes(event: Any) -> None:
    if not await ensure_access(event):
        return
    user_id = event.chat_id
    active_posts = [a["phone"] for a in get_accounts(user_id) if get_account_settings(user_id, a["phone"]).get("enabled")]
    active_replies = [a["phone"] for a in get_accounts(user_id) if get_account_settings(user_id, a["phone"]).get("auto_reply_enabled")]
    scheduled = [job for job in get_data("scheduled_posts", {}).values() if job.get("user_id") == user_id and job.get("status") == "pending"]
    text = "🔄 **العمليات الجارية**\n\n"
    text += "📤 نشر تلقائي: " + (", ".join(f"+{phone}" for phone in active_posts) if active_posts else "لا يوجد") + "\n"
    text += "🤖 رد تلقائي: " + (", ".join(f"+{phone}" for phone in active_replies) if active_replies else "لا يوجد") + "\n"
    text += f"📅 منشورات مجدولة: {len(scheduled)}"
    await safe_edit(event, text, [[Button.inline("🔙 رجوع", b"back_main")]])


@client.on(events.CallbackQuery(data=b"auto_reply"))
async def auto_reply(event: Any) -> None:
    if not await ensure_access(event):
        return
    accounts = get_accounts(event.chat_id)
    if not accounts:
        await safe_edit(event, "❌ أضف حسابًا أولًا لتشغيل الرد التلقائي.", [[Button.inline("📱 إضافة حساب", b"add_account")], [Button.inline("🔙 رجوع", b"back_main")]])
        return
    buttons = [[Button.inline(f"🤖 +{account['phone']}", f"auto_reply_acc_{account['phone']}".encode())] for account in accounts]
    buttons.append([Button.inline("🔙 رجوع", b"back_main")])
    await safe_edit(event, "🤖 اختر الحساب لإعداد الرد التلقائي:", buttons)


async def show_auto_reply_account(event: Any, user_id: int, phone: str) -> None:
    settings = get_account_settings(user_id, phone)
    status = "✅ مفعل" if settings["auto_reply_enabled"] else "⏸️ معطل"
    text = f"🤖 **الرد التلقائي: +{phone}**\nالحالة: {status}\n\nالنص الحالي:\n{settings['auto_reply_text']}"
    buttons = [
        [Button.inline("🔄 تفعيل/إيقاف", f"toggle_reply_{phone}".encode())],
        [Button.inline("✏️ تغيير النص", f"set_reply_{phone}".encode())],
        [Button.inline("🔙 رجوع", b"auto_reply")],
    ]
    await safe_edit(event, text, buttons)


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"auto_reply_acc_")))
async def auto_reply_account(event: Any) -> None:
    if not await ensure_access(event):
        return
    phone = event.data.decode().split("_", 3)[3]
    if not get_account(event.chat_id, phone):
        await acknowledge(event, "الحساب غير موجود.", alert=True)
        return
    await show_auto_reply_account(event, event.chat_id, phone)


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"toggle_reply_")))
async def toggle_auto_reply(event: Any) -> None:
    if not await ensure_access(event):
        return
    phone = event.data.decode().split("_", 2)[2]
    account = get_account(event.chat_id, phone)
    if not account:
        await acknowledge(event, "الحساب غير موجود.", alert=True)
        return
    settings = get_account_settings(event.chat_id, phone)
    settings["auto_reply_enabled"] = not bool(settings.get("auto_reply_enabled"))
    save_account_settings(event.chat_id, phone, settings)
    key = (event.chat_id, phone)
    if settings["auto_reply_enabled"]:
        start_task(auto_reply_tasks, key, auto_reply_loop(event.chat_id, phone, account["session"]), f"reply:{event.chat_id}:{phone}")
        await acknowledge(event, "تم تفعيل الرد التلقائي.")
    else:
        task = auto_reply_tasks.get(key)
        if task and not task.done():
            task.cancel()
        await acknowledge(event, "تم إيقاف الرد التلقائي.")
    await show_auto_reply_account(event, event.chat_id, phone)


@client.on(events.CallbackQuery(data=lambda data: data and data.startswith(b"set_reply_")))
async def set_auto_reply(event: Any) -> None:
    if not await ensure_access(event):
        return
    phone = event.data.decode().split("_", 2)[2]
    if not get_account(event.chat_id, phone):
        await acknowledge(event, "الحساب غير موجود.", alert=True)
        return
    await set_input_state(event.chat_id, "set_reply_text", phone=phone)
    await safe_edit(event, "✏️ أرسل نص الرد التلقائي الجديد.", [[Button.inline("إلغاء", b"cancel")]])


@client.on(events.CallbackQuery(data=b"help_bot"))
async def help_bot(event: Any) -> None:
    if not await ensure_access(event):
        return
    text = (
        "📖 **شرح الاستخدام**\n\n"
        "1. أضف الحساب من إدارة الأرقام وأكمل رمز التحقق.\n"
        "2. حدّد كليشة النشر والفاصل لكل حساب.\n"
        "3. استخدم النشر العادي أو المجدول، أو فعّل النشر التلقائي.\n"
        "4. اختر حسابًا لتكوين نص الرد التلقائي.\n"
        "5. اكتب /cancel لإلغاء أي خطوة إدخال.\n\n"
        "يُستحسن النشر في المجموعات التي لديك حق النشر فيها فقط، مع احترام حدود تيليجرام."
    )
    await safe_edit(event, text, [[Button.inline("🔙 رجوع", b"back_main")]])


# ---------------------------------------------------------------------------
# لوحة المشرف
# ---------------------------------------------------------------------------
async def admin_menu(event: Any | None = None) -> None:
    users = get_data("users", {})
    total_users = sum(1 for uid in users if uid.isdigit())
    accounts = sum(len(user.get("accounts", [])) for user in users.values())
    premium = sum(1 for membership in get_data("memberships", {}).values() if membership.get("active"))
    pending = len(get_data("pending_requests", {}))
    text = f"👑 **لوحة المشرف**\n\n👥 المستخدمون: {total_users}\n📱 الحسابات: {accounts}\n💎 المشتركون: {premium}\n⏳ الطلبات: {pending}"
    buttons = [
        [Button.inline("📊 إحصائيات", b"admin_stats"), Button.inline("💎 المشتركون", b"premium_list")],
        [Button.inline("⏳ طلبات الاشتراك", b"show_pending")],
        [Button.inline("➕ ترقية", b"upgrade"), Button.inline("➖ إزالة", b"remove")],
        [Button.inline("📢 إذاعة", b"broadcast")],
        [Button.inline("🔙 رجوع", b"back_main")],
    ]
    if event is None:
        await client.send_message(ADMIN_ID, text, buttons=buttons)
    else:
        await safe_edit(event, text, buttons)


@client.on(events.CallbackQuery(data=b"admin_panel"))
async def admin_panel(event: Any) -> None:
    if await is_admin(event.chat_id):
        await admin_menu(event)


@client.on(events.CallbackQuery(data=b"admin_stats"))
async def admin_stats(event: Any) -> None:
    if not await is_admin(event.chat_id):
        return
    users = get_data("users", {})
    total_users = sum(1 for uid in users if uid.isdigit())
    accounts = sum(len(user.get("accounts", [])) for user in users.values())
    memberships = sum(1 for membership in get_data("memberships", {}).values() if membership.get("active"))
    await acknowledge(event, f"👥 {total_users} | 📱 {accounts} | 💎 {memberships}", alert=True)


@client.on(events.CallbackQuery(data=b"premium_list"))
async def premium_list(event: Any) -> None:
    if not await is_admin(event.chat_id):
        return
    memberships = get_data("memberships", {})
    active = [(uid, info) for uid, info in memberships.items() if info.get("active")]
    if not active:
        await safe_edit(event, "💎 لا يوجد مشتركون نشطون.", [[Button.inline("🔙 رجوع", b"admin_panel")]])
        return
    lines = [f"🆔 `{uid}` — {datetime.fromtimestamp(float(info.get('expiry', 0))):%Y-%m-%d}" for uid, info in active[:50]]
    await safe_edit(event, "💎 **المشتركون النشطون**\n\n" + "\n".join(lines), [[Button.inline("🔙 رجوع", b"admin_panel")]])


@client.on(events.CallbackQuery(data=b"show_pending"))
async def show_pending(event: Any) -> None:
    if not await is_admin(event.chat_id):
        return
    pending = get_data("pending_requests", {})
    if not pending:
        await safe_edit(event, "⏳ لا توجد طلبات انتظار.", [[Button.inline("🔙 رجوع", b"admin_panel")]])
        return
    lines = []
    for uid, info in list(pending.items())[:50]:
        lines.append(f"👤 {info.get('name', 'مستخدم')} | 🆔 `{uid}` | 📅 {info.get('date', '')}")
    await safe_edit(event, "⏳ **طلبات الاشتراك**\n\n" + "\n".join(lines), [[Button.inline("🔙 رجوع", b"admin_panel")]])


@client.on(events.CallbackQuery(data=b"upgrade"))
async def upgrade_member(event: Any) -> None:
    if not await is_admin(event.chat_id):
        return
    await set_input_state(event.chat_id, "admin_upgrade_user")
    await safe_edit(event, "➕ أرسل معرّف المستخدم الرقمي.", [[Button.inline("إلغاء", b"cancel")]])


@client.on(events.CallbackQuery(data=b"remove"))
async def remove_member(event: Any) -> None:
    if not await is_admin(event.chat_id):
        return
    await set_input_state(event.chat_id, "admin_remove_user")
    await safe_edit(event, "➖ أرسل معرّف المستخدم الرقمي لإزالة اشتراكه.", [[Button.inline("إلغاء", b"cancel")]])


@client.on(events.CallbackQuery(data=b"broadcast"))
async def broadcast(event: Any) -> None:
    if not await is_admin(event.chat_id):
        return
    await set_input_state(event.chat_id, "admin_broadcast")
    await safe_edit(event, "📢 أرسل نص الإذاعة الآن.", [[Button.inline("إلغاء", b"cancel")]])


async def broadcast_task(admin_id: int, text: str) -> None:
    sent = failed = 0
    for uid in get_data("users", {}):
        if not uid.isdigit():
            continue
        try:
            await client.send_message(int(uid), text)
            sent += 1
            await asyncio.sleep(0.5)
        except FloodWaitError as exc:
            await asyncio.sleep(exc.seconds)
            failed += 1
        except Exception:
            failed += 1
    await client.send_message(admin_id, f"✅ اكتملت الإذاعة.\n📨 أُرسل: {sent}\n⚠️ فشل: {failed}")


# ---------------------------------------------------------------------------
# معالج الإدخال الموحد: يمنع تضارب معالجات الرسائل المتداخلة في النسخة الأصلية.
# ---------------------------------------------------------------------------
@client.on(events.NewMessage(incoming=True))
async def handle_user_input(event: Any) -> None:
    if not event.is_private:
        return
    user_id = event.chat_id
    text = (event.raw_text or "").strip()
    if text.startswith("/"):
        if text.lower() == "/cancel":
            had_state = user_id in pending_inputs or user_id in login_contexts
            await clear_input_state(user_id, close_login=True)
            await respond(event, "✅ أُلغيت العملية." if had_state else "لا توجد عملية قيد التنفيذ.")
            if await check_subscription(user_id):
                await render_main(event, user_id, edit=False)
        return

    state = pending_inputs.get(user_id)
    if not state:
        # توجيه الرسائل غير المتعلقة بنماذج الإدخال إلى المشرف فقط.
        if ADMIN_ID and user_id != ADMIN_ID and text:
            try:
                await client.send_message(ADMIN_ID, f"📨 رسالة من المستخدم\n🆔 `{user_id}`\n💬 {text[:500]}")
            except Exception:
                logger.info("تعذر توجيه رسالة المستخدم للمشرف")
        return

    kind = state.get("kind")
    try:
        if kind == "add_phone":
            phone = clean_phone(text)
            if not phone:
                await respond(event, "⚠️ أرسل رقمًا دوليًا صحيحًا فقط، مثال: +966512345678")
                return
            if get_account(user_id, phone):
                await respond(event, "⚠️ هذا الحساب مضاف مسبقًا. أرسل رقمًا آخر أو /cancel.")
                return
            temp = TelegramClient(StringSession(), API_ID, API_HASH)
            await temp.connect()
            try:
                sent_code = await temp.send_code_request(phone)
            except Exception:
                await disconnect_quietly(temp)
                raise
            login_contexts[user_id] = {"client": temp, "phone": phone, "phone_code_hash": sent_code.phone_code_hash}
            await set_input_state(user_id, "add_code")
            await respond(event, "🔐 أُرسل رمز التحقق إلى تيليجرام. أرسله هنا دون مسافات.\nاستخدم /cancel للإلغاء.")
            return

        if kind == "add_code":
            context = login_contexts.get(user_id)
            if not context:
                await clear_input_state(user_id)
                await respond(event, "⚠️ انتهت جلسة التحقق. ابدأ بإضافة الحساب مجددًا.")
                return
            code = re.sub(r"\s+", "", text)
            try:
                await context["client"].sign_in(phone=context["phone"], code=code, phone_code_hash=context["phone_code_hash"])
            except PhoneCodeInvalidError:
                await respond(event, "❌ رمز التحقق غير صحيح. أعد إرساله أو /cancel.")
                return
            except PhoneCodeExpiredError:
                await clear_input_state(user_id, close_login=True)
                await respond(event, "⚠️ انتهت صلاحية الرمز. ابدأ بإضافة الحساب من جديد.")
                return
            except SessionPasswordNeededError:
                await set_input_state(user_id, "add_password")
                await respond(event, "🔐 الحساب محمي بالتحقق بخطوتين. أرسل كلمة المرور أو /cancel.")
                return
            await persist_logged_in_account(event, user_id)
            return

        if kind == "add_password":
            context = login_contexts.get(user_id)
            if not context:
                await clear_input_state(user_id)
                await respond(event, "⚠️ انتهت جلسة التحقق. ابدأ مجددًا.")
                return
            try:
                await context["client"].sign_in(password=text)
            except PasswordHashInvalidError:
                await respond(event, "❌ كلمة المرور غير صحيحة. أعد المحاولة أو /cancel.")
                return
            await persist_logged_in_account(event, user_id)
            return

        if kind == "set_post_message":
            phone = state["phone"]
            settings = get_account_settings(user_id, phone)
            settings["message"] = text
            save_account_settings(user_id, phone, settings)
            await clear_input_state(user_id)
            await respond(event, f"✅ حُفظت كليشة النشر للحساب +{phone}.")
            return

        if kind == "set_interval":
            try:
                interval = int(text)
            except ValueError:
                await respond(event, "⚠️ أرسل رقمًا صحيحًا بالثواني.")
                return
            interval = max(MIN_POST_INTERVAL, min(3600, interval))
            phone = state["phone"]
            settings = get_account_settings(user_id, phone)
            settings["interval"] = interval
            save_account_settings(user_id, phone, settings)
            await clear_input_state(user_id)
            await respond(event, f"✅ ضُبط الفاصل للحساب +{phone} إلى {interval} ثانية.")
            return

        if kind == "normal_message":
            await set_input_state(user_id, "normal_message_ready", message=text)
            await show_publish_account_choices(event, user_id, "normal_message_ready")
            return

        if kind == "turbo_message":
            await clear_input_state(user_id)
            await respond(event, "🔄 بدأت عملية النشر السريع. ستصلك النتيجة عند اكتمالها.")

            async def run_turbo() -> None:
                success = failed = 0
                for account in get_accounts(user_id)[:3]:
                    try:
                        ok, bad = await publish_once(user_id, account["phone"], text, limit=MAX_GROUPS_TURBO)
                        success += ok
                        failed += bad
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("فشل النشر السريع للحساب %s", account.get("phone"))
                        failed += 1
                detail = "\nℹ️ إذا كان الفشل كاملًا، تأكد أن الحساب عضو في المجموعات ولديه صلاحية إرسال الرسائل." if success == 0 else ""
                await client.send_message(user_id, f"⚡ اكتمل النشر السريع.\n📨 نجح: {success}\n⚠️ فشل: {failed}{detail}")

            start_task(scheduled_tasks, f"turbo:{user_id}:{time.time_ns()}", run_turbo(), f"turbo:{user_id}")
            return

        if kind == "schedule_message":
            await set_input_state(user_id, "schedule_delay", message=text)
            await respond(event, "⏱ أرسل عدد الدقائق حتى النشر (1–10080).")
            return

        if kind == "schedule_delay":
            try:
                minutes = int(text)
            except ValueError:
                await respond(event, "⚠️ أرسل عدد دقائق صحيحًا.")
                return
            if not 1 <= minutes <= 10080:
                await respond(event, "⚠️ أدخل قيمة بين 1 و10080 دقيقة.")
                return
            await set_input_state(user_id, "schedule_account_ready", message=state["message"], minutes=minutes)
            await show_publish_account_choices(event, user_id, "schedule_account_ready")
            return

        if kind == "join_links":
            links = [line.strip() for line in text.splitlines() if line.strip()]
            links = [link for link in links if "t.me/" in link or link.startswith("@")]
            if not links:
                await respond(event, "⚠️ لم أجد روابط تيليجرام صالحة. أرسل رابطًا واحدًا بكل سطر.")
                return
            await set_input_state(user_id, "join_wait", phone=state["phone"], links=links[:100])
            await respond(event, "⏱ أرسل وقت الانتظار بين المحاولات بالثواني (5–60).")
            return

        if kind == "join_wait":
            try:
                wait_seconds = int(text)
            except ValueError:
                await respond(event, "⚠️ أرسل رقمًا صحيحًا بالثواني.")
                return
            wait_seconds = max(5, min(60, wait_seconds))
            phone, links = state["phone"], state["links"]
            await clear_input_state(user_id)
            await respond(event, f"🔄 بدأت محاولة الانضمام إلى {len(links)} رابط. ستصلك النتيجة عند الانتهاء.")
            start_task(scheduled_tasks, f"join:{user_id}:{time.time_ns()}", join_groups_task(user_id, phone, links, wait_seconds), f"join:{user_id}:{phone}")
            return

        if kind == "set_reply_text":
            phone = state["phone"]
            settings = get_account_settings(user_id, phone)
            settings["auto_reply_text"] = text
            save_account_settings(user_id, phone, settings)
            await clear_input_state(user_id)
            await respond(event, f"✅ حُفظ نص الرد التلقائي للحساب +{phone}.")
            return

        if kind == "admin_approve_days":
            if not await is_admin(user_id):
                return
            try:
                days = int(text)
            except ValueError:
                await respond(event, "⚠️ أرسل عدد أيام صحيحًا.")
                return
            if not 1 <= days <= 3660:
                await respond(event, "⚠️ أدخل عددًا بين 1 و3660.")
                return
            target_id = int(state["target_id"])
            memberships = get_data("memberships", {})
            memberships[str(target_id)] = {"active": True, "expiry": (datetime.now() + timedelta(days=days)).timestamp()}
            save_data("memberships", memberships)
            pending = get_data("pending_requests", {})
            pending.pop(str(target_id), None)
            save_data("pending_requests", pending)
            await clear_input_state(user_id)
            try:
                await client.send_message(target_id, f"🎉 تم تفعيل اشتراكك لمدة {days} يومًا.")
            except Exception:
                logger.info("تعذر إخطار المستخدم %s بتفعيل الاشتراك", target_id)
            await respond(event, f"✅ فُعّل اشتراك `{target_id}` لمدة {days} يومًا.")
            return

        if kind == "admin_upgrade_user":
            if not await is_admin(user_id):
                return
            if not text.isdigit():
                await respond(event, "⚠️ أرسل معرّفًا رقميًا صحيحًا.")
                return
            await set_input_state(user_id, "admin_upgrade_days", target_id=int(text))
            await respond(event, "📅 أرسل عدد أيام الاشتراك (1–3660).")
            return

        if kind == "admin_upgrade_days":
            if not await is_admin(user_id):
                return
            try:
                days = int(text)
            except ValueError:
                await respond(event, "⚠️ أرسل عدد أيام صحيحًا.")
                return
            if not 1 <= days <= 3660:
                await respond(event, "⚠️ أدخل عددًا بين 1 و3660.")
                return
            target_id = int(state["target_id"])
            memberships = get_data("memberships", {})
            memberships[str(target_id)] = {"active": True, "expiry": (datetime.now() + timedelta(days=days)).timestamp()}
            save_data("memberships", memberships)
            await clear_input_state(user_id)
            await respond(event, f"✅ فُعّل اشتراك `{target_id}` لمدة {days} يومًا.")
            return

        if kind == "admin_remove_user":
            if not await is_admin(user_id):
                return
            if not text.isdigit():
                await respond(event, "⚠️ أرسل معرّفًا رقميًا صحيحًا.")
                return
            memberships = get_data("memberships", {})
            if memberships.pop(text, None) is None:
                await respond(event, f"⚠️ `{text}` ليس لديه اشتراك نشط.")
            else:
                save_data("memberships", memberships)
                await respond(event, f"✅ أُزيل اشتراك `{text}`.")
            await clear_input_state(user_id)
            return

        if kind == "admin_broadcast":
            if not await is_admin(user_id):
                return
            await clear_input_state(user_id)
            await respond(event, "🔄 بدأت الإذاعة. ستصلك النتيجة عند اكتمالها.")
            start_task(scheduled_tasks, f"broadcast:{time.time_ns()}", broadcast_task(user_id, text), "broadcast")
            return

        await clear_input_state(user_id, close_login=True)
        await respond(event, "⚠️ انتهت العملية الحالية. ابدأ مجددًا من القائمة.")
    except Exception as exc:
        logger.exception("فشل إدخال المستخدم في الحالة %s", kind)
        await respond(event, f"❌ {safe_error(exc)}")


async def persist_logged_in_account(event: Any, user_id: int) -> None:
    context = login_contexts.get(user_id)
    if not context:
        await respond(event, "⚠️ انتهت جلسة التحقق. ابدأ مجددًا.")
        return
    temp: TelegramClient = context["client"]
    phone = context["phone"]
    try:
        session_string = temp.session.save()
        users = get_data("users", {})
        user = users.get(str(user_id)) or {"accounts": [], "created_at": datetime.now().strftime("%d-%m-%Y %H:%M:%S")}
        if any(account.get("phone") == phone for account in user.get("accounts", [])):
            await respond(event, f"⚠️ الحساب +{phone} مضاف بالفعل.")
        else:
            user.setdefault("accounts", []).append({"phone": phone, "session": session_string})
            users[str(user_id)] = user
            save_data("users", users)
            save_account_settings(user_id, phone, get_account_settings(user_id, phone))
            await respond(event, f"✅ أُضيف الحساب +{phone} بنجاح.")
    finally:
        await clear_input_state(user_id, close_login=True)


# ---------------------------------------------------------------------------
# نقطة التشغيل
# ---------------------------------------------------------------------------
def validate_configuration() -> None:
    missing = []
    if API_ID <= 0:
        missing.append("TELEGRAM_API_ID")
    if not API_HASH:
        missing.append("TELEGRAM_API_HASH")
    if not BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if ADMIN_ID <= 0:
        missing.append("TELEGRAM_ADMIN_ID")
    if missing:
        raise RuntimeError("متغيرات البيئة المطلوبة غير مضبوطة: " + ", ".join(missing))


async def main() -> None:
    validate_configuration()
    init_db()
    health_state["started_at"] = datetime.now().isoformat(timespec="seconds")
    await client.start(bot_token=BOT_TOKEN)
    health_state["bot_connected"] = True
    await restore_background_tasks()
    logger.info("البوت يعمل الآن")
    try:
        await client.run_until_disconnected()
    finally:
        health_state["bot_connected"] = False
        for store in (post_tasks, auto_reply_tasks, scheduled_tasks):
            for task in list(store.values()):
                task.cancel()
        await client.disconnect()


if __name__ == "__main__":
    threading.Thread(target=run_health_server, name="health-server", daemon=True).start()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("أوقف المستخدم البوت")
    except Exception as exc:
        logger.critical("تعذر بدء البوت: %s", exc)
        raise
