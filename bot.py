#!/usr/bin/env python
# -*- coding: utf-8 -*-

# بوت النشر التلقائي الاحترافي - النسخة المتكاملة
# المطور: @Motazalkade

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
import json
import sqlite3
from telethon.sessions import StringSession
import asyncio
from kvsqlite.sync import Client as uu
from telethon import TelegramClient, events, Button
import random
from datetime import datetime, timedelta
from telethon.errors import FloodWaitError, SessionPasswordNeededError, PhoneCodeInvalidError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

if not os.path.isdir('database'):
    os.makedirs('database')

# ========== بياناتك ==========
API_ID = 35983238
API_HASH = "daf2ef391f5d9017043b33f4d1f84052"
BOT_TOKEN = "7987342508:AAEzwochQazEwX_ycq2RNZjnNCI_A19V09k"
ADMIN_ID = 5517628630
ADMIN_USERNAME = "Motazalkade"
# ===========================

client = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ========== دالة قراءة البيانات المتوافقة مع الإصدارات القديمة ==========
def get_data_legacy(key, default=None):
    """قراءة البيانات من قاعدة البيانات مع دعم الإصدارات القديمة"""
    try:
        # محاولة القراءة من kvsqlite أولاً (الطريقة الجديدة)
        if db.exists(key):
            return db.get(key)
    except:
        pass
    
    # محاولة القراءة من جدول bot مباشرة (الطريقة القديمة)
    try:
        conn = sqlite3.connect('database/bot_data.ss')
        cursor = conn.execute('SELECT value FROM bot WHERE key=?', (key,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except:
        pass
    
    return default or {}

def save_data_legacy(key, value):
    """حفظ البيانات مع دعم الإصدارات القديمة"""
    try:
        # حفظ في kvsqlite (الطريقة الجديدة)
        db.set(key, value)
    except:
        pass
    
    # حفظ في جدول bot (الطريقة القديمة) للتوافق
    try:
        conn = sqlite3.connect('database/bot_data.ss')
        cursor = conn.execute('SELECT key FROM bot WHERE key=?', (key,))
        exists = cursor.fetchone()
        if exists:
            conn.execute('UPDATE bot SET value=? WHERE key=?', (json.dumps(value), key))
        else:
            conn.execute('INSERT INTO bot (key, value) VALUES (?, ?)', (key, json.dumps(value)))
        conn.commit()
        conn.close()
    except:
        pass

# ========== تهيئة قاعدة البيانات ==========
db = uu('database/bot_data.ss', 'bot')

# تهيئة جميع المفاتيح مع الاحتفاظ بالبيانات القديمة
def init_db_legacy():
    keys = ["users", "accounts_settings", "memberships", "pending_requests", "admins", "bot_enabled", "user_stats", "collected_links"]
    for key in keys:
        if not db.exists(key):
            # محاولة قراءة البيانات القديمة قبل إنشاء مفتاح جديد
            try:
                conn = sqlite3.connect('database/bot_data.ss')
                cursor = conn.execute('SELECT value FROM bot WHERE key=?', (key,))
                row = cursor.fetchone()
                conn.close()
                if row:
                    old_data = json.loads(row[0])
                    db.set(key, old_data)
                    continue
            except:
                pass
            # إذا لم توجد بيانات قديمة، أنشئ مفتاحاً جديداً
            if key == "bot_enabled":
                db.set(key, True)
            elif key == "admins":
                db.set(key, [ADMIN_ID])
            else:
                db.set(key, {})

init_db_legacy()

def get_data(key, default=None):
    return get_data_legacy(key, default)

def save_data(key, value):
    save_data_legacy(key, value)

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
    total_groups = stats.get("groups", 0)
    total_posts = stats.get("posts", 0)
    total_links = len(get_data("collected_links").get(str(user_id), {}))
    active_processes = 0
    
    for acc in accounts:
        phone = acc.get("phone") or acc.get("phone_number", "")
        if not phone:
            continue
        acc_settings = settings.get(f"acc_{phone}", {})
        if acc_settings.get("enabled"):
            active_processes += 1
    
    created_at = user_data.get("created_at", datetime.now().strftime("%d-%m-%Y %H:%M:%S"))
    
    return {
        "total_accounts": total_accounts,
        "total_folders": 0,
        "total_groups": total_groups,
        "total_posts": total_posts,
        "total_links": total_links,
        "total_violations": 0,
        "active_processes": active_processes,
        "created_at": created_at
    }

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

# ========== رسائل البوت ==========
WELCOME_MESSAGE = """
🔥 **بوت النشر التلقائي الاحترافي**

🤖 يساعدك على نشر رسائلك تلقائياً في جميع المجموعات

📌 **المميزات:**
✅ نشر تلقائي 24/7
✅ إضافة حسابات متعددة
✅ جلب المجموعات
✅ جلب الروابط من المجموعات (تيليجرام وواتساب)
✅ دعم التحقق بخطوتين

💎 **للاشتراك، اضغط على زر الاشتراك أدناه**
"""

MAIN_MENU = """
📊 **لوحة المعلومات**

📱 إجمالي أرقامك: {}
👥 المجموعات المنضم لها: {}
📨 إجمالي المنشورات: {}
🔗 إجمالي الروابط المجموعة: {}
⚡ عمليات جارية: {}

📅 تاريخ الإنشاء: {}
"""

MAIN_BUTTONS = [
    [Button.inline("📱 إدارة الأرقام", b"manage_accounts")],
    [Button.inline("🚀 محرك النشر", b"publish_engine")],
    [Button.inline("⚡ النشر السريع", b"turbo_publish")],
    [Button.inline("🔗 جلب الروابط", b"fetch_links")],
    [Button.inline("🔄 العمليات الجارية", b"running_processes")],
    [Button.inline("📖 شرح البوت", b"help_bot")]
]

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
    
    if not await check_subscription(user_id):
        buttons = [[Button.inline("💎 طلب اشتراك", b"request_sub")]]
        return await event.respond(WELCOME_MESSAGE, buttons=buttons)
    
    users = get_data("users")
    if str(user_id) not in users:
        users[str(user_id)] = {"accounts": [], "created_at": datetime.now().strftime("%d-%m-%Y %H:%M:%S")}
        save_data("users", users)
    
    stats = get_user_stats(user_id)
    
    info_text = MAIN_MENU.format(
        stats["total_accounts"],
        stats["total_groups"],
        stats["total_posts"],
        stats["total_links"],
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
        return await event.answer("لديك طلب قيد الانتظار", alert=True)
    
    user = await event.get_sender()
    pending[str(user_id)] = {"name": user.first_name or "مستخدم", "date": datetime.now().strftime("%Y-%m-%d %H:%M")}
    save_data("pending_requests", pending)
    
    await client.send_message(
        ADMIN_ID,
        f"🆕 **طلب اشتراك جديد!**\n👤 {pending[str(user_id)]['name']}\n🆔 `{user_id}`",
        buttons=[[Button.inline("✅ قبول", f"accept_{user_id}".encode()), Button.inline("❌ رفض", f"reject_{user_id}".encode())]]
    )
    await event.edit("✅ تم إرسال طلب اشتراكك للمشرف")

# ========== قبول اشتراك ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"accept_")))
async def accept_subscription(event):
    if not await is_admin(event.chat_id):
        return
    
    user_id = int(event.data.decode().split("_")[1])
    await event.edit(f"✅ قبول طلب `{user_id}`\n📅 أرسل عدد الأيام:")
    
    @client.on(events.NewMessage(incoming=True, from_users=ADMIN_ID))
    async def get_days(msg):
        client.remove_event_handler(get_days)
        try:
            days = int(msg.text)
            memberships = get_data("memberships")
            memberships[str(user_id)] = {"active": True, "expiry": (datetime.now() + timedelta(days=days)).timestamp()}
            save_data("memberships", memberships)
            pending = get_data("pending_requests")
            pending.pop(str(user_id), None)
            save_data("pending_requests", pending)
            await client.send_message(user_id, f"🎉 تم تفعيل اشتراكك لمدة {days} يوم")
            await event.edit(f"✅ تم تفعيل اشتراك `{user_id}` لـ {days} يوم")
            await admin_menu()
        except:
            await event.reply("⚠️ أرسل رقماً صحيحاً")

# ========== رفض اشتراك ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"reject_")))
async def reject_subscription(event):
    if not await is_admin(event.chat_id):
        return
    
    user_id = int(event.data.decode().split("_")[1])
    pending = get_data("pending_requests")
    pending.pop(str(user_id), None)
    save_data("pending_requests", pending)
    await client.send_message(user_id, "❌ تم رفض طلب الاشتراك")
    await event.edit(f"✅ تم رفض طلب `{user_id}`")

# ========== إضافة حساب ==========
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
            await msg.reply(f"❌ خطأ: {str(e)[:100]}")
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
                
                if any(a.get("phone") == phone or a.get("phone_number") == phone for a in user_data["accounts"]):
                    await code_msg.reply(f"⚠️ الحساب {phone} مضاف مسبقاً")
                    return
                
                user_data["accounts"].append({"phone": phone, "session": session_str})
                users[str(user_id)] = user_data
                save_data("users", users)
                
                await code_msg.reply(f"✅ **تم إضافة الرقم {phone} بنجاح!**")
                await start_cmd(code_msg)
                
            except SessionPasswordNeededError:
                await code_msg.reply("🔐 **أرسل كلمة المرور (2FA)**")
                
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
                        
                        if any(a.get("phone") == phone or a.get("phone_number") == phone for a in user_data["accounts"]):
                            await pw_msg.reply(f"⚠️ الحساب {phone} مضاف مسبقاً")
                            return
                        
                        user_data["accounts"].append({"phone": phone, "session": session_str, "has_2fa": True})
                        users[str(user_id)] = user_data
                        save_data("users", users)
                        
                        await pw_msg.reply(f"✅ **تم إضافة الرقم {phone} بنجاح!**")
                        await start_cmd(pw_msg)
                        
                    except Exception as e:
                        await pw_msg.reply(f"❌ خطأ: {str(e)[:100]}")
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
        await event.edit("❌ لا توجد أرقام", buttons=[[Button.inline("➕ إضافة رقم", b"add_account")], [Button.inline("🔙 رجوع", b"back_main")]])
        return
    
    buttons = []
    for acc in accounts:
        phone = acc.get("phone") or acc.get("phone_number", "")
        if not phone:
            continue
        settings = get_data("accounts_settings")
        acc_settings = settings.get(f"acc_{phone}", {})
        status = "✅" if acc_settings.get("enabled") else "⏸️"
        buttons.append([Button.inline(f"{status} {phone}", f"manage_acc_{phone}".encode())])
    
    buttons.append([Button.inline("➕ إضافة رقم", b"add_account")])
    buttons.append([Button.inline("🔙 رجوع", b"back_main")])
    
    await event.edit(f"📱 **إدارة الأرقام**\nلديك {len(accounts)} رقم:", buttons=buttons)

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
    
    buttons = [
        [Button.inline("📋 جلب المجموعات", f"get_groups_{phone}".encode())],
        [Button.inline("✏️ تعيين الكليشة", f"set_msg_{phone}".encode())],
        [Button.inline("⏱ تعيين الفاصل", f"set_int_{phone}".encode())],
        [Button.inline("🔄 تفعيل/تعطيل", f"toggle_{phone}".encode())],
        [Button.inline("🗑 حذف الرقم", f"delete_acc_{phone}".encode())],
        [Button.inline("🔙 رجوع", b"manage_accounts")]
    ]
    
    await event.edit(f"📱 **{phone}**\n📊 حالة النشر: {'✅ مفعل' if acc_settings['enabled'] else '⏸️ معطل'}\n⏱ الفاصل: {acc_settings['interval']} ثانية", buttons=buttons)

# ========== جلب المجموعات ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"get_groups_")))
async def get_groups(event):
    phone = event.data.decode().split("_")[2]
    user_id = event.chat_id
    
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    account = next((a for a in accounts if a.get("phone") == phone or a.get("phone_number") == phone), None)
    
    if not account:
        return await event.answer("❌ الحساب غير موجود", alert=True)
    
    session_str = account.get("session")
    if not session_str:
        return await event.answer("❌ جلسة الحساب غير موجودة", alert=True)
    
    await event.edit("🔄 جاري جلب المجموعات...")
    try:
        temp = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await temp.connect()
        dialogs = await temp.get_dialogs()
        groups = [d for d in dialogs if d.is_group]
        await temp.disconnect()
        
        update_user_stats(user_id, "groups", len(groups))
        
        if not groups:
            return await event.edit("⚠️ لا توجد مجموعات", buttons=[[Button.inline("🔙 رجوع", f"manage_acc_{phone}".encode())]])
        
        msg = f"📋 **قائمة المجموعات**\n📞 {phone}\n📊 العدد: {len(groups)}\n\n"
        for i, g in enumerate(groups[:20], 1):
            msg += f"{i}. {g.name}\n🆔 `{g.id}`\n\n"
        
        await event.edit(msg, buttons=[[Button.inline("🔙 رجوع", f"manage_acc_{phone}".encode())]])
    except Exception as e:
        await event.edit(f"❌ خطأ: {str(e)[:100]}", buttons=[[Button.inline("🔙 رجوع", f"manage_acc_{phone}".encode())]])

# ========== تعيين الكليشة ==========
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

# ========== تعيين الفاصل ==========
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
        account = next((a for a in accounts if a.get("phone") == phone or a.get("phone_number") == phone), None)
        if account:
            session_str = account.get("session")
            if session_str:
                asyncio.create_task(auto_post_loop(user_id, phone, session_str))
                await event.answer(f"✅ تم تفعيل النشر للحساب {phone}")
            else:
                await event.answer(f"⚠️ لا توجد جلسة للحساب {phone}")
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
    user_data["accounts"] = [a for a in user_data.get("accounts", []) if a.get("phone") != phone and a.get("phone_number") != phone]
    users[str(user_id)] = user_data
    save_data("users", users)
    
    await event.answer("✅ تم حذف الرقم", alert=True)
    await manage_accounts(event)

# ========== جلب الروابط (تيليجرام وواتساب) ==========
@client.on(events.CallbackQuery(data=b"fetch_links"))
async def fetch_links(event):
    user_id = event.chat_id
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    
    if not accounts:
        return await event.answer("❌ لا توجد حسابات", alert=True)
    
    buttons = []
    for acc in accounts:
        phone = acc.get("phone") or acc.get("phone_number", "")
        if phone:
            buttons.append([Button.inline(f"📱 {phone}", f"fetch_from_{phone}".encode())])
    buttons.append([Button.inline("🔙 رجوع", b"back_main")])
    await event.edit("🔗 **اختر الحساب لجلب الروابط:**", buttons=buttons)

@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"fetch_from_")))
async def fetch_from_account(event):
    phone = event.data.decode().split("_")[2]
    user_id = event.chat_id
    
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    account = next((a for a in accounts if a.get("phone") == phone or a.get("phone_number") == phone), None)
    
    if not account:
        return await event.answer("❌ الحساب غير موجود", alert=True)
    
    session_str = account.get("session")
    if not session_str:
        return await event.answer("❌ جلسة الحساب غير موجودة", alert=True)
    
    await event.edit(f"🔄 جاري جلب الروابط من `{phone}`...")
    
    try:
        temp = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await temp.connect()
        
        if not await temp.is_user_authorized():
            await event.edit("❌ الحساب غير مصرح")
            await temp.disconnect()
            return
        
        dialogs = await temp.get_dialogs()
        all_links = []
        total_messages = 0
        
        for dialog in dialogs:
            if not dialog.is_group and not dialog.is_channel:
                continue
            
            try:
                async for message in temp.iter_messages(dialog.entity, limit=100):
                    total_messages += 1
                    if message.text:
                        # روابط تيليجرام
                        tg_links = re.findall(r'(t\.me/[^\s]+)', message.text)
                        tg_links_full = [f"https://{link}" for link in tg_links]
                        # روابط واتساب
                        wa_links = re.findall(r'(https?://wa\.me/[^\s]+)', message.text)
                        wa_links += re.findall(r'(https?://chat\.whatsapp\.com/[^\s]+)', message.text)
                        # روابط عامة
                        urls = re.findall(r'(https?://[^\s]+)', message.text)
                        
                        all_links.extend(tg_links_full)
                        all_links.extend(wa_links)
                        all_links.extend(urls)
            except:
                continue
        
        await temp.disconnect()
        
        # فلترة الروابط (تيليجرام وواتساب فقط)
        filtered_links = []
        for link in all_links:
            if 't.me/' in link or 'wa.me/' in link or 'whatsapp.com' in link:
                filtered_links.append(link)
        
        unique_links = list(set(filtered_links))
        
        links_data = get_data("collected_links")
        user_links = links_data.get(str(user_id), {})
        user_links[phone] = unique_links
        links_data[str(user_id)] = user_links
        save_data("collected_links", links_data)
        
        update_user_stats(user_id, "links", len(unique_links))
        
        if not unique_links:
            await event.edit(f"⚠️ **لا توجد روابط تيليجرام أو واتساب**\n📊 تم فحص {total_messages} رسالة", buttons=[[Button.inline("🔙 رجوع", b"back_main")]])
            return
        
        msg = f"🔗 **الروابط المجموعة**\n📞 {phone}\n📊 العدد: {len(unique_links)}\n📊 تم فحص: {total_messages} رسالة\n\n"
        
        for i, link in enumerate(unique_links[:20], 1):
            msg += f"{i}. {link}\n"
        
        if len(unique_links) > 20:
            msg += f"\n... و {len(unique_links) - 20} رابط آخر"
        
        buttons = [
            [Button.inline("📥 تصدير الروابط", f"export_links_{phone}".encode())],
            [Button.inline("🔙 رجوع", b"back_main")]
        ]
        
        await event.edit(msg, buttons=buttons, link_preview=False)
        
    except Exception as e:
        await event.edit(f"❌ خطأ: {str(e)[:200]}", buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== تصدير الروابط ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"export_links_")))
async def export_links(event):
    phone = event.data.decode().split("_")[2]
    user_id = event.chat_id
    
    links_data = get_data("collected_links")
    user_links = links_data.get(str(user_id), {})
    links = user_links.get(phone, [])
    
    if not links:
        return await event.answer("❌ لا توجد روابط", alert=True)
    
    file_content = f"روابط من {phone}\nتاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nعدد: {len(links)}\n\n" + "\n".join(links)
    
    file_path = f"links_{phone}_{int(datetime.now().timestamp())}.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(file_content)
    
    await client.send_file(user_id, file_path, caption=f"📁 **روابط من** `{phone}`\n📊 العدد: {len(links)}")
    os.remove(file_path)
    await event.answer("✅ تم إرسال الملف", alert=True)

# ========== النشر السريع ==========
@client.on(events.CallbackQuery(data=b"turbo_publish"))
async def turbo_publish(event):
    user_id = event.chat_id
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    
    if not accounts:
        return await event.answer("❌ لا توجد حسابات", alert=True)
    
    await event.edit("⚡ **النشر السريع**\n📝 أرسل الرسالة:")
    
    @client.on(events.NewMessage(incoming=True, from_users=user_id))
    async def turbo_msg(msg):
        client.remove_event_handler(turbo_msg)
        await event.edit("🔄 جاري النشر السريع...")
        
        success = 0
        for acc in accounts[:3]:
            session_str = acc.get("session")
            if not session_str:
                continue
            try:
                temp = TelegramClient(StringSession(session_str), API_ID, API_HASH)
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
        
        await event.edit(f"✅ **تم النشر السريع!**\n📨 تم النشر في {success} مجموعة", buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== محرك النشر ==========
@client.on(events.CallbackQuery(data=b"publish_engine"))
async def publish_engine(event):
    await event.edit("🚀 **محرك النشر**\nاختر نوع النشر:", buttons=[
        [Button.inline("📤 نشر عادي", b"normal_publish")],
        [Button.inline("🔄 نشر تلقائي", b"auto_publish")],
        [Button.inline("🔙 رجوع", b"back_main")]
    ])

@client.on(events.CallbackQuery(data=b"normal_publish"))
async def normal_publish(event):
    user_id = event.chat_id
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    
    if not accounts:
        return await event.answer("❌ لا توجد حسابات", alert=True)
    
    await event.edit("📤 **نشر عادي**\n📝 أرسل الرسالة:")
    
    @client.on(events.NewMessage(incoming=True, from_users=user_id))
    async def normal_msg(msg):
        client.remove_event_handler(normal_msg)
        await event.edit("🔄 جاري النشر...")
        
        success = 0
        for acc in accounts[:1]:
            session_str = acc.get("session")
            if not session_str:
                continue
            try:
                temp = TelegramClient(StringSession(session_str), API_ID, API_HASH)
                await temp.connect()
                dialogs = await temp.get_dialogs()
                groups = [d for d in dialogs if d.is_group]
                for g in groups[:20]:
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
        
        await event.edit(f"✅ **تم النشر!**\n📨 تم النشر في {success} مجموعة", buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== العمليات الجارية ==========
@client.on(events.CallbackQuery(data=b"running_processes"))
async def running_processes(event):
    user_id = event.chat_id
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    settings = get_data("accounts_settings")
    
    active = []
    for a in accounts:
        phone = a.get("phone") or a.get("phone_number", "")
        if phone and settings.get(f"acc_{phone}", {}).get("enabled"):
            active.append(f"✅ {phone}")
    
    if active:
        await event.edit("🔄 **العمليات الجارية:**\n\n" + "\n".join(active), buttons=[[Button.inline("🔙 رجوع", b"back_main")]])
    else:
        await event.edit("🔄 **العمليات الجارية:**\n\nلا توجد عمليات جارية", buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== شرح البوت ==========
@client.on(events.CallbackQuery(data=b"help_bot"))
async def help_bot(event):
    await event.edit("📖 **شرح البوت**\n\n"
                    "🤖 **بوت النشر التلقائي**\n\n"
                    "📌 **طريقة الاستخدام:**\n"
                    "1️⃣ أضف رقمك من 'إدارة الأرقام'\n"
                    "2️⃣ اذهب إلى 'محرك النشر' للنشر\n"
                    "3️⃣ استخدم 'النشر السريع' للنشر بسرعة\n"
                    "4️⃣ استخدم 'جلب الروابط' لجمع روابط تيليجرام وواتساب\n\n"
                    "👨‍💻 **المطور:** @Motazalkade",
                    buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== رجوع ==========
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
            msg += f"🆔 `{uid}` → {datetime.fromtimestamp(info.get('expiry', 0)).strftime('%Y-%m-%d')}\n"
        await event.edit(msg)
    
    elif data == b"show_pending":
        pending = get_data("pending_requests")
        if not pending:
            return await event.answer("لا توجد طلبات", alert=True)
        msg = "⏳ **الطلبات:**\n" + "\n".join([f"👤 {info['name']}\n🆔 `{uid}`" for uid, info in pending.items()])
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

# ========== توجيه الرسائل ==========
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