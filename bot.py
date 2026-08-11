#!/usr/bin/env python
# -*- coding: utf-8 -*-

# ===================================================
# بوت النشر التلقائي الاحترافي - النسخة النهائية
# جميع الحقوق محفوظة للمطور: @Motazalkade
# ===================================================

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
import json
import sqlite3
import asyncio
import re
import random
from datetime import datetime, timedelta
from telethon.sessions import StringSession
from telethon import TelegramClient, events, Button
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

if not os.path.isdir('database'):
    os.makedirs('database')

# ========== البيانات الثابتة ==========
API_ID = 35983238
API_HASH = "daf2ef391f5d9017043b33f4d1f84052"
BOT_TOKEN = "7987342508:AAEzwochQazEwX_ycq2RNZjnNCI_A19V09k"
ADMIN_ID = 5517628630
ADMIN_USERNAME = "Motazalkade"
# =====================================

client = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ========== قاعدة البيانات (بسيطة ومضمونة) ==========
def get_db():
    conn = sqlite3.connect('database/bot_data.db')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS data (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    conn.commit()
    return conn

def save_user_data(user_id, data):
    conn = get_db()
    conn.execute('REPLACE INTO data (key, value) VALUES (?, ?)', (f"user_{user_id}", json.dumps(data)))
    conn.commit()
    conn.close()

def get_user_data(user_id):
    conn = get_db()
    cursor = conn.execute('SELECT value FROM data WHERE key = ?', (f"user_{user_id}",))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return {"accounts": [], "settings": {}}

# ===================================================
# ========== دوال البوت الرئيسية ==========
# ===================================================

@client.on(events.NewMessage(pattern="/start", func=lambda x: x.is_private))
async def start_cmd(event):
    user_id = str(event.chat_id)
    user_data = get_user_data(user_id)
    accounts = user_data.get("accounts", [])
    
    main_menu_text = f"""
📊 **لوحة المعلومات**

📱 عدد حساباتك: {len(accounts)}
👥 المجموعات: {user_data.get("groups", 0)}
📨 المنشورات: {user_data.get("posts", 0)}
⚡ عمليات جارية: {user_data.get("active", 0)}

📅 تاريخ الإنشاء: {user_data.get("created_at", datetime.now().strftime("%d-%m-%Y %H:%M"))}
"""
    
    buttons = [
        [Button.inline("➕ إضافة حساب", b"add_account")],
        [Button.inline("📋 حساباتي", b"my_accounts")],
        [Button.inline("🔗 جلب الروابط", b"fetch_links")],
        [Button.inline("🚀 نشر سريع", b"fast_publish")],
        [Button.inline("📖 المساعدة", b"help")]
    ]
    
    if user_id == str(ADMIN_ID):
        buttons.append([Button.inline("👑 لوحة المشرف", b"admin_panel")])
    
    await event.respond(main_menu_text, buttons=buttons)

# ========== إضافة حساب ==========
@client.on(events.CallbackQuery(data=b"add_account"))
async def add_account(event):
    user_id = str(event.chat_id)
    
    await event.edit("📱 **أرسل رقم الهاتف مع رمز الدولة**\nمثال: +966512345678")
    
    @client.on(events.NewMessage(incoming=True, from_users=event.chat_id))
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
        
        await msg.reply("📝 **أرسل كود التحقق**")
        
        @client.on(events.NewMessage(incoming=True, from_users=event.chat_id))
        async def get_code(code_msg):
            client.remove_event_handler(get_code)
            code = code_msg.text.replace(" ", "")
            
            try:
                await temp.sign_in(phone, code)
                session_str = temp.session.save()
                await temp.disconnect()
                
                user_data = get_user_data(user_id)
                accounts = user_data.get("accounts", [])
                accounts.append({"phone": phone, "session": session_str})
                user_data["accounts"] = accounts
                save_user_data(user_id, user_data)
                
                await code_msg.reply(f"✅ **تم إضافة الحساب {phone} بنجاح!**")
                await start_cmd(code_msg)
                
            except SessionPasswordNeededError:
                await code_msg.reply("🔐 **أرسل كلمة المرور (2FA)**")
                
                @client.on(events.NewMessage(incoming=True, from_users=event.chat_id))
                async def get_password(pw_msg):
                    client.remove_event_handler(get_password)
                    password = pw_msg.text
                    
                    try:
                        await temp.sign_in(password=password)
                        session_str = temp.session.save()
                        await temp.disconnect()
                        
                        user_data = get_user_data(user_id)
                        accounts = user_data.get("accounts", [])
                        accounts.append({"phone": phone, "session": session_str})
                        user_data["accounts"] = accounts
                        save_user_data(user_id, user_data)
                        
                        await pw_msg.reply(f"✅ **تم إضافة الحساب {phone} بنجاح!**")
                        await start_cmd(pw_msg)
                        
                    except Exception as e:
                        await pw_msg.reply(f"❌ خطأ: {str(e)[:100]}")
                        await temp.disconnect()
                        
            except Exception as e:
                await code_msg.reply(f"❌ خطأ: {str(e)[:100]}")
                await temp.disconnect()

# ========== عرض الحسابات ==========
@client.on(events.CallbackQuery(data=b"my_accounts"))
async def my_accounts(event):
    user_id = str(event.chat_id)
    user_data = get_user_data(user_id)
    accounts = user_data.get("accounts", [])
    
    if not accounts:
        await event.edit("❌ لا توجد حسابات مضافه", buttons=[[Button.inline("🔙 رجوع", b"back_main")]])
        return
    
    buttons = []
    for acc in accounts:
        phone = acc["phone"]
        buttons.append([Button.inline(f"📱 {phone}", f"manage_acc_{phone}".encode())])
    buttons.append([Button.inline("🔙 رجوع", b"back_main")])
    
    await event.edit("📋 **حساباتك:**\nاختر حساباً للتحكم به:", buttons=buttons)

# ========== إدارة حساب فردي ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"manage_acc_")))
async def manage_account(event):
    phone = event.data.decode().split("_")[2]
    user_id = str(event.chat_id)
    user_data = get_user_data(user_id)
    accounts = user_data.get("accounts", [])
    account = next((a for a in accounts if a["phone"] == phone), None)
    
    if not account:
        await event.answer("❌ الحساب غير موجود", alert=True)
        return
    
    buttons = [
        [Button.inline("📋 جلب المجموعات", f"get_groups_{phone}".encode())],
        [Button.inline("🗑 حذف الحساب", f"delete_acc_{phone}".encode())],
        [Button.inline("🔙 رجوع", b"my_accounts")]
    ]
    
    await event.edit(f"📱 **{phone}**\nاختر إجراء:", buttons=buttons)

# ========== جلب المجموعات ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"get_groups_")))
async def get_groups(event):
    phone = event.data.decode().split("_")[2]
    user_id = str(event.chat_id)
    user_data = get_user_data(user_id)
    accounts = user_data.get("accounts", [])
    account = next((a for a in accounts if a["phone"] == phone), None)
    
    if not account:
        await event.answer("❌ الحساب غير موجود", alert=True)
        return
    
    await event.edit("🔄 جاري جلب المجموعات...")
    try:
        temp = TelegramClient(StringSession(account["session"]), API_ID, API_HASH)
        await temp.connect()
        dialogs = await temp.get_dialogs()
        groups = [d for d in dialogs if d.is_group]
        await temp.disconnect()
        
        if not groups:
            await event.edit("⚠️ لا توجد مجموعات", buttons=[[Button.inline("🔙 رجوع", f"manage_acc_{phone}".encode())]])
            return
        
        msg = f"📋 **قائمة المجموعات**\n📞 {phone}\n📊 العدد: {len(groups)}\n\n"
        for i, g in enumerate(groups[:20], 1):
            msg += f"{i}. {g.name}\n🆔 `{g.id}`\n\n"
        
        await event.edit(msg, buttons=[[Button.inline("🔙 رجوع", f"manage_acc_{phone}".encode())]])
    except Exception as e:
        await event.edit(f"❌ خطأ: {str(e)[:100]}", buttons=[[Button.inline("🔙 رجوع", f"manage_acc_{phone}".encode())]])

# ========== حذف حساب ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"delete_acc_")))
async def delete_account(event):
    phone = event.data.decode().split("_")[2]
    user_id = str(event.chat_id)
    user_data = get_user_data(user_id)
    accounts = user_data.get("accounts", [])
    user_data["accounts"] = [a for a in accounts if a["phone"] != phone]
    save_user_data(user_id, user_data)
    
    await event.answer("✅ تم حذف الحساب", alert=True)
    await my_accounts(event)

# ========== جلب الروابط ==========
@client.on(events.CallbackQuery(data=b"fetch_links"))
async def fetch_links(event):
    user_id = str(event.chat_id)
    user_data = get_user_data(user_id)
    accounts = user_data.get("accounts", [])
    
    if not accounts:
        await event.answer("❌ لا توجد حسابات", alert=True)
        return
    
    await event.edit("🔗 **جلب الروابط**\nاختر الحساب:", buttons=[
        [Button.inline(f"📱 {a['phone']}", f"fetch_from_{a['phone']}".encode()) for a in accounts[:3]],
        [Button.inline("🔙 رجوع", b"back_main")]
    ])

@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"fetch_from_")))
async def fetch_from_account(event):
    phone = event.data.decode().split("_")[2]
    user_id = str(event.chat_id)
    user_data = get_user_data(user_id)
    accounts = user_data.get("accounts", [])
    account = next((a for a in accounts if a["phone"] == phone), None)
    
    if not account:
        await event.answer("❌ الحساب غير موجود", alert=True)
        return
    
    await event.edit(f"🔄 جاري جلب الروابط من `{phone}`...")
    try:
        temp = TelegramClient(StringSession(account["session"]), API_ID, API_HASH)
        await temp.connect()
        
        dialogs = await temp.get_dialogs()
        all_links = []
        
        for dialog in dialogs:
            if not dialog.is_group:
                continue
            try:
                async for msg in temp.iter_messages(dialog.entity, limit=50):
                    if msg.text:
                        links = re.findall(r'(https?://[^\s]+)', msg.text)
                        all_links.extend(links)
            except:
                continue
        
        await temp.disconnect()
        unique_links = list(set(all_links))
        
        if not unique_links:
            await event.edit("⚠️ لا توجد روابط", buttons=[[Button.inline("🔙 رجوع", b"back_main")]])
            return
        
        msg = f"🔗 **الروابط المجموعة**\n📞 {phone}\n📊 العدد: {len(unique_links)}\n\n"
        for i, link in enumerate(unique_links[:20], 1):
            msg += f"{i}. {link}\n"
        
        buttons = [[Button.inline("🔙 رجوع", b"back_main")]]
        await event.edit(msg, buttons=buttons, link_preview=False)
    except Exception as e:
        await event.edit(f"❌ خطأ: {str(e)[:200]}", buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== النشر السريع ==========
@client.on(events.CallbackQuery(data=b"fast_publish"))
async def fast_publish(event):
    user_id = str(event.chat_id)
    user_data = get_user_data(user_id)
    accounts = user_data.get("accounts", [])
    
    if not accounts:
        await event.answer("❌ لا توجد حسابات", alert=True)
        return
    
    await event.edit("🚀 **النشر السريع**\nأرسل رسالتك للنشر في جميع المجموعات")
    
    @client.on(events.NewMessage(incoming=True, from_users=event.chat_id))
    async def publish_msg(msg):
        client.remove_event_handler(publish_msg)
        await event.edit("🔄 جاري النشر...")
        
        total = 0
        for acc in accounts:
            try:
                temp = TelegramClient(StringSession(acc["session"]), API_ID, API_HASH)
                await temp.connect()
                dialogs = await temp.get_dialogs()
                groups = [d for d in dialogs if d.is_group]
                for group in groups[:5]:
                    try:
                        await temp.send_message(group.entity, msg.text)
                        total += 1
                    except:
                        pass
                    await asyncio.sleep(2)
                await temp.disconnect()
            except:
                pass
        
        await event.edit(f"✅ **تم النشر!**\n📨 تم النشر في {total} مجموعة", buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== المساعدة ==========
@client.on(events.CallbackQuery(data=b"help"))
async def help_cmd(event):
    await event.edit("📖 **شرح البوت**\n\n"
                    "🤖 **بوت النشر التلقائي**\n\n"
                    "📌 **طريقة الاستخدام:**\n"
                    "1️⃣ أضف رقمك من 'إضافة حساب'\n"
                    "2️⃣ استخدم 'جلب الروابط' لجمع الروابط\n"
                    "3️⃣ استخدم 'نشر سريع' للنشر الفوري\n"
                    "4️⃣ استخدم 'حساباتي' لإدارة حساباتك\n\n"
                    "👨‍💻 **المطور:** @Motazalkade",
                    buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== رجوع ==========
@client.on(events.CallbackQuery(data=b"back_main"))
async def back_main(event):
    await start_cmd(event)

# ========== لوحة المشرف ==========
@client.on(events.CallbackQuery(data=b"admin_panel"))
async def admin_panel(event):
    if str(event.chat_id) != str(ADMIN_ID):
        await event.answer("غير مصرح", alert=True)
        return
    
    await event.edit("👑 **لوحة المشرف**\nاختر إجراء:", buttons=[
        [Button.inline("📊 الإحصائيات", b"admin_stats")],
        [Button.inline("📢 إذاعة", b"admin_broadcast")],
        [Button.inline("🔙 رجوع", b"back_main")]
    ])

@client.on(events.CallbackQuery(data=b"admin_stats"))
async def admin_stats(event):
    if str(event.chat_id) != str(ADMIN_ID):
        return
    
    # إحصائيات بسيطة
    conn = get_db()
    cursor = conn.execute('SELECT COUNT(*) FROM data')
    count = cursor.fetchone()[0]
    conn.close()
    
    await event.answer(f"📊 عدد المستخدمين: {count}", alert=True)

@client.on(events.CallbackQuery(data=b"admin_broadcast"))
async def admin_broadcast(event):
    if str(event.chat_id) != str(ADMIN_ID):
        return
    
    await event.edit("📢 **أرسل رسالة الإذاعة**")
    
    @client.on(events.NewMessage(incoming=True, from_users=ADMIN_ID))
    async def broadcast_msg(msg):
        client.remove_event_handler(broadcast_msg)
        await event.edit("🔄 جاري الإرسال...")
        
        conn = get_db()
        cursor = conn.execute('SELECT key FROM data')
        rows = cursor.fetchall()
        conn.close()
        
        sent = 0
        for row in rows:
            user_id = row[0].replace("user_", "")
            try:
                await client.send_message(int(user_id), msg.text)
                sent += 1
            except:
                pass
            await asyncio.sleep(0.5)
        
        await event.edit(f"✅ تم الإرسال إلى {sent} مستخدم", buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== توجيه الرسائل للمشرف ==========
@client.on(events.NewMessage(incoming=True))
async def forward_to_admin(event):
    if event.is_private and event.chat_id != ADMIN_ID and not event.text.startswith('/'):
        try:
            await client.send_message(ADMIN_ID, f"📨 رسالة من المستخدم\n🆔 {event.chat_id}\n💬 {event.text[:500]}")
        except:
            pass

# ========== تشغيل البوت ==========
print("✅ البوت شغال @Motazalkade")
client.run_until_disconnected()