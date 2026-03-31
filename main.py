import discord
from discord.ext import commands, tasks
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from groq import Groq # Fast & Free Alternative AI

# --------------------------------------------------------
# 🧠 AI INITIALIZATION (Swapping to Groq for speed & limits)
# --------------------------------------------------------
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def get_ai_response(prompt):
    completion = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
    )
    return completion.choices[0].message.content

# --------------------------------------------------------
# ⚙️ BOT SETUP
# --------------------------------------------------------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='+', intents=intents, help_command=None)
IST = timezone(timedelta(hours=5, minutes=30))
restricted_words = [] # Load from JSON as per previous versions

# --------------------------------------------------------
# 🛡️ CORE COMMANDS (+say, +purge, +status)
# --------------------------------------------------------

@bot.command()
@commands.has_permissions(manage_messages=True)
async def say(ctx, *, message):
    """Make the bot talk"""
    await ctx.message.delete()
    await ctx.send(message)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def purge(ctx, amount: int):
    """Delete messages in bulk"""
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 Deleted {amount} messages.", delete_after=3)

@bot.command()
async def online(ctx):
    if ctx.author.name == "kanjuuubarfii":
        await bot.change_presence(status=discord.Status.online)
        await ctx.send("Status: **Online** 🟢")

@bot.command()
async def idle(ctx):
    if ctx.author.name == "kanjuuubarfii":
        await bot.change_presence(status=discord.Status.idle)
        await ctx.send("Status: **Idle** 🟡")

@bot.command()
async def dnd(ctx):
    if ctx.author.name == "kanjuuubarfii":
        await bot.change_presence(status=discord.Status.dnd)
        await ctx.send("Status: **Do Not Disturb** 🔴")

# --------------------------------------------------------
# 💬 CUSTOM & AI COMMANDS
# --------------------------------------------------------

@bot.command()
async def talk(ctx, *, query):
    """Fast AI Chat using Groq"""
    async with ctx.typing():
        response = await asyncio.to_thread(get_ai_response, query)
        await ctx.reply(response)

@bot.command()
async def rate(ctx, member: discord.Member = None):
    """Rate avatar using logic (since Groq is text-only, we use aesthetic logic)"""
    member = member or ctx.author
    prompt = f"Give a creative 1-5 star rating and aesthetic description for a Discord user named {member.display_name}."
    response = await asyncio.to_thread(get_ai_response, prompt)
    embed = discord.Embed(title=f"Rating: {member.name}", description=response, color=0xFFD700)
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot: return

    # --- CUSTOM MESSAGES ---
    if "ashley" in message.content.lower():
        await message.channel.send("Ashley is the queen of this server! 👑")
    
    if "swastik" in message.content.lower():
        await message.channel.send("Swastik is always watching... 👁️")

    # --- AI AUTO-RATING (Poem/Song) ---
    if "Poem-" in message.channel.name and len(message.content.split()) > 5:
        res = await asyncio.to_thread(get_ai_response, f"Rate this poem 1-5: {message.content}")
        await message.reply(f"✍️ **Poem Review:**\n{res}")

    if "Song-" in message.channel.name and message.attachments:
        res = await asyncio.to_thread(get_ai_response, "Give a critique of a song submission.")
        await message.reply(f"🎧 **Music Review:**\n{res}")

    await bot.process_commands(message)

# --------------------------------------------------------
# 🎨 CREATIVE MENUS (Fixed Buttons)
# --------------------------------------------------------
class CreateMenu(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Poem", emoji="✍️", style=discord.ButtonStyle.primary)
    async def poem(self, interaction, button):
        thread = await interaction.channel.create_thread(name=f"Poem-{interaction.user.name}")
        words = await asyncio.to_thread(get_ai_response, "Give 5 random poetic words.")
        await thread.send(f"Write a poem using: **{words}**")
        await interaction.response.send_message("Poem thread created!", ephemeral=True)

    @discord.ui.button(label="Riddle", emoji="🧩", style=discord.ButtonStyle.success)
    async def riddle(self, interaction, button):
        thread = await interaction.channel.create_thread(name=f"Case-{interaction.user.name}")
        riddle = await asyncio.to_thread(get_ai_response, "Give a hard mysterious crime riddle.")
        await thread.send(f"🕵️ **THE CASE:**\n{riddle}")
        await interaction.response.send_message("Riddle thread created!", ephemeral=True)

@bot.command()
async def create(ctx):
    await ctx.send("🎨 **Creative Hub**", view=CreateMenu())

bot.run(os.getenv("DISCORD_TOKEN"))
