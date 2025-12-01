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
import logging
import time
import copy

# Configurer le logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

class SecurityConfig:
    def __init__(self):
        self.config_path = "utils/security_config.json"
        
        # Anti-raid settings
        self.raid_protection_enabled = True
        self.raid_detection_threshold = 5  # Nombre de nouveaux membres
        self.raid_detection_timeframe = 10  # Secondes
        self.raid_mode_action = "lockdown"  # "lockdown", "captcha", "kick", "ban"
        self.raid_mode_duration = 300  # 5 minutes par défaut
        
        # Anti-spam settings
        self.spam_protection_enabled = True
        self.duplicate_message_threshold = 4  # Nombre de messages similaires
        self.duplicate_message_timeframe = 10  # Secondes
        self.mention_spam_threshold = 5  # Nombre de mentions dans un message
        self.emoji_spam_threshold = 10  # Nombre d'emojis dans un message
        self.rapid_message_threshold = 7  # Nombre de messages
        self.rapid_message_timeframe = 5  # Secondes
        
        # Anti-nuke settings
        self.nuke_protection_enabled = True
        self.channel_deletion_threshold = 3  # Nombre de canaux supprimés
        self.channel_deletion_timeframe = 10  # Secondes
        self.role_deletion_threshold = 3  # Nombre de rôles supprimés
        self.role_deletion_timeframe = 10  # Secondes
        self.mass_ban_threshold = 5  # Nombre de bans
        self.mass_ban_timeframe = 10  # Secondes
        
        # Permissions dangereuses à surveiller
        self.dangerous_permissions = [
            "administrator", "ban_members", "kick_members", 
            "manage_channels", "manage_guild", "manage_roles", "manage_webhooks"
        ]
        
        # Utilisateurs et rôles de confiance (immunisés aux mesures de sécurité)
        self.trusted_users = set()
        self.trusted_roles = set()
        self.whitelisted_invites = set()
        
        # Domaines blacklistés
        self.blacklisted_domains = set()
        
        # Paramètres de sauvegarde
        self.backup_enabled = True
        self.backup_interval = 86400  # 24 heures
        self.last_backup_time = 0
        self.backups = {}  # Stocke les sauvegardes de canaux et rôles
        
        # Système de score de confiance
        self.trust_score_enabled = True
        self.user_trust_scores = {}  # {user_id: {score: float, join_date: timestamp}}
        self.minimum_account_age = 7  # Jours
        self.suspicious_patterns = [  # Motifs pour usernames suspects
            r"discord\.gg", r"invite\.(gg|io)", r"twitch\.tv",
            r"youtube\.com", r"twitter\.com", r"instagram\.com"
        ]
        
        # Données temporaires
        self.recent_joins = deque(maxlen=50)  # Enregistre les arrivées récentes
        self.recent_channel_deletions = deque(maxlen=20)  # Suppressions de canaux récentes
        self.recent_role_deletions = deque(maxlen=20)  # Suppressions de rôles récentes
        self.recent_bans = deque(maxlen=20)  # Bans récents
        self.message_history = defaultdict(lambda: deque(maxlen=20))  # Historique des messages par utilisateur
        self.captcha_verification = {}  # {user_id: captcha_code}
        
        # État actuel de la sécurité
        self.raid_mode_active = False
        self.raid_mode_end_time = 0
        self.lockdown_channels = {}  # {channel_id: original_permissions}
        
        # Charger la configuration existante
        self.load_config()
    
    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                    
                    # Anti-raid settings
                    self.raid_protection_enabled = data.get('raid_protection_enabled', self.raid_protection_enabled)
                    self.raid_detection_threshold = data.get('raid_detection_threshold', self.raid_detection_threshold)
                    self.raid_detection_timeframe = data.get('raid_detection_timeframe', self.raid_detection_timeframe)
                    self.raid_mode_action = data.get('raid_mode_action', self.raid_mode_action)
                    self.raid_mode_duration = data.get('raid_mode_duration', self.raid_mode_duration)
                    
                    # Anti-spam settings
                    self.spam_protection_enabled = data.get('spam_protection_enabled', self.spam_protection_enabled)
                    self.duplicate_message_threshold = data.get('duplicate_message_threshold', self.duplicate_message_threshold)
                    self.duplicate_message_timeframe = data.get('duplicate_message_timeframe', self.duplicate_message_timeframe)
                    self.mention_spam_threshold = data.get('mention_spam_threshold', self.mention_spam_threshold)
                    self.emoji_spam_threshold = data.get('emoji_spam_threshold', self.emoji_spam_threshold)
                    self.rapid_message_threshold = data.get('rapid_message_threshold', self.rapid_message_threshold)
                    self.rapid_message_timeframe = data.get('rapid_message_timeframe', self.rapid_message_timeframe)
                    
                    # Anti-nuke settings
                    self.nuke_protection_enabled = data.get('nuke_protection_enabled', self.nuke_protection_enabled)
                    self.channel_deletion_threshold = data.get('channel_deletion_threshold', self.channel_deletion_threshold)
                    self.channel_deletion_timeframe = data.get('channel_deletion_timeframe', self.channel_deletion_timeframe)
                    self.role_deletion_threshold = data.get('role_deletion_threshold', self.role_deletion_threshold)
                    self.role_deletion_timeframe = data.get('role_deletion_timeframe', self.role_deletion_timeframe)
                    self.mass_ban_threshold = data.get('mass_ban_threshold', self.mass_ban_threshold)
                    self.mass_ban_timeframe = data.get('mass_ban_timeframe', self.mass_ban_timeframe)
                    
                    # Trusted users and roles
                    self.trusted_users = set(data.get('trusted_users', []))
                    self.trusted_roles = set(data.get('trusted_roles', []))
                    self.whitelisted_invites = set(data.get('whitelisted_invites', []))
                    
                    # Blacklisted domains
                    self.blacklisted_domains = set(data.get('blacklisted_domains', []))
                    
                    # Backup settings
                    self.backup_enabled = data.get('backup_enabled', self.backup_enabled)
                    self.backup_interval = data.get('backup_interval', self.backup_interval)
                    self.last_backup_time = data.get('last_backup_time', self.last_backup_time)
                    self.backups = data.get('backups', self.backups)
                    
                    # Trust scores
                    self.trust_score_enabled = data.get('trust_score_enabled', self.trust_score_enabled)
                    self.user_trust_scores = data.get('user_trust_scores', self.user_trust_scores)
                    self.minimum_account_age = data.get('minimum_account_age', self.minimum_account_age)
                    
            except Exception as e:
                logging.error(f"Erreur lors du chargement de la configuration de sécurité: {e}")
    
    def save_config(self):
        try:
            # Créer le répertoire parent s'il n'existe pas
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            
            data = {
                # Anti-raid settings
                'raid_protection_enabled': self.raid_protection_enabled,
                'raid_detection_threshold': self.raid_detection_threshold,
                'raid_detection_timeframe': self.raid_detection_timeframe,
                'raid_mode_action': self.raid_mode_action,
                'raid_mode_duration': self.raid_mode_duration,
                
                # Anti-spam settings
                'spam_protection_enabled': self.spam_protection_enabled,
                'duplicate_message_threshold': self.duplicate_message_threshold,
                'duplicate_message_timeframe': self.duplicate_message_timeframe,
                'mention_spam_threshold': self.mention_spam_threshold,
                'emoji_spam_threshold': self.emoji_spam_threshold,
                'rapid_message_threshold': self.rapid_message_threshold,
                'rapid_message_timeframe': self.rapid_message_timeframe,
                
                # Anti-nuke settings
                'nuke_protection_enabled': self.nuke_protection_enabled,
                'channel_deletion_threshold': self.channel_deletion_threshold,
                'channel_deletion_timeframe': self.channel_deletion_timeframe,
                'role_deletion_threshold': self.role_deletion_threshold,
                'role_deletion_timeframe': self.role_deletion_timeframe,
                'mass_ban_threshold': self.mass_ban_threshold,
                'mass_ban_timeframe': self.mass_ban_timeframe,
                
                # Trusted users and roles
                'trusted_users': list(self.trusted_users),
                'trusted_roles': list(self.trusted_roles),
                'whitelisted_invites': list(self.whitelisted_invites),
                
                # Blacklisted domains
                'blacklisted_domains': list(self.blacklisted_domains),
                
                # Backup settings
                'backup_enabled': self.backup_enabled,
                'backup_interval': self.backup_interval,
                'last_backup_time': self.last_backup_time,
                'backups': self.backups,
                
                # Trust scores
                'trust_score_enabled': self.trust_score_enabled,
                'user_trust_scores': self.user_trust_scores,
                'minimum_account_age': self.minimum_account_age,
            }
            
            with open(self.config_path, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logging.error(f"Erreur lors de la sauvegarde de la configuration de sécurité: {e}")

    def adjust_thresholds_for_server_size(self, member_count):
        """Ajuster automatiquement les seuils de sécurité en fonction de la taille du serveur"""
        if member_count <= 50:  # Petit serveur
            self.raid_detection_threshold = 3
            self.raid_detection_timeframe = 5
            self.channel_deletion_threshold = 2
            self.role_deletion_threshold = 2
        elif member_count <= 500:  # Serveur moyen
            self.raid_detection_threshold = 5
            self.raid_detection_timeframe = 10
            self.channel_deletion_threshold = 3
            self.role_deletion_threshold = 3
        else:  # Grand serveur
            self.raid_detection_threshold = 10
            self.raid_detection_timeframe = 15
            self.channel_deletion_threshold = 5
            self.role_deletion_threshold = 5
            
        # Sauvegarder les paramètres ajustés
        self.save_config()

# Générateur de captcha visuel via HTML
class CaptchaGenerator:
    @staticmethod
    def generate_captcha_code(length=6):
        """Générer un code captcha aléatoire alphanumérique"""
        chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
        code = ''.join(random.choice(chars) for _ in range(length))
        return code
    
    @staticmethod
    def generate_captcha_html(code):
        """Générer le HTML pour l'affichage du captcha"""
        colors = ['#FF5733', '#33FF57', '#3357FF', '#F3FF33', '#FF33F3']
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 200px;
                    background-color: #f0f0f0;
                }}
                .captcha-container {{
                    position: relative;
                    background-color: white;
                    border: 2px solid #ccc;
                    padding: 20px;
                    border-radius: 10px;
                    overflow: hidden;
                }}
                .captcha-text {{
                    font-family: monospace;
                    font-size: 36px;
                    font-weight: bold;
                    letter-spacing: 8px;
                }}
                .captcha-noise {{
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    opacity: 0.2;
                    z-index: -1;
                }}
                .noise-line {{
                    position: absolute;
                    background-color: #333;
                    height: 2px;
                    width: 80%;
                }}
                .noise-dot {{
                    position: absolute;
                    background-color: #333;
                    height: 4px;
                    width: 4px;
                    border-radius: 50%;
                }}
            </style>
        </head>
        <body>
            <div class="captcha-container">
                <div class="captcha-text">
        """
        
        # Ajouter chaque caractère avec une rotation et une couleur aléatoires
        for char in code:
            rotation = random.randint(-10, 10)
            color = random.choice(colors)
            html += f'<span style="display:inline-block; transform:rotate({rotation}deg); color:{color}">{char}</span>'
        
        # Ajouter du bruit au captcha
        html += """
                </div>
                <div class="captcha-noise">
        """
        
        for i in range(10):
            top = random.randint(0, 100)
            left = random.randint(0, 100)
            transform = f"rotate({random.randint(0, 180)}deg)"
            html += f'<div class="noise-line" style="top:{top}%; left:{left}%; transform:{transform}"></div>'
        
        for i in range(50):
            top = random.randint(0, 100)
            left = random.randint(0, 100)
            html += f'<div class="noise-dot" style="top:{top}%; left:{left}%"></div>'
        
        html += """
                </div>
            </div>
        </body>
        </html>
        """
        return html

# Modal pour la configuration des seuils de sécurité
class SecurityThresholdModal(discord.ui.Modal, title="Configuration de Sécurité"):
    # Anti-raid settings
    raid_threshold = discord.ui.TextInput(
        label="Seuil de détection de raid (membres)",
        placeholder="5",
        required=True
    )
    
    raid_timeframe = discord.ui.TextInput(
        label="Période de détection de raid (secondes)",
        placeholder="10",
        required=True
    )
    
    # Anti-nuke settings
    channel_threshold = discord.ui.TextInput(
        label="Seuil de suppression de salons",
        placeholder="3",
        required=True
    )
    
    role_threshold = discord.ui.TextInput(
        label="Seuil de suppression de rôles",
        placeholder="3",
        required=True
    )
    
    spam_threshold = discord.ui.TextInput(
        label="Seuil de messages rapides",
        placeholder="7",
        required=True
    )
    
    def __init__(self, cog):
        super().__init__()
        self.cog = cog
        
        # Pré-remplir les valeurs actuelles
        self.raid_threshold.default = str(self.cog.security.raid_detection_threshold)
        self.raid_timeframe.default = str(self.cog.security.raid_detection_timeframe)
        self.channel_threshold.default = str(self.cog.security.channel_deletion_threshold)
        self.role_threshold.default = str(self.cog.security.role_deletion_threshold)
        self.spam_threshold.default = str(self.cog.security.rapid_message_threshold)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Valider et mettre à jour les paramètres
            raid_threshold = int(self.raid_threshold.value)
            raid_timeframe = int(self.raid_timeframe.value)
            channel_threshold = int(self.channel_threshold.value)
            role_threshold = int(self.role_threshold.value)
            spam_threshold = int(self.spam_threshold.value)
            
            if raid_threshold <= 0 or raid_timeframe <= 0 or channel_threshold <= 0 or role_threshold <= 0 or spam_threshold <= 0:
                await interaction.response.send_message("Tous les seuils doivent être des nombres positifs.", ephemeral=True)
                return
            
            # Mettre à jour la configuration
            self.cog.security.raid_detection_threshold = raid_threshold
            self.cog.security.raid_detection_timeframe = raid_timeframe
            self.cog.security.channel_deletion_threshold = channel_threshold
            self.cog.security.role_deletion_threshold = role_threshold
            self.cog.security.rapid_message_threshold = spam_threshold
            
            # Sauvegarder la configuration
            self.cog.security.save_config()
            
            # Message de confirmation
            embed = discord.Embed(
                title="✅ Configuration de sécurité mise à jour",
                description="Les seuils de sécurité ont été mis à jour avec succès.",
                color=discord.Color.green()
            )
            embed.add_field(name="Seuil de raid", value=f"{raid_threshold} membres en {raid_timeframe}s")
            embed.add_field(name="Seuil de suppression de salons", value=str(channel_threshold))
            embed.add_field(name="Seuil de suppression de rôles", value=str(role_threshold))
            embed.add_field(name="Seuil de spam", value=f"{spam_threshold} messages")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
            # Log les changements
            await self.cog.log_security_action(
                interaction.guild,
                f"Configuration de sécurité mise à jour par {interaction.user.mention}",
                interaction.user,
                discord.Color.blue()
            )
            
        except ValueError:
            await interaction.response.send_message("Veuillez entrer des valeurs numériques valides pour tous les champs.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Une erreur s'est produite: {str(e)}", ephemeral=True)

# Modal pour l'ajout de domaines blacklistés
class BlacklistDomainModal(discord.ui.Modal, title="Ajouter un domaine à la liste noire"):
    domain = discord.ui.TextInput(
        label="Domaine à blacklister",
        placeholder="exemple.com",
        required=True
    )
    
    reason = discord.ui.TextInput(
        label="Raison du blacklist",
        placeholder="Site malveillant, phishing, etc.",
        required=True,
        style=discord.TextStyle.paragraph
    )
    
    def __init__(self, cog):
        super().__init__()
        self.cog = cog
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            domain_value = self.domain.value.lower()
            
            # Vérifier que c'est un domaine valide
            if not re.match(r'^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$', domain_value):
                await interaction.response.send_message("Format de domaine invalide. Veuillez entrer un nom de domaine valide (ex: exemple.com).", ephemeral=True)
                return
            
            if domain_value in self.cog.security.blacklisted_domains:
                await interaction.response.send_message("Ce domaine est déjà dans la liste noire.", ephemeral=True)
                return
            
            # Ajouter le domaine à la liste noire
            self.cog.security.blacklisted_domains.add(domain_value)
            self.cog.security.save_config()
            
            # Message de confirmation
            await interaction.response.send_message(f"Domaine `{domain_value}` ajouté à la liste noire pour la raison: {self.reason.value}", ephemeral=True)
            
            # Log l'action
            await self.cog.log_security_action(
                interaction.guild,
                f"Domaine ajouté à la liste noire",
                interaction.user,
                discord.Color.red(),
                fields=[
                    {"name": "Domaine", "value": domain_value},
                    {"name": "Raison", "value": self.reason.value}
                ]
            )
                
        except Exception as e:
            await interaction.response.send_message(f"Une erreur s'est produite: {str(e)}", ephemeral=True)

# Vue pour les boutons de gestion du mode raid
class RaidModeView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
    
    @discord.ui.button(label="Activer mode raid", style=discord.ButtonStyle.danger, custom_id="enable_raid_mode")
    async def enable_raid_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.cog.security.raid_mode_active:
            await interaction.response.send_message("Le mode raid est déjà activé!", ephemeral=True)
            return
        
        await interaction.response.defer()
        await self.cog.activate_raid_mode(interaction.guild, "Activation manuelle", interaction.user)
        
        embed = discord.Embed(
            title="🛡️ Mode raid activé",
            description=f"Mode raid activé manuellement par {interaction.user.mention}",
            color=discord.Color.red()
        )
        duration_text = self.cog.format_time_duration(self.cog.security.raid_mode_duration)
        embed.add_field(name="Durée", value=f"Le mode raid sera désactivé automatiquement dans {duration_text}")
        embed.add_field(name="Action", value=self.cog.get_raid_mode_action_description())
        
        await interaction.followup.send(embed=embed)
    
    @discord.ui.button(label="Désactiver mode raid", style=discord.ButtonStyle.success, custom_id="disable_raid_mode")
    async def disable_raid_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.security.raid_mode_active:
            await interaction.response.send_message("Le mode raid n'est pas activé!", ephemeral=True)
            return
        
        await interaction.response.defer()
        await self.cog.deactivate_raid_mode(interaction.guild, "Désactivation manuelle", interaction.user)
        
        embed = discord.Embed(
            title="✅ Mode raid désactivé",
            description=f"Mode raid désactivé manuellement par {interaction.user.mention}",
            color=discord.Color.green()
        )
        
        await interaction.followup.send(embed=embed)
    
    @discord.ui.button(label="Voir statut", style=discord.ButtonStyle.primary, custom_id="raid_mode_status")
    async def raid_mode_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.cog.security.raid_mode_active:
            time_left = self.cog.security.raid_mode_end_time - time.time()
            if time_left > 0:
                time_left_text = self.cog.format_time_duration(time_left)
                status = f"🔴 **ACTIF** - Se désactive dans {time_left_text}"
            else:
                status = "🔴 **ACTIF** - Désactivation imminente"
        else:
            status = "🟢 **INACTIF**"
        
        embed = discord.Embed(
            title="🛡️ Statut du mode raid",
            description=status,
            color=discord.Color.red() if self.cog.security.raid_mode_active else discord.Color.green()
        )
        
        if self.cog.security.raid_mode_active:
            embed.add_field(name="Action", value=self.cog.get_raid_mode_action_description())
            
            # Statistiques sur les arrivées récentes
            recent_join_count = len(self.cog.security.recent_joins)
            if recent_join_count > 0:
                embed.add_field(name="Arrivées récentes", value=f"{recent_join_count} membres")
        
        # Paramètres de détection
        embed.add_field(
            name="Paramètres de détection",
            value=f"{self.cog.security.raid_detection_threshold} membres en {self.cog.security.raid_detection_timeframe}s"
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

# Vue pour la configuration de sécurité
class SecurityConfigView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.cog = cog
    
    @discord.ui.button(label="Ajuster les seuils", style=discord.ButtonStyle.primary, row=0)
    async def thresholds(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SecurityThresholdModal(self.cog)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Domaines blacklistés", style=discord.ButtonStyle.danger, row=0)
    async def blacklist(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Choisissez une action pour la liste noire des domaines:",
            view=BlacklistManagementView(self.cog),
            ephemeral=True
        )
    
    @discord.ui.button(label="Utilisateurs de confiance", style=discord.ButtonStyle.success, row=0)
    async def trusted_users(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Gestion des utilisateurs de confiance:",
            view=TrustedUsersView(self.cog),
            ephemeral=True
        )
    
    @discord.ui.button(label="Sauvegarde serveur", style=discord.ButtonStyle.secondary, row=1)
    async def backup(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        # Créer une nouvelle sauvegarde
        backup_result = await self.cog.create_server_backup(interaction.guild)
        
        if backup_result:
            embed = discord.Embed(
                title="✅ Sauvegarde effectuée",
                description="Une sauvegarde complète du serveur a été créée.",
                color=discord.Color.green()
            )
            
            # Statistiques sur la sauvegarde
            channels_count = len(backup_result.get('channels', []))
            roles_count = len(backup_result.get('roles', []))
            
            embed.add_field(name="Salons sauvegardés", value=str(channels_count))
            embed.add_field(name="Rôles sauvegardés", value=str(roles_count))
            embed.add_field(name="Date", value=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
            
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send("❌ Erreur lors de la création de la sauvegarde.", ephemeral=True)
    
    @discord.ui.button(label="Voir les logs", style=discord.ButtonStyle.secondary, row=1)
    async def view_logs(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Générer un résumé des événements de sécurité récents
        embed = discord.Embed(
            title="📊 Résumé des événements de sécurité récents",
            description="Voici un aperçu des actions de sécurité récentes:",
            color=discord.Color.blue()
        )
        
        # Récupérer le canal de logs de sécurité
        category = interaction.guild.get_channel(1228669526879633408)
        log_channel = None
        
        if category and isinstance(category, discord.CategoryChannel):
            log_channel = discord.utils.get(category.text_channels, name="security-logs")
        
        if not log_channel:
            log_channel = discord.utils.get(interaction.guild.text_channels, name="security-logs")
        
        if log_channel:
            try:
                # Récupérer les 10 messages les plus récents du canal de logs
                messages = []
                async for message in log_channel.history(limit=10):
                    messages.append(message)
                
                if messages:
                    for message in messages:
                        if message.embeds:
                            log_embed = message.embeds[0]
                            embed.add_field(
                                name=f"{log_embed.title or 'Log'} - {message.created_at.strftime('%d/%m %H:%M')}",
                                value=log_embed.description[:100] + ("..." if len(log_embed.description or "") > 100 else ""),
                                inline=False
                            )
                else:
                    embed.add_field(name="Aucun log récent", value="Aucun événement de sécurité récent n'a été enregistré.")
            
                embed.set_footer(text=f"Pour voir tous les logs, consultez le canal {log_channel.mention}")
                await interaction.response.send_message(embed=embed, ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"Erreur lors de la récupération des logs: {str(e)}", ephemeral=True)
        else:
            await interaction.response.send_message("Canal de logs de sécurité introuvable. Vérifiez que le canal #security-logs existe.", ephemeral=True)
    
    @discord.ui.button(label="Activer/Désactiver protections", style=discord.ButtonStyle.primary, row=1)
    async def toggle_protections(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Activer ou désactiver les différentes protections:",
            view=ToggleProtectionsView(self.cog),
            ephemeral=True
        )

# Vue pour la gestion des domaines blacklistés
class BlacklistManagementView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=180)  # 3 minutes timeout
        self.cog = cog
    
    @discord.ui.button(label="Ajouter un domaine", style=discord.ButtonStyle.danger)
    async def add_domain(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = BlacklistDomainModal(self.cog)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Voir la liste", style=discord.ButtonStyle.secondary)
    async def view_domains(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        if not self.cog.security.blacklisted_domains:
            await interaction.followup.send("Aucun domaine n'est actuellement sur la liste noire.", ephemeral=True)
            return
        
        # Créer un embed avec les domaines blacklistés
        embed = discord.Embed(
            title="⛔ Domaines sur liste noire",
            description=f"Il y a actuellement {len(self.cog.security.blacklisted_domains)} domaines sur la liste noire:",
            color=discord.Color.red()
        )
        
        domains_text = "\n".join(sorted(self.cog.security.blacklisted_domains))
        
        # Découper en morceaux si nécessaire
        if len(domains_text) > 1024:
            chunks = [domains_text[i:i+1024] for i in range(0, len(domains_text), 1024)]
            for i, chunk in enumerate(chunks):
                embed.add_field(name=f"Domaines (partie {i+1})", value=f"```\n{chunk}\n```", inline=False)
        else:
            embed.add_field(name="Domaines", value=f"```\n{domains_text}\n```", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="Supprimer un domaine", style=discord.ButtonStyle.primary)
    async def remove_domain(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.security.blacklisted_domains:
            await interaction.response.send_message("Aucun domaine n'est actuellement sur la liste noire.", ephemeral=True)
            return
        
        # Créer un menu de sélection avec les domaines
        await interaction.response.send_message(
            "Sélectionnez le domaine à retirer de la liste noire:",
            view=BlacklistRemoveView(self.cog),
            ephemeral=True
        )

# Vue pour la sélection de domaines à supprimer
class BlacklistRemoveView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=60)
        self.cog = cog
        
        # Ajouter les domaines au menu de sélection
        domains = sorted(list(self.cog.security.blacklisted_domains))
        
        # Limiter à 25 (limite Discord)
        if len(domains) > 25:
            domains = domains[:25]
        
        options = [discord.SelectOption(label=domain, value=domain) for domain in domains]
        
        if options:
            self.add_item(BlacklistSelect(options, cog))
        else:
            # S'il n'y a aucun domaine, ajouter un placeholder
            options = [discord.SelectOption(label="Aucun domaine disponible", value="none")]
            self.add_item(BlacklistSelect(options, cog))

class BlacklistSelect(discord.ui.Select):
    def __init__(self, options, cog):
        super().__init__(placeholder="Choisir un domaine à retirer...", options=options)
        self.cog = cog
    
    async def callback(self, interaction: discord.Interaction):
        domain = self.values[0]
        
        if domain == "none":
            await interaction.response.send_message("Aucun domaine à retirer.", ephemeral=True)
            return
        
        # Retirer le domaine de la liste noire
        if domain in self.cog.security.blacklisted_domains:
            self.cog.security.blacklisted_domains.remove(domain)
            self.cog.security.save_config()
            
            await interaction.response.send_message(f"Domaine `{domain}` retiré de la liste noire!", ephemeral=True)
            
            # Log l'action
            await self.cog.log_security_action(
                interaction.guild,
                f"Domaine retiré de la liste noire",
                interaction.user,
                discord.Color.green(),
                fields=[{"name": "Domaine", "value": domain}]
            )
        else:
            await interaction.response.send_message("Ce domaine n'est plus sur la liste noire.", ephemeral=True)

# Vue pour la gestion des utilisateurs de confiance
class TrustedUsersView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=180)
        self.cog = cog
    
    @discord.ui.button(label="Ajouter un utilisateur", style=discord.ButtonStyle.success)
    async def add_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = TrustedUserModal(self.cog)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Voir la liste", style=discord.ButtonStyle.secondary)
    async def view_users(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        if not self.cog.security.trusted_users:
            await interaction.followup.send("Aucun utilisateur n'est actuellement dans la liste de confiance.", ephemeral=True)
            return
        
        # Créer un embed avec les utilisateurs de confiance
        embed = discord.Embed(
            title="✅ Utilisateurs de confiance",
            description=f"Il y a actuellement {len(self.cog.security.trusted_users)} utilisateurs de confiance:",
            color=discord.Color.green()
        )
        
        # Obtenir les objets utilisateur à partir des IDs
        trusted_user_mentions = []
        for user_id in self.cog.security.trusted_users:
            user = interaction.guild.get_member(int(user_id))
            if user:
                trusted_user_mentions.append(f"{user.mention} ({user.name}, ID: {user.id})")
            else:
                trusted_user_mentions.append(f"ID: {user_id} (utilisateur non trouvé)")
        
        users_text = "\n".join(trusted_user_mentions)
        
        # Découper en morceaux si nécessaire
        if len(users_text) > 1024:
            chunks = [users_text[i:i+1024] for i in range(0, len(users_text), 1024)]
            for i, chunk in enumerate(chunks):
                embed.add_field(name=f"Utilisateurs (partie {i+1})", value=chunk, inline=False)
        else:
            embed.add_field(name="Utilisateurs", value=users_text, inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="Supprimer un utilisateur", style=discord.ButtonStyle.danger)
    async def remove_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.security.trusted_users:
            await interaction.response.send_message("Aucun utilisateur n'est actuellement dans la liste de confiance.", ephemeral=True)
            return
        
        # Créer une vue avec la liste des utilisateurs de confiance
        await interaction.response.send_message(
            "Sélectionnez l'utilisateur à retirer de la liste de confiance:",
            view=TrustedUserRemoveView(self.cog, interaction.guild),
            ephemeral=True
        )

# Modal pour ajouter un utilisateur de confiance
class TrustedUserModal(discord.ui.Modal, title="Ajouter un utilisateur de confiance"):
    user_id = discord.ui.TextInput(
        label="ID de l'utilisateur",
        placeholder="123456789012345678",
        required=True
    )
    
    reason = discord.ui.TextInput(
        label="Raison",
        placeholder="Pourquoi cet utilisateur est de confiance",
        required=True,
        style=discord.TextStyle.paragraph
    )
    
    def __init__(self, cog):
        super().__init__()
        self.cog = cog
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_id = self.user_id.value.strip()
            
            # Vérifier si c'est un ID d'utilisateur valide
            if not user_id.isdigit():
                await interaction.response.send_message("L'ID d'utilisateur doit être un nombre.", ephemeral=True)
                return
            
            user_id_int = int(user_id)
            
            # Vérifier si l'utilisateur existe dans le serveur
            user = interaction.guild.get_member(user_id_int)
            if not user:
                await interaction.response.send_message("Cet utilisateur n'a pas été trouvé sur le serveur.", ephemeral=True)
                return
            
            # Ajouter l'utilisateur à la liste des utilisateurs de confiance
            if user_id in self.cog.security.trusted_users:
                await interaction.response.send_message(f"{user.mention} est déjà dans la liste des utilisateurs de confiance.", ephemeral=True)
                return
            
            self.cog.security.trusted_users.add(user_id)
            self.cog.security.save_config()
            
            await interaction.response.send_message(f"{user.mention} a été ajouté à la liste des utilisateurs de confiance pour la raison: {self.reason.value}", ephemeral=True)
            
            # Log l'action
            await self.cog.log_security_action(
                interaction.guild,
                f"Utilisateur ajouté à la liste de confiance",
                interaction.user,
                discord.Color.green(),
                fields=[
                    {"name": "Utilisateur", "value": f"{user.mention} ({user.name})"},
                    {"name": "Raison", "value": self.reason.value}
                ]
            )
                
        except Exception as e:
            await interaction.response.send_message(f"Une erreur s'est produite: {str(e)}", ephemeral=True)

# Vue pour la sélection d'utilisateurs à supprimer
class TrustedUserRemoveView(discord.ui.View):
    def __init__(self, cog, guild):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild = guild
        
        # Ajouter les utilisateurs au menu de sélection
        options = []
        for user_id in self.cog.security.trusted_users:
            user = guild.get_member(int(user_id))
            if user:
                options.append(discord.SelectOption(
                    label=f"{user.name}",
                    value=user_id,
                    description=f"ID: {user_id}"
                ))
            else:
                options.append(discord.SelectOption(
                    label=f"Utilisateur inconnu",
                    value=user_id,
                    description=f"ID: {user_id}"
                ))
        
        # Limiter à 25 (limite Discord)
        if len(options) > 25:
            options = options[:25]
        
        if options:
            self.add_item(TrustedUserSelect(options, cog))
        else:
            # S'il n'y a aucun utilisateur, ajouter un placeholder
            options = [discord.SelectOption(label="Aucun utilisateur disponible", value="none")]
            self.add_item(TrustedUserSelect(options, cog))

class TrustedUserSelect(discord.ui.Select):
    def __init__(self, options, cog):
        super().__init__(placeholder="Choisir un utilisateur à retirer...", options=options)
        self.cog = cog
    
    async def callback(self, interaction: discord.Interaction):
        user_id = self.values[0]
        
        if user_id == "none":
            await interaction.response.send_message("Aucun utilisateur à retirer.", ephemeral=True)
            return
        
        # Retirer l'utilisateur de la liste des utilisateurs de confiance
        if user_id in self.cog.security.trusted_users:
            self.cog.security.trusted_users.remove(user_id)
            self.cog.security.save_config()
            
            # Essayer d'obtenir l'objet utilisateur pour un message plus sympa
            user = interaction.guild.get_member(int(user_id))
            if user:
                user_text = f"{user.mention} ({user.name})"
            else:
                user_text = f"Utilisateur ID: {user_id}"
            
            await interaction.response.send_message(f"{user_text} retiré de la liste des utilisateurs de confiance!", ephemeral=True)
            
            # Log l'action
            await self.cog.log_security_action(
                interaction.guild,
                f"Utilisateur retiré de la liste de confiance",
                interaction.user,
                discord.Color.orange(),
                fields=[{"name": "Utilisateur", "value": user_text}]
            )
        else:
            await interaction.response.send_message("Cet utilisateur n'est plus sur la liste de confiance.", ephemeral=True)

# Vue pour activer/désactiver les protections
class ToggleProtectionsView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=180)
        self.cog = cog
        
        # Mettre à jour les labels des boutons en fonction de l'état actuel
        self.raid_protection.label = f"Protection anti-raid: {'ON' if self.cog.security.raid_protection_enabled else 'OFF'}"
        self.spam_protection.label = f"Protection anti-spam: {'ON' if self.cog.security.spam_protection_enabled else 'OFF'}"
        self.nuke_protection.label = f"Protection anti-nuke: {'ON' if self.cog.security.nuke_protection_enabled else 'OFF'}"
        self.trust_score.label = f"Système de confiance: {'ON' if self.cog.security.trust_score_enabled else 'OFF'}"
        
        # Mettre à jour les styles des boutons
        self.raid_protection.style = discord.ButtonStyle.green if self.cog.security.raid_protection_enabled else discord.ButtonStyle.gray
        self.spam_protection.style = discord.ButtonStyle.green if self.cog.security.spam_protection_enabled else discord.ButtonStyle.gray
        self.nuke_protection.style = discord.ButtonStyle.green if self.cog.security.nuke_protection_enabled else discord.ButtonStyle.gray
        self.trust_score.style = discord.ButtonStyle.green if self.cog.security.trust_score_enabled else discord.ButtonStyle.gray
    
    @discord.ui.button(label="Protection anti-raid", row=0)
    async def raid_protection(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Basculer la protection
        self.cog.security.raid_protection_enabled = not self.cog.security.raid_protection_enabled
        self.cog.security.save_config()
        
        # Mettre à jour le bouton
        button.label = f"Protection anti-raid: {'ON' if self.cog.security.raid_protection_enabled else 'OFF'}"
        button.style = discord.ButtonStyle.green if self.cog.security.raid_protection_enabled else discord.ButtonStyle.gray
        
        await interaction.response.edit_message(view=self)
        
        # Log le changement
        await self.cog.log_security_action(
            interaction.guild,
            f"Protection anti-raid {'activée' if self.cog.security.raid_protection_enabled else 'désactivée'}",
            interaction.user,
            discord.Color.blue()
        )
    
    @discord.ui.button(label="Protection anti-spam", row=0)
    async def spam_protection(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Basculer la protection
        self.cog.security.spam_protection_enabled = not self.cog.security.spam_protection_enabled
        self.cog.security.save_config()
        
        # Mettre à jour le bouton
        button.label = f"Protection anti-spam: {'ON' if self.cog.security.spam_protection_enabled else 'OFF'}"
        button.style = discord.ButtonStyle.green if self.cog.security.spam_protection_enabled else discord.ButtonStyle.gray
        
        await interaction.response.edit_message(view=self)
        
        # Log le changement
        await self.cog.log_security_action(
            interaction.guild,
            f"Protection anti-spam {'activée' if self.cog.security.spam_protection_enabled else 'désactivée'}",
            interaction.user,
            discord.Color.blue()
        )
    
    @discord.ui.button(label="Protection anti-nuke", row=1)
    async def nuke_protection(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Basculer la protection
        self.cog.security.nuke_protection_enabled = not self.cog.security.nuke_protection_enabled
        self.cog.security.save_config()
        
        # Mettre à jour le bouton
        button.label = f"Protection anti-nuke: {'ON' if self.cog.security.nuke_protection_enabled else 'OFF'}"
        button.style = discord.ButtonStyle.green if self.cog.security.nuke_protection_enabled else discord.ButtonStyle.gray
        
        await interaction.response.edit_message(view=self)
        
        # Log le changement
        await self.cog.log_security_action(
            interaction.guild,
            f"Protection anti-nuke {'activée' if self.cog.security.nuke_protection_enabled else 'désactivée'}",
            interaction.user,
            discord.Color.blue()
        )
    
    @discord.ui.button(label="Système de confiance", row=1)
    async def trust_score(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Basculer la protection
        self.cog.security.trust_score_enabled = not self.cog.security.trust_score_enabled
        self.cog.security.save_config()
        
        # Mettre à jour le bouton
        button.label = f"Système de confiance: {'ON' if self.cog.security.trust_score_enabled else 'OFF'}"
        button.style = discord.ButtonStyle.green if self.cog.security.trust_score_enabled else discord.ButtonStyle.gray
        
        await interaction.response.edit_message(view=self)
        
        # Log le changement
        await self.cog.log_security_action(
            interaction.guild,
            f"Système de confiance {'activé' if self.cog.security.trust_score_enabled else 'désactivé'}",
            interaction.user,
            discord.Color.blue()
        )

# Class pour le test du captcha
class CaptchaTestView(discord.ui.View):
    def __init__(self, code):
        super().__init__(timeout=300)  # 5 minutes
        self.code = code
    
    @discord.ui.button(label="Vérifier le code", style=discord.ButtonStyle.primary)
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Créer un modal pour entrer le code
        class CaptchaModal(discord.ui.Modal, title="Vérification Captcha"):
            code_input = discord.ui.TextInput(
                label="Code Captcha",
                placeholder="Entrez le code affiché ci-dessus",
                required=True
            )
            
            def __init__(self, code):
                super().__init__()
                self.code = code
            
            async def on_submit(self, modal_interaction: discord.Interaction):
                if self.code_input.value == self.code:
                    await modal_interaction.response.send_message("✅ Code correct! Le membre aurait été vérifié.", ephemeral=True)
                else:
                    await modal_interaction.response.send_message("❌ Code incorrect! Le membre devrait réessayer.", ephemeral=True)
        
        await interaction.response.send_modal(CaptchaModal(self.code))

# Classe principale du cog de sécurité
class SecuritySystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.security = SecurityConfig()
        
        # Démarrer les tâches de fond
        self.raid_check_task = self.bot.loop.create_task(self.check_raid_mode())
        self.backup_task = self.bot.loop.create_task(self.automatic_backup())
        
        # Vues persistantes
        self.raid_mode_view = RaidModeView(self)
        
        # Cache pour les états de permission précédents avant verrouillage
        self.channel_perms_cache = {}
        
        # Cooldown pour les invitations
        self.invite_cooldowns = commands.CooldownMapping.from_cooldown(2, 60, commands.BucketType.member)
        
        # Détection pour les membres rejoignant avec des noms similaires
        self.similar_names_detector = defaultdict(list)
        
        # Stockage des compteurs de spam
        self.spam_counts = {}
    
    def cog_unload(self):
        # Annuler les tâches de fond quand le cog est déchargé
        self.raid_check_task.cancel()
        self.backup_task.cancel()
    
    # Tâche de fond pour vérifier si le mode raid doit être désactivé
    async def check_raid_mode(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                if self.security.raid_mode_active:
                    if time.time() >= self.security.raid_mode_end_time:
                        # Trouver le serveur où le mode raid est actif
                        for guild in self.bot.guilds:
                            await self.deactivate_raid_mode(guild, "Timeout automatique", None)
                            break
            except Exception as e:
                logging.error(f"Erreur dans la tâche de vérification du mode raid: {e}")
            
            await asyncio.sleep(30)  # Vérifier toutes les 30 secondes
    
    # Tâche de fond pour les sauvegardes automatiques
    async def automatic_backup(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                if self.security.backup_enabled:
                    current_time = time.time()
                    if current_time - self.security.last_backup_time >= self.security.backup_interval:
                        for guild in self.bot.guilds:
                            await self.create_server_backup(guild)
                            break
            except Exception as e:
                logging.error(f"Erreur dans la tâche de sauvegarde automatique: {e}")
            
            await asyncio.sleep(3600)  # Vérifier toutes les heures
    
    # Événements
    @commands.Cog.listener()
    async def on_ready(self):
        # Enregistrer les vues persistantes
        self.bot.add_view(self.raid_mode_view)
        
        # Ajuster les seuils en fonction de la taille du serveur
        for guild in self.bot.guilds:
            self.security.adjust_thresholds_for_server_size(guild.member_count)
            
            # Créer le canal security-logs s'il n'existe pas
            try:
                # D'abord, chercher dans la catégorie spécifiée
                category = guild.get_channel(1228669526879633408)
                security_logs = None
                
                if category and isinstance(category, discord.CategoryChannel):
                    security_logs = discord.utils.get(category.text_channels, name="security-logs")
                
                # Si pas trouvé, chercher dans tout le serveur
                if not security_logs:
                    security_logs = discord.utils.get(guild.text_channels, name="security-logs")
                
                # Si toujours pas trouvé, créer le canal
                if not security_logs:
                    # Configurer les permissions pour le canal
                    overwrites = {
                        guild.default_role: discord.PermissionOverwrite(read_messages=False),
                        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True, attach_files=True)
                    }
                    
                    # Essayer de trouver les rôles admin ou mod pour leur donner accès
                    for role in guild.roles:
                        if role.permissions.administrator or role.permissions.manage_guild or "mod" in role.name.lower() or "admin" in role.name.lower():
                            overwrites[role] = discord.PermissionOverwrite(read_messages=True)
                    
                    # Créer le canal dans la catégorie spécifiée si elle existe
                    if category and isinstance(category, discord.CategoryChannel):
                        await guild.create_text_channel(
                            "security-logs",
                            overwrites=overwrites,
                            category=category,
                            reason="Canal de logs de sécurité pour le système de sécurité du serveur",
                            topic="Logs d'actions et alertes de sécurité du serveur"
                        )
                    else:
                        await guild.create_text_channel(
                            "security-logs",
                            overwrites=overwrites,
                            reason="Canal de logs de sécurité pour le système de sécurité du serveur",
                            topic="Logs d'actions et alertes de sécurité du serveur"
                        )
                    
                    logging.info(f"Canal security-logs créé dans {guild.name}")
            except discord.Forbidden:
                logging.error(f"Permissions manquantes pour créer le canal security-logs dans {guild.name}")
            except Exception as e:
                logging.error(f"Erreur lors de la création du canal security-logs dans {guild.name}: {e}")
        
        logging.info("Système de sécurité initialisé")
    
    @commands.Cog.listener()
    async def on_member_join(self, member):
        # Ignorer si le membre est un bot
        if member.bot:
            return
        
        # Enregistrer l'heure d'arrivée pour la détection anti-raid
        timestamp = time.time()
        self.security.recent_joins.append((member.id, timestamp))
        
        # Détection anti-raid
        if self.security.raid_protection_enabled and not self.security.raid_mode_active:
            # Compter les arrivées récentes dans la période seuil
            recent_count = sum(1 for _, t in self.security.recent_joins if timestamp - t <= self.security.raid_detection_timeframe)
            
            if recent_count >= self.security.raid_detection_threshold:
                await self.activate_raid_mode(member.guild, f"Détection de raid: {recent_count} nouveaux membres en {self.security.raid_detection_timeframe}s", None)
        
        # Appliquer l'action du mode raid au nouveau membre si actif
        if self.security.raid_mode_active:
            await self.apply_raid_mode_action(member)
        
        # Vérifier les noms d'utilisateurs suspicieusement similaires
        similar_names = self.detect_similar_usernames(member)
        if similar_names and len(similar_names) >= 3:  # Si 3+ utilisateurs ont des noms très similaires
            await self.log_security_event(
                member.guild,
                "⚠️ Détection de noms similaires",
                discord.Color.gold(),
                f"Plusieurs membres avec des noms similaires ont rejoint le serveur. Possible tentative de raid.",
                member
            )
            
            if not self.security.raid_mode_active:
                # Activer le mode raid s'il n'est pas déjà actif
                await self.activate_raid_mode(member.guild, f"Détection de noms similaires: {len(similar_names) + 1} membres", None)
        
        # Calculer et mettre à jour le score de confiance pour le nouveau membre
        try:
            await self.calculate_user_trust_score(member)
        except Exception as e:
            logging.error(f"Erreur lors du calcul du score de confiance: {e}")
        
        # Vérifier l'âge du compte si minimum défini
        if self.security.minimum_account_age > 0:
            try:
                # Utiliser datetime.datetime.now(datetime.timezone.utc) pour obtenir une date aware
                account_age_days = (datetime.datetime.now(datetime.timezone.utc) - member.created_at).days
                if account_age_days < self.security.minimum_account_age:
                    await self.log_security_event(
                        member.guild,
                        "⚠️ Compte récent",
                        discord.Color.gold(),
                        f"Un membre avec un compte récent ({account_age_days} jours) a rejoint le serveur.",
                        member
                    )
            except Exception as e:
                logging.error(f"Erreur lors de la vérification de l'âge du compte: {e}")
    
    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignorer les messages du bot, DMs ou autres bots
        if message.author.bot or not message.guild:
            return
        
        # Ignorer les utilisateurs de confiance
        if str(message.author.id) in self.security.trusted_users:
            return
        
        # Ignorer les utilisateurs avec des rôles de confiance
        if any(str(role.id) in self.security.trusted_roles for role in message.author.roles):
            return
        
        # Vérifications anti-spam
        if self.security.spam_protection_enabled:
            # Stocker le message dans l'historique de l'utilisateur
            user_id = message.author.id
            self.security.message_history[user_id].append((message.content, time.time()))
            
            # Vérifier le spam de messages (messages rapides)
            if len(self.security.message_history[user_id]) >= self.security.rapid_message_threshold:
                oldest_allowed = time.time() - self.security.rapid_message_timeframe
                recent_messages = [msg for msg, t in self.security.message_history[user_id] if t >= oldest_allowed]
                
                if len(recent_messages) >= self.security.rapid_message_threshold:
                    await self.handle_spam_detection(message, "messages rapides", recent_messages)
                    return
            
            # Vérifier les messages dupliqués
            if len(self.security.message_history[user_id]) >= 2:
                # Obtenir les messages les plus récents
                recent_messages = list(self.security.message_history[user_id])[-self.security.duplicate_message_threshold:]
                recent_contents = [msg for msg, _ in recent_messages]
                
                # Vérifier si le message le plus récent apparaît plusieurs fois
                if message.content and message.content in recent_contents and recent_contents.count(message.content) >= self.security.duplicate_message_threshold - 1:
                    await self.handle_spam_detection(message, "messages dupliqués", recent_contents)
                    return
            
            # Vérifier le spam de mentions
            if len(message.mentions) + len(message.role_mentions) >= self.security.mention_spam_threshold:
                await self.handle_spam_detection(message, "spam de mentions", [message.content])
                return
            
            # Vérifier le spam d'emojis
            emoji_count = len(re.findall(r'<a?:\w+:\d+>', message.content))  # Emojis personnalisés
            emoji_count += len(re.findall(r'[\U00010000-\U0010ffff]', message.content))  # Emojis Unicode
            
            if emoji_count >= self.security.emoji_spam_threshold:
                await self.handle_spam_detection(message, "spam d'emojis", [message.content])
                return
            
            # Vérifier les domaines blacklistés
            if self.security.blacklisted_domains:
                for domain in self.security.blacklisted_domains:
                    if domain in message.content:
                        try:
                            await message.delete()
                            await message.channel.send(
                                f"{message.author.mention}, votre message a été supprimé car il contient un domaine interdit.",
                                delete_after=5
                            )
                            
                            await self.log_security_event(
                                message.guild,
                                "🔗 Domaine interdit détecté",
                                discord.Color.red(),
                                f"Message avec un domaine interdit.\nDomaine: {domain}",
                                message.author,
                                additional_fields=[
                                    {"name": "Canal", "value": message.channel.mention},
                                    {"name": "Message", "value": message.content[:1000] + ('...' if len(message.content) > 1000 else '')}
                                ]
                            )
                            return
                        except Exception as e:
                            logging.error(f"Erreur lors de la suppression d'un message avec domaine blacklisté: {e}")
            
            # Vérifier les invitations Discord
            invite_match = re.search(r'discord(?:\.gg|app\.com\/invite|\.com\/invite)\/(\S+)', message.content)
            if invite_match:
                invite_code = invite_match.group(1)
                
                # Ignorer si c'est une invitation whitelistée
                if invite_code in self.security.whitelisted_invites:
                    return
                
                # Appliquer un cooldown pour éviter les abus
                bucket = self.invite_cooldowns.get_bucket(message)
                retry_after = bucket.update_rate_limit()
                
                if retry_after:
                    # L'utilisateur envoie des invitations trop rapidement
                    try:
                        await message.delete()
                        await message.channel.send(
                            f"{message.author.mention}, vous envoyez des invitations Discord trop rapidement. Veuillez attendre avant d'en envoyer d'autres.",
                            delete_after=5
                        )
                        
                        await self.log_security_event(
                            message.guild,
                            "⚠️ Spam d'invitations Discord",
                            discord.Color.orange(),
                            f"Spam potentiel d'invitations Discord",
                            message.author,
                            additional_fields=[
                                {"name": "Canal", "value": message.channel.mention},
                                {"name": "Message", "value": message.content[:1000] + ('...' if len(message.content) > 1000 else '')}
                            ]
                        )
                    except Exception as e:
                        logging.error(f"Erreur lors de la gestion du spam d'invitations: {e}")
    
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if not self.security.nuke_protection_enabled:
            return
            
        # Enregistrer la suppression de canal
        timestamp = time.time()
        guild = channel.guild
        
        if not hasattr(channel, 'guild') or not channel.guild:
            return
        
        # Récupérer l'entrée du journal d'audit pour trouver qui a supprimé le canal
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
                if entry.target.id == channel.id:
                    # Ajouter aux suppressions récentes
                    self.security.recent_channel_deletions.append((channel.id, timestamp, entry.user.id))
                    
                    # Vérifier les suppressions massives
                    recent_count = sum(1 for _, t, uid in self.security.recent_channel_deletions 
                                      if timestamp - t <= self.security.channel_deletion_timeframe 
                                      and uid == entry.user.id)
                    
                    if recent_count >= self.security.channel_deletion_threshold:
                        # Ignorer si l'utilisateur est de confiance
                        if str(entry.user.id) in self.security.trusted_users:
                            return
                            
                        # Ignorer si l'utilisateur a un rôle de confiance
                        if any(str(role.id) in self.security.trusted_roles for role in entry.user.roles):
                            return
                            
                        # Prendre des mesures - c'est grave!
                        await self.handle_nuke_attempt(guild, entry.user, "suppression massive de canaux", 
                                                     f"{recent_count} canaux supprimés en {self.security.channel_deletion_timeframe}s")
                        
                        # Essayer de restaurer les canaux à partir de la sauvegarde
                        if self.security.backups:
                            await self.restore_channels_from_backup(guild)
                    
                    break
        except Exception as e:
            logging.error(f"Erreur lors de la vérification du journal d'audit pour la suppression de canal: {e}")
    
    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        if not self.security.nuke_protection_enabled:
            return
            
        # Enregistrer la suppression de rôle
        timestamp = time.time()
        guild = role.guild
        
        # Récupérer l'entrée du journal d'audit pour trouver qui a supprimé le rôle
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
                if entry.target.id == role.id:
                    # Ajouter aux suppressions récentes
                    self.security.recent_role_deletions.append((role.id, timestamp, entry.user.id))
                    
                    # Vérifier les suppressions massives
                    recent_count = sum(1 for _, t, uid in self.security.recent_role_deletions 
                                      if timestamp - t <= self.security.role_deletion_timeframe 
                                      and uid == entry.user.id)
                    
                    if recent_count >= self.security.role_deletion_threshold:
                        # Ignorer si l'utilisateur est de confiance
                        if str(entry.user.id) in self.security.trusted_users:
                            return
                            
                        # Ignorer si l'utilisateur a un rôle de confiance
                        if any(str(role.id) in self.security.trusted_roles for role in entry.user.roles):
                            return
                            
                        # Prendre des mesures - c'est grave!
                        await self.handle_nuke_attempt(guild, entry.user, "suppression massive de rôles", 
                                                     f"{recent_count} rôles supprimés en {self.security.role_deletion_timeframe}s")
                        
                        # Essayer de restaurer les rôles à partir de la sauvegarde
                        if self.security.backups:
                            await self.restore_roles_from_backup(guild)
                    
                    break
        except Exception as e:
            logging.error(f"Erreur lors de la vérification du journal d'audit pour la suppression de rôle: {e}")
    
    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        if not self.security.nuke_protection_enabled:
            return
            
        # Enregistrer le ban
        timestamp = time.time()
        
        # Récupérer l'entrée du journal d'audit pour trouver qui a effectué le ban
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
                if entry.target.id == user.id:
                    # Ajouter aux bans récents
                    self.security.recent_bans.append((user.id, timestamp, entry.user.id))
                    
                    # Vérifier les bans massifs
                    recent_count = sum(1 for _, t, uid in self.security.recent_bans 
                                      if timestamp - t <= self.security.mass_ban_timeframe 
                                      and uid == entry.user.id)
                    
                    if recent_count >= self.security.mass_ban_threshold:
                        # Ignorer si l'utilisateur est de confiance
                        if str(entry.user.id) in self.security.trusted_users:
                            return
                            
                        # Ignorer si l'utilisateur a un rôle de confiance
                        if any(str(role.id) in self.security.trusted_roles for role in entry.user.roles):
                            return
                            
                        # Prendre des mesures - c'est grave!
                        await self.handle_nuke_attempt(guild, entry.user, "ban massif", 
                                                     f"{recent_count} membres bannis en {self.security.mass_ban_timeframe}s")
                    
                    break
        except Exception as e:
            logging.error(f"Erreur lors de la vérification du journal d'audit pour le ban: {e}")
    
    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        # Vérifier la création de rôles suspects avec des permissions dangereuses
        dangerous_perms = [perm for perm in self.security.dangerous_permissions 
                         if getattr(role.permissions, perm)]
        
        if dangerous_perms:
            # Obtenir qui a créé le rôle
            try:
                async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create):
                    if entry.target.id == role.id:
                        # Ignorer si l'utilisateur est de confiance
                        if str(entry.user.id) in self.security.trusted_users:
                            return
                            
                        # Ignorer si l'utilisateur a un rôle de confiance
                        if any(str(r.id) in self.security.trusted_roles for r in entry.user.roles):
                            return
                        
                        # Logger l'événement
                        perms_list = ", ".join(dangerous_perms)
                        await self.log_security_event(
                            role.guild,
                            "⚠️ Rôle créé avec permissions dangereuses",
                            discord.Color.orange(),
                            f"Un rôle avec des permissions potentiellement dangereuses a été créé.",
                            entry.user,
                            additional_fields=[
                                {"name": "Rôle", "value": role.name},
                                {"name": "Permissions dangereuses", "value": perms_list}
                            ]
                        )
                        break
            except Exception as e:
                logging.error(f"Erreur lors de la vérification du journal d'audit pour la création de rôle: {e}")
    
    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        # Ignorer si pas de changements de permissions
        if before.permissions == after.permissions:
            return
            
        # Vérifier les permissions dangereuses nouvellement ajoutées
        new_dangerous_perms = []
        for perm in self.security.dangerous_permissions:
            if getattr(after.permissions, perm) and not getattr(before.permissions, perm):
                new_dangerous_perms.append(perm)
        
        if new_dangerous_perms:
            # Obtenir qui a mis à jour le rôle
            try:
                async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_update):
                    if entry.target.id == after.id:
                        # Ignorer si l'utilisateur est de confiance
                        if str(entry.user.id) in self.security.trusted_users:
                            return
                            
                        # Ignorer si l'utilisateur a un rôle de confiance
                        if any(str(role.id) in self.security.trusted_roles for role in entry.user.roles):
                            return
                        
                        # Logger l'événement
                        perms_list = ", ".join(new_dangerous_perms)
                        await self.log_security_event(
                            after.guild,
                            "⚠️ Permissions dangereuses ajoutées à un rôle",
                            discord.Color.orange(),
                            f"Des permissions potentiellement dangereuses ont été ajoutées à un rôle.",
                            entry.user,
                            additional_fields=[
                                {"name": "Rôle", "value": after.name},
                                {"name": "Permissions ajoutées", "value": perms_list}
                            ]
                        )
                        break
            except Exception as e:
                logging.error(f"Erreur lors de la vérification du journal d'audit pour la mise à jour de rôle: {e}")
    
    # Fonctions utilitaires
    async def activate_raid_mode(self, guild, reason, user):
        """Activer le mode de protection contre les raids"""
        if self.security.raid_mode_active:
            return  # Déjà actif
            
        self.security.raid_mode_active = True
        self.security.raid_mode_end_time = time.time() + self.security.raid_mode_duration
        
        # Appliquer l'action du mode raid en fonction de la configuration
        if self.security.raid_mode_action == "lockdown":
            # Verrouiller le serveur - stocker les permissions originales et verrouiller tous les canaux
            await self.lockdown_server(guild)
        
        # Logger l'activation du mode raid
        executor = user.mention if user else "Système automatique"
        await self.log_security_event(
            guild,
            "🛡️ Mode Raid Activé",
            discord.Color.red(),
            f"Le mode raid a été activé.\nRaison: {reason}\nDurée: {self.format_time_duration(self.security.raid_mode_duration)}",
            user if user else None,
            additional_fields=[
                {"name": "Action", "value": self.get_raid_mode_action_description()},
                {"name": "Exécuteur", "value": executor}
            ]
        )
        
        # Envoyer une alerte dans le canal général si possible
        try:
            general = discord.utils.get(guild.text_channels, name="général") or \
                      discord.utils.get(guild.text_channels, name="general") or \
                      guild.system_channel
                      
            if general:
                embed = discord.Embed(
                    title="🛡️ Mode Raid Activé",
                    description=f"Le serveur est maintenant en mode protection contre les raids.\nCe mode se désactivera automatiquement dans {self.format_time_duration(self.security.raid_mode_duration)}.",
                    color=discord.Color.red()
                )
                embed.add_field(name="Raison", value=reason)
                
                if self.security.raid_mode_action == "lockdown":
                    embed.add_field(
                        name="Action", 
                        value="Les canaux ont été verrouillés. Seuls les membres existants peuvent interagir."
                    )
                elif self.security.raid_mode_action == "captcha":
                    embed.add_field(
                        name="Action", 
                        value="Les nouveaux membres devront résoudre un captcha pour accéder au serveur."
                    )
                    
                await general.send(embed=embed)
        except Exception as e:
            logging.error(f"Erreur lors de l'envoi de la notification de mode raid au canal général: {e}")
    
    async def deactivate_raid_mode(self, guild, reason, user):
        """Désactiver le mode de protection contre les raids"""
        if not self.security.raid_mode_active:
            return  # Pas actif
            
        self.security.raid_mode_active = False
        
        # Restaurer les paramètres originaux en fonction de l'action du mode raid
        if self.security.raid_mode_action == "lockdown":
            # Déverrouiller le serveur - restaurer les permissions originales
            await self.unlock_server(guild)
        
        # Logger la désactivation du mode raid
        executor = user.mention if user else "Système automatique"
        await self.log_security_event(
            guild,
            "✅ Mode Raid Désactivé",
            discord.Color.green(),
            f"Le mode raid a été désactivé.\nRaison: {reason}",
            user if user else None,
            additional_fields=[{"name": "Exécuteur", "value": executor}]
        )
        
        # Envoyer une notification dans le canal général si possible
        try:
            general = discord.utils.get(guild.text_channels, name="général") or \
                      discord.utils.get(guild.text_channels, name="general") or \
                      guild.system_channel
                      
            if general:
                embed = discord.Embed(
                    title="✅ Mode Raid Désactivé",
                    description="Le serveur n'est plus en mode protection contre les raids. Les fonctionnalités normales ont été restaurées.",
                    color=discord.Color.green()
                )
                
                await general.send(embed=embed)
        except Exception as e:
            logging.error(f"Erreur lors de l'envoi de la notification de désactivation du mode raid: {e}")
    
    async def apply_raid_mode_action(self, member):
        """Appliquer l'action du mode raid à un nouveau membre"""
        if not self.security.raid_mode_active:
            return
            
        if self.security.raid_mode_action == "lockdown":
            # En mode verrouillage, les nouveaux membres peuvent rester mais ont un accès limité
            # Les permissions sont déjà restreintes par le verrouillage
            pass
            
        elif self.security.raid_mode_action == "captcha":
            # Attribuer un rôle restreint et exiger une vérification par captcha
            try:
                # S'assurer d'avoir un rôle de vérification
                verification_role = discord.utils.get(member.guild.roles, name="Non vérifié")
                if not verification_role:
                    # Créer le rôle s'il n'existe pas
                    verification_role = await member.guild.create_role(
                        name="Non vérifié",
                        reason="Rôle pour les membres non vérifiés pendant le mode raid"
                    )
                    
                    # Définir les permissions pour le rôle
                    for channel in member.guild.channels:
                        if isinstance(channel, discord.TextChannel):
                            # Autoriser uniquement à voir le canal de vérification
                            if channel.name == "verification":
                                await channel.set_permissions(verification_role, read_messages=True, send_messages=True)
                            else:
                                await channel.set_permissions(verification_role, read_messages=False)
                
                # Attribuer le rôle de vérification
                await member.add_roles(verification_role)
                
                # Générer un captcha pour cet utilisateur
                captcha_code = CaptchaGenerator.generate_captcha_code()
                self.security.captcha_verification[str(member.id)] = captcha_code
                
                # Essayer d'envoyer un DM avec le captcha
                try:
                    embed = discord.Embed(
                        title="🛡️ Vérification requise",
                        description=f"Le serveur {member.guild.name} est actuellement en mode protection. Pour accéder au serveur, veuillez résoudre le captcha ci-dessous et entrer le code dans le canal #verification.",
                        color=discord.Color.orange()
                    )
                    
                    # Pour l'instant, envoyer simplement le code puisqu'on ne peut pas facilement afficher du HTML
                    embed.add_field(name="Code", value=f"`{captcha_code}`")
                    embed.add_field(
                        name="Instructions", 
                        value="Entrez ce code dans le canal #verification pour obtenir l'accès au serveur."
                    )
                    
                    await member.send(embed=embed)
                    
                    # S'assurer qu'il y a un canal de vérification
                    verification_channel = discord.utils.get(member.guild.text_channels, name="verification")
                    if not verification_channel:
                        # Créer un canal de vérification
                        overwrites = {
                            member.guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                            verification_role: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                            member.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                        }
                        
                        verification_channel = await member.guild.create_text_channel(
                            "verification",
                            overwrites=overwrites,
                            reason="Canal pour la vérification captcha",
                            topic="Entrez le code de vérification qui vous a été envoyé par message privé."
                        )
                        
                        # Envoyer les instructions
                        await verification_channel.send(
                            embed=discord.Embed(
                                title="🔐 Canal de vérification",
                                description="Le serveur est en mode protection contre les raids. Pour obtenir l'accès, entrez le code qui vous a été envoyé par message privé.",
                                color=discord.Color.blue()
                            )
                        )
                    
                except discord.Forbidden:
                    # Impossible de leur envoyer un DM, notifier dans le canal de vérification
                    verification_channel = discord.utils.get(member.guild.text_channels, name="verification")
                    if verification_channel:
                        await verification_channel.send(
                            f"{member.mention}, je n'ai pas pu vous envoyer de message privé. Veuillez activer les DMs pour recevoir votre code de vérification ou contacter un administrateur."
                        )
            
            except Exception as e:
                logging.error(f"Erreur lors de l'application de la vérification captcha: {e}")
                
        elif self.security.raid_mode_action == "kick":
            # Simplement expulser les nouveaux membres pendant le mode raid
            try:
                await member.kick(reason="Mode protection contre les raids actif - nouveaux membres refusés temporairement")
                
                await self.log_security_event(
                    member.guild,
                    "👢 Membre expulsé (mode raid)",
                    discord.Color.orange(),
                    f"Un membre a été expulsé automatiquement car le serveur est en mode raid.",
                    member
                )
            except Exception as e:
                logging.error(f"Erreur lors de l'expulsion d'un membre pendant le mode raid: {e}")
                
        elif self.security.raid_mode_action == "ban":
            # Bannir les nouveaux membres pendant le mode raid (mesure extrême)
            try:
                await member.ban(reason="Mode protection contre les raids actif - nouveaux membres bannis temporairement")
                
                await self.log_security_event(
                    member.guild,
                    "🔨 Membre banni (mode raid)",
                    discord.Color.red(),
                    f"Un membre a été banni automatiquement car le serveur est en mode raid.",
                    member
                )
            except Exception as e:
                logging.error(f"Erreur lors du bannissement d'un membre pendant le mode raid: {e}")
    
    async def lockdown_server(self, guild):
        """Verrouiller tous les canaux pendant le mode raid"""
        try:
            # Sauvegarder les permissions actuelles pour restauration ultérieure
            self.channel_perms_cache = {}
            
            for channel in guild.channels:
                if isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel)):
                    # Ignorer les canaux explicitement destinés à rester publics même pendant le verrouillage
                    if channel.name.lower() in ["règles", "rules", "annonces", "announcements", "verification"]:
                        continue
                        
                    # Stocker les permissions originales
                    self.channel_perms_cache[channel.id] = {
                        "overwrites": copy.deepcopy(channel.overwrites),
                        "name": channel.name,
                        "type": type(channel).__name__
                    }
                    
                    # Mettre à jour les permissions pour empêcher les nouveaux utilisateurs d'envoyer des messages
                    overwrites = copy.deepcopy(channel.overwrites)
                    
                    # Verrouiller pour @everyone
                    everyone_overwrite = overwrites.get(guild.default_role, discord.PermissionOverwrite())
                    if isinstance(channel, discord.TextChannel):
                        everyone_overwrite.send_messages = False
                    elif isinstance(channel, discord.VoiceChannel):
                        everyone_overwrite.speak = False
                    
                    overwrites[guild.default_role] = everyone_overwrite
                    
                    # Mettre à jour les permissions du canal
                    await channel.edit(overwrites=overwrites)
            
            logging.info(f"Verrouillage du serveur activé dans {guild.name}")
            
        except Exception as e:
            logging.error(f"Erreur lors du verrouillage du serveur: {e}")
    
    async def unlock_server(self, guild):
        """Restaurer les permissions des canaux après la fin du mode raid"""
        try:
            for channel_id, data in self.channel_perms_cache.items():
                channel = guild.get_channel(channel_id)
                if channel:
                    # Restaurer les permissions originales
                    await channel.edit(overwrites=data["overwrites"])
            
            # Vider le cache
            self.channel_perms_cache = {}
            
            logging.info(f"Verrouillage du serveur désactivé dans {guild.name}")
            
        except Exception as e:
            logging.error(f"Erreur lors du déverrouillage du serveur: {e}")
    
    async def handle_spam_detection(self, message, spam_type, message_contents):
        """Gérer une tentative de spam détectée"""
        try:
            # Supprimer le message offensant
            await message.delete()
            
            # Notifier l'utilisateur
            notification = await message.channel.send(
                f"{message.author.mention}, veuillez cesser d'envoyer du {spam_type}. Cela peut entraîner des sanctions.",
                delete_after=5
            )
            
            # Logger l'événement de spam
            await self.log_security_event(
                message.guild,
                f"🔄 Détection de spam",
                discord.Color.orange(),
                f"Détection de {spam_type}",
                message.author,
                additional_fields=[
                    {"name": "Canal", "value": message.channel.mention},
                    {"name": "Messages détectés", "value": "\n".join(message_contents)[:1000] + ("..." if len("\n".join(message_contents)) > 1000 else "")}
                ]
            )
            
            # Si c'est un récidiviste, intensifier
            user_id = str(message.author.id)
            if not hasattr(self, 'spam_counts'):
                self.spam_counts = {}
                
            if user_id not in self.spam_counts:
                self.spam_counts[user_id] = {"count": 1, "last_time": time.time()}
            else:
                # Ne compter que les spams dans la dernière heure
                if time.time() - self.spam_counts[user_id]["last_time"] < 3600:
                    self.spam_counts[user_id]["count"] += 1
                else:
                    self.spam_counts[user_id]["count"] = 1
                
                self.spam_counts[user_id]["last_time"] = time.time()
            
            # Vérifier si nous devons prendre des mesures plus sérieuses
            spam_count = self.spam_counts[user_id]["count"]
            
            if spam_count >= 5:  # Plus de 5 détections de spam en une heure
                # Essayer d'utiliser d'abord le système de modération existant
                try:
                    moderation_cog = self.bot.get_cog("Moderation")
                    if moderation_cog and hasattr(moderation_cog, 'automod'):
                        # Utiliser le mute du cog modération si disponible
                        mute_role = discord.utils.get(message.guild.roles, name="Muted")
                        if not mute_role:
                            mute_role = await moderation_cog.create_mute_role(message.guild)
                        
                        await message.author.add_roles(mute_role, reason=f"Spam automatique détecté: {spam_type}")
                        
                        # Enregistrer le mute dans le système de modération
                        end_time = time.time() + (30 * 60)  # 30 minutes en secondes
                        moderation_cog.automod.muted_users[user_id] = {
                            'guild_id': str(message.guild.id),
                            'duration': 30 * 60,  # 30 minutes en secondes
                            'end_time': end_time
                        }
                        moderation_cog.automod.save_config()
                    else:
                        # Utiliser le timeout natif de Discord
                        timeout_duration = datetime.timedelta(minutes=30)
                        await message.author.timeout(timeout_duration, reason=f"Spam automatique détecté: {spam_type}")
                    
                    # Logger le mute/timeout automatique
                    action_type = "Mute" if moderation_cog and hasattr(moderation_cog, 'automod') else "Timeout"
                    await self.log_security_event(
                        message.guild,
                        f"🔇 {action_type} automatique",
                        discord.Color.red(),
                        f"Un membre a été {action_type.lower()} automatiquement pour spam excessif ({spam_count} détections en une heure).",
                        message.author,
                        additional_fields=[
                            {"name": "Type de spam", "value": spam_type},
                            {"name": "Durée", "value": "30 minutes"}
                        ]
                    )
                    
                    # Notifier dans le canal
                    await message.channel.send(
                        f"{message.author.mention} a été {action_type.lower()} automatiquement pour 30 minutes en raison de spam excessif.",
                        delete_after=10
                    )
                except Exception as e:
                    logging.error(f"Erreur lors de l'application du mute/timeout: {e}")
                
        except Exception as e:
            logging.error(f"Erreur lors de la gestion de la détection de spam: {e}")
    
    async def handle_nuke_attempt(self, guild, user, nuke_type, details):
        """Gérer une tentative détectée de nuking (dommage massif) du serveur"""
        try:
            # Logger l'événement de sécurité grave
            await self.log_security_event(
                guild,
                "🚨 ALERTE DE SÉCURITÉ CRITIQUE",
                discord.Color.dark_red(),
                f"Tentative potentielle de nuking détectée: {nuke_type}\nDétails: {details}",
                user,
                ping_admins=True
            )
            
            # Prendre des mesures immédiates contre l'utilisateur (ban)
            try:
                # Créer un embed de ban avec les détails
                ban_embed = discord.Embed(
                    title="🔨 Ban de sécurité automatique",
                    description=f"{user.mention} a été banni du serveur pour tentative de nuking.",
                    color=discord.Color.dark_red()
                )
                ban_embed.add_field(name="Type d'attaque", value=nuke_type)
                ban_embed.add_field(name="Détails", value=details)
                
                # Récupérer le canal mod-logs
                mod_logs = discord.utils.get(guild.text_channels, name="mod-logs")
                if mod_logs:
                    await mod_logs.send(embed=ban_embed)
                
                # Bannir l'utilisateur
                await guild.ban(user, reason=f"Tentative de nuking détectée: {nuke_type} - {details}")
                
            except discord.Forbidden:
                logging.error(f"Échec du bannissement de l'utilisateur {user.id} pour tentative de nuking - permissions manquantes")
            except Exception as e:
                logging.error(f"Erreur lors du bannissement de l'utilisateur {user.id} pour tentative de nuking: {e}")
            
            # Si c'est une suppression massive de canaux/rôles, essayer de restaurer à partir de la sauvegarde
            if nuke_type in ["suppression massive de canaux", "suppression massive de rôles"]:
                if self.security.backups:
                    if nuke_type == "suppression massive de canaux":
                        await self.restore_channels_from_backup(guild)
                    elif nuke_type == "suppression massive de rôles":
                        await self.restore_roles_from_backup(guild)
                
            # Activer le mode raid s'il n'est pas déjà actif
            if not self.security.raid_mode_active:
                await self.activate_raid_mode(guild, f"Tentative de nuking détectée: {nuke_type}", None)
                
        except Exception as e:
            logging.error(f"Erreur lors de la gestion de la tentative de nuking: {e}")
    
    async def calculate_user_trust_score(self, member):
        """Calculer et mettre à jour le score de confiance pour un utilisateur"""
        if not self.security.trust_score_enabled:
            return
            
        user_id = str(member.id)
        
        # Le score de base commence à 50 (neutre)
        score = 50
        
        # Facteur d'âge du compte
        # Utiliser datetime.now(timezone.utc) pour avoir le même type que member.created_at
        account_age_days = (datetime.datetime.now(datetime.timezone.utc) - member.created_at).days
        if account_age_days < 1:
            score -= 30  # Compte très récent, gros drapeau rouge
        elif account_age_days < 7:
            score -= 20  # Nouveau compte, préoccupation importante
        elif account_age_days < 30:
            score -= 10  # Compte relativement récent, certaine préoccupation
        elif account_age_days > 365:
            score += 10  # Ancien compte, plus digne de confiance
        
        # Facteurs de nom d'utilisateur
        username = member.name.lower()
        
        # Vérifier les modèles de noms d'utilisateur suspects
        for pattern in self.security.suspicious_patterns:
            if re.search(pattern, username):
                score -= 15
                break
        
        # Vérifier les noms d'utilisateur aléatoires (par exemple, "User1234")
        if re.match(r'^[a-z]+\d{4,}$', username):
            score -= 5
        
        # Stocker le score de confiance
        self.security.user_trust_scores[user_id] = {
            "score": score,
            "join_date": time.time()
        }
        
        # Sauvegarder les scores mis à jour
        self.security.save_config()
        
        # Logger les scores de confiance très bas
        if score < 30:
            await self.log_security_event(
                member.guild,
                "⚠️ Membre à faible confiance",
                discord.Color.gold(),
                f"Un nouveau membre avec un score de confiance très faible a rejoint.",
                member,
                additional_fields=[
                    {"name": "Score de confiance", "value": f"{score}/100"},
                    {"name": "Âge du compte", "value": f"{account_age_days} jours"},
                    {"name": "Date de création", "value": member.created_at.strftime("%d/%m/%Y %H:%M:%S")}
                ]
            )
    
    def detect_similar_usernames(self, member):
        """Détecter si plusieurs utilisateurs rejoignent avec des noms très similaires"""
        # Obtenir la base du nom d'utilisateur (supprimer les chiffres à la fin)
        base_name = re.sub(r'\d+$', '', member.name.lower())
        
        # Ignorer les noms très communs ou courts
        if len(base_name) < 4:
            return []
        
        # Enregistrer ce nom d'utilisateur
        current_time = time.time()
        self.similar_names_detector[base_name].append((member.id, member.name, current_time))
        
        # Ne garder que les entrées de la dernière heure
        one_hour_ago = current_time - 3600
        self.similar_names_detector[base_name] = [
            entry for entry in self.similar_names_detector[base_name] 
            if entry[2] >= one_hour_ago
        ]
        
        # Retourner les noms similaires s'il y en a assez
        similar_names = self.similar_names_detector[base_name]
        if len(similar_names) >= 3:
            return similar_names
        
        return []
    
    async def create_server_backup(self, guild):
        """Créer une sauvegarde des canaux et rôles du serveur"""
        try:
            backup = {
                "timestamp": time.time(),
                "guild_id": str(guild.id),
                "guild_name": guild.name,
                "channels": [],
                "roles": []
            }
            
            # Sauvegarde des canaux
            for channel in guild.channels:
                # Ignorer les canaux vocaux pour simplifier
                if isinstance(channel, discord.TextChannel):
                    channel_data = {
                        "id": str(channel.id),
                        "name": channel.name,
                        "type": "text",
                        "position": channel.position,
                        "category_id": str(channel.category_id) if channel.category_id else None,
                        "permissions": [],
                        "topic": channel.topic,
                        "slowmode_delay": channel.slowmode_delay,
                        "nsfw": channel.is_nsfw()
                    }
                    
                    # Sauvegarder les permissions
                    for target, overwrite in channel.overwrites.items():
                        overwrite_dict = {
                            "id": str(target.id),
                            "type": "role" if isinstance(target, discord.Role) else "member"
                        }
                        
                        # Ajouter les permissions d'autorisation et de refus
                        for perm, value in overwrite._values.items():
                            if value is not None:
                                overwrite_dict[perm] = value
                                
                        channel_data["permissions"].append(overwrite_dict)
                    
                    backup["channels"].append(channel_data)
                elif isinstance(channel, discord.CategoryChannel):
                    channel_data = {
                        "id": str(channel.id),
                        "name": channel.name,
                        "type": "category",
                        "position": channel.position,
                        "permissions": []
                    }
                    
                    # Sauvegarder les permissions
                    for target, overwrite in channel.overwrites.items():
                        overwrite_dict = {
                            "id": str(target.id),
                            "type": "role" if isinstance(target, discord.Role) else "member"
                        }
                        
                        # Ajouter les permissions d'autorisation et de refus
                        for perm, value in overwrite._values.items():
                            if value is not None:
                                overwrite_dict[perm] = value
                                
                        channel_data["permissions"].append(overwrite_dict)
                    
                    backup["channels"].append(channel_data)
            
            # Sauvegarde des rôles
            for role in guild.roles:
                # Ignorer le rôle @everyone
                if role.is_default():
                    continue
                    
                role_data = {
                    "id": str(role.id),
                    "name": role.name,
                    "color": role.color.value,
                    "hoist": role.hoist,
                    "position": role.position,
                    "permissions": role.permissions.value,
                    "mentionable": role.mentionable
                }
                
                backup["roles"].append(role_data)
            
            # Sauvegarder la sauvegarde
            self.security.backups[str(guild.id)] = backup
            self.security.last_backup_time = time.time()
            self.security.save_config()
            
            logging.info(f"Sauvegarde du serveur créée pour {guild.name}")
            
            return backup
        except Exception as e:
            logging.error(f"Erreur lors de la création de la sauvegarde du serveur: {e}")
            return None
    
    async def restore_channels_from_backup(self, guild):
        """Restaurer les canaux à partir de la dernière sauvegarde"""
        try:
            backup = self.security.backups.get(str(guild.id))
            
            if not backup or "channels" not in backup:
                logging.error(f"Aucune sauvegarde valide trouvée pour le serveur {guild.id}")
                return False
            
            # Logger que nous commençons la restauration
            await self.log_security_event(
                guild,
                "🔄 Restauration de canaux",
                discord.Color.blue(),
                "Début de la restauration des canaux à partir de la sauvegarde."
            )
            
            # D'abord, créer les catégories
            category_map = {}  # Mapper l'ancien ID de catégorie à la nouvelle catégorie
            
            for channel_data in backup["channels"]:
                if channel_data["type"] == "category":
                    # Vérifier si la catégorie existe déjà par nom
                    existing = discord.utils.get(guild.categories, name=channel_data["name"])
                    
                    if existing:
                        category_map[channel_data["id"]] = existing
                    else:
                        # Créer la catégorie
                        category = await guild.create_category(
                            name=channel_data["name"],
                            position=channel_data["position"],
                            reason="Restauration à partir de la sauvegarde"
                        )
                        
                        # Appliquer les permissions
                        overwrites = {}
                        for overwrite in channel_data["permissions"]:
                            target_id = int(overwrite["id"])
                            target = None
                            
                            if overwrite["type"] == "role":
                                target = guild.get_role(target_id)
                            else:
                                target = guild.get_member(target_id)
                                
                            if target:
                                perms = discord.PermissionOverwrite()
                                for perm, value in overwrite.items():
                                    if perm not in ["id", "type"]:
                                        setattr(perms, perm, value)
                                        
                                overwrites[target] = perms
                        
                        if overwrites:
                            await category.edit(overwrites=overwrites)
                            
                        category_map[channel_data["id"]] = category
            
            # Maintenant créer les canaux textuels
            created_channels = 0
            
            for channel_data in backup["channels"]:
                if channel_data["type"] == "text":
                    # Vérifier si le canal existe déjà par nom
                    existing = discord.utils.get(guild.text_channels, name=channel_data["name"])
                    
                    if not existing:
                        # Déterminer la catégorie
                        category = None
                        if channel_data["category_id"] and channel_data["category_id"] in category_map:
                            category = category_map[channel_data["category_id"]]
                        
                        # Créer le canal
                        try:
                            channel = await guild.create_text_channel(
                                name=channel_data["name"],
                                topic=channel_data["topic"],
                                position=channel_data["position"],
                                category=category,
                                slowmode_delay=channel_data["slowmode_delay"],
                                nsfw=channel_data["nsfw"],
                                reason="Restauration à partir de la sauvegarde"
                            )
                            
                            # Appliquer les permissions
                            overwrites = {}
                            for overwrite in channel_data["permissions"]:
                                target_id = int(overwrite["id"])
                                target = None
                                
                                if overwrite["type"] == "role":
                                    target = guild.get_role(target_id)
                                else:
                                    target = guild.get_member(target_id)
                                    
                                if target:
                                    perms = discord.PermissionOverwrite()
                                    for perm, value in overwrite.items():
                                        if perm not in ["id", "type"]:
                                            setattr(perms, perm, value)
                                            
                                    overwrites[target] = perms
                            
                            if overwrites:
                                await channel.edit(overwrites=overwrites)
                                
                            created_channels += 1
                        except Exception as e:
                            logging.error(f"Erreur lors de la restauration du canal {channel_data['name']}: {e}")
            
            # Logger la fin
            await self.log_security_event(
                guild,
                "✅ Restauration terminée",
                discord.Color.green(),
                f"Restauration des canaux terminée. {created_channels} canaux ont été recréés."
            )
            
            return True
            
        except Exception as e:
            logging.error(f"Erreur lors de la restauration des canaux à partir de la sauvegarde: {e}")
            
            # Logger l'erreur
            await self.log_security_event(
                guild,
                "❌ Échec de restauration",
                discord.Color.red(),
                f"La restauration des canaux a échoué: {str(e)}"
            )
            
            return False
    
    async def restore_roles_from_backup(self, guild):
        """Restaurer les rôles à partir de la dernière sauvegarde"""
        try:
            backup = self.security.backups.get(str(guild.id))
            
            if not backup or "roles" not in backup:
                logging.error(f"Aucune sauvegarde valide trouvée pour le serveur {guild.id}")
                return False
            
            # Logger que nous commençons la restauration
            await self.log_security_event(
                guild,
                "🔄 Restauration de rôles",
                discord.Color.blue(),
                "Début de la restauration des rôles à partir de la sauvegarde."
            )
            
            # Créer les rôles de la position la plus élevée à la plus basse
            created_roles = 0
            
            # Trier les rôles par position dans l'ordre décroissant
            sorted_roles = sorted(backup["roles"], key=lambda r: r["position"], reverse=True)
            
            for role_data in sorted_roles:
                # Vérifier si le rôle existe déjà par nom
                existing = discord.utils.get(guild.roles, name=role_data["name"])
                
                if not existing:
                    try:
                        # Créer le rôle
                        await guild.create_role(
                            name=role_data["name"],
                            permissions=discord.Permissions(role_data["permissions"]),
                            colour=discord.Colour(role_data["color"]),
                            hoist=role_data["hoist"],
                            mentionable=role_data["mentionable"],
                            reason="Restauration à partir de la sauvegarde"
                        )
                        
                        created_roles += 1
                    except Exception as e:
                        logging.error(f"Erreur lors de la restauration du rôle {role_data['name']}: {e}")
            
            # Logger la fin
            await self.log_security_event(
                guild,
                "✅ Restauration terminée",
                discord.Color.green(),
                f"Restauration des rôles terminée. {created_roles} rôles ont été recréés."
            )
            
            return True
            
        except Exception as e:
            logging.error(f"Erreur lors de la restauration des rôles à partir de la sauvegarde: {e}")
            
            # Logger l'erreur
            await self.log_security_event(
                guild,
                "❌ Échec de restauration",
                discord.Color.red(),
                f"La restauration des rôles a échoué: {str(e)}"
            )
            
            return False
    
    async def log_security_event(self, guild, title, color, description, user=None, additional_fields=None, ping_admins=False):
        """Logger un événement de sécurité dans le canal de logs de sécurité"""
        try:
            # D'abord, chercher dans la catégorie spécifiée
            category = guild.get_channel(1228669526879633408)
            log_channel = None
            
            if category and isinstance(category, discord.CategoryChannel):
                log_channel = discord.utils.get(category.text_channels, name="security-logs")
            
            # Si pas trouvé, chercher dans tout le serveur
            if not log_channel:
                log_channel = discord.utils.get(guild.text_channels, name="security-logs")
                
                # Si toujours pas trouvé, créer le canal dans la catégorie spécifiée si elle existe
                if not log_channel:
                    try:
                        overwrites = {
                            guild.default_role: discord.PermissionOverwrite(read_messages=False),
                            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                        }
                        
                        # Trouver les rôles admin/mod pour leur donner accès
                        for role in guild.roles:
                            if role.permissions.administrator or role.permissions.manage_guild:
                                overwrites[role] = discord.PermissionOverwrite(read_messages=True)
                        
                        if category and isinstance(category, discord.CategoryChannel):
                            log_channel = await guild.create_text_channel(
                                "security-logs",
                                category=category,
                                overwrites=overwrites,
                                reason="Canal de logs de sécurité"
                            )
                        else:
                            log_channel = await guild.create_text_channel(
                                "security-logs",
                                overwrites=overwrites,
                                reason="Canal de logs de sécurité"
                            )
                    except Exception as e:
                        logging.error(f"Erreur lors de la création du canal de logs: {e}")
                        return
            
            if not log_channel:
                return
                
            embed = discord.Embed(
                title=title,
                description=description,
                color=color,
                timestamp=datetime.datetime.now()
            )
            
            if user:
                embed.add_field(name="Utilisateur", value=f"{user.mention} ({user.name}, ID: {user.id})")
                embed.set_thumbnail(url=user.display_avatar.url)
            
            if additional_fields:
                for field in additional_fields:
                    embed.add_field(name=field["name"], value=field["value"], inline=field.get("inline", True))
            
            content = None
            if ping_admins:
                # Ping les utilisateurs avec des permissions d'administrateur
                admin_role = None
                for role in guild.roles:
                    if role.permissions.administrator and not role.is_default():
                        admin_role = role
                        break
                
                if admin_role:
                    content = f"{admin_role.mention} **ALERTE DE SÉCURITÉ CRITIQUE** - Action requise immédiatement!"
                else:
                    # Essayer de trouver le propriétaire si pas de rôle admin
                    content = f"<@{guild.owner_id}> **ALERTE DE SÉCURITÉ CRITIQUE** - Action requise immédiatement!"
            
            await log_channel.send(content=content, embed=embed)
            
        except Exception as e:
            logging.error(f"Erreur lors de la journalisation de l'événement de sécurité: {e}")
    
    async def log_security_action(self, guild, description, user, color, fields=None):
        """Logger une action de sécurité effectuée par un admin/mod"""
        try:
            # D'abord, chercher dans la catégorie spécifiée
            category = guild.get_channel(1228669526879633408)
            log_channel = None
            
            if category and isinstance(category, discord.CategoryChannel):
                log_channel = discord.utils.get(category.text_channels, name="security-logs")
            
            # Si pas trouvé, chercher dans tout le serveur
            if not log_channel:
                log_channel = discord.utils.get(guild.text_channels, name="security-logs")
            
            if not log_channel:
                return
                
            embed = discord.Embed(
                title="🔧 Action de sécurité",
                description=description,
                color=color,
                timestamp=datetime.datetime.now()
            )
            
            if user:
                embed.add_field(name="Exécuté par", value=f"{user.mention} ({user.name})")
                embed.set_footer(text=f"ID: {user.id}")
            
            if fields:
                for field in fields:
                    embed.add_field(name=field["name"], value=field["value"], inline=field.get("inline", True))
            
            await log_channel.send(embed=embed)
            
        except Exception as e:
            logging.error(f"Erreur lors de la journalisation de l'action de sécurité: {e}")
    
    def format_time_duration(self, seconds):
        """Formatter une durée en secondes en chaîne lisible par l'homme"""
        minutes, seconds = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        
        parts = []
        if days > 0:
            parts.append(f"{days} jour{'s' if days > 1 else ''}")
        if hours > 0:
            parts.append(f"{hours} heure{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        if seconds > 0 and not parts:  # Afficher les secondes uniquement s'il n'y a pas d'unités plus grandes
            parts.append(f"{seconds} seconde{'s' if seconds > 1 else ''}")
            
        return " ".join(parts) if parts else "0 seconde"
    
    def get_raid_mode_action_description(self):
        """Obtenir une description lisible de l'action actuelle du mode raid"""
        if self.security.raid_mode_action == "lockdown":
            return "Verrouillage du serveur - Les nouveaux membres ne peuvent pas interagir"
        elif self.security.raid_mode_action == "captcha":
            return "Vérification par captcha pour les nouveaux membres"
        elif self.security.raid_mode_action == "kick":
            return "Expulsion automatique des nouveaux membres"
        elif self.security.raid_mode_action == "ban":
            return "Bannissement automatique des nouveaux membres"
        else:
            return f"Action inconnue: {self.security.raid_mode_action}"
    
    # Groupe de commandes pour le système de sécurité
    @app_commands.command(name="security", description="Gérer le système de sécurité du serveur")
    @app_commands.default_permissions(administrator=True)
    async def security_cmd(self, interaction: discord.Interaction):
        """Commande pour gérer le système de sécurité du serveur"""
        # Créer un embed avec l'état actuel de la sécurité
        embed = discord.Embed(
            title="🛡️ Système de Sécurité du Serveur",
            description="Bienvenue dans le panneau de contrôle du système de sécurité. Utilisez les boutons ci-dessous pour gérer les paramètres de sécurité.",
            color=discord.Color.blue()
        )
        
        # Section d'état
        status_lines = []
        status_lines.append(f"🛡️ **Protection anti-raid:** {'✅ Activée' if self.security.raid_protection_enabled else '❌ Désactivée'}")
        status_lines.append(f"🔄 **Protection anti-spam:** {'✅ Activée' if self.security.spam_protection_enabled else '❌ Désactivée'}")
        status_lines.append(f"💣 **Protection anti-nuke:** {'✅ Activée' if self.security.nuke_protection_enabled else '❌ Désactivée'}")
        status_lines.append(f"⭐ **Système de confiance:** {'✅ Activé' if self.security.trust_score_enabled else '❌ Désactivé'}")
        
        status_text = "\n".join(status_lines)
        embed.add_field(name="Statut des protections", value=status_text, inline=False)
        
        # Section des seuils
        thresholds_lines = []
        thresholds_lines.append(f"🚪 Seuil de raid: **{self.security.raid_detection_threshold}** membres en **{self.security.raid_detection_timeframe}s**")
        thresholds_lines.append(f"📢 Seuil de spam: **{self.security.rapid_message_threshold}** messages en **{self.security.rapid_message_timeframe}s**")
        thresholds_lines.append(f"📜 Seuil de suppression de salons: **{self.security.channel_deletion_threshold}** en **{self.security.channel_deletion_timeframe}s**")
        thresholds_lines.append(f"🏷️ Seuil de suppression de rôles: **{self.security.role_deletion_threshold}** en **{self.security.role_deletion_timeframe}s**")
        
        thresholds_text = "\n".join(thresholds_lines)
        embed.add_field(name="Seuils de détection", value=thresholds_text, inline=False)
        
        # État du mode raid
        if self.security.raid_mode_active:
            time_left = self.security.raid_mode_end_time - time.time()
            if time_left > 0:
                time_left_text = self.format_time_duration(time_left)
                raid_status = f"🔴 **ACTIF** - Se désactive dans {time_left_text}"
            else:
                raid_status = "🔴 **ACTIF** - Désactivation imminente"
            
            raid_status += f"\nAction: {self.get_raid_mode_action_description()}"
        else:
            raid_status = "🟢 **INACTIF**"
            
        embed.add_field(name="Statut du mode raid", value=raid_status, inline=False)
        
        # Statistiques
        stats_lines = []
        stats_lines.append(f"🛡️ Utilisateurs de confiance: **{len(self.security.trusted_users)}**")
        stats_lines.append(f"⛔ Domaines blacklistés: **{len(self.security.blacklisted_domains)}**")
        
        # Afficher les infos de sauvegarde si disponibles
        if self.security.last_backup_time > 0:
            backup_age = time.time() - self.security.last_backup_time
            backup_age_text = self.format_time_duration(backup_age)
            stats_lines.append(f"💾 Dernière sauvegarde: il y a **{backup_age_text}**")
        else:
            stats_lines.append("💾 Aucune sauvegarde disponible")
            
        stats_text = "\n".join(stats_lines)
        embed.add_field(name="Statistiques", value=stats_text, inline=False)
        
        # Envoyer l'embed avec les boutons interactifs
        await interaction.response.send_message(
            embed=embed,
            view=SecurityConfigView(self),
            ephemeral=True
        )
        
    @app_commands.command(name="raidmode", description="Gérer le mode raid du serveur")
    @app_commands.default_permissions(administrator=True)
    async def raidmode_cmd(self, interaction: discord.Interaction):
        """Commande pour gérer le mode raid"""
        embed = discord.Embed(
            title="🛡️ Gestion du Mode Raid",
            description="Le mode raid protège votre serveur contre les attaques coordonnées.",
            color=discord.Color.red() if self.security.raid_mode_active else discord.Color.blue()
        )
        
        # État actuel
        if self.security.raid_mode_active:
            time_left = self.security.raid_mode_end_time - time.time()
            if time_left > 0:
                time_left_text = self.format_time_duration(time_left)
                status = f"🔴 **ACTIF** - Se désactive dans {time_left_text}"
            else:
                status = "🔴 **ACTIF** - Désactivation imminente"
        else:
            status = "🟢 **INACTIF**"
            
        embed.add_field(name="Statut", value=status, inline=False)
        
        # Configuration
        config_lines = []
        config_lines.append(f"📝 Action: **{self.get_raid_mode_action_description()}**")
        config_lines.append(f"⏱️ Durée: **{self.format_time_duration(self.security.raid_mode_duration)}**")
        config_lines.append(f"🔍 Seuil de détection: **{self.security.raid_detection_threshold}** membres en **{self.security.raid_detection_timeframe}s**")
        
        config_text = "\n".join(config_lines)
        embed.add_field(name="Configuration", value=config_text, inline=False)
        
        # Envoyer l'embed avec les contrôles du mode raid
        await interaction.response.send_message(
            embed=embed,
            view=self.raid_mode_view,
            ephemeral=False  # Rendre visible pour tous les modérateurs
        )
        
    @app_commands.command(name="backup", description="Créer ou restaurer une sauvegarde du serveur")
    @app_commands.default_permissions(administrator=True)
    async def backup_cmd(self, interaction: discord.Interaction, action: typing.Literal["create", "restore"]):
        """Commande pour créer ou restaurer des sauvegardes de serveur"""
        await interaction.response.defer(ephemeral=True)
        
        if action == "create":
            # Créer une nouvelle sauvegarde
            backup_result = await self.create_server_backup(interaction.guild)
            
            if backup_result:
                embed = discord.Embed(
                    title="✅ Sauvegarde effectuée",
                    description="Une sauvegarde complète du serveur a été créée.",
                    color=discord.Color.green()
                )
                
                # Statistiques sur la sauvegarde
                channels_count = len(backup_result.get('channels', []))
                roles_count = len(backup_result.get('roles', []))
                
                embed.add_field(name="Salons sauvegardés", value=str(channels_count))
                embed.add_field(name="Rôles sauvegardés", value=str(roles_count))
                embed.add_field(name="Date", value=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
                
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send("❌ Erreur lors de la création de la sauvegarde.", ephemeral=True)
        
        elif action == "restore":
            # Montrer une confirmation d'abord
            embed = discord.Embed(
                title="⚠️ Confirmation de restauration",
                description="Êtes-vous sûr de vouloir restaurer le serveur à partir de la dernière sauvegarde? Cette action ne peut pas être annulée.",
                color=discord.Color.orange()
            )
            
            # Obtenir les infos de sauvegarde si disponibles
            if str(interaction.guild.id) in self.security.backups:
                backup = self.security.backups[str(interaction.guild.id)]
                backup_time = datetime.datetime.fromtimestamp(backup.get('timestamp', 0)).strftime("%d/%m/%Y %H:%M:%S")
                
                embed.add_field(name="Date de la sauvegarde", value=backup_time)
                embed.add_field(name="Canaux", value=str(len(backup.get('channels', []))))
                embed.add_field(name="Rôles", value=str(len(backup.get('roles', []))))
            else:
                embed.description = "Aucune sauvegarde disponible pour ce serveur. Créez d'abord une sauvegarde."
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Créer des boutons confirmer/annuler
            view = discord.ui.View(timeout=60)
            
            async def confirm_callback(confirm_interaction):
                if confirm_interaction.user.id != interaction.user.id:
                    await confirm_interaction.response.send_message("Vous n'êtes pas autorisé à utiliser ces boutons.", ephemeral=True)
                    return
                
                await confirm_interaction.response.defer(ephemeral=True)
                
                # Démarrer la restauration
                success_channels = await self.restore_channels_from_backup(interaction.guild)
                success_roles = await self.restore_roles_from_backup(interaction.guild)
                
                if success_channels and success_roles:
                    result_embed = discord.Embed(
                        title="✅ Restauration terminée",
                        description="Le serveur a été restauré à partir de la sauvegarde.",
                        color=discord.Color.green()
                    )
                elif success_channels or success_roles:
                    result_embed = discord.Embed(
                        title="⚠️ Restauration partielle",
                        description="Le serveur a été partiellement restauré à partir de la sauvegarde.",
                        color=discord.Color.gold()
                    )
                    
                    if not success_channels:
                        result_embed.add_field(name="Erreur canaux", value="La restauration des canaux a échoué.")
                    
                    if not success_roles:
                        result_embed.add_field(name="Erreur rôles", value="La restauration des rôles a échoué.")
                else:
                    result_embed = discord.Embed(
                        title="❌ Échec de restauration",
                        description="La restauration du serveur a échoué. Veuillez consulter les logs pour plus de détails.",
                        color=discord.Color.red()
                    )
                
                await confirm_interaction.followup.send(embed=result_embed, ephemeral=True)
                
                # Désactiver les boutons
                view.clear_items()
                await interaction.edit_original_response(view=view)
            
            async def cancel_callback(cancel_interaction):
                if cancel_interaction.user.id != interaction.user.id:
                    await cancel_interaction.response.send_message("Vous n'êtes pas autorisé à utiliser ces boutons.", ephemeral=True)
                    return
                
                await cancel_interaction.response.send_message("Restauration annulée.", ephemeral=True)
                
                # Désactiver les boutons
                view.clear_items()
                await interaction.edit_original_response(view=view)
            
            # Ajouter les boutons à la vue
            confirm_button = discord.ui.Button(label="Confirmer", style=discord.ButtonStyle.danger)
            confirm_button.callback = confirm_callback
            view.add_item(confirm_button)
            
            cancel_button = discord.ui.Button(label="Annuler", style=discord.ButtonStyle.secondary)
            cancel_button.callback = cancel_callback
            view.add_item(cancel_button)
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    
                             duration: int, threshold: int = None, timeframe: int = None):
        """Commande pour configurer les paramètres du mode raid"""
        # Valider les paramètres
        if duration <= 0:
            await interaction.response.send_message("La durée doit être positive.", ephemeral=True)
            return
        
        if threshold is not None and threshold <= 0:
            await interaction.response.send_message("Le seuil doit être positif.", ephemeral=True)
            return
            
        if timeframe is not None and timeframe <= 0:
            await interaction.response.send_message("La période doit être positive.", ephemeral=True)
            return
        
        # Mettre à jour la configuration
        self.security.raid_mode_action = action
        self.security.raid_mode_duration = duration
        
        if threshold is not None:
            self.security.raid_detection_threshold = threshold
            
        if timeframe is not None:
            self.security.raid_detection_timeframe = timeframe
        
        # Sauvegarder la configuration
        self.security.save_config()
        
        # Message de confirmation
        embed = discord.Embed(
            title="✅ Configuration du mode raid mise à jour",
            description="Les paramètres du mode raid ont été mis à jour avec succès.",
            color=discord.Color.green()
        )
        
        embed.add_field(name="Action", value=self.get_raid_mode_action_description())
        embed.add_field(name="Durée", value=self.format_time_duration(duration))
        
        if threshold is not None and timeframe is not None:
            embed.add_field(
                name="Seuil de détection", 
                value=f"{threshold} membres en {timeframe}s", 
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        # Logger le changement
        await self.log_security_action(
            interaction.guild,
            "Configuration du mode raid mise à jour",
            interaction.user,
            discord.Color.blue(),
            fields=[
                {"name": "Action", "value": action},
                {"name": "Durée", "value": self.format_time_duration(duration)},
                {"name": "Seuil", "value": f"{threshold} membres en {timeframe}s" if threshold and timeframe else "Inchangé"}
            ]
        )
    
    @app_commands.command(name="blacklist", description="Gérer la liste noire des domaines")
    @app_commands.default_permissions(administrator=True)
    async def blacklist_cmd(self, interaction: discord.Interaction, action: typing.Literal["add", "remove", "view"], domain: str = None):
        """Commande pour gérer la liste noire des domaines"""
        if action == "add":
            if not domain:
                # Afficher le modal pour ajouter un domaine
                modal = BlacklistDomainModal(self)
                await interaction.response.send_modal(modal)
                return
            else:
                # Ajouter le domaine directement
                domain = domain.lower()
                
                # Vérifier que c'est un domaine valide
                if not re.match(r'^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$', domain):
                    await interaction.response.send_message("Format de domaine invalide. Veuillez entrer un nom de domaine valide (ex: exemple.com).", ephemeral=True)
                    return
                
                if domain in self.security.blacklisted_domains:
                    await interaction.response.send_message("Ce domaine est déjà dans la liste noire.", ephemeral=True)
                    return
                
                # Ajouter le domaine à la liste noire
                self.security.blacklisted_domains.add(domain)
                self.security.save_config()
                
                # Message de confirmation
                await interaction.response.send_message(f"Domaine `{domain}` ajouté à la liste noire.", ephemeral=True)
                
                # Logger l'action
                await self.log_security_action(
                    interaction.guild,
                    f"Domaine ajouté à la liste noire",
                    interaction.user,
                    discord.Color.red(),
                    fields=[{"name": "Domaine", "value": domain}]
                )
        
        elif action == "remove":
            if not domain:
                # Afficher une vue avec un menu de sélection pour supprimer des domaines
                await interaction.response.send_message(
                    "Sélectionnez le domaine à retirer de la liste noire:",
                    view=BlacklistRemoveView(self),
                    ephemeral=True
                )
                return
            else:
                # Supprimer le domaine directement
                domain = domain.lower()
                
                if domain not in self.security.blacklisted_domains:
                    await interaction.response.send_message("Ce domaine n'est pas dans la liste noire.", ephemeral=True)
                    return
                
                # Supprimer le domaine
                self.security.blacklisted_domains.remove(domain)
                self.security.save_config()
                
                # Message de confirmation
                await interaction.response.send_message(f"Domaine `{domain}` retiré de la liste noire.", ephemeral=True)
                
                # Logger l'action
                await self.log_security_action(
                    interaction.guild,
                    f"Domaine retiré de la liste noire",
                    interaction.user,
                    discord.Color.green(),
                    fields=[{"name": "Domaine", "value": domain}]
                )
        
        elif action == "view":
            await interaction.response.defer(ephemeral=True)
            
            if not self.security.blacklisted_domains:
                await interaction.followup.send("Aucun domaine n'est actuellement sur la liste noire.", ephemeral=True)
                return
            
            # Créer un embed avec les domaines blacklistés
            embed = discord.Embed(
                title="⛔ Domaines sur liste noire",
                description=f"Il y a actuellement {len(self.security.blacklisted_domains)} domaines sur la liste noire:",
                color=discord.Color.red()
            )
            
            domains_text = "\n".join(sorted(self.security.blacklisted_domains))
            
            # Diviser en morceaux si nécessaire
            if len(domains_text) > 1024:
                chunks = [domains_text[i:i+1024] for i in range(0, len(domains_text), 1024)]
                for i, chunk in enumerate(chunks):
                    embed.add_field(name=f"Domaines (partie {i+1})", value=f"```\n{chunk}\n```", inline=False)
            else:
                embed.add_field(name="Domaines", value=f"```\n{domains_text}\n```", inline=False)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @app_commands.command(name="trustuser", description="Gérer les utilisateurs de confiance")
    @app_commands.default_permissions(administrator=True)
    async def trust_user_cmd(self, interaction: discord.Interaction, action: typing.Literal["add", "remove", "view"], user: discord.Member = None):
        """Commande pour gérer les utilisateurs de confiance"""
        if action == "add":
            if not user:
                # Afficher le modal pour ajouter un utilisateur
                modal = TrustedUserModal(self)
                await interaction.response.send_modal(modal)
                return
            else:
                # Ajouter l'utilisateur directement
                user_id = str(user.id)
                
                if user_id in self.security.trusted_users:
                    await interaction.response.send_message(f"{user.mention} est déjà dans la liste des utilisateurs de confiance.", ephemeral=True)
                    return
                
                # Ajouter l'utilisateur à la liste des utilisateurs de confiance
                self.security.trusted_users.add(user_id)
                self.security.save_config()
                
                # Message de confirmation
                await interaction.response.send_message(f"{user.mention} a été ajouté à la liste des utilisateurs de confiance.", ephemeral=True)
                
                # Logger l'action
                await self.log_security_action(
                    interaction.guild,
                    f"Utilisateur ajouté à la liste de confiance",
                    interaction.user,
                    discord.Color.green(),
                    fields=[{"name": "Utilisateur", "value": f"{user.mention} ({user.name})"}]
                )
        
        elif action == "remove":
            if not user:
                # Afficher une vue avec un menu de sélection pour supprimer des utilisateurs
                await interaction.response.send_message(
                    "Sélectionnez l'utilisateur à retirer de la liste de confiance:",
                    view=TrustedUserRemoveView(self, interaction.guild),
                    ephemeral=True
                )
                return
            else:
                # Supprimer l'utilisateur directement
                user_id = str(user.id)
                
                if user_id not in self.security.trusted_users:
                    await interaction.response.send_message(f"{user.mention} n'est pas dans la liste des utilisateurs de confiance.", ephemeral=True)
                    return
                
                # Supprimer l'utilisateur
                self.security.trusted_users.remove(user_id)
                self.security.save_config()
                
                # Message de confirmation
                await interaction.response.send_message(f"{user.mention} a été retiré de la liste des utilisateurs de confiance.", ephemeral=True)
                
                # Logger l'action
                await self.log_security_action(
                    interaction.guild,
                    f"Utilisateur retiré de la liste de confiance",
                    interaction.user,
                    discord.Color.orange(),
                    fields=[{"name": "Utilisateur", "value": f"{user.mention} ({user.name})"}]
                )
        
        elif action == "view":
            await interaction.response.defer(ephemeral=True)
            
            if not self.security.trusted_users:
                await interaction.followup.send("Aucun utilisateur n'est actuellement dans la liste de confiance.", ephemeral=True)
                return
            
            # Créer un embed avec les utilisateurs de confiance
            embed = discord.Embed(
                title="✅ Utilisateurs de confiance",
                description=f"Il y a actuellement {len(self.security.trusted_users)} utilisateurs de confiance:",
                color=discord.Color.green()
            )
            
            # Obtenir les objets utilisateur à partir des IDs
            trusted_user_mentions = []
            for user_id in self.security.trusted_users:
                user = interaction.guild.get_member(int(user_id))
                if user:
                    trusted_user_mentions.append(f"{user.mention} ({user.name})")
                else:
                    trusted_user_mentions.append(f"ID: {user_id} (utilisateur non trouvé)")
            
            users_text = "\n".join(trusted_user_mentions)
            
            # Diviser en morceaux si nécessaire
            if len(users_text) > 1024:
                chunks = [users_text[i:i+1024] for i in range(0, len(users_text), 1024)]
                for i, chunk in enumerate(chunks):
                    embed.add_field(name=f"Utilisateurs (partie {i+1})", value=chunk, inline=False)
            else:
                embed.add_field(name="Utilisateurs", value=users_text, inline=False)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
    @app_commands.command(name="test_captcha", description="Tester le système de captcha")
    @app_commands.default_permissions(administrator=True)
    async def test_captcha_cmd(self, interaction: discord.Interaction):
        """Commande pour tester le système de captcha"""
        await interaction.response.defer(ephemeral=True)
        
        # Vérifier que le raid mode est configuré sur captcha
        if self.security.raid_mode_action != "captcha":
            await interaction.followup.send("Pour tester le captcha, configurez d'abord le mode raid sur 'captcha' avec la commande `/config_raid captcha <durée> <seuil> <période>`", ephemeral=True)
            return
        
        try:
            # Générer un captcha de test
            captcha_code = CaptchaGenerator.generate_captcha_code()
            
            # Créer un embed pour afficher le captcha
            embed = discord.Embed(
                title="🧩 Test du Captcha",
                description="Voici à quoi ressemblerait le captcha envoyé aux nouveaux membres pendant le mode raid:",
                color=discord.Color.blue()
            )
            
            embed.add_field(name="Code généré", value=f"`{captcha_code}`")
            
            # Créer une vue avec un champ de texte pour tester la vérification
            class CaptchaTestView(discord.ui.View):
                def __init__(self, code):
                    super().__init__(timeout=300)  # 5 minutes
                    self.code = code
                
                @discord.ui.button(label="Vérifier le code", style=discord.ButtonStyle.primary)
                async def verify_button(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                    # Créer un modal pour entrer le code
                    class CaptchaModal(discord.ui.Modal, title="Vérification Captcha"):
                        code_input = discord.ui.TextInput(
                            label="Code Captcha",
                            placeholder="Entrez le code affiché ci-dessus",
                            required=True
                        )
                        
                        def __init__(self, code):
                            super().__init__()
                            self.code = code
                        
                        async def on_submit(self, modal_interaction: discord.Interaction):
                            if self.code_input.value == self.code:
                                await modal_interaction.response.send_message("✅ Code correct! Le membre aurait été vérifié.", ephemeral=True)
                            else:
                                await modal_interaction.response.send_message("❌ Code incorrect! Le membre devrait réessayer.", ephemeral=True)
                    
                    await button_interaction.response.send_modal(CaptchaModal(self.code))
            
            await interaction.followup.send(embed=embed, view=CaptchaTestView(captcha_code), ephemeral=True)
            
            # Montrer aussi comment serait l'affichage HTML (de manière textuelle)
            captcha_html = CaptchaGenerator.generate_captcha_html(captcha_code)
            await interaction.followup.send("Le HTML du captcha ressemblerait à ceci (représentation partielle):\n```html\n" + captcha_html[:500] + "...\n```", ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"Erreur lors du test du captcha: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(SecuritySystem(bot))