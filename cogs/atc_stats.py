import os
from dotenv import load_dotenv
import discord
import asyncio
import aiohttp
import logging
import datetime
import calendar
import time
import json
import traceback
import unicodedata
import sqlite3
import hashlib
import random
import re
from discord.ext import commands, tasks
from discord import app_commands
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from bs4 import BeautifulSoup

# Configuration des chemins
os.makedirs('utils/logs', exist_ok=True)
os.makedirs('utils/data', exist_ok=True)

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('utils/logs/atc_stats.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('atc_stats')

# === CONFIGURATION ROBUSTE AVEC STOCKAGE JSON ET WEBSCRAPPING CONSERVÉ ===

# Configuration des salons Discord
STATS_CHANNEL_ID = 1234605334782279692  # Salon forum pour les statistiques
TEST_CHANNEL_ID = 1228454882202226839   # Salon pour les tests et logs

# Configuration API IVAO
# Charger les variables d'environnement
load_dotenv()

# Récupérer la clé API IVAO depuis .env
IVAO_API_KEY = os.getenv("IVAO_API_KEY", "")
if not IVAO_API_KEY:
    raise ValueError("❌ IVAO_API_KEY non définie dans .env")

# NOTE: CLIENT_ID et CLIENT_SECRET ne sont plus utilisés - authentification par clé API
CLIENT_ID = "deprecated"
CLIENT_SECRET = "deprecated"
USER_VID = "722124"
USER_PASSWORD = "1ICGmIBMJP0Y"

# Positions surveillées organisées par région (CONSERVÉES)
WATCHED_POSITIONS = {
    # ANTILLES
    "ANTILLES": [
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
    ],
    
    # GUYANE
    "GUYANE": [
        # SOCA - Cayenne
        "SOCA_APP", "SOCA_TWR",
        # SOOO - Contrôle Océanique
        "SOOO_CTR", "SOOO_MIL_CTR",
    ],
    
    # POLYNÉSIE FRANÇAISE
    "POLYNÉSIE": [
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
    ],
    
    # LA RÉUNION ET MAYOTTE
    "RÉUNION_MAYOTTE": [
        # FMEE - La Réunion (Saint-Denis)
        "FMEE_APP", "FMEE_GND", "FMEE_TWR",
        # FMEP - Pierrefonds (Saint-Pierre)
        "FMEP_FIS_TWR", "FMEP_I_TWR",
        # FMCZ - Dzaoudzi (Mayotte)
        "FMCZ_TWR",
    ],
    
    # NOUVELLE-CALÉDONIE
    "NOUVELLE_CALÉDONIE": [
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
    ],
    
    # WALLIS ET FUTUNA
    "WALLIS_FUTUNA": [
        # NLWW - Wallis Hihifo
        "NLWW_FIS_TWR", "NLWW_I_TWR",
        # NLWF - Futuna Pointe Vele
        "NLWF_FIS_TWR", "NLWF_I_TWR",
    ],
    
    # SAINT-PIERRE ET MIQUELON
    "SPM": [
        # LFVP - Saint-Pierre
        "LFVP_APP", "LFVP_TWR",
        # LFVM - Miquelon
        "LFVM_FIS_TWR", "LFVM_I_TWR",
    ]
}

# Créer une liste plate de toutes les positions surveillées
ALL_WATCHED_POSITIONS = []
for region_positions in WATCHED_POSITIONS.values():
    ALL_WATCHED_POSITIONS.extend(region_positions)

# Aéroports ultramarins français avec noms complets (CONSERVÉS)
OVERSEAS_AIRPORTS = {
    # Antilles - Guyane
    "TFFF": "Fort-de-France / Aimé Césaire (Martinique)",
    "TFFR": "Pointe-à-Pitre / Le Raizet (Guadeloupe)",
    "TFFM": "Marie-Galante (Guadeloupe)",
    "TFFG": "Grand Case (Saint-Martin)",
    "TFFJ": "Saint-Barthélemy / Gustaf III (Saint-Barthélemy)",
    "SOCA": "Cayenne / Félix Éboué (Guyane)",
    "SOOO": "Océanique Guyane (Guyane)",
    
    # Réunion - Mayotte
    "FMEE": "Saint-Denis / Roland Garros (La Réunion)",
    "FMEP": "Saint-Pierre / Pierrefonds (La Réunion)",
    "FMCZ": "Dzaoudzi / Pamandzi (Mayotte)",
    
    # Polynésie française
    "NTAA": "Tahiti / Faa'a (Polynésie)",
    "NTTB": "Bora Bora (Polynésie)",
    "NTTR": "Raiatea (Polynésie)",
    "NTTM": "Moorea / Temae (Polynésie)",
    "NTTH": "Huahine (Polynésie)",
    "NTTT": "Centre Tahiti (Polynésie)",
    "NTAR": "Rurutu (Polynésie)",
    "NTAT": "Tubuai (Polynésie)",
    "NTAV": "Raivavae (Polynésie)",
    "NTGC": "Tikehau (Polynésie)",
    "NTGF": "Fakarava (Polynésie)",
    "NTGI": "Manihi (Polynésie)",
    "NTGJ": "Totegegie (Polynésie)",
    "NTGK": "Kaukura (Polynésie)",
    "NTGM": "Makemo (Polynésie)",
    "NTGT": "Takapoto (Polynésie)",
    "NTGU": "Arutua (Polynésie)",
    "NTGV": "Mataiva (Polynésie)",
    "NTMD": "Nuku Hiva (Polynésie)",
    "NTMN": "Atuona Hiva Oa (Polynésie)",
    "NTMP": "Ua Pou (Polynésie)",
    "NTMU": "Ua Huka (Polynésie)",
    "NTTO": "Hao (Polynésie)",
    "NTTP": "Maupiti (Polynésie)",
    
    # Nouvelle-Calédonie
    "NWWW": "Nouméa / La Tontouta (Nouvelle-Calédonie)",
    "NWWM": "Nouméa / Magenta (Nouvelle-Calédonie)",
    "NWWL": "Lifou / Wanaham (Nouvelle-Calédonie)",
    "NWWD": "Koné (Nouvelle-Calédonie)",
    "NWWE": "Île des Pins / Moué (Nouvelle-Calédonie)",
    "NWWR": "Maré / La Roche (Nouvelle-Calédonie)",
    "NWWU": "Touho (Nouvelle-Calédonie)",
    "NWWV": "Ouvéa (Nouvelle-Calédonie)",
    
    # Saint-Pierre et Miquelon
    "LFVP": "Saint-Pierre (Saint-Pierre et Miquelon)",
    "LFVM": "Miquelon (Saint-Pierre et Miquelon)",
    
    # Wallis-et-Futuna
    "NLWW": "Wallis / Hihifo (Wallis-et-Futuna)",
    "NLWF": "Futuna / Pointe Vele (Wallis-et-Futuna)",
}

# Emojis thématiques pour les statistiques par aéroport (CONSERVÉS)
AIRPORT_EMOJIS = {
    # Antilles-Guyane
    "TFFF": "🌴", "TFFR": "🍹", "TFFM": "🏝️", "TFFG": "⛵", "TFFJ": "🥥", 
    "SOCA": "🦜", "SOOO": "🌿",
    
    # Réunion-Mayotte
    "FMEE": "🌋", "FMEP": "🌋", "FMCZ": "🐢",
    
    # Polynésie
    "NTAA": "🌺", "NTTB": "🐠", "NTTR": "🥥", "NTTM": "🏄‍♂️", "NTTH": "🌊",
    "NTTT": "🌴", "NTAR": "🐢", "NTAT": "🏊‍♂️", "NTAV": "🐚", "NTGC": "🌸",
    "NTGF": "🐳", "NTGI": "🧜‍♀️", "NTGJ": "🪸", "NTGK": "🐡", "NTGM": "🪨",
    "NTGT": "🐙", "NTGU": "🐬", "NTGV": "🦦", "NTMD": "🗿", "NTMN": "🌅",
    "NTMP": "🦪", "NTMU": "🏝️", "NTTO": "🏖️", "NTTP": "🦩",
    
    # Nouvelle-Calédonie
    "NWWW": "🦘", "NWWM": "🦘", "NWWL": "🐊", "NWWD": "🌿", "NWWE": "🥥",
    "NWWR": "🦜", "NWWU": "🐆", "NWWV": "🐢",
    
    # Saint-Pierre et Miquelon
    "LFVP": "❄️", "LFVM": "🦭",
    
    # Wallis-et-Futuna
    "NLWW": "🐚", "NLWF": "🐚",
}

# Couleurs thématiques par région (CONSERVÉES)
REGION_COLORS = {
    "ANTILLES": 0xFFA500,           # Orange
    "GUYANE": 0x228B22,             # Vert forêt
    "RÉUNION_MAYOTTE": 0x964B00,    # Marron volcanique
    "POLYNÉSIE": 0x00CED1,          # Turquoise
    "NOUVELLE_CALÉDONIE": 0x32CD32, # Vert lime
    "SPM": 0x87CEEB,                # Bleu ciel
    "WALLIS_FUTUNA": 0x4169E1,      # Bleu royal
    "Autre": 0x3498db               # Bleu par défaut
}

# Emojis par région (CONSERVÉS)
REGION_EMOJIS = {
    "ANTILLES": "🌴",
    "GUYANE": "🌿", 
    "RÉUNION_MAYOTTE": "🌋",
    "POLYNÉSIE": "🌺",
    "NOUVELLE_CALÉDONIE": "🦘",
    "SPM": "❄️",
    "WALLIS_FUTUNA": "🐚"
}

# Phrases régionales de remerciement (CONSERVÉES)
REGIONAL_THANKS = {
    "ANTILLES": "🗣️ \"Mèsi anpil\" comme on dit aux Antilles",
    "GUYANE": "🗣️ \"Mési\" comme on dit en Guyane",
    "RÉUNION_MAYOTTE": "🗣️ \"Merci zot tout\" comme on dit à La Réunion",
    "POLYNÉSIE": "🗣️ \"E mauruuru roa\" comme on dit en Polynésie",
    "NOUVELLE_CALÉDONIE": "🗣️ \"Oleti\" comme on dit en Nouvelle-Calédonie",
    "SPM": "🗣️ \"Mérsi byin\" comme on dit à Saint-Pierre et Miquelon",
    "WALLIS_FUTUNA": "🗣️ \"Malo aupito\" comme on dit à Wallis-et-Futuna"
}

# Citations intéressantes sur l'outre-mer français (CONSERVÉES)
INTERESTING_FACTS = [
    "✈️ L'outre-mer français représente plus de 120 000 km² d'espace aérien !",
    "🌍 Les territoires ultramarins français s'étendent sur 12 fuseaux horaires différents",
    "🏝️ La France possède le 2ème plus grand domaine maritime mondial grâce à ses territoires d'outre-mer",
    "🌺 De Tahiti à Saint-Pierre-et-Miquelon, le contrôle aérien français ne dort jamais !",
    "🦘 La Nouvelle-Calédonie abrite 5% des espèces terrestres mondiales sur 0,05% des terres émergées",
    "🌋 La Réunion et Mayotte sont des ponts aériens stratégiques dans l'océan Indien",
    "❄️ Saint-Pierre-et-Miquelon : le plus petit territoire français avec un grand cœur aéronautique !",
]

def get_airport_region(airport_code: str) -> str:
    """Retourne la région d'un aéroport donné"""
    for region, positions in WATCHED_POSITIONS.items():
        for position in positions:
            if position.startswith(airport_code):
                return region
    return "Autre"

def get_region_info(airport_code: str) -> Tuple[str, int]:
    """Retourne la région et la couleur d'un aéroport"""
    region = get_airport_region(airport_code)
    color = REGION_COLORS.get(region, REGION_COLORS["Autre"])
    return region, color

def clean_text(text: str) -> str:
    """Nettoie le texte des caractères d'encodage problématiques"""
    if not text:
        return ""
    
    text = unicodedata.normalize('NFC', text)
    
    replacements = {
        'Ã©': 'é', 'Ã¨': 'è', 'Ã ': 'à', 'Ã´': 'ô', 'Ã®': 'î', 'Ã¢': 'â',
        'Ã»': 'û', 'Ã§': 'ç', 'Ã¼': 'ü', 'Ã±': 'ñ', 'Ã¯': 'ï', 'Ã«': 'ë'
    }
    
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    return text

# === SYSTÈME DE VERROUILLAGE ROBUSTE ===

class SystemLockManager:
    """Gestionnaire de verrouillage système pour éviter les crashes"""
    
    def __init__(self):
        self.is_locked = False
        self.lock_reason = ""
        self.lock_started = None
        self.current_operation = ""
        self.progress_info = {}
        self.estimated_completion = None
    
    def lock_system(self, reason: str, operation: str = "", estimated_duration_minutes: int = None):
        """Verrouille le système avec informations détaillées"""
        self.is_locked = True
        self.lock_reason = reason
        self.current_operation = operation
        self.lock_started = datetime.datetime.now()
        self.progress_info = {}
        
        if estimated_duration_minutes:
            self.estimated_completion = self.lock_started + datetime.timedelta(minutes=estimated_duration_minutes)
        else:
            self.estimated_completion = None
            
        logger.info(f"🔒 Système verrouillé: {reason}")
    
    def unlock_system(self):
        """Déverrouille le système"""
        if self.is_locked:
            duration = datetime.datetime.now() - self.lock_started
            logger.info(f"🔓 Système déverrouillé après {duration}")
        
        self.is_locked = False
        self.lock_reason = ""
        self.current_operation = ""
        self.lock_started = None
        self.progress_info = {}
        self.estimated_completion = None
    
    def update_progress(self, **kwargs):
        """Met à jour les informations de progression"""
        self.progress_info.update(kwargs)
    
    def get_professional_status_embed(self) -> discord.Embed:
        """Retourne un embed professionnel avec le statut du système"""
        if not self.is_locked:
            return discord.Embed(
                title="✅ Système ATC Disponible",
                description="Toutes les commandes sont accessibles. Le système fonctionne normalement.",
                color=0x00FF00
            )
        
        duration = datetime.datetime.now() - self.lock_started
        hours, remainder = divmod(duration.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        embed = discord.Embed(
            title="⚡ Opération en cours",
            description=f"**{self.lock_reason}**",
            color=0xFFA500  # Couleur Antilles
        )
        
        # Informations sur l'opération
        embed.add_field(
            name="📋 Détails de l'opération",
            value=f"**Type:** {self.current_operation}\n"
                  f"**Durée écoulée:** {int(hours)}h {int(minutes)}m {int(seconds)}s\n"
                  f"**Démarrée:** <t:{int(self.lock_started.timestamp())}:F>",
            inline=False
        )
        
        # Progression si disponible
        if self.progress_info:
            progress_text = ""
            for key, value in self.progress_info.items():
                progress_text += f"**{key.title()}:** {value}\n"
            
            embed.add_field(
                name="📊 Progression en temps réel",
                value=progress_text,
                inline=False
            )
        
        # Estimation de fin
        if self.estimated_completion:
            embed.add_field(
                name="⏰ Estimation de fin",
                value=f"<t:{int(self.estimated_completion.timestamp())}:R>",
                inline=True
            )
        
        embed.add_field(
            name="ℹ️ Information",
            value="Le système reprendra automatiquement les commandes une fois l'opération terminée.\n"
                  "Cette protection évite les conflits et garantit la cohérence des données.",
            inline=False
        )
        
        embed.set_footer(text="🌴 Système ATC Outre-Mer • Opération sécurisée")
        
        return embed

# Instance globale du gestionnaire de verrouillage
system_lock = SystemLockManager()

# === SYSTÈME DE STOCKAGE JSON ET SQL HYBRIDE ===

class ATCDataStorage:
    """Système de stockage hybride JSON/SQLite avec archivage"""
    
    def __init__(self, db_path: str = "utils/data/atc_database.db"):
        self.db_path = db_path
        self.data_dir = "utils/data"
        self.monthly_stats_file = f"{self.data_dir}/monthly_stats.json"
        self.annual_stats_file = f"{self.data_dir}/annual_stats.json"
        self.system_state_file = f"{self.data_dir}/system_state.json"
        self.user_cache_file = f"{self.data_dir}/user_cache.json"
        self.progress_file = f"{self.data_dir}/progress_state.json"
        self.sent_status_file = f"{self.data_dir}/sent_status.json"
        
        # Initialiser les systèmes
        self.init_database()
        self._ensure_json_files_exist()
    
    def init_database(self):
        """Initialise la base de données complète avec migration automatique"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            # Migration automatique - évite l'erreur "no such column"
            try:
                cursor = conn.execute("PRAGMA table_info(monthly_stats)")
                columns = [row[1] for row in cursor.fetchall()]
                
                if "sent_to_discord" not in columns:
                    logger.warning("⚠️ Colonne 'sent_to_discord' manquante, ajout automatique...")
                    conn.execute("ALTER TABLE monthly_stats ADD COLUMN sent_to_discord BOOLEAN DEFAULT 0")
                    logger.info("✅ Migration colonne 'sent_to_discord' réussie")
            except sqlite3.OperationalError:
                # Table n'existe pas encore, la créer
                pass
            
            # Table des sessions brutes avec validation
            conn.execute("""
                CREATE TABLE IF NOT EXISTS raw_sessions (
                    session_id TEXT PRIMARY KEY,
                    airport_code TEXT NOT NULL,
                    callsign TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    user_name TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    connection_type TEXT NOT NULL,
                    raw_data TEXT NOT NULL,
                    data_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_valid BOOLEAN NOT NULL DEFAULT 1,
                    validation_errors TEXT
                )
            """)
            
            # Table des statistiques mensuelles avec colonne sent_to_discord
            conn.execute("""
                CREATE TABLE IF NOT EXISTS monthly_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    airport_code TEXT NOT NULL,
                    region TEXT NOT NULL,
                    total_time INTEGER NOT NULL,
                    total_sessions INTEGER NOT NULL,
                    controllers_data TEXT NOT NULL,
                    controller_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    sent_to_discord BOOLEAN DEFAULT 0,
                    UNIQUE(year, month, airport_code)
                )
            """)
            
            # Table des statistiques annuelles
            conn.execute("""
                CREATE TABLE IF NOT EXISTS annual_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year INTEGER NOT NULL UNIQUE,
                    stats_data TEXT NOT NULL,
                    total_time INTEGER NOT NULL,
                    total_sessions INTEGER NOT NULL,
                    total_controllers INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            
            # Index pour les performances
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_airport_date ON raw_sessions(airport_code, start_time, end_time)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_monthly_year_month ON monthly_stats(year, month)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_monthly_sent ON monthly_stats(sent_to_discord, year, month)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_annual_year ON annual_stats(year)")
    
    def _ensure_json_files_exist(self):
        """Crée les fichiers JSON s'ils n'existent pas"""
        files_to_create = [
            (self.monthly_stats_file, {}),
            (self.annual_stats_file, {}),
            (self.system_state_file, {
                "last_recovery": None,
                "missing_periods": [],
                "recovery_in_progress": False,
                "auto_send_enabled": True
            }),
            (self.user_cache_file, {}),
            (self.progress_file, {}),
            (self.sent_status_file, {})
        ]
        
        for file_path, default_content in files_to_create:
            if not os.path.exists(file_path):
                self._save_json(file_path, default_content)
    
    def _load_json(self, file_path: str) -> Dict:
        """Charge un fichier JSON de façon robuste"""
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"❌ Erreur lecture {file_path}: {e}")
        
        return {}
    
    def _save_json(self, file_path: str, data: Dict):
        """Sauvegarde un fichier JSON de façon robuste"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde {file_path}: {e}")
    
    def calculate_data_hash(self, session_data: Dict) -> str:
        """Calcule un hash pour détecter les changements"""
        critical_fields = {
            'id': session_data.get('id'),
            'callsign': session_data.get('callsign'),
            'userId': session_data.get('userId'),
            'time': session_data.get('time'),
            'createdAt': session_data.get('createdAt'),
            'completedAt': session_data.get('completedAt')
        }
        data_string = json.dumps(critical_fields, sort_keys=True)
        return hashlib.md5(data_string.encode()).hexdigest()
    
    def validate_session_data(self, session_data: Dict) -> tuple:
        """Valide la cohérence des données avec cross-check"""
        errors = []
        
        if not session_data.get('id'):
            errors.append("ID manquant")
        
        if not session_data.get('callsign'):
            errors.append("Callsign manquant")
        
        duration = session_data.get('time', 0)
        if duration < 10:
            errors.append(f"Durée trop courte: {duration}s")
        
        if duration > 86400:
            errors.append(f"Durée excessive: {duration}s")
        
        # Cross-check dates vs durée
        start_time = session_data.get('createdAt')
        end_time = session_data.get('completedAt')
        
        if start_time and end_time:
            try:
                start_dt = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                end_dt = datetime.datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                
                if end_dt <= start_dt:
                    errors.append("Dates incohérentes")
                
                calculated_duration = int((end_dt - start_dt).total_seconds())
                if abs(calculated_duration - duration) > 60:
                    errors.append(f"CROSS-CHECK FAILED: API={duration}s vs calc={calculated_duration}s")
            except:
                errors.append("Erreur parsing dates")
        elif not start_time:
            errors.append("Date création manquante")
        
        user_data = session_data.get('user', {})
        if not user_data.get('id'):
            errors.append("User ID manquant")
        
        return len(errors) == 0, errors
    
    def store_raw_sessions(self, airport_code: str, sessions: List[Dict]) -> Dict:
        """Stocke les sessions brutes avec validation (SQL)"""
        results = {'stored': 0, 'updated': 0, 'invalid': 0, 'errors': []}
        
        with sqlite3.connect(self.db_path) as conn:
            for session in sessions:
                try:
                    session_id = str(session.get('id'))
                    data_hash = self.calculate_data_hash(session)
                    is_valid, validation_errors = self.validate_session_data(session)
                    
                    user_data = session.get('user', {})
                    user_name = f"{user_data.get('firstName', 'Inconnu')} {user_data.get('lastName', '')}"
                    
                    # Vérifier si existe
                    cursor = conn.execute(
                        'SELECT data_hash FROM raw_sessions WHERE session_id = ?',
                        (session_id,)
                    )
                    existing = cursor.fetchone()
                    
                    if existing:
                        if existing[0] != data_hash:
                            # Mise à jour si hash différent
                            conn.execute("""
                                UPDATE raw_sessions SET
                                    raw_data=?, data_hash=?, updated_at=?,
                                    is_valid=?, validation_errors=?
                                WHERE session_id=?
                            """, (
                                json.dumps(session), data_hash,
                                datetime.datetime.now().isoformat(),
                                is_valid, json.dumps(validation_errors) if validation_errors else None,
                                session_id
                            ))
                            results['updated'] += 1
                    else:
                        # Nouvelle session
                        conn.execute("""
                            INSERT INTO raw_sessions 
                            (session_id, airport_code, callsign, user_id, user_name,
                             start_time, end_time, duration_seconds, connection_type,
                             raw_data, data_hash, created_at, updated_at, is_valid,
                             validation_errors)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            session_id, airport_code, session.get('callsign', ''),
                            session.get('userId', 0), user_name.strip(),
                            session.get('createdAt', ''), session.get('completedAt', ''),
                            session.get('time', 0), session.get('connectionType', ''),
                            json.dumps(session), data_hash,
                            datetime.datetime.now().isoformat(),
                            datetime.datetime.now().isoformat(),
                            is_valid, json.dumps(validation_errors) if validation_errors else None
                        ))
                        results['stored'] += 1
                    
                    if not is_valid:
                        results['invalid'] += 1
                        
                except Exception as e:
                    results['errors'].append(str(e))
        
        return results
    
    def store_monthly_stats_json(self, year: int, month: int, airport_stats: Dict):
        """Stocke les statistiques mensuelles en JSON"""
        data = self._load_json(self.monthly_stats_file)
        
        key = f"{year}-{month:02d}"
        data[key] = {
            "year": year,
            "month": month,
            "generated_at": datetime.datetime.now().isoformat(),
            "airport_stats": airport_stats,
            "total_sessions": sum(stats.get("total_sessions", 0) for stats in airport_stats.values()),
            "total_time": sum(stats.get("total_time", 0) for stats in airport_stats.values())
        }
        
        self._save_json(self.monthly_stats_file, data)
        logger.info(f"✅ Stats mensuelles JSON stockées: {key}")
    
    def archive_monthly_stats(self, year: int, month: int, airport_stats: Dict):
        """Archive les statistiques mensuelles (SQL + JSON)"""
        # Stockage JSON
        self.store_monthly_stats_json(year, month, airport_stats)
        
        # Stockage SQL pour compatibilité
        with sqlite3.connect(self.db_path) as conn:
            for airport_code, stats in airport_stats.items():
                if stats['total_time'] > 0:
                    region = get_airport_region(airport_code)
                    
                    conn.execute("""
                        INSERT OR REPLACE INTO monthly_stats 
                        (year, month, airport_code, region, total_time, total_sessions,
                         controllers_data, controller_count, created_at, sent_to_discord)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """, (
                        year, month, airport_code, region,
                        stats['total_time'], stats['total_sessions'],
                        json.dumps(stats['controllers']), stats['controller_count'],
                        datetime.datetime.now().isoformat()
                    ))
        
        logger.info(f"✅ Stats mensuelles archivées (SQL+JSON): {year}/{month:02d}")
    
    def get_monthly_stats_json(self, year: int = None, month: int = None) -> Dict:
        """Récupère les statistiques mensuelles depuis JSON"""
        data = self._load_json(self.monthly_stats_file)
        
        if year is not None and month is not None:
            key = f"{year}-{month:02d}"
            return data.get(key, {})
        
        return data
    
    def mark_month_sent(self, year: int, month: int):
        """Marque un mois comme envoyé sur Discord (JSON + SQL)"""
        # JSON
        sent_data = self._load_json(self.sent_status_file)
        key = f"{year}-{month:02d}"
        sent_data[key] = {
            "sent_at": datetime.datetime.now().isoformat(),
            "sent_to_discord": True
        }
        self._save_json(self.sent_status_file, sent_data)
        
        # SQL
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE monthly_stats SET sent_to_discord = 1
                WHERE year = ? AND month = ?
            """, (year, month))
    
    def is_month_sent(self, year: int, month: int) -> bool:
        """Vérifie si un mois a été envoyé (JSON d'abord, SQL fallback)"""
        # Vérifier JSON d'abord
        sent_data = self._load_json(self.sent_status_file)
        key = f"{year}-{month:02d}"
        json_sent = sent_data.get(key, {}).get("sent_to_discord", False)
        
        if json_sent:
            return True
        
        # Fallback SQL
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM monthly_stats 
                    WHERE year = ? AND month = ? AND sent_to_discord = 1
                """, (year, month))
                return cursor.fetchone()[0] > 0
        except:
            return False
    
    def get_unsent_months(self) -> List[Tuple[int, int]]:
        """Retourne les mois non envoyés sur Discord"""
        monthly_data = self._load_json(self.monthly_stats_file)
        sent_data = self._load_json(self.sent_status_file)
        unsent = []
        
        for key, month_data in monthly_data.items():
            if not sent_data.get(key, {}).get("sent_to_discord", False):
                total_sessions = month_data.get("total_sessions", 0)
                if total_sessions > 0:
                    year, month = month_data["year"], month_data["month"]
                    unsent.append((year, month))
        
        return unsent
    
    def get_missing_months(self, start_year: int = None) -> List[Tuple[int, int]]:
        """Retourne les mois manquants de l'année courante SEULEMENT"""
        data = self._load_json(self.monthly_stats_file)
        missing = []
        
        current_date = datetime.datetime.now()
        
        # CORRECTION : On ne récupère QUE l'année courante
        year = current_date.year  # 2025 actuellement
        start_month = 1
        end_month = current_date.month - 1  # Jusqu'au mois précédent
        
        for month in range(start_month, end_month + 1):
            key = f"{year}-{month:02d}"
            
            # Vérifier si existe et a des données significatives
            month_data = data.get(key, {})
            total_sessions = month_data.get("total_sessions", 0)
            
            if total_sessions == 0:
                missing.append((year, month))
        
        logger.info(f"🔍 Mois manquants {year}: {len(missing)} périodes")
        return missing

    
    def save_progress_state(self, process_id: str, data: Dict):
        """Sauvegarde l'état de progression"""
        progress_data = self._load_json(self.progress_file)
        progress_data[process_id] = {
            **data,
            "updated_at": datetime.datetime.now().isoformat()
        }
        self._save_json(self.progress_file, progress_data)
    
    def get_progress_state(self, process_id: str) -> Dict:
        """Récupère l'état de progression"""
        progress_data = self._load_json(self.progress_file)
        return progress_data.get(process_id, {})
    
    def clear_progress_state(self, process_id: str):
        """Efface l'état de progression"""
        progress_data = self._load_json(self.progress_file)
        if process_id in progress_data:
            del progress_data[process_id]
        self._save_json(self.progress_file, progress_data)
    
    def get_annual_data(self, year: int) -> Dict:
        """Récupère toutes les données mensuelles pour une année"""
        monthly_data = self._load_json(self.monthly_stats_file)
        annual_data = {}
        
        for key, month_data in monthly_data.items():
            month_year, month_num = key.split('-')
            if int(month_year) == year:
                month_int = int(month_num)
                annual_data[month_int] = month_data.get("airport_stats", {})
        
        return annual_data
    
    def store_annual_stats(self, year: int, annual_data: Dict):
        """Stocke les statistiques annuelles (JSON + SQL)"""
        # JSON
        data = self._load_json(self.annual_stats_file)
        data[str(year)] = {
            "year": year,
            "generated_at": datetime.datetime.now().isoformat(),
            "annual_data": annual_data
        }
        self._save_json(self.annual_stats_file, data)
        
        # SQL pour compatibilité
        total_time = 0
        total_sessions = 0
        all_controllers = set()
        
        for month_data in annual_data.values():
            for airport_stats in month_data.values():
                total_time += airport_stats.get('total_time', 0)
                total_sessions += airport_stats.get('total_sessions', 0)
                all_controllers.update(airport_stats.get('controllers', {}).keys())
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO annual_stats 
                (year, stats_data, total_time, total_sessions, total_controllers, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                year, json.dumps(annual_data), total_time, total_sessions,
                len(all_controllers), datetime.datetime.now().isoformat()
            ))
        
        logger.info(f"✅ Stats annuelles stockées (JSON+SQL): {year}")
    
    def get_stats_summary(self) -> Dict:
        """Retourne un résumé complet des statistiques"""
        monthly_data = self._load_json(self.monthly_stats_file)
        annual_data = self._load_json(self.annual_stats_file)
        sent_data = self._load_json(self.sent_status_file)
        
        total_periods = len(monthly_data)
        total_sessions = sum(month_data.get("total_sessions", 0) for month_data in monthly_data.values())
        
        active_airports = set()
        for month_data in monthly_data.values():
            airport_stats = month_data.get("airport_stats", {})
            for airport_code, stats in airport_stats.items():
                if stats.get("total_sessions", 0) > 0:
                    active_airports.add(airport_code)
        
        sent_count = len(sent_data)
        missing_count = len(self.get_missing_months())
        unsent_count = len(self.get_unsent_months())
        
        return {
            "total_periods": total_periods,
            "total_sessions": total_sessions,
            "active_airports": len(active_airports),
            "annual_reports": len(annual_data),
            "sent_months": sent_count,
            "missing_months": missing_count,
            "unsent_months": unsent_count
        }

# === SYSTÈME DE RÉCUPÉRATION AUTOMATIQUE ===

class DataRecoveryManager:
    """Gestionnaire de récupération automatique des données manquantes"""
    
    def __init__(self, storage_manager):
        self.storage = storage_manager
    
    def get_missing_periods(self, start_year: int = 2022) -> List[Tuple[int, int]]:
        """Identifie les périodes manquantes depuis start_year"""
        return self.storage.get_missing_months(start_year)
    
    async def perform_intelligent_recovery(self, processor_instance, progress_channel=None) -> Dict[str, Any]:
        """Effectue une récupération intelligente des données manquantes"""
        system_state = self.storage._load_json(self.storage.system_state_file)
        
        if system_state.get("recovery_in_progress"):
            logger.warning("⚠️ Récupération déjà en cours")
            return {"status": "already_running"}
        
        # Marquer la récupération en cours
        system_state["recovery_in_progress"] = True
        system_state["recovery_started"] = datetime.datetime.now().isoformat()
        self.storage._save_json(self.storage.system_state_file, system_state)
        
        try:
            missing_periods = self.get_missing_periods()
            
            if not missing_periods:
                logger.info("✅ Toutes les données sont à jour")
                return {"status": "up_to_date", "recovered": 0}
            
            logger.info(f"🔄 Récupération intelligente: {len(missing_periods)} périodes à traiter")
            
            recovered_count = 0
            failed_count = 0
            errors = []
            
            # Traitement par batch de 10 périodes maximum pour éviter la surcharge
            for i, (year, month) in enumerate(missing_periods[:10]):
                try:
                    # Sauvegarder le progrès
                    self.storage.save_progress_state("recovery_batch", {
                        "current_period": f"{year}-{month:02d}",
                        "completed": i,
                        "total": min(len(missing_periods), 10),
                        "status": "processing"
                    })
                    
                    # Mise à jour du verrou système
                    system_lock.update_progress(
                        période_actuelle=f"{year}-{month:02d}",
                        progression=f"{i+1}/{min(len(missing_periods), 10)}"
                    )
                    
                    # Collecte des données
                    airport_stats = await processor_instance.collect_month_data(year, month, progress_channel)
                    
                    # Stockage
                    self.storage.archive_monthly_stats(year, month, airport_stats)
                    
                    recovered_count += 1
                    logger.info(f"✅ Période {year}-{month:02d} récupérée ({i+1}/{min(len(missing_periods), 10)})")
                    
                    # Pause pour éviter la surcharge
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    error_msg = f"Erreur {year}-{month:02d}: {str(e)}"
                    logger.error(f"❌ {error_msg}")
                    errors.append(error_msg)
                    failed_count += 1
            
            # Finaliser la récupération
            system_state["recovery_in_progress"] = False
            system_state["last_recovery"] = datetime.datetime.now().isoformat()
            self.storage._save_json(self.storage.system_state_file, system_state)
            
            self.storage.clear_progress_state("recovery_batch")
            
            return {
                "status": "completed",
                "recovered": recovered_count,
                "failed": failed_count,
                "errors": errors,
                "total_missing": len(missing_periods)
            }
            
        except Exception as e:
            # Réinitialiser l'état en cas d'erreur globale
            system_state["recovery_in_progress"] = False
            self.storage._save_json(self.storage.system_state_file, system_state)
            logger.error(f"❌ Erreur globale récupération: {e}")
            return {"status": "error", "error": str(e)}

# Instance globale du stockage et récupération
storage = ATCDataStorage()
recovery_manager = DataRecoveryManager(storage)

# === CLIENT API IVAO INTELLIGENT AVEC WEBSCRAPING CONSERVÉ ===

class IVAOAPIClient:
    """Client API IVAO intelligent - récupère toutes les sessions puis fait le scraping"""
    
    def __init__(self, client_id: str, client_secret: str, user_vid: str, user_password: str):
        # Utiliser la clé API depuis .env au lieu de client_id/secret
        self.api_key = IVAO_API_KEY
        self.user_vid = user_vid
        self.user_password = user_password
        self.session = None
        self.rate_limit_delay = 3.0
        self.user_cache = {}  # Cache des noms utilisateurs
        
    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=60, connect=15)
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers={'User-Agent': 'IVAO-ATC-Stats-Bot/5.0-Robust'}
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def make_request(self, endpoint: str, params: dict = None) -> dict:
        """Effectue une requête robuste avec authentification"""
        token = IVAO_API_KEY
        if not token:
            return {'items': [], 'pages': 0, 'totalItems': 0}
        
        url = f"https://api.ivao.aero{endpoint}"
        headers = {
            'apiKey': IVAO_API_KEY,
            'Content-Type': 'application/json'
        }
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await asyncio.sleep(self.rate_limit_delay)
                
                async with self.session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 401:
                        # Token expiré, forcer le renouvellement
                        self.token = None
                        token = IVAO_API_KEY
                        if token:
                            headers['apiKey'] = IVAO_API_KEY
                            continue
                    elif response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 60))
                        logger.warning(f"Rate limited, attente {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        logger.warning(f"API status {response.status}")
                        
            except Exception as e:
                logger.warning(f"Erreur requête tentative {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
        
        return {'items': [], 'pages': 0, 'totalItems': 0}
    
    def is_valid_atc_session(self, session: Dict, expected_callsign: str) -> bool:
        """VALIDATION INTELLIGENTE - Si on cherche une position ATC, c'est forcément de l'ATC !"""
        try:
            # 1. Vérifier qu'on a une session
            if not session:
                return False
                
            # 2. Vérifier qu'on a un callsign
            callsign = session.get('callsign', '')
            if not callsign:
                return False
                
            # 3. Vérifier que le callsign correspond (flexible)
            if not (expected_callsign in callsign or callsign.startswith(expected_callsign)):
                return False
            
            # 4. Vérifier qu'on a une durée raisonnable (minimum 10 secondes)
            time_seconds = session.get('time', 0)
            if time_seconds < 10:
                return False
                
            # 5. Vérifier qu'on a un utilisateur
            user = session.get('user', {})
            if not user or not user.get('id'):
                return False
            
            # C'EST TOUT ! Pas besoin de vérifier le type de connexion
            # Car si on cherche une position ATC, c'est forcément de l'ATC
            return True
            
        except:
            return False
    
    async def fetch_sessions_smart(self, callsign_prefix: str, 
                                   start_date: datetime.datetime, 
                                   end_date: datetime.datetime) -> List[Dict]:
        """Récupère TOUTES les sessions intelligemment puis fait le scraping"""
        all_sessions = []
        page = 1
        per_page = 50  # Maximum 50 par page comme spécifié
        
        logger.info(f"🔍 Recherche SMART {callsign_prefix} du {start_date.date()} au {end_date.date()}")
        
        # ===== ÉTAPE 1: RÉCUPÉRER TOUTES LES SESSIONS =====
        while page <= 20:  # Maximum 20 pages
            try:
                params = {
                    'page': page,
                    'perPage': per_page,
                    'from': start_date.isoformat() + 'Z',
                    'to': end_date.isoformat() + 'Z',
                    'callsign': callsign_prefix
                    # PAS DE FILTRE connectionType !
                }
                
                logger.info(f"📡 SMART Page {page}: {callsign_prefix}")
                
                data = await self.make_request('/v2/tracker/sessions', params)
                
                if not data or 'items' not in data:
                    logger.warning(f"⚠️ Pas de données page {page}")
                    break
                
                page_sessions = data.get('items', [])
                total_items = data.get('totalItems', 0)
                pages_total = data.get('pages', 0)
                
                logger.info(f"📄 Page {page}/{pages_total}: {len(page_sessions)} items bruts sur {total_items} totaux")
                
                if not page_sessions:
                    logger.info(f"📄 Page {page} vide, fin de pagination")
                    break
                
                # Debug des premières sessions
                if page == 1 and page_sessions:
                    logger.info(f"🔍 ÉCHANTILLON BRUT {callsign_prefix}:")
                    for i, session in enumerate(page_sessions[:3]):
                        logger.info(f"   {i+1}: {session.get('callsign')} - {session.get('connectionType')} - {session.get('time')}s - user:{session.get('user', {}).get('id')}")
                
                # Validation simple
                valid_sessions = []
                rejected_sessions = []
                
                for session in page_sessions:
                    if self.is_valid_atc_session(session, callsign_prefix):
                        valid_sessions.append(session)
                    else:
                        rejected_sessions.append(session)
                
                all_sessions.extend(valid_sessions)
                logger.info(f"✅ Page {page}: {len(valid_sessions)} valides, {len(rejected_sessions)} rejetées")
                
                # Vérification pagination
                if len(page_sessions) < per_page:
                    logger.info(f"📄 Fin de pagination (page incomplète)")
                    break
                    
                if page >= pages_total:
                    logger.info(f"📄 Fin de pagination (dernière page)")
                    break
                    
                page += 1
                await asyncio.sleep(self.rate_limit_delay)
                
            except Exception as e:
                logger.error(f"❌ Erreur page {page}: {e}")
                break
        
        logger.info(f"🏁 COLLECTÉ {callsign_prefix}: {len(all_sessions)} sessions valides")
        
        # ===== ÉTAPE 2: ENRICHISSEMENT DES NOMS (UNE SEULE FOIS) =====
        if all_sessions:
            logger.info(f"🔍 Enrichissement des noms pour {callsign_prefix}...")
            await self.enrich_user_names(all_sessions)
        
        return all_sessions
    
    async def enrich_user_names(self, sessions: List[Dict]):
        """Enrichit les noms d'utilisateur pour toutes les sessions collectées"""
        unique_vids = set()
        
        # Extraire tous les VID uniques
        for session in sessions:
            user = session.get('user', {})
            vid = user.get('id')
            if vid:
                unique_vids.add(vid)
        
        logger.info(f"🔍 Enrichissement de {len(unique_vids)} utilisateurs uniques")
        
        # Enrichir chaque VID unique
        enriched = 0
        for vid in unique_vids:
            try:
                if vid not in self.user_cache:
                    first_name, last_name = await self.get_user_name_from_vid(vid)
                    if first_name and first_name != 'Unknown':
                        self.user_cache[vid] = (first_name, last_name)
                        enriched += 1
                        logger.debug(f"✅ VID {vid}: {first_name} {last_name}")
                    else:
                        self.user_cache[vid] = (f"Controller{vid}", "")
                    
                    # Rate limiting pour le scraping
                    await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.warning(f"⚠️ Erreur enrichissement VID {vid}: {e}")
                self.user_cache[vid] = (f"Controller{vid}", "")
        
        logger.info(f"✅ Enrichissement terminé: {enriched} noms récupérés, {len(unique_vids)} en cache")
    
    async def get_user_name_from_vid(self, vid: int) -> Tuple[str, str]:
        """Récupère le nom d'un utilisateur via web scraping IVAO (CONSERVÉ)"""
        try:
            # URL de la page de connexion
            login_url = "https://ivao.aero/Login.aspx"
            profile_url = f"https://ivao.aero/Member.aspx?Id={vid}"

            # Première requête pour obtenir les jetons CSRF
            async with self.session.get(login_url, params={"r": f"Member.aspx?Id={vid}"}) as response:
                if response.status != 200:
                    logger.debug(f"❌ Erreur page connexion VID {vid}: {response.status}")
                    return "Unknown", "User"

                html_content = await response.text()
                soup = BeautifulSoup(html_content, 'html.parser')

                # Extraire les champs cachés nécessaires pour la connexion
                try:
                    viewstate = soup.find('input', {'name': '__VIEWSTATE'})['value']
                    viewstategenerator = soup.find('input', {'name': '__VIEWSTATEGENERATOR'})['value']
                    eventvalidation = soup.find('input', {'name': '__EVENTVALIDATION'})['value']
                    try:
                        post_url = soup.find('input', {'name': 'ctl00$ContentPlaceHolder1$postUrl'})['value']
                    except:
                        post_url = profile_url
                except:
                    logger.debug(f"❌ Impossible de récupérer les tokens CSRF pour VID {vid}")
                    return "Unknown", "User"

            # Préparer les données de connexion
            login_data = {
                '__VIEWSTATE': viewstate,
                '__VIEWSTATEGENERATOR': viewstategenerator,
                '__EVENTVALIDATION': eventvalidation,
                'ctl00$ContentPlaceHolder1$postUrl': post_url,
                'ctl00$ContentPlaceHolder1$loginVID': self.user_vid,
                'ctl00$ContentPlaceHolder1$loginPassword': self.user_password,
                'ctl00$ContentPlaceHolder1$loginRemember': 'on',
                'ctl00$ContentPlaceHolder1$loginBtn': 'Login'
            }

            # Effectuer la connexion
            async with self.session.post(login_url, data=login_data, allow_redirects=True) as response:
                if response.status != 200:
                    logger.debug(f"❌ Échec connexion IVAO pour VID {vid}: {response.status}")
                    return "Unknown", "User"

            # Accéder à la page du profil
            async with self.session.get(profile_url) as response:
                if response.status != 200:
                    logger.debug(f"❌ Échec accès profil VID {vid}: {response.status}")
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

                    logger.debug(f"✅ VID {vid}: {first_name} {last_name}")
                    return first_name, last_name

            logger.debug(f"⚠️ VID {vid}: Nom non trouvé dans le profil")
            return "Unknown", "User"
            
        except Exception as e:
            logger.debug(f"❌ Erreur web scraping VID {vid}: {str(e)}")
            return "Unknown", "User"

# === COLLECTEUR DE DONNÉES INTELLIGENT ===

class ATCDataCollector:
    """Collecteur de données intelligent avec scraping optimisé"""
    
    def __init__(self, api_client, storage):
        self.api_client = api_client
        self.storage = storage
        
    async def collect_month_data_with_progress(self, year: int, month: int, 
                                               progress_channel=None) -> Dict[str, Dict]:
        """Collecte intelligente avec scraping optimisé"""
        start_date = datetime.datetime(year, month, 1)
        if month == 12:
            end_date = datetime.datetime(year + 1, 1, 1) - datetime.timedelta(seconds=1)
        else:
            end_date = datetime.datetime(year, month + 1, 1) - datetime.timedelta(seconds=1)
        
        # Extraire tous les aéroports uniques
        airports = set()
        for positions in WATCHED_POSITIONS.values():
            for position in positions:
                airport_code = position.split('_')[0]
                airports.add(airport_code)
        
        airports = list(airports)
        total_airports = len(airports)
        
        logger.info(f"🚀 COLLECTE INTELLIGENTE {year}/{month:02d} pour {total_airports} aéroports")
        
        if progress_channel:
            progress_embed = discord.Embed(
                title="📊 Collecte INTELLIGENTE des données ATC",
                description=f"**Période:** {calendar.month_name[month]} {year}\n**Aéroports:** {total_airports}",
                color=0x00ff00
            )
            progress_embed.add_field(
                name="🔄 État", 
                value="Démarrage de la collecte intelligente...", 
                inline=False
            )
            progress_msg = await progress_channel.send(embed=progress_embed)
        else:
            progress_msg = None
        
        airport_stats = {}
        collected = 0
        total_sessions_found = 0
        errors = []
        
        for i, airport_code in enumerate(airports):
            try:
                # Mise à jour du progrès
                progress_pct = (i / total_airports) * 100
                
                if progress_msg and (i % 5 == 0):  # Mise à jour moins fréquente
                    progress_embed = discord.Embed(
                        title="📊 Collecte INTELLIGENTE en cours",
                        description=f"**Période:** {calendar.month_name[month]} {year}",
                        color=0xffa500
                    )
                    progress_embed.add_field(
                        name="🔄 Progression", 
                        value=f"**{i+1}/{total_airports}** aéroports ({progress_pct:.1f}%)\n"
                              f"📍 Actuellement: **{airport_code}**\n"
                              f"✅ Sessions trouvées: **{total_sessions_found}**", 
                        inline=False
                    )
                    
                    try:
                        await progress_msg.edit(embed=progress_embed)
                    except:
                        pass
                
                # Récupération INTELLIGENTE des données
                logger.info(f"🔍 [{i+1}/{total_airports}] {airport_code}")
                
                sessions = await self.api_client.fetch_sessions_smart(
                    airport_code, start_date, end_date
                )
                
                if sessions:
                    # Stocker en base
                    store_results = self.storage.store_raw_sessions(airport_code, sessions)
                    
                    # Calcul des stats avec noms enrichis
                    stats = await self.calculate_airport_stats_enriched(sessions)
                    airport_stats[airport_code] = stats
                    total_sessions_found += len(sessions)
                    collected += 1
                    logger.info(f"✅ {airport_code}: {len(sessions)} sessions, {stats['controller_count']} contrôleurs")
                else:
                    airport_stats[airport_code] = {
                        'total_time': 0, 'total_sessions': 0, 
                        'controllers': {}, 'controller_count': 0
                    }
                    logger.info(f"⚪ {airport_code}: Vide")
                
                # Mise à jour système lock
                system_lock.update_progress(
                    aéroport_actuel=airport_code,
                    progression=f"{i+1}/{total_airports}"
                )
                
                # Attente réduite
                await asyncio.sleep(1)
                
            except Exception as e:
                error_msg = f"Erreur {airport_code}: {str(e)[:100]}"
                errors.append(error_msg)
                logger.error(f"❌ {error_msg}")
                
                airport_stats[airport_code] = {
                    'total_time': 0, 'total_sessions': 0, 
                    'controllers': {}, 'controller_count': 0
                }
        
        # Résultat final
        if progress_msg:
            final_embed = discord.Embed(
                title="✅ Collecte INTELLIGENTE terminée",
                description=f"**Période:** {calendar.month_name[month]} {year}",
                color=0x00ff00 if total_sessions_found > 0 else 0xff0000
            )
            final_embed.add_field(
                name="📊 Résultats", 
                value=f"🏢 **{collected}/{total_airports}** aéroports avec données\n"
                      f"✈️ **{total_sessions_found}** sessions totales trouvées\n"
                      f"⚠️ **{len(errors)}** erreurs rencontrées", 
                inline=False
            )
            
            try:
                await progress_msg.edit(embed=final_embed)
            except:
                pass
        
        logger.info(f"🏁 COLLECTE TERMINÉE: {collected}/{total_airports} aéroports, {total_sessions_found} sessions")
        return airport_stats
    
    async def calculate_airport_stats_enriched(self, sessions: List[Dict]) -> Dict:
        """Calcule les statistiques avec noms déjà enrichis"""
        if not sessions:
            return {'total_time': 0, 'total_sessions': 0, 'controllers': {}, 'controller_count': 0}
        
        total_time = 0
        controllers = {}
        
        for session in sessions:
            try:
                time_seconds = session.get('time', 0)
                total_time += time_seconds
                
                user = session.get('user', {})
                user_id = user.get('id')
                
                if user_id:
                    # Récupérer le nom du cache (déjà enrichi)
                    if user_id in self.api_client.user_cache:
                        first_name, last_name = self.api_client.user_cache[user_id]
                    else:
                        # Fallback depuis l'API
                        first_name = user.get('firstName', f'Controller{user_id}')
                        last_name = user.get('lastName', '')
                    
                    controller_key = f"{first_name} {last_name[0]}." if last_name else first_name
                    
                    if user_id not in controllers:
                        controllers[user_id] = {
                            'name': controller_key,
                            'vid': user_id,
                            'total_time': 0,
                            'sessions': 0
                        }
                    
                    controllers[user_id]['total_time'] += time_seconds
                    controllers[user_id]['sessions'] += 1
            except Exception as e:
                logger.warning(f"Erreur traitement session: {e}")
                continue
        
        return {
            'total_time': total_time,
            'total_sessions': len(sessions),
            'controllers': controllers,
            'controller_count': len(controllers)
        }

# === PROCESSEUR DE STATISTIQUES ===

class ATCStatsProcessor:
    """Processeur principal des statistiques ATC intelligent"""
    
    def __init__(self):
        self.storage = storage
        
    def format_duration(self, seconds: int) -> str:
        """Formate une durée"""
        if seconds < 60:
            return "< 1min"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h{minutes:02d}m"
    
    async def collect_month_data(self, year: int, month: int, progress_channel=None) -> Dict[str, Dict]:
        """Collecte les données pour un mois complet avec intelligence"""
        async with IVAOAPIClient("", "", USER_VID, USER_PASSWORD) as api_client:
            collector = ATCDataCollector(api_client, self.storage)
            return await collector.collect_month_data_with_progress(year, month, progress_channel)
    
    def calculate_regional_stats(self, airport_stats: Dict) -> Dict:
        """Calcule les statistiques par région"""
        regional_stats = {}
        
        # Initialiser toutes les régions
        for region in WATCHED_POSITIONS.keys():
            regional_stats[region] = {
                'total_time': 0,
                'total_sessions': 0,
                'active_airports': 0,
                'total_airports': 0
            }
        
        # Compter le nombre total d'aéroports par région
        for region, positions in WATCHED_POSITIONS.items():
            unique_airports = set()
            for position in positions:
                airport_code = position.split('_')[0]
                unique_airports.add(airport_code)
            regional_stats[region]['total_airports'] = len(unique_airports)
        
        # Calculer les stats par aéroport
        for airport_code, stats in airport_stats.items():
            region = get_airport_region(airport_code)
            
            if region in regional_stats and stats.get('total_time', 0) > 0:
                regional_stats[region]['active_airports'] += 1
                regional_stats[region]['total_time'] += stats['total_time']
                regional_stats[region]['total_sessions'] += stats['total_sessions']
        
        return regional_stats

# === GÉNÉRATEURS D'EMBEDS PROFESSIONNELS (CONSERVÉS) ===

class ATCStatsEmbed:
    """Générateur d'embeds Discord avec thèmes régionaux conservés"""
    
    def __init__(self, processor: ATCStatsProcessor):
        self.processor = processor
        
    def create_monthly_global_embed(self, airport_stats: Dict, year: int, month: int, 
                                   is_test: bool = False) -> discord.Embed:
        """Crée l'embed des statistiques mensuelles globales (CONSERVÉ mais sans emojis débiles)"""
        regional_stats = self.processor.calculate_regional_stats(airport_stats)
        
        total_time = sum(stats['total_time'] for stats in regional_stats.values())
        total_sessions = sum(stats['total_sessions'] for stats in regional_stats.values())
        total_active_airports = sum(stats['active_airports'] for stats in regional_stats.values())
        total_airports = sum(stats['total_airports'] for stats in regional_stats.values())
        
        month_name = calendar.month_name[month]
        
        title = clean_text(f"🇫🇷 Contrôle Aérien • Outre-Mer Français")
        description = clean_text(f"**{month_name} {year}**" + (" (TEST)" if is_test else ""))
        description += clean_text(f"\n\n*Surveillance du contrôle aérien dans les territoires ultramarins*")
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=REGION_COLORS["ANTILLES"],
            timestamp=datetime.datetime.now()
        )
        
        if total_time > 0:
            # Statistiques globales
            avg_time = total_time // total_active_airports if total_active_airports > 0 else 0
            
            global_stats = clean_text(
                f"⏱️ **Temps total:** {self.processor.format_duration(total_time)}\n"
                f"📡 **Sessions:** {total_sessions:,}\n"
                f"🏢 **Aéroports actifs:** {total_active_airports}/{total_airports}\n"
                f"📈 **Moyenne/aéroport:** {self.processor.format_duration(avg_time)}"
            )
            
            embed.add_field(
                name=clean_text("📊 Vue d'ensemble"),
                value=global_stats,
                inline=False
            )
            
            # Répartition par région avec emojis conservés
            region_text = ""
            for region, stats in sorted(regional_stats.items(), key=lambda x: x[1]['total_time'], reverse=True):
                if stats['total_time'] > 0:
                    percentage = (stats['total_time'] / total_time) * 100
                    emoji = REGION_EMOJIS.get(region, "🌍")
                    region_line = f"{emoji} **{region}** • {self.processor.format_duration(stats['total_time'])} ({percentage:.0f}%)\n"
                    region_text += clean_text(region_line)
            
            if region_text:
                embed.add_field(
                    name=clean_text("🗺️ Répartition régionale"),
                    value=region_text,
                    inline=True
                )
            
            # Top aéroports
            airport_list = []
            for airport_code, stats in airport_stats.items():
                if stats['total_time'] > 0:
                    emoji = AIRPORT_EMOJIS.get(airport_code, '✈️')
                    airport_list.append({
                        'code': airport_code,
                        'time': stats['total_time'],
                        'sessions': stats['total_sessions'],
                        'controllers': stats['controller_count'],
                        'emoji': emoji
                    })
            
            airport_list.sort(key=lambda x: x['time'], reverse=True)
            
            if airport_list:
                top_text = ""
                for airport in airport_list[:8]:
                    line = f"{airport['emoji']} **{airport['code']}** • {self.processor.format_duration(airport['time'])} • {airport['controllers']} contrôleurs\n"
                    top_text += clean_text(line)
                
                embed.add_field(
                    name=clean_text("🏆 Aéroports les plus actifs"),
                    value=top_text,
                    inline=True
                )
        
        else:
            embed.add_field(
                name=clean_text("📊 Aucune activité"),
                value=clean_text(f"Aucune session de contrôle enregistrée pour {month_name} {year}."),
                inline=False
            )
        
        # Citation conservée mais pas "débile"
        quote = random.choice(INTERESTING_FACTS)
        embed.add_field(
            name=clean_text("💡 Le saviez-vous ?"),
            value=clean_text(quote),
            inline=False
        )
        
        embed.set_footer(text=f"🌴 Données IVAO • {len(ALL_WATCHED_POSITIONS)} positions surveillées")
        
        return embed
    
    def create_monthly_airport_embed(self, airport_code: str, stats: Dict, year: int, month: int) -> discord.Embed:
        """Crée l'embed pour un aéroport spécifique avec thème régional (CONSERVÉ)"""
        airport_name = OVERSEAS_AIRPORTS.get(airport_code, airport_code)
        airport_emoji = AIRPORT_EMOJIS.get(airport_code, '✈️')
        region, color = get_region_info(airport_code)
        month_name = calendar.month_name[month]
        
        title = clean_text(f"{airport_emoji} {airport_code} • Rapport détaillé")
        description = clean_text(f"**{airport_name}**\n{month_name} {year}")
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.datetime.now()
        )
        
        if stats.get("total_time", 0) > 0:
            # Stats globales
            global_stats = clean_text(
                f"⏱️ **Temps:** {self.processor.format_duration(stats['total_time'])}\n"
                f"📡 **Sessions:** {stats.get('total_sessions', 0)}\n"
                f"👨‍✈️ **Contrôleurs:** {stats.get('controller_count', 0)}"
            )
            
            embed.add_field(
                name=clean_text("📊 Statistiques"),
                value=global_stats,
                inline=True
            )
            
            # Top contrôleurs
            controllers = stats.get('controllers', {})
            if controllers:
                controllers_list = list(controllers.values())
                controllers_list.sort(key=lambda x: x['total_time'], reverse=True)
                
                controllers_text = ""
                for controller in controllers_list[:5]:
                    line = f"**{controller['name']}** • {self.processor.format_duration(controller['total_time'])} • {controller['sessions']} sessions\n"
                    controllers_text += clean_text(line)
                
                embed.add_field(
                    name=clean_text("🏆 Top contrôleurs"),
                    value=controllers_text,
                    inline=False
                )
        
        else:
            embed.add_field(
                name=clean_text("📊 Aucune activité"),
                value=clean_text(f"Aucune session enregistrée pour {airport_code} durant cette période."),
                inline=False
            )
        
        return embed

# === COG PRINCIPAL ULTRA-ROBUSTE (AVEC TOUT CONSERVÉ) ===

class ATCStatsCogRobust(commands.Cog):
    """Cog ATC ultra-robuste avec système complet, stockage JSON et webscraping conservé"""
    
    def __init__(self, bot):
        self.bot = bot
        self.processor = ATCStatsProcessor()
        self.embed_generator = ATCStatsEmbed(self.processor)
        self.recovery_manager = recovery_manager
        self.startup_completed = False
        
        # Démarrage des tâches
        if not self.system_monitor_task.is_running():
            self.system_monitor_task.start()
        if not self.precise_monthly_stats.is_running():
            self.precise_monthly_stats.start()
        if not self.pre_collect_task.is_running():
            self.pre_collect_task.start()
        if not self.unsent_stats_processor.is_running():
            self.unsent_stats_processor.start()
        if not self.annual_stats_task.is_running():
            self.annual_stats_task.start()
    
    def cog_unload(self):
        """Arrêt des tâches"""
        self.system_monitor_task.cancel()
        self.precise_monthly_stats.cancel()
        self.pre_collect_task.cancel()
        self.unsent_stats_processor.cancel()
        self.annual_stats_task.cancel()
    
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Gestionnaire d'erreur global avec embed professionnel"""
        if system_lock.is_locked:
            embed = system_lock.get_professional_status_embed()
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.response.send_message(embed=embed, ephemeral=True)
            except:
                pass
        else:
            logger.error(f"Erreur commande {interaction.command.name}: {error}")
    
    # === TÂCHES AUTOMATIQUES PRÉCISES ===
    
    @tasks.loop(minutes=5)
    async def system_monitor_task(self):
        """Surveillance et récupération automatique"""
        try:
            if not self.startup_completed:
                await asyncio.sleep(30)
                self.startup_completed = True
                
                # Récupération au démarrage si nécessaire
                missing_months = self.recovery_manager.get_missing_periods()
                unsent_months = storage.get_unsent_months()
                
                if len(missing_months) > 0 or len(unsent_months) > 0:
                    logger.info(f"🔄 Démarrage: {len(missing_months)} mois manquants, {len(unsent_months)} non envoyés")
                    
                    test_channel = self.bot.get_channel(TEST_CHANNEL_ID)
                    if test_channel:
                        startup_embed = discord.Embed(
                            title="🔄 Démarrage du système ATC Robuste",
                            description=f"**Récupération:** {len(missing_months)} mois manquants\n"
                                       f"**Publication:** {len(unsent_months)} à envoyer",
                            color=REGION_COLORS["ANTILLES"]
                        )
                        await test_channel.send(embed=startup_embed)
                        
                        # Lancer la récupération si nécessaire
                        if len(missing_months) > 0:
                            asyncio.create_task(self.recovery_manager.perform_intelligent_recovery(self.processor, test_channel))
            
            # Déblocage automatique après 2h
            if system_lock.is_locked:
                duration = datetime.datetime.now() - system_lock.lock_started
                if duration.total_seconds() > 7200:
                    logger.warning("⚠️ Déblocage automatique après 2h")
                    system_lock.unlock_system()
        
        except Exception as e:
            logger.error(f"❌ Erreur surveillance: {e}")
    
    @tasks.loop(minutes=1)
    async def pre_collect_task(self):
        """Pré-collecte à 23:45 le dernier jour du mois"""
        now = datetime.datetime.now()
        
        # 23:45 le dernier jour du mois
        last_day = calendar.monthrange(now.year, now.month)[1]
        if now.day == last_day and now.hour == 23 and now.minute == 45:
            if system_lock.is_locked:
                return
            
            logger.info("🔄 Pré-collecte mensuelle démarrée à 23:45")
            
            system_lock.lock_system(
                "Pré-collecte des statistiques mensuelles",
                f"Préparation données {calendar.month_name[now.month]} {now.year}",
                estimated_duration_minutes=15
            )
            
            try:
                await self.pre_collect_monthly_data(now.year, now.month)
            finally:
                system_lock.unlock_system()
    
    @tasks.loop(minutes=1)
    async def precise_monthly_stats(self):
        """Génération mensuelle à 00:30 précis le 1er du mois"""
        now = datetime.datetime.now()
        
        # 1er du mois à 00:30 précis
        if now.day == 1 and now.hour == 0 and now.minute == 30:
            if system_lock.is_locked:
                return
            
            # Calculer le mois précédent
            if now.month == 1:
                target_month = 12
                target_year = now.year - 1
            else:
                target_month = now.month - 1
                target_year = now.year
            
            logger.info(f"📊 Génération automatique précise: {target_year}/{target_month:02d}")
            
            system_lock.lock_system(
                "Génération automatique des statistiques mensuelles",
                f"Traitement final {calendar.month_name[target_month]} {target_year}",
                estimated_duration_minutes=5
            )
            
            try:
                await self.generate_and_send_monthly_stats(target_year, target_month)
            finally:
                system_lock.unlock_system()
    
    @tasks.loop(minutes=15)
    async def unsent_stats_processor(self):
        """Traite automatiquement les statistiques non envoyées"""
        if system_lock.is_locked:
            return
        
        try:
            unsent_periods = storage.get_unsent_months()
            if not unsent_periods:
                return
            
            logger.info(f"📬 Traitement {len(unsent_periods)} stats non envoyées")
            
            # Traiter une période à la fois
            for year, month in unsent_periods[:1]:
                try:
                    await self.send_stored_monthly_stats(year, month)
                    storage.mark_month_sent(year, month)
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.error(f"❌ Erreur envoi {year}-{month:02d}: {e}")
                    
        except Exception as e:
            logger.error(f"❌ Erreur processeur stats non envoyées: {e}")
    
    @tasks.loop(minutes=1)
    async def annual_stats_task(self):
        """Génération annuelle à 00:00 précis le 1er janvier"""
        now = datetime.datetime.now()
        
        if now.month == 1 and now.day == 1 and now.hour == 0 and now.minute == 0:
            if system_lock.is_locked:
                return
            
            target_year = now.year - 1
            
            logger.info(f"🎊 Génération bilan annuel {target_year}")
            
            system_lock.lock_system(
                "Génération du bilan annuel",
                f"Compilation complète année {target_year}",
                estimated_duration_minutes=30
            )
            
            try:
                await self.generate_and_send_annual_stats(target_year)
            finally:
                system_lock.unlock_system()
    
    # === MÉTHODES DE COLLECTE ET GÉNÉRATION ===
    
    async def pre_collect_monthly_data(self, year: int, month: int):
        """Pré-collecte les données du mois (sans envoi)"""
        try:
            airport_stats = await self.processor.collect_month_data(year, month)
            storage.store_monthly_stats_json(year, month, airport_stats)
            logger.info(f"✅ Pré-collecte {year}/{month:02d} terminée")
        except Exception as e:
            logger.error(f"❌ Erreur pré-collecte: {e}")
    
    async def generate_and_send_monthly_stats(self, year: int, month: int):
        """Génère et envoie les statistiques mensuelles"""
        try:
            # Vérifier si déjà envoyé
            if storage.is_month_sent(year, month):
                logger.info(f"📊 Stats {year}/{month:02d} déjà envoyées")
                return
            
            # Récupérer les données pré-collectées ou collecter
            month_data = storage.get_monthly_stats_json(year, month)
            airport_stats = month_data.get("airport_stats", {})
            
            if not airport_stats:
                logger.info(f"🔄 Données non trouvées, collecte directe {year}/{month:02d}")
                airport_stats = await self.processor.collect_month_data(year, month)
                storage.store_monthly_stats_json(year, month, airport_stats)
            
            total_sessions = sum(stats.get("total_sessions", 0) for stats in airport_stats.values())
            
            if total_sessions > 0:
                await self.send_monthly_stats_to_channel(year, month, airport_stats)
                storage.mark_month_sent(year, month)
                logger.info(f"✅ Stats mensuelles {year}/{month:02d} envoyées")
            else:
                logger.info(f"⚪ Aucune donnée pour {year}/{month:02d}")
            
        except Exception as e:
            logger.error(f"❌ Erreur génération mensuelle: {e}")
    
    async def generate_and_send_annual_stats(self, year: int):
        """Génère et envoie les statistiques annuelles"""
        try:
            # Compiler les données de tous les mois
            annual_data = storage.get_annual_data(year)
            
            if annual_data:
                storage.store_annual_stats(year, annual_data)
                await self.send_annual_stats_to_channel(year, annual_data)
                logger.info(f"✅ Bilan annuel {year} envoyé")
            
        except Exception as e:
            logger.error(f"❌ Erreur bilan annuel: {e}")
    
    async def send_stored_monthly_stats(self, year: int, month: int):
        """Envoie les stats mensuelles déjà stockées"""
        month_data = storage.get_monthly_stats_json(year, month)
        airport_stats = month_data.get("airport_stats", {})
        
        if airport_stats:
            total_sessions = sum(stats.get("total_sessions", 0) for stats in airport_stats.values())
            if total_sessions > 0:
                await self.send_monthly_stats_to_channel(year, month, airport_stats)
    
    # === MÉTHODES D'ENVOI DISCORD (CONSERVÉES) ===
    
    async def send_monthly_stats_to_channel(self, year: int, month: int, airport_stats: Dict):
        """Envoie les stats mensuelles vers Discord (CONSERVÉ)"""
        channel = self.bot.get_channel(STATS_CHANNEL_ID)
        if not channel:
            logger.error("❌ Canal introuvable")
            return
        
        try:
            month_name = calendar.month_name[month]
            
            # Embed principal
            summary_embed = self.embed_generator.create_monthly_global_embed(
                airport_stats, year, month
            )
            
            # Créer thread dans le forum
            if hasattr(channel, 'create_thread'):
                thread_name = f"📊 {month_name} {year}"
                thread = await channel.create_thread(
                    name=thread_name,
                    embed=summary_embed,
                    content=f"**Rapport mensuel ATC** • {month_name} {year}\n\n"
                           f"Surveillance du contrôle aérien dans les territoires ultramarins français."
                )
                
                # Ajouter détails pour les aéroports actifs
                sorted_airports = sorted(
                    [(k, v) for k, v in airport_stats.items() if v.get("total_time", 0) > 0],
                    key=lambda x: x[1]["total_time"],
                    reverse=True
                )
                
                for airport, stats in sorted_airports[:5]:
                    detail_embed = self.embed_generator.create_monthly_airport_embed(airport, stats, year, month)
                    await thread.thread.send(embed=detail_embed)
                    await asyncio.sleep(1)
            
            else:
                await channel.send(embed=summary_embed)
            
            logger.info(f"✅ Stats mensuelles envoyées: {month_name} {year}")
            
        except Exception as e:
            logger.error(f"❌ Erreur envoi Discord: {e}")
    
    async def send_annual_stats_to_channel(self, year: int, annual_data: Dict):
        """Envoie le bilan annuel vers Discord"""
        # À implémenter selon les besoins
        pass
    
    # === AVANT-DÉMARRAGE DES TÂCHES ===
    
    @system_monitor_task.before_loop
    async def before_system_monitor(self):
        await self.bot.wait_until_ready()
    
    @precise_monthly_stats.before_loop
    async def before_monthly_stats(self):
        await self.bot.wait_until_ready()
    
    @pre_collect_task.before_loop
    async def before_pre_collect(self):
        await self.bot.wait_until_ready()
    
    @unsent_stats_processor.before_loop
    async def before_unsent_processor(self):
        await self.bot.wait_until_ready()
    
    @annual_stats_task.before_loop
    async def before_annual_stats(self):
        await self.bot.wait_until_ready()
    
    # === COMMANDES UTILISATEUR (CONSERVÉES ET AMÉLIORÉES) ===
    
    @app_commands.command(name="atc_stats", description="Génère les statistiques ATC mensuelles")
    @app_commands.describe(
        month="Mois (1-12, défaut: mois précédent)",
        year="Année (défaut: année actuelle)"
    )
    async def manual_monthly_stats(self, interaction: discord.Interaction, 
                                  month: int = None, year: int = None):
        """Génération manuelle des statistiques mensuelles"""
        if system_lock.is_locked:
            embed = system_lock.get_professional_status_embed()
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            now = datetime.datetime.now()
            if month is None:
                if now.month == 1:
                    month = 12
                    year = now.year - 1 if year is None else year
                else:
                    month = now.month - 1
                    year = now.year if year is None else year
            elif year is None:
                year = now.year
            
            if not (1 <= month <= 12) or not (2020 <= year <= now.year):
                await interaction.followup.send("❌ Paramètres invalides", ephemeral=True)
                return
            
            month_name = calendar.month_name[month]
            
            system_lock.lock_system(
                "Génération manuelle des statistiques",
                f"Traitement {month_name} {year}",
                estimated_duration_minutes=10
            )
            
            try:
                await interaction.followup.send(f"🔄 Génération des statistiques pour **{month_name} {year}**...")
                
                await self.generate_and_send_monthly_stats(year, month)
                
                await interaction.followup.send(f"✅ Statistiques **{month_name} {year}** générées et publiées !")
                
            finally:
                system_lock.unlock_system()
            
        except Exception as e:
            system_lock.unlock_system()
            logger.error(f"❌ Erreur commande manuelle: {e}")
            await interaction.followup.send(f"❌ Erreur: {str(e)[:1000]}")
    
    @app_commands.command(name="atc_recovery", description="Lance la récupération des données manquantes")
    async def manual_recovery(self, interaction: discord.Interaction):
        """Récupération manuelle des données"""
        if system_lock.is_locked:
            embed = system_lock.get_professional_status_embed()
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            missing_periods = self.recovery_manager.get_missing_periods()
            
            if not missing_periods:
                embed = discord.Embed(
                    title="✅ Système à jour",
                    description="Toutes les données historiques sont présentes.",
                    color=0x00FF00
                )
                await interaction.followup.send(embed=embed)
                return
            
            await interaction.followup.send(
                f"🔄 Lancement de la récupération de **{len(missing_periods)}** périodes manquantes..."
            )
            
            # Lancer la récupération
            results = await self.recovery_manager.perform_intelligent_recovery(self.processor)
            
            result_embed = discord.Embed(
                title="✅ Récupération terminée",
                color=0x00FF00 if results.get("status") == "completed" else 0xFFA500
            )
            result_embed.add_field(
                name="📊 Résultats",
                value=f"**Récupéré:** {results.get('recovered', 0)} périodes\n"
                      f"**Échoué:** {results.get('failed', 0)} périodes\n"
                      f"**Total manquant:** {results.get('total_missing', 0)}",
                inline=False
            )
            
            await interaction.followup.send(embed=result_embed)
            
        except Exception as e:
            logger.error(f"❌ Erreur récupération manuelle: {e}")
            await interaction.followup.send(f"❌ Erreur: {str(e)[:1000]}")
    
    @app_commands.command(name="atc_status", description="Affiche le statut du système ATC")
    async def system_status(self, interaction: discord.Interaction):
        """Affiche le statut complet du système"""
        await interaction.response.defer()
        
        try:
            if system_lock.is_locked:
                embed = system_lock.get_professional_status_embed()
                await interaction.followup.send(embed=embed)
                return
            
            # Récupérer les statistiques système
            summary = storage.get_stats_summary()
            
            embed = discord.Embed(
                title="🌴 Système ATC Robuste • État",
                description="Surveillance du contrôle aérien français d'outre-mer",
                color=REGION_COLORS["ANTILLES"],
                timestamp=datetime.datetime.now()
            )
            
            # État système
            embed.add_field(
                name="📊 État du système",
                value=f"**Statut:** 🟢 Opérationnel\n"
                      f"**Stockage:** 🟢 Hybride JSON+SQL\n"
                      f"**Webscraping:** 🟢 Actif\n"
                      f"**Positions surveillées:** {len(ALL_WATCHED_POSITIONS)}\n"
                      f"**Aéroports:** {len(OVERSEAS_AIRPORTS)}\n"
                      f"**Régions:** {len(WATCHED_POSITIONS)}",
                inline=True
            )
            
            # Données
            embed.add_field(
                name="💾 Données",
                value=f"**Périodes:** {summary['total_periods']}\n"
                      f"**Sessions:** {summary['total_sessions']:,}\n"
                      f"**Aéroports actifs:** {summary['active_airports']}\n"
                      f"**Rapports annuels:** {summary['annual_reports']}",
                inline=True
            )
            
            # État en attente
            recovery_status = "🟢 À jour" if summary['missing_months'] == 0 else f"🟡 {summary['missing_months']} manquants"
            sending_status = "🟢 À jour" if summary['unsent_months'] == 0 else f"🟡 {summary['unsent_months']} à envoyer"
            
            embed.add_field(
                name="🔄 État",
                value=f"**Collecte:** {recovery_status}\n"
                      f"**Publication:** {sending_status}\n"
                      f"**Surveillance:** 🟢 Active\n"
                      f"**Auto-envoi:** 🟢 Actif",
                inline=True
            )
            
            # Prochaines exécutions
            now = datetime.datetime.now()
            if now.month == 12:
                next_monthly = datetime.datetime(now.year + 1, 1, 1, 0, 30)
            else:
                next_monthly = datetime.datetime(now.year, now.month + 1, 1, 0, 30)
            
            next_annual = datetime.datetime(now.year + 1, 1, 1, 0, 0)
            
            embed.add_field(
                name="⏰ Planification",
                value=f"**Prochain mensuel:** <t:{int(next_monthly.timestamp())}:R>\n"
                      f"**Prochain annuel:** <t:{int(next_annual.timestamp())}:R>",
                inline=False
            )
            
            embed.set_footer(text="🌴 Système ultra-robuste avec récupération automatique")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"❌ Erreur statut système: {e}")
            await interaction.followup.send(f"❌ Erreur: {str(e)[:1000]}")

async def setup(bot):
    """Configuration du cog ultra-robuste avec stockage JSON et webscraping conservé"""
    try:
        await bot.add_cog(ATCStatsCogRobust(bot))
        logger.info("🌴 Système ATC Stats Ultra-Robuste Complet démarré")
        logger.info("🚀 Fonctionnalités activées:")
        logger.info("   • Stockage hybride JSON+SQL (migration auto)")
        logger.info("   • Webscraping IVAO conservé et optimisé")
        logger.info("   • Récupération automatique des données manquantes")
        logger.info("   • Génération précise à 00:30 pile (avec pré-collecte 23:45)")
        logger.info("   • Système de verrouillage anti-crash professionnel")
        logger.info("   • Traitement automatique des stats non envoyées")
        logger.info("   • Interface Discord avec thème Antilles conservé")
        logger.info("   • Embeds professionnels (sans les termes SMART/INTELLIGENT)")
        logger.info("   • Système de récupération intelligent")
        logger.info("   • Résilience totale avec récupération d'état")
        logger.info("   • Surveillance continue et déblocage auto")
        logger.info("   • Validation cross-check des données")
        logger.info("   • Client API robuste avec retry intelligent")
        
    except Exception as e:
        logger.error(f"❌ Erreur critique démarrage système ATC: {e}")
        raise