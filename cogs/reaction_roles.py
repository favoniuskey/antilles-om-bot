import discord
from discord.ext import commands
import json
import os
import logging
from typing import Optional, Dict, Any, List

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
    avec un panneau de gestion central.
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
                "Utilisez les boutons ci-dessous pour configurer les rôles :\n"
                "- Créer un reaction-role sur un message\n"
                "- Créer un menu déroulant de rôles\n"
                "- Ajouter un rôle à un menu existant\n"
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
            "Sous-commandes disponibles :\n"
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

        # On tente d'ajouter la réaction pour toi
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
        if not entries:
            await ctx.send("Aucun reaction-role configuré sur ce serveur.")
            return

        lines = []
        for e in entries[:20]:
            role = ctx.guild.get_role(e["role_id"])
            lines.append(
                f"- message `{e['message_id']}`, emoji `{e['emoji']}`, rôle: {role.mention if role else e['role_id']}"
            )

        if len(entries) > 20:
            lines.append(f"... ({len(entries) - 20} de plus)")

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

    # ========== ROLE MENUS (SELECT) ==========

    @commands.group(name="rolemenu", invoke_without_command=True)
    @commands.has_permissions(manage_roles=True)
    async def rolemenu_group(self, ctx: commands.Context):
        await ctx.send(
            "Sous-commandes :\n"
            "- `!rolemenu create <titre> <#salon> [max_values]`\n"
            "- `!rolemenu addrole <menu_id> <@role> [emoji] [label]`",
            delete_after=20,
        )

    @rolemenu_group.command(name="create")
    @commands.has_permissions(manage_roles=True)
    async def rolemenu_create(
        self,
        ctx: commands.Context,
        titre: str,
        channel: discord.TextChannel,
        max_values: Optional[int] = 1,
    ):
        await ctx.message.delete()

        menu_id = f"{ctx.guild.id}-{ctx.channel.id}-{ctx.message.id}"

        embed = discord.Embed(
            title=titre,
            description="Sélectionnez les rôles désirés dans le menu ci-dessous.",
            color=discord.Color.blurple(),
        )
        msg = await channel.send(embed=embed)

        menu_entry = {
            "id": menu_id,
            "guild_id": ctx.guild.id,
            "channel_id": channel.id,
            "message_id": msg.id,
            "placeholder": "Choisissez vos rôles",
            "max_values": max_values,
            "roles": [],
        }

        self.config.setdefault("role_menus", []).append(menu_entry)
        self.save()

        await ctx.send(
            f"Menu de rôles créé avec ID `{menu_id}`. "
            f"Ajoutez des rôles avec `!rolemenu addrole {menu_id} @role [emoji] [label]`.",
            delete_after=20,
        )

    @rolemenu_group.command(name="addrole")
    @commands.has_permissions(manage_roles=True)
    async def rolemenu_addrole(
        self,
        ctx: commands.Context,
        menu_id: str,
        role: discord.Role,
        emoji: Optional[str] = None,
        *,
        label: Optional[str] = None,
    ):
        await ctx.message.delete()

        menu = next((m for m in self.config.get("role_menus", []) if m["id"] == menu_id), None)
        if not menu:
            await ctx.send("Menu introuvable. Vérifie l'ID.", delete_after=10)
            return

        menu["roles"].append(
            {
                "role_id": role.id,
                "emoji": emoji,
                "label": label or role.name,
                "description": None,
            }
        )
        self.save()

        guild = ctx.guild
        channel = guild.get_channel(menu["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            await ctx.send("Salon du menu introuvable.", delete_after=10)
            return

        try:
            msg = await channel.fetch_message(menu["message_id"])
        except discord.NotFound:
            await ctx.send("Message du menu introuvable.", delete_after=10)
            return

        view = RoleSelectView(self, menu_id)
        await msg.edit(view=view)

        await ctx.send(
            f"Rôle {role.mention} ajouté au menu `{menu_id}`.",
            delete_after=10,
        )


# ========== VUES & MODALS ==========


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
        label="Ajouter rôle à un menu",
        style=discord.ButtonStyle.secondary,
        custom_id="rr:addrole_menu",
    )
    async def addrole_menu_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not self.user_allowed(interaction.user):
            await interaction.response.send_message(
                "Tu n'as pas la permission de gérer les rôles.",
                ephemeral=True,
            )
            return

        modal = AddRoleToMenuModal(self.cog)
        await interaction.response.send_modal(modal)

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


class CreateReactionRoleModal(discord.ui.Modal, title="Créer un reaction-role"):
    def __init__(self, cog: ReactionRolesCog):
        super().__init__()
        self.cog = cog

        self.channel_input = discord.ui.TextInput(
            label="Salon (mention ou ID, vide = salon du message)",
            required=False,
            placeholder="#règlement ou ID",
        )
        self.add_item(self.channel_input)

        self.message_input = discord.ui.TextInput(
            label="ID ou URL du message",
            required=True,
            placeholder="1234567890 ou https://discord.com/channels/...",
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
                "Action indisponible en message privé.",
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

        # Emoji
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

        # Enregistrement config
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

        # On tente d'ajouter la réaction
        try:
            msg = await channel.fetch_message(message_id)
            await msg.add_reaction(emoji_str)
        except Exception as e:
            logger.warning(f"Impossible d'ajouter la réaction automatiquement: {e}")

        await interaction.response.send_message(
            f"Reaction-role créé sur le message `{message_id}` avec l'emoji `{emoji_str}` pour le rôle {role.mention}.",
            ephemeral=True,
        )


class CreateRoleMenuModal(discord.ui.Modal, title="Créer un menu de rôles"):
    def __init__(self, cog: ReactionRolesCog):
        super().__init__()
        self.cog = cog

        self.channel_input = discord.ui.TextInput(
            label="Salon (mention ou ID, vide = salon actuel)",
            required=False,
            placeholder="#roles ou ID",
        )
        self.add_item(self.channel_input)

        self.title_input = discord.ui.TextInput(
            label="Titre du menu",
            required=True,
            placeholder="Rôles facultatifs",
        )
        self.add_item(self.title_input)

        self.placeholder_input = discord.ui.TextInput(
            label="Texte du menu (placeholder)",
            required=False,
            placeholder="Choisissez vos rôles",
        )
        self.add_item(self.placeholder_input)

        self.max_values_input = discord.ui.TextInput(
            label="Nombre max de rôles sélectionnables (1 par défaut)",
            required=False,
            placeholder="1",
        )
        self.add_item(self.max_values_input)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Action indisponible en message privé.",
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
            description="Sélectionnez les rôles désirés dans le menu ci-dessous.",
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
            f"Ajoute des rôles avec le bouton 'Ajouter rôle à un menu' ou la commande `!rolemenu addrole`.",
            ephemeral=True,
        )


class AddRoleToMenuModal(discord.ui.Modal, title="Ajouter un rôle à un menu"):
    def __init__(self, cog: ReactionRolesCog):
        super().__init__()
        self.cog = cog

        self.menu_id_input = discord.ui.TextInput(
            label="ID du menu",
            required=True,
            placeholder="ID donné lors de la création",
        )
        self.add_item(self.menu_id_input)

        self.role_input = discord.ui.TextInput(
            label="Rôle (mention ou ID)",
            required=True,
            placeholder="@Membre ou 1234567890",
        )
        self.add_item(self.role_input)

        self.emoji_input = discord.ui.TextInput(
            label="Emoji (optionnel)",
            required=False,
            placeholder="✅",
        )
        self.add_item(self.emoji_input)

        self.label_input = discord.ui.TextInput(
            label="Label (optionnel, vide = nom du rôle)",
            required=False,
            placeholder="Nom affiché dans le menu",
        )
        self.add_item(self.label_input)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Action indisponible en message privé.",
                ephemeral=True,
            )
            return

        menu_id = self.menu_id_input.value.strip()
        menu = next((m for m in self.cog.config.get("role_menus", []) if m["id"] == menu_id), None)
        if not menu:
            await interaction.response.send_message(
                "Menu introuvable. Vérifie l'ID.",
                ephemeral=True,
            )
            return

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

        emoji = self.emoji_input.value.strip() or None
        label = self.label_input.value.strip() or role.name

        menu["roles"].append(
            {
                "role_id": role.id,
                "emoji": emoji,
                "label": label,
                "description": None,
            }
        )
        self.cog.save()

        channel = guild.get_channel(menu["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Salon du menu introuvable (ou non textuel).",
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

        view = RoleSelectView(self.cog, menu_id)
        await msg.edit(view=view)

        await interaction.response.send_message(
            f"Rôle {role.mention} ajouté au menu `{menu_id}`.",
            ephemeral=True,
        )


class RoleSelectView(discord.ui.View):
    """Vue persistante pour un menu de rôles."""

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

        options = []
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
                "Action indisponible en message privé.",
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
        all_role_ids = {int(opt["value"]) for opt in interaction.data["component"]["options"]}

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