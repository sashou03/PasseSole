import discord
from discord.ext import commands
import csv
import random
import asyncio

# --- CONFIGURATION DU BOT ---
intents = discord.Intents.default()
intents.message_content = True  # Requis pour lire le contenu des commandes
intents.members = True          # Requis pour pouvoir interagir directement avec les joueurs (DM)

# Définition du préfixe des commandes (ici '!')
bot = commands.Bot(command_prefix='!', intents=intents)

# --- ETAT DE LA PARTIE ---
class GameState:
    def __init__(self):
        self.active = False            # Est-ce que la partie a commencé ?
        self.creator = None            # Utilisateur (discord.Member) qui a créé la partie (administrateur)
        self.players = []              # Liste des joueurs (discord.Member)
        self.scores = {}               # Dictionnaire {id_joueur: score_du_joueur}
        self.missions = []             # Liste des missions chargées depuis le CSV
        self.current_player = None     # Le joueur qui a accomplir la mission en cours
        self.current_mission = None    # Le texte de la mission en cours assignée
        self.timer_task = None         # Tâche asynchrone pour le minuteur de 5 minutes assigné
        self.channel = None            # Le salon textuel où se déroule la partie
        # Rotation équitable
        self.played_this_cycle = []    # Joueurs ayant déjà joué dans le cycle actuel
        
# Instance unique pour la partie
game = GameState()

# --- FONCTIONS UTILITAIRES ---
def load_missions(filename='missions.csv'):
    """Charge les missions depuis le fichier CSV en local."""
    missions = []
    try:
        with open(filename, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                missions.append(row)
    except FileNotFoundError:
        print(f"⚠️ Erreur : Le fichier {filename} est introuvable.")
    return missions

async def assign_new_mission(channel=None):
    """
    Choisit un joueur selon la rotation équitable, lui attribue une mission 
    et démarre le compteur de 5 minutes.
    """
    if not game.active or not game.players:
        return

    # Rotation équitable : si tout le monde a joué, on repart d'un nouveau cycle
    remaining = [p for p in game.players if p not in game.played_this_cycle]
    if not remaining:
        game.played_this_cycle = []
        remaining = list(game.players)

    # Choisir un joueur parmi ceux qui n'ont pas encore joué ce cycle
    game.current_player = random.choice(remaining)
    if game.current_player not in game.played_this_cycle:
        game.played_this_cycle.append(game.current_player)

    # Choisir une mission au hasard
    if game.missions:
        mission_data = random.choice(game.missions)
        game.current_mission = mission_data['Mission']
    else:
        game.current_mission = "Faire sourire quelqu'un (mission par défaut)"

    target_channel = channel or game.channel

    if target_channel:
        await target_channel.send("🎯 **Une nouvelle mission** a été attribuée à un joueur mystère... Il a le temps ! 5 minutes top chrono !")

    # Envoyer la mission en message privé (DM) pour qu'elle reste secrète
    try:
        await game.current_player.send(
            "🕵️ **NOUVELLE MISSION SECRÈTE** 🕵️\n"
            f"Votre mission : **{game.current_mission}**\n\n"
            "⏳ Vous avez **5 minutes** pour l'accomplir **discrètement** dans la vraie vie.\n"
            "Dès que vous avez réussi, tapez `!mission_reussie` dans le serveur !"
        )
    except discord.Forbidden:
        if target_channel:
            await target_channel.send(f"⚠️ **Attention !** Impossible d'envoyer un message privé à {game.current_player.mention}. L'utilisateur doit autoriser les messages privés depuis les paramètres du serveur !")

    # Annuler l'ancien timer s'il y en a un
    if game.timer_task:
        game.timer_task.cancel()
        
    # Démarrer automatiquement un timer de 5 minutes en tâche de fond
    game.timer_task = bot.loop.create_task(mission_timer(target_channel))

async def mission_timer(channel):
    """Gère le chronomètre de 5 minutes pour une mission donnée."""
    try:
        # Attendre 5 minutes (300 secondes)
        await asyncio.sleep(300)
        
        # Si la tâche n'est pas annulée avant 5 minutes, c'est un échec temporel
        if game.active and channel and game.current_player:
            await channel.send(
                f"⏰ Temps écoulé ! La mission de {game.current_player.mention} est terminée.\n"
                f"Sa mission secrète était : *{game.current_mission}*"
            )
            await asyncio.sleep(2)
            # Attribuer une nouvelle mission a un nouveau joueur automatiquement
            await assign_new_mission(channel=channel)
            
    except asyncio.CancelledError:
        # La tâche est annulée (par exemple quand on utilise !stop_mission ou quand quelqu'un réussit la sienne)
        pass

# --- ÉVÉNEMENTS DISCORD ---
@bot.event
async def on_ready():
    print("="*40)
    print(f"🤖 Bot connecté et prêt : {bot.user.name}")
    print("="*40)

# --- COMMANDES (JOUEURS) ---

@bot.command()
async def creer_partie(ctx):
    """Commande : !creer_partie -> Initialise une partie et donne les droits de créateur."""
    if game.creator is not None:
        await ctx.send("❌ Une partie a déjà été créée ! Terminez-la d'abord.")
        return
        
    game.creator = ctx.author
    game.channel = ctx.channel
    game.players = [ctx.author]  # Le créateur est automatiquement ajouté
    game.scores = {ctx.author.id: 0}
    game.played_this_cycle = []
    
    await ctx.send(
        "🎮 **Nouvelle partie de Passe Solé créée !**\n"
        f"👑 {ctx.author.mention} est l'administrateur de la partie.\n"
        "👉 Rejoignez avec `!join` (15 joueurs maximum).\n"
        "👉 L'administrateur lance la partie avec `!start`.\n"
        "👉 Pendant la partie : `!quit` pour abandonner une mission en cours (-1 point), `!abandon` pour quitter la partie."
    )

@bot.command()
async def join(ctx):
    """Commande : !join -> Le joueur est ajouté à la liste des participants."""
    if game.creator is None:
        await ctx.send("❌ Aucune partie n'est créée. Quelqu'un doit faire `!creer_partie`.")
        return

    # Limite de 15 joueurs
    if len(game.players) >= 15:
        await ctx.send("❌ La partie est complète ! Maximum 15 joueurs autorisés.")
        return
        
    if ctx.author not in game.players:
        game.players.append(ctx.author)
        game.scores[ctx.author.id] = 0
        await ctx.send(f"✅ {ctx.author.mention} a rejoint la partie ! ({len(game.players)}/15 joueurs confirmés)")
    else:
        await ctx.send(f"{ctx.author.mention}, vous êtes déjà dans la partie.")

@bot.command()
async def start(ctx):
    """Commande : !start -> Lance la partie (Réservé à l'administrateur)."""
    if game.creator is None:
        await ctx.send("❌ Créez d'abord une partie avec `!creer_partie`.")
        return
    if ctx.author != game.creator:
        await ctx.send("❌ Seul le créateur de la partie peut la lancer !")
        return
    if game.active:
        await ctx.send("❌ La partie a déjà commencé !")
        return
        
    game.missions = load_missions()
    if not game.missions:
        await ctx.send("⚠️ Info : Le fichier `missions.csv` est vide ou introuvable. Une mission par défaut sera utilisée.")

    game.active = True
    game.played_this_cycle = []
    await ctx.send(f"🚀 **LA PARTIE COMMENCE !** 🚀\nNombre de joueurs participants : {len(game.players)}\nPréparation de la première mission...")
    
    await asyncio.sleep(2)
    await assign_new_mission(channel=ctx.channel)

@bot.command()
async def mission_reussie(ctx):
    """Commande : !mission_reussie -> Déclare la mission complétée et ouvre le vote."""
    if not game.active:
        await ctx.send("❌ La partie n'est pas en cours !")
        return
    if ctx.author != game.current_player:
        await ctx.send("❌ Ce n'est pas à vous de faire ça, l'imposteur !")
        return
        
    # Si la personne valide à temps, on arrête le compte à rebours de 5 minutes
    if game.timer_task:
        game.timer_task.cancel()
        
    # Envoi du message pour lancer les votes
    poll_msg = await ctx.send(
        f"📢 Mission de {ctx.author.mention} terminée.\n\n"
        f"Sa mission secrète était de de : **{game.current_mission}**\n\n"
        "Votez pour confirmer si la mission a été bien exécutée (et si vous l'avez bien vu) !\n"
        "Réactions :\n"
        "✅ = mission réussie\n"
        "❌ = mission ratée (ex: elle ne l'a pas fait, ou n'a pas été discrète)\n\n"
        "⏳ Vous avez **45 secondes** pour voter !"
    )
    
    # Ajout des réactions du bot pour faciliter le vote
    await poll_msg.add_reaction("✅")
    await poll_msg.add_reaction("❌")
    
    # Attendre la fin des votes
    await asyncio.sleep(45)
    
    # Rafraîchir le message pour lire les réactions finales
    poll_msg = await ctx.channel.fetch_message(poll_msg.id)
    
    yes_votes = 0
    no_votes = 0
    
    for reaction in poll_msg.reactions:
        if str(reaction.emoji) == "✅":
            yes_votes = reaction.count - 1  # On exclut la 1ère réaction du bot
        elif str(reaction.emoji) == "❌":
            no_votes = reaction.count - 1
            
    total_votes = yes_votes + no_votes
    
    # Plus de 50% de votes positifs = validé
    if total_votes > 0 and yes_votes > (total_votes / 2):
        game.scores[ctx.author.id] += 1
        await ctx.send(
            f"🎉 **MISSION VALIDÉE !** {ctx.author.mention} gagne **1 point** !\n"
            f"(Score des votes : ✅ {yes_votes} / ❌ {no_votes})"
        )
    else:
        await ctx.send(
            "😢 **MISSION REFUSÉE !** La majorité l'a rejetée. Aucun point accordé.\n"
            f"(Score des votes : ✅ {yes_votes} / ❌ {no_votes})"
        )
        
    # Relance une nouvelle attribution
    await asyncio.sleep(4)
    await assign_new_mission(channel=ctx.channel)

@bot.command()
async def quit(ctx):
    """Commande : !quit -> Le joueur abandonne sa mission en cours et perd 1 point."""
    if not game.active:
        await ctx.send("❌ La partie n'est pas en cours !")
        return

    if ctx.author != game.current_player:
        await ctx.send("Ce n'est pas ton tour.")
        return

    if game.timer_task:
        game.timer_task.cancel()

    game.scores[ctx.author.id] -= 1

    await ctx.send(
        f"❌ {ctx.author.mention} a abandonné sa mission et perd 1 point.\n"
        f"*(Score actuel : {game.scores[ctx.author.id]} point(s))*"
    )

    await asyncio.sleep(2)
    await assign_new_mission(channel=ctx.channel)

@bot.command()
async def abandon(ctx):
    """Un joueur quitte la partie en cours sans arrêter le jeu."""
    if not game.active:
        await ctx.send("❌ La partie n'est pas en cours !")
        return

    if ctx.author not in game.players:
        await ctx.send("Tu n'es pas dans la partie.")
        return

    # Si c'est l'admin qui abandonne
    if ctx.author == game.creator:
        # Retirer l'admin de la liste des joueurs
        if ctx.author in game.players:
            game.players.remove(ctx.author)

        # Choisir le nouveau créateur = le joueur qui est venu en premier (index 0)
        if game.players:
            game.creator = game.players[0]
            await ctx.send(
                f"👑 {ctx.author.mention} a quitté la partie. "
                f"{game.creator.mention} est maintenant l'administrateur."
            )
        else:
            # Plus aucun joueur, on reset proprement
            game.creator = None
            game.active = False
            game.current_player = None
            game.current_mission = None
            if game.timer_task:
                game.timer_task.cancel()
            await ctx.send("Tous les joueurs ont quitté la partie. La partie est arrêtée.")
        return

    # Ici, c'est un joueur normal qui abandonne
    # Si c'est le joueur actuellement en mission
    if ctx.author == game.current_player:
        # Annuler le timer
        if game.timer_task:
            game.timer_task.cancel()

        # Le retirer des joueurs
        if ctx.author in game.players:
            game.players.remove(ctx.author)

        await ctx.send(f"🚪 {ctx.author.mention} a abandonné la partie.")
        # Si plus de joueurs, on stoppe tout
        if not game.players:
            game.active = False
            game.current_player = None
            game.current_mission = None
            await ctx.send("Il n'y a plus de joueurs. La partie se termine.")
            return

        # Sinon on passe au joueur suivant avec une nouvelle mission
        await asyncio.sleep(2)
        await assign_new_mission(channel=ctx.channel)
    else:
        # Pas le joueur en mission, il sort de la partie sans impacter la mission
        if ctx.author in game.players:
            game.players.remove(ctx.author)
        await ctx.send(f"🚪 {ctx.author.mention} a quitté la partie.")

@bot.command()
async def score(ctx):
    """Commande : !score -> Affiche le tableau des scores des joueurs de la partie."""
    if not game.players:
        await ctx.send("Il n'y a personne dans la partie pour le moment.")
        return
        
    sorted_scores = sorted(game.scores.items(), key=lambda item: item[1], reverse=True)
    
    leaderboard = "**🏆 Classement 🏆**\n\n"
    for idx, (player_id, score) in enumerate(sorted_scores, 1):
        player = discord.utils.get(game.players, id=player_id)
        name = player.display_name if player else f"Joueur ({player_id})"
        leaderboard += f"**{idx}.** {name} — {score} point(s)\n"
        
    await ctx.send(leaderboard)

# --- COMMANDES ADMINISTRATION / TEMPORISATION ---

@bot.command()
async def stop_mission(ctx):
    """Commande : !stop_mission -> Coupe immédiatement la mission en cours sans point."""
    if ctx.author != game.creator:
        await ctx.send("❌ Seul le créateur de la partie peut faire cette commande.")
        return
        
    if game.timer_task:
        game.timer_task.cancel()
        
    await ctx.send("🛑 Mission arrêtée par l'administrateur.")

@bot.command()
async def restart_timer(ctx):
    """Commande : !restart_timer -> Relance un timer propre de 5 minutes."""
    if ctx.author != game.creator:
        await ctx.send("❌ Seul le créateur de la partie peut faire cette commande.")
        return
    if not game.active:
        return
        
    if game.timer_task:
        game.timer_task.cancel()
        
    game.timer_task = bot.loop.create_task(mission_timer(ctx.channel))
    await ctx.send("⏱️ Le timer de 5 minutes a été relancé de zéro pour le joueur actif !")

@bot.command()
async def skip_mission(ctx):
    """Commande : !skip_mission -> Annule la mission et passe la main à qqn d'autre."""
    if ctx.author != game.creator:
        await ctx.send("❌ Seul le créateur de la partie peut faire cette commande.")
        return
    if not game.active:
        return
        
    if game.timer_task:
        game.timer_task.cancel()
        
    await ctx.send(
        f"⏭️ Phase passée par l'administrateur.\n"
        f"Le joueur précédent était {game.current_player.mention} (sa mission : *{game.current_mission}*)."
    )
    
    await asyncio.sleep(1)
    await assign_new_mission(channel=ctx.channel)

@bot.command()
async def help_passe(ctx):
    """Affiche l'aide du jeu Passe Solé."""
    embed = discord.Embed(
        title="Passe Solé - Aide",
        description="Liste des commandes disponibles pour jouer.",
        color=discord.Color.gold()
    )

    embed.add_field(
        name="Commandes de base",
        value=(
            "**!creer_partie** : Crée une nouvelle partie et te rend admin.\n"
            "**!join** : Rejoindre la partie en cours (max 15 joueurs).\n"
            "**!start** : Lancer la partie (admin uniquement).\n"
            "**!score** : Afficher le classement des joueurs."
        ),
        inline=False
    )

    embed.add_field(
        name="Pendant les missions",
        value=(
            "**!mission_reussie** : Quand tu as terminé ta mission secrète, déclenche le vote.\n"
            "**!quit** : Abandonner TA mission en cours, tu perds 1 point et le jeu passe au joueur suivant.\n"
            "**!abandon** : Quitter la partie en cours sans l'arrêter.\n"
            "• Si tu es en mission, la mission passe à un autre joueur.\n"
            "• Si tu es admin, l'admin passe au premier joueur qui a rejoint."
        ),
        inline=False
    )

    embed.add_field(
        name="Commandes admin",
        value=(
            "**!stop_mission** : Arrêter la mission en cours sans point.\n"
            "**!restart_timer** : Relancer le timer de 5 minutes pour le joueur actuel.\n"
            "**!skip_mission** : Passer la mission actuelle et en donner une nouvelle à un autre joueur."
        ),
        inline=False
    )

    embed.set_footer(text="Utilise !help_passe pour revoir ces commandes à tout moment.")
    await ctx.send(embed=embed)


# -- LANCEMENT DU BOT --
# Remplacer cette valeur par le token de votre propre bot depuis le panel développeur de Discord
bot.run("VOTRE_TOKEN_DISCORD_ICI")
