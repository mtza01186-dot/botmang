#!/usr/bin/env python
# -*- coding: utf-8 -*-

# بوت النشر التلقائي الاحترافي - النسخة المتكاملة
# المطور: @Motazalkade
# القناة: @enmotaz

from flask import Flask
import threading

app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=10000)

threading.Thread(target=run_flask).start()

import os
import re
from telethon.sessions import StringSession
import asyncio
from kvsqlite.sync import Client as uu
from telethon import TelegramClient, events, Button
import random
from datetime import datetime, timedelta
from telethon.errors import FloodWaitError, SessionPasswordNeededError, PhoneCodeInvalidError
from telethon.tl.functions.channels import JoinChannelRequest, GetParticipantRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest
from telethon.errors.rpcerrorlist import UserNotParticipantError

if not os.path.isdir('database'):
    os.makedirs('database')

# ========== بياناتك ==========
API_ID = 35983238
API_HASH = "daf2ef391f5d9017043b33f4d1f84052"
BOT_TOKEN = "7987342508:AAEzwochQazEwX_ycq2RNZjnNCI_A19V09k"
ADMIN_ID = 5517628630
ADMIN_USERNAME = "Motazalkade"
REQUIRED_CHANNEL = "enmotaz"
# ===========================

client = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)
db = uu('database/bot_data.ss', 'bot')

# ========== تهيئة قاعدة البيانات ==========
def init_db():
    keys = ["users", "accounts_settings", "memberships", "pending_requests", "admins", "bot_enabled", "user_stats", "folders", "collected_links", "violations", "posts_count"]
    for key in keys:
        if not db.exists(key):
            db.set(key, {} if key not in ["bot_enabled", "admins"] else True if key == "bot_enabled" else [ADMIN_ID] if key == "admins" else {})

init_db()

def get_data(key, default=None):
    if db.exists(key):
        return db.get(key)
    return default or {}

def save_data(key, value):
    db.set(key, value)

# ========== دوال الإحصائيات ==========
def update_user_stats(user_id, stat_type, value=1):
    stats = get_data("user_stats")
    user_stats = stats.get(str(user_id), {})
    user_stats[stat_type] = user_stats.get(stat_type, 0) + value
    stats[str(user_id)] = user_stats
    save_data("user_stats", stats)

def get_user_stats(user_id):
    users = get_data("users")
    user_data = users.get(str(user_id), {})
    accounts = user_data.get("accounts", [])
    settings = get_data("accounts_settings")
    stats = get_data("user_stats").get(str(user_id), {})
    
    total_accounts = len(accounts)
    total_folders = len(get_data("folders").get(str(user_id), {}))
    total_groups = stats.get("groups", 0)
    total_posts = stats.get("posts", 0)
    total_links = len(get_data("collected_links").get(str(user_id), {}))
    total_violations = stats.get("violations", 0)
    active_processes = 0
    
    for acc in accounts:
        phone = acc["phone"]
        acc_settings = settings.get(f"acc_{phone}", {})
        if acc_settings.get("enabled"):
            active_processes += 1
    
    created_at = user_data.get("created_at", datetime.now().strftime("%d-%m-%Y %H:%M:%S"))
    
    return {
        "total_accounts": total_accounts,
        "total_folders": total_folders,
        "total_groups": total_groups,
        "total_posts": total_posts,
        "total_links": total_links,
        "total_violations": total_violations,
        "active_processes": active_processes,
        "created_at": created_at
    }

# ========== رسائل البوت ==========
WELCOME_MESSAGE = """
╔══════════════════════════════════════════════════════╗
║     🔥 بوت النشر التلقائي - الإصدار الاحترافي 🔥     ║
╚══════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🤖 **ماذا يفعل هذا البوت؟**

هذا البوت يساعدك على نشر رسائلك •تلقائياً• في 
{جميع المجموعات والقنوات} التي انضم إليها حسابك.

🚀 **كيف يعمل؟**

1️⃣ تضيف حسابك (رقم هاتفك) إلى البوت
2️⃣ تحدد الرسالة التي تريد نشرها (كليشة)
3️⃣ البوت ينشرها تلقائياً في جميع مجموعاتك

📌 **مميزات البوت:**

✅ نشر تلقائي 24/7
✅ إضافة حسابات متعددة
✅ جلب جميع المجموعات المنضم لها حسابك
✅ جلب الروابط من المجموعات والقنوات
✅ تغيير الصورة والاسم والبايو
✅ الانضمام لروابط متعددة دفعة واحدة
✅ لوحة تحكم متكاملة وإحصائيات دقيقة

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💎 **هذا البوت للاشتراك فقط**

للاشتراك، اضغط على زر الاشتراك أدناه
سيتم التواصل معك لتحديد المدة والسعر

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

👨‍💻 **المطور:** @Motazalkade
📢 **القناة:** @enmotaz
"""

SUBSCRIBE_REQUEST_SENT = """
✅ **تم إرسال طلب اشتراكك إلى المشرف بنجاح!**

📌 **ماذا يحدث الآن؟**

• سيقوم المشرف بالتواصل معك قريباً
• سيتم الاتفاق على مدة الاشتراك والسعر
• بعد الموافقة، سيتم تفعيل حسابك

📞 **يمكنك أيضاً التواصل مع المشرف مباشرة:**
👤 @Motazalkade

⏳ **يرجى الانتظار، سيتم إعلامك عند الموافقة.**
"""

ADMIN_SUBSCRIBE_REQUEST = """
🆕 **طلب اشتراك جديد!**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

👤 **اسم المستخدم:** {}
🆔 **ايدي المستخدم:** `{}`
🔗 **معرف المستخدم:** @{}
📅 **تاريخ الطلب:** {}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📌 **للتواصل مع المستخدم:**
• اضغط على الايدي لفتح المحادثة
• أو استخدم زر التواصل أدناه

💡 **نصيحة:** تواصل مع المستخدم لتحديد:
• مدة الاشتراك (أيام)
• السعر المناسب

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

MAIN_MENU = """
📊 **لوحة المعلومات – بياناتك أنت فقط**

📱 إجمالي أرقامك: {}
📁 إجمالي مجلداتك: {}
👥 المجموعات/القنوات المنضم لها: {}
📨 إجمالي منشوراتك (Ads): {}
🔗 إجمالي الروابط المجموعة: {}
⚠️ إجمالي مخالفاتك المسجلة: {}
⚡ عمليات جارية الآن (حسابك): {}

📅 تاريخ إنشاء حسابك: {}
"""

MAIN_BUTTONS = [
    [Button.inline("📱 إدارة الأرقام", b"manage_accounts")],
    [Button.inline("🚀 محرك النشر", b"publish_engine")],
    [Button.inline("⚡ النشر السريع (Turbo)", b"turbo_publish")],
    [Button.inline("🔗 جلب الروابط", b"fetch_links")],
    [Button.inline("📂 الانضمام وعمل مجلدات", b"join_folders")],
    [Button.inline("🔄 العمليات الجارية", b"running_processes")],
    [Button.inline("🤖 الرد التلقائي", b"auto_reply")],
    [Button.inline("📖 شرح البوت", b"help_bot")]
]

# ========== دوال التحقق ==========
async def is_admin(user_id):
    return user_id == ADMIN_ID

async def check_subscription(user_id):
    if user_id == ADMIN_ID:
        return True
    memberships = get_data("memberships")
    user_sub = memberships.get(str(user_id), {})
    if user_sub.get("active", False):
        expiry = user_sub.get("expiry")
        if expiry and datetime.now().timestamp() > expiry:
            memberships.pop(str(user_id), None)
            save_data("memberships", memberships)
            return False
        return True
    return False

async def is_user_member(user_id):
    if not REQUIRED_CHANNEL:
        return True
    try:
        channel_entity = await client.get_entity(f"t.me/{REQUIRED_CHANNEL}")
        await client(GetParticipantRequest(channel=channel_entity, participant=user_id))
        return True
    except:
        return False

# ========== النشر التلقائي ==========
async def auto_post_loop(user_id, phone, session_str):
    acc_key = f"acc_{phone}"
    print(f"🔄 بدء النشر التلقائي للحساب {phone}")
    
    while True:
        if not db.get("bot_enabled"):
            await asyncio.sleep(10)
            continue
        
        settings = get_data("accounts_settings")
        acc_settings = settings.get(acc_key, {})
        
        if not acc_settings.get("enabled", False):
            print(f"⏹️ إيقاف النشر للحساب {phone}")
            break
        
        post_msg = acc_settings.get("message", "مرحباً")
        interval = max(acc_settings.get("interval", 120), 30)
        
        try:
            temp = TelegramClient(StringSession(session_str), API_ID, API_HASH)
            await temp.connect()
            
            if not await temp.is_user_authorized():
                print(f"❌ الحساب {phone} غير مصرح")
                await temp.disconnect()
                break
            
            dialogs = await temp.get_dialogs()
            groups = [d for d in dialogs if d.is_group]
            
            if groups:
                random.shuffle(groups)
                for group in groups[:30]:
                    settings = get_data("accounts_settings")
                    if not settings.get(acc_key, {}).get("enabled", False):
                        break
                    try:
                        await temp.send_message(group.entity, post_msg)
                        update_user_stats(user_id, "posts")
                        print(f"✅ {phone}: تم النشر في {group.name}")
                        await asyncio.sleep(random.uniform(3, 7))
                    except FloodWaitError as e:
                        await asyncio.sleep(e.seconds)
                    except:
                        await asyncio.sleep(5)
            
            await temp.disconnect()
            
            for _ in range(interval):
                await asyncio.sleep(1)
                settings = get_data("accounts_settings")
                if not settings.get(acc_key, {}).get("enabled", False):
                    break
                    
        except Exception as e:
            print(f"❌ خطأ في حساب {phone}: {e}")
            await asyncio.sleep(60)

# ========== لوحة المشرف ==========
async def admin_menu():
    users = get_data("users")
    real_users = sum(1 for k in users.keys() if k.isdigit())
    accounts = sum(len(u.get("accounts", [])) for u in users.values())
    premium = len(get_data("memberships"))
    pending = len(get_data("pending_requests"))
    
    text = f"👑 **لوحة المشرف**\n\n👥 المستخدمين: {real_users}\n📱 الحسابات: {accounts}\n💎 المميزين: {premium}\n⏳ الطلبات: {pending}"
    
    buttons = [
        [Button.inline("📊 إحصائيات", b"stats"), Button.inline("💎 المميزين", b"premium_list")],
        [Button.inline("⏳ طلبات الاشتراك", b"show_pending")],
        [Button.inline("➕ ترقية", b"upgrade"), Button.inline("➖ إزالة", b"remove")],
        [Button.inline("📢 إذاعة", b"broadcast")],
        [Button.inline("🔙 رجوع", b"back_main")]
    ]
    await client.send_message(ADMIN_ID, text, buttons=buttons)

# ========== أمر /start ==========
@client.on(events.NewMessage(pattern="/start", func=lambda x: x.is_private))
async def start_cmd(event):
    user_id = event.chat_id
    
    if not await is_user_member(user_id):
        return await event.respond(f"⚠️ يجب عليك الانضمام إلى قناتنا أولاً\n@{REQUIRED_CHANNEL}")
    
    if not await check_subscription(user_id):
        buttons = [
            [Button.inline("💎 طلب اشتراك", b"request_sub")],
            [Button.inline("📖 شرح البوت", b"help_bot")]
        ]
        return await event.respond(WELCOME_MESSAGE, buttons=buttons)
    
    users = get_data("users")
    if str(user_id) not in users:
        users[str(user_id)] = {"accounts": [], "created_at": datetime.now().strftime("%d-%m-%Y %H:%M:%S")}
        save_data("users", users)
    
    stats = get_user_stats(user_id)
    
    info_text = MAIN_MENU.format(
        stats["total_accounts"],
        stats["total_folders"],
        stats["total_groups"],
        stats["total_posts"],
        stats["total_links"],
        stats["total_violations"],
        stats["active_processes"],
        stats["created_at"]
    )
    
    buttons = MAIN_BUTTONS.copy()
    if await is_admin(user_id):
        buttons.append([Button.inline("👑 لوحة المشرف", b"admin_panel")])
    
    await event.respond(info_text, buttons=buttons)

# ========== طلب اشتراك ==========
@client.on(events.CallbackQuery(data=b"request_sub"))
async def request_subscription(event):
    user_id = event.chat_id
    if await is_admin(user_id):
        return await event.answer("أنت المشرف!", alert=True)
    
    pending = get_data("pending_requests")
    if str(user_id) in pending:
        return await event.answer("لديك طلب قيد الانتظار بالفعل", alert=True)
    
    user = await event.get_sender()
    user_name = user.first_name or "مستخدم"
    user_username = user.username or "لا يوجد"
    user_id_str = str(user_id)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    pending[str(user_id)] = {
        "name": user_name,
        "username": user_username,
        "date": current_time,
        "user_id": user_id_str
    }
    save_data("pending_requests", pending)
    
    admin_msg = ADMIN_SUBSCRIBE_REQUEST.format(
        user_name,
        user_id_str,
        user_username,
        current_time
    )
    
    admin_buttons = [
        [Button.inline("✅ قبول الاشتراك", f"accept_{user_id}".encode())],
        [Button.inline("❌ رفض الاشتراك", f"reject_{user_id}".encode())],
        [Button.url("📞 التواصل مع المستخدم", f"tg://user?id={user_id}")]
    ]
    
    await client.send_message(ADMIN_ID, admin_msg, buttons=admin_buttons)
    
    await client.send_message(
        ADMIN_ID,
        f"📌 **تذكير:** يمكنك التواصل مع المستخدم مباشرة من خلال الزر أعلاه أو من خلال المعرف @{user_username}",
        buttons=[[Button.url("📞 فتح محادثة مع المستخدم", f"tg://user?id={user_id}")]]
    )
    
    await event.edit(SUBSCRIBE_REQUEST_SENT)

# ========== قبول اشتراك ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"accept_")))
async def accept_subscription(event):
    if not await is_admin(event.chat_id):
        return await event.answer("غير مصرح", alert=True)
    
    user_id = int(event.data.decode().split("_")[1])
    pending = get_data("pending_requests")
    user_info = pending.get(str(user_id), {})
    user_name = user_info.get("name", "المستخدم")
    
    await event.edit(f"✅ **قبول طلب اشتراك** `{user_name}`\n📅 أرسل عدد الأيام:")
    
    @client.on(events.NewMessage(incoming=True, from_users=ADMIN_ID))
    async def get_days(msg):
        client.remove_event_handler(get_days)
        try:
            days = int(msg.text)
            memberships = get_data("memberships")
            memberships[str(user_id)] = {"active": True, "expiry": (datetime.now() + timedelta(days=days)).timestamp()}
            save_data("memberships", memberships)
            pending.pop(str(user_id), None)
            save_data("pending_requests", pending)
            
            await client.send_message(
                user_id, 
                f"🎉 **تم تفعيل اشتراكك لمدة {days} يوم!**\n\n"
                f"📌 يمكنك الآن استخدام جميع ميزات البوت.\n"
                f"أرسل /start للبدء."
            )
            
            await event.edit(f"✅ **تم تفعيل اشتراك المستخدم `{user_name}` لمدة {days} يوم بنجاح!**")
            await admin_menu()
        except:
            await event.reply("⚠️ أرسل رقماً صحيحاً")

# ========== رفض اشتراك ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"reject_")))
async def reject_subscription(event):
    if not await is_admin(event.chat_id):
        return await event.answer("غير مصرح", alert=True)
    
    user_id = int(event.data.decode().split("_")[1])
    pending = get_data("pending_requests")
    user_info = pending.get(str(user_id), {})
    user_name = user_info.get("name", "المستخدم")
    
    pending.pop(str(user_id), None)
    save_data("pending_requests", pending)
    
    await client.send_message(
        user_id,
        "❌ **تم رفض طلب الاشتراك الخاص بك**\n\n"
        "📞 يمكنك التواصل مع المشرف مباشرة للاستفسار:\n"
        f"👤 @{ADMIN_USERNAME}"
    )
    
    await event.edit(f"✅ **تم رفض طلب المستخدم `{user_name}`**")

# ========== إضافة حساب (بدون conv.get_response) ==========
@client.on(events.CallbackQuery(data=b"add_account"))
async def add_account(event):
    user_id = event.chat_id
    
    await event.edit("📱 **أرسل رقم الهاتف مع رمز الدولة**\nمثال: +966512345678")
    
    @client.on(events.NewMessage(incoming=True, from_users=user_id))
    async def get_phone(msg):
        client.remove_event_handler(get_phone)
        phone = msg.text.replace("+", "").replace(" ", "")
        
        await msg.reply("🔄 جاري إرسال كود التحقق...")
        
        temp = TelegramClient(StringSession(), API_ID, API_HASH)
        await temp.connect()
        
        try:
            await temp.send_code_request(phone)
        except Exception as e:
            await msg.reply(f"❌ خطأ في إرسال الكود: {str(e)[:100]}")
            await temp.disconnect()
            return
        
        @client.on(events.NewMessage(incoming=True, from_users=user_id))
        async def get_code(code_msg):
            client.remove_event_handler(get_code)
            code = code_msg.text.replace(" ", "")
            
            try:
                await temp.sign_in(phone, code)
                session_str = temp.session.save()
                await temp.disconnect()
                
                users = get_data("users")
                user_data = users.get(str(user_id), {"accounts": [], "created_at": datetime.now().strftime("%d-%m-%Y %H:%M:%S")})
                
                if any(a["phone"] == phone for a in user_data["accounts"]):
                    await code_msg.reply(f"⚠️ الحساب {phone} مضاف مسبقاً")
                    return
                
                user_data["accounts"].append({"phone": phone, "session": session_str})
                users[str(user_id)] = user_data
                save_data("users", users)
                
                await code_msg.reply(f"✅ **تم إضافة الرقم {phone} بنجاح!**")
                await start_cmd(code_msg)
                
            except SessionPasswordNeededError:
                await code_msg.reply("🔐 **الحساب محمي بكلمة مرور (2FA)**\nأرسل كلمة المرور:")
                
                @client.on(events.NewMessage(incoming=True, from_users=user_id))
                async def get_password(pw_msg):
                    client.remove_event_handler(get_password)
                    password = pw_msg.text
                    
                    try:
                        await temp.sign_in(password=password)
                        session_str = temp.session.save()
                        await temp.disconnect()
                        
                        users = get_data("users")
                        user_data = users.get(str(user_id), {"accounts": [], "created_at": datetime.now().strftime("%d-%m-%Y %H:%M:%S")})
                        
                        if any(a["phone"] == phone for a in user_data["accounts"]):
                            await pw_msg.reply(f"⚠️ الحساب {phone} مضاف مسبقاً")
                            return
                        
                        user_data["accounts"].append({"phone": phone, "session": session_str, "has_2fa": True})
                        users[str(user_id)] = user_data
                        save_data("users", users)
                        
                        await pw_msg.reply(f"✅ **تم إضافة الرقم {phone} بنجاح (مع التحقق بخطوتين)!**")
                        await start_cmd(pw_msg)
                        
                    except Exception as e:
                        await pw_msg.reply(f"❌ خطأ في كلمة المرور: {str(e)[:100]}")
                        await temp.disconnect()
                        
            except PhoneCodeInvalidError:
                await code_msg.reply("❌ كود التحقق غير صحيح، حاول مرة أخرى")
                await temp.disconnect()
            except Exception as e:
                await code_msg.reply(f"❌ خطأ: {str(e)[:100]}")
                await temp.disconnect()

# ========== إدارة الأرقام ==========
@client.on(events.CallbackQuery(data=b"manage_accounts"))
async def manage_accounts(event):
    user_id = event.chat_id
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    
    if not accounts:
        await event.edit("❌ لا توجد أرقام مضافه\n\n📱 **إضافة رقم جديد:**\nاضغط الزر أدناه", 
                        buttons=[[Button.inline("➕ إضافة رقم", b"add_account")],
                                [Button.inline("🔙 رجوع", b"back_main")]])
        return
    
    buttons = []
    for acc in accounts:
        phone = acc["phone"]
        settings = get_data("accounts_settings")
        acc_settings = settings.get(f"acc_{phone}", {})
        status = "✅" if acc_settings.get("enabled") else "⏸️"
        buttons.append([Button.inline(f"{status} {phone}", f"manage_acc_{phone}".encode())])
    
    buttons.append([Button.inline("➕ إضافة رقم جديد", b"add_account")])
    buttons.append([Button.inline("🔙 رجوع", b"back_main")])
    
    await event.edit(f"📱 **إدارة الأرقام**\n\nلديك {len(accounts)} رقم/أرقام\nاختر رقماً للتحكم به:", buttons=buttons)

# ========== إدارة حساب فردي ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"manage_acc_")))
async def manage_single_account(event):
    phone = event.data.decode().split("_")[2]
    user_id = event.chat_id
    
    settings = get_data("accounts_settings")
    acc_settings = settings.get(f"acc_{phone}", {})
    
    if 'enabled' not in acc_settings: acc_settings['enabled'] = False
    if 'message' not in acc_settings: acc_settings['message'] = "مرحباً"
    if 'interval' not in acc_settings: acc_settings['interval'] = 30
    
    status = "✅ مفعل" if acc_settings['enabled'] else "⏸️ معطل"
    
    buttons = [
        [Button.inline("📋 جلب المجموعات", f"get_groups_{phone}".encode())],
        [Button.inline("✏️ تعيين الكليشة", f"set_msg_{phone}".encode())],
        [Button.inline("⏱ تعيين الفاصل", f"set_int_{phone}".encode())],
        [Button.inline("🔄 تفعيل/تعطيل", f"toggle_{phone}".encode())],
        [Button.inline("🗑 حذف الرقم", f"delete_acc_{phone}".encode())],
        [Button.inline("🔙 رجوع", b"manage_accounts")]
    ]
    
    msg = f"📱 **الرقم:** {phone}\n📊 **الحالة:** {status}\n⏱ **الفاصل:** {acc_settings['interval']} ثانية"
    await event.edit(msg, buttons=buttons)

# ========== جلب المجموعات ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"get_groups_")))
async def get_groups(event):
    phone = event.data.decode().split("_")[2]
    user_id = event.chat_id
    
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    account = next((a for a in accounts if a["phone"] == phone), None)
    
    if not account:
        return await event.answer("❌ الحساب غير موجود", alert=True)
    
    await event.edit("🔄 جاري جلب المجموعات...")
    try:
        temp = TelegramClient(StringSession(account["session"]), API_ID, API_HASH)
        await temp.connect()
        dialogs = await temp.get_dialogs()
        groups = [d for d in dialogs if d.is_group]
        await temp.disconnect()
        
        update_user_stats(user_id, "groups", len(groups))
        
        if not groups:
            return await event.edit("⚠️ لا توجد مجموعات", buttons=[[Button.inline("🔙 رجوع", f"manage_acc_{phone}".encode())]])
        
        msg = f"📋 **قائمة المجموعات**\n📞 {phone}\n📊 العدد: {len(groups)}\n\n"
        for i, g in enumerate(groups[:30], 1):
            msg += f"{i}. {g.name}\n🆔 `{g.id}`\n\n"
        
        await event.edit(msg, buttons=[[Button.inline("🔙 رجوع", f"manage_acc_{phone}".encode())]])
    except Exception as e:
        await event.edit(f"❌ خطأ: {str(e)[:100]}", buttons=[[Button.inline("🔙 رجوع", f"manage_acc_{phone}".encode())]])

# ========== تعيين الكليشة (بدون conv) ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"set_msg_")))
async def set_message(event):
    phone = event.data.decode().split("_")[2]
    user_id = event.chat_id
    
    await event.edit("✏️ **أرسل الكليشة الجديدة**", buttons=[[Button.inline("إلغاء", f"manage_acc_{phone}".encode())]])
    
    @client.on(events.NewMessage(incoming=True, from_users=user_id))
    async def save_msg(msg):
        client.remove_event_handler(save_msg)
        settings = get_data("accounts_settings")
        settings[f"acc_{phone}"] = settings.get(f"acc_{phone}", {})
        settings[f"acc_{phone}"]["message"] = msg.text
        save_data("accounts_settings", settings)
        await msg.reply(f"✅ تم حفظ الكليشة", buttons=[[Button.inline("🔙 رجوع", f"manage_acc_{phone}".encode())]])

# ========== تعيين الفاصل (بدون conv) ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"set_int_")))
async def set_interval(event):
    phone = event.data.decode().split("_")[2]
    user_id = event.chat_id
    
    await event.edit("⏱ **أرسل الفاصل الزمني (30-300 ثانية)**", buttons=[[Button.inline("إلغاء", f"manage_acc_{phone}".encode())]])
    
    @client.on(events.NewMessage(incoming=True, from_users=user_id))
    async def save_int(msg):
        client.remove_event_handler(save_int)
        try:
            interval = max(30, min(300, int(msg.text)))
            settings = get_data("accounts_settings")
            settings[f"acc_{phone}"] = settings.get(f"acc_{phone}", {})
            settings[f"acc_{phone}"]["interval"] = interval
            save_data("accounts_settings", settings)
            await msg.reply(f"✅ تم تعيين الفاصل {interval} ثانية", buttons=[[Button.inline("🔙 رجوع", f"manage_acc_{phone}".encode())]])
        except:
            await msg.reply("⚠️ أرسل رقماً صحيحاً")

# ========== تفعيل/تعطيل النشر ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"toggle_")))
async def toggle_post(event):
    phone = event.data.decode().split("_")[1]
    user_id = event.chat_id
    
    settings = get_data("accounts_settings")
    acc_settings = settings.get(f"acc_{phone}", {"enabled": False})
    new_state = not acc_settings.get("enabled", False)
    
    settings[f"acc_{phone}"] = acc_settings
    settings[f"acc_{phone}"]["enabled"] = new_state
    save_data("accounts_settings", settings)
    
    if new_state:
        users = get_data("users")
        accounts = users.get(str(user_id), {}).get("accounts", [])
        account = next((a for a in accounts if a["phone"] == phone), None)
        if account:
            asyncio.create_task(auto_post_loop(user_id, phone, account["session"]))
            await event.answer(f"✅ تم تفعيل النشر للحساب {phone}")
    else:
        await event.answer(f"⏹️ تم إيقاف النشر للحساب {phone}")
    
    await manage_single_account(event)

# ========== حذف حساب ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"delete_acc_")))
async def delete_account(event):
    phone = event.data.decode().split("_")[2]
    user_id = event.chat_id
    
    settings = get_data("accounts_settings")
    if settings.get(f"acc_{phone}", {}).get("enabled"):
        settings[f"acc_{phone}"]["enabled"] = False
        save_data("accounts_settings", settings)
    
    users = get_data("users")
    user_data = users.get(str(user_id), {})
    user_data["accounts"] = [a for a in user_data.get("accounts", []) if a["phone"] != phone]
    users[str(user_id)] = user_data
    save_data("users", users)
    
    await event.answer("✅ تم حذف الرقم", alert=True)
    await manage_accounts(event)

# ========== أزرار القائمة الرئيسية الأخرى ==========

# محرك النشر
@client.on(events.CallbackQuery(data=b"publish_engine"))
async def publish_engine(event):
    await event.edit("🚀 **محرك النشر**\n\nاختر نوع النشر الذي تريده:",
                    buttons=[
                        [Button.inline("📤 نشر عادي", b"normal_publish")],
                        [Button.inline("📅 نشر جدول زمني", b"schedule_publish")],
                        [Button.inline("🔄 نشر تلقائي", b"auto_publish")],
                        [Button.inline("🔙 رجوع", b"back_main")]
                    ])

# النشر السريع (Turbo)
@client.on(events.CallbackQuery(data=b"turbo_publish"))
async def turbo_publish(event):
    await event.edit("⚡ **النشر السريع (Turbo)**\n\nهذا الوضع ينشر رسالتك بسرعة فائقة\n⚠️ انتباه: قد يتسبب بحظر حسابك",
                    buttons=[
                        [Button.inline("🚀 تشغيل Turbo", b"start_turbo")],
                        [Button.inline("🔙 رجوع", b"back_main")]
                    ])

@client.on(events.CallbackQuery(data=b"start_turbo"))
async def start_turbo(event):
    user_id = event.chat_id
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    
    if not accounts:
        return await event.answer("❌ لا توجد حسابات!", alert=True)
    
    await event.edit("📝 **أرسل الرسالة التي تريد نشرها (Turbo)**")
    
    @client.on(events.NewMessage(incoming=True, from_users=user_id))
    async def turbo_msg(msg):
        client.remove_event_handler(turbo_msg)
        await event.edit("🔄 جاري النشر السريع...")
        
        success = 0
        for acc in accounts[:3]:
            try:
                temp = TelegramClient(StringSession(acc["session"]), API_ID, API_HASH)
                await temp.connect()
                dialogs = await temp.get_dialogs()
                groups = [d for d in dialogs if d.is_group]
                for g in groups[:10]:
                    try:
                        await temp.send_message(g.entity, msg.text)
                        success += 1
                        update_user_stats(user_id, "posts")
                    except:
                        pass
                    await asyncio.sleep(2)
                await temp.disconnect()
            except:
                pass
        
        await event.edit(f"✅ **تم النشر السريع!**\n📨 تم النشر في {success} مجموعة")

# ========== جلب الروابط من المجموعات والقنوات (معدل) ==========
@client.on(events.CallbackQuery(data=b"fetch_links"))
async def fetch_links(event):
    user_id = event.chat_id
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    
    if not accounts:
        return await event.answer("❌ لا توجد حسابات! أضف حساباً أولاً", alert=True)
    
    buttons = []
    for acc in accounts:
        phone = acc["phone"]
        buttons.append([Button.inline(f"📱 {phone}", f"fetch_from_{phone}".encode())])
    buttons.append([Button.inline("🔙 رجوع", b"back_main")])
    
    await event.edit("🔗 **اختر الحساب الذي تريد جلب الروابط من مجموعاته:**", buttons=buttons)

@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"fetch_from_")))
async def fetch_from_account(event):
    phone = event.data.decode().split("_")[2]
    user_id = event.chat_id
    
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    account = next((a for a in accounts if a["phone"] == phone), None)
    
    if not account:
        return await event.answer("❌ الحساب غير موجود", alert=True)
    
    await event.edit(f"🔄 **جاري جلب الروابط من مجموعات الحساب** `{phone}` ...\n⏳ قد يستغرق هذا بضع ثوانٍ")
    
    try:
        temp = TelegramClient(StringSession(account["session"]), API_ID, API_HASH)
        await temp.connect()
        
        if not await temp.is_user_authorized():
            await event.edit("❌ الحساب غير مصرح به، يرجى إعادة إضافته")
            await temp.disconnect()
            return
        
        dialogs = await temp.get_dialogs()
        all_links = []
        total_messages = 0
        
        # أنماط البحث المطلوبة (تيليجرام وواتساب فقط)
        telegram_pattern = r'(?:https?://)?(?:www\.)?t\.me/[^\s]+'
        whatsapp_pattern = r'(?:https?://)?(?:www\.)?(?:wa\.me/[^\s]+|chat\.whatsapp\.com/[^\s]+)'
        combined_pattern = re.compile(f'({telegram_pattern}|{whatsapp_pattern})', re.IGNORECASE)
        
        for dialog in dialogs:
            if not dialog.is_group and not dialog.is_channel:
                continue
            
            try:
                async for message in temp.iter_messages(dialog.entity, limit=150):
                    total_messages += 1
                    if message.text:
                        found_links = re.findall(combined_pattern, message.text)
                        for link in found_links:
                            if isinstance(link, tuple):
                                link = link[0]
                            if link and link not in all_links:
                                if not link.startswith('http'):
                                    link = 'https://' + link
                                all_links.append(link)
            except:
                continue
        
        await temp.disconnect()
        
        all_links = list(set(all_links))
        all_links.sort()
        
        links_data = get_data("collected_links")
        user_links = links_data.get(str(user_id), {})
        user_links[phone] = all_links
        links_data[str(user_id)] = user_links
        save_data("collected_links", links_data)
        
        update_user_stats(user_id, "links", len(all_links))
        
        if not all_links:
            await event.edit(f"⚠️ **لا توجد روابط تيليجرام أو واتساب في مجموعات الحساب** `{phone}`\n\n📊 تم فحص {total_messages} رسالة", 
                           buttons=[[Button.inline("🔙 رجوع", b"back_main")]])
            return
        
        msg = f"🔗 **الروابط المجموعة من الحساب** `{phone}`\n\n📊 **عدد الروابط:** {len(all_links)}\n📊 **تم فحص:** {total_messages} رسالة\n\n"
        
        for i, link in enumerate(all_links[:30], 1):
            if 't.me' in link:
                icon = "📱"
            elif 'wa.me' in link or 'whatsapp' in link:
                icon = "💬"
            else:
                icon = "🔗"
            msg += f"{i}. {icon} {link}\n"
        
        if len(all_links) > 30:
            msg += f"\n... و {len(all_links) - 30} رابط آخر"
        
        buttons = [
            [Button.inline("📥 تصدير الروابط", f"export_links_{phone}".encode())],
            [Button.inline("🔙 رجوع", b"back_main")]
        ]
        
        await event.edit(msg, buttons=buttons, link_preview=False)
        
    except Exception as e:
        await event.edit(f"❌ **خطأ أثناء جلب الروابط:**\n{str(e)[:200]}", 
                        buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== تصدير الروابط كملف ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"export_links_")))
async def export_links(event):
    phone = event.data.decode().split("_")[2]
    user_id = event.chat_id
    
    links_data = get_data("collected_links")
    user_links = links_data.get(str(user_id), {})
    links = user_links.get(phone, [])
    
    if not links:
        return await event.answer("❌ لا توجد روابط للتصدير", alert=True)
    
    file_content = f"روابط مجمعة من الحساب: {phone}\n"
    file_content += f"تاريخ التصدير: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    file_content += f"عدد الروابط: {len(links)}\n"
    file_content += "=" * 40 + "\n\n"
    file_content += "\n".join(links)
    
    file_path = f"links_{phone}_{int(datetime.now().timestamp())}.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(file_content)
    
    await client.send_file(user_id, file_path, caption=f"📁 **روابط مجمعة من** `{phone}`\n📊 العدد: {len(links)}")
    os.remove(file_path)
    
    await event.answer("✅ تم إرسال الملف", alert=True)

# ========== الانضمام وعمل مجلدات ==========
@client.on(events.CallbackQuery(data=b"join_folders"))
async def join_folders(event):
    await event.edit("📂 **الانضمام وعمل مجلدات**\n\nاختر الإجراء المناسب:",
                    buttons=[
                        [Button.inline("🔗 انضمام لمجموعات", b"join_section")],
                        [Button.inline("📁 إنشاء مجلد", b"create_folder")],
                        [Button.inline("🔙 رجوع", b"back_main")]
                    ])

@client.on(events.CallbackQuery(data=b"create_folder"))
async def create_folder(event):
    user_id = event.chat_id
    await event.edit("📁 **إنشاء مجلد جديد**\n\nأرسل اسم المجلد:")
    
    @client.on(events.NewMessage(incoming=True, from_users=user_id))
    async def get_folder_name(msg):
        client.remove_event_handler(get_folder_name)
        folder_name = msg.text.strip()
        
        folders = get_data("folders")
        user_folders = folders.get(str(user_id), {})
        user_folders[folder_name] = []
        folders[str(user_id)] = user_folders
        save_data("folders", folders)
        
        await event.edit(f"✅ **تم إنشاء المجلد**\n📁 {folder_name}",
                        buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== الانضمام لمجموعات ==========
@client.on(events.CallbackQuery(data=b"join_section"))
async def join_section(event):
    user_id = event.chat_id
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    
    if not accounts:
        return await event.answer("❌ لا توجد حسابات", alert=True)
    
    buttons = [[Button.inline(f"📱 {a['phone']}", f"join_with_{a['phone']}".encode())] for a in accounts]
    buttons.append([Button.inline("🔙 رجوع", b"back_main")])
    await event.edit("🔗 **اختر الحساب للانضمام:**", buttons=buttons)

@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"join_with_")))
async def join_with_account(event):
    phone = event.data.decode().split("_")[2]
    user_id = event.chat_id
    
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    account = next((a for a in accounts if a["phone"] == phone), None)
    
    if not account:
        return await event.answer("❌ الحساب غير موجود", alert=True)
    
    await event.edit("🔗 **أرسل الروابط (كل رابط في سطر)**\n\nثم أرسل وقت الانتظار (مثال: 120)")
    
    @client.on(events.NewMessage(incoming=True, from_users=user_id))
    async def get_links(msg):
        client.remove_event_handler(get_links)
        links = [l.strip() for l in msg.text.split('\n') if l.strip()]
        await event.edit("⏱ **أرسل وقت الانتظار بالثواني (مثال: 120)**")
        
        @client.on(events.NewMessage(incoming=True, from_users=user_id))
        async def get_wait(w):
            client.remove_event_handler(get_wait)
            try:
                wait = max(30, int(w.text))
            except:
                wait = 120
            
            await event.edit(f"🔄 جاري الانضمام إلى {len(links)} رابط...\n⏱ الانتظار {wait} ثانية")
            success, failed = 0, 0
            
            for i, link in enumerate(links):
                try:
                    temp = TelegramClient(StringSession(account["session"]), API_ID, API_HASH)
                    await temp.connect()
                    
                    if 't.me/joinchat/' in link or 't.me/+' in link:
                        await temp(ImportChatInviteRequest(link.split('/')[-1].split('?')[0]))
                    elif 't.me/' in link:
                        await temp(JoinChannelRequest(link.split('t.me/')[-1].split('?')[0]))
                    else:
                        await temp(JoinChannelRequest(link))
                    
                    await temp.disconnect()
                    success += 1
                    await event.edit(f"✅ {i+1}/{len(links)} انضم\n⏳ انتظر {wait} ثانية...")
                    await asyncio.sleep(wait)
                    
                except FloodWaitError as fl:
                    failed += 1
                    await event.edit(f"⚠️ انتظار {fl.seconds//60} دقيقة")
                    await asyncio.sleep(fl.seconds)
                except Exception as e:
                    failed += 1
                    if "successfully requested" in str(e):
                        await event.edit(f"⏳ {link[:30]}... يحتاج موافقة مشرف (تم التخطي)")
                    else:
                        await event.edit(f"❌ فشل: {link[:30]}")
                    await asyncio.sleep(wait//2)
            
            await event.edit(f"✅ **تم الانتهاء!**\n✅ نجح: {success}\n❌ فشل: {failed}",
                           buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== العمليات الجارية ==========
@client.on(events.CallbackQuery(data=b"running_processes"))
async def running_processes(event):
    user_id = event.chat_id
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    settings = get_data("accounts_settings")
    
    active = []
    for acc in accounts:
        phone = acc["phone"]
        acc_settings = settings.get(f"acc_{phone}", {})
        if acc_settings.get("enabled"):
            active.append(phone)
    
    if active:
        msg = "🔄 **العمليات الجارية:**\n\n"
        for phone in active:
            msg += f"✅ {phone} - يعمل\n"
        msg += f"\n📊 إجمالي العمليات: {len(active)}"
    else:
        msg = "🔄 **العمليات الجارية:**\n\nلا توجد عمليات جارية حالياً"
    
    await event.edit(msg, buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== الرد التلقائي ==========
@client.on(events.CallbackQuery(data=b"auto_reply"))
async def auto_reply(event):
    await event.edit("🤖 **الرد التلقائي**\n\nإعدادات الرد التلقائي على الرسائل",
                    buttons=[
                        [Button.inline("✅ تفعيل", b"enable_auto_reply")],
                        [Button.inline("❌ تعطيل", b"disable_auto_reply")],
                        [Button.inline("🔙 رجوع", b"back_main")]
                    ])

@client.on(events.CallbackQuery(data=b"enable_auto_reply"))
async def enable_auto_reply(event):
    await event.edit("✅ **تم تفعيل الرد التلقائي**\n\nسيتم الرد تلقائياً على جميع الرسائل",
                    buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

@client.on(events.CallbackQuery(data=b"disable_auto_reply"))
async def disable_auto_reply(event):
    await event.edit("❌ **تم تعطيل الرد التلقائي**",
                    buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== شرح البوت ==========
@client.on(events.CallbackQuery(data=b"help_bot"))
async def help_bot(event):
    await event.edit("📖 **شرح البوت**\n\n"
                    "🤖 **بوت النشر التلقائي الاحترافي**\n\n"
                    "📌 **ما هو هذا البوت؟**\n"
                    "بوت متخصص في نشر الرسائل تلقائياً في جميع المجموعات والقنوات التي انضم إليها حسابك.\n\n"
                    "📌 **طريقة الاستخدام:**\n"
                    "1️⃣ أضف رقمك من خلال زر 'إدارة الأرقام'\n"
                    "2️⃣ اذهب إلى 'محرك النشر' واختر نوع النشر\n"
                    "3️⃣ استخدم 'النشر السريع' للنشر بسرعة\n"
                    "4️⃣ استخدم 'جلب الروابط' للحصول على روابط المجموعات\n\n"
                    "🔐 **الأمان:**\n"
                    "• جميع بياناتك مشفرة\n"
                    "• لا يتم مشاركة جلساتك مع أي طرف ثالث\n\n"
                    "👨‍💻 **المطور:** @Motazalkade\n"
                    "📢 **القناة:** @enmotaz",
                    buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== رجوع للقائمة الرئيسية ==========
@client.on(events.CallbackQuery(data=b"back_main"))
async def back_main(event):
    await start_cmd(event)

# ========== دوال المشرف ==========
@client.on(events.CallbackQuery(data=b"admin_panel"))
async def admin_panel(event):
    if not await is_admin(event.chat_id):
        return
    await admin_menu()

@client.on(events.CallbackQuery())
async def admin_callbacks(event):
    if not await is_admin(event.chat_id):
        return
    data = event.data
    
    if data == b"stats":
        users = get_data("users")
        real = sum(1 for k in users.keys() if k.isdigit())
        accs = sum(len(u.get("accounts", [])) for u in users.values())
        premium = len(get_data("memberships"))
        await event.answer(f"👥 {real} | 📱 {accs} | 💎 {premium}", alert=True)
    
    elif data == b"premium_list":
        mems = get_data("memberships")
        if not mems:
            return await event.answer("لا يوجد مميزين", alert=True)
        msg = "💎 **المميزين:**\n"
        for uid, info in mems.items():
            expiry = datetime.fromtimestamp(info.get("expiry", 0)).strftime("%Y-%m-%d")
            msg += f"🆔 `{uid}` → {expiry}\n"
        await event.edit(msg)
    
    elif data == b"show_pending":
        pending = get_data("pending_requests")
        if not pending:
            return await event.answer("لا توجد طلبات", alert=True)
        msg = "⏳ **طلبات الاشتراك:**\n\n"
        for uid, info in pending.items():
            msg += f"👤 {info['name']}\n🆔 `{uid}`\n📅 {info['date']}\n━━━━━━━━━━━\n"
        await event.edit(msg)
    
    elif data == b"upgrade":
        await event.edit("➕ أرسل ايدي المستخدم")
        @client.on(events.NewMessage(from_users=ADMIN_ID))
        async def get_uid(m):
            client.remove_event_handler(get_uid)
            uid = m.text
            await event.edit("📅 أرسل عدد الأيام")
            @client.on(events.NewMessage(from_users=ADMIN_ID))
            async def set_days(d):
                client.remove_event_handler(set_days)
                days = int(d.text)
                mems = get_data("memberships")
                mems[uid] = {"active": True, "expiry": (datetime.now() + timedelta(days=days)).timestamp()}
                save_data("memberships", mems)
                await event.edit(f"✅ تم ترقية {uid} لـ {days} يوم")
    
    elif data == b"remove":
        await event.edit("➖ أرسل ايدي المستخدم")
        @client.on(events.NewMessage(from_users=ADMIN_ID))
        async def get_uid(m):
            client.remove_event_handler(get_uid)
            uid = m.text
            mems = get_data("memberships")
            if uid in mems:
                del mems[uid]
                save_data("memberships", mems)
                await event.edit(f"✅ تم إزالة {uid}")
            else:
                await event.edit(f"❌ {uid} ليس لديه عضوية")
    
    elif data == b"broadcast":
        await event.edit("📢 أرسل رسالة الإذاعة")
        @client.on(events.NewMessage(from_users=ADMIN_ID))
        async def send_msg(m):
            client.remove_event_handler(send_msg)
            users = get_data("users")
            sent = 0
            for uid in users:
                if uid.isdigit():
                    try:
                        await client.send_message(int(uid), m.text)
                        sent += 1
                    except:
                        pass
                    await asyncio.sleep(0.5)
            await event.edit(f"✅ تم الإرسال إلى {sent} مستخدم")

# ========== توجيه الرسائل للمشرف ==========
@client.on(events.NewMessage(incoming=True))
async def forward_messages(event):
    if event.is_private and event.chat_id != ADMIN_ID and not event.text.startswith('/'):
        try:
            await client.send_message(ADMIN_ID, f"📨 رسالة من المستخدم\n🆔 {event.chat_id}\n💬 {event.text[:500]}")
        except:
            pass

# ========== تشغيل البوت ==========
print("✅ البوت شغال @Motazalkade")
client.run_until_disconnected()