import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from config import config
from api_client import ToeApiClient
from schedule_parser import (
    ScheduleParser,
    STATUS_ON,
    STATUS_OFF,
    STATUS_MAYBE,
    format_duration
)
from database import db
from keyboards import get_status_inline_keyboard

logger = logging.getLogger(__name__)

class NotifierService:
    def __init__(self, bot: Bot, api_client: ToeApiClient):
        self.bot = bot
        self.api = api_client
        self.is_running = False

    async def broadcast(self, message: str, filter_key: Optional[str] = None):
        """
        Sends message to all active subscribers, checking individual user preferences
        and applying quiet night mode if active (23:00 - 07:00).
        """
        tz = ZoneInfo(config.TIMEZONE)
        now = datetime.now(tz)
        is_night = (now.hour >= 23 or now.hour < 7)

        subscribers = await db.get_active_subscribers()
        for sub in subscribers:
            chat_id = sub["chat_id"]
            if filter_key:
                # If subscriber disabled this notification type, skip
                if not sub.get(filter_key, 1):
                    continue

            # Determine silent notification for quiet night mode
            silent = False
            if is_night and sub.get("quiet_night", 1):
                silent = True

            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                    disable_notification=silent,
                    disable_web_page_preview=True
                )
                await asyncio.sleep(0.05)  # Telegram broadcast throttle
            except TelegramForbiddenError:
                logger.warning(f"User {chat_id} blocked bot. Deactivating.")
                await db.update_setting(chat_id, "is_active", 0)
            except TelegramBadRequest as e:
                logger.warning(f"Bad request sending to {chat_id}: {e}")
            except Exception as e:
                logger.error(f"Error sending message to {chat_id}: {e}")

    async def update_pinned_messages(self, status_text: str):
        """
        Updates pinned live status message for subscribers who have enabled it.
        """
        subscribers = await db.get_active_subscribers()
        for sub in subscribers:
            pinned_id = sub.get("pinned_message_id")
            if pinned_id:
                try:
                    await self.bot.edit_message_text(
                        chat_id=sub["chat_id"],
                        message_id=pinned_id,
                        text=status_text,
                        reply_markup=get_status_inline_keyboard(),
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

    async def check_for_updates(self):
        """
        Main check cycle run periodically:
        1. Checks schedule changes on poweron.toe.com.ua
        2. Checks transition events (outage started / power restored)
        3. Checks advance warnings (e.g. 15 min before outage)
        4. Updates live pinned messages
        5. Sends morning digest at 08:00
        """
        tz = ZoneInfo(config.TIMEZONE)
        now = datetime.now(tz)
        today_str = now.strftime("%Y-%m-%d")

        schedule_members = await self.api.get_schedule()
        if not schedule_members:
            return

        # Find today's and tomorrow's graph
        today_graph = None
        tomorrow_graph = None
        for m in schedule_members:
            date_graph = m.get("dateGraph", "")
            if date_graph.startswith(today_str):
                today_graph = m
            elif (now + timedelta(days=1)).strftime("%Y-%m-%d") in date_graph:
                tomorrow_graph = m

        if not today_graph and schedule_members:
            today_graph = schedule_members[0]

        today_sched = ScheduleParser.extract_day_schedule(today_graph, config.CHER_GPV)
        if not today_sched:
            return

        times = today_sched.get("times", {})

        # --- 1. Check Schedule Updates (Compare ONLY actual timeslots for queue 2.1, NOT dateCreate) ---
        today_hash = hashlib.md5(json.dumps(times, sort_keys=True).encode("utf-8")).hexdigest()
        saved_today_hash = await db.get_state(f"today_times_hash_{today_str}")

        if saved_today_hash is None:
            await db.set_state(f"today_times_hash_{today_str}", today_hash)
        elif saved_today_hash != today_hash:
            logger.info("Today's timeslots actually changed! Broadcasting notification...")
            await db.set_state(f"today_times_hash_{today_str}", today_hash)
            
            schedule_text = ScheduleParser.format_schedule_text(today_sched, "сьогодні (ОНОВЛЕНО)")
            msg = (
                "🔄 <b>Оновлено години відключень на сьогодні!</b>\n"
                f"📍 {config.short_address} (Черга {config.CHER_GPV})\n\n"
                f"{schedule_text}"
            )
            await self.broadcast(msg, filter_key="notify_schedule_change")

        # Check tomorrow's timeslots if published or updated
        tomorrow_times = tomorrow_graph.get("dataJson", {}).get(config.CHER_GPV, {}).get("times") if tomorrow_graph else None
        if tomorrow_times:
            tomorrow_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            tomorrow_hash = hashlib.md5(json.dumps(tomorrow_times, sort_keys=True).encode("utf-8")).hexdigest()
            saved_tomorrow_hash = await db.get_state(f"tomorrow_times_hash_{tomorrow_date}")

            if saved_tomorrow_hash is None:
                # First time tomorrow's schedule is published
                await db.set_state(f"tomorrow_times_hash_{tomorrow_date}", tomorrow_hash)
                tomorrow_sched = ScheduleParser.extract_day_schedule(tomorrow_graph, config.CHER_GPV)
                if tomorrow_sched:
                    schedule_text = ScheduleParser.format_schedule_text(tomorrow_sched, "завтра (НОВИЙ)")
                    msg = (
                        "📆 <b>Оприлюднено графік відключень на завтра!</b>\n"
                        f"📍 {config.short_address} (Черга {config.CHER_GPV})\n\n"
                        f"{schedule_text}"
                    )
                    await self.broadcast(msg, filter_key="notify_schedule_change")
            elif saved_tomorrow_hash != tomorrow_hash:
                # Tomorrow's schedule changed
                await db.set_state(f"tomorrow_times_hash_{tomorrow_date}", tomorrow_hash)
                tomorrow_sched = ScheduleParser.extract_day_schedule(tomorrow_graph, config.CHER_GPV)
                if tomorrow_sched:
                    schedule_text = ScheduleParser.format_schedule_text(tomorrow_sched, "завтра (ОНОВЛЕНО)")
                    msg = (
                        "🔄 <b>Оновлено графік відключень на завтра!</b>\n"
                        f"📍 {config.short_address} (Черга {config.CHER_GPV})\n\n"
                        f"{schedule_text}"
                    )
                    await self.broadcast(msg, filter_key="notify_schedule_change")

        # --- 2. Check Real-Time Status Transitions ---
        current_status_info = ScheduleParser.get_current_status(times, now)
        current_status = current_status_info["status"]
        curr_interval = current_status_info["current_interval"]
        next_interval = current_status_info["next_interval"]

        last_status_key = f"last_status_{today_str}"
        last_status = await db.get_state(last_status_key)

        if last_status is None:
            await db.set_state(last_status_key, current_status)
        elif last_status != current_status:
            await db.set_state(last_status_key, current_status)

            # A) Transition to OUTAGE (🔴 1)
            if current_status == STATUS_OFF:
                end_time = curr_interval["end"] if curr_interval else "кінця інтервалу"
                dur_str = format_duration(curr_interval["end_minutes"] - curr_interval["start_minutes"]) if curr_interval else ""
                dur_suffix = f" (на {dur_str})" if dur_str else ""

                msg = (
                    f"🔴 <b>Світло вимкнено до {end_time}</b>{dur_suffix}\n"
                    f"📍 {config.short_address} (Черга {config.CHER_GPV})\n\n"
                    f"💡 Орієнтовний час відновлення електроенергії — <b>{end_time}</b>."
                )
                await self.broadcast(msg, filter_key="notify_outage")

            # B) Transition to RESTORATION (🟢 0)
            elif current_status == STATUS_ON and last_status in (STATUS_OFF, STATUS_MAYBE):
                next_outage_msg = ""
                if next_interval and next_interval["status"] == STATUS_OFF:
                    next_outage_msg = f" (наступне вимкнення о {next_interval['start']})"
                elif next_interval and next_interval["status"] == STATUS_MAYBE:
                    next_outage_msg = f" (можливе вимкнення о {next_interval['start']})"

                msg = (
                    f"🟢 <b>Світло увімкнено!</b>{next_outage_msg}\n"
                    f"📍 {config.short_address} (Черга {config.CHER_GPV})\n\n"
                    f"💡 Електропостачання відновлено за графіком."
                )
                await self.broadcast(msg, filter_key="notify_restore")

            # C) Transition to MAYBE OUTAGE (🟡 10)
            elif current_status == STATUS_MAYBE and last_status == STATUS_ON:
                end_time = curr_interval["end"] if curr_interval else "кінця інтервалу"
                msg = (
                    f"🟡 <b>Період можливого відключення (до {end_time})</b>\n"
                    f"📍 {config.short_address} (Черга {config.CHER_GPV})\n\n"
                    f"⚠️ До <b>{end_time}</b> можливе відключення у разі перевищення лімітів."
                )
                await self.broadcast(msg, filter_key="notify_outage")

        # --- 3. Check Advance Warning (e.g. 15-30 mins before) ---
        intervals = ScheduleParser.get_intervals(times)
        curr_minutes = now.hour * 60 + now.minute

        subscribers = await db.get_active_subscribers()
        is_night = (now.hour >= 23 or now.hour < 7)

        for sub in subscribers:
            warn_mins = sub.get("notify_warning", 15)
            if not warn_mins or warn_mins <= 0:
                continue

            for inter in intervals:
                if inter["status"] in (STATUS_OFF, STATUS_MAYBE):
                    diff = inter["start_minutes"] - curr_minutes
                    if 0 < diff <= warn_mins:
                        warn_state_key = f"warn_{sub['chat_id']}_{today_str}_{inter['start']}"
                        already_sent = await db.get_state(warn_state_key)
                        if not already_sent:
                            await db.set_state(warn_state_key, "1")
                            
                            status_title = "відключення" if inter["status"] == STATUS_OFF else "можливе вимкнення"
                            emoji = "⚠️" if inter["status"] == STATUS_OFF else "🟡"
                            
                            warning_msg = (
                                f"{emoji} <b>Через {diff} хв {status_title} світла (до {inter['end']})</b>\n"
                                f"📍 {config.short_address} (Черга {config.CHER_GPV})\n\n"
                                f"О <b>{inter['start']}</b> планується вимкнення до <b>{inter['end']}</b>.\n"
                                f"🔌 <i>Встигніть зарядити пристрої та закінчити справи!</i>"
                            )
                            silent = is_night and sub.get("quiet_night", 1)
                            try:
                                await self.bot.send_message(
                                    chat_id=sub["chat_id"],
                                    text=warning_msg,
                                    parse_mode="HTML",
                                    disable_notification=silent
                                )
                            except Exception as e:
                                logger.error(f"Failed to send warning to {sub['chat_id']}: {e}")

        # --- 4. Update Live Pinned Messages ---
        tomorrow_sched = ScheduleParser.extract_day_schedule(tomorrow_graph, config.CHER_GPV) if tomorrow_graph else None
        live_status = ScheduleParser.format_status_message(today_sched, tomorrow_sched, now)
        pinned_text = f"📌 <b>ЖИВИЙ СТАТУС (ОНОВЛЮЄТЬСЯ АВТОМАТИЧНО)</b>\n\n{live_status}"
        await self.update_pinned_messages(pinned_text)

        # --- 5. Morning Digest at 08:00 ---
        if now.hour == 8 and now.minute <= 2:
            digest_state_key = f"digest_sent_{today_str}"
            already_sent = await db.get_state(digest_state_key)
            if not already_sent:
                await db.set_state(digest_state_key, "1")
                digest_text = ScheduleParser.format_daily_digest(today_sched)
                await self.broadcast(digest_text, filter_key="daily_digest")

    async def start(self):
        """
        Starts the background polling loop.
        """
        self.is_running = True
        logger.info(f"Starting notifier background service with interval {config.CHECK_INTERVAL_SECONDS}s")
        while self.is_running:
            try:
                await self.check_for_updates()
            except Exception as e:
                logger.error(f"Error in notifier check loop: {e}", exc_info=True)
            await asyncio.sleep(config.CHECK_INTERVAL_SECONDS)

    def stop(self):
        self.is_running = False
