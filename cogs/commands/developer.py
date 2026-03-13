import discord
from discord.ext import commands
from discord import app_commands
import typing
from utils.constants import Constants, logger, EmbedDesign
from utils.pagination import Paginator
from utils.staff import StaffUtils
from utils.twilio_verification import VerificationModal, TOTPVerificationModal, CommandVerifier
from utils.constants import EmbedDesign, Constants
from utils.database import DatabaseManager

# Initialize constants
constants = Constants()


class developer(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @commands.hybrid_command(name="sync", description="Sync the bot's commands")
    @app_commands.guilds(discord.Object(id=Constants().main_server_id()))
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def sync(self, ctx: commands.Context):
        if not await StaffUtils.has_developer_permission_cross_guild(self.bot, ctx.author, "manage_bot"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You don't have permission to sync commands. This requires Developer access."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        try:
            msg = await ctx.send("Syncing commands...")
            await msg.edit(content="Syncing guild commands...")
            await self.bot.tree.sync(guild=discord.Object(constants.main_server_id()))
            await msg.edit(content="Syncing global commands...")
            await self.bot.tree.sync()
            
            embed = EmbedDesign.success(
                title="Commands Synced",
                description="Successfully synced all commands."
            )
            await msg.edit(content=None, embed=embed)
        except Exception as e:
            embed = EmbedDesign.error(
                title="Sync Error",
                description=f"Error syncing commands: {str(e)}"
            )
            await msg.edit(content=None, embed=embed)
        
async def setup(bot):
    await bot.add_cog(developer(bot))