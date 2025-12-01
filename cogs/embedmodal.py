import discord
from discord.ext import commands, tasks
import asyncio
from discord.ui import Modal, TextInput, Button, View
import io
import aiohttp
import os
from typing import Optional, List
import logging

# Configuration du logging
logger = logging.getLogger('embed_modal')

class EmbedModalCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.file_cache = {}  # Pour stocker temporairement les fichiers
        
        # Nettoyer le cache toutes les heures
        self.cleanup_cache.start()

    def cog_unload(self):
        """Nettoie les ressources lors du déchargement du cog"""
        self.cleanup_cache.cancel()

    @tasks.loop(hours=1)
    async def cleanup_cache(self):
        """Nettoie le cache des fichiers toutes les heures"""
        if self.file_cache:
            logger.info(f"Nettoyage du cache : {len(self.file_cache)} fichiers supprimés")
            self.file_cache.clear()

    @cleanup_cache.before_loop
    async def before_cleanup_cache(self):
        await self.bot.wait_until_ready()

    class EmbedModal(discord.ui.Modal):
        def __init__(self, cog, file_id=None):
            super().__init__(title="🌴 Création d'un Embed")
            self.cog = cog
            self.file_id = file_id

            self.title_input = discord.ui.TextInput(
                label="Titre de l'embed",
                placeholder="Exemple : Bienvenue sur notre serveur !",
                max_length=256,
                required=True
            )
            self.add_item(self.title_input)

            self.description_input = discord.ui.TextInput(
                label="Description",
                placeholder="Exemple : Découvrez nos événements à venir !",
                style=discord.TextStyle.long,
                max_length=4000,
                required=True
            )
            self.add_item(self.description_input)

            self.image_url_input = discord.ui.TextInput(
                label="URL d'image (facultatif)",
                placeholder="Exemple : https://example.com/image.png",
                required=False
            )
            self.add_item(self.image_url_input)

            self.ping_input = discord.ui.TextInput(
                label="Mentions (facultatif)",
                placeholder="Ex: @role ou @everyone (séparés par des virgules)",
                required=False
            )
            self.add_item(self.ping_input)

            self.footer_input = discord.ui.TextInput(
                label="Footer (facultatif)",
                placeholder="Exemple : Organisé par l'équipe 🌴",
                max_length=256,
                required=False
            )
            self.add_item(self.footer_input)

        async def on_submit(self, interaction: discord.Interaction):
            try:
                embed = discord.Embed(
                    title=self.title_input.value,
                    description=self.description_input.value,
                    color=discord.Color.blue()
                )
                
                # Ajouter l'image si fournie
                if self.image_url_input.value.strip():
                    embed.set_image(url=self.image_url_input.value.strip())
                        
                if self.footer_input.value.strip():
                    embed.set_footer(text=self.footer_input.value.strip())

                # Stocker les mentions pour plus tard
                mentions = self.ping_input.value.strip() if self.ping_input.value else ""

                view = ChannelSelectView(self.cog, embed, mentions, interaction.guild, self.file_id)
                await interaction.response.send_message(
                    "🎯 Choisissez le salon où envoyer l'embed :", view=view, ephemeral=True
                )
            except Exception as e:
                await interaction.response.send_message(
                    f"❌ Erreur lors de la création de l'embed : {str(e)}", ephemeral=True
                )

    @commands.command(name="embed")
    @commands.has_permissions(administrator=True)
    async def embed(self, ctx):
        """Commande pour ouvrir un formulaire interactif Embed."""
        view = CreateEmbedView(ctx.author.id, self)
        embed = discord.Embed(
            title="🌴 Créateur d'Embed",
            description="Cliquez sur le bouton ci-dessous pour créer un embed personnalisé.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed, view=view)

    @commands.command(name="embed_fichier")
    @commands.has_permissions(administrator=True)
    async def embed_fichier(self, ctx):
        """Commande pour créer un embed avec fichier joint."""
        if not ctx.message.attachments:
            await ctx.send("⚠️ Veuillez joindre un fichier à votre message.")
            return
            
        attachment = ctx.message.attachments[0]
        
        # Vérifier la taille du fichier
        if attachment.size > 25 * 1024 * 1024:
            await ctx.send("⚠️ Le fichier dépasse la limite de 25 MB.")
            return
            
        try:
            # Télécharger et stocker temporairement le fichier
            file_data = await attachment.read()
            file_id = f"{ctx.author.id}_{ctx.message.id}"
            self.file_cache[file_id] = {
                "data": file_data,
                "filename": attachment.filename,
                "content_type": getattr(attachment, 'content_type', 'application/octet-stream')
            }
            
            view = CreateEmbedView(ctx.author.id, self, file_id)
            await ctx.send(f"📎 Fichier `{attachment.filename}` reçu ! Cliquez pour créer un embed :", view=view)
            
        except Exception as e:
            await ctx.send(f"❌ Erreur lors du traitement du fichier : {str(e)}")

class ChannelSelectView(discord.ui.View):
    def __init__(self, cog, embed, mentions, guild, file_id=None):
        super().__init__(timeout=300)
        self.cog = cog
        self.embed = embed
        self.mentions = mentions
        self.guild = guild
        self.file_id = file_id
        self.page = 0
        self.channels_per_page = 24
        
        # Filtrer et trier les salons
        self.all_channels = self.get_available_channels()
        self.update_view()

    def get_available_channels(self):
        """Récupère tous les salons textuels accessibles"""
        channels = []
        
        for channel in self.guild.text_channels:
            if channel.permissions_for(self.guild.me).send_messages:
                channels.append({
                    'channel': channel,
                    'category': channel.category.name if channel.category else "Sans catégorie",
                    'name': channel.name
                })
        
        # Trier par catégorie puis par nom
        channels.sort(key=lambda x: (x['category'], x['name']))
        return channels

    def get_current_page_channels(self):
        """Retourne les salons de la page actuelle"""
        start = self.page * self.channels_per_page
        end = start + self.channels_per_page
        return self.all_channels[start:end]

    @property
    def max_pages(self):
        """Nombre total de pages"""
        return max(1, (len(self.all_channels) + self.channels_per_page - 1) // self.channels_per_page)

    def update_view(self):
        """Met à jour la vue avec les salons de la page actuelle"""
        self.clear_items()
        
        current_channels = self.get_current_page_channels()
        
        if not current_channels:
            return
        
        # Créer les options pour le select
        options = []
        
        for ch_info in current_channels:
            channel = ch_info['channel']
            category = ch_info['category']
            
            # Emoji selon le type de salon
            emoji = "📢"
            if "annonce" in channel.name.lower():
                emoji = "📣"
            elif "général" in channel.name.lower():
                emoji = "💬"
            elif "event" in channel.name.lower():
                emoji = "🎉"
            
            # Label avec catégorie si multiple pages
            if self.max_pages > 1:
                label = f"[{category}] {channel.name}"
            else:
                label = channel.name
            
            options.append(discord.SelectOption(
                label=label[:100],  # Limite Discord
                value=str(channel.id),
                emoji=emoji,
                description=f"Catégorie: {category}"[:100]
            ))
        
        if options:
            select = discord.ui.Select(
                placeholder=f"🎯 Sélectionnez un salon (Page {self.page + 1}/{self.max_pages})",
                options=options
            )
            select.callback = self.channel_callback
            self.add_item(select)
        
        # Boutons de navigation si nécessaire
        if self.max_pages > 1:
            # Bouton page précédente
            if self.page > 0:
                prev_button = discord.ui.Button(
                    label="◀️ Précédent",
                    style=discord.ButtonStyle.gray
                )
                prev_button.callback = self.previous_page
                self.add_item(prev_button)
            
            # Bouton page suivante
            if self.page < self.max_pages - 1:
                next_button = discord.ui.Button(
                    label="Suivant ▶️",
                    style=discord.ButtonStyle.gray
                )
                next_button.callback = self.next_page
                self.add_item(next_button)
        
        # Bouton pour ajouter un fichier
        if not self.file_id:
            file_button = discord.ui.Button(
                label="📎 Ajouter fichier",
                style=discord.ButtonStyle.secondary
            )
            file_button.callback = self.add_file_callback
            self.add_item(file_button)

    async def channel_callback(self, interaction):
        """Callback pour la sélection de salon"""
        try:
            channel_id = int(interaction.data['values'][0])
            channel = self.guild.get_channel(channel_id)
            
            if not channel:
                await interaction.response.send_message("⚠️ Salon introuvable.", ephemeral=True)
                return
            
            if not channel.permissions_for(self.guild.me).send_messages:
                await interaction.response.send_message(
                    f"⚠️ Pas de permission pour #{channel.name}.", ephemeral=True
                )
                return
                    
            view = ColorSelectView(self.cog, self.embed, channel, self.mentions, self.file_id)
            await interaction.response.send_message(
                f"🎨 Choisissez une couleur pour #{channel.name} :", view=view, ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur: {str(e)}", ephemeral=True)

    async def previous_page(self, interaction):
        """Page précédente"""
        if self.page > 0:
            self.page -= 1
            self.update_view()
            await interaction.response.edit_message(view=self)

    async def next_page(self, interaction):
        """Page suivante"""
        if self.page < self.max_pages - 1:
            self.page += 1
            self.update_view()
            await interaction.response.edit_message(view=self)

    async def add_file_callback(self, interaction):
        """Callback pour ajouter un fichier"""
        modal = FileAttachModal(self)
        await interaction.response.send_modal(modal)

class FileAttachModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="📎 Joindre un fichier")
        self.view = view
        
        self.file_url = discord.ui.TextInput(
            label="URL du fichier (25 MB max)",
            placeholder="https://example.com/document.pdf",
            required=True
        )
        self.add_item(self.file_url)

    async def on_submit(self, interaction: discord.Interaction):
        url = self.file_url.value.strip()
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        await interaction.response.send_message(
                            f"⚠️ Erreur téléchargement: {resp.status}", ephemeral=True
                        )
                        return
                        
                    # Vérifier la taille
                    content_length = int(resp.headers.get("Content-Length", 0))
                    if content_length > 25 * 1024 * 1024:
                        await interaction.response.send_message(
                            "⚠️ Fichier trop volumineux (max 25 MB).", ephemeral=True
                        )
                        return
                        
                    # Nom du fichier
                    filename = os.path.basename(url.split('?')[0])
                    if not filename or '.' not in filename:
                        filename = "fichier.bin"
                        
                    data = await resp.read()
                    
                    # Stocker le fichier
                    file_id = f"{interaction.user.id}_{interaction.id}"
                    self.view.cog.file_cache[file_id] = {
                        "data": data,
                        "filename": filename,
                        "content_type": resp.headers.get("Content-Type", "application/octet-stream")
                    }
                    self.view.file_id = file_id
                    
                    await interaction.response.send_message(
                        f"✅ Fichier `{filename}` ajouté !", ephemeral=True
                    )
                    
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Erreur: {str(e)}", ephemeral=True)

class ColorSelectView(discord.ui.View):
    def __init__(self, cog, embed, channel, mentions="", file_id=None):
        super().__init__(timeout=300)
        self.cog = cog
        self.embed = embed
        self.channel = channel
        self.mentions = mentions
        self.file_id = file_id

    @discord.ui.select(
        placeholder="🌈 Choisissez une couleur",
        options=[
            discord.SelectOption(label="Bleu lagon", value="0x40E0D0", emoji="🌊"),
            discord.SelectOption(label="Vert palmier", value="0x228B22", emoji="🌴"),
            discord.SelectOption(label="Jaune soleil", value="0xFFD700", emoji="☀️"),
            discord.SelectOption(label="Rouge hibiscus", value="0xFF1493", emoji="🌺"),
            discord.SelectOption(label="Turquoise", value="0x00CED1", emoji="🏖️"),
            discord.SelectOption(label="Orange mangue", value="0xFF8C00", emoji="🥭"),
            discord.SelectOption(label="Rose", value="0xFF69B4", emoji="🌸"),
            discord.SelectOption(label="Violet", value="0x9932CC", emoji="🌺"),
            discord.SelectOption(label="Vert bambou", value="0x98FF98", emoji="🎋"),
            discord.SelectOption(label="Noir", value="0x000000", emoji="⚫"),
            discord.SelectOption(label="Blanc", value="0xFFFFFF", emoji="⚪"),
            discord.SelectOption(label="Gris", value="0x808080", emoji="⚙️"),
        ]
    )
    async def select_color(self, interaction: discord.Interaction, select: discord.ui.Select):
        try:
            color_value = int(select.values[0], 16)
            self.embed.color = discord.Color(color_value)
            
            view = ConfirmEmbedView(self.cog, self.embed, self.channel, self.mentions, self.file_id)
            
            await interaction.response.send_message(
                f"👀 Aperçu pour #{self.channel.name}. Confirmez-vous l'envoi ?",
                embed=self.embed, view=view, ephemeral=True
            )
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur: {str(e)}", ephemeral=True)

class ConfirmEmbedView(discord.ui.View):
    def __init__(self, cog, embed, channel, mentions="", file_id=None):
        super().__init__(timeout=300)
        self.cog = cog
        self.embed = embed
        self.channel = channel
        self.mentions = mentions
        self.file_id = file_id
        self.sent = False

    @discord.ui.button(label="✅ Envoyer", style=discord.ButtonStyle.green)
    async def send_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Envoyer l'embed dans le salon."""
        if self.sent:
            await interaction.response.send_message("⛔ Déjà envoyé !", ephemeral=True)
            return

        try:
            # Préparer le contenu avec les mentions
            content = self.process_mentions(interaction.guild)

            # Préparer le fichier si présent
            file = None
            if self.file_id and self.file_id in self.cog.file_cache:
                file_info = self.cog.file_cache[self.file_id]
                file = discord.File(
                    io.BytesIO(file_info["data"]),
                    filename=file_info["filename"]
                )

            # Envoyer le message
            await self.channel.send(content=content, embed=self.embed, file=file)
            
            self.disable_buttons()
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(f"✅ Envoyé dans #{self.channel.name} !", ephemeral=True)
            
            self.sent = True
            
            # Nettoyer le cache
            if self.file_id and self.file_id in self.cog.file_cache:
                del self.cog.file_cache[self.file_id]
                
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur: {str(e)}", ephemeral=True)

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.red)
    async def cancel_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Annuler l'envoi."""
        if self.sent:
            await interaction.response.send_message("⛔ Déjà envoyé !", ephemeral=True)
            return

        self.disable_buttons()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("❌ Annulé.", ephemeral=True)
        
        # Nettoyer le cache
        if self.file_id and self.file_id in self.cog.file_cache:
            del self.cog.file_cache[self.file_id]

    def process_mentions(self, guild):
        """Traite les mentions et retourne le contenu approprié"""
        if not self.mentions:
            return None
            
        content_parts = []
        mention_parts = [part.strip() for part in self.mentions.split(',')]
        
        for part in mention_parts:
            if part.lower() == "@everyone":
                content_parts.append("@everyone")
            elif part.lower() == "@here":
                content_parts.append("@here")
            elif part.startswith("@"):
                role_name = part[1:]
                # Chercher un rôle
                role = discord.utils.get(guild.roles, name=role_name)
                if role:
                    content_parts.append(role.mention)
                else:
                    # Chercher un membre
                    member = discord.utils.get(guild.members, name=role_name)
                    if member:
                        content_parts.append(member.mention)
                    else:
                        content_parts.append(part)
            else:
                content_parts.append(part)
                
        return " ".join(content_parts) if content_parts else None

    def disable_buttons(self):
        """Désactiver les boutons après un clic."""
        for child in self.children:
            child.disabled = True

class CreateEmbedView(discord.ui.View):
    def __init__(self, author_id, cog, file_id=None):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.cog = cog
        self.file_id = file_id

    @discord.ui.button(label="🌴 Créer un Embed", style=discord.ButtonStyle.blurple)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("🔒 Non autorisé.", ephemeral=True)
            return
        
        modal = EmbedModalCog.EmbedModal(self.cog, self.file_id)
        await interaction.response.send_modal(modal)

async def setup(bot):
    await bot.add_cog(EmbedModalCog(bot))