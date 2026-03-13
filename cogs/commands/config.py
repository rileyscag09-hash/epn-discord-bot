import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from typing import Optional
from utils.constants import logger, Constants, EmbedDesign
from utils.staff import StaffUtils

# Initialize constants
constants = Constants()

class ConfigCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config_views = {}

    async def get_current_configs(self, guild_id: int) -> dict:
        """Get current configurations for a guild using optimized single query."""
        configs = await self.bot.db.find_all_configs(guild_id)
        
        return {
            "log": configs["log_config"],
            "ping": configs["ping_config"],
            "alert": configs["alert_config"]
        }

    async def create_config_embed(self, guild: discord.Guild) -> discord.Embed:
        """Create embed with current configurations."""
        configs = await self.get_current_configs(guild.id)
        
        embed = EmbedDesign.info(
            title="Server Configuration",
            description="Use the buttons below to configure your settings:"
        )
        
        # Add current configurations to embed
        config_fields = []
        if configs["log"]:
            channel = guild.get_channel(configs["log"].get("channel_id"))
            config_fields.append(f"[*] **Log Channel:** {channel.mention if channel else 'Unknown'}")
        else:
            config_fields.append("[ ] **Log Channel:** Not configured")
            
        if configs["ping"]:
            role = guild.get_role(configs["ping"].get("role_id"))
            config_fields.append(f"[*] **Ping Role:** {role.mention if role else 'Unknown'}")
        else:
            config_fields.append("[ ] **Ping Role:** Not configured")
            
        if configs["alert"]:
            role = guild.get_role(configs["alert"].get("role_id"))
            config_fields.append(f"[*] **Alert Role:** {role.mention if role else 'Unknown'}")
        else:
            config_fields.append("[ ] **Alert Role:** Not configured")
        
        embed.add_field(name="Current Configurations", value="\n".join(config_fields), inline=False)
        
        return embed

    @commands.hybrid_command(name="config", description="Configure bot settings for this server")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def config(self, ctx: commands.Context):
        """Base command for configuration."""
        embed = await self.create_config_embed(ctx.guild)
        
        # Create configuration buttons
        log_button = discord.ui.Button(
            label="Log Channel",
            style=discord.ButtonStyle.primary,
            custom_id="config_log_channel"
        )
        ping_button = discord.ui.Button(
            label="Ping Role",
            style=discord.ButtonStyle.primary,
            custom_id="config_ping_role"
        )
        alert_button = discord.ui.Button(
            label="Alert Role",
            style=discord.ButtonStyle.primary,
            custom_id="config_alert_role"
        )
        clear_button = discord.ui.Button(
            label="Clear All",
            style=discord.ButtonStyle.danger,
            custom_id="clear_configs"
        )
        
        # Create view with buttons
        view = discord.ui.View()
        view.add_item(log_button)
        view.add_item(ping_button)
        view.add_item(alert_button)
        view.add_item(clear_button)
        
        await ctx.reply(embed=embed, view=view)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Handle all interactions including buttons."""
        if interaction.type == discord.InteractionType.component:
            # Get custom_id from the appropriate location based on component type
            custom_id = None
            if hasattr(interaction, 'custom_id'):
                custom_id = interaction.custom_id
            elif interaction.data and 'custom_id' in interaction.data:
                custom_id = interaction.data['custom_id']
            
            if custom_id:
                if custom_id == "config_log_channel":
                    await self.handle_log_channel_config(interaction)
                elif custom_id == "config_ping_role":
                    await self.handle_ping_role_config(interaction)
                elif custom_id == "config_alert_role":
                    await self.handle_alert_role_config(interaction)
                elif custom_id == "clear_configs":
                    await self.handle_clear_configs(interaction)
                elif custom_id == "confirm_clear_configs":
                    await self.confirm_clear_configs(interaction)
                elif custom_id == "cancel_clear_configs":
                    await self.cancel_clear_configs(interaction)

    async def handle_log_channel_config(self, interaction: discord.Interaction):
        """Handle log channel configuration button."""
        if not await StaffUtils.has_staff_permission_cross_guild(self.bot, interaction.user, "manage_messages"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You need Staff permissions to configure settings."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        modal = LogChannelModal(self.bot, interaction)
        await interaction.response.send_modal(modal)

    async def handle_ping_role_config(self, interaction: discord.Interaction):
        """Handle ping role configuration button."""
        if not await StaffUtils.has_staff_permission_cross_guild(self.bot, interaction.user, "manage_messages"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You need Staff permissions to configure settings."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        modal = RoleModal("ping", self.bot, interaction)
        await interaction.response.send_modal(modal)

    async def handle_alert_role_config(self, interaction: discord.Interaction):
        """Handle alert role configuration button."""
        if not await StaffUtils.has_staff_permission_cross_guild(self.bot, interaction.user, "manage_messages"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You need Staff permissions to configure settings."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        modal = RoleModal("alert", self.bot, interaction)
        await interaction.response.send_modal(modal)

    async def handle_clear_configs(self, interaction: discord.Interaction):
        """Handle clear configurations button."""
        if not await StaffUtils.has_staff_permission_cross_guild(self.bot, interaction.user, "manage_messages"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You need Staff permissions to clear configurations."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Get current configurations
        configs = await self.get_current_configs(interaction.guild.id)

        if not any(configs.values()):
            embed = EmbedDesign.warning(
                title="No Configurations Found",
                description="No configurations are currently set for this server."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Create confirmation embed
        embed = EmbedDesign.warning(
            title="Clear All Configurations",
            description="Are you sure you want to clear all configurations for this server? This action cannot be undone."
        )
        
        # Add current configurations to embed
        configs_list = []
        if configs["log"]:
            channel = interaction.guild.get_channel(configs["log"].get("channel_id"))
            configs_list.append(f"Log Channel: {channel.mention if channel else 'Unknown'}")
        if configs["ping"]:
            role = interaction.guild.get_role(configs["ping"].get("role_id"))
            configs_list.append(f"Ping Role: {role.mention if role else 'Unknown'}")
        if configs["alert"]:
            role = interaction.guild.get_role(configs["alert"].get("role_id"))
            configs_list.append(f"Alert Role: {role.mention if role else 'Unknown'}")
        
        if configs_list:
            embed.add_field(name="Current Configurations", value="\n".join(configs_list), inline=False)

        # Create confirmation buttons
        confirm_button = discord.ui.Button(
            label="Confirm Clear",
            style=discord.ButtonStyle.danger,
            custom_id="confirm_clear_configs"
        )
        cancel_button = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.secondary,
            custom_id="cancel_clear_configs"
        )
        
        view = discord.ui.View()
        view.add_item(confirm_button)
        view.add_item(cancel_button)
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def confirm_clear_configs(self, interaction: discord.Interaction):
        """Confirm clearing all configurations."""
        try:
            # Clear all configurations
            # Clear all configurations by setting them inactive
            # Clear all configurations
            await self.bot.db.clear_log_configs(interaction.guild.id)
            await self.bot.db.clear_ping_configs(interaction.guild.id) 
            await self.bot.db.clear_alert_configs(interaction.guild.id)
            
            # Update the original config message
            try:
                original_embed = await self.bot.get_cog('ConfigCommands').create_config_embed(interaction.guild)
                await interaction.message.edit(embed=original_embed)
            except Exception as e:
                logger.error(f"Error updating original message: {e}")
            
            embed = EmbedDesign.success(
                title="Configurations Cleared",
                description="All configurations have been cleared for this server."
            )
            await interaction.response.edit_message(embed=embed, view=None)
            
        except Exception as e:
            logger.error(f"Error clearing configurations: {e}")
            embed = EmbedDesign.error(
                title="Error",
                description="An error occurred while clearing configurations."
            )
            await interaction.response.edit_message(embed=embed, view=None)

    async def cancel_clear_configs(self, interaction: discord.Interaction):
        """Cancel clearing configurations."""
        embed = EmbedDesign.info(
            title="Operation Cancelled",
            description="Configuration clearing has been cancelled."
        )
        await interaction.response.edit_message(embed=embed, view=None)

class LogChannelModal(discord.ui.Modal, title="Configure Log Channel"):
    def __init__(self, bot: commands.Bot, original_interaction: discord.Interaction):
        super().__init__()
        self.bot = bot
        self.original_interaction = original_interaction
        self.channel_id = discord.ui.TextInput(
            label="Channel ID",
            placeholder="Enter the channel ID for logging",
            required=True,
            min_length=10,
            max_length=20
        )
        self.add_item(self.channel_id)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission for log channel configuration."""
        await interaction.response.defer(ephemeral=True)
        try:
            channel_id = int(self.channel_id.value)
            channel = interaction.guild.get_channel(channel_id)
            
            if not channel or not isinstance(channel, discord.TextChannel):
                embed = EmbedDesign.error(title="Invalid Channel", description="Please provide a valid text channel ID.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            if not channel.permissions_for(interaction.guild.me).send_messages:
                embed = EmbedDesign.error(title="Permission Error", description="I don't have permission to send messages in that channel.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            await self.bot.db.clear_log_configs(interaction.guild.id)
            await self.bot.db.insert_log_config(interaction.guild.id, channel.id, interaction.user.id)
            
            try:
                original_embed = await self.bot.get_cog('ConfigCommands').create_config_embed(interaction.guild)
                await self.original_interaction.message.edit(embed=original_embed)
            except Exception as e:
                logger.error(f"Error updating original message: {e}")
            
            embed = EmbedDesign.success(title="Log Channel Configured", description=f"Log channel has been set to {channel.mention}")
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except ValueError:
            embed = EmbedDesign.error(title="Invalid Input", description="Please provide a valid channel ID.")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error configuring log channel: {e}")
            embed = EmbedDesign.error(title="Error", description="An error occurred while configuring the log channel.")
            await interaction.followup.send(embed=embed, ephemeral=True)

class RoleModal(discord.ui.Modal, title="Configure Role"):
    def __init__(self, role_type: str, bot: commands.Bot, original_interaction: discord.Interaction):
        super().__init__()
        self.role_type = role_type
        self.bot = bot
        self.original_interaction = original_interaction
        self.role_id = discord.ui.TextInput(
            label="Role ID",
            placeholder="Enter the role ID",
            required=True,
            min_length=10,
            max_length=20
        )
        self.add_item(self.role_id)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission for role configuration."""
        await interaction.response.defer(ephemeral=True)
        try:
            role_id = int(self.role_id.value)
            role = interaction.guild.get_role(role_id)
            
            if not role:
                embed = EmbedDesign.error(title="Invalid Role", description="The provided role ID is not valid or the role doesn't exist.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            if self.role_type == "ping":
                await self.bot.db.clear_ping_configs(interaction.guild.id)
                await self.bot.db.insert_ping_config(interaction.guild.id, role.id, interaction.user.id)
            elif self.role_type == "alert":
                await self.bot.db.clear_alert_configs(interaction.guild.id)
                await self.bot.db.insert_alert_config(interaction.guild.id, role.id, interaction.user.id)
            
            try:
                original_embed = await self.bot.get_cog('ConfigCommands').create_config_embed(interaction.guild)
                await self.original_interaction.message.edit(embed=original_embed)
            except Exception as e:
                logger.error(f"Error updating original message: {e}")
            
            role_type_display = "Ping" if self.role_type == "ping" else "Alert"
            
            embed = EmbedDesign.success(title=f"{role_type_display} Role Configured", description=f"{role_type_display} role has been set to {role.mention}")
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except ValueError:
            embed = EmbedDesign.error(title="Invalid Input", description="Please provide a valid role ID.")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error configuring {self.role_type} role: {e}")
            embed = EmbedDesign.error(title="Error", description=f"An error occurred while configuring the {self.role_type} role.")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ConfigCommands(bot)) 