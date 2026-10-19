import logging
from datetime import datetime, time
from typing import Dict, List, Optional, Any
from zoneinfo import ZoneInfo
from config import config

logger = logging.getLogger(__name__)

STATUS_ON = "0"
STATUS_OFF = "1"
STATUS_MAYBE = "10"

STATUS_LABELS = {
    STATUS_ON: "Світло є",
    STATUS_OFF: "Світла немає (відключення)",
    STATUS_MAYBE: "Можливе відключення",
}

STATUS_EMOJIS = {
    STATUS_ON: "🟢",
    STATUS_OFF: "🔴",
    STATUS_MAYBE: "🟡",
}

def parse_time_str(t_str: str) -> time:
    h, m = map(int, t_str.split(":"))
    return time(hour=h, minute=m)

def slot_to_minutes(slot_idx: int) -> int:
    return slot_idx * 30

def minutes_to_str(total_minutes: int) -> str:
    if total_minutes >= 24 * 60:
        return "24:00"
    h = total_minutes // 60
    m = total_minutes % 60
    return f"{h:02d}:{m:02d}"

def format_duration(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    if h > 0 and m > 0:
        return f"{h} год {m} хв"
    elif h > 0:
        return f"{h} год"
    else:
        return f"{m} хв"

class ScheduleParser:
    @staticmethod
    def extract_day_schedule(graph_member: Dict[str, Any], group: str = config.CHER_GPV) -> Optional[Dict[str, Any]]:
        """
        Extracts date and times mapping for the requested group from a hydra:member entry.
        """
        if not graph_member:
            return None
            
        data_json = graph_member.get("dataJson", {})
        group_data = data_json.get(group)
        if not group_data and isinstance(data_json, dict):
            for k, v in data_json.items():
                if k.strip() == group.strip():
                    group_data = v
                    break
                    
        if not group_data:
            return None

        times = group_data.get("times", {})
        date_graph = graph_member.get("dateGraph", "")
        date_create = graph_member.get("dateCreate", "")

        return {
            "dateGraph": date_graph,
            "dateCreate": date_create,
            "times": times,
            "group": group
        }

    @staticmethod
    def get_intervals(times: Dict[str, str]) -> List[Dict[str, Any]]:
        """
        Groups 48 half-hour slots into contiguous status intervals.
        """
        slots = []
        for h in range(24):
            for m in (0, 30):
                slot_key = f"{h:02d}:{m:02d}"
                val = times.get(slot_key, STATUS_ON)
                slots.append((slot_key, val))

        intervals = []
        if not slots:
            return intervals

        curr_status = slots[0][1]
        start_idx = 0

        for i in range(1, len(slots)):
            status = slots[i][1]
            if status != curr_status:
                end_minutes = i * 30
                intervals.append({
                    "start": minutes_to_str(start_idx * 30),
                    "end": minutes_to_str(end_minutes),
                    "start_minutes": start_idx * 30,
                    "end_minutes": end_minutes,
                    "status": curr_status,
                    "label": STATUS_LABELS.get(curr_status, "Невідомо"),
                    "emoji": STATUS_EMOJIS.get(curr_status, "⚪")
                })
                curr_status = status
                start_idx = i

        intervals.append({
            "start": minutes_to_str(start_idx * 30),
            "end": "24:00",
            "start_minutes": start_idx * 30,
            "end_minutes": 24 * 60,
            "status": curr_status,
            "label": STATUS_LABELS.get(curr_status, "Невідомо"),
            "emoji": STATUS_EMOJIS.get(curr_status, "⚪")
        })

        return intervals

    @staticmethod
    def get_current_status(times: Dict[str, str], dt: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Determines current power status, active interval, and next change info based on times dict.
        """
        if dt is None:
            tz = ZoneInfo(config.TIMEZONE)
            dt = datetime.now(tz)

        curr_minutes = dt.hour * 60 + dt.minute
        intervals = ScheduleParser.get_intervals(times)

        current_interval = None
        next_interval = None

        for idx, interval in enumerate(intervals):
            if interval["start_minutes"] <= curr_minutes < interval["end_minutes"]:
                current_interval = interval
                if idx + 1 < len(intervals):
                    next_interval = intervals[idx + 1]
                break

        if not current_interval and intervals:
            current_interval = intervals[-1]

        minutes_remaining = 0
        if current_interval:
            minutes_remaining = max(0, current_interval["end_minutes"] - curr_minutes)

        return {
            "current_time": dt.strftime("%H:%M"),
            "current_interval": current_interval,
            "next_interval": next_interval,
            "minutes_remaining": minutes_remaining,
            "status": current_interval["status"] if current_interval else STATUS_ON,
            "label": current_interval["label"] if current_interval else "Світло є",
            "emoji": current_interval["emoji"] if current_interval else "🟢"
        }

    @staticmethod
    def generate_timeline_bar(times: Dict[str, str]) -> str:
        """
        Generates a visual timeline emoji bar representing 24 hours.
        """
        bar_chars = []
        for h in range(24):
            val00 = times.get(f"{h:02d}:00", STATUS_ON)
            val30 = times.get(f"{h:02d}:30", STATUS_ON)
            if val00 == STATUS_OFF or val30 == STATUS_OFF:
                bar_chars.append("🟥")
            elif val00 == STATUS_MAYBE or val30 == STATUS_MAYBE:
                bar_chars.append("🟨")
            else:
                bar_chars.append("🟩")

        line1 = "".join(bar_chars[:12]) + " (00:00 - 12:00)"
        line2 = "".join(bar_chars[12:]) + " (12:00 - 24:00)"
        return f"{line1}\n{line2}"

    @staticmethod
    def format_schedule_text(
        day_schedule: Dict[str, Any],
        title_prefix: str = "сьогодні",
        dt: Optional[datetime] = None
    ) -> str:
        """
        Builds a clean, logical, human-friendly HTML message describing the schedule for a given day.
        """
        times = day_schedule.get("times", {})
        date_graph = day_schedule.get("dateGraph", "")
        group = day_schedule.get("group", config.CHER_GPV)

        formatted_date = ""
        if date_graph:
            try:
                d = datetime.fromisoformat(date_graph.replace("Z", "+00:00"))
                formatted_date = d.strftime("%d.%m.%Y")
            except Exception:
                formatted_date = date_graph[:10]

        if dt is None:
            tz = ZoneInfo(config.TIMEZONE)
            dt = datetime.now(tz)

        curr_minutes = dt.hour * 60 + dt.minute
        is_today = "сьогодні" in title_prefix.lower()

        intervals = ScheduleParser.get_intervals(times)
        off_intervals = [i for i in intervals if i["status"] == STATUS_OFF]
        maybe_intervals = [i for i in intervals if i["status"] == STATUS_MAYBE]

        lines = [
            f"📅 <b>Графік на {title_prefix} ({formatted_date})</b>",
            f"📍 {config.short_address} (Черга {group})\n"
        ]

        if not off_intervals and not maybe_intervals:
            lines.append("🎉 <b>Відключень не заплановано! Світло буде весь день 🟢</b>\n")
        else:
            # Check if all outages have already passed today
            if is_today:
                upcoming_off = [i for i in off_intervals if i["end_minutes"] > curr_minutes]
                if not upcoming_off and off_intervals:
                    lines.append("🎉 <b>Усі відключення на сьогодні вже завершилися!</b>")
                    lines.append("Світло подається стабільно до кінця доби 🟢\n")
                    lines.append("<i>Сьогодні були відключення:</i>")
                    for i in off_intervals:
                        dur = format_duration(i["end_minutes"] - i["start_minutes"])
                        lines.append(f"  • {i['start']} — {i['end']} ({dur}) — <i>минуло</i>")
                    lines.append("")
                else:
                    lines.append("🔴 <b>Години відключень:</b>")
                    for i in off_intervals:
                        dur = format_duration(i["end_minutes"] - i["start_minutes"])
                        if i["end_minutes"] <= curr_minutes:
                            tag = " — <i>минуло</i>"
                        elif i["start_minutes"] <= curr_minutes < i["end_minutes"]:
                            tag = " ◀️ <b>зараз</b>"
                        else:
                            tag = ""
                        lines.append(f"  • <b>{i['start']} — {i['end']}</b> ({dur}){tag}")
                    lines.append("")
            else:
                lines.append("🔴 <b>Години відключень:</b>")
                for i in off_intervals:
                    dur = format_duration(i["end_minutes"] - i["start_minutes"])
                    lines.append(f"  • <b>{i['start']} — {i['end']}</b> ({dur})")
                lines.append("")

            if maybe_intervals:
                if is_today:
                    upcoming_maybe = [i for i in maybe_intervals if i["end_minutes"] > curr_minutes]
                    if upcoming_maybe:
                        lines.append("🟡 <b>Можливі відключення (за потреби):</b>")
                        for i in maybe_intervals:
                            if i["end_minutes"] <= curr_minutes:
                                tag = " — <i>минуло</i>"
                            elif i["start_minutes"] <= curr_minutes < i["end_minutes"]:
                                tag = " ◀️ <b>зараз</b>"
                            else:
                                tag = ""
                            lines.append(f"  • {i['start']} — {i['end']}{tag}")
                        lines.append("")
                else:
                    lines.append("🟡 <b>Можливі відключення (за потреби):</b>")
                    for i in maybe_intervals:
                        lines.append(f"  • {i['start']} — {i['end']}")
                    lines.append("")

        lines.append("📊 <b>Шкала доби:</b>")
        lines.append(ScheduleParser.generate_timeline_bar(times))
        lines.append("🟩 — світло є | 🟥 — вимкнення | 🟨 — можливе")

        return "\n".join(lines)

    @staticmethod
    def format_status_message(
        today_sched: Optional[Dict[str, Any]],
        tomorrow_sched: Optional[Dict[str, Any]] = None,
        dt: Optional[datetime] = None
    ) -> str:
        """
        Builds a human, logical real-time status message without robotic clutter.
        """
        if dt is None:
            tz = ZoneInfo(config.TIMEZONE)
            dt = datetime.now(tz)

        curr_time_str = dt.strftime("%H:%M")
        curr_minutes = dt.hour * 60 + dt.minute

        if not today_sched:
            formatted_today = dt.strftime("%d.%m.%Y")
            return (
                f"ℹ️ <b>Офіційний графік на сьогодні ({formatted_today}) відсутній на сайті обленерго.</b>\n"
                f"📍 {config.short_address} (Черга {config.CHER_GPV})\n"
                f"🕒 <b>Зараз:</b> {curr_time_str}\n\n"
                "💡 За плановим погодинним розкладом даних немає.\n"
                "⚠️ <b>Якщо світла немає зараз, причини:</b>\n"
                "• <b>Аварійне відключення (ГАВ/СГАВ)</b> за командою «Укренерго»\n"
                "• <b>Позапланові ремонтні роботи</b> на лініях електромереж\n"
                "• Затримка публікації погодинного графіка сервером обленерго\n\n"
                "<i>Бот щохвилини перевіряє базу обленерго і сповістить, щойно дані з'являться.</i>"
            )

        times = today_sched.get("times", {})
        status_info = ScheduleParser.get_current_status(times, dt)
        curr_status = status_info["status"]
        curr_interval = status_info["current_interval"]
        mins_left = status_info["minutes_remaining"]
        time_left_str = format_duration(mins_left)

        intervals = ScheduleParser.get_intervals(times)
        off_intervals = [i for i in intervals if i["status"] == STATUS_OFF]
        maybe_intervals = [i for i in intervals if i["status"] == STATUS_MAYBE]

        # Upcoming outages today (strictly after current time)
        upcoming_off = [i for i in off_intervals if i["start_minutes"] > curr_minutes]
        upcoming_maybe = [i for i in maybe_intervals if i["start_minutes"] > curr_minutes]

        lines = []

        if curr_status == STATUS_OFF:
            # 🔴 Outage right now
            end_time = curr_interval["end"] if curr_interval else "кінця інтервалу"
            lines.append("🔴 <b>СВІТЛА НЕМАЄ</b>\n")
            lines.append(f"📍 {config.short_address} (Черга {config.CHER_GPV})")
            lines.append(f"🕒 <b>Зараз:</b> {curr_time_str}\n")
            lines.append(f"💡 <b>Орієнтовне увімкнення:</b> о <b>{end_time}</b>")
            lines.append(f"⏳ Залишилось чекати: <b>{time_left_str}</b>")

            if upcoming_off:
                next_off = upcoming_off[0]
                lines.append(f"\n⏭ Наступне вимкнення сьогодні: <b>{next_off['start']} — {next_off['end']}</b>")
            else:
                lines.append("\n🎉 <i>Після цього вимкнень на сьогодні більше не заплановано.</i>")

        elif curr_status == STATUS_MAYBE:
            # 🟡 Possible outage right now
            end_time = curr_interval["end"] if curr_interval else "кінця інтервалу"
            lines.append("🟡 <b>МОЖЛИВЕ ВІДКЛЮЧЕННЯ</b>\n")
            lines.append(f"📍 {config.short_address} (Черга {config.CHER_GPV})")
            lines.append(f"🕒 <b>Зараз:</b> {curr_time_str}\n")
            lines.append(f"⚠️ Зона можливого відключення: <b>до {end_time}</b> (залишилось {time_left_str})")
            lines.append("<i>Світло вимикається лише у разі перевищення лімітів.</i>")

            if upcoming_off:
                next_off = upcoming_off[0]
                wait_off = format_duration(next_off["start_minutes"] - curr_minutes)
                lines.append(f"\n🔴 Точне вимкнення: о <b>{next_off['start']}</b> (через {wait_off})")

        else:
            # 🟢 Power is ON
            lines.append("🟢 <b>СВІТЛО Є</b>\n")
            lines.append(f"📍 {config.short_address} (Черга {config.CHER_GPV})")
            lines.append(f"🕒 <b>Зараз:</b> {curr_time_str}\n")

            if upcoming_off:
                next_off = upcoming_off[0]
                wait_time = format_duration(next_off["start_minutes"] - curr_minutes)
                dur = format_duration(next_off["end_minutes"] - next_off["start_minutes"])
                lines.append("⏳ <b>Наступне відключення:</b>")
                lines.append(f"О <b>{next_off['start']}</b> (через {wait_time}) — триватиме до <b>{next_off['end']}</b> ({dur})")

                if len(upcoming_off) > 1:
                    later_ranges = ", ".join([f"{i['start']}–{i['end']}" for i in upcoming_off[1:]])
                    lines.append(f"<i>Також пізніше сьогодні: {later_ranges}</i>")
            elif upcoming_maybe:
                next_m = upcoming_maybe[0]
                wait_time = format_duration(next_m["start_minutes"] - curr_minutes)
                lines.append(f"🟡 Наступне можливе відключення: о <b>{next_m['start']}</b> (через {wait_time})")
            else:
                # No more outages today!
                lines.append("🎉 <b>На сьогодні відключень більше немає!</b>")
                lines.append("До кінця доби світло подаватиметься стабільно 🟢\n")

                # Show info about tomorrow if available
                if tomorrow_sched:
                    t_times = tomorrow_sched.get("times", {})
                    t_intervals = ScheduleParser.get_intervals(t_times)
                    t_off = [i for i in t_intervals if i["status"] == STATUS_OFF]
                    if t_off:
                        first_t = t_off[0]
                        lines.append(f"📅 <i>Завтра перше вимкнення: о <b>{first_t['start']}</b> (до {first_t['end']})</i>")
                    else:
                        lines.append("📅 <i>На завтра відключень також не заплановано 🎉</i>")
                else:
                    if dt.hour >= 20:
                        lines.append("📅 <i>Графік на завтра обленерго зазвичай оприлюднює ввечері.</i>")

        return "\n".join(lines)

    @staticmethod
    def format_daily_digest(day_schedule: Dict[str, Any]) -> str:
        """
        Builds a compact morning overview for the daily digest.
        """
        times = day_schedule.get("times", {})
        date_graph = day_schedule.get("dateGraph", "")
        formatted_date = ""
        if date_graph:
            try:
                d = datetime.fromisoformat(date_graph.replace("Z", "+00:00"))
                formatted_date = d.strftime("%d.%m.%Y")
            except Exception:
                formatted_date = date_graph[:10]

        intervals = ScheduleParser.get_intervals(times)
        off_intervals = [i for i in intervals if i["status"] == STATUS_OFF]
        maybe_intervals = [i for i in intervals if i["status"] == STATUS_MAYBE]

        lines = [
            f"☕️ <b>Доброго ранку! Графік на сьогодні ({formatted_date})</b>",
            f"📍 {config.short_address} (Черга {config.CHER_GPV})\n"
        ]

        if not off_intervals and not maybe_intervals:
            lines.append("🎉 <b>Сьогодні вимкнень не заплановано!</b> Світло буде весь день 🟢")
        else:
            if off_intervals:
                lines.append("🔴 <b>Години відключень:</b>")
                for i in off_intervals:
                    dur_str = format_duration(i["end_minutes"] - i["start_minutes"])
                    lines.append(f"  • <b>{i['start']} — {i['end']}</b> ({dur_str})")
                lines.append("")

            if maybe_intervals:
                lines.append("🟡 <b>Можливі відключення:</b>")
                for i in maybe_intervals:
                    lines.append(f"  • {i['start']} — {i['end']}")
                lines.append("")

            lines.append("🟢 <i>У решту годин світло подається безперебійно. Гарного дня!</i>")

        return "\n".join(lines)
