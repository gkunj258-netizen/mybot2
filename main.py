import discord
from discord.ext import commands, tasks
import asyncio
import os
import json
from datetime import datetime, timedelta, timezone
from groq import Groq
from google import genai

# --------------------------------------------------------
# 🧠 DUAL AI SETUP
# --------------------------------------------------------
# Groq for Fast Text (Riddles, Poems, Chat)
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Gemini for Vision (Avatar Rating Only)
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def get_groq_text(prompt):
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

# --------------------------------------------------------
# 🖼️ THE FIXED +RATE COMMAND (Real Vision)
# --------------------------------------------------------
@bot.command()
async def rate(ctx, member: discord.Member = None):
    """ACTUALLY sees the PFP using Gemini Vision"""
    member = member or ctx.author
    async with ctx.typing():
        try:
            # We use Gemini here because it can actually 'see' the image URL
            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[
                    "Rate this Discord profile picture out of 5 stars. Describe the colors, style, and vibe. Give 1 tip to make it better.",
                    member.display_avatar.url
                ]
            )
            embed = discord.Embed(title=f"Avatar Rating: {member.name}", description=response.text, color=0xFFD700)
            embed.set_thumbnail(url=member.display_avatar.url)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Vision Error: {e}. (Make sure your Gemini Key is valid!)")

# --------------------------------------------------------
# ✍️ FIXED CREATIVE THREADS (+create)
# --------------------------------------------------------
class CreateMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Poem", emoji="✍️", style=discord.ButtonStyle.primary)
    async def poem(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Fix: Using auto_archive_duration to ensure thread is visible
        thread = await interaction.channel.create_thread(
            name=f"Poem-{interaction.user.name}",
            auto_archive_duration=60,
            type=discord.ChannelType.public_thread
        )
        await interaction.response.send_message(f"✅ Poem thread created: {thread.mention}", ephemeral=True)
        
        words = await asyncio.to_thread(get_groq_text, "Give 5 random poetic words. Just the words.")
        await thread.send(f"Welcome {interaction.user.mention}! Write a poem using: **{words}**")

    @discord.ui.button(label="Riddle", emoji="🧩", style=discord.ButtonStyle.success)
    async def riddle(self, interaction: discord.Interaction, button: discord.ui.Button):
        thread = await interaction.channel.create_thread(
            name=f"Case-{interaction.user.name}",
            auto_archive_duration=60,
            type=discord.ChannelType.public_thread
        )
        await interaction.response.send_message(f"🕵️ Case started in: {thread.mention}", ephemeral=True)
        
        case = await asyncio.to_thread(get_groq_text, "Generate a hard mysterious detective riddle.")
        await thread.send(f"🔍 **THE MYSTERY:**\n{case}")

    @discord.ui.button(label="Song", emoji="🎤", style=discord.ButtonStyle.danger)
    async def song(self, interaction: discord.Interaction, button: discord.ui.Button):
        thread = await interaction.channel.create_thread(
            name=f"Song-{interaction.user.name}",
            auto_archive_duration=60,
            type=discord.ChannelType.public_thread
        )
        await interaction.response.send_message(f"🎤 Studio opened: {thread.mention}", ephemeral=True)
        await thread.send("Upload your song (mp3/wav) here! I'll give you a professional critique.")

# --------------------------------------------------------
# 🛡️ SYSTEM COMMANDS (+purge, +say, +status)
# --------------------------------------------------------
@bot.command()
@commands.has_permissions(manage_messages=True)
async def purge(ctx, amount: int):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 Purged {amount} messages.", delete_after=2)

@bot.command()
async def say(ctx, *, text):
    await ctx.message.delete()
    await ctx.send(text)

@bot.command()
async def online(ctx):
    if ctx.author.name == "kanjuuubarfii":
        await bot.change_presence(status=discord.Status.online)
        await ctx.send("Status -> **Online** 🟢")

@bot.command()
async def dnd(ctx):
    if ctx.author.name == "kanjuuubarfii":
        await bot.change_presence(status=discord.Status.dnd)
        await ctx.send("Status -> **Do Not Disturb** 🔴")

# --------------------------------------------------------
# 💬 CUSTOM TRIGGERS (Ashley/Swastik)
# --------------------------------------------------------
@bot.event
async def on_message(message):
    if message.author.bot: return

    content = message.content.lower()
    if "ashley" in content:
        await message.channel.send("Ashley is the queen of this server! 👑")
    if "swastik" in content:
        await message.channel.send("Swastik is always watching... 👁️")

    # Auto-Rate Poems in threads
    if "Poem-" in message.channel.name and len(message.content.split()) > 8:
        review = await asyncio.to_thread(get_groq_text, f"Rate this poem 1-5 and give a 1-sentence feedback: {message.content}")
        await message.reply(f"✍️ **AI Review:**\n{review}")

    await bot.process_commands(message)

@bot.command()
async def create(ctx):
    embed = discord.Embed(title="🎨 Creative Menu", description="Choose a mode below:", color=0x2ECC71)
    await ctx.send(embed=embed, view=CreateMenu())

bot.run(os.getenv("DISCORD_TOKEN"))
