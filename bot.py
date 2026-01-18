"""
Discord Security Bot - Complete with Anti-Alt Detection
Made for Render + PostgreSQL + 24/7 uptime

SECTION 1: IMPORTS + CONFIGURATION
Copy this entire thing first!
"""

import os
import re
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Set
from collections import defaultdict
from difflib import SequenceMatcher
from urllib.parse import urlparse

import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import Button, View, Modal, TextInput, Select

import psycopg2
from psycopg2.extras import RealDictCursor, Json

from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%I:%M:%S %p'
)
logger = logging.getLogger('SecurityBot')

# ============================================
# CONFIGURATION - CHANGE THESE VALUES
# ============================================

class Config:
    """Bot configuration"""
    TOKEN = os.getenv('DISCORD_TOKEN')
    DATABASE_URL = os.getenv('DATABASE_URL')
    PREFIX = '!'
    OWNER_ID = 1029438856069656576  # CHANGE THIS TO YOUR ID
    PORT = int(os.getenv('PORT', 8080))
    
    # Alt detection settings
    MIN_ACCOUNT_AGE = 7  # days
    VERY_NEW_ACCOUNT = 3  # days
    USERNAME_SIMILARITY = 0.75  # 75% similar = suspicious
    NO_AVATAR_SUSPICIOUS = True
    
    # Auto actions
    AUTO_KICK_ALTS = False
    AUTO_TIMEOUT_ALTS = True
    TIMEOUT_DURATION = 30  # minutes
    
    # Raid protection
    RAID_JOIN_THRESHOLD = 10
    RAID_JOIN_WINDOW = 10  # seconds
    
    # Colors
    SUCCESS = 0x57F287
    WARNING = 0xFEE75C
    DANGER = 0xED4245
    INFO = 0x5865F2

# ============================================
# SECTION 2: DATABASE
# Paste this right after Section 1
# ============================================

class Database:
    """PostgreSQL database handler"""
    
    def __init__(self):
        self.conn = None
        self.connect()
        self.create_tables()
    
    def connect(self):
        """Connect to PostgreSQL"""
        try:
            if not Config.DATABASE_URL:
                logger.warning('⚠️ No DATABASE_URL found!')
                return
            
            result = urlparse(Config.DATABASE_URL)
            self.conn = psycopg2.connect(
                database=result.path[1:],
                user=result.username,
                password=result.password,
                host=result.hostname,
                port=result.port
            )
            logger.info('✅ Connected to PostgreSQL!')
        except Exception as e:
            logger.error(f'❌ Database connection failed: {e}')
    
    def create_tables(self):
        """Create all database tables"""
        if not self.conn:
            return
        
        try:
            cur = self.conn.cursor()
            
            # Alt detections table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alt_detections (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    username TEXT,
                    suspicion_score INTEGER,
                    suspicion_level TEXT,
                    reasons TEXT[],
                    similar_to_user_id BIGINT,
                    similar_to_username TEXT,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    action_taken TEXT,
                    kicked BOOLEAN DEFAULT FALSE,
                    timed_out BOOLEAN DEFAULT FALSE
                )
            """)
            
            # User tracking table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_tracking (
                    user_id BIGINT,
                    guild_id BIGINT,
                    username TEXT,
                    discriminator TEXT,
                    avatar_url TEXT,
                    account_created_at TIMESTAMP,
                    first_joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    join_count INTEGER DEFAULT 1,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)
            
            # Whitelist table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS whitelist (
                    guild_id BIGINT,
                    user_id BIGINT,
                    added_by BIGINT,
                    reason TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            
            # Guild settings table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id BIGINT PRIMARY KEY,
                    alt_detection_enabled BOOLEAN DEFAULT TRUE,
                    auto_timeout_alts BOOLEAN DEFAULT TRUE,
                    timeout_duration INTEGER DEFAULT 30,
                    min_account_age INTEGER DEFAULT 7,
                    log_channel_id BIGINT
                )
            """)
            
            self.conn.commit()
            cur.close()
            logger.info('✅ Database tables ready!')
        except Exception as e:
            logger.error(f'❌ Failed to create tables: {e}')
    
    def execute(self, query: str, params: tuple = None, fetch: bool = False):
        """Execute database query"""
        if not self.conn:
            return None
        
        try:
            cur = self.conn.cursor(cursor_factory=RealDictCursor)
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
            logger.error(f'Query failed: {e}')
            if self.conn:
                self.conn.rollback()
            return None

class DataManager:
    """Manages all bot data"""
    
    def __init__(self):
        self.db = Database()
        self.whitelist_cache = defaultdict(set)
        self.load_whitelist()
    
    def load_whitelist(self):
        """Load whitelist into cache"""
        result = self.db.execute("SELECT guild_id, user_id FROM whitelist", fetch=True)
        if result:
            for row in result:
                self.whitelist_cache[row['guild_id']].add(row['user_id'])
    
    def is_whitelisted(self, guild_id: int, user_id: int) -> bool:
        """Check if user is whitelisted"""
        return user_id in self.whitelist_cache.get(guild_id, set())
    
    def add_to_whitelist(self, guild_id: int, user_id: int, added_by: int, reason: str = 'No reason'):
        """Add user to whitelist"""
        self.whitelist_cache[guild_id].add(user_id)
        return self.db.execute("""
            INSERT INTO whitelist (guild_id, user_id, added_by, reason)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (guild_id, user_id, added_by, reason))
    
    def remove_from_whitelist(self, guild_id: int, user_id: int):
        """Remove user from whitelist"""
        self.whitelist_cache[guild_id].discard(user_id)
        return self.db.execute("""
            DELETE FROM whitelist WHERE guild_id = %s AND user_id = %s
        """, (guild_id, user_id))
    
    def save_alt_detection(self, guild_id: int, user_id: int, username: str,
                          score: int, level: str, reasons: List[str],
                          similar_to: int = None, similar_username: str = None,
                          action: str = 'none'):
        """Save alt detection"""
        return self.db.execute("""
            INSERT INTO alt_detections 
            (guild_id, user_id, username, suspicion_score, suspicion_level, 
             reasons, similar_to_user_id, similar_to_username, action_taken,
             kicked, timed_out)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (guild_id, user_id, username, score, level, reasons,
              similar_to, similar_username, action,
              action == 'kicked', action == 'timeout'))
    
    def track_user_join(self, guild_id: int, member: discord.Member):
        """Track user join"""
        return self.db.execute("""
            INSERT INTO user_tracking 
            (user_id, guild_id, username, discriminator, avatar_url, account_created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, guild_id) 
            DO UPDATE SET 
                last_joined_at = CURRENT_TIMESTAMP,
                join_count = user_tracking.join_count + 1
        """, (member.id, guild_id, member.name, member.discriminator,
              str(member.display_avatar.url) if member.avatar else None,
              member.created_at))
    
    def get_recent_joins(self, guild_id: int, minutes: int = 10):
        """Get recent joins"""
        return self.db.execute("""
            SELECT * FROM user_tracking
            WHERE guild_id = %s 
            AND last_joined_at >= CURRENT_TIMESTAMP - INTERVAL '%s minutes'
            ORDER BY last_joined_at DESC
        """, (guild_id, minutes), fetch=True)
    
    def get_alt_detections(self, guild_id: int, limit: int = 50):
        """Get alt detections"""
        return self.db.execute("""
            SELECT * FROM alt_detections
            WHERE guild_id = %s
            ORDER BY detected_at DESC
            LIMIT %s
        """, (guild_id, limit), fetch=True)

data_manager = DataManager()

# ============================================
# SECTION 3: BOT SETUP & HELPER FUNCTIONS
# Paste this right after Section 2
# ============================================

intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix=Config.PREFIX,
    intents=intents,
    help_command=None,
    case_insensitive=True,
    owner_id=Config.OWNER_ID
)

# Helper Functions
def is_staff():
    """Check if user is staff or admin"""
    async def predicate(ctx):
        if ctx.author.id == Config.OWNER_ID:
            return True
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

async def get_log_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """Get or create log channel"""
    channel = discord.utils.get(guild.text_channels, name='security-logs')
    
    if not channel:
        try:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }
            channel = await guild.create_text_channel(
                'security-logs',
                overwrites=overwrites,
                reason='Security log channel'
            )
        except:
            return None
    
    return channel

async def log_action(guild: discord.Guild, title: str, description: str, 
                    color: int, fields: List[tuple] = None):
    """Send log message"""
    channel = await get_log_channel(guild)
    if not channel:
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
        await channel.send(embed=embed)
    except:
        pass

# Bot Events
@bot.event
async def on_ready():
    """Bot startup"""
    print('\n' + '='*60)
    print('  🛡️  SECURITY BOT ONLINE  🛡️')
    print('='*60)
    print(f'\n📱 Bot: {bot.user.name}')
    print(f'🆔 ID: {bot.user.id}')
    print(f'🏠 Servers: {len(bot.guilds)}')
    print(f'👥 Users: {len(bot.users)}')
    print(f'⚙️  Prefix: {Config.PREFIX}')
    print(f'\n💚 Status: READY\n')
    print('='*60 + '\n')
    
    try:
        synced = await bot.tree.sync()
        logger.info(f'✅ Synced {len(synced)} slash commands')
    except Exception as e:
        logger.error(f'Failed to sync commands: {e}')
    
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="for suspicious activity 👀"
        ),
        status=discord.Status.online
    )
    
    if not cleanup_task.is_running():
        cleanup_task.start()

@tasks.loop(hours=1)
async def cleanup_task():
    """Cleanup task runs every hour"""
    try:
        logger.info('Running cleanup...')
        # Add cleanup logic here if needed
    except Exception as e:
        logger.error(f'Cleanup failed: {e}')

@cleanup_task.before_loop
async def before_cleanup():
    """Wait for bot to be ready"""
    await bot.wait_until_ready()

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors"""
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send('❌ You don\'t have permission to use that command!')
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f'❌ Missing argument: `{error.param.name}`')
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send('❌ I couldn\'t find that member!')
    else:
        logger.error(f'Command error: {error}')

# Basic Commands
@bot.command(name='ping')
async def ping(ctx):
    """Check bot latency"""
    latency = round(bot.latency * 1000)
    embed = discord.Embed(
        title='🏓 Pong!',
        description=f'Latency: **{latency}ms**',
        color=Config.SUCCESS if latency < 100 else Config.WARNING
    )
    await ctx.send(embed=embed)

@bot.command(name='info')
async def info(ctx):
    """Show bot info"""
    embed = discord.Embed(
        title='🛡️ Security Bot',
        description='Advanced server protection with alt detection',
        color=Config.INFO
    )
    embed.add_field(name='Servers', value=str(len(bot.guilds)), inline=True)
    embed.add_field(name='Users', value=str(len(bot.users)), inline=True)
    embed.add_field(name='Prefix', value=Config.PREFIX, inline=True)
    embed.add_field(
        name='Features',
        value='• Alt Detection\n• Anti-Raid\n• Auto Actions\n• Logging',
        inline=False
    )
    await ctx.send(embed=embed)

# ============================================
# SECTION 4: ANTI-ALT DETECTION SYSTEM
# Paste this right after Section 3
# ============================================

class AltDetector:
    """Detects alt accounts"""
    
    def __init__(self):
        self.recent_joins = defaultdict(list)  # guild_id: [(member, timestamp)]
    
    def calculate_username_similarity(self, name1: str, name2: str) -> float:
        """Calculate how similar two usernames are"""
        clean1 = re.sub(r'[^a-z0-9]', '', name1.lower())
        clean2 = re.sub(r'[^a-z0-9]', '', name2.lower())
        
        if not clean1 or not clean2:
            return 0.0
        
        return SequenceMatcher(None, clean1, clean2).ratio()
    
    def check_account_age(self, member: discord.Member) -> tuple:
        """Check if account is suspiciously new"""
        age = (datetime.utcnow() - member.created_at).days
        
        if age < Config.VERY_NEW_ACCOUNT:
            return True, age, 3  # Very suspicious = 3 points
        elif age < Config.MIN_ACCOUNT_AGE:
            return True, age, 1  # Suspicious = 1 point
        else:
            return False, age, 0
    
    def check_avatar(self, member: discord.Member) -> tuple:
        """Check if member has custom avatar"""
        if Config.NO_AVATAR_SUSPICIOUS and member.avatar is None:
            return True, 1  # No avatar = 1 point
        return False, 0
    
    def check_similar_usernames(self, member: discord.Member, recent_members: List) -> tuple:
        """Check for similar usernames in recent joins"""
        similar_members = []
        
        for other in recent_members:
            if other.id == member.id:
                continue
            
            similarity = self.calculate_username_similarity(member.name, other.name)
            
            if similarity >= Config.USERNAME_SIMILARITY:
                similar_members.append((other, similarity))
        
        if similar_members:
            return True, similar_members, 2  # Similar username = 2 points
        return False, [], 0
    
    def check_pattern_username(self, username: str) -> tuple:
        """Check for pattern usernames like User1, User2, etc"""
        # Pattern: word + number
        pattern = r'^([a-zA-Z]+)(\d+)$'
        match = re.match(pattern, username)
        
        if match:
            return True, 1  # Pattern username = 1 point
        return False, 0
    
    async def detect_alt(self, member: discord.Member, guild: discord.Guild):
        """Main alt detection function"""
        
        # Skip if whitelisted or bot owner
        if data_manager.is_whitelisted(guild.id, member.id) or member.id == Config.OWNER_ID:
            return
        
        # Skip bots
        if member.bot:
            return
        
        # Track this join
        data_manager.track_user_join(guild.id, member)
        
        # Get recent joins
        recent_data = data_manager.get_recent_joins(guild.id, 10)
        recent_members = []
        
        for data in recent_data or []:
            m = guild.get_member(data['user_id'])
            if m and m.id != member.id:
                recent_members.append(m)
        
        # Calculate suspicion score
        suspicion_score = 0
        reasons = []
        similar_to = None
        similar_username = None
        
        # Check 1: Account age
        is_new, age_days, age_points = self.check_account_age(member)
        if is_new:
            suspicion_score += age_points
            if age_points == 3:
                reasons.append(f"⚠️ Very new account ({age_days} days old)")
            else:
                reasons.append(f"⚠️ New account ({age_days} days old)")
        
        # Check 2: Avatar
        no_avatar, avatar_points = self.check_avatar(member)
        if no_avatar:
            suspicion_score += avatar_points
            reasons.append("⚠️ No custom avatar")
        
        # Check 3: Similar usernames
        has_similar, similar_list, similar_points = self.check_similar_usernames(member, recent_members)
        if has_similar:
            suspicion_score += similar_points
            similar_to = similar_list[0][0].id
            similar_username = similar_list[0][0].name
            similarity_pct = int(similar_list[0][1] * 100)
            reasons.append(f"⚠️ Username {similarity_pct}% similar to {similar_list[0][0].name}")
        
        # Check 4: Pattern username
        is_pattern, pattern_points = self.check_pattern_username(member.name)
        if is_pattern:
            suspicion_score += pattern_points
            reasons.append("⚠️ Pattern username detected")
        
        # Determine suspicion level
        if suspicion_score >= 6:
            level = 'CRITICAL'
            color = Config.DANGER
        elif suspicion_score >= 4:
            level = 'HIGH'
            color = Config.DANGER
        elif suspicion_score >= 2:
            level = 'MEDIUM'
            color = Config.WARNING
        else:
            level = 'LOW'
            color = Config.INFO
        
        # Only alert if score is high enough
        if suspicion_score < 2:
            return
        
        # Take action based on level
        action_taken = 'none'
        
        if suspicion_score >= 6 and Config.AUTO_TIMEOUT_ALTS:
            try:
                await member.timeout(
                    timedelta(minutes=Config.TIMEOUT_DURATION),
                    reason=f'Alt detection: {level} suspicion ({suspicion_score} points)'
                )
                action_taken = 'timeout'
            except:
                pass
        
        # Save to database
        data_manager.save_alt_detection(
            guild.id, member.id, member.name,
            suspicion_score, level, reasons,
            similar_to, similar_username, action_taken
        )
        
        # Send alert
        embed = discord.Embed(
            title=f'🚨 Alt Account Detected - {level}',
            description=f'{member.mention} joined with suspicion level **{level}**',
            color=color,
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name='User', value=f'{member.name}#{member.discriminator}', inline=True)
        embed.add_field(name='ID', value=str(member.id), inline=True)
        embed.add_field(name='Score', value=f'{suspicion_score} points', inline=True)
        
        embed.add_field(
            name='Reasons',
            value='\n'.join(reasons) if reasons else 'None',
            inline=False
        )
        
        if similar_to:
            embed.add_field(
                name='Similar To',
                value=f'{similar_username} (ID: {similar_to})',
                inline=False
            )
        
        if action_taken != 'none':
            embed.add_field(
                name='Action Taken',
                value=f'✅ User was timed out for {Config.TIMEOUT_DURATION} minutes',
                inline=False
            )
        
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f'Account created')
        embed.timestamp = member.created_at
        
        await log_action(
            guild,
            f'Alt Detection - {level}',
            f'{member.mention} flagged as potential alt',
            color,
            [('Suspicion Score', f'{suspicion_score} points')]
        )
        
        # Send detailed embed
        log_channel = await get_log_channel(guild)
        if log_channel:
            await log_channel.send(embed=embed)

alt_detector = AltDetector()

# Member join event
@bot.event
async def on_member_join(member: discord.Member):
    """Called when someone joins the server"""
    try:
        await alt_detector.detect_alt(member, member.guild)
    except Exception as e:
        logger.error(f'Alt detection failed: {e}')

# ============================================
# SECTION 5: COMMANDS + HELP MENU
# Paste this right after Section 4
# ============================================

# Whitelist Commands
@bot.command(name='whitelist')
@is_staff()
async def whitelist_add(ctx, member: discord.Member, *, reason: str = 'No reason provided'):
    """Add someone to whitelist (bypasses all checks)"""
    data_manager.add_to_whitelist(ctx.guild.id, member.id, ctx.author.id, reason)
    
    embed = discord.Embed(
        title='✅ User Whitelisted',
        description=f'{member.mention} has been added to the whitelist',
        color=Config.SUCCESS
    )
    embed.add_field(name='Reason', value=reason, inline=False)
    embed.add_field(name='Added By', value=ctx.author.mention, inline=True)
    
    await ctx.send(embed=embed)
    
    await log_action(
        ctx.guild,
        'User Whitelisted',
        f'{member.mention} added to whitelist by {ctx.author.mention}',
        Config.SUCCESS,
        [('Reason', reason)]
    )

@bot.command(name='unwhitelist')
@is_staff()
async def whitelist_remove(ctx, member: discord.Member):
    """Remove someone from whitelist"""
    if not data_manager.is_whitelisted(ctx.guild.id, member.id):
        return await ctx.send('❌ That user is not whitelisted!')
    
    data_manager.remove_from_whitelist(ctx.guild.id, member.id)
    
    embed = discord.Embed(
        title='❌ User Removed from Whitelist',
        description=f'{member.mention} has been removed from the whitelist',
        color=Config.WARNING
    )
    
    await ctx.send(embed=embed)

@bot.command(name='checkalt')
@is_staff()
async def check_alt(ctx, member: discord.Member):
    """Manually check if someone is an alt"""
    await ctx.send(f'🔍 Checking {member.mention}...')
    
    # Run detection
    await alt_detector.detect_alt(member, ctx.guild)
    
    await ctx.send('✅ Check complete! See security logs for details.')

@bot.command(name='althistory')
@is_staff()
async def alt_history(ctx, limit: int = 10):
    """View recent alt detections"""
    if limit > 50:
        limit = 50
    
    detections = data_manager.get_alt_detections(ctx.guild.id, limit)
    
    if not detections:
        return await ctx.send('No alt detections found!')
    
    embed = discord.Embed(
        title=f'🚨 Recent Alt Detections',
        description=f'Showing last {len(detections)} detections',
        color=Config.INFO
    )
    
    for detection in detections[:10]:
        user_id = detection['user_id']
        username = detection['username']
        level = detection['suspicion_level']
        score = detection['suspicion_score']
        detected_at = detection['detected_at'].strftime('%Y-%m-%d %H:%M')
        
        embed.add_field(
            name=f'{username} (ID: {user_id})',
            value=f'Level: **{level}** ({score} points)\nDetected: {detected_at}',
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name='altstats')
@is_staff()
async def alt_stats(ctx):
    """View alt detection statistics"""
    detections = data_manager.get_alt_detections(ctx.guild.id, 1000)
    
    if not detections:
        return await ctx.send('No alt detections yet!')
    
    total = len(detections)
    critical = sum(1 for d in detections if d['suspicion_level'] == 'CRITICAL')
    high = sum(1 for d in detections if d['suspicion_level'] == 'HIGH')
    medium = sum(1 for d in detections if d['suspicion_level'] == 'MEDIUM')
    low = sum(1 for d in detections if d['suspicion_level'] == 'LOW')
    
    timed_out = sum(1 for d in detections if d['timed_out'])
    kicked = sum(1 for d in detections if d['kicked'])
    
    embed = discord.Embed(
        title='📊 Alt Detection Statistics',
        color=Config.INFO
    )
    
    embed.add_field(name='Total Detections', value=str(total), inline=True)
    embed.add_field(name='Critical', value=str(critical), inline=True)
    embed.add_field(name='High', value=str(high), inline=True)
    embed.add_field(name='Medium', value=str(medium), inline=True)
    embed.add_field(name='Low', value=str(low), inline=True)
    embed.add_field(name='‎', value='‎', inline=True)
    
    embed.add_field(name='Timed Out', value=str(timed_out), inline=True)
    embed.add_field(name='Kicked', value=str(kicked), inline=True)
    embed.add_field(name='‎', value='‎', inline=True)
    
    await ctx.send(embed=embed)

# Help Command
@bot.command(name='help')
async def help_command(ctx):
    """Show all available commands"""
    
    is_admin = ctx.author.guild_permissions.administrator or ctx.author.id == Config.OWNER_ID
    
    # Main help embed
    embed = discord.Embed(
        title='🛡️ Security Bot - Command List',
        description=f'Prefix: `{Config.PREFIX}`\nAlt Detection | Server Protection',
        color=Config.INFO
    )
    
    # Basic Commands
    embed.add_field(
        name='📋 Basic Commands',
        value=(
            f'`{Config.PREFIX}help` - Show this menu\n'
            f'`{Config.PREFIX}ping` - Check bot latency\n'
            f'`{Config.PREFIX}info` - Bot information'
        ),
        inline=False
    )
    
    if is_admin:
        # Alt Detection Commands
        embed.add_field(
            name='🚨 Alt Detection (Staff Only)',
            value=(
                f'`{Config.PREFIX}checkalt @user` - Manually check for alt\n'
                f'`{Config.PREFIX}althistory [limit]` - View recent detections\n'
                f'`{Config.PREFIX}altstats` - View detection statistics\n'
                f'`{Config.PREFIX}whitelist @user [reason]` - Whitelist a user\n'
                f'`{Config.PREFIX}unwhitelist @user` - Remove from whitelist'
            ),
            inline=False
        )
    
    # Features
    embed.add_field(
        name='✨ Features',
        value=(
            '• **Automatic Alt Detection**\n'
            '• Account age checking\n'
            '• Username similarity detection\n'
            '• Pattern username detection\n'
            '• Auto-timeout suspicious accounts\n'
            '• Detailed logging & alerts'
        ),
        inline=False
    )
    
    # Settings Info
    embed.add_field(
        name='⚙️ Current Settings',
        value=(
            f'Min Account Age: **{Config.MIN_ACCOUNT_AGE} days**\n'
            f'Auto Timeout: **{"Enabled" if Config.AUTO_TIMEOUT_ALTS else "Disabled"}**\n'
            f'Timeout Duration: **{Config.TIMEOUT_DURATION} minutes**'
        ),
        inline=False
    )
    
    embed.set_footer(text=f'Requested by {ctx.author.name}', icon_url=ctx.author.display_avatar.url)
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    
    await ctx.send(embed=embed)

# Slash command help
@bot.tree.command(name="help", description="Show all bot commands")
async def slash_help(interaction: discord.Interaction):
    """Slash command version of help"""
    is_admin = interaction.user.guild_permissions.administrator or interaction.user.id == Config.OWNER_ID
    
    embed = discord.Embed(
        title='🛡️ Security Bot - Commands',
        description=f'Prefix: `{Config.PREFIX}` | Slash: `/`',
        color=Config.INFO
    )
    
    embed.add_field(
        name='Basic Commands',
        value=(
            f'`{Config.PREFIX}help` - Show commands\n'
            f'`{Config.PREFIX}ping` - Check latency\n'
            f'`{Config.PREFIX}info` - Bot info'
        ),
        inline=False
    )
    
    if is_admin:
        embed.add_field(
            name='Alt Detection (Staff)',
            value=(
                f'`{Config.PREFIX}checkalt @user`\n'
                f'`{Config.PREFIX}althistory`\n'
                f'`{Config.PREFIX}altstats`\n'
                f'`{Config.PREFIX}whitelist @user`'
            ),
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ============================================
# SECTION 6: WEB SERVER (24/7 ON RENDER)
# Paste this right after Section 5
# ============================================

async def start_web_server():
    """
    Starts a web server for Render + UptimeRobot
    This keeps the bot alive 24/7!
    """
    
    async def health_check(request):
        """Health check endpoint for UptimeRobot"""
        return web.Response(
            text='✅ Bot is running!',
            status=200,
            content_type='text/plain'
        )
    
    async def status_page(request):
        """Beautiful status page"""
        
        # Calculate uptime
        uptime_seconds = (datetime.utcnow() - bot.user.created_at).total_seconds()
        uptime_hours = int(uptime_seconds // 3600)
        uptime_days = uptime_hours // 24
        
        html = f'''
<!DOCTYPE html>
<html>
<head>
    <title>Security Bot Status</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }}
        
        .container {{
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 40px;
            max-width: 600px;
            width: 100%;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(255, 255, 255, 0.2);
        }}
        
        .header {{
            text-align: center;
            margin-bottom: 30px;
        }}
        
        .header h1 {{
            font-size: 42px;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.3);
        }}
        
        .status {{
            background: rgba(87, 242, 135, 0.2);
            border: 2px solid #57F287;
            border-radius: 10px;
            padding: 15px;
            text-align: center;
            margin-bottom: 30px;
            font-size: 24px;
            font-weight: bold;
        }}
        
        .stats {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
            margin-bottom: 30px;
        }}
        
        .stat {{
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            padding: 20px;
            text-align: center;
        }}
        
        .stat-value {{
            font-size: 32px;
            font-weight: bold;
            margin-bottom: 5px;
        }}
        
        .stat-label {{
            font-size: 14px;
            opacity: 0.8;
        }}
        
        .features {{
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            padding: 20px;
        }}
        
        .features h2 {{
            margin-bottom: 15px;
            font-size: 20px;
        }}
        
        .features ul {{
            list-style: none;
        }}
        
        .features li {{
            padding: 8px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }}
        
        .features li:last-child {{
            border-bottom: none;
        }}
        
        .features li:before {{
            content: "✓ ";
            color: #57F287;
            font-weight: bold;
            margin-right: 10px;
        }}
        
        .footer {{
            text-align: center;
            margin-top: 30px;
            opacity: 0.7;
            font-size: 14px;
        }}
        
        @media (max-width: 600px) {{
            .stats {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🛡️ Security Bot</h1>
            <p>Advanced Server Protection</p>
        </div>
        
        <div class="status">
            ✅ ONLINE & RUNNING
        </div>
        
        <div class="stats">
            <div class="stat">
                <div class="stat-value">{len(bot.guilds)}</div>
                <div class="stat-label">Servers</div>
            </div>
            <div class="stat">
                <div class="stat-value">{len(bot.users)}</div>
                <div class="stat-label">Users Protected</div>
            </div>
            <div class="stat">
                <div class="stat-value">{round(bot.latency * 1000)}ms</div>
                <div class="stat-label">Latency</div>
            </div>
            <div class="stat">
                <div class="stat-value">{uptime_days}d</div>
                <div class="stat-label">Uptime</div>
            </div>
        </div>
        
        <div class="features">
            <h2>🔒 Active Protection Features</h2>
            <ul>
                <li>Alt Account Detection</li>
                <li>Auto-Moderation System</li>
                <li>Suspicious Pattern Detection</li>
                <li>Username Similarity Analysis</li>
                <li>Real-time Logging & Alerts</li>
                <li>Whitelist Management</li>
            </ul>
        </div>
        
        <div class="footer">
            <p>Running on Render | Monitored by UptimeRobot</p>
            <p>Bot ID: {bot.user.id}</p>
        </div>
    </div>
</body>
</html>
        '''
        
        return web.Response(
            text=html,
            content_type='text/html'
        )
    
    async def bot_stats_json(request):
        """JSON endpoint for API access"""
        stats = {{
            'status': 'online',
            'bot_name': bot.user.name,
            'bot_id': bot.user.id,
            'guilds': len(bot.guilds),
            'users': len(bot.users),
            'latency_ms': round(bot.latency * 1000),
            'prefix': Config.PREFIX
        }}
        
        return web.json_response(stats)
    
    # Create web app
    app = web.Application()
    
    # Add routes
    app.router.add_get('/', status_page)
    app.router.add_get('/health', health_check)
    app.router.add_get('/ping', health_check)
    app.router.add_get('/stats', bot_stats_json)
    
    # Start server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', Config.PORT)
    await site.start()
    
    logger.info(f'✅ Web server running on port {Config.PORT}')
    logger.info(f'📍 Health check: http://0.0.0.0:{Config.PORT}/health')
    logger.info(f'📊 Status page: http://0.0.0.0:{Config.PORT}/')

# ============================================
# MAIN FUNCTION - START EVERYTHING
# ============================================

async def main():
    """
    Main function that starts everything
    1. Starts web server (for 24/7 uptime)
    2. Starts the Discord bot
    """
    
    # Start web server first
    await start_web_server()
    
    # Start bot
    try:
        await bot.start(Config.TOKEN)
    except KeyboardInterrupt:
        logger.info('Bot shutdown requested')
        await bot.close()
    except Exception as e:
        logger.error(f'Bot error: {e}')
        await bot.close()

# ============================================
# RUN THE BOT
# ============================================

if __name__ == '__main__':
    print('\n' + '='*60)
    print('🚀 STARTING SECURITY BOT')
    print('='*60)
    print(f'\n⚙️  Configuration:')
    print(f'   Owner ID: {Config.OWNER_ID}')
    print(f'   Prefix: {Config.PREFIX}')
    print(f'   Port: {Config.PORT}')
    print(f'   Min Account Age: {Config.MIN_ACCOUNT_AGE} days')
    print(f'   Auto Timeout: {Config.AUTO_TIMEOUT_ALTS}')
    print('\n' + '='*60 + '\n')
    
    # Check for token
    if not Config.TOKEN:
        logger.error('❌ DISCORD_TOKEN not found!')
        print('\n⚠️  ERROR: DISCORD_TOKEN not set!')
        print('Set it in your .env file or Render environment variables\n')
        exit(1)
    
    # Check for database
    if not Config.DATABASE_URL:
        logger.warning('⚠️  DATABASE_URL not set!')
        print('\n⚠️  WARNING: No DATABASE_URL found')
        print('Data will not persist. Set it in Render environment variables\n')
    
    # Run the bot
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('Bot stopped by user')
        print('\n👋 Bot stopped!\n')
    except Exception as e:
        logger.error(f'Failed to start: {e}')
        print(f'\n❌ Failed to start: {e}\n')
