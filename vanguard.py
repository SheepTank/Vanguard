from discord.app_commands import Choice, describe, choices, checks
from discord import app_commands
from discord.ext import commands
from discord import Client
import discord
import asyncio
import pytz
import re

import traceback

from os import environ

from baalib.logger import Logger
from Database import *

token = environ.get("TOKEN")

intents = discord.Intents()
intents.members = True
bot: Client = Client(intents=discord.Intents.all())
tree = app_commands.CommandTree(bot)

logger = Logger(logName="log.Vanguard", verbose=True, write=True, debug=True)


def getBanHistory(bans: list, reason=False):
    template = "\t<t:{timestamp}:R> <t:{timestamp}:D> ({active}, expiry: <t:{expiresby}:R>) | Reason: {reason}\n"
    reason = ""
    for ban in sorted(bans, lambda x: x.when):
        msg = template.format(
            timestamp=int(ban.when.timestamp()),
            active="Active" if ban.active else "Expired",
            expiresby=int(ban.expiresby.timestamp()),
            reason=ban.reason,
        )
        if len(reason) + len(msg) < 1900:
            reason += msg
        else:
            break
    if reason:
        return reason
    return bans


async def action_unbans(bans):
    logger.debug(f"Actioning unbans")
    un_ban_counter = 0
    try:
        for ban in bans:
            user = await bot.fetch_user(ban.discord_user_id) or None
            if user is None:
                logger.warn(f"Failed to find user ({ban.discord_user_id}). Skipping")
                continue
            guilds = session.query(Guild).where(Guild.enforce == 2).all()

            for guild in guilds:
                g = await bot.fetch_guild(guild.discord_guild_id) or None
                if g is not None:
                    await g.unban(user)
                    un_ban_counter += 1
                else:
                    logger.fatal("Failed to get Guild, skipping...")
            ban.banned = False
            ban.actioned = True
            session.commit()
            logger.warn(f"Committed.")
    except Exception as e:
        logger.fatal(f"{str(e)}")
    logger.log(f"Successfully processed {un_ban_counter} expired bans.")


async def action_bans(actions):
    try:
        _actionsCounter = 0
        guilds = session.query(Guild).where(Guild.enforce == 2).all()
        for action in actions:
            user = await bot.fetch_user(action.discord_user_id) or None
            if user is None:
                logger.warn(f"Failed to find user ({action.discord_user_id}). Skipping")
                continue

            for g in guilds:
                guild = await bot.fetch_guild(g.discord_guild_id) or None
                logger.debug(repr(guild))
                if guild is not None:
                    await guild.ban(user, reason=action.reason)
            action.actioned = True
            _actionsCounter += 1
            session.commit()
        logger.success(f"Actioned {_actionsCounter} bans across {len(guilds)} guilds.")
    except Exception as e:
        logger.warn(f"actionBans: {str(e)}")


async def monitor():
    while not bot.is_ready():
        await asyncio.sleep(1)

    logger.log(f"monitor: running...")

    while bot.is_ready():
        # Actions: Bans which have been issued but haven't been affected yet
        # Expired: Where Bans have expired but people are still banned.

        actions = (
            session.query(Ban)
            .where(and_(Ban.actioned == False and Ban.banned == True))
            .all()
        )
        expired = (
            session.query(Ban)
            .where(and_(Ban.expires_by < datetime.utcnow(), Ban.banned))
            .all()
        )

        if not bool(len(expired) or len(actions)):
            await asyncio.sleep(5)
            continue

        if len(actions) > 0:
            logger.log(f"Found unactioned bans. Processing {len(actions)} bans...")
            await action_bans(actions)

        if len(expired) > 0:
            logger.log(f"Found expired bans. Processing {len(expired)} unbans...")
            await action_unbans(expired)


@tree.command(description="Set Enforcement Mode")
@describe(
    enforce="An optional argument which changes the enforcement level of the server."
)
@choices(
    enforce=[
        Choice(name="Aggressive", value=2),
        Choice(name="On", value=1),
        Choice(name="Off", value=0),
    ]
)
async def enforcement(interaction: discord.Interaction, enforce: int):
    await interaction.response.defer(ephemeral=True)

    try:
        guild = (
            session.query(Guild)
            .where(Guild.discord_guild_id == interaction.guild.id)
            .one()
        )
    except Exception as e:
        logger.error(f"enforcement: Error: {str(e)}")
        await interaction.edit_original_response(
            content=f"Guild not found within database."
        )
        return

    if enforce is None:
        await interaction.edit_original_response(
            content=f"This guild's automatic ban enforcement is set to {guild.enforce}.\n\nThis means:\n**True**: Vanguard automatically checks members of the guild against the database, and bans users with active bans.\n**False**: This prevents vanguard from automatically banning people, users instead can run an 'Audit' (/banaudit), which discloses any users found with bans, and their reasons."
        )
    if enforce == 1:
        await interaction.edit_original_response(
            content=f"This guild's enforcement has been set to On. Vanguard will only remove new-joiners if they are found within the Vangaurd Database."
        )
        guild.enforce = enforce
        session.commit()
    elif enforce == 0:
        await interaction.edit_original_response(
            content=f"This guild's enforcement has been set to Off. Vanguard will not remove any members found within the Vangaurd Database."
        )
        guild.enforce = enforce
        session.commit()
    else:
        in60 = datetime.utcnow() + timedelta(seconds=60)
        await interaction.edit_original_response(
            content=f"This guild's enforcement is set to Aggressive. Vanguard will remove all discord members with an active ban within the Vanguard database.\n**This will action automatically <t:{int(in60.timestamp())}:R>. Please change the enforcement level to prevent this action**"
        )
        guild.enforce = enforce
        session.commit()
        await asyncio.sleep(60)

        guild = (
            session.query(Guild)
            .where(Guild.discord_guild_id == interaction.guild.id)
            .one()
        )
        g = await bot.fetch_guild(guild.discord_guild_id)
        activeBans = session.query(Ban).filter(
            and_(
                Ban.banned,
                Ban.user_id.in_([user.id for user in interaction.guild.members]),
            )
        )

        if guild.enforce == 2:
            for ban in activeBans:
                await g.ban(
                    await bot.fetch_user(ban.discord_user_id), reason=ban.reason
                )
        else:
            await interaction.edit_original_response(f"Cancelling ban-wave.")
            return


# TODO: FIX THIS
@tree.command(
    description="Run an audit on the server to find users with a history within Vanguard",
    name="banaudit",
)
@checks.has_permissions(ban_members=True)
async def ban_audit(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    logger.debug(f"Called audit")
    bans = {}

    for member in interaction.guild.members:
        _bans = session.query(Ban).where(Ban.user_id == member.id).all()
        if len(_bans) > 0:
            bans[member] = _bans

    header = f"# Report for {interaction.guild.name}\nThis server has {len(bans.keys())} member(s) with Vanguard history.\n"
    report = header
    for member, history in bans.items():
        report += (
            f"\t{member.mention} has a total of {len(history)} ban(s) on record.\n"
        )
        report += getBanHistory(history, reason=True)

    if len(report) > 2000:
        report = header
        for member, history in bans.items():
            if (
                len(report)
                + (
                    len(
                        f"\t{member.mention} has a total of {len(history)} ban(s) on record.\n"
                    )
                )
                > 2000
            ):
                break
            report += (
                f"\t{member.mention} has a total of {len(history)} ban(s) on record.\n"
            )

    await interaction.edit_original_response(content=report)


@tree.command(
    name="auditchannel",
    description="Userd to set the audit channel for any notifications generated by Vanguard",
)
async def audit_channel(interaction: discord.Interaction):
    g = session.query(Guild).where(Guild.discord_guild_id == interaction.guild.id).one()
    g.audit_log_channel_id = interaction.channel.id
    session.commit()

    channel = await bot.fetch_channel(g.audit_log_channel_id)
    await interaction.response.send_message(
        content=f"{channel.jump_url} has been set for audit logs.", ephemeral=True
    )


@tree.command(name="banguard", description="Ban a user using the banguard system.")
@describe(member="A member of the discord server. Select the correct user.")
@describe(
    duration="This is a short-hand way to ban a user. You can use y/m/w/d/h/s to ban them for a specific amount of time. 2w5d for example would ban them for 2 weeks and 5 days."
)
@describe(reason="A reason for why you're banning them.")
@checks.has_permissions(ban_members=True)
async def ban_guard(
    interaction: discord.Interaction, member: discord.Member, duration: str, reason: str
):  # TODO: Retrofit database to accept varying ban duration, with optional permanent.
    await interaction.response.defer(ephemeral=False)
    logger.debug(f"Called banguard")

    def get_duration_in_seconds(duration: str, maximum=None):
        converter = {
            "y": (3600 * 24) * 365.25,
            "m": ((3600 * 24) * 7) * 4,
            "w": (3600 * 24) * 7,
            "d": 3600 * 24,
            "h": 3600,
            "m": 60,
            "s": 1,
        }

        durations = re.findall(r"([0-9]{1,}[ymwdhms]{1})", duration)
        seconds = 0
        for x in durations:
            multiplier, key = int(x[:-1]), x[-1:]
            logger.debug(repr([multiplier, key]))
            seconds = seconds + (converter[key] * multiplier)

        logger.debug(f"Duration ({duration}) is {seconds}")
        if maximum is not None:
            if seconds > get_duration_in_seconds(maximum):
                return maximum
        return seconds

    logger.debug(f"Attempting to create duration")

    if duration is not None:
        try:
            seconds = get_duration_in_seconds(duration)
        except Exception as e:
            logger.fatal(f"banguard: 1 FATAL {str(e)}")
        logger.warn(f"get_duration_in_seconds: {seconds}")
        duration = datetime.utcnow() + timedelta(seconds=seconds)

    logger.debug(f"Banning until {repr(duration)}")
    try:
        ban = Ban(
            discord_user_id=member.id,
            discord_guild_id=member.guild.id,
            reason=reason,
            banned=True,
            issuedby=interaction.user.id,
            expires=True if duration is not None else False,
            expiresby=duration,
        )
    except Exception as e:
        logger.fatal(f"banguard: 2 FATAL {str(e)}")
        print(traceback.print_exc())

    logger.debug(f"Created ban object")

    session.add(ban)
    session.commit()
    session.flush()

    logger.debug(f"Committed ban object")
    logger.success(f"Vanguard ban: {reason} (duration:{duration})")

    if ban.expires:
        await member.send(
            f"You have been banned using Vanguard.\nReason: {reason}.\nYour ban expires <t:{int(duration.timestamp())}:R> (<t:{int(duration.timestamp())}:F>)"
        )
    else:
        await member.send(
            f"You have been banned using Vanguard.\nReason: {reason}.\nYour ban does not expire. Please appeal with the server administrators."
        )
    try:
        await interaction.edit_original_response(
            content=f"{member.mention} ({member.id}) has been banned for: {reason}"
        )
    except Exception as e:
        logger.warn(f"Errored on interaction edit: {str(e)}")
    logger.success(f"Completed banguard operation")


@tree.command(name="unbanguard", description="Unban a user from Vanguard")
@describe(member="Select a member to unban")
@checks.has_permissions(ban_members=True)
async def unban_guard(interaction: discord.Interaction, member: discord.Member):
    logger.log(f"Unbanning {member.name}")
    await interaction.response.defer(ephemeral=True)
    try:
        bans = (
            session.query(Ban).where(and_(Ban.user_id == member.id, Ban.banned)).all()
        )
        await action_unbans(bans)
        await interaction.edit_original_response(
            content=f"Actioned unbans of {member.mention}"
        )
    except Exception as e:
        logger.fatal(f"unbanguard: FATAL {str(e)}")


@bot.event
async def on_guild_join(guild):
    try:
        logger.log(f"Joined a new guild ({guild.id})")
        session.add(
            Guild(
                discord_guild_id=guild.id,
                guild_name=guild.name,
                enforce=False,
                auditlogchannel=0,
            )
        )
        session.commit()
        logger.log(f"Added guild to database ({guild.id})")
    except Exception as e:
        logger.fatal(f"on_guild_join FATAL: {str(e)}")


@bot.event
async def on_guild_leave(guild):
    logger.log(f"Leaving guild ({guild.id})")


@bot.event  # Ban and Enforcement Checks
async def on_member_join(member: discord.Member):
    logger.log(f"User has joined guild ({member.id}:{member.guild.id})")
    try:
        bans = session.query(Ban).where(Ban.user_id == member.id).all() or None
    except Exception as e:
        logger.fatal(f"on_member_join: FATAL {str(e)}")
    try:
        guild = (
            session.query(Guild).where(Guild.discord_guild_id == member.guild.id).one()
            or None
        )
    except Exception as e:
        logger.fatal(f"on_member_join: FATAL {str(e)}")

    if guild is None:
        logger.error(
            f"on_member_join: Failed to find guild from the database. Skipping..."
        )
        return

    # Check if db found something
    if bans is None:
        logger.error(
            f"on_member_join: User came up clean with no past band. Skipping..."
        )
        return

    # Check if any of the bans are active
    for ban in bans:
        if ban.active:
            # Check if guild is actively enforcing or not.
            if bool(guild.enforce):
                await member.send(
                    f"Hello {member.mention}, {member.guild.name} is a Vanguard protected server. You currently have an active ban, which prevents you from joining this server.\n\n"
                    + getBanHistory(bans, reason=True)
                )
                await member.ban(
                    reason=f"Vanguard Ban: User was found to be banned in another server for: {ban.reason}"
                )
                logger.success(
                    f"Vanguard Ban: User was found to be banned in another server for: {ban.reason}"
                )
                break
            else:
                logger.warn(
                    f"{member.id} is actively banned, but the server isn't actively enforcing bans."
                )
                break
    if guild.auditlogchannel != 0:
        audit = await bot.fetch_channel(guild.auditlogchannel)
        reason = getBanHistory(bans, reason=True)

        if guild.enforce:
            await audit.send(
                f"{member.mention} has been found within the server and is serving an active ban within Vanguard. The user's ban history is available below:\n"
                + reason
            )
        else:
            await audit.send(
                f"{member.mention} has joined the server and is serving an active ban. Ban history is available below:\n"
                + reason
            )


@tree.command(name="sync", description="Force a sync for your server.")
async def sync_all(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    synced = await tree.sync()
    await interaction.edit_original_response(
        content=f"Synced {len(synced)} commands to the current guild."
    )


@tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    errors = {
        app_commands.CommandOnCooldown: "This command is on cooldown, please try again later",
        app_commands.BotMissingPermissions: "The bot is missing permissions. Please ensure the bot has the correct permissions",
        app_commands.TransformerError: "Failed to locate user. Has this user already been banned, or left the server recently?",
    }

    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            errors.get(app_commands.CommandOnCooldown), ephemeral=True
        )
    elif isinstance(error, app_commands.BotMissingPermissions):
        await interaction.response.send_message(
            errors.get(app_commands.BotMissingPermissions), ephemeral=True
        )
    elif isinstance(error, app_commands.TransformerError):
        await interaction.response.send_message(
            errors.get(app_commands.TransformerError), ephemeral=True
        )
    else:
        logger.fatal(f"Unknown Error: {str(error)}" + traceback.format_exc())
        await interaction.response.send_message("An error occurred!", ephemeral=True)


@bot.event
async def on_member_leave(member: discord.Member):
    history = session.query(Ban).where(Ban.user_id == member.id).all()
    if len(history) > 0:
        g = session.query(Guild).where(Guild.discord_guild_id == member.guild.id).one()
        notifs = await bot.fetch_channel(g.audit_log_channel_id)
        notifs.send(
            f"{member.mention} with {len(history)} record(s) within Vanguard, has left the server."
        )


async def startup():
    while not bot.is_ready():
        await asyncio.sleep(1)

    logger.log("Startup: Ready. Starting checks...")
    for guild in bot.guilds:
        try:
            session.query(Guild).where(Guild.discord_guild_id == guild.id).one()
        except Exception as e:
            logger.warn(
                f"Missing Guild: {guild.id} not found in database. Creating Guild..."
            )
            session.add(
                Guild(
                    discord_guild_id=guild.id,
                    guild_name=guild.name,
                    enforce=0,
                    audit_log_channel_id=0,
                )
            )
            session.commit()


async def start_bot():
    logger.log("[Vanguard:Startup] Vanguard starting up...")
    await bot.login(token)
    await bot.connect()


@bot.event
async def on_ready():
    logger.log(f"Vanguard: syncing commands")
    await tree.sync()
    logger.success(f"Vanguard: sync complete")


async def main():
    await asyncio.gather(start_bot(), startup(), monitor())


if __name__ == "__main__":
    asyncio.run(main())
