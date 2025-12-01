import discord
from discord.ext import commands, tasks
import aiohttp
import datetime
import asyncio
import os
from dotenv import load_dotenv
import json
from datetime import timezone, timedelta
import logging
import random
from collections import Counter
from operator import itemgetter

# Configuration du logging
# Charger les variables d'environnement
load_dotenv()

# Récupérer la clé API IVAO depuis .env
IVAO_API_KEY = os.getenv("IVAO_API_KEY", "")
if not IVAO_API_KEY:
    raise ValueError("❌ IVAO_API_KEY non définie dans .env")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("utils/logs/PilotStatsCog")

# Liste des aéroports ultramarins français
OVERSEAS_AIRPORTS = {
    # Antilles
    "TFFR": "Pointe-à-Pitre, Guadeloupe",
    "TFFF": "Fort-de-France, Martinique",
    "TFFJ": "Saint-Barthélemy",
    "LFVP": "Saint-Pierre, Saint-Pierre-et-Miquelon",
    "TFFG": "Grand-Case, Saint-Martin",  # Corrigé de TFFM à TFFG
    # Guyane
    "SOCA": "Cayenne, Guyane",
    # Océan Indien
    "FMEE": "Saint-Denis, La Réunion",
    "FMEP": "Saint-Pierre, La Réunion",
    "FMCZ": "Dzaoudzi, Mayotte",
    # Pacifique
    "NWWW": "Nouméa, Nouvelle-Calédonie",
    "NTAA": "Tahiti Faa'a, Polynésie française",
    "NTTB": "Bora Bora, Polynésie française",
    "NTTR": "Raiatea, Polynésie française",
    "NTTM": "Moorea, Polynésie française",
    "NTTG": "Rangiroa, Polynésie française",
    "NTTX": "Hao, Polynésie française",
    "NTGJ": "Totegegie, Polynésie française",
    "NTAT": "Tubuai, Polynésie française",
    "NTGA": "Anaa, Polynésie française",
    "NTGB": "Apataki, Polynésie française",
    "NTMD": "Nuku Hiva, Polynésie française",
    "NTAR": "Rurutu, Polynésie française"
}

# Regroupement par région
AIRPORT_REGIONS = {
    "Antilles": ["TFFR", "TFFF", "TFFJ", "LFVP", "TFFG"],  # Corrigé de TFFM à TFFG
    "Guyane": ["SOCA"],
    "Océan Indien": ["FMEE", "FMEP", "FMCZ"],
    "Pacifique": ["NWWW", "NTAA", "NTTB", "NTTR", "NTTM", "NTTG", "NTTX", "NTGJ", "NTAT", "NTGA", "NTGB", "NTMD", "NTAR"]
}

# Couleurs par région
REGION_COLORS = {
    "Antilles": 0xFF9500,      # Orange vif
    "Guyane": 0x00C853,        # Vert forêt
    "Océan Indien": 0x2962FF,  # Bleu océan
    "Pacifique": 0x00B8D4      # Turquoise
}

# Messages créoles antillais
CREOLE_MESSAGES = [
"🌴 Un petit aperçu statistique pour vous! Découvrez l'activité des pilotes IVAO dans nos belles îles 🇬🇵 🇲🇶",
"🌊 Voici les chiffres! Jetons un coup d'œil au trafic de nos aéroports 🏝️",
"🌞 Quel plaisir de voir tous ces membres voler sur IVAO, continuez comme ça! 🛫",
"🥥 Voici la situation, tous les mouvements du mois, pas mal du tout! 🏝️",
"🍹 Impressionnant, voici un bel ensemble de données pour vous! Tous les détails du trafic sont ici! 🛩️",
"🌺 Quel beau travail nous faisons! Voici toutes les statistiques de vol pour votre information 🌴",
"🐠 Regardons cela! Les statistiques sont chaudes comme le soleil des Caraïbes! 🔥"
]

class PilotStatsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.stats_channel_id = 1303460838446989362
        self.test_channel_id = 1228454882202226839
        self.client_secret = "mI2S1Y0oEAfoeix3LJ7C4aSdKmT2ajd0"
        self.token = None
        self.token_expires = None
        
        # Créer le dossier data s'il n'existe pas
        os.makedirs("utils", exist_ok=True)
        
        # Fichier pour stocker les dernières statistiques envoyées
        self.last_stats_file = "utils/last_pilot_stats.json"
        
        # Démarrer les tâches périodiques
        self.scheduler.start()
        self.token_refresh_task.start()

    def cog_unload(self):
        self.scheduler.cancel()
        self.token_refresh_task.cancel()

    @tasks.loop(hours=1)
    async def token_refresh_task(self):
        """Rafraîchit le token périodiquement"""
        
    @token_refresh_task.before_loop
    async def before_token_refresh(self):
        await self.bot.wait_until_ready()

    async def get_airport_stats(self, icao, start_date, end_date):
        """Récupérer les statistiques d'un aéroport sur une période donnée"""
        token = IVAO_API_KEY
        if not token:
            logger.error("Impossible d'obtenir un token pour l'API")
            return None
            
        try:
            headers = {"apiKey": IVAO_API_KEY}
            url = f"https://api.ivao.aero/v2/airports/{icao}/traffics/count"
            params = {
                "from": start_date.isoformat(),
                "to": end_date.isoformat()
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 200:
                        stats = await response.json()
                        return stats
                    else:
                        error_text = await response.text()
                        logger.error(f"Erreur API ({response.status}) pour {icao}: {error_text}")
                        return None
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des stats pour {icao}: {e}")
            return None

    async def get_all_airport_stats(self, start_date, end_date):
        """Récupérer les statistiques pour tous les aéroports ultramarins"""
        results = {}
        total_stats = {"inbound": 0, "outbound": 0, "flightover": 0, "total": 0}
        
        for icao, name in OVERSEAS_AIRPORTS.items():
            logger.info(f"Récupération des stats pour {icao} ({name})")
            stats = await self.get_airport_stats(icao, start_date, end_date)
            
            if stats:
                # Ajouter le nom de l'aéroport aux statistiques
                stats["name"] = name
                # Calculer le total pour cet aéroport
                stats["total"] = stats.get("inbound", 0) + stats.get("outbound", 0) + stats.get("flightover", 0)
                
                # Mise à jour des totaux
                total_stats["inbound"] += stats.get("inbound", 0)
                total_stats["outbound"] += stats.get("outbound", 0)
                total_stats["flightover"] += stats.get("flightover", 0)
                total_stats["total"] += stats["total"]
                
                results[icao] = stats
                # Attendre un court moment pour ne pas surcharger l'API
                await asyncio.sleep(0.5)
            else:
                logger.warning(f"Aucune donnée pour {icao}, on continue")
        
        return {"airports": results, "total": total_stats}

    def save_last_stats(self, stats, period):
        """Sauvegarder les dernières statistiques envoyées"""
        try:
            data = {}
            if os.path.exists(self.last_stats_file):
                with open(self.last_stats_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            
            data[period] = {
                "timestamp": datetime.datetime.now().isoformat(),
                "stats": stats
            }
            
            with open(self.last_stats_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde des stats: {e}")

    def load_last_stats(self, period):
        """Charger les dernières statistiques envoyées"""
        try:
            if os.path.exists(self.last_stats_file):
                with open(self.last_stats_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get(period, {}).get("stats")
            return None
        except Exception as e:
            logger.error(f"Erreur lors du chargement des stats: {e}")
            return None

    def get_top_airports(self, stats, limit=5):
        """Récupérer les N aéroports les plus actifs"""
        airports = stats.get("airports", {})
        
        # Créer une liste d'aéroports triée par nombre total de mouvements
        airport_list = [
            {"icao": icao, "name": data.get("name", ""), "total": data.get("total", 0)}
            for icao, data in airports.items()
        ]
        
        # Trier par total décroissant
        airport_list.sort(key=lambda x: x["total"], reverse=True)
        
        # Retourner les N premiers
        return airport_list[:limit]

    def create_monthly_embed(self, region_name, airports_stats):
        """Créer un embed pour les statistiques mensuelles d'une région"""
        color = REGION_COLORS.get(region_name, 0x00BFFF)
        
        embed = discord.Embed(
            title=f"🌴 Statistiques - {region_name} 🌴",
            color=color,
            timestamp=datetime.datetime.now()
        )
        
        # Limiter à 3 airports par embed pour une meilleure lisibilité
        sorted_airports = sorted(airports_stats.items(), key=lambda x: x[1].get("total", 0), reverse=True)
        
        for icao, stats in sorted_airports:
            name = stats.get("name", OVERSEAS_AIRPORTS.get(icao, "Inconnu"))
            inbound = stats.get("inbound", 0)
            outbound = stats.get("outbound", 0)
            flightover = stats.get("flightover", 0)
            total = stats.get("total", 0)
            
            # Utiliser des emojis personnalisés pour chaque aéroport
            embed.add_field(
                name=f"✈️ {icao} - {name}",
                value=f"🛬 **Arrivées**: {inbound}\n🛫 **Départs**: {outbound}\n☁️ **Survols**: {flightover}\n📊 **Total**: {total}",
                inline=False
            )
        
        # Ajouter un indicateur de région avec des emojis
        region_emoji = {
            "Antilles": "🌴🥥🏝️",
            "Guyane": "🌿🐊🌳",
            "Océan Indien": "🐠🌊🏖️",
            "Pacifique": "🐚🏄‍♂️🌺"
        }
        
        embed.set_footer(text=f"Region {region_name} {region_emoji.get(region_name, '')}")
        return embed

    def create_summary_embed(self, stats, period_name):
        """Créer un embed de résumé pour toutes les régions"""
        embed = discord.Embed(
            title=f"📊 Résumé {period_name} - Aéroports Ultramarins 🏝️",
            description=random.choice(CREOLE_MESSAGES),
            color=0xFF9500,  # Orange vif des Antilles
            timestamp=datetime.datetime.now()
        )
        
        # Ajouter le thumbnail (image)
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1234567890/example.png")
        
        total = stats.get("total", {})
        # Utiliser des barres de progression pour les statistiques globales
        total_movements = total.get("total", 0)
        embed.add_field(
            name="📈 Mouvements Globaux",
            value=(
                f"🛬 **Arrivées**: {total.get('inbound', 0)}\n"
                f"🛫 **Départs**: {total.get('outbound', 0)}\n"
                f"☁️ **Survols**: {total.get('flightover', 0)}\n"
                f"📊 **Total**: {total_movements}"
            ),
            inline=False
        )
        
        # Ajouter des statistiques par région de manière plus visuelle
        region_values = []
        for region, icao_list in AIRPORT_REGIONS.items():
            region_total = 0
            for icao in icao_list:
                if icao in stats.get("airports", {}):
                    region_total += stats["airports"][icao].get("total", 0)
            
            # Calculer le pourcentage pour cette région
            if total_movements > 0:
                percentage = round((region_total / total_movements) * 100)
            else:
                percentage = 0
            
            region_values.append(f"**{region}**: {region_total} vols ({percentage}%)")
        
        embed.add_field(
            name="🌍 Répartition par Région",
            value="\n".join(region_values),
            inline=False
        )
        
        # Pied de page avec signature créole
        embed.set_footer(text="Statistiques IVAO Antilles et Outre-Mer | An nou volé!")
        return embed

    def create_top_airports_embed(self, stats, period_name):
        """Créer un embed pour le top 5 des aéroports les plus actifs"""
        top_airports = self.get_top_airports(stats, 5)
        
        embed = discord.Embed(
            title=f"🏆 Top 5 des Aéroports - {period_name} 🏆",
            description="Les aéroports ultramarins les plus actifs sur IVAO!",
            color=0xFFD700,  # Couleur or pour le top
            timestamp=datetime.datetime.now()
        )
        
        # Ajouter chaque aéroport du top avec un emoji de médaille
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        
        for i, airport in enumerate(top_airports):
            if i < len(medals):
                medal = medals[i]
                embed.add_field(
                    name=f"{medal} {airport['icao']} - {airport['name']}",
                    value=f"**Total des mouvements**: {airport['total']}",
                    inline=False
                )
        
        # Ajouter un message de félicitation en créole
        embed.set_footer(text="Félisitasyon pou sé aéwopò-la ki pli aktif la! 🎉")
        return embed

    async def post_thread_message(self, thread, content=None, embed=None):
        """Poster un message dans un thread avec gestion des erreurs"""
        try:
            await thread.send(content=content, embed=embed)
            return True
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi d'un message dans le thread: {e}")
            return False

    async def create_stats_thread(self, channel, title, summary_embed, region_embeds, top_airports_embed):
        """Créer un thread pour les statistiques et y poster les embeds"""
        try:
            # Vérifier le type de canal
            if isinstance(channel, discord.ForumChannel):
                # Pour les canaux de forum, créer un post
                message = await channel.create_thread(
                    name=title,
                    content=random.choice(CREOLE_MESSAGES),
                    auto_archive_duration=10080  # 7 jours (en minutes)
                )
                thread = message.thread
            else:
                # Pour les canaux normaux, créer un message puis un thread
                initial_message = await channel.send("📊 **Statistiques de Trafic IVAO** 📊")
                thread = await initial_message.create_thread(
                    name=title,
                    auto_archive_duration=10080  # 7 jours (en minutes)
                )
            
            # Poster le résumé
            await self.post_thread_message(thread, embed=summary_embed)
            
            # Poster le top 5 des aéroports
            await self.post_thread_message(thread, embed=top_airports_embed)
            
            # Poster les embeds par région
            for embed in region_embeds:
                await self.post_thread_message(thread, embed=embed)
                await asyncio.sleep(0.5)  # Petit délai entre les messages
            
            # Message de conclusion en créole
            await self.post_thread_message(
                thread, 
                content="🌴 **Mèsi anpil** pou vwè sé statistik-la! Kontinié fè vwèl bel adan syel-la! 🛫"
            )
            
            return thread
            
        except Exception as e:
            logger.error(f"Erreur lors de la création du thread: {e}")
            # Essayer d'envoyer un message dans le canal original
            try:
                await channel.send(f"❌ Erreur lors de la création du thread pour les statistiques: {e}")
            except:
                pass
            return None

    async def send_monthly_stats(self, month=None, year=None, channel_id=None):
        """Envoyer les statistiques mensuelles"""
        # Déterminer le mois/année précédent si non spécifié
        now = datetime.datetime.now()
        if month is None:
            if now.month == 1:  # Si janvier, prendre décembre de l'année précédente
                month = 12
                year = now.year - 1
            else:
                month = now.month - 1
                year = now.year
        if year is None:
            year = now.year
            
        # Période de statistiques
        start_date = datetime.datetime(year, month, 1, tzinfo=timezone.utc)
        if month == 12:
            end_date = datetime.datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end_date = datetime.datetime(year, month + 1, 1, tzinfo=timezone.utc)
        
        # Formater le nom du mois en français
        month_names = [
            "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
            "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"
        ]
        month_name = month_names[month - 1]
        
        logger.info(f"Génération des statistiques pour {month_name} {year}")
        
        # Récupérer les statistiques
        stats = await self.get_all_airport_stats(start_date, end_date)
        if not stats:
            logger.error("Échec de la récupération des statistiques")
            return False
            
        # Sauvegarde des statistiques
        self.save_last_stats(stats, f"monthly_{year}_{month}")
        
        # Créer les embeds
        summary_embed = self.create_summary_embed(stats, f"{month_name} {year}")
        top_airports_embed = self.create_top_airports_embed(stats, f"{month_name} {year}")
        region_embeds = []
        
        for region, icao_list in AIRPORT_REGIONS.items():
            region_stats = {}
            for icao in icao_list:
                if icao in stats.get("airports", {}):
                    region_stats[icao] = stats["airports"][icao]
            if region_stats:
                region_embed = self.create_monthly_embed(region, region_stats)
                region_embeds.append(region_embed)
        
        # Déterminer le channel
        channel_to_use = channel_id or self.stats_channel_id
        channel = self.bot.get_channel(channel_to_use)
        if not channel:
            logger.error(f"Canal introuvable: {channel_to_use}")
            return False
            
        # Créer le thread et envoyer les statistiques
        thread_title = f"📊 Trafic IVAO - {month_name} {year} 🌴"
        await self.create_stats_thread(channel, thread_title, summary_embed, region_embeds, top_airports_embed)
        
        logger.info(f"Statistiques pour {month_name} {year} envoyées avec succès")
        return True

    async def send_yearly_stats(self, year=None, channel_id=None):
        """Envoyer les statistiques annuelles"""
        # Déterminer l'année précédente si non spécifiée
        now = datetime.datetime.now()
        if year is None:
            year = now.year - 1
            
        # Période de statistiques
        start_date = datetime.datetime(year, 1, 1, tzinfo=timezone.utc)
        end_date = datetime.datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        
        logger.info(f"Génération des statistiques annuelles pour {year}")
        
        # Récupérer les statistiques
        stats = await self.get_all_airport_stats(start_date, end_date)
        if not stats:
            logger.error("Échec de la récupération des statistiques annuelles")
            return False
            
        # Sauvegarde des statistiques
        self.save_last_stats(stats, f"yearly_{year}")
        
        # Créer les embeds
        summary_embed = self.create_summary_embed(stats, f"Bilan Annuel {year}")
        top_airports_embed = self.create_top_airports_embed(stats, f"Année {year}")
        region_embeds = []
        
        for region, icao_list in AIRPORT_REGIONS.items():
            region_stats = {}
            for icao in icao_list:
                if icao in stats.get("airports", {}):
                    region_stats[icao] = stats["airports"][icao]
            if region_stats:
                region_embed = self.create_monthly_embed(region, region_stats)
                region_embeds.append(region_embed)
        
        # Déterminer le channel
        channel_to_use = channel_id or self.stats_channel_id
        channel = self.bot.get_channel(channel_to_use)
        if not channel:
            logger.error(f"Canal introuvable: {channel_to_use}")
            return False
            
        # Créer le thread et envoyer les statistiques
        thread_title = f"🏆 Bilan Annuel IVAO - {year} 🌴"
        await self.create_stats_thread(channel, thread_title, summary_embed, region_embeds, top_airports_embed)
        
        logger.info(f"Statistiques annuelles pour {year} envoyées avec succès")
        return True

    @tasks.loop(minutes=15)  # Vérifier toutes les 15 minutes
    async def scheduler(self):
        """Planificateur qui vérifie s'il est temps d'envoyer les statistiques"""
        now = datetime.datetime.now()
        
        # Envoyer les statistiques mensuelles le 1er du mois à 00:15
        if now.day == 1 and 0 <= now.hour < 1:
            # Calculer le mois et l'année précédents
            prev_month = 12 if now.month == 1 else now.month - 1
            prev_year = now.year - 1 if now.month == 1 else now.year
            
            # Vérifier si les stats ont déjà été envoyées ce mois-ci
            stats_key = f"monthly_{prev_year}_{prev_month}"
            if not self.load_last_stats(stats_key):
                logger.info(f"Envoi automatique des statistiques mensuelles pour {prev_month}/{prev_year}")
                await self.send_monthly_stats(prev_month, prev_year)
        
        # Envoyer les statistiques annuelles le 1er janvier à 01:00
        if now.day == 1 and now.month == 1 and 1 <= now.hour < 2:
            # Vérifier si les stats annuelles ont déjà été envoyées cette année
            stats_key = f"yearly_{now.year - 1}"
            if not self.load_last_stats(stats_key):
                logger.info(f"Envoi automatique des statistiques annuelles pour {now.year - 1}")
                await self.send_yearly_stats(now.year - 1)

    @scheduler.before_loop
    async def before_scheduler(self):
        await self.bot.wait_until_ready()
        logger.info("Planificateur de statistiques démarré")

    @commands.command(name="testpilotstat")
    @commands.has_permissions(administrator=True)
    async def test_pilot_stats(self, ctx):
        """Tester l'envoi des statistiques pilotes"""
        await ctx.send("🔄 Récupération des statistiques pilotes du mois en cours. Pwan on ti pasyans, sa ka vini titalè! 🌴")
        
        # Déterminer le mois en cours
        now = datetime.datetime.now()
        current_month = now.month
        current_year = now.year
        
        # Envoyer les statistiques du mois en cours dans le canal de test
        success = await self.send_monthly_stats(current_month, current_year, self.test_channel_id)
        
        if success:
            await ctx.send("✅ Test de statistiques pilotes réussi! Tjè mwen kontan! 🎉")
        else:
            await ctx.send("❌ Aïe aïe aïe! Erreur lors du test des statistiques. Vérifiez les logs.")

    @commands.command(name="forcepilotstat")
    @commands.has_permissions(administrator=True)
    async def force_pilot_stats(self, ctx, month: int = None, year: int = None):
        """Forcer l'envoi des statistiques pilotes pour un mois spécifique"""
        if month is None:
            # Utiliser le mois précédent par défaut
            now = datetime.datetime.now()
            if now.month == 1:
                month = 12
                year = now.year - 1 if year is None else year
            else:
                month = now.month - 1
                year = now.year if year is None else year
        
        if not (1 <= month <= 12):
            await ctx.send("❌ Mois invalide! Fok ou mèt on chif ant 1 é 12.")
            return
            
        if year is None:
            year = datetime.datetime.now().year
            
        month_names = [
            "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
            "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"
        ]
        month_name = month_names[month - 1]
            
        await ctx.send(f"🔄 On ka jwenn statistik pou {month_name} {year}... Pwan on ti pasyans! 🌴")
        
        success = await self.send_monthly_stats(month, year)
        
        if success:
            await ctx.send(f"✅ Statistiques pour {month_name} {year} envoyées avec succès! Sa bel, non? 🏝️")
        else:
            await ctx.send(f"❌ Pa ni chans! Erreur lors de l'envoi des statistiques pour {month_name} {year}.")

    @commands.command(name="forceyearlystat")
    @commands.has_permissions(administrator=True)
    async def force_yearly_stats(self, ctx, year: int = None):
        """Forcer l'envoi des statistiques pilotes annuelles"""
        if year is None:
            year = datetime.datetime.now().year - 1
            
        await ctx.send(f"🔄 On ka jwenn tout sé statistik pou lanné {year}... Sa pé pwan on ti moman! 🌴")
        
        success = await self.send_yearly_stats(year)
        
        if success:
            await ctx.send(f"✅ Statistiques annuelles pour {year} envoyées avec succès! Mi bel travay-la! 🎉")
        else:
            await ctx.send(f"❌ Awa! Erreur lors de l'envoi des statistiques annuelles pour {year}. Véyé log-la!")

async def setup(bot):
    await bot.add_cog(PilotStatsCog(bot))