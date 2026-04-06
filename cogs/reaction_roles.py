import discord
from discord.ext import commands
import json
import os
import logging
from typing import Optional, Dict, Any, List, Set

logger = logging.getLogger("reaction_roles")

DATA_DIR = "utils/data"
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(DATA_DIR, "reaction_roles.json")

# ID super-admin autorisé à poser le panneau
OWNER_ID = 123456789012345678  # <-- à remplacer par ton ID


def load_config() -> Dict[str, Any]:
    if not os.path.isfile(CONFIG_FILE):
        return {"reaction_roles": [], "role_menus": []}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Erreur lecture {CONFIG_FILE}: {e}")
        return {"reaction_roles": [], "role_menus": []}


def save_config(cfg: Dict[str, Any]) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Erreur écriture {CONFIG_FILE}: {e}")


class ReactionRolesCog(commands.Cog):
    """
    Gestion des rôles par réactions ET par menu déroulant,
    avec un panneau de gestion central pour les staffs.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config: Dict[str, Any] = load_config()

    # ========== OUTILS CONFIG ==========

    def save(self):
        save_config(self.config)

    def find_reaction_entry(self, message_id: int, emoji_str: str) -> Optional[Dict[str, Any]]:
        for entry in self.config.get("reaction_roles", []):
            if entry["message_id"] == message_id and entry["emoji"] == emoji_str:
                return entry
        return None

    def is_owner_ctx(self, ctx: commands.Context) -> bool:
        return ctx.author.id == OWNER_ID or ctx.author.guild_permissions.administrator

    # ========== PANNEAU DE GESTION ==========

    @commands.command(name="rr_panel")
    async def rr_panel(self, ctx: commands.Context):
        """Crée le panneau de gestion des rôles (réactions + menus)."""
        if not self.is_owner_ctx(ctx):
            await ctx.send("Tu n'es pas autorisé à créer ce panneau.", delete_after=10)
            return

        view = ReactionPanelView(self)
        embed = discord.Embed(
            title="Panneau de gestion des rôles",
            description=(
                "Boutons disponibles :\n"
                "- Créer un reaction-role sur un message\n"
                "- Créer un menu déroulant de rôles\n"
                "- Configurer les menus de rôles existants\n"
                "- Lister les configurations"
            ),
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed, view=view)

    # ========== COMMANDES TEXTE (BACKUP / AVANCÉ) ==========

    @commands.group(name="rr", invoke_without_command=True)
    @commands.has_permissions(manage_roles=True)
    async def rr_group(self, ctx: commands.Context):
        await ctx.send(
            "Sous-commandes :\n"
            "- `!rr add <message_id> <emoji> <@role>`\n"
            "- `!rr remove <message_id> <emoji>`\n"
            "- `!rr list`",
            delete_after=15,
        )

    @rr_group.command(name="add")
    @commands.has_permissions(manage_roles=True)
    async def rr_add(self, ctx: commands.Context, message_id: int, emoji: str, role: discord.Role):
        await ctx.message.delete()

        emoji_str = emoji
        if self.find_reaction_entry(message_id, emoji_str):
            await ctx.send("Cette combinaison message/emoji existe déjà.", delete_after=10)
            return

        self.config.setdefault("reaction_roles", []).append(
            {
                "guild_id": ctx.guild.id,
                "channel_id": ctx.channel.id,
                "message_id": message_id,
                "emoji": emoji_str,
                "role_id": role.id,
            }
        )
        self.save()

        try:
            msg = await ctx.channel.fetch_message(message_id)
            await msg.add_reaction(emoji_str)
        except Exception as e:
            logger.warning(f"Impossible d'ajouter la réaction automatiquement: {e}")

        await ctx.send(
            f"Reaction-role ajouté : message `{message_id}`, emoji `{emoji_str}`, rôle {role.mention}.",
            delete_after=10,
        )

    @rr_group.command(name="remove")
    @commands.has_permissions(manage_roles=True)
    async def rr_remove(self, ctx: commands.Context, message_id: int, emoji: str):
        await ctx.message.delete()

        before = len(self.config.get("reaction_roles", []))
        self.config["reaction_roles"] = [
            e for e in self.config.get("reaction_roles", [])
            if not (e["message_id"] == message_id and e["emoji"] == emoji)
        ]
        after = len(self.config["reaction_roles"])
        self.save()

        if before == after:
            await ctx.send("Aucune entrée trouvée pour ce message/emoji.", delete_after=10)
        else:
            await ctx.send("Reaction-role supprimé.", delete_after=10)

    @rr_group.command(name="list")
    @commands.has_permissions(manage_roles=True)
    async def rr_list(self, ctx: commands.Context):
        entries = [
            e for e in self.config.get("reaction_roles", [])
            if e["guild_id"] == ctx.guild.id
        ]
        menus = [
            m for m in self.config.get("role_menus", [])
            if m["guild_id"] == ctx.guild.id
        ]

        if not entries and not menus:
            await ctx.send("Aucune configuration de rôle sur ce serveur.")
            return

        lines = []
        if entries:
            lines.append("Reaction-roles :")
            for e in entries[:15]:
                role = ctx.guild.get_role(e["role_id"])
                lines.append(
                    f"- msg `{e['message_id']}`, emoji `{e['emoji']}`, rôle: {role.mention if role else e['role_id']}"
                )
            if len(entries) > 15:
                lines.append(f"... ({len(entries) - 15} de plus)")
        if menus:
            lines.append("")
            lines.append("Menus de rôles :")
            for m in menus[:10]:
                ch = ctx.guild.get_channel(m["channel_id"])
                lines.append(
                    f"- ID `{m['id']}` dans {ch.mention if ch else f'<#{m['channel_id']}>'}, rôles: {len(m['roles'])}"
                )
            if len(menus) > 10:
                lines.append(f"... ({len(menus) - 10} de plus)")

        await ctx.send("\n".join(lines))

    # ========== EVENTS REACTION ==========

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Donne un rôle quand quelqu'un réagit avec un emoji configuré."""
        if payload.guild_id is None:
            return
        if payload.user_id == self.bot.user.id:
            return

        emoji_str = str(payload.emoji)
        entry = self.find_reaction_entry(payload.message_id, emoji_str)
        if not entry:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        member = guild.get_member(payload.user_id)
        if not member:
            return

        role = guild.get_role(entry["role_id"])
        if not role:
            return

        try:
            if role not in member.roles:
                await member.add_roles(role, reason="Reaction role ajout")
        except discord.Forbidden:
            logger.warning(f"Pas la permission d'ajouter {role} à {member}")
        except discord.HTTPException as e:
            logger.error(f"Erreur add_roles: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """Retire le rôle quand quelqu'un retire sa réaction."""
        if payload.guild_id is None:
            return
        if payload.user_id == self.bot.user.id:
            return

        emoji_str = str(payload.emoji)
        entry = self.find_reaction_entry(payload.message_id, emoji_str)
        if not entry:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        member = guild.get_member(payload.user_id)
        if not member:
            return

        role = guild.get_role(entry["role_id"])
        if not role:
            return

        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Reaction role retrait")
        except discord.Forbidden:
            logger.warning(f"Pas la permission de retirer {role} à {member}")
        except discord.HTTPException as e:
            logger.error(f"Erreur remove_roles: {e}")


# ========== VUES & MODALS DU PANNEAU ==========


class ReactionPanelView(discord.ui.View):
    """Panneau principal de gestion (persistant)."""

    def __init__(self, cog: ReactionRolesCog):
        super().__init__(timeout=None)
        self.cog = cog

    def user_allowed(self, member: discord.Member) -> bool:
        return member.guild_permissions.manage_roles

    @discord.ui.button(
        label="Créer reaction-role",
        style=discord.ButtonStyle.primary,
        custom_id="rr:create_rr",
    )
    async def create_rr_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not self.user_allowed(interaction.user):
            await interaction.response.send_message(
                "Tu n'as pas la permission de gérer les rôles.",
                ephemeral=True,
            )
            return

        modal = CreateReactionRoleModal(self.cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="Créer menu de rôles",
        style=discord.ButtonStyle.success,
        custom_id="rr:create_menu",
    )
    async def create_menu_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not self.user_allowed(interaction.user):
            await interaction.response.send_message(
                "Tu n'as pas la permission de gérer les rôles.",
                ephemeral=True,
            )
            return

        modal = CreateRoleMenuModal(self.cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="Configurer menus",
        style=discord.ButtonStyle.secondary,
        custom_id="rr:config_menus",
    )
    async def config_menus_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not self.user_allowed(interaction.user):
            await interaction.response.send_message(
                "Tu n'as pas la permission de gérer les rôles.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Action impossible en message privé.",
                ephemeral=True,
            )
            return

        menus = [m for m in self.cog.config.get("role_menus", []) if m["guild_id"] == guild.id]
        if not menus:
            await interaction.response.send_message(
                "Aucun menu de rôles configuré sur ce serveur.",
                ephemeral=True,
            )
            return

        view = MenuConfigSelectView(self.cog, guild)
        has_menus = await view.populate()
        if not has_menus:
            await interaction.response.send_message(
                "Aucun menu exploitable.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Sélectionnez un menu à configurer :",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Lister configs",
        style=discord.ButtonStyle.secondary,
        custom_id="rr:list_configs",
    )
    async def list_configs_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not self.user_allowed(interaction.user):
            await interaction.response.send_message(
                "Tu n'as pas la permission de gérer les rôles.",
                ephemeral=True,
            )
            return

        cfg = self.cog.config
        rr_count = len(cfg.get("reaction_roles", []))
        menu_count = len(cfg.get("role_menus", []))

        text = (
            f"Reaction-roles configurés : {rr_count}\n"
            f"Menus de rôles configurés : {menu_count}"
        )
        await interaction.response.send_message(text, ephemeral=True)


class CreateReactionRoleModal(discord.ui.Modal, title="Nouveau reaction-role"):
    def __init__(self, cog: ReactionRolesCog):
        super().__init__()
        self.cog = cog

        self.channel_input = discord.ui.TextInput(
            label="Salon (mention ou ID)",
            required=False,
            placeholder="#règlement ou ID (vide = actuel)",
        )
        self.add_item(self.channel_input)

        self.message_input = discord.ui.TextInput(
            label="Message (ID ou URL)",
            required=True,
            placeholder="1234567890 ou URL",
        )
        self.add_item(self.message_input)

        self.emoji_input = discord.ui.TextInput(
            label="Emoji",
            required=True,
            placeholder="✅",
        )
        self.add_item(self.emoji_input)

        self.role_input = discord.ui.TextInput(
            label="Rôle (mention ou ID)",
            required=True,
            placeholder="@Membre ou 1234567890",
        )
        self.add_item(self.role_input)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Action impossible en message privé.",
                ephemeral=True,
            )
            return

        # Channel
        raw_channel = self.channel_input.value.strip()
        channel: discord.TextChannel
        if not raw_channel:
            channel = interaction.channel  # type: ignore
        else:
            channel = None
            if raw_channel.startswith("<#") and raw_channel.endswith(">"):
                try:
                    cid = int(raw_channel[2:-1])
                    c = guild.get_channel(cid)
                    if isinstance(c, discord.TextChannel):
                        channel = c
                except ValueError:
                    pass
            if channel is None:
                try:
                    cid = int(raw_channel)
                    c = guild.get_channel(cid)
                    if isinstance(c, discord.TextChannel):
                        channel = c
                except ValueError:
                    pass

        if channel is None:
            await interaction.response.send_message(
                "Salon invalide.",
                ephemeral=True,
            )
            return

        # Message
        raw_msg = self.message_input.value.strip()
        message_id = None
        if "discord.com/channels/" in raw_msg:
            try:
                parts = raw_msg.split("/")
                message_id = int(parts[-1])
                chan_id = int(parts[-2])
                chan = guild.get_channel(chan_id)
                if isinstance(chan, discord.TextChannel):
                    channel = chan
            except Exception:
                await interaction.response.send_message(
                    "URL de message invalide.",
                    ephemeral=True,
                )
                return
        else:
            try:
                message_id = int(raw_msg)
            except ValueError:
                await interaction.response.send_message(
                    "ID de message invalide.",
                    ephemeral=True,
                )
                return

        emoji_str = self.emoji_input.value.strip()

        # Rôle
        raw_role = self.role_input.value.strip()
        role = None
        if raw_role.startswith("<@&") and raw_role.endswith(">"):
            try:
                rid = int(raw_role[3:-1])
                role = guild.get_role(rid)
            except ValueError:
                pass
        if role is None:
            try:
                rid = int(raw_role)
                role = guild.get_role(rid)
            except ValueError:
                pass
        if role is None:
            role = discord.utils.get(guild.roles, name=raw_role)

        if role is None:
            await interaction.response.send_message(
                "Rôle introuvable.",
                ephemeral=True,
            )
            return

        if self.cog.find_reaction_entry(message_id, emoji_str):
            await interaction.response.send_message(
                "Cette combinaison message/emoji existe déjà.",
                ephemeral=True,
            )
            return

        self.cog.config.setdefault("reaction_roles", []).append(
            {
                "guild_id": guild.id,
                "channel_id": channel.id,
                "message_id": message_id,
                "emoji": emoji_str,
                "role_id": role.id,
            }
        )
        self.cog.save()

        try:
            msg = await channel.fetch_message(message_id)
            await msg.add_reaction(emoji_str)
        except Exception as e:
            logger.warning(f"Impossible d'ajouter la réaction automatiquement: {e}")

        await interaction.response.send_message(
            f"Reaction-role créé sur le message `{message_id}` avec `{emoji_str}` pour {role.mention}.",
            ephemeral=True,
        )


class CreateRoleMenuModal(discord.ui.Modal, title="Nouveau menu de rôles"):
    def __init__(self, cog: ReactionRolesCog):
        super().__init__()
        self.cog = cog

        self.channel_input = discord.ui.TextInput(
            label="Salon (mention ou ID)",
            required=False,
            placeholder="#roles ou ID (vide = actuel)",
        )
        self.add_item(self.channel_input)

        self.title_input = discord.ui.TextInput(
            label="Titre du menu",
            required=True,
            placeholder="Rôles facultatifs",
        )
        self.add_item(self.title_input)

        self.placeholder_input = discord.ui.TextInput(
            label="Texte du menu",
            required=False,
            placeholder="Choisissez vos rôles",
        )
        self.add_item(self.placeholder_input)

        self.max_values_input = discord.ui.TextInput(
            label="Max rôles sélectionnables",
            required=False,
            placeholder="1",
        )
        self.add_item(self.max_values_input)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Action impossible en message privé.",
                ephemeral=True,
            )
            return

        # Channel
        raw_channel = self.channel_input.value.strip()
        channel: discord.TextChannel
        if not raw_channel:
            channel = interaction.channel  # type: ignore
        else:
            channel = None
            if raw_channel.startswith("<#") and raw_channel.endswith(">"):
                try:
                    cid = int(raw_channel[2:-1])
                    c = guild.get_channel(cid)
                    if isinstance(c, discord.TextChannel):
                        channel = c
                except ValueError:
                    pass
            if channel is None:
                try:
                    cid = int(raw_channel)
                    c = guild.get_channel(cid)
                    if isinstance(c, discord.TextChannel):
                        channel = c
                except ValueError:
                    pass

        if channel is None:
            await interaction.response.send_message(
                "Salon invalide.",
                ephemeral=True,
            )
            return

        titre = self.title_input.value.strip()
        placeholder = self.placeholder_input.value.strip() or "Choisissez vos rôles"

        max_values = 1
        if self.max_values_input.value.strip():
            try:
                max_values = max(1, int(self.max_values_input.value.strip()))
            except ValueError:
                pass

        menu_id = f"{guild.id}-{interaction.id}"

        embed = discord.Embed(
            title=titre,
            description="Sélectionnez les rôles dans le menu ci-dessous.",
            color=discord.Color.blurple(),
        )
        msg = await channel.send(embed=embed)

        menu_entry = {
            "id": menu_id,
            "guild_id": guild.id,
            "channel_id": channel.id,
            "message_id": msg.id,
            "placeholder": placeholder,
            "max_values": max_values,
            "roles": [],
        }

        self.cog.config.setdefault("role_menus", []).append(menu_entry)
        self.cog.save()

        await interaction.response.send_message(
            f"Menu de rôles créé avec ID `{menu_id}` dans {channel.mention}.\n"
            f"Utilise 'Configurer menus' pour y associer des rôles.",
            ephemeral=True,
        )


class MenuConfigSelectView(discord.ui.View):
    """
    Étape 1 : choisir quel menu de rôles configurer (via Select).
    """

    def __init__(self, cog: ReactionRolesCog, guild: discord.Guild):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild = guild
        self.menu_select: Optional[discord.ui.Select] = None

    async def populate(self) -> bool:
        menus = [m for m in self.cog.config.get("role_menus", []) if m["guild_id"] == self.guild.id]
        if not menus:
            return False

        options: List[discord.SelectOption] = []
        for m in menus[:25]:  # limite Discord : 25 options max[web:61]
            ch = self.guild.get_channel(m["channel_id"])
            label = f"{ch.name if ch else 'inconnu'} ({m['id'][-6:]})"
            desc = f"Menu ID: {m['id']}"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=m["id"],
                    description=desc[:100],
                )
            )

        select = discord.ui.Select(
            placeholder="Choisissez un menu à configurer",
            options=options,
        )
        select.callback = self.on_select_menu
        self.menu_select = select
        self.add_item(select)
        return True

    async def on_select_menu(self, interaction: discord.Interaction):
        menu_id = self.menu_select.values[0]
        new_view = MenuRoleConfigView(self.cog, menu_id)
        has_roles = await new_view.populate(interaction.guild)
        if not has_roles:
            await interaction.response.edit_message(
                content="Aucun rôle gérable trouvé (vérifie les permissions et la hiérarchie).",
                view=None,
            )
            return

        await interaction.response.edit_message(
            content=f"Configurez les rôles pour le menu `{menu_id}` :\n"
                    f"- Cochez les rôles à inclure dans le menu.\n"
                    f"- Décochez ceux à retirer.",
            view=new_view,
        )


class MenuRoleConfigView(discord.ui.View):
    """
    Étape 2 : choisir quels rôles sont inclus dans le menu sélectionné.
    """

    def __init__(self, cog: ReactionRolesCog, menu_id: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.menu_id = menu_id
        self.role_select: Optional[discord.ui.Select] = None

    async def populate(self, guild: discord.Guild) -> bool:
        menu = next((m for m in self.cog.config.get("role_menus", []) if m["id"] == self.menu_id), None)
        if not menu:
            return False

        # Rôles actuellement enregistrés dans le menu
        current_ids: Set[int] = {entry["role_id"] for entry in menu["roles"]}

        me = guild.me
        if me is None:
            return False

        # On liste les rôles que le bot peut gérer (sous son propre rôle, sauf @everyone)
        candidate_roles: List[discord.Role] = []
        for r in guild.roles:
            if r.is_default():
                continue
            if r.position >= me.top_role.position:
                continue
            candidate_roles.append(r)

        if not candidate_roles:
            return False

        # On limite à 25 pour respecter la limite Discord[web:61]
        candidate_roles = list(reversed(candidate_roles))[:25]

        options: List[discord.SelectOption] = []
        for role in candidate_roles:
            default_selected = role.id in current_ids
            options.append(
                discord.SelectOption(
                    label=role.name[:100],
                    value=str(role.id),
                    default=default_selected,
                )
            )

        select = discord.ui.Select(
            placeholder="Sélectionnez les rôles inclus dans ce menu",
            min_values=0,
            max_values=len(options),
            options=options,
        )
        select.callback = self.on_select_roles
        self.role_select = select
        self.add_item(select)
        return True

    async def on_select_roles(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Action impossible en message privé.",
                ephemeral=True,
            )
            return

        menu = next((m for m in self.cog.config.get("role_menus", []) if m["id"] == self.menu_id), None)
        if not menu:
            await interaction.response.send_message(
                "Menu introuvable.",
                ephemeral=True,
            )
            return

        selected_ids = {int(v) for v in self.role_select.values}

        # On reconstruit la liste des rôles du menu à partir des rôles sélectionnés
        new_entries: List[Dict[str, Any]] = []
        for rid in selected_ids:
            role = guild.get_role(rid)
            if not role:
                continue
            new_entries.append(
                {
                    "role_id": rid,
                    "emoji": None,
                    "label": role.name,
                    "description": None,
                }
            )

        menu["roles"] = new_entries
        self.cog.save()

        # On met à jour le vrai message du menu de rôles
        channel = guild.get_channel(menu["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Salon du menu introuvable.",
                ephemeral=True,
            )
            return

        try:
            msg = await channel.fetch_message(menu["message_id"])
        except discord.NotFound:
            await interaction.response.send_message(
                "Message du menu introuvable.",
                ephemeral=True,
            )
            return

        view = RoleSelectView(self.cog, self.menu_id)
        await msg.edit(view=view)

        await interaction.response.edit_message(
            content=f"Menu `{self.menu_id}` mis à jour. Rôles inclus : {len(new_entries)}.",
            view=None,
        )


class RoleSelectView(discord.ui.View):
    """Vue persistante pour un menu de rôles côté utilisateurs."""

    def __init__(self, cog: ReactionRolesCog, menu_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.menu_id = menu_id

        config = self.cog.config
        menu = next((m for m in config.get("role_menus", []) if m["id"] == menu_id), None)
        if not menu:
            return

        guild = self.cog.bot.get_guild(menu["guild_id"])
        if not guild:
            return

        options: List[discord.SelectOption] = []
        for entry in menu["roles"]:
            role = guild.get_role(entry["role_id"])
            if not role:
                continue
            label = entry.get("label") or role.name
            description = entry.get("description") or None
            emoji = entry.get("emoji") or None
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(role.id),
                    description=(description[:100] if description else None),
                    emoji=emoji,
                )
            )

        if not options:
            return

        max_values = menu.get("max_values") or 1
        max_values = min(max_values, len(options))

        select = discord.ui.Select(
            placeholder=menu.get("placeholder") or "Sélectionnez vos rôles",
            min_values=0,
            max_values=max_values,
            options=options,
            custom_id=f"role_menu:{menu_id}",
        )
        select.callback = self._callback
        self.add_item(select)

    async def _callback(self, interaction: discord.Interaction):
        menu = next((m for m in self.cog.config.get("role_menus", []) if m["id"] == self.menu_id), None)
        if not menu:
            await interaction.response.send_message(
                "Ce menu de rôles n'est plus configuré.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Action impossible en message privé.",
                ephemeral=True,
            )
            return

        member = interaction.user if isinstance(interaction.user, discord.Member) else guild.get_member(interaction.user.id)
        if member is None:
            await interaction.response.send_message(
                "Membre introuvable dans ce serveur.",
                ephemeral=True,
            )
            return

        selected_role_ids = {int(v) for v in interaction.data.get("values", [])}
        all_role_ids = {entry["role_id"] for entry in menu["roles"]}

        to_add = selected_role_ids
        to_remove = all_role_ids - selected_role_ids

        added = []
        removed = []

        for rid in to_add:
            role = guild.get_role(rid)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason=f"Role menu {self.menu_id}")
                    added.append(role.name)
                except discord.Forbidden:
                    logger.warning(f"Pas la permission d'ajouter {role} à {member}")
                except discord.HTTPException as e:
                    logger.error(f"Erreur add_roles: {e}")

        for rid in to_remove:
            role = guild.get_role(rid)
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason=f"Role menu {self.menu_id}")
                    removed.append(role.name)
                except discord.Forbidden:
                    logger.warning(f"Pas la permission de retirer {role} à {member}")
                except discord.HTTPException as e:
                    logger.error(f"Erreur remove_roles: {e}")

        parts = []
        if added:
            parts.append("Ajouté : " + ", ".join(added))
        if removed:
            parts.append("Retiré : " + ", ".join(removed))
        if not parts:
            parts.append("Aucun changement.")

        msg = "\n".join(parts)

        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    cog = ReactionRolesCog(bot)
    await bot.add_cog(cog)

    # Panneau persistant
    bot.add_view(ReactionPanelView(cog))

    # Menus de rôles persistants
    for menu in cog.config.get("role_menus", []):
        bot.add_view(RoleSelectView(cog, menu["id"]))