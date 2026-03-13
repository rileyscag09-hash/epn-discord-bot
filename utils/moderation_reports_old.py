import discord
from discord.ext import commands
from typing import Dict, List, Optional, Any
from datetime import datetime
import io
from utils.constants import logger, EmbedDesign

class ModerationReportView(discord.ui.View):
    """View for moderation reports with accept/deny buttons."""
    
    def __init__(self, report_id: str, timeout: float = 86400):  # 24 hour timeout
        super().__init__(timeout=timeout)
        self.report_id = report_id
    
    @discord.ui.button(label="Accept Report", style=discord.ButtonStyle.danger, emoji="✅")
    async def accept_report(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Accept the moderation report and take action."""
        try:
            # Get the original embed
            embed = interaction.message.embeds[0]
            
            # Update embed to show accepted
            embed.color = 0xFF0000  # Red
            embed.add_field(
                name="Status",
                value=f"✅ **ACCEPTED** by {interaction.user.mention}",
                inline=False
            )
            embed.add_field(
                name="Action Taken",
                value="Message deleted",
                inline=False
            )
            
            # Disable all buttons
            for item in self.children:
                item.disabled = True
            
            await interaction.response.edit_message(embed=embed, view=self)
            
            # Take moderation action
            await self._execute_moderation_action(interaction, embed)
            
        except Exception as e:
            logger.error(f"Error accepting report: {e}")
            await interaction.response.send_message("Error processing report acceptance.", ephemeral=True)
    
    @discord.ui.button(label="Deny Report", style=discord.ButtonStyle.secondary, emoji="❌")
    async def deny_report(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Deny the moderation report."""
        try:
            # Get the original embed
            embed = interaction.message.embeds[0]
            
            # Update embed to show denied
            embed.color = 0x00FF00  # Green
            embed.add_field(
                name="Status",
                value=f"❌ **DENIED** by {interaction.user.mention}",
                inline=False
            )
            embed.add_field(
                name="Reason",
                value="Content determined to be acceptable",
                inline=False
            )
            
            # Disable all buttons
            for item in self.children:
                item.disabled = True
            
            await interaction.response.edit_message(embed=embed, view=self)
            
        except Exception as e:
            logger.error(f"Error denying report: {e}")
            await interaction.response.send_message("Error processing report denial.", ephemeral=True)
    
    @discord.ui.button(label="View Message", style=discord.ButtonStyle.primary, emoji="🔗")
    async def view_message(self, interaction: discord.Interaction, button: discord.ui.Button):
        """View the original message."""
        try:
            # Get message link from embed
            embed = interaction.message.embeds[0]
            message_link = None
            
            for field in embed.fields:
                if "Message Link" in field.name:
                    message_link = field.value
                    break
            
            if message_link:
                await interaction.response.send_message(f"Original message: {message_link}", ephemeral=True)
            else:
                await interaction.response.send_message("Message link not found.", ephemeral=True)
                
        except Exception as e:
            logger.error(f"Error viewing message: {e}")
            await interaction.response.send_message("Error retrieving message link.", ephemeral=True)
    
    async def _execute_moderation_action(self, interaction: discord.Interaction, embed: discord.Embed):
        """Execute moderation action after report acceptance."""
        try:
            # Extract guild and channel info from embed
            guild_id = None
            channel_id = None
            message_id = None
            
            for field in embed.fields:
                if "Server" in field.name:
                    # Extract guild ID
                    import re
                    match = re.search(r'\((\d+)\)', field.value)
                    if match:
                        guild_id = int(match.group(1))
                elif "Channel" in field.name:
                    # Extract channel ID
                    import re
                    match = re.search(r'<#(\d+)>', field.value)
                    if match:
                        channel_id = int(match.group(1))
                elif "Message Link" in field.name:
                    # Extract message ID from jump URL
                    import re
                    match = re.search(r'/channels/\d+/(\d+)/(\d+)', field.value)
                    if match:
                        message_id = int(match.group(2))
            
            if not all([guild_id, channel_id, message_id]):
                logger.error("Could not extract required IDs from report embed")
                return
            
            # Get the bot instance
            bot = interaction.client
            
            # Get guild
            guild = bot.get_guild(guild_id)
            if not guild:
                logger.error(f"Guild {guild_id} not found")
                return
            
            # Get channel
            channel = guild.get_channel(channel_id)
            if not channel:
                logger.error(f"Channel {channel_id} not found in guild {guild_id}")
                return
            
            # Try to get and delete the message
            try:
                message = await channel.fetch_message(message_id)
                await message.delete()
                logger.info(f"Deleted message {message_id} from channel {channel_id}")
                
            except discord.NotFound:
                logger.warning(f"Message {message_id} not found, may have been already deleted")
            except discord.Forbidden:
                logger.error(f"No permission to delete message {message_id}")
            except Exception as e:
                logger.error(f"Error deleting message {message_id}: {e}")
            
        except Exception as e:
            logger.error(f"Error executing moderation action: {e}")

class ModerationReportManager:
    """Manager for moderation reports."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.report_channel_id = None  # Will be set from constants
        self.active_reports: Dict[str, discord.Message] = {}
    
    async def send_moderation_report(self, scan_data: Dict[str, Any], message: discord.Message) -> Optional[discord.Message]:
        """Send a moderation report to the report channel."""
        try:
            # Get report channel
            if not self.report_channel_id:
                from utils.constants import constants
                self.report_channel_id = constants.report_channel_id()
            
            report_channel = self.bot.get_channel(self.report_channel_id)
            if not report_channel:
                logger.error(f"Report channel {self.report_channel_id} not found")
                return None
            
            # Create report embed
            embed = await self._create_report_embed(scan_data, message)
            
            # Create view with buttons
            report_id = f"{message.guild.id}_{message.id}_{int(datetime.utcnow().timestamp())}"
            view = ModerationReportView(report_id)
            
            # Send report
            report_message = await report_channel.send(embed=embed, view=view)
            
            # Store active report
            self.active_reports[report_id] = report_message
            
            logger.info(f"Sent moderation report {report_id} for message {message.id}")
            return report_message
            
        except Exception as e:
            logger.error(f"Error sending moderation report: {e}")
            return None
    
    async def _create_report_embed(self, scan_data: Dict[str, Any], message: discord.Message) -> discord.Embed:
        """Create embed for moderation report."""
        try:
            # Determine severity and color
            severity = "HIGH" if scan_data.get('ai_confidence', {}).get('confidence', 0) > 0.8 else "MEDIUM"
            color = 0xFF0000 if severity == "HIGH" else 0xFFA500
            
            # Create base embed
            embed = EmbedDesign.error(
                title=f"🤖 AI Moderation Report - {severity}",
                description=f"**{message.author.display_name}** sent content flagged by AI moderation."
            )
            
            # Set custom color if provided
            if color:
                embed.color = color
            
            # Add basic info
            embed.add_field(
                name="User",
                value=f"{message.author.mention} ({message.author.id})",
                inline=True
            )
            embed.add_field(
                name="Server",
                value=f"{message.guild.name} ({message.guild.id})",
                inline=True
            )
            embed.add_field(
                name="Channel",
                value=f"{message.channel.mention}",
                inline=True
            )
            
            # Add message info
            embed.add_field(
                name="Message Link",
                value=f"[Jump to Message]({message.jump_url})",
                inline=True
            )
            embed.add_field(
                name="Message Type",
                value=scan_data.get('message_type', 'normal').title(),
                inline=True
            )
            embed.add_field(
                name="Timestamp",
                value=f"<t:{int(message.created_at.timestamp())}:F>",
                inline=True
            )
            
            # Add content
            content = message.content[:1000] + "..." if len(message.content) > 1000 else message.content
            embed.add_field(
                name="Content",
                value=content if content else "*No text content*",
                inline=False
            )
            
            # Add AI analysis
            ai_confidence = scan_data.get('ai_confidence', {})
            embed.add_field(
                name="AI Confidence",
                value=f"{ai_confidence.get('confidence', 0):.2f}",
                inline=True
            )
            embed.add_field(
                name="AI Reasoning",
                value=ai_confidence.get('reasoning', 'No reasoning provided')[:200] + "...",
                inline=False
            )
            
            # Add OpenAI moderation results
            text_analysis = scan_data.get('text_analysis', {})
            if text_analysis.get('flagged_categories'):
                embed.add_field(
                    name="OpenAI Categories",
                    value=", ".join(text_analysis['flagged_categories']),
                    inline=False
                )
            
            # Add image analysis
            image_analysis = scan_data.get('image_analysis', [])
            if image_analysis:
                image_info = []
                for img in image_analysis:
                    if img.get('flagged'):
                        image_info.append(f"🚩 {img.get('filename', 'unknown')}: {', '.join(img.get('categories', []))}")
                    else:
                        image_info.append(f"✅ {img.get('filename', 'unknown')}: Clean")
                
                embed.add_field(
                    name="Image Analysis",
                    value="\n".join(image_info),
                    inline=False
                )
            
            # Add attachments if any
            if message.attachments:
                attachment_info = []
                for att in message.attachments:
                    attachment_info.append(f"📎 {att.filename} ({att.size} bytes)")
                
                embed.add_field(
                    name="Attachments",
                    value="\n".join(attachment_info),
                    inline=False
                )
            
            # Add footer
            embed.set_footer(text=f"Report ID: {scan_data.get('message_id', 'unknown')} • Use buttons below to take action")
            
            return embed
            
        except Exception as e:
            logger.error(f"Error creating report embed: {e}")
            # Return basic embed if creation fails
            return EmbedDesign.error(
                title="AI Moderation Report",
                description=f"Content flagged by AI moderation from {message.author.display_name}",
                fields=[
                    {"name": "Error", "value": str(e), "inline": False}
                ]
            )
    
    async def send_image_attachments(self, scan_data: Dict[str, Any], message: discord.Message, report_channel: discord.TextChannel):
        """Send image attachments to report channel for preservation."""
        try:
            if not message.attachments:
                return
            
            # Filter for images
            image_attachments = [att for att in message.attachments if att.content_type and att.content_type.startswith('image/')]
            
            if not image_attachments:
                return
            
            # Send images as attachments
            files = []
            for att in image_attachments:
                try:
                    file_data = await att.read()
                    files.append(discord.File(io.BytesIO(file_data), filename=att.filename))
                except Exception as e:
                    logger.error(f"Error downloading attachment {att.filename}: {e}")
            
            if files:
                embed = EmbedDesign.info(
                    title="📷 Flagged Images",
                    description=f"Images from message by {message.author.display_name}",
                    fields=[
                        {"name": "Message Link", "value": f"[Jump to Message]({message.jump_url})", "inline": True},
                        {"name": "Count", "value": str(len(files)), "inline": True}
                    ]
                )
                
                await report_channel.send(embed=embed, files=files)
                logger.info(f"Sent {len(files)} image attachments to report channel")
                
        except Exception as e:
            logger.error(f"Error sending image attachments: {e}")

# Global instance
moderation_report_manager = None

def get_moderation_report_manager(bot: commands.Bot) -> ModerationReportManager:
    """Get or create the global moderation report manager."""
    global moderation_report_manager
    if moderation_report_manager is None:
        moderation_report_manager = ModerationReportManager(bot)
    return moderation_report_manager
