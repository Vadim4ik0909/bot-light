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
    keyboard = [
        [
            InlineKeyboardButton(text="🔄 Оновити зараз", callback_data="refresh_status"),
            InlineKeyboardButton(text="📅 Сьогодні", callback_data="btn_today")
        ],
        [
            InlineKeyboardButton(text="📆 Завтра", callback_data="btn_tomorrow"),
            InlineKeyboardButton(text="🌐 Сайт обленерго", url="https://poweron.toe.com.ua/")
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
                text=f"Попередження до вимкнення: {warn_text}",
                callback_data="cycle_notify_warning"
            )
        ],
        [
            InlineKeyboardButton(text="🔙 Закрити налаштування", callback_data="close_settings")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
