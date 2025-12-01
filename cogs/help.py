import discord
from discord.ext import commands

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="aide")
    async def aide(self, ctx):
        embed = discord.Embed(
            title="📚 Liste des Commandes",
            description="Voici la liste de toutes les commandes disponibles",
            color=discord.Color.blue()
        )

        # Commandes de modération (Admin uniquement)
        embed.add_field(
            name="🛡️ Commandes de Modération (Admin)",
            value="""
`!ban <membre> [raison]` - Bannir un membre
`!unban <membre#0000>` - Débannir un membre
`!kick <membre> [raison]` - Expulser un membre
`!purge <nombre> [mode]` - Supprimer des messages
- mode "all": tous les messages (par défaut)
- mode "bot": uniquement les messages des bots
            """,
            inline=False
        )

        # Système de Tickets
        embed.add_field(
            name="🎫 Système de Tickets",
            value="""
`!ticket` - Créer un panneau de tickets (Admin)

**Fonctionnalités des tickets:**
• Création de ticket via le bouton 🎟️
• Fermeture de ticket 🔒
• Réouverture de ticket 🔓
• Suppression de ticket 🗑️
            """,
            inline=False
        )

        # Commandes Météo Aviation
        embed.add_field(
            name="🛩️ Météo Aviation",
            value="""
`!metar <ICAO>` - Obtenir le METAR d'un aéroport
`!taf <ICAO>` - Obtenir le TAF d'un aéroport
`!zulu` - Affiche le  Temps Universel Coordonné actuel
`!stations` - Affiche les informations détailées d'un terrain

            """,
            inline=False
        )

        # Commandes Fun
        embed.add_field(
            name="🎮 Commandes Fun",
            value="""
`!joke` - Raconte une blague sur l'aviation
`!dice` - Lance un dé à 6 faces
`!piece` - Lance une pièce (Pile ou Face)
`!atc` - Phrase aléatoire de contrôleur aérien
`!pilot` - Phrase aléatoire de pilote
`!emergency` - Génère une situation d'urgence aléatoire
            """,
            inline=False
        )

        # Note de bas de page
        embed.set_footer(text="[] = optionnel | <> = obligatoire | Admin = Commande réservée aux administrateurs")

        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Help(bot))