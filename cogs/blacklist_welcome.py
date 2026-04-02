import discord
from discord.ext import commands
import json
import os
import asyncio
import datetime
import typing

class BlacklistWelcomeSystem(commands.Cog):
    """Système de gestion de blacklist et de messages de bienvenue"""
    
    def __init__(self, bot):
        self.bot = bot
        self.config_dir = 'utils'
        self.blacklist_path = f'{self.config_dir}/blacklist.json'
        self.welcome_config_path = f'{self.config_dir}/welcome_config.json'
        self.ensure_config_directory()
        self.blacklist = self.load_blacklist()
        self.welcome_config = self.load_welcome_config()
        
    def ensure_config_directory(self):
        """Assure que le répertoire de configuration existe"""
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)
    
    def load_blacklist(self):
        """Charge la liste noire des utilisateurs bannis"""
        try:
            if os.path.exists(self.blacklist_path):
                with open(self.blacklist_path, 'r') as f:
                    data = json.load(f)
                    # Format amélioré avec raisons et dates
                    if isinstance(data, list) and all(isinstance(item, int) for item in data):
                        # Migration du format ancien vers le nouveau
                        return {str(user_id): {"reason": "Blacklisté", "date": datetime.datetime.now().isoformat(), "by": "Système"} for user_id in data}
                    return data
            return {}
        except Exception as e:
            print(f"Erreur lors du chargement de la blacklist: {e}")
            return {}

    def load_welcome_config(self):
        """Charge la configuration des messages de bienvenue"""
        try:
            if os.path.exists(self.welcome_config_path):
                with open(self.welcome_config_path, 'r') as f:
                    return json.load(f)
            return {
                "welcome_channel_id": 1228477224349339658,
                "rules_channel_id": 1228454190981054585,
                "presentation_channel_id": 1228669909249294367,
                "logo_path": "/home/container/logo.png",
                "enabled": True,
                "ban_on_blacklist": True
            }
        except Exception as e:
            print(f"Erreur lors du chargement de la config de bienvenue: {e}")
            return {
                "welcome_channel_id": 1228477224349339658,
                "rules_channel_id": 1228454190981054585,
                "presentation_channel_id": 1228669909249294367,
                "logo_path": "/home/container/logo.png",
                "enabled": True,
                "ban_on_blacklist": True
            }

    def save_config(self, config_type):
        """Sauvegarde la configuration spécifiée"""
        try:
            if config_type == "blacklist":
                with open(self.blacklist_path, 'w') as f:
                    json.dump(self.blacklist, f, indent=4)
            elif config_type == "welcome":
                with open(self.welcome_config_path, 'w') as f:
                    json.dump(self.welcome_config, f, indent=4)
        except Exception as e:
            print(f"Erreur lors de la sauvegarde de {config_type}: {e}")

    def is_blacklisted(self, user_id):
        """Vérifie si un utilisateur est dans la liste noire"""
        return str(user_id) in self.blacklist
    
    @commands.group(name="blacklist", aliases=["bl"], invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def blacklist_group(self, ctx):
        """Commandes de gestion de la blacklist"""
        await ctx.send_help(ctx.command)
    
    @blacklist_group.command(name="add", aliases=["a"])
    @commands.has_permissions(administrator=True)
    async def blacklist_add(self, ctx, user: typing.Union[discord.Member, discord.User, int], *, reason="Non spécifié"):
        """Ajoute un utilisateur à la blacklist"""
        user_id = user.id if isinstance(user, (discord.Member, discord.User)) else user
        user_name = str(user) if isinstance(user, (discord.Member, discord.User)) else f"ID: {user_id}"

        if self.is_blacklisted(user_id):
            return await ctx.send(f"⚠️ **{user_name}** est déjà dans la blacklist.")

        # Ajout à la blacklist avec informations
        self.blacklist[str(user_id)] = {
            "reason": reason,
            "date": datetime.datetime.now().isoformat(),
            "by": str(ctx.author.id)
        }
        self.save_config("blacklist")

        # Tentative de bannissement si l'utilisateur est sur le serveur
        ban_status = ""
        if isinstance(user, discord.Member) and self.welcome_config["ban_on_blacklist"]:
            try:
                await ctx.guild.ban(user, reason=f"Blacklisté: {reason}")
                ban_status = "\n✅ L'utilisateur a été banni du serveur."
            except Exception as e:
                ban_status = f"\n⚠️ Impossible de bannir l'utilisateur: {e}"

        embed = discord.Embed(
            title="⛔ Utilisateur Blacklisté",
            description=f"**Utilisateur**: {user_name}\n**Raison**: {reason}{ban_status}",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now()
        )
        embed.set_footer(text=f"Ajouté par {ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)
    
    @blacklist_group.command(name="remove", aliases=["rm", "r"])
    @commands.has_permissions(administrator=True)
    async def blacklist_remove(self, ctx, user: typing.Union[discord.Member, discord.User, int]):
        """Retire un utilisateur de la blacklist"""
        user_id = user.id if isinstance(user, (discord.Member, discord.User)) else user
        user_name = str(user) if isinstance(user, (discord.Member, discord.User)) else f"ID: {user_id}"

        if not self.is_blacklisted(user_id):
            return await ctx.send(f"⚠️ **{user_name}** n'est pas dans la blacklist.")

        # Supprimer de la blacklist
        del self.blacklist[str(user_id)]
        self.save_config("blacklist")

        embed = discord.Embed(
            title="✅ Utilisateur retiré de la Blacklist",
            description=f"**{user_name}** a été retiré de la blacklist.",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()
        )
        embed.set_footer(text=f"Retiré par {ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @blacklist_group.command(name="list", aliases=["l"])
    @commands.has_permissions(administrator=True)
    async def blacklist_list(self, ctx):
        """Affiche la liste des utilisateurs blacklistés"""
        if not self.blacklist:
            return await ctx.send("📋 La blacklist est vide.")

        # Pagination pour les longues listes
        entries_per_page = 5
        pages = []
        
        blacklist_items = list(self.blacklist.items())
        total_pages = (len(blacklist_items) + entries_per_page - 1) // entries_per_page

        for i in range(0, len(blacklist_items), entries_per_page):
            embed = discord.Embed(
                title="📋 Liste des utilisateurs blacklistés",
                color=discord.Color.red(),
                timestamp=datetime.datetime.now()
            )
            
            page_entries = blacklist_items[i:i+entries_per_page]
            for user_id, data in page_entries:
                # Tenter de récupérer l'utilisateur
                try:
                    user = await self.bot.fetch_user(int(user_id))
                    user_display = f"{user} ({user.id})"
                except:
                    user_display = f"ID: {user_id} (introuvable)"
                
                # Formater les détails
                reason = data.get("reason", "Non spécifié")
                date_str = "Non spécifié"
                
                if "date" in data:
                    try:
                        date = datetime.datetime.fromisoformat(data["date"])
                        date_str = date.strftime("%d/%m/%Y %H:%M")
                    except:
                        date_str = data["date"]
                
                by_user = "Système"
                if "by" in data:
                    try:
                        by_user_obj = await self.bot.fetch_user(int(data["by"]))
                        by_user = str(by_user_obj)
                    except:
                        by_user = f"ID: {data['by']}"
                
                embed.add_field(
                    name=user_display,
                    value=f"📝 **Raison:** {reason}\n📅 **Date:** {date_str}\n👮 **Par:** {by_user}",
                    inline=False
                )
            
            embed.set_footer(text=f"Page {i//entries_per_page + 1}/{total_pages}")
            pages.append(embed)
        
        if not pages:  # Sécurité
            return await ctx.send("Erreur lors de la génération de la liste.")
        
        # Si une seule page, pas besoin de pagination
        if len(pages) == 1:
            return await ctx.send(embed=pages[0])
        
        # Système de pagination simple
        current_page = 0
        message = await ctx.send(embed=pages[current_page])
        
        # Ajouter des réactions pour la navigation
        await message.add_reaction("⬅️")
        await message.add_reaction("➡️")
        
        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ["⬅️", "➡️"] and reaction.message.id == message.id
        
        while True:
            try:
                reaction, user = await self.bot.wait_for("reaction_add", timeout=60.0, check=check)
                
                if str(reaction.emoji) == "➡️" and current_page < len(pages) - 1:
                    current_page += 1
                    await message.edit(embed=pages[current_page])
                    await message.remove_reaction(reaction, user)
                    
                elif str(reaction.emoji) == "⬅️" and current_page > 0:
                    current_page -= 1
                    await message.edit(embed=pages[current_page])
                    await message.remove_reaction(reaction, user)
                    
                else:
                    await message.remove_reaction(reaction, user)
                    
            except asyncio.TimeoutError:
                await message.clear_reactions()
                break

    @blacklist_group.command(name="check", aliases=["c"])
    @commands.has_permissions(administrator=True)
    async def blacklist_check(self, ctx, user: typing.Union[discord.Member, discord.User, int]):
        """Vérifie si un utilisateur est blacklisté"""
        user_id = user.id if isinstance(user, (discord.Member, discord.User)) else user
        user_name = str(user) if isinstance(user, (discord.Member, discord.User)) else f"ID: {user_id}"

        if not self.is_blacklisted(user_id):
            embed = discord.Embed(
                title="✅ Vérification Blacklist",
                description=f"**{user_name}** n'est pas dans la blacklist.",
                color=discord.Color.green()
            )
            return await ctx.send(embed=embed)
        
        # Utilisateur blacklisté, afficher les détails
        data = self.blacklist[str(user_id)]
        reason = data.get("reason", "Non spécifié")
        date_str = "Non spécifié"
        
        if "date" in data:
            try:
                date = datetime.datetime.fromisoformat(data["date"])
                date_str = date.strftime("%d/%m/%Y %H:%M")
            except:
                date_str = data["date"]
        
        by_user = "Système"
        if "by" in data:
            try:
                by_user_obj = await self.bot.fetch_user(int(data["by"]))
                by_user = str(by_user_obj)
            except:
                by_user = f"ID: {data['by']}"
        
        embed = discord.Embed(
            title="⛔ Vérification Blacklist",
            description=f"**{user_name}** est dans la blacklist.",
            color=discord.Color.red()
        )
        embed.add_field(name="Raison", value=reason, inline=False)
        embed.add_field(name="Date", value=date_str, inline=True)
        embed.add_field(name="Ajouté par", value=by_user, inline=True)
        
        await ctx.send(embed=embed)

    @blacklist_group.command(name="clear")
    @commands.has_permissions(administrator=True)
    async def blacklist_clear(self, ctx):
        """Vide complètement la blacklist (demande confirmation)"""
        # Confirmation avant de procéder
        embed = discord.Embed(
            title="⚠️ Confirmation",
            description="Voulez-vous vraiment vider complètement la blacklist?\nCette action est irréversible.",
            color=discord.Color.gold()
        )
        message = await ctx.send(embed=embed)
        
        # Ajouter les réactions pour la confirmation
        await message.add_reaction("✅")
        await message.add_reaction("❌")
        
        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == message.id
        
        try:
            reaction, user = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)
            
            if str(reaction.emoji) == "✅":
                count = len(self.blacklist)
                self.blacklist = {}
                self.save_config("blacklist")
                
                confirm_embed = discord.Embed(
                    title="🗑️ Blacklist vidée",
                    description=f"{count} utilisateurs ont été retirés de la blacklist.",
                    color=discord.Color.green()
                )
                await message.edit(embed=confirm_embed)
                await message.clear_reactions()
            else:
                cancel_embed = discord.Embed(
                    title="❌ Opération annulée",
                    description="La blacklist n'a pas été modifiée.",
                    color=discord.Color.red()
                )
                await message.edit(embed=cancel_embed)
                await message.clear_reactions()
                
        except asyncio.TimeoutError:
            timeout_embed = discord.Embed(
                title="⏱️ Délai expiré",
                description="La confirmation a expiré. La blacklist n'a pas été modifiée.",
                color=discord.Color.grey()
            )
            await message.edit(embed=timeout_embed)
            await message.clear_reactions()

    @commands.group(name="welcome", aliases=["wlc"], invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def welcome_group(self, ctx):
        """Commandes de gestion des messages de bienvenue"""
        await ctx.send_help(ctx.command)
    
    @welcome_group.command(name="config")
    @commands.has_permissions(administrator=True)
    async def welcome_config_cmd(self, ctx):
        """Affiche la configuration actuelle du système de bienvenue"""
        config = self.welcome_config
        
        # Obtenir les noms des canaux
        welcome_channel = self.bot.get_channel(config.get("welcome_channel_id"))
        welcome_channel_name = welcome_channel.name if welcome_channel else "Non trouvé"
        
        rules_channel = self.bot.get_channel(config.get("rules_channel_id"))
        rules_channel_name = rules_channel.name if rules_channel else "Non trouvé"
        
        presentation_channel = self.bot.get_channel(config.get("presentation_channel_id"))
        presentation_channel_name = presentation_channel.name if presentation_channel else "Non trouvé"
        
        # Vérifier si le logo existe
        logo_path = config.get("logo_path", "Non configuré")
        logo_exists = os.path.exists(logo_path) if logo_path != "Non configuré" else False
        
        embed = discord.Embed(
            title="⚙️ Configuration du Système de Bienvenue",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="État du Système",
            value=f"Actif: {'✅' if config.get('enabled', True) else '❌'}\n"
                  f"Ban automatique: {'✅' if config.get('ban_on_blacklist', True) else '❌'}",
            inline=False
        )
        
        embed.add_field(
            name="Canaux",
            value=f"Bienvenue: {welcome_channel.mention if welcome_channel else welcome_channel_name}\n"
                  f"Règles: {rules_channel.mention if rules_channel else rules_channel_name}\n"
                  f"Présentation: {presentation_channel.mention if presentation_channel else presentation_channel_name}",
            inline=False
        )
        
        embed.add_field(
            name="Logo",
            value=f"Chemin: `{logo_path}`\n"
                  f"Existence: {'✅' if logo_exists else '❌'}",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @welcome_group.command(name="set")
    @commands.has_permissions(administrator=True)
    async def welcome_set(self, ctx, setting: str, *, value):
        """Configure un paramètre du système de bienvenue"""
        setting = setting.lower()
        
        # Paramètres qui nécessitent un canal
        if setting in ["welcome", "welcomechannel", "welcome_channel"]:
            try:
                # Extraire l'ID du canal s'il est mentionné
                if value.startswith("<#") and value.endswith(">"):
                    channel_id = int(value[2:-1])
                else:
                    channel_id = int(value)
                
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    return await ctx.send("⚠️ Canal introuvable.")
                
                self.welcome_config["welcome_channel_id"] = channel_id
                self.save_config("welcome")
                await ctx.send(f"✅ Canal de bienvenue défini sur {channel.mention}.")
            except ValueError:
                await ctx.send("⚠️ Veuillez fournir un ID de canal valide ou mentionner un canal.")
        
        elif setting in ["rules", "ruleschannel", "rules_channel"]:
            try:
                if value.startswith("<#") and value.endswith(">"):
                    channel_id = int(value[2:-1])
                else:
                    channel_id = int(value)
                
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    return await ctx.send("⚠️ Canal introuvable.")
                
                self.welcome_config["rules_channel_id"] = channel_id
                self.save_config("welcome")
                await ctx.send(f"✅ Canal des règles défini sur {channel.mention}.")
            except ValueError:
                await ctx.send("⚠️ Veuillez fournir un ID de canal valide ou mentionner un canal.")
        
        elif setting in ["presentation", "presentationchannel", "presentation_channel"]:
            try:
                if value.startswith("<#") and value.endswith(">"):
                    channel_id = int(value[2:-1])
                else:
                    channel_id = int(value)
                
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    return await ctx.send("⚠️ Canal introuvable.")
                
                self.welcome_config["presentation_channel_id"] = channel_id
                self.save_config("welcome")
                await ctx.send(f"✅ Canal de présentation défini sur {channel.mention}.")
            except ValueError:
                await ctx.send("⚠️ Veuillez fournir un ID de canal valide ou mentionner un canal.")
        
        # Paramètres booléens
        elif setting in ["enabled", "active", "enable"]:
            value_lower = value.lower()
            if value_lower in ["true", "yes", "y", "oui", "o", "1"]:
                self.welcome_config["enabled"] = True
                self.save_config("welcome")
                await ctx.send("✅ Système de bienvenue activé.")
            elif value_lower in ["false", "no", "n", "non", "0"]:
                self.welcome_config["enabled"] = False
                self.save_config("welcome")
                await ctx.send("✅ Système de bienvenue désactivé.")
            else:
                await ctx.send("⚠️ Valeur non reconnue. Utilisez 'oui' ou 'non'.")
        
        elif setting in ["ban_on_blacklist", "ban", "autoban"]:
            value_lower = value.lower()
            if value_lower in ["true", "yes", "y", "oui", "o", "1"]:
                self.welcome_config["ban_on_blacklist"] = True
                self.save_config("welcome")
                await ctx.send("✅ Bannissement automatique des utilisateurs blacklistés activé.")
            elif value_lower in ["false", "no", "n", "non", "0"]:
                self.welcome_config["ban_on_blacklist"] = False
                self.save_config("welcome")
                await ctx.send("✅ Bannissement automatique des utilisateurs blacklistés désactivé.")
            else:
                await ctx.send("⚠️ Valeur non reconnue. Utilisez 'oui' ou 'non'.")
        
        # Paramètre pour le logo
        elif setting in ["logo", "logopath", "logo_path"]:
            self.welcome_config["logo_path"] = value
            self.save_config("welcome")
            # Vérifier si le fichier existe
            if os.path.exists(value):
                await ctx.send(f"✅ Chemin du logo défini sur `{value}`.")
            else:
                await ctx.send(f"⚠️ Chemin du logo défini sur `{value}`, mais le fichier n'existe pas.")
        
        else:
            await ctx.send("⚠️ Paramètre non reconnu. Options disponibles: welcome_channel, rules_channel, presentation_channel, enabled, ban_on_blacklist, logo_path")
    
    @welcome_group.command(name="test")
    @commands.has_permissions(administrator=True)
    async def welcome_test(self, ctx):
        """Teste le message de bienvenue"""
        if not self.welcome_config.get("enabled", True):
            return await ctx.send("⚠️ Le système de bienvenue est désactivé.")
        
        # Simuler un message de bienvenue pour l'auteur de la commande
        try:
            await self.send_welcome_message(ctx.author, ctx.guild)
            await ctx.send("✅ Message de bienvenue de test envoyé.")
        except Exception as e:
            await ctx.send(f"⚠️ Erreur lors de l'envoi du message de test: {e}")
    
    async def send_welcome_message(self, member, guild):
        """Envoie le message de bienvenue pour un membre"""
        # Si le système est désactivé, ne rien faire
        if not self.welcome_config.get("enabled", True):
            return
        
        welcome_channel_id = self.welcome_config.get("welcome_channel_id")
        welcome_channel = self.bot.get_channel(welcome_channel_id)
        
        if not welcome_channel:
            print(f"Canal de bienvenue introuvable (ID: {welcome_channel_id})")
            return
        
        try:
            # Obtenir les mentions des canaux
            rules_channel_id = self.welcome_config.get("rules_channel_id")
            rules_channel = f"<#{rules_channel_id}>" if rules_channel_id else "canal des règles"
            
            presentation_channel_id = self.welcome_config.get("presentation_channel_id")
            presentation_channel = f"<#{presentation_channel_id}>" if presentation_channel_id else "canal de présentation"
            
            # Compter les membres (sans les bots)
            member_count = len([m for m in guild.members if not m.bot])
            
            # Préparer l'embed
            embed = discord.Embed(
                title="🌴 Bienvenue sur Les Antilles - OM 🌴",
                description=f"""
Un nouveau membre vient d'arriver !
Salut {member.mention} ! Tu es notre {member_count}ème membre !

Merci de :
• Accepter les règles dans {rules_channel}
• Te présenter dans {presentation_channel}
• Changer ton pseudo en `Prénom - VID IVAO` si tu en as un

Si tu n'as pas encore de VID IVAO, n'hésite pas à rejoindre IVAO, la communauté sera là pour t'accompagner !

Bons vols ! ✈️
                """,
                color=discord.Color.blue(),
                timestamp=datetime.datetime.now()
            )
            
            # Vérifier le logo
            logo_path = self.welcome_config.get("logo_path")
            if logo_path and os.path.exists(logo_path):
                logo = discord.File(logo_path, filename="logo.png")
                embed.set_thumbnail(url="attachment://logo.png")
                embed.set_author(name="Les Antilles - OM", icon_url="attachment://logo.png")
                embed.set_footer(text="Bienvenue !", icon_url="attachment://logo.png")
                await welcome_channel.send(file=logo, embed=embed)
            else:
                embed.set_footer(text="Bienvenue !")
                await welcome_channel.send(embed=embed)
            
        except Exception as e:
            print(f"Erreur lors de l'envoi du message de bienvenue: {e}")
    
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Gestionnaire d'événement pour l'arrivée d'un membre"""
        # Vérifier d'abord la blacklist
        if self.is_blacklisted(member.id):
            if self.welcome_config.get("ban_on_blacklist", True):
                try:
                    reason = self.blacklist.get(str(member.id), {}).get("reason", "Utilisateur blacklisté")
                    await member.guild.ban(member, reason=reason)
                    print(f"Utilisateur blacklisté {member} ({member.id}) banni automatiquement.")
                except Exception as e:
                    print(f"Impossible de bannir l'utilisateur blacklisté {member.id}: {e}")
            return
        
        # Si l'utilisateur n'est pas blacklisté, envoyer le message de bienvenue
        await self.send_welcome_message(member, member.guild)
    
    # Commandes de compatibilité avec l'ancien système
    @commands.command(name="addbll")
    @commands.has_permissions(administrator=True)
    async def legacy_add_blacklist(self, ctx, user_id: int):
        """Compatibilité avec l'ancienne commande addbll"""
        await self.blacklist_add(ctx, user_id)
    
    @commands.command(name="unbll")
    @commands.has_permissions(administrator=True)
    async def legacy_remove_blacklist(self, ctx, user_id: int):
        """Compatibilité avec l'ancienne commande unbll"""
        await self.blacklist_remove(ctx, user_id)

async def setup(bot):
    await bot.add_cog(BlacklistWelcomeSystem(bot))