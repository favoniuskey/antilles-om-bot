"""Système de tickets V2.

Architecture :
- Panneau dans `🚨・ticket-support` et `🎧・ticket-atc` avec bouton "Ouvrir un ticket"
- Click → modale (sujet + description)
- Création d'un salon dans la catégorie `🎫 ▸ TICKETS OUVERTS` (auto-créée)
- Salon privé : seuls le créateur + staff voient
- Dans le ticket : boutons « 🔒 Fermer » et « 👋 Prendre en charge »
- À la fermeture : transcript .txt généré, DM au créateur, log staff, suppression auto
- Limite : 1 ticket actif par user par type
- Views persistantes (custom_id stables) → survivent aux restarts
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands


logger = logging.getLogger("tickets_v2")

DATA_DIR = Path(__file__).resolve().parent.parent / "utils"
TICKETS_STATE = DATA_DIR / "tickets_v2_state.json"

TICKETS_CATEGORY_NAME = "🎫 ▸ TICKETS OUVERTS"
SUPPORT_PANEL_CHANNEL = "🚨・ticket-support"
ATC_PANEL_CHANNEL = "🎧・ticket-atc"
LOG_CHANNEL_NAME = "📋・logs"

STAFF_ROLE_NAMES = {
    "Modérateur", "Helper", "Responsable accueil",
    "Administrateur", "Directeur communauté",
}
ATC_STAFF_ROLE_NAMES = {
    "Modérateur", "Responsable aviation", "Staff IVAO",
    "Administrateur", "Directeur communauté",
}

TYPE_CONFIG = {
    "support": {
        "emoji": "🚨",
        "label": "Support général",
        "color": discord.Color.from_rgb(28, 168, 102),
        "channel_prefix": "support",
        "staff_roles": STAFF_ROLE_NAMES,
        "description": (
            "Questions sur le serveur, signalement d'un problème, "
            "réclamation, demande administrative."
        ),
    },
    "atc": {
        "emoji": "🎧",
        "label": "Support ATC / Aviation",
        "color": discord.Color.from_rgb(70, 130, 180),
        "channel_prefix": "atc",
        "staff_roles": ATC_STAFF_ROLE_NAMES,
        "description": (
            "Question liée au contrôle aérien, à IVAO, "
            "à un événement de vol, à la coordination ATC."
        ),
    },
}


# ----------------------------------------------------------------------
# Persistance
# ----------------------------------------------------------------------

def _load_state() -> dict:
    if not TICKETS_STATE.exists():
        return {"open_tickets": {}}
    try:
        return json.loads(TICKETS_STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"open_tickets": {}}


def _save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TICKETS_STATE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _user_has_open_ticket(state: dict, user_id: int, ticket_type: str) -> Optional[int]:
    """Retourne l'ID du salon de ticket actif (ou None)."""
    for ch_id_str, info in state.get("open_tickets", {}).items():
        if info.get("user_id") == user_id and info.get("type") == ticket_type:
            return int(ch_id_str)
    return None


# ----------------------------------------------------------------------
# Views persistantes
# ----------------------------------------------------------------------

class OpenSupportView(discord.ui.View):
    """View persistante du panneau ticket-support (1 seul bouton)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Ouvrir un ticket Support",
        style=discord.ButtonStyle.success,
        emoji="🚨",
        custom_id="tickets:open_support",
    )
    async def open_support(self, interaction: discord.Interaction,
                            button: discord.ui.Button) -> None:
        await interaction.response.send_modal(TicketModal("support"))


class OpenAtcView(discord.ui.View):
    """View persistante du panneau ticket-atc (1 seul bouton)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Ouvrir un ticket ATC",
        style=discord.ButtonStyle.primary,
        emoji="🎧",
        custom_id="tickets:open_atc",
    )
    async def open_atc(self, interaction: discord.Interaction,
                        button: discord.ui.Button) -> None:
        await interaction.response.send_modal(TicketModal("atc"))


class TicketModal(discord.ui.Modal):
    """Modale demandant sujet + description au moment de l'ouverture."""

    def __init__(self, ticket_type: str) -> None:
        cfg = TYPE_CONFIG[ticket_type]
        super().__init__(title=f"{cfg['emoji']} Ouvrir un ticket {cfg['label']}")
        self.ticket_type = ticket_type
        self.subject = discord.ui.TextInput(
            label="Sujet",
            placeholder="Résume ton problème en une phrase",
            min_length=4,
            max_length=80,
            required=True,
        )
        self.description = discord.ui.TextInput(
            label="Description détaillée",
            placeholder="Donne autant de détails que possible (contexte, ce que tu attends, etc.)",
            style=discord.TextStyle.paragraph,
            min_length=10,
            max_length=1500,
            required=True,
        )
        self.add_item(self.subject)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        cog: Optional[TicketsV2] = interaction.client.get_cog("TicketsV2")
        if cog is None:
            await interaction.followup.send("❌ Cog tickets indisponible.", ephemeral=True)
            return
        try:
            channel = await cog.create_ticket(
                interaction.guild,
                interaction.user,
                self.ticket_type,
                self.subject.value,
                self.description.value,
            )
            if channel is None:
                return  # Erreur déjà signalée
            await interaction.followup.send(
                f"✅ Ticket ouvert : {channel.mention}",
                ephemeral=True,
            )
        except Exception as e:
            logger.exception("Erreur création ticket")
            await interaction.followup.send(
                f"❌ Erreur lors de la création : {e}", ephemeral=True
            )


class TicketControlView(discord.ui.View):
    """Boutons dans le salon du ticket (fermer + claim)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Fermer le ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="tickets:close",
    )
    async def close_ticket(self, interaction: discord.Interaction,
                            button: discord.ui.Button) -> None:
        cog: Optional[TicketsV2] = interaction.client.get_cog("TicketsV2")
        if cog is None:
            await interaction.response.send_message("Cog indisponible.", ephemeral=True)
            return
        await cog.close_ticket(interaction)

    @discord.ui.button(
        label="Prendre en charge",
        style=discord.ButtonStyle.secondary,
        emoji="👋",
        custom_id="tickets:claim",
    )
    async def claim_ticket(self, interaction: discord.Interaction,
                            button: discord.ui.Button) -> None:
        cog: Optional[TicketsV2] = interaction.client.get_cog("TicketsV2")
        if cog is None:
            await interaction.response.send_message("Cog indisponible.", ephemeral=True)
            return
        await cog.claim_ticket(interaction)


class ConfirmCloseView(discord.ui.View):
    """Confirmation de fermeture (timeout 30s)."""

    def __init__(self, requester_id: int) -> None:
        super().__init__(timeout=30)
        self.requester_id = requester_id
        self.confirmed = False

    @discord.ui.button(label="Oui, fermer", style=discord.ButtonStyle.danger, emoji="🔒")
    async def confirm(self, interaction, button):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Pas pour toi.", ephemeral=True)
            return
        self.confirmed = True
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction, button):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Pas pour toi.", ephemeral=True)
            return
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()


# ----------------------------------------------------------------------
# Cog principal
# ----------------------------------------------------------------------

class TicketsV2(commands.Cog):
    """Système de tickets V2."""

    tickets = app_commands.Group(name="tickets", description="Gestion des tickets V2")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def get_or_create_category(self, guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        cat = discord.utils.get(guild.categories, name=TICKETS_CATEGORY_NAME)
        if cat is not None:
            return cat
        # Création avec @everyone deny par défaut
        try:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
            }
            for r in guild.roles:
                if r.name in STAFF_ROLE_NAMES or r.name == "Antilles - Outre Mer":
                    overwrites[r] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True,
                        manage_channels=True, manage_messages=True,
                        read_message_history=True,
                    )
            cat = await guild.create_category(
                name=TICKETS_CATEGORY_NAME,
                overwrites=overwrites,
                reason="Tickets V2 — catégorie auto-créée",
            )
            return cat
        except discord.Forbidden:
            logger.error("Impossible de créer la catégorie tickets")
            return None

    # ------------------------------------------------------------------
    # Création d'un ticket
    # ------------------------------------------------------------------

    async def create_ticket(self, guild: discord.Guild, user: discord.Member,
                             ticket_type: str, subject: str, description: str
                             ) -> Optional[discord.TextChannel]:
        state = _load_state()
        existing = _user_has_open_ticket(state, user.id, ticket_type)
        if existing:
            ch = guild.get_channel(existing)
            if ch:
                # Notifier qu'un ticket est déjà ouvert
                return ch
            else:
                # Salon référencé n'existe plus → nettoyage
                state["open_tickets"].pop(str(existing), None)
                _save_state(state)

        cat = await self.get_or_create_category(guild)
        if cat is None:
            return None

        cfg = TYPE_CONFIG[ticket_type]
        channel_name = f"{cfg['channel_prefix']}-{user.name}".lower()[:90]

        # Permissions : @everyone deny, user + staff allow
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                read_message_history=True, attach_files=True,
                embed_links=True, add_reactions=True,
            ),
        }
        for r in guild.roles:
            if r.name in cfg["staff_roles"] or r.name == "Antilles - Outre Mer":
                overwrites[r] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, manage_messages=True,
                    read_message_history=True, attach_files=True, embed_links=True,
                )

        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=cat,
                overwrites=overwrites,
                reason=f"Ticket {ticket_type} de {user}",
            )
        except discord.Forbidden:
            logger.error("Refus création salon ticket")
            return None

        # Sauvegarder le ticket
        state.setdefault("open_tickets", {})[str(channel.id)] = {
            "user_id": user.id,
            "user_name": str(user),
            "type": ticket_type,
            "subject": subject,
            "opened_at": datetime.now().isoformat(),
            "claimed_by": None,
        }
        _save_state(state)

        # Embed initial dans le ticket
        embed = discord.Embed(
            title=f"{cfg['emoji']} Ticket {cfg['label']}",
            description=f"**Sujet :** {subject}\n\n**Description :**\n{description}",
            color=cfg["color"],
            timestamp=datetime.now(),
        )
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)
        embed.add_field(name="Créé par", value=user.mention, inline=True)
        embed.add_field(name="Type", value=cfg["label"], inline=True)
        embed.set_footer(text=f"Ticket ID: {channel.id}")

        # Mentions staff selon le type
        staff_mentions = " ".join(
            r.mention for r in guild.roles
            if r.name in cfg["staff_roles"] and r.mentionable
        )

        try:
            await channel.send(
                content=f"{user.mention} • {staff_mentions if staff_mentions else ''}",
                embed=embed,
                view=TicketControlView(),
                allowed_mentions=discord.AllowedMentions(users=True, roles=True),
            )
        except discord.HTTPException:
            pass

        # Log dans staff-logs
        log_ch = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
        if log_ch:
            log_embed = discord.Embed(
                title=f"{cfg['emoji']} Nouveau ticket {ticket_type}",
                description=f"{user.mention} a ouvert {channel.mention}\n**Sujet :** {subject}",
                color=cfg["color"],
                timestamp=datetime.now(),
            )
            try:
                await log_ch.send(embed=log_embed)
            except discord.HTTPException:
                pass

        return channel

    # ------------------------------------------------------------------
    # Claim
    # ------------------------------------------------------------------

    async def claim_ticket(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not any(r.name in STAFF_ROLE_NAMES | ATC_STAFF_ROLE_NAMES for r in member.roles):
            await interaction.response.send_message(
                "🚫 Seul le staff peut prendre en charge un ticket.", ephemeral=True
            )
            return

        state = _load_state()
        info = state.get("open_tickets", {}).get(str(interaction.channel.id))
        if info is None:
            await interaction.response.send_message(
                "❌ Ce salon n'est pas un ticket valide.", ephemeral=True
            )
            return

        if info.get("claimed_by"):
            already = interaction.guild.get_member(int(info["claimed_by"]))
            await interaction.response.send_message(
                f"ℹ️ Déjà pris en charge par {already.mention if already else 'un staff'}.",
                ephemeral=True,
            )
            return

        info["claimed_by"] = member.id
        info["claimed_at"] = datetime.now().isoformat()
        state["open_tickets"][str(interaction.channel.id)] = info
        _save_state(state)

        embed = discord.Embed(
            description=f"👋 {member.mention} a pris ce ticket en charge.",
            color=discord.Color.gold(),
            timestamp=datetime.now(),
        )
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # Fermeture
    # ------------------------------------------------------------------

    async def close_ticket(self, interaction: discord.Interaction) -> None:
        state = _load_state()
        info = state.get("open_tickets", {}).get(str(interaction.channel.id))
        if info is None:
            await interaction.response.send_message(
                "❌ Ce salon n'est pas un ticket valide.", ephemeral=True
            )
            return

        member = interaction.user
        is_owner = member.id == info.get("user_id")
        is_staff = any(r.name in STAFF_ROLE_NAMES | ATC_STAFF_ROLE_NAMES for r in member.roles)
        if not (is_owner or is_staff):
            await interaction.response.send_message(
                "🚫 Seul le créateur ou un staff peut fermer ce ticket.", ephemeral=True
            )
            return

        view = ConfirmCloseView(member.id)
        await interaction.response.send_message(
            "⚠️ Confirmer la fermeture du ticket ?", view=view, ephemeral=True
        )
        await view.wait()
        if not view.confirmed:
            return

        # Générer le transcript
        transcript_lines = [
            f"# Transcript ticket {info.get('type', '?')}",
            f"Salon: #{interaction.channel.name} (id {interaction.channel.id})",
            f"Créé par: {info.get('user_name')} ({info.get('user_id')})",
            f"Sujet: {info.get('subject')}",
            f"Ouvert le: {info.get('opened_at')}",
            f"Fermé le: {datetime.now().isoformat()}",
            f"Fermé par: {member} ({member.id})",
            "",
            "## Messages",
            "",
        ]
        try:
            async for msg in interaction.channel.history(limit=1000, oldest_first=True):
                ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
                author = f"{msg.author}" if msg.author else "?"
                content = msg.content or ""
                if msg.embeds:
                    content += " [embed]"
                if msg.attachments:
                    content += " " + " ".join(f"[fichier: {a.filename}]" for a in msg.attachments)
                transcript_lines.append(f"[{ts}] {author}: {content}")
        except discord.HTTPException:
            transcript_lines.append("(historique partiellement inaccessible)")

        transcript_text = "\n".join(transcript_lines)
        transcript_file = discord.File(
            io.BytesIO(transcript_text.encode("utf-8")),
            filename=f"transcript-{interaction.channel.name}.txt",
        )

        # DM au créateur
        owner = interaction.guild.get_member(info.get("user_id"))
        if owner:
            try:
                await owner.send(
                    content=(
                        f"📋 Ton ticket **{info.get('subject')}** a été fermé.\n"
                        f"Voici le transcript :"
                    ),
                    file=transcript_file,
                )
            except discord.HTTPException:
                pass

        # Log staff
        log_ch = discord.utils.get(interaction.guild.text_channels, name=LOG_CHANNEL_NAME)
        if log_ch:
            log_embed = discord.Embed(
                title="🔒 Ticket fermé",
                description=(
                    f"Salon: `#{interaction.channel.name}`\n"
                    f"Créé par: <@{info.get('user_id')}>\n"
                    f"Fermé par: {member.mention}\n"
                    f"Sujet: {info.get('subject')}"
                ),
                color=discord.Color.dark_red(),
                timestamp=datetime.now(),
            )
            try:
                transcript_file2 = discord.File(
                    io.BytesIO(transcript_text.encode("utf-8")),
                    filename=f"transcript-{interaction.channel.name}.txt",
                )
                await log_ch.send(embed=log_embed, file=transcript_file2)
            except discord.HTTPException:
                pass

        # Nettoyer le state
        state["open_tickets"].pop(str(interaction.channel.id), None)
        _save_state(state)

        # Message final puis suppression
        try:
            await interaction.channel.send(
                "🔒 Ticket fermé. Suppression du salon dans 10 secondes…"
            )
        except discord.HTTPException:
            pass
        await asyncio.sleep(10)
        try:
            await interaction.channel.delete(reason="Ticket fermé V2")
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------------
    # /tickets setup
    # ------------------------------------------------------------------

    @tickets.command(
        name="setup",
        description="Poste les panneaux d'ouverture de ticket dans ticket-support et ticket-atc",
    )
    async def setup_cmd(self, interaction: discord.Interaction) -> None:
        # Réservé staff
        if not any(r.name in STAFF_ROLE_NAMES for r in interaction.user.roles):
            await interaction.response.send_message(
                "🚫 Commande réservée au staff.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild = interaction.guild
        support_ch = discord.utils.get(guild.text_channels, name=SUPPORT_PANEL_CHANNEL)
        atc_ch = discord.utils.get(guild.text_channels, name=ATC_PANEL_CHANNEL)

        if support_ch is None or atc_ch is None:
            await interaction.followup.send(
                f"❌ Salons panneau introuvables. Cherchés : `{SUPPORT_PANEL_CHANNEL}` "
                f"et `{ATC_PANEL_CHANNEL}`",
                ephemeral=True,
            )
            return

        # Embed support
        embed_support = discord.Embed(
            title="🎫 Support général",
            description=(
                "Besoin d'aide ? Une question sur le serveur ? Un souci à signaler ?\n\n"
                "Clique sur le bouton ci-dessous pour **ouvrir un ticket privé** "
                "avec le staff. Tu seras invité à décrire ton problème en quelques mots.\n\n"
                "**Sois précis** pour qu'on puisse t'aider rapidement. ✈️"
            ),
            color=TYPE_CONFIG["support"]["color"],
        )
        embed_support.set_footer(text="Un seul ticket actif à la fois")

        # Embed ATC
        embed_atc = discord.Embed(
            title="🎧 Support ATC / Aviation",
            description=(
                "Question liée au contrôle aérien, à IVAO, à un événement de vol, "
                "à la coordination ATC ?\n\n"
                "Clique sur le bouton ci-dessous pour ouvrir un ticket privé avec "
                "l'équipe aviation du serveur."
            ),
            color=TYPE_CONFIG["atc"]["color"],
        )
        embed_atc.set_footer(text="Un seul ticket actif à la fois")

        # Un seul bouton par panneau, dédié au type du salon
        try:
            await support_ch.send(embed=embed_support, view=OpenSupportView())
            await atc_ch.send(embed=embed_atc, view=OpenAtcView())
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Permission refusée pour poster.", ephemeral=True
            )
            return

        await interaction.followup.send(
            f"✅ Panneaux postés dans {support_ch.mention} et {atc_ch.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    cog = TicketsV2(bot)
    await bot.add_cog(cog)
    # Views persistantes (les custom_id matcheront les anciens messages aussi)
    bot.add_view(OpenSupportView())
    bot.add_view(OpenAtcView())
    bot.add_view(TicketControlView())
