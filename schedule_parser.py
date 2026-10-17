import logging
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Tuple, Any
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
            # Try to match without trailing/leading spaces or fallback to first key
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
        Returns list of intervals with start_time, end_time, status, status_label, emoji.
        """
        # All 48 slots in order
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

        # Last interval
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

        # Calculate minutes remaining until next change
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
            # If both are off -> red square
            # If both are on -> green square
            # If maybe -> yellow square
            if val00 == STATUS_OFF or val30 == STATUS_OFF:
                bar_chars.append("🟥")
            elif val00 == STATUS_MAYBE or val30 == STATUS_MAYBE:
                bar_chars.append("🟨")
            else:
                bar_chars.append("🟩")

        # Split in 2 lines of 12 hours for readability on mobile
        line1 = "".join(bar_chars[:12]) + " (00:00 - 12:00)"
        line2 = "".join(bar_chars[12:]) + " (12:00 - 24:00)"
        return f"{line1}\n{line2}"

    @staticmethod
    def format_schedule_text(
        day_schedule: Dict[str, Any],
        title_prefix: str = "Сьогодні"
    ) -> str:
        """
        Builds a rich formatted HTML message describing the schedule for a given day.
        """
        times = day_schedule.get("times", {})
        date_graph = day_schedule.get("dateGraph", "")
        date_create = day_schedule.get("dateCreate", "")
        group = day_schedule.get("group", config.CHER_GPV)

        # Parse dates
        formatted_date = ""
        if date_graph:
            try:
                d = datetime.fromisoformat(date_graph.replace("Z", "+00:00"))
                formatted_date = d.strftime("%d.%m.%Y")
            except Exception:
                formatted_date = date_graph[:10]

        formatted_updated = ""
        if date_create:
            try:
                d = datetime.fromisoformat(date_create.replace("Z", "+00:00"))
                # Convert to Kyiv tz
                tz = ZoneInfo(config.TIMEZONE)
                d = d.astimezone(tz)
                formatted_updated = d.strftime("%d.%m.%Y %H:%M")
            except Exception:
                formatted_updated = date_create[:16]

        intervals = ScheduleParser.get_intervals(times)
        
        # Categorize intervals
        off_intervals = [i for i in intervals if i["status"] == STATUS_OFF]
        maybe_intervals = [i for i in intervals if i["status"] == STATUS_MAYBE]

        lines = [
            f"📅 <b>Графік на {title_prefix} ({formatted_date})</b>",
            f"📍 <b>Адреса:</b> м. {config.CITY_NAME}, {config.STREET_NAME}, буд. {config.BUILDING_NAME}",
            f"⚡️ <b>Черга:</b> {group}",
        ]
        if formatted_updated:
            lines.append(f"🕒 <i>Оновлено: {formatted_updated}</i>")

        lines.append("")
        lines.append("📊 <b>Візуальна шкала:</b>")
        lines.append(ScheduleParser.generate_timeline_bar(times))
        lines.append("🟩 — світло є | 🟥 — відключення | 🟨 — можливе")
        lines.append("")

        if not off_intervals and not maybe_intervals:
            lines.append("🎉 <b>Відключень не заплановано! Світло буде весь день.</b>")
        else:
            if off_intervals:
                lines.append("🔴 <b>Години відключення (світла немає):</b>")
                for i in off_intervals:
                    lines.append(f"  • <b>{i['start']} — {i['end']}</b>")
                lines.append("")

            if maybe_intervals:
                lines.append("🟡 <b>Можливе вимкнення (за потреби):</b>")
                for i in maybe_intervals:
                    lines.append(f"  • <b>{i['start']} — {i['end']}</b>")
                lines.append("")

        return "\n".join(lines)
