import urllib.parse
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)

def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """
    Bottom persistent reply keyboard for fast single-tap access.
    """
    keyboard = [
        [
            KeyboardButton(text="💡 Поточний стан"),
            KeyboardButton(text="📅 Графік на сьогодні")
        ],
        [
            KeyboardButton(text="📆 Графік на завтра"),
            KeyboardButton(text="🚨 Аварійні роботи")
        ],
        [
            KeyboardButton(text="⚙️ Налаштування сповіщень"),
            KeyboardButton(text="ℹ️ Допомога")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_status_inline_keyboard() -> InlineKeyboardMarkup:
    """
    Inline keyboard attached to status or schedule messages.
    """
    share_text = "Бот відключень світла для нашого будинку (Бережани, вул. Героїв Майдану, 2-А) ⚡️"
    share_url = f"https://t.me/share/url?url=https://t.me/light_metios_bot&text={urllib.parse.quote(share_text)}"

    keyboard = [
        [
            InlineKeyboardButton(text="🔄 Оновити зараз", callback_data="refresh_status"),
            InlineKeyboardButton(text="📅 Сьогодні", callback_data="btn_today")
        ],
        [
            InlineKeyboardButton(text="📆 Завтра", callback_data="btn_tomorrow"),
            InlineKeyboardButton(text="📌 Закріпити статус", callback_data="pin_live_status")
        ],
        [
            InlineKeyboardButton(text="👥 Поділитися з сусідом", url=share_url)
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_settings_inline_keyboard(user_settings: dict) -> InlineKeyboardMarkup:
    """
    Interactive toggle buttons for notification preferences.
    """
    notify_outage = "✅ Увімкнено" if user_settings.get("notify_outage", 1) else "❌ Вимкнено"
    notify_restore = "✅ Увімкнено" if user_settings.get("notify_restore", 1) else "❌ Вимкнено"
    notify_change = "✅ Увімкнено" if user_settings.get("notify_schedule_change", 1) else "❌ Вимкнено"
    quiet_night = "🌙 Без звуку" if user_settings.get("quiet_night", 1) else "🔔 Зі звуком"
    daily_digest = "✅ Увімкнено" if user_settings.get("daily_digest", 1) else "❌ Вимкнено"

    warning_mins = user_settings.get("notify_warning", 15)
    if warning_mins == 15:
        warn_text = "⏱ За 15 хв"
    elif warning_mins == 30:
        warn_text = "⏱ За 30 хв"
    else:
        warn_text = "❌ Вимкнено"

    keyboard = [
        [
            InlineKeyboardButton(
                text=f"Вимкнення світла: {notify_outage}",
                callback_data="toggle_notify_outage"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"Увімкнення світла: {notify_restore}",
                callback_data="toggle_notify_restore"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"Зміна графіка: {notify_change}",
                callback_data="toggle_notify_schedule_change"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"Попередження: {warn_text}",
                callback_data="cycle_notify_warning"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"Нічний режим (23-07): {quiet_night}",
                callback_data="toggle_quiet_night"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"Ранковий дайджест (08:00): {daily_digest}",
                callback_data="toggle_daily_digest"
            )
        ],
        [
            InlineKeyboardButton(text="📌 Закріпити живий статус", callback_data="pin_live_status")
        ],
        [
            InlineKeyboardButton(text="🔙 Закрити налаштування", callback_data="close_settings")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
