import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    CHECK_INTERVAL_SECONDS: int = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))
    
    # Target address configuration:
    # Бережани (Бережанська ОТГ), вул. Героїв Майдану, буд. 2-А
    OTG_ID: int = int(os.getenv("OTG_ID", "17"))
    OTG_NAME: str = os.getenv("OTG_NAME", "Бережанська ОТГ")
    
    CITY_ID: int = int(os.getenv("CITY_ID", "136"))
    CITY_NAME: str = os.getenv("CITY_NAME", "Бережани")
    
    STREET_ID: int = int(os.getenv("STREET_ID", "1663"))
    STREET_NAME: str = os.getenv("STREET_NAME", "вул. Героїв Майдану")
    
    BUILDING_NAME: str = os.getenv("BUILDING_NAME", "2-А")
    CHER_GPV: str = os.getenv("CHER_GPV", "2.1")
    
    DB_PATH: str = os.getenv("DB_PATH", "bot_data.db")
    TIMEZONE: str = os.getenv("TIMEZONE", "Europe/Kyiv")

config = Config()
