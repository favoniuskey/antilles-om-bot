import discord
from discord.ext import commands
import asyncio
import random  # Vous avez oublié d'importer random

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ===== Commande Fun ===== #
    # Listes de réponses
    aviation_jokes = [
        # Blagues sophistiquées sur l'aviation commerciale
        "Un A320 se plaint à un A380 : 'La vie est injuste, tu transportes 500 passagers et moi à peine 180...' L'A380 répond : 'T'inquiète pas, t'as plus de vols que moi... et au moins toi tu rentres dans tous les parkings !'",
        "Conversation entre deux contrôleurs :\n- 'Tu connais la différence entre un contrôleur aérien et un pilote ?'\n- 'Le pilote a mille et une histoires à raconter, le contrôleur n'en a qu'une : celle où il a sauvé mille et un pilotes.'",
        "Le commandant de bord annonce : 'Mesdames et messieurs, je viens d'éteindre le signal des ceintures de sécurité. Pour ceux qui souhaitent continuer à avoir peur, nous traverserons une zone de turbulences dans environ une heure.'",
        "Un jeune pilote à son instructeur : 'Comment faire pour être un bon pilote ?' L'instructeur : 'L'expérience.' Le jeune : 'Et comment acquérir de l'expérience ?' L'instructeur : 'Les mauvaises décisions.'",
        # Blagues techniques
        "Dialogue maintenance/pilote :\nPilote : 'Le moteur n°2 a développé un comportement erratique.'\nMaintenance : 'On lui a donné des cours de rattrapage, il devrait mieux se comporter maintenant.'",
        "Un mécanicien aviation explique son métier : 'Mon travail c'est comme de la chirurgie, sauf que si je me trompe, je peux toujours utiliser mon parachute.'",
        "Discussion entre pilotes :\n- 'Tu connais la nouvelle procédure pour économiser le carburant ?'\n- 'Non ?'\n- 'Tu coupes les moteurs et tu pries.'",
        # Humour sur la culture aviation
        "Premier cours de météo pour les pilotes :\n'Les cumulus, c'est cumulatif. Les stratus, c'est stratégique. Les nimbus, c'est n'importe quoi.'",
        "Un contrôleur à un pilote perdu dans le brouillard :\n- 'Quelle est votre position ?'\n- 'Je suis dans le cockpit.'\n- 'Non, je veux dire vos coordonnées.'\n- '42 ans, marié, trois enfants.'",
        "Pourquoi les pilotes de chasse sont-ils nuls en amour ? Parce que quand ça devient sérieux, ils s'éjectent !",
        # Situations réelles détournées
        "Annonce réelle d'un commandant après un atterrissage sportif :\n'Mesdames et messieurs, ce n'était pas un atterrissage, c'était une interception contrôlée de la piste.'",
        "Dialogue tour/pilote :\n- Tour : 'Confirmez votre altitude.'\n- Pilote : '35,000 pieds.'\n- Tour : 'Et comment pouvez-vous être à 35,000 pieds alors que mon radar indique 3,500 ?'\n- Pilote : 'Simple, je suis en train de faire du parachutisme.'",
        # Interactions passagers
        "Une hôtesse au micro : 'Pour les passagers du côté droit, vous pouvez admirer un magnifique coucher de soleil. Pour les passagers du côté gauche, vous pouvez admirer les passagers du côté droit admirer un magnifique coucher de soleil.'",
        "Annonce à bord : 'Pour les passagers qui ont peur en avion, rappelons que statistiquement, il y a plus de chances qu'il y ait un médecin à bord qu'un crash aérien.'",
        # Low-cost et compagnies
        "Nouveau service Ryanair : 'Pour seulement 5€ de plus, le pilote fera un second essai d'atterrissage si le premier a échoué.'",
        "Conversation Ryanair :\n- 'Monsieur, vous ne pouvez pas embarquer avec ces deux sacs.'\n- 'Mais c'est le même sac coupé en deux !'\n- 'Dans ce cas, ça fera 60€ pour avoir découpé nos airs.'",
        # Formation et apprentissage
        "L'instructeur au jeune pilote : 'Il y a 3 règles pour un bon atterrissage : d'abord la vitesse, ensuite la vitesse, et enfin... la vitesse.'\nL'élève : 'Et la piste ?'\nL'instructeur : 'Ça aide aussi.'"
    ]

    atc_phrases = [
        "F-GXYZ autorisé décollage piste 27, vent 180 degrés 8 nœuds",
        "Air France 1234 contactez approche 119.85",
        "Speedbird rappelez établi localizer piste 09",
        "HOP! maintenez niveau 90, trafic convergent 2000 pieds au-dessus",
        "Transavia 789 autorisé atterrissage piste 27 droite",
        "Eagle Force remise de gaz, trafic sur piste",
        "Air Corsica 456 roulez point d'arrêt A7 piste 27",
        "Attention tous aéronefs, cisaillement de vent signalé en finale",
        "Swiss 345 vérifiez train sorti",
        "À toutes stations, activation zone dangereuse Delta 31",
        "BAW123 cleared for ILS approach runway 27L",
        "United 456 caution wake turbulence departing A380",
        "Delta 789 contact departure 124.52",
        "American 234 reduce speed 180 knots",
        "Emirates 567 taxi via Alpha, Bravo to holding point C",
        "KLM 890 climb FL290, report passing FL250",
        "Singapore 123 traffic 2 o'clock, 5 miles, crossing right to left",
        "Lufthansa 456 hold short runway 09, landing traffic",
        "JAL 789 expect vectors for weather deviation",
        "Qantas 234 squawk 4721"
    ]

    pilot_phrases = [
        "Tour de Paris, F-GTRD, établi en finale 27 droite",
        "Air France 789, en sortie niveau 150 vers niveau 210",
        "Sol, Volotea 456, prêt à rouler, information Mike",
        "Approche, HOP! 234, demandons déroutement météo",
        "MAYDAY MAYDAY MAYDAY, Transavia 567, panne moteur droit",
        "Air Corsica 890, PAN PAN PAN, urgence médicale à bord",
        "Swiss 123, accusons réception, maintenant 5000 pieds",
        "Eagle Force 456, reçu autorisation, alignement et attente 27",
        "Tour, F-HZPK, remise de gaz cause turbulence",
        "Bretagne 789, niveau stable 320, demandons direct BOKNO",
        "Heathrow Tower, G-ABCD, established ILS 27R",
        "BA123 passing FL120 climbing FL240",
        "Ground, EZY456 ready for pushback stand 15",
        "Approach, RYR789 request weather deviation right of track",
        "MAYDAY MAYDAY MAYDAY, UA234 engine fire",
        "DLH567 PAN PAN PAN declaring minimum fuel",
        "Emirates 890 roger, maintaining heading 270",
        "SIA123 confirming STAR arrival KODAP 2A",
        "KLM456 going around, windshear warning",
        "QFA789 request progressive taxi, unfamiliar airport"
    ]
    
    emergency_situations = [
        # Urgences aéronautiques sérieuses
        "🚨 Panne moteur numéro 2 ! Déviation d'urgence vers l'aéroport le plus proche",
        "⚠️ Train d'atterrissage avant refuse de sortir ! Préparation pour atterrissage d'urgence",
        "🔥 Feu détecté dans la soute ! Équipage en procédure d'urgence",
        "💨 Dépressurisation rapide de la cabine à 35,000 pieds ! Masques à oxygène déployés",
        "📡 Perte totale des communications radio et satellite !",
        "🌩️ Foudre a frappé l'aile gauche ! Vérification des systèmes en cours",
        
        # Urgences amusantes
        "☕ ALERTE CRITIQUE : Plus de café en cabine ! Équipage en panique",
        "🍕 La dernière part de pizza a été mangée par le copilote ! Mutinerie en cours",
        "🎵 Le pilote automatique s'est mis à chanter du karaoké ! Impossible de l'arrêter",
        "🦆 Un canard avec des lunettes de soleil bloque la piste d'atterrissage",
        "🎮 Le pilote est trop absorbé par son jeu vidéo ! Qui peut prendre les commandes ?",
        "🌯 Turbulences extrêmes causées par un burrito mal digéré du commandant",
        
        # Situations absurdes
        "👽 OVNI repéré ! Il demande notre meilleure recette de crêpes",
        "🎪 Un cirque ambulant s'est installé sur la piste ! Les éléphants refusent de bouger",
        "🦁 Un chat s'est échappé en cabine et prétend être le nouveau commandant de bord",
        "🎅 Le Père Noël demande une autorisation d'atterrissage d'urgence pour réparer son traîneau",
        "🌈 Arc-en-ciel trop brillant ! Les pilotes doivent mettre leurs lunettes de soleil",
        "🎭 L'équipage entier s'est transformé en troupe de théâtre ! Représentation dans 10 minutes",
        
        # Urgences techniques avec une touche d'humour
        "💻 Le système informatique de bord ne répond qu'en émojis ! 😱",
        "📱 Tous les passagers doivent mettre leur téléphone en mode avion... littéralement !",
        "🔧 La clé à molette de secours a pris vie et refuse de réparer quoi que ce soit",
        "🚽 Toilettes en panne ! Temps estimé jusqu'à la destination : 3 heures... Bonne chance !",
        "🎵 Le système de divertissement ne diffuse plus que Baby Shark en boucle",
        "🌡️ La climatisation est bloquée en mode sauna ! Séance de yoga improvisée en cours"
    ]

    @commands.command(name="joke")
    async def joke(self, ctx):
        """Raconte une blague sur l'aviation"""
        await ctx.send(random.choice(self.aviation_jokes))

    @commands.command(name="dice")
    async def dice(self, ctx):
        """Lance un dé à 6 faces"""
        result = random.randint(1, 6)
        await ctx.send(f"🎲 Le dé roule et... **{result}** !")

    @commands.command(name="piece")
    async def piece(self, ctx):
        """Lance une pièce"""
        result = random.choice(["Pile", "Face"])
        await ctx.send(f"🪙 La pièce virevolte, tourne et... **{result}** !")

    @commands.command(name="atc")
    async def atc(self, ctx):
        """Génère une phrase aléatoire de contrôleur aérien"""
        await ctx.send(f"🎙️ *{random.choice(self.atc_phrases)}*")

    @commands.command(name="pilot")
    async def pilot(self, ctx):
        """Génère une phrase aléatoire de pilote"""
        await ctx.send(f"✈️ *{random.choice(self.pilot_phrases)}*")

    @commands.command(name="emergency")
    async def emergency(self, ctx):
        """Génère une situation d'urgence aléatoire"""
        await ctx.send(random.choice(self.emergency_situations))

    @commands.command(name="mega_emergency")
    async def mega_emergency(self, ctx):
        """Génère plusieurs situations d'urgence simultanées"""
        nb_situations = random.randint(2, 4)
        selected = random.sample(self.emergency_situations, nb_situations)
        await ctx.send("🚨 **MEGA EMERGENCY !!**\n" + "\n".join(selected))

async def setup(bot):
    await bot.add_cog(Fun(bot))