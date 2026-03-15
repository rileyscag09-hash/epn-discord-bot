import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from datetime import datetime, timezone
from typing import Optional, Union
from utils.constants import Constants, logger, EmbedDesign
from utils.staff import StaffUtils
from utils.rate_limiter import MelonlyRateLimiter

# Initialize constants
constants = Constants()


class InfoCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bloxlink_api_key = constants.bloxlink_api_key()
        self.melonly_api_key = constants.melonly_api_key()

        # Initialize rate limiter for Melonly API
        self.melonly_rate_limiter = MelonlyRateLimiter(
            database_manager=getattr(bot, "db", None)
        )

    async def get_bloxlink_info(self, user_id: int) -> Optional[dict]:
        """Get Roblox information from Bloxlink API using global key."""
        if not self.bloxlink_api_key:
            logger.warning("Bloxlink API key not configured")
            return None

        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": self.bloxlink_api_key}
                url = f"https://api.blox.link/v4/public/discord-to-roblox/{user_id}"

                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("robloxID")
                    else:
                        response_text = await response.text()
                        logger.warning(
                            f"Bloxlink API error: {response.status} - {response_text}"
                        )
                    return None
        except Exception as e:
            logger.error(f"Error fetching Bloxlink info: {e}")
            return None

    async def get_roblox_user_info(self, roblox_user_id: int) -> Optional[dict]:
        """Get detailed Roblox user information from Roblox API."""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://users.roblox.com/v1/users/{roblox_user_id}"

                async with session.get(url) as response:
                    if response.status == 200:
                        user_data = await response.json()
                        details = {}

                        if "displayName" in user_data:
                            details["displayName"] = user_data["displayName"]

                        if "name" in user_data:
                            details["username"] = user_data["name"]

                        if "created" in user_data:
                            created_date = datetime.fromisoformat(
                                user_data["created"].replace("Z", "+00:00")
                            )
                            account_age = (datetime.now(timezone.utc) - created_date).days
                            details["accountAge"] = account_age
                            details["created"] = user_data["created"]

                        try:
                            async with session.get(
                                f"https://users.roblox.com/v1/users/{roblox_user_id}/status"
                            ) as status_response:
                                if status_response.status == 200:
                                    status_data = await status_response.json()
                                    details["status"] = status_data.get("status", "Unknown")
                                else:
                                    details["status"] = "Unknown"
                        except aiohttp.ClientError as e:
                            logger.warning(
                                f"Could not fetch Roblox status for {roblox_user_id}: {e}"
                            )
                            details["status"] = "Unknown"

                        return details
                    else:
                        response_text = await response.text()
                        logger.warning(
                            f"Roblox user API error: {response.status} - {response_text}"
                        )
                    return None
        except Exception as e:
            logger.error(f"Error fetching Roblox user info: {e}")
            return None

    async def get_roblox_thumbnail(self, roblox_user_id: int) -> Optional[str]:
        """Get Roblox user thumbnail."""
        try:
            async with aiohttp.ClientSession() as session:
                url = (
                    "https://thumbnails.roblox.com/v1/users/avatar-headshot"
                    f"?userIds={roblox_user_id}&size=150x150&format=Png&isCircular=false"
                )

                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("data") and len(data["data"]) > 0:
                            return data["data"][0].get("imageUrl")
                    else:
                        response_text = await response.text()
                        logger.warning(
                            f"Roblox thumbnail API error: {response.status} - {response_text}"
                        )
                    return None
        except Exception as e:
            logger.error(f"Error fetching Roblox thumbnail: {e}")
            return None

    async def get_discord_from_roblox(self, roblox_id: str) -> Optional[dict]:
        """Get Discord account information from Roblox ID using Melonly API."""
        if not self.melonly_api_key:
            logger.warning("Melonly API key not configured")
            return None

        if not await self.melonly_rate_limiter.can_make_request():
            wait_time = await self.melonly_rate_limiter.get_wait_time()
            logger.warning(
                f"Melonly API rate limit exceeded. Next request allowed in {wait_time:.2f} seconds"
            )
            return None

        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api.melonly.xyz/api/v1/verification/roblox/{roblox_id}/discord"
                headers = {"Authorization": f"Bearer {self.melonly_api_key}"}

                async with session.get(url, headers=headers) as response:
                    await self.melonly_rate_limiter.record_request()

                    if response.status == 200:
                        data = await response.json()
                        return data
                    elif response.status == 400:
                        logger.warning(f"Invalid Roblox ID parameter: {roblox_id}")
                    elif response.status == 401:
                        logger.warning("Authentication required for Melonly API")
                    elif response.status == 404:
                        logger.info(f"No Discord account found for Roblox ID: {roblox_id}")
                    elif response.status == 429:
                        logger.warning("Melonly API rate limit exceeded")
                    elif response.status == 500:
                        logger.error("Melonly API internal server error")
                    else:
                        response_text = await response.text()
                        logger.warning(
                            f"Melonly API error: {response.status} - {response_text}"
                        )
                    return None
        except aiohttp.ClientError as e:
            logger.error(f"Network error fetching Discord info from Roblox ID: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching Discord info from Roblox ID: {e}")
            return None

    @commands.hybrid_command(name="userinfo", description="Get information about a user")
    @app_commands.describe(user="The user to get information about")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def userinfo(
        self,
        ctx: commands.Context,
        user: Optional[Union[discord.Member, discord.User]] = None,
    ):
        """Get information about a user."""
        if user is None:
            user = ctx.author

        from utils.scraping_detector import get_scraping_detector

        scraping_detector = get_scraping_detector()
        guild_id = ctx.guild.id if ctx.guild else None
        await scraping_detector.track_user_lookup(
            user_id=ctx.author.id,
            command="userinfo",
            target_user_id=user.id,
            guild_id=guild_id,
        )

        roblox_info = await self.get_bloxlink_info(user.id)
        roblox_details = None

        if not self.bloxlink_api_key:
            logger.warning(
                "Bloxlink API key not configured. Roblox data will not be fetched."
            )

        if roblox_info:
            roblox_user_id = roblox_info
            roblox_details = await self.get_roblox_user_info(roblox_user_id)

        badges = []

        if user.public_flags.staff:
            badges.append("Discord Staff")
        if user.public_flags.partner:
            badges.append("Discord Partner")
        if user.public_flags.hypesquad:
            badges.append("HypeSquad Events")
        if user.public_flags.bug_hunter:
            badges.append("Bug Hunter Level 1")
        if user.public_flags.bug_hunter_level_2:
            badges.append("Bug Hunter Level 2")
        if user.public_flags.hypesquad_bravery:
            badges.append("HypeSquad Bravery")
        if user.public_flags.hypesquad_brilliance:
            badges.append("HypeSquad Brilliance")
        if user.public_flags.hypesquad_balance:
            badges.append("HypeSquad Balance")
        if user.public_flags.early_supporter:
            badges.append("Early Supporter")
        if user.public_flags.team_user:
            badges.append("Team User")
        if getattr(user.public_flags, "verified_bot_developer", False):
            badges.append("Verified Bot Developer")
        if user.public_flags.active_developer:
            badges.append("Active Developer")
        if user.public_flags.verified_bot:
            badges.append("Verified Bot")
        if getattr(user.public_flags, "discord_certified_moderator", False):
            badges.append("Discord Certified Moderator")

        description = " • ".join(badges) if badges else ""

        user_info = f"**Mention:** <@{user.id}>\n"
        user_info += f"**Display Name:** {user.display_name}\n"
        user_info += (
            f"**Account Created:** <t:{int(user.created_at.timestamp())}:F> "
            f"(<t:{int(user.created_at.timestamp())}:R>)\n"
        )

        if isinstance(user, discord.Member) and user.joined_at:
            user_info += (
                f"**Joined Server:** <t:{int(user.joined_at.timestamp())}:F> "
                f"(<t:{int(user.joined_at.timestamp())}:R>)\n"
            )

        if roblox_details:
            roblox_username = roblox_details.get("username", "Unknown")
            user_info += f"**Roblox:** {roblox_username}\n"

        roles_section = ""
        if isinstance(user, discord.Member) and hasattr(user, "roles") and user.roles:
            user_roles = [role for role in user.roles if role.name != "@everyone"]
            if user_roles:
                user_roles.reverse()
                roles_section = ""
                for role in user_roles[:10]:
                    roles_section += f"{role.mention}\n"
                if len(user_roles) > 10:
                    roles_section += f"... and {len(user_roles) - 10} more"

        stats_info = ""

        try:
            mutual_guilds = []
            for guild in self.bot.guilds:
                if guild.get_member(user.id):
                    mutual_guilds.append(guild)

            if mutual_guilds:
                stats_info += f"**Mutual Servers:** {len(mutual_guilds)} servers\n"
        except Exception as e:
            logger.error(f"Error getting mutual servers count: {e}")

        try:
            blacklist_record = await self.bot.db.find_blacklist(user.id, active=True)
            if blacklist_record:
                stats_info += "**Status:** UEC Banned\n"
        except Exception as e:
            logger.error(f"Error checking blacklist status: {e}")

        fields = [{"name": "User Information", "value": user_info, "inline": False}]

        if roles_section:
            fields.append({"name": "Roles", "value": roles_section, "inline": False})

        if stats_info:
            fields.append({"name": "Statistics", "value": stats_info, "inline": False})

        embed = EmbedDesign.info(
            title="User Information",
            description=description,
            fields=fields,
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        await ctx.reply(embed=embed)

    @commands.hybrid_command(
        name="robloxinfo", description="Get Roblox information about a user"
    )
    @app_commands.describe(
        user="The Discord user to get Roblox information about",
        username="The Roblox username to get information about",
        roblox_id="The Roblox user ID to get information about",
    )
    async def roblox(
        self,
        ctx: commands.Context,
        user: Optional[discord.Member] = None,
        username: Optional[str] = None,
        roblox_id: Optional[str] = None,
    ):
        """Get Roblox information about a user."""
        if user is None and username is None and roblox_id is None:
            user = ctx.author

        if user and user != ctx.author:
            from utils.scraping_detector import get_scraping_detector

            scraping_detector = get_scraping_detector()
            guild_id = ctx.guild.id if ctx.guild else None
            await scraping_detector.track_user_lookup(
                user_id=ctx.author.id,
                command="robloxinfo",
                target_user_id=user.id,
                guild_id=guild_id,
            )

        roblox_user_id = None
        roblox_details = None

        if roblox_id:
            try:
                roblox_user_id = int(roblox_id)
                logger.info(f"Using provided Roblox ID: {roblox_user_id}")
            except ValueError:
                await ctx.reply(
                    embed=EmbedDesign.error(
                        title="Invalid Roblox ID",
                        description="Please provide a valid numeric Roblox user ID.",
                    )
                )
                return

        elif user:
            roblox_info = await self.get_bloxlink_info(user.id)
            if roblox_info:
                roblox_user_id = roblox_info
                logger.info(
                    f"Found Roblox user ID: {roblox_user_id} for Discord user {user.id}"
                )
            else:
                await ctx.reply(
                    embed=EmbedDesign.error(
                        title="No Roblox Account Found",
                        description=f"**{user.display_name}** is not linked to a Roblox account.",
                    )
                )
                return

        elif username:
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"https://users.roblox.com/v1/users/search?keyword={username}&limit=10"
                    logger.info(f"Searching for Roblox user: {username} at URL: {url}")

                    async with session.get(url) as response:
                        logger.info(
                            f"Roblox search API response status: {response.status}"
                        )

                        if response.status == 200:
                            data = await response.json()
                            logger.info(f"Roblox search API response data: {data}")

                            if data.get("data") and len(data["data"]) > 0:
                                exact_match = None
                                partial_match = None

                                for result_user in data["data"]:
                                    if result_user["name"].lower() == username.lower():
                                        exact_match = result_user
                                        break
                                    elif result_user["name"].lower().startswith(
                                        username.lower()
                                    ):
                                        partial_match = result_user

                                selected_user = exact_match or partial_match or data["data"][0]
                                roblox_user_id = selected_user["id"]
                                logger.info(
                                    f"Found Roblox user ID: {roblox_user_id} for username: {username}"
                                )
                            else:
                                alt_url = f"https://users.roblox.com/v1/users/search?keyword={username}"
                                logger.info(f"Trying alternative search URL: {alt_url}")

                                async with session.get(alt_url) as alt_response:
                                    if alt_response.status == 200:
                                        alt_data = await alt_response.json()
                                        if alt_data.get("data") and len(alt_data["data"]) > 0:
                                            roblox_user_id = alt_data["data"][0]["id"]
                                            logger.info(
                                                f"Found Roblox user ID via alternative search: {roblox_user_id}"
                                            )
                                        else:
                                            await ctx.reply(
                                                embed=EmbedDesign.error(
                                                    title="User Not Found",
                                                    description=f"No Roblox user found with username **{username}**.",
                                                )
                                            )
                                            return
                                    else:
                                        await ctx.reply(
                                            embed=EmbedDesign.error(
                                                title="User Not Found",
                                                description=f"No Roblox user found with username **{username}**.",
                                            )
                                        )
                                        return
                        else:
                            response_text = await response.text()
                            logger.warning(
                                f"Roblox search API error: {response.status} - {response_text}"
                            )
                            await ctx.reply(
                                embed=EmbedDesign.error(
                                    title="API Error",
                                    description=f"Failed to search for Roblox user. Status: {response.status}",
                                )
                            )
                            return
            except Exception as e:
                logger.error(f"Error searching for Roblox user: {e}")
                await ctx.reply(
                    embed=EmbedDesign.error(
                        title="Error",
                        description="An error occurred while searching for the Roblox user.",
                    )
                )
                return

        if roblox_user_id:
            roblox_details = await self.get_roblox_user_info(roblox_user_id)

        if not roblox_details:
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Error",
                    description="Failed to fetch Roblox user information.",
                )
            )
            return

        discord_info = await self.get_discord_from_roblox(str(roblox_user_id))
        roblox_thumbnail = await self.get_roblox_thumbnail(roblox_user_id)

        if (
            "displayName" in roblox_details
            and roblox_details["displayName"] != roblox_details.get("username")
        ):
            roblox_section = f"@{roblox_details['displayName']}\n"
        else:
            roblox_section = f"@{roblox_details.get('username', 'Unknown')}\n"

        roblox_section += f"**{roblox_details.get('username', 'Unknown')}** ({roblox_user_id})\n"
        roblox_section += f"**Profile:** https://www.roblox.com/users/{roblox_user_id}/profile\n"

        if "created" in roblox_details:
            created_date = datetime.fromisoformat(
                roblox_details["created"].replace("Z", "+00:00")
            )
            created_timestamp = int(created_date.timestamp())
            roblox_section += f"**Account Created:** <t:{created_timestamp}:F>\n"

        if "status" in roblox_details:
            roblox_section += f"**Description:** {roblox_details['status']}\n"

        discord_section = ""
        if discord_info:
            if "providerAccountId" in discord_info:
                discord_user = self.bot.get_user(int(discord_info["providerAccountId"]))
                if discord_user:
                    discord_section += f"{discord_user.name}\n"
                    discord_section += f"**Mention:** <@{discord_user.id}>\n"
                    discord_section += (
                        f"**Account Created:** <t:{int(discord_user.created_at.timestamp())}:F>\n"
                    )
                else:
                    discord_section += f"@{discord_info['providerAccountId']}\n"
                    discord_section += (
                        f"**Mention:** <@{discord_info['providerAccountId']}>\n"
                    )
                    discord_section += "**Account Created:** Unknown\n"
            else:
                discord_section += "No linked Discord account found"
        else:
            discord_section += "No linked Discord account found"

        fields = [
            {"name": "Roblox Information", "value": roblox_section, "inline": False}
        ]

        if discord_section:
            fields.append(
                {"name": "Discord Information", "value": discord_section, "inline": False}
            )

        embed = EmbedDesign.info(
            title="Roblox Information",
            fields=fields,
        )
        embed.set_thumbnail(
            url=roblox_thumbnail if roblox_thumbnail else "https://www.roblox.com/favicon.ico"
        )

        await ctx.reply(embed=embed)

    @commands.hybrid_command(name="serverinfo", description="Get information about the server")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def serverinfo(self, ctx: commands.Context):
        """Get information about the server."""
        guild = ctx.guild

        if guild is None:
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Unavailable",
                    description="This command can only be used in a server.",
                )
            )
            return

        total_members = guild.member_count
        bot_count = len([m for m in guild.members if m.bot])
        human_count = total_members - bot_count

        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)

        role_count = len(guild.roles)

        boost_level = guild.premium_tier
        boost_count = guild.premium_subscription_count or 0

        profile_section = f"**{guild.name}**\n"
        if guild.description:
            profile_section += f"{guild.description}\n"
        profile_section += f"`{guild.id}`\n"

        info_section = "🏠 **Server Information**\n"
        info_section += f"  • **Owner:** {guild.owner.mention if guild.owner else 'Unknown'}\n"
        info_section += f"  • **Created:** <t:{int(guild.created_at.timestamp())}:F>\n"
        info_section += f"  • **Age:** <t:{int(guild.created_at.timestamp())}:R>\n"

        stats_section = "📊 **Statistics**\n"
        stats_section += f"  • **Members:** {total_members:,} total\n"
        stats_section += f"    `{human_count:,} humans • {bot_count:,} bots`\n\n"
        stats_section += f"  • **Channels:** {text_channels + voice_channels + categories} total\n"
        stats_section += (
            f"    `{text_channels} text • {voice_channels} voice • {categories} categories`\n\n"
        )
        stats_section += f"  • **Roles:** {role_count} roles"

        boost_section = "🚀 **Boost Information**\n"
        if boost_level > 0:
            boost_section += f"  • **Boost Level:** {boost_level}\n"
            boost_section += f"  • **Boosts:** {boost_count:,}"
        else:
            boost_section += "  • **No boosts**"

        fields = [
            {"name": "Server Profile", "value": profile_section, "inline": False},
            {"name": "Server Information", "value": info_section, "inline": False},
            {"name": "Statistics", "value": stats_section, "inline": False},
            {"name": "Boost Information", "value": boost_section, "inline": False},
        ]

        embed = EmbedDesign.info(
            title="Server Information",
            fields=fields,
        )

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(InfoCommands(bot))
