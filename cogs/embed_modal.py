# cogs/embed_modal.py

import discord
from discord.ext import commands, tasks
import asyncio
from discord.ui import Modal, TextInput, Button, View
import io
import aiohttp
import os
from typing import Optional, List
import logging
import time

logger = logging.getLogger("embed_modal")

MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB
FILE_TTL_SECONDS = 60 * 60        # 1 heure

# Ton ID utilisateur (super-admin du panneau)
OWNER_ID = 595343318779428874  # <-- À REMPLACER PAR TON ID

# Rôles autorisés à utiliser le panneau de gestion
AUTHORIZED_ROLE_IDS: List[int] = [
     1297138129920196639,
     1297148016725332068,
     1309969291822760038,
]


class EmbedModalCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # file_id -> dict(data, filename, content_type, created_at)
        self.file_cache: dict[str, dict] = {}

        self.cleanup_cache.start()

    # ---------- Autorisations ----------

    def is_allowed(self, member: discord.Member) -> bool:
        """Vérifie si un membre est autorisé à utiliser le panneau."""
        perms = member.guild_permissions
        if perms.administrator or perms.manage_messages:
            return True
        if AUTHORIZED_ROLE_IDS:
            return any(role.id in AUTHORIZED_ROLE_IDS for role in member.roles)
        return False

    def is_owner_ctx(self, ctx: commands.Context) -> bool:
        return ctx.author.id == OWNER_ID

    # ---------- Tâche de nettoyage du cache ----------

    def cog_unload(self):
        self.cleanup_cache.cancel()

    @tasks.loop(hours=1)
    async def cleanup_cache(self):
        """Nettoie le cache des fichiers toutes les heures."""
        now = time.time()
        before = len(self.file_cache)

        self.file_cache = {
            k: v for k, v in self.file_cache.items()
            if now - v.get("created_at", now) < FILE_TTL_SECONDS
        }

        after = len(self.file_cache)
        if before != after:
            logger.info(f"Nettoyage du cache : {before - after} fichiers supprimés")

    @cleanup_cache.before_loop
    async def before_cleanup_cache(self):
        await self.bot.wait_until_ready()

    # ---------- Modal de création / édition d'embed ----------

    class EmbedModal(discord.ui.Modal):
        def __init__(
            self,
            cog: "EmbedModalCog",
            file_id: Optional[str] = None,
            target_message: Optional[discord.Message] = None,
            original_embed: Optional[discord.Embed] = None,
        ):
            super().__init__(title="Création / édition d'embed")
            self.cog = cog
            self.file_id = file_id
            self.target_message = target_message
            self.original_embed = original_embed

            existing_title = original_embed.title if original_embed else ""
            existing_desc = original_embed.description or "" if original_embed else ""
            existing_image = (
                original_embed.image.url
                if (original_embed and original_embed.image)
                else ""
            )
            existing_footer = (
                original_embed.footer.text
                if (original_embed and original_embed.footer)
                else ""
            )

            self.title_input = discord.ui.TextInput(
                label="Titre",
                max_length=256,
                required=True,
                default=existing_title,
            )
            self.add_item(self.title_input)

            self.description_input = discord.ui.TextInput(
                label="Description",
                style=discord.TextStyle.long,
                max_length=4000,
                required=True,
                default=existing_desc,
            )
            self.add_item(self.description_input)

            self.image_url_input = discord.ui.TextInput(
                label="URL d'image (optionnel)",
                required=False,
                default=existing_image,
            )
            self.add_item(self.image_url_input)

            self.ping_input = discord.ui.TextInput(
                label="Mentions (optionnel)",
                placeholder="Ex: @role ou @everyone (séparés par des virgules)",
                required=False,
            )
            self.add_item(self.ping_input)

            self.footer_input = discord.ui.TextInput(
                label="Pied de page (optionnel)",
                max_length=256,
                required=False,
                default=existing_footer,
            )
            self.add_item(self.footer_input)

        async def on_submit(self, interaction: discord.Interaction):
            try:
                embed_color = (
                    self.original_embed.color
                    if self.original_embed and self.original_embed.color
                    else discord.Color.blue()
                )

                embed = discord.Embed(
                    title=self.title_input.value,
                    description=self.description_input.value,
                    color=embed_color,
                )

                if self.image_url_input.value.strip():
                    embed.set_image(url=self.image_url_input.value.strip())

                if self.footer_input.value.strip():
                    embed.set_footer(text=self.footer_input.value.strip())

                mentions = self.ping_input.value.strip() if self.ping_input.value else ""

                # MODE ÉDITION : modifier un message existant
                if self.target_message is not None:
                    base_content = self.target_message.content or ""
                    extra_mentions = f" {mentions}" if mentions else ""
                    new_content = (base_content + extra_mentions).strip() or None

                    await self.target_message.edit(content=new_content, embed=embed)
                    await interaction.response.send_message(
                        "Embed mis à jour.",
                        ephemeral=True,
                    )
                    return

                # MODE CRÉATION : flux standard
                view = ChannelSelectView(
                    self.cog, embed, mentions, interaction.guild, self.file_id
                )
                await interaction.response.send_message(
                    "Choisissez le salon où envoyer l'embed :",
                    view=view,
                    ephemeral=True,
                )
            except Exception as e:
                logger.exception("Erreur dans EmbedModal.on_submit", exc_info=e)
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"Erreur lors de la création/édition de l'embed : {e}",
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        f"Erreur lors de la création/édition de l'embed : {e}",
                        ephemeral=True,
                    )

    # ---------- Commandes ----------

    @commands.command(name="embed")
    @commands.has_permissions(administrator=True)
    async def embed(self, ctx: commands.Context):
        """Ouvre le formulaire de création d'embed."""
        view = CreateEmbedView(ctx.author.id, self)
        embed = discord.Embed(
            title="Créateur d'embed",
            description="Cliquez sur le bouton ci-dessous pour créer un embed personnalisé.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed, view=view)

    @commands.command(name="embed_fichier")
    @commands.has_permissions(administrator=True)
    async def embed_fichier(self, ctx: commands.Context):
        """Créer un embed avec fichier joint."""
        if not ctx.message.attachments:
            await ctx.send("Veuillez joindre un fichier à votre message.")
            return

        attachment = ctx.message.attachments[0]

        if attachment.size > MAX_FILE_SIZE:
            await ctx.send("Le fichier dépasse la limite de 25 MB.")
            return

        try:
            file_data = await attachment.read()
            file_id = f"{ctx.author.id}_{ctx.message.id}"
            self.file_cache[file_id] = {
                "data": file_data,
                "filename": attachment.filename,
                "content_type": getattr(
                    attachment, "content_type", "application/octet-stream"
                ),
                "created_at": time.time(),
            }

            view = CreateEmbedView(ctx.author.id, self, file_id)
            await ctx.send(
                f"Fichier `{attachment.filename}` reçu. Cliquez pour créer un embed :",
                view=view,
            )

        except Exception as e:
            logger.exception("Erreur dans embed_fichier", exc_info=e)
            await ctx.send(f"Erreur lors du traitement du fichier : {e}")

    @commands.command(name="embed_edit")
    @commands.has_permissions(administrator=True)
    async def embed_edit(self, ctx: commands.Context, message: discord.Message):
        """
        Ouvre le formulaire de modification sur un message déjà envoyé par le bot.
        Usage : !embed_edit <id_message> ou en répondant au message.
        """
        if message.author.id != self.bot.user.id:
            await ctx.send("Je ne peux modifier que mes propres messages.")
            return

        if not message.embeds:
            await ctx.send("Ce message ne contient pas d'embed à modifier.")
            return

        original_embed = message.embeds[0]
        view = CreateEmbedView(
            author_id=ctx.author.id,
            cog=self,
            file_id=None,
            target_message=message,
            original_embed=original_embed,
        )

        await ctx.send(
            "Cliquez sur le bouton pour modifier cet embed.",
            view=view,
        )

    @commands.command(name="embed_panel")
    @commands.check(lambda ctx: ctx.cog.is_owner_ctx(ctx))
    async def embed_panel(self, ctx: commands.Context):
        """
        Crée le panneau de gestion des messages dans ce salon.
        Réservé au super-admin (OWNER_ID).
        """
        view = ManageMessagesView(self)
        embed = discord.Embed(
            title="Panneau de gestion des messages",
            description=(
                "Ce panneau permet aux membres autorisés de :\n"
                "- Créer un embed\n"
                "- Modifier un message du bot\n"
                "- Supprimer un message\n"
                "- Déplacer un message vers un autre salon"
            ),
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed, view=view)


# ===================== VUES & MODALS =====================


class ChannelSelectView(discord.ui.View):
    def __init__(self, cog: EmbedModalCog, embed: discord.Embed,
                 mentions: str, guild: discord.Guild, file_id: Optional[str] = None):
        super().__init__(timeout=300)
        self.cog = cog
        self.embed = embed
        self.mentions = mentions
        self.guild = guild
        self.file_id = file_id
        self.page = 0
        self.channels_per_page = 24

        self.all_channels = self.get_available_channels()
        self.update_view()

    def get_available_channels(self):
        channels = []
        for channel in self.guild.text_channels:
            if channel.permissions_for(self.guild.me).send_messages:
                channels.append(
                    {
                        "channel": channel,
                        "category": channel.category.name
                        if channel.category
                        else "Sans catégorie",
                        "name": channel.name,
                    }
                )
        channels.sort(key=lambda x: (x["category"], x["name"]))
        return channels

    def get_current_page_channels(self):
        start = self.page * self.channels_per_page
        end = start + self.channels_per_page
        return self.all_channels[start:end]

    @property
    def max_pages(self):
        return max(
            1, (len(self.all_channels) + self.channels_per_page - 1) // self.channels_per_page
        )

    def update_view(self):
        self.clear_items()

        current_channels = self.get_current_page_channels()
        if not current_channels:
            return

        options = []
        for ch_info in current_channels:
            channel = ch_info["channel"]
            category = ch_info["category"]

            label = (
                f"[{category}] {channel.name}" if self.max_pages > 1 else channel.name
            )

            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(channel.id),
                    description=f"Catégorie: {category}"[:100],
                )
            )

        if options:
            select = discord.ui.Select(
                placeholder=f"Sélectionnez un salon (Page {self.page + 1}/{self.max_pages})",
                options=options,
            )
            select.callback = self.channel_callback
            self.add_item(select)

        if self.max_pages > 1:
            if self.page > 0:
                prev_button = discord.ui.Button(
                    label="Précédent", style=discord.ButtonStyle.secondary
                )
                prev_button.callback = self.previous_page
                self.add_item(prev_button)

            if self.page < self.max_pages - 1:
                next_button = discord.ui.Button(
                    label="Suivant", style=discord.ButtonStyle.secondary
                )
                next_button.callback = self.next_page
                self.add_item(next_button)

        if not self.file_id:
            file_button = discord.ui.Button(
                label="Ajouter un fichier", style=discord.ButtonStyle.secondary
            )
            file_button.callback = self.add_file_callback
            self.add_item(file_button)

    async def channel_callback(self, interaction: discord.Interaction):
        try:
            channel_id = int(interaction.data["values"][0])
            channel = self.guild.get_channel(channel_id)

            if not channel:
                await interaction.response.send_message(
                    "Salon introuvable.", ephemeral=True
                )
                return

            if not channel.permissions_for(self.guild.me).send_messages:
                await interaction.response.send_message(
                    f"Pas de permission pour envoyer des messages dans #{channel.name}.",
                    ephemeral=True,
                )
                return

            view = ColorSelectView(
                self.cog, self.embed, channel, self.mentions, self.file_id
            )
            await interaction.response.send_message(
                f"Choisissez une couleur pour #{channel.name}.",
                view=view,
                ephemeral=True,
            )
        except Exception as e:
            logger.exception("Erreur dans ChannelSelectView.channel_callback", exc_info=e)
            await interaction.response.send_message(
                f"Erreur : {e}", ephemeral=True
            )

    async def previous_page(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            self.update_view()
            await interaction.response.edit_message(view=self)

    async def next_page(self, interaction: discord.Interaction):
        if self.page < self.max_pages - 1:
            self.page += 1
            self.update_view()
            await interaction.response.edit_message(view=self)

    async def add_file_callback(self, interaction: discord.Interaction):
        modal = FileAttachModal(self)
        await interaction.response.send_modal(modal)


class FileAttachModal(discord.ui.Modal):
    def __init__(self, view: ChannelSelectView):
        super().__init__(title="Joindre un fichier")
        self.view = view

        self.file_url = discord.ui.TextInput(
            label="URL du fichier (25 MB max)",
            placeholder="https://example.com/document.pdf",
            required=True,
        )
        self.add_item(self.file_url)

    async def on_submit(self, interaction: discord.Interaction):
        url = self.file_url.value.strip()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        await interaction.response.send_message(
                            f"Erreur téléchargement : {resp.status}", ephemeral=True
                        )
                        return

                    content_length = int(resp.headers.get("Content-Length", 0))
                    if content_length and content_length > MAX_FILE_SIZE:
                        await interaction.response.send_message(
                            "Fichier trop volumineux (max 25 MB).",
                            ephemeral=True,
                        )
                        return

                    filename = os.path.basename(url.split("?")[0])
                    if not filename or "." not in filename:
                        filename = "fichier.bin"

                    data = await resp.read()

                    file_id = f"{interaction.user.id}_{interaction.id}"
                    self.view.cog.file_cache[file_id] = {
                        "data": data,
                        "filename": filename,
                        "content_type": resp.headers.get(
                            "Content-Type", "application/octet-stream"
                        ),
                        "created_at": time.time(),
                    }
                    self.view.file_id = file_id

                    await interaction.response.send_message(
                        f"Fichier `{filename}` ajouté.", ephemeral=True
                    )

        except Exception as e:
            logger.exception("Erreur dans FileAttachModal.on_submit", exc_info=e)
            await interaction.response.send_message(
                f"Erreur : {e}", ephemeral=True
            )


class ColorSelectView(discord.ui.View):
    def __init__(self, cog: EmbedModalCog, embed: discord.Embed,
                 channel: discord.TextChannel, mentions: str = "",
                 file_id: Optional[str] = None):
        super().__init__(timeout=300)
        self.cog = cog
        self.embed = embed
        self.channel = channel
        self.mentions = mentions
        self.file_id = file_id

    @discord.ui.select(
        placeholder="Choisissez une couleur",
        options=[
            discord.SelectOption(label="Bleu", value="0x40E0D0"),
            discord.SelectOption(label="Vert", value="0x228B22"),
            discord.SelectOption(label="Jaune", value="0xFFD700"),
            discord.SelectOption(label="Rouge", value="0xFF0000"),
            discord.SelectOption(label="Turquoise", value="0x00CED1"),
            discord.SelectOption(label="Orange", value="0xFF8C00"),
            discord.SelectOption(label="Violet", value="0x9932CC"),
            discord.SelectOption(label="Noir", value="0x000000"),
            discord.SelectOption(label="Blanc", value="0xFFFFFF"),
            discord.SelectOption(label="Gris", value="0x808080"),
        ],
    )
    async def select_color(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        try:
            color_value = int(select.values[0], 16)
            self.embed.color = discord.Color(color_value)

            view = ConfirmEmbedView(
                self.cog, self.embed, self.channel, self.mentions, self.file_id
            )

            await interaction.response.send_message(
                f"Aperçu pour #{self.channel.name}. Confirmez-vous l'envoi ?",
                embed=self.embed,
                view=view,
                ephemeral=True,
            )

        except Exception as e:
            logger.exception("Erreur dans ColorSelectView.select_color", exc_info=e)
            await interaction.response.send_message(
                f"Erreur : {e}", ephemeral=True
            )


class ConfirmEmbedView(discord.ui.View):
    def __init__(self, cog: EmbedModalCog, embed: discord.Embed,
                 channel: discord.TextChannel, mentions: str = "",
                 file_id: Optional[str] = None):
        super().__init__(timeout=300)
        self.cog = cog
        self.embed = embed
        self.channel = channel
        self.mentions = mentions
        self.file_id = file_id
        self.sent = False

    @discord.ui.button(label="Envoyer", style=discord.ButtonStyle.success)
    async def send_embed(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if self.sent:
            await interaction.response.send_message(
                "Déjà envoyé.", ephemeral=True
            )
            return

        try:
            perms = self.channel.permissions_for(self.channel.guild.me)
            if not perms.send_messages:
                await interaction.response.send_message(
                    f"Pas de permission pour envoyer dans #{self.channel.name}.",
                    ephemeral=True,
                )
                return
            if self.file_id and not perms.attach_files:
                await interaction.response.send_message(
                    f"Pas de permission pour envoyer des fichiers dans #{self.channel.name}.",
                    ephemeral=True,
                )
                return

            content = self.process_mentions(interaction.guild)

            file = None
            if self.file_id and self.file_id in self.cog.file_cache:
                file_info = self.cog.file_cache[self.file_id]
                file = discord.File(
                    io.BytesIO(file_info["data"]), filename=file_info["filename"]
                )

            await self.channel.send(content=content, embed=self.embed, file=file)

            self.disable_buttons()
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(
                f"Message envoyé dans #{self.channel.name}.", ephemeral=True
            )

            self.sent = True

            if self.file_id and self.file_id in self.cog.file_cache:
                del self.cog.file_cache[self.file_id]

        except Exception as e:
            logger.exception("Erreur dans ConfirmEmbedView.send_embed", exc_info=e)
            await interaction.response.send_message(
                f"Erreur : {e}", ephemeral=True
            )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.danger)
    async def cancel_embed(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if self.sent:
            await interaction.response.send_message(
                "Déjà envoyé.", ephemeral=True
            )
            return

        self.disable_buttons()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("Opération annulée.", ephemeral=True)

        if self.file_id and self.file_id in self.cog.file_cache:
            del self.cog.file_cache[self.file_id]

    def process_mentions(self, guild: discord.Guild) -> Optional[str]:
        if not self.mentions:
            return None

        content_parts = []
        mention_parts = [part.strip() for part in self.mentions.split(",")]

        for part in mention_parts:
            if part.lower() == "@everyone":
                content_parts.append("@everyone")
            elif part.lower() == "@here":
                content_parts.append("@here")
            elif part.startswith("@"):
                role_name = part[1:]
                role = discord.utils.get(guild.roles, name=role_name)
                if role:
                    content_parts.append(role.mention)
                else:
                    member = discord.utils.get(guild.members, name=role_name)
                    if member:
                        content_parts.append(member.mention)
                    else:
                        content_parts.append(part)
            else:
                content_parts.append(part)

        return " ".join(content_parts) if content_parts else None

    def disable_buttons(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True


class CreateEmbedView(discord.ui.View):
    def __init__(
        self,
        author_id: int,
        cog: EmbedModalCog,
        file_id: Optional[str] = None,
        target_message: Optional[discord.Message] = None,
        original_embed: Optional[discord.Embed] = None,
    ):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.cog = cog
        self.file_id = file_id
        self.target_message = target_message
        self.original_embed = original_embed

    @discord.ui.button(label="Ouvrir le formulaire", style=discord.ButtonStyle.primary)
    async def open_modal(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Vous n'êtes pas autorisé pour cette action.",
                ephemeral=True,
            )
            return

        modal = EmbedModalCog.EmbedModal(
            self.cog,
            file_id=self.file_id,
            target_message=self.target_message,
            original_embed=self.original_embed,
        )
        await interaction.response.send_modal(modal)


# ---------- Sélection de message du bot ----------


class SelectBotMessageView(discord.ui.View):
    """
    Vue qui liste les derniers messages envoyés par le bot dans un salon,
    et permet d'en sélectionner un pour modification / suppression / déplacement.
    """

    def __init__(self, cog: EmbedModalCog, mode: str, channel: discord.TextChannel):
        super().__init__(timeout=60)
        self.cog = cog
        self.mode = mode  # "edit" | "delete" | "move"
        self.channel = channel
        self.message_select: Optional[discord.ui.Select] = None

    async def populate(self) -> bool:
        """
        Récupère jusqu'à 25 messages du bot avec embed dans ce salon
        (en scannant plus large que juste les tout derniers messages).
        """
        bot_user = self.cog.bot.user
        messages = []
        # On scanne plus profond (ex: 500 derniers messages) pour trouver les embeds du bot
        async for m in self.channel.history(limit=500):
            if m.author.id == bot_user.id and m.embeds:
                messages.append(m)
            if len(messages) >= 25:  # limite du Select
                break

        if not messages:
            return False

        options = []
        for msg in messages:
            if msg.content:
                preview = msg.content.replace("\n", " ")
            elif msg.embeds:
                preview = "[Embed]"
            else:
                preview = "[Sans contenu]"

            preview = (preview[:80] + "…") if len(preview) > 80 else preview
            label = f"[{msg.created_at.strftime('%d/%m %H:%M')}] {preview}"

            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(msg.id),
                )
            )

        select = discord.ui.Select(
            placeholder=f"Sélectionnez un message du bot dans #{self.channel.name}",
            options=options,
        )
        select.callback = self.on_select_message
        self.message_select = select
        self.add_item(select)
        return True

    async def on_select_message(self, interaction: discord.Interaction):
        msg_id = int(self.message_select.values[0])
        try:
            msg = await self.channel.fetch_message(msg_id)
        except discord.NotFound:
            await interaction.response.send_message(
                "Message introuvable (supprimé entre-temps ?).",
                ephemeral=True,
            )
            return
        except Exception as e:
            logger.exception("Erreur fetch_message dans SelectBotMessageView", exc_info=e)
            await interaction.response.send_message(
                f"Erreur lors de la récupération du message : {e}",
                ephemeral=True,
            )
            return

        if self.mode == "edit":
            if not msg.embeds:
                await interaction.response.send_message(
                    "Ce message ne contient pas d'embed à modifier.",
                    ephemeral=True,
                )
                return

            original_embed = msg.embeds[0]
            view = CreateEmbedView(
                author_id=interaction.user.id,
                cog=self.cog,
                file_id=None,
                target_message=msg,
                original_embed=original_embed,
            )
            await interaction.response.send_message(
                "Cliquez sur le bouton pour modifier cet embed.",
                view=view,
                ephemeral=True,
            )

        elif self.mode == "delete":
            try:
                await msg.delete()
                await interaction.response.send_message(
                    "Message supprimé.",
                    ephemeral=True,
                )
            except discord.Forbidden:
                await interaction.response.send_message(
                    "Je n'ai pas la permission de supprimer ce message.",
                    ephemeral=True,
                )
            except Exception as e:
                logger.exception("Erreur suppression dans SelectBotMessageView", exc_info=e)
                await interaction.response.send_message(
                    f"Erreur lors de la suppression : {e}",
                    ephemeral=True,
                )

        elif self.mode == "move":
            modal = MoveMessageModal(self.cog, preset_message=msg)
            await interaction.response.send_modal(modal)

        # On essaye de désactiver le select seulement si le message n'est pas éphémère
        self.disable_all_items()
        try:
            if interaction.message and not interaction.message.flags.ephemeral:
                await interaction.message.edit(view=self)
        except discord.NotFound:
            # Le message a pu être supprimé entre-temps, on ignore
            pass
        except Exception as e:
            logger.exception("Erreur lors de l'édition du message de sélection", exc_info=e)

    def disable_all_items(self):
        for child in self.children:
            if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                child.disabled = True


class SelectChannelForBotMessagesView(discord.ui.View):
    """
    Étape 1 : on liste les salons textuels dans le même ordre que l'UI Discord,
    en ne gardant que ceux où le bot a envoyé au moins un embed (dans l'historique
    accessible, pas uniquement les messages tout récents).
    """

    def __init__(self, cog: EmbedModalCog, mode: str, guild: discord.Guild):
        super().__init__(timeout=60)
        self.cog = cog
        self.mode = mode  # "edit" | "delete" | "move"
        self.guild = guild
        self.channel_select: Optional[discord.ui.Select] = None

    async def populate(self) -> bool:
        """
        Parcourt les salons textuels dans l'ordre naturel de guild.text_channels
        (même ordre que dans Discord) et ne conserve que ceux où le bot a au
        moins un message avec embed dans l'historique (on scanne un peu profond
        pour éviter de ne voir que les tout derniers messages).
        """
        bot_user = self.cog.bot.user
        channels_with_bot_embeds: list[discord.TextChannel] = []

        # guild.text_channels est déjà dans l'ordre d'affichage Discord.[web:91]
        for channel in self.guild.text_channels:
            perms = channel.permissions_for(self.guild.me)
            if not perms.read_message_history:
                continue

            found = False
            try:
                # On regarde jusqu'à ~200 derniers messages pour trouver un embed du bot
                async for m in channel.history(limit=200):
                    if m.author.id == bot_user.id and m.embeds:
                        found = True
                        break
            except discord.Forbidden:
                continue
            except Exception as e:
                logger.exception("Erreur history dans SelectChannelForBotMessagesView", exc_info=e)
                continue

            if found:
                channels_with_bot_embeds.append(channel)

        if not channels_with_bot_embeds:
            return False

        # Limités à 25 options max par Select Discord
        options = []
        for channel in channels_with_bot_embeds[:25]:
            label = channel.name
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(channel.id),
                )
            )

        select = discord.ui.Select(
            placeholder="Choisissez un salon où le bot a déjà envoyé un embed",
            options=options,
        )
        select.callback = self.select_channel
        self.channel_select = select
        self.add_item(select)

        return True

    async def select_channel(self, interaction: discord.Interaction):
        channel_id = int(self.channel_select.values[0])
        channel = self.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Salon invalide.",
                ephemeral=True,
            )
            return

        view = SelectBotMessageView(self.cog, self.mode, channel)
        has_messages = await view.populate()
        if not has_messages:
            await interaction.response.send_message(
                "Aucun message avec embed du bot trouvé dans ce salon.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content=f"Sélectionnez un message du bot dans #{channel.name} :",
            view=view,
        )

# ---------- Panneau persistant ----------


class ManageMessagesView(discord.ui.View):
    """
    Panneau de gestion persistant.
    Reste utilisable après redémarrage si la vue est réenregistrée avec bot.add_view.
    """

    def __init__(self, cog: EmbedModalCog):
        super().__init__(timeout=None)  # Vue persistante
        self.cog = cog

    def user_allowed(self, member: discord.Member) -> bool:
        return self.cog.is_allowed(member)

    @discord.ui.button(
        label="Créer un embed",
        style=discord.ButtonStyle.success,
        custom_id="manage:create_embed",
    )
    async def create_embed_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not self.user_allowed(interaction.user):
            await interaction.response.send_message(
                "Vous n'êtes pas autorisé à utiliser ce panneau.",
                ephemeral=True,
            )
            return

        view = CreateEmbedView(interaction.user.id, self.cog)
        embed = discord.Embed(
            title="Créateur d'embed",
            description="Cliquez sur le bouton ci-dessous pour créer un embed personnalisé.",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Modifier un message",
        style=discord.ButtonStyle.primary,
        custom_id="manage:edit_message",
    )
    async def edit_message_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not self.user_allowed(interaction.user):
            await interaction.response.send_message(
                "Vous n'êtes pas autorisé à utiliser ce panneau.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Action indisponible en message privé.",
                ephemeral=True,
            )
            return

        # 1) ACK rapide de l'interaction pour éviter l'expiration
        await interaction.response.defer(ephemeral=True, thinking=True)

        view = SelectChannelForBotMessagesView(self.cog, "edit", guild)
        has_channels = await view.populate()
        if not has_channels:
            await interaction.followup.send(
                "Aucun salon où le bot a envoyé des messages récemment.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "Choisissez un salon où le bot a envoyé un message :",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Supprimer un message",
        style=discord.ButtonStyle.danger,
        custom_id="manage:delete_message",
    )
    async def delete_message_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not self.user_allowed(interaction.user):
            await interaction.response.send_message(
                "Vous n'êtes pas autorisé à utiliser ce panneau.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Action indisponible en message privé.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        view = SelectChannelForBotMessagesView(self.cog, "delete", guild)
        has_channels = await view.populate()
        if not has_channels:
            await interaction.followup.send(
                "Aucun salon où le bot a envoyé des messages récemment.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "Choisissez un salon où le bot a envoyé un message :",
            view=view,
            ephemeral=True,
        )
        
    @discord.ui.button(
        label="Déplacer un message",
        style=discord.ButtonStyle.secondary,
        custom_id="manage:move_message",
    )
    async def move_message_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not self.user_allowed(interaction.user):
            await interaction.response.send_message(
                "Vous n'êtes pas autorisé à utiliser ce panneau.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Action indisponible en message privé.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        view = SelectChannelForBotMessagesView(self.cog, "move", guild)
        has_channels = await view.populate()
        if not has_channels:
            await interaction.followup.send(
                "Aucun salon où le bot a envoyé des messages récemment.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "Choisissez un salon où le bot a envoyé un message :",
            view=view,
            ephemeral=True,
        )


# ---------- Déplacement de message ----------


class MoveMessageModal(discord.ui.Modal):
    """
    Déplace un message vers un autre salon :
    - clone contenu + embed + fichiers dans le nouveau salon
    - supprime l'original
    """

    def __init__(self, cog: EmbedModalCog, preset_message: Optional[discord.Message] = None):
        super().__init__(title="Déplacer un message")
        self.cog = cog
        self.preset_message = preset_message

        self.message_ref = discord.ui.TextInput(
            label="ID ou lien du message",
            placeholder="Ex: 1234567890 ou https://discord.com/channels/.../message_id",
            required=(preset_message is None),
        )
        if preset_message is None:
            self.add_item(self.message_ref)

        self.target_channel_input = discord.ui.TextInput(
            label="Salon cible",
            placeholder="Mention (#salon) ou ID ou nom",
            required=True,
        )
        self.add_item(self.target_channel_input)

    async def resolve_message(
        self, interaction: discord.Interaction
    ) -> Optional[discord.Message]:
        ref = self.message_ref.value.strip()

        if "discord.com/channels/" in ref:
            try:
                parts = ref.split("/")
                channel_id = int(parts[-2])
                message_id = int(parts[-1])
            except Exception:
                await interaction.response.send_message(
                    "Lien invalide.", ephemeral=True
                )
                return None

            channel = interaction.guild.get_channel(channel_id)
            if not channel or not isinstance(channel, discord.TextChannel):
                await interaction.response.send_message(
                    "Salon introuvable depuis ce lien.", ephemeral=True
                )
                return None
        else:
            try:
                message_id = int(ref)
            except ValueError:
                await interaction.response.send_message(
                    "ID de message invalide.", ephemeral=True
                )
                return None
            channel = interaction.channel

        try:
            msg = await channel.fetch_message(message_id)
        except discord.NotFound:
            await interaction.response.send_message(
                "Message introuvable.", ephemeral=True
            )
            return None
        except Exception as e:
            logger.exception("Erreur fetch_message dans MoveMessageModal", exc_info=e)
            await interaction.response.send_message(
                f"Erreur lors de la récupération du message : {e}",
                ephemeral=True,
            )
            return None

        return msg

    async def resolve_channel(
        self, interaction: discord.Interaction
    ) -> Optional[discord.TextChannel]:
        raw = self.target_channel_input.value.strip()

        if raw.startswith("<#") and raw.endswith(">"):
            try:
                channel_id = int(raw[2:-1])
            except ValueError:
                await interaction.response.send_message(
                    "Mention de salon invalide.", ephemeral=True
                )
                return None
            channel = interaction.guild.get_channel(channel_id)
        else:
            try:
                channel_id = int(raw)
                channel = interaction.guild.get_channel(channel_id)
            except ValueError:
                channel = discord.utils.get(
                    interaction.guild.text_channels, name=raw
                )

        if not channel or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Salon cible introuvable.", ephemeral=True
            )
            return None

        return channel

    async def on_submit(self, interaction: discord.Interaction):
        if self.preset_message is not None:
            msg = self.preset_message
        else:
            msg = await self.resolve_message(interaction)
            if msg is None:
                return

        target_channel = await self.resolve_channel(interaction)
        if target_channel is None:
            return

        perms = target_channel.permissions_for(target_channel.guild.me)
        if not perms.send_messages:
            await interaction.response.send_message(
                f"Je ne peux pas envoyer de messages dans {target_channel.mention}.",
                ephemeral=True,
            )
            return

        try:
            content = msg.content or None
            embed = msg.embeds[0] if msg.embeds else None

            files = []
            for attachment in msg.attachments:
                if attachment.size > MAX_FILE_SIZE:
                    continue
                files.append(await attachment.to_file())

            await target_channel.send(content=content, embed=embed, files=files)
            await msg.delete()

            await interaction.response.send_message(
                f"Message déplacé vers {target_channel.mention}.",
                ephemeral=True,
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "Permission refusée pour déplacer/supprimer ce message.",
                ephemeral=True,
            )
        except Exception as e:
            logger.exception("Erreur dans MoveMessageModal.on_submit", exc_info=e)
            await interaction.response.send_message(
                f"Erreur lors du déplacement : {e}", ephemeral=True
            )


# ---------- SETUP DU COG ----------


async def setup(bot: commands.Bot):
    cog = EmbedModalCog(bot)
    await bot.add_cog(cog)
    # Enregistrement de la vue persistante pour recâbler les panneaux existants
    bot.add_view(ManageMessagesView(cog))