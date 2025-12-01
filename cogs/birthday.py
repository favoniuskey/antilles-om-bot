import discord
from discord.ext import commands, tasks
import datetime
import json
import os
import asyncio
import random
from typing import Optional, List, Dict, Any

class Birthday(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.birthdays_file = "utils/birthdays.json"
        self.birthdays = self._load_birthdays()
        self.last_check_date = None
        self.channel_id = 1228454285478461611  # Le salon spécifié
        self.check_birthdays.start()

    def _load_birthdays(self) -> Dict[str, Dict[str, Any]]:
        """Charge les anniversaires depuis le fichier JSON."""
        if os.path.exists(self.birthdays_file):
            try:
                with open(self.birthdays_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_birthdays(self) -> None:
        """Sauvegarde les anniversaires dans le fichier JSON."""
        with open(self.birthdays_file, "w", encoding="utf-8") as f:
            json.dump(self.birthdays, f, ensure_ascii=False, indent=4)

    async def _check_user_in_guild(self, user_id: int, guild_id: int) -> bool:
        """Vérifie si l'utilisateur est toujours dans le serveur."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return False
        return guild.get_member(user_id) is not None

    @commands.command(name="birthday", aliases=["bd"])
    async def add_birthday(self, ctx, user: discord.Member, prenom: str, date: str):
        """Ajoute un anniversaire à la base de données.
        Format: !birthday @utilisateur Prenom JJ/MM/AAAA"""
        
        # Validation de la date
        try:
            day, month, year = map(int, date.split("/"))
            birthday_date = datetime.datetime(year, month, day)
            
            # Calcul de l'âge
            today = datetime.datetime.now()
            age = today.year - year - ((today.month, today.day) < (month, day))
            
            # Stockage au format JJ/MM/AAAA pour faciliter la comparaison
            date_string = f"{day:02d}/{month:02d}/{year}"
            
            # Enregistrer dans la base de données
            self.birthdays[str(user.id)] = {
                "name": prenom,
                "date": date_string,
                "guild_id": ctx.guild.id
            }
            
            self._save_birthdays()
            
            embed = discord.Embed(
                title="🎂 Anniversaire enregistré 🎂",
                description=f"L'anniversaire de **{prenom}** ({user.mention}) a été enregistré au **{date_string}**.\n"
                           f"Âge actuel: **{age}** ans",
                color=discord.Color.green()
            )
            
            # Trouver le prochain anniversaire à venir
            next_birthday = self._get_next_birthday()
            if next_birthday:
                user_id, data = next_birthday
                next_user = self.bot.get_user(int(user_id))
                next_name = data["name"]
                next_date = data["date"]
                
                embed.set_footer(text=f"Prochain anniversaire: {next_name} le {next_date[:5]}")
            
            await ctx.send(embed=embed)
            
        except ValueError:
            await ctx.send("❌ Format de date invalide. Utilisez le format JJ/MM/AAAA.")
        except Exception as e:
            await ctx.send(f"❌ Une erreur s'est produite: {e}")

    @commands.command(name="birthdayls", aliases=["bdls", "birthdays"])
    async def list_birthdays(self, ctx):
        """Affiche la liste des anniversaires enregistrés."""
        if not self.birthdays:
            await ctx.send("Aucun anniversaire n'est enregistré.")
            return
        
        # Vérifier et nettoyer les utilisateurs qui ont quitté le serveur
        users_to_remove = []
        for user_id, data in self.birthdays.items():
            if "guild_id" in data and not await self._check_user_in_guild(int(user_id), data["guild_id"]):
                users_to_remove.append(user_id)
        
        for user_id in users_to_remove:
            del self.birthdays[user_id]
        
        if users_to_remove:
            self._save_birthdays()
        
        if not self.birthdays:
            await ctx.send("Aucun anniversaire n'est enregistré (tous les utilisateurs ont quitté le serveur).")
            return
        
        # Trier les anniversaires par mois et jour
        sorted_birthdays = sorted(
            self.birthdays.items(),
            key=lambda x: (int(x[1]["date"].split("/")[1]), int(x[1]["date"].split("/")[0]))
        )
        
        embed = discord.Embed(
            title="🎂 Liste des anniversaires 🎂",
            description="Voici la liste des anniversaires enregistrés:",
            color=discord.Color.blue()
        )
        
        for user_id, data in sorted_birthdays:
            user = self.bot.get_user(int(user_id))
            username = user.name if user else "Utilisateur inconnu"
            embed.add_field(
                name=f"{data['name']} ({username})",
                value=f"Date: {data['date'][:5]}", # Affiche juste JJ/MM
                inline=True
            )
        
        # Trouver le prochain anniversaire à venir
        next_birthday = self._get_next_birthday()
        if next_birthday:
            user_id, data = next_birthday
            next_name = data["name"]
            next_date = data["date"]
            embed.set_footer(text=f"Prochain anniversaire: {next_name} le {next_date[:5]}")
        
        await ctx.send(embed=embed)

    def _get_next_birthday(self):
        """Détermine le prochain anniversaire à venir."""
        if not self.birthdays:
            return None
        
        today = datetime.datetime.now()
        today_formatted = f"{today.day:02d}/{today.month:02d}"
        
        upcoming_birthdays = []
        for user_id, data in self.birthdays.items():
            day, month, _ = map(int, data["date"].split("/"))
            
            # Calculer la date pour cette année
            this_year = today.year
            next_year = today.year + 1
            
            # Date d'anniversaire cette année
            birthday_this_year = datetime.datetime(this_year, month, day)
            
            # Si l'anniversaire est déjà passé cette année, on regarde l'année prochaine
            if birthday_this_year < today:
                next_birthday = datetime.datetime(next_year, month, day)
            else:
                next_birthday = birthday_this_year
            
            # Nombre de jours jusqu'au prochain anniversaire
            days_until = (next_birthday - today).days
            
            upcoming_birthdays.append((user_id, data, days_until))
        
        # Trier par nombre de jours jusqu'au prochain anniversaire
        upcoming_birthdays.sort(key=lambda x: x[2])
        
        if upcoming_birthdays:
            return (upcoming_birthdays[0][0], upcoming_birthdays[0][1])
        
        return None

    @tasks.loop(minutes=30)
    async def check_birthdays(self):
        """Vérifie les anniversaires et envoie des messages de félicitations."""
        now = datetime.datetime.now()
        today_date = now.strftime("%d/%m")
        
        # Vérifie si on a déjà fait la vérification aujourd'hui à 9h ou après
        if self.last_check_date == now.strftime("%d/%m/%Y") and now.hour >= 9:
            return
        
        # Si ce n'est pas encore 9h du matin, on ne fait rien
        if now.hour < 9:
            return
        
        # Marquer comme vérifié pour aujourd'hui
        self.last_check_date = now.strftime("%d/%m/%Y")
        
        birthdays_today = []
        users_to_remove = []
        
        for user_id, data in self.birthdays.items():
            birthday_date = data["date"][:5]  # Format JJ/MM
            guild_id = data.get("guild_id")
            
            if birthday_date == today_date:
                # Vérifier si l'utilisateur est toujours dans le serveur
                if guild_id and await self._check_user_in_guild(int(user_id), guild_id):
                    birthdays_today.append((user_id, data))
                else:
                    users_to_remove.append(user_id)
        
        # Supprimer les utilisateurs qui ont quitté le serveur
        for user_id in users_to_remove:
            del self.birthdays[user_id]
        
        if users_to_remove:
            self._save_birthdays()
        
        if birthdays_today:
            channel = self.bot.get_channel(self.channel_id)
            if channel:
                for user_id, data in birthdays_today:
                    user = self.bot.get_user(int(user_id))
                    if user:
                        name = data["name"]
                        day, month, year = map(int, data["date"].split("/"))
                        
                        # Calculer l'âge
                        current_year = now.year
                        age = current_year - year
                        
                        # Créer le message d'anniversaire
                        await self._send_birthday_message(channel, user, name, age)

    async def _send_birthday_message(self, channel, user, name, age):
        """Envoie un message d'anniversaire personnalisé."""
        # Messages d'anniversaire sur le thème des Antilles
        greetings = [
            f"🌴 **Joyeux Anniversaire {name}** 🌴",
            f"🥥 **Joyeux Anniversaire {name}** 🥥",
            f"🏝️ **Joyeux Anniversaire {name}** 🏝️",
            f"🌺 **Joyeux Anniversaire {name}** 🌺"
        ]
        
        wishes = [
            f"Que cette journée soit aussi chaude et ensoleillée que les plages des Antilles!",
            f"Que le rhum coule à flots et que les tambours battent en ton honneur!",
            f"Que les vagues du bonheur t'emportent vers une année remplie de joie!",
            f"Que le soleil des Caraïbes brille sur ton année et éclaire ton chemin!",
            f"Autant de bonheur que de grains de sable sur nos belles plages!",
            f"Que cette journée soit aussi délicieuse qu'un bon colombo et aussi douce qu'un planteur!"
        ]
        
        # Créer l'embed
        embed = discord.Embed(
            title=random.choice(greetings),
            description=f"🎉 **{name}** fête ses **{age} ans** aujourd'hui! 🎉\n\n{random.choice(wishes)}",
            color=discord.Color(0xFFA500)  # Couleur orange tropicale
        )
        
        embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
        
        # Ajouter des éléments décoratifs antillais
        emoji_decorations = ["🌴", "🥥", "🏝️", "🎂", "🥂", "🍹", "🌺", "🐚", "🦜", "🎺", "🥁"]
        decoration_line = " ".join(random.sample(emoji_decorations, 5))
        
        embed.add_field(
            name=f"{decoration_line}",
            value=f"Tous les membres du serveur te souhaitent un merveilleux anniversaire {user.mention}!",
            inline=False
        )
        
        # Trouver le prochain anniversaire
        next_birthday = self._get_next_birthday()
        if next_birthday:
            user_id, data = next_birthday
            next_name = data["name"]
            next_date = data["date"][:5]  # Format JJ/MM
            embed.set_footer(text=f"Prochain anniversaire: {next_name} le {next_date}")
        
        # Mention here (fausse mention comme demandé)
        await channel.send("@here", embed=embed)

    @check_birthdays.before_loop
    async def before_check(self):
        """Attend que le bot soit prêt avant de commencer la tâche."""
        await self.bot.wait_until_ready()

    def cog_unload(self):
        """Arrête la tâche lorsque le cog est déchargé."""
        self.check_birthdays.cancel()

async def setup(bot):
    await bot.add_cog(Birthday(bot))