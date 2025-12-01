import discord
from discord.ext import commands
import asyncio
import logging
from datetime import datetime, timezone, timedelta
import json
import aiohttp
from discord.ext import tasks
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
    raise ValueError("❌ IVAO_API_KEY non définie dans .env")

class DiscordRateLimiter:
    """Gère le rate limiting pour les opérations Discord"""
    def __init__(self, delay: float = 1.2):
        self.delay = delay
        self.last_operation = {}
        self._lock = asyncio.Lock()

    async def wait_if_needed(self, operation_key: str = "default"):
        """Attend si nécessaire pour respecter le rate limit"""
        async with self._lock:
            current_time = asyncio.get_event_loop().time()
            last_time = self.last_operation.get(operation_key, 0)
            
            time_since_last = current_time - last_time
            if time_since_last < self.delay:
                wait_time = self.delay - time_since_last
                await asyncio.sleep(wait_time)
            
            self.last_operation[operation_key] = asyncio.get_event_loop().time()

class MessageCache:
    """Cache pour les messages Discord validés"""
    def __init__(self):
        self._cache: Dict[str, discord.Message] = {}
        self._last_validation: Dict[str, float] = {}
        self._validation_timeout = 300  # 5 minutes
        self._lock = asyncio.Lock()

    async def get_message(self, message_type: str, channel: discord.TextChannel, message_id: Optional[str]) -> Optional[discord.Message]:
        """Récupère un message depuis le cache ou Discord"""
        if not message_id:
            return None
            
        async with self._lock:
            current_time = asyncio.get_event_loop().time()
            
            # Vérifier le cache
            if message_type in self._cache and message_type in self._last_validation:
                if current_time - self._last_validation[message_type] < self._validation_timeout:
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
        """Invalide le cache pour un type de message"""
        async with self._lock:
            self._cache.pop(message_type, None)
            self._last_validation.pop(message_type, None)

class EnhancedMonitoring(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.STATUS_MESSAGE = None
        self.LAST_CONTROLLER_MESSAGE = None
        self.auto_setup_complete = False
        self.setup_retries = 0
        self.max_retries = 5
        self.session = None
        self.ivao_session = None
        self.last_update_attempt = 0
        self.failed_attempts = 0
        self._message_lock = asyncio.Lock()
        
        # Nouveaux composants pour la résilience
        self.rate_limiter = DiscordRateLimiter(1.2)
        self.message_cache = MessageCache()
        self.heartbeat_counter = 0
        self.last_successful_update = datetime.now(timezone.utc)
        self.system_health = "healthy"  # healthy, warning, error
        
        # Configuration
        self.CHANNEL_ID = 1310926262566387753
        self.apikey = IVAO_API_KEY  # Clé API IVAO
        self.ATC_URL = "https://api.ivao.aero/v2/tracker/now/atc"
        self.CACHE_FILE = 'utils/atc_positions_cache.json'
        self.MESSAGE_ID_FILE = 'utils/status_message_id.json'
        self.USER_CACHE_FILE = 'utils/user_name_cache.json'
        self.LAST_CONTROLLER_FILE = 'utils/last_controller.json'
        self.USER_VID = "722124"  # Pour la récupération des noms
        self.USER_PASSWORD = "1ICGmIBMJP0Y"
        
        # Vérifier et créer les répertoires nécessaires
        os.makedirs('utils', exist_ok=True)
        os.makedirs('utils/logs', exist_ok=True)
        
        # Configuration des positions et régions (alignées avec le système de booking)
        self.setup_regions_and_positions()
        
        # Charger le cache des noms d'utilisateurs
        self.name_cache = self.load_user_name_cache()
        
        # Démarrer les tâches
        self.update_positions.start()
        self.auto_setup_task.start()

    def setup_regions_and_positions(self):
        """Configure les positions surveillées et leurs régions (alignées avec le système de booking)"""
        # Positions surveillées organisées par région (identiques au système de booking)
        self.REGIONS = {
            "ANTILLES": {
                "emoji": "🏝️",
                "color": 0x3498db,
                "positions": [
                    # TFFF - Martinique (Fort-de-France)
                    "TFFF_APP", "TFFF_DEL", "TFFF_TWR",
                    # TFFR - Guadeloupe (Pointe-à-Pitre)
                    "TFFR_APP", "TFFR_TWR",
                    # TFFJ - Saint-Barthélemy
                    "TFFJ_FIS_TWR", "TFFJ_I_TWR",
                    # TFFG - Saint-Martin
                    "TFFG_FIS_TWR", "TFFG_I_TWR",
                    # TFFM - Marie-Galante
                    "TFFM_I_TWR",
                ]
            },
            "GUYANE": {
                "emoji": "🌳",
                "color": 0x27ae60,
                "positions": [
                    # SOCA - Cayenne
                    "SOCA_APP", "SOCA_TWR",
                    # SOOO - Contrôle Océanique
                    "SOOO_CTR", "SOOO_MIL_CTR",
                ]
            },
            "POLYNÉSIE": {
                "emoji": "🌺",
                "color": 0xe74c3c,
                "positions": [
                    # NTAA - Tahiti-Faa'a (Papeete)
                    "NTAA_APP", "NTAA_DEL", "NTAA_TWR",
                    # NTTB - Bora Bora
                    "NTTB_TWR",
                    # NTTH - Huahine
                    "NTTH_FIS_TWR", "NTTH_I_TWR",
                    # NTTM - Moorea (Temae)
                    "NTTM_TWR",
                    # NTTR - Raiatea
                    "NTTR_TWR",
                    # NTTG - Rangiroa
                    "NTTG_FIS_TWR", "NTTG_I_TWR",
                    # NTTT - Centre de contrôle de Tahiti
                    "NTTT_CTR",
                    # NTAR - Rurutu
                    "NTAR_FIS_TWR", "NTAR_I_TWR",
                    # NTAT - Tubuai
                    "NTAT_FIS_TWR", "NTAT_I_TWR",
                    # NTAV - Raivavae
                    "NTAV_FIS_TWR", "NTAV_I_TWR",
                    # NTGC - Tikehau
                    "NTGC_FIS_TWR", "NTGC_I_TWR",
                    # NTGF - Fakarava
                    "NTGF_FIS_TWR", "NTGF_I_TWR",
                    # NTGI - Manihi
                    "NTGI_FIS_TWR", "NTGI_I_TWR",
                    # NTGJ - Totegegie (Gambier)
                    "NTGJ_FIS_TWR", "NTGJ_I_TWR",
                    # NTGK - Kaukura
                    "NTGK_FIS_TWR", "NTGK_I_TWR",
                    # NTGM - Makemo
                    "NTGM_FIS_TWR", "NTGM_I_TWR",
                    # NTGT - Takapoto
                    "NTGT_FIS_TWR", "NTGT_I_TWR",
                    # NTGU - Arutua
                    "NTGU_FIS_TWR", "NTGU_I_TWR",
                    # NTGV - Mataiva
                    "NTGV_FIS_TWR", "NTGV_I_TWR",
                    # NTMD - Nuku Hiva (Marquises)
                    "NTMD_FIS_TWR", "NTMD_I_TWR",
                    # NTMN - Atuona Hiva Oa
                    "NTMN_FIS_TWR", "NTMN_I_TWR",
                    # NTMP - Ua Pou (Marquises)
                    "NTMP_FIS_TWR", "NTMP_I_TWR",
                    # NTMU - Ua Huka (Marquises)
                    "NTMU_FIS_TWR", "NTMU_I_TWR",
                    # NTTO - Hao
                    "NTTO_FIS_TWR", "NTTO_I_TWR",
                    # NTTP - Maupiti
                    "NTTP_FIS_TWR", "NTTP_I_TWR",
                ]
            },
            "RÉUNION_MAYOTTE": {
                "emoji": "🌋",
                "color": 0xf39c12,
                "positions": [
                    # FMEE - La Réunion (Saint-Denis)
                    "FMEE_APP", "FMEE_GND", "FMEE_TWR",
                    # FMEP - Pierrefonds (Saint-Pierre)
                    "FMEP_FIS_TWR", "FMEP_I_TWR",
                    # FMCZ - Dzaoudzi (Mayotte)
                    "FMCZ_TWR",
                ]
            },
            "NOUVELLE_CALÉDONIE": {
                "emoji": "🐠",
                "color": 0x9b59b6,
                "positions": [
                    # NWWW - Nouméa La Tontouta
                    "NWWW_APP", "NWWW_GND", "NWWW_TWR",
                    # NWWM - Nouméa Magenta
                    "NWWM_APP", "NWWM_TWR",
                    # NWWL - Lifou Wanaham
                    "NWWL_FIS_TWR",
                    # NWWD - Koné
                    "NWWD_FIS_TWR", "NWWD_I_TWR",
                    # NWWE - Île des Pins Moué
                    "NWWE_FIS_TWR", "NWWE_I_TWR",
                    # NWWR - Maré La Roche
                    "NWWR_FIS_TWR", "NWWR_I_TWR",
                    # NWWU - Touho
                    "NWWU_FIS_TWR", "NWWU_I_TWR",
                    # NWWV - Ouvéa
                    "NWWV_FIS_TWR", "NWWV_I_TWR",
                ]
            },
            "WALLIS_FUTUNA": {
                "emoji": "🏖️",
                "color": 0x1abc9c,
                "positions": [
                    # NLWW - Wallis Hihifo
                    "NLWW_FIS_TWR", "NLWW_I_TWR",
                    # NLWF - Futuna Pointe Vele
                    "NLWF_FIS_TWR", "NLWF_I_TWR",
                ]
            },
            "SPM": {
                "emoji": "❄️",
                "color": 0x34495e,
                "positions": [
                    # LFVP - Saint-Pierre
                    "LFVP_APP", "LFVP_TWR",
                    # LFVM - Miquelon
                    "LFVM_FIS_TWR", "LFVM_I_TWR",
                ]
            }
        }
        
        # Créer une liste plate de toutes les positions surveillées
        self.MONITORED_POSITIONS = []
        for region in self.REGIONS.values():
            self.MONITORED_POSITIONS.extend(region["positions"])
        
        # Mappage des types de positions pour les couleurs et icônes
        self.POSITION_TYPES = {
            "TWR": {"emoji": "🗼", "name": "Tour"},
            "APP": {"emoji": "🛬", "name": "Approche"},
            "CTR": {"emoji": "🌐", "name": "Centre"},
            "DEL": {"emoji": "🧾", "name": "Délivrance"},
            "GND": {"emoji": "🚜", "name": "Sol"},
            "FIS": {"emoji": "🔭", "name": "Info Vol"},
            "I": {"emoji": "🔧", "name": "Maintenance"}
        }
        
        # Convertir les ratings IVAO
        self.IVAO_RATINGS = {
            2: "AS1", 3: "AS2", 4: "AS3",
            5: "ADC", 6: "APC", 7: "ACC",
            8: "SEC", 9: "SAI", 10: "CAI"
        }

    def get_heartbeat_emoji(self):
        """Retourne un emoji de heartbeat qui change"""
        heartbeat_emojis = ["💚", "💛", "❤️", "🧡", "💜", "💙"]
        return heartbeat_emojis[self.heartbeat_counter % len(heartbeat_emojis)]

    def get_system_status_emoji(self):
        """Retourne l'emoji de statut du système"""
        if self.system_health == "healthy":
            return "🟢"
        elif self.system_health == "warning":
            return "🟡"
        else:
            return "🔴"

    def update_system_health(self):
        """Met à jour l'état de santé du système"""
        now = datetime.now(timezone.utc)
        time_since_update = (now - self.last_successful_update).total_seconds()
        
        if time_since_update < 60:  # Moins d'1 minute
            self.system_health = "healthy"
        elif time_since_update < 300:  # Moins de 5 minutes
            self.system_health = "warning"
        else:  # Plus de 5 minutes
            self.system_health = "error"

    def cog_unload(self):
        """Nettoyage lors du déchargement du cog"""
        self.update_positions.cancel()
        self.auto_setup_task.cancel()
        if hasattr(self, 'update_status_table') and self.update_status_table.is_running():
            self.update_status_table.cancel()
        if self.session:
            asyncio.create_task(self.close_session())

    async def close_session(self):
        """Ferme proprement les sessions HTTP"""
        if self.session:
            await self.session.close()
            self.session = None
        if self.ivao_session:
            await self.ivao_session.close()
            self.ivao_session = None

    async def init_session(self):
        """Initialise les sessions HTTP si nécessaire"""
        if not self.session:
            self.session = aiohttp.ClientSession()
        if not self.ivao_session:
            self.ivao_session = aiohttp.ClientSession()

    @tasks.loop(seconds=10, count=None)
    async def auto_setup_task(self):
        """Tâche qui vérifie périodiquement si le monitoring est correctement configuré"""
        if self.auto_setup_complete:
            self.auto_setup_task.cancel()
            return
            
        if not self.bot.is_ready():
            return
            
        try:
            success = await self.setup_monitoring()
            if success:
                logger.info("✅ Auto-setup réussi!")
                self.auto_setup_complete = True
                self.auto_setup_task.cancel()
            else:
                self.setup_retries += 1
                logger.warning(f"⚠️ Échec de l'auto-setup. Tentative {self.setup_retries}/{self.max_retries}")
                if self.setup_retries >= self.max_retries:
                    logger.error("❌ Nombre maximum de tentatives d'auto-setup atteint. Passage à un intervalle plus long.")
                    self.auto_setup_task.change_interval(minutes=5)
                    self.setup_retries = 0
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'auto-setup: {e}")
            logger.error(traceback.format_exc())
            self.setup_retries += 1
            if self.setup_retries >= self.max_retries:
                logger.error("❌ Nombre maximum de tentatives d'auto-setup atteint. Passage à un intervalle plus long.")
                self.auto_setup_task.change_interval(minutes=5)
                self.setup_retries = 0

    @auto_setup_task.before_loop
    async def before_auto_setup(self):
        await self.bot.wait_until_ready()
        logger.info("✅ Bot prêt, tâche d'auto-setup démarrée")

    def format_duration(self, seconds, compact=False):
        """Formate une durée en heures et minutes avec option compacte"""
        if seconds is None or seconds < 0:
            seconds = 0
            
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        
        if compact:
            return f"{hours}h{minutes:02d}m"
        else:
            return f"{hours:02d}h {minutes:02d}min"

    def format_time_ago(self, timestamp):
        """Formate un timestamp en temps écoulé depuis (il y a X heures/minutes)"""
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
        elif seconds < 3600:
            minutes = int(seconds // 60)
            return f"il y a {minutes} minute{'s' if minutes > 1 else ''}"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            return f"il y a {hours} heure{'s' if hours > 1 else ''}"
        else:
            days = int(seconds // 86400)
            return f"il y a {days} jour{'s' if days > 1 else ''}"

    def get_position_type(self, position):
        """Détermine le type de position (TWR, APP, CTR, etc.)"""
        if not position:
            return "OTHER"
            
        if "_CTR" in position:
            return "CTR"
        elif "_APP" in position:
            return "APP"
        elif "_TWR" in position:
            return "TWR"
        elif "_DEL" in position:
            return "DEL"
        elif "_GND" in position:
            return "GND"
        elif "_FIS" in position:
            return "FIS"
        elif "_I_" in position or position.endswith("_I"):
            return "I"
        else:
            return "OTHER"

    def get_position_region(self, position):
        """Determine à quelle région appartient une position"""
        for region_name, region_data in self.REGIONS.items():
            if position in region_data["positions"]:
                return region_name
        return "Autre"

    def load_atc_cache(self):
        """Charge les positions ATC depuis le fichier cache"""
        try:
            with open(self.CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning("⚠️ Fichier cache introuvable ou corrompu, retour à un cache vide.")
            return {"active": {}, "recent": {}}

    def save_atc_cache(self, data):
        """Sauvegarde les positions ATC dans le fichier cache"""
        try:
            os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)
            with open(self.CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"❌ Erreur lors de la sauvegarde du cache ATC: {e}")
            return False

    def load_user_name_cache(self):
        """Charge le cache des noms d'utilisateurs"""
        try:
            with open(self.USER_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_user_name_cache(self):
        """Sauvegarde le cache des noms d'utilisateurs"""
        try:
            os.makedirs(os.path.dirname(self.USER_CACHE_FILE), exist_ok=True)
            with open(self.USER_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.name_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"❌ Erreur lors de la sauvegarde du cache des noms: {e}")

    def save_message_id(self, message_id=None, channel_id=None, last_controller_message_id=None):
        """Sauvegarde l'ID du message de statut et du canal avec validation"""
        data = {
            "message_id": str(message_id) if message_id else None,
            "channel_id": channel_id or self.CHANNEL_ID,
            "last_controller_message_id": str(last_controller_message_id) if last_controller_message_id else None,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        try:
            os.makedirs(os.path.dirname(self.MESSAGE_ID_FILE), exist_ok=True)
            with open(self.MESSAGE_ID_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ ID de message sauvegardé: {message_id} dans le canal {channel_id or self.CHANNEL_ID}")
            return True
        except Exception as e:
            logger.error(f"❌ Erreur lors de la sauvegarde de l'ID du message: {e}")
            return False

    def load_message_id(self):
        """Charge l'ID du message de statut depuis le fichier"""
        try:
            with open(self.MESSAGE_ID_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.info(f"✅ ID de message chargé: {data}")
                return data.get("message_id"), data.get("channel_id", self.CHANNEL_ID), data.get("last_controller_message_id")
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning("⚠️ Fichier d'ID de message introuvable ou corrompu, retour à None.")
            return None, self.CHANNEL_ID, None

    def save_last_controller(self, controller_data):
        """Sauvegarde les informations du dernier contrôleur dans un fichier JSON"""
        try:
            controller_data["saved_at"] = datetime.now(timezone.utc).isoformat()
            os.makedirs(os.path.dirname(self.LAST_CONTROLLER_FILE), exist_ok=True)
            with open(self.LAST_CONTROLLER_FILE, 'w', encoding='utf-8') as f:
                json.dump(controller_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"❌ Erreur lors de la sauvegarde des données du dernier contrôleur: {e}")
            return False

    def load_last_controller(self):
        """Charge les informations du dernier contrôleur depuis le fichier JSON"""
        try:
            with open(self.LAST_CONTROLLER_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning("⚠️ Fichier de dernier contrôleur introuvable ou corrompu, retour à un dictionnaire vide.")
            return {}

    async def get_user_name_from_vid(self, vid: int) -> Tuple[str, str]:
        """Récupère le nom d'un utilisateur à partir de son VID en utilisant le web scraping du site IVAO"""
        if not vid:
            return "Unknown", "User"
            
        # Vérifier d'abord dans le cache
        vid_str = str(vid)
        if vid_str in self.name_cache:
            cache_entry = self.name_cache[vid_str]
            # Vérifier si l'entrée du cache n'est pas trop ancienne (7 jours)
            if "updated_at" in cache_entry:
                try:
                    cache_time = datetime.fromisoformat(cache_entry["updated_at"].replace('Z', '+00:00'))
                    if (datetime.now(timezone.utc) - cache_time).days < 7:
                        return cache_entry["first_name"], cache_entry["last_name"]
                except:
                    pass
            else:
                return cache_entry["first_name"], cache_entry["last_name"]
            
        try:
            await self.init_session()

            # URL de la page de connexion
            login_url = "https://ivao.aero/Login.aspx"
            profile_url = f"https://ivao.aero/Member.aspx?Id={vid}"

            # Première requête pour obtenir les jetons CSRF
            async with self.session.get(login_url, params={"r": f"Member.aspx?Id={vid}"}) as response:
                if response.status != 200:
                    logger.error(f"❌ Erreur lors de l'accès à la page de connexion: {response.status}")
                    return "Unknown", "User"

                html_content = await response.text()
                soup = BeautifulSoup(html_content, 'html.parser')

                # Extraire les champs cachés nécessaires pour la connexion
                viewstate = soup.find('input', {'name': '__VIEWSTATE'})
                if not viewstate:
                    logger.error("❌ Impossible de trouver le viewstate dans la page de connexion")
                    return "Unknown", "User"
                viewstate = viewstate['value']
                
                viewstategenerator = soup.find('input', {'name': '__VIEWSTATEGENERATOR'})
                if not viewstategenerator:
                    logger.error("❌ Impossible de trouver le viewstategenerator dans la page de connexion")
                    return "Unknown", "User"
                viewstategenerator = viewstategenerator['value']
                
                eventvalidation = soup.find('input', {'name': '__EVENTVALIDATION'})
                if not eventvalidation:
                    logger.error("❌ Impossible de trouver l'eventvalidation dans la page de connexion")
                    return "Unknown", "User"
                eventvalidation = eventvalidation['value']
                
                try:
                    post_url = soup.find('input', {'name': 'ctl00$ContentPlaceHolder1$postUrl'})['value']
                except:
                    post_url = profile_url

            # Préparer les données de connexion
            login_data = {
                '__VIEWSTATE': viewstate,
                '__VIEWSTATEGENERATOR': viewstategenerator,
                '__EVENTVALIDATION': eventvalidation,
                'ctl00$ContentPlaceHolder1$postUrl': post_url,
                'ctl00$ContentPlaceHolder1$loginVID': self.USER_VID,
                'ctl00$ContentPlaceHolder1$loginPassword': self.USER_PASSWORD,
                'ctl00$ContentPlaceHolder1$loginRemember': 'on',
                'ctl00$ContentPlaceHolder1$loginBtn': 'Login'
            }

            # Effectuer la connexion
            async with self.session.post(login_url, data=login_data, allow_redirects=True) as response:
                if response.status != 200:
                    logger.error(f"❌ Échec de la connexion: {response.status}")
                    return "Unknown", "User"

            # Accéder à la page du profil
            async with self.session.get(profile_url) as response:
                if response.status != 200:
                    logger.error(f"❌ Échec d'accès au profil {vid}: {response.status}")
                    return "Unknown", "User"

                html_content = await response.text()
                soup = BeautifulSoup(html_content, 'html.parser')

                # Chercher le nom dans la page
                name_element = soup.find('h3')
                if name_element:
                    full_name = name_element.text.strip()

                    # Détection intelligente du prénom et du nom
                    parts = full_name.split()
                    if len(parts) >= 2:
                        # Considérer le dernier mot comme nom de famille
                        first_name = " ".join(parts[:-1])
                        last_name = parts[-1]
                    else:
                        first_name = full_name
                        last_name = ""

                    # Mettre en cache pour de futures utilisations
                    self.name_cache[vid_str] = {
                        "first_name": first_name, 
                        "last_name": last_name,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                    self.save_user_name_cache()
                    
                    return first_name, last_name

            return "Unknown", "User"

        except Exception as e:
            logger.error(f"❌ Erreur lors de la récupération du nom d'utilisateur pour VID {vid}: {str(e)}")
            return "Unknown", "User"

    def format_controller_name(self, first_name: str, last_name: str, user_id: int) -> str:
        """Formate le nom d'un contrôleur pour l'affichage"""
        if first_name == "Unknown" or not last_name:
            return f"Inconnu (VID: {user_id})"
            
        last_initial = last_name[0] if last_name else ""
        return f"{first_name} {last_initial}. (VID: {user_id})"

    async def update_atc_cache(self):
        """Met à jour le cache avec les positions ATC actuelles et récentes"""
        try:

            headers = {'apiKey': self.apikey, 'Accept': 'application/json'}
            await self.init_session()
            
            async with self.session.get(self.ATC_URL, headers=headers) as response:
                if response.status != 200:
                    response_text = await response.text()
                    logger.error(f"❌ Erreur API: {response.status} - {response_text}")
                    return False
                    
                all_controllers = await response.json()
                current_cache = self.load_atc_cache()
                active_positions = {}
                
                # Traiter les contrôleurs actifs
                for controller in all_controllers:
                    atc_position = controller.get('atcPosition')
                    if atc_position is None:
                        continue

                    callsign = atc_position.get('composePosition')
                    if callsign not in self.MONITORED_POSITIONS:
                        continue

                    user_id = controller.get('userId', 'N/A')
                    created_at = controller.get('createdAt', '')
                    try:
                        start_time = int(datetime.fromisoformat(created_at.replace('Z', '+00:00')).timestamp())
                    except Exception:
                        start_time = int(datetime.now(timezone.utc).timestamp())

                    # Récupérer le nom s'il n'est pas déjà en cache
                    first_name, last_name = "Unknown", "User"
                    if user_id and user_id != 'N/A':
                        try:
                            first_name, last_name = await self.get_user_name_from_vid(user_id)
                        except Exception as e:
                            logger.error(f"❌ Erreur lors de la récupération du nom pour {user_id}: {e}")

                    # Sauvegarder les données du contrôleur actif
                    active_positions[callsign] = {
                        'vid': user_id,
                        'rating': self.IVAO_RATINGS.get(controller.get('user', {}).get('rating', {}).get('atcRatingId', 0), 'Unknown'),
                        'start_time': start_time,
                        'first_name': first_name,
                        'last_name': last_name,
                        'position_type': self.get_position_type(callsign)
                    }

                # Vérifier quels contrôleurs ont déconnecté (ceux qui étaient actifs avant mais plus maintenant)
                previous_active = current_cache.get('active', {})
                now = int(datetime.now(timezone.utc).timestamp())
                recent_positions = current_cache.get('recent', {})
                
                for callsign, info in previous_active.items():
                    if callsign not in active_positions:
                        # Ce contrôleur s'est déconnecté, l'ajouter aux positions récentes
                        controller_data = {
                            'vid': info.get('vid', 'N/A'),
                            'rating': info.get('rating', 'Unknown'),
                            'start_time': info.get('start_time', 0),
                            'end_time': now,
                            'duration': now - info.get('start_time', now),
                            'first_name': info.get('first_name', 'Unknown'),
                            'last_name': info.get('last_name', 'User'),
                            'position_type': info.get('position_type', self.get_position_type(callsign)),
                            'callsign': callsign,
                            'region': self.get_position_region(callsign)
                        }
                        recent_positions[callsign] = controller_data
                        
                        # Sauvegarder le dernier contrôleur déconnecté
                        self.save_last_controller(controller_data)
                        
                # Limiter la taille du dictionnaire des positions récentes (garder seulement les 20 plus récentes)
                if len(recent_positions) > 20:
                    # Trier par end_time (du plus récent au plus ancien)
                    sorted_recent = sorted(recent_positions.items(), key=lambda x: x[1].get('end_time', 0), reverse=True)
                    # Garder uniquement les 20 premiers
                    recent_positions = dict(sorted_recent[:20])
                
                # Mettre à jour le cache
                updated_cache = {
                    'active': active_positions,
                    'recent': recent_positions,
                    'last_update': now
                }
                
                self.save_atc_cache(updated_cache)
                self.last_successful_update = datetime.now(timezone.utc)
                return True
                
        except Exception as e:
            logger.error(f"❌ Erreur lors de la mise à jour du cache ATC: {e}")
            logger.error(traceback.format_exc())
            return False

    def create_table_overview(self, active_sessions, region_name=None):
        """Crée un tableau en code bloc pour afficher les positions actives"""
        # Si un nom de région est spécifié, filtrer les positions pour cette région
        filtered_sessions = {}
        if region_name:
            for callsign, info in active_sessions.items():
                if self.get_position_region(callsign) == region_name:
                    filtered_sessions[callsign] = info
        else:
            filtered_sessions = active_sessions
            
        # Si aucune position après filtrage, renvoyer un message approprié
        if not filtered_sessions:
            if region_name:
                return f"```yaml\n# Aucune position active dans la région {region_name}\n```"
            else:
                return "```yaml\n# Aucune position ATC active actuellement\n```"
                
        # Créer l'en-tête du tableau
        header = f"{'Position':<15} | {'Contrôleur':<18} | {'VID':<7} | {'Rating':<5} | {'Durée':<12}"
        separator = "-" * 70
        
        # Créer les lignes du tableau
        table_lines = [header, separator]
        
        # Trier les positions par callsign
        sorted_sessions = sorted(filtered_sessions.items())
        
        for callsign, info in sorted_sessions:
            # Obtenir le type de position pour une éventuelle mise en forme
            position_type = info.get('position_type', 'OTHER')
            
            # Formater le nom du contrôleur
            first_name = info.get('first_name', 'Unknown')
            last_name = info.get('last_name', 'User')
            vid = info.get('vid', 'N/A')
            
            if first_name != "Unknown" and last_name:
                controller_name = f"{first_name} {last_name[0]}."[:18]  # Limiter à 18 caractères
            else:
                controller_name = "Inconnu"
                
            # Calculer la durée en ligne
            now = datetime.now(timezone.utc)
            start_time = info.get('start_time', 0)
            if start_time:
                try:
                    start_time_dt = datetime.fromtimestamp(start_time, timezone.utc)
                    duration = (now - start_time_dt).total_seconds()
                    duration_str = self.format_duration(duration, compact=True)
                except Exception:
                    duration_str = "N/A"
            else:
                duration_str = "N/A"
                
            # Ajouter la ligne au tableau
            line = f"{callsign:<15} | {controller_name:<18} | {str(vid):<7} | {info.get('rating', 'N/A'):<5} | {duration_str:<12}"
            table_lines.append(line)
            
        # Assembler le tableau final
        return f"```yaml\n{chr(10).join(table_lines)}\n```"

    def create_status_embeds(self):
        """Crée les embeds pour afficher le statut des positions ATC avec heartbeat et indicateurs de santé"""
        # Charger les données
        data = self.load_atc_cache()
        active_sessions = data.get('active', {})
        
        # Mettre à jour le heartbeat et la santé du système
        self.heartbeat_counter += 1
        self.update_system_health()
        
        # Créer l'embed principal avec le tableau
        heartbeat = self.get_heartbeat_emoji()
        system_status = self.get_system_status_emoji()
        
        main_embed = discord.Embed(
            title=f"{heartbeat} MONITORING DES POSITIONS ATC ULTRAMARINES {system_status}",
            color=0x1E90FF,  # Bleu royal
            timestamp=datetime.now(timezone.utc)
        )
        
        # Ajouter un lien vers le site IVAO
        main_embed.url = "https://webeye.ivao.aero/"
        
        # Ajouter l'image de thumbnail
        main_embed.set_thumbnail(url="https://upload.wikimedia.org/wikipedia/commons/c/c3/Flag_of_France.svg")
        
        # Ajouter les informations générales avec indicateurs de santé
        position_count = len(active_sessions)
        
        # Informations sur la dernière mise à jour
        last_update_time = data.get('last_update', 0)
        if last_update_time:
            last_update_str = self.format_time_ago(last_update_time)
        else:
            last_update_str = "jamais"
        
        status_text = (
            f"**Statut en temps réel des positions de contrôle ultramarines**\n"
            f"{system_status} **{position_count}** position{'s' if position_count != 1 else ''} active{'s' if position_count != 1 else ''} actuellement\n"
            f"🕒 **Dernière mise à jour:** {last_update_str}\n"
            f"💭 **Heartbeat:** Battement #{self.heartbeat_counter}\n"
            f"📊 **Statut système:** {self.system_health.title()}"
        )
        main_embed.description = status_text
        
        # Ajouter un tableau pour chaque région, même s'il n'y a pas de contrôleurs
        for region_name, region_info in self.REGIONS.items():
            region_emoji = region_info["emoji"]
            region_table = self.create_table_overview(active_sessions, region_name)
            main_embed.add_field(name=f"{region_emoji} {region_name}", value=region_table, inline=False)
        
        # Créer l'embed pour le dernier contrôleur déconnecté
        last_controller_embed = None
        
        # Charger le dernier contrôleur depuis le fichier
        last_controller = self.load_last_controller()
        
        if last_controller:
            # Formater le nom du contrôleur
            controller_name = self.format_controller_name(
                last_controller.get('first_name', 'Unknown'), 
                last_controller.get('last_name', 'User'), 
                last_controller.get('vid', 'N/A')
            )
            
            # Formater la durée de session
            duration_str = self.format_duration(last_controller.get('duration', 0))
            
            # Créer l'embed pour le dernier contrôleur
            position_type = last_controller.get('position_type', 'OTHER')
            type_emoji = self.POSITION_TYPES.get(position_type, {}).get("emoji", "🔹")
            callsign = last_controller.get('callsign', 'UNKNOWN')
            
            last_controller_embed = discord.Embed(
                title=f"{type_emoji} Dernière position fermée: {callsign}",
                description=(
                    f"**Contrôleur:** {controller_name}\n"
                    f"**Rating:** {last_controller.get('rating', 'Unknown')}\n"
                    f"**Durée de session:** {duration_str}\n"
                    f"**Déconnecté:** {self.format_time_ago(last_controller.get('end_time', 0))}"
                ),
                color=0x4286f4,  # Bleu clair
                timestamp=datetime.fromtimestamp(last_controller.get('end_time', 0), timezone.utc)
            )
            
            # Obtenir la région pour la couleur
            region = last_controller.get('region', 'Inconnue')
            region_info = self.REGIONS.get(region, {"emoji": "🌍"})
            region_emoji = region_info["emoji"]
            
            last_controller_embed.set_footer(text=f"{region_emoji} {region} • Antilles Contrôle")
        
        # Ajouter le footer au message principal
        main_embed.set_footer(
            text=f"🔄 Mis à jour automatiquement • Antilles Contrôle • Beat #{self.heartbeat_counter}",
            icon_url="https://em-content.zobj.net/thumbs/120/twitter/321/airplane_2708-fe0f.png"
        )
        
        return main_embed, last_controller_embed

    async def find_status_message(self, channel_id=None):
        """Recherche le message de statut dans le canal spécifié avec cache amélioré"""
        # Si un ID de message est déjà configuré, l'utiliser d'abord
        message_id, stored_channel_id, last_controller_message_id = self.load_message_id()
        
        # Si un canal spécifique est demandé, l'utiliser
        if channel_id:
            channel = self.bot.get_channel(channel_id)
        # Sinon, vérifier le canal stocké et celui par défaut
        else:
            channel = self.bot.get_channel(stored_channel_id) or self.bot.get_channel(self.CHANNEL_ID)
        
        if not channel:
            logger.error(f"❌ Canal introuvable: {stored_channel_id}")
            return None, None, None
            
        # Si on a un ID de message, essayer de le récupérer via le cache
        if message_id:
            try:
                message = await self.message_cache.get_message("main", channel, message_id)
                
                # Si on a aussi un ID pour le message du dernier contrôleur
                last_controller_message = None
                if last_controller_message_id:
                    try:
                        last_controller_message = await self.message_cache.get_message("last_controller", channel, last_controller_message_id)
                    except Exception:
                        last_controller_message = None
                
                if message:
                    logger.info(f"✅ Message de statut trouvé: {message.id}")
                    return message, channel, last_controller_message
            except Exception as e:
                logger.warning(f"⚠️ Message {message_id} non trouvé: {e}")
        
        # Si le message n'a pas été trouvé avec l'ID stocké, chercher dans l'historique récent
        try:
            main_message = None
            last_controller_message = None
            
            async for message in channel.history(limit=30):  # Augmenté de 20 à 30
                if message.author == self.bot.user and message.embeds:
                    embed = message.embeds[0]
                    if "MONITORING DES POSITIONS ATC ULTRAMARINES" in embed.title:
                        main_message = message
                        break
            
            # Chercher le message du dernier contrôleur
            if main_message:
                async for message in channel.history(limit=10, after=main_message):
                    if message.author == self.bot.user and message.embeds:
                        embed = message.embeds[0]
                        if "Dernière position fermée" in embed.title:
                            last_controller_message = message
                            break
                
                logger.info(f"✅ Message de statut trouvé dans l'historique: {main_message.id}")
                self.save_message_id(main_message.id, channel.id, last_controller_message.id if last_controller_message else None)
                return main_message, channel, last_controller_message
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning(f"⚠️ Impossible de lire l'historique du canal {channel.id}: {e}")
        
        # Aucun message trouvé
        return None, channel, None

    async def setup_monitoring(self):
        """Configuration du monitoring - utilisé par on_ready et la commande monitor"""
        try:
            # Assurez-vous que le bot est prêt
            if not self.bot.is_ready():
                logger.warning("⚠️ Le bot n'est pas encore prêt. Configuration reportée.")
                return False
            
            # Vérifier que le canal existe
            default_channel = self.bot.get_channel(self.CHANNEL_ID)
            if not default_channel:
                logger.error(f"❌ Canal par défaut {self.CHANNEL_ID} non trouvé!")
                # Chercher un canal alternatif pour le monitoring
                guild = next((g for g in self.bot.guilds), None)
                if guild:
                    for channel in guild.text_channels:
                        if "monitoring" in channel.name.lower() or "position" in channel.name.lower():
                            logger.info(f"✅ Canal alternatif trouvé: {channel.name} ({channel.id})")
                            default_channel = channel
                            self.CHANNEL_ID = channel.id
                            break
                if not default_channel:
                    return False

            # Chercher le message existant
            message, channel, last_controller_message = await self.find_status_message()
            self.STATUS_MESSAGE = message
            self.LAST_CONTROLLER_MESSAGE = last_controller_message
            
            # S'assurer que les données sont chargées
            await self.update_atc_cache()
            
            # Si aucun message n'a été trouvé, en créer un nouveau
            if not self.STATUS_MESSAGE:
                await self.rate_limiter.wait_if_needed("setup_main")
                
                main_embed, last_controller_embed = self.create_status_embeds()
                
                # Envoyer l'embed principal
                self.STATUS_MESSAGE = await channel.send(embed=main_embed)
                
                # Si nous avons des informations sur le dernier contrôleur, les ajouter
                if last_controller_embed:
                    await self.rate_limiter.wait_if_needed("setup_last_controller")
                    self.LAST_CONTROLLER_MESSAGE = await channel.send(embed=last_controller_embed)
                    
                logger.info(f"✅ Nouveau message de statut créé: {self.STATUS_MESSAGE.id}")
                
                # Sauvegarder l'ID du nouveau message
                self.save_message_id(
                    self.STATUS_MESSAGE.id, 
                    channel.id, 
                    self.LAST_CONTROLLER_MESSAGE.id if self.LAST_CONTROLLER_MESSAGE else None
                )

            # Démarrer la tâche de mise à jour si elle n'est pas déjà en cours
            if not hasattr(self, 'update_status_table') or not self.update_status_table.is_running():
                self.update_status_table.start()
                logger.info("✅ Tâche de mise à jour du statut démarrée")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de la configuration du monitoring: {e}")
            logger.error(traceback.format_exc())
            return False

    @commands.command(name="monitor")
    @commands.has_permissions(administrator=True)
    async def monitor(self, ctx):
        """Commande pour démarrer/redémarrer manuellement le monitoring"""
        try:
            # Nettoyer les anciens messages avec rate limiting
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
            
            await ctx.send("🔄 Démarrage du système de monitoring amélioré... veuillez patienter.")
            
            # Mettre à jour le cache avant de créer le message
            await self.update_atc_cache()
            
            success = await self.setup_monitoring()
            if success:
                self.auto_setup_complete = True
                await ctx.send("✅ Monitoring démarré avec succès! Le tableau est maintenant visible et se mettra à jour automatiquement avec heartbeat.")
            else:
                await ctx.send("❌ Impossible de démarrer le monitoring. Vérifiez les logs pour plus de détails.")
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'exécution de la commande monitor: {e}")
            logger.error(traceback.format_exc())
            await ctx.send(f"❌ Erreur: {str(e)}")

    async def update_message_safely(self, message, embed, message_type):
        """Met à jour un message de manière sécurisée avec gestion d'erreurs"""
        async with self._message_lock:
            try:
                await self.rate_limiter.wait_if_needed(f"update_{message_type}")
                await message.edit(embed=embed)
                return True
            except discord.NotFound:
                logger.error(f"❌ Le message {message_type} a été supprimé")
                if message_type == "main":
                    self.STATUS_MESSAGE = None
                else:
                    self.LAST_CONTROLLER_MESSAGE = None
                await self.message_cache.invalidate(message_type)
                return False
            except discord.HTTPException as e:
                logger.error(f"❌ Erreur HTTP lors de la mise à jour {message_type}: {e}")
                if "Unknown Message" in str(e):
                    if message_type == "main":
                        self.STATUS_MESSAGE = None
                    else:
                        self.LAST_CONTROLLER_MESSAGE = None
                    await self.message_cache.invalidate(message_type)
                return False
            except Exception as e:
                logger.error(f"❌ Erreur inattendue lors de la mise à jour {message_type}: {e}")
                return False

    @tasks.loop(seconds=30)
    async def update_status_table(self):
        """Actualise le tableau des positions ATC avec gestion robuste des erreurs"""
        try:
            now = int(datetime.now().timestamp())
            
            # Si trop de tentatives échouées consécutives, essayer de trouver ou recréer le message
            if self.failed_attempts >= 3 and (now - self.last_update_attempt) > 120:
                logger.warning(f"⚠️ Trop d'échecs consécutifs ({self.failed_attempts}), recherche du message...")
                message, channel, last_controller_message = await self.find_status_message()
                if message:
                    self.STATUS_MESSAGE = message
                    self.LAST_CONTROLLER_MESSAGE = last_controller_message
                    self.failed_attempts = 0
                else:
                    # Si le message est introuvable, le recréer
                    logger.info("🔄 Recréation du message de monitoring...")
                    await self.setup_monitoring()
                    return
                    
            # Vérifier que le message existe
            if not self.STATUS_MESSAGE:
                self.last_update_attempt = now
                self.failed_attempts += 1
                logger.error(f"❌ Message de statut introuvable pour mise à jour (tentative {self.failed_attempts}).")
                return

            # Créer les embeds mis à jour
            main_embed, last_controller_embed = self.create_status_embeds()
            
            # Mettre à jour l'embed principal
            main_update_success = await self.update_message_safely(self.STATUS_MESSAGE, main_embed, "main")
            
            if main_update_success:
                # Gérer le message du dernier contrôleur
                if last_controller_embed:
                    if self.LAST_CONTROLLER_MESSAGE:
                        last_controller_update_success = await self.update_message_safely(
                            self.LAST_CONTROLLER_MESSAGE, last_controller_embed, "last_controller"
                        )
                        
                        if not last_controller_update_success:
                            # Créer un nouveau message pour le dernier contrôleur
                            try:
                                await self.rate_limiter.wait_if_needed("create_last_controller")
                                self.LAST_CONTROLLER_MESSAGE = await self.STATUS_MESSAGE.channel.send(embed=last_controller_embed)
                                self.save_message_id(
                                    self.STATUS_MESSAGE.id, 
                                    self.STATUS_MESSAGE.channel.id, 
                                    self.LAST_CONTROLLER_MESSAGE.id
                                )
                            except Exception as e:
                                logger.error(f"❌ Erreur lors de la création du nouveau message last_controller: {e}")
                    else:
                        # Créer un nouveau message pour le dernier contrôleur
                        try:
                            await self.rate_limiter.wait_if_needed("create_last_controller")
                            self.LAST_CONTROLLER_MESSAGE = await self.STATUS_MESSAGE.channel.send(embed=last_controller_embed)
                            self.save_message_id(
                                self.STATUS_MESSAGE.id, 
                                self.STATUS_MESSAGE.channel.id, 
                                self.LAST_CONTROLLER_MESSAGE.id
                            )
                        except Exception as e:
                            logger.error(f"❌ Erreur lors de la création du message last_controller: {e}")
                
                self.failed_attempts = 0
                self.last_update_attempt = now
                logger.debug(f"✅ Mise à jour réussie - Beat #{self.heartbeat_counter}")
                
            else:
                self.failed_attempts += 1
                self.last_update_attempt = now
                
        except Exception as e:
            logger.error(f"❌ Erreur majeure dans update_status_table: {e}")
            logger.error(traceback.format_exc())
            self.failed_attempts += 1
            self.last_update_attempt = int(datetime.now().timestamp())

    @update_status_table.before_loop
    async def before_update_status_table(self):
        await self.bot.wait_until_ready()
        logger.info("✅ Bot prêt, tâche de mise à jour de statut prête à démarrer")

    @tasks.loop(minutes=1)
    async def update_positions(self):
        """Mise à jour des données dans le fichier cache"""
        try:
            success = await self.update_atc_cache()
            if success:
                logger.debug("✅ Cache ATC mis à jour avec succès")
            else:
                logger.warning("⚠️ Échec de la mise à jour du cache ATC")
        except Exception as e:
            logger.error(f"❌ Erreur lors de la mise à jour des positions: {e}")
            logger.error(traceback.format_exc())

    @update_positions.before_loop
    async def before_update_positions(self):
        await self.bot.wait_until_ready()
        logger.info("✅ Bot prêt, tâche de mise à jour des positions démarrée")

# Configuration du logging améliorée
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("utils/logs/monitoring.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Permet de manipuler le temps
import time

async def setup(bot):
    await bot.add_cog(EnhancedMonitoring(bot))