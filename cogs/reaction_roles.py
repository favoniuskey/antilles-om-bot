import discord
from discord.ext import commands
import json
import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("reaction_roles")

DATA_DIR = "utils/data"
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(DATA_DIR, "reaction_roles.json")


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


class RoleSelectView(discord.ui.View):
    """
    Vue persistante pour un menu déroulant de rôles.
    Liée à un message via message_id dans la config.
    """

    def __init__(self, cog: "ReactionRolesCog", menu_id: str):
        super().__init__(timeout=None)  # persistante
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
            emoji = None
            if entry.get("emoji"):
                emoji = entry["emoji"]
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
        all_role_ids = {int(opt.value) for opt in interaction.data["component"]["options"]}

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


class ReactionRolesCog(commands.Cog):
    """
    Gestion des rôles par réactions ET par menu déroulant.
    - Reaction roles: réaction emoji sur un message -> rôle
    - Role menus: Select menu persistant avec un ensemble de rôles
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

    # ========== REACTION ROLES ==========

    @commands.group(name="rr", invoke_without_command=True)
    @commands.has_permissions(manage_roles=True)
    async def rr_group(self, ctx: commands.Context):
        """Groupe de commandes pour configurer les reaction roles."""
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
        """
        Ajoute une entrée reaction-role :
        Quand un membre réagit avec <emoji> sur <message_id>, on lui donne <role>.
        """
        await ctx.message.delete()

        channel = ctx.channel
        msg = None
        try:
            msg = await channel.fetch_message(message_id)
        except discord.NotFound:
            # On ne bloque pas : on peut vouloir réagir sur un message d'un autre salon
            pass

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

        await ctx.send(
            f"Reaction-role ajouté : message `{message_id}`, emoji `{emoji_str}`, rôle {role.mention}.",
            delete_after=10,
        )

    @rr_group.command(name="remove")
    @commands.has_permissions(manage_roles=True)
    async def rr_remove(self, ctx: commands.Context, message_id: int, emoji: str):
        """Supprime une entrée reaction-role."""
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
        """Liste les reaction roles configurés pour ce serveur."""
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
        """
        Donne un rôle quand quelqu'un réagit avec un emoji configuré
        sur un message configuré.
        Utilise on_raw_reaction_add pour marcher même si le message n'est pas en cache.[web:112]
        """
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
        """
        Retire le rôle quand quelqu'un retire sa réaction.
        """
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
        """Groupe de commandes pour configurer les menus de rôles (Select)."""
        await ctx.send(
            "Sous-commandes :\n"
            "- `!rolemenu create <titre> <#salon>`\n"
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
        """
        Crée un menu déroulant de rôles dans un salon.
        Étape suivante : ajouter des rôles avec !rolemenu addrole
        """
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

        # Comme il n'y a pas encore de rôles, on n'ajoute pas encore la vue.
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
        """
        Ajoute un rôle dans un menu de rôles existant.
        Exemple :
        !rolemenu addrole <menu_id> @Membre ✅ "Accès serveur"
        """
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

        # Mettre à jour le message avec la vue
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


async def setup(bot: commands.Bot):
    cog = ReactionRolesCog(bot)
    await bot.add_cog(cog)

    # Enregistre les vues persistantes pour les menus déjà existants
    for menu in cog.config.get("role_menus", []):
        bot.add_view(RoleSelectView(cog, menu["id"]))