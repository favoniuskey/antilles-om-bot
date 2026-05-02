import discord
from discord.ext import commands, tasks
import asyncio
import logging
from datetime import datetime, timezone, timedelta
import json
import aiohttp
import os
import traceback
import random
import re
from bs4 import BeautifulSoup
from typing import Dict, Any, Tuple, List, Optional, Union

from dotenv import load_dotenv

load_dotenv()

IVAO_API_KEY = os.getenv("IVAO_API_KEY", "")
if not IVAO_API_KEY:
    raise ValueError("IVAO_API_KEY non définie dans .env")


# ------------------------------------------------------------------ #
# Logging
# ------------------------------------------------------------------ #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("utils/logs/monitoring.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Rate limiter
# ------------------------------------------------------------------ #

class DiscordRateLimiter:
    """Gère le rate limiting pour les opérations Discord."""

    def __init__(self, delay: float = 1.2):
        self.delay = delay
        self.last_operation: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait_if_needed(self, operation_key: str = "default"):
        async with self._lock:
            current_time = asyncio.get_event_loop().time()
            last_time = self.last_operation.get(operation_key, 0)
            time_since_last = current_time - last_time
            if time_since_last < self.delay:
                await asyncio.sleep(self.delay - time_since_last)
            self.last_operation[operation_key] = asyncio.get_event_loop().time()


# ------------------------------------------------------------------ #
# Message cache
# ------------------------------------------------------------------ #

class MessageCache:
    """Cache pour les messages Discord validés."""

    def __init__(self):
        self._cache: Dict[str, discord.Message] = {}
        self._last_validation: Dict[str, float] = {}
        self._validation_timeout = 300
        self._lock = asyncio.Lock()

    async def get_message(
        self,
        message_type: str,
        channel: discord.TextChannel,
        message_id: Optional[str],
    ) -> Optional[discord.Message]:
        if not message_id:
            return None

        async with self._lock:
            current_time = asyncio.get_event_loop().time()
            if (
                message_type in self._cache
                and message_type in self._last_validation
                and current_time - self._last_validation[message_type] < self._validation_timeout
            ):
                return self._cache[message_type]

            try:
                message = await channel.fetch_message(int(message_id))
                self._cache[message_type] = message
                self._last_validation[message_type] = current_time
                return message
            except (discord.errors.NotFound, discord.errors.Forbidden, ValueError):
                self._cache.pop(message_type, None)
                self._last_validation.pop(message_type, None)
                return None
            except Exception as e:
                logger.warning("Erreur validation message %s: %s", message_type, e)
                return None

    async def invalidate(self, message_type: str):
        async with self._lock:
            self._cache.pop(message_type, None)
            self._last_validation.pop(message_type, None)


# ------------------------------------------------------------------ #
# Cog principal
# ------------------------------------------------------------------ #

class EnhancedMonitoring(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self.STATUS_MESSAGE: Optional[discord.Message] = None
        self.LAST_CONTROLLER_MESSAGE: Optional[discord.Message] = None

        self.auto_setup_complete = False
        self.setup_retries = 0
        self.max_retries = 5

        self.session: Optional[aiohttp.ClientSession] = None
        self.ivao_session: Optional[aiohttp.ClientSession] = None

        self.last_update_attempt = 0
        self.failed_attempts = 0
        self._message_lock = asyncio.Lock()

        self.rate_limiter = DiscordRateLimiter(1.2)
        self.message_cache = MessageCache()
        self.heartbeat_counter = 0
        self.last_successful_update = datetime.now(timezone.utc)
        self.system_health = "healthy"

        self.CHANNEL_ID = 1310926262566387753
        self.apikey = IVAO_API_KEY
        self.ATC_URL = "https://api.ivao.aero/v2/tracker/now/atc"
        self.CACHE_FILE = "utils/atc_positions_cache.json"
        self.MESSAGE_ID_FILE = "utils/status_message_id.json"
        self.USER_CACHE_FILE = "utils/user_name_cache.json"
        self.LAST_CONTROLLER_FILE = "utils/last_controller.json"
        self.USER_VID = "722124"
        self.USER_PASSWORD = "1ICGmIBMJP0Y"

        os.makedirs("utils", exist_ok=True)
        os.makedirs("utils/logs", exist_ok=True)

        self.setup_regions_and_positions()
        self.name_cache = self.load_user_name_cache()

        self.update_positions.start()
        self.auto_setup_task.start()
        self.update_status_table.start()

    # ------------------------------------------------------------------ #
    # Régions / positions
    # ------------------------------------------------------------------ #

    def setup_regions_and_positions(self):
        self.REGIONS = {
            "ANTILLES": {
                "emoji": "🏝️",
                "color": 0x3498DB,
                "positions": [
                    "TFFF_APP", "TFFF_DEL", "TFFF_TWR",
                    "TFFR_APP", "TFFR_TWR",
                    "TFFJ_FIS_TWR", "TFFJ_I_TWR",
                    "TFFG_FIS_TWR", "TFFG_I_TWR",
                    "TFFM_I_TWR",
                ],
            },
            "GUYANE": {
                "emoji": "🌳",
                "color": 0x27AE60,
                "positions": ["SOCA_APP", "SOCA_TWR", "SOOO_CTR", "SOOO_MIL_CTR"],
            },
            "POLYNÉSIE": {
                "emoji": "🌺",
                "color": 0xE74C3C,
                "positions": [
                    "NTAA_APP", "NTAA_DEL", "NTAA_TWR",
                    "NTTB_TWR",
                    "NTTH_FIS_TWR", "NTTH_I_TWR",
                    "NTTM_TWR", "NTTR_TWR",
                    "NTTG_FIS_TWR", "NTTG_I_TWR",
                    "NTTT_CTR",
                    "NTAR_FIS_TWR", "NTAR_I_TWR",
                    "NTAT_FIS_TWR", "NTAT_I_TWR",
                    "NTAV_FIS_TWR", "NTAV_I_TWR",
                    "NTGC_FIS_TWR", "NTGC_I_TWR",
                    "NTGF_FIS_TWR", "NTGF_I_TWR",
                    "NTGI_FIS_TWR", "NTGI_I_TWR",
                    "NTGJ_FIS_TWR", "NTGJ_I_TWR",
                    "NTGK_FIS_TWR", "NTGK_I_TWR",
                    "NTGM_FIS_TWR", "NTGM_I_TWR",
                    "NTGT_FIS_TWR", "NTGT_I_TWR",
                    "NTGU_FIS_TWR", "NTGU_I_TWR",
                    "NTGV_FIS_TWR", "NTGV_I_TWR",
                    "NTMD_FIS_TWR", "NTMD_I_TWR",
                    "NTMN_FIS_TWR", "NTMN_I_TWR",
                    "NTMP_FIS_TWR", "NTMP_I_TWR",
                    "NTMU_FIS_TWR", "NTMU_I_TWR",
                    "NTTO_FIS_TWR", "NTTO_I_TWR",
                    "NTTP_FIS_TWR", "NTTP_I_TWR",
                ],
            },
            "RÉUNION_MAYOTTE": {
                "emoji": "🌋",
                "color": 0xF39C12,
                "positions": [
                    "FMEE_APP", "FMEE_GND", "FMEE_TWR",
                    "FMEP_FIS_TWR", "FMEP_I_TWR",
                    "FMCZ_TWR",
                ],
            },
            "NOUVELLE_CALÉDONIE": {
                "emoji": "🐠",
                "color": 0x9B59B6,
                "positions": [
                    "NWWW_APP", "NWWW_GND", "NWWW_TWR",
                    "NWWM_APP", "NWWM_TWR",
                    "NWWL_FIS_TWR",
                    "NWWD_FIS_TWR", "NWWD_I_TWR",
                    "NWWE_FIS_TWR", "NWWE_I_TWR",
                    "NWWR_FIS_TWR", "NWWR_I_TWR",
                    "NWWU_FIS_TWR", "NWWU_I_TWR",
                    "NWWV_FIS_TWR", "NWWV_I_TWR",
                ],
            },
            "WALLIS_FUTUNA": {
                "emoji": "🏖️",
                "color": 0x1ABC9C,
                "positions": [
                    "NLWW_FIS_TWR", "NLWW_I_TWR",
                    "NLWF_FIS_TWR", "NLWF_I_TWR",
                ],
            },
            "SPM": {
                "emoji": "❄️",
                "color": 0x34495E,
                "positions": [
                    "LFVP_APP", "LFVP_TWR",
                    "LFVM_FIS_TWR", "LFVM_I_TWR",
                ],
            },
        }

        self.MONITORED_POSITIONS: List[str] = []
        for region in self.REGIONS.values():
            self.MONITORED_POSITIONS.extend(region["positions"])

        self.POSITION_TYPES = {
            "TWR": {"emoji": "🗼", "name": "Tour"},
            "APP": {"emoji": "🛬", "name": "Approche"},
            "CTR": {"emoji": "🌐", "name": "Centre"},
            "DEL": {"emoji": "🧾", "name": "Délivrance"},
            "GND": {"emoji": "🚜", "name": "Sol"},
            "FIS": {"emoji": "🔭", "name": "Info Vol"},
            "I":   {"emoji": "🔧", "name": "Maintenance"},
        }

        self.IVAO_RATINGS = {
            2: "AS1", 3: "AS2", 4: "AS3",
            5: "ADC", 6: "APC", 7: "ACC",
            8: "SEC", 9: "SAI", 10: "CAI",
        }

    # ------------------------------------------------------------------ #
    # Utilitaires état système
    # ------------------------------------------------------------------ #

    def get_heartbeat_emoji(self) -> str:
        emojis = ["💚", "💛", "❤️", "🧡", "💜", "💙"]
        return emojis[self.heartbeat_counter % len(emojis)]

    def get_system_status_emoji(self) -> str:
        if self.system_health == "healthy":
            return "🟢"
        if self.system_health == "warning":
            return "🟡"
        return "🔴"

    def update_system_health(self):
        secs = (datetime.now(timezone.utc) - self.last_successful_update).total_seconds()
        if secs < 60:
            self.system_health = "healthy"
        elif secs < 300:
            self.system_health = "warning"
        else:
            self.system_health = "error"

    # ------------------------------------------------------------------ #
    # Cycle de vie
    # ------------------------------------------------------------------ #

    def cog_unload(self):
        self.update_positions.cancel()
        self.auto_setup_task.cancel()
        if hasattr(self, "update_status_table") and self.update_status_table.is_running():
            self.update_status_table.cancel()
        if self.session:
            asyncio.create_task(self.close_session())

    async def close_session(self):
        if self.session:
            await self.session.close()
            self.session = None
        if self.ivao_session:
            await self.ivao_session.close()
            self.ivao_session = None

    async def init_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
        if not self.ivao_session:
            self.ivao_session = aiohttp.ClientSession()

    # ------------------------------------------------------------------ #
    # Auto-setup
    # ------------------------------------------------------------------ #

    @tasks.loop(seconds=10, count=None)
    async def auto_setup_task(self):
        if self.auto_setup_complete:
            self.auto_setup_task.cancel()
            return
        if not self.bot.is_ready():
            return
        try:
            success = await self.setup_monitoring()
            if success:
                logger.info("Auto-setup réussi")
                self.auto_setup_complete = True
                self.auto_setup_task.cancel()
            else:
                self.setup_retries += 1
                logger.warning("Echec auto-setup %s/%s", self.setup_retries, self.max_retries)
                if self.setup_retries >= self.max_retries:
                    logger.error("Max tentatives auto-setup atteint, intervalle 5 min")
                    self.auto_setup_task.change_interval(minutes=5)
                    self.setup_retries = 0
        except Exception as e:
            logger.error("Erreur auto-setup: %s", e)
            self.setup_retries += 1
            if self.setup_retries >= self.max_retries:
                self.auto_setup_task.change_interval(minutes=5)
                self.setup_retries = 0

    @auto_setup_task.before_loop
    async def before_auto_setup(self):
        await self.bot.wait_until_ready()
        logger.info("Bot prêt, tâche d'auto-setup démarrée")

    # ------------------------------------------------------------------ #
    # Formatage
    # ------------------------------------------------------------------ #

    def format_duration(self, seconds: float, compact: bool = False) -> str:
        if not seconds or seconds < 0:
            seconds = 0
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h{minutes:02d}m" if compact else f"{hours:02d}h {minutes:02d}min"

    def format_time_ago(self, timestamp: int) -> str:
        if not timestamp or timestamp <= 0:
            return "récemment"
        try:
            secs = (datetime.now(timezone.utc) - datetime.fromtimestamp(timestamp, timezone.utc)).total_seconds()
        except (ValueError, OverflowError, OSError):
            return "récemment"
        if secs < 60:
            return "il y a quelques instants"
        if secs < 3600:
            m = int(secs // 60)
            return f"il y a {m} minute{'s' if m > 1 else ''}"
        if secs < 86400:
            h = int(secs // 3600)
            return f"il y a {h} heure{'s' if h > 1 else ''}"
        d = int(secs // 86400)
        return f"il y a {d} jour{'s' if d > 1 else ''}"

    def get_position_type(self, position: str) -> str:
        if not position:
            return "OTHER"
        for key in ("_CTR", "_APP", "_TWR", "_DEL", "_GND", "_FIS"):
            if key in position:
                return key[1:]
        if "_I_" in position or position.endswith("_I"):
            return "I"
        return "OTHER"

    def get_position_region(self, position: str) -> str:
        for region_name, region_data in self.REGIONS.items():
            if position in region_data["positions"]:
                return region_name
        return "Autre"

    # ------------------------------------------------------------------ #
    # Cache fichiers
    # ------------------------------------------------------------------ #

    def load_atc_cache(self) -> Dict[str, Any]:
        try:
            with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"active": {}, "recent": {}}

    def save_atc_cache(self, data: Dict[str, Any]) -> bool:
        try:
            os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error("Erreur sauvegarde cache ATC: %s", e)
            return False

    def load_user_name_cache(self) -> Dict[str, Any]:
        try:
            with open(self.USER_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_user_name_cache(self):
        try:
            os.makedirs(os.path.dirname(self.USER_CACHE_FILE), exist_ok=True)
            with open(self.USER_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.name_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Erreur sauvegarde cache noms: %s", e)

    def save_message_id(
        self,
        message_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        last_controller_message_id: Optional[int] = None,
    ) -> bool:
        data = {
            "message_id": str(message_id) if message_id else None,
            "channel_id": channel_id or self.CHANNEL_ID,
            "last_controller_message_id": str(last_controller_message_id) if last_controller_message_id else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            os.makedirs(os.path.dirname(self.MESSAGE_ID_FILE), exist_ok=True)
            with open(self.MESSAGE_ID_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("ID message sauvegardé: %s", message_id)
            return True
        except Exception as e:
            logger.error("Erreur sauvegarde ID message: %s", e)
            return False

    def load_message_id(self) -> Tuple[Optional[str], int, Optional[str]]:
        try:
            with open(self.MESSAGE_ID_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return (
                data.get("message_id"),
                data.get("channel_id", self.CHANNEL_ID),
                data.get("last_controller_message_id"),
            )
        except (FileNotFoundError, json.JSONDecodeError):
            return None, self.CHANNEL_ID, None

    def save_last_controller(self, controller_data: Dict[str, Any]) -> bool:
        try:
            controller_data["saved_at"] = datetime.now(timezone.utc).isoformat()
            os.makedirs(os.path.dirname(self.LAST_CONTROLLER_FILE), exist_ok=True)
            with open(self.LAST_CONTROLLER_FILE, "w", encoding="utf-8") as f:
                json.dump(controller_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error("Erreur sauvegarde dernier contrôleur: %s", e)
            return False

    def load_last_controller(self) -> Dict[str, Any]:
        try:
            with open(self.LAST_CONTROLLER_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    # ------------------------------------------------------------------ #
    # Nom utilisateur IVAO
    # ------------------------------------------------------------------ #

    async def get_user_name_from_vid(self, vid: int) -> Tuple[str, str]:
        if not vid:
            return "Unknown", "User"

        vid_str = str(vid)
        if vid_str in self.name_cache:
            entry = self.name_cache[vid_str]
            if "updated_at" in entry:
                try:
                    cache_time = datetime.fromisoformat(entry["updated_at"].replace("Z", "+00:00"))
                    if (datetime.now(timezone.utc) - cache_time).days < 7:
                        return entry["first_name"], entry["last_name"]
                except Exception:
                    pass
            else:
                return entry["first_name"], entry["last_name"]

        try:
            await self.init_session()
            login_url = "https://ivao.aero/Login.aspx"
            profile_url = f"https://ivao.aero/Member.aspx?Id={vid}"

            async with self.session.get(login_url, params={"r": f"Member.aspx?Id={vid}"}) as resp:
                if resp.status != 200:
                    return "Unknown", "User"
                soup = BeautifulSoup(await resp.text(), "html.parser")

            def get_input(name):
                el = soup.find("input", {"name": name})
                return el["value"] if el else ""

            try:
                post_url = soup.find("input", {"name": "ctl00$ContentPlaceHolder1$postUrl"})["value"]
            except Exception:
                post_url = profile_url

            login_data = {
                "__VIEWSTATE": get_input("__VIEWSTATE"),
                "__VIEWSTATEGENERATOR": get_input("__VIEWSTATEGENERATOR"),
                "__EVENTVALIDATION": get_input("__EVENTVALIDATION"),
                "ctl00$ContentPlaceHolder1$postUrl": post_url,
                "ctl00$ContentPlaceHolder1$loginVID": self.USER_VID,
                "ctl00$ContentPlaceHolder1$loginPassword": self.USER_PASSWORD,
                "ctl00$ContentPlaceHolder1$loginRemember": "on",
                "ctl00$ContentPlaceHolder1$loginBtn": "Login",
            }

            async with self.session.post(login_url, data=login_data, allow_redirects=True) as resp:
                if resp.status != 200:
                    return "Unknown", "User"

            async with self.session.get(profile_url) as resp:
                if resp.status != 200:
                    return "Unknown", "User"
                soup = BeautifulSoup(await resp.text(), "html.parser")

            name_el = soup.find("h3")
            if name_el:
                parts = name_el.text.strip().split()
                first_name = " ".join(parts[:-1]) if len(parts) >= 2 else parts[0]
                last_name = parts[-1] if len(parts) >= 2 else ""
                self.name_cache[vid_str] = {
                    "first_name": first_name,
                    "last_name": last_name,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                self.save_user_name_cache()
                return first_name, last_name

        except Exception as e:
            logger.error("Erreur récupération nom VID %s: %s", vid, e)

        return "Unknown", "User"

    def format_controller_name(self, first_name: str, last_name: str, user_id: int) -> str:
        if first_name == "Unknown" or not last_name:
            return f"Inconnu (VID: {user_id})"
        return f"{first_name} {last_name[0]}. (VID: {user_id})"

    # ------------------------------------------------------------------ #
    # Cache ATC
    # ------------------------------------------------------------------ #

    async def update_atc_cache(self) -> bool:
        try:
            headers = {"apiKey": self.apikey, "Accept": "application/json"}
            await self.init_session()

            async with self.session.get(self.ATC_URL, headers=headers) as response:
                if response.status != 200:
                    logger.error("Erreur API IVAO ATC %s", response.status)
                    return False

                all_controllers = await response.json()

            current_cache = self.load_atc_cache()
            active_positions: Dict[str, Dict[str, Any]] = {}

            for controller in all_controllers:
                atc_position = controller.get("atcPosition")
                if not atc_position:
                    continue
                callsign = atc_position.get("composePosition")
                if callsign not in self.MONITORED_POSITIONS:
                    continue

                user_id = controller.get("userId", "N/A")
                created_at = controller.get("createdAt", "")
                try:
                    start_time = int(datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp())
                except Exception:
                    start_time = int(datetime.now(timezone.utc).timestamp())

                first_name, last_name = "Unknown", "User"
                if user_id and user_id != "N/A":
                    try:
                        first_name, last_name = await self.get_user_name_from_vid(user_id)
                    except Exception as e:
                        logger.error("Erreur nom VID %s: %s", user_id, e)

                rating_id = controller.get("user", {}).get("rating", {}).get("atcRatingId", 0)
                active_positions[callsign] = {
                    "vid": user_id,
                    "rating": self.IVAO_RATINGS.get(rating_id, "Unknown"),
                    "start_time": start_time,
                    "first_name": first_name,
                    "last_name": last_name,
                    "position_type": self.get_position_type(callsign),
                }

            previous_active = current_cache.get("active", {})
            now_ts = int(datetime.now(timezone.utc).timestamp())
            recent_positions = current_cache.get("recent", {})

            for callsign, info in previous_active.items():
                if callsign not in active_positions:
                    controller_data = {
                        "vid": info.get("vid", "N/A"),
                        "rating": info.get("rating", "Unknown"),
                        "start_time": info.get("start_time", 0),
                        "end_time": now_ts,
                        "duration": now_ts - info.get("start_time", now_ts),
                        "first_name": info.get("first_name", "Unknown"),
                        "last_name": info.get("last_name", "User"),
                        "position_type": info.get("position_type", self.get_position_type(callsign)),
                        "callsign": callsign,
                        "region": self.get_position_region(callsign),
                    }
                    recent_positions[callsign] = controller_data
                    self.save_last_controller(controller_data)

            if len(recent_positions) > 20:
                recent_positions = dict(
                    sorted(recent_positions.items(), key=lambda x: x[1].get("end_time", 0), reverse=True)[:20]
                )

            self.save_atc_cache({"active": active_positions, "recent": recent_positions, "last_update": now_ts})
            self.last_successful_update = datetime.now(timezone.utc)
            return True

        except Exception as e:
            logger.error("Erreur update_atc_cache: %s", e)
            logger.error(traceback.format_exc())
            return False

    # ------------------------------------------------------------------ #
    # Construction des embeds
    # ------------------------------------------------------------------ #

    def create_table_overview(self, active_sessions: Dict[str, Any], region_name: Optional[str] = None) -> str:
        if region_name:
            filtered = {k: v for k, v in active_sessions.items() if self.get_position_region(k) == region_name}
        else:
            filtered = active_sessions

        if not filtered:
            msg = f"dans la région {region_name}" if region_name else "ATC"
            return f"```yaml\n# Aucune position active {msg} actuellement\n```"

        header = f"{'Position':<15} | {'Contrôleur':<18} | {'VID':<7} | {'Rating':<5} | {'Durée':<12}"
        lines = [header, "-" * 70]

        for callsign, info in sorted(filtered.items()):
            fn, ln, vid = info.get("first_name", "Unknown"), info.get("last_name", "User"), info.get("vid", "N/A")
            name = f"{fn} {ln[0]}."[:18] if fn != "Unknown" and ln else "Inconnu"
            st = info.get("start_time", 0)
            try:
                dur = self.format_duration((datetime.now(timezone.utc) - datetime.fromtimestamp(st, timezone.utc)).total_seconds(), compact=True) if st else "N/A"
            except Exception:
                dur = "N/A"
            lines.append(f"{callsign:<15} | {name:<18} | {str(vid):<7} | {info.get('rating', 'N/A'):<5} | {dur:<12}")

        return f"```yaml\n{chr(10).join(lines)}\n```"

    def create_status_embeds(self) -> Tuple[discord.Embed, Optional[discord.Embed]]:
        data = self.load_atc_cache()
        active_sessions = data.get("active", {})

        self.heartbeat_counter += 1
        self.update_system_health()

        hb = self.get_heartbeat_emoji()
        ss = self.get_system_status_emoji()
        count = len(active_sessions)
        last_update_str = self.format_time_ago(data.get("last_update", 0))

        main_embed = discord.Embed(
            title=f"{hb} MONITORING DES POSITIONS ATC ULTRAMARINES {ss}",
            color=0x1E90FF,
            timestamp=datetime.now(timezone.utc),
        )
        main_embed.url = "https://webeye.ivao.aero/"
        main_embed.set_thumbnail(url="https://upload.wikimedia.org/wikipedia/commons/c/c3/Flag_of_France.svg")
        main_embed.description = (
            "**Statut en temps réel des positions de contrôle ultramarines**\n"
            f"{ss} **{count}** position{'s' if count != 1 else ''} active{'s' if count != 1 else ''} actuellement\n"
            f"🕒 **Dernière mise à jour:** {last_update_str}\n"
            f"💭 **Heartbeat:** Battement #{self.heartbeat_counter}\n"
            f"📊 **Statut système:** {self.system_health.title()}"
        )

        for region_name, region_info in self.REGIONS.items():
            main_embed.add_field(
                name=f"{region_info['emoji']} {region_name}",
                value=self.create_table_overview(active_sessions, region_name),
                inline=False,
            )

        main_embed.set_footer(
            text=f"Mis à jour automatiquement • Antilles Contrôle • Beat #{self.heartbeat_counter}",
            icon_url="https://em-content.zobj.net/thumbs/120/twitter/321/airplane_2708-fe0f.png",
        )

        last_controller_embed = None
        lc = self.load_last_controller()
        if lc:
            callsign = lc.get("callsign", "UNKNOWN")
            end_time = lc.get("end_time", 0)
            type_emoji = self.POSITION_TYPES.get(lc.get("position_type", "OTHER"), {}).get("emoji", "🔹")
            region = lc.get("region", "Inconnue")
            region_emoji = self.REGIONS.get(region, {"emoji": "🌍"})["emoji"]

            last_controller_embed = discord.Embed(
                title=f"{type_emoji} Dernière position fermée: {callsign}",
                description=(
                    f"**Contrôleur:** {self.format_controller_name(lc.get('first_name', 'Unknown'), lc.get('last_name', 'User'), lc.get('vid', 'N/A'))}\n"
                    f"**Rating:** {lc.get('rating', 'Unknown')}\n"
                    f"**Durée de session:** {self.format_duration(lc.get('duration', 0))}\n"
                    f"**Déconnecté:** {self.format_time_ago(end_time)}"
                ),
                color=0x4286F4,
                timestamp=datetime.fromtimestamp(end_time, timezone.utc) if end_time else datetime.now(timezone.utc),
            )
            last_controller_embed.set_footer(text=f"{region_emoji} {region} • Antilles Contrôle")

        return main_embed, last_controller_embed

    # ------------------------------------------------------------------ #
    # Recherche messages existants
    # ------------------------------------------------------------------ #

    async def _find_existing_last_controller_message(
        self, channel: discord.TextChannel
    ) -> Optional[discord.Message]:
        """
        Scanne les 100 derniers messages du canal pour retrouver
        le message 'Dernière position fermée' envoyé par le bot.
        Retourne le plus récent trouvé.
        """
        try:
            async for msg in channel.history(limit=100):
                if msg.author == self.bot.user and msg.embeds:
                    title = msg.embeds[0].title or ""
                    if "Dernière position fermée" in title:
                        logger.info(
                            "Message last_controller retrouvé dans l'historique: %s", msg.id
                        )
                        return msg
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning("Impossible de scanner l'historique pour last_controller: %s", e)
        return None

    async def find_status_message(
        self, channel_id: Optional[int] = None
    ) -> Tuple[Optional[discord.Message], Optional[discord.TextChannel], Optional[discord.Message]]:
        message_id, stored_channel_id, last_controller_message_id = self.load_message_id()

        channel = self.bot.get_channel(channel_id or stored_channel_id) or self.bot.get_channel(self.CHANNEL_ID)
        if not channel:
            logger.error("Canal introuvable: %s", stored_channel_id)
            return None, None, None

        # 1) Via ID stocké
        if message_id:
            try:
                main_msg = await self.message_cache.get_message("main", channel, message_id)
                last_msg = None
                if last_controller_message_id:
                    last_msg = await self.message_cache.get_message("last_controller", channel, last_controller_message_id)
                if main_msg:
                    logger.info("Message statut trouvé par ID: %s", main_msg.id)
                    return main_msg, channel, last_msg
            except Exception as e:
                logger.warning("Erreur récupération message par ID: %s", e)

        # 2) Scan historique
        try:
            main_msg = None
            last_msg = None

            async for msg in channel.history(limit=50):
                if msg.author == self.bot.user and msg.embeds:
                    title = msg.embeds[0].title or ""
                    if "MONITORING DES POSITIONS ATC ULTRAMARINES" in title:
                        main_msg = msg
                        break

            if main_msg:
                # Chercher le last_controller APRÈS le message principal
                async for msg in channel.history(limit=20, after=main_msg):
                    if msg.author == self.bot.user and msg.embeds:
                        title = msg.embeds[0].title or ""
                        if "Dernière position fermée" in title:
                            last_msg = msg
                            break

                self.save_message_id(main_msg.id, channel.id, last_msg.id if last_msg else None)
                logger.info("Message statut trouvé dans l'historique: %s", main_msg.id)
                return main_msg, channel, last_msg

        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning("Impossible de lire l'historique du canal %s: %s", channel.id, e)

        return None, channel, None

    # ------------------------------------------------------------------ #
    # Setup monitoring
    # ------------------------------------------------------------------ #

    async def setup_monitoring(self) -> bool:
        try:
            if not self.bot.is_ready():
                return False

            default_channel = self.bot.get_channel(self.CHANNEL_ID)
            if not default_channel:
                guild = next((g for g in self.bot.guilds), None)
                if guild:
                    for ch in guild.text_channels:
                        if "monitoring" in ch.name.lower() or "position" in ch.name.lower():
                            default_channel = ch
                            self.CHANNEL_ID = ch.id
                            break
                if not default_channel:
                    return False

            if self.STATUS_MESSAGE:
                if not self.update_status_table.is_running():
                    self.update_status_table.start()
                return True

            message, channel, last_controller_message = await self.find_status_message()
            self.STATUS_MESSAGE = message
            self.LAST_CONTROLLER_MESSAGE = last_controller_message

            await self.update_atc_cache()

            if not self.STATUS_MESSAGE:
                await self.rate_limiter.wait_if_needed("setup_main")
                main_embed, last_controller_embed = self.create_status_embeds()

                self.STATUS_MESSAGE = await channel.send(embed=main_embed)
                logger.info("Nouveau message statut créé: %s", self.STATUS_MESSAGE.id)

                if last_controller_embed:
                    await self.rate_limiter.wait_if_needed("setup_last_controller")
                    self.LAST_CONTROLLER_MESSAGE = await channel.send(embed=last_controller_embed)
                    logger.info("Nouveau message last_controller créé: %s", self.LAST_CONTROLLER_MESSAGE.id)

                self.save_message_id(
                    self.STATUS_MESSAGE.id,
                    channel.id,
                    self.LAST_CONTROLLER_MESSAGE.id if self.LAST_CONTROLLER_MESSAGE else None,
                )
            else:
                logger.info("Message statut existant réutilisé: %s", self.STATUS_MESSAGE.id)

            if not self.update_status_table.is_running():
                self.update_status_table.start()

            return True

        except Exception as e:
            logger.error("Erreur setup_monitoring: %s", e)
            logger.error(traceback.format_exc())
            return False

    # ------------------------------------------------------------------ #
    # Commande manuelle
    # ------------------------------------------------------------------ #

    @commands.command(name="monitor")
    @commands.has_permissions(administrator=True)
    async def monitor(self, ctx: commands.Context):
        """Redémarre le monitoring manuellement."""
        try:
            for attr, key in [("STATUS_MESSAGE", "main"), ("LAST_CONTROLLER_MESSAGE", "last_controller")]:
                msg = getattr(self, attr)
                if msg:
                    try:
                        await self.rate_limiter.wait_if_needed(f"cleanup_{key}")
                        await msg.delete()
                    except (discord.NotFound, discord.HTTPException):
                        pass
                    setattr(self, attr, None)
                    await self.message_cache.invalidate(key)

            await ctx.send("🔄 Démarrage du monitoring... veuillez patienter.")
            await self.update_atc_cache()
            success = await self.setup_monitoring()
            if success:
                self.auto_setup_complete = True
                await ctx.send("✅ Monitoring démarré avec succès.")
            else:
                await ctx.send("❌ Impossible de démarrer le monitoring. Vérifiez les logs.")
        except Exception as e:
            logger.error("Erreur commande monitor: %s", e)
            await ctx.send(f"❌ Erreur: {e}")

    # ------------------------------------------------------------------ #
    # Mise à jour sécurisée
    # ------------------------------------------------------------------ #

    async def update_message_safely(
        self, message: discord.Message, embed: discord.Embed, message_type: str
    ) -> bool:
        async with self._message_lock:
            try:
                await self.rate_limiter.wait_if_needed(f"update_{message_type}")
                await message.edit(embed=embed)

                if message_type == "main":
                    self.STATUS_MESSAGE = message
                    self.save_message_id(
                        self.STATUS_MESSAGE.id,
                        self.STATUS_MESSAGE.channel.id,
                        self.LAST_CONTROLLER_MESSAGE.id if self.LAST_CONTROLLER_MESSAGE else None,
                    )
                elif message_type == "last_controller":
                    self.LAST_CONTROLLER_MESSAGE = message
                    if self.STATUS_MESSAGE:
                        self.save_message_id(
                            self.STATUS_MESSAGE.id,
                            self.STATUS_MESSAGE.channel.id,
                            self.LAST_CONTROLLER_MESSAGE.id,
                        )
                return True

            except discord.NotFound:
                logger.error("Message %s introuvable (supprimé)", message_type)
                if message_type == "main":
                    self.STATUS_MESSAGE = None
                else:
                    self.LAST_CONTROLLER_MESSAGE = None
                await self.message_cache.invalidate(message_type)
                return False
            except discord.HTTPException as e:
                logger.error("Erreur HTTP mise à jour %s: %s", message_type, e)
                if "Unknown Message" in str(e):
                    if message_type == "main":
                        self.STATUS_MESSAGE = None
                    else:
                        self.LAST_CONTROLLER_MESSAGE = None
                    await self.message_cache.invalidate(message_type)
                return False
            except Exception as e:
                logger.error("Erreur inattendue mise à jour %s: %s", message_type, e)
                return False

    # ------------------------------------------------------------------ #
    # TÂCHE PRINCIPALE — fix doublons "Dernière position fermée"
    # ------------------------------------------------------------------ #

    @tasks.loop(seconds=30)
    async def update_status_table(self):
        try:
            now_ts = int(datetime.now().timestamp())

            # Récupération de secours après trop d'échecs
            if self.failed_attempts >= 3 and (now_ts - self.last_update_attempt) > 120:
                logger.warning("Trop d'échecs (%s), tentative de récupération", self.failed_attempts)
                msg, channel, last_msg = await self.find_status_message()
                if msg:
                    self.STATUS_MESSAGE = msg
                    self.LAST_CONTROLLER_MESSAGE = last_msg
                    self.failed_attempts = 0
                else:
                    logger.info("Recréation complète du monitoring")
                    await self.setup_monitoring()
                    return

            if not self.STATUS_MESSAGE:
                self.last_update_attempt = now_ts
                self.failed_attempts += 1
                logger.error("Message statut introuvable (tentative %s)", self.failed_attempts)
                return

            await self.update_atc_cache()
            main_embed, last_controller_embed = self.create_status_embeds()

            main_ok = await self.update_message_safely(self.STATUS_MESSAGE, main_embed, "main")

            if main_ok:
                self.last_successful_update = datetime.now(timezone.utc)
                self.update_system_health()
                self.failed_attempts = 0
                self.last_update_attempt = now_ts

                if last_controller_embed:
                    if self.LAST_CONTROLLER_MESSAGE:
                        # --- CAS 1 : on a déjà le message → on édite
                        last_ok = await self.update_message_safely(
                            self.LAST_CONTROLLER_MESSAGE, last_controller_embed, "last_controller"
                        )
                        if not last_ok:
                            # L'édition a échoué (message mort) → on cherche un éventuel rescapé
                            # dans l'historique avant d'en créer un nouveau
                            existing = await self._find_existing_last_controller_message(
                                self.STATUS_MESSAGE.channel
                            )
                            if existing:
                                self.LAST_CONTROLLER_MESSAGE = existing
                                await self.update_message_safely(
                                    self.LAST_CONTROLLER_MESSAGE, last_controller_embed, "last_controller"
                                )
                            else:
                                # Aucun trouvé → création unique
                                await self.rate_limiter.wait_if_needed("create_last_controller")
                                self.LAST_CONTROLLER_MESSAGE = await self.STATUS_MESSAGE.channel.send(
                                    embed=last_controller_embed
                                )
                                logger.info(
                                    "Nouveau message last_controller créé après échec édition: %s",
                                    self.LAST_CONTROLLER_MESSAGE.id,
                                )
                                self.save_message_id(
                                    self.STATUS_MESSAGE.id,
                                    self.STATUS_MESSAGE.channel.id,
                                    self.LAST_CONTROLLER_MESSAGE.id,
                                )
                    else:
                        # --- CAS 2 : référence perdue → chercher d'abord dans l'historique
                        existing = await self._find_existing_last_controller_message(
                            self.STATUS_MESSAGE.channel
                        )
                        if existing:
                            # On réutilise l'ancien message
                            self.LAST_CONTROLLER_MESSAGE = existing
                            self.save_message_id(
                                self.STATUS_MESSAGE.id,
                                self.STATUS_MESSAGE.channel.id,
                                self.LAST_CONTROLLER_MESSAGE.id,
                            )
                            await self.update_message_safely(
                                self.LAST_CONTROLLER_MESSAGE, last_controller_embed, "last_controller"
                            )
                            logger.info(
                                "Message last_controller existant réutilisé: %s",
                                self.LAST_CONTROLLER_MESSAGE.id,
                            )
                        else:
                            # Vraiment absent → on crée (une seule fois)
                            await self.rate_limiter.wait_if_needed("create_last_controller")
                            self.LAST_CONTROLLER_MESSAGE = await self.STATUS_MESSAGE.channel.send(
                                embed=last_controller_embed
                            )
                            logger.info(
                                "Nouveau message last_controller créé (introuvable): %s",
                                self.LAST_CONTROLLER_MESSAGE.id,
                            )
                            self.save_message_id(
                                self.STATUS_MESSAGE.id,
                                self.STATUS_MESSAGE.channel.id,
                                self.LAST_CONTROLLER_MESSAGE.id,
                            )

                logger.debug("Mise à jour réussie — Beat #%s", self.heartbeat_counter)
            else:
                self.failed_attempts += 1
                self.last_update_attempt = now_ts

        except Exception as e:
            logger.error("Erreur majeure update_status_table: %s", e)
            logger.error(traceback.format_exc())
            self.failed_attempts += 1
            self.last_update_attempt = int(datetime.now().timestamp())

    @update_status_table.before_loop
    async def before_update_status_table(self):
        await self.bot.wait_until_ready()
        logger.info("Bot prêt, tâche de mise à jour démarrée")

    # ------------------------------------------------------------------ #
    # Mise à jour cache positions (tâche 1 min)
    # ------------------------------------------------------------------ #

    @tasks.loop(minutes=1)
    async def update_positions(self):
        try:
            if not await self.update_atc_cache():
                logger.warning("Echec mise à jour cache ATC")
        except Exception as e:
            logger.error("Erreur update_positions: %s", e)
            logger.error(traceback.format_exc())

    @update_positions.before_loop
    async def before_update_positions(self):
        await self.bot.wait_until_ready()
        logger.info("Bot prêt, tâche mise à jour positions démarrée")


async def setup(bot: commands.Bot):
    await bot.add_cog(EnhancedMonitoring(bot))
