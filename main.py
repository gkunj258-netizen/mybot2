import discord
from discord.ext import commands, tasks
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone, time
from discord import ui, ButtonStyle, Interaction, Embed
from collections import defaultdict
import openai
from google import genai

# --------------------------------------------------------
# 🧠 AI INITIALIZATION
# --------------------------------------------------------
# Gemini for Chat/Text (Poem words, Riddles, etc.)
client_gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
chat_session = client_gemini.chats.create(model="gemini-2.0-flash")

# OpenAI for Vision (Avatar Rating)
client_openai = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --------------------------------------------------------
# ⚙️ BOT SETUP & DATA PERSISTENCE
# --------------------------------------------------------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='+', intents=intents, help_command=None)

FILES = {
    "afk": "afk.json", "warns": "warnings.json", "msgs": "messages.json",
    "reps": "reputation.json", "restr": "restricted_words.json", "remind": "reminders.json"
}

def load_json(key, default):
    if os.path.exists(FILES[key]):
        with open(FILES[key], 'r') as f: return json.load(f)
    return default

def save_json(key, data):
    with open(FILES[key], 'w') as f: json.dump(data, f, indent=4)

# Global Variables
afk_users = load_json("afk", {})
warnings_data = load_json("warns", {})
message_counts = load_json("msgs", {})
reputation = load_json("reps", {})
restricted_words = load_json("restr", [])
reminders_data = load_json("remind", [])
spam_tracker = defaultdict(lambda: {"messages": [], "strikes": 0})
IST = timezone(timedelta(hours=5, minutes=30))

# --------------------------------------------------------
# 🎨 UI VIEWS (RolePicker & CreateMenu are SEPARATE)
# --------------------------------------------------------

class RolePicker(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def handle_role(self, interaction: Interaction, role_name: str):
        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if not role: return await interaction.response.send_message(f"Role '{role_name}' not found!", ephemeral=True)
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(f"Removed {role_name}!", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"Added {role_name}!", ephemeral=True)

    @ui.button(label="Male", emoji="👦", style=ButtonStyle.blurple, custom_id="r_male")
    async def male(self, i, b): await self.handle_role(i, "Male")
    @ui.button(label="Female", emoji="👧", style=ButtonStyle.danger, custom_id="r_female")
    async def female(self, i, b): await self.handle_role(i, "Female")
    @ui.button(label="Valorant", emoji="🎯", style=ButtonStyle.success, custom_id="r_val")
    async def valo(self, i, b): await self.handle_role(i, "Valorant")
    @ui.button(label="BGMI", emoji="🪂", style=ButtonStyle.success, custom_id="r_bgmi")
    async def bgmi(self, i, b): await self.handle_role(i, "BGMI")

class CreateMenu(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Poem", emoji="✍️", style=ButtonStyle.primary)
    async def poem_start(self, interaction: Interaction, button: ui.Button):
        thread = await interaction.channel.create_thread(name=f"Poem-{interaction.user.name}", type=discord.ChannelType.public_thread)
        await interaction.response.send_message(f"Created {thread.mention}", ephemeral=True)
        res = await asyncio.to_thread(client_gemini.models.generate_content, model="gemini-2.0-flash", contents="Give 5 random poetic words.")
        await thread.send(f"Welcome! Write a poem using: **{res.text.strip()}**\nUse `+hpoem` for a hint!")

    @ui.button(label="Riddle", emoji="🧩", style=ButtonStyle.success)
    async def riddle_start(self, interaction: Interaction, button: ui.Button):
        thread = await interaction.channel.create_thread(name=f"Case-{interaction.user.name}", type=discord.ChannelType.public_thread)
        await interaction.response.send_message(f"Mystery started!", ephemeral=True)
        res = await asyncio.to_thread(client_gemini.models.generate_content, model="gemini-2.0-flash", contents="Generate a hard crime riddle.")
        await thread.send(f"🕵️ **THE CASE:**\n{res.text}")

    @ui.button(label="Song Critique", emoji="🎤", style=ButtonStyle.danger)
    async def song_start(self, interaction: Interaction, button: ui.Button):
        thread = await interaction.channel.create_thread(name=f"Song-{interaction.user.name}", type=discord.ChannelType.public_thread)
        await interaction.response.send_message(f"Studio open!", ephemeral=True)
        await thread.send("Upload your audio file! I'll analyze the structure.")

# --------------------------------------------------------
# ⏰ TASKS & BACKGROUND LOOPS
# --------------------------------------------------------

@tasks.loop(seconds=30)
async def check_reminders():
    now = datetime.now(IST).timestamp()
    to_remove = []
    for r in reminders_data:
        if now >= r['time']:
            target = bot.get_user(r['target_id'])
            if target:
                try:
                    if r.get('type') == "scheduled_dm":
                        sender = bot.get_user(r['user_id'])
                        embed = Embed(title="📬 Scheduled Message", description=r['reason'], color=0x00FF00)
                        embed.set_footer(text=f"Sent via {sender.name if sender else 'System'}")
                        await target.send(embed=embed)
                    else:
                        await target.send(f"⏰ **Reminder:** {r['reason']}")
                except: pass
            to_remove.append(r)
    if to_remove:
        for item in to_remove:
            if item in reminders_data: reminders_data.remove(item)
        save_json("remind", reminders_data)

@tasks.loop(time=time(hour=0, minute=0, tzinfo=IST))
async def weekly_reset():
    if datetime.now(IST).weekday() == 6: # Sunday
        message_counts.clear()
        save_json("msgs", message_counts)

# --------------------------------------------------------
# 🛡️ EVENTS & AI AUTO-DETECTION
# --------------------------------------------------------

@bot.event
async def on_ready():
    bot.add_view(RolePicker())
    bot.add_view(CreateMenu())
    check_reminders.start()
    weekly_reset.start()
    print(f"✅ {bot.user} is fully operational.")

@bot.event
async def on_message(message):
    if message.author.bot: return

    # 1. PROCESS COMMANDS FIRST (Fixes Unrestrict bug)
    await bot.process_commands(message)

    # 2. AFK SYSTEM
    if str(message.author.id) in afk_users:
        del afk_users[str(message.author.id)]
        save_json("afk", afk_users)
        await message.reply(f"Welcome back {message.author.name}! AFK removed.")

    for mention in message.mentions:
        if str(mention.id) in afk_users:
            await message.reply(f"💤 {mention.display_name} is AFK: {afk_users[str(mention.id)]}")

    # 3. FILTERS & SPAM
    if not message.content.startswith('+'):
        # Restriction Filter
        if any(word in message.content.lower() for word in restricted_words):
            try: await message.delete()
            except: pass
            return

        # Spam Auto-Timeout
        tracker = spam_tracker[message.author.id]
        tracker['messages'].append(message.content)
        if len(tracker['messages']) > 5: tracker['messages'].pop(0)
        if tracker['messages'].count(message.content) >= 5:
            try:
                await message.author.timeout(timedelta(days=1), reason="Spamming")
                await message.channel.send(f"🚫 {message.author.mention} timed out for 24h (Spam).")
            except: pass

    # 4. AI THREAD DETECTION
    if "Poem-" in message.channel.name and len(message.content.split()) > 10:
        res = await asyncio.to_thread(chat_session.send_message, f"Rate this poem 1-5: {message.content}")
        await message.reply(f"⭐ **AI Review:**\n{res.text}")

    if "Song-" in message.channel.name and message.attachments:
        res = await asyncio.to_thread(chat_session.send_message, "Analyze this song submission structure.")
        await message.reply(f"🎧 **Review:**\n{res.text}")

# --------------------------------------------------------
# 🛠️ COMMANDS
# --------------------------------------------------------

@bot.command()
async def rate(ctx, member: discord.Member = None):
    """ChatGPT Vision Avatar Rating"""
    member = member or ctx.author
    async with ctx.typing():
        try:
            response = client_openai.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "Rate this avatar 1-5, describe it, and give tips."},
                    {"type": "image_url", "image_url": {"url": member.display_avatar.url}}
                ]}]
            )
            embed = Embed(title=f"AI Rating: {member.name}", description=response.choices[0].message.content, color=0xFFD700)
            embed.set_thumbnail(url=member.display_avatar.url)
            await ctx.send(embed=embed)
        except Exception as e: await ctx.send(f"❌ Error: {e}")

@bot.command()
async def wish(ctx, member: discord.Member):
    """Birthday wisher with auto-role removal"""
    role = discord.utils.get(ctx.guild.roles, name="Birthday Boy/Girl")
    if not role: role = await ctx.guild.create_role(name="Birthday Boy/Girl", color=0xFF69B4)
    await member.add_roles(role)
    await ctx.send(f"🎉 Happy Birthday {member.mention}! 🎂", embed=Embed(description="You have the birthday role for 24 hours!"))
    await asyncio.sleep(86400)
    await member.remove_roles(role)

@bot.command()
async def senddm(ctx, member: discord.Member, duration: str, *, text: str):
    """Schedule a DM to someone else"""
    unit = duration[-1]
    amount = int(duration[:-1])
    secs = amount * 60 if unit == 'm' else amount * 3600 if unit == 'h' else amount
    reminders_data.append({"user_id": ctx.author.id, "target_id": member.id, "time": datetime.now(IST).timestamp() + secs, "reason": text, "type": "scheduled_dm"})
    save_json("remind", reminders_data)
    await ctx.send(f"📅 DM scheduled for {member.name} in {duration}.")

@bot.command()
async def remindpvt(ctx, duration: str, *, reason: str):
    """Private reminder confirmation"""
    unit = duration[-1]
    amount = int(duration[:-1])
    secs = amount * 60 if unit == 'm' else amount * 3600 if unit == 'h' else amount
    reminders_data.append({"user_id": ctx.author.id, "target_id": ctx.author.id, "time": datetime.now(IST).timestamp() + secs, "reason": reason, "type": "pvt"})
    save_json("remind", reminders_data)
    await ctx.send(f"🤫 Reminder set for {duration}!", ephemeral=True)

@bot.command()
@commands.has_permissions(administrator=True)
async def restrict(ctx, word: str):
    restricted_words.append(word.lower())
    save_json("restr", restricted_words)
    await ctx.send(f"🚫 '{word}' restricted.")

@bot.command()
@commands.has_permissions(administrator=True)
async def unrestrict(ctx, word: str):
    if word.lower() in restricted_words:
        restricted_words.remove(word.lower())
        save_json("restr", restricted_words)
        await ctx.send(f"✅ '{word}' allowed.")

@bot.command()
async def setup_roles(ctx):
    await ctx.send(embed=Embed(title="🎭 Get Roles", color=0x5865F2), view=RolePicker())

@bot.command()
async def create(ctx):
    await ctx.send(embed=Embed(title="🎮 Creative Games", color=0x2ECC71), view=CreateMenu())

# --------------------------------------------------------
# 📖 HELP INTERFACE
# --------------------------------------------------------

class HelpView(ui.View):
    def __init__(self, author):
        super().__init__(timeout=60)
        self.author, self.page = author, 0
        self.pages = [
            ("🛡️ Moderation", "`+kick`, `+ban`, `+timeout`, `+purge`, `+warn`, `+restrict`, `+unrestrict`"),
            ("🤖 AI & Fun", "`+rate`, `+create`, `+wish`, `+rep`, `+talk`"),
            ("⏰ Time/DM", "`+remind`, `+remindpvt`, `+senddm`, `+schedule`, `+afk`"),
            ("👤 Profile", "`+profile`, `+av`, `+banner`, `+leaderboard`"),
        ]

    def get_embed(self):
        t, d = self.pages[self.page]
        return Embed(title=t, description=d, color=0x3498DB).set_footer(text=f"Page {self.page+1}/4")

    @ui.button(label="Next", style=ButtonStyle.gray)
    async def next(self, i, b):
        self.page = (self.page + 1) % 4
        await i.response.edit_message(embed=self.get_embed())

@bot.command()
async def help(ctx):
    await ctx.send(embed=HelpView(ctx.author).get_embed(), view=HelpView(ctx.author))

bot.run(os.getenv("DISCORD_TOKEN"))
