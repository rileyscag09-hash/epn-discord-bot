import discord
from discord.ext import commands
from typing import Dict, List, Optional, Any
from datetime import datetime
import io
from utils.constants import logger

class ModerationReportView(discord.ui.View):
    """Clean moderation report view with simple buttons."""
    
    def __init__(self, report_id: str, timeout: float = 86400):
        super().__init__(timeout=timeout)
        self.report_id = report_id

    @discord.ui.button(label="Accept Report", style=discord.ButtonStyle.danger, emoji="✅")
    async def accept_report(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Accept the moderation report and delete the message."""
        if not await self._check_staff_permission(interaction):
            await interaction.response.send_message("❌ You don't have permission to accept this report.", ephemeral=True)
            return

        try:
            embed = interaction.message.embeds[0]
            
            # Update embed to show accepted
            embed.color = 0xFF4444  # Red
            embed.add_field(
                name="✅ Status",
                value=f"**ACCEPTED** by {interaction.user.mention}\n*Message deleted*",
                inline=False
            )

            # Disable all buttons
            for item in self.children:
                item.disabled = True

            await interaction.response.edit_message(embed=embed, view=self)
            await self._delete_message(interaction, embed)

        except Exception as e:
            logger.error(f"Error accepting report: {e}")
            await interaction.response.send_message("❌ Error processing report acceptance.", ephemeral=True)

    @discord.ui.button(label="Deny Report", style=discord.ButtonStyle.secondary, emoji="❌")
    async def deny_report(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Deny the moderation report."""
        if not await self._check_staff_permission(interaction):
            await interaction.response.send_message("❌ You don't have permission to deny this report.", ephemeral=True)
            return

        try:
            embed = interaction.message.embeds[0]
            
            # Update embed to show denied
            embed.color = 0x00AA00  # Green
            embed.add_field(
                name="❌ Status",
                value=f"**DENIED** by {interaction.user.mention}\n*No action taken*",
                inline=False
            )

            # Disable all buttons
            for item in self.children:
                item.disabled = True

            await interaction.response.edit_message(embed=embed, view=self)

        except Exception as e:
            logger.error(f"Error denying report: {e}")
            await interaction.response.send_message("❌ Error processing report denial.", ephemeral=True)

    @discord.ui.button(label="View Message", style=discord.ButtonStyle.primary, emoji="🔗")
    async def view_message(self, interaction: discord.Interaction, button: discord.ui.Button):
        """View the original message."""
        try:
            embed = interaction.message.embeds[0]
            
            # Find the message link in the embed
            message_link = None
            for field in embed.fields:
                if "View Message" in field.name or "Jump to Message" in field.name:
                    # Extract URL from markdown link
                    import re
                    match = re.search(r'\[.*?\]\((.*?)\)', field.value)
                    if match:
                        message_link = match.group(1)
                        break
            
            if message_link:
                await interaction.response.send_message(f"🔗 [Click here to view the message]({message_link})", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Could not find message link.", ephemeral=True)

        except Exception as e:
            logger.error(f"Error viewing message: {e}")
            await interaction.response.send_message("❌ Error retrieving message link.", ephemeral=True)

    async def _check_staff_permission(self, interaction: discord.Interaction) -> bool:
        """Check if user has staff permissions."""
        try:
            # Check if user has manage_messages permission
            if interaction.user.guild_permissions.manage_messages:
                return True
            
            # Check if user has administrator permission
            if interaction.user.guild_permissions.administrator:
                return True
                
            return False
        except:
            return False

    async def _delete_message(self, interaction: discord.Interaction, embed: discord.Embed):
        """Delete the original message."""
        try:
            # Extract message info from embed
            guild_id = None
            channel_id = None
            message_id = None

            for field in embed.fields:
                if "Location" in field.name:
                    # Extract channel ID from the field value
                    import re
                    match = re.search(r'<#(\d+)>', field.value)
                    if match:
                        channel_id = int(match.group(1))
                elif "View Message" in field.name or "Jump to Message" in field.name:
                    # Extract message ID from URL
                    import re
                    match = re.search(r'/channels/\d+/(\d+)/(\d+)', field.value)
                    if match:
                        message_id = int(match.group(2))

            if not all([channel_id, message_id]):
                logger.error("Could not extract required IDs from report embed")
                return

            bot = interaction.client
            channel = bot.get_channel(channel_id)
            if not channel:
                logger.error(f"Channel {channel_id} not found")
                return

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
    """Clean moderation report manager."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def send_moderation_report(self, scan_data: Dict[str, Any], message: discord.Message) -> Optional[discord.Message]:
        """Send a clean moderation report."""
        try:
            report_channel = self.bot.get_channel(scan_data.get('report_channel_id'))
            if not report_channel:
                logger.error("Report channel not found")
                return None

            # Create clean embed
            embed = self._create_clean_embed(scan_data, message)
            
            # Create view
            report_id = f"{message.guild.id}_{message.channel.id}_{message.id}"
            view = ModerationReportView(report_id)
            
            # Send report
            report_message = await report_channel.send(embed=embed, view=view)
            
            logger.info(f"Sent clean moderation report {report_id} for message {message.id}")
            return report_message

        except Exception as e:
            logger.error(f"Error sending moderation report: {e}")
            return None

    def _create_clean_embed(self, scan_data: Dict[str, Any], message: discord.Message) -> discord.Embed:
        """Create a clean, user-friendly moderation report embed."""
        try:
            # Determine severity and color
            ai_confidence = scan_data.get('ai_confidence', {})
            confidence = ai_confidence.get('confidence', 0.0)
            severity = "HIGH" if confidence > 0.8 else "MEDIUM" if confidence > 0.5 else "LOW"
            
            # Clean color scheme
            colors = {
                "HIGH": 0xFF4444,    # Red
                "MEDIUM": 0xFF8800,  # Orange  
                "LOW": 0xFFAA00      # Yellow
            }
            
            # Create clean embed
            embed = discord.Embed(
                title=f"🚨 Moderation Alert - {severity}",
                description=f"**{message.author.display_name}** sent potentially problematic content",
                color=colors.get(severity, 0xFF8800)
            )
            
            # Add user info in a clean way
            embed.add_field(
                name="👤 User",
                value=f"{message.author.mention}\n`{message.author.id}`",
                inline=True
            )
            embed.add_field(
                name="📍 Location", 
                value=f"#{message.channel.name}\n`{message.guild.name}`",
                inline=True
            )
            embed.add_field(
                name="⏰ Time",
                value=f"<t:{int(message.created_at.timestamp())}:R>",
                inline=True
            )
            
            # Add the flagged content in a clean way
            content = message.content
            if content:
                # Truncate long content
                display_content = content[:200] + "..." if len(content) > 200 else content
                embed.add_field(
                    name="💬 Message Content",
                    value=f"```{display_content}```",
                    inline=False
                )
            
            # Add AI analysis in a clean way
            if ai_confidence:
                confidence_pct = int(confidence * 100)
                reasoning = ai_confidence.get('reasoning', 'No analysis available')
                
                # Clean up reasoning
                if len(reasoning) > 150:
                    reasoning = reasoning[:150] + "..."
                
                embed.add_field(
                    name="🤖 AI Analysis",
                    value=f"**Confidence:** {confidence_pct}%\n**Analysis:** {reasoning}",
                    inline=False
                )
            
            # Add detected issues in a clean way
            text_analysis = scan_data.get('text_analysis', {})
            flagged_categories = text_analysis.get('flagged_categories', [])
            
            if flagged_categories:
                # Convert technical names to user-friendly names
                friendly_names = {
                    'harassment': 'Harassment',
                    'harassment_threatening': 'Threatening Language',
                    'violence': 'Violence',
                    'hate': 'Hate Speech',
                    'hate_threatening': 'Threatening Hate',
                    'sexual': 'Sexual Content',
                    'sexual_minors': 'Minor Sexual Content',
                    'self_harm': 'Self-Harm',
                    'self_harm_intent': 'Self-Harm Intent',
                    'self_harm_instructions': 'Self-Harm Instructions',
                    'illicit': 'Illicit Content',
                    'illicit_violent': 'Violent Illicit Content',
                    'violence_graphic': 'Graphic Violence'
                }
                
                friendly_categories = [friendly_names.get(cat, cat.replace('_', ' ').title()) for cat in flagged_categories]
                
                embed.add_field(
                    name="⚠️ Detected Issues",
                    value="• " + "\n• ".join(friendly_categories),
                    inline=False
                )
            
            # Add image info if present
            image_analysis = scan_data.get('image_analysis', [])
            if image_analysis:
                flagged_images = [img for img in image_analysis if img.get('flagged')]
                if flagged_images:
                    embed.add_field(
                        name="🖼️ Images",
                        value=f"{len(flagged_images)} image(s) flagged - see attachments below",
                        inline=False
                    )
            
            # Add message link
            embed.add_field(
                name="🔗 Quick Actions",
                value=f"[View Message]({message.jump_url}) • [Jump to Channel](https://discord.com/channels/{message.guild.id}/{message.channel.id})",
                inline=False
            )
            
            # Clean footer
            embed.set_footer(text="Use the buttons below to take action")
            
            return embed
            
        except Exception as e:
            logger.error(f"Error creating clean report embed: {e}")
            # Return basic embed if creation fails
            return discord.Embed(
                title="🚨 Moderation Alert",
                description=f"Content flagged by AI moderation from {message.author.display_name}",
                color=0xFF8800,
                fields=[
                    {"name": "User", "value": f"{message.author.mention}", "inline": True},
                    {"name": "Channel", "value": f"#{message.channel.name}", "inline": True},
                    {"name": "Message", "value": f"[View Message]({message.jump_url})", "inline": False}
                ]
            )

    async def send_image_attachments(self, scan_data: Dict[str, Any], message: discord.Message, report_channel: discord.TextChannel):
        """Send image attachments to the report channel."""
        try:
            if not message.attachments:
                return

            flagged_images = []
            for attachment in message.attachments:
                if attachment.content_type and attachment.content_type.startswith('image/'):
                    flagged_images.append(attachment)

            if not flagged_images:
                return

            # Send images as attachments
            files = []
            for attachment in flagged_images:
                try:
                    file_data = await attachment.read()
                    file_obj = discord.File(io.BytesIO(file_data), filename=attachment.filename)
                    files.append(file_obj)
                except Exception as e:
                    logger.error(f"Error processing image {attachment.filename}: {e}")

            if files:
                embed = discord.Embed(
                    title="🖼️ Flagged Images",
                    description=f"Images from {message.author.display_name}'s message",
                    color=0xFF8800
                )
                await report_channel.send(embed=embed, files=files)

        except Exception as e:
            logger.error(f"Error sending image attachments: {e}")

# Global instance
_moderation_report_manager = None

def get_moderation_report_manager(bot: commands.Bot) -> ModerationReportManager:
    """Get or create the global moderation report manager."""
    global _moderation_report_manager
    if _moderation_report_manager is None:
        _moderation_report_manager = ModerationReportManager(bot)
    return _moderation_report_manager
