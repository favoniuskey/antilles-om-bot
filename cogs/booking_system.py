import discord
from discord.ext import commands
import asyncio
import logging
from datetime import datetime, timezone, timedelta
import json
import aiohttp
import time
from discord.ext import tasks
from discord import app_commands
import os
from dotenv import load_dotenv
from typing import Dict, Optional, Set

# Configuration identique à ton code original
# Charger les variables d'environnement
load_dotenv()

# Récupérer la clé API IVAO depuis .env
IVAO_API_KEY = os.getenv("IVAO_API_KEY", "")
if not IVAO_API_KEY:
    raise ValueError("❌ IVAO_API_KEY non définie dans .env")

CONFIG = {
    "CHANNEL_ID": "1317134328559440024",
    "BASE_URL": "https://api.ivao.aero/v2/atc/bookings",
    "PER_PAGE": 100,
    "TOKEN_REFRESH_INTERVAL": 600,
    "MAX_MESSAGE_HISTORY": 100,
    "UPDATE_INTERVAL": 5,
    "MESSAGE_PERSISTENCE_FILE": "utils/atc_booking_messages.json",
    "DISCORD_RATE_LIMIT_DELAY": 2.0,  # Augmenté pour plus de sécurité
    "MESSAGE_UPDATE_TIMEOUT": 10,
    "MAX_CONSECUTIVE_FAILURES": 2,  # Nouveau : limite avant recréation
    "MESSAGE_HEALTH_CHECK_INTERVAL": 10,  # Nouveau : vérification santé messages
}

# Positions surveillées (identique à ton code)
WATCHED_POSITIONS = {
    "ANTILLES": [
        "TFFF_APP", "TFFF_DEL", "TFFF_TWR",
        "TFFR_APP", "TFFR_TWR",
        "TFFJ_FIS_TWR", "TFFJ_I_TWR",
        "TFFG_FIS_TWR", "TFFG_I_TWR",
        "TFFM_I_TWR",
    ],
    "GUYANE": [
        "SOCA_APP", "SOCA_TWR",
        "SOOO_CTR", "SOOO_MIL_CTR",
    ],
    "POLYNÉSIE": [
        "NTAA_APP", "NTAA_DEL", "NTAA_TWR",
        "NTTB_TWR", "NTTH_FIS_TWR", "NTTH_I_TWR",
        "NTTM_TWR", "NTTR_TWR", "NTTG_FIS_TWR", "NTTG_I_TWR",
        "NTTT_CTR", "NTAR_FIS_TWR", "NTAR_I_TWR",
        "NTAT_FIS_TWR", "NTAT_I_TWR", "NTAV_FIS_TWR", "NTAV_I_TWR",
        "NTGC_FIS_TWR", "NTGC_I_TWR", "NTGF_FIS_TWR", "NTGF_I_TWR",
        "NTGI_FIS_TWR", "NTGI_I_TWR", "NTGJ_FIS_TWR", "NTGJ_I_TWR",
        "NTGK_FIS_TWR", "NTGK_I_TWR", "NTGM_FIS_TWR", "NTGM_I_TWR",
        "NTGT_FIS_TWR", "NTGT_I_TWR", "NTGU_FIS_TWR", "NTGU_I_TWR",
        "NTGV_FIS_TWR", "NTGV_I_TWR", "NTMD_FIS_TWR", "NTMD_I_TWR",
        "NTMN_FIS_TWR", "NTMN_I_TWR", "NTMP_FIS_TWR", "NTMP_I_TWR",
        "NTMU_FIS_TWR", "NTMU_I_TWR", "NTTO_FIS_TWR", "NTTO_I_TWR",
        "NTTP_FIS_TWR", "NTTP_I_TWR",
    ],
    "RÉUNION_MAYOTTE": [
        "FMEE_APP", "FMEE_GND", "FMEE_TWR",
        "FMEP_FIS_TWR", "FMEP_I_TWR",
        "FMCZ_TWR",
    ],
    "NOUVELLE_CALÉDONIE": [
        "NWWW_APP", "NWWW_GND", "NWWW_TWR",
        "NWWM_APP", "NWWM_TWR",
        "NWWL_FIS_TWR", "NWWD_FIS_TWR", "NWWD_I_TWR",
        "NWWE_FIS_TWR", "NWWE_I_TWR", "NWWR_FIS_TWR", "NWWR_I_TWR",
        "NWWU_FIS_TWR", "NWWU_I_TWR", "NWWV_FIS_TWR", "NWWV_I_TWR",
    ],
    "WALLIS_FUTUNA": [
        "NLWW_FIS_TWR", "NLWW_I_TWR",
        "NLWF_FIS_TWR", "NLWF_I_TWR",
    ],
    "SPM": [
        "LFVP_APP", "LFVP_TWR",
        "LFVM_FIS_TWR", "LFVM_I_TWR",
    ]
}

WATCHED_POSITIONS_FLAT = []
for region, positions in WATCHED_POSITIONS.items():
    WATCHED_POSITIONS_FLAT.extend(positions)

class RegionMessageManager:
    """Gestionnaire ultra-robuste pour un message de région spécifique"""
    
    def __init__(self, region: str, channel: discord.TextChannel, rate_limiter):
        self.region = region
        self.channel = channel
        self.rate_limiter = rate_limiter
        self.message_id: Optional[str] = None
        self.message_cache: Optional[discord.Message] = None
        self.last_successful_update = 0
        self.consecutive_failures = 0
        self.is_updating = False
        self.pending_embed: Optional[discord.Embed] = None
        self._lock = asyncio.Lock()
        
        print(f"🔧 Gestionnaire créé pour région {region}")

    async def update_message(self, embed: discord.Embed) -> bool:
        """Met à jour le message de manière ultra-robuste"""
        async with self._lock:
            if self.is_updating:
                # Si une mise à jour est en cours, stocker l'embed pour plus tard
                self.pending_embed = embed
                print(f"⏳ Mise à jour en cours pour {self.region}, embed mis en attente")
                return True
            
            self.is_updating = True
            
        try:
            success = await self._perform_update(embed)
            
            # Traiter l'embed en attente si présent
            if self.pending_embed and success:
                print(f"🔄 Traitement de l'embed en attente pour {self.region}")
                success = await self._perform_update(self.pending_embed)
                self.pending_embed = None
            
            return success
            
        finally:
            async with self._lock:
                self.is_updating = False

    async def _perform_update(self, embed: discord.Embed) -> bool:
        """Effectue la mise à jour réelle"""
        # Rate limiting spécifique à la région
        await self.rate_limiter.wait_if_needed(f"region_{self.region}")
        
        try:
            # Étape 1 : Valider le message existant
            current_message = await self._validate_current_message()
            
            if current_message:
                # Étape 2 : Tenter mise à jour
                try:
                    await current_message.edit(embed=embed)
                    await self._mark_success()
                    print(f"✅ Message mis à jour pour {self.region} (ID: {self.message_id})")
                    return True
                    
                except discord.HTTPException as e:
                    if e.status == 429:  # Rate limit
                        print(f"⚠️ Rate limit pour {self.region}, attente...")
                        await asyncio.sleep(5)
                        return await self._retry_update(current_message, embed)
                    else:
                        print(f"❌ Erreur HTTP {e.status} pour {self.region}: {e}")
                        await self._mark_failure()
                        
                except Exception as e:
                    print(f"❌ Erreur mise à jour {self.region}: {e}")
                    await self._mark_failure()
            
            # Étape 3 : Créer nouveau message si nécessaire
            if self.consecutive_failures >= CONFIG["MAX_CONSECUTIVE_FAILURES"] or not current_message:
                return await self._create_new_message(embed)
            
            return False
            
        except Exception as e:
            print(f"❌ Erreur critique pour {self.region}: {e}")
            await self._mark_failure()
            return False

    async def _validate_current_message(self) -> Optional[discord.Message]:
        """Valide que le message actuel existe et est accessible"""
        if not self.message_id:
            return None
            
        # Utiliser le cache si récent
        if (self.message_cache and 
            time.time() - self.last_successful_update < 300):  # 5 minutes
            return self.message_cache
        
        try:
            message = await self.channel.fetch_message(int(self.message_id))
            self.message_cache = message
            return message
            
        except discord.NotFound:
            print(f"⚠️ Message {self.message_id} pour {self.region} introuvable")
            await self._reset_message_data()
            return None
            
        except discord.Forbidden:
            print(f"❌ Aucune autorisation pour le message {self.message_id} ({self.region})")
            return None
            
        except Exception as e:
            print(f"❌ Erreur validation message {self.region}: {e}")
            return None

    async def _retry_update(self, message: discord.Message, embed: discord.Embed) -> bool:
        """Retry après rate limit"""
        try:
            await message.edit(embed=embed)
            await self._mark_success()
            print(f"✅ Retry réussi pour {self.region}")
            return True
        except Exception as e:
            print(f"❌ Retry échoué pour {self.region}: {e}")
            await self._mark_failure()
            return False

    async def _create_new_message(self, embed: discord.Embed) -> bool:
        """Crée un nouveau message après nettoyage"""
        try:
            # Nettoyer l'ancien message s'il existe
            await self._cleanup_old_message()
            
            # Rate limiting pour création
            await self.rate_limiter.wait_if_needed(f"create_{self.region}")
            
            # Créer le nouveau message
            new_message = await self.channel.send(embed=embed)
            
            # Mettre à jour les données
            self.message_id = str(new_message.id)
            self.message_cache = new_message
            await self._mark_success()
            
            print(f"✅ Nouveau message créé pour {self.region} (ID: {self.message_id})")
            return True
            
        except Exception as e:
            print(f"❌ Erreur création message {self.region}: {e}")
            await self._mark_failure()
            return False

    async def _cleanup_old_message(self):
        """Nettoie l'ancien message si possible"""
        if self.message_id and self.message_cache:
            try:
                await self.message_cache.delete()
                print(f"🗑️ Ancien message supprimé pour {self.region}")
            except:
                pass  # Ignore les erreurs de suppression
        
        await self._reset_message_data()

    async def _reset_message_data(self):
        """Remet à zéro les données du message"""
        self.message_id = None
        self.message_cache = None
        self.consecutive_failures = 0

    async def _mark_success(self):
        """Marque une mise à jour réussie"""
        import time
        self.last_successful_update = time.time()
        self.consecutive_failures = 0

    async def _mark_failure(self):
        """Marque un échec de mise à jour"""
        self.consecutive_failures += 1
        print(f"⚠️ Échec #{self.consecutive_failures} pour {self.region}")

    async def health_check(self) -> bool:
        """Vérifie la santé du message"""
        if not self.message_id:
            return False
            
        # Si trop d'échecs consécutifs, considérer comme unhealthy
        if self.consecutive_failures >= CONFIG["MAX_CONSECUTIVE_FAILURES"]:
            print(f"🔴 Message {self.region} en mauvaise santé (échecs: {self.consecutive_failures})")
            return False
            
        # Vérifier si le message existe toujours
        message = await self._validate_current_message()
        return message is not None

class DiscordRateLimiter:
    """Rate limiter amélioré avec backoff"""
    def __init__(self, delay: float = 2.0):
        self.delay = delay
        self.last_operation = {}
        self._lock = asyncio.Lock()
        self.backoff_multiplier = {}

    async def wait_if_needed(self, operation_key: str = "default"):
        async with self._lock:
            current_time = time.time()
            last_time = self.last_operation.get(operation_key, 0)
            
            # Calculer le délai avec backoff si nécessaire
            base_delay = self.delay
            multiplier = self.backoff_multiplier.get(operation_key, 1.0)
            actual_delay = base_delay * multiplier
            
            time_since_last = current_time - last_time
            if time_since_last < actual_delay:
                wait_time = actual_delay - time_since_last
                await asyncio.sleep(wait_time)
            
            self.last_operation[operation_key] = time.time()

    def increase_backoff(self, operation_key: str):
        """Augmente le backoff pour une opération spécifique"""
        current = self.backoff_multiplier.get(operation_key, 1.0)
        self.backoff_multiplier[operation_key] = min(current * 1.5, 5.0)  # Max 5x
        
    def reset_backoff(self, operation_key: str):
        """Remet le backoff à zéro"""
        self.backoff_multiplier.pop(operation_key, None)

class BookingMonitor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rate_limiter = DiscordRateLimiter(CONFIG["DISCORD_RATE_LIMIT_DELAY"])
        
        # Gestionnaires de messages par région
        self.region_managers: Dict[str, RegionMessageManager] = {}
        self.monitored_regions = ["MAIN"] + list(WATCHED_POSITIONS.keys())
        
        # Données de persistance
        self.message_persistence_data = {}
        
        self.EMBED_LIMITS = {
            "title": 256, "description": 4096, "fields": 25,
            "field_name": 256, "field_value": 1024, "footer": 2048, "total": 6000
        }
        
        self.initialized = False
        self.ready_event = asyncio.Event()
        
        os.makedirs('utils', exist_ok=True)

    async def wait_for_bot_ready(self):
        if not self.bot.is_ready():
            print("En attente que le bot soit prêt...")
            await self.bot.wait_until_ready()
        self.ready_event.set()

    async def cog_load(self):
        self.bot.loop.create_task(self.initialize_and_start())

    async def initialize_and_start(self):
        await self.wait_for_bot_ready()
        
        try:
            print("🚀 Initialisation du système de booking ultra-robuste...")
            await self.initialize()
            self.load_persistence_data()
            await self.setup_region_managers()
            
            await asyncio.sleep(3)  # Délai initial
            
            if not self.update_bookings.is_running():
                self.update_bookings.start()
                print("✅ Système démarré")
                
            if not self.health_check_loop.is_running():
                self.health_check_loop.start()
                print("✅ Monitoring de santé démarré")
                
        except Exception as e:
            print(f"❌ Erreur initialisation: {e}")
            import traceback
            traceback.print_exc()

    async def initialize(self):
        self.initialized = True

    def load_persistence_data(self):
        """Charge les données de persistance"""
        try:
            with open(CONFIG["MESSAGE_PERSISTENCE_FILE"], "r") as f:
                self.message_persistence_data = json.load(f)
                print(f"📂 Données chargées: {len(self.message_persistence_data)} régions")
        except (FileNotFoundError, json.JSONDecodeError):
            self.message_persistence_data = {}
            print("📂 Nouvelles données de persistance créées")

    def save_persistence_data(self):
        """Sauvegarde les données de persistance"""
        try:
            # Collecter les IDs des gestionnaires
            for region, manager in self.region_managers.items():
                if manager.message_id:
                    self.message_persistence_data[region] = manager.message_id
                else:
                    self.message_persistence_data.pop(region, None)
            
            os.makedirs(os.path.dirname(CONFIG["MESSAGE_PERSISTENCE_FILE"]), exist_ok=True)
            with open(CONFIG["MESSAGE_PERSISTENCE_FILE"], "w") as f:
                json.dump(self.message_persistence_data, f, indent=2)
                
        except Exception as e:
            print(f"❌ Erreur sauvegarde: {e}")

    async def setup_region_managers(self):
        """Configure les gestionnaires de région"""
        channel = self.bot.get_channel(int(CONFIG["CHANNEL_ID"]))
        if not channel:
            channel = await self.bot.fetch_channel(int(CONFIG["CHANNEL_ID"]))
        
        if not channel:
            raise Exception("Canal introuvable")
        
        # Créer les gestionnaires
        for region in self.monitored_regions:
            manager = RegionMessageManager(region, channel, self.rate_limiter)
            
            # Restaurer l'ID du message si disponible
            if region in self.message_persistence_data:
                manager.message_id = self.message_persistence_data[region]
                print(f"🔗 ID restauré pour {region}: {manager.message_id}")
            
            self.region_managers[region] = manager

    @tasks.loop(minutes=CONFIG["MESSAGE_HEALTH_CHECK_INTERVAL"])
    async def health_check_loop(self):
        """Vérifie la santé des messages périodiquement"""
        if not self.ready_event.is_set():
            return
            
        print("🔍 Vérification de santé des messages...")
        
        unhealthy_regions = []
        for region, manager in self.region_managers.items():
            try:
                is_healthy = await manager.health_check()
                if not is_healthy:
                    unhealthy_regions.append(region)
            except Exception as e:
                print(f"❌ Erreur health check {region}: {e}")
                unhealthy_regions.append(region)
        
        if unhealthy_regions:
            print(f"🚨 Régions en mauvaise santé: {unhealthy_regions}")
            # Forcer une mise à jour pour les réparer
            await self.force_update_unhealthy_regions(unhealthy_regions)

    async def force_update_unhealthy_regions(self, unhealthy_regions):
        """Force la mise à jour des régions en mauvaise santé"""
        try:
            # Déclencher une mise à jour complète
            await self.update_bookings()
            print(f"🔄 Mise à jour forcée pour réparer {len(unhealthy_regions)} régions")
        except Exception as e:
            print(f"❌ Erreur lors de la réparation: {e}")

    # Méthodes API identiques à ton code original
    async def fetch_bookings(self, date, page):
        """Identique à ton code"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                token = IVAO_API_KEY
                headers = {"apiKey": IVAO_API_KEY}
                params = {"date": date, "page": page, "perPage": CONFIG["PER_PAGE"]}
                
                async with aiohttp.ClientSession().get(
                    CONFIG["BASE_URL"], headers=headers, params=params, timeout=30
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 401:
                                    continue
                    else:
                        error_text = await response.text()
                        if attempt < max_retries - 1:
                            wait_time = 2 ** attempt
                            await asyncio.sleep(wait_time)
                        else:
                            raise Exception(f"Erreur API: {error_text}")
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)
                else:
                    raise
        return {"items": [], "pages": 0}

    async def fetch_daily_bookings(self, date):
        """Identique à ton code"""
        try:
            bookings = []
            page = 1
            while True:
                data = await self.fetch_bookings(date, page)
                bookings.extend(data["items"])
                if page >= data["pages"] or "pages" not in data:
                    break
                page += 1
            return bookings
        except Exception as e:
            print(f"Erreur fetch daily {date}: {e}")
            return []

    async def fetch_weekly_bookings(self, start_date):
        """Identique à ton code"""
        weekly_bookings = {}
        tasks = []
        
        for i in range(7):
            day = start_date + timedelta(days=i)
            formatted_date = day.strftime("%Y-%m-%d")
            weekly_bookings[formatted_date] = []
            tasks.append((formatted_date, self.fetch_daily_bookings(formatted_date)))
        
        for formatted_date, task in tasks:
            try:
                weekly_bookings[formatted_date] = await task
            except Exception as e:
                print(f"Erreur fetch {formatted_date}: {e}")
                weekly_bookings[formatted_date] = []
        
        return weekly_bookings

    def get_position_region(self, position):
        """Identique à ton code"""
        for region, positions in WATCHED_POSITIONS.items():
            if position in positions:
                return region
        return "AUTRE"

    async def create_or_update_embeds(self, bookings, next_update, channel):
        """Version ultra-robuste de la création/mise à jour des embeds"""
        print("🎨 Création des embeds...")
        
        # Filtrer et organiser les bookings (logique identique à ton code)
        filtered_bookings = {
            date: [b for b in day_bookings if b["atcPosition"] in WATCHED_POSITIONS_FLAT]
            for date, day_bookings in bookings.items()
        }
        
        regional_bookings = {}
        for region in WATCHED_POSITIONS.keys():
            regional_bookings[region] = {}
            for date in filtered_bookings.keys():
                regional_bookings[region][date] = []
                
        for date, day_bookings in filtered_bookings.items():
            for booking in day_bookings:
                region = self.get_position_region(booking["atcPosition"])
                if region in regional_bookings and date in regional_bookings[region]:
                    regional_bookings[region][date].append(booking)
        
        # Créer l'embed principal (logique identique)
        current_datetime = datetime.now(timezone.utc)
        has_any_bookings = any(len(day_bookings) > 0 for day_bookings in filtered_bookings.values())
        
        main_embed = discord.Embed(
            title="🌴 Réservations ATC Outre-Mer 🏝️",
            description=(
                "```md\n# Positions de contrôle surveillées cette semaine\n```\n"
                f"**Date actuelle: {format_date_french(current_datetime)}**\n"
                f"**Heure actuelle: {current_datetime.strftime('%H:%M')} UTC**\n\n"
                "Les réservations sont organisées par région et par jour.\n"
                "*Les positions déjà passées sont ~~barrées~~.*"
            ),
            color=discord.Color.from_rgb(0, 128, 128)
        )
        main_embed.set_thumbnail(url="https://i.imgur.com/QgTGR4j.png")
        
        # Logique de construction des embeds identique à ton code...
        if not has_any_bookings:
            main_embed.add_field(
                name="📅 Semaine en cours",
                value="```🏝️ Aucune réservation cette semaine```",
                inline=False
            )
        else:
            total_bookings = sum(len(day_bookings) for day_bookings in filtered_bookings.values())
            regions_with_bookings = sum(1 for region in regional_bookings if any(
                len(regional_bookings[region][date]) > 0 for date in regional_bookings[region]
            ))
            
            stats_field = (
                f"**Total des réservations:** {total_bookings}\n"
                f"**Régions avec activité:** {regions_with_bookings}/{len(WATCHED_POSITIONS)}\n"
                f"**Période:** {format_date_short(min(filtered_bookings.keys()))} au {format_date_short(max(filtered_bookings.keys()))}"
            )
            main_embed.add_field(name="📊 Statistiques", value=stats_field, inline=False)
            
            region_summary = []
            for region, dates in sorted(regional_bookings.items()):
                region_booking_count = sum(len(bookings) for bookings in dates.values())
                if region_booking_count > 0:
                    region_summary.append(f"• **{region}**: {region_booking_count} réservations")
                else:
                    region_summary.append(f"• **{region}**: Aucune réservation")
            
            if region_summary:
                main_embed.add_field(
                    name="🗺️ Résumé par région",
                    value="\n".join(region_summary),
                    inline=False
                )
        
        next_update_str = (current_datetime + timedelta(minutes=CONFIG["UPDATE_INTERVAL"])).strftime("%H:%M")
        main_embed.set_footer(
            text=f"🔄 Prochaine mise à jour à {next_update_str} UTC • Powered by IVAO API • Antilles Contrôle",
            icon_url="https://em-content.zobj.net/thumbs/120/twitter/321/airplane_2708-fe0f.png"
        )
        
        # **PARTIE ULTRA-ROBUSTE** : Mise à jour avec les gestionnaires
        
        # 1. Mettre à jour le message principal
        success_main = await self.region_managers["MAIN"].update_message(main_embed)
        if success_main:
            self.rate_limiter.reset_backoff("region_MAIN")
        else:
            self.rate_limiter.increase_backoff("region_MAIN")
        
        # 2. Mettre à jour les messages par région avec délais échelonnés
        update_tasks = []
        for i, region in enumerate(WATCHED_POSITIONS.keys()):
            # Créer l'embed pour cette région (logique identique à ton code)
            region_dates = regional_bookings[region]
            has_region_bookings = any(len(bookings) > 0 for bookings in region_dates.values())
            
            region_embed = discord.Embed(
                title=f"🌴 {region} 🏝️",
                color=discord.Color.from_rgb(0, 128, 128)
            )
            
            if not has_region_bookings:
                region_embed.description = f"**Aucune réservation pour la région {region} cette semaine.**\n\n*Les réservations apparaîtront ici dès qu'elles seront disponibles.*"
            else:
                current_date = current_datetime.strftime("%Y-%m-%d")
                for day, day_bookings in sorted(region_dates.items()):
                    if not day_bookings:
                        continue
                        
                    is_current_day = day == current_date
                    day_prefix = "🔆 AUJOURD'HUI" if is_current_day else "📅"
                    
                    day_name = get_french_day_name(datetime.strptime(day, "%Y-%m-%d").strftime("%A"))
                    day_date = datetime.strptime(day, "%Y-%m-%d").strftime(" %d/%m/%Y")
                    field_name = f"{day_prefix} {day_name}{day_date}"
                    
                    field_content = format_day_table(day_bookings, current_datetime)
                    
                    if len(field_content) > self.EMBED_LIMITS["field_value"]:
                        parts = split_content(field_content, self.EMBED_LIMITS["field_value"])
                        for j, part in enumerate(parts):
                            part_name = f"{field_name}" + (f" (Suite {j+1})" if j > 0 else "")
                            region_embed.add_field(name=part_name, value=part, inline=False)
                    else:
                        region_embed.add_field(name=field_name, value=field_content, inline=False)
            
            region_embed.set_footer(
                text=f"🔄 Mis à jour le {current_datetime.strftime('%d/%m/%Y à %H:%M')} UTC • {region}",
                icon_url="https://em-content.zobj.net/thumbs/120/twitter/321/airplane_2708-fe0f.png"
            )
            
            # Programmer la mise à jour avec délai
            async def update_region_delayed(region_name, embed, delay):
                await asyncio.sleep(delay)
                manager = self.region_managers[region_name]
                success = await manager.update_message(embed)
                if success:
                    self.rate_limiter.reset_backoff(f"region_{region_name}")
                else:
                    self.rate_limiter.increase_backoff(f"region_{region_name}")
                return success
            
            # Délai échelonné pour éviter le rate limiting
            delay = i * 3  # 3 secondes entre chaque région
            task = asyncio.create_task(update_region_delayed(region, region_embed, delay))
            update_tasks.append(task)
        
        # Attendre que toutes les mises à jour se terminent
        try:
            results = await asyncio.gather(*update_tasks, return_exceptions=True)
            successful_updates = sum(1 for r in results if r is True)
            print(f"✅ {successful_updates}/{len(update_tasks)} régions mises à jour avec succès")
        except Exception as e:
            print(f"❌ Erreur lors des mises à jour: {e}")
        
        # Sauvegarder après toutes les mises à jour
        self.save_persistence_data()

    @tasks.loop(minutes=CONFIG["UPDATE_INTERVAL"])
    async def update_bookings(self):
        """Boucle principale de mise à jour"""
        if not self.ready_event.is_set():
            await self.wait_for_bot_ready()
        
        try:
            current_time = datetime.now(timezone.utc)
            week_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=current_time.weekday())
            
            print(f"🔄 Mise à jour des réservations ({current_time.strftime('%Y-%m-%d %H:%M:%S')} UTC)")
            
            # Vérifier le canal
            channel = self.bot.get_channel(int(CONFIG["CHANNEL_ID"]))
            if not channel:
                channel = await self.bot.fetch_channel(int(CONFIG["CHANNEL_ID"]))
                if not channel:
                    print("❌ Canal introuvable")
                    return
            
            # Récupérer les bookings
            try:
                bookings = await asyncio.wait_for(
                    self.fetch_weekly_bookings(week_start), 
                    timeout=120
                )
            except asyncio.TimeoutError:
                print("⚠️ Timeout lors de la récupération des réservations")
                return
                
            await self.create_or_update_embeds(bookings, None, channel)
            next_update = current_time + timedelta(minutes=CONFIG["UPDATE_INTERVAL"])
            print(f"✅ Mise à jour terminée. Prochaine à {next_update.strftime('%H:%M:%S')} UTC")

        except Exception as e:
            print(f"❌ Erreur mise à jour: {e}")
            import traceback
            traceback.print_exc()

    @update_bookings.before_loop
    async def before_update_bookings(self):
        await self.bot.wait_until_ready()

    @health_check_loop.before_loop  
    async def before_health_check_loop(self):
        await self.bot.wait_until_ready()

    def cog_unload(self):
        if self.update_bookings.is_running():
            self.update_bookings.cancel()
        if self.health_check_loop.is_running():
            self.health_check_loop.cancel()
            
        self.save_persistence_data()

# Fonctions utilitaires identiques à ton code
def get_french_day_name(day):
    french_days = {
        "Monday": "Lundi", "Tuesday": "Mardi", "Wednesday": "Mercredi",
        "Thursday": "Jeudi", "Friday": "Vendredi", "Saturday": "Samedi", "Sunday": "Dimanche"
    }
    return french_days.get(day, day)

def format_date_french(date):
    day_name = get_french_day_name(date.strftime("%A"))
    return f"{day_name} {date.strftime('%d/%m/%Y')}"

def format_date_short(date_str):
    date = datetime.strptime(date_str, "%Y-%m-%d")
    return date.strftime("%d/%m")

def format_day_table(bookings, current_datetime):
    """Formate les réservations d'un jour en tableau avec prénom + initiale"""
    rows = []
    
    # Trier les réservations par heure de début
    sorted_bookings = sorted(
        bookings, 
        key=lambda b: b.get("startDate", "")
    )
    
    for booking in sorted_bookings:
        position = booking["atcPosition"]
        
        # Format des dates et heures
        start_datetime_str = booking.get("startDate", "")
        end_datetime_str = booking.get("endDate", "")
        
        if not start_datetime_str or not end_datetime_str:
            continue
        
        start_datetime = datetime.fromisoformat(start_datetime_str.replace("Z", "+00:00"))
        end_datetime = datetime.fromisoformat(end_datetime_str.replace("Z", "+00:00"))
        
        start_time = start_datetime.strftime("%H:%M")
        end_time = end_datetime.strftime("%H:%M")
        
        # Vérifier si la réservation est déjà passée
        is_past = end_datetime < current_datetime
        
        user = booking.get("user", {})
        first_name = user.get("firstName")
        last_name = user.get("lastName")
        user_vid = user.get("id", "❓")
        
        # Format : Prénom + Initiale du nom + VID
        if first_name and last_name:
            user_display = f"👤 {first_name} {last_name[0]}. (VID: {user_vid})"
        elif first_name:  # Si pas de nom de famille
            user_display = f"👤 {first_name} (VID: {user_vid})"
        else:  # Si aucun nom disponible
            user_display = f"👤 VID: {user_vid}"
        
        booking_type = "📚 Training" if booking.get("training", False) else "✈️ Normal"
        
        # Formatage avec barrage si la position est déjà passée
        if is_past:
            row = f"```css\n~~[{position}] {start_time}-{end_time} | {user_display} | {booking_type}~~```"
        else:
            row = f"```css\n[{position}] {start_time}-{end_time} | {user_display} | {booking_type}```"
        
        rows.append(row)
    
    return "\n".join(rows) if rows else "```🏝️ Aucune réservation ce jour```"

def split_content(content, max_length):
    parts = []
    current_part = []
    current_length = 0
    
    for line in content.split('\n'):
        if current_length + len(line) + 1 > max_length:
            if current_part:
                parts.append('\n'.join(current_part))
                current_part = []
                current_length = 0
            
            if len(line) > max_length:
                parts.append(line[:max_length])
                remainder = line[max_length:]
                while remainder:
                    parts.append(remainder[:max_length])
                    remainder = remainder[max_length:]
                continue
        
        current_part.append(line)
        current_length += len(line) + 1
    
    if current_part:
        parts.append('\n'.join(current_part))
    
    return parts

# Classe des commandes identique à ton code mais avec les nouvelles méthodes
class BookingCommands(commands.Cog):
    def __init__(self, bot, booking_monitor):
        self.bot = bot
        self.booking_monitor = booking_monitor
        
    @app_commands.command(name="booking_start", description="Démarre la mise à jour automatique")
    @app_commands.checks.has_permissions(administrator=True)
    async def start_update(self, interaction: discord.Interaction):
        if not self.booking_monitor.update_bookings.is_running():
            await self.booking_monitor.initialize()
            self.booking_monitor.update_bookings.start()
            if not self.booking_monitor.health_check_loop.is_running():
                self.booking_monitor.health_check_loop.start()
            await interaction.response.send_message("✅ Système ultra-robuste démarré.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Déjà en cours.", ephemeral=True)

    @app_commands.command(name="booking_stop", description="Arrête la mise à jour automatique")
    @app_commands.checks.has_permissions(administrator=True)
    async def stop_update(self, interaction: discord.Interaction):
        stopped = []
        if self.booking_monitor.update_bookings.is_running():
            self.booking_monitor.update_bookings.cancel()
            stopped.append("mise à jour")
        if self.booking_monitor.health_check_loop.is_running():
            self.booking_monitor.health_check_loop.cancel()
            stopped.append("monitoring")
            
        if stopped:
            await interaction.response.send_message(f"🛑 Arrêté: {', '.join(stopped)}.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Rien à arrêter.", ephemeral=True)

    @app_commands.command(name="booking_force_update", description="Force une mise à jour immédiate")
    @app_commands.checks.has_permissions(administrator=True)
    async def force_update(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            await self.booking_monitor.update_bookings()
            await interaction.followup.send("✅ Mise à jour forcée effectuée.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur: {e}", ephemeral=True)

    @app_commands.command(name="booking_status", description="Affiche l'état du système")
    async def status(self, interaction: discord.Interaction):
        embed = discord.Embed(title="État du système ultra-robuste", color=discord.Color.blue())
        
        # État général
        status_info = []
        status_info.append(f"🤖 Bot prêt: {self.bot.is_ready()}")
        status_info.append(f"📡 Mise à jour active: {self.booking_monitor.update_bookings.is_running()}")
        status_info.append(f"🔍 Monitoring actif: {self.booking_monitor.health_check_loop.is_running()}")
        status_info.append(f"🔑 Token OK: {self.booking_monitor.token_manager.access_token is not None}")
        
        embed.add_field(name="📊 État général", value="\n".join(status_info), inline=False)
        
        # État des gestionnaires de région
        region_status = []
        healthy_count = 0
        for region, manager in self.booking_monitor.region_managers.items():
            has_message = bool(manager.message_id)
            failures = manager.consecutive_failures
            
            if has_message and failures == 0:
                status = "✅"
                healthy_count += 1
            elif has_message and failures < CONFIG["MAX_CONSECUTIVE_FAILURES"]:
                status = "⚠️"
            else:
                status = "❌"
                
            region_status.append(f"{status} **{region}**: MSG={has_message}, Échecs={failures}")
        
        embed.add_field(
            name=f"🌍 Gestionnaires ({healthy_count}/{len(self.booking_monitor.region_managers)} sains)",
            value="\n".join(region_status),
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="booking_repair", description="Répare les messages défaillants")
    @app_commands.checks.has_permissions(administrator=True)
    async def repair_messages(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Réinitialiser tous les gestionnaires défaillants
        repaired = []
        for region, manager in self.booking_monitor.region_managers.items():
            if manager.consecutive_failures >= CONFIG["MAX_CONSECUTIVE_FAILURES"]:
                await manager._reset_message_data()
                repaired.append(region)
        
        if repaired:
            # Forcer une mise à jour pour recréer les messages
            await self.booking_monitor.update_bookings()
            await interaction.followup.send(f"🔧 Réparé: {', '.join(repaired)}", ephemeral=True)
        else:
            await interaction.followup.send("✅ Aucune réparation nécessaire.", ephemeral=True)

    # Autres commandes identiques à ton code...
    @app_commands.command(name="booking_help", description="Affiche l'aide")
    async def help_booking(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Aide système booking ultra-robuste",
            description="Système avec gestionnaires individuels par région et monitoring de santé.",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="📊 Commandes utilisateurs",
            value="`/booking_status` - État du système\n`/booking_help` - Cette aide",
            inline=False
        )
        
        embed.add_field(
            name="🔧 Commandes admin",
            value=(
                "`/booking_start` - Démarre le système\n"
                "`/booking_stop` - Arrête le système\n"
                "`/booking_force_update` - Force une mise à jour\n"
                "`/booking_repair` - Répare les messages défaillants"
            ),
            inline=False
        )
        
        embed.set_footer(text="Système ultra-robuste v2.0 • Antilles Contrôle")
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    import time
    
    booking_monitor = BookingMonitor(bot)
    await bot.add_cog(booking_monitor)
    
    booking_commands = BookingCommands(bot, booking_monitor)
    await bot.add_cog(booking_commands)
    
    return booking_monitor