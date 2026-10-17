import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command

from config import config
from api_client import ToeApiClient
from schedule_parser import ScheduleParser, STATUS_OFF, STATUS_MAYBE
from database import db
from keyboards import (
    get_main_reply_keyboard,
    get_status_inline_keyboard,
    get_settings_inline_keyboard
)

logger = logging.getLogger(__name__)
router = Router()
api_client = ToeApiClient()

def get_current_time_str() -> str:
    tz = ZoneInfo(config.TIMEZONE)
    return datetime.now(tz).strftime("%H:%M")

async def build_status_message() -> str:
    """
    Constructs the real-time status message based on current power schedule and time.
    """
    tz = ZoneInfo(config.TIMEZONE)
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")

    schedule_members = await api_client.get_schedule()
    if not schedule_members:
        return (
            "⚠️ <b>Тимчасово не вдалося отримати дані з сайту обленерго.</b>\n\n"
            "Спробуйте натиснути кнопку «🔄 Оновити зараз» через хвилину."
        )

    # Find today's schedule
    today_graph = None
    for m in schedule_members:
        if m.get("dateGraph", "").startswith(today_str):
            today_graph = m
            break
    if not today_graph and schedule_members:
        today_graph = schedule_members[0]

    today_sched = ScheduleParser.extract_day_schedule(today_graph, config.CHER_GPV)
    if not today_sched:
        return (
            "ℹ️ <b>На сьогодні інформація про відключення відсутня.</b>\n"
            "Світло має бути постійно 🟢"
        )

    times = today_sched.get("times", {})
    status_info = ScheduleParser.get_current_status(times, now)

    curr_interval = status_info["current_interval"]
    next_interval = status_info["next_interval"]
    curr_status = status_info["status"]

    mins_left = status_info["minutes_remaining"]
    hours_left = mins_left // 60
    rem_mins = mins_left % 60
    time_left_str = f"{hours_left} год {rem_mins} хв" if hours_left > 0 else f"{rem_mins} хв"

    if curr_status == STATUS_OFF:
        status_header = f"🔴 <b>СВІТЛА НЕМАЄ</b> (до {curr_interval['end']})"
    elif curr_status == STATUS_MAYBE:
        status_header = f"🟡 <b>МОЖЛИВЕ ВІДКЛЮЧЕННЯ</b> (до {curr_interval['end']})"
    else:
        status_header = "🟢 <b>СВІТЛО Є</b>"

    interval_str = f"{curr_interval['start']} — {curr_interval['end']}" if curr_interval else "поточний час"

    next_msg = ""
    if next_interval:
        next_label = next_interval["label"]
        next_emoji = next_interval["emoji"]
        next_msg = (
            f"\n\n⏭ <b>Наступна зміна:</b>\n"
            f"О <b>{next_interval['start']}</b>: {next_emoji} {next_label}\n"
            f"⏳ Залишилось: <b>{time_left_str}</b>"
        )
    else:
        next_msg = f"\n\nПоточний режим діє до <b>{curr_interval['end']}</b> (залишилось {time_left_str})."

    # Overview of outages today
    intervals = ScheduleParser.get_intervals(times)
    off_intervals = [i for i in intervals if i["status"] == STATUS_OFF]
    if off_intervals:
        ranges = ", ".join([f"{i['start']}-{i['end']}" for i in off_intervals])
        today_outages_summary = f"\n\n⚡️ <b>Вимкнення сьогодні:</b> <b>{ranges}</b>"
    else:
        today_outages_summary = "\n\n🎉 <i>Сьогодні вимкнень більше не заплановано!</i>"

    msg = (
        f"{status_header}\n\n"
        f"📍 <b>Адреса:</b> вул. {config.STREET_NAME}, буд. {config.BUILDING_NAME}\n"
        f"⚡️ <b>Черга:</b> {config.CHER_GPV}\n"
        f"🕒 <b>Зараз:</b> {now.strftime('%H:%M')} (період {interval_str})"
        f"{next_msg}"
        f"{today_outages_summary}\n\n"
        f"<i>Синхронізовано з poweron.toe.com.ua</i>"
    )
    return msg

@router.message(CommandStart())
async def cmd_start(message: Message):
    chat_id = message.chat.id
    user = message.from_user
    username = user.username if user else None
    first_name = user.first_name if user else "Користувач"

    await db.add_subscriber(chat_id, username, first_name)

    greeting = (
        f"👋 <b>Вітаю, {first_name}!</b>\n\n"
        f"Бот моніторить відключення та включення світла для:\n"
        f"📍 <b>м. {config.CITY_NAME}, {config.STREET_NAME}, буд. {config.BUILDING_NAME}</b>\n"
        f"⚡️ <b>Черга ГПВ:</b> <b>{config.CHER_GPV}</b>\n\n"
        f"🔔 <b>Ви автоматично підписані на сповіщення:</b>\n"
        f"• 🔴 Початок вимкнення\n"
        f"• 🟢 Включення світла\n"
        f"• ⚠️ За 15 хв до відключення\n"
        f"• 🌙 Тихий режим уночі (без звуку з 23:00 до 07:00)\n"
        f"<i>(Ранкове зведення можна увімкнути в налаштуваннях)</i>\n\n"
        f"👇 Оберіть дію в меню:"
    )

    await message.answer(greeting, reply_markup=get_main_reply_keyboard(), parse_mode="HTML")
    status_text = await build_status_message()
    sent_msg = await message.answer(status_text, reply_markup=get_status_inline_keyboard(), parse_mode="HTML")
    await db.update_setting(chat_id, "last_status_message_id", sent_msg.message_id)

@router.message(F.text.in_({"💡 Поточний стан", "/status", "/now"}))
async def handle_status(message: Message):
    chat_id = message.chat.id
    sub = await db.get_subscriber(chat_id)

    # Clean up previous status message to keep chat tidy
    if sub and sub.get("last_status_message_id"):
        try:
            await message.bot.delete_message(chat_id, sub["last_status_message_id"])
        except Exception:
            pass

    status_text = await build_status_message()
    sent_msg = await message.answer(status_text, reply_markup=get_status_inline_keyboard(), parse_mode="HTML")
    await db.update_setting(chat_id, "last_status_message_id", sent_msg.message_id)

@router.callback_query(F.data == "refresh_status")
async def cb_refresh_status(call: CallbackQuery):
    status_text = await build_status_message()
    try:
        await call.message.edit_text(status_text, reply_markup=get_status_inline_keyboard(), parse_mode="HTML")
    except Exception:
        pass
    await call.answer("✅ Дані оновлено!")

@router.callback_query(F.data == "pin_live_status")
async def cb_pin_live_status(call: CallbackQuery):
    chat_id = call.message.chat.id
    status_text = await build_status_message()
    sent_msg = await call.message.answer(
        f"📌 <b>ЖИВИЙ СТАТУС (ОНОВЛЮЄТЬСЯ АВТОМАТИЧНО)</b>\n\n{status_text}",
        reply_markup=get_status_inline_keyboard(),
        parse_mode="HTML"
    )
    try:
        await call.bot.pin_chat_message(chat_id, sent_msg.message_id, disable_notification=True)
        await db.update_setting(chat_id, "pinned_message_id", sent_msg.message_id)
        await call.answer("📌 Віджет закріплено зверху чату! Він оновлюватиметься автоматично.", show_alert=True)
    except Exception as e:
        logger.error(f"Failed to pin message: {e}")
        await call.answer("⚠️ Не вдалося закріпити повідомлення (перевірте дозволи чату).")

@router.message(F.text.in_({"📅 Графік на сьогодні", "/today"}))
@router.callback_query(F.data == "btn_today")
async def handle_today(event: Message | CallbackQuery):
    tz = ZoneInfo(config.TIMEZONE)
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")

    schedule_members = await api_client.get_schedule()
    today_graph = None
    for m in schedule_members:
        if m.get("dateGraph", "").startswith(today_str):
            today_graph = m
            break
    if not today_graph and schedule_members:
        today_graph = schedule_members[0]

    today_sched = ScheduleParser.extract_day_schedule(today_graph, config.CHER_GPV) if today_graph else None
    if not today_sched:
        text = "ℹ️ Графік на сьогодні ще не завантажено або відключень немає."
    else:
        text = ScheduleParser.format_schedule_text(today_sched, "сьогодні")

    if isinstance(event, CallbackQuery):
        await event.message.answer(text, reply_markup=get_status_inline_keyboard(), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=get_status_inline_keyboard(), parse_mode="HTML")

@router.message(F.text.in_({"📆 Графік на завтра", "/tomorrow"}))
@router.callback_query(F.data == "btn_tomorrow")
async def handle_tomorrow(event: Message | CallbackQuery):
    tz = ZoneInfo(config.TIMEZONE)
    now = datetime.now(tz)
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    schedule_members = await api_client.get_schedule()
    tomorrow_graph = None
    for m in schedule_members:
        if m.get("dateGraph", "").startswith(tomorrow_str):
            tomorrow_graph = m
            break

    tomorrow_sched = ScheduleParser.extract_day_schedule(tomorrow_graph, config.CHER_GPV) if tomorrow_graph else None

    if not tomorrow_sched:
        text = (
            f"📆 <b>Графік на завтра ({tomorrow_str})</b>\n\n"
            f"ℹ️ Графік на завтра ще <b>не оприлюднено</b> обленерго.\n"
            f"Зазвичай графіки з'являються після 18:00 - 20:00.\n\n"
            f"Як тільки він з'явиться — бот надішле сповіщення!"
        )
    else:
        text = ScheduleParser.format_schedule_text(tomorrow_sched, "завтра")

    if isinstance(event, CallbackQuery):
        await event.message.answer(text, reply_markup=get_status_inline_keyboard(), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=get_status_inline_keyboard(), parse_mode="HTML")

@router.message(F.text.in_({"🚨 Аварійні роботи", "/accidents"}))
async def handle_accidents(message: Message):
    accidents = await api_client.get_accidents()
    planed = await api_client.get_planed_accidents()

    lines = [
        f"🚨 <b>Аварійні та ремонтні роботи</b>",
        f"📍 <b>Адреса:</b> м. {config.CITY_NAME}, {config.STREET_NAME}\n"
    ]

    if not accidents and not planed:
        lines.append("✅ <b>Аварійних чи планових ремонтних робіт за вашою адресою не зафіксовано.</b>")
    else:
        if accidents:
            lines.append("⚠️ <b>Аварійні відключення:</b>")
            for a in accidents:
                lines.append(f"• {a.get('reason', 'Аварійна ситуація')} (до {a.get('dateEnd', 'уточнюється')})")
            lines.append("")
        if planed:
            lines.append("🛠 <b>Планові ремонти:</b>")
            for p in planed:
                lines.append(f"• {p.get('reason', 'Планові роботи')} ({p.get('dateStart', '')} - {p.get('dateEnd', '')})")

    await message.answer("\n".join(lines), parse_mode="HTML")

@router.message(F.text.in_({"⚙️ Налаштування сповіщень", "/settings"}))
async def handle_settings(message: Message):
    sub = await db.get_subscriber(message.chat.id)
    if not sub:
        await db.add_subscriber(message.chat.id, message.from_user.username, message.from_user.first_name)
        sub = await db.get_subscriber(message.chat.id)

    text = (
        "⚙️ <b>Налаштування сповіщень та комфорту</b>\n\n"
        "Натискайте кнопки нижче для налаштування під себе:"
    )
    await message.answer(text, reply_markup=get_settings_inline_keyboard(sub), parse_mode="HTML")

@router.callback_query(F.data.startswith("toggle_"))
async def cb_toggle_setting(call: CallbackQuery):
    key = call.data.replace("toggle_", "")
    sub = await db.get_subscriber(call.message.chat.id)
    if not sub:
        await call.answer()
        return

    current_val = sub.get(key, 1)
    new_val = 0 if current_val else 1
    await db.update_setting(call.message.chat.id, key, new_val)

    updated_sub = await db.get_subscriber(call.message.chat.id)
    await call.message.edit_reply_markup(reply_markup=get_settings_inline_keyboard(updated_sub))
    status_label = "увімкнено" if new_val else "вимкнено"
    await call.answer(f"Налаштування {status_label}")

@router.callback_query(F.data == "cycle_notify_warning")
async def cb_cycle_warning(call: CallbackQuery):
    sub = await db.get_subscriber(call.message.chat.id)
    if not sub:
        await call.answer()
        return

    curr_val = sub.get("notify_warning", 15)
    if curr_val == 15:
        new_val = 30
    elif curr_val == 30:
        new_val = 0
    else:
        new_val = 15

    await db.update_setting(call.message.chat.id, "notify_warning", new_val)
    updated_sub = await db.get_subscriber(call.message.chat.id)
    await call.message.edit_reply_markup(reply_markup=get_settings_inline_keyboard(updated_sub))
    msg = f"Попередження: {new_val} хв" if new_val else "Попередження вимкнено"
    await call.answer(msg)

@router.callback_query(F.data == "close_settings")
async def cb_close_settings(call: CallbackQuery):
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer("Налаштування збережено.")

@router.message(F.text.in_({"ℹ️ Допомога", "/help"}))
async def handle_help(message: Message):
    text = (
        "📖 <b>Довідка по боту:</b>\n\n"
        "Бот працює 24/7 у хмарі та щохвилини перевіряє офіційний портал «Тернопільобленерго» (poweron.toe.com.ua).\n\n"
        "<b>Можливості:</b>\n"
        "• 💡 <b>Поточний стан</b> — чи є світло зараз і коли наступне вимкнення\n"
        "• 📅 <b>Графік на сьогодні</b> — розклад на добу\n"
        "• 📆 <b>Графік на завтра</b> — розклад на наступний день\n"
        "• 🚨 <b>Аварійні роботи</b> — позапланові аварії та ремонти\n"
        "• ⚙️ <b>Налаштування</b> — нічний режим, ранковий дайджест, час попередження\n"
        "• 📌 <b>Закріплений статус</b> — закріплює живе повідомлення у верхній частині чату\n\n"
        "🎯 <b>Адреса:</b> м. Бережани, вул. Героїв Майдану, буд. 2-А (Черга 2.1)"
    )
    await message.answer(text, reply_markup=get_main_reply_keyboard(), parse_mode="HTML")
