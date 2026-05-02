"""
╔══════════════════════════════════════════════════════════╗
║         🎵 COG MUSIQUE — VIBES ANTILLAISES 🌴            ║
║  Propulsé par Wavelink 3.2 + Lavalink public             ║
╚══════════════════════════════════════════════════════════╝
"""

import discord
from discord import app_commands, ui
from discord.ext import commands
import wavelink
import random
import logging

logger = logging.getLogger("music_cog")

# ─────────────────────────────────────────────
#  THÈME ANTILLES
# ─────────────────────────────────────────────

EMOJIS = {
    "play":      "▶️",
    "pause":     "⏸️",
    "stop":      "⏹️",
    "skip":      "⏭️",
    "loop":      "🔁",
    "shuffle":   "🔀",
    "volume":    "🔊",
    "queue":     "📋",
    "note":      "🎵",
    "palm":      "🌴",
    "wave":      "🌊",
    "sun":       "☀️",
    "beach":     "🏝️",
    "drum":      "🪘",
    "dancer":    "💃",
    "pineapple": "🍍",
    "search":    "🔍",
}

COLORS = {
    "turquoise": 0x40E0D0,
    "sand":      0xF5DEB3,
    "sunset":    0xFF7F50,
    "palm":      0x00A651,
    "coral":     0xFF6F61,
    "ocean":     0x0077BE,
}

QUOTES = [
    "La musique des Antilles, c'est le soleil en notes! 🌴",
    "À la Caraïbe, le rythme est un mode de vie 🥁",
    "Laissez-vous porter par les vibrations tropicales 🌊",
    "Le zouk et la biguine réchauffent les cœurs 💃",
    "Des mélodies qui sentent le sable chaud et l'eau turquoise 🏝️",
    "La musique antillaise : un remède contre la grisaille! ☀️",
    "Vibrations des Caraïbes pour ensoleiller votre journée 🌺",
]

# ─────────────────────────────────────────────
#  NOEUDS LAVALINK PUBLICS
#  wavelink essaie dans l'ordre, bascule auto
# ─────────────────────────────────────────────

LAVALINK_NODES = [
    # lavalink.jirayu.net — 99.91% uptime, 179j+ de fonctionnement
    {"uri": "http://lavalink.jirayu.net:13592", "password": "youshallnotpass"},
    # serenetia — nœud v4, SSL disponible
    {"uri": "http://lavalinkv4.serenetia.com:80", "password": "https://dsc.gg/ajidevserver"},
    # nexcloud — 99.88% uptime vérifié
    {"uri": "http://n3.nexcloud.in:2026", "password": "nexcloud"},
    # vexanode — 99.97% uptime vérifié
    {"uri": "http://omega.vexanode.cloud:2031", "password": "https://discord.vexanode.cloud"},
]


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def fmt_duration(ms: int) -> str:
    if not ms:
        return "∞"
    s = ms // 1000
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def vol_bar(vol: int) -> str:
    filled = vol // 10
    return "█" * filled + "░" * (10 - filled)


# ─────────────────────────────────────────────
#  VUE BOUTONS
# ─────────────────────────────────────────────

class PlayerView(ui.View):
    def __init__(self, cog: "MusicCog", guild_id: int):
        super().__init__(timeout=None)
        self.cog      = cog
        self.guild_id = guild_id

    def _player(self) -> wavelink.Player | None:
        guild = self.cog.bot.get_guild(self.guild_id)
        return guild.voice_client if guild else None  # type: ignore

    @ui.button(emoji="⏸️", label="Pause", style=discord.ButtonStyle.primary, custom_id="music_pause")
    async def btn_pause(self, interaction: discord.Interaction, button: ui.Button):
        player = self._player()
        if not player:
            return await interaction.response.send_message("❌ Pas de lecteur actif.", ephemeral=True)
        await player.pause(not player.paused)
        if player.paused:
            button.emoji = discord.PartialEmoji.from_str("▶️")
            button.label = "Reprendre"
            button.style = discord.ButtonStyle.success
        else:
            button.emoji = discord.PartialEmoji.from_str("⏸️")
            button.label = "Pause"
            button.style = discord.ButtonStyle.primary
        await interaction.response.edit_message(view=self)

    @ui.button(emoji="⏭️", label="Skip", style=discord.ButtonStyle.secondary, custom_id="music_skip")
    async def btn_skip(self, interaction: discord.Interaction, button: ui.Button):
        player = self._player()
        if not player:
            return await interaction.response.send_message("❌ Pas de lecteur actif.", ephemeral=True)
        await player.skip(force=True)
        await interaction.response.send_message(f"{EMOJIS['skip']} Piste passée!", ephemeral=True)

    @ui.button(emoji="⏹️", label="Stop", style=discord.ButtonStyle.danger, custom_id="music_stop")
    async def btn_stop(self, interaction: discord.Interaction, button: ui.Button):
        player = self._player()
        if not player:
            return await interaction.response.send_message("❌ Pas de lecteur actif.", ephemeral=True)
        player.queue.clear()
        await player.stop()
        await player.disconnect()
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"{EMOJIS['stop']} Lecture stoppée.", ephemeral=True)

    @ui.button(emoji="🔁", label="Loop", style=discord.ButtonStyle.secondary, custom_id="music_loop")
    async def btn_loop(self, interaction: discord.Interaction, button: ui.Button):
        player = self._player()
        if not player:
            return await interaction.response.send_message("❌ Pas de lecteur actif.", ephemeral=True)
        mode = player.queue.mode
        if mode == wavelink.QueueMode.normal:
            player.queue.mode = wavelink.QueueMode.loop
            button.style = discord.ButtonStyle.success
            button.label = "Loop 🔂"
        elif mode == wavelink.QueueMode.loop:
            player.queue.mode = wavelink.QueueMode.loop_all
            button.label = "Loop All 🔁"
        else:
            player.queue.mode = wavelink.QueueMode.normal
            button.style = discord.ButtonStyle.secondary
            button.label = "Loop"
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f"{EMOJIS['loop']} Mode : **{player.queue.mode.name}**", ephemeral=True
        )

    @ui.button(emoji="🔊", label="+10%", style=discord.ButtonStyle.secondary, custom_id="music_vol_up")
    async def btn_vol_up(self, interaction: discord.Interaction, button: ui.Button):
        player = self._player()
        if not player:
            return await interaction.response.send_message("❌ Pas de lecteur actif.", ephemeral=True)
        new_vol = min(100, player.volume + 10)
        await player.set_volume(new_vol)
        await interaction.response.send_message(
            f"{EMOJIS['volume']} `{vol_bar(new_vol)}` **{new_vol}%**", ephemeral=True
        )

    @ui.button(emoji="🔉", label="-10%", style=discord.ButtonStyle.secondary, custom_id="music_vol_down")
    async def btn_vol_down(self, interaction: discord.Interaction, button: ui.Button):
        player = self._player()
        if not player:
            return await interaction.response.send_message("❌ Pas de lecteur actif.", ephemeral=True)
        new_vol = max(0, player.volume - 10)
        await player.set_volume(new_vol)
        await interaction.response.send_message(
            f"{EMOJIS['volume']} `{vol_bar(new_vol)}` **{new_vol}%**", ephemeral=True
        )


# ─────────────────────────────────────────────
#  COG PRINCIPAL
# ─────────────────────────────────────────────

class MusicCog(commands.Cog, name="Musique"):
    """🎵 Système de musique complet — Vibes Antillaises"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        nodes = [
            wavelink.Node(uri=n["uri"], password=n["password"])
            for n in LAVALINK_NODES
        ]
        try:
            await wavelink.Pool.connect(nodes=nodes, client=self.bot, cache_capacity=100)
            logger.info(f"🎵 Wavelink connecté ({len(nodes)} nœuds)")
        except Exception as e:
            logger.error(f"❌ Erreur connexion Lavalink: {e}")

    # ── Événements Wavelink ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        logger.info(f"✅ Nœud Lavalink prêt : {payload.node.uri}")

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        player: wavelink.Player = payload.player
        if not hasattr(player, "text_channel") or not player.text_channel:
            return
        embed = self._make_embed(player, payload.track)
        view  = PlayerView(self, player.guild.id)
        try:
            if hasattr(player, "player_message") and player.player_message:
                await player.player_message.edit(embed=embed, view=view)
            else:
                player.player_message = await player.text_channel.send(embed=embed, view=view)
        except Exception:
            player.player_message = await player.text_channel.send(embed=embed, view=view)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        player: wavelink.Player = payload.player
        if not player.queue and not player.playing:
            if hasattr(player, "text_channel") and player.text_channel:
                embed = discord.Embed(
                    title=f"{EMOJIS['beach']} Fin de la playlist",
                    description="Toutes les tracks ont été jouées. Utilisez `/play` pour relancer!",
                    color=COLORS["sand"],
                )
                await player.text_channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player):
        await player.disconnect()

    # ── Helper embed ──────────────────────────────────────────────────────────

    def _make_embed(self, player: wavelink.Player, track: wavelink.Playable) -> discord.Embed:
        color = random.choice(list(COLORS.values()))
        embed = discord.Embed(
            title=f"{EMOJIS['note']} En cours — Vibes Antillaises {EMOJIS['palm']}",
            description=f"**[{track.title}]({track.uri})**",
            color=color,
        )
        if track.artwork:
            embed.set_thumbnail(url=track.artwork)

        requester = getattr(track, "requester", None)
        embed.add_field(name=f"{EMOJIS['dancer']} Demandé par", value=requester.mention if requester else "?", inline=True)
        embed.add_field(name=f"{EMOJIS['sun']} Durée",          value=fmt_duration(track.length), inline=True)
        embed.add_field(name=f"{EMOJIS['wave']} Auteur",         value=track.author or "?", inline=True)

        vol    = player.volume
        mode   = player.queue.mode
        extras = f"{EMOJIS['volume']} `{vol_bar(vol)}` {vol}%"
        if mode == wavelink.QueueMode.loop:
            extras += f"  {EMOJIS['loop']} Loop piste"
        elif mode == wavelink.QueueMode.loop_all:
            extras += f"  {EMOJIS['loop']} Loop queue"
        embed.add_field(name="Contrôles", value=extras, inline=False)

        if player.queue:
            preview = "\n".join(
                f"`{i+1}.` **{t.title}** — {fmt_duration(t.length)}"
                for i, t in enumerate(list(player.queue)[:3])
            )
            if len(player.queue) > 3:
                preview += f"\n… et **{len(player.queue) - 3}** autres"
            embed.add_field(name=f"{EMOJIS['queue']} À venir", value=preview, inline=False)

        embed.set_footer(text=f"{random.choice(QUOTES)} • DJ {self.bot.user.display_name}")
        return embed

    # ── Vérification vocale ───────────────────────────────────────────────────

    async def _ensure_player(self, interaction: discord.Interaction) -> wavelink.Player | None:
        if not interaction.user.voice:
            await interaction.response.send_message(
                f"{EMOJIS['palm']} Tu dois être dans un canal vocal!", ephemeral=True
            )
            return None
        if not wavelink.Pool.nodes:
            await interaction.response.send_message(
                "❌ Aucun nœud Lavalink disponible. Réessaie dans quelques secondes.", ephemeral=True
            )
            return None

        player: wavelink.Player = interaction.guild.voice_client  # type: ignore
        if not player:
            player = await interaction.user.voice.channel.connect(cls=wavelink.Player)
            player.text_channel    = interaction.channel
            player.player_message  = None
            player.inactive_timeout = 300
        elif player.channel != interaction.user.voice.channel:
            await player.move_to(interaction.user.voice.channel)

        return player

    # ─────────────────────────────────────────────────────────────────────────
    #  COMMANDES SLASH
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="play", description="🎵 Joue une musique (URL YouTube ou recherche)")
    @app_commands.describe(query="Titre, URL YouTube ou lien de playlist")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(thinking=True)
        player = await self._ensure_player(interaction)
        if not player:
            return

        try:
            tracks = await wavelink.Playable.search(query)
        except Exception as e:
            logger.error(f"Erreur recherche: {e}")
            return await interaction.followup.send(f"❌ Erreur : `{e}`", ephemeral=True)

        if not tracks:
            return await interaction.followup.send(
                f"{EMOJIS['search']} Aucun résultat pour `{query}`", ephemeral=True
            )

        if isinstance(tracks, wavelink.Playlist):
            for t in tracks.tracks:
                t.requester = interaction.user
            added = await player.queue.put_wait(tracks)
            embed = discord.Embed(
                title=f"{EMOJIS['palm']} Playlist ajoutée — {added} tracks",
                description="\n".join(f"`{i+1}.` {t.title}" for i, t in enumerate(tracks.tracks[:5])) +
                            (f"\n… et {len(tracks.tracks)-5} autres" if len(tracks.tracks) > 5 else ""),
                color=COLORS["ocean"],
            )
            await interaction.followup.send(embed=embed)
        else:
            track = tracks[0]
            track.requester = interaction.user
            await player.queue.put_wait(track)
            embed = discord.Embed(
                title=f"{EMOJIS['pineapple']} Ajouté à la playlist",
                description=f"**[{track.title}]({track.uri})**",
                color=COLORS["turquoise"],
            )
            embed.add_field(name="Durée",       value=fmt_duration(track.length), inline=True)
            embed.add_field(name="Position",    value=f"#{len(player.queue)}", inline=True)
            embed.add_field(name="Demandé par", value=interaction.user.mention, inline=True)
            if track.artwork:
                embed.set_thumbnail(url=track.artwork)
            await interaction.followup.send(embed=embed)

        if not player.playing:
            await player.play(player.queue.get())

    @app_commands.command(name="pause", description="⏸️ Met en pause ou reprend la lecture")
    async def pause(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client  # type: ignore
        if not player:
            return await interaction.response.send_message("❌ Pas de lecture en cours.", ephemeral=True)
        await player.pause(not player.paused)
        status = "en pause" if player.paused else "reprise"
        icon   = EMOJIS["pause"] if player.paused else EMOJIS["play"]
        await interaction.response.send_message(f"{icon} Lecture {status}.", ephemeral=True)

    @app_commands.command(name="skip", description="⏭️ Passe la piste actuelle")
    @app_commands.describe(count="Nombre de pistes à passer (défaut : 1)")
    async def skip(self, interaction: discord.Interaction, count: int = 1):
        player: wavelink.Player = interaction.guild.voice_client  # type: ignore
        if not player or not player.playing:
            return await interaction.response.send_message("❌ Rien à passer.", ephemeral=True)
        count = max(1, min(count, len(player.queue) + 1))
        for _ in range(count - 1):
            try:
                player.queue.get()
            except wavelink.QueueEmpty:
                break
        await player.skip(force=True)
        await interaction.response.send_message(f"{EMOJIS['skip']} {count} piste(s) passée(s).", ephemeral=True)

    @app_commands.command(name="stop", description="⏹️ Arrête la lecture et vide la file")
    async def stop(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client  # type: ignore
        if not player:
            return await interaction.response.send_message("❌ Pas de lecture en cours.", ephemeral=True)
        player.queue.clear()
        await player.stop()
        await interaction.response.send_message(f"{EMOJIS['stop']} Lecture stoppée et file vidée.", ephemeral=True)

    @app_commands.command(name="leave", description="👋 Déconnecte le bot du canal vocal")
    async def leave(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client  # type: ignore
        if not player:
            return await interaction.response.send_message("❌ Je ne suis pas en vocal.", ephemeral=True)
        player.queue.clear()
        await player.disconnect()
        embed = discord.Embed(
            title=f"{EMOJIS['wave']} À bientôt! {EMOJIS['sun']}",
            description="Le DJ des îles quitte la scène. `/play` pour relancer!",
            color=COLORS["sunset"],
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="queue", description="📋 Affiche la file d'attente")
    @app_commands.describe(page="Page de la file (défaut : 1)")
    async def queue_cmd(self, interaction: discord.Interaction, page: int = 1):
        player: wavelink.Player = interaction.guild.voice_client  # type: ignore
        if not player or (not player.current and not player.queue):
            return await interaction.response.send_message(
                f"{EMOJIS['beach']} La file est vide. Utilisez `/play`!", ephemeral=True
            )
        per_page = 10
        queue    = list(player.queue)
        total    = len(queue)
        pages    = max(1, -(-total // per_page))
        page     = max(1, min(page, pages))
        start    = (page - 1) * per_page

        embed = discord.Embed(title=f"{EMOJIS['palm']} Playlist Antillaise {EMOJIS['sun']}", color=COLORS["turquoise"])
        if player.current:
            embed.add_field(
                name=f"{EMOJIS['note']} En cours",
                value=f"**[{player.current.title}]({player.current.uri})** — {fmt_duration(player.current.length)}",
                inline=False,
            )
        if queue:
            lines = [
                f"`{start+i+1}.` **{t.title}** — {fmt_duration(t.length)}"
                for i, t in enumerate(queue[start:start+per_page])
            ]
            embed.add_field(
                name=f"{EMOJIS['queue']} À venir ({total}) — page {page}/{pages}",
                value="\n".join(lines),
                inline=False,
            )
            total_ms = sum(t.length or 0 for t in queue)
            embed.set_footer(text=f"Durée totale : {fmt_duration(total_ms)} • {random.choice(QUOTES)}")
        else:
            embed.add_field(name="À venir", value="Aucune track en attente.", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="nowplaying", description="🎵 Affiche la piste en cours")
    async def nowplaying(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client  # type: ignore
        if not player or not player.current:
            return await interaction.response.send_message("❌ Rien en cours de lecture.", ephemeral=True)
        embed = self._make_embed(player, player.current)
        view  = PlayerView(self, interaction.guild.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="volume", description="🔊 Règle le volume (0-100)")
    @app_commands.describe(level="Niveau entre 0 et 100")
    async def volume(self, interaction: discord.Interaction, level: int):
        if not 0 <= level <= 100:
            return await interaction.response.send_message("❌ Volume entre 0 et 100.", ephemeral=True)
        player: wavelink.Player = interaction.guild.voice_client  # type: ignore
        if not player:
            return await interaction.response.send_message("❌ Pas de lecture en cours.", ephemeral=True)
        await player.set_volume(level)
        await interaction.response.send_message(
            f"{EMOJIS['volume']} `{vol_bar(level)}` **{level}%**", ephemeral=True
        )

    @app_commands.command(name="loop", description="🔁 Cycle des modes (off → piste → queue)")
    async def loop_cmd(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client  # type: ignore
        if not player:
            return await interaction.response.send_message("❌ Pas de lecture en cours.", ephemeral=True)
        mode = player.queue.mode
        if mode == wavelink.QueueMode.normal:
            player.queue.mode = wavelink.QueueMode.loop
            label = "🔂 Loop piste activé"
        elif mode == wavelink.QueueMode.loop:
            player.queue.mode = wavelink.QueueMode.loop_all
            label = "🔁 Loop queue activé"
        else:
            player.queue.mode = wavelink.QueueMode.normal
            label = "❌ Boucle désactivée"
        await interaction.response.send_message(label, ephemeral=True)

    @app_commands.command(name="shuffle", description="🔀 Mélange la file d'attente")
    async def shuffle_cmd(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client  # type: ignore
        if not player or not player.queue:
            return await interaction.response.send_message("❌ La file est vide.", ephemeral=True)
        player.queue.shuffle()
        await interaction.response.send_message(f"{EMOJIS['shuffle']} File mélangée!", ephemeral=True)

    @app_commands.command(name="remove", description="🗑️ Retire une piste de la file")
    @app_commands.describe(position="Position dans la file (voir /queue)")
    async def remove(self, interaction: discord.Interaction, position: int):
        player: wavelink.Player = interaction.guild.voice_client  # type: ignore
        if not player:
            return await interaction.response.send_message("❌ Pas de lecture en cours.", ephemeral=True)
        queue = list(player.queue)
        if position < 1 or position > len(queue):
            return await interaction.response.send_message(
                f"❌ Position invalide. La file a {len(queue)} piste(s).", ephemeral=True
            )
        track = queue[position - 1]
        del player.queue[position - 1]
        await interaction.response.send_message(
            f"{EMOJIS['stop']} **{track.title}** retiré de la file.", ephemeral=True
        )

    @app_commands.command(name="clearqueue", description="🗑️ Vide la file d'attente")
    async def clearqueue(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client  # type: ignore
        if not player:
            return await interaction.response.send_message("❌ Pas de lecture en cours.", ephemeral=True)
        count = len(player.queue)
        player.queue.clear()
        await interaction.response.send_message(
            f"{EMOJIS['stop']} {count} piste(s) retirée(s) de la file.", ephemeral=True
        )

    @app_commands.command(name="join", description="🎤 Connecte le bot à ton canal vocal")
    async def join(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            return await interaction.response.send_message(
                f"{EMOJIS['palm']} Tu dois être dans un canal vocal!", ephemeral=True
            )
        player: wavelink.Player = interaction.guild.voice_client  # type: ignore
        if player:
            await player.move_to(interaction.user.voice.channel)
        else:
            player = await interaction.user.voice.channel.connect(cls=wavelink.Player)
            player.text_channel   = interaction.channel
            player.player_message = None
        await interaction.response.send_message(
            f"{EMOJIS['note']} Connecté à **{interaction.user.voice.channel.name}**!", ephemeral=True
        )


# ─────────────────────────────────────────────
#  SETUP
# ─────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))