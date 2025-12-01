# cogs/aviation.py
import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import json
import math
import datetime
import re
import random
from typing import Optional, Dict, List, Any, Union, Tuple

AVWX_TOKEN = "y_HR2UvMJO074sqwy8eJ2nqvy5v--VT0HvYY934sb0w"  # Remplacez par votre token AVWX
API_BASE = "https://avwx.rest/api"

# Phrases créoles martiniquaises avec leur traduction
CREOLE_COMMENTS = [
    ("An bel tan-an! Siel-la klè kon dlo koko!", "Quel beau temps! Le ciel est clair comme l'eau de coco!"),
    ("I ni lapli ki ka vini, pran parapli'w!", "Il va pleuvoir, prends ton parapluie!"),
    ("Van-an ka souflay fò, tjenbé chapé'w!", "Le vent souffle fort, tiens ton chapeau!"),
    ("Tan-an cho kon difé!", "Il fait chaud comme le feu!"),
    ("Lapli ka tonbé kon si siel-la té fann!", "Il pleut comme si le ciel s'était fendu!"),
    ("Tan-an fré, mété konpa'w!", "Il fait froid, couvre-toi!"),
    ("Tan-an bel kon an lanmè dé karayib!", "Le temps est beau comme la mer des Caraïbes!"),
    ("Syèl-la ka sanm an vié boutèy wonm!", "Le ciel ressemble à une vieille bouteille de rhum!"),
    ("Nou ké ni bon tan jodi-a!", "Nous aurons du beau temps aujourd'hui!"),
    ("Bwouya épé kon an soup", "Le brouillard est épais comme une soupe"),
    ("Pa ni yon ti van ka soufflé, chalè-la ka tjwé mwen!", "Pas un souffle de vent, la chaleur me tue!"),
    ("Lapli-a ka déboutonnen sièl-la!", "La pluie déboutonne le ciel!"),
    ("Zyé kochon pa ka wè sièl-la!", "Les yeux du cochon ne voient pas le ciel! (visibilité très basse)"),
    ("An ti van fwèt ka soufflé, pa bliyé chimiz-ou!", "Une petite brise fraîche souffle, n'oublie pas ta chemise!"),
    ("Lapli-a tonbé kontel grenn pwa!", "La pluie tombe comme des grains de pois! (forte pluie)"),
]

# Table de conversion des règles de vol
FLIGHT_RULES = {
    "VFR": ("Visual Flight Rules", "🟢", "Conditions de vol à vue excellentes"),
    "MVFR": ("Marginal Visual Flight Rules", "🟡", "Conditions de vol à vue marginales, prudence recommandée"),
    "IFR": ("Instrument Flight Rules", "🟠", "Conditions de vol aux instruments nécessaires"),
    "LIFR": ("Low Instrument Flight Rules", "🔴", "Conditions de vol aux instruments difficiles, visibilité très réduite")
}

# Table des types de nuages
CLOUD_TYPES = {
    "FEW": "Quelques nuages",
    "SCT": "Nuages épars",
    "BKN": "Nuages fragmentés",
    "OVC": "Couverture nuageuse complète",
    "NSC": "Pas de nuages significatifs",
    "SKC": "Ciel clair",
    "CLR": "Ciel clair",
    "///": "Type non détecté"
}

CLOUD_MODIFIERS = {
    "CB": "cumulonimbus",
    "TCU": "cumulus bourgeonnant",
    "CU": "cumulus",
    "CI": "cirrus",
    "///": "indéterminé"
}

# Table de conversion des phénomènes météo
WEATHER_PHENOMENA = {
    # Intensité
    "-": "légère",
    "+": "forte",
    "VC": "à proximité",
    
    # Descripteurs
    "MI": "mince",
    "PR": "partiel",
    "BC": "bancs",
    "DR": "chasse basse",
    "BL": "chasse haute",
    "SH": "averse(s)",
    "TS": "orage",
    "FZ": "se congelant",
    
    # Précipitations
    "DZ": "bruine",
    "RA": "pluie",
    "SN": "neige",
    "SG": "neige en grains",
    "IC": "cristaux de glace",
    "PL": "grésil",
    "GR": "grêle",
    "GS": "grésil et/ou neige roulée",
    "UP": "précipitation inconnue",
    
    # Obscurcissements
    "FG": "brouillard",
    "BR": "brume",
    "SA": "sable",
    "DU": "poussière",
    "HZ": "brume sèche",
    "FU": "fumée",
    "VA": "cendres volcaniques",
    "PY": "brume",
    
    # Autres
    "PO": "tourbillons de poussière/sable",
    "SQ": "grains",
    "FC": "nuage en entonnoir (tornade ou trombe)",
    "SS": "tempête de sable",
    "DS": "tempête de poussière",
}

class Aviation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = None
    
    async def ensure_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
    
    def cog_unload(self):
        if self.session:
            self.bot.loop.create_task(self.session.close())
    
    async def fetch_data(self, endpoint, params=None):
        await self.ensure_session()
        
        headers = {"Authorization": f"Token {AVWX_TOKEN}"}
        url = f"{API_BASE}/{endpoint}"
        
        try:
            async with self.session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 204:
                    return None
                else:
                    error_data = await response.text()
                    return {"error": f"Erreur {response.status}: {error_data}"}
        except Exception as e:
            return {"error": f"Erreur de connexion: {str(e)}"}
    
    async def get_station_info(self, ident):
        return await self.fetch_data(f"station/{ident}")
    
    async def get_metar(self, ident, options="translate,summary"):
        return await self.fetch_data(f"metar/{ident}", {"options": options})
    
    async def get_taf(self, ident, options="translate,summary"):
        return await self.fetch_data(f"taf/{ident}", {"options": options})
    
    async def get_nearest_stations(self, lat, lon, n=5, airport=True, reporting=True):
        # Limitation à 5 stations max pour éviter l'erreur 400
        n = min(5, n)
        params = {
            "n": n,
            "airport": "true" if airport else "false",
            "reporting": "true" if reporting else "false"
        }
        return await self.fetch_data(f"station/near/{lat},{lon}", params)
    
    def format_altitude(self, alt_ft):
        """Formate l'altitude en pieds et mètres"""
        if alt_ft is None:
            return "Inconnue"
        
        alt_m = int(alt_ft * 0.3048)
        return f"{alt_ft} ft ({alt_m} m)"
    
    def parse_visibility(self, vis_data):
        """Convertit la visibilité en format lisible"""
        if not isinstance(vis_data, dict):
            return "Non rapportée"
        
        vis_value = vis_data.get("value")
        vis_repr = vis_data.get("repr", "")
        
        # Cas spécial pour 9999 (> 10 km)
        if vis_repr == "9999":
            return "Plus de 10 km (visibilité excellente)"
        
        # Cas spécial CAVOK
        if vis_repr == "CAVOK":
            return "CAVOK (plafond et visibilité OK) - Plus de 10 km"
        
        # Si la valeur est en mètres (valeurs numériques élevées)
        if vis_value is not None and vis_value > 100:  # Probablement en mètres
            km_value = vis_value / 1000
            miles_value = km_value / 1.60934
            
            if km_value < 1:
                return f"{vis_value} m ({miles_value:.2f} SM) - Visibilité très réduite"
            elif km_value < 3:
                return f"{vis_value} m ({miles_value:.2f} SM) - Visibilité réduite"
            elif km_value < 8:
                return f"{km_value:.1f} km ({miles_value:.2f} SM) - Visibilité modérée"
            else:
                return f"{km_value:.1f} km ({miles_value:.2f} SM) - Bonne visibilité"
        
        # Si la valeur est en miles (SM)
        if vis_value is not None:
            meters = int(vis_value * 1609.34)
            km_value = meters / 1000
            
            if vis_value < 0.5:
                return f"{vis_value} SM ({meters} m) - Visibilité très réduite"
            elif vis_value < 3:
                return f"{vis_value} SM ({km_value:.1f} km) - Visibilité réduite"
            elif vis_value < 6:
                return f"{vis_value} SM ({km_value:.1f} km) - Visibilité modérée"
            else:
                return f"{vis_value} SM ({km_value:.1f} km) - Bonne visibilité"
        
        return "Non rapportée"
    
    def parse_pressure(self, pressure_data):
        """Convertit la pression correctement en tenant compte du format d'origine"""
        if isinstance(pressure_data, dict):
            value = pressure_data.get("value")
            repr_value = pressure_data.get("repr", "")
            
            # Si le format est déjà en hPa (commence par Q)
            if repr_value.startswith("Q"):
                try:
                    hpa_value = float(repr_value[1:])
                    inhg_value = hpa_value / 33.8639
                    return f"{hpa_value:.0f} hPa ({inhg_value:.2f} inHg)"
                except (ValueError, TypeError):
                    pass
            
            # Sinon, supposons que c'est en inHg
            if value is not None:
                hpa_value = value * 33.8639
                return f"{value:.2f} inHg ({hpa_value:.0f} hPa)"
        
        return "Non rapportée"
    
    def weather_code_translation(self, code):
        """Traduit un code météo (ex: -RA) en texte lisible"""
        if not code:
            return ""
        
        intensity = ""
        descriptor = ""
        phenomena = []
        
        # Extraire l'intensité
        if code.startswith('+'):
            intensity = "forte "
            code = code[1:]
        elif code.startswith('-'):
            intensity = "légère "
            code = code[1:]
        
        # Extraire le descripteur (2 caractères)
        if len(code) >= 2 and code[:2] in WEATHER_PHENOMENA:
            descriptor = WEATHER_PHENOMENA[code[:2]] + " "
            code = code[2:]
        
        # Le reste est le phénomène
        while code:
            if len(code) >= 2 and code[:2] in WEATHER_PHENOMENA:
                phenomena.append(WEATHER_PHENOMENA[code[:2]])
                code = code[2:]
            else:
                # Si on ne reconnaît pas le code, on l'ajoute tel quel
                phenomena.append(code)
                break
        
        result = intensity + descriptor + " de ".join(phenomena) if phenomena else intensity + descriptor
        return result.strip()
    
    def format_cloud_layer(self, cloud):
        """Formate une couche nuageuse pour affichage"""
        if not cloud:
            return "Aucun nuage"
        
        cloud_type = cloud.get("type", "")
        cloud_type_text = CLOUD_TYPES.get(cloud_type, cloud_type)
        
        # Traitement des cas spéciaux comme "BKN018///"
        if "///" in cloud_type:
            cloud_type_text = "Couche de nuages (type non précisé)"
        else:
            cloud_type_text = CLOUD_TYPES.get(cloud_type, cloud_type)
        
        altitude_ft = cloud.get("altitude", 0) * 100
        altitude_m = int(altitude_ft * 0.3048)
        
        # Construction du message de base
        result = f"{cloud_type_text} à {altitude_ft} ft ({altitude_m} m)"
        
        # Ajout du modificateur (CB, TCU, etc.)
        modifier = cloud.get("modifier")
        if modifier:
            modifier_text = CLOUD_MODIFIERS.get(modifier, modifier)
            result += f" - {modifier_text}"
        
        return result
    
    def get_wind_direction_text(self, degrees):
        """Convertit les degrés en direction cardinale"""
        if degrees is None:
            return "Variable"
        
        directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", 
                      "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        
        index = round(degrees / 22.5) % 16
        return directions[index]
    
    def celsius_to_fahrenheit(self, celsius):
        """Convertit Celsius en Fahrenheit"""
        if celsius is None:
            return None
        return (celsius * 9/5) + 32
    
    def get_random_creole_comment(self):
        """Retourne un commentaire aléatoire en créole avec sa traduction"""
        return random.choice(CREOLE_COMMENTS)
    
    def select_appropriate_creole_comment(self, metar_data):
        """Sélectionne un commentaire créole approprié aux conditions météo"""
        if not metar_data:
            return self.get_random_creole_comment()
        
        # Récupération des données météo pertinentes
        temp = None
        temp_data = metar_data.get("temperature", {})
        if isinstance(temp_data, dict):
            temp = temp_data.get("value")
        
        wind_speed = None
        wind_speed_data = metar_data.get("wind_speed", {})
        if isinstance(wind_speed_data, dict):
            wind_speed = wind_speed_data.get("value")
        
        # Recherche de phénomènes météo spécifiques
        has_rain = False
        has_fog = False
        has_storm = False
        
        wx_codes = metar_data.get("wx_codes", [])
        for wx in wx_codes:
            if not isinstance(wx, dict):
                continue
            code = wx.get("repr", "")
            if "RA" in code:
                has_rain = True
            if "FG" in code:
                has_fog = True
            if "TS" in code:
                has_storm = True
        
        # Sélection du commentaire approprié
        if has_storm:
            storm_comments = [c for c in CREOLE_COMMENTS if "lapli" in c[0].lower() and "fò" in c[0].lower()]
            return random.choice(storm_comments if storm_comments else CREOLE_COMMENTS)
        elif has_rain:
            rain_comments = [c for c in CREOLE_COMMENTS if "lapli" in c[0].lower()]
            return random.choice(rain_comments if rain_comments else CREOLE_COMMENTS)
        elif has_fog:
            fog_comments = [c for c in CREOLE_COMMENTS if "bwouya" in c[0].lower()]
            return random.choice(fog_comments if fog_comments else CREOLE_COMMENTS)
        elif temp and temp > 28:
            hot_comments = [c for c in CREOLE_COMMENTS if "cho" in c[0].lower()]
            return random.choice(hot_comments if hot_comments else CREOLE_COMMENTS)
        elif temp and temp < 15:
            cold_comments = [c for c in CREOLE_COMMENTS if "fré" in c[0].lower()]
            return random.choice(cold_comments if cold_comments else CREOLE_COMMENTS)
        elif wind_speed and wind_speed > 15:
            wind_comments = [c for c in CREOLE_COMMENTS if "van" in c[0].lower()]
            return random.choice(wind_comments if wind_comments else CREOLE_COMMENTS)
        else:
            good_weather = [c for c in CREOLE_COMMENTS if "bel" in c[0].lower()]
            return random.choice(good_weather if good_weather else CREOLE_COMMENTS)
    
    def create_weather_comment(self, metar_data):
        """Crée un commentaire personnalisé basé sur les conditions météo"""
        if not metar_data:
            return ["Données météo non disponibles"]
            
        comments = []
        
        # Règles de vol
        flight_rules = metar_data.get("flight_rules", "")
        if flight_rules in FLIGHT_RULES:
            fr_info = FLIGHT_RULES[flight_rules]
            comments.append(f"**Règles de vol**: {fr_info[0]} - {fr_info[2]}")
        
        # Visibilité
        visibility = None
        visibility_data = metar_data.get("visibility", {})
        if visibility_data and isinstance(visibility_data, dict):
            visibility = visibility_data.get("value")
            
        if visibility is not None:
            if visibility <= 1:
                comments.append("**Visibilité**: Très réduite, conditions dangereuses pour le vol à vue.")
            elif visibility <= 3:
                comments.append("**Visibilité**: Limitée, prudence recommandée.")
            elif visibility >= 10 or (visibility_data.get("repr") == "9999"):
                comments.append("**Visibilité**: Excellente, conditions idéales.")
        
        # Vent
        wind_speed = None
        wind_speed_data = metar_data.get("wind_speed", {})
        if wind_speed_data and isinstance(wind_speed_data, dict):
            wind_speed = wind_speed_data.get("value")
            
        wind_gust = None
        wind_gust_data = metar_data.get("wind_gust")
        if wind_gust_data and isinstance(wind_gust_data, dict):
            wind_gust = wind_gust_data.get("value")
        
        if wind_speed is not None:
            if wind_speed < 5:
                comments.append("**Vent**: Faible, conditions favorables.")
            elif wind_speed < 15:
                comments.append("**Vent**: Modéré, soyez vigilant lors des manœuvres.")
            elif wind_speed < 25:
                comments.append("**Vent**: Fort, prudence lors du décollage et de l'atterrissage.")
            else:
                comments.append("**Vent**: Très fort, conditions difficiles pour les opérations aériennes.")
        
        if wind_gust and wind_speed and wind_gust > wind_speed + 10:
            comments.append(f"**Attention**: Rafales importantes, anticipez les variations brusques du vent.")
        
        # Phénomènes météo
        wx_codes = metar_data.get("wx_codes", [])
        wx_comments = []
        
        for wx in wx_codes:
            if not isinstance(wx, dict):
                continue
                
            code = wx.get("repr", "")
            if "TS" in code:
                wx_comments.append("⚡ Orages signalés, évitez la zone si possible.")
            if "+RA" in code:
                wx_comments.append("🌧️ Fortes pluies pouvant affecter la visibilité.")
            if "FG" in code:
                wx_comments.append("🌫️ Brouillard présent, anticipez des difficultés de visibilité.")
        
        if wx_comments:
            comments.append("**Phénomènes notables**: " + " ".join(wx_comments))
        
        # Température
        temp = None
        temp_data = metar_data.get("temperature", {})
        if temp_data and isinstance(temp_data, dict):
            temp = temp_data.get("value")
            
        if temp is not None:
            if temp > 30:
                comments.append("**Température**: 🔥 Très élevée, performances des aéronefs réduites.")
            elif temp < 0:
                comments.append("**Température**: ❄️ Négative, possibilité de givrage.")
        
        # Commentaire créole
        creole, translation = self.select_appropriate_creole_comment(metar_data)
        comments.append(f"🌴 **Créole**: \"{creole}\" _(Traduction: {translation})_")
        
        return comments
    
    def format_metar_embed(self, metar_data, station_info=None):
        """Crée un embed Discord pour afficher les informations METAR"""
        if not metar_data or "error" in metar_data:
            error_msg = metar_data.get("error", "Données METAR non disponibles") if metar_data else "Données METAR non disponibles"
            embed = discord.Embed(
                title="❌ Erreur METAR",
                description=error_msg,
                color=discord.Color.red()
            )
            return embed
        
        station = metar_data.get("station", "Unknown")
        raw_text = metar_data.get("raw", "Données non disponibles")
        
        # Obtenir l'émoticône et la couleur basées sur les règles de vol
        flight_rules = metar_data.get("flight_rules", "")
        fr_emoji, fr_color = "❓", discord.Color.light_grey()
        
        if flight_rules in FLIGHT_RULES:
            fr_emoji = FLIGHT_RULES[flight_rules][1]
            if flight_rules == "VFR":
                fr_color = discord.Color.green()
            elif flight_rules == "MVFR":
                fr_color = discord.Color.gold()
            elif flight_rules == "IFR":
                fr_color = discord.Color.orange()
            elif flight_rules == "LIFR":
                fr_color = discord.Color.red()
        
        # Créer l'embed
        station_name = f"{station}"
        if station_info:
            if station_info.get("name"):
                station_name += f" - {station_info.get('name')}"
            if station_info.get("city") and station_info.get("state"):
                station_name += f" ({station_info.get('city')}, {station_info.get('state')})"
            elif station_info.get("city"):
                station_name += f" ({station_info.get('city')})"
        
        embed = discord.Embed(
            title=f"{fr_emoji} METAR pour {station_name}",
            description=f"```{raw_text}```",
            color=fr_color,
            timestamp=datetime.datetime.now()
        )
        
        # Informations sur l'heure d'observation
        time_data = metar_data.get("time", {})
        if time_data and isinstance(time_data, dict) and time_data.get("dt"):
            try:
                obs_time = datetime.datetime.fromisoformat(time_data.get("dt").replace('Z', '+00:00'))
                embed.add_field(
                    name="⏰ Heure d'observation",
                    value=obs_time.strftime("%d %b %Y à %H:%M UTC"),
                    inline=True
                )
            except (ValueError, AttributeError):
                pass
        
        # Règle de vol
        if flight_rules:
            embed.add_field(
                name="✈️ Règle de vol",
                value=f"{FLIGHT_RULES.get(flight_rules, (flight_rules, ''))[0]}",
                inline=True
            )
        
        # Vent
        wind_dir_data = metar_data.get("wind_direction", {})
        wind_speed_data = metar_data.get("wind_speed", {})
        wind_gust_data = metar_data.get("wind_gust")
        wind_var_dir = metar_data.get("wind_variable_direction", [])
        
        wind_dir = None
        wind_speed = None
        wind_gust = None
        
        if isinstance(wind_dir_data, dict):
            wind_dir = wind_dir_data.get("value")
        if isinstance(wind_speed_data, dict):
            wind_speed = wind_speed_data.get("value")
        if isinstance(wind_gust_data, dict):
            wind_gust = wind_gust_data.get("value")
        
        wind_text = "Calme"
        if wind_dir is not None and wind_speed is not None:
            direction_text = self.get_wind_direction_text(wind_dir)
            wind_text = f"{direction_text} ({wind_dir}°) à {wind_speed} kt"
            
            if wind_gust:
                wind_text += f" avec rafales à {wind_gust} kt"
                
            # Ajouter direction variable si présente
            if wind_var_dir and len(wind_var_dir) >= 2:
                try:
                    dir1 = wind_var_dir[0].get("value", 0)
                    dir2 = wind_var_dir[1].get("value", 0)
                    wind_text += f"\nDirection variable entre {dir1}° et {dir2}°"
                except (IndexError, AttributeError, KeyError):
                    pass
        elif wind_dir_data.get("repr") == "VRB" and wind_speed is not None:
            wind_text = f"Variable à {wind_speed} kt"
            
            if wind_gust:
                wind_text += f" avec rafales à {wind_gust} kt"
        
        embed.add_field(
            name="💨 Vent",
            value=wind_text,
            inline=True
        )
        
        # Visibilité
        visibility = metar_data.get("visibility", {})
        vis_text = self.parse_visibility(visibility)
        
        embed.add_field(
            name="👁️ Visibilité",
            value=vis_text,
            inline=False
        )
        
        # Phénomènes météorologiques
        wx_codes = metar_data.get("wx_codes", [])
        wx_text = "Aucun phénomène signalé"
        
        if wx_codes:
            wx_lines = []
            for code in wx_codes:
                if isinstance(code, dict) and "repr" in code:
                    wx_lines.append(f"`{code.get('repr', '')}` — {self.weather_code_translation(code.get('repr', ''))}")
            
            if wx_lines:
                wx_text = "\n".join(wx_lines)
        
        embed.add_field(
            name="🌦️ Phénomènes météo",
            value=wx_text,
            inline=False
        )
        
        # Nuages
        clouds = metar_data.get("clouds", [])
        clouds_text = "Aucun nuage rapporté"
        
        if clouds:
            cloud_lines = []
            for cloud in clouds:
                if isinstance(cloud, dict):
                    cloud_lines.append(self.format_cloud_layer(cloud))
            
            if cloud_lines:
                clouds_text = "\n".join(cloud_lines)
        elif "CAVOK" in raw_text or "SKC" in raw_text or "CLR" in raw_text:
            clouds_text = "Ciel clair"
        
        embed.add_field(
            name="☁️ Nuages",
            value=clouds_text,
            inline=False
        )
        
        # Température et point de rosée
        temp_data = metar_data.get("temperature", {})
        dewpoint_data = metar_data.get("dewpoint", {})
        
        temp = None
        dewpoint = None
        
        if isinstance(temp_data, dict):
            temp = temp_data.get("value")
        if isinstance(dewpoint_data, dict):
            dewpoint = dewpoint_data.get("value")
        
        temp_text = "Non rapportée"
        if temp is not None:
            temp_f = self.celsius_to_fahrenheit(temp)
            temp_text = f"{temp}°C ({temp_f:.1f}°F)"
            
            if dewpoint is not None:
                dewpoint_f = self.celsius_to_fahrenheit(dewpoint)
                temp_text += f"\nPoint de rosée: {dewpoint}°C ({dewpoint_f:.1f}°F)"
                
                # Ajouter l'humidité relative si disponible
                rh = metar_data.get("relative_humidity")
                if rh is not None:
                    temp_text += f"\nHumidité relative: {rh*100:.0f}%"
        
        embed.add_field(
            name="🌡️ Température",
            value=temp_text,
            inline=True
        )
        
        # Pression
        altimeter = metar_data.get("altimeter", {})
        pressure_text = self.parse_pressure(altimeter)
        
        embed.add_field(
            name="⏱️ Pression (QNH)",
            value=pressure_text,
            inline=True
        )
        
        # Ajouter des informations sur la station si disponibles
        if station_info:
            station_lat = station_info.get("latitude")
            station_lon = station_info.get("longitude")
            station_elevation = station_info.get("elevation_ft")
            
            info_text = ""
            
            if station_lat and station_lon:
                info_text += f"📍 Coordonnées: {station_lat:.4f}, {station_lon:.4f}\n"
            
            if station_elevation is not None:
                info_text += f"⛰️ Élévation: {self.format_altitude(station_elevation)}\n"
            
            if info_text:
                embed.add_field(
                    name="ℹ️ Informations station",
                    value=info_text,
                    inline=False
                )
        
        # Ajouter les commentaires sur la météo
        weather_comments = self.create_weather_comment(metar_data)
        if weather_comments:
            embed.add_field(
                name="📝 Analyse météo",
                value="\n".join(weather_comments),
                inline=False
            )
        
        # Si la station a une icao différente de iata, mentionner les deux
        if station_info and station_info.get("icao") != station_info.get("iata") and station_info.get("iata"):
            footer_text = f"ICAO: {station_info.get('icao')} | IATA: {station_info.get('iata')}"
            embed.set_footer(text=footer_text)
        
        return embed
    
    def format_taf_embed(self, taf_data, station_info=None):
        """Crée un embed Discord pour afficher les informations TAF"""
        if not taf_data or "error" in taf_data:
            error_msg = taf_data.get("error", "Données TAF non disponibles") if taf_data else "Données TAF non disponibles"
            embed = discord.Embed(
                title="❌ Erreur TAF",
                description=error_msg,
                color=discord.Color.red()
            )
            return embed
        
        station = taf_data.get("station", "Unknown")
        raw_text = taf_data.get("raw", "Données non disponibles")
        
        # Créer l'embed
        station_name = f"{station}"
        if station_info:
            if station_info.get("name"):
                station_name += f" - {station_info.get('name')}"
            if station_info.get("city") and station_info.get("state"):
                station_name += f" ({station_info.get('city')}, {station_info.get('state')})"
            elif station_info.get("city"):
                station_name += f" ({station_info.get('city')})"
        
        embed = discord.Embed(
            title=f"🗓️ TAF pour {station_name}",
            description=f"```{raw_text}```",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now()
        )
        
        # Informations sur l'heure d'émission
        time_data = taf_data.get("time", {})
        if time_data and isinstance(time_data, dict) and time_data.get("dt"):
            try:
                obs_time = datetime.datetime.fromisoformat(time_data.get("dt").replace('Z', '+00:00'))
                embed.add_field(
                    name="⏰ Émis le",
                    value=obs_time.strftime("%d %b %Y à %H:%M UTC"),
                    inline=True
                )
            except (ValueError, AttributeError):
                pass
        
        # Période de validité
        start_time = taf_data.get("start_time", {})
        end_time = taf_data.get("end_time", {})
        
        validity_text = "Inconnue"
        if isinstance(start_time, dict) and start_time.get("dt") and isinstance(end_time, dict) and end_time.get("dt"):
            try:
                start_dt = datetime.datetime.fromisoformat(start_time.get("dt").replace('Z', '+00:00'))
                end_dt = datetime.datetime.fromisoformat(end_time.get("dt").replace('Z', '+00:00'))
                
                validity_text = f"Du {start_dt.strftime('%d/%m à %H:%M')} au {end_dt.strftime('%d/%m à %H:%M')} UTC"
            except (ValueError, AttributeError):
                pass
        
        embed.add_field(
            name="⏳ Période de validité",
            value=validity_text,
            inline=True
        )
        
        # Prévisions
        forecasts = taf_data.get("forecast", [])
        if forecasts:
            for i, forecast in enumerate(forecasts):
                if not isinstance(forecast, dict):
                    continue
                    
                # Limiter à 5 périodes pour ne pas dépasser la limite des embeds
                if i >= 5:
                    embed.add_field(
                        name="...",
                        value="Plus de périodes disponibles dans le TAF brut ci-dessus",
                        inline=False
                    )
                    break
                
                # Titre de la période
                period_title = "Période initiale" if i == 0 else forecast.get("type", "")
                
                start_time = forecast.get("start_time", {})
                end_time = forecast.get("end_time", {})
                
                if isinstance(start_time, dict) and start_time.get("dt") and isinstance(end_time, dict) and end_time.get("dt"):
                    try:
                        start_dt = datetime.datetime.fromisoformat(start_time.get("dt").replace('Z', '+00:00'))
                        end_dt = datetime.datetime.fromisoformat(end_time.get("dt").replace('Z', '+00:00'))
                        
                        period_title += f" {start_dt.strftime('%d/%m %H:%M')} - {end_dt.strftime('%d/%m %H:%M')} UTC"
                    except (ValueError, AttributeError):
                        pass
                
                # Flight rules pour cette période
                flight_rules = forecast.get("flight_rules", "")
                if flight_rules in FLIGHT_RULES:
                    fr_emoji = FLIGHT_RULES[flight_rules][1]
                    period_title = f"{fr_emoji} {period_title} ({flight_rules})"
                
                # Récupérer les résumés si disponibles, sinon créer un résumé
                forecast_summary = forecast.get("summary", "")
                
                if not forecast_summary:
                    # Construire le résumé manuellement
                    summary_parts = []
                    
                    # Vent
                    wind_dir_data = forecast.get("wind_direction", {})
                    wind_speed_data = forecast.get("wind_speed", {})
                    wind_gust_data = forecast.get("wind_gust")
                    
                    wind_dir = None
                    wind_speed = None
                    wind_gust = None
                    
                    if isinstance(wind_dir_data, dict):
                        wind_dir = wind_dir_data.get("value")
                    if isinstance(wind_speed_data, dict):
                        wind_speed = wind_speed_data.get("value")
                    if isinstance(wind_gust_data, dict):
                        wind_gust = wind_gust_data.get("value")
                    
                    if wind_dir is not None and wind_speed is not None:
                        direction_text = self.get_wind_direction_text(wind_dir)
                        wind_text = f"**Vent**: {direction_text} ({wind_dir}°) à {wind_speed} kt"
                        
                        if wind_gust:
                            wind_text += f" avec rafales à {wind_gust} kt"
                        
                        summary_parts.append(wind_text)
                    elif wind_dir_data.get("repr") == "VRB" and wind_speed is not None:
                        wind_text = f"**Vent**: Variable à {wind_speed} kt"
                        
                        if wind_gust:
                            wind_text += f" avec rafales à {wind_gust} kt"
                        
                        summary_parts.append(wind_text)
                    
                    # Visibilité
                    visibility = forecast.get("visibility", {})
                    vis_text = self.parse_visibility(visibility)
                    summary_parts.append(f"**Visibilité**: {vis_text}")
                    
                    # Phénomènes météo
                    wx_codes = forecast.get("wx_codes", [])
                    if wx_codes:
                        wx_texts = []
                        for code in wx_codes:
                            if isinstance(code, dict) and "repr" in code:
                                wx_texts.append(f"`{code.get('repr')}` {self.weather_code_translation(code.get('repr', ''))}")
                        
                        if wx_texts:
                            summary_parts.append(f"**Météo**: {', '.join(wx_texts)}")
                    
                    # Nuages
                    clouds = forecast.get("clouds", [])
                    if clouds:
                        cloud_texts = []
                        for cloud in clouds[:2]:  # Limiter à 2 couches
                            if isinstance(cloud, dict):
                                cloud_texts.append(self.format_cloud_layer(cloud))
                        
                        if cloud_texts:
                            summary_parts.append(f"**Nuages**: {', '.join(cloud_texts)}")
                    
                    forecast_summary = "\n".join(summary_parts) if summary_parts else "Pas de données détaillées"
                
                embed.add_field(
                    name=period_title,
                    value=forecast_summary or "Pas de données détaillées",
                    inline=False
                )
        
        # Si la station a une icao différente de iata, mentionner les deux
        if station_info and station_info.get("icao") != station_info.get("iata") and station_info.get("iata"):
            footer_text = f"ICAO: {station_info.get('icao')} | IATA: {station_info.get('iata')}"
            embed.set_footer(text=footer_text)
        
        return embed
    
    def format_stations_embed(self, station_info, title="Informations de la station"):
        """Crée un embed Discord pour afficher les informations détaillées d'une station"""
        if not station_info or "error" in station_info:
            error_msg = station_info.get("error", "Informations de station non disponibles") if station_info else "Informations de station non disponibles"
            embed = discord.Embed(
                title="❌ Erreur de recherche de station",
                description=error_msg,
                color=discord.Color.red()
            )
            return embed
            
        station_code = station_info.get("icao", "Unknown")
        station_name = station_info.get("name", "Station inconnue")
        
        embed = discord.Embed(
            title=f"📍 {station_name} ({station_code})",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now()
        )
        
        # Codes et identifiants
        codes_text = ""
        if station_info.get("icao"):
            codes_text += f"ICAO: `{station_info.get('icao')}`\n"
        if station_info.get("iata"):
            codes_text += f"IATA: `{station_info.get('iata')}`\n"
        if station_info.get("gps"):
            codes_text += f"GPS: `{station_info.get('gps')}`\n"
        if station_info.get("local"):
            codes_text += f"Local: `{station_info.get('local')}`\n"
            
        if codes_text:
            embed.add_field(
                name="🏷️ Codes et identifiants",
                value=codes_text,
                inline=True
            )
        
        # Localisation
        location_text = ""
        if station_info.get("city"):
            location_text += f"**Ville**: {station_info.get('city')}\n"
        if station_info.get("state"):
            location_text += f"**État/Région**: {station_info.get('state')}\n"
        if station_info.get("country"):
            location_text += f"**Pays**: {station_info.get('country')}\n"
        if station_info.get("latitude") and station_info.get("longitude"):
            location_text += f"**Coordonnées**: `{station_info.get('latitude'):.4f}, {station_info.get('longitude'):.4f}`\n"
            
        if location_text:
            embed.add_field(
                name="📌 Localisation",
                value=location_text,
                inline=True
            )
        
        # Informations techniques
        tech_text = ""
        if station_info.get("elevation_ft") is not None:
            tech_text += f"**Élévation**: {self.format_altitude(station_info.get('elevation_ft'))}\n"
        if station_info.get("type"):
            tech_text += f"**Type**: {station_info.get('type')}\n"
        if station_info.get("reporting") is not None:
            tech_text += f"**Rapporte METAR**: {'✅' if station_info.get('reporting') else '❌'}\n"
            
        if tech_text:
            embed.add_field(
                name="🔧 Informations techniques",
                value=tech_text,
                inline=True
            )
        
        # Pistes
        runways = station_info.get("runways", [])
        if runways:
            runways_text = ""
            for i, runway in enumerate(runways):
                if not isinstance(runway, dict) or i >= 5:  # Limiter à 5 pistes pour l'affichage
                    break
                    
                ident_text = f"{runway.get('ident1', '??')} / {runway.get('ident2', '??')}"
                length_ft = runway.get('length_ft', 0)
                width_ft = runway.get('width_ft', 0)
                length_m = int(length_ft * 0.3048) if length_ft else 0
                width_m = int(width_ft * 0.3048) if width_ft else 0
                
                runways_text += f"**Piste {ident_text}**: {length_ft} ft × {width_ft} ft ({length_m} m × {width_m} m)\n"
                
            if len(runways) > 5:
                runways_text += f"*+ {len(runways) - 5} autres pistes...*\n"
                
            if runways_text:
                embed.add_field(
                    name="🛫 Pistes",
                    value=runways_text,
                    inline=False
                )
        
        # Informations supplémentaires
        extra_text = ""
        if station_info.get("website"):
            extra_text += f"[Site web officiel]({station_info.get('website')})\n"
        if station_info.get("wiki"):
            extra_text += f"[Page Wikipedia]({station_info.get('wiki')})\n"
        if station_info.get("note"):
            extra_text += f"**Note**: {station_info.get('note')}\n"
            
        if extra_text:
            embed.add_field(
                name="ℹ️ Informations supplémentaires",
                value=extra_text,
                inline=False
            )
        
        # Lien vers les commandes météo
        embed.add_field(
            name="🔄 Commandes associées",
            value=f"Pour obtenir les informations météo, utilisez:\n`/metar {station_code}`\n`/taf {station_code}`",
            inline=False
        )
        
        return embed
        
    def format_nearest_stations_embed(self, stations_data, query=None):
        """Crée un embed Discord pour afficher les informations sur les stations proches"""
        if not stations_data or "error" in stations_data:
            error_msg = stations_data.get("error", "Aucune station trouvée") if isinstance(stations_data, dict) else "Aucune station trouvée"
            embed = discord.Embed(
                title="❌ Erreur de recherche de stations",
                description=error_msg,
                color=discord.Color.red()
            )
            return embed
        
        title = "Stations météo aéronautiques"
        if query:
            title += f" près de {query}"
        
        embed = discord.Embed(
            title=title,
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now()
        )
        
        # Message d'info sur la limitation
        embed.description = "⚠️ L'API limite les résultats à 5 stations à la fois. Voici les stations les plus proches:"
        
        for station_data in stations_data:
            if not isinstance(station_data, dict):
                continue
                
            station = station_data.get("station", {})
            if not isinstance(station, dict):
                continue
                
            distance = station_data.get("kilometers", 0)
            distance_nm = station_data.get("nautical_miles", 0)
            
            station_code = station.get("icao", "Unknown")
            station_name = station.get("name", "Station inconnue")
            station_city = station.get("city", "")
            
            field_title = f"{station_code}"
            if station.get("iata") and station.get("iata") != station_code:
                field_title += f" / {station.get('iata')}"
            
            field_value = f"**{station_name}**\n"
            
            if station_city:
                field_value += f"📍 {station_city}"
                if station.get("state"):
                    field_value += f", {station.get('state')}"
                field_value += "\n"
            
            if station.get("latitude") is not None and station.get("longitude") is not None:
                field_value += f"🌐 `{station.get('latitude'):.4f}, {station.get('longitude'):.4f}`\n"
            
            if station.get("elevation_ft") is not None:
                field_value += f"⛰️ Élévation: {self.format_altitude(station.get('elevation_ft'))}\n"
            
            if distance:
                field_value += f"📏 Distance: {distance:.1f} km ({distance_nm:.1f} NM)\n"
            
            is_reporting = station.get("reporting", False)
            field_value += f"📡 Rapporte METAR: {'✅' if is_reporting else '❌'}\n"
            
            # Ajout des commandes
            field_value += f"🔗 `/metar {station_code}` `/taf {station_code}`"
            
            embed.add_field(
                name=field_title,
                value=field_value,
                inline=True
            )
        
        embed.set_footer(text="Utiliser /stations suivi du code ICAO pour des informations détaillées sur une station spécifique")
        return embed
    
    @app_commands.command(name="metar", description="Obtenir les informations METAR d'un aérodrome")
    @app_commands.describe(
        station="Code ICAO/IATA de la station (ex: KJFK, LFPG) ou coordonnées (lat,lon)"
    )
    async def metar_command(self, interaction: discord.Interaction, station: str):
        await interaction.response.defer()
        
        # Vérifier si c'est une coordonnée (contient une virgule)
        if "," in station:
            try:
                lat, lon = map(float, station.split(","))
                nearest_stations = await self.get_nearest_stations(lat, lon, n=1)
                
                if not nearest_stations or len(nearest_stations) == 0:
                    return await interaction.followup.send("Aucune station météo trouvée près de ces coordonnées.")
                
                station = nearest_stations[0]["station"]["icao"]
            except Exception as e:
                return await interaction.followup.send(f"Format de coordonnées invalide. Utilisez lat,lon comme 48.8567,2.3508. Erreur: {str(e)}")
        
        # Normaliser la station en majuscules
        station = station.upper().strip()
        
        # Obtenir les infos de la station
        station_info = await self.get_station_info(station)
        
        if not station_info or "error" in station_info:
            await interaction.followup.send(f"Station {station} non trouvée. Vérifiez le code ICAO/IATA.")
            return
        
        # Obtenir le METAR
        metar_data = await self.get_metar(station)
        
        # Si pas de METAR disponible, essayer de trouver la station la plus proche qui a des METARs
        if not metar_data or "error" in metar_data:
            lat = station_info.get("latitude")
            lon = station_info.get("longitude")
            
            if lat and lon:
                nearest_stations = await self.get_nearest_stations(lat, lon, n=5)
                
                if nearest_stations and len(nearest_stations) > 0:
                    for station_data in nearest_stations:
                        if not isinstance(station_data, dict) or not isinstance(station_data.get("station"), dict):
                            continue
                            
                        nearby_station_info = station_data.get("station")
                        if nearby_station_info.get("icao") != station and nearby_station_info.get("reporting"):
                            nearby_station = nearby_station_info.get("icao")
                            nearby_metar = await self.get_metar(nearby_station)
                            
                            if nearby_metar and "error" not in nearby_metar:
                                nearby_station_info_full = await self.get_station_info(nearby_station)
                                distance = station_data.get("kilometers", 0)
                                
                                embed = self.format_metar_embed(nearby_metar, nearby_station_info_full)
                                
                                await interaction.followup.send(
                                    content=f"⚠️ Pas de METAR disponible pour {station}. Voici le METAR de la station la plus proche ({nearby_station}) à {distance:.1f} km :",
                                    embed=embed
                                )
                                return
            
            await interaction.followup.send(f"Pas de METAR disponible pour {station} et aucune station proche n'a de données.")
            return
        
        # Créer et envoyer l'embed
        embed = self.format_metar_embed(metar_data, station_info)
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="taf", description="Obtenir les prévisions TAF d'un aérodrome")
    @app_commands.describe(
        station="Code ICAO/IATA de la station (ex: KJFK, LFPG) ou coordonnées (lat,lon)"
    )
    async def taf_command(self, interaction: discord.Interaction, station: str):
        await interaction.response.defer()
        
        # Vérifier si c'est une coordonnée (contient une virgule)
        if "," in station:
            try:
                lat, lon = map(float, station.split(","))
                nearest_stations = await self.get_nearest_stations(lat, lon, n=1)
                
                if not nearest_stations or len(nearest_stations) == 0:
                    return await interaction.followup.send("Aucune station météo trouvée près de ces coordonnées.")
                
                station = nearest_stations[0]["station"]["icao"]
            except Exception as e:
                return await interaction.followup.send(f"Format de coordonnées invalide. Utilisez lat,lon comme 48.8567,2.3508. Erreur: {str(e)}")
        
        # Normaliser la station en majuscules
        station = station.upper().strip()
        
        # Obtenir les infos de la station
        station_info = await self.get_station_info(station)
        
        if not station_info or "error" in station_info:
            await interaction.followup.send(f"Station {station} non trouvée. Vérifiez le code ICAO/IATA.")
            return
        
        # Obtenir le TAF
        taf_data = await self.get_taf(station)
        
        # Si pas de TAF disponible, essayer de trouver la station la plus proche qui a des TAFs
        if not taf_data or "error" in taf_data:
            lat = station_info.get("latitude")
            lon = station_info.get("longitude")
            
            if lat and lon:
                nearest_stations = await self.get_nearest_stations(lat, lon, n=5)
                
                if nearest_stations and len(nearest_stations) > 0:
                    for station_data in nearest_stations:
                        if not isinstance(station_data, dict) or not isinstance(station_data.get("station"), dict):
                            continue
                            
                        nearby_station_info = station_data.get("station")
                        if nearby_station_info.get("icao") != station and nearby_station_info.get("reporting"):
                            nearby_station = nearby_station_info.get("icao")
                            nearby_taf = await self.get_taf(nearby_station)
                            
                            if nearby_taf and "error" not in nearby_taf:
                                nearby_station_info_full = await self.get_station_info(nearby_station)
                                distance = station_data.get("kilometers", 0)
                                
                                embed = self.format_taf_embed(nearby_taf, nearby_station_info_full)
                                
                                await interaction.followup.send(
                                    content=f"⚠️ Pas de TAF disponible pour {station}. Voici le TAF de la station la plus proche ({nearby_station}) à {distance:.1f} km :",
                                    embed=embed
                                )
                                return
            
            await interaction.followup.send(f"Pas de TAF disponible pour {station} et aucune station proche n'a de prévisions.")
            return
        
        # Créer et envoyer l'embed
        embed = self.format_taf_embed(taf_data, station_info)
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="stations", description="Obtenir les informations détaillées d'une station aéronautique")
    @app_commands.describe(
        station="Code ICAO/IATA de la station (ex: KJFK, LFPG)"
    )
    async def stations_command(self, interaction: discord.Interaction, station: str):
        await interaction.response.defer()
        
        # Normaliser la station en majuscules
        station = station.upper().strip()
        
        # Obtenir les infos de la station
        station_info = await self.get_station_info(station)
        
        if not station_info or "error" in station_info:
            await interaction.followup.send(f"Station {station} non trouvée. Vérifiez le code ICAO/IATA.")
            return
        
        # Créer et envoyer l'embed
        embed = self.format_stations_embed(station_info)
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="stations_nearest", description="Trouver les stations météo aéronautiques proches")
    @app_commands.describe(
        query="Code ICAO/IATA d'une station ou coordonnées lat,lon (ex: 48.8567,2.3508)",
        nombre="Nombre de stations à afficher (max 5)"
    )
    async def stations_nearest_command(self, interaction: discord.Interaction, query: str, nombre: Optional[int] = 5):
        await interaction.response.defer()
        
        # Limiter le nombre de stations à 5 pour éviter l'erreur 400
        nombre = min(5, max(1, nombre))
        
        # Vérifier si c'est une coordonnée (contient une virgule)
        if "," in query:
            try:
                lat, lon = map(float, query.split(","))
                stations_data = await self.get_nearest_stations(lat, lon, n=nombre)
                
                if not stations_data or len(stations_data) == 0:
                    return await interaction.followup.send("Aucune station météo trouvée près de ces coordonnées.")
                
                embed = self.format_nearest_stations_embed(stations_data, f"{lat:.4f}, {lon:.4f}")
                return await interaction.followup.send(embed=embed)
            except Exception as e:
                return await interaction.followup.send(f"Format de coordonnées invalide. Utilisez lat,lon comme 48.8567,2.3508. Erreur: {str(e)}")
        
        # Si c'est un code de station, récupérer les coordonnées et chercher les stations proches
        station = query.upper().strip()
        station_info = await self.get_station_info(station)
        
        if not station_info or "error" in station_info:
            return await interaction.followup.send(f"Station {station} non trouvée. Vérifiez le code ICAO/IATA ou utilisez des coordonnées.")
        
        lat = station_info.get("latitude")
        lon = station_info.get("longitude")
        
        if not lat or not lon:
            return await interaction.followup.send(f"Coordonnées non disponibles pour {station}.")
        
        stations_data = await self.get_nearest_stations(lat, lon, n=nombre)
        
        if not stations_data or len(stations_data) == 0:
            return await interaction.followup.send(f"Aucune station météo trouvée près de {station}.")
        
        embed = self.format_nearest_stations_embed(stations_data, station)
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Aviation(bot))