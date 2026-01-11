import discord
from discord.ext import commands
from discord.ui import Button, View, Select, Modal, TextInput
import os
import json
from datetime import datetime
import asyncio
import random
from flask import Flask
from threading import Thread

# ===== FLASK KEEPALIVE =====
app = Flask('')

@app.route('/')
def home():
    return "<h1 style='text-align:center; margin-top:50px; font-family:Arial;'>Bot is Active</h1>"

def run():
    app.run(host='0.0.0.0', port=5000)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ===== BOT CONFIGURATION =====
PREFIX = '$'
TICKET_CATEGORY = 'Tickets'
LOG_CHANNEL = 'ticket-logs'

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ===== CONSTANTS =====
TICKET_CATEGORY_NAME = "Base Tickets"
BASE_PROVIDER_ROLE_ID = 1457797160564298031

# Middleman Role IDs
MM_ROLE_IDS = {
    "trial": 1453757017218093239,
    "middleman": 1434610759140118640,
    "pro": 1453757157144137911,
    "head": 1453757225267892276,
}

# ===== STORAGE =====
active_tickets = {}
claimed_tickets = {}
ticket_roles = {}

# ===== COLORS =====
COLORS = {
    'partnership': 0x5865F2,
    'middleman': 0xFEE75C,
    'support': 0x57F287,
    'error': 0xED4245,
    'success': 0x57F287,
    'info': 0x5865F2
}

# ===== TICKET TYPES =====
TICKET_TYPES = {
    'partnership': {
        'name': 'Partnership',
        'emoji': '🤝',
        'color': COLORS['partnership'],
        'description': 'Discuss partnership opportunities'
    },
    'middleman': {
        'name': 'Middleman',
        'emoji': '⚖️',
        'color': COLORS['middleman'],
        'description': 'Request middleman services'
    },
    'support': {
        'name': 'Support',
        'emoji': '🎫',
        'color': COLORS['support'],
        'description': 'Get help and support'
    }
}

# ===== MM TIERS =====
MM_TIERS = {
    'trial': {'name': '0-100m middleman', 'range': 'Up to 100m/s'},
    'middleman': {'name': '100-500m middleman', 'range': '100m/s - 500m/s'},
    'pro': {'name': '500m+ middleman', 'range': '500m/s+'},
    'head': {'name': 'All Trades Middleman', 'range': 'all trades middleman'},
}

# ===== DATA FUNCTIONS =====
def initialize_json_files():
    if not os.path.exists('bot_data.json'):
        with open('bot_data.json', 'w') as f:
            json.dump({'ticket_roles': {}, 'active_tickets': {}, 'claimed_tickets': {}}, f, indent=4)
        print('✅ Created bot_data.json')

def load_data():
    global ticket_roles, active_tickets, claimed_tickets
    try:
        with open('bot_data.json', 'r') as f:
            data = json.load(f)
            ticket_roles.update(data.get('ticket_roles', {}))
            active_tickets.update(data.get('active_tickets', {}))
            claimed_tickets.update(data.get('claimed_tickets', {}))
        print('✅ Data loaded successfully!')
    except FileNotFoundError:
        print('⚠️ No saved data found, starting fresh.')
    except Exception as e:
        print(f'❌ Error loading data: {e}')

def save_data():
    with open('bot_data.json', 'w') as f:
        json.dump({
            'ticket_roles': ticket_roles,
            'active_tickets': active_tickets,
            'claimed_tickets': claimed_tickets
        }, f, indent=4)

initialize_json_files()

# ===== MODALS =====
class MMTradeModal(Modal, title='Middleman Trade Details'):
    def __init__(self, tier):
        super().__init__()
        self.tier = tier

        self.trader = TextInput(
            label='Who are you trading with?',
            placeholder='@user or ID',
            required=True,
            max_length=100
        )

        self.giving = TextInput(
            label='What are you giving?',
            placeholder='Example: 1 garam',
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500
        )

        self.receiving = TextInput(
            label='What is the other trader giving?',
            placeholder='Example: 296 Robux',
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500
        )

        self.both_join = TextInput(
            label='Can both users join links?',
            placeholder='YES or NO',
            required=True,
            max_length=10
        )

        self.tip = TextInput(
            label='Will you tip the MM?',
            placeholder='Optional',
            required=False,
            max_length=200
        )

        self.add_item(self.trader)
        self.add_item(self.giving)
        self.add_item(self.receiving)
        self.add_item(self.both_join)
        self.add_item(self.tip)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            await create_ticket_with_details(
                interaction.guild, 
                interaction.user, 
                'middleman',
                self.tier,
                self.trader.value,
                self.giving.value,
                self.receiving.value,
                self.both_join.value,
                self.tip.value if self.tip.value else 'None'
            )
            await interaction.followup.send('✅ Middleman ticket created! Check the ticket channel.', ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f'❌ Error creating ticket: {str(e)}', ephemeral=True)

# ===== DROPDOWNS =====
class TierSelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label='0-100m/s Middleman',
                description='Up to 100m/s',
                value='trial',
                emoji='🆕'
            ),
            discord.SelectOption(
                label='100-500m/s Middleman',
                description='100m/s - 250m/s',
                value='middleman',
                emoji='⚖️'
            ),
            discord.SelectOption(
                label='500m/s+ Middleman',
                description='250m/s - 500m/s',
                value='pro',
                emoji='⭐'
            ),
            discord.SelectOption(
                label='All Trades Middleman',
                description='500m/s+',
                value='head',
                emoji='👑'
            )
        ]
        
        super().__init__(
            placeholder='Select tier based on your trade value',
            options=options,
            custom_id='tier_select'
        )
    
    async def callback(self, interaction: discord.Interaction):
        selected_tier = self.values[0]
        modal = MMTradeModal(selected_tier)
        await interaction.response.send_modal(modal)
        
        try:
            await interaction.message.delete()
        except:
            pass

class TierSelectView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TierSelect())

class BaseServiceSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Halloween Base",
                description="🎃 Open a Halloween base service ticket",
                emoji="🎃",
                value="halloween"
            ),
            discord.SelectOption(
                label="Aqua Base",
                description="🌊 Open an Aqua base service ticket",
                emoji="🌊",
                value="aqua"
            )
        ]

        super().__init__(
            placeholder="Choose a base service…",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        choice = self.values[0]

        category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
        if category is None:
            category = await guild.create_category(TICKET_CATEGORY_NAME)

        if choice == "halloween":
            channel_name = f"ticket-halloween🎃-{user.name}".lower()
            title = "🎃 Halloween Base Ticket"
            color = discord.Color.orange()
        else:
            channel_name = f"ticket-aqua🌊-{user.name}".lower()
            title = "🌊 Aqua Base Ticket"
            color = discord.Color.blue()

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            ),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }

        channel = await guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites
        )

        embed = discord.Embed(
            title=title,
            description=f"Welcome {user.mention}!\nA provider will assist you shortly 💬",
            color=color
        )

        role = guild.get_role(BASE_PROVIDER_ROLE_ID)

        await channel.send(
            content=role.mention if role else "⚠️ Provider role not found",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(roles=True)
        )

        await interaction.response.send_message(
            f"✅ Ticket created: {channel.mention}",
            ephemeral=True
        )

class BasePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(BaseServiceSelect())

  # ===== TICKET BUTTON VIEWS =====
class TicketButtons(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Partnership', emoji='🤝', style=discord.ButtonStyle.primary, custom_id='ticket_partnership')
    async def partnership_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        try:
            await create_ticket(interaction.guild, interaction.user, 'partnership')
            await interaction.followup.send('✅ Ticket created! Check the ticket channel.', ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send('❌ I don\'t have permission to create channels!', ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f'❌ Error: {str(e)}', ephemeral=True)

    @discord.ui.button(label='Middleman', emoji='⚖️', style=discord.ButtonStyle.secondary, custom_id='ticket_middleman')
    async def middleman_button(self, interaction: discord.Interaction, button: Button):
        tier_embed = discord.Embed(
            title='Select your middleman tier:',
            color=COLORS['middleman']
        )
        await interaction.response.send_message(embed=tier_embed, view=TierSelectView(), ephemeral=True)

    @discord.ui.button(label='Support', emoji='🎫', style=discord.ButtonStyle.success, custom_id='ticket_support')
    async def support_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        try:
            await create_ticket(interaction.guild, interaction.user, 'support')
            await interaction.followup.send('✅ Ticket created! Check the ticket channel.', ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send('❌ I don\'t have permission to create channels!', ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f'❌ Error: {str(e)}', ephemeral=True)

class CloseTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Close Ticket', emoji='🔒', style=discord.ButtonStyle.danger, custom_id='confirm_close')
    async def close_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        await close_ticket(interaction.channel, interaction.user)

class MMTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label='✅ Claim Ticket', style=discord.ButtonStyle.success, custom_id='claim_mm_ticket')
    async def claim_button(self, interaction: discord.Interaction, button: Button):
        mm_role_ids = [
            1453757017218093239,
            1434610759140118640,
            1453757157144137911,
            1453757225267892276
        ]
        
        user_role_ids = [role.id for role in interaction.user.roles]
        is_mm = any(role_id in user_role_ids for role_id in mm_role_ids)
        is_admin = interaction.user.guild_permissions.administrator
        
        if not is_mm and not is_admin:
            return await interaction.response.send_message('❌ Only middlemen or administrators can claim tickets!', ephemeral=True)
        
        if interaction.channel.id in claimed_tickets:
            claimer_id = claimed_tickets[interaction.channel.id]
            claimer = interaction.guild.get_member(claimer_id)
            return await interaction.response.send_message(f'❌ This ticket is already claimed by {claimer.mention if claimer else "someone"}!', ephemeral=True)
        
        claimed_tickets[interaction.channel.id] = interaction.user.id
        
        ticket_data = active_tickets.get(interaction.channel.id)
        ticket_creator_id = ticket_data.get('user_id') if ticket_data else None
        ticket_creator = interaction.guild.get_member(ticket_creator_id) if ticket_creator_id else None
        
        await interaction.channel.set_permissions(
            interaction.user,
            view_channel=True,
            send_messages=True,
            read_message_history=True
        )
        
        if ticket_creator:
            await interaction.channel.set_permissions(
                ticket_creator,
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )
        
        embed = discord.Embed(
            description=f'✅ Ticket claimed by {interaction.user.mention}\n\n🔒 **Only the claimer and ticket creator can now send messages.**',
            color=COLORS['success']
        )
        embed.timestamp = datetime.utcnow()
        
        await interaction.response.send_message(embed=embed)
        await interaction.channel.edit(name=f"{interaction.channel.name}-claimed")
    
    @discord.ui.button(label='🔒 Close Ticket', style=discord.ButtonStyle.danger, custom_id='close_mm_ticket')
    async def close_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        await close_ticket(interaction.channel, interaction.user)

# ===== TICKET HELPER FUNCTIONS =====
async def create_ticket(guild, user, ticket_type):
    """Create a simple ticket (for partnership and support)"""
    try:
        ticket_info = TICKET_TYPES[ticket_type]
        
        category = discord.utils.get(guild.categories, name=TICKET_CATEGORY)
        if not category:
            category = await guild.create_category(TICKET_CATEGORY)
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True, 
                send_messages=True, 
                read_message_history=True,
                mention_everyone=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True
            )
        }
        
        ticket_channel = await guild.create_text_channel(
            name=f'ticket-{user.name}-{ticket_type}',
            category=category,
            overwrites=overwrites
        )
        
        active_tickets[ticket_channel.id] = {
            'user_id': user.id,
            'type': ticket_type,
            'created_at': datetime.utcnow().isoformat()
        }
        
        guild_id = str(guild.id)
        role_to_ping = None
        
        if guild_id in ticket_roles and ticket_type in ticket_roles[guild_id]:
            role_id = ticket_roles[guild_id][ticket_type]
            role_to_ping = guild.get_role(role_id)
        
        if role_to_ping:
            ping_message = f"{role_to_ping.mention} - New {ticket_info['name']} ticket opened!"
            await ticket_channel.send(ping_message, allowed_mentions=discord.AllowedMentions(roles=True))
        
        embed = discord.Embed(
            title=f"{ticket_info['emoji']} {ticket_info['name']} Ticket",
            description=f"Welcome {user.mention}!\n\n**Ticket Type:** {ticket_info['description']}\n\nOur team will be with you shortly. Please describe your inquiry in detail.",
            color=ticket_info['color']
        )
        embed.add_field(
            name='📌 Commands',
            value='`$close` - Close this ticket\n`$claim` - Claim this ticket\n`$add <user>` - Add a user\n`$remove <user>` - Remove a user',
            inline=False
        )
        embed.set_footer(text=f'Ticket created by {user}', icon_url=user.display_avatar.url)
        embed.timestamp = datetime.utcnow()
        
        await ticket_channel.send(content=user.mention, embed=embed, view=CloseTicketView())
        
    except Exception as e:
        print(f'[ERROR] Ticket creation failed: {e}')
        raise

async def create_ticket_with_details(guild, user, ticket_type, tier, trader, giving, receiving, both_join, tip):
    """Create a middleman ticket with trade details"""
    try:
        ticket_info = TICKET_TYPES[ticket_type]
        
        category = discord.utils.get(guild.categories, name=TICKET_CATEGORY)
        if not category:
            category = await guild.create_category(TICKET_CATEGORY)
        
        mm_role_ids = [
            1453757017218093239,
            1434610759140118640,
            1453757157144137911,
            1453757225267892276
        ]
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True, 
                send_messages=True, 
                read_message_history=True,
                mention_everyone=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True
            )
        }
        
        for role_id in mm_role_ids:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True
                )
        
        ticket_channel = await guild.create_text_channel(
            name=f'ticket-{user.name}-{ticket_type}',
            category=category,
            overwrites=overwrites
        )
        
        active_tickets[ticket_channel.id] = {
            'user_id': user.id,
            'type': ticket_type,
            'created_at': datetime.utcnow().isoformat(),
            'tier': tier,
            'trader': trader,
            'giving': giving,
            'receiving': receiving,
            'both_join': both_join,
            'tip': tip
        }
        
        tier_role_id = MM_ROLE_IDS.get(tier)
        tier_role = guild.get_role(tier_role_id) if tier_role_id else None
        
        if tier_role:
            ping_message = f"{tier_role.mention} - New {MM_TIERS[tier]['name']} ticket opened!"
            await ticket_channel.send(ping_message, allowed_mentions=discord.AllowedMentions(roles=True))
        
        embed = discord.Embed(
            title=f"{ticket_info['emoji']} {ticket_info['name']} Ticket",
            description=f"Welcome {user.mention}!\n\nOur team will be with you shortly.",
            color=ticket_info['color']
        )
        embed.set_footer(text=f'Ticket created by {user}', icon_url=user.display_avatar.url)
        embed.timestamp = datetime.utcnow()
        
        await ticket_channel.send(content=user.mention, embed=embed)
        
        details_embed = discord.Embed(
            title='📋 Middleman Trade Request',
            description=f'**Selected Tier:** {MM_TIERS[tier]["name"]}\n**Range:** {MM_TIERS[tier]["range"]}',
            color=COLORS['middleman']
        )
        
        details_embed.add_field(name='Trading With', value=trader, inline=False)
        details_embed.add_field(name='Requester Giving', value=giving, inline=False)
        details_embed.add_field(name='Requester Receiving', value=receiving, inline=False)
        details_embed.add_field(name='Both Can Join Links?', value=both_join, inline=False)
        details_embed.add_field(name='Tip', value=tip, inline=False)
        
        details_embed.set_footer(text=f'Requested by {user}', icon_url=user.display_avatar.url)
        details_embed.timestamp = datetime.utcnow()
        
        await ticket_channel.send(embed=details_embed, view=MMTicketView())
        
    except Exception as e:
        print(f'[ERROR] MM Ticket creation failed: {e}')
        raise

async def close_ticket(channel, user):
    ticket_data = active_tickets.get(channel.id)

    embed = discord.Embed(
        title='🔒 Ticket Closed',
        description=f'Ticket closed by {user.mention}',
        color=COLORS['error']
    )
    embed.timestamp = datetime.utcnow()

    await channel.send(embed=embed)

    log_channel = discord.utils.get(channel.guild.channels, name=LOG_CHANNEL)
    if log_channel:
        log_embed = discord.Embed(
            title='🎫 Ticket Closed',
            color=COLORS['error']
        )
        log_embed.add_field(name='Channel', value=channel.name, inline=True)
        log_embed.add_field(name='Closed By', value=user.name, inline=True)
        log_embed.add_field(name='Type', value=ticket_data.get('type', 'Unknown') if ticket_data else 'Unknown', inline=True)
        log_embed.timestamp = datetime.utcnow()

        await log_channel.send(embed=log_embed)

    if channel.id in active_tickets:
        del active_tickets[channel.id]
    if channel.id in claimed_tickets:
        del claimed_tickets[channel.id]

    await asyncio.sleep(5)
    await channel.delete()

# ===== BOT EVENTS =====
@bot.event
async def on_ready():
    print(f'✅ Bot is online as {bot.user}')
    print(f'📊 Serving {len(bot.guilds)} servers')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name='$help | Ticket System'))

    bot.add_view(TicketButtons())
    bot.add_view(CloseTicketView())
    bot.add_view(TierSelectView())
    bot.add_view(MMTicketView())
    bot.add_view(BasePanelView())
    
    load_data()

# ===== SETUP COMMANDS =====
@bot.command(name='setup')
@commands.has_permissions(administrator=True)
async def setup(ctx):
    """Create a beautiful ticket panel"""
    
    embed = discord.Embed(
        title='🎫 Support Ticket System',
        description=(
            '> **Need assistance? Open a ticket!**\n'
            '> Our team is ready to help you 24/7\n\n'
            '**Choose your ticket type below:**'
        ),
        color=0x5865F2
    )
    
    embed.add_field(
        name='🤝 Partnership',
        value='```\nFor business collaborations\nand partnership opportunities```',
        inline=True
    )
    
    embed.add_field(
        name='⚖️ Middleman',
        value='```\nSecure trading services\nwith trusted middlemen```',
        inline=True
    )
    
    embed.add_field(
        name='🎫 Support',
        value='```\nGeneral help, questions\nand technical support```',
        inline=True
    )
    
    await ctx.send(embed=embed, view=TicketButtons())
    
    confirm = discord.Embed(
        description='✅ **Ticket panel created successfully!**',
        color=0x57F287
    )
    await ctx.reply(embed=confirm, delete_after=5)

@bot.command(name='basepanel')
@commands.has_permissions(administrator=True)
async def basepanel(ctx):
    """Create beautiful base services panel"""
    
    embed = discord.Embed(
        title='🛠️ Base Services',
        description=(
            '> **Professional base services**\n'
            '> Select the service you need below\n\n'
            '**Available Services:**'
        ),
        color=0x9B59B6
    )
    
    embed.add_field(
        name='🎃 Halloween Base',
        value='```\n• Spooky themed designs\n• Custom decorations\n• Fast delivery```',
        inline=True
    )
    
    embed.add_field(
        name='🌊 Aqua Base',
        value='```\n• Ocean themed builds\n• Underwater designs\n• Professional quality```',
        inline=True
    )
    
    embed.set_footer(
        text='Select a service from the dropdown menu',
        icon_url=ctx.guild.icon.url if ctx.guild.icon else None
    )

    await ctx.send(embed=embed, view=BasePanelView())
    
    confirm = discord.Embed(
        description='✅ **Base services panel created!**',
        color=0x57F287
    )
    await ctx.reply(embed=confirm, delete_after=5)

# ===== TICKET COMMANDS =====
@bot.command(name='close')
async def close_command(ctx):
    if not ctx.channel.name.startswith('ticket-'):
        await ctx.reply('❌ This command can only be used in ticket channels!')
        return

    embed = discord.Embed(
        title='⚠️ Close Ticket',
        description='Are you sure you want to close this ticket?',
        color=COLORS['error']
    )
    embed.set_footer(text='This action cannot be undone')

    view = CloseTicketView()
    cancel_button = Button(label='Cancel', style=discord.ButtonStyle.secondary)

    async def cancel_callback(interaction):
        await interaction.response.edit_message(content='❌ Ticket closure cancelled.', embed=None, view=None)

    cancel_button.callback = cancel_callback
    view.add_item(cancel_button)

    await ctx.reply(embed=embed, view=view)

@bot.command(name='claim')
async def claim(ctx):
    if not ctx.channel.name.startswith('ticket-'):
        await ctx.reply('❌ This command can only be used in ticket channels!')
        return

    if ctx.channel.id in claimed_tickets:
        await ctx.reply('❌ This ticket is already claimed!')
        return

    claimed_tickets[ctx.channel.id] = ctx.author.id
    
    ticket_data = active_tickets.get(ctx.channel.id)
    ticket_creator_id = ticket_data.get('user_id') if ticket_data else None
    ticket_creator = ctx.guild.get_member(ticket_creator_id) if ticket_creator_id else None
    
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
        description=f'✅ Ticket claimed by {ctx.author.mention}\n\n🔒 **Only the claimer and ticket creator can now send messages.**',
        color=COLORS['success']
    )
    embed.timestamp = datetime.utcnow()

    await ctx.send(embed=embed)
    await ctx.channel.edit(name=f"{ctx.channel.name}-claimed")

@bot.command(name='unclaim')
async def unclaim(ctx):
    if not ctx.channel.name.startswith('ticket-'):
        await ctx.reply('❌ This command can only be used in ticket channels!')
        return

    if ctx.channel.id not in claimed_tickets:
        await ctx.reply('❌ This ticket is not claimed!')
        return

    claimer = claimed_tickets[ctx.channel.id]
    if claimer != ctx.author.id and not ctx.author.guild_permissions.administrator:
        await ctx.reply('❌ Only the claimer or an administrator can unclaim this ticket!')
        return

    del claimed_tickets[ctx.channel.id]
    
    claimer_member = ctx.guild.get_member(claimer)
    if claimer_member:
        await ctx.channel.set_permissions(claimer_member, overwrite=None)

    embed = discord.Embed(
        description=f'✅ Ticket unclaimed by {ctx.author.mention}\n\n🔓 **All staff can now send messages again.**',
        color=COLORS['info']
    )
    embed.timestamp = datetime.utcnow()

    await ctx.send(embed=embed)
    new_name = ctx.channel.name.replace('-claimed', '')
    await ctx.channel.edit(name=new_name)

@bot.command(name='add')
async def add_user(ctx, member: discord.Member = None):
    if not ctx.channel.name.startswith('ticket-'):
        await ctx.reply('❌ This command can only be used in ticket channels!')
        return

    if not member:
        await ctx.reply('❌ Please mention a valid user!')
        return

    await ctx.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)

    embed = discord.Embed(
        description=f'✅ {member.mention} has been added to the ticket',
        color=COLORS['success']
    )
    embed.timestamp = datetime.utcnow()

    await ctx.reply(embed=embed)

@bot.command(name='remove')
async def remove_user(ctx, member: discord.Member = None):
    if not ctx.channel.name.startswith('ticket-'):
        await ctx.reply('❌ This command can only be used in ticket channels!')
        return

    if not member:
        await ctx.reply('❌ Please mention a valid user!')
        return

    await ctx.channel.set_permissions(member, overwrite=None)

    embed = discord.Embed(
        description=f'✅ {member.mention} has been removed from the ticket',
        color=COLORS['success']
    )
    embed.timestamp = datetime.utcnow()

    await ctx.reply(embed=embed)

@bot.command(name='rename')
async def rename(ctx, *, new_name: str = None):
    if not ctx.channel.name.startswith('ticket-'):
        await ctx.reply('❌ This command can only be used in ticket channels!')
        return

    if not new_name:
        await ctx.reply('❌ Please provide a new name for the ticket!')
        return

    new_name = new_name.lower().replace(' ', '-')
    await ctx.channel.edit(name=f'ticket-{new_name}')

    embed = discord.Embed(
        description=f'✅ Ticket renamed to **ticket-{new_name}**',
        color=COLORS['success']
    )
    embed.timestamp = datetime.utcnow()

    await ctx.reply(embed=embed)
    save_data()

@bot.command(name='proof')
async def proof_command(ctx):
    if not ctx.channel.name.startswith('ticket-'):
        return await ctx.reply('❌ This command can only be used in a ticket.')

    ticket = active_tickets.get(ctx.channel.id)
    if not ticket:
        return await ctx.reply('❌ No ticket data found.')

    requester = ctx.guild.get_member(ticket['user_id'])
    trader = ticket.get('trader', 'Unknown')
    giving = ticket.get('giving', 'Unknown')
    receiving = ticket.get('receiving', 'Unknown')
    tier = ticket.get('tier', 'Unknown')

    PROOF_CHANNEL_ID = 1441905610340962486
    proof_channel = ctx.guild.get_channel(PROOF_CHANNEL_ID)

    if not proof_channel:
        return await ctx.reply('❌ Proof channel not found.')

    embed = discord.Embed(
        title='✅ Trade Completed',
        color=0x57F287
    )

    embed.add_field(name='Middleman', value=ctx.author.mention, inline=False)
    embed.add_field(name='Type', value='MM', inline=False)
    embed.add_field(name='Tier', value=MM_TIERS[tier]['name'], inline=False)
    embed.add_field(name='Requester', value=requester.mention if requester else 'Unknown', inline=False)
    embed.add_field(name='Trader', value=trader, inline=False)
    embed.add_field(name='Gave', value=giving, inline=False)
    embed.add_field(name='Received', value=receiving, inline=False)

    ticket_number = ctx.channel.name.replace('ticket-', '')
    embed.set_footer(text=f"Ticket #{ticket_number}")

    await proof_channel.send(embed=embed)
    await ctx.reply('✅ Proof sent successfully!')

@bot.command(name='stats')
async def stats(ctx):
    tickets = [c for c in ctx.guild.channels if c.name.startswith('ticket-')]
    claimed = [c for c in tickets if c.id in claimed_tickets]

    embed = discord.Embed(
        title='📊 Ticket Statistics',
        color=COLORS['info']
    )
    embed.add_field(name='🎫 Active Tickets', value=f'`{len(tickets)}`', inline=True)
    embed.add_field(name='✅ Claimed Tickets', value=f'`{len(claimed)}`', inline=True)
    embed.add_field(name='⏳ Unclaimed Tickets', value=f'`{len(tickets) - len(claimed)}`', inline=True)
    embed.set_footer(text=f'Requested by {ctx.author}', icon_url=ctx.author.display_avatar.url)

    await ctx.reply(embed=embed)

@bot.command(name='ticketrole')
@commands.has_permissions(administrator=True)
async def ticket_role(ctx, ticket_type: str, role: discord.Role):
    """Set which role gets pinged for each ticket type"""
    ticket_type = ticket_type.lower()
    
    if ticket_type not in ['partnership', 'middleman', 'support']:
        embed = discord.Embed(
            title='❌ Invalid Ticket Type',
            description='Valid types: `partnership`, `middleman`, `support`',
            color=COLORS['error']
        )
        return await ctx.send(embed=embed)
    
    guild_id = str(ctx.guild.id)
    if guild_id not in ticket_roles:
        ticket_roles[guild_id] = {}
    
    ticket_roles[guild_id][ticket_type] = role.id
    save_data()
    
    embed = discord.Embed(
        title='✅ Ticket Role Set',
        description=f'**{ticket_type.title()}** tickets will now ping {role.mention}',
        color=COLORS['success']
    )
    await ctx.send(embed=embed)

@bot.command(name='ticketroles')
@commands.has_permissions(administrator=True)
async def ticket_roles_list(ctx):
    """View current ticket role settings"""
    guild_id = str(ctx.guild.id)
    
    embed = discord.Embed(
        title='🎫 Ticket Role Settings',
        color=COLORS['info']
    )
    
    if guild_id not in ticket_roles or not ticket_roles[guild_id]:
        embed.description = 'No ticket roles configured yet.\n\nUse `$ticketrole <type> <role>` to set them.'
    else:
        for ticket_type, role_id in ticket_roles[guild_id].items():
            role = ctx.guild.get_role(role_id)
            if role:
                embed.add_field(
                    name=f'{ticket_type.title()} Tickets',
                    value=f'Pings: {role.mention}',
                    inline=False
                )
    
    await ctx.send(embed=embed)

# ===== COINFLIP SYSTEM =====

# Store active flips
active_flips = {}

class CoinflipChoiceView(View):
    def __init__(self, flip_id, user1, user2):
        super().__init__(timeout=60)
        self.flip_id = flip_id
        self.user1 = user1
        self.user2 = user2
        self.choices = {}
    
    @discord.ui.button(label='Heads', emoji='🪙', style=discord.ButtonStyle.primary)
    async def heads_button(self, interaction: discord.Interaction, button: Button):
        await self.handle_choice(interaction, 'heads')
    
    @discord.ui.button(label='Tails', emoji='💫', style=discord.ButtonStyle.secondary)
    async def tails_button(self, interaction: discord.Interaction, button: Button):
        await self.handle_choice(interaction, 'tails')
    
    async def handle_choice(self, interaction: discord.Interaction, choice: str):
        # Check if user is part of this flip
        if interaction.user.id not in [self.user1.id, self.user2.id]:
            return await interaction.response.send_message('❌ This flip is not for you!', ephemeral=True)
        
        # Check if they already chose
        if interaction.user.id in self.choices:
            return await interaction.response.send_message('❌ You already picked!', ephemeral=True)
        
        # Check if choice is already taken
        if choice in self.choices.values():
            return await interaction.response.send_message(f'❌ {choice.title()} is already taken! Pick the other side.', ephemeral=True)
        
        # Record choice
        self.choices[interaction.user.id] = choice
        
        await interaction.response.send_message(f'✅ You picked **{choice.title()}**!', ephemeral=True)
        
        # If both chose, start the game
        if len(self.choices) == 2:
            self.stop()
            await self.start_game(interaction)
    
    async def start_game(self, interaction):
        # Get flip data
        flip_data = active_flips.get(self.flip_id)
        if not flip_data:
            return
        
        mode = flip_data['mode']
        amount = flip_data['amount']
        channel = flip_data['channel']
        
        # Disable buttons
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        
        # Show what each user picked
        user1_choice = self.choices.get(self.user1.id, 'unknown')
        user2_choice = self.choices.get(self.user2.id, 'unknown')
        
        choices_embed = discord.Embed(
            title='🪙 Choices Locked!',
            description=f'{self.user1.mention} picked **{user1_choice.title()}**\n{self.user2.mention} picked **{user2_choice.title()}**',
            color=discord.Color.gold()
        )
        await channel.send(embed=choices_embed)
        
        await asyncio.sleep(2)
        
        # Start the actual flip
        if mode == 'ft':
            await run_first_to(channel, self.user1, self.user2, amount, self.choices)
        else:  # bo
            await run_best_of(channel, self.user1, self.user2, amount, self.choices)

async def run_first_to(channel, user1, user2, points_needed, choices):
    """First to X points wins"""
    scores = {user1.id: 0, user2.id: 0}
    
    embed = discord.Embed(
        title='🪙 First to ' + str(points_needed) + ' Coinflip!',
        description=f'{user1.mention} vs {user2.mention}',
        color=discord.Color.gold()
    )
    embed.add_field(name=user1.display_name, value='0', inline=True)
    embed.add_field(name=user2.display_name, value='0', inline=True)
    embed.add_field(name='First to', value=str(points_needed), inline=False)
    
    message = await channel.send(embed=embed)
    
    round_num = 0
    
    while scores[user1.id] < points_needed and scores[user2.id] < points_needed:
        round_num += 1
        await asyncio.sleep(2)
        
        # Flip the coin
        result = random.choice(['heads', 'tails'])
        
        # Determine winner of this round
        winner = None
        for user_id, choice in choices.items():
            if choice == result:
                winner = user1 if user_id == user1.id else user2
                scores[user_id] += 1
                break
        
        # Update embed
        embed = discord.Embed(
            title='🪙 First to ' + str(points_needed) + ' Coinflip!',
            description=f'{user1.mention} vs {user2.mention}\n\n**Round {round_num}:** {result.title()}! {winner.mention if winner else "No one"} wins!',
            color=discord.Color.gold()
        )
        embed.add_field(name=user1.display_name, value=str(scores[user1.id]), inline=True)
        embed.add_field(name=user2.display_name, value=str(scores[user2.id]), inline=True)
        embed.add_field(name='First to', value=str(points_needed), inline=False)
        
        await message.edit(embed=embed)
    
    # Determine final winner
    await asyncio.sleep(2)
    
    final_winner = user1 if scores[user1.id] >= points_needed else user2
    
    final_embed = discord.Embed(
        title='🏆 Coinflip Results!',
        description=f'{user1.mention} vs {user2.mention}',
        color=discord.Color.green()
    )
    final_embed.add_field(name=user1.display_name, value=f'**{scores[user1.id]}** points', inline=True)
    final_embed.add_field(name=user2.display_name, value=f'**{scores[user2.id]}** points', inline=True)
    final_embed.add_field(name='Winner', value=f'🎉 {final_winner.mention}', inline=False)
    final_embed.add_field(name='Total Rounds', value=str(round_num), inline=True)
    
    await message.edit(embed=final_embed)

async def run_best_of(channel, user1, user2, total_rounds, choices):
    """Best of X rounds"""
    scores = {user1.id: 0, user2.id: 0}
    
    embed = discord.Embed(
        title='🪙 Best of ' + str(total_rounds) + ' Coinflip!',
        description=f'{user1.mention} vs {user2.mention}',
        color=discord.Color.gold()
    )
    embed.add_field(name=user1.display_name, value='0', inline=True)
    embed.add_field(name=user2.display_name, value='0', inline=True)
    embed.add_field(name='Rounds Remaining', value=str(total_rounds), inline=False)
    
    message = await channel.send(embed=embed)
    
    for round_num in range(1, total_rounds + 1):
        await asyncio.sleep(2)
        
        # Flip the coin
        result = random.choice(['heads', 'tails'])
        
        # Determine winner of this round
        winner = None
        for user_id, choice in choices.items():
            if choice == result:
                winner = user1 if user_id == user1.id else user2
                scores[user_id] += 1
                break
        
        # Update embed
        embed = discord.Embed(
            title='🪙 Best of ' + str(total_rounds) + ' Coinflip!',
            description=f'{user1.mention} vs {user2.mention}\n\n**Round {round_num}/{total_rounds}:** {result.title()}! {winner.mention if winner else "No one"} wins!',
            color=discord.Color.gold()
        )
        embed.add_field(name=user1.display_name, value=str(scores[user1.id]), inline=True)
        embed.add_field(name=user2.display_name, value=str(scores[user2.id]), inline=True)
        embed.add_field(name='Rounds Remaining', value=str(total_rounds - round_num), inline=False)
        
        await message.edit(embed=embed)
    
    # Determine final winner
    await asyncio.sleep(2)
    
    if scores[user1.id] > scores[user2.id]:
        final_winner = user1
        color = discord.Color.green()
    elif scores[user2.id] > scores[user1.id]:
        final_winner = user2
        color = discord.Color.green()
    else:
        final_winner = None
        color = discord.Color.blue()
    
    final_embed = discord.Embed(
        title='🏆 Coinflip Results!',
        description=f'{user1.mention} vs {user2.mention}',
        color=color
    )
    final_embed.add_field(name=user1.display_name, value=f'**{scores[user1.id]}** wins', inline=True)
    final_embed.add_field(name=user2.display_name, value=f'**{scores[user2.id]}** wins', inline=True)
    
    if final_winner:
        final_embed.add_field(name='Winner', value=f'🎉 {final_winner.mention}', inline=False)
    else:
        final_embed.add_field(name='Result', value='🤝 It\'s a tie!', inline=False)
    
    await message.edit(embed=final_embed)

@bot.command(name='bf', aliases=['battleflip', 'coinflip'])
async def battle_flip(ctx, user1: discord.Member, vs: str, user2: discord.Member, mode: str, amount: int):
    """
    Coinflip battle between two users
    Usage: $bf @user1 vs @user2 ft 10  (first to 10 points)
    Usage: $bf @user1 vs @user2 bo 10  (best of 10 rounds)
    """
    
    # Check if user has MM role
    mm_role_ids = [
        1453757017218093239,
        1434610759140118640,
        1453757157144137911,
        1453757225267892276
    ]
    
    user_role_ids = [role.id for role in ctx.author.roles]
    has_mm_role = any(role_id in user_role_ids for role_id in mm_role_ids)
    
    if not has_mm_role and not ctx.author.guild_permissions.administrator:
        return await ctx.reply('❌ Only middlemen can start coinflips!')
    
    # Validate "vs"
    if vs.lower() != 'vs':
        return await ctx.reply('❌ Format: `$bf @user1 vs @user2 ft/bo amount`')
    
    # Validate mode
    mode = mode.lower()
    if mode not in ['ft', 'bo']:
        return await ctx.reply('❌ Mode must be either `ft` (first to) or `bo` (best of)')
    
    # Validate amount
    if amount < 1:
        return await ctx.reply('❌ Amount must be at least 1!')
    
    if amount > 100:
        return await ctx.reply('❌ Maximum amount is 100!')
    
    # Check if users are same
    if user1.id == user2.id:
        return await ctx.reply('❌ You can\'t flip against yourself!')
    
    # Create flip ID
    flip_id = ctx.message.id
    
    # Store flip data
    active_flips[flip_id] = {
        'mode': mode,
        'amount': amount,
        'channel': ctx.channel,
        'user1': user1,
        'user2': user2
    }
    
    # Create choice embed
    mode_name = 'First to' if mode == 'ft' else 'Best of'
    
    embed = discord.Embed(
        title=f'🪙 {mode_name} {amount} Coinflip!',
        description=(
            f'**{user1.mention} vs {user2.mention}**\n\n'
            f'Both players must choose **Heads** or **Tails**!\n'
            f'Each player must pick a different side.\n\n'
            f'Started by: {ctx.author.mention}'
        ),
        color=discord.Color.gold()
    )
    
    view = CoinflipChoiceView(flip_id, user1, user2)
    await ctx.send(embed=embed, view=view)

# ===== HELP COMMAND =====
@bot.command(name='help')
async def help_command(ctx):
    """Display all available commands"""
    
    embed = discord.Embed(
        title='📚 Bot Command List',
        description=(
            '> **Professional ticket & management system**\n'
            '**Command Prefix:** `$`'
        ),
        color=COLORS['info']
    )
    
    # Ticket Commands
    embed.add_field(
        name='🎫 Ticket Commands',
        value=(
            '```ini\n'
            '[Close]   Close current ticket\n'
            '[Claim]   Claim a ticket\n'
            '[Unclaim] Unclaim a ticket\n'
            '[Add]     Add user to ticket\n'
            '[Remove]  Remove user from ticket\n'
            '[Rename]  Rename ticket channel\n'
            '[Proof]   Submit MM trade proof\n'
            '[Stats]   View ticket statistics\n'
            '```'
        ),
        inline=False
    )
    
    # Setup Commands (Admin)
    embed.add_field(
        name='⚙️ Setup Commands (Admin)',
        value=(
            '```ini\n'
            '[Setup]      Create ticket panel\n'
            '[Basepanel]  Create base services panel\n'
            '[Ticketrole] Set ticket ping role\n'
            '[Ticketroles] View ticket roles\n'
            '```'
        ),
        inline=False
    )
    
    # Coinflip Commands
    embed.add_field(
        name='🪙 Coinflip Commands (MM Only)',
        value=(
            '```ini\n'
            '[BF] Start coinflip battle\n\n'
            'Usage:\n'
            '$bf @user1 vs @user2 ft 10\n'
            '(First to 10 points)\n\n'
            '$bf @user1 vs @user2 bo 10\n'
            '(Best of 10 rounds)\n'
            '```'
        ),
        inline=False
    )
    
    # Ticket Types
    embed.add_field(
        name='🏷️ Available Ticket Types',
        value=(
            '```\n'
            'partnership - Partnership inquiries\n'
            'middleman   - Middleman services\n'
            'support     - General support\n'
            '```'
        ),
        inline=False
    )
    
    embed.set_footer(
        text=f'Requested by {ctx.author} • Type $help for details',
        icon_url=ctx.author.display_avatar.url
    )
    embed.timestamp = datetime.utcnow()

    await ctx.reply(embed=embed)

# ===== ERROR HANDLING =====
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        try:
            await ctx.reply('❌ You do not have permission to use this command!')
        except:
            pass
    elif isinstance(error, commands.MemberNotFound):
        try:
            await ctx.reply('❌ User not found!')
        except:
            pass
    elif isinstance(error, commands.MissingRequiredArgument):
        try:
            await ctx.reply(f'❌ Missing required argument! Use `$help` for command usage.')
        except:
            pass
    elif isinstance(error, commands.CommandInvokeError):
        if 'Forbidden' in str(error):
            print(f'Permission Error: Bot lacks permissions in {ctx.guild.name} - {ctx.channel.name}')
            try:
                await ctx.author.send(f'❌ I don\'t have permission to send messages in #{ctx.channel.name}. Please give me "Send Messages" and "Embed Links" permissions!')
            except:
                pass
        else:
            print(f'Error: {error}')
    else:
        print(f'Error: {error}')

# ===== RUN BOT =====
if __name__ == '__main__':
    keep_alive()
    TOKEN = os.getenv('TOKEN')
    if not TOKEN:
        print('❌ ERROR: No TOKEN found in environment variables!')
        print('Please set your Discord bot token as TOKEN environment variable')
    else:
        print('🚀 Starting Discord Ticket Bot...')
        bot.run(TOKEN)
