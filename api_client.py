import base64
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo
import aiohttp
from config import config

logger = logging.getLogger(__name__)

BASE_URL = "https://api-poweron.toe.com.ua/api"

class ToeApiClient:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=20)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                }
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_schedule(
        self,
        city_id: int = config.CITY_ID,
        street_id: int = config.STREET_ID,
        building_name: str = config.BUILDING_NAME,
        group: str = config.CHER_GPV
    ) -> List[Dict[str, Any]]:
        """
        Fetches today's and tomorrow's GPV schedule for the specified address and queue.
        """
        tz = ZoneInfo(config.TIMEZONE)
        now = datetime.now(tz)
        
        # In poweron frontend:
        # yesterday = now.subtract(1, 'day').startOf('day').format("YYYY-MM-DDT12:00:00+00:00")
        # tomorrow = now.add(1, 'day').startOf('day').format("YYYY-MM-DDTHH:mm:ss+00:00")
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%dT12:00:00+00:00")
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        
        c_val = f"{city_id}/{street_id}/{building_name}"
        x_debug_key = base64.b64encode(c_val.encode("utf-8")).decode("ascii")

        params = {
            "before": tomorrow,
            "after": yesterday,
            "group[]": group,
            "time": c_val.replace("/", "")
        }

        headers = {
            "X-debug-key": x_debug_key
        }

        session = await self.get_session()
        try:
            async with session.get(f"{self.base_url}/a_gpv_g", params=params, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    members = data.get("hydra:member", [])
                    return members
                else:
                    text = await resp.text()
                    logger.error(f"Error fetching schedule: HTTP {resp.status} - {text[:200]}")
                    return []
        except Exception as e:
            logger.error(f"Exception during get_schedule: {e}")
            return []

    async def get_accidents(
        self,
        otg_id: int = config.OTG_ID,
        city_id: int = config.CITY_ID,
        street_id: int = config.STREET_ID
    ) -> List[Dict[str, Any]]:
        """
        Fetches unplanned/emergency outages.
        """
        session = await self.get_session()
        params = {
            "page": 1,
            "otg.id": otg_id,
            "city.id": city_id,
            "street.id": street_id
        }
        try:
            async with session.get(f"{self.base_url}/pw_accidents", params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data if isinstance(data, list) else data.get("hydra:member", [])
                return []
        except Exception as e:
            logger.error(f"Exception during get_accidents: {e}")
            return []

    async def get_planed_accidents(
        self,
        otg_id: int = config.OTG_ID,
        city_id: int = config.CITY_ID,
        street_id: int = config.STREET_ID
    ) -> List[Dict[str, Any]]:
        """
        Fetches planned repair outages.
        """
        session = await self.get_session()
        params = {
            "page": 1,
            "otg.id": otg_id,
            "city.id": city_id,
            "street.id": street_id
        }
        try:
            async with session.get(f"{self.base_url}/pw_accident_planeds", params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data if isinstance(data, list) else data.get("hydra:member", [])
                return []
        except Exception as e:
            logger.error(f"Exception during get_planed_accidents: {e}")
            return []
