#!/usr/bin/env python
# -*- coding: utf-8 -*-

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
from telethon.errors import FloodWaitError, SessionPasswordNeededError
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
db = uu('database/bot_data.ss', 'bot')

# تهيئة قاعدة البيانات
if not db.exists("users"):
    db.set("users", {})
if not db.exists("accounts_settings"):
    db.set("accounts_settings", {})
if not db.exists("collected_links"):
    db.set("collected_links", {})

def get_data(key):
    if db.exists(key):
        return db.get(key)
    return {}

def save_data(key, value):
    db.set(key, value)

# ========== دالة إرسال آمنة (تتجنب MessageNotModifiedError) ==========
async def safe_edit(event, text, buttons=None):
    try:
        await event.edit(text, buttons=buttons)
    except Exception as e:
        if "MessageNotModifiedError" in str(e):
            # إذا كانت الرسالة نفسها، نرسل رسالة جديدة بدلاً من التعديل
            await event.answer("تم تحديث القائمة", alert=True)
        else:
            print(f"خطأ في التعديل: {e}")

# ========== أمر /start ==========
@client.on(events.NewMessage(pattern="/start"))
async def start_cmd(event):
    if not event.is_private:
        return
    
    user_id = event.chat_id
    users = get_data("users")
    
    if str(user_id) not in users:
        users[str(user_id)] = {"accounts": [], "created_at": datetime.now().strftime("%d-%m-%Y %H:%M:%S")}
        save_data("users", users)
    
    accounts = users.get(str(user_id), {}).get("accounts", [])
    has_account = len(accounts) > 0
    
    buttons = [
        [Button.inline(f"📱 الحساب: {'✅' if has_account else '❌'}", b"none")],
        [Button.inline("➕ إضافة حساب", b"add_account")],
        [Button.inline("📤 حساباتي", b"my_accounts")],
        [Button.inline("🔗 جلب الروابط", b"fetch_links")],
        [Button.inline("📂 انضمام لمجموعة", b"join_section")]
    ]
    
    if user_id == ADMIN_ID:
        buttons.append([Button.inline("👑 لوحة المشرف", b"admin_panel")])
    
    await event.respond("🔹 **مرحباً بك في بوت النشر التلقائي**\nاختر أحد الأزرار:", buttons=buttons)

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
                user_data = users.get(str(user_id), {"accounts": []})
                
                if any(a["phone"] == phone for a in user_data["accounts"]):
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
                    try:
                        await temp.sign_in(password=pw_msg.text)
                        session_str = temp.session.save()
                        await temp.disconnect()
                        
                        users = get_data("users")
                        user_data = users.get(str(user_id), {"accounts": []})
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

# ========== عرض الحسابات ==========
@client.on(events.CallbackQuery(data=b"my_accounts"))
async def my_accounts(event):
    user_id = event.chat_id
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    
    if not accounts:
        await event.edit("❌ لا توجد حسابات", buttons=[[Button.inline("🔙 رجوع", b"back_main")]])
        return
    
    buttons = []
    for acc in accounts:
        phone = acc["phone"]
        settings = get_data("accounts_settings")
        acc_settings = settings.get(f"acc_{phone}", {})
        status = "✅" if acc_settings.get("enabled") else "⏸️"
        buttons.append([Button.inline(f"{status} {phone}", f"manage_{phone}".encode())])
    
    buttons.append([Button.inline("🔙 رجوع", b"back_main")])
    await event.edit(f"📱 **حساباتك:** ({len(accounts)})", buttons=buttons)

# ========== إدارة حساب ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"manage_")))
async def manage_account(event):
    phone = event.data.decode().split("_")[1]
    user_id = event.chat_id
    
    settings = get_data("accounts_settings")
    acc_settings = settings.get(f"acc_{phone}", {})
    
    if 'enabled' not in acc_settings:
        acc_settings['enabled'] = False
    if 'message' not in acc_settings:
        acc_settings['message'] = "مرحباً"
    if 'interval' not in acc_settings:
        acc_settings['interval'] = 30
    
    status = "✅ مفعل" if acc_settings['enabled'] else "⏸️ معطل"
    
    buttons = [
        [Button.inline("📋 جلب المجموعات", f"groups_{phone}".encode())],
        [Button.inline("✏️ كليشة", f"msg_{phone}".encode())],
        [Button.inline("⏱ فاصل", f"int_{phone}".encode())],
        [Button.inline("🔄 تفعيل/تعطيل", f"toggle_{phone}".encode())],
        [Button.inline("🗑 حذف", f"del_{phone}".encode())],
        [Button.inline("🔙 رجوع", b"my_accounts")]
    ]
    
    await event.edit(f"📱 **{phone}**\n📊 {status}\n⏱ {acc_settings['interval']} ثانية", buttons=buttons)

# ========== جلب المجموعات ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"groups_")))
async def get_groups(event):
    phone = event.data.decode().split("_")[1]
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
        
        if not groups:
            await event.edit("⚠️ لا توجد مجموعات", buttons=[[Button.inline("🔙 رجوع", f"manage_{phone}".encode())]])
            return
        
        msg = f"📋 **المجموعات** ({len(groups)}):\n\n"
        for i, g in enumerate(groups[:20], 1):
            msg += f"{i}. {g.name}\n🆔 `{g.id}`\n\n"
        
        await event.edit(msg, buttons=[[Button.inline("🔙 رجوع", f"manage_{phone}".encode())]])
    except Exception as e:
        await event.edit(f"❌ خطأ: {str(e)[:100]}", buttons=[[Button.inline("🔙 رجوع", f"manage_{phone}".encode())]])

# ========== تعيين الكليشة ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"msg_")))
async def set_message(event):
    phone = event.data.decode().split("_")[1]
    user_id = event.chat_id
    
    await event.edit("✏️ **أرسل الكليشة الجديدة**", buttons=[[Button.inline("إلغاء", f"manage_{phone}".encode())]])
    
    @client.on(events.NewMessage(incoming=True, from_users=user_id))
    async def save_msg(msg):
        client.remove_event_handler(save_msg)
        settings = get_data("accounts_settings")
        settings[f"acc_{phone}"] = settings.get(f"acc_{phone}", {})
        settings[f"acc_{phone}"]["message"] = msg.text
        save_data("accounts_settings", settings)
        await msg.reply(f"✅ تم حفظ الكليشة", buttons=[[Button.inline("🔙 رجوع", f"manage_{phone}".encode())]])

# ========== تعيين الفاصل ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"int_")))
async def set_interval(event):
    phone = event.data.decode().split("_")[1]
    user_id = event.chat_id
    
    await event.edit("⏱ **أرسل الفاصل (30-300 ثانية)**", buttons=[[Button.inline("إلغاء", f"manage_{phone}".encode())]])
    
    @client.on(events.NewMessage(incoming=True, from_users=user_id))
    async def save_int(msg):
        client.remove_event_handler(save_int)
        try:
            interval = max(30, min(300, int(msg.text)))
            settings = get_data("accounts_settings")
            settings[f"acc_{phone}"] = settings.get(f"acc_{phone}", {})
            settings[f"acc_{phone}"]["interval"] = interval
            save_data("accounts_settings", settings)
            await msg.reply(f"✅ تم تعيين الفاصل {interval} ثانية", buttons=[[Button.inline("🔙 رجوع", f"manage_{phone}".encode())]])
        except:
            await msg.reply("⚠️ أرسل رقماً صحيحاً")

# ========== تفعيل/تعطيل ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"toggle_")))
async def toggle_post(event):
    phone = event.data.decode().split("_")[1]
    
    settings = get_data("accounts_settings")
    acc_settings = settings.get(f"acc_{phone}", {"enabled": False})
    new_state = not acc_settings.get("enabled", False)
    
    settings[f"acc_{phone}"] = acc_settings
    settings[f"acc_{phone}"]["enabled"] = new_state
    save_data("accounts_settings", settings)
    
    await event.answer(f"تم {'تفعيل' if new_state else 'تعطيل'}")
    await manage_account(event)

# ========== حذف حساب ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"del_")))
async def delete_account(event):
    phone = event.data.decode().split("_")[1]
    user_id = event.chat_id
    
    users = get_data("users")
    user_data = users.get(str(user_id), {})
    user_data["accounts"] = [a for a in user_data.get("accounts", []) if a["phone"] != phone]
    users[str(user_id)] = user_data
    save_data("users", users)
    
    await event.answer("✅ تم الحذف", alert=True)
    await my_accounts(event)

# ========== جلب الروابط (تيليجرام وواتساب فقط) ==========
@client.on(events.CallbackQuery(data=b"fetch_links"))
async def fetch_links(event):
    user_id = event.chat_id
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    
    if not accounts:
        return await event.answer("❌ لا توجد حسابات", alert=True)
    
    buttons = [[Button.inline(f"📱 {a['phone']}", f"fetch_{a['phone']}".encode())] for a in accounts]
    buttons.append([Button.inline("🔙 رجوع", b"back_main")])
    await event.edit("🔗 **اختر الحساب لجلب الروابط:**", buttons=buttons)

@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"fetch_")))
async def fetch_from_account(event):
    phone = event.data.decode().split("_")[1]
    user_id = event.chat_id
    
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    account = next((a for a in accounts if a["phone"] == phone), None)
    
    if not account:
        return await event.answer("❌ الحساب غير موجود", alert=True)
    
    await event.edit(f"🔄 جاري جلب الروابط من `{phone}`...")
    
    try:
        temp = TelegramClient(StringSession(account["session"]), API_ID, API_HASH)
        await temp.connect()
        
        if not await temp.is_user_authorized():
            await event.edit("❌ الحساب غير مصرح")
            await temp.disconnect()
            return
        
        dialogs = await temp.get_dialogs()
        all_links = []
        
        # أنماط تيليجرام وواتساب فقط
        tg_pattern = r'(?:https?://)?(?:www\.)?t\.me/[^\s]+'
        wa_pattern = r'(?:https?://)?(?:www\.)?(?:wa\.me/[^\s]+|chat\.whatsapp\.com/[^\s]+)'
        combined = re.compile(f'({tg_pattern}|{wa_pattern})', re.IGNORECASE)
        
        for dialog in dialogs:
            if not dialog.is_group and not dialog.is_channel:
                continue
            try:
                async for msg in temp.iter_messages(dialog.entity, limit=100):
                    if msg.text:
                        found = re.findall(combined, msg.text)
                        for link in found:
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
        
        # حفظ الروابط
        links_data = get_data("collected_links")
        user_links = links_data.get(str(user_id), {})
        user_links[phone] = all_links
        links_data[str(user_id)] = user_links
        save_data("collected_links", links_data)
        
        if not all_links:
            await event.edit(f"⚠️ لا توجد روابط تيليجرام أو واتساب", buttons=[[Button.inline("🔙 رجوع", b"back_main")]])
            return
        
        msg = f"🔗 **روابط من {phone}**\n📊 العدد: {len(all_links)}\n\n"
        for i, link in enumerate(all_links[:20], 1):
            icon = "📱" if "t.me" in link else "💬"
            msg += f"{i}. {icon} {link}\n"
        
        if len(all_links) > 20:
            msg += f"\n... و {len(all_links)-20} أخرى"
        
        await event.edit(msg, buttons=[[Button.inline("📥 تصدير", f"export_{phone}".encode()), Button.inline("🔙 رجوع", b"back_main")]])
    except Exception as e:
        await event.edit(f"❌ خطأ: {str(e)[:200]}", buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== تصدير الروابط ==========
@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"export_")))
async def export_links(event):
    phone = event.data.decode().split("_")[1]
    user_id = event.chat_id
    
    links_data = get_data("collected_links")
    links = links_data.get(str(user_id), {}).get(phone, [])
    
    if not links:
        return await event.answer("❌ لا توجد روابط", alert=True)
    
    file_content = f"روابط من {phone}\n"
    file_content += f"التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    file_content += f"العدد: {len(links)}\n"
    file_content += "=" * 40 + "\n\n"
    file_content += "\n".join(links)
    
    file_path = f"links_{phone}.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(file_content)
    
    await client.send_file(user_id, file_path, caption=f"📁 روابط من {phone}")
    os.remove(file_path)
    await event.answer("✅ تم الإرسال", alert=True)

# ========== الانضمام لمجموعة ==========
@client.on(events.CallbackQuery(data=b"join_section"))
async def join_section(event):
    user_id = event.chat_id
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    
    if not accounts:
        return await event.answer("❌ لا توجد حسابات", alert=True)
    
    buttons = [[Button.inline(f"📱 {a['phone']}", f"join_{a['phone']}".encode())] for a in accounts]
    buttons.append([Button.inline("🔙 رجوع", b"back_main")])
    await event.edit("🔗 **اختر الحساب للانضمام:**", buttons=buttons)

@client.on(events.CallbackQuery(data=lambda x: x and x.startswith(b"join_")))
async def join_with_account(event):
    phone = event.data.decode().split("_")[1]
    user_id = event.chat_id
    
    users = get_data("users")
    accounts = users.get(str(user_id), {}).get("accounts", [])
    account = next((a for a in accounts if a["phone"] == phone), None)
    
    if not account:
        return await event.answer("❌ الحساب غير موجود", alert=True)
    
    await event.edit("🔗 **أرسل الروابط (كل رابط بسطر)**\nثم أرسل وقت الانتظار")
    
    @client.on(events.NewMessage(incoming=True, from_users=user_id))
    async def get_links(msg):
        client.remove_event_handler(get_links)
        links = [l.strip() for l in msg.text.split('\n') if l.strip()]
        await event.edit("⏱ **أرسل وقت الانتظار (5-30 ثانية)**")
        
        @client.on(events.NewMessage(incoming=True, from_users=user_id))
        async def get_wait(w):
            client.remove_event_handler(get_wait)
            try:
                wait = max(5, min(30, int(w.text)))
            except:
                wait = 10
            
            await event.edit(f"🔄 جاري الانضمام إلى {len(links)} رابط...")
            success, failed = 0, 0
            
            for link in links:
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
                    await asyncio.sleep(wait)
                except FloodWaitError as fl:
                    failed += 1
                    await asyncio.sleep(fl.seconds)
                except:
                    failed += 1
                    await asyncio.sleep(wait//2)
            
            await event.edit(f"✅ **تم الانتهاء!**\n✅ نجح: {success}\n❌ فشل: {failed}", buttons=[[Button.inline("🔙 رجوع", b"back_main")]])

# ========== رجوع للقائمة الرئيسية ==========
@client.on(events.CallbackQuery(data=b"back_main"))
async def back_main(event):
    await start_cmd(event)

# ========== لوحة المشرف ==========
@client.on(events.CallbackQuery(data=b"admin_panel"))
async def admin_panel(event):
    if event.chat_id != ADMIN_ID:
        return
    
    users = get_data("users")
    real = sum(1 for k in users.keys() if k.isdigit())
    accounts = sum(len(u.get("accounts", [])) for u in users.values())
    
    buttons = [
        [Button.inline("📊 إحصائيات", b"stats"), Button.inline("👥 المستخدمين", b"user_list")],
        [Button.inline("🔙 رجوع", b"back_main")]
    ]
    await event.edit(f"👑 **لوحة المشرف**\n👥 المستخدمين: {real}\n📱 الحسابات: {accounts}", buttons=buttons)

@client.on(events.CallbackQuery())
async def admin_cb(event):
    if event.chat_id != ADMIN_ID:
        return
    data = event.data
    
    if data == b"stats":
        users = get_data("users")
        real = sum(1 for k in users.keys() if k.isdigit())
        accs = sum(len(u.get("accounts", [])) for u in users.values())
        await event.answer(f"👥 {real} | 📱 {accs}", alert=True)
    
    elif data == b"user_list":
        users = get_data("users")
        msg = "👥 **المستخدمين:**\n"
        for uid in users.keys():
            if uid.isdigit():
                msg += f"🆔 `{uid}`\n"
        await event.edit(msg[:2000])

# ========== توجيه الرسائل ==========
@client.on(events.NewMessage(incoming=True))
async def forward_messages(event):
    if event.is_private and event.chat_id != ADMIN_ID and not event.text.startswith('/'):
        try:
            await client.send_message(ADMIN_ID, f"📨 من {event.chat_id}:\n{event.text[:500]}")
        except:
            pass

print("✅ البوت شغال @Motazalkade")
client.run_until_disconnected()