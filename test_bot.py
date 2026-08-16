#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات محلية لا تتصل بواجهة تيليجرام."""

import asyncio
import os
import shutil
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.update(
    {
        "TELEGRAM_API_ID": "12345",
        "TELEGRAM_API_HASH": "0123456789abcdef0123456789abcdef",
        "TELEGRAM_BOT_TOKEN": "123456:TEST_TOKEN_ONLY_FOR_LOCAL_IMPORT",
        "TELEGRAM_ADMIN_ID": "999999",
        "REQUIRED_CHANNEL": "",
    }
)
sys.path.insert(0, str(ROOT))

# إزالة بيانات اختبار سابقة قبل استيراد الوحدة.
shutil.rmtree(ROOT / "database", ignore_errors=True)
import bot  # noqa: E402


class FakeEvent:
    def __init__(self, user_id: int, text: str = "") -> None:
        self.chat_id = user_id
        self.raw_text = text
        self.is_private = True
        self.responses: list[tuple[str, object]] = []
        self.edits: list[tuple[str, object]] = []
        self.answers: list[tuple[object, bool]] = []

    async def respond(self, text: str, buttons=None, **kwargs) -> None:
        self.responses.append((text, buttons))

    async def edit(self, text: str, buttons=None, **kwargs) -> None:
        self.edits.append((text, buttons))

    async def answer(self, text=None, alert=False) -> None:
        self.answers.append((text, alert))


async def run_tests() -> None:
    bot.init_db()

    # 1) صحة تنظيف أرقام الهاتف.
    assert bot.clean_phone("+966 512-345-678") == "966512345678"
    assert bot.clean_phone("123") is None

    # 2) إنشاء المستخدم والحساب وإعداداته الخاصة به.
    user_one, user_two, phone = 111111, 222222, "966512345678"
    for user_id in (user_one, user_two):
        bot.ensure_user(user_id)
    users = bot.get_data("users", {})
    users[str(user_one)]["accounts"] = [{"phone": phone, "session": "session-one"}]
    users[str(user_two)]["accounts"] = [{"phone": phone, "session": "session-two"}]
    bot.save_data("users", users)

    one_settings = bot.get_account_settings(user_one, phone)
    one_settings.update({"message": "رسالة المستخدم الأول", "interval": 12})
    bot.save_account_settings(user_one, phone, one_settings)
    two_settings = bot.get_account_settings(user_two, phone)
    assert two_settings["message"] == bot.DEFAULT_ACCOUNT_SETTINGS["message"]
    assert bot.get_account_settings(user_one, phone)["interval"] >= bot.MIN_POST_INTERVAL

    # 3) معالج الإدخال الموحد: حفظ الكليشة وتغيير الفاصل ونص الرد.
    await bot.set_input_state(user_one, "set_post_message", phone=phone)
    event = FakeEvent(user_one, "محتوى اختبار")
    await bot.handle_user_input(event)
    assert bot.get_account_settings(user_one, phone)["message"] == "محتوى اختبار"
    assert event.responses and "حُفظت" in event.responses[-1][0]

    await bot.set_input_state(user_one, "set_interval", phone=phone)
    event = FakeEvent(user_one, "10")
    await bot.handle_user_input(event)
    assert bot.get_account_settings(user_one, phone)["interval"] == bot.MIN_POST_INTERVAL

    await bot.set_input_state(user_one, "set_reply_text", phone=phone)
    event = FakeEvent(user_one, "سأرد لاحقًا")
    await bot.handle_user_input(event)
    assert bot.get_account_settings(user_one, phone)["auto_reply_text"] == "سأرد لاحقًا"

    # 4) نموذج النشر الطبيعي ينتقل من الرسالة إلى اختيار الحساب.
    await bot.set_input_state(user_one, "normal_message")
    event = FakeEvent(user_one, "نص نشر تجريبي")
    await bot.handle_user_input(event)
    assert bot.pending_inputs[user_one]["kind"] == "normal_message_ready"
    assert event.responses and "اختر الحساب" in event.responses[-1][0]
    assert event.responses[-1][1]

    # 5) أزرار الواجهة الأساسية، فحص الصحة وإعدادات التشغيل صالحة.
    assert len(bot.MAIN_BUTTONS) == 8
    response = bot.app.test_client().get("/")
    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    required_fixed_callbacks = [
        "request_sub", "back_main", "cancel", "manage_accounts", "add_account",
        "publish_engine", "normal_publish", "schedule_publish", "auto_publish",
        "turbo_publish", "fetch_links", "join_section", "running_processes",
        "auto_reply", "help_bot", "admin_panel", "admin_stats", "premium_list",
        "show_pending", "upgrade", "remove", "broadcast",
    ]
    required_callback_prefixes = [
        "accept_", "reject_", "manage_acc_", "get_groups_", "set_msg_",
        "set_int_", "toggle_", "delete_acc_", "confirm_delete_", "normal_to_",
        "schedule_to_", "fetch_from_", "export_links_", "join_with_",
        "auto_reply_acc_", "toggle_reply_", "set_reply_",
    ]
    for callback in required_fixed_callbacks:
        assert f'data=b"{callback}"' in source, callback
    for prefix in required_callback_prefixes:
        assert f'startswith(b"{prefix}")' in source, prefix
    assert 'not data.startswith(b"toggle_reply_")' in source
    assert 'await respond(event, "📱 اختر الحساب المستهدف للنشر:", buttons)' in source
    bot.validate_configuration()
    with (ROOT / "railway.toml").open("rb") as config_file:
        railway_config = tomllib.load(config_file)
    assert railway_config["build"]["builder"] == "NIXPACKS"
    assert railway_config["deploy"]["startCommand"] == "python bot.py"
    assert railway_config["deploy"]["healthcheckPath"] == "/"

    # 6) الضغط المتكرر على زر الواجهة لا يسقط معالج الحدث.
    original_error = bot.MessageNotModifiedError

    class UnchangedMessageError(Exception):
        pass

    class UnchangedEvent(FakeEvent):
        async def edit(self, text: str, buttons=None, **kwargs) -> None:
            raise UnchangedMessageError()

    bot.MessageNotModifiedError = UnchangedMessageError
    unchanged_event = UnchangedEvent(user_one)
    assert await bot.safe_edit(unchanged_event, "النص نفسه") is False
    assert unchanged_event.answers
    bot.MessageNotModifiedError = original_error

    # 7) إنشاء منشور مجدول يضيف مهمة قابلة للاستعادة دون تنفيذ النشر الآن.
    job = bot.schedule_post(user_one, [phone], "رسالة مجدولة", 60)
    assert job["status"] == "pending"
    assert job["user_id"] == user_one
    task = bot.scheduled_tasks[job_id := next(iter(bot.scheduled_tasks))]
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    bot.scheduled_tasks.pop(job_id, None)

    print("ALL_LOCAL_TESTS_PASSED")


if __name__ == "__main__":
    asyncio.run(run_tests())
