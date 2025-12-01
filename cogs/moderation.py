import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import datetime
import json
import re
import typing
from collections import defaultdict, deque
import os
import random

class AutoModConfig:
    def __init__(self):
        self.config_path = "utils/automod_config.json"
        self.muted_users = {}
        self.auto_purge_users = set()
        self.auto_purge_channels = set()
        self.spam_detection = defaultdict(lambda: deque(maxlen=10))
        self.word_filter = []
        self.load_config()
    
    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                    self.muted_users = data.get('muted_users', {})
                    self.auto_purge_users = set(data.get('auto_purge_users', []))
                    self.auto_purge_channels = set(data.get('auto_purge_channels', []))
                    self.word_filter = data.get('word_filter', [])
            except Exception as e:
                print(f"Erreur lors du chargement de la configuration: {e}")
    
    def save_config(self):
        data = {
            'muted_users': self.muted_users,
            'auto_purge_users': list(self.auto_purge_users),
            'auto_purge_channels': list(self.auto_purge_channels),
            'word_filter': self.word_filter
        }
        try:
            with open(self.config_path, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Erreur lors de la sauvegarde de la configuration: {e}")

# Modal pour les raisons de ban
class BanModal(discord.ui.Modal, title="Bannir un membre"):
    reason = discord.ui.TextInput(
        label="Raison du bannissement",
        placeholder="Entrez la raison du bannissement ici...",
        required=True,
        style=discord.TextStyle.paragraph
    )
    
    delete_days = discord.ui.TextInput(
        label="Jours de messages à supprimer (0-7)",
        placeholder="1",
        required=True,
        max_length=1,
        default="1"
    )
    
    def __init__(self, member, cog):
        super().__init__()
        self.member = member
        self.cog = cog
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Vérifier que le nombre de jours est valide
            try:
                days = int(self.delete_days.value)
                if days < 0 or days > 7:
                    raise ValueError("Le nombre de jours doit être entre 0 et 7")
            except ValueError:
                await interaction.response.send_message("Le nombre de jours doit être un chiffre entre 0 et 7", ephemeral=True)
                return
                
            await self.member.ban(reason=self.reason.value, delete_message_days=days)
            
            # Messages style Antilles
            ban_messages = [
                f"{self.member.mention} a été envoyé faire un tour aux Bahamas! 🏝️",
                f"{self.member.mention} a glissé sur une peau de banane et s'est retrouvé hors du serveur! 🍌",
                f"{self.member.mention} est parti danser le zouk ailleurs! 🎵",
                f"{self.member.mention} a été emporté par une vague de la mer des Caraïbes! 🌊",
                f"{self.member.mention} s'est fait piquer par un oursin, il reviendra plus tard! 🌴",
                f"{self.member.mention} est parti bronzer sur une autre plage! ☀️",
                f"{self.member.mention} a été chassé par un crabe et a quitté l'île! 🦀"
            ]
            
            ban_message = random.choice(ban_messages)
            
            embed = discord.Embed(
                title="🔨 Ban",
                description=ban_message,
                color=discord.Color.red()
            )
            embed.add_field(name="Raison", value=self.reason.value)
            embed.add_field(name="Modérateur", value=interaction.user.mention)
            embed.set_footer(text=f"ID: {self.member.id}")
            
            await interaction.response.send_message(embed=embed)
            
            # Log
            guild = interaction.guild
            log_channel = discord.utils.get(guild.text_channels, name="mod-logs")
            if log_channel:
                log_embed = embed.copy()
                log_embed.add_field(name="Date", value=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                await log_channel.send(embed=log_embed)
            
            # DM à l'utilisateur
            try:
                dm_embed = discord.Embed(
                    title=f"Vous avez été banni de {guild.name}",
                    description=f"Raison: {self.reason.value}",
                    color=discord.Color.red()
                )
                await self.member.send(embed=dm_embed)
            except:
                pass
                
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission de bannir ce membre.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Une erreur s'est produite: {str(e)}", ephemeral=True)

# Modal pour les mutes temporaires
class TempMuteModal(discord.ui.Modal, title="Mute temporaire"):
    reason = discord.ui.TextInput(
        label="Raison du mute",
        placeholder="Entrez la raison du mute ici...",
        required=True,
        style=discord.TextStyle.paragraph
    )
    
    duration = discord.ui.TextInput(
        label="Durée (exemple: 1h, 30m, 1d)",
        placeholder="1h",
        required=True
    )
    
    def __init__(self, member, cog):
        super().__init__()
        self.member = member
        self.cog = cog
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Parse duration
            duration_in_seconds = 0
            time_units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}
            
            pattern = re.compile(r'(\d+)([smhdw])')
            matches = pattern.findall(self.duration.value)
            
            if not matches:
                await interaction.response.send_message("Format de durée invalide. Utilisez des formats comme 1d, 2h, 30m, etc.", ephemeral=True)
                return
            
            for value, unit in matches:
                duration_in_seconds += int(value) * time_units[unit]
            
            if duration_in_seconds <= 0:
                await interaction.response.send_message("La durée doit être positive!", ephemeral=True)
                return
            
            # Vérifier si le rôle Muted existe
            guild = interaction.guild
            mute_role = discord.utils.get(guild.roles, name="Muted")
            if not mute_role:
                mute_role = await self.cog.create_mute_role(guild)
            
            # Appliquer le rôle mute
            await self.member.add_roles(mute_role, reason=self.reason.value)
            
            # Enregistrer le mute pour un démute automatique
            user_id = str(self.member.id)
            end_time = datetime.datetime.now().timestamp() + duration_in_seconds
            
            self.cog.automod.muted_users[user_id] = {
                'guild_id': str(guild.id),
                'duration': duration_in_seconds,
                'end_time': end_time
            }
            self.cog.automod.save_config()
            
            # Message de confirmation
            mute_messages = [
                f"{self.member.mention} a perdu sa voix comme la petite sirène! 🧜‍♀️",
                f"{self.member.mention} a mangé trop de piment et ne peut plus parler pour {self.duration.value}! 🌶️",
                f"{self.member.mention} s'est retrouvé coincé sous un cocotier pour {self.duration.value}! 🥥",
                f"{self.member.mention} est parti faire la sieste au soleil pour {self.duration.value}! 🌞"
            ]
            
            mute_message = random.choice(mute_messages)
            
            embed = discord.Embed(
                title="🔇 Membre réduit au silence",
                description=mute_message,
                color=discord.Color.red()
            )
            embed.add_field(name="Raison", value=self.reason.value)
            embed.add_field(name="Modérateur", value=interaction.user.mention)
            embed.set_footer(text=f"ID: {self.member.id}")
            await interaction.response.send_message(embed=embed)
            
            # Log
            log_channel = discord.utils.get(guild.text_channels, name="mod-logs")
            if log_channel:
                log_embed = embed.copy()
                log_embed.add_field(name="Date", value=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                await log_channel.send(embed=log_embed)
            
            # DM à l'utilisateur
            try:
                dm_embed = discord.Embed(
                    title=f"Vous avez été mute dans {guild.name}",
                    description=f"Durée: {self.duration.value}\nRaison: {self.reason.value}",
                    color=discord.Color.red()
                )
                await self.member.send(embed=dm_embed)
            except:
                pass
                
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission de mute ce membre!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Une erreur s'est produite: {str(e)}", ephemeral=True)

# Modal pour les avertissements
class WarnModal(discord.ui.Modal, title="Avertir un membre"):
    reason = discord.ui.TextInput(
        label="Raison de l'avertissement",
        placeholder="Entrez la raison de l'avertissement ici...",
        required=True,
        style=discord.TextStyle.paragraph
    )
    
    def __init__(self, member):
        super().__init__()
        self.member = member
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Message de confirmation
            embed = discord.Embed(
                title="⚠️ Avertissement",
                description=f"{self.member.mention} a reçu un avertissement!",
                color=discord.Color.gold()
            )
            embed.add_field(name="Raison", value=self.reason.value)
            embed.add_field(name="Modérateur", value=interaction.user.mention)
            embed.set_footer(text=f"ID: {self.member.id}")
            await interaction.response.send_message(embed=embed)
            
            # Log
            guild = interaction.guild
            log_channel = discord.utils.get(guild.text_channels, name="mod-logs")
            if log_channel:
                log_embed = embed.copy()
                log_embed.add_field(name="Date", value=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                await log_channel.send(embed=log_embed)
            
            # DM à l'utilisateur
            try:
                dm_embed = discord.Embed(
                    title=f"Vous avez reçu un avertissement dans {guild.name}",
                    description=f"Raison: {self.reason.value}",
                    color=discord.Color.gold()
                )
                dm_embed.add_field(name="Note", value="Veuillez respecter les règles du serveur pour éviter des sanctions plus sévères.")
                await self.member.send(embed=dm_embed)
            except:
                await interaction.followup.send("Je n'ai pas pu envoyer un message privé à ce membre.", ephemeral=True)
                
        except Exception as e:
            await interaction.response.send_message(f"Une erreur s'est produite: {str(e)}", ephemeral=True)

# Modal pour le filtre de mots
class WordFilterModal(discord.ui.Modal, title="Ajouter un mot au filtre"):
    word = discord.ui.TextInput(
        label="Mot à filtrer",
        placeholder="Entrez le mot à filtrer...",
        required=True
    )
    
    def __init__(self, cog):
        super().__init__()
        self.cog = cog
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            word_value = self.word.value.lower()
            
            if word_value in [w.lower() for w in self.cog.automod.word_filter]:
                await interaction.response.send_message("Ce mot est déjà dans la liste des mots interdits.", ephemeral=True)
                return
            
            self.cog.automod.word_filter.append(word_value)
            self.cog.automod.save_config()
            
            await interaction.response.send_message(f"Mot ajouté à la liste des termes interdits.", ephemeral=True)
            
            # Log
            log_channel = discord.utils.get(interaction.guild.text_channels, name="mod-logs")
            if log_channel:
                embed = discord.Embed(
                    title="⛔ Filtre de mots mis à jour",
                    description=f"Un nouveau mot a été ajouté à la liste des termes interdits",
                    color=discord.Color.red()
                )
                embed.add_field(name="Modérateur", value=interaction.user.mention)
                embed.add_field(name="Date", value=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                await log_channel.send(embed=embed)
                
        except Exception as e:
            await interaction.response.send_message(f"Une erreur s'est produite: {str(e)}", ephemeral=True)

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.automod = AutoModConfig()
        self.cooldowns = commands.CooldownMapping.from_cooldown(5, 10, commands.BucketType.user)
        
        # Démarrer la boucle de background task pour vérifier les mutes temporaires
        self.check_mutes_task = self.bot.loop.create_task(self.check_temp_mutes())
    
    def cog_unload(self):
        self.check_mutes_task.cancel()
    
    # Boucle pour vérifier les mutes temporaires
    async def check_temp_mutes(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            current_time = datetime.datetime.now().timestamp()
            to_unmute = []
            
            for user_id, mute_data in list(self.automod.muted_users.items()):
                if 'duration' in mute_data and current_time >= mute_data['end_time']:
                    to_unmute.append((user_id, mute_data['guild_id']))
            
            for user_id, guild_id in to_unmute:
                guild = self.bot.get_guild(int(guild_id))
                if guild:
                    try:
                        member = await guild.fetch_member(int(user_id))
                        if member:
                            mute_role = discord.utils.get(guild.roles, name="Muted")
                            if mute_role in member.roles:
                                await member.remove_roles(mute_role)
                                del self.automod.muted_users[user_id]
                                self.automod.save_config()
                                
                                log_channel = discord.utils.get(guild.text_channels, name="mod-logs")
                                if log_channel:
                                    embed = discord.Embed(
                                        title="🔊 Auto-Unmute",
                                        description=f"{member.mention} a retrouvé sa voix! Il peut à nouveau parler sous le soleil des Caraïbes! 🌴",
                                        color=discord.Color.green()
                                    )
                                    await log_channel.send(embed=embed)
                    except Exception as e:
                        print(f"Erreur lors du démute automatique: {e}")
            
            await asyncio.sleep(60)  # Vérifier toutes les minutes
    
    # Listeners pour l'automod
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        
        # Auto-purge utilisateur
        if str(message.author.id) in self.automod.auto_purge_users:
            try:
                await message.delete()
                return
            except:
                pass
        
        # Auto-purge salon
        if str(message.channel.id) in self.automod.auto_purge_channels:
            try:
                await message.delete()
                return
            except:
                pass
        
        # Filtre de mots interdits
        if self.automod.word_filter:
            content_lower = message.content.lower()
            for word in self.automod.word_filter:
                if word.lower() in content_lower:
                    try:
                        await message.delete()
                        await message.channel.send(f"{message.author.mention}, votre message a été supprimé car il contient un terme interdit. Ce n'est pas du rhum arrangé ça! 🍹", delete_after=5)
                        
                        # Log
                        log_channel = discord.utils.get(message.guild.text_channels, name="mod-logs")
                        if log_channel:
                            embed = discord.Embed(
                                title="🔍 Mot interdit détecté",
                                description=f"Message de {message.author.mention} supprimé",
                                color=discord.Color.orange()
                            )
                            embed.add_field(name="Canal", value=message.channel.mention)
                            embed.add_field(name="Mot interdit", value=word)
                            await log_channel.send(embed=embed)
                        return
                    except:
                        pass
        
        # Détection de spam
        bucket = self.cooldowns.get_bucket(message)
        retry_after = bucket.update_rate_limit()
        
        if retry_after:
            # L'utilisateur envoie trop de messages
            user_id = str(message.author.id)
            self.automod.spam_detection[user_id].append(message.created_at.timestamp())
            
            # Si l'utilisateur a envoyé plus de 8 messages dans un court laps de temps
            if len(self.automod.spam_detection[user_id]) >= 8:
                oldest = self.automod.spam_detection[user_id][0]
                newest = self.automod.spam_detection[user_id][-1]
                
                # Si les messages ont été envoyés en moins de 10 secondes
                if newest - oldest < 10:
                    try:
                        # Mute temporaire de l'utilisateur pour spam
                        mute_role = discord.utils.get(message.guild.roles, name="Muted")
                        if not mute_role:
                            mute_role = await self.create_mute_role(message.guild)
                        
                        await message.author.add_roles(mute_role)
                        # Mute pour 10 minutes
                        duration = 600
                        end_time = datetime.datetime.now().timestamp() + duration
                        
                        self.automod.muted_users[user_id] = {
                            'guild_id': str(message.guild.id),
                            'duration': duration,
                            'end_time': end_time
                        }
                        self.automod.save_config()
                        
                        await message.channel.send(f"{message.author.mention} a été mute pendant 10 minutes pour spam. C'est pas une plage ici, mon frère! 🏝️", delete_after=10)
                        
                        # Log
                        log_channel = discord.utils.get(message.guild.text_channels, name="mod-logs")
                        if log_channel:
                            embed = discord.Embed(
                                title="🔇 Mute Automatique",
                                description=f"{message.author.mention} a été mute pour spam",
                                color=discord.Color.red()
                            )
                            embed.add_field(name="Durée", value="10 minutes")
                            await log_channel.send(embed=embed)
                    except Exception as e:
                        print(f"Erreur lors du mute automatique: {e}")
    
    async def create_mute_role(self, guild):
        # Créer le rôle muted s'il n'existe pas
        mute_role = await guild.create_role(name="Muted", reason="Rôle automatique pour les utilisateurs mute")
        
        # Configurer les permissions pour tous les canaux
        for channel in guild.channels:
            if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                overwrites = channel.overwrites_for(mute_role)
                overwrites.send_messages = False
                overwrites.speak = False
                overwrites.add_reactions = False
                await channel.set_permissions(mute_role, overwrite=overwrites)
        
        return mute_role
    
    # Commandes slash
    @app_commands.command(name="ban", description="Bannir un membre du serveur")
    @app_commands.default_permissions(administrator=True)
    async def ban_slash(self, interaction: discord.Interaction, member: discord.Member):
        """Bannir un membre avec un modal pour la raison"""
        if member == interaction.user:
            await interaction.response.send_message("Vous ne pouvez pas vous bannir vous-même!", ephemeral=True)
            return
                
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("Vous ne pouvez pas bannir un membre ayant un rôle supérieur ou égal au vôtre!", ephemeral=True)
            return
        
        # Utiliser un modal pour la raison et les options
        modal = BanModal(member, self)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="tempban", description="Bannir temporairement un membre du serveur")
    @app_commands.default_permissions(administrator=True)
    async def tempban_slash(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = None):
        try:
            if member == interaction.user:
                await interaction.response.send_message("Vous ne pouvez pas vous bannir temporairement!", ephemeral=True)
                return
                
            if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
                await interaction.response.send_message("Vous ne pouvez pas bannir un membre ayant un rôle supérieur ou égal au vôtre!", ephemeral=True)
                return
            
            # Parse duration (1d, 2h, 30m, etc.)
            duration_in_seconds = 0
            time_units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}
            
            pattern = re.compile(r'(\d+)([smhdw])')
            matches = pattern.findall(duration)
            
            if not matches:
                await interaction.response.send_message("Format de durée invalide. Utilisez des formats comme 1d, 2h, 30m, etc.", ephemeral=True)
                return
            
            for value, unit in matches:
                duration_in_seconds += int(value) * time_units[unit]
            
            if duration_in_seconds <= 0:
                await interaction.response.send_message("La durée doit être positive!", ephemeral=True)
                return
                
            await member.ban(reason=f"Ban temporaire: {reason}", delete_message_days=1)
            
            # Messages style Antilles
            temp_ban_messages = [
                f"{member.mention} est parti faire un tour aux Bahamas pour {duration}! 🏝️",
                f"{member.mention} a glissé sur une peau de banane et reviendra dans {duration}! 🍌",
                f"{member.mention} est allé pêcher dans la mer des Caraïbes pour {duration}! 🎣",
                f"{member.mention} est parti prendre un cocktail sur une autre île pour {duration}! 🍹",
                f"{member.mention} a été emporté par une vague et reviendra quand la marée sera basse dans {duration}! 🌊"
            ]
            
            ban_message = random.choice(temp_ban_messages)
            
            embed = discord.Embed(
                title="⏱️ Ban Temporaire",
                description=ban_message,
                color=discord.Color.red()
            )
            embed.add_field(name="Raison", value=reason or "Aucune raison spécifiée")
            embed.add_field(name="Modérateur", value=interaction.user.mention)
            embed.set_footer(text=f"ID: {member.id}")
            await interaction.response.send_message(embed=embed)
            
            # Log
            log_channel = discord.utils.get(interaction.guild.text_channels, name="mod-logs")
            if log_channel:
                log_embed = embed.copy()
                log_embed.add_field(name="Date", value=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                await log_channel.send(embed=log_embed)
            
            # Schedule unban
            self.bot.loop.create_task(self.schedule_unban(interaction.guild, member, duration_in_seconds))
                
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission de bannir ce membre.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Une erreur s'est produite: {str(e)}", ephemeral=True)
    
    async def schedule_unban(self, guild, member, duration_in_seconds):
        await asyncio.sleep(duration_in_seconds)
        try:
            await guild.unban(member, reason="Fin du ban temporaire")
            
            # Log unban
            log_channel = discord.utils.get(guild.text_channels, name="mod-logs")
            if log_channel:
                unban_embed = discord.Embed(
                    title="🔓 Fin du Ban Temporaire",
                    description=f"{member} revient de son escapade aux Caraïbes! 🏝️",
                    color=discord.Color.green()
                )
                await log_channel.send(embed=unban_embed)
        except:
            log_channel = discord.utils.get(guild.text_channels, name="mod-logs")
            if log_channel:
                error_embed = discord.Embed(
                    title="⚠️ Erreur de déban automatique",
                    description=f"Impossible de débannir {member} automatiquement",
                    color=discord.Color.gold()
                )
                await log_channel.send(embed=error_embed)

    @app_commands.command(name="unban", description="Débannir un membre du serveur")
    @app_commands.default_permissions(administrator=True)
    async def unban_slash(self, interaction: discord.Interaction, user_id: str):
        try:
            banned_users = [entry async for entry in interaction.guild.bans()]
            
            user_to_unban = None
            if user_id.isdigit():  # User ID
                user_id_int = int(user_id)
                for ban_entry in banned_users:
                    if ban_entry.user.id == user_id_int:
                        user_to_unban = ban_entry.user
                        break
            else:  # Username format
                for ban_entry in banned_users:
                    if ban_entry.user.name.lower() == user_id.lower():
                        user_to_unban = ban_entry.user
                        break
            
            if user_to_unban:
                await interaction.guild.unban(user_to_unban)
                
                unban_messages = [
                    f"{user_to_unban} est revenu de son voyage aux Bahamas! 🏝️",
                    f"{user_to_unban} a trouvé son chemin de retour sur l'île! 🌴",
                    f"{user_to_unban} a repris le bateau et est de retour parmi nous! ⛵",
                    f"{user_to_unban} a décidé de revenir danser le zouk avec nous! 🎵"
                ]
                
                unban_message = random.choice(unban_messages)
                
                embed = discord.Embed(
                    title="🔓 Unban",
                    description=unban_message,
                    color=discord.Color.green()
                )
                embed.add_field(name="Modérateur", value=interaction.user.mention)
                embed.set_footer(text=f"ID: {user_to_unban.id}")
                await interaction.response.send_message(embed=embed)
                
                # Log
                log_channel = discord.utils.get(interaction.guild.text_channels, name="mod-logs")
                if log_channel:
                    log_embed = embed.copy()
                    log_embed.add_field(name="Date", value=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                    await log_channel.send(embed=log_embed)
            else:
                await interaction.response.send_message("Utilisateur banni non trouvé.", ephemeral=True)
                
        except Exception as e:
            await interaction.response.send_message(f"Erreur lors du déban: {str(e)}", ephemeral=True)

    @app_commands.command(name="kick", description="Expulser un membre du serveur")
    @app_commands.default_permissions(administrator=True)
    async def kick_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        try:
            if member == interaction.user:
                await interaction.response.send_message("Vous ne pouvez pas vous expulser vous-même!", ephemeral=True)
                return
                
            if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
                await interaction.response.send_message("Vous ne pouvez pas expulser un membre ayant un rôle supérieur ou égal au vôtre!", ephemeral=True)
                return

            # Messages rigolos pour l'expulsion
            kick_messages = [
                f"{member.mention} a été botté hors du serveur comme un ballon de foot sur la plage! 🦵",
                f"{member.mention} a été catapulté vers une autre île! 🏝️",
                f"{member.mention} a glissé sur une peau de banane et s'est retrouvé hors du serveur! 🍌",
                f"{member.mention} est allé explorer le vaste monde des Caraïbes! 🌴",
                f"{member.mention} a pris un aller simple pour une autre plage! 🏖️",
                f"{member.mention} a été emporté par une vague géante! 🌊",
                f"{member.mention} est parti chercher des noix de coco ailleurs! 🥥"
            ]
            
            # DM à l'utilisateur avant le kick
            try:
                dm_embed = discord.Embed(
                    title=f"Vous avez été expulsé de {interaction.guild.name}",
                    description=f"Raison: {reason or 'Aucune raison spécifiée'}",
                    color=discord.Color.orange()
                )
                await member.send(embed=dm_embed)
            except:
                pass
            
            await member.kick(reason=reason)
            
            # Message aléatoire pour le kick
            kick_message = random.choice(kick_messages)
            
            embed = discord.Embed(
                title="👢 Membre expulsé",
                description=kick_message,
                color=discord.Color.orange()
            )
            embed.add_field(name="Raison", value=reason or "Aucune raison spécifiée")
            embed.add_field(name="Modérateur", value=interaction.user.mention)
            embed.set_footer(text=f"ID: {member.id}")
            await interaction.response.send_message(embed=embed)
            
            # Log
            log_channel = discord.utils.get(interaction.guild.text_channels, name="mod-logs")
            if log_channel:
                log_embed = embed.copy()
                log_embed.add_field(name="Date", value=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                await log_channel.send(embed=log_embed)
                
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission d'expulser ce membre!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Une erreur s'est produite: {str(e)}", ephemeral=True)

    @app_commands.command(name="purge", description="Supprimer plusieurs messages d'un canal")
    @app_commands.default_permissions(administrator=True)
    async def purge_slash(self, interaction: discord.Interaction, amount: int, filter_type: typing.Optional[str] = None, filter_value: typing.Optional[str] = None):
        try:
            if amount <= 0 or amount > 100:
                await interaction.response.send_message("Le nombre de messages à supprimer doit être entre 1 et 100.", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            # Configuration des filtres de purge
            def check_message(message):
                # Si aucun filtre spécifié, supprimer tous les messages
                if not filter_type:
                    return True
                
                filter_type_lower = filter_type.lower()
                
                # Filtre par type d'utilisateur
                if filter_type_lower == "bots":
                    return message.author.bot
                elif filter_type_lower == "users":
                    return not message.author.bot
                elif filter_type_lower == "images":
                    return len(message.attachments) > 0
                elif filter_type_lower == "links":
                    return "http://" in message.content or "https://" in message.content
                elif filter_type_lower == "from" and filter_value:
                    # Filter by user
                    if filter_value.isdigit():
                        return message.author.id == int(filter_value)
                    else:
                        return message.author.display_name.lower() == filter_value.lower()
                elif filter_type_lower == "contains" and filter_value:
                    return filter_value.lower() in message.content.lower()
                else:
                    return True
            
            deleted = await interaction.channel.purge(limit=amount, check=check_message)
            
            # Message de confirmation
            filter_text = ""
            if filter_type:
                filter_text = f" ({filter_type}"
                if filter_value:
                    filter_text += f": {filter_value}"
                filter_text += ")"
            
            await interaction.followup.send(f"{len(deleted)} messages ont été supprimés{filter_text}.", ephemeral=True)
            
            # Log
            log_channel = discord.utils.get(interaction.guild.text_channels, name="mod-logs")
            if log_channel:
                log_embed = discord.Embed(
                    title="🧹 Purge de messages",
                    description=f"{len(deleted)} messages ont été supprimés dans {interaction.channel.mention}",
                    color=discord.Color.blue()
                )
                log_embed.add_field(name="Modérateur", value=interaction.user.mention)
                log_embed.add_field(name="Filtre", value=filter_text or "Aucun")
                await log_channel.send(embed=log_embed)
                
        except Exception as e:
            await interaction.followup.send(f"Erreur lors de la suppression des messages: {str(e)}", ephemeral=True)

    @app_commands.command(name="mute", description="Réduire un membre au silence")
    @app_commands.default_permissions(administrator=True)
    async def mute_slash(self, interaction: discord.Interaction, member: discord.Member):
        if member == interaction.user:
            await interaction.response.send_message("Vous ne pouvez pas vous mute vous-même!", ephemeral=True)
            return
                
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("Vous ne pouvez pas mute un membre ayant un rôle supérieur ou égal au vôtre!", ephemeral=True)
            return
        
        # Utiliser un modal pour la raison et la durée
        modal = TempMuteModal(member, self)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="unmute", description="Redonner la parole à un membre")
    @app_commands.default_permissions(administrator=True)
    async def unmute_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        try:
            # Vérifier si le rôle "Muted" existe
            mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
            if not mute_role:
                await interaction.response.send_message("Le rôle Muted n'existe pas!", ephemeral=True)
                return
            
            # Vérifier si le membre est mute
            if mute_role not in member.roles:
                await interaction.response.send_message(f"{member.display_name} n'est pas mute!", ephemeral=True)
                return
            
            # Retirer le rôle mute
            await member.remove_roles(mute_role, reason=reason)
            
            # Retirer des mutes temporaires si présent
            user_id = str(member.id)
            if user_id in self.automod.muted_users:
                del self.automod.muted_users[user_id]
                self.automod.save_config()
            
            # Messages style Antilles
            unmute_messages = [
                f"{member.mention} a retrouvé sa voix et peut maintenant chanter le zouk! 🎵",
                f"{member.mention} a fini sa sieste au soleil et peut à nouveau parler! 🌞",
                f"{member.mention} a fini son cocktail et peut maintenant discuter! 🍹",
                f"{member.mention} a retrouvé sa voix après avoir mangé trop de piment! 🌶️"
            ]
            
            unmute_message = random.choice(unmute_messages)
            
            # Message de confirmation
            embed = discord.Embed(
                title="🔊 Membre démute",
                description=unmute_message,
                color=discord.Color.green()
            )
            embed.add_field(name="Raison", value=reason or "Aucune raison spécifiée")
            embed.add_field(name="Modérateur", value=interaction.user.mention)
            embed.set_footer(text=f"ID: {member.id}")
            await interaction.response.send_message(embed=embed)
            
            # Log
            log_channel = discord.utils.get(interaction.guild.text_channels, name="mod-logs")
            if log_channel:
                log_embed = embed.copy()
                log_embed.add_field(name="Date", value=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                await log_channel.send(embed=log_embed)
            
            # DM à l'utilisateur
            try:
                dm_embed = discord.Embed(
                    title=f"Vous avez été démute dans {interaction.guild.name}",
                    description=f"Vous pouvez à nouveau parler dans le serveur!",
                    color=discord.Color.green()
                )
                await member.send(embed=dm_embed)
            except:
                pass
                
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission de démute ce membre!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Une erreur s'est produite: {str(e)}", ephemeral=True)

    @app_commands.command(name="warn", description="Avertir un membre")
    @app_commands.default_permissions(administrator=True)
    async def warn_slash(self, interaction: discord.Interaction, member: discord.Member):
        if member == interaction.user:
            await interaction.response.send_message("Vous ne pouvez pas vous avertir vous-même!", ephemeral=True)
            return
                
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("Vous ne pouvez pas avertir un membre ayant un rôle supérieur ou égal au vôtre!", ephemeral=True)
            return
        
        # Utiliser un modal pour la raison
        modal = WarnModal(member)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="slowmode", description="Définir le mode lent d'un canal")
    @app_commands.default_permissions(administrator=True)
    async def slowmode_slash(self, interaction: discord.Interaction, seconds: int = None):
        try:
            if seconds is None:
                await interaction.response.send_message(f"Le slowmode actuel est de {interaction.channel.slowmode_delay} secondes.")
                return
            
            if seconds < 0:
                await interaction.response.send_message("Le délai de slowmode ne peut pas être négatif!", ephemeral=True)
                return
            
            if seconds > 21600:
                await interaction.response.send_message("Le délai de slowmode ne peut pas dépasser 6 heures (21600 secondes)!", ephemeral=True)
                return
            
            await interaction.channel.edit(slowmode_delay=seconds)
            
            if seconds == 0:
                embed = discord.Embed(
                    title="⏱️ Slowmode désactivé",
                    description=f"Le slowmode a été désactivé dans {interaction.channel.mention}",
                    color=discord.Color.green()
                )
            else:
                embed = discord.Embed(
                    title="⏱️ Slowmode activé",
                    description=f"Le slowmode a été défini à {seconds} secondes dans {interaction.channel.mention}. On prend son temps sous le soleil des Antilles! 🌴",
                    color=discord.Color.blue()
                )
            
            embed.add_field(name="Modérateur", value=interaction.user.mention)
            await interaction.response.send_message(embed=embed)
            
            # Log
            log_channel = discord.utils.get(interaction.guild.text_channels, name="mod-logs")
            if log_channel:
                log_embed = embed.copy()
                log_embed.add_field(name="Date", value=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                await log_channel.send(embed=log_embed)
                
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission de modifier le slowmode de ce canal!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Une erreur s'est produite: {str(e)}", ephemeral=True)

    @app_commands.command(name="lock", description="Verrouiller un canal")
    @app_commands.default_permissions(administrator=True)
    async def lock_slash(self, interaction: discord.Interaction, channel: typing.Optional[discord.TextChannel] = None):
        channel = channel or interaction.channel
        try:
            overwrites = channel.overwrites_for(interaction.guild.default_role)
            overwrites.send_messages = False
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
            
            embed = discord.Embed(
                title="🔒 Canal verrouillé",
                description=f"{channel.mention} a été verrouillé. La plage est fermée temporairement! 🏖️",
                color=discord.Color.red()
            )
            embed.add_field(name="Modérateur", value=interaction.user.mention)
            await interaction.response.send_message(embed=embed)
            
            # Log
            log_channel = discord.utils.get(interaction.guild.text_channels, name="mod-logs")
            if log_channel and log_channel != channel:
                log_embed = embed.copy()
                log_embed.add_field(name="Date", value=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                await log_channel.send(embed=log_embed)
                
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission de verrouiller ce canal!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Une erreur s'est produite: {str(e)}", ephemeral=True)

    @app_commands.command(name="unlock", description="Déverrouiller un canal")
    @app_commands.default_permissions(administrator=True)
    async def unlock_slash(self, interaction: discord.Interaction, channel: typing.Optional[discord.TextChannel] = None):
        channel = channel or interaction.channel
        try:
            overwrites = channel.overwrites_for(interaction.guild.default_role)
            overwrites.send_messages = True
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
            
            embed = discord.Embed(
                title="🔓 Canal déverrouillé",
                description=f"{channel.mention} a été déverrouillé. La plage est à nouveau ouverte! 🏝️",
                color=discord.Color.green()
            )
            embed.add_field(name="Modérateur", value=interaction.user.mention)
            await interaction.response.send_message(embed=embed)
            
            # Log
            log_channel = discord.utils.get(interaction.guild.text_channels, name="mod-logs")
            if log_channel and log_channel != channel:
                log_embed = embed.copy()
                log_embed.add_field(name="Date", value=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                await log_channel.send(embed=log_embed)
                
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission de déverrouiller ce canal!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Une erreur s'est produite: {str(e)}", ephemeral=True)
    
    @app_commands.command(name="autopurge_user", description="Supprimer automatiquement tous les messages d'un utilisateur")
    @app_commands.default_permissions(administrator=True)
    async def autopurge_user_slash(self, interaction: discord.Interaction, member: discord.Member, enable: bool = True):
        try:
            user_id = str(member.id)
            
            if enable:
                if user_id not in self.automod.auto_purge_users:
                    self.automod.auto_purge_users.add(user_id)
                    self.automod.save_config()
                    await interaction.response.send_message(f"Auto-purge activé pour {member.mention}. Tous ses messages seront automatiquement supprimés.")
                else:
                    await interaction.response.send_message(f"L'auto-purge est déjà activé pour {member.mention}.", ephemeral=True)
            else:
                if user_id in self.automod.auto_purge_users:
                    self.automod.auto_purge_users.remove(user_id)
                    self.automod.save_config()
                    await interaction.response.send_message(f"Auto-purge désactivé pour {member.mention}.")
                else:
                    await interaction.response.send_message(f"L'auto-purge n'était pas activé pour {member.mention}.", ephemeral=True)
            
            # Log
            log_channel = discord.utils.get(interaction.guild.text_channels, name="mod-logs")
            if log_channel:
                embed = discord.Embed(
                    title=f"🧹 Auto-purge {'activé' if enable else 'désactivé'}",
                    description=f"Auto-purge pour {member.mention} a été {'activé' if enable else 'désactivé'}",
                    color=discord.Color.blue()
                )
                embed.add_field(name="Modérateur", value=interaction.user.mention)
                embed.add_field(name="Date", value=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                await log_channel.send(embed=embed)
                
        except Exception as e:
            await interaction.response.send_message(f"Une erreur s'est produite: {str(e)}", ephemeral=True)
    
    @app_commands.command(name="autopurge_channel", description="Supprimer automatiquement tous les messages d'un canal")
    @app_commands.default_permissions(administrator=True)
    async def autopurge_channel_slash(self, interaction: discord.Interaction, channel: typing.Optional[discord.TextChannel] = None, enable: bool = True):
        channel = channel or interaction.channel
        try:
            channel_id = str(channel.id)
            
            if enable:
                if channel_id not in self.automod.auto_purge_channels:
                    self.automod.auto_purge_channels.add(channel_id)
                    self.automod.save_config()
                    await interaction.response.send_message(f"Auto-purge activé pour {channel.mention}. Tous les messages y seront automatiquement supprimés.")
                else:
                    await interaction.response.send_message(f"L'auto-purge est déjà activé pour {channel.mention}.", ephemeral=True)
            else:
                if channel_id in self.automod.auto_purge_channels:
                    self.automod.auto_purge_channels.remove(channel_id)
                    self.automod.save_config()
                    await interaction.response.send_message(f"Auto-purge désactivé pour {channel.mention}.")
                else:
                    await interaction.response.send_message(f"L'auto-purge n'était pas activé pour {channel.mention}.", ephemeral=True)
            
            # Log
            log_channel = discord.utils.get(interaction.guild.text_channels, name="mod-logs")
            if log_channel and log_channel != channel:
                embed = discord.Embed(
                    title=f"🧹 Auto-purge de canal {'activé' if enable else 'désactivé'}",
                    description=f"Auto-purge pour {channel.mention} a été {'activé' if enable else 'désactivé'}",
                    color=discord.Color.blue()
                )
                embed.add_field(name="Modérateur", value=interaction.user.mention)
                embed.add_field(name="Date", value=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                await log_channel.send(embed=embed)
                
        except Exception as e:
            await interaction.response.send_message(f"Une erreur s'est produite: {str(e)}", ephemeral=True)
    
    @app_commands.command(name="addfilter", description="Ajouter un mot au filtre anti-mots")
    @app_commands.default_permissions(administrator=True)
    async def addfilter_slash(self, interaction: discord.Interaction):
        # Utiliser un modal pour le mot à filtrer
        modal = WordFilterModal(self)
        await interaction.response.send_modal(modal)
    
    @app_commands.command(name="removefilter", description="Retirer un mot du filtre anti-mots")
    @app_commands.default_permissions(administrator=True)
    async def removefilter_slash(self, interaction: discord.Interaction, word: str):
        try:
            if word.lower() not in [w.lower() for w in self.automod.word_filter]:
                await interaction.response.send_message("Ce mot n'est pas dans la liste des mots interdits.", ephemeral=True)
                return
            
            # Trouver le mot exact (avec la même casse)
            for w in self.automod.word_filter[:]:
                if w.lower() == word.lower():
                    self.automod.word_filter.remove(w)
            
            self.automod.save_config()
            
            await interaction.response.send_message(f"Mot retiré de la liste des termes interdits.", ephemeral=True)
            
            # Log
            log_channel = discord.utils.get(interaction.guild.text_channels, name="mod-logs")
            if log_channel:
                embed = discord.Embed(
                    title="⛔ Filtre de mots mis à jour",
                    description=f"Un mot a été retiré de la liste des termes interdits",
                    color=discord.Color.orange()
                )
                embed.add_field(name="Modérateur", value=interaction.user.mention)
                embed.add_field(name="Date", value=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                await log_channel.send(embed=embed)
                
        except Exception as e:
            await interaction.response.send_message(f"Une erreur s'est produite: {str(e)}", ephemeral=True)
    
    @app_commands.command(name="wordfilter", description="Voir la liste des mots filtrés")
    @app_commands.default_permissions(administrator=True)
    async def wordfilter_slash(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            
            if not self.automod.word_filter:
                await interaction.followup.send("Aucun mot n'est actuellement filtré.", ephemeral=True)
                return
            
            # Créer un message privé avec la liste
            words_list = "\n".join(self.automod.word_filter)
            
            embed = discord.Embed(
                title="⛔ Liste des mots interdits",
                description=f"Voici la liste des {len(self.automod.word_filter)} mots actuellement filtrés:",
                color=discord.Color.red()
            )
            
            # Envoyer en message éphémère
            await interaction.followup.send(embed=embed, ephemeral=True)
            await interaction.followup.send(f"```\n{words_list}\n```", ephemeral=True)
                
        except Exception as e:
            await interaction.followup.send(f"Une erreur s'est produite: {str(e)}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Moderation(bot))