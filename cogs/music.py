import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
import asyncio
import os
import typing
import datetime
import random

# Émojis et éléments thématiques des Antilles
ANTILLES_EMOJIS = {
    "play": "▶️",
    "pause": "⏸️",
    "stop": "⏹️",
    "skip": "⏭️",
    "palm": "🌴",
    "wave": "🌊",
    "sun": "☀️",
    "pineapple": "🍍",
    "coconut": "🥥",
    "beach": "🏝️",
    "note": "🎵",
    "shell": "🐚",
    "dancer": "💃",
    "flower": "🌺",
    "drum": "🪘",
    "volume": "🔊",
    "parrot": "🦜"
}

# Couleurs thématiques
ANTILLES_COLORS = {
    "turquoise": 0x40E0D0,   # Eau turquoise
    "sand": 0xF5DEB3,        # Sable
    "sunset": 0xFF7F50,      # Coucher de soleil
    "palm": 0x00A651,        # Palmier
    "coral": 0xFF6F61,       # Corail
    "ocean": 0x0077BE        # Océan profond
}

class MusicPlayerView(ui.View):
    def __init__(self, cog, timeout=180):
        super().__init__(timeout=timeout)
        self.cog = cog

    @ui.button(label="Pause", emoji="⏸️", style=discord.ButtonStyle.primary)
    async def pause_button(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.guild.voice_client or not interaction.guild.voice_client.is_playing():
            return await interaction.response.send_message("❌ Je ne joue pas de musique actuellement!", ephemeral=True)
        
        interaction.guild.voice_client.pause()
        button.label = "Reprendre"
        button.emoji = "▶️"
        button.style = discord.ButtonStyle.success
        self.children[1].disabled = False  # Enable resume button
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"{ANTILLES_EMOJIS['pause']} Musique en pause", ephemeral=True)

    @ui.button(label="Suivant", emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def skip_button(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.guild.voice_client or not interaction.guild.voice_client.is_playing():
            return await interaction.response.send_message("❌ Je ne joue pas de musique actuellement!", ephemeral=True)
        
        guild_id = interaction.guild.id
        
        if guild_id not in self.cog.queue or len(self.cog.queue[guild_id]) == 0:
            await interaction.response.send_message(f"{ANTILLES_EMOJIS['skip']} Piste ignorée (fin de la file d'attente)", ephemeral=True)
        else:
            await interaction.response.send_message(f"{ANTILLES_EMOJIS['skip']} Piste ignorée (encore {len(self.cog.queue[guild_id])} dans la file)", ephemeral=True)
        
        interaction.guild.voice_client.stop()

    @ui.button(label="Stop", emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop_button(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.guild.voice_client:
            return await interaction.response.send_message("❌ Je ne suis pas dans un canal vocal!", ephemeral=True)
        
        guild_id = interaction.guild.id
        
        if guild_id in self.cog.queue:
            self.cog.queue[guild_id] = []
        
        if guild_id in self.cog.now_playing:
            del self.cog.now_playing[guild_id]
        
        interaction.guild.voice_client.stop()
        
        # Désactiver tous les boutons
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"{ANTILLES_EMOJIS['stop']} Lecture arrêtée et file d'attente vidée", ephemeral=True)

    @ui.button(label="+ Volume", emoji="🔊", style=discord.ButtonStyle.secondary)
    async def volume_up_button(self, interaction: discord.Interaction, button: ui.Button):
        guild_id = interaction.guild.id
        
        if guild_id not in self.cog.volume:
            self.cog.volume[guild_id] = 0.5
        
        # Augmenter le volume de 10%
        new_volume = min(1.0, self.cog.volume[guild_id] + 0.1)
        self.cog.volume[guild_id] = new_volume
        
        # Appliquer immédiatement
        if interaction.guild.voice_client and interaction.guild.voice_client.source:
            interaction.guild.voice_client.source.volume = new_volume
        
        percentage = int(new_volume * 100)
        await interaction.response.send_message(f"{ANTILLES_EMOJIS['volume']} Volume ajusté à {percentage}%", ephemeral=True)

    @ui.button(label="- Volume", emoji="🔉", style=discord.ButtonStyle.secondary)
    async def volume_down_button(self, interaction: discord.Interaction, button: ui.Button):
        guild_id = interaction.guild.id
        
        if guild_id not in self.cog.volume:
            self.cog.volume[guild_id] = 0.5
        
        # Diminuer le volume de 10%
        new_volume = max(0.0, self.cog.volume[guild_id] - 0.1)
        self.cog.volume[guild_id] = new_volume
        
        # Appliquer immédiatement
        if interaction.guild.voice_client and interaction.guild.voice_client.source:
            interaction.guild.voice_client.source.volume = new_volume
        
        percentage = int(new_volume * 100)
        await interaction.response.send_message(f"{ANTILLES_EMOJIS['volume']} Volume ajusté à {percentage}%", ephemeral=True)


class MP3PlayerAntilles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = {}  # {guild_id: [track1, track2, ...]}
        self.now_playing = {}  # {guild_id: current_track}
        self.volume = {}  # {guild_id: volume_level}
        self.player_messages = {}  # {guild_id: player_message}
        self.update_now_playing.start()
        
        # Citations et messages thématiques des Antilles
        self.antilles_quotes = [
            "La musique des Antilles, c'est le soleil en notes! 🌴",
            "À la Caraïbe, le rythme est un mode de vie 🥁",
            "Laissez-vous porter par les vibrations tropicales 🌊",
            "Le zouk et la biguine réchauffent les cœurs 💃",
            "Des mélodies qui sentent le sable chaud et l'eau turquoise 🏝️",
            "La musique antillaise: un remède contre la grisaille! ☀️",
            "Le gwoka bat au rythme du cœur des îles 🪘",
            "Vibrations des Caraïbes pour ensoleiller votre journée 🌺"
        ]
    
    def cog_unload(self):
        self.update_now_playing.cancel()
    
    @tasks.loop(seconds=10.0)
    async def update_now_playing(self):
        """Met à jour périodiquement les messages du lecteur"""
        for guild_id, player_message in list(self.player_messages.items()):
            try:
                if guild_id in self.now_playing:
                    # Récupérer l'objet guild
                    guild = self.bot.get_guild(guild_id)
                    if not guild or not guild.voice_client:
                        # Nettoyage si le bot n'est plus connecté
                        del self.player_messages[guild_id]
                        continue
                    
                    # Mise à jour du message avec progression
                    await self._update_player_message(guild)
            except (discord.NotFound, discord.HTTPException):
                # Nettoyage si le message n'existe plus
                if guild_id in self.player_messages:
                    del self.player_messages[guild_id]
    
    async def _update_player_message(self, guild):
        """Met à jour le message du lecteur avec progression"""
        guild_id = guild.id
        if guild_id not in self.now_playing:
            return
        
        track_info = self.now_playing[guild_id]
        player_message = self.player_messages.get(guild_id)
        if not player_message:
            return
            
        # Créer une barre de progression visuelle
        progress_bar = ""
        if guild.voice_client and guild.voice_client.source:
            # Simuler la progression (impossible de connaître la position exacte sans analyser le fichier)
            progress_bar = self._create_progress_bar()
            
        # Créer un embed mis à jour
        embed = self._create_playing_embed(guild_id, track_info, progress_bar)
            
        try:
            await player_message.edit(embed=embed)
        except discord.HTTPException:
            pass
    
    def _create_progress_bar(self):
        """Crée une barre de progression aléatoire (puisqu'on ne peut pas mesurer la progression réelle)"""
        position = random.randint(1, 10)
        total = 10
        
        filled = ANTILLES_EMOJIS["wave"] * position
        empty = "▬" * (total - position)
        
        return f"{filled}{empty}"
    
    def _create_playing_embed(self, guild_id, track_info, progress_bar=""):
        """Crée un embed pour la piste en cours"""
        # Choisir une couleur et un message aléatoires
        color = random.choice(list(ANTILLES_COLORS.values()))
        quote = random.choice(self.antilles_quotes)
        
        embed = discord.Embed(
            title=f"{ANTILLES_EMOJIS['note']} Vibes Antillaises {ANTILLES_EMOJIS['palm']}",
            description=f"**{track_info['title']}**\n{quote}",
            color=color
        )
        
        embed.add_field(
            name=f"{ANTILLES_EMOJIS['dancer']} Demandé par",
            value=track_info['requester'],
            inline=True
        )
        
        # Ajouter la barre de progression si disponible
        if progress_bar:
            embed.add_field(
                name=f"{ANTILLES_EMOJIS['note']} Progression", 
                value=progress_bar,
                inline=False
            )
        
        # Ajouter les infos de la file d'attente
        if guild_id in self.queue and len(self.queue[guild_id]) > 0:
            next_tracks = "\n".join([
                f"{i+1}. **{t['title']}** ({t['requester']})" 
                for i, t in enumerate(self.queue[guild_id][:3])
            ])
            
            if len(self.queue[guild_id]) > 3:
                next_tracks += f"\n... et {len(self.queue[guild_id]) - 3} autres"
                
            embed.add_field(
                name=f"{ANTILLES_EMOJIS['pineapple']} À venir",
                value=next_tracks,
                inline=False
            )
        
        # Ajouter un footer
        embed.set_footer(text=f"Vibrations des Antilles {ANTILLES_EMOJIS['drum']} • DJ {self.bot.user.name}")
        
        return embed
    
    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignorer les messages de bots
        if message.author.bot:
            return
        
        # Vérifier si le bot est mentionné ET qu'il y a une pièce jointe
        if self.bot.user in message.mentions and message.attachments:
            # Vérifier si le fichier est un MP3
            for attachment in message.attachments:
                if attachment.filename.lower().endswith('.mp3'):
                    # Si l'utilisateur est dans un canal vocal
                    if message.author.voice:
                        await self._play_attachment(message, attachment)
                        return
                    else:
                        await message.channel.send(f"{ANTILLES_EMOJIS['palm']} Tu dois être dans un canal vocal pour que je puisse diffuser les vibes!")
                        return
    
    async def _play_attachment(self, message, attachment):
        """Joue un fichier joint au message avec une interface améliorée"""
        # Préparation du dossier temp
        if not os.path.exists('./temp'):
            os.makedirs('./temp')
        
        # Télécharger le fichier
        file_path = f'./temp/{attachment.filename}'
        await attachment.save(file_path)
        
        guild_id = message.guild.id
        
        # Initialiser la file d'attente si elle n'existe pas
        if guild_id not in self.queue:
            self.queue[guild_id] = []
            self.volume[guild_id] = 0.5  # Volume par défaut à 50%
        
        # Préparer les infos de la piste
        track_info = {
            'title': attachment.filename.replace('.mp3', ''),
            'path': file_path,
            'requester': message.author.name,
            'duration': "Inconnue",
            'added_at': datetime.datetime.now()
        }
        
        # Si le bot n'est pas dans un canal vocal ou s'il est inactif
        if not message.guild.voice_client:
            # Message d'attente
            wait_embed = discord.Embed(
                title=f"{ANTILLES_EMOJIS['palm']} Préparation des Vibes Antillaises {ANTILLES_EMOJIS['sun']}",
                description=f"**{track_info['title']}**\nJe me connecte à votre canal et prépare l'ambiance des îles...",
                color=ANTILLES_COLORS["turquoise"]
            )
            loading_msg = await message.channel.send(embed=wait_embed)
            
            # Rejoindre le canal vocal
            voice_client = await message.author.voice.channel.connect()
            
            # Jouer directement
            await self._play_track(message, voice_client, track_info, loading_msg)
        else:
            # Ajouter à la file d'attente
            self.queue[guild_id].append(track_info)
            
            embed = discord.Embed(
                title=f"{ANTILLES_EMOJIS['pineapple']} Track ajouté à la playlist des îles",
                description=f"**{track_info['title']}**\nDemandé par: {track_info['requester']}",
                color=ANTILLES_COLORS["sunset"]
            )
            
            # Si le bot ne joue pas de musique, démarrer la lecture
            if not message.guild.voice_client.is_playing():
                await self._play_next(message.guild.voice_client, message.channel)
            else:
                position = len(self.queue[guild_id])
                embed.add_field(
                    name=f"{ANTILLES_EMOJIS['palm']} Position", 
                    value=f"#{position} dans la playlist tropicale"
                )
                await message.channel.send(embed=embed)
    
    async def _play_track(self, message, voice_client, track_info, existing_message=None):
        """Joue une piste et met à jour les infos de lecture"""
        guild_id = message.guild.id
        
        # Définir la piste en cours
        self.now_playing[guild_id] = track_info
        
        # Créer la source audio
        audio_source = discord.FFmpegPCMAudio(track_info['path'])
        transformed_source = discord.PCMVolumeTransformer(audio_source, volume=self.volume[guild_id])
        
        # Jouer le fichier
        voice_client.play(
            transformed_source, 
            after=lambda e: asyncio.run_coroutine_threadsafe(
                self._play_next(voice_client, message.channel, error=e), 
                self.bot.loop
            )
        )
        
        # Créer l'interface de contrôle
        embed = self._create_playing_embed(guild_id, track_info)
        view = MusicPlayerView(self)
        
        # Mettre à jour le message existant ou en créer un nouveau
        if existing_message:
            player_message = await existing_message.edit(embed=embed, view=view)
            self.player_messages[guild_id] = existing_message
        else:
            player_message = await message.channel.send(embed=embed, view=view)
            self.player_messages[guild_id] = player_message
    
    async def _play_next(self, voice_client, text_channel, error=None):
        """Joue la piste suivante dans la file d'attente"""
        if error:
            await text_channel.send(f"❌ Erreur de lecture: {error}")
        
        if not voice_client.is_connected():
            return
            
        guild_id = voice_client.guild.id
        
        # S'il reste des pistes dans la file d'attente
        if guild_id in self.queue and len(self.queue[guild_id]) > 0:
            # Récupérer la prochaine piste
            next_track = self.queue[guild_id].pop(0)
            
            # Mettre à jour les infos de lecture
            self.now_playing[guild_id] = next_track
            
            # Créer la source audio
            audio_source = discord.FFmpegPCMAudio(next_track['path'])
            transformed_source = discord.PCMVolumeTransformer(audio_source, volume=self.volume[guild_id])
            
            # Jouer le fichier
            voice_client.play(
                transformed_source,
                after=lambda e: asyncio.run_coroutine_threadsafe(
                    self._play_next(voice_client, text_channel, error=e),
                    self.bot.loop
                )
            )
            
            # Créer l'interface de contrôle
            embed = self._create_playing_embed(guild_id, next_track)
            view = MusicPlayerView(self)
            
            # Envoyer un nouveau message de contrôle
            player_message = await text_channel.send(embed=embed, view=view)
            self.player_messages[guild_id] = player_message
        else:
            # Supprimer l'entrée de now_playing
            if guild_id in self.now_playing:
                del self.now_playing[guild_id]
                
            # Message de fin de lecture
            embed = discord.Embed(
                title=f"{ANTILLES_EMOJIS['beach']} Fin de la playlist tropicale",
                description="Toutes les vibes antillaises ont été diffusées. Ajoutez plus de tracks en me mentionnant avec un fichier MP3!",
                color=ANTILLES_COLORS["sand"]
            )
            await text_channel.send(embed=embed)
    
    @app_commands.command(name="queue", description="🏝️ Affiche la playlist des vibes antillaises")
    async def queue_command(self, interaction: discord.Interaction):
        """Affiche la file d'attente stylisée"""
        guild_id = interaction.guild.id
        
        if guild_id not in self.queue or len(self.queue[guild_id]) == 0:
            if guild_id in self.now_playing:
                embed = discord.Embed(
                    title=f"{ANTILLES_EMOJIS['palm']} Playlist des îles {ANTILLES_EMOJIS['sun']}",
                    description="Aucune autre track en attente après celle-ci",
                    color=ANTILLES_COLORS["ocean"]
                )
                embed.add_field(
                    name=f"{ANTILLES_EMOJIS['note']} En cours", 
                    value=f"**{self.now_playing[guild_id]['title']}**\nDemandé par: {self.now_playing[guild_id]['requester']}"
                )
                return await interaction.response.send_message(embed=embed)
            else:
                embed = discord.Embed(
                    title=f"{ANTILLES_EMOJIS['beach']} Playlist vide",
                    description="Aucune musique en attente ni en lecture.\nMentionnez-moi avec un fichier MP3 pour lancer les vibes!",
                    color=ANTILLES_COLORS["sand"]
                )
                return await interaction.response.send_message(embed=embed)
        
        # Créer l'embed avec la liste des pistes
        embed = discord.Embed(
            title=f"{ANTILLES_EMOJIS['palm']} Playlist des Vibes Antillaises {ANTILLES_EMOJIS['sun']}",
            description=f"{len(self.queue[guild_id])} tracks en attente",
            color=ANTILLES_COLORS["turquoise"]
        )
        
        # Ajouter la piste en cours
        if guild_id in self.now_playing:
            embed.add_field(
                name=f"{ANTILLES_EMOJIS['note']} En cours", 
                value=f"**{self.now_playing[guild_id]['title']}**\nDemandé par: {self.now_playing[guild_id]['requester']}",
                inline=False
            )
        
        # Ajouter les pistes en attente (max 10)
        tracks_list = ""
        for i, track in enumerate(self.queue[guild_id][:10]):
            tracks_list += f"{i+1}. **{track['title']}** (Demandé par: {track['requester']})\n"
        
        if len(self.queue[guild_id]) > 10:
            tracks_list += f"\n... et {len(self.queue[guild_id]) - 10} autres tracks"
            
        embed.add_field(
            name=f"{ANTILLES_EMOJIS['pineapple']} À venir", 
            value=tracks_list,
            inline=False
        )
        
        # Citation aléatoire comme footer
        embed.set_footer(text=random.choice(self.antilles_quotes))
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="leave", description="🏝️ Déconnecte le DJ des îles")
    async def leave_command(self, interaction: discord.Interaction):
        """Quitte le canal vocal"""
        if not interaction.guild.voice_client:
            return await interaction.response.send_message(f"{ANTILLES_EMOJIS['palm']} Je ne suis pas dans un canal vocal!", ephemeral=True)
        
        guild_id = interaction.guild.id
        
        # Nettoyage
        if guild_id in self.queue:
            self.queue[guild_id] = []
        
        if guild_id in self.now_playing:
            del self.now_playing[guild_id]
        
        # Message d'au revoir
        embed = discord.Embed(
            title=f"{ANTILLES_EMOJIS['wave']} À bientôt! {ANTILLES_EMOJIS['sun']}",
            description="Le DJ des îles quitte la scène. Mentionnez-moi avec un MP3 pour retrouver l'ambiance Antillaise!",
            color=ANTILLES_COLORS["sunset"]
        )
        
        # Déconnexion
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message(embed=embed)

# Fonction setup requise pour charger l'extension
def setup(bot):
    bot.add_cog(MP3PlayerAntilles(bot))