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

# Charger les variables d'environnement
load_dotenv()

# Récupérer la clé API IVAO depuis les variables d'environnement
IVAO_API_KEY = os.getenv("IVAO_API_KEY", "")
if not IVAO_API_KEY:
    raise ValueError("IVAO_API_KEY non définie dans .env")


class DiscordRateLimiter:
    """Gère le rate limiting pour les opérations Discord."""

    def __init__(self, delay: float = 1.2):
        self.delay = delay
        self.last_operation: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait_if_needed(self, operation_key: str = "default"):
        """Attend si nécessaire pour respecter le rate limit."""
        async with self._lock:
            current_time = asyncio.get_event_loop().time()
            last_time = self.last_operation.get(operation_key, 0)

            time_since_last = current_time - last_time
            if time_since_last < self.delay:
                wait_time = self.delay - time_since_last
                await asyncio.sleep(wait_time)

            self.last_operation[operation_key] = asyncio.get_event_loop().time()


class MessageCache:
    """Cache pour les messages Discord validés."""

    def __init__(self):
        self._cache: Dict[str, discord.Message] = {}
        self._last_validation: Dict[str, float] = {}
        self._validation_timeout = 300  # 5 minutes
        self._lock = asyncio.Lock()

    async def get_message(
        self,
        message_type: str,
        channel: discord.TextChannel,
        message_id: Optional[str],
    ) -> Optional[discord.Message]:
        """Récupère un message depuis le cache ou Discord."""
        if not message_id:
            return None

        async with self._lock:
            current_time = asyncio.get_event_loop().time()

            # Vérifier le cache
            if (
                message_type in self._cache
                and message_type in self._last_validation
            ):
                if (
                    current_time - self._last_validation[message_type]
                    < self._validation_timeout
                ):
                    return self._cache[message_type]

            # Valider le message sur Discord
            try:
                message = await channel.fetch_message(int(message_id))
                self._cache[message_type] = message
                self._last_validation[message_type] = current_time
                return message
            except (discord.errors.NotFound, discord.errors.Forbidden, ValueError):
                # Nettoyer le cache si le message n'existe plus
                self._cache.pop(message_type, None)
                self._last_validation.pop(message_type, None)
                return None
            except Exception as e:
                print(f"Erreur lors de la validation du message pour {message_type}: {e}")
                return None

    async def invalidate(self, message_type: str):
        """Invalide le cache pour un type de message."""
        async with self._lock:
            self._cache.pop(message_type, None)
            self._last_validation.pop(message_type, None)


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

        # Composants de résilience
        self.rate_limiter = DiscordRateLimiter(1.2)
        self.message_cache = MessageCache()
        self.heartbeat_counter = 0
        self.last_successful_update = datetime.now(timezone.utc)
        self.system_health = "healthy"  # healthy, warning, error

        # Configuration
        self.CHANNEL_ID = 1310926262566387753
        self.apikey = IVAO_API_KEY
        self.ATC_URL = "https://api.ivao.aero/v2/tracker/now/atc"
        self.CACHE_FILE = "utils/atc_positions_cache.json"
        self.MESSAGE_ID_FILE = "utils/status_message_id.json"
        self.USER_CACHE_FILE = "utils/user_name_cache.json"
        self.LAST_CONTROLLER_FILE = "utils/last_controller.json"
        self.USER_VID = "722124"
        self.USER_PASSWORD = "1ICGmIBMJP0Y"

        # Vérifier et créer les répertoires nécessaires
        os.makedirs("utils", exist_ok=True)
        os.makedirs("utils/logs", exist_ok=True)

        # Config des positions/régions
        self.setup_regions_and_positions()

        # Cache des noms
        self.name_cache = self.load_user_name_cache()

        # Démarrer les tâches
        self.update_positions.start()
        self.auto_setup_task.start()
        self.update_status_table.start()

    # ------------------------------------------------------------------ #
    # Configuration régions / positions
    # ------------------------------------------------------------------ #

    def setup_regions_and_positions(self):
        """Configure les positions surveillées et leurs régions."""

        self.REGIONS = {
            "ANTILLES": {
                "emoji": "🏝️",
                "color": 0x3498DB,
                "positions": [
                    # TFFF - Martinique (Fort-de-France)
                    "TFFF_APP",
                    "TFFF_DEL",
                    "TFFF_TWR",
                    # TFFR - Guadeloupe (Pointe-à-Pitre)
                    "TFFR_APP",
                    "TFFR_TWR",
                    # TFFJ - Saint-Barthélemy
                    "TFFJ_FIS_TWR",
                    "TFFJ_I_TWR",
                    # TFFG - Saint-Martin
                    "TFFG_FIS_TWR",
                    "TFFG_I_TWR",
                    # TFFM - Marie-Galante
                    "TFFM_I_TWR",
                ],
            },
            "GUYANE": {
                "emoji": "🌳",
                "color": 0x27AE60,
                "positions": [
                    # SOCA - Cayenne
                    "SOCA_APP",
                    "SOCA_TWR",
                    # SOOO - Contrôle Océanique
                    "SOOO_CTR",
                    "SOOO_MIL_CTR",
                ],
            },
            "POLYNÉSIE": {
                "emoji": "🌺",
                "color": 0xE74C3C,
                "positions": [
                    # NTAA - Tahiti-Faa'a (Papeete)
                    "NTAA_APP",
                    "NTAA_DEL",
                    "NTAA_TWR",
                    # NTTB - Bora Bora
                    "NTTB_TWR",
                    # NTTH - Huahine
                    "NTTH_FIS_TWR",
                    "NTTH_I_TWR",
                    # NTTM - Moorea (Temae)
                    "NTTM_TWR",
                    # NTTR - Raiatea
                    "NTTR_TWR",
                    # NTTG - Rangiroa
                    "NTTG_FIS_TWR",
                    "NTTG_I_TWR",
                    # NTTT - Centre de contrôle de Tahiti
                    "NTTT_CTR",
                    # NTAR - Rurutu
                    "NTAR_FIS_TWR",
                    "NTAR_I_TWR",
                    # NTAT - Tubuai
                    "NTAT_FIS_TWR",
                    "NTAT_I_TWR",
                    # NTAV - Raivavae
                    "NTAV_FIS_TWR",
                    "NTAV_I_TWR",
                    # NTGC - Tikehau
                    "NTGC_FIS_TWR",
                    "NTGC_I_TWR",
                    # NTGF - Fakarava
                    "NTGF_FIS_TWR",
                    "NTGF_I_TWR",
                    # NTGI - Manihi
                    "NTGI_FIS_TWR",
                    "NTGI_I_TWR",
                    # NTGJ - Totegegie (Gambier)
                    "NTGJ_FIS_TWR",
                    "NTGJ_I_TWR",
                    # NTGK - Kaukura
                    "NTGK_FIS_TWR",
                    "NTGK_I_TWR",
                    # NTGM - Makemo
                    "NTGM_FIS_TWR",
                    "NTGM_I_TWR",
                    # NTGT - Takapoto
                    "NTGT_FIS_TWR",
                    "NTGT_I_TWR",
                    # NTGU - Arutua
                    "NTGU_FIS_TWR",
                    "NTGU_I_TWR",
                    # NTGV - Mataiva
                    "NTGV_FIS_TWR",
                    "NTGV_I_TWR",
                    # NTMD - Nuku Hiva (Marquises)
                    "NTMD_FIS_TWR",
                    "NTMD_I_TWR",
                    # NTMN - Atuona Hiva Oa
                    "NTMN_FIS_TWR",
                    "NTMN_I_TWR",
                    # NTMP - Ua Pou (Marquises)
                    "NTMP_FIS_TWR",
                    "NTMP_I_TWR",
                    # NTMU - Ua Huka (Marquises)
                    "NTMU_FIS_TWR",
                    "NTMU_I_TWR",
                    # NTTO - Hao
                    "NTTO_FIS_TWR",
                    "NTTO_I_TWR",
                    # NTTP - Maupiti
                    "NTTP_FIS_TWR",
                    "NTTP_I_TWR",
                ],
            },
            "RÉUNION_MAYOTTE": {
                "emoji": "🌋",
                "color": 0xF39C12,
                "positions": [
                    # FMEE - La Réunion (Saint-Denis)
                    "FMEE_APP",
                    "FMEE_GND",
                    "FMEE_TWR",
                    # FMEP - Pierrefonds (Saint-Pierre)
                    "FMEP_FIS_TWR",
                    "FMEP_I_TWR",
                    # FMCZ - Dzaoudzi (Mayotte)
                    "FMCZ_TWR",
                ],
            },
            "NOUVELLE_CALÉDONIE": {
                "emoji": "🐠",
                "color": 0x9B59B6,
                "positions": [
                    # NWWW - Nouméa La Tontouta
                    "NWWW_APP",
                    "NWWW_GND",
                    "NWWW_TWR",
                    # NWWM - Nouméa Magenta
                    "NWWM_APP",
                    "NWWM_TWR",
                    # NWWL - Lifou Wanaham
                    "NWWL_FIS_TWR",
                    # NWWD - Koné
                    "NWWD_FIS_TWR",
                    "NWWD_I_TWR",
                    # NWWE - Île des Pins Moué
                    "NWWE_FIS_TWR",
                    "NWWE_I_TWR",
                    # NWWR - Maré La Roche
                    "NWWR_FIS_TWR",
                    "NWWR_I_TWR",
                    # NWWU - Touho
                    "NWWU_FIS_TWR",
                    "NWWU_I_TWR",
                    # NWWV - Ouvéa
                    "NWWV_FIS_TWR",
                    "NWWV_I_TWR",
                ],
            },
            "WALLIS_FUTUNA": {
                "emoji": "🏖️",
                "color": 0x1ABC9C,
                "positions": [
                    # NLWW - Wallis Hihifo
                    "NLWW_FIS_TWR",
                    "NLWW_I_TWR",
                    # NLWF - Futuna Pointe Vele
                    "NLWF_FIS_TWR",
                    "NLWF_I_TWR",
                ],
            },
            "SPM": {
                "emoji": "❄️",
                "color": 0x34495E,
                "positions": [
                    # LFVP - Saint-Pierre
                    "LFVP_APP",
                    "LFVP_TWR",
                    # LFVM - Miquelon
                    "LFVM_FIS_TWR",
                    "LFVM_I_TWR",
                ],
            },
        }

        # Liste plate des positions
        self.MONITORED_POSITIONS: List[str] = []
        for region in self.REGIONS.values():
            self.MONITORED_POSITIONS.extend(region["positions"])

        # Types de positions
        self.POSITION_TYPES = {
            "TWR": {"emoji": "🗼", "name": "Tour"},
            "APP": {"emoji": "🛬", "name": "Approche"},
            "CTR": {"emoji": "🌐", "name": "Centre"},
            "DEL": {"emoji": "🧾", "name": "Délivrance"},
            "GND": {"emoji": "🚜", "name": "Sol"},
            "FIS": {"emoji": "🔭", "name": "Info Vol"},
            "I": {"emoji": "🔧", "name": "Maintenance"},
        }

        # Ratings IVAO
        self.IVAO_RATINGS = {
            2: "AS1",
            3: "AS2",
            4: "AS3",
            5: "ADC",
            6: "APC",
            7: "ACC",
            8: "SEC",
            9: "SAI",
            10: "CAI",
        }

    # ------------------------------------------------------------------ #
    # Utilitaires d'état système
    # ------------------------------------------------------------------ #

    def get_heartbeat_emoji(self) -> str:
        heartbeat_emojis = ["💚", "💛", "❤️", "🧡", "💜", "💙"]
        return heartbeat_emojis[self.heartbeat_counter % len(heartbeat_emojis)]

    def get_system_status_emoji(self) -> str:
        if self.system_health == "healthy":
            return "🟢"
        elif self.system_health == "warning":
            return "🟡"
        return "🔴"

    def update_system_health(self):
        now = datetime.now(timezone.utc)
        time_since_update = (now - self.last_successful_update).total_seconds()

        if time_since_update < 60:
            self.system_health = "healthy"
        elif time_since_update < 300:
            self.system_health = "warning"
        else:
            self.system_health = "error"

    # ------------------------------------------------------------------ #
    # Cycle de vie du cog
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
                logger.warning(
                    "Echec de l'auto-setup. Tentative %s/%s",
                    self.setup_retries,
                    self.max_retries,
                )
                if self.setup_retries >= self.max_retries:
                    logger.error(
                        "Nombre maximum de tentatives d'auto-setup atteint. Passage à un intervalle plus long."
                    )
                    self.auto_setup_task.change_interval(minutes=5)
                    self.setup_retries = 0
        except Exception as e:
            logger.error("Erreur lors de l'auto-setup: %s", e)
            logger.error(traceback.format_exc())
            self.setup_retries += 1
            if self.setup_retries >= self.max_retries:
                logger.error(
                    "Nombre maximum de tentatives d'auto-setup atteint. Passage à un intervalle plus long."
                )
                self.auto_setup_task.change_interval(minutes=5)
                self.setup_retries = 0

    @auto_setup_task.before_loop
    async def before_auto_setup(self):
        await self.bot.wait_until_ready()
        logger.info("Bot prêt, tâche d'auto-setup démarrée")

    # ------------------------------------------------------------------ #
    # Formatage temps / types / régions
    # ------------------------------------------------------------------ #

    def format_duration(self, seconds: float, compact: bool = False) -> str:
        if seconds is None or seconds < 0:
            seconds = 0

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)

        if compact:
            return f"{hours}h{minutes:02d}m"
        return f"{hours:02d}h {minutes:02d}min"

    def format_time_ago(self, timestamp: int) -> str:
        if timestamp is None or timestamp <= 0:
            return "récemment"

        now = datetime.now(timezone.utc)
        try:
            dt = now - datetime.fromtimestamp(timestamp, timezone.utc)
        except (ValueError, OverflowError, OSError):
            return "récemment"

        seconds = dt.total_seconds()
        if seconds < 60:
            return "il y a quelques instants"
        if seconds < 3600:
            minutes = int(seconds // 60)
            return f"il y a {minutes} minute{'s' if minutes > 1 else ''}"
        if seconds < 86400:
            hours = int(seconds // 3600)
            return f"il y a {hours} heure{'s' if hours > 1 else ''}"
        days = int(seconds // 86400)
        return f"il y a {days} jour{'s' if days > 1 else ''}"

    def get_position_type(self, position: str) -> str:
        if not position:
            return "OTHER"

        if "_CTR" in position:
            return "CTR"
        if "_APP" in position:
            return "APP"
        if "_TWR" in position:
            return "TWR"
        if "_DEL" in position:
            return "DEL"
        if "_GND" in position:
            return "GND"
        if "_FIS" in position:
            return "FIS"
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
                data = json.load(f)
                return data
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning("Fichier cache introuvable ou corrompu, utilisation d'un cache vide")
            return {"active": {}, "recent": {}}

    def save_atc_cache(self, data: Dict[str, Any]) -> bool:
        try:
            os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error("Erreur lors de la sauvegarde du cache ATC: %s", e)
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
            logger.error("Erreur lors de la sauvegarde du cache des noms: %s", e)

    def save_message_id(
        self,
        message_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        last_controller_message_id: Optional[int] = None,
    ) -> bool:
        data = {
            "message_id": str(message_id) if message_id else None,
            "channel_id": channel_id or self.CHANNEL_ID,
            "last_controller_message_id": str(last_controller_message_id)
            if last_controller_message_id
            else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            os.makedirs(os.path.dirname(self.MESSAGE_ID_FILE), exist_ok=True)
            with open(self.MESSAGE_ID_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(
                "ID de message sauvegardé: %s dans le canal %s",
                message_id,
                channel_id or self.CHANNEL_ID,
            )
            return True
        except Exception as e:
            logger.error("Erreur lors de la sauvegarde de l'ID du message: %s", e)
            return False

    def load_message_id(self) -> Tuple[Optional[str], int, Optional[str]]:
        try:
            with open(self.MESSAGE_ID_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.info("ID de message chargé: %s", data)
                return (
                    data.get("message_id"),
                    data.get("channel_id", self.CHANNEL_ID),
                    data.get("last_controller_message_id"),
                )
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning("Fichier d'ID de message introuvable ou corrompu")
            return None, self.CHANNEL_ID, None

    def save_last_controller(self, controller_data: Dict[str, Any]) -> bool:
        try:
            controller_data["saved_at"] = datetime.now(timezone.utc).isoformat()
            os.makedirs(os.path.dirname(self.LAST_CONTROLLER_FILE), exist_ok=True)
            with open(self.LAST_CONTROLLER_FILE, "w", encoding="utf-8") as f:
                json.dump(controller_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error("Erreur lors de la sauvegarde du dernier contrôleur: %s", e)
            return False

    def load_last_controller(self) -> Dict[str, Any]:
        try:
            with open(self.LAST_CONTROLLER_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning(
                "Fichier du dernier contrôleur introuvable ou corrompu, utilisation d'un dict vide"
            )
            return {}

    # ------------------------------------------------------------------ #
    # Récupération nom utilisateur IVAO
    # ------------------------------------------------------------------ #

    async def get_user_name_from_vid(self, vid: int) -> Tuple[str, str]:
        if not vid:
            return "Unknown", "User"

        vid_str = str(vid)
        if vid_str in self.name_cache:
            cache_entry = self.name_cache[vid_str]
            if "updated_at" in cache_entry:
                try:
                    cache_time = datetime.fromisoformat(
                        cache_entry["updated_at"].replace("Z", "+00:00")
                    )
                    if (datetime.now(timezone.utc) - cache_time).days < 7:
                        return cache_entry["first_name"], cache_entry["last_name"]
                except Exception:
                    pass
            else:
                return cache_entry["first_name"], cache_entry["last_name"]

        try:
            await self.init_session()

            login_url = "https://ivao.aero/Login.aspx"
            profile_url = f"https://ivao.aero/Member.aspx?Id={vid}"

            async with self.session.get(
                login_url, params={"r": f"Member.aspx?Id={vid}"}
            ) as response:
                if response.status != 200:
                    logger.error(
                        "Erreur accès page de connexion IVAO: %s", response.status
                    )
                    return "Unknown", "User"

                html_content = await response.text()
                soup = BeautifulSoup(html_content, "html.parser")

                viewstate = soup.find("input", {"name": "__VIEWSTATE"})
                if not viewstate:
                    logger.error("VIEWSTATE introuvable sur la page de connexion")
                    return "Unknown", "User"
                viewstate = viewstate["value"]

                viewstategenerator = soup.find(
                    "input", {"name": "__VIEWSTATEGENERATOR"}
                )
                if not viewstategenerator:
                    logger.error("VIEWSTATEGENERATOR introuvable")
                    return "Unknown", "User"
                viewstategenerator = viewstategenerator["value"]

                eventvalidation = soup.find(
                    "input", {"name": "__EVENTVALIDATION"}
                )
                if not eventvalidation:
                    logger.error("EVENTVALIDATION introuvable")
                    return "Unknown", "User"
                eventvalidation = eventvalidation["value"]

                try:
                    post_url = soup.find(
                        "input", {"name": "ctl00$ContentPlaceHolder1$postUrl"}
                    )["value"]
                except Exception:
                    post_url = profile_url

            login_data = {
                "__VIEWSTATE": viewstate,
                "__VIEWSTATEGENERATOR": viewstategenerator,
                "__EVENTVALIDATION": eventvalidation,
                "ctl00$ContentPlaceHolder1$postUrl": post_url,
                "ctl00$ContentPlaceHolder1$loginVID": self.USER_VID,
                "ctl00$ContentPlaceHolder1$loginPassword": self.USER_PASSWORD,
                "ctl00$ContentPlaceHolder1$loginRemember": "on",
                "ctl00$ContentPlaceHolder1$loginBtn": "Login",
            }

            async with self.session.post(
                login_url, data=login_data, allow_redirects=True
            ) as response:
                if response.status != 200:
                    logger.error("Echec connexion IVAO: %s", response.status)
                    return "Unknown", "User"

            async with self.session.get(profile_url) as response:
                if response.status != 200:
                    logger.error(
                        "Echec accès profil IVAO %s: %s", vid, response.status
                    )
                    return "Unknown", "User"

                html_content = await response.text()
                soup = BeautifulSoup(html_content, "html.parser")

                name_element = soup.find("h3")
                if name_element:
                    full_name = name_element.text.strip()
                    parts = full_name.split()
                    if len(parts) >= 2:
                        first_name = " ".join(parts[:-1])
                        last_name = parts[-1]
                    else:
                        first_name = full_name
                        last_name = ""

                    self.name_cache[vid_str] = {
                        "first_name": first_name,
                        "last_name": last_name,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                    self.save_user_name_cache()
                    return first_name, last_name

            return "Unknown", "User"

        except Exception as e:
            logger.error(
                "Erreur lors de la récupération du nom utilisateur IVAO pour VID %s: %s",
                vid,
                e,
            )
            return "Unknown", "User"

    def format_controller_name(
        self, first_name: str, last_name: str, user_id: int
    ) -> str:
        if first_name == "Unknown" or not last_name:
            return f"Inconnu (VID: {user_id})"
        last_initial = last_name[0] if last_name else ""
        return f"{first_name} {last_initial}. (VID: {user_id})"

    # ------------------------------------------------------------------ #
    # Récupération et cache ATC
    # ------------------------------------------------------------------ #

    async def update_atc_cache(self) -> bool:
        try:
            headers = {"apiKey": self.apikey, "Accept": "application/json"}
            await self.init_session()

            async with self.session.get(self.ATC_URL, headers=headers) as response:
                if response.status != 200:
                    response_text = await response.text()
                    logger.error(
                        "Erreur API IVAO ATC %s: %s", response.status, response_text
                    )
                    return False

                all_controllers = await response.json()
                current_cache = self.load_atc_cache()
                active_positions: Dict[str, Dict[str, Any]] = {}

                for controller in all_controllers:
                    atc_position = controller.get("atcPosition")
                    if atc_position is None:
                        continue

                    callsign = atc_position.get("composePosition")
                    if callsign not in self.MONITORED_POSITIONS:
                        continue

                    user_id = controller.get("userId", "N/A")
                    created_at = controller.get("createdAt", "")
                    try:
                        start_time = int(
                            datetime.fromisoformat(
                                created_at.replace("Z", "+00:00")
                            ).timestamp()
                        )
                    except Exception:
                        start_time = int(datetime.now(timezone.utc).timestamp())

                    first_name, last_name = "Unknown", "User"
                    if user_id and user_id != "N/A":
                        try:
                            first_name, last_name = await self.get_user_name_from_vid(
                                user_id
                            )
                        except Exception as e:
                            logger.error(
                                "Erreur récupération nom pour VID %s: %s", user_id, e
                            )

                    rating_id = (
                        controller.get("user", {})
                        .get("rating", {})
                        .get("atcRatingId", 0)
                    )
                    rating = self.IVAO_RATINGS.get(rating_id, "Unknown")

                    active_positions[callsign] = {
                        "vid": user_id,
                        "rating": rating,
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
                            "position_type": info.get(
                                "position_type", self.get_position_type(callsign)
                            ),
                            "callsign": callsign,
                            "region": self.get_position_region(callsign),
                        }
                        recent_positions[callsign] = controller_data
                        self.save_last_controller(controller_data)

                if len(recent_positions) > 20:
                    sorted_recent = sorted(
                        recent_positions.items(),
                        key=lambda x: x[1].get("end_time", 0),
                        reverse=True,
                    )
                    recent_positions = dict(sorted_recent[:20])

                updated_cache = {
                    "active": active_positions,
                    "recent": recent_positions,
                    "last_update": now_ts,
                }

                self.save_atc_cache(updated_cache)
                self.last_successful_update = datetime.now(timezone.utc)
                return True

        except Exception as e:
            logger.error("Erreur mise à jour cache ATC: %s", e)
            logger.error(traceback.format_exc())
            return False

    # ------------------------------------------------------------------ #
    # Construction des embeds
    # ------------------------------------------------------------------ #

    def create_table_overview(
        self, active_sessions: Dict[str, Any], region_name: Optional[str] = None
    ) -> str:
        filtered_sessions: Dict[str, Any] = {}

        if region_name:
            for callsign, info in active_sessions.items():
                if self.get_position_region(callsign) == region_name:
                    filtered_sessions[callsign] = info
        else:
            filtered_sessions = active_sessions

        if not filtered_sessions:
            if region_name:
                return f"```yaml\n# Aucune position active dans la région {region_name}\n```"
            return "```yaml\n# Aucune position ATC active actuellement\n```"

        header = (
            f"{'Position':<15} | {'Contrôleur':<18} | {'VID':<7} | {'Rating':<5} | {'Durée':<12}"
        )
        separator = "-" * 70
        table_lines = [header, separator]

        sorted_sessions = sorted(filtered_sessions.items())

        for callsign, info in sorted_sessions:
            first_name = info.get("first_name", "Unknown")
            last_name = info.get("last_name", "User")
            vid = info.get("vid", "N/A")

            if first_name != "Unknown" and last_name:
                controller_name = f"{first_name} {last_name[0]}."[:18]
            else:
                controller_name = "Inconnu"

            now = datetime.now(timezone.utc)
            start_time = info.get("start_time", 0)
            if start_time:
                try:
                    start_time_dt = datetime.fromtimestamp(start_time, timezone.utc)
                    duration = (now - start_time_dt).total_seconds()
                    duration_str = self.format_duration(duration, compact=True)
                except Exception:
                    duration_str = "N/A"
            else:
                duration_str = "N/A"

            line = (
                f"{callsign:<15} | {controller_name:<18} | {str(vid):<7} | "
                f"{info.get('rating', 'N/A'):<5} | {duration_str:<12}"
            )
            table_lines.append(line)

        return f"```yaml\n{chr(10).join(table_lines)}\n```"

    def create_status_embeds(
        self,
    ) -> Tuple[discord.Embed, Optional[discord.Embed]]:
        data = self.load_atc_cache()
        active_sessions = data.get("active", {})

        self.heartbeat_counter += 1
        self.update_system_health()

        heartbeat = self.get_heartbeat_emoji()
        system_status = self.get_system_status_emoji()

        main_embed = discord.Embed(
            title=f"{heartbeat} MONITORING DES POSITIONS ATC ULTRAMARINES {system_status}",
            color=0x1E90FF,
            timestamp=datetime.now(timezone.utc),
        )

        main_embed.url = "https://webeye.ivao.aero/"
        main_embed.set_thumbnail(
            url="https://upload.wikimedia.org/wikipedia/commons/c/c3/Flag_of_France.svg"
        )

        position_count = len(active_sessions)
        last_update_time = data.get("last_update", 0)
        if last_update_time:
            last_update_str = self.format_time_ago(last_update_time)
        else:
            last_update_str = "jamais"

        status_text = (
            "**Statut en temps réel des positions de contrôle ultramarines**\n"
            f"{system_status} **{position_count}** position{'s' if position_count != 1 else ''} "
            f"active{'s' if position_count != 1 else ''} actuellement\n"
            f"🕒 **Dernière mise à jour:** {last_update_str}\n"
            f"💭 **Heartbeat:** Battement #{self.heartbeat_counter}\n"
            f"📊 **Statut système:** {self.system_health.title()}"
        )
        main_embed.description = status_text

        for region_name, region_info in self.REGIONS.items():
            region_emoji = region_info["emoji"]
            region_table = self.create_table_overview(active_sessions, region_name)
            main_embed.add_field(
                name=f"{region_emoji} {region_name}",
                value=region_table,
                inline=False,
            )

        last_controller_embed = None
        last_controller = self.load_last_controller()

        if last_controller:
            controller_name = self.format_controller_name(
                last_controller.get("first_name", "Unknown"),
                last_controller.get("last_name", "User"),
                last_controller.get("vid", "N/A"),
            )
            duration_str = self.format_duration(last_controller.get("duration", 0))

            position_type = last_controller.get("position_type", "OTHER")
            type_emoji = self.POSITION_TYPES.get(position_type, {}).get("emoji", "🔹")
            callsign = last_controller.get("callsign", "UNKNOWN")

            end_time = last_controller.get("end_time", 0)
            last_controller_embed = discord.Embed(
                title=f"{type_emoji} Dernière position fermée: {callsign}",
                description=(
                    f"**Contrôleur:** {controller_name}\n"
                    f"**Rating:** {last_controller.get('rating', 'Unknown')}\n"
                    f"**Durée de session:** {duration_str}\n"
                    f"**Déconnecté:** {self.format_time_ago(end_time)}"
                ),
                color=0x4286F4,
                timestamp=datetime.fromtimestamp(end_time, timezone.utc)
                if end_time
                else datetime.now(timezone.utc),
            )

            region = last_controller.get("region", "Inconnue")
            region_info = self.REGIONS.get(region, {"emoji": "🌍"})
            region_emoji = region_info["emoji"]

            last_controller_embed.set_footer(
                text=f"{region_emoji} {region} • Antilles Contrôle"
            )

        main_embed.set_footer(
            text=f"Mis à jour automatiquement • Antilles Contrôle • Beat #{self.heartbeat_counter}",
            icon_url=(
                "https://em-content.zobj.net/thumbs/120/twitter/321/"
                "airplane_2708-fe0f.png"
            ),
        )

        return main_embed, last_controller_embed

    # ------------------------------------------------------------------ #
    # Gestion du message de statut (recherche / création)
    # ------------------------------------------------------------------ #

    async def find_status_message(
        self, channel_id: Optional[int] = None
    ) -> Tuple[Optional[discord.Message], Optional[discord.TextChannel], Optional[discord.Message]]:
        """Recherche le message de statut dans le canal, de manière robuste."""
        message_id, stored_channel_id, last_controller_message_id = self.load_message_id()

        if channel_id:
            channel = self.bot.get_channel(channel_id)
        else:
            channel = self.bot.get_channel(stored_channel_id) or self.bot.get_channel(
                self.CHANNEL_ID
            )

        if not channel:
            logger.error("Canal introuvable: %s", stored_channel_id)
            return None, None, None

        # 1) Tentative via ID stocké
        if message_id:
            try:
                main_msg = await self.message_cache.get_message(
                    "main", channel, message_id
                )
                last_msg = None
                if last_controller_message_id:
                    last_msg = await self.message_cache.get_message(
                        "last_controller", channel, last_controller_message_id
                    )
                if main_msg:
                    logger.info("Message de statut trouvé par ID: %s", main_msg.id)
                    return main_msg, channel, last_msg
            except Exception as e:
                logger.warning("Erreur récupération message par ID: %s", e)

        # 2) Scan de l'historique si pas trouvé
        try:
            main_msg = None
            last_msg = None

            async for msg in channel.history(limit=30):
                if msg.author == self.bot.user and msg.embeds:
                    embed = msg.embeds[0]
                    if embed.title and "MONITORING DES POSITIONS ATC ULTRAMARINES" in embed.title:
                        main_msg = msg
                        break

            if main_msg:
                async for msg in channel.history(limit=10, after=main_msg):
                    if msg.author == self.bot.user and msg.embeds:
                        embed = msg.embeds[0]
                        if embed.title and "Dernière position fermée" in embed.title:
                            last_msg = msg
                            break

                self.save_message_id(
                    main_msg.id, channel.id, last_msg.id if last_msg else None
                )
                logger.info(
                    "Message de statut trouvé dans l'historique: %s", main_msg.id
                )
                return main_msg, channel, last_msg

        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning("Impossible de lire l'historique du canal %s: %s", channel.id, e)

        return None, channel, None

    async def setup_monitoring(self) -> bool:
        """Configuration du monitoring (appelé par on_ready et la commande monitor)."""
        try:
            if not self.bot.is_ready():
                logger.warning("Bot non prêt, configuration reportée")
                return False

            default_channel = self.bot.get_channel(self.CHANNEL_ID)
            if not default_channel:
                logger.error("Canal par défaut %s non trouvé", self.CHANNEL_ID)
                guild = next((g for g in self.bot.guilds), None)
                if guild:
                    for channel in guild.text_channels:
                        if "monitoring" in channel.name.lower() or "position" in channel.name.lower():
                            logger.info(
                                "Canal alternatif trouvé: %s (%s)",
                                channel.name,
                                channel.id,
                            )
                            default_channel = channel
                            self.CHANNEL_ID = channel.id
                            break
                if not default_channel:
                    return False

            # Si on a déjà un STATUS_MESSAGE valide, ne pas recréer
            if self.STATUS_MESSAGE:
                if not hasattr(self, "update_status_table") or not self.update_status_table.is_running():
                    self.update_status_table.start()
                    logger.info("Tâche de mise à jour du statut démarrée")
                return True

            message, channel, last_controller_message = await self.find_status_message()
            self.STATUS_MESSAGE = message
            self.LAST_CONTROLLER_MESSAGE = last_controller_message

            await self.update_atc_cache()

            if not self.STATUS_MESSAGE:
                await self.rate_limiter.wait_if_needed("setup_main")
                main_embed, last_controller_embed = self.create_status_embeds()

                self.STATUS_MESSAGE = await channel.send(embed=main_embed)
                if last_controller_embed:
                    await self.rate_limiter.wait_if_needed("setup_last_controller")
                    self.LAST_CONTROLLER_MESSAGE = await channel.send(
                        embed=last_controller_embed
                    )

                logger.info("Nouveau message de statut créé: %s", self.STATUS_MESSAGE.id)

                self.save_message_id(
                    self.STATUS_MESSAGE.id,
                    channel.id,
                    self.LAST_CONTROLLER_MESSAGE.id if self.LAST_CONTROLLER_MESSAGE else None,
                )
            else:
                logger.info("Message de statut existant réutilisé: %s", self.STATUS_MESSAGE.id)

            if not hasattr(self, "update_status_table") or not self.update_status_table.is_running():
                self.update_status_table.start()
                logger.info("Tâche de mise à jour du statut démarrée")

            return True

        except Exception as e:
            logger.error("Erreur lors de la configuration du monitoring: %s", e)
            logger.error(traceback.format_exc())
            return False

    # ------------------------------------------------------------------ #
    # Commande manuelle
    # ------------------------------------------------------------------ #

    @commands.command(name="monitor")
    @commands.has_permissions(administrator=True)
    async def monitor(self, ctx: commands.Context):
        """Commande pour démarrer/redémarrer manuellement le monitoring."""
        try:
            if self.STATUS_MESSAGE:
                try:
                    await self.rate_limiter.wait_if_needed("cleanup_main")
                    await self.STATUS_MESSAGE.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass
                self.STATUS_MESSAGE = None
                await self.message_cache.invalidate("main")

            if self.LAST_CONTROLLER_MESSAGE:
                try:
                    await self.rate_limiter.wait_if_needed("cleanup_last_controller")
                    await self.LAST_CONTROLLER_MESSAGE.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass
                self.LAST_CONTROLLER_MESSAGE = None
                await self.message_cache.invalidate("last_controller")

            await ctx.send(
                "Démarrage du système de monitoring amélioré... veuillez patienter."
            )

            await self.update_atc_cache()
            success = await self.setup_monitoring()
            if success:
                self.auto_setup_complete = True
                await ctx.send(
                    "Monitoring démarré avec succès. Le tableau est visible et se mettra à jour automatiquement."
                )
            else:
                await ctx.send(
                    "Impossible de démarrer le monitoring. Vérifiez les logs pour plus de détails."
                )
        except Exception as e:
            logger.error("Erreur lors de la commande monitor: %s", e)
            logger.error(traceback.format_exc())
            await ctx.send(f"Erreur: {str(e)}")

    # ------------------------------------------------------------------ #
    # Mise à jour sécurisée des messages (fix doublons)
    # ------------------------------------------------------------------ #

    async def update_message_safely(
        self, message: discord.Message, embed: discord.Embed, message_type: str
    ) -> bool:
        """Met à jour un message avec gestion d'erreurs et persistance des IDs."""
        async with self._message_lock:
            try:
                await self.rate_limiter.wait_if_needed(f"update_{message_type}")
                await message.edit(embed=embed)

                if message_type == "main":
                    self.STATUS_MESSAGE = message
                    self.save_message_id(
                        self.STATUS_MESSAGE.id,
                        self.STATUS_MESSAGE.channel.id,
                        self.LAST_CONTROLLER_MESSAGE.id
                        if self.LAST_CONTROLLER_MESSAGE
                        else None,
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
                logger.error("Message %s supprimé", message_type)
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
                logger.error(traceback.format_exc())
                return False

    # ------------------------------------------------------------------ #
    # Tâche principale de mise à jour
    # ------------------------------------------------------------------ #

    @tasks.loop(seconds=30)
    async def update_status_table(self):
        """Actualise les embeds de monitoring avec gestion robuste."""
        try:
            now_ts = int(datetime.now().timestamp())

            if self.failed_attempts >= 3 and (now_ts - self.last_update_attempt) > 120:
                logger.warning(
                    "Trop d'échecs consécutifs (%s), tentative de récupération du message",
                    self.failed_attempts,
                )
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
                logger.error(
                    "Message de statut introuvable pour mise à jour (tentative %s)",
                    self.failed_attempts,
                )
                return

            await self.update_atc_cache()
            main_embed, last_controller_embed = self.create_status_embeds()

            main_ok = await self.update_message_safely(
                self.STATUS_MESSAGE, main_embed, "main"
            )

            if main_ok:
                self.last_successful_update = datetime.now(timezone.utc)
                self.update_system_health()
                self.failed_attempts = 0
                self.last_update_attempt = now_ts

                if last_controller_embed:
                    if self.LAST_CONTROLLER_MESSAGE:
                        last_ok = await self.update_message_safely(
                            self.LAST_CONTROLLER_MESSAGE,
                            last_controller_embed,
                            "last_controller",
                        )
                        if not last_ok:
                            try:
                                await self.rate_limiter.wait_if_needed(
                                    "create_last_controller"
                                )
                                self.LAST_CONTROLLER_MESSAGE = (
                                    await self.STATUS_MESSAGE.channel.send(
                                        embed=last_controller_embed
                                    )
                                )
                                self.save_message_id(
                                    self.STATUS_MESSAGE.id,
                                    self.STATUS_MESSAGE.channel.id,
                                    self.LAST_CONTROLLER_MESSAGE.id,
                                )
                            except Exception as e:
                                logger.error(
                                    "Erreur création message last_controller: %s", e
                                )
                    else:
                        try:
                            await self.rate_limiter.wait_if_needed(
                                "create_last_controller"
                            )
                            self.LAST_CONTROLLER_MESSAGE = (
                                await self.STATUS_MESSAGE.channel.send(
                                    embed=last_controller_embed
                                )
                            )
                            self.save_message_id(
                                self.STATUS_MESSAGE.id,
                                self.STATUS_MESSAGE.channel.id,
                                self.LAST_CONTROLLER_MESSAGE.id,
                            )
                        except Exception as e:
                            logger.error(
                                "Erreur création message last_controller: %s", e
                            )

                logger.debug("Mise à jour réussie - Beat #%s", self.heartbeat_counter)
            else:
                self.failed_attempts += 1
                self.last_update_attempt = now_ts

        except Exception as e:
            logger.error("Erreur majeure dans update_status_table: %s", e)
            logger.error(traceback.format_exc())
            self.failed_attempts += 1
            self.last_update_attempt = int(datetime.now().timestamp())

    @update_status_table.before_loop
    async def before_update_status_table(self):
        await self.bot.wait_until_ready()
        logger.info("Bot prêt, tâche de mise à jour de statut prête à démarrer")

    # ------------------------------------------------------------------ #
    # Tâche de mise à jour du cache ATC
    # ------------------------------------------------------------------ #

    @tasks.loop(minutes=1)
    async def update_positions(self):
        """Mise à jour périodique du cache ATC."""
        try:
            success = await self.update_atc_cache()
            if success:
                logger.debug("Cache ATC mis à jour avec succès")
            else:
                logger.warning("Echec de mise à jour du cache ATC")
        except Exception as e:
            logger.error("Erreur lors de la mise à jour des positions: %s", e)
            logger.error(traceback.format_exc())

    @update_positions.before_loop
    async def before_update_positions(self):
        await self.bot.wait_until_ready()
        logger.info("Bot prêt, tâche de mise à jour des positions démarrée")


# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("utils/logs/monitoring.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


async def setup(bot: commands.Bot):
    await bot.add_cog(EnhancedMonitoring(bot))