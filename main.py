import discord
from discord.ext import commands, tasks
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone, time 
from discord import ui, ButtonStyle, Interaction, Embed
import sys
import re 
from operator import itemgetter
from typing import Optional
import aiohttp 
from collections import defaultdict

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# --------------------------------------------------------
# 🧠 GEMINI AI INTEGRATION
# --------------------------------------------------------
try:
    from google import genai
    from google.genai import types 
except ImportError:
    print("Error: The 'google-genai' library is not installed. Please run 'pip install google-genai'")
    sys.exit(1)

# --- FIXED GEMINI INITIALIZATION ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Create the client and start a chat session
# Place this at the top of your script with your other global variables
user_chats = {}
client = genai.Client(api_key=GEMINI_API_KEY)
chat_session = client.chats.create(model="gemini-2.0-flash") # This defines chat_session

if GEMINI_API_KEY == "YOUR_GEMINI_API_KEY_HERE":
    print("\nWARNING: GEMINI_API_KEY is using the placeholder. AI commands will not work.")
else:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        chat = client.chats.create(model="gemini-2.5-flash")
        
        print("Gemini client initialized for chat.")
    except Exception as e:
        print(f"\nFATAL ERROR initializing Gemini client: {e}")
        
# --------------------------------------------------------
# --- BOT CONFIGURATION ---
# --------------------------------------------------------
AI_CHANNEL_ID = 1462463900451737745
# Replace with your bot's token 
MOD_LOG_CHANNEL_NAME = "mod-log"
MAX_MESSAGE_LENGTH = 2000
IST_TIMEZONE = timezone(timedelta(hours=5, minutes=30))

# --- DATA FILES ---
AFK_FILE = 'afk.json'
WARNINGS_FILE = 'warnings.json'
MESSAGES_FILE = 'messages.json'
REMINDERS_FILE = 'reminders.json' 

# --- LEADERBOARD CONFIG ---
LEADERBOARD_CHANNEL_NAME = "general" 
WINNER_ROLE_NAME = "The Chatterbox" 

# --- INTENTS & BOT INITIALIZATION ---
intents = discord.Intents.default()
intents.members = True 
intents.message_content = True 

# Disabled default help command and set prefix
bot = commands.Bot(command_prefix='+', intents=intents, help_command=None)
bot.http_session = None # Initialize http_session
    
# --- NEW:SPAM PROTECTION STORAGE ---
# Tracks message repeats and 12-hour strikes
spam_tracker = defaultdict(lambda: {"messages": [], "strikes": 0, "last_strike_time": None})

def load_data(filename, default={}):
    if os.path.exists(filename):
        with open(filename,'r') as f:
            try:
                return json.load(f)
            except:
                    return default
                    
# --- 2. FILE & DATA INITIALIZATION ---

HIGHLIGHTS_FILE = 'highlights.json'

# Load existing data into memory
highlights = load_data(HIGHLIGHTS_FILE)
restricted_words = load_data('restricted_words.json',default=[])
if restricted_words is None:
    restricted_words = []

reputation = load_data('reputation.json')
if reputation is None:
    reputation = {}
message_counts = load_data('messages.json')
if message_counts is None:
    message_counts = {}
    
user_chats = {}
HIGHLIGHTS_FILE = 'highlights.json'

def load_highlights():
    if os.path.exists(HIGHLIGHTS_FILE):
        with open(HIGHLIGHTS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_highlights(data):
    with open(HIGHLIGHTS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

highlights = load_highlights()

def load_data(filename, default={}):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print(f"Warning: {filename} is corrupted. Starting with default data.")
                return default
    return default

def save_data(data, filename):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4)

afk_users = load_data(AFK_FILE)
warnings_data = load_data(WARNINGS_FILE)
message_counts = load_data(MESSAGES_FILE)
reminders_data = load_data(REMINDERS_FILE)

# --- LOGGING UTILITIES ---
def get_mod_log_channel(guild: discord.Guild):
    return discord.utils.get(guild.text_channels, name=MOD_LOG_CHANNEL_NAME)

async def send_mod_log(guild, title, description, moderator: discord.User):
    channel = get_mod_log_channel(guild)
    if channel:
        embed = discord.Embed(title=title, description=description, color=discord.Color.orange())
        embed.set_footer(text=f"Moderator: {moderator.name}#{moderator.discriminator}", 
                             icon_url=moderator.display_avatar.url)
        embed.timestamp = datetime.now(timezone.utc)
        await channel.send(embed=embed)

def split_message_chunks(text: str) -> list[str]:
    # Basic logic to split long responses
    if len(text) <= MAX_MESSAGE_LENGTH: return [text]
    
    chunks = []
    current_chunk = ""
    for line in text.split('\n'):
        if len(current_chunk) + len(line) + 1 > MAX_MESSAGE_LENGTH:
            chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += '\n' + line if current_chunk else line
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

# --------------------------------------------------------
# ⚙️ BACKGROUND TASKS AND UTILITIES
# --------------------------------------------------------

# --- REMINDER PARSING AND CREATION UTILITY ---
def parse_reminder_time(date_str: str, time_str: str) -> datetime:
    """Parses DD/MM/YYYY and HH:MM IST into a UTC datetime object."""
    if ':' not in time_str: time_str += ":00"
    full_str = f"{date_str} {time_str}"
    try:
        naive_dt = datetime.strptime(full_str, '%d/%m/%Y %H:%M') 
    except ValueError:
        raise ValueError("Invalid date or time format. Please use **DD/MM/YYYY HH:MM** (e.g., 25/12/2026 14:30)")
    
    localized_dt_ist = naive_dt.replace(tzinfo=IST_TIMEZONE)
    localized_dt_utc = localized_dt_ist.astimezone(timezone.utc)
    if localized_dt_utc <= datetime.now(timezone.utc):
        raise ValueError("The reminder time must be in the future.")
    return localized_dt_utc

# --- Core Reminder Setter Function ---
async def create_reminder(ctx, title: str, date_str: str, time_str: str, private: bool, recipient_id: int):
    try:
        # 1. Parse and validate time
        reminder_time_utc = parse_reminder_time(date_str, time_str)
    except ValueError as e:
        return await ctx.send(f"❌ Time Error: {e}")

    # 2. Store data
    reminder_id = str(datetime.now().timestamp())
    reminders_data[reminder_id] = {
        'user_id': str(ctx.author.id),
        'channel_id': str(ctx.channel.id),
        'title': title,
        'time_utc': reminder_time_utc.isoformat(),
        'recipient_id': str(recipient_id) # NEW: Store the recipient ID
    }
    save_data(reminders_data, REMINDERS_FILE)

    # 3. Create confirmation message
    confirmation_time_ist = reminder_time_utc.astimezone(IST_TIMEZONE).strftime('%A, %d %B at %I:%M %p IST')
    
    # Check if recipient is the author (standard reminder)
    is_self_reminder = recipient_id == ctx.author.id
    
    embed_title = "✅ Reminder Set!" if is_self_reminder else "✅ DM Scheduled!"
    
    embed = discord.Embed(
        title=embed_title,
        description=f"**Title:** {title}\n**Delivery:** {confirmation_time_ist}",
        color=discord.Color.green()
    )
    
    # Attempt to fetch recipient name for a clear confirmation message
    try:
        recipient = await bot.fetch_user(recipient_id)
        if not is_self_reminder:
             embed.add_field(name="Recipient", value=recipient.mention, inline=False)
        embed.set_footer(text=f"The message will be sent to {recipient.display_name}'s DM.")
    except discord.NotFound:
        # If user is not found, use the raw ID
        if not is_self_reminder:
             embed.add_field(name="Recipient ID", value=recipient_id, inline=False)
        embed.set_footer(text=f"The message will be sent to user ID {recipient_id}'s DM.")
    
    # 4. Send confirmation (public or private)
    if private:
        # FIX: Delete the command message for privacy
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            print("Warning: Bot lacks permissions to delete command messages.")
            
        await ctx.reply(embed=embed, ephemeral=True) # Sends the confirmation privately
    else:
        await ctx.send(f"🔔 Reminder set by {ctx.author.mention}!", embed=embed)
        
async def remove_winner_role_after_delay(guild_id, member_id, role_id, delay_seconds, channel_id):
    """Waits for the delay and then attempts to remove the Chatterbox role."""
    await asyncio.sleep(delay_seconds)
    guild = bot.get_guild(guild_id)
    member = guild.get_member(member_id) if guild else None
    role = guild.get_role(role_id) if guild else None
    if member and role in member.roles:
        try:
            await member.remove_roles(role, reason="Weekly Chatterbox Role Expiration.")
            channel = bot.get_channel(channel_id)
            if channel:
                await channel.send(f"👑 {member.mention}'s **{role.name}** role has expired. Congrats on your win last week!")
        except discord.Forbidden:
            print(f"Error removing role {role.name} from {member.name}: Forbidden.")
        except Exception as e:
            print(f"Error during role removal: {e}")

# --------------------------------------------------------
# 🕰️ BACKGROUND TASK: REMINDER CHECK (UPDATED)
# --------------------------------------------------------
@tasks.loop(minutes=1.0)
async def reminder_check_loop():
    """Checks for expired reminders every minute and delivers them via DM."""
    global reminders_data
    if not reminders_data: return
    now_utc = datetime.now(timezone.utc)
    reminders_to_remove = []

    for reminder_id, data in reminders_data.items():
        try:
            reminder_time = datetime.fromisoformat(data['time_utc'])
            if reminder_time <= now_utc:
                
                # Fetch Recipient (Can be any user ID)
                recipient = await bot.fetch_user(int(data['recipient_id']))
                
                # Fetch Sender (The person who set the reminder)
                sender = bot.get_user(int(data['user_id']))
                sender_name = sender.display_name if sender else "A previous user"
                
                reminder_embed = discord.Embed(
                    title="🔔 Scheduled Message/Reminder!",
                    description=f"**{data['title']}**",
                    color=discord.Color.red()
                )
                reminder_embed.add_field(
                    name="Scheduled Time", 
                    value=f"{reminder_time.astimezone(IST_TIMEZONE).strftime('%A, %d %B %Y at %I:%M %p IST')}"
                )
                reminder_embed.set_footer(text=f"Sent by {sender_name}")
                
                try:
                    # Send DM to the recipient
                    await recipient.send(embed=reminder_embed)
                except discord.Forbidden:
                    # If recipient DMs are disabled, send a notice to the original channel.
                    channel = bot.get_channel(int(data['channel_id']))
                    if channel:
                        await channel.send(f"⚠️ **DM Failed for {recipient.mention}:** The scheduled message titled '{data['title']}' could not be delivered because their DMs are likely disabled.")
                
                reminders_to_remove.append(reminder_id)
        except discord.NotFound:
            print(f"Recipient for reminder ID {reminder_id} not found. Removing reminder.")
            reminders_to_remove.append(reminder_id)
        except Exception as e:
            print(f"Error processing reminder ID {reminder_id}: {e}")
            reminders_to_remove.append(reminder_id) 

    for r_id in reminders_to_remove:
        if r_id in reminders_data: del reminders_data[r_id]
            
    if reminders_to_remove: save_data(reminders_data, REMINDERS_FILE)

@reminder_check_loop.error
async def reminder_check_loop_error(error):
    print(f"🚨 Reminder Check Loop Error: {error}")

# --------------------------------------------------------
# 🏆 BACKGROUND TASK: WEEKLY LEADERBOARD
# --------------------------------------------------------
@tasks.loop(time=time(hour=0, minute=0, tzinfo=IST_TIMEZONE))
async def weekly_leaderboard_announcement():
    """Runs every Sunday at 12:00 AM IST to assign 'The Chatterbox' role."""
    
    now_ist = datetime.now(IST_TIMEZONE)
    if now_ist.weekday() != 6: return 

    global message_counts
    for guild_id_str, counts in message_counts.items():
        guild = bot.get_guild(int(guild_id_str))
        if not guild: continue

        channel = discord.utils.get(guild.text_channels, name=LEADERBOARD_CHANNEL_NAME)
        if not channel: continue 
            
        user_counts = {k: v for k, v in counts.items() if guild.get_member(int(k)) and not guild.get_member(int(k)).bot}
        
        if not user_counts:
            await channel.send("The weekly message leaderboard reset has occurred, but no active user messages were found this week.")
            continue
            
        winner_id_str, max_messages = max(user_counts.items(), key=lambda item: item[1])
        winner = guild.get_member(int(winner_id_str))

        if not winner or max_messages == 0:
            await channel.send("The weekly message leaderboard reset has occurred, but no active winner was found this week.")
            continue

        winner_role = discord.utils.get(guild.roles, name=WINNER_ROLE_NAME)
        if not winner_role:
            try:
                winner_role = await guild.create_role(name=WINNER_ROLE_NAME, color=discord.Color.yellow(), reason="Weekly Activity Leaderboard Role")
                await channel.send(f"**ADMIN NOTE:** The required role **{WINNER_ROLE_NAME}** was created automatically. Please adjust its permissions/position.")
            except discord.Forbidden:
                await channel.send(f"❌ Cannot assign **{WINNER_ROLE_NAME}**. Bot lacks `manage_roles` permission or the role is too high.")
                continue

        for member in guild.members:
            if winner_role in member.roles and member.id != winner.id:
                try:
                    await member.remove_roles(winner_role, reason="Previous Chatterbox winner cleanup.")
                except discord.Forbidden:
                    pass

        try:
            await winner.add_roles(winner_role, reason="Weekly Activity Champion: Highest message count.")
            removal_delay = 60 * 60 * 24 * 7 
            bot.loop.create_task(
                remove_winner_role_after_delay(guild.id, winner.id, winner_role.id, removal_delay, channel.id)
            )

        except discord.Forbidden:
            await channel.send(f"❌ Failed to assign **{WINNER_ROLE_NAME}** to {winner.mention}. Check bot role hierarchy.")
            continue
        
        embed = discord.Embed(
            title=f"🏆 WEEKLY ACTIVITY CHAMPION! 🏆",
            description=f"Our chat king/queen for the week is...",
            color=discord.Color.gold()
        )
        embed.add_field(name=f"🥇 The Winner: {winner.display_name} 🥇", value=f"They sent a massive **{max_messages}** messages this week!", inline=False)
        embed.add_field(name=f"👑 Reward:", value=f"They have won the temporary custom role: **{WINNER_ROLE_NAME}**!", inline=False)
        embed.set_thumbnail(url=winner.display_avatar.url)
        embed.set_footer(text=f"Role will expire in 7 days. Counts reset for the next week! Start chatting!")
        await channel.send(f"🎉 **@everyone** 🎉", embed=embed)
        
        message_counts[guild_id_str] = {} 
        
    save_data(message_counts, MESSAGES_FILE)

@weekly_leaderboard_announcement.error
async def weekly_leaderboard_announcement_error(error):
    print(f"🚨 Weekly Leaderboard Task Error: {error}")

# --------------------------------------------------------
# 🤖 BOT EVENTS
# --------------------------------------------------------

# --- 1. THE CLASS (Place this first) ---
class RolePicker(ui.View):
    def __init__(self):
        super().__init__(timeout=None) # This makes the buttons last forever

    @ui.button(label="Male", style=ButtonStyle.blue, custom_id="role_male")
    async def male(self, interaction: Interaction, button: ui.Button):
        role = discord.utils.get(interaction.guild.roles, name="Male")
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message("Removed 'Male' role.", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message("Added 'Male' role!", ephemeral=True)

    @ui.button(label="Female", style=ButtonStyle.red, custom_id="role_female")
    async def female(self, interaction: Interaction, button: ui.Button):
        role = discord.utils.get(interaction.guild.roles, name="Female")
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message("Removed 'Female' role.", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message("Added 'Female' role!", ephemeral=True)

# --- 2. THE COMMAND (Place this right after the class) ---
@bot.command()
@commands.has_permissions(administrator=True)
async def setup_roles(ctx):
    """Admin only: Sends the menu for users to pick roles."""
    embed = discord.Embed(
        title="Select Your Gender Role", 
        description="Click the buttons below to toggle your roles.", 
        color=discord.Color.purple()
    )
    await ctx.send(embed=embed, view=RolePicker())
    
@bot.event
async def on_ready():
    bot.add_view(RolePicker())
    print(f'Bot is ready! Logged in as {bot.user}')
    await bot.change_presence(activity=discord.Game(name="+help | Gemini AI"))
    
    # NEW: Initialize aiohttp session for file downloads
    if bot.http_session is None:
        bot.http_session = aiohttp.ClientSession()

    # --- START TASK LOOPS ---
    if not reminder_check_loop.is_running():
        reminder_check_loop.start()
        
    # UNCOMMENT THE LINE BELOW WHEN YOU ARE READY TO START THE WEEKLY LEADERBOARD!
    # if not weekly_leaderboard_announcement.is_running():
    #     weekly_leaderboard_announcement.start

# Place this with your other Events
@bot.event
async def on_member_join(member):
    # Replace this number with your actual Welcome Channel ID
    WELCOME_CHANNEL_ID = 1455502594947551254 
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    
    if channel:
        embed = discord.Embed(
            title="Welcome to the Server! 🎉",
            description=f"Welcome {member.mention}! We're glad to have you here.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Member Count", value=f"You are our {len(member.guild.members)}th member!", inline=False)
        embed.set_footer(text=f"ID: {member.id}")
        
        await channel.send(content=f"Hey {member.mention}, welcome!", embed=embed)

# Place these in your Events section
@bot.event
async def on_message_delete(message):
    
    # GHOST PING CHANNEL ID (Replace with your private mod channel ID)
    GHOST_PING_LOG_ID = 1464667139414950040
    
    if message.author.bot or not message.mentions:
        return

    now = datetime.now(timezone.utc)
    # Only alert if deleted within 2 minutes of being sent
    if (now - message.created_at).total_seconds() > 120:
        return

    log_channel = bot.get_channel(GHOST_PING_LOG_ID)
    if log_channel:
        embed = discord.Embed(
            title="👻 Ghost Ping Detected!",
            color=discord.Color.red(),
            timestamp=now
        )
        embed.add_field(name="Author", value=f"{message.author.mention} ({message.author.id})", inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        
        pinged_users = ", ".join([user.mention for user in message.mentions])
        embed.add_field(name="Users Targeted", value=pinged_users, inline=False)
        
        if message.content:
            embed.add_field(name="Deleted Content", value=message.content, inline=False)

        await log_channel.send(embed=embed)

@bot.event
async def on_message_edit(before, after):
    GHOST_PING_LOG_ID = 1464667139414950040 # Use the same ID here
    
    # If the edit removed a mention
    if before.mentions and not after.mentions:
        if before.author.bot: return

        log_channel = bot.get_channel(GHOST_PING_LOG_ID)
        if log_channel:
            embed = discord.Embed(
                title="📝 Ghost Ping (Edited)",
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Author", value=before.author.mention, inline=True)
            embed.add_field(name="Channel", value=before.channel.mention, inline=True)
            
            pinged_users = ", ".join([user.mention for user in before.mentions])
            embed.add_field(name="Pings Removed", value=pinged_users, inline=False)
            embed.add_field(name="Original Content", value=before.content, inline=False)

            await log_channel.send(embed=embed)


@bot.event
async def on_message(message):
    if message.author == bot.user or message.guild is None:
        await bot.process_commands(message)
        return

    # 2. THE FILTER (Add this part!)
    content_lower = message.content.lower()
    if restricted_words: # Only check if the list isn't empty
        for word in restricted_words:
            if word in content_lower:
                await message.delete()
                await message.channel.send(f"🚫 {message.author.mention}, that word is not allowed here!", delete_after=5)
                return # Stop processing so it doesn't count as a message or trigger other commands
                
    # --- HIGHLIGHT CHECKER ---
    # We don't want to ping the person who actually wrote the message
    content = message.content.lower()
    
    for user_id, words in highlights.items():
        if int(user_id) == message.author.id:
            continue
            
        for word in words:
            if word in content:
                user = bot.get_user(int(user_id))
                if user:
                    try:
                        embed = discord.Embed(
                            title="📌 Highlight Triggered!",
                            description=f"The word **'{word}'** was mentioned in {message.channel.mention}.",
                            color=discord.Color.gold()
                        )
                        embed.add_field(name="Author", value=message.author.name, inline=True)
                        embed.add_field(name="Message", value=message.content, inline=False)
                        embed.add_field(name="Jump to Message", value=f"[Click Here]({message.jump_url})")
                        
                        await user.send(embed=embed)
                    except discord.Forbidden:
                        # This happens if the user's DMs are closed
                        pass
                        
    # --- 🛡️ SPAM PROTECTION FEATURE ---
    uid = message.author.id
    now = datetime.now(timezone.utc)
    data = spam_tracker[uid]

    # Reset strikes after 12 hours
    if data["last_strike_time"] and (now - data["last_strike_time"]).total_seconds() > 43200:
        data["strikes"] = 0

    # History tracking (10s window)
    data["messages"].append((message.content.lower(), now))
    data["messages"] = [m for m in data["messages"] if (now - m[1]).total_seconds() <= 10]

    # Detect 4 identical messages
    history = [m[0] for m in data["messages"]]
    if len(history) >= 4 and all(x == history[-1] for x in history[-4:]):
        data["strikes"] += 1
        data["last_strike_time"] = now
        data["messages"] = []
        
        s = data["strikes"]
        if s <= 2:
            await message.channel.send(f"⚠️ {message.author.mention}, don't repeat that! Warning {s}/3")
        elif s == 3:
            try: await message.author.send("🚨 Final Warning: One more spam and you get a 1-day timeout.")
            except: pass
            await message.channel.send(f"⚠️ {message.author.mention}, Final Warning! Check your DMs.")
        elif s >= 4:
            try:
                await message.author.timeout(timedelta(days=1), reason="Spamming")
                await message.channel.send(f"🔇 {message.author.mention} timed out for 1 day for spamming.")
                data["strikes"] = 0
            except: await message.channel.send("❌ Permission error: Can't timeout user.")

    user_id = str(message.author.id)
    if user_id in afk_users:
        del afk_users[user_id]
        save_data(afk_users, AFK_FILE)
        await message.channel.send(f"👋 Welcome back, {message.author.mention}! You're no longer AFK.", delete_after=5)

    # --- Weekly Message Tracking Logic ---
    if not message.author.bot: 
        guild_id = str(message.guild.id)
        user_id = str(message.author.id)
        if guild_id not in message_counts: message_counts[guild_id] = {}
        message_counts[guild_id][user_id] = message_counts[guild_id].get(user_id, 0) + 1
        save_data(message_counts, MESSAGES_FILE)
    
    # --- AFK Check Logic ---
    user_id = str(message.author.id)
    if user_id in afk_users:
        del afk_users[user_id]
        save_data(afk_users, AFK_FILE)
        await message.channel.send(f"👋 Welcome back, {message.author.mention}! You're no longer AFK.", delete_after=5)

    for mention in message.mentions:
        mention_id = str(mention.id)
        if mention_id in afk_users:
            data = afk_users[mention_id]
            reason = data['reason']
            try:
                afk_time = datetime.fromisoformat(data['time'].replace('Z', '+00:00'))
                delta = datetime.now(timezone.utc) - afk_time
                if delta.days > 0: time_ago = f"{delta.days} days ago"
                elif delta.seconds >= 3600: time_ago = f"{delta.seconds // 3600} hours ago"
                elif delta.seconds >= 60: time_ago = f"{delta.seconds // 60} minutes ago"
                else: time_ago = "just now"
            except ValueError:
                time_ago = "an unknown time ago" 
            
            await message.channel.send(f"😴 {mention.mention} is currently AFK ({time_ago}): **{reason}**")

    # --- Custom Responses (CONFIRMED PRESENT) ---
    content = message.content.lower()
    if "ashley" in content:
        await message.channel.send("You wrote the name of the pookiest member 😉")
    elif "swastik" in content:
        await message.channel.send("ye kon bhadu bkl haryanvi gendu ka naam hai 😡")

    await bot.process_commands(message)

# --------------------------------------------------------
# 📢 REMINDER COMMANDS
# --------------------------------------------------------

@bot.command()
async def rep(ctx, member: discord.Member):
    
    global reputation 
    if reputation is None:reputation = {}
    """Give a reputation point to a helpful user."""
    if member.id == ctx.author.id:
       return await ctx.send("You can't give yourself reputation! 💀")
    
    now = datetime.now()

    if ctx.author.id in rep_cooldowns:
        if now < rep_cooldowns[ctx.author.id] + timedelta(hours=1):
            return await ctx.send("⏳ You can only give rep once per hour!")

    mid = str(member.id)
    reputation[mid] = reputation.get(mid, 0) + 1
    rep_cooldowns[ctx.author.id] = now
    save_data(reputation, 'reputation.json')
    await ctx.send(f"⭐ {ctx.author.mention} gave a rep point to {member.mention}! (Total: {reputation[mid]})")

@bot.command()
async def profile(ctx, member: discord.Member = None):
    global reputation,message_counts
    if reputation is None:reputation = {}
    if message_counts is None:message_counts = {}
        
    """View server profile, reputation, and message count."""
    member = member or ctx.author
    mid = str(member.id)
    gid = str(ctx.guild.id)
    
    # Getting counts from your existing message_counts logic
    msgs = message_counts.get(gid, {}).get(mid, 0)
    reps = reputation.get(mid, 0)

    embed = discord.Embed(title=f"User Profile: {member.name}", color=member.color)
    embed.add_field(name="💬 Messages", value=f"`{msgs}`", inline=True)
    embed.add_field(name="⭐ Reputation", value=f"`{reps}`", inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)
    
@bot.command()
@commands.has_permissions(manage_guild=True)
async def restrict(ctx, word: str):
    global restricted_words
    if restricted_words is None:
        restricted_words = []
        
    word = word.lower()
    if word not in restricted_words:
        restricted_words.append(word)
        save_data(restricted_words, 'restricted_words.json')
        await ctx.send(f"🚫 Restricted: **{word}**")
    else:
        await ctx.send("Word is already restricted.")
        
@bot.command()
@commands.has_permissions(manage_guild=True)
async def unrestrict(ctx, word: str):
    """Remove a word from the blacklist."""
    word = word.lower()
    if word in restricted_words:
        restricted_words.remove(word)
        save_data(restricted_words, 'restricted_words.json')
        await ctx.send(f"✅ The word *'{word}'* has been unrestricted.")
    else:
        await ctx.send("That word isn't in the restriction list.")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def restrictedlist(ctx):
    """Show all currently banned words to moderators."""
    if not restricted_words:
        return await ctx.send("No words are currently restricted.")
    words = ", ".join([f"{w}" for w in restricted_words])
    await ctx.send(f"*Restricted Words:* {words}")
    
@bot.command(name="hl")
@commands.has_permissions(manage_messages=True)
async def add_highlight(ctx, *, word: str):
    """Adds a word to your DM highlight list (Mods only)."""
    word = word.lower()
    uid = str(ctx.author.id)
    
    if uid not in highlights:
        highlights[uid] = []
    
    if word in highlights[uid]:
        return await ctx.send(f"❌ You already have '{word}' highlighted!")
    
    highlights[uid].append(word)
    save_data(highlights, HIGHLIGHTS_FILE)
    await ctx.send(f"✅ I'll DM you whenever someone mentions **'{word}'**!")

@bot.command(name="unhl")
@commands.has_permissions(manage_messages=True)
async def remove_highlight(ctx, *, word: str):
    """Removes a word from your list (Mods only)."""
    word = word.lower()
    uid = str(ctx.author.id)
    
    if uid in highlights and word in highlights[uid]:
        highlights[uid].remove(word)
        save_data(highlights, HIGHLIGHTS_FILE)
        await ctx.send(f"🗑️ Removed **'{word}'** from your highlights.")
    else:
        await ctx.send(f"❌ You don't have '{word}' highlighted.")

@bot.command(name="listhl")
@commands.has_permissions(manage_messages=True)
async def list_highlights(ctx):
    """Shows all words you have highlighted (Mods only)."""
    uid = str(ctx.author.id)
    
    if uid not in highlights or not highlights[uid]:
        return await ctx.send("📝 You don't have any highlight words set.")
    
    # Format the list with numbers
    word_list = "\n".join([f"{i+1}. {word}" for i, word in enumerate(highlights[uid])])
    
    embed = discord.Embed(
        title="Your Highlighted Words",
        description=word_list,
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)
    
@bot.command()
@commands.has_permissions(manage_nicknames=True) # This ensures only Mods can use it
async def nick(ctx, member: discord.Member, *, new_nickname: str):
    """Changes the nickname of a member. Only for Moderators."""
    try:
        # Discord limit for nicknames is 32 characters
        if len(new_nickname) > 32:
            return await ctx.send("❌ That nickname is too long! (Max 32 chars)")

        old_name = member.display_name
        await member.edit(nick=new_nickname)
        
        embed = discord.Embed(
            title="Nickname Updated ✅",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="User", value=member.mention, inline=False)
        embed.add_field(name="Old Name", value=old_name, inline=True)
        embed.add_field(name="New Name", value=new_nickname, inline=True)
        embed.set_footer(text=f"Changed by {ctx.author.name}")
        
        await ctx.send(embed=embed)

    except discord.Forbidden:
        await ctx.send("❌ **Error:** I cannot change this user's name. They might have a higher role than me, or I'm missing the 'Manage Nicknames' permission.")
    except Exception as e:
        print(f"Nick Command Error: {e}")
        await ctx.send("❌ Something went wrong.")

# This block catches the error if a non-mod tries to use the command
@nick.error
async def nick_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(f"❌ {ctx.author.mention}, you need the **Manage Nicknames** permission to use this command!")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ **Usage:** `+nick @user New Name`")

@bot.command()
async def reset(ctx):
    """Clears your private AI chat history."""
    if ctx.author.id in user_chats:
        del user_chats[ctx.author.id]
        await ctx.send("✅ Memory cleared! Let's start a fresh conversation.")
    else:
        await ctx.send("We don't have an active chat session to reset.")
        
@bot.command(name='remind', usage='"<Title>" <DD/MM/YYYY> <HH:MM>', help="Sets a public reminder that will be delivered via DM to you.")
async def remind_public(ctx, title: str, date_str: str, time_str: str):
    """Sets a public reminder that will be delivered via DM to the author."""
    # Recipient is the author
    await create_reminder(ctx, title, date_str, time_str, private=False, recipient_id=ctx.author.id)

@bot.command(name='remindpvt', usage='"<Title>" <DD/MM/YYYY> <HH:MM>', help="Sets a private reminder (confirmation hidden) delivered via DM to you.")
async def remind_private(ctx, title: str, date_str: str, time_str: str):
    """Sets a private reminder that will be delivered via DM (only you see the confirmation)."""
    # Recipient is the author
    await create_reminder(ctx, title, date_str, time_str, private=True, recipient_id=ctx.author.id)

@bot.command(name='senddm', usage='<User ID/@mention> "<Title>" <DD/MM/YYYY> <HH:MM>', help="Schedules a message to be sent via DM to a specific user.")
async def send_scheduled_dm(ctx, recipient: discord.User, title: str, date_str: str, time_str: str):
    """Schedules a message to be sent via DM to a specific user (can be outside the server)."""
    if recipient.bot:
        return await ctx.send("❌ Cannot send scheduled DMs to other bots.")
    
    # Recipient is the specified user
    await create_reminder(ctx, title, date_str, time_str, private=False, recipient_id=recipient.id)


# --------------------------------------------------------
# 🏆 LEADERBOARD COMMAND 
# --------------------------------------------------------

@bot.command(aliases=['lb'], help="Displays the current top 10 message count rankings for the week.")
async def leaderboard(ctx):
    """Displays the current top 10 message count rankings for the week."""
    guild_id_str = str(ctx.guild.id)
    
    if guild_id_str not in message_counts or not message_counts[guild_id_str]:
        return await ctx.send("No messages have been tracked yet this week! Time to chat!")

    all_counts = message_counts[guild_id_str]
    sorted_list = sorted(all_counts.items(), key=itemgetter(1), reverse=True)
    
    leaderboard_text = ""
    trophies = {0: "🥇", 1: "🥈", 2: "🥉"} 
    
    for index, (user_id_str, count) in enumerate(sorted_list[:10]):
        member = ctx.guild.get_member(int(user_id_str))
        if member is None or member.bot: continue

        rank_display = trophies.get(index, f"#{index + 1}")
        leaderboard_text += f"{rank_display} **{member.display_name}**: `{count}` messages\n"

    now_ist = datetime.now(IST_TIMEZONE)
    days_until_sunday = (6 - now_ist.weekday() + 7) % 7
    if days_until_sunday == 0 and (now_ist.hour > 0 or now_ist.minute > 0): days_until_sunday = 7
    
    reset_date = (now_ist + timedelta(days=days_until_sunday)).replace(hour=0, minute=0, second=0, microsecond=0)
    time_remaining = reset_date - now_ist
    hours, remainder = divmod(time_remaining.total_seconds(), 3600)
    minutes, _ = divmod(remainder, 60)

    embed = discord.Embed(
        title="💬 Weekly Message Leaderboard 🏆",
        description="Top chatters of the week! Rankings reset every Sunday at 12:00 AM IST.",
        color=discord.Color.blue()
    )
    if leaderboard_text:
        embed.add_field(name="Current Top 10", value=leaderboard_text, inline=False)
    else:
         embed.add_field(name="Current Top 10", value="No valid users to display yet!", inline=False)
         
    embed.set_footer(text=f"Reset in: {int(hours)} hours and {int(minutes)} minutes.")
    await ctx.send(embed=embed)


# --------------------------------------------------------
# 🛡️ MODERATION COMMANDS (Assumed correct)
# --------------------------------------------------------
@bot.command()
@commands.has_permissions(kick_members=True)
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    warnings_data = load_data(WARNINGS_FILE)
    user_id = str(member.id)

    if user_id not in warnings_data:
        warnings_data[user_id] = []

    new_warn = {
        "reason": reason,
        "moderator_id": ctx.author.id,
        "moderator_name": ctx.author.name,
        "date": ctx.message.created_at.strftime("%Y-%m-%d %H:%M")
    }

    warnings_data[user_id].append(new_warn)
    save_data(warnings_data, WARNINGS_FILE) # CRITICAL: This saves it to the file
    
    await ctx.send(f"⚠️ **{member.mention}** has been warned for: {reason}")
    
@bot.command()
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def timeout(ctx, member: discord.Member, duration_minutes: int, *, reason: str = "No reason provided"):
    if ctx.author.top_role <= member.top_role and ctx.guild.owner_id != ctx.author.id:
        await ctx.send("You cannot timeout someone with a higher or equal role.")
        return
        
    duration = timedelta(minutes=duration_minutes)
    if duration.total_seconds() < 60 or duration.days > 28:
        await ctx.send("Timeout duration must be between 1 minute and 28 days.")
        return

    await member.timeout(discord.utils.utcnow() + duration, reason=reason)
    await ctx.send(f"✅ {member.mention} has been timed out for **{duration_minutes} minutes**.")
    await send_mod_log(ctx.guild, "Member Timed Out", 
                       f"**User:** {member.mention}\n**Duration:** {duration_minutes} minutes\n**Reason:** {reason}", 
                       ctx.author)

@bot.command()
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    if ctx.author.top_role <= member.top_role and ctx.guild.owner_id != ctx.author.id:
        await ctx.send("You cannot ban someone with a higher or equal role.")
        return
        
    try:
        await member.ban(reason=reason)
        await ctx.send(f"🔨 {member.mention} has been banned.")
        await send_mod_log(ctx.guild, "Member Banned", 
                           f"**User:** {member.mention} ({member.id})\n**Reason:** {reason}", 
                           ctx.author)
    except discord.Forbidden:
        await ctx.send("I do not have permission to ban that member.")

@bot.command()
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def unban(ctx, user_id_or_name: str):
    try:
        if user_id_or_name.isdigit():
            user_id = int(user_id_or_name)
            user = discord.Object(id=user_id)
            await ctx.guild.unban(user)
            await ctx.send(f"✅ User with ID `{user_id}` has been unbanned.")
            await send_mod_log(ctx.guild, "Member Unbanned", 
                               f"**User ID:** {user_id}\nUnbanned by: {ctx.author.mention}", 
                               ctx.author)
            return
            
        bans = [entry async for entry in ctx.guild.bans()]
        for ban_entry in bans:
            user = ban_entry.user
            if user.name.lower() == user_id_or_name.lower() or str(user).lower() == user_id_or_name.lower():
                await ctx.guild.unban(user)
                await ctx.send(f"✅ {user} has been unbanned.")
                await send_mod_log(ctx.guild, "Member Unbanned", 
                                   f"**User:** {user.name} ({user.id})\nUnbanned by: {ctx.author.mention}", 
                                   ctx.author)
                return
                
        await ctx.send("User not found in ban list (check ID or full tag).")
        
    except discord.Forbidden:
        await ctx.send("I do not have permission to unban this user.")
    except discord.NotFound:
        await ctx.send("This user is not banned.")

@bot.command()
@commands.has_permissions(kick_members=True)
@commands.bot_has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    if ctx.author.top_role <= member.top_role and ctx.guild.owner_id != ctx.author.id:
        await ctx.send("You can't kick someone with a higher or equal role!")
        return
    try:
        await member.kick(reason=reason)
        await ctx.send(f"👢 {member.mention} has been kicked. Reason: {reason}")
        await send_mod_log(ctx.guild, "Member Kicked", 
                           f"**User:** {member.mention}\n**Reason:** {reason}", 
                           ctx.author)
    except discord.Forbidden:
        await ctx.send("I do not have permission to kick this member.")

@bot.command(help="Deletes a specified number of messages (max 100).")
@commands.has_permissions(manage_messages=True)
async def purge(ctx, amount: int):
    if amount < 1 or amount > 100:
        return await ctx.send("❌ Please specify an amount between 1 and 100.")
    
    try:
        deleted = await ctx.channel.purge(limit=amount + 1) # +1 to delete the command message itself
        # Send ephemeral message if possible, otherwise delete after a few seconds
        await ctx.send(f"🗑️ Deleted **{len(deleted) - 1}** messages.", delete_after=5)
        await send_mod_log(ctx.guild, "Messages Purged", f"Channel: {ctx.channel.mention}\nAmount: {len(deleted) - 1}\nModerator: {ctx.author.mention}", ctx.author)
    except discord.Forbidden:
        await ctx.send("❌ I do not have permission to delete messages.")
    except Exception as e:
        await ctx.send(f"❌ An error occurred: {e}")
        
@bot.command(help="Prevents the @everyone role from sending messages.")
@commands.has_permissions(manage_channels=True)
async def lock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send("🔒 Channel locked.")
    await send_mod_log(ctx.guild, "Channel Locked", f"Channel: {ctx.channel.mention}", ctx.author)

@bot.command(help="Allows the @everyone role to send messages.")
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
    # This specifically sets it back to 'None' (default) or 'True' so mods/users can speak
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send("🔓 Channel unlocked.")
    await send_mod_log(ctx.guild, "Channel Unlocked", f"Channel: {ctx.channel.mention}", ctx.author)

# --- WARNING SYSTEM COMMANDS ---

@bot.command(name="warnings", help="View a member's warnings.")
@commands.has_permissions(kick_members=True)
async def view_warnings(ctx, member: discord.Member):
    warnings_data = load_data(WARNINGS_FILE)
    user_id = str(member.id)

    # Check if user exists in the data and has a list of warns
    if user_id not in warnings_data or not isinstance(warnings_data[user_id], list) or len(warnings_data[user_id]) == 0:
        return await ctx.send(f"✅ **{member.display_name}** has a clean record.")

    embed = discord.Embed(
        title=f"⚠️ Warning History: {member.display_name}",
        color=discord.Color.orange()
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    # Correctly looping through the LIST of warnings
    for i, warn in enumerate(warnings_data[user_id], 1):
        # We use .get() to prevent crashes if a specific field is missing
        reason = warn.get('reason', 'No reason provided')
        mod_name = warn.get('moderator_name', 'Unknown Admin')
        date = warn.get('date', 'Unknown Date')
        
        embed.add_field(
            name=f"Warning #{i}",
            value=f"**Reason:** {reason}\n**By:** {mod_name}\n**Date:** {date}",
            inline=False
        )

    await ctx.send(embed=embed)

@bot.command(name="delwarn", help="Delete a specific warning by ID or 'all'. Usage: +delwarn @user 1")
@commands.has_permissions(manage_messages=True)
async def delete_warning(ctx, member: discord.Member, warn_id: str):
    warnings_data = load_data(WARNINGS_FILE)
    user_id = str(member.id)

    if user_id not in warnings_data or not warnings_data[user_id]:
        return await ctx.send("This user has no warnings to delete.")

    # Option to delete ALL warnings
    if warn_id.lower() == "all":
        warnings_data[user_id] = []
        save_data(warnings_data, WARNINGS_FILE)
        return await ctx.send(f"🗑️ Cleared all warnings for **{member.display_name}**.")

    # Delete specific warning by ID
    try:
        idx = int(warn_id) - 1  # Convert 1-based ID to 0-based index
        if 0 <= idx < len(warnings_data[user_id]):
            removed = warnings_data[user_id].pop(idx)
            save_data(warnings_data, WARNINGS_FILE)
            await ctx.send(f"✅ Deleted Warning #{warn_id} ({removed['reason']}) for {member.mention}.")
        else:
            await ctx.send(f"❌ Invalid ID. Use `+warnings @user` to see valid IDs.")
    except ValueError:
        await ctx.send("❌ Please provide a valid number ID or type `all`.")        

#-------BIRTHDAY WISH------
@bot.command(name='wish', help="Wish someone a birthday and give them a temporary role. (Mods only)")
@commands.has_permissions(manage_roles=True)
async def wish(ctx, member: discord.Member):
    # Role Names
    MALE_ROLE = "Male"
    FEMALE_ROLE = "Female"
    BDAY_BOY = "Birthday Boy"
    BDAY_GIRL = "Birthday Girl"

    # Determine which birthday role to give
    role_to_give_name = BDAY_BOY if any(r.name == MALE_ROLE for r in member.roles) else BDAY_GIRL
    
    # Find or create the role
    bday_role = discord.utils.get(ctx.guild.roles, name=role_to_give_name)
    if not bday_role:
        bday_role = await ctx.guild.create_role(name=role_to_give_name, color=discord.Color.magenta())

    await member.add_roles(bday_role)

    # Custom Birthday Message
    embed = discord.Embed(
        title="🎉 Happy Birthday! 🎉",
        description=f"Everyone join us in wishing {member.mention} a very Happy Birthday! 🎂✨\n\nYou've been granted the **{role_to_give_name}** role for 24 hours!",
        color=discord.Color.random()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    
    await ctx.send(content=f"🎈 {member.mention} 🎈", embed=embed)

    # Task to remove role after 24 hours
    async def remove_bday_role():
        await asyncio.sleep(86400) # 24 hours
        if bday_role in member.roles:
            await member.remove_roles(bday_role)
            print(f"Removed birthday role from {member.name}")

    bot.loop.create_task(remove_bday_role())
    
# --------------------------------------------------------
# 🔨 UTILITY COMMANDS (Assumed correct)
# --------------------------------------------------------

@bot.command(help="Checks the bot's latency to the server.")
async def ping(ctx):
    await ctx.send(f'🏓 Pong! Latency is **{round(bot.latency * 1000)}ms**.')

@bot.command(help="Sets your status to AFK.")
async def afk(ctx, *, reason: str = "No reason provided"):
    user_id = str(ctx.author.id)
    afk_users[user_id] = {
        'reason': reason,
        'time': datetime.now(timezone.utc).isoformat()
    }
    save_data(afk_users, AFK_FILE)
    await ctx.send(f"😴 {ctx.author.mention} is now AFK: **{reason}**.")

@bot.command(help="Shows the avatar of a user.")
async def av(ctx, member: Optional[discord.Member]):
    member = member or ctx.author
    embed = discord.Embed(title=f"Avatar for {member.display_name}", color=discord.Color.blue())
    embed.set_image(url=member.display_avatar.url)
    embed.set_footer(text=f"Requested by {ctx.author.display_name}")
    await ctx.send(embed=embed)

@bot.command(help="Shows info about a user.")
async def userinfo(ctx, member: Optional[discord.Member]):
    member = member or ctx.author
    
    embed = discord.Embed(
        title=f"User Info: {member.display_name}",
        description=member.mention,
        color=member.color
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    # Calculate join time
    join_delta = datetime.now(timezone.utc) - member.joined_at.replace(tzinfo=timezone.utc)
    join_days = join_delta.days

    # Calculate creation time
    creation_delta = datetime.now(timezone.utc) - member.created_at.replace(tzinfo=timezone.utc)
    creation_days = creation_days.days

    embed.add_field(name="ID", value=member.id, inline=False)
    embed.add_field(name="Joined Server", value=f"{member.joined_at.strftime('%Y-%m-%d')} ({join_days} days ago)", inline=False)
    embed.add_field(name="Account Created", value=f"{member.created_at.strftime('%Y-%m-%d')} ({creation_days} days ago)", inline=False)
    
    roles = [role.name for role in member.roles if role.name != '@everyone']
    if roles:
        embed.add_field(name=f"Roles ({len(roles)})", value=", ".join(roles), inline=False)
    
    await ctx.send(embed=embed)

@bot.command(help="Makes the bot say a message and deletes the original command.")
@commands.has_permissions(manage_messages=True)
async def say(ctx, *, message: str):
    await ctx.message.delete()
    await ctx.send(message)

@bot.command()
async def online(ctx):
    if ctx.author.name != "kanjuuubarfii":
        return await ctx.send("❌ Only **kanjuuubarfii** can do this!")
    # Force reset and set to Green
    await bot.change_presence(status=discord.Status.online, activity=discord.Game(name="Ready!"))
    await ctx.send("🟢 Status changed to **Online**.")

@bot.command()
async def dnd(ctx):
    if ctx.author.name != "kanjuuubarfii":
        return await ctx.send("❌ Only **kanjuuubarfii** can do this!")
    # Force reset and set to Red
    activity = discord.Activity(type=discord.ActivityType.watching, name="the server...")
    await bot.change_presence(status=discord.Status.do_not_disturb, activity=activity)
    await ctx.send("🔴 Status changed to **Do Not Disturb**.")

@bot.command()
async def idle(ctx):
    if ctx.author.name != "kanjuuubarfii":
        return await ctx.send("❌ Only **kanjuuubarfii** can do this!")
    # Force reset and set to Half-Moon
    activity = discord.Activity(type=discord.ActivityType.listening, name="to music")
    await bot.change_presence(status=discord.Status.idle, activity=activity)
    await ctx.send("🌙 Status changed to **Idle**.")
    
@bot.command(name="afkclear")
@commands.has_permissions(manage_messages=True)
async def afk_clear(ctx, member: discord.Member):
    # Assuming your AFK data is stored in a dictionary called 'afk_users'
    # or loaded via load_data(AFK_FILE)
    afk_data = load_data(AFK_FILE) 
    user_id = str(member.id)

    if user_id in afk_data:
        del afk_data[user_id]
        save_data(afk_data, AFK_FILE)
        await ctx.send(f"✅ AFK status for {member.display_name} has been cleared by a moderator.")
    else:
        await ctx.send(f"❌ {member.display_name} is not currently AFK.")
        
#------Banner------

@bot.command(name="banner", help="Get a user's profile banner.")
async def banner(ctx, member: discord.Member = None):
    # If no member is mentioned, check the author
    member = member or ctx.author
    
    # We must FETCH the user from the API to see the banner
    user = await bot.fetch_user(member.id)
    
    if user.banner:
        banner_url = user.banner.url
        embed = discord.Embed(title=f"🖼️ {member.display_name}'s Banner", color=member.color)
        embed.set_image(url=banner_url)
        await ctx.send(embed=embed)
    else:
        # If they don't have a banner image, they might have an accent color
        if user.accent_color:
            await ctx.send(f"❌ {member.display_name} doesn't have a banner image, but their profile accent color is `{user.accent_color}`.")
        else:
            await ctx.send(f"❌ {member.display_name} does not have a banner.")

# --- Scheduled Command ---
@bot.command()
@commands.has_permissions(manage_messages=True)
async def schedule(ctx, movie: str, date: str, time: str):
    """Schedules an announcement for a movie or event. Use MM/DD/YYYY HH:MM."""
    try:
        scheduled_datetime_naive = datetime.strptime(f"{date} {time}", "%m/%d/%Y %H:%M")
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        scheduled_datetime_aware = scheduled_datetime_naive.replace(tzinfo=ist_tz) 
        scheduled_utc = scheduled_datetime_aware.astimezone(timezone.utc)
        now_aware = datetime.now(timezone.utc)
        delay = (scheduled_utc - now_aware).total_seconds()
        
        if delay <= 0:
            await ctx.send("The scheduled time is in the past. Please choose a future time.")
            return
        
        td = scheduled_utc - now_aware
        total_minutes = td.seconds // 60
        hours = total_minutes // 60
        minutes = total_minutes % 60

        await ctx.send(f"✅ Scheduled movie announcement for **'{movie}'** on **{date} at {time} IST** (in about {hours} hours and {minutes} minutes).")
        await send_mod_log(ctx.guild, "Movie Scheduled", 
                           f"{ctx.author.mention} scheduled '{movie}' for {date} {time} IST.", 
                           ctx.author)
                            
        await asyncio.sleep(delay)
        
        channel = ctx.channel
        await channel.send(f"@everyone 🍿 **Movie Time!** 🎬 **'{movie}'** is starting now! Grab your popcorn!")
        
    except ValueError:
        await ctx.send("⚠️ Invalid date or time format. Use **MM/DD/YYYY** for date and **HH:MM** for time (24-hour, e.g., 21:30).")

# --------------------------------------------------------
# 🧠 GEMINI AI COMMANDS
# --------------------------------------------------------
@bot.command()
async def rate(ctx, member: discord.Member = None):
    """Rates a member's avatar using Gemini's vision capabilities."""
    if client is None:
        await ctx.send("Sorry, the AI system is not available.")
        return

    member = member or ctx.author
    await ctx.send(f"🔍 Analyzing {member.display_name}'s avatar... hang tight!")

    avatar_url = member.display_avatar.url
    
    try:
        # Use a fresh session to avoid the 'Internal Session' crash
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url) as resp:
                if resp.status != 200:
                    await ctx.send(f"Could not download the avatar (Status: {resp.status}).")
                    return
                image_data = await resp.read()

        image_part = types.Part.from_bytes(
            data=image_data,
            mime_type='image/png'  
        )
        
        prompt_text = (
            "Analyze the provided image, which is a Discord profile picture (avatar). "
            "Identify the subject (e.g., human portrait, cartoon, meme). "
            "Give it a rating out of 5 stars based on creativity and appeal. "
            "Format your response strictly with: **Rating**, **Description**, and **Suggestion**."
        )

        config = types.GenerateContentConfig(safety_settings=SAFETY_SETTINGS)
        
        # FIXED MODEL NAME TO 2.0
        response = await asyncio.to_thread(
            client.models.generate_content,
            model='gemini-2.0-flash', 
            contents=[prompt_text, image_part],
            config=config 
        )
        
        ai_response = response.text
        
        # --- Embed Formatting ---
        embed = discord.Embed(
            title=f"⭐ AI Avatar Analysis for {member.display_name}",
            color=discord.Color.gold()
        )
        
        # Regex to pull out the sections you requested
        rating_match = re.search(r'\*\*Rating\*\*(.*?)(\*\*Description\*\*|\Z)', ai_response, re.DOTALL | re.IGNORECASE)
        desc_match = re.search(r'\*\*Description\*\*(.*?)(\*\*Suggestion\*\*|\Z)', ai_response, re.DOTALL | re.IGNORECASE)
        suggest_match = re.search(r'\*\*Suggestion\*\*(.*?)(\Z)', ai_response, re.DOTALL | re.IGNORECASE)

        if rating_match:
            embed.add_field(name="Rating 🌟", value=rating_match.group(1).strip(), inline=False)
        if desc_match:
            embed.add_field(name="Description 🧐", value=desc_match.group(1).strip(), inline=False)
        if suggest_match:
            embed.add_field(name="Suggestion 💡", value=suggest_match.group(1).strip(), inline=False)
        
        if not any([rating_match, desc_match, suggest_match]):
             embed.description = ai_response[:2000]
             
        embed.set_thumbnail(url=avatar_url)
        embed.set_footer(text="Powered by Google Gemini")

        await ctx.send(embed=embed)

    except Exception as e:
        print(f"Gemini Rate Command Error: {e}")
        await ctx.send("💢 My AI brain stalled out. Try again in a few seconds!")
        
# --------------------------------------------------------
# 🧠 GEMINI CHAT COMMAND
# --------------------------------------------------------
@bot.command()
async def talk(ctx, *, prompt: str):
    """Allows the user to chat with the Gemini model. Sends full response by splitting it."""
    if chat is None:
        await ctx.send("Sorry, the AI chat system is currently unavailable (API key issue).")
        return

    is_deferred = False
    
    # We leave the deferral logic in +talk in case the user later adds slash command support
    try:
        await ctx.defer() 
        is_deferred = True
    except AttributeError:
        await ctx.send("... Thinking ...")

    try:
        response = await asyncio.to_thread(chat.send_message, prompt) 
        response_text = response.text
        message_chunks = split_message_chunks(response_text)
        
        for chunk in message_chunks:
            if is_deferred and hasattr(ctx, 'followup'):
                await ctx.followup.send(chunk)
                is_deferred = False 
            else:
                await ctx.send(chunk)

    except Exception as e:
        print(f"Gemini API Error in +talk: {e}")
        error_message = "I hit an error trying to process that. Please try again later."
        
        if is_deferred and hasattr(ctx, 'followup'):
            try:
                await ctx.followup.send(error_message)
            except Exception:
                await ctx.send(error_message)
        else:
            await ctx.send(error_message)


# --------------------------------------------------------
# 🎨 CUSTOM INTERACTIVE HELP COMMAND (Assumed correct)
# --------------------------------------------------------
class HelpView(ui.View):
    def __init__(self, bot, author):
        super().__init__(timeout=60)
        self.bot = bot
        self.author = author
        self.current_page = 1
        # Make sure this list matches the function names below exactly
        self.pages = [
            self.get_moderation_page,
            self.get_utility_page,
            self.get_ai_page,
            self.get_engagement_page,
            self.get_owner_page
        ]

    def create_page(self, page_num):
        embed = discord.Embed(color=discord.Color.blue())
        embed.set_footer(text=f"Page {page_num} of {len(self.pages)} | Requested by {self.author.name}")
        return self.pages[page_num - 1](embed)

    def get_moderation_page(self, embed):
        embed.title = "🛡️ Moderation Commands"
        embed.description = "Maintain order in the server."
        embed.add_field(name="`+warn` / `+warnings` / `+delwarn`", value="Manage user warnings.", inline=False)
        embed.add_field(name="`+lock` / `+unlock`", value="Manage channel talking permissions.", inline=False)
        embed.add_field(name="`+kick` / `+ban` / `+purge`", value="Standard mod actions.", inline=False)
        return embed

    def get_utility_page(self, embed):
        embed.title = "🛠️ Utility & General"
        embed.description = "Useful tools and profile info."
        embed.add_field(name="`+banner [user]`", value="Extract a user's profile banner.", inline=False)
        embed.add_field(name="`+av [user]`", value="Show a user's avatar.", inline=False)
        embed.add_field(name="`+afk` / `+afkclear`", value="Manage AFK status.", inline=False)
        return embed

    def get_ai_page(self, embed):
        embed.title = "🧠 Gemini AI Commands"
        embed.description = "AI features powered by Gemini."
        embed.add_field(name="`+talk <query>`", value="Chat with the AI.", inline=False)
        embed.add_field(name="`+rate [image]`", value="AI analysis of images/avatars.", inline=False)
        return embed

    def get_engagement_page(self, embed):
        embed.title = "🏆 Engagement & Fun"
        embed.description = "Leaderboards and celebrations."
        embed.add_field(name="`+leaderboard`", value="Top message senders.", inline=False)
        embed.add_field(name="`+wish <user>`", value="Birthday wishes and roles.", inline=False)
        return embed

    def get_owner_page(self, embed):
        embed.title = "👑 Owner Commands"
        embed.description = "Exclusive for **kanjuuubarfii**."
        embed.add_field(name="`+online` / `+idle` / `+dnd`", value="Change bot's status icon.", inline=False)
        return embed

    @ui.button(label="<", style=discord.ButtonStyle.primary)
    async def prev(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("This isn't your menu!", ephemeral=True)
        self.current_page = max(1, self.current_page - 1)
        await interaction.response.edit_message(embed=self.create_page(self.current_page), view=self)

    @ui.button(label=">", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("This isn't your menu!", ephemeral=True)
        self.current_page = min(len(self.pages), self.current_page + 1)
        await interaction.response.edit_message(embed=self.create_page(self.current_page), view=self)

@bot.command()
async def help(ctx):
    """Displays the interactive, multi-page help guide."""
    view = HelpView(bot, ctx.author)
    embed = view.create_page(1)
    view.message = await ctx.send(embed=embed, view=view)


# --------------------------------------------------------
# ❌ ERROR HANDLING (Assumed correct)
# --------------------------------------------------------

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return 
    
    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send(f"❌ **Missing Argument:** You are missing a required argument for this command. Usage: `+{ctx.command.name} {ctx.command.usage}`", delete_after=15)
        
    if isinstance(error, commands.BadArgument):
        # Specific handler for the new command to clarify User ID vs. Member mention
        if ctx.command.name == 'senddm' and isinstance(error, commands.UserNotFound):
            return await ctx.send("❌ **Recipient Error:** Could not find that user. Please ensure you are mentioning a user or providing a valid User ID.", delete_after=15)
            
        return await ctx.send(f"❌ **Invalid Argument:** Please check the type of argument you provided (e.g., mention a user, use an integer, use correct date format). Usage: `+{ctx.command.name} {ctx.command.usage}`", delete_after=15)

    if isinstance(error, commands.MissingPermissions):
        permission_list = [p.replace('_', ' ').title() for p in error.missing_permissions]
        return await ctx.send(f"❌ **Permission Denied:** You need the following permission(s) to use this: `{', '.join(permission_list)}`", delete_after=15)

    if isinstance(error, commands.BotMissingPermissions):
        permission_list = [p.replace('_', ' ').title() for p in error.missing_permissions]
        return await ctx.send(f"❌ **Bot Permission Error:** I need the following permission(s) to execute this: `{', '.join(permission_list)}`")

    if isinstance(error, commands.CommandInvokeError):
        print(f"🚨 Unhandled CommandInvokeError in command {ctx.command}: {error.original}")
        return await ctx.send(f"❌ An internal error occurred while running this command. The developer has been notified (Error type: {type(error.original).__name__}).", delete_after=15)


    print(f"Ignoring unhandled exception in command {ctx.command}: {error}")

# --- BOT RUNNER ---
try:
    TOKEN = os.getenv("DISCORD_TOKEN")
    bot.run(TOKEN)
except discord.errors.LoginFailure:
    print("\n\nFATAL ERROR: Improper token has been passed. Check your TOKEN variable.")
except Exception as e:

    print(f"\n\nAn unexpected error occurred: {e}")

























































































