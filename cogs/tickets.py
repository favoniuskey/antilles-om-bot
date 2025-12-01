import discord
from discord.ext import commands
from discord.ui import Modal, TextInput, Button, View
from datetime import datetime
import json
import asyncio
import os
import logging
from typing import Dict, List, Optional

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("utils/logs/tickets.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("tickets")

class TicketCache:
    def __init__(self):
        self.tickets = {}
        self.ensure_directory()
        self.load_from_file()

    def ensure_directory(self):
        os.makedirs("utils", exist_ok=True)
        os.makedirs("utils/logs", exist_ok=True)

    def save_to_file(self):
        try:
            with open('utils/tickets.json', 'w') as f:
                json.dump(self.tickets, f, indent=4)
            logger.info(f"Ticket cache saved. Current tickets: {len(self.tickets)}")
        except Exception as e:
            logger.error(f"Error saving ticket cache: {e}")

    def add_ticket(self, channel_id, ticket_data):
        self.tickets[str(channel_id)] = ticket_data
        self.save_to_file()
        logger.info(f"Added ticket {channel_id} of type {ticket_data['type']}")

    def remove_ticket(self, channel_id):
        if str(channel_id) in self.tickets:
            ticket_type = self.tickets[str(channel_id)]['type']
            del self.tickets[str(channel_id)]
            self.save_to_file()
            logger.info(f"Removed ticket {channel_id} of type {ticket_type}")

    def get_user_tickets(self, user_id):
        return [ticket for channel_id, ticket in self.tickets.items() 
                if ticket['opener_id'] == user_id and ticket['status'] != 'deleted']
    
    def get_user_tickets_by_type(self, user_id, ticket_type):
        return [ticket for channel_id, ticket in self.tickets.items() 
                if ticket['opener_id'] == user_id and ticket['type'] == ticket_type and ticket['status'] != 'deleted']
    
    def cleanup_deleted_tickets(self):
        """Nettoie les tickets qui sont marqués comme supprimés"""
        to_remove = []
        for channel_id in self.tickets.keys():
            if self.tickets[channel_id]['status'] == 'deleted':
                to_remove.append(channel_id)
        
        for channel_id in to_remove:
            del self.tickets[channel_id]
        
        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} deleted tickets")
            self.save_to_file()

    def load_from_file(self):
        try:
            with open('utils/tickets.json', 'r') as f:
                try:
                    self.tickets = json.load(f)
                    self.cleanup_deleted_tickets()
                    logger.info(f"Loaded {len(self.tickets)} tickets from file")
                except json.JSONDecodeError:
                    self.tickets = {}
                    logger.warning("JSON decode error, initialized empty ticket cache")
        except FileNotFoundError:
            self.tickets = {}
            self.save_to_file()
            logger.info("Tickets file not found, created new one")

class TicketView(discord.ui.View):
    def __init__(self, ticket_type, cog):
        super().__init__(timeout=None)
        self.ticket_type = ticket_type
        self.cog = cog
        
        # Utiliser un custom_id unique pour chaque type de ticket
        custom_id = f"open_{ticket_type}_ticket_button"
        
        # Styler le bouton en fonction du type de ticket
        style = discord.ButtonStyle.primary if ticket_type == "atc" else discord.ButtonStyle.success
        emoji = "🛩️" if ticket_type == "atc" else "🛟"
        
        # Supprimer l'ancien bouton si présent
        for item in self.children.copy():
            self.remove_item(item)
        
        # Ajouter le bouton correctement configuré
        self.add_item(discord.ui.Button(
            label=f"Ouvrir un ticket {ticket_type.upper()}", 
            style=style, 
            custom_id=custom_id,
            emoji=emoji
        ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    @discord.ui.button(label="", style=discord.ButtonStyle.primary, custom_id="placeholder")
    async def _placeholder(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ce bouton ne sera jamais utilisé, il est remplacé lors de l'initialisation
        pass

class TicketControlView(discord.ui.View):
    def __init__(self, ticket_type, opener_id, cog):
        super().__init__(timeout=None)
        self.ticket_type = ticket_type
        self.opener_id = opener_id
        self.cog = cog
        
        # Custom ID unique pour chaque action et type de ticket
        close_id = f"close_{ticket_type}_ticket"
        reopen_id = f"reopen_{ticket_type}_ticket"
        delete_id = f"delete_{ticket_type}_ticket"
        transcript_id = f"transcript_{ticket_type}_ticket"
        
        # Supprimer les boutons par défaut
        for item in self.children.copy():
            self.remove_item(item)
            
        # Ajouter les boutons personnalisés
        self.add_item(discord.ui.Button(
            label="🔒 Fermer", 
            style=discord.ButtonStyle.danger, 
            custom_id=close_id
        ))
        
        self.add_item(discord.ui.Button(
            label="🔓 Réouvrir", 
            style=discord.ButtonStyle.success, 
            custom_id=reopen_id
        ))
        
        self.add_item(discord.ui.Button(
            label="📑 Transcription", 
            style=discord.ButtonStyle.secondary, 
            custom_id=transcript_id
        ))
        
        self.add_item(discord.ui.Button(
            label="⛔ Supprimer", 
            style=discord.ButtonStyle.red, 
            custom_id=delete_id
        ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    @discord.ui.button(label="", style=discord.ButtonStyle.primary, custom_id="placeholder2")
    async def _placeholder(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ce bouton ne sera jamais utilisé, il est remplacé lors de l'initialisation
        pass

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ticket_cache = TicketCache()
        
        # Constantes
        self.ATC_ROLE_ID = 1228450258254827691
        self.ADMIN_ROLES = [1297138129920196639, 1297148016725332068, 1309969291822760038]
        self.ATC_CATEGORY_ID = 1313797047844995093
        self.SUPPORT_CATEGORY_ID = 1313796797562490902
        
        # Configuration des embeds
        self.COLORS = {
            "atc": discord.Color.blue(),
            "support": discord.Color.green(),
            "closed": discord.Color.red(),
            "reopened": discord.Color.teal(),
            "deleted": discord.Color.dark_red()
        }
        
        # Initialiser les vues persistantes
        bot.loop.create_task(self.init_persistent_views())

    async def init_persistent_views(self):
        # Attendre que le bot soit prêt
        await self.bot.wait_until_ready()
        
        # Restaurer les vues persistantes
        logger.info("Initializing persistent views")
        
        # Créer et ajouter les vues de ticket (boutons pour ouvrir)
        atc_view = TicketView("atc", self)
        support_view = TicketView("support", self)
        
        # Ajouter les gestionnaires d'interaction pour les boutons de création de tickets
        self.bot.add_view(atc_view)
        self.bot.add_view(support_view)
        
        # Restaurer les vues de contrôle pour chaque ticket existant
        control_views_added = 0
        for channel_id, ticket_data in self.ticket_cache.tickets.items():
            control_view = TicketControlView(ticket_data['type'], ticket_data['opener_id'], self)
            self.bot.add_view(control_view)
            control_views_added += 1
        
        logger.info(f"Added {control_views_added} ticket control views")
        
        # Ajouter des gestionnaires d'événements pour les boutons spécifiques
        self.bot.add_listener(self.handle_ticket_interactions, 'on_interaction')
    
    async def handle_ticket_interactions(self, interaction: discord.Interaction):
        if not interaction.data or 'custom_id' not in interaction.data:
            return
        
        custom_id = interaction.data['custom_id']
        
        # Gestion des boutons d'ouverture de ticket
        if custom_id == "open_atc_ticket_button":
            await interaction.response.defer(ephemeral=True)
            await self.create_ticket(interaction, "atc")
            return
            
        elif custom_id == "open_support_ticket_button":
            await interaction.response.defer(ephemeral=True)
            await self.create_ticket(interaction, "support")
            return
            
        # Gestion des boutons de contrôle
        if not interaction.channel:
            return
            
        channel_id = str(interaction.channel.id)
        ticket_data = self.ticket_cache.tickets.get(channel_id)
        
        if not ticket_data:
            return
            
        ticket_type = ticket_data['type']
        
        # Gestion de la fermeture
        if custom_id == f"close_{ticket_type}_ticket":
            await interaction.response.defer()
            if interaction.user.id != ticket_data['opener_id'] and not any(role.id in self.ADMIN_ROLES for role in interaction.user.roles):
                return await interaction.followup.send("❌ Vous n'avez pas la permission de fermer ce ticket.", ephemeral=True)
            
            if ticket_data['status'] == 'closed':
                return await interaction.followup.send("❌ Ce ticket est déjà fermé.", ephemeral=True)
            
            await self.close_ticket(interaction.channel, interaction.user, ticket_data)
            await interaction.followup.send("✅ Ticket fermé.")
            
        # Gestion de la réouverture
        elif custom_id == f"reopen_{ticket_type}_ticket":
            await interaction.response.defer()
            if not any(role.id in self.ADMIN_ROLES for role in interaction.user.roles):
                return await interaction.followup.send("❌ Vous n'avez pas la permission de réouvrir ce ticket.", ephemeral=True)
            
            if ticket_data['status'] != 'closed':
                return await interaction.followup.send("❌ Ce ticket n'est pas fermé.", ephemeral=True)
            
            await self.reopen_ticket(interaction.channel, ticket_data)
            await interaction.followup.send("✅ Ticket réouvert.")
            
        # Gestion de la transcription
        elif custom_id == f"transcript_{ticket_type}_ticket":
            await interaction.response.defer()
            await self.create_transcript(interaction, ticket_data)
            
        # Gestion de la suppression
        elif custom_id == f"delete_{ticket_type}_ticket":
            await interaction.response.defer()
            if not any(role.id in self.ADMIN_ROLES for role in interaction.user.roles):
                return await interaction.followup.send("❌ Vous n'avez pas la permission de supprimer ce ticket.", ephemeral=True)
            
            confirm_view = discord.ui.View(timeout=30)
            confirm_view.add_item(discord.ui.Button(label="✅ Confirmer", style=discord.ButtonStyle.danger, custom_id="confirm_delete"))
            confirm_view.add_item(discord.ui.Button(label="❌ Annuler", style=discord.ButtonStyle.secondary, custom_id="cancel_delete"))
            
            confirm_msg = await interaction.followup.send("⚠️ Êtes-vous sûr de vouloir supprimer ce ticket ? Cette action est irréversible.", view=confirm_view)
            
            try:
                confirm_interaction = await self.bot.wait_for(
                    "interaction",
                    check=lambda i: i.data.get("custom_id") in ["confirm_delete", "cancel_delete"] and i.user.id == interaction.user.id,
                    timeout=30
                )
                
                if confirm_interaction.data.get("custom_id") == "confirm_delete":
                    await confirm_interaction.response.defer()
                    await self.delete_ticket(interaction.channel, interaction.user, ticket_data)
                else:
                    await confirm_interaction.response.defer()
                    await confirm_interaction.followup.send("❌ Suppression annulée.", ephemeral=True)
                    
                await confirm_msg.delete()
            except asyncio.TimeoutError:
                await confirm_msg.edit(content="⏱️ Délai d'attente dépassé. Suppression annulée.", view=None)

    async def create_ticket(self, interaction: discord.Interaction, ticket_type):
        try:
            logger.info(f"Creating {ticket_type} ticket for {interaction.user.name} ({interaction.user.id})")
            
            # Vérification des tickets déjà existants pour cet utilisateur et ce type
            existing_tickets = self.ticket_cache.get_user_tickets_by_type(interaction.user.id, ticket_type)
            
            if existing_tickets:
                return await interaction.followup.send(f"❌ Vous avez déjà un ticket {ticket_type.upper()} actif.", ephemeral=True)
            
            # Récupération de la catégorie appropriée
            category_id = self.ATC_CATEGORY_ID if ticket_type == 'atc' else self.SUPPORT_CATEGORY_ID
            category = interaction.guild.get_channel(category_id)
            
            if not category:
                logger.error(f"Category {category_id} not found")
                return await interaction.followup.send("❌ Erreur: Catégorie introuvable.", ephemeral=True)
            
            # Création du nom du canal
            timestamp = datetime.now().strftime("%m%d")
            channel_name = f"{ticket_type}-{interaction.user.name}-{timestamp}"
            
            # Configuration des permissions du canal
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            
            # Permissions spécifiques selon le type de ticket
            if ticket_type == 'atc':
                atc_role = interaction.guild.get_role(self.ATC_ROLE_ID)
                if atc_role:
                    overwrites[atc_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            # Permissions pour les administrateurs
            for role_id in self.ADMIN_ROLES:
                role = interaction.guild.get_role(role_id)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            # Création du canal
            channel = await interaction.guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites
            )
            
            # Enregistrement des données du ticket
            ticket_data = {
                'opener_id': interaction.user.id,
                'type': ticket_type,
                'status': 'open',
                'created_at': datetime.now().isoformat(),
                'closed_by': None,
                'closed_at': None,
                'deleted_by': None,
                'deleted_at': None
            }
            
            self.ticket_cache.add_ticket(channel.id, ticket_data)
            
            # Création de l'embed initial
            title = "🛩️ Ticket ATC" if ticket_type == 'atc' else "🛟 Ticket Support"
            color = self.COLORS[ticket_type]
            
            embed = discord.Embed(
                title=f"{title} - Antilles",
                description=f"Bienvenue {interaction.user.mention} dans votre ticket {ticket_type.upper()}",
                color=color,
                timestamp=datetime.now()
            )
            
            if ticket_type == "atc":
                embed.add_field(name="📋 Instructions", value="Décrivez votre demande de couverture ATC en précisant:\n• Date et heure (UTC)\n• Secteurs demandés\n• Événement concerné (si applicable)", inline=False)
            else:
                embed.add_field(name="📋 Instructions", value="Décrivez votre demande de support en détaillant:\n• Le problème rencontré\n• Les étapes déjà essayées\n• Toute information utile à la résolution", inline=False)
            
            embed.add_field(name="⚙️ Gestion", value="Utilisez les boutons ci-dessous pour gérer ce ticket", inline=False)
            embed.set_footer(text=f"ID: {interaction.user.id} • ATC Antilles")
            
            # Envoi du message initial avec les boutons de contrôle
            control_view = TicketControlView(ticket_type, interaction.user.id, self)
            
            if ticket_type == 'atc':
                initial_message = await channel.send(f"<@{interaction.user.id}> <@&{self.ATC_ROLE_ID}>", embed=embed, view=control_view)
            else:
                admin_mentions = ' '.join(f"<@&{role_id}>" for role_id in self.ADMIN_ROLES)
                initial_message = await channel.send(f"<@{interaction.user.id}> {admin_mentions}", embed=embed, view=control_view)
            
            # Épingler le message initial
            await initial_message.pin()
            
            # Notifier l'utilisateur
            await interaction.followup.send(f"✅ Votre ticket a été créé: {channel.mention}", ephemeral=True)
            
            logger.info(f"Successfully created {ticket_type} ticket in channel {channel.id}")
            
        except Exception as e:
            logger.error(f"Error creating ticket: {str(e)}", exc_info=True)
            await interaction.followup.send(f"❌ Une erreur est survenue lors de la création du ticket: {str(e)}", ephemeral=True)

    async def close_ticket(self, channel, user, ticket_data):
        logger.info(f"Closing ticket {channel.id} by {user.name} ({user.id})")
        
        ticket_data['status'] = 'closed'
        ticket_data['closed_by'] = user.id
        ticket_data['closed_at'] = datetime.now().isoformat()
        self.ticket_cache.save_to_file()
        
        embed = discord.Embed(
            title="🔒 Ticket Fermé",
            description=f"Ce ticket a été fermé par {user.mention}",
            color=self.COLORS["closed"],
            timestamp=datetime.now()
        )
        
        embed.add_field(name="ℹ️ Information", value="Le ticket est maintenant en lecture seule. Un administrateur peut le réouvrir si nécessaire.", inline=False)
        embed.set_footer(text="ATC Antilles - Service de tickets")
        
        await channel.send(embed=embed)
        
        # Mettre à jour les permissions pour empêcher l'envoi de messages
        for target, overwrites in channel.overwrites.items():
            if isinstance(target, (discord.Member, discord.Role)) and target != self.bot.user:
                overwrites.send_messages = False
                await channel.set_permissions(target, overwrite=overwrites)
        
        # Mettre à jour le nom du canal pour indiquer qu'il est fermé
        try:
            new_name = f"🔒-{channel.name}" if not channel.name.startswith("🔒-") else channel.name
            await channel.edit(name=new_name)
        except:
            logger.warning(f"Failed to rename channel {channel.id}")

    async def reopen_ticket(self, channel, ticket_data):
        logger.info(f"Reopening ticket {channel.id}")
        
        ticket_data['status'] = 'open'
        ticket_data['closed_by'] = None
        ticket_data['closed_at'] = None
        self.ticket_cache.save_to_file()
        
        embed = discord.Embed(
            title="🔓 Ticket Réouvert",
            description="Ce ticket a été réouvert et est à nouveau actif.",
            color=self.COLORS["reopened"],
            timestamp=datetime.now()
        )
        
        embed.add_field(name="ℹ️ Information", value="Vous pouvez maintenant continuer la conversation.", inline=False)
        embed.set_footer(text="ATC Antilles - Service de tickets")
        
        await channel.send(embed=embed)
        
        # Rétablir les permissions d'envoi de messages
        for target, overwrites in channel.overwrites.items():
            if isinstance(target, (discord.Member, discord.Role)) and target != self.bot.user:
                overwrites.send_messages = True
                await channel.set_permissions(target, overwrite=overwrites)
        
        # Mettre à jour le nom du canal
        try:
            new_name = channel.name.replace("🔒-", "")
            await channel.edit(name=new_name)
        except:
            logger.warning(f"Failed to rename channel {channel.id}")

    async def create_transcript(self, interaction: discord.Interaction, ticket_data):
        logger.info(f"Creating transcript for ticket {interaction.channel.id}")
        
        await interaction.followup.send("📝 Création de la transcription en cours...")
        
        channel = interaction.channel
        messages = []
        
        async for message in channel.history(limit=500, oldest_first=True):
            if message.author.bot and message.author.id != self.bot.user.id:
                continue
                
            content = message.content
            if not content and message.embeds:
                content = f"[Embed: {message.embeds[0].title if message.embeds[0].title else 'Sans titre'}]"
                
            timestamp = message.created_at.strftime("%d/%m/%Y %H:%M:%S")
            messages.append(f"[{timestamp}] {message.author.name}: {content}")
        
        if not messages:
            return await interaction.followup.send("❌ Aucun message trouvé pour créer une transcription.", ephemeral=True)
        
        # Créer le contenu de la transcription
        ticket_type = ticket_data['type'].upper()
        opener = await self.bot.fetch_user(ticket_data['opener_id'])
        opener_name = opener.name if opener else "Utilisateur inconnu"
        
        transcript_content = [
            f"=== TRANSCRIPTION TICKET {ticket_type} ===",
            f"Ouvert par: {opener_name} (ID: {ticket_data['opener_id']})",
            f"Date d'ouverture: {datetime.fromisoformat(ticket_data['created_at']).strftime('%d/%m/%Y %H:%M:%S')}",
            f"Statut: {ticket_data['status'].upper()}",
            "="*40,
            ""
        ] + messages
        
        transcript_text = "\n".join(transcript_content)
        
        # Créer le fichier temporairement
        os.makedirs("utils/tmp", exist_ok=True)
        file_name = f"utils/tmp/transcript_{ticket_type}_{interaction.channel.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(transcript_text)
        
        # Créer un embed pour la transcription
        embed = discord.Embed(
            title="📑 Transcription du Ticket",
            description=f"Transcription du ticket {channel.mention}",
            color=self.COLORS[ticket_data['type']],
            timestamp=datetime.now()
        )
        
        embed.add_field(name="Type", value=ticket_type, inline=True)
        embed.add_field(name="Créé par", value=opener.mention if opener else f"ID: {ticket_data['opener_id']}", inline=True)
        embed.add_field(name="Statut", value=ticket_data['status'].upper(), inline=True)
        
        # Envoyer le fichier en MP à l'utilisateur qui a demandé la transcription
        try:
            with open(file_name, "rb") as f:
                transcript_file = discord.File(f, filename=f"transcript_{channel.name}.txt")
                await interaction.user.send(embed=embed, file=transcript_file)
            
            # Notifier dans le canal du ticket que la transcription a été envoyée en MP
            await interaction.followup.send(f"✅ La transcription a été envoyée en message privé à {interaction.user.mention}.")
            
            # Si l'utilisateur est différent de celui qui a ouvert le ticket, envoyer aussi au créateur du ticket
            if opener and interaction.user.id != ticket_data['opener_id']:
                try:
                    with open(file_name, "rb") as f:
                        transcript_file = discord.File(f, filename=f"transcript_{channel.name}.txt")
                        await opener.send(embed=embed, file=transcript_file)
                    await interaction.followup.send(f"✅ Une copie de la transcription a également été envoyée à {opener.mention}.")
                except Exception as e:
                    logger.warning(f"Failed to send transcript to ticket opener {ticket_data['opener_id']}: {e}")
        except Exception as e:
            logger.error(f"Error sending transcript to DM: {e}")
            # En cas d'échec, essayer de l'envoyer dans le canal
            with open(file_name, "rb") as f:
                transcript_file = discord.File(f, filename=f"transcript_{channel.name}.txt")
                await interaction.followup.send("❌ Impossible d'envoyer le transcript en message privé. Envoi dans ce canal à la place.")
                await interaction.followup.send(embed=embed, file=transcript_file)
        
        # Supprimer le fichier temporaire
        try:
            os.remove(file_name)
        except Exception as e:
            logger.warning(f"Failed to delete temporary transcript file: {e}")

    async def delete_ticket(self, channel, user, ticket_data):
        logger.info(f"Deleting ticket {channel.id} by {user.name} ({user.id})")
        
        ticket_data['status'] = 'deleted'
        ticket_data['deleted_by'] = user.id
        ticket_data['deleted_at'] = datetime.now().isoformat()
        
        # Calculer la durée du ticket
        created_at = datetime.fromisoformat(ticket_data['created_at'])
        duration = (datetime.now() - created_at).total_seconds() / 60
        
        # Sauvegarder une transcription avant la suppression
        try:
            messages = []
            async for message in channel.history(limit=500, oldest_first=True):
                timestamp = message.created_at.strftime("%d/%m/%Y %H:%M:%S")
                content = message.content if message.content else "[Embed ou contenu spécial]"
                messages.append(f"[{timestamp}] {message.author.name}: {content}")
            
            if messages:
                os.makedirs("utils/tickets_transcripts", exist_ok=True)
                
                transcript_path = f"utils/tickets_transcripts/transcript_{channel.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                with open(transcript_path, "w", encoding="utf-8") as f:
                    f.write(f"=== TRANSCRIPTION TICKET {ticket_data['type'].upper()} ===\n")
                    f.write(f"ID: {channel.id}\n")
                    f.write(f"Créé par: {ticket_data['opener_id']}\n")
                    f.write(f"Date: {created_at.strftime('%d/%m/%Y %H:%M:%S')}\n")
                    f.write("="*50 + "\n\n")
                    f.write("\n".join(messages))
                
                logger.info(f"Saved transcript to {transcript_path}")
        except Exception as e:
            logger.error(f"Error saving transcript: {e}")
        
        # Créer et envoyer un résumé au créateur du ticket
        try:
            opener = await self.bot.fetch_user(ticket_data['opener_id'])
            if opener:
                embed = discord.Embed(
                    title="📋 Résumé du Ticket",
                    description=f"Votre ticket {ticket_data['type'].upper()} a été supprimé",
                    color=self.COLORS[ticket_data['type']],
                    timestamp=datetime.now()
                )
                
                embed.add_field(name="📊 Informations", value=f"**Type:** {ticket_data['type'].upper()}\n**Durée:** {duration:.1f} minutes", inline=False)
                
                if ticket_data['closed_by']:
                    closer = await self.bot.fetch_user(ticket_data['closed_by'])
                    closer_name = closer.name if closer else "Inconnu"
                    closed_at = datetime.fromisoformat(ticket_data['closed_at']).strftime("%d/%m/%Y %H:%M")
                    embed.add_field(name="🔒 Fermé par", value=f"{closer_name} le {closed_at}", inline=False)
                
                if ticket_data['deleted_by']:
                    deleter = await self.bot.fetch_user(ticket_data['deleted_by'])
                    deleter_name = deleter.name if deleter else "Inconnu"
                    embed.add_field(name="⛔ Supprimé par", value=deleter_name, inline=False)
                
                embed.set_footer(text="ATC Antilles - Service de tickets")
                
                # Joindre la transcription au résumé
                transcript_path = None
                for file in os.listdir("utils/tickets_transcripts"):
                    if file.startswith(f"transcript_{channel.id}_"):
                        transcript_path = f"utils/tickets_transcripts/{file}"
                        break
                
                if transcript_path:
                    try:
                        with open(transcript_path, "rb") as f:
                            file = discord.File(f, filename=f"transcript_{channel.name}.txt")
                            await opener.send(embed=embed, file=file)
                    except:
                        logger.warning(f"Failed to send transcript with ticket summary to user {opener.id}")
                        await opener.send(embed=embed)
                else:
                    await opener.send(embed=embed)
        except Exception as e:
            logger.error(f"Error sending ticket summary: {e}")
        
        # Supprimer le ticket du cache et le canal
        self.ticket_cache.remove_ticket(channel.id)
        
        try:
            await channel.delete()
            logger.info(f"Channel {channel.id} deleted successfully")
        except Exception as e:
            logger.error(f"Error deleting channel {channel.id}: {e}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def ticket_atc(self, ctx):
        """Crée un message avec un bouton pour ouvrir un ticket ATC"""
        embed = discord.Embed(
            title="🛩️ Ticket ATC - Antilles",
            description="Utilisez ce bouton pour contacter notre équipe de contrôleurs aériens.\n\nPour une demande de couverture ATC ou toute question liée aux opérations aériennes.",
            color=self.COLORS["atc"]
        )
        embed.set_footer(text="ATC Antilles - Service de tickets")
        
        view = TicketView(ticket_type="atc", cog=self)
        await ctx.send(embed=embed, view=view)
        await ctx.message.delete()

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def ticket_support(self, ctx):
        """Crée un message avec un bouton pour ouvrir un ticket Support"""
        embed = discord.Embed(
            title="🛟 Ticket Support - Antilles",
            description="Utilisez ce bouton pour contacter notre équipe de support.\n\nPour toute demande d'aide, signalement de problème ou question générale.",
            color=self.COLORS["support"]
        )
        embed.set_footer(text="ATC Antilles - Service de tickets")
        
        view = TicketView(ticket_type="support", cog=self)
        await ctx.send(embed=embed, view=view)
        await ctx.message.delete()

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setup_tickets(self, ctx):
        """Configure les deux types de tickets avec une présentation améliorée"""
        await ctx.message.delete()
        
        # Créer l'embed pour les tickets ATC
        atc_embed = discord.Embed(
            title="🛩️ Service de Ticket ATC",
            description="Contactez notre équipe de contrôleurs aériens pour toute demande liée au contrôle du trafic aérien:",
            color=self.COLORS["atc"]
        )
        atc_embed.add_field(name="Utilisez ce service pour:", value="• Demander une couverture ATC\n• Questions sur les procédures ATC\n• Coordination d'événements aériens", inline=False)
        atc_embed.set_footer(text="ATC Antilles - Centre de contrôle")
        
        # Créer l'embed pour les tickets Support
        support_embed = discord.Embed(
            title="🛟 Service de Ticket Support",
            description="Contactez notre équipe de support pour toute question ou assistance technique:",
            color=self.COLORS["support"]
        )
        support_embed.add_field(name="Utilisez ce service pour:", value="• Assistance technique\n• Questions générales\n• Signalement de problèmes\n• Besoin d'aide", inline=False)
        support_embed.set_footer(text="ATC Antilles - Support technique")
        
        # Créer les vues avec les boutons
        atc_view = TicketView("atc", self)
        support_view = TicketView("support", self)
        
        # Envoyer les messages avec les embeds et les boutons
        await ctx.send(embed=atc_embed, view=atc_view)
        await ctx.send(embed=support_embed, view=support_view)
        
        await ctx.send("✅ Système de tickets configuré avec succès!", delete_after=5)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def ticket_stats(self, ctx):
        """Affiche des statistiques sur les tickets"""
        tickets = self.ticket_cache.tickets
        
        total_tickets = len(tickets)
        atc_tickets = len([t for t in tickets.values() if t['type'] == 'atc'])
        support_tickets = len([t for t in tickets.values() if t['type'] == 'support'])
        open_tickets = len([t for t in tickets.values() if t['status'] == 'open'])
        closed_tickets = len([t for t in tickets.values() if t['status'] == 'closed'])
        
        embed = discord.Embed(
            title="📊 Statistiques des Tickets",
            description=f"Vue d'ensemble du système de tickets",
            color=discord.Color.gold(),
            timestamp=datetime.now()
        )
        
        embed.add_field(name="Total des tickets", value=str(total_tickets), inline=True)
        embed.add_field(name="Tickets ATC", value=str(atc_tickets), inline=True)
        embed.add_field(name="Tickets Support", value=str(support_tickets), inline=True)
        embed.add_field(name="Tickets ouverts", value=str(open_tickets), inline=True)
        embed.add_field(name="Tickets fermés", value=str(closed_tickets), inline=True)
        
        embed.set_footer(text="ATC Antilles - Système de tickets")
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Tickets(bot))