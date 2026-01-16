"""
Combined Discord Bot - Part 1: Setup & Config with PostgreSQL
Yo this is gonna be epic! Let's build this thing 🚀
Using PostgreSQL so data actually saves on Render!
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import Button, View, Modal, TextInput, Select
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
import json
import os
from typing import Optional, Set, Dict, List, Tuple
import re
from dotenv import load_dotenv
import logging
import psycopg2
from psycopg2.extras import Json
from urllib.parse import urlparse

load_dotenv()

# logging setup
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

class Config:
    """all the bot settings in one place"""
    OWNER_ID = 1029438856069656576
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    DATABASE_URL = os.getenv('DATABASE_URL')  # Render provides this
    PREFIX = '+'
    PORT = int(os.getenv('PORT', 8080))
    STAFF_ROLE_ID = 1432081794647199895
    
    # spam stuff
    SPAM_THRESHOLD = 7
    SPAM_TIMEFRAME = 4
    SPAM_TIMEOUTS = {1: 5, 2: 15, 3: 30, 4: 60, 5: 180}
    
    # raid protection 
    RAID_JOIN_THRESHOLD = 10
    RAID_JOIN_TIMEFRAME = 10
    ACCOUNT_AGE_MINIMUM = 7
    
    # bad words filter
    PROFANITY_TIMEOUT = 10
    BANNED_WORDS = ['nigger', 'nigga', 'n1gger', 'n1gga', 'faggot', 'f4ggot']
    BANNED_PATTERNS = [r'n[i1!]gg[ae]r', r'f[a4@]gg[o0]t']
    
    # mention/link limits
    MENTION_LIMIT = 5
    MENTION_TIMEOUT = 15
    LINK_LIMIT = 3
    LINK_TIMEFRAME = 10
    
    # anti-nuke thresholds
    CHANNEL_DELETE_THRESHOLD = 3
    CHANNEL_DELETE_TIMEFRAME = 30
    ROLE_DELETE_THRESHOLD = 3
    ROLE_DELETE_TIMEFRAME = 30
    BAN_THRESHOLD = 3
    BAN_TIMEFRAME = 30
    KICK_THRESHOLD = 5
    KICK_TIMEFRAME = 60
    
    # dangerous perms to watch
    DANGEROUS_PERMISSIONS = [
        'administrator',
        'kick_members',
        'ban_members',
        'manage_channels',
        'manage_guild',
        'manage_roles',
        'manage_webhooks',
        'manage_messages',
        'mention_everyone'
    ]

class Database:
    """handles all database stuff with PostgreSQL"""
    
    def __init__(self):
        self.conn = None
        self.connect()
        self.create_tables()
    
    def connect(self):
        """connect to postgres"""
        try:
            if Config.DATABASE_URL:
                # parse the database url
                result = urlparse(Config.DATABASE_URL)
                self.conn = psycopg2.connect(
                    database=result.path[1:],
                    user=result.username,
                    password=result.password,
                    host=result.hostname,
                    port=result.port
                )
                logging.info("connected to postgres database!")
            else:
                logging.warning("no database url found, using fallback")
        except Exception as e:
            logging.error(f"database connection failed: {e}")
    
    def create_tables(self):
        """create all the tables we need"""
        if not self.conn:
            return
        
        try:
            cur = self.conn.cursor()
            
            # settings table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                       guild_id BIGINT PRIMARY KEY,
                       log_channel_id BIGINT,
                       verified_role_id BIGINT,
                       unverified_role_id BIGINT,
                       verification_channel_id BIGINT,
                       staff_role_id BIGINT,
                       automod_enabled BOOLEAN DEFAULT TRUE,
                       anti_raid_enabled BOOLEAN DEFAULT TRUE,
                       anti_nuke_enabled BOOLEAN DEFAULT TRUE,
                       welcome_channel_id BIGINT,
                       leave_channel_id BIGINT,
                       welcome_message TEXT,
                       leave_message TEXT,
                       invite_tracking_enabled BOOLEAN DEFAULT FALSE,
                       invite_tracker_channel_id BIGINT
                   )
               """)


            
            # whitelist table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS whitelist (
                    user_id BIGINT PRIMARY KEY
                )
            """)
            
            # blacklist table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS blacklist (
                    user_id BIGINT PRIMARY KEY
                )
            """)
            
            # violations table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS violations (
                    user_id BIGINT PRIMARY KEY,
                    count INTEGER DEFAULT 0
                )
            """)
            
            # warnings table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS warnings (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    reason TEXT,
                    moderator_id BIGINT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # tickets table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    channel_id BIGINT PRIMARY KEY,
                    guild_id BIGINT,
                    user_id BIGINT,
                    ticket_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    claimed_by BIGINT,
                    ticket_data JSONB
                )
            """)
            
            # ticket roles table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ticket_roles (
                    guild_id BIGINT,
                    ticket_type TEXT,
                    role_id BIGINT,
                    PRIMARY KEY (guild_id, ticket_type)
                )
            """)
            
            # invites table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS invites (
                    guild_id BIGINT,
                    code TEXT,
                    inviter_id BIGINT,
                    uses INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, code)
                )
            """)
            
            # invite joins table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS invite_joins (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    user_id BIGINT,
                    inviter_id BIGINT,
                    invite_code TEXT,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            self.conn.commit()
            cur.close()
            logging.info("database tables created successfully")
        except Exception as e:
            logging.error(f"failed to create tables: {e}")
    
    def execute(self, query, params=None, fetch=False):
        """run a query"""
        if not self.conn:
            return None
        
        try:
            cur = self.conn.cursor()
            cur.execute(query, params)
            
            if fetch:
                result = cur.fetchall()
                cur.close()
                return result
            else:
                self.conn.commit()
                cur.close()
                return True
        except Exception as e:
            logging.error(f"query failed: {e}")
            self.conn.rollback()
            return None

class DataManager:
    """handles all the data stuff with postgres"""
    
    def __init__(self):
        self.db = Database()
        
        # in-memory cache for faster access
        self.whitelist: Set[int] = set()
        self.blacklist: Set[int] = set()
        self.user_violations: Dict[int, int] = defaultdict(int)
        self.message_history: Dict[int, List[float]] = defaultdict(list)
        self.link_history: Dict[int, List[float]] = defaultdict(list)
        self.action_history: Dict[str, List[Dict]] = defaultdict(list)
        
        # load from db
        self.load_whitelist()
        self.load_blacklist()
        self.load_violations()
    
    def load_whitelist(self):
        """load whitelist from db"""
        result = self.db.execute("SELECT user_id FROM whitelist", fetch=True)
        if result:
            self.whitelist = {row[0] for row in result}
    
    def load_blacklist(self):
        """load blacklist from db"""
        result = self.db.execute("SELECT user_id FROM blacklist", fetch=True)
        if result:
            self.blacklist = {row[0] for row in result}
    
    def load_violations(self):
        """load violations from db"""
        result = self.db.execute("SELECT user_id, count FROM violations", fetch=True)
        if result:
            self.user_violations = defaultdict(int, {row[0]: row[1] for row in result})
    
    # whitelist stuff
    def add_to_whitelist(self, user_id: int):
        self.whitelist.add(user_id)
        self.blacklist.discard(user_id)
        self.db.execute("INSERT INTO whitelist (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
        self.db.execute("DELETE FROM blacklist WHERE user_id = %s", (user_id,))
    
    def remove_from_whitelist(self, user_id: int):
        self.whitelist.discard(user_id)
        self.db.execute("DELETE FROM whitelist WHERE user_id = %s", (user_id,))
    
    def is_whitelisted(self, user_id: int) -> bool:
        return user_id in self.whitelist
    
    # blacklist stuff
    def add_to_blacklist(self, user_id: int):
        self.blacklist.add(user_id)
        self.whitelist.discard(user_id)
        self.db.execute("INSERT INTO blacklist (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
        self.db.execute("DELETE FROM whitelist WHERE user_id = %s", (user_id,))
    
    def remove_from_blacklist(self, user_id: int):
        self.blacklist.discard(user_id)
        self.db.execute("DELETE FROM blacklist WHERE user_id = %s", (user_id,))
    
    def is_blacklisted(self, user_id: int) -> bool:
        return user_id in self.blacklist
    
    # violations
    def add_violation(self, user_id: int):
        self.user_violations[user_id] += 1
        count = self.user_violations[user_id]
        self.db.execute("""
            INSERT INTO violations (user_id, count) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET count = %s
        """, (user_id, count, count))
    
    def clear_violations(self, user_id: int):
        self.user_violations[user_id] = 0
        self.db.execute("DELETE FROM violations WHERE user_id = %s", (user_id,))
    
    # warnings
    def add_warning(self, user_id: int, reason: str, moderator_id: int):
        self.db.execute("""
            INSERT INTO warnings (user_id, reason, moderator_id)
            VALUES (%s, %s, %s)
        """, (user_id, reason, moderator_id))
    
    def get_warnings(self, user_id: int) -> List[Dict]:
        result = self.db.execute("""
            SELECT reason, moderator_id, timestamp
            FROM warnings WHERE user_id = %s
            ORDER BY timestamp DESC
        """, (user_id,), fetch=True)
        
        if result:
            return [
                {
                    'reason': row[0],
                    'moderator': row[1],
                    'timestamp': row[2].isoformat()
                }
                for row in result
            ]
        return []
    
    def clear_warnings(self, user_id: int):
        self.db.execute("DELETE FROM warnings WHERE user_id = %s", (user_id,))
    
    # settings
    def get_guild_settings(self, guild_id: int) -> Dict:
    """Get guild settings from database"""
    result = self.db.execute("""
        SELECT log_channel_id, verified_role_id, unverified_role_id, 
               verification_channel_id, staff_role_id, automod_enabled,
               anti_raid_enabled, anti_nuke_enabled, welcome_channel_id,
               leave_channel_id, welcome_message, leave_message,
               invite_tracking_enabled, invite_tracker_channel_id
        FROM bot_settings 
        WHERE guild_id = %s
    """, (guild_id,), fetch=True)
    
    if result and len(result) > 0:
        row = result[0]
        return {
            'log_channel_id': row[0],
            'verified_role_id': row[1],
            'unverified_role_id': row[2],
            'verification_channel_id': row[3],
            'staff_role_id': row[4],
            'automod_enabled': row[5] if row[5] is not None else True,
            'anti_raid_enabled': row[6] if row[6] is not None else True,
            'anti_nuke_enabled': row[7] if row[7] is not None else True,
            'welcome_channel_id': row[8],
            'leave_channel_id': row[9],
            'welcome_message': row[10],
            'leave_message': row[11],
            'invite_tracking_enabled': row[12] if row[12] is not None else False,
            'invite_tracker_channel_id': row[13]
        }
    
    # Return defaults if no settings found
    return {
        'log_channel_id': None,
        'verified_role_id': None,
        'unverified_role_id': None,
        'verification_channel_id': None,
        'staff_role_id': None,
        'automod_enabled': True,
        'anti_raid_enabled': True,
        'anti_nuke_enabled': True,
        'welcome_channel_id': None,
        'leave_channel_id': None,
        'welcome_message': None,
        'leave_message': None,
        'invite_tracking_enabled': False,
        'invite_tracker_channel_id': None
    }
        
    
    def update_guild_setting(self, guild_id: int, setting: str, value):
        self.db.execute(f"""
            INSERT INTO bot_settings (guild_id, {setting})
            VALUES (%s, %s)
            ON CONFLICT (guild_id)
            DO UPDATE SET {setting} = %s
        """, (guild_id, value, value))

# bot setup
intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix=Config.PREFIX,
    intents=intents,
    help_command=None,
    case_insensitive=True
)
data_manager = DataManager()

# helper functions
def is_owner():
    """check if user is the owner"""
    async def predicate(interaction: discord.Interaction):
        if interaction.user.id != Config.OWNER_ID:
            await interaction.response.send_message(
                "nah bro only the owner can do that",
                 ephemeral=True
            )
            return False
        return True
    return app_commands.check(predicate)

def is_owner_or_admin():
    """check if owner or admin"""
    async def predicate(ctx):
        return ctx.author.id == Config.OWNER_ID or ctx.author.guild_permissions.administrator
    return commands.check(predicate)

def is_moderator():
    """check if user can moderate"""
    async def predicate(ctx):
        if ctx.author.id == Config.OWNER_ID:
            return True
        if ctx.author.guild_permissions.administrator:
            return True
        if ctx.author.guild_permissions.kick_members or ctx.author.guild_permissions.ban_members:
            return True
        return False
    return commands.check(predicate)

def can_execute_action(ctx, target: discord.Member) -> Tuple[bool, str]:
    """check if user can perform action on target"""
    # cant target yourself
    if ctx.author.id == target.id:
        return False, "you cant do that to yourself lol"
    
    # owner can do anything
    if ctx.author.id == Config.OWNER_ID:
        return True, ""
    
    # cant target the owner
    if target.id == Config.OWNER_ID:
        return False, "nice try but you cant touch the owner"
    
    # cant target server owner
    if target.id == ctx.guild.owner_id:
        return False, "you cant do that to the server owner"
    
    # check role hierarchy
    if ctx.author.top_role <= target.top_role:
        return False, "their role is higher or equal to yours"
    
    # check if bot can actually do it
    if ctx.guild.me.top_role <= target.top_role:
        return False, "that person's role is too high for me to touch"
    
    return True, ""

async def get_log_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """get or create log channel"""
    settings = data_manager.get_guild_settings(guild.id)
    log_channel_id = settings.get('log_channel_id')
    
    if log_channel_id:
        channel = guild.get_channel(log_channel_id)
        if channel:
            return channel
    
    log_channel = discord.utils.get(guild.text_channels, name='security-logs')
    if not log_channel:
        try:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            log_channel = await guild.create_text_channel(
                'security-logs',
                reason='logging channel',
                overwrites=overwrites
            )
            data_manager.update_guild_setting(guild.id, 'log_channel_id', log_channel.id)
        except Exception as e:
            logging.error(f"couldnt create log channel: {e}")
            return None
    
    return log_channel

async def log_action(guild: discord.Guild, title: str, description: str, color: discord.Color, fields: List[Tuple[str, str]] = None):
    """log stuff to the log channel"""
    log_channel = await get_log_channel(guild)
    if not log_channel:
        return
    
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.utcnow()
    )
    
    if fields:
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=True)
    
    try:
        await log_channel.send(embed=embed)
    except Exception as e:
        logging.error(f"failed to log: {e}")

def calculate_timeout(violation_count: int) -> int:
    """figure out how long to timeout someone"""
    return Config.SPAM_TIMEOUTS.get(violation_count, 180)

def contains_profanity(content: str) -> Tuple[bool, str]:
    """check for bad words"""
    content_lower = content.lower()
    
    for word in Config.BANNED_WORDS:
        if re.search(r'\b' + re.escape(word) + r'\b', content_lower):
            return True, word
    
    for pattern in Config.BANNED_PATTERNS:
        match = re.search(pattern, content_lower, re.IGNORECASE)
        if match:
            return True, match.group(0)
    
    return False, ''

def extract_links(content: str) -> List[str]:
    """grab all links from a message"""
    url_pattern = r'https?://[^\s]+'
    return re.findall(url_pattern, content)

def is_suspicious_account(member: discord.Member) -> Tuple[bool, str]:
    """check if account looks sketchy"""
    account_age = (datetime.utcnow() - member.created_at).days
    
    if account_age < Config.ACCOUNT_AGE_MINIMUM:
        return True, f"account is only {account_age} days old"
    
    if member.avatar is None:
        return True, "no profile picture"
    
    return False, ""

"""
Part 2: Invite Tracking & Welcome/Leave Messages
time to track who invited who and say hi/bye to people
"""

# invite tracking stuff
async def update_invites_cache(guild: discord.Guild):
    """save all current invites to database"""
    try:
        invites = await guild.invites()
        
        # clear old invites for this guild
        data_manager.db.execute("DELETE FROM invites WHERE guild_id = %s", (guild.id,))
        
        # save new ones
        for invite in invites:
            data_manager.db.execute("""
                INSERT INTO invites (guild_id, code, inviter_id, uses)
                VALUES (%s, %s, %s, %s)
            """, (guild.id, invite.code, invite.inviter.id if invite.inviter else 0, invite.uses))
        
        logging.info(f"cached {len(invites)} invites for {guild.name}")
    except Exception as e:
        logging.error(f"failed to cache invites: {e}")

async def get_used_invite(guild: discord.Guild) -> Optional[Tuple[discord.Invite, discord.Member]]:
    """figure out which invite was used"""
    try:
        # get current invites
        current_invites = await guild.invites()
        
        # get cached invites from db
        cached = data_manager.db.execute("""
            SELECT code, inviter_id, uses FROM invites WHERE guild_id = %s
        """, (guild.id,), fetch=True)
        
        if not cached:
            return None
        
        # make it easier to work with
        cached_dict = {row[0]: {'inviter_id': row[1], 'uses': row[2]} for row in cached}
        
        # find which invite got used
        for invite in current_invites:
            if invite.code in cached_dict:
                if invite.uses > cached_dict[invite.code]['uses']:
                    inviter = guild.get_member(cached_dict[invite.code]['inviter_id'])
                    return invite, inviter
        
        return None
    except Exception as e:
        logging.error(f"error finding used invite: {e}")
        return None

@bot.event
async def on_ready():
    """bot startup"""
    print('=' * 70)
    print(f'yo the bot is online: {bot.user}')
    print(f'in {len(bot.guilds)} servers')
    print(f'watching over {len(bot.users)} users')
    print(f'prefix: {Config.PREFIX}')
    print('=' * 70)
    
    # sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f'synced {len(synced)} slash commands')
    except Exception as e:
        logging.error(f'command sync failed: {e}')
    
    # set status
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{Config.PREFIX}help | keeping things safe"
        ),
        status=discord.Status.online
    )
    
    # cache invites for all guilds
    for guild in bot.guilds:
        await update_invites_cache(guild)
    
    # start cleanup task
    if not cleanup_task.is_running():
        cleanup_task.start()
    
    print('all systems go!')
    print('=' * 70)

@tasks.loop(hours=1)
async def cleanup_task():
    """clean up old data every hour"""
    try:
        current_time = datetime.utcnow().timestamp()
        
        # clean message history
        for user_id in list(data_manager.message_history.keys()):
            data_manager.message_history[user_id] = [
                ts for ts in data_manager.message_history[user_id]
                if current_time - ts <= 3600
            ]
            if not data_manager.message_history[user_id]:
                del data_manager.message_history[user_id]
        
        # clean link history
        for user_id in list(data_manager.link_history.keys()):
            data_manager.link_history[user_id] = [
                ts for ts in data_manager.link_history[user_id]
                if current_time - ts <= 3600
            ]
            if not data_manager.link_history[user_id]:
                del data_manager.link_history[user_id]
        
        logging.info("cleanup done")
    except Exception as e:
        logging.error(f"cleanup failed: {e}")

@bot.event
async def on_guild_join(guild: discord.Guild):
    """when bot joins a server"""
    await update_invites_cache(guild)
    print(f"joined new server: {guild.name}")

@bot.event
async def on_invite_create(invite: discord.Invite):
    """when someone creates an invite"""
    await update_invites_cache(invite.guild)

@bot.event
async def on_invite_delete(invite: discord.Invite):
    """when an invite gets deleted"""
    await update_invites_cache(invite.guild)

@bot.event
async def on_member_join(member: discord.Member):
    """when someone joins the server"""
    guild = member.guild
    settings = data_manager.get_guild_settings(guild.id)
    
    # check if blacklisted
    if data_manager.is_blacklisted(member.id):
        try:
            await member.kick(reason="blacklisted user tried to join")
            await log_action(
                guild,
                'blacklisted user kicked',
                f'{member.mention} tried to join but theyre blacklisted',
                discord.Color.red(),
                [('user id', str(member.id))]
            )
        except Exception as e:
            logging.error(f"failed to kick blacklisted user: {e}")
        return
    
    # invite tracking
    inviter = None
    invite_code = None
    
    if settings.get('invite_tracking_enabled'):
        invite_data = await get_used_invite(guild)
        if invite_data:
            invite, inviter = invite_data
            invite_code = invite.code
            
            # save to database
            data_manager.db.execute("""
                INSERT INTO invite_joins (guild_id, user_id, inviter_id, invite_code)
                VALUES (%s, %s, %s, %s)
            """, (guild.id, member.id, inviter.id if inviter else 0, invite_code))
            
            # update invite cache
            await update_invites_cache(guild)

    # Add this code RIGHT AFTER the invite tracking section in on_member_join
# (after updating invite cache and saving to database)

# Send invite tracker notification to dedicated channel
    if settings.get('invite_tracking_enabled') and inviter:
        tracker_channel_id = settings.get('invite_tracker_channel_id')
        if tracker_channel_id:
            tracker_channel = guild.get_channel(tracker_channel_id)
            if tracker_channel:
                try:
                    # Create the message like invite tracker bot
                    tracker_msg = f"{member.mention} joined! Invited by {inviter.mention}"
                    await tracker_channel.send(tracker_msg)
                except Exception as e:
                    logging.error(f"failed to send invite tracker message: {e}")
    
    # auto-assign unverified role if verification is set up
    unverified_role_id = settings.get('unverified_role_id')
    if unverified_role_id:
        unverified_role = guild.get_role(unverified_role_id)
        if unverified_role:
            try:
                await member.add_roles(unverified_role, reason="auto-assign unverified")
            except Exception as e:
                logging.error(f"failed to assign unverified role: {e}")
    
    # check for suspicious account
    is_suspicious, reason = is_suspicious_account(member)
    if is_suspicious and settings.get('anti_raid_enabled', True):
        await log_action(
            guild,
            'sus account joined',
            f'{member.mention} looks kinda sketchy',
            discord.Color.orange(),
            [('user id', str(member.id)), ('reason', reason)]
        )
    
    

    # send welcome message
    welcome_channel_id = settings.get('welcome_channel_id')
    if welcome_channel_id:
        welcome_channel = guild.get_channel(welcome_channel_id)
        if welcome_channel:
            
            # get custom message or use default
            message = settings.get('welcome_message') or "Welcome {user} to **{server}**!"
        
            # replace placeholders
            message = message.replace('{user}', member.mention)
            message = message.replace('{server}', guild.name)
            message = message.replace('{count}', str(guild.member_count))
        
            if inviter:
                message = message.replace('{inviter}', inviter.mention)
            else:
                message = message.replace('{inviter}', 'unknown')
        
            try:
               # Send plain text message, no embed!
               await welcome_channel.send(message)
            except Exception as e:
                logging.error(f"failed to send welcome message: {e}")
    
    # bot protection
    if member.bot:
        await asyncio.sleep(1)
        
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.bot_add):
            if entry.target.id == member.id:
                bot_inviter = entry.user
                
                if bot_inviter.id == Config.OWNER_ID or data_manager.is_whitelisted(bot_inviter.id):
                    await log_action(
                        guild,
                        'bot added (authorized)',
                        f'{bot_inviter.mention} added {member.mention}',
                        discord.Color.green(),
                        [('bot', member.mention), ('added by', bot_inviter.mention)]
                    )
                    return
                
                if settings.get('anti_nuke_enabled', True):
                    try:
                        await member.kick(reason=f'unauthorized bot addition by {bot_inviter}')
                        
                        inviter_member = guild.get_member(bot_inviter.id)
                        if inviter_member and inviter_member != guild.owner:
                            roles_to_remove = [
                                r for r in inviter_member.roles
                                if r != guild.default_role and r.position < guild.me.top_role.position
                            ]
                            if roles_to_remove:
                                await inviter_member.remove_roles(*roles_to_remove, reason='unauthorized bot addition')
                        
                        await log_action(
                            guild,
                            'anti-nuke: unauthorized bot blocked',
                            f'bot: {member.mention}\nadded by: {bot_inviter.mention}',
                            discord.Color.red(),
                            [('action', 'bot kicked, inviter roles stripped')]
                        )
                    except Exception as e:
                        logging.error(f"failed to handle unauthorized bot: {e}")
                break
    
    # raid detection
    if not settings.get('anti_raid_enabled', True):
        return
    
    current_time = datetime.utcnow().timestamp()
    
    if not hasattr(bot, 'recent_joins'):
        bot.recent_joins = defaultdict(list)
    
    bot.recent_joins[guild.id].append(current_time)
    bot.recent_joins[guild.id] = [
        ts for ts in bot.recent_joins[guild.id]
        if current_time - ts <= Config.RAID_JOIN_TIMEFRAME
    ]
    
    if len(bot.recent_joins[guild.id]) >= Config.RAID_JOIN_THRESHOLD:
        try:
            await guild.edit(
                verification_level=discord.VerificationLevel.highest,
                reason='raid detected - auto protection'
            )
            await log_action(
                guild,
                'anti-raid: mass join detected',
                f'detected {len(bot.recent_joins[guild.id])} joins in {Config.RAID_JOIN_TIMEFRAME} seconds',
                discord.Color.red(),
                [('action', 'verification set to highest')]
            )
            bot.recent_joins[guild.id].clear()
        except Exception as e:
            logging.error(f"failed to activate raid protection: {e}")

@bot.event
async def on_member_remove(member: discord.Member):
    """when someone leaves the server"""
    guild = member.guild
    settings = data_manager.get_guild_settings(guild.id)
    
    # send leave message (PLAIN TEXT - NO EMBED)
    leave_channel_id = settings.get('leave_channel_id')
    if leave_channel_id:
        leave_channel = guild.get_channel(leave_channel_id)
        if leave_channel:
            # get custom message or use default
            message = settings.get('leave_message') or "**{user}** just left us... rip"
            
            # replace placeholders
            message = message.replace('{user}', member.name)
            message = message.replace('{server}', guild.name)
            message = message.replace('{count}', str(guild.member_count))
            
            try:
                # Send plain text message, no embed!
                await leave_channel.send(message)
            except Exception as e:
                logging.error(f"failed to send leave message: {e}")
    
    # log it
    await log_action(
        guild,
        'member left',
        f'{member.mention} left the server',
        discord.Color.orange(),
        [('user', str(member)), ('id', str(member.id))]
    )

# welcome/leave setup commands
@bot.command(name='setwelcome')
@is_owner_or_admin()
async def set_welcome(ctx, channel: discord.TextChannel):
    """set the welcome channel"""
    data_manager.update_guild_setting(ctx.guild.id, 'welcome_channel_id', channel.id)
    
    embed = discord.Embed(
        title='welcome channel set!',
        description=f'welcome messages will be sent to {channel.mention}',
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

@bot.command(name='setleave')
@is_owner_or_admin()
async def set_leave(ctx, channel: discord.TextChannel):
    """set the leave channel"""
    data_manager.update_guild_setting(ctx.guild.id, 'leave_channel_id', channel.id)
    
    embed = discord.Embed(
        title='leave channel set!',
        description=f'leave messages will be sent to {channel.mention}',
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

@bot.command(name='welcomemsg')
@is_owner_or_admin()
async def welcome_message(ctx, *, message: str):
    """set custom welcome message
    
    placeholders:
    {user} - mentions the user
    {server} - server name
    {count} - member count
    {inviter} - who invited them
    """
    data_manager.update_guild_setting(ctx.guild.id, 'welcome_message', message)
    
    embed = discord.Embed(
        title='welcome message updated!',
        description=f'new message:\n{message}',
        color=discord.Color.green()
    )
    embed.set_footer(text='placeholders: {user} {server} {count} {inviter}')
    await ctx.send(embed=embed)

@bot.command(name='leavemsg')
@is_owner_or_admin()
async def leave_message(ctx, *, message: str):
    """set custom leave message
    
    placeholders:
    {user} - username
    {server} - server name
    {count} - member count
    """
    data_manager.update_guild_setting(ctx.guild.id, 'leave_message', message)
    
    embed = discord.Embed(
        title='leave message updated!',
        description=f'new message:\n{message}',
        color=discord.Color.green()
    )
    embed.set_footer(text='placeholders: {user} {server} {count}')
    await ctx.send(embed=embed)

# invite tracking commands
@bot.command(name='invitetracking')
@is_owner_or_admin()
async def invite_tracking(ctx, mode: str):
    """toggle invite tracking (on/off)"""
    mode = mode.lower()
    
    if mode == 'on':
        data_manager.update_guild_setting(ctx.guild.id, 'invite_tracking_enabled', True)
        await update_invites_cache(ctx.guild)
        await ctx.send('invite tracking enabled! gonna start tracking who invites who')
    elif mode == 'off':
        data_manager.update_guild_setting(ctx.guild.id, 'invite_tracking_enabled', False)
        await ctx.send('invite tracking disabled')
    else:
        await ctx.send('use `+invitetracking on` or `+invitetracking off`')

# Add this command with the other invite tracking commands

@bot.command(name='setinvitetracker')
@is_owner_or_admin()
async def set_invite_tracker(ctx, channel: discord.TextChannel):
    """set the channel where invite tracking messages appear"""
    data_manager.update_guild_setting(ctx.guild.id, 'invite_tracker_channel_id', channel.id)
    
    embed = discord.Embed(
        title='invite tracker channel set!',
        description=f'invite notifications will be sent to {channel.mention}',
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

@bot.command(name='invites')
async def check_invites(ctx, member: discord.Member = None):
    """check how many people someone invited"""
    member = member or ctx.author
    
    result = data_manager.db.execute("""
        SELECT COUNT(*) FROM invite_joins
        WHERE guild_id = %s AND inviter_id = %s
    """, (ctx.guild.id, member.id), fetch=True)
    
    count = result[0][0] if result else 0
    
    # get recent invites
    recent = data_manager.db.execute("""
        SELECT user_id, joined_at FROM invite_joins
        WHERE guild_id = %s AND inviter_id = %s
        ORDER BY joined_at DESC
        LIMIT 5
    """, (ctx.guild.id, member.id), fetch=True)
    
    embed = discord.Embed(
        title=f'invites for {member.name}',
        color=discord.Color.blue()
    )
    embed.add_field(name='total invites', value=str(count), inline=False)
    
    if recent:
        recent_text = ''
        for user_id, joined_at in recent:
            user = ctx.guild.get_member(user_id)
            if user:
                recent_text += f'{user.mention} - {joined_at.strftime("%Y-%m-%d")}\n'
        
        if recent_text:
            embed.add_field(name='recent invites', value=recent_text, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='migratedb')
@is_owner_or_admin()
async def migrate_database(ctx):
    """add the invite_tracker_channel_id column to database"""
    try:
        # Add the new column
        data_manager.db.execute("""
            ALTER TABLE bot_settings 
            ADD COLUMN IF NOT EXISTS invite_tracker_channel_id BIGINT
        """)
        
        await ctx.send('✅ database migrated! invite tracker channel column added')
    except Exception as e:
        await ctx.send(f'❌ migration failed: {e}')

@bot.command(name='whoinvited')
@is_moderator()
async def who_invited(ctx, member: discord.Member):
    """check who invited someone"""
    result = data_manager.db.execute("""
        SELECT inviter_id, invite_code, joined_at FROM invite_joins
        WHERE guild_id = %s AND user_id = %s
        ORDER BY joined_at DESC
        LIMIT 1
    """, (ctx.guild.id, member.id), fetch=True)
    
    if result:
        inviter_id, invite_code, joined_at = result[0]
        inviter = ctx.guild.get_member(inviter_id)
        
        embed = discord.Embed(
            title=f'who invited {member.name}',
            color=discord.Color.blue()
        )
        embed.add_field(name='invited by', value=inviter.mention if inviter else 'unknown', inline=False)
        embed.add_field(name='invite code', value=invite_code or 'unknown', inline=True)
        embed.add_field(name='joined', value=joined_at.strftime('%Y-%m-%d %H:%M'), inline=True)
        
        await ctx.send(embed=embed)
    else:
        await ctx.send(f'couldnt find who invited {member.mention}')



"""
Part 3: Moderation Commands
all the mod commands with proper permission checks
"""

@bot.command(name='kick')
@is_owner_or_admin()
async def kick_cmd(ctx, member: discord.Member, *, reason: str = "no reason given"):
    """kick someone from the server"""
    can_do, error_msg = can_execute_action(ctx, member)
    
    if not can_do:
        return await ctx.send(f'❌ {error_msg}')
    
    try:
        await member.kick(reason=f'{reason} | by {ctx.author}')
        
        embed = discord.Embed(
            title='member kicked',
            description=f'{member.mention} got kicked',
            color=discord.Color.orange()
        )
        embed.add_field(name='reason', value=reason, inline=False)
        embed.add_field(name='moderator', value=ctx.author.mention, inline=True)
        
        await ctx.send(embed=embed)
        
        await log_action(
            ctx.guild,
            'member kicked',
            f'user: {member.mention}\nmoderator: {ctx.author.mention}',
            discord.Color.orange(),
            [('reason', reason)]
        )
    except Exception as e:
        await ctx.send(f'failed to kick: {e}')

@bot.command(name='ban')
@is_owner_or_admin()
async def ban_cmd(ctx, member: discord.Member, *, reason: str = "no reason given"):
    """ban someone from the server"""
    can_do, error_msg = can_execute_action(ctx, member)
    
    if not can_do:
        return await ctx.send(f'❌ {error_msg}')
    
    try:
        await member.ban(reason=f'{reason} | by {ctx.author}', delete_message_days=1)
        
        embed = discord.Embed(
            title='member banned',
            description=f'{member.mention} got the hammer',
            color=discord.Color.red()
        )
        embed.add_field(name='reason', value=reason, inline=False)
        embed.add_field(name='moderator', value=ctx.author.mention, inline=True)
        
        await ctx.send(embed=embed)
        
        await log_action(
            ctx.guild,
            'member banned',
            f'user: {member.mention}\nmoderator: {ctx.author.mention}',
            discord.Color.red(),
            [('reason', reason)]
        )
    except Exception as e:
        await ctx.send(f'failed to ban: {e}')

@bot.command(name='unban')
@is_owner_or_admin()
async def unban_cmd(ctx, user_id: int, *, reason: str = "no reason given"):
    """unban someone using their id"""
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user, reason=f'{reason} | by {ctx.author}')
        
        await ctx.send(f'unbanned {user} (id: {user_id})')
        
        await log_action(
            ctx.guild,
            'member unbanned',
            f'user: {user} (id: {user_id})\nmoderator: {ctx.author.mention}',
            discord.Color.green(),
            [('reason', reason)]
        )
    except Exception as e:
        await ctx.send(f'failed to unban: {e}')

@bot.command(name='softban')
@is_owner_or_admin()
async def softban_cmd(ctx, member: discord.Member, *, reason: str = "no reason given"):
    """softban someone (ban then unban to delete messages)"""
    can_do, error_msg = can_execute_action(ctx, member)
    
    if not can_do:
        return await ctx.send(f'❌ {error_msg}')
    
    try:
        await member.ban(reason=f'softban: {reason} | by {ctx.author}', delete_message_days=7)
        await ctx.guild.unban(member, reason=f'softban unban | by {ctx.author}')
        
        await ctx.send(f'softbanned {member.mention} (messages deleted)')
        
        await log_action(
            ctx.guild,
            'member softbanned',
            f'user: {member.mention}\nmoderator: {ctx.author.mention}',
            discord.Color.orange(),
            [('reason', reason)]
        )
    except Exception as e:
        await ctx.send(f'failed to softban: {e}')

@bot.command(name='timeout')
@is_owner_or_admin()
async def timeout_cmd(ctx, member: discord.Member, duration: int, *, reason: str = "no reason given"):
    """timeout someone (duration in minutes)"""
    can_do, error_msg = can_execute_action(ctx, member)
    
    if not can_do:
        return await ctx.send(f'❌ {error_msg}')
    
    if duration > 40320:  # 28 days max
        return await ctx.send("max timeout is 40320 minutes (28 days)")
    
    try:
        await member.timeout(timedelta(minutes=duration), reason=f'{reason} | by {ctx.author}')
        
        embed = discord.Embed(
            title='member timed out',
            description=f'{member.mention} got timed out',
            color=discord.Color.orange()
        )
        embed.add_field(name='duration', value=f'{duration} minutes', inline=True)
        embed.add_field(name='reason', value=reason, inline=False)
        
        await ctx.send(embed=embed)
        
        await log_action(
            ctx.guild,
            'member timed out',
            f'user: {member.mention}\nduration: {duration} minutes\nmoderator: {ctx.author.mention}',
            discord.Color.orange(),
            [('reason', reason)]
        )
    except Exception as e:
        await ctx.send(f'failed to timeout: {e}')

@bot.command(name='untimeout')
@is_owner_or_admin()
async def untimeout_cmd(ctx, member: discord.Member):
    """remove timeout from someone"""
    can_do, error_msg = can_execute_action(ctx, member)
    
    if not can_do:
        return await ctx.send(f'❌ {error_msg}')
    
    try:
        await member.timeout(None, reason=f'timeout removed by {ctx.author}')
        await ctx.send(f'timeout removed from {member.mention}')
        
        await log_action(
            ctx.guild,
            'timeout removed',
            f'user: {member.mention}\nmoderator: {ctx.author.mention}',
            discord.Color.green()
        )
    except Exception as e:
        await ctx.send(f'failed to remove timeout: {e}')

@bot.command(name='warn')
@is_moderator()
async def warn_cmd(ctx, member: discord.Member, *, reason: str = "no reason given"):
    """warn someone"""
    can_do, error_msg = can_execute_action(ctx, member)
    
    if not can_do:
        return await ctx.send(f'❌ {error_msg}')
    
    data_manager.add_warning(member.id, reason, ctx.author.id)
    warning_count = len(data_manager.get_warnings(member.id))
    
    try:
        await member.send(
            f'**warning from {ctx.guild.name}**\n\n'
            f'you got warned by {ctx.author}\n'
            f'reason: {reason}\n'
            f'total warnings: {warning_count}'
        )
        dm_sent = True
    except:
        dm_sent = False
    
    embed = discord.Embed(
        title='member warned',
        description=f'{member.mention} got warned',
        color=discord.Color.gold()
    )
    embed.add_field(name='reason', value=reason, inline=False)
    embed.add_field(name='total warnings', value=str(warning_count), inline=True)
    embed.add_field(name='dm sent', value='yes' if dm_sent else 'no', inline=True)
    
    await ctx.send(embed=embed)
    
    await log_action(
        ctx.guild,
        'warning issued',
        f'user: {member.mention}\nmoderator: {ctx.author.mention}\ntotal warnings: {warning_count}',
        discord.Color.gold(),
        [('reason', reason)]
    )

@bot.command(name='warnings')
@is_moderator()
async def warnings_cmd(ctx, member: discord.Member):
    """check someone's warnings"""
    warnings = data_manager.get_warnings(member.id)
    
    if not warnings:
        return await ctx.send(f'{member.mention} has no warnings')
    
    embed = discord.Embed(
        title=f'warnings for {member}',
        description=f'total warnings: {len(warnings)}',
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    
    for i, warning in enumerate(warnings[:10], 1):
        moderator = await bot.fetch_user(warning['moderator'])
        timestamp = datetime.fromisoformat(warning['timestamp']).strftime('%Y-%m-%d %H:%M')
        embed.add_field(
            name=f'warning {i}',
            value=f"reason: {warning['reason']}\nmoderator: {moderator.mention}\ndate: {timestamp}",
            inline=False
        )
    
    if len(warnings) > 10:
        embed.set_footer(text=f'showing 10 of {len(warnings)} warnings')
    
    await ctx.send(embed=embed)

@bot.command(name='clearwarnings')
@is_owner_or_admin()
async def clearwarnings_cmd(ctx, member: discord.Member):
    """clear all warnings for someone"""
    warnings = data_manager.get_warnings(member.id)
    
    if not warnings:
        return await ctx.send(f'{member.mention} has no warnings to clear')
    
    warning_count = len(warnings)
    data_manager.clear_warnings(member.id)
    
    await ctx.send(f'cleared {warning_count} warnings for {member.mention}')
    
    await log_action(
        ctx.guild,
        'warnings cleared',
        f'user: {member.mention}\ncleared by: {ctx.author.mention}\nwarnings removed: {warning_count}',
        discord.Color.blue()
    )

@bot.command(name='purge')
@is_owner_or_admin()
async def purge_cmd(ctx, amount: int):
    """delete messages (max 100)"""
    if amount <= 0:
        return await ctx.send("amount must be greater than 0")
    
    if amount > 100:
        return await ctx.send("max 100 messages at once")
    
    try:
        deleted = await ctx.channel.purge(limit=amount + 1)
        
        msg = await ctx.send(f'deleted {len(deleted) - 1} messages')
        await asyncio.sleep(3)
        await msg.delete()
        
        await log_action(
            ctx.guild,
            'messages purged',
            f'channel: {ctx.channel.mention}\namount: {len(deleted) - 1}\nmoderator: {ctx.author.mention}',
            discord.Color.blue()
        )
    except Exception as e:
        await ctx.send(f'failed to purge: {e}')

@bot.command(name='purgeuser')
@is_owner_or_admin()
async def purgeuser_cmd(ctx, member: discord.Member, amount: int = 100):
    """delete messages from a specific user"""
    if amount > 100:
        amount = 100
    
    try:
        deleted = await ctx.channel.purge(limit=amount, check=lambda m: m.author.id == member.id)
        
        msg = await ctx.send(f'deleted {len(deleted)} messages from {member.mention}')
        await asyncio.sleep(3)
        await msg.delete()
        
        await log_action(
            ctx.guild,
            'user messages purged',
            f'user: {member.mention}\nchannel: {ctx.channel.mention}\namount: {len(deleted)}\nmoderator: {ctx.author.mention}',
            discord.Color.blue()
        )
    except Exception as e:
        await ctx.send(f'failed to purge user messages: {e}')

@bot.command(name='slowmode')
@is_owner_or_admin()
async def slowmode_cmd(ctx, seconds: int):
    """set slowmode for a channel (0 to disable)"""
    if seconds < 0 or seconds > 21600:
        return await ctx.send("slowmode must be between 0 and 21600 seconds (6 hours)")
    
    try:
        await ctx.channel.edit(slowmode_delay=seconds)
        
        if seconds == 0:
            await ctx.send(f'slowmode disabled in {ctx.channel.mention}')
        else:
            await ctx.send(f'slowmode set to {seconds} seconds in {ctx.channel.mention}')
        
        await log_action(
            ctx.guild,
            'slowmode updated',
            f'channel: {ctx.channel.mention}\ndelay: {seconds} seconds\nmoderator: {ctx.author.mention}',
            discord.Color.blue()
        )
    except Exception as e:
        await ctx.send(f'failed to set slowmode: {e}')

@bot.command(name='lock')
@is_owner_or_admin()
async def lock_cmd(ctx, channel: discord.TextChannel = None):
    """lock a channel"""
    channel = channel or ctx.channel
    
    try:
        await channel.set_permissions(ctx.guild.default_role, send_messages=False)
        
        # let staff still talk
        settings = data_manager.get_guild_settings(ctx.guild.id)
        staff_role_id = settings.get('staff_role_id') or Config.STAFF_ROLE_ID
        if staff_role_id:
            staff_role = ctx.guild.get_role(staff_role_id)
            if staff_role:
                await channel.set_permissions(staff_role, send_messages=True)
        
        await ctx.send(f'🔒 {channel.mention} locked')
        
        await log_action(
            ctx.guild,
            'channel locked',
            f'channel: {channel.mention}\nmoderator: {ctx.author.mention}',
            discord.Color.red()
        )
    except Exception as e:
        await ctx.send(f'failed to lock channel: {e}')

@bot.command(name='unlock')
@is_owner_or_admin()
async def unlock_cmd(ctx, channel: discord.TextChannel = None):
    """unlock a channel"""
    channel = channel or ctx.channel
    
    try:
        await channel.set_permissions(ctx.guild.default_role, send_messages=True)
        await ctx.send(f'🔓 {channel.mention} unlocked')
        
        await log_action(
            ctx.guild,
            'channel unlocked',
            f'channel: {channel.mention}\nmoderator: {ctx.author.mention}',
            discord.Color.green()
        )
    except Exception as e:
        await ctx.send(f'failed to unlock channel: {e}')

@bot.command(name='lockdown')
@is_owner_or_admin()
async def lockdown_cmd(ctx):
    """lockdown entire server"""
    locked_count = 0
    settings = data_manager.get_guild_settings(ctx.guild.id)
    staff_role_id = settings.get('staff_role_id') or Config.STAFF_ROLE_ID
    staff_role = ctx.guild.get_role(staff_role_id) if staff_role_id else None
    
    try:
        for channel in ctx.guild.text_channels:
            try:
                await channel.set_permissions(ctx.guild.default_role, send_messages=False)
                
                if staff_role:
                    await channel.set_permissions(staff_role, send_messages=True)
                
                locked_count += 1
            except:
                pass
        
        embed = discord.Embed(
            title='🚨 server lockdown active',
            description=f'locked {locked_count} text channels',
            color=discord.Color.dark_red()
        )
        embed.add_field(name='moderator', value=ctx.author.mention)
        if staff_role:
            embed.add_field(name='staff access', value='staff can still send messages')
        
        await ctx.send(embed=embed)
        
        await log_action(
            ctx.guild,
            'server lockdown',
            f'channels locked: {locked_count}\nmoderator: {ctx.author.mention}',
            discord.Color.dark_red(),
            [('staff role', staff_role.mention if staff_role else 'none')]
        )
    except Exception as e:
        await ctx.send(f'failed to lockdown: {e}')

@bot.command(name='unlockdown')
@is_owner_or_admin()
async def unlockdown_cmd(ctx):
    """remove server lockdown"""
    unlocked_count = 0
    
    try:
        for channel in ctx.guild.text_channels:
            try:
                await channel.set_permissions(ctx.guild.default_role, send_messages=True)
                unlocked_count += 1
            except:
                pass
        
        embed = discord.Embed(
            title='✅ server lockdown ended',
            description=f'unlocked {unlocked_count} text channels',
            color=discord.Color.green()
        )
        embed.add_field(name='moderator', value=ctx.author.mention)
        
        await ctx.send(embed=embed)
        
        await log_action(
            ctx.guild,
            'server lockdown ended',
            f'channels unlocked: {unlocked_count}\nmoderator: {ctx.author.mention}',
            discord.Color.green()
        )
    except Exception as e:
        await ctx.send(f'failed to end lockdown: {e}')

"""
Part 4: Auto-Moderation & Message Filtering
automatic protection from spam, profanity, and bad stuff
"""

@bot.event
async def on_message(message: discord.Message):
    """auto-mod for every message"""
    if message.author.bot or not message.guild:
        await bot.process_commands(message)
        return
    
    # whitelist bypass
    if data_manager.is_whitelisted(message.author.id) or message.author.id == Config.OWNER_ID:
        await bot.process_commands(message)
        return
    
    # blacklist check
    if data_manager.is_blacklisted(message.author.id):
        try:
            await message.delete()
            await message.author.timeout(timedelta(hours=1), reason='blacklisted user')
        except:
            pass
        return
    
    settings = data_manager.get_guild_settings(message.guild.id)
    
    if not settings.get('automod_enabled', True):
        await bot.process_commands(message)
        return
    
    user_id = message.author.id
    current_time = datetime.utcnow().timestamp()
    
    # spam detection
    data_manager.message_history[user_id].append(current_time)
    data_manager.message_history[user_id] = [
        ts for ts in data_manager.message_history[user_id]
        if current_time - ts <= Config.SPAM_TIMEFRAME
    ]
    
    message_count = len(data_manager.message_history[user_id])
    
    if message_count >= Config.SPAM_THRESHOLD:
        data_manager.add_violation(user_id)
        violation_count = data_manager.user_violations[user_id]
        
        timeout_minutes = calculate_timeout(violation_count)
        
        try:
            await message.channel.purge(limit=20, check=lambda m: m.author.id == user_id)
            await message.author.timeout(timedelta(minutes=timeout_minutes), reason=f'spam: {message_count} messages')
            
            warning = await message.channel.send(
                f'{message.author.mention} got timed out for {timeout_minutes} minutes for spamming'
            )
            await asyncio.sleep(5)
            try:
                await warning.delete()
            except:
                pass
            
            await log_action(
                message.guild,
                'anti-spam action',
                f'user: {message.author.mention}\nmessages: {message_count}\ntimeout: {timeout_minutes} minutes',
                discord.Color.orange(),
                [('violations', str(violation_count))]
            )
        except Exception as e:
            logging.error(f"spam protection failed: {e}")
        
        data_manager.message_history[user_id].clear()
        return
    
    # profanity filter
    is_profane, matched_word = contains_profanity(message.content)
    if is_profane:
        try:
            await message.delete()
            await message.author.timeout(timedelta(minutes=Config.PROFANITY_TIMEOUT), reason=f'profanity: {matched_word}')
            
            warning = await message.channel.send(
                f'{message.author.mention} got timed out for {Config.PROFANITY_TIMEOUT} minutes for using bad words'
            )
            await asyncio.sleep(5)
            try:
                await warning.delete()
            except:
                pass
            
            await log_action(
                message.guild,
                'profanity filter',
                f'user: {message.author.mention}\nword: ||{matched_word}||',
                discord.Color.red(),
                [('action', f'{Config.PROFANITY_TIMEOUT}min timeout')]
            )
        except Exception as e:
            logging.error(f"profanity filter failed: {e}")
        return
    
    # mention spam
    mention_count = len(message.mentions) + len(message.role_mentions)
    if mention_count >= Config.MENTION_LIMIT:
        try:
            await message.delete()
            await message.author.timeout(timedelta(minutes=Config.MENTION_TIMEOUT), reason=f'mention spam: {mention_count} mentions')
            
            warning = await message.channel.send(
                f'{message.author.mention} got timed out for {Config.MENTION_TIMEOUT} minutes for mention spam'
            )
            await asyncio.sleep(5)
            try:
                await warning.delete()
            except:
                pass
            
            await log_action(
                message.guild,
                'mention spam',
                f'user: {message.author.mention}\nmentions: {mention_count}',
                discord.Color.red(),
                [('action', f'{Config.MENTION_TIMEOUT}min timeout')]
            )
        except Exception as e:
            logging.error(f"mention spam protection failed: {e}")
        return
    
    # link spam detection
    links = extract_links(message.content)
    if links:
        data_manager.link_history[user_id].append(current_time)
        data_manager.link_history[user_id] = [
            ts for ts in data_manager.link_history[user_id]
            if current_time - ts <= Config.LINK_TIMEFRAME
        ]
        
        link_count = len(data_manager.link_history[user_id])
        
        if link_count >= Config.LINK_LIMIT:
            try:
                await message.delete()
                await message.author.timeout(timedelta(minutes=15), reason=f'link spam: {link_count} links')
                
                warning = await message.channel.send(
                    f'{message.author.mention} got timed out for 15 minutes for link spam'
                )
                await asyncio.sleep(5)
                try:
                    await warning.delete()
                except:
                    pass
                
                await log_action(
                    message.guild,
                    'link spam',
                    f'user: {message.author.mention}\nlinks posted: {link_count}',
                    discord.Color.red(),
                    [('action', '15min timeout')]
                )
                
                data_manager.link_history[user_id].clear()
            except Exception as e:
                logging.error(f"link spam protection failed: {e}")
            return
    
    # caps lock detection
    if len(message.content) >= 20:
        caps_count = sum(1 for c in message.content if c.isupper())
        caps_ratio = caps_count / len(message.content)
        
        if caps_ratio >= 0.7:
            try:
                await message.delete()
                warning = await message.channel.send(
                    f'{message.author.mention} chill with the caps lock bro'
                )
                await asyncio.sleep(4)
                try:
                    await warning.delete()
                except:
                    pass
            except Exception as e:
                logging.error(f"caps lock filter failed: {e}")
            return
    
    await bot.process_commands(message)

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    """check edited messages too"""
    if after.author.bot or not after.guild:
        return
    
    if before.content == after.content:
        return
    
    settings = data_manager.get_guild_settings(after.guild.id)
    
    # check edited message for profanity
    is_profane, matched_word = contains_profanity(after.content)
    if is_profane and settings.get('automod_enabled', True):
        try:
            await after.delete()
            await after.author.timeout(timedelta(minutes=Config.PROFANITY_TIMEOUT), reason=f'profanity in edit: {matched_word}')
            
            await log_action(
                after.guild,
                'profanity in edited message',
                f'user: {after.author.mention}\nword: ||{matched_word}||',
                discord.Color.red(),
                [('action', f'{Config.PROFANITY_TIMEOUT}min timeout')]
            )
        except Exception as e:
            logging.error(f"edit profanity check failed: {e}")

@bot.event
async def on_message_delete(message: discord.Message):
    """log message deletions"""
    if message.author.bot or not message.guild:
        return
    
    await asyncio.sleep(0.5)
    
    async for entry in message.guild.audit_logs(limit=1, action=discord.AuditLogAction.message_delete):
        if entry.target.id == message.author.id:
            deleter = entry.user
            
            await log_action(
                message.guild,
                'message deleted',
                f'author: {message.author.mention}\ndeleted by: {deleter.mention}\nchannel: {message.channel.mention}',
                discord.Color.orange(),
                [('content', message.content[:100] if message.content else 'no content')]
            )
            break

@bot.event
async def on_bulk_message_delete(messages):
    """log bulk message deletions"""
    if not messages:
        return
    
    guild = messages[0].guild
    await log_action(
        guild,
        'bulk message delete',
        f'channel: {messages[0].channel.mention}\nmessages deleted: {len(messages)}',
        discord.Color.orange(),
        [('count', str(len(messages)))]
    )

# auto-mod toggle commands
@bot.command(name='automod')
@is_owner_or_admin()
async def automod_cmd(ctx, mode: str):
    """toggle auto-moderation (on/off)"""
    mode = mode.lower()
    
    if mode == 'on':
        data_manager.update_guild_setting(ctx.guild.id, 'automod_enabled', True)
        await ctx.send('✅ auto-moderation enabled')
        
        await log_action(
            ctx.guild,
            'auto-moderation enabled',
            f'moderator: {ctx.author.mention}',
            discord.Color.green()
        )
    
    elif mode == 'off':
        data_manager.update_guild_setting(ctx.guild.id, 'automod_enabled', False)
        await ctx.send('⚠️ auto-moderation disabled')
        
        await log_action(
            ctx.guild,
            'auto-moderation disabled',
            f'moderator: {ctx.author.mention}',
            discord.Color.orange()
        )
    
    else:
        await ctx.send('use `+automod on` or `+automod off`')

@bot.command(name='antiraid')
@is_owner_or_admin()
async def antiraid_cmd(ctx, mode: str):
    """toggle anti-raid mode (on/off)"""
    mode = mode.lower()
    
    if mode == 'on':
        try:
            await ctx.guild.edit(verification_level=discord.VerificationLevel.highest)
            data_manager.update_guild_setting(ctx.guild.id, 'anti_raid_enabled', True)
            
            await ctx.send('✅ anti-raid mode enabled. verification set to highest')
            
            await log_action(
                ctx.guild,
                'anti-raid enabled',
                f'moderator: {ctx.author.mention}',
                discord.Color.green()
            )
        except Exception as e:
            await ctx.send(f'failed to enable anti-raid: {e}')
    
    elif mode == 'off':
        try:
            await ctx.guild.edit(verification_level=discord.VerificationLevel.low)
            data_manager.update_guild_setting(ctx.guild.id, 'anti_raid_enabled', False)
            
            await ctx.send('⚠️ anti-raid mode disabled. verification restored')
            
            await log_action(
                ctx.guild,
                'anti-raid disabled',
                f'moderator: {ctx.author.mention}',
                discord.Color.orange()
            )
        except Exception as e:
            await ctx.send(f'failed to disable anti-raid: {e}')
    
    else:
        await ctx.send('use `+antiraid on` or `+antiraid off`')

@bot.command(name='antinuke')
@is_owner_or_admin()
async def antinuke_cmd(ctx, mode: str):
    """toggle anti-nuke protection (on/off)"""
    mode = mode.lower()
    
    if mode == 'on':
        data_manager.update_guild_setting(ctx.guild.id, 'anti_nuke_enabled', True)
        await ctx.send('✅ anti-nuke protection enabled')
        
        await log_action(
            ctx.guild,
            'anti-nuke enabled',
            f'moderator: {ctx.author.mention}',
            discord.Color.green()
        )
    
    elif mode == 'off':
        data_manager.update_guild_setting(ctx.guild.id, 'anti_nuke_enabled', False)
        await ctx.send('⚠️ anti-nuke protection disabled')
        
        await log_action(
            ctx.guild,
            'anti-nuke disabled',
            f'moderator: {ctx.author.mention}',
            discord.Color.orange()
        )
    
    else:
        await ctx.send('use `+antinuke on` or `+antinuke off`')

# whitelist/blacklist commands
@bot.tree.command(name="whitelist_add", description="add user to whitelist")
@app_commands.describe(user="user to whitelist")
@is_owner()
async def whitelist_add(interaction: discord.Interaction, user: discord.User):
    """add someone to whitelist"""
    if data_manager.is_whitelisted(user.id):
        return await interaction.response.send_message(
            f'{user.mention} is already whitelisted',
            ephemeral=True
        )
    
    data_manager.add_to_whitelist(user.id)
    
    embed = discord.Embed(
        title='user whitelisted',
        description=f'{user.mention} added to whitelist',
        color=discord.Color.green()
    )
    embed.add_field(
        name='permissions',
        value='bypass spam detection\nbypass auto-moderation\nauthorized bot additions\ngrant roles without restrictions',
        inline=False
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    
    await interaction.response.send_message(embed=embed)
    
    await log_action(
        interaction.guild,
        'user whitelisted',
        f'user: {user.mention}\nadded by: {interaction.user.mention}',
        discord.Color.green()
    )

@bot.tree.command(name="whitelist_remove", description="remove user from whitelist")
@app_commands.describe(user="user to remove")
@is_owner()
async def whitelist_remove(interaction: discord.Interaction, user: discord.User):
    """remove someone from whitelist"""
    if not data_manager.is_whitelisted(user.id):
        return await interaction.response.send_message(
            f'{user.mention} is not whitelisted',
            ephemeral=True
        )
    
    data_manager.remove_from_whitelist(user.id)
    
    embed = discord.Embed(
        title='removed from whitelist',
        description=f'{user.mention} removed from whitelist',
        color=discord.Color.red()
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    
    await interaction.response.send_message(embed=embed)
    
    await log_action(
        interaction.guild,
        'user removed from whitelist',
        f'user: {user.mention}\nremoved by: {interaction.user.mention}',
        discord.Color.orange()
    )

@bot.tree.command(name="whitelist_list", description="view whitelisted users")
@is_owner()
async def whitelist_list(interaction: discord.Interaction):
    """list all whitelisted users"""
    if not data_manager.whitelist:
        return await interaction.response.send_message(
            'whitelist is empty',
            ephemeral=True
        )
    
    user_list = []
    for user_id in data_manager.whitelist:
        user = bot.get_user(user_id)
        if user:
            user_list.append(f'{user.mention} (id: {user_id})')
        else:
            user_list.append(f'unknown user (id: {user_id})')
    
    embed = discord.Embed(
        title='whitelisted users',
        description='\n'.join(user_list),
        color=discord.Color.blue()
    )
    embed.set_footer(text=f'total: {len(data_manager.whitelist)} users')
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="blacklist_add", description="add user to blacklist")
@app_commands.describe(user="user to blacklist", reason="reason for blacklisting")
@is_owner()
async def blacklist_add(interaction: discord.Interaction, user: discord.User, reason: str = "no reason given"):
    """add someone to blacklist"""
    if data_manager.is_blacklisted(user.id):
        return await interaction.response.send_message(
            f'{user.mention} is already blacklisted',
            ephemeral=True
        )
    
    data_manager.add_to_blacklist(user.id)
    
    embed = discord.Embed(
        title='user blacklisted',
        description=f'{user.mention} added to blacklist',
        color=discord.Color.dark_red()
    )
    embed.add_field(name='reason', value=reason, inline=False)
    embed.add_field(
        name='effects',
        value='cannot verify\nmessages auto-deleted\nauto-timeout on message\nauto-kick on join',
        inline=False
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    
    await interaction.response.send_message(embed=embed)
    
    await log_action(
        interaction.guild,
        'user blacklisted',
        f'user: {user.mention}\nadded by: {interaction.user.mention}',
        discord.Color.dark_red(),
        [('reason', reason)]
    )

@bot.tree.command(name="blacklist_remove", description="remove user from blacklist")
@app_commands.describe(user="user to remove")
@is_owner()
async def blacklist_remove(interaction: discord.Interaction, user: discord.User):
    """remove someone from blacklist"""
    if not data_manager.is_blacklisted(user.id):
        return await interaction.response.send_message(
            f'{user.mention} is not blacklisted',
            ephemeral=True
        )
    
    data_manager.remove_from_blacklist(user.id)
    
    embed = discord.Embed(
        title='removed from blacklist',
        description=f'{user.mention} removed from blacklist',
        color=discord.Color.green()
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    
    await interaction.response.send_message(embed=embed)
    
    await log_action(
        interaction.guild,
        'user removed from blacklist',
        f'user: {user.mention}\nremoved by: {interaction.user.mention}',
        discord.Color.green()
    )

@bot.tree.command(name="blacklist_list", description="view blacklisted users")
@is_owner()
async def blacklist_list(interaction: discord.Interaction):
    """list all blacklisted users"""
    if not data_manager.blacklist:
        return await interaction.response.send_message(
            'blacklist is empty',
            ephemeral=True
        )
    
    user_list = []
    for user_id in data_manager.blacklist:
        user = bot.get_user(user_id)
        if user:
            user_list.append(f'{user.mention} (id: {user_id})')
        else:
            user_list.append(f'unknown user (id: {user_id})')
    
    embed = discord.Embed(
        title='blacklisted users',
        description='\n'.join(user_list),
        color=discord.Color.dark_red()
    )
    embed.set_footer(text=f'total: {len(data_manager.blacklist)} users')
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

"""
Part 5: Ticket System
full ticket system with buttons and everything
"""

# ticket colors
ticket_colors = {
    'partnership': 0x5865F2,
    'middleman': 0xFEE75C,
    'support': 0x57F287,
    'error': 0xED4245,
    'success': 0x57F287,
    'info': 0x5865F2
}

# ticket button view
class TicketButtons(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='partnership', emoji='🤝', style=discord.ButtonStyle.primary, custom_id='ticket_partnership')
    async def partnership_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        try:
            await create_ticket(interaction.guild, interaction.user, 'partnership')
            await interaction.followup.send('✅ ticket created! check the ticket channel', ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send('❌ i dont have permission to create channels', ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f'❌ error: {str(e)}', ephemeral=True)

    @discord.ui.button(label='middleman', emoji='⚖️', style=discord.ButtonStyle.secondary, custom_id='ticket_middleman')
    async def middleman_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        try:
            await create_ticket(interaction.guild, interaction.user, 'middleman')
            await interaction.followup.send('✅ ticket created! check the ticket channel', ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send('❌ i dont have permission to create channels', ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f'❌ error: {str(e)}', ephemeral=True)

    @discord.ui.button(label='support', emoji='🎫', style=discord.ButtonStyle.success, custom_id='ticket_support')
    async def support_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        try:
            await create_ticket(interaction.guild, interaction.user, 'support')
            await interaction.followup.send('✅ ticket created! check the ticket channel', ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send('❌ i dont have permission to create channels', ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f'❌ error: {str(e)}', ephemeral=True)

# close ticket view
class CloseTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='close ticket', emoji='🔒', style=discord.ButtonStyle.danger, custom_id='confirm_close')
    async def close_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        await close_ticket(interaction.channel, interaction.user)

async def create_ticket(guild: discord.Guild, user: discord.Member, ticket_type: str):
    """create a new ticket"""
    try:
        # get or create ticket category
        category = discord.utils.get(guild.categories, name='tickets')
        if not category:
            category = await guild.create_category('tickets')
        
        # permissions
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True, 
                send_messages=True, 
                read_message_history=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True
            )
        }
        
        # create channel
        ticket_channel = await guild.create_text_channel(
            name=f'ticket-{user.name}-{ticket_type}',
            category=category,
            overwrites=overwrites
        )
        
        # save to database
        data_manager.db.execute("""
            INSERT INTO tickets (channel_id, guild_id, user_id, ticket_type)
            VALUES (%s, %s, %s, %s)
        """, (ticket_channel.id, guild.id, user.id, ticket_type))
        
        # check for ticket role
        role_to_ping = None
        result = data_manager.db.execute("""
            SELECT role_id FROM ticket_roles
            WHERE guild_id = %s AND ticket_type = %s
        """, (guild.id, ticket_type), fetch=True)
        
        if result:
            role_to_ping = guild.get_role(result[0][0])
        
        if role_to_ping:
            ping_message = f"{role_to_ping.mention} - new {ticket_type} ticket!"
            await ticket_channel.send(ping_message, allowed_mentions=discord.AllowedMentions(roles=True))
        
        # ticket info embed
        embed = discord.Embed(
            title=f'🎫 {ticket_type.title()} ticket',
            description=f"hey {user.mention}!\n\nour team will be with you soon. describe your issue in detail",
            color=ticket_colors.get(ticket_type, discord.Color.blue())
        )
        embed.add_field(
            name='📌 commands',
            value='`+close` - close this ticket\n`+claim` - claim this ticket\n`+add <user>` - add a user\n`+remove <user>` - remove a user',
            inline=False
        )
        embed.set_footer(text=f'ticket by {user}', icon_url=user.display_avatar.url)
        embed.timestamp = datetime.utcnow()
        
        await ticket_channel.send(content=user.mention, embed=embed, view=CloseTicketView())
        
        await log_action(
            guild,
            'ticket created',
            f'user: {user.mention}\ntype: {ticket_type}\nchannel: {ticket_channel.mention}',
            discord.Color.green()
        )
        
    except Exception as e:
        logging.error(f'ticket creation failed: {e}')
        raise

async def close_ticket(channel: discord.TextChannel, user: discord.Member):
    """close a ticket"""
    # get ticket data
    result = data_manager.db.execute("""
        SELECT user_id, ticket_type FROM tickets WHERE channel_id = %s
    """, (channel.id,), fetch=True)
    
    ticket_data = result[0] if result else None

    embed = discord.Embed(
        title='🔒 ticket closed',
        description=f'ticket closed by {user.mention}',
        color=ticket_colors['error']
    )
    embed.timestamp = datetime.utcnow()

    await channel.send(embed=embed)

    # log it
    await log_action(
        channel.guild,
        'ticket closed',
        f'channel: {channel.name}\nclosed by: {user.mention}',
        discord.Color.red(),
        [('type', ticket_data[1] if ticket_data else 'unknown')]
    )

    # delete from database
    data_manager.db.execute("DELETE FROM tickets WHERE channel_id = %s", (channel.id,))

    await asyncio.sleep(5)
    await channel.delete()

# ticket setup command
@bot.command(name='ticketsetup')
@is_owner_or_admin()
async def ticket_setup(ctx):
    """create the ticket panel"""
    embed = discord.Embed(
        title='🎫 support ticket system',
        description=(
            '> **need help? open a ticket!**\n'
            '> our team is ready to help you 24/7\n\n'
            '**choose your ticket type:**'
        ),
        color=0x5865F2
    )
    
    embed.add_field(
        name='🤝 partnership',
        value='```\nbusiness collaborations\nand partnership opportunities```',
        inline=True
    )
    
    embed.add_field(
        name='⚖️ middleman',
        value='```\nsecure trading services\nwith trusted middlemen```',
        inline=True
    )
    
    embed.add_field(
        name='🎫 support',
        value='```\ngeneral help and questions\ntechnical support```',
        inline=True
    )
    
    await ctx.send(embed=embed, view=TicketButtons())
    
    confirm = discord.Embed(
        description='✅ **ticket panel created!**',
        color=0x57F287
    )
    await ctx.reply(embed=confirm, delete_after=5)

# ticket commands
@bot.command(name='close')
async def close_command(ctx):
    """close a ticket"""
    if not ctx.channel.name.startswith('ticket-'):
        return await ctx.reply('❌ this only works in ticket channels')

    embed = discord.Embed(
        title='⚠️ close ticket',
        description='are you sure you want to close this ticket?',
        color=ticket_colors['error']
    )
    embed.set_footer(text='this cannot be undone')

    view = CloseTicketView()
    cancel_button = Button(label='cancel', style=discord.ButtonStyle.secondary)

    async def cancel_callback(interaction):
        await interaction.response.edit_message(content='❌ ticket closure cancelled', embed=None, view=None)

    cancel_button.callback = cancel_callback
    view.add_item(cancel_button)

    await ctx.reply(embed=embed, view=view)

@bot.command(name='claim')
async def claim_ticket(ctx):
    """claim a ticket"""
    if not ctx.channel.name.startswith('ticket-'):
        return await ctx.reply('❌ this only works in ticket channels')

    # check if already claimed
    result = data_manager.db.execute("""
        SELECT claimed_by FROM tickets WHERE channel_id = %s
    """, (ctx.channel.id,), fetch=True)
    
    if result and result[0][0]:
        return await ctx.reply('❌ this ticket is already claimed')

    # claim it
    data_manager.db.execute("""
        UPDATE tickets SET claimed_by = %s WHERE channel_id = %s
    """, (ctx.author.id, ctx.channel.id))
    
    # get ticket creator
    ticket_result = data_manager.db.execute("""
        SELECT user_id FROM tickets WHERE channel_id = %s
    """, (ctx.channel.id,), fetch=True)
    
    ticket_creator_id = ticket_result[0][0] if ticket_result else None
    ticket_creator = ctx.guild.get_member(ticket_creator_id) if ticket_creator_id else None
    
    # update permissions
    await ctx.channel.set_permissions(
        ctx.author,
        view_channel=True,
        send_messages=True,
        read_message_history=True
    )
    
    if ticket_creator:
        await ctx.channel.set_permissions(
            ticket_creator,
            view_channel=True,
            send_messages=True,
            read_message_history=True
        )
    
    embed = discord.Embed(
        description=f'✅ ticket claimed by {ctx.author.mention}\n\n🔒 **only the claimer and ticket creator can now send messages**',
        color=ticket_colors['success']
    )

    await ctx.send(embed=embed)
    await ctx.channel.edit(name=f"{ctx.channel.name}-claimed")

@bot.command(name='unclaim')
async def unclaim_ticket(ctx):
    """unclaim a ticket"""
    if not ctx.channel.name.startswith('ticket-'):
        return await ctx.reply('❌ this only works in ticket channels')

    result = data_manager.db.execute("""
        SELECT claimed_by FROM tickets WHERE channel_id = %s
    """, (ctx.channel.id,), fetch=True)
    
    if not result or not result[0][0]:
        return await ctx.reply('❌ this ticket is not claimed')

    claimer_id = result[0][0]
    if claimer_id != ctx.author.id and not ctx.author.guild_permissions.administrator:
        return await ctx.reply('❌ only the claimer or an admin can unclaim')

    # unclaim it
    data_manager.db.execute("""
        UPDATE tickets SET claimed_by = NULL WHERE channel_id = %s
    """, (ctx.channel.id,))
    
    claimer_member = ctx.guild.get_member(claimer_id)
    if claimer_member:
        await ctx.channel.set_permissions(claimer_member, overwrite=None)

    embed = discord.Embed(
        description=f'✅ ticket unclaimed by {ctx.author.mention}\n\n🔓 **all staff can now send messages again**',
        color=ticket_colors['info']
    )

    await ctx.send(embed=embed)
    new_name = ctx.channel.name.replace('-claimed', '')
    await ctx.channel.edit(name=new_name)

@bot.command(name='add')
async def add_to_ticket(ctx, member: discord.Member = None):
    """add someone to a ticket"""
    if not ctx.channel.name.startswith('ticket-'):
        return await ctx.reply('❌ this only works in ticket channels')

    if not member:
        return await ctx.reply('❌ mention a valid user')

    await ctx.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)

    embed = discord.Embed(
        description=f'✅ {member.mention} added to the ticket',
        color=ticket_colors['success']
    )

    await ctx.reply(embed=embed)

@bot.command(name='remove')
async def remove_from_ticket(ctx, member: discord.Member = None):
    """remove someone from a ticket"""
    if not ctx.channel.name.startswith('ticket-'):
        return await ctx.reply('❌ this only works in ticket channels')

    if not member:
        return await ctx.reply('❌ mention a valid user')

    await ctx.channel.set_permissions(member, overwrite=None)

    embed = discord.Embed(
        description=f'✅ {member.mention} removed from the ticket',
        color=ticket_colors['success']
    )

    await ctx.reply(embed=embed)

@bot.command(name='ticketrole')
@is_owner_or_admin()
async def ticket_role(ctx, ticket_type: str, role: discord.Role):
    """set which role gets pinged for tickets"""
    ticket_type = ticket_type.lower()
    
    if ticket_type not in ['partnership', 'middleman', 'support']:
        embed = discord.Embed(
            title='❌ invalid ticket type',
            description='valid types: `partnership`, `middleman`, `support`',
            color=ticket_colors['error']
        )
        return await ctx.send(embed=embed)
    
    # save to database
    data_manager.db.execute("""
        INSERT INTO ticket_roles (guild_id, ticket_type, role_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (guild_id, ticket_type)
        DO UPDATE SET role_id = %s
    """, (ctx.guild.id, ticket_type, role.id, role.id))
    
    embed = discord.Embed(
        title='✅ ticket role set',
        description=f'**{ticket_type}** tickets will now ping {role.mention}',
        color=ticket_colors['success']
    )
    await ctx.send(embed=embed)

@bot.command(name='ticketstats')
async def ticket_stats(ctx):
    """view ticket statistics"""
    # get all tickets for this guild
    result = data_manager.db.execute("""
        SELECT COUNT(*) FROM tickets WHERE guild_id = %s
    """, (ctx.guild.id,), fetch=True)
    
    total_tickets = result[0][0] if result else 0
    
    # get claimed tickets
    claimed_result = data_manager.db.execute("""
        SELECT COUNT(*) FROM tickets WHERE guild_id = %s AND claimed_by IS NOT NULL
    """, (ctx.guild.id,), fetch=True)
    
    claimed_tickets = claimed_result[0][0] if claimed_result else 0

    embed = discord.Embed(
        title='📊 ticket statistics',
        color=ticket_colors['info']
    )
    embed.add_field(name='🎫 active tickets', value=f'`{total_tickets}`', inline=True)
    embed.add_field(name='✅ claimed tickets', value=f'`{claimed_tickets}`', inline=True)
    embed.add_field(name='⏳ unclaimed tickets', value=f'`{total_tickets - claimed_tickets}`', inline=True)
    embed.set_footer(text=f'requested by {ctx.author}', icon_url=ctx.author.display_avatar.url)

    await ctx.reply(embed=embed)

# register persistent views on ready
@bot.event
async def on_ready_tickets():
    """register ticket views"""
    bot.add_view(TicketButtons())
    bot.add_view(CloseTicketView())

"""
Part 6: Utility Commands & Bot Launch (FINAL PART)
all the info commands and help menu
"""

# utility commands
@bot.command(name='ping')
async def ping_cmd(ctx):
    """check bot latency"""
    latency = round(bot.latency * 1000)
    
    embed = discord.Embed(
        title='pong! 🏓',
        description=f'latency: {latency}ms',
        color=discord.Color.green() if latency < 100 else discord.Color.orange() if latency < 200 else discord.Color.red()
    )
    
    await ctx.send(embed=embed)

@bot.command(name='serverinfo')
async def serverinfo_cmd(ctx):
    """view server info"""
    guild = ctx.guild
    
    embed = discord.Embed(
        title=f'{guild.name}',
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    
    embed.add_field(name='server id', value=str(guild.id), inline=True)
    embed.add_field(name='owner', value=guild.owner.mention, inline=True)
    embed.add_field(name='created', value=guild.created_at.strftime('%Y-%m-%d'), inline=True)
    
    embed.add_field(name='members', value=str(guild.member_count), inline=True)
    embed.add_field(name='roles', value=str(len(guild.roles)), inline=True)
    embed.add_field(name='channels', value=str(len(guild.channels)), inline=True)
    
    embed.add_field(name='text channels', value=str(len(guild.text_channels)), inline=True)
    embed.add_field(name='voice channels', value=str(len(guild.voice_channels)), inline=True)
    embed.add_field(name='boost level', value=str(guild.premium_tier), inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='userinfo')
async def userinfo_cmd(ctx, member: discord.Member = None):
    """view user info"""
    member = member or ctx.author
    
    embed = discord.Embed(
        title=f'{member.name}',
        color=member.color,
        timestamp=datetime.utcnow()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    
    embed.add_field(name='user id', value=str(member.id), inline=True)
    embed.add_field(name='nickname', value=member.nick or 'none', inline=True)
    embed.add_field(name='bot', value='yes' if member.bot else 'no', inline=True)
    
    embed.add_field(name='joined server', value=member.joined_at.strftime('%Y-%m-%d'), inline=True)
    embed.add_field(name='account created', value=member.created_at.strftime('%Y-%m-%d'), inline=True)
    
    roles = [role.mention for role in member.roles if role != ctx.guild.default_role]
    embed.add_field(name=f'roles ({len(roles)})', value=' '.join(roles) if roles else 'none', inline=False)
    
    # security info
    is_whitelisted = data_manager.is_whitelisted(member.id)
    is_blacklisted = data_manager.is_blacklisted(member.id)
    violations = data_manager.user_violations.get(member.id, 0)
    warnings = len(data_manager.get_warnings(member.id))
    
    security_info = []
    if is_whitelisted:
        security_info.append('✅ whitelisted')
    if is_blacklisted:
        security_info.append('❌ blacklisted')
    if violations > 0:
        security_info.append(f'{violations} violations')
    if warnings > 0:
        security_info.append(f'{warnings} warnings')
    
    if security_info:
        embed.add_field(name='security status', value=', '.join(security_info), inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='avatar')
async def avatar_cmd(ctx, member: discord.Member = None):
    """view someone's avatar"""
    member = member or ctx.author
    
    embed = discord.Embed(
        title=f"{member.display_name}'s avatar",
        color=member.color
    )
    embed.set_image(url=member.display_avatar.url)
    embed.add_field(name='avatar url', value=f'[click here]({member.display_avatar.url})', inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='botinfo')
async def botinfo_cmd(ctx):
    """view bot info"""
    embed = discord.Embed(
        title=f'{bot.user.name}',
        description='combined security & ticket bot - keeping your server safe',
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    
    embed.add_field(name='bot id', value=str(bot.user.id), inline=True)
    embed.add_field(name='servers', value=str(len(bot.guilds)), inline=True)
    embed.add_field(name='users', value=str(len(bot.users)), inline=True)
    
    embed.add_field(name='prefix', value=Config.PREFIX, inline=True)
    embed.add_field(name='latency', value=f'{round(bot.latency * 1000)}ms', inline=True)
    embed.add_field(name='owner', value=f'<@{Config.OWNER_ID}>', inline=True)
    
    embed.add_field(
        name='features',
        value='🛡️ anti-nuke protection\n🚫 anti-raid system\n🤖 auto-moderation\n🎫 ticket system\n👋 welcome/leave messages\n📊 invite tracking',
        inline=False
    )
    
    await ctx.send(embed=embed)

# help command
@bot.command(name='help')
async def help_cmd(ctx):
    """main help menu"""
    is_owner_user = ctx.author.id == Config.OWNER_ID
    is_admin = ctx.author.guild_permissions.administrator if ctx.guild else False
    is_mod = ctx.author.guild_permissions.kick_members or ctx.author.guild_permissions.ban_members if ctx.guild else False
    
    embed = discord.Embed(
        title='bot commands',
        description=f'prefix: `{Config.PREFIX}` | slash commands: `/`',
        color=discord.Color.blue()
    )
    
    if is_mod or is_admin or is_owner_user:
        embed.add_field(
            name='🛡️ moderation',
            value='`+kick` `+ban` `+unban` `+softban` `+timeout` `+untimeout`\n`+warn` `+warnings` `+clearwarnings` `+purge` `+purgeuser` `+slowmode`',
            inline=False
        )
    
    if is_admin or is_owner_user:
        embed.add_field(
            name='🔒 server security',
            value='`+lock` `+unlock` `+lockdown` `+unlockdown`\n`+antiraid` `+antinuke` `+automod`',
            inline=False
        )
        
        embed.add_field(
            name='👋 welcome/leave',
            value='`+setwelcome` `+setleave` `+welcomemsg` `+leavemsg`',
            inline=False
        )
        
        embed.add_field(
            name='📊 invite tracking',
            value='`+invitetracking` `+invites` +setinvitetracker` +whoinvited`',
            inline=False
        )
    
    if is_owner_user:
        embed.add_field(
            name='⚙️ whitelist/blacklist',
            value='`/whitelist_add` `/whitelist_remove` `/whitelist_list`\n`/blacklist_add` `/blacklist_remove` `/blacklist_list`',
            inline=False
        )
    
    embed.add_field(
        name='🎫 tickets',
        value='`+ticketsetup` `+close` `+claim` `+unclaim`\n`+add` `+remove` `+ticketrole` `+ticketstats`',
        inline=False
    )
    
    embed.add_field(
        name='ℹ️ utility',
        value='`+ping` `+serverinfo` `+userinfo` `+avatar` `+botinfo`',
        inline=False
    )
    
    settings = data_manager.get_guild_settings(ctx.guild.id)
    embed.add_field(
        name='🛡️ protection status',
        value=f'anti-nuke: {"✅" if settings.get("anti_nuke_enabled", True) else "❌"}\n'
              f'anti-raid: {"✅" if settings.get("anti_raid_enabled", True) else "❌"}\n'
              f'auto-mod: {"✅" if settings.get("automod_enabled", True) else "❌"}',
        inline=False
    )
    
    embed.set_footer(text=f'requested by {ctx.author}')
    
    await ctx.send(embed=embed)

# error handlers
@bot.event
async def on_command_error(ctx, error):
    """handle command errors"""
    if isinstance(error, commands.CommandNotFound):
        return
    
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send('❌ you dont have permission to use this command')
    
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f'❌ missing required argument: `{error.param.name}`')
    
    elif isinstance(error, commands.BadArgument):
        await ctx.send('❌ invalid argument provided')
    
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send('❌ member not found')
    
    elif isinstance(error, commands.UserNotFound):
        await ctx.send('❌ user not found')
    
    elif isinstance(error, commands.RoleNotFound):
        await ctx.send('❌ role not found')
    
    elif isinstance(error, commands.ChannelNotFound):
        await ctx.send('❌ channel not found')
    
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f'⏰ this command is on cooldown. try again in {error.retry_after:.1f}s')
    
    else:
        logging.error(f'command error in {ctx.command}: {error}')
        await ctx.send('❌ an error occurred while executing this command')

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """handle slash command errors"""
    if isinstance(error, app_commands.CheckFailure):
        return
    
    elif isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            '❌ you dont have permission to use this command',
            ephemeral=True
        )
    
    elif isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f'⏰ this command is on cooldown. try again in {error.retry_after:.1f}s',
            ephemeral=True
        )
    
    else:
        logging.error(f'slash command error: {error}')
        try:
            await interaction.response.send_message(
                '❌ an error occurred',
                ephemeral=True
            )
        except:
            pass

# web server for keeping bot alive on render
from aiohttp import web

async def start_web_server():
    """start web server for render"""
    
    async def health(request):
        return web.Response(
            text='bot online!',
            status=200,
            content_type='text/plain'
        )
    
    async def status_page(request):
        settings_counts = {}
        for guild in bot.guilds:
            settings = data_manager.get_guild_settings(guild.id)
            settings_counts[guild.name] = {
                'anti_nuke': settings.get('anti_nuke_enabled', True),
                'anti_raid': settings.get('anti_raid_enabled', True),
                'automod': settings.get('automod_enabled', True)
            }
        
        html = f'''
<!DOCTYPE html>
<html>
<head>
    <title>discord bot</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }}
        .container {{
            text-align: center;
            padding: 40px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 20px;
            backdrop-filter: blur(10px);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }}
        h1 {{
            font-size: 48px;
            margin: 0 0 20px 0;
        }}
        .status {{
            font-size: 24px;
            margin: 20px 0;
        }}
        .info {{
            font-size: 18px;
            margin: 10px 0;
            opacity: 0.9;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 bot online</h1>
        <div class="status">✅ running</div>
        <div class="info">servers: {len(bot.guilds)}</div>
        <div class="info">users: {len(bot.users)}</div>
        <div class="info">prefix: {Config.PREFIX}</div>
        <div class="info">latency: {round(bot.latency * 1000)}ms</div>
    </div>
</body>
</html>
        '''
        return web.Response(
            text=html,
            content_type='text/html'
        )
    
    app = web.Application()
    app.router.add_get('/', status_page)
    app.router.add_get('/health', health)
    app.router.add_get('/ping', health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', Config.PORT)
    await site.start()
    
    logging.info(f'web server running on port {Config.PORT}')

# main function
async def main():
    """main bot startup"""
    await start_web_server()
    
    try:
        await bot.start(Config.TOKEN)
    except KeyboardInterrupt:
        logging.info('bot shutdown requested')
        await bot.close()
    except Exception as e:
        logging.error(f'bot error: {e}')
        await bot.close()

# run the bot
if __name__ == '__main__':
    print('=' * 70)
    print('combined discord bot starting up')
    print('=' * 70)
    print(f'owner id: {Config.OWNER_ID}')
    print(f'prefix: {Config.PREFIX}')
    print(f'port: {Config.PORT}')
    print('=' * 70)
    
    if not Config.TOKEN:
        logging.error('DISCORD_BOT_TOKEN not set!')
        print('\nerror: DISCORD_BOT_TOKEN not found!')
        print('set it in your environment variables')
        exit(1)
    
    if not Config.DATABASE_URL:
        logging.warning('DATABASE_URL not set! bot will not save data')
        print('\nwarning: no database url found')
        print('data will not persist across restarts')
        print('set DATABASE_URL in your environment variables')
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info('bot stopped by user')
    except Exception as e:
        logging.error(f'failed to start bot: {e}')
        print(f'\nfailed to start: {e}')
