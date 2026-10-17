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
    STATUS_MAYBE
)
from database import db

logger = logging.getLogger(__name__)

class NotifierService:
    def __init__(self, bot: Bot, api_client: ToeApiClient):
        self.bot = bot
        self.api = api_client
        self.is_running = False

    async def broadcast(self, message: str, filter_key: Optional[str] = None):
        """
        Sends message to all active subscribers, checking individual user preferences.
        """
        subscribers = await db.get_active_subscribers()
        for sub in subscribers:
            chat_id = sub["chat_id"]
            if filter_key:
                # If subscriber disabled this notification type, skip
                if not sub.get(filter_key, 1):
                    continue

            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
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

    async def check_for_updates(self):
        """
        Main check cycle run periodically:
        1. Checks schedule changes on poweron.toe.com.ua
        2. Checks transition events (outage started / power restored)
        3. Checks advance warnings (e.g. 15 min before outage)
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

        # --- 1. Check Schedule Update Hash ---
        raw_signature = json.dumps({
            "today_dateCreate": today_graph.get("dateCreate"),
            "today_times": times,
            "tomorrow_dateCreate": tomorrow_graph.get("dateCreate") if tomorrow_graph else None,
            "tomorrow_times": tomorrow_graph.get("dataJson", {}).get(config.CHER_GPV, {}).get("times") if tomorrow_graph else None
        }, sort_keys=True)
        current_hash = hashlib.md5(raw_signature.encode("utf-8")).hexdigest()

        saved_hash = await db.get_state("schedule_hash")
        if saved_hash is None:
            # First run, just save hash
            await db.set_state("schedule_hash", current_hash)
        elif saved_hash != current_hash:
            logger.info("Schedule updated on site! Broadcasting notification...")
            await db.set_state("schedule_hash", current_hash)
            
            schedule_text = ScheduleParser.format_schedule_text(today_sched, "сьогодні (ОНОВЛЕНО)")
            msg = (
                "🔄 <b>УВАГА! ОНОВЛЕНО ГРАФІК ВІДКЛЮЧЕНЬ!</b>\n\n"
                f"{schedule_text}\n\n"
                "ℹ️ <i>Перевірте актуальні години відключень на сьогодні.</i>"
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
            # Initialize for today
            await db.set_state(last_status_key, current_status)
        elif last_status != current_status:
            # Status has changed!
            await db.set_state(last_status_key, current_status)

            # A) Transition to OUTAGE (🔴 1)
            if current_status == STATUS_OFF:
                end_time = curr_interval["end"] if curr_interval else "кінця інтервалу"
                msg = (
                    "🔴 <b>УВАГА! ВІДКЛЮЧЕННЯ СВІТЛА РОЗПОЧАЛОСЯ</b>\n\n"
                    f"📍 <b>Адреса:</b> м. {config.CITY_NAME}, {config.STREET_NAME}, буд. {config.BUILDING_NAME}\n"
                    f"⚡️ <b>Черга:</b> {config.CHER_GPV}\n\n"
                    f"⏳ Згідно з графіком, електроенергія буде відсутня <b>до {end_time}</b>."
                )
                await self.broadcast(msg, filter_key="notify_outage")

            # B) Transition to RESTORATION (🟢 0)
            elif current_status == STATUS_ON and last_status in (STATUS_OFF, STATUS_MAYBE):
                next_outage_msg = ""
                if next_interval and next_interval["status"] == STATUS_OFF:
                    next_outage_msg = f"\n⏳ Наступне планове відключення: <b>о {next_interval['start']}</b>."
                elif next_interval and next_interval["status"] == STATUS_MAYBE:
                    next_outage_msg = f"\n⏳ Наступне можливе відключення: <b>о {next_interval['start']}</b>."

                msg = (
                    "🟢 <b>СВІТЛО УВІМКНЕНО!</b>\n\n"
                    f"📍 <b>Адреса:</b> м. {config.CITY_NAME}, {config.STREET_NAME}, буд. {config.BUILDING_NAME}\n"
                    f"⚡️ <b>Черга:</b> {config.CHER_GPV}\n\n"
                    f"💡 Електропостачання відновлено.{next_outage_msg}"
                )
                await self.broadcast(msg, filter_key="notify_restore")

            # C) Transition to MAYBE OUTAGE (🟡 10)
            elif current_status == STATUS_MAYBE and last_status == STATUS_ON:
                end_time = curr_interval["end"] if curr_interval else "кінця інтервалу"
                msg = (
                    "🟡 <b>ПОЧАВСЯ ПЕРІОД МОЖЛИВОГО ВІДКЛЮЧЕННЯ</b>\n\n"
                    f"📍 <b>Адреса:</b> м. {config.CITY_NAME}, {config.STREET_NAME}, буд. {config.BUILDING_NAME}\n"
                    f"⚡️ <b>Черга:</b> {config.CHER_GPV}\n\n"
                    f"⚠️ В період <b>з {curr_interval['start']} до {end_time}</b> можливе вимкнення світла у разі дефіциту потужності."
                )
                await self.broadcast(msg, filter_key="notify_outage")

        # --- 3. Check Advance Warning (e.g. 15-30 mins before) ---
        intervals = ScheduleParser.get_intervals(times)
        curr_minutes = now.hour * 60 + now.minute

        subscribers = await db.get_active_subscribers()
        for sub in subscribers:
            warn_mins = sub.get("notify_warning", 15)
            if not warn_mins or warn_mins <= 0:
                continue

            target_minutes = curr_minutes + warn_mins

            # Look for an interval that starts around target_minutes
            for inter in intervals:
                if inter["status"] in (STATUS_OFF, STATUS_MAYBE):
                    # Check if interval starts in exactly warn_mins (or within [warn_mins-1, warn_mins+1])
                    diff = inter["start_minutes"] - curr_minutes
                    if 0 < diff <= warn_mins:
                        # Check if we already sent warning for this chat and this interval
                        warn_state_key = f"warn_{sub['chat_id']}_{today_str}_{inter['start']}"
                        already_sent = await db.get_state(warn_state_key)
                        if not already_sent:
                            await db.set_state(warn_state_key, "1")
                            
                            status_title = "відключення електроенергії" if inter["status"] == STATUS_OFF else "можливе відключення світла"
                            emoji = "⚠️" if inter["status"] == STATUS_OFF else "🟡"
                            
                            warning_msg = (
                                f"{emoji} <b>ПОПЕРЕДЖЕННЯ: {diff} ХВ ДО ВІДКЛЮЧЕННЯ!</b>\n\n"
                                f"📍 <b>Адреса:</b> м. {config.CITY_NAME}, {config.STREET_NAME}, буд. {config.BUILDING_NAME}\n"
                                f"⚡️ <b>Черга:</b> {config.CHER_GPV}\n\n"
                                f"О <b>{inter['start']}</b> планується {status_title} (орієнтовно до <b>{inter['end']}</b>).\n\n"
                                f"🔌 <i>Будь ласка, перевірте заряд акумуляторів та вимкніть чутливі електроприлади!</i>"
                            )
                            try:
                                await self.bot.send_message(
                                    chat_id=sub["chat_id"],
                                    text=warning_msg,
                                    parse_mode="HTML"
                                )
                            except Exception as e:
                                logger.error(f"Failed to send warning to {sub['chat_id']}: {e}")

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
