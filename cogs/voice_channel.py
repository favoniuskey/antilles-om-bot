import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
import json
import os
import asyncio
import datetime
import logging
from typing import Optional, Dict, List
from pathlib import Path
import time

# =============================================================================
# IMPORTS & CONFIGURATION
# =============================================================================

logger = logging.getLogger("voice_channels")
logger.setLevel(logging.INFO)
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
handler = logging.FileHandler(
    filename=log_dir / "voice_channels.log",
    encoding="utf-8",
    mode="a"
)
formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
handler.setFormatter(formatter)
logger.addHandler(handler)

EMBED_COLOR = 0x00BCD4
CATEGORY_USER_ID = 1224706989146378373
MAX_CHANNELS_PER_USER = 3
CLEANUP_INTERVAL = 1  # 1 minute pour cleanup plus agressif

THEMES = {
    "standard": "🏝️", "plage": "🏖️", "jungle": "🌴", "volcan": "🌋", "lagon": "🐠",
    "gaming": "🎮", "music": "🎵", "study": "📚", "chill": "😎", "party": "🎉",
    "work": "💼", "podcast": "🎙️", "creative": "🎨", "streaming": "📺",
}

# =============================================================================
# SERVICE LAYER
# =============================================================================

class VoiceChannelService:
    """Gestion persistance des données"""

    def __init__(self, data_file: str = "voice_channels.json"):
        self.data_file = Path(data_file)
        self.channels: Dict = {}
        self.lock = asyncio.Lock()
        self.load_data()

    def load_data(self) -> None:
        try:
            if self.data_file.exists():
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.channels = {str(k): v for k, v in data.items()}
                logger.info(f"✅ {len(self.channels)} salons chargés")
            else:
                self.channels = {}
        except json.JSONDecodeError:
            logger.error("❌ JSON corrompu, réinitialisation")
            self.channels = {}
            self.save_data()
        except Exception as e:
            logger.error(f"❌ Erreur chargement: {e}", exc_info=True)
            self.channels = {}

    def save_data(self) -> None:
        try:
            temp_file = self.data_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.channels, f, ensure_ascii=False, indent=2)
            backup_file = self.data_file.with_suffix(".backup")
            if self.data_file.exists():
                self.data_file.rename(backup_file)
            temp_file.rename(self.data_file)
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde: {e}", exc_info=True)

    async def add_channel(self, channel_id: int, owner_id: int, data: Dict) -> None:
        async with self.lock:
            self.channels[str(channel_id)] = {
                "owner_id": str(owner_id),
                "created_at": datetime.datetime.now().isoformat(),
                "type": data.get("type", "public"),
                "name": data.get("name", ""),
                "user_limit": int(data.get("user_limit", 0)),
                "theme": data.get("theme", "standard"),
                "locked": bool(data.get("locked", False)),
                "bitrate": int(data.get("bitrate", 96000)),
                "description": data.get("description", ""),
                "blacklist": list(data.get("blacklist", [])),
                "whitelist": list(data.get("whitelist", [])),
                "stats": {
                    "total_joins": 0,
                    "peak_members": 1,
                    "created_timestamp": time.time(),
                }
            }
            self.save_data()

    async def remove_channel(self, channel_id: int) -> bool:
        async with self.lock:
            if str(channel_id) in self.channels:
                del self.channels[str(channel_id)]
                self.save_data()
                return True
        return False

    def get_channel(self, channel_id: int) -> Optional[Dict]:
        return self.channels.get(str(channel_id))

    async def update_channel(self, channel_id: int, data: Dict) -> bool:
        async with self.lock:
            if str(channel_id) in self.channels:
                self.channels[str(channel_id)].update(data)
                self.save_data()
                return True
        return False

    def get_owner_channels(self, owner_id: int) -> Dict:
        return {k: v for k, v in self.channels.items() if v.get("owner_id") == str(owner_id)}

    async def increment_join_stats(self, channel_id: int, current_members: int) -> None:
        async with self.lock:
            if str(channel_id) in self.channels:
                stats = self.channels[str(channel_id)].get("stats", {})
                stats["total_joins"] = stats.get("total_joins", 0) + 1
                stats["peak_members"] = max(stats.get("peak_members", 1), current_members)
                self.channels[str(channel_id)]["stats"] = stats
                self.save_data()

# =============================================================================
# MODALS
# =============================================================================

class RenameModal(ui.Modal, title="✏️ Renommer"):
    def __init__(self, cog, channel_id: int):
        super().__init__()
        self.cog = cog
        self.channel_id = channel_id
        self.name_input = ui.TextInput(
            label="Nouveau nom",
            placeholder="Gaming squad",
            required=True,
            max_length=50
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            channel = interaction.guild.get_channel(self.channel_id)
            channel_data = self.cog.voice_data.get_channel(self.channel_id)
            if not channel or not channel_data:
                return await interaction.response.send_message("❌ Salon introuvable", ephemeral=True)
            
            theme = channel_data.get("theme", "standard")
            emoji = THEMES.get(theme, "🏝️")
            new_name = f"{emoji} {self.name_input.value}"
            
            await channel.edit(name=new_name)
            await self.cog.voice_data.update_channel(self.channel_id, {"name": new_name})
            await interaction.response.send_message(f"✅ Renommé: {new_name}", ephemeral=True)
        except Exception as e:
            logger.error(f"Erreur renommage: {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)


class LimitModal(ui.Modal, title="👥 Limite"):
    def __init__(self, cog, channel_id: int, current_limit: int):
        super().__init__()
        self.cog = cog
        self.channel_id = channel_id
        self.limit_input = ui.TextInput(
            label="Limite (0-99)",
            default=str(current_limit),
            required=True,
            max_length=2
        )
        self.add_item(self.limit_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = max(0, min(99, int(self.limit_input.value)))
            channel = interaction.guild.get_channel(self.channel_id)
            if not channel:
                return await interaction.response.send_message("❌ Salon introuvable", ephemeral=True)
            
            await channel.edit(user_limit=limit)
            await self.cog.voice_data.update_channel(self.channel_id, {"user_limit": limit})
            await interaction.response.send_message(
                f"✅ Limite: {limit if limit > 0 else 'Illimitée'}",
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message("❌ Nombre invalide", ephemeral=True)
        except Exception as e:
            logger.error(f"Erreur limite: {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)


class DescriptionModal(ui.Modal, title="📝 Description"):
    def __init__(self, cog, channel_id: int):
        super().__init__()
        self.cog = cog
        self.channel_id = channel_id
        self.desc_input = ui.TextInput(
            label="Description",
            placeholder="Décrivez votre salon...",
            required=False,
            max_length=200,
            style=ui.TextInputStyle.paragraph
        )
        self.add_item(self.desc_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            channel = interaction.guild.get_channel(self.channel_id)
            if not channel:
                return await interaction.response.send_message("❌ Salon introuvable", ephemeral=True)
            
            await channel.edit(topic=self.desc_input.value)
            await self.cog.voice_data.update_channel(self.channel_id, {"description": self.desc_input.value})
            await interaction.response.send_message("✅ Description mise à jour", ephemeral=True)
        except Exception as e:
            logger.error(f"Erreur description: {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)


class BitrateModal(ui.Modal, title="🔊 Bitrate"):
    def __init__(self, cog, channel_id: int):
        super().__init__()
        self.cog = cog
        self.channel_id = channel_id
        self.bitrate_input = ui.TextInput(
            label="Bitrate (64-320 kbps)",
            placeholder="128",
            required=True,
            max_length=3
        )
        self.add_item(self.bitrate_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            bitrate = max(64000, min(320000, int(self.bitrate_input.value) * 1000))
            channel = interaction.guild.get_channel(self.channel_id)
            if not channel:
                return await interaction.response.send_message("❌ Salon introuvable", ephemeral=True)
            
            await channel.edit(bitrate=bitrate)
            await self.cog.voice_data.update_channel(self.channel_id, {"bitrate": bitrate})
            await interaction.response.send_message(f"✅ Bitrate: {bitrate // 1000} kbps", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Nombre invalide", ephemeral=True)
        except Exception as e:
            logger.error(f"Erreur bitrate: {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)


class SearchUserModal(ui.Modal, title="🔍 Rechercher"):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.search_input = ui.TextInput(
            label="Nom ou ID",
            placeholder="Entrez un nom...",
            required=True,
            min_length=2,
            max_length=100
        )
        self.add_item(self.search_input)

    async def on_submit(self, interaction: discord.Interaction):
        await self.callback(interaction, self.search_input.value)

# =============================================================================
# VIEWS
# =============================================================================

class ConfirmView(ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.value = None

    @ui.button(label="Confirmer", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        await interaction.response.defer()

    @ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        await interaction.response.defer()


class ThemeSelectView(ui.View):
    def __init__(self, cog, channel_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.channel_id = channel_id
        
        select = ui.Select(
            placeholder="Choisir un thème...",
            options=[
                discord.SelectOption(label=name.capitalize(), value=name, emoji=emoji)
                for name, emoji in list(THEMES.items())[:25]
            ]
        )
        select.callback = self.theme_select_callback
        self.add_item(select)

    async def theme_select_callback(self, interaction: discord.Interaction):
        try:
            theme = interaction.data["values"][0]
            emoji = THEMES.get(theme, "🏝️")
            channel = interaction.guild.get_channel(self.channel_id)
            if channel:
                channel_data = self.cog.voice_data.get_channel(self.channel_id)
                name_part = channel_data.get('name', '').split()[-1] if channel_data else interaction.user.display_name
                new_name = f"{emoji} {name_part}"
                await channel.edit(name=new_name)
                await self.cog.voice_data.update_channel(self.channel_id, {"theme": theme})
                await interaction.response.send_message(f"✅ Thème: {theme.capitalize()}", ephemeral=True)
                self.stop()
        except Exception as e:
            logger.error(f"Erreur thème: {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)


class UserSearchResultView(ui.View):
    def __init__(self, members, callback, page: int = 0):
        super().__init__(timeout=60)
        self.members = members
        self.callback = callback
        self.page = page
        self.members_per_page = 10
        self.total_pages = max(1, (len(members) + self.members_per_page - 1) // self.members_per_page)
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        start = self.page * self.members_per_page
        end = min(start + self.members_per_page, len(self.members))
        
        for i in range(start, end):
            member = self.members[i]
            button = ui.Button(
                style=discord.ButtonStyle.secondary,
                label=member.display_name[:20],
                custom_id=f"user_{member.id}"
            )
            
            async def user_callback(interaction: discord.Interaction, m=member):
                await self.callback(interaction, m)
                self.stop()
            
            button.callback = user_callback
            self.add_item(button)
        
        if self.total_pages > 1:
            prev_btn = ui.Button(
                style=discord.ButtonStyle.primary,
                label="◀️ Précédent",
                disabled=self.page == 0,
                row=4
            )
            async def prev_cb(interaction: discord.Interaction):
                self.page = max(0, self.page - 1)
                self.update_buttons()
                await interaction.response.edit_message(view=self)
            prev_btn.callback = prev_cb
            self.add_item(prev_btn)
            
            next_btn = ui.Button(
                style=discord.ButtonStyle.primary,
                label="Suivant ▶️",
                disabled=self.page >= self.total_pages - 1,
                row=4
            )
            async def next_cb(interaction: discord.Interaction):
                self.page = min(self.total_pages - 1, self.page + 1)
                self.update_buttons()
                await interaction.response.edit_message(view=self)
            next_btn.callback = next_cb
            self.add_item(next_btn)


class ChannelControlPanel(ui.View):
    """Panneau de contrôle complet"""

    def __init__(self, cog, channel_id: int, owner_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.channel_id = channel_id
        self.owner_id = owner_id

    def _check_owner(self, user_id: int) -> bool:
        return user_id == self.owner_id

    # RANGÉE 1 - Contrôles principaux
    @ui.button(label="Verrouiller", emoji="🔒", style=discord.ButtonStyle.secondary, row=0)
    async def lock_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_owner(interaction.user.id):
            return await interaction.response.send_message("🚫 Non autorisé", ephemeral=True)
        
        try:
            channel = interaction.guild.get_channel(self.channel_id)
            channel_data = self.cog.voice_data.get_channel(self.channel_id)
            
            if not channel or not channel_data:
                return await interaction.response.send_message("❌ Salon introuvable", ephemeral=True)
            
            locked = not channel_data.get("locked", False)
            await self.cog.voice_data.update_channel(self.channel_id, {"locked": locked})
            
            if locked:
                await channel.set_permissions(interaction.guild.default_role, connect=False)
                button.label = "Déverrouiller"
                button.emoji = "🔓"
            else:
                if channel_data.get("type") == "public":
                    await channel.set_permissions(interaction.guild.default_role, connect=True)
                button.label = "Verrouiller"
                button.emoji = "🔒"
            
            await interaction.message.edit(view=self)
            await interaction.response.send_message(
                f"{'🔒 Verrouillé' if locked else '🔓 Déverrouillé'}",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Erreur verrou: {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @ui.button(label="Renommer", emoji="✏️", style=discord.ButtonStyle.secondary, row=0)
    async def rename_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_owner(interaction.user.id):
            return await interaction.response.send_message("🚫 Non autorisé", ephemeral=True)
        
        modal = RenameModal(self.cog, self.channel_id)
        await interaction.response.send_modal(modal)

    @ui.button(label="Limite", emoji="👥", style=discord.ButtonStyle.secondary, row=0)
    async def limit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_owner(interaction.user.id):
            return await interaction.response.send_message("🚫 Non autorisé", ephemeral=True)
        
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            return await interaction.response.send_message("❌ Salon introuvable", ephemeral=True)
        
        modal = LimitModal(self.cog, self.channel_id, channel.user_limit)
        await interaction.response.send_modal(modal)

    @ui.button(label="Type", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def type_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_owner(interaction.user.id):
            return await interaction.response.send_message("🚫 Non autorisé", ephemeral=True)
        
        try:
            channel = interaction.guild.get_channel(self.channel_id)
            channel_data = self.cog.voice_data.get_channel(self.channel_id)
            
            if not channel or not channel_data:
                return await interaction.response.send_message("❌ Salon introuvable", ephemeral=True)
            
            current_type = channel_data.get("type", "public")
            new_type = "private" if current_type == "public" else "public"
            
            if new_type == "public":
                await channel.set_permissions(interaction.guild.default_role, connect=True)
            else:
                await channel.set_permissions(interaction.guild.default_role, connect=False)
            
            await self.cog.voice_data.update_channel(self.channel_id, {"type": new_type})
            await interaction.response.send_message(
                f"📝 Salon {'public' if new_type == 'public' else 'privé'}",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Erreur type: {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    # RANGÉE 2 - Personnalisation
    @ui.button(label="Description", emoji="📝", style=discord.ButtonStyle.secondary, row=1)
    async def desc_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_owner(interaction.user.id):
            return await interaction.response.send_message("🚫 Non autorisé", ephemeral=True)
        
        modal = DescriptionModal(self.cog, self.channel_id)
        await interaction.response.send_modal(modal)

    @ui.button(label="Bitrate", emoji="🔊", style=discord.ButtonStyle.secondary, row=1)
    async def bitrate_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_owner(interaction.user.id):
            return await interaction.response.send_message("🚫 Non autorisé", ephemeral=True)
        
        modal = BitrateModal(self.cog, self.channel_id)
        await interaction.response.send_modal(modal)

    @ui.button(label="Thème", emoji="🎨", style=discord.ButtonStyle.secondary, row=1)
    async def theme_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_owner(interaction.user.id):
            return await interaction.response.send_message("🚫 Non autorisé", ephemeral=True)
        
        view = ThemeSelectView(self.cog, self.channel_id)
        await interaction.response.send_message("Choisir un thème:", view=view, ephemeral=True)

    # RANGÉE 3 - Gestion membres
    @ui.button(label="Inviter", emoji="👋", style=discord.ButtonStyle.success, row=2)
    async def invite_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_owner(interaction.user.id):
            return await interaction.response.send_message("🚫 Non autorisé", ephemeral=True)
        
        modal = SearchUserModal(self.search_and_invite)
        await interaction.response.send_modal(modal)

    async def search_and_invite(self, interaction: discord.Interaction, search_query: str):
        guild = interaction.guild
        found_members = []
        search_query = search_query.lower()
        
        if search_query.isdigit():
            member = guild.get_member(int(search_query))
            if member and not member.bot and member.id != self.owner_id:
                found_members.append(member)
        
        for member in guild.members:
            if (member not in found_members and not member.bot and member.id != self.owner_id and
                (search_query in member.name.lower() or search_query in member.display_name.lower())):
                found_members.append(member)
        
        if not found_members:
            return await interaction.response.send_message("❌ Aucun utilisateur trouvé", ephemeral=True)
        
        view = UserSearchResultView(found_members, self.invite_user)
        await interaction.response.send_message(
            f"Résultats ({len(found_members)} trouvé(s)):",
            view=view,
            ephemeral=True
        )

    async def invite_user(self, interaction: discord.Interaction, user):
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            return await interaction.response.send_message("❌ Salon introuvable", ephemeral=True)
        
        try:
            await channel.set_permissions(user, connect=True)
            
            channel_data = self.cog.voice_data.get_channel(self.channel_id)
            if channel_data:
                whitelist = channel_data.get("whitelist", [])
                if str(user.id) not in whitelist:
                    whitelist.append(str(user.id))
                
                blacklist = channel_data.get("blacklist", [])
                if str(user.id) in blacklist:
                    blacklist.remove(str(user.id))
                
                await self.cog.voice_data.update_channel(self.channel_id, {
                    "whitelist": whitelist,
                    "blacklist": blacklist
                })
            
            try:
                embed = discord.Embed(
                    title="🌴 Invitation",
                    description=f"Vous avez été invité au salon **{channel.name}**",
                    color=EMBED_COLOR
                )
                await user.send(embed=embed)
            except:
                pass
            
            await interaction.response.send_message(f"✅ {user.mention} invité", ephemeral=True)
        except Exception as e:
            logger.error(f"Erreur invitation: {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @ui.button(label="Expulser", emoji="👢", style=discord.ButtonStyle.danger, row=2)
    async def kick_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_owner(interaction.user.id):
            return await interaction.response.send_message("🚫 Non autorisé", ephemeral=True)
        
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            return await interaction.response.send_message("❌ Salon introuvable", ephemeral=True)
        
        members = [m for m in channel.members if m.id != self.owner_id]
        if not members:
            return await interaction.response.send_message("❌ Aucun membre", ephemeral=True)
        
        view = UserSearchResultView(members, self.kick_user)
        await interaction.response.send_message("Sélectionnez un utilisateur à expulser:", view=view, ephemeral=True)

    async def kick_user(self, interaction: discord.Interaction, user):
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            return await interaction.response.send_message("❌ Salon introuvable", ephemeral=True)
        
        try:
            if user.voice and user.voice.channel and user.voice.channel.id == self.channel_id:
                await user.move_to(None)
            
            await channel.set_permissions(user, connect=False)
            
            channel_data = self.cog.voice_data.get_channel(self.channel_id)
            if channel_data:
                blacklist = channel_data.get("blacklist", [])
                if str(user.id) not in blacklist:
                    blacklist.append(str(user.id))
                
                whitelist = channel_data.get("whitelist", [])
                if str(user.id) in whitelist:
                    whitelist.remove(str(user.id))
                
                await self.cog.voice_data.update_channel(self.channel_id, {
                    "blacklist": blacklist,
                    "whitelist": whitelist
                })
            
            await interaction.response.send_message(f"✅ {user.mention} expulsé", ephemeral=True)
        except Exception as e:
            logger.error(f"Erreur expulsion: {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @ui.button(label="Blacklist", emoji="🚫", style=discord.ButtonStyle.secondary, row=2)
    async def blacklist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_owner(interaction.user.id):
            return await interaction.response.send_message("🚫 Non autorisé", ephemeral=True)
        
        channel_data = self.cog.voice_data.get_channel(self.channel_id)
        blacklist = channel_data.get("blacklist", []) if channel_data else []
        
        embed = discord.Embed(
            title="🚫 Blacklist",
            description=f"{len(blacklist)} utilisateur(s) bloqués",
            color=EMBED_COLOR
        )
        
        if blacklist:
            users_list = []
            for uid in blacklist:
                user = interaction.guild.get_member(int(uid))
                if user:
                    users_list.append(f"• {user.mention}")
            embed.add_field(name="Utilisateurs", value="\n".join(users_list), inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Whitelist", emoji="✅", style=discord.ButtonStyle.secondary, row=2)
    async def whitelist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_owner(interaction.user.id):
            return await interaction.response.send_message("🚫 Non autorisé", ephemeral=True)
        
        channel_data = self.cog.voice_data.get_channel(self.channel_id)
        whitelist = channel_data.get("whitelist", []) if channel_data else []
        
        embed = discord.Embed(
            title="✅ Whitelist",
            description=f"{len(whitelist)} utilisateur(s) autorisés",
            color=EMBED_COLOR
        )
        
        if whitelist:
            users_list = []
            for uid in whitelist:
                user = interaction.guild.get_member(int(uid))
                if user:
                    users_list.append(f"• {user.mention}")
            embed.add_field(name="Utilisateurs", value="\n".join(users_list), inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # RANGÉE 4 - Infos & Actions
    @ui.button(label="Membres", emoji="👥", style=discord.ButtonStyle.primary, row=3)
    async def members_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_owner(interaction.user.id):
            return await interaction.response.send_message("🚫 Non autorisé", ephemeral=True)
        
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            return await interaction.response.send_message("❌ Salon introuvable", ephemeral=True)
        
        if not channel.members:
            return await interaction.response.send_message("❌ Aucun membre", ephemeral=True)
        
        members_list = []
        for member in channel.members:
            status = " 👑" if member.id == self.owner_id else ""
            members_list.append(f"• {member.mention}{status}")
        
        embed = discord.Embed(
            title=f"👥 Membres ({len(channel.members)})",
            description="\n".join(members_list),
            color=EMBED_COLOR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Stats", emoji="📊", style=discord.ButtonStyle.primary, row=3)
    async def stats_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_owner(interaction.user.id):
            return await interaction.response.send_message("🚫 Non autorisé", ephemeral=True)
        
        channel_data = self.cog.voice_data.get_channel(self.channel_id)
        if not channel_data:
            return await interaction.response.send_message("❌ Données introuvables", ephemeral=True)
        
        stats = channel_data.get("stats", {})
        created_at = datetime.datetime.fromisoformat(channel_data.get("created_at"))
        uptime = datetime.datetime.now() - created_at
        
        embed = discord.Embed(
            title="📊 Statistiques",
            color=EMBED_COLOR
        )
        embed.add_field(name="Total joins", value=f"{stats.get('total_joins', 0)}", inline=True)
        embed.add_field(name="Peak simultané", value=f"{stats.get('peak_members', 1)}", inline=True)
        embed.add_field(name="Temps de vie", value=f"{uptime.days}j {uptime.seconds // 3600}h {(uptime.seconds // 60) % 60}m", inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Supprimer", emoji="🗑️", style=discord.ButtonStyle.danger, row=3)
    async def delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_owner(interaction.user.id):
            return await interaction.response.send_message("🚫 Non autorisé", ephemeral=True)
        
        view = ConfirmView()
        await interaction.response.send_message("❓ Êtes-vous sûr?", view=view, ephemeral=True)
        await view.wait()
        if view.value:
            await self.cog.delete_voice_channel(interaction, self.channel_id)

# =============================================================================
# COG PRINCIPAL
# =============================================================================

class VoiceChannelsCog(commands.Cog):
    """🌴 Système de salons vocaux Antilles Premium v6.0"""

    def __init__(self, bot):
        self.bot = bot
        self.voice_data = VoiceChannelService()
        self.creator_channel_id: Optional[int] = None
        self.cleanup_empty_channels.start()
        self.load_config()

    def load_config(self) -> None:
        try:
            if os.path.exists("voice_config.json"):
                with open("voice_config.json", "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.creator_channel_id = config.get("creator_channel_id")
                logger.info("✅ Configuration chargée")
        except Exception as e:
            logger.error(f"Erreur config: {e}", exc_info=True)

    def save_config(self) -> None:
        try:
            config = {"creator_channel_id": self.creator_channel_id}
            with open("voice_config.json", "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            logger.error(f"Erreur sauvegarde config: {e}", exc_info=True)

    def cog_unload(self):
        self.cleanup_empty_channels.cancel()

    @tasks.loop(minutes=CLEANUP_INTERVAL)
    async def cleanup_empty_channels(self):
        """Nettoie les salons vides - CORRIGÉ"""
        try:
            await self.bot.wait_until_ready()
            logger.debug("🧹 Nettoyage des salons en cours...")
            
            for guild in self.bot.guilds:
                # Copier la liste des IDs pour éviter les problèmes de modification pendant l'itération
                channel_ids = list(self.voice_data.channels.keys())
                
                for channel_id in channel_ids:
                    try:
                        channel = guild.get_channel(int(channel_id))
                        
                        # Si le canal n'existe pas dans Discord
                        if not channel:
                            await self.voice_data.remove_channel(int(channel_id))
                            logger.info(f"🧹 Salon {channel_id} supprimé (inexistant)")
                            continue
                        
                        # Si le canal est vide
                        if len(channel.members) == 0:
                            try:
                                await channel.delete(reason="Nettoyage - salon vide")
                                await self.voice_data.remove_channel(int(channel_id))
                                logger.info(f"🧹 Salon {channel.name} supprimé (vide)")
                            except discord.errors.NotFound:
                                await self.voice_data.remove_channel(int(channel_id))
                                logger.info(f"🧹 Salon {channel_id} supprimé (déjà disparu)")
                            except Exception as e:
                                logger.error(f"Erreur suppression salon {channel_id}: {e}")
                    
                    except Exception as e:
                        logger.error(f"Erreur traitement salon {channel_id}: {e}")
        
        except Exception as e:
            logger.error(f"Erreur tâche cleanup: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Gestion des changements d'état vocal"""
        if member.bot:
            return

        try:
            # Création du salon
            if after.channel and self.creator_channel_id and after.channel.id == self.creator_channel_id:
                await self.create_voice_channel(member)
                return

            # Stats d'entrée
            if after.channel and not before.channel:
                channel_data = self.voice_data.get_channel(after.channel.id)
                if channel_data:
                    await self.voice_data.increment_join_stats(after.channel.id, len(after.channel.members))

            # Suppression salon vide (redondant mais utile)
            if before.channel and not after.channel:
                if len(before.channel.members) == 0:
                    channel_data = self.voice_data.get_channel(before.channel.id)
                    if channel_data:
                        try:
                            await before.channel.delete(reason="Salon vide")
                            await self.voice_data.remove_channel(before.channel.id)
                            logger.info(f"🧹 Salon {before.channel.name} supprimé (dernier membre parti)")
                        except Exception as e:
                            logger.error(f"Erreur suppression auto: {e}")
        except Exception as e:
            logger.error(f"Erreur voice state: {e}", exc_info=True)

    async def create_voice_channel(self, member: discord.Member):
        """Crée un salon vocal personnalisé"""
        try:
            guild = member.guild

            # Limite par utilisateur
            owner_channels = self.voice_data.get_owner_channels(member.id)
            if len(owner_channels) >= MAX_CHANNELS_PER_USER:
                try:
                    await member.send(f"❌ Limite atteinte ({MAX_CHANNELS_PER_USER} salons max)")
                except:
                    pass
                await member.move_to(None)
                return

            # Vérifier catégorie
            category = guild.get_channel(CATEGORY_USER_ID)
            if not category:
                try:
                    await member.send("❌ Catégorie introuvable")
                except:
                    pass
                await member.move_to(None)
                return

            # Créer le canal
            channel_name = f"🏝️ {member.display_name}"
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(connect=True),
                member: discord.PermissionOverwrite(
                    connect=True,
                    move_members=True,
                    mute_members=True,
                    deafen_members=True
                ),
                guild.me: discord.PermissionOverwrite(
                    connect=True,
                    move_members=True,
                    mute_members=True
                ),
            }

            channel = await guild.create_voice_channel(
                name=channel_name,
                overwrites=overwrites,
                category=category,
                bitrate=96000
            )

            # Enregistrer les données
            await self.voice_data.add_channel(
                channel.id,
                member.id,
                {
                    "type": "public",
                    "name": channel_name,
                    "user_limit": 0,
                    "theme": "standard",
                    "bitrate": 96000,
                    "description": "",
                    "blacklist": [],
                    "whitelist": [],
                }
            )

            # Déplacer le membre
            await member.move_to(channel)

            # Envoyer le panneau
            control_panel = ChannelControlPanel(self, channel.id, member.id)
            embed = discord.Embed(
                title=f"🌴 Salon créé: {channel.name}",
                description=(
                    "🎉 **Bienvenue dans votre salon personnalisé!**\n\n"
                    "**Contrôles disponibles:**\n"
                    "🔒 Verrouiller | ✏️ Renommer | 👥 Limite | 🔄 Type\n"
                    "📝 Description | 🔊 Bitrate | 🎨 Thème\n"
                    "👋 Inviter | 👢 Expulser\n"
                    "🚫 Blacklist | ✅ Whitelist\n"
                    "👥 Membres | 📊 Stats | 🗑️ Supprimer\n\n"
                    "✅ Le salon sera supprimé automatiquement quand vide."
                ),
                color=EMBED_COLOR
            )
            embed.set_footer(text="🌴 Antilles - Premium Voice Channels v6.0")

            await channel.send(embed=embed, view=control_panel)
            logger.info(f"✅ Salon créé: {channel.name} par {member.name}")

        except Exception as e:
            logger.error(f"Erreur création: {e}", exc_info=True)
            try:
                await member.move_to(None)
            except:
                pass

    async def delete_voice_channel(self, interaction: discord.Interaction, channel_id: int):
        """Supprime un salon vocal"""
        try:
            channel = interaction.guild.get_channel(channel_id)
            
            # Supprimer le message du panneau
            try:
                await interaction.message.delete()
            except:
                pass
            
            # Supprimer le canal Discord
            if channel:
                try:
                    await channel.delete(reason=f"Supprimé par {interaction.user.name}")
                except:
                    pass
            
            # Retirer de la base de données
            await self.voice_data.remove_channel(channel_id)
            
            # Envoyer confirmation
            try:
                await interaction.followup.send("✅ Salon supprimé", ephemeral=True)
            except:
                pass
            
            logger.info(f"✅ Salon {channel_id} supprimé par {interaction.user.name}")

        except Exception as e:
            logger.error(f"Erreur suppression: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ Erreur suppression", ephemeral=True)
            except:
                pass

    # SLASH COMMANDS
    vc_group = app_commands.Group(name="vc", description="🌴 Commandes salons vocaux")

    @vc_group.command(name="delete", description="Supprimer votre salon")
    @app_commands.guild_only()
    async def vc_delete(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("❌ Vous n'êtes pas en vocal", ephemeral=True)

        channel_id = interaction.user.voice.channel.id
        channel_data = self.voice_data.get_channel(channel_id)

        if not channel_data:
            return await interaction.response.send_message("❌ Salon non personnalisé", ephemeral=True)

        if str(interaction.user.id) != channel_data.get("owner_id") and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("🚫 Non autorisé", ephemeral=True)

        view = ConfirmView()
        await interaction.response.send_message("❓ Êtes-vous sûr?", view=view, ephemeral=True)
        await view.wait()
        if view.value:
            await self.delete_voice_channel(interaction, channel_id)

    @vc_group.command(name="panel", description="Afficher le panneau")
    @app_commands.guild_only()
    async def vc_panel(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("❌ Vous n'êtes pas en vocal", ephemeral=True)

        channel_id = interaction.user.voice.channel.id
        channel_data = self.voice_data.get_channel(channel_id)

        if not channel_data:
            return await interaction.response.send_message("❌ Salon non personnalisé", ephemeral=True)

        if str(interaction.user.id) != channel_data.get("owner_id") and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("🚫 Non autorisé", ephemeral=True)

        control_panel = ChannelControlPanel(self, channel_id, int(channel_data.get("owner_id")))

        embed = discord.Embed(
            title=f"🌴 Panneau: {interaction.user.voice.channel.name}",
            description=(
                f"**Type:** {'Public' if channel_data.get('type') == 'public' else 'Privé'}\n"
                f"**Limite:** {channel_data.get('user_limit', 0) if channel_data.get('user_limit', 0) > 0 else 'Illimitée'}\n"
                f"**Verrouillé:** {'Oui' if channel_data.get('locked', False) else 'Non'}\n"
                f"**Thème:** {channel_data.get('theme', 'standard').capitalize()}\n"
                f"**Bitrate:** {channel_data.get('bitrate', 96000) // 1000} kbps"
            ),
            color=EMBED_COLOR
        )
        embed.set_footer(text="🌴 Antilles")

        await interaction.response.send_message(embed=embed, view=control_panel, ephemeral=True)

    @commands.command(name="vc_setup")
    @commands.has_permissions(administrator=True)
    async def vc_setup(self, ctx):
        try:
            category = ctx.guild.get_channel(CATEGORY_USER_ID)
            if not category:
                return await ctx.send(f"❌ Catégorie {CATEGORY_USER_ID} introuvable")

            creator_channel = await ctx.guild.create_voice_channel("🌴 Créer ton salon", category=category)

            self.creator_channel_id = creator_channel.id
            self.save_config()

            embed = discord.Embed(
                title="✅ Setup complété!",
                description=f"Utilisez {creator_channel.mention}",
                color=EMBED_COLOR
            )
            await ctx.send(embed=embed)
            logger.info("✅ Setup complété")

        except Exception as e:
            logger.error(f"Erreur setup: {e}", exc_info=True)
            await ctx.send(f"❌ Erreur: {e}")


async def setup(bot):
    await bot.add_cog(VoiceChannelsCog(bot))