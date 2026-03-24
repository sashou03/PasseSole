import discord
from discord.ext import commands
import os
import json
import csv
import random
import asyncio
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

games = {}  # channel_id -> Game state
scores_file = 'scores.json'


class MissionState:
    def __init__(self, text, user_name):
        self.text = text
        self.user_name = user_name
        self.timer_task = None
        self.message_vote_id = None


class Game:
    def __init__(self, owner_id):
        self.owner_id = owner_id
        self.players = set()
        self.started = False
        self.missions = []
        self.active_missions = {}  # user_id -> MissionState


def load_scores():
    if os.path.exists(scores_file):
        with open(scores_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_scores(scores):
    with open(scores_file, 'w', encoding='utf-8') as f:
        json.dump(scores, f, indent=4, ensure_ascii=False)


def update_score(user_id, points):
    scores = load_scores()
    uid = str(user_id)
    if uid not in scores:
        scores[uid] = 0
    scores[uid] += points
    save_scores(scores)


@bot.command()
async def creer_partie(ctx):
    if ctx.channel.id in games:
        await ctx.send("Une partie est déjà en cours ou en préparation dans ce salon.")
        return

    games[ctx.channel.id] = Game(ctx.author.id)
    await ctx.send(
        f"Partie créée par {ctx.author.mention} ! "
        f"Utilisez `!join` pour la rejoindre et `!start` pour la lancer."
    )


@bot.command()
async def join(ctx):
    if ctx.channel.id not in games:
        await ctx.send(
            "Aucune partie n'est en préparation dans ce salon. "
            "Utilisez `!creer_partie` pour en créer une."
        )
        return

    game = games[ctx.channel.id]
    if ctx.author.id in game.players:
        await ctx.send(f"{ctx.author.mention}, vous êtes déjà inscrit !")
        return

    if len(game.players) >= 15:
        await ctx.send("Désolé, la partie est pleine (15 joueurs maximum).")
        return

    game.players.add(ctx.author.id)
    await ctx.send(
        f"{ctx.author.mention} a rejoint la partie ! ({len(game.players)}/15 joueurs)"
    )


@bot.command()
async def quit(ctx):
    if ctx.channel.id not in games:
        return

    game = games[ctx.channel.id]

    if ctx.author.id == game.owner_id:
        await ctx.send("Le créateur de la partie a fait `!quit`. La partie est terminée !")

        scores = load_scores()
        game_scores = [(pid, scores.get(str(pid), 0)) for pid in game.players]
        game_scores.sort(key=lambda x: x[1], reverse=True)

        if game_scores:
            leaderboard = "**Classement final de la partie :**\n"
            for idx, (pid, score) in enumerate(game_scores, 1):
                leaderboard += f"{idx}. <@{pid}> : {score} points\n"
            await ctx.send(leaderboard)

        del games[ctx.channel.id]
    else:
        if ctx.author.id in game.players:
            game.players.remove(ctx.author.id)
            if ctx.author.id in game.active_missions:
                mission_state = game.active_missions.pop(ctx.author.id)
                if mission_state.timer_task:
                    mission_state.timer_task.cancel()
            await ctx.send(f"{ctx.author.mention} a quitté la partie.")


@bot.command()
async def start(ctx):
    if ctx.channel.id not in games:
        await ctx.send(
            "Aucune partie n'est en préparation dans ce salon. Utilisez `!creer_partie`."
        )
        return

    game = games[ctx.channel.id]

    if game.started:
        await ctx.send("La partie a déjà commencé !")
        return

    if len(game.players) < 2:
        await ctx.send("Il faut au moins 2 joueurs pour commencer la partie.")
        return

    missions = []
    try:
        with open('missions.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                missions.append(row)
    except Exception:
        await ctx.send("Erreur lors du chargement des missions.")
        return

    if not missions:
        await ctx.send("Le fichier des missions est vide.")
        return

    random.shuffle(missions)
    game.missions = missions
    game.started = True

    samples = random.sample(missions, min(3, len(missions)))
    annonce = "🕹️ **La partie commence !** Voici un exemple des missions possibles :\n"
    for m in samples:
        annonce += f"- {m['Mission']} ({m['Difficulte']})\n"
    annonce += "\n👉 Utilisez `!lancer_mission` pour recevoir votre première mission !"

    await ctx.send(annonce)


@bot.command()
async def lancer_mission(ctx):
    if ctx.channel.id not in games:
        await ctx.send("Aucune partie en cours dans ce salon.")
        return

    game = games[ctx.channel.id]
    if not game.started:
        await ctx.send(
            "La partie n'a pas encore commencé. "
            "Attendez que le créateur fasse `!start`."
        )
        return

    if ctx.author.id not in game.players:
        await ctx.send(
            "Vous ne participez pas à cette partie. "
            "Utilisez `!join` si ce n'est pas complet."
        )
        return

    if ctx.author.id in game.active_missions:
        await ctx.send(
            "Vous avez déjà une mission en cours ! "
            "Vous devez la réussir (`!mission_reussie`) ou l'abandonner (`!abandon`)."
        )
        return

    if not game.missions:
        await ctx.send("Il n'y a plus de missions disponibles dans cette partie !")
        return

    mission = random.choice(game.missions)
    text = f"{mission['Mission']} (Difficulté: {mission['Difficulte']})"

    mission_state = MissionState(text, ctx.author.display_name)
    game.active_missions[ctx.author.id] = mission_state

    await ctx.send(
        f"🎯 **Mission attribuée à {ctx.author.mention} !**\n\n"
        f"📜 {text}\n\n"
        f"⏰ Tu as 5 minutes pour accomplir cette mission."
    )

    async def timer_task():
        await asyncio.sleep(300)
        if hasattr(game, 'active_missions') and ctx.author.id in game.active_missions:
            m = game.active_missions[ctx.author.id]
            if m == mission_state:
                del game.active_missions[ctx.author.id]
                update_score(ctx.author.id, -1)
                await ctx.send(
                    f"⏳ **Temps écoulé pour {ctx.author.mention} !**\n"
                    f"La mission n'a pas été validée à temps. Pénalité: -1 point."
                )

    mission_state.timer_task = bot.loop.create_task(timer_task())


@bot.command()
async def mission_reussie(ctx):
    if ctx.channel.id not in games:
        return
    game = games[ctx.channel.id]
    if ctx.author.id not in game.active_missions:
        await ctx.send(f"{ctx.author.mention}, vous n'avez aucune mission en cours.")
        return

    mission_state = game.active_missions[ctx.author.id]

    if mission_state.timer_task:
        mission_state.timer_task.cancel()

    vote_msg = await ctx.send(
        f"📢 **Mission de {ctx.author.mention} terminée.**\n\n"
        f"Rappel : *{mission_state.text}*\n\n"
        f"Votez pour confirmer si la mission est réussie ! (30s)"
    )
    await vote_msg.add_reaction("✅")
    await vote_msg.add_reaction("❌")

    mission_state.message_vote_id = vote_msg.id

    await asyncio.sleep(30)

    try:
        updated_msg = await ctx.channel.fetch_message(vote_msg.id)
    except Exception:
        if ctx.author.id in game.active_missions:
            del game.active_missions[ctx.author.id]
        return

    yes_votes = 0
    no_votes = 0
    for react in updated_msg.reactions:
        if str(react.emoji) == "✅":
            yes_votes = react.count - 1
        elif str(react.emoji) == "❌":
            no_votes = react.count - 1

    if ctx.author.id in game.active_missions:
        del game.active_missions[ctx.author.id]

    if yes_votes == 0 and no_votes == 0:
        update_score(ctx.author.id, 1)
        await ctx.send(
            f"⏱️ Aucun vote reçu pour la mission de {ctx.author.mention}.\n"
            f"✅ Mission validée automatiquement (+1 point)."
        )
        return

    if yes_votes > no_votes:
        update_score(ctx.author.id, 1)
        await ctx.send(
            f"🎉 **Mission validée pour {ctx.author.mention} !** "
            f"(+1 point) ✅ ({yes_votes} oui contre {no_votes} non)"
        )
    else:
        update_score(ctx.author.id, -1)
        await ctx.send(
            f"❌ **Mission refusée pour {ctx.author.mention}.** "
            f"(-1 point) ❌ ({yes_votes} oui, {no_votes} non)"
        )


@bot.command()
async def abandon(ctx):
    if ctx.channel.id not in games:
        return
    game = games[ctx.channel.id]
    if ctx.author.id not in game.active_missions:
        await ctx.send(f"{ctx.author.mention}, vous n'avez aucune mission à abandonner.")
        return

    mission_state = game.active_missions.pop(ctx.author.id)
    if mission_state.timer_task:
        mission_state.timer_task.cancel()

    update_score(ctx.author.id, -1)
    await ctx.send(f"🏳️ {ctx.author.mention} a abandonné sa mission. (-1 point)")


@bot.command()
async def score(ctx):
    scores = load_scores()
    if not scores:
        await ctx.send("Le classement est vide pour le moment !")
        return

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    leaderboard = "🏆 **Classement Global Passe Solé** 🏆\n\n"
    for idx, (uid, sc) in enumerate(sorted_scores[:20], 1):
        leaderboard += f"**{idx}.** <@{uid}> : {sc} points\n"

    await ctx.send(leaderboard)


@bot.event
async def on_ready():
    print(f'Connecté en tant que {bot.user}')


bot.run(TOKEN)
