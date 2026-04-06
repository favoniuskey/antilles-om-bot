import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
import os
import logging
from datetime import datetime
from dotenv import load_dotenv

# Configuration du logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler()])
logger = logging.getLogger('discord_bot')

# Chargement des variables d'environnement
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
IVAO_API_KEY = os.getenv("IVAO_API_KEY")

# Configuration
GUILD_ID = 1224706989146378371
ATC_ROLE_ID = 1228450258254827691
ADMIN_ROLES = [1297138129920196639, 1297148016725332068, 1309969291822760038]
ATC_CATEGORY_ID = 1313797047844995093
SUPPORT_CATEGORY_ID = 1313796797562490902

# Configuration du bot
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.presences = True

bot = commands.Bot(
    command_prefix='!', 
    intents=intents, 
    activity=discord.Game(name="!aide -- Assistance, Monitoring et Tickets"),
    reconnect=True,
    auto_sync_commands=False
)

# ========== SYSTÈME DE RELOAD DE COGS ==========

@bot.command(name="reload", hidden=True)
@commands.has_any_role(*ADMIN_ROLES)
async def reload_cog(ctx, cog_name: str = None):
    """Recharge un cog ou tous les cogs."""
    try:
        await ctx.message.delete()

        if cog_name is None:
            reloaded = []
            failed = []

            for cog in list(bot.extensions.keys()):
                try:
                    await bot.reload_extension(cog)
                    reloaded.append(cog)
                    logger.info(f"🔄 Cog rechargé: {cog}")
                except Exception as e:
                    failed.append(f"{cog}: {str(e)[:50]}")
                    logger.error(f"❌ Erreur reload {cog}: {e}")

            message = f"✅ Rechargement complet\n"
            message += f"OK: {len(reloaded)}\n"
            if failed:
                message += f"Erreurs: {len(failed)}"

            confirmation = await ctx.send(message)
            await asyncio.sleep(10)
            await confirmation.delete()
        else:
            cog_path = f"cogs.{cog_name}"
            try:
                await bot.reload_extension(cog_path)
                confirmation = await ctx.send(f"✅ **{cog_name}** rechargé!")
                logger.info(f"🔄 {cog_path} rechargé")
                await asyncio.sleep(5)
                await confirmation.delete()
            except Exception as e:
                error_msg = await ctx.send(f"❌ Erreur **{cog_name}**: {str(e)[:80]}")
                logger.error(f"❌ {e}")
                await asyncio.sleep(5)
                await error_msg.delete()
    except Exception as e:
        logger.error(f"❌ reload_cog: {e}")

@bot.command(name="load", hidden=True)
@commands.has_any_role(*ADMIN_ROLES)
async def load_cog(ctx, cog_name: str):
    """Charge un nouveau cog."""
    try:
        await ctx.message.delete()
        cog_path = f"cogs.{cog_name}"

        try:
            await bot.load_extension(cog_path)
            confirmation = await ctx.send(f"✅ **{cog_name}** chargé!")
            logger.info(f"📦 {cog_path} chargé")
            await asyncio.sleep(5)
            await confirmation.delete()
        except Exception as e:
            error_msg = await ctx.send(f"❌ Erreur **{cog_name}**: {str(e)[:80]}")
            logger.error(f"❌ {e}")
            await asyncio.sleep(5)
            await error_msg.delete()
    except Exception as e:
        logger.error(f"❌ load_cog: {e}")

@bot.command(name="unload", hidden=True)
@commands.has_any_role(*ADMIN_ROLES)
async def unload_cog(ctx, cog_name: str):
    """Décharge un cog."""
    try:
        await ctx.message.delete()
        cog_path = f"cogs.{cog_name}"

        try:
            await bot.unload_extension(cog_path)
            confirmation = await ctx.send(f"✅ **{cog_name}** déchargé!")
            logger.info(f"🗑️ {cog_path} déchargé")
            await asyncio.sleep(5)
            await confirmation.delete()
        except Exception as e:
            error_msg = await ctx.send(f"❌ Erreur **{cog_name}**: {str(e)[:80]}")
            logger.error(f"❌ {e}")
            await asyncio.sleep(5)
            await error_msg.delete()
    except Exception as e:
        logger.error(f"❌ unload_cog: {e}")

# ========== ÉVÉNEMENTS ==========

@bot.event
async def on_command(ctx):
    """Supprime le message de commande."""
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass

@bot.event
async def on_command_error(ctx, error):
    """Gestion des erreurs."""
    try:
        await ctx.message.delete()
    except (discord.errors.NotFound, discord.errors.Forbidden):
        pass

    if isinstance(error, commands.MissingPermissions):
        message = await ctx.send("❌ Tu n'as pas les permissions")
    elif isinstance(error, commands.MissingRequiredArgument):
        message = await ctx.send("❌ Il manque un argument")
    elif isinstance(error, commands.BadArgument):
        message = await ctx.send("❌ Argument invalide")
    elif isinstance(error, commands.CommandNotFound):
        message = await ctx.send("❌ Commande non trouvée")
    else:
        logger.error(f"❌ Erreur: {error}", exc_info=True)
        message = await ctx.send("❌ Une erreur s'est produite")

    try:
        await message.delete(delay=5)
    except:
        pass

@bot.command(name="syncsrv", hidden=True)
@commands.has_any_role(*ADMIN_ROLES)
async def sync_server_command(ctx):
    """Synchronise les commandes slash."""
    try:
        await ctx.message.delete()
        guild = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild)
        confirmation = await ctx.send(f"✅ {len(synced)} commandes synchronisées")
        logger.info(f"Commandes sync: {len(synced)}")
        await asyncio.sleep(5)
        await confirmation.delete()
    except Exception as e:
        logger.error(f"❌ Erreur sync: {e}")

@bot.command(name="syncall", hidden=True)
@commands.has_any_role(*ADMIN_ROLES)
async def sync_global_command(ctx):
    """Synchronise globalement."""
    try:
        await ctx.message.delete()
        synced = await bot.tree.sync()
        confirmation = await ctx.send(f"✅ {len(synced)} commandes globales")
        logger.info(f"Sync global: {len(synced)}")
        await asyncio.sleep(5)
        await confirmation.delete()
    except Exception as e:
        logger.error(f"❌ Erreur sync: {e}")

@bot.command(name="cogstatus", hidden=True)
@commands.has_any_role(*ADMIN_ROLES)
async def cog_status(ctx):
    """État des cogs."""
    try:
        await ctx.message.delete()
        loaded_cogs = list(bot.extensions.keys())
        commands_list = [cmd.name for cmd in bot.tree.get_commands()]

        status = f"**Cogs ({len(loaded_cogs)})**: " + ", ".join(loaded_cogs[:5])
        status += f"\n**Commandes ({len(commands_list)})**: " + ", ".join(sorted(commands_list)[:10])

        await ctx.send(status)
    except Exception as e:
        logger.error(f"❌ Erreur: {e}")

@bot.event
async def on_ready():
    """Démarrage du bot."""
    logger.info(f"🤖 Bot connecté: {bot.user}")

    if not TOKEN:
        logger.critical("❌ DISCORD_TOKEN manquant")
    if not IVAO_API_KEY:
        logger.warning("⚠️ IVAO_API_KEY manquante (necessaire pour l'API)")

    try:
        cogs_to_load = [
            "cogs.moderation",
            "cogs.help",
            "cogs.monitoring",
            "cogs.embed_modal",
            "cogs.booking_system",
            "cogs.aviation",
            "cogs.reaction_roles",
            "cogs.fun",
            "cogs.blacklist_welcome",
            "cogs.tickets",
            "cogs.voice_channel",
            "cogs.birthday",
            "cogs.server_dump",
            "cogs.RoleManager",
            "cogs.pilot_stats",
            "cogs.atc_stats"
        ]

        for cog in cogs_to_load:
            try:
                await bot.load_extension(cog)
                logger.info(f"✅ Cog chargé: {cog}")
            except Exception as e:
                logger.error(f"❌ Erreur {cog}: {e}")

        await asyncio.sleep(3)

        try:
            guild = discord.Object(id=GUILD_ID)
            synced_guild = await bot.tree.sync(guild=guild)
            logger.info(f"Commandes serveur: {len(synced_guild)}")
        except Exception as e:
            logger.error(f"❌ Erreur sync serveur: {e}")

        try:
            synced_global = await bot.tree.sync()
            logger.info(f"Commandes globales: {len(synced_global)}")
        except Exception as e:
            logger.error(f"❌ Erreur sync global: {e}")

        commands_list = [cmd.name for cmd in bot.tree.get_commands()]
        logger.info(f"Total: {len(commands_list)} commandes")

    except Exception as e:
        logger.error(f"❌ Erreur initialisation: {e}")

# ========== LANCEMENT ==========

if __name__ == "__main__":
    if not TOKEN:
        logger.critical("❌ DISCORD_TOKEN manquant!")
        exit(1)

    os.makedirs('cogs', exist_ok=True)
    os.makedirs('utils/data', exist_ok=True)
    os.makedirs('utils/logs', exist_ok=True)

    try:
        logger.info("🚀 Démarrage du bot...")
        bot.run(TOKEN)
    except discord.LoginFailure:
        logger.critical("❌ Token Discord invalide!")
    except Exception as e:
        logger.critical(f"❌ Erreur: {e}")
    finally:
        import gc
        gc.collect()
        logger.info("✅ Bot arrêté")
