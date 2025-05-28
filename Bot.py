# Importation des modules nécessaires
import os
import discord
import random
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
import yt_dlp
from collections import deque
import asyncio
from datetime import timedelta, datetime
import uuid
import logging

# Chargement des variables d'environnement (notamment le token du bot)
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Configuration des permissions (intents) du bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

logging.basicConfig(level=logging.DEBUG)

bot = commands.Bot(command_prefix="!", intents=intents)

user_strikes = {}
strike_timeouts = [
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=5),
    timedelta(minutes=10),
    timedelta(hours=1)
]
STRIKE_EXPIRATION_HOURS = 4
SONG_QUEUES = {}

async def search_ytdlp_async(query, ydl_opts):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _extract(query, ydl_opts))

def _extract(query, ydl_opts):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(query, download=False)

badwords = ["nword", "n word", "Nword", "N Word", "jgl diff", "JGL DIFF", "JGL diff", "jgl DIFF"]
badwordsSentences = [
    "Je crois que t'utilise encore la version démo de ton cerveau",
    "Chaque fois que tu parles, le QI moyen du serveur chute.",
    "Vu les résultats sur toi, je crois que tu t'es fais arnaquer, demande un remboursement à l'école.",
    "C'est pas une insulte, c'est un appel à l'aide avec de la haine autour.",
    "Ton message sent l'échec scolaire et la Wi-Fi volée.",
    "Tu pollues le chat, ferme-la, même Babou est plus intéressant.",
    "Tu fais honte à ton clavier, à ta famille, à ton PC, même le Wi-Fi que tu utilises a honte de toi.",
    "Ton clavier mérite mieux que toi",
    "Appelle le 3114, c'est gratuit, c'est pour les gens comme toi"
]

def format_timedelta(td):
    total_sec = int(td.total_seconds())
    if total_sec < 60:
        return f"{total_sec}s"
    elif total_sec < 3600:
        return f"{total_sec // 60}m"
    else:
        return f"{total_sec // 3600}h"

@tasks.loop(minutes=10)
async def clear_expired_strikes():
    now = datetime.utcnow()
    for user_id in list(user_strikes.keys()):
        user_strikes[user_id] = [
            (t, lvl) for t, lvl in user_strikes[user_id]
            if (now - t) < timedelta(hours=STRIKE_EXPIRATION_HOURS)
        ]
        if not user_strikes[user_id]:
            del user_strikes[user_id]

async def sanction_user(message):
    author = message.author
    now = datetime.utcnow()

    if author.id not in user_strikes:
        user_strikes[author.id] = []

    user_strikes[author.id] = [
        (t, lvl) for t, lvl in user_strikes[author.id]
        if (now - t) < timedelta(hours=STRIKE_EXPIRATION_HOURS)
    ]

    current_strike = len(user_strikes[author.id])
    strike_level = min(current_strike, len(strike_timeouts) - 1)
    duration = strike_timeouts[strike_level]
    user_strikes[author.id].append((now, strike_level))

    try:
        await author.timeout(duration, reason=f"{current_strike + 1} ???")
    except Exception as e:
        print(f"Erreur timeout : {e}")

    log_channel = discord.utils.get(message.guild.text_channels, name="code")
    if log_channel:
        embed = discord.Embed(
            title="🔝 Sanction appliquée",
            description=f"{author.mention} a été sanctionné",
            color=discord.Color.red(),
            timestamp=now
        )
        embed.add_field(name="Contenu du message", value=message.content, inline=False)
        embed.add_field(name="Strike #", value=str(current_strike + 1), inline=True)
        embed.add_field(name="Durée", value=format_timedelta(duration), inline=True)
        embed.set_footer(text=f"Utilisateur ID: {author.id}")
        await log_channel.send(embed=embed)

@bot.event
async def on_ready():
    print(f"{bot.user} is online!")

    synced = 0
    for guild in bot.guilds:
        try:
            await bot.tree.sync(guild=guild)
            print(f"Synchronized slash commands for guild: {guild.name} ({guild.id})")
            synced += 1
        except Exception as e:
            print(f"Failed to sync for guild {guild.name} ({guild.id}): {e}")

    clear_expired_strikes.start()
    print(f"Synchronized slash commands for {synced} server(s).")


@bot.event
async def on_message(message):
    if message.author.id != bot.user.id and any(word in message.content.lower() for word in badwords):
        await message.channel.send(f"{message.author.mention} " + random.choice(badwordsSentences))
        await asyncio.sleep(1)
        await message.channel.send("Pour la peine je te propose d'aller faire un petit tour 🧹")
        await sanction_user(message)
        await message.delete()

    await bot.process_commands(message)

@bot.tree.command(name="skip", description="Skip la musique en cours")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client and (interaction.guild.voice_client.is_playing() or interaction.guild.voice_client.is_paused()):
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("Skipped the current song.")
    else:
        await interaction.response.send_message("Pas de musique à skip")

@bot.tree.command(name="pause", description="Met la musique en pause")
async def pause(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client is None:
        return await interaction.response.send_message("Pas connecté à un chan")
    if not voice_client.is_playing():
        return await interaction.response.send_message("Aucune musique en cours.")
    voice_client.pause()
    await interaction.response.send_message("Mute!")

@bot.tree.command(name="resume", description="Reprend la musique en pause")
async def resume(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client is None:
        return await interaction.response.send_message("Pas connecté à un chan")
    if not voice_client.is_paused():
        return await interaction.response.send_message("I'm not paused right now.")
    voice_client.resume()
    await interaction.response.send_message("Playback resumed!")

@bot.tree.command(name="stop", description="Stop playback and clear the queue.")
async def stop(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if not voice_client or not voice_client.is_connected():
        return await interaction.response.send_message("Pas connecté à un chan")

    guild_id_str = str(interaction.guild_id)
    if guild_id_str in SONG_QUEUES:
        SONG_QUEUES[guild_id_str].clear()

    if voice_client.is_playing() or voice_client.is_paused():
        voice_client.stop()
    await voice_client.disconnect()

    await interaction.response.send_message("Stopped playback and disconnected!")

@bot.tree.command(name="liste", description="Affiche les musiques dans la file d'attente")
async def queue(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)

    if guild_id not in SONG_QUEUES or len(SONG_QUEUES[guild_id]) == 0:
        await interaction.response.send_message("La file d'attente est vide.")
        return

    queue_list = SONG_QUEUES[guild_id]
    embed = discord.Embed(title="🎵 File d'attente", color=discord.Color.blue())

    for i, (_, title) in enumerate(queue_list, start=1):
        embed.add_field(name=f"{i}.", value=title, inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="sync", description="Force la synchronisation des commandes slash.")
async def sync(interaction: discord.Interaction):
    synced = await bot.tree.sync()
    await interaction.response.send_message(f"{len(synced)} commande(s) slash synchronisée(s) !")

@bot.tree.command(name="play", description="Ajoute une musique à la file d'attente")
@app_commands.describe(song_query="Search query")
async def play(interaction: discord.Interaction, song_query: str):
    await interaction.response.defer()

    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.followup.send("Tu dois être dans un channel vocal pour lancer une musique.")
        return

    voice_channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client

    if voice_client is None:
        voice_client = await voice_channel.connect()
    elif voice_client.channel != voice_channel:
        await voice_client.move_to(voice_channel)

    ydl_options = {
        "format": "bestaudio[abr<=96]/bestaudio",
        "noplaylist": True,
        "youtube_include_dash_manifest": False,
        "youtube_include_hls_manifest": False,
    }

    query = "ytsearch1: " + song_query

    try:
        results = await search_ytdlp_async(query, ydl_options)
        tracks = results.get("entries", [])

        if not tracks:
            await interaction.followup.send("❌ Aucun résultat trouvé.")
            return

        first_track = tracks[0]
        audio_url = first_track["url"]
        title = first_track.get("title", "Untitled")

        guild_id = str(interaction.guild_id)
        if SONG_QUEUES.get(guild_id) is None:
            SONG_QUEUES[guild_id] = deque()

        SONG_QUEUES[guild_id].append((audio_url, title))

        if voice_client.is_playing() or voice_client.is_paused():
            await interaction.followup.send(f"✅ Ajouté à la file d'attente : **{title}**")
        else:
            await interaction.followup.send(f"▶️ Lecture de : **{title}**")
            await play_next_song(voice_client, guild_id, interaction.channel)

    except Exception as e:
        logging.error(f"Erreur lors de la recherche de musique : {e}")
        await interaction.followup.send("❌ Une erreur est survenue pendant la recherche.")


async def play_next_song(voice_client, guild_id, channel):
    if SONG_QUEUES[guild_id]:
        audio_url, title = SONG_QUEUES[guild_id].popleft()

        # Téléchargement du fichier avec yt_dlp
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"/tmp/{uuid.uuid4()}.%(ext)s",  # fichier temporaire Railway
            "quiet": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(audio_url, download=True)
            file_path = ydl.prepare_filename(info)

        source = discord.FFmpegPCMAudio(file_path, options="-vn")

        def after_play(error):
            if error:
                print(f"Error playing {title}: {error}")
            if os.path.exists(file_path):
                os.remove(file_path)
            asyncio.run_coroutine_threadsafe(play_next_song(voice_client, guild_id, channel), bot.loop)

        voice_client.play(source, after=after_play)
        asyncio.create_task(channel.send(f"On écoute: **{title}**"))
    else:
        await voice_client.disconnect()
        SONG_QUEUES[guild_id] = deque()

# Run the bot
bot.run(TOKEN)
