import discord
from discord.ext import commands
import json
import asyncio
from typing import Dict, List, Optional, Union, Any

class ServerSetupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.roles_cache = {}
        self.categories_cache = {}
        
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def restore_server(self, ctx, config_path=None):
        """Restaure la configuration complète du serveur depuis un fichier JSON"""
        
        if config_path is None:
            config_path = "server_config.json"
            
        await ctx.send("🔄 Démarrage de la restauration du serveur...")
        
        # Chargement des données
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            return await ctx.send(f"❌ Erreur lors du chargement du fichier JSON: {e}")
        
        guild = ctx.guild
        
        # Vérification que le serveur est le bon
        server_info = data.get('server_info', {})
        if str(guild.id) != server_info.get('id'):
            await ctx.send(f"⚠️ Attention: L'ID du serveur actuel ({guild.id}) ne correspond pas à celui dans le JSON ({server_info.get('id')})")
            confirm = await ctx.send("Voulez-vous continuer quand même? (Oui/Non)")
            
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ["oui", "non"]
            
            try:
                response = await self.bot.wait_for('message', check=check, timeout=30)
                if response.content.lower() != "oui":
                    return await ctx.send("❌ Restauration annulée.")
            except asyncio.TimeoutError:
                return await ctx.send("❌ Délai d'attente dépassé. Restauration annulée.")
        
        # Restauration des éléments du serveur
        progress = await ctx.send("1/6: Restauration des rôles...")
        await self.restore_roles(guild, data.get('roles', []))
        
        await progress.edit(content="2/6: Restauration des catégories...")
        await self.restore_categories(guild, data.get('categories', []))
        
        await progress.edit(content="3/6: Restauration des canaux textuels...")
        await self.restore_text_channels(guild, data.get('text_channels', []))
        
        await progress.edit(content="4/6: Restauration des canaux vocaux...")
        await self.restore_voice_channels(guild, data.get('voice_channels', []))
        
        await progress.edit(content="5/6: Restauration des canaux de stage...")
        await self.restore_stage_channels(guild, data.get('stage_channels', []))
        
        await progress.edit(content="6/6: Restauration des forums...")
        await self.restore_forum_channels(guild, data.get('forum_channels', []))
        
        await ctx.send("✅ Restauration du serveur terminée!")
    
    async def restore_roles(self, guild: discord.Guild, roles_data: List[Dict]):
        """Restaure tous les rôles du serveur"""
        
        # Trier les rôles par position (du plus bas au plus haut)
        roles_data.sort(key=lambda r: r.get('position', 0))
        
        # Rôle @everyone spécial
        everyone_data = next((r for r in roles_data if r.get('is_default', False)), None)
        if everyone_data:
            # Mettre à jour les permissions du rôle @everyone
            await guild.default_role.edit(
                permissions=discord.Permissions(permissions=everyone_data.get('permissions', 0))
            )
            self.roles_cache[everyone_data.get('id')] = guild.default_role
        
        # Créer ou mettre à jour les autres rôles
        for role_data in roles_data:
            if role_data.get('is_default', False):
                continue  # Sauter le rôle @everyone qui a déjà été traité
            
            # Vérifier si le rôle existe déjà
            role = discord.utils.get(guild.roles, name=role_data.get('name'))
            
            # Conversion de la couleur
            color = discord.Color(role_data.get('color', 0))
            
            if role:
                # Mettre à jour le rôle existant
                try:
                    await role.edit(
                        name=role_data.get('name'),
                        permissions=discord.Permissions(permissions=role_data.get('permissions', 0)),
                        color=color,
                        hoist=role_data.get('hoist', False),
                        mentionable=role_data.get('mentionable', False)
                    )
                except discord.Forbidden:
                    pass  # Ignorer si on n'a pas les permissions
            else:
                # Créer un nouveau rôle
                try:
                    role = await guild.create_role(
                        name=role_data.get('name'),
                        permissions=discord.Permissions(permissions=role_data.get('permissions', 0)),
                        color=color,
                        hoist=role_data.get('hoist', False),
                        mentionable=role_data.get('mentionable', False)
                    )
                except discord.Forbidden:
                    continue  # Passer au suivant si on n'a pas les permissions
            
            self.roles_cache[role_data.get('id')] = role
        
        # Réorganiser les positions des rôles
        roles_positions = {self.roles_cache[r.get('id')]: r.get('position') 
                          for r in roles_data if r.get('id') in self.roles_cache}
        
        if roles_positions:
            try:
                await guild.edit_role_positions(positions=roles_positions)
            except discord.Forbidden:
                pass  # Ignorer si on n'a pas les permissions
    
    async def restore_categories(self, guild: discord.Guild, categories_data: List[Dict]):
        """Restaure toutes les catégories du serveur"""
        
        # Trier les catégories par position
        categories_data.sort(key=lambda c: c.get('position', 0))
        
        for category_data in categories_data:
            # Vérifier si la catégorie existe déjà
            category = discord.utils.get(guild.categories, name=category_data.get('name'))
            
            if not category:
                # Créer une nouvelle catégorie
                try:
                    category = await guild.create_category(
                        name=category_data.get('name'),
                        position=category_data.get('position', 0)
                    )
                except discord.Forbidden:
                    continue  # Passer à la suivante si on n'a pas les permissions
            
            # Définir les permissions de la catégorie
            overwrites = await self.create_permission_overwrites(category_data.get('permissions', []))
            
            if overwrites:
                try:
                    await category.edit(overwrites=overwrites)
                except discord.Forbidden:
                    pass  # Ignorer si on n'a pas les permissions
            
            self.categories_cache[category_data.get('id')] = category
    
    async def restore_text_channels(self, guild: discord.Guild, channels_data: List[Dict]):
        """Restaure tous les canaux textuels du serveur"""
        
        # Trier les canaux par position
        channels_data.sort(key=lambda c: c.get('position', 0))
        
        for channel_data in channels_data:
            # Trouver la catégorie du canal
            category = None
            if channel_data.get('category_id') in self.categories_cache:
                category = self.categories_cache[channel_data.get('category_id')]
            
            # Vérifier si le canal existe déjà
            channel = discord.utils.get(guild.text_channels, name=channel_data.get('name'))
            
            if not channel:
                # Créer un nouveau canal
                try:
                    overwrites = await self.create_permission_overwrites(channel_data.get('permissions', []))
                    
                    channel = await guild.create_text_channel(
                        name=channel_data.get('name'),
                        category=category,
                        position=channel_data.get('position', 0),
                        topic=channel_data.get('topic'),
                        slowmode_delay=channel_data.get('slowmode_delay', 0),
                        nsfw=channel_data.get('nsfw', False),
                        overwrites=overwrites
                    )
                except discord.Forbidden:
                    continue  # Passer au suivant si on n'a pas les permissions
            else:
                # Mettre à jour le canal existant
                try:
                    await channel.edit(
                        name=channel_data.get('name'),
                        category=category,
                        position=channel_data.get('position', 0),
                        topic=channel_data.get('topic'),
                        slowmode_delay=channel_data.get('slowmode_delay', 0),
                        nsfw=channel_data.get('nsfw', False)
                    )
                    
                    # Mettre à jour les permissions
                    overwrites = await self.create_permission_overwrites(channel_data.get('permissions', []))
                    if overwrites:
                        await channel.edit(overwrites=overwrites)
                        
                except discord.Forbidden:
                    pass  # Ignorer si on n'a pas les permissions
    
    async def restore_voice_channels(self, guild: discord.Guild, channels_data: List[Dict]):
        """Restaure tous les canaux vocaux du serveur"""
        
        # Trier les canaux par position
        channels_data.sort(key=lambda c: c.get('position', 0))
        
        for channel_data in channels_data:
            # Trouver la catégorie du canal
            category = None
            if channel_data.get('category_id') in self.categories_cache:
                category = self.categories_cache[channel_data.get('category_id')]
            
            # Vérifier si le canal existe déjà
            channel = discord.utils.get(guild.voice_channels, name=channel_data.get('name'))
            
            if not channel:
                # Créer un nouveau canal
                try:
                    overwrites = await self.create_permission_overwrites(channel_data.get('permissions', []))
                    
                    channel = await guild.create_voice_channel(
                        name=channel_data.get('name'),
                        category=category,
                        position=channel_data.get('position', 0),
                        bitrate=channel_data.get('bitrate', 64000),
                        user_limit=channel_data.get('user_limit', 0),
                        rtc_region=channel_data.get('rtc_region'),
                        overwrites=overwrites
                    )
                except discord.Forbidden:
                    continue  # Passer au suivant si on n'a pas les permissions
            else:
                # Mettre à jour le canal existant
                try:
                    await channel.edit(
                        name=channel_data.get('name'),
                        category=category,
                        position=channel_data.get('position', 0),
                        bitrate=channel_data.get('bitrate', 64000),
                        user_limit=channel_data.get('user_limit', 0),
                        rtc_region=channel_data.get('rtc_region')
                    )
                    
                    # Mettre à jour les permissions
                    overwrites = await self.create_permission_overwrites(channel_data.get('permissions', []))
                    if overwrites:
                        await channel.edit(overwrites=overwrites)
                        
                except discord.Forbidden:
                    pass  # Ignorer si on n'a pas les permissions
    
    async def restore_stage_channels(self, guild: discord.Guild, channels_data: List[Dict]):
        """Restaure tous les canaux de stage du serveur"""
        
        # Trier les canaux par position
        channels_data.sort(key=lambda c: c.get('position', 0))
        
        for channel_data in channels_data:
            # Trouver la catégorie du canal
            category = None
            if channel_data.get('category_id') in self.categories_cache:
                category = self.categories_cache[channel_data.get('category_id')]
            
            # Vérifier si le canal existe déjà
            channel = discord.utils.get(guild.stage_channels, name=channel_data.get('name'))
            
            if not channel:
                # Créer un nouveau canal
                try:
                    overwrites = await self.create_permission_overwrites(channel_data.get('permissions', []))
                    
                    channel = await guild.create_stage_channel(
                        name=channel_data.get('name'),
                        category=category,
                        position=channel_data.get('position', 0),
                        topic=channel_data.get('topic'),
                        overwrites=overwrites
                    )
                except discord.Forbidden:
                    continue  # Passer au suivant si on n'a pas les permissions
            else:
                # Mettre à jour le canal existant
                try:
                    await channel.edit(
                        name=channel_data.get('name'),
                        category=category,
                        position=channel_data.get('position', 0),
                        topic=channel_data.get('topic')
                    )
                    
                    # Mettre à jour les permissions
                    overwrites = await self.create_permission_overwrites(channel_data.get('permissions', []))
                    if overwrites:
                        await channel.edit(overwrites=overwrites)
                        
                except discord.Forbidden:
                    pass  # Ignorer si on n'a pas les permissions
    
    async def restore_forum_channels(self, guild: discord.Guild, channels_data: List[Dict]):
        """Restaure tous les forums du serveur"""
        
        # Trier les canaux par position
        channels_data.sort(key=lambda c: c.get('position', 0))
        
        for channel_data in channels_data:
            # Trouver la catégorie du canal
            category = None
            if channel_data.get('category_id') in self.categories_cache:
                category = self.categories_cache[channel_data.get('category_id')]
            
            # Vérifier si le canal existe déjà
            channel = discord.utils.get(guild.forums, name=channel_data.get('name'))
            
            if not channel:
                # Créer un nouveau canal
                try:
                    overwrites = await self.create_permission_overwrites(channel_data.get('permissions', []))
                    
                    channel = await guild.create_forum(
                        name=channel_data.get('name'),
                        category=category,
                        position=channel_data.get('position', 0),
                        overwrites=overwrites
                    )
                except discord.Forbidden:
                    continue  # Passer au suivant si on n'a pas les permissions
            else:
                # Mettre à jour le canal existant
                try:
                    await channel.edit(
                        name=channel_data.get('name'),
                        category=category,
                        position=channel_data.get('position', 0)
                    )
                    
                    # Mettre à jour les permissions
                    overwrites = await self.create_permission_overwrites(channel_data.get('permissions', []))
                    if overwrites:
                        await channel.edit(overwrites=overwrites)
                        
                except discord.Forbidden:
                    pass  # Ignorer si on n'a pas les permissions
    
    async def create_permission_overwrites(self, permissions_data: List[Dict]) -> Dict[Union[discord.Role, discord.Member], discord.PermissionOverwrite]:
        """Crée les objets de permission pour un canal"""
        overwrites = {}
        
        for perm_data in permissions_data:
            target = None
            
            # Déterminer la cible (rôle ou membre)
            if perm_data.get('type') == 'role':
                if perm_data.get('id') in self.roles_cache:
                    target = self.roles_cache[perm_data.get('id')]
                else:
                    # Essayer de trouver le rôle par son nom
                    target = discord.utils.get(self.bot.guilds[0].roles, name=perm_data.get('name'))
            
            elif perm_data.get('type') == 'member':
                # Trouver le membre par son ID
                try:
                    target = await self.bot.guilds[0].fetch_member(int(perm_data.get('id')))
                except (discord.NotFound, discord.HTTPException):
                    continue
            
            if target:
                # Créer l'objet de permissions
                perms = discord.PermissionOverwrite()
                
                for perm_name, perm_value in perm_data.get('permissions', {}).items():
                    if hasattr(perms, perm_name):
                        setattr(perms, perm_name, perm_value)
                
                overwrites[target] = perms
        
        return overwrites

async def setup(bot):
    await bot.add_cog(ServerSetupCog(bot))
    return