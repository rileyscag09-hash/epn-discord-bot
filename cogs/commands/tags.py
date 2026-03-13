import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from typing import Optional, List
from utils.constants import logger, Constants, EmbedDesign
from utils.staff import StaffUtils
from utils.validation import validate_input, InputSanitizer
from utils.security_logger import get_security_logger, SecurityEventType, SecurityEventSeverity

# Initialize constants
constants = Constants()

class TagCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_tag(self, guild_id: int, tag_name: str) -> Optional[dict]:
        """Get a tag by name for a specific guild."""
        return await self.bot.db.find_tag(guild_id, tag_name)

    async def get_all_tags(self, guild_id: int) -> List[dict]:
        """Get all active tags for a guild."""
        return await self.bot.db.find_all_tags(guild_id)

    async def create_tag_embed(self, tag: dict, guild: discord.Guild) -> discord.Embed:
        """Create embed for displaying a tag."""
        creator = guild.get_member(tag.get("created_by"))
        creator_mention = creator.mention if creator else f"<@{tag.get('created_by')}>"
        
        embed = EmbedDesign.info(
            title=f"Tag: {tag['name']}",
            description=tag['content'],
            fields=[
                {"name": "Created by", "value": creator_mention, "inline": True},
                {"name": "Created", "value": tag['created_at'].strftime("%Y-%m-%d %H:%M:%S"), "inline": True},
                {"name": "Uses", "value": str(tag.get('uses', 0)), "inline": True}
            ]
        )
        
        if tag.get('last_used'):
            embed.add_field(name="Last Used", value=tag['last_used'].strftime("%Y-%m-%d %H:%M:%S"), inline=True)
        
        return embed

    async def create_tags_list_embed(self, guild: discord.Guild) -> discord.Embed:
        """Create embed listing all tags for a guild."""
        tags = await self.get_all_tags(guild.id)
        
        if not tags:
            embed = EmbedDesign.info(
                title="Support Tags",
                description="No tags have been created yet. Use `/tag create` to create your first tag!"
            )
            return embed
        
        # Group tags by category
        categories = {}
        for tag in tags:
            category = tag.get('category', 'General')
            if category not in categories:
                categories[category] = []
            categories[category].append(tag)
        
        # Build description
        description_parts = []
        for category, category_tags in categories.items():
            tag_list = ", ".join([f"`{tag['name']}`" for tag in category_tags])
            description_parts.append(f"**{category}:** {tag_list}")
        
        embed = EmbedDesign.info(
            title="Support Tags",
            description="\n".join(description_parts),
            fields=[
                {"name": "Total Tags", "value": str(len(tags)), "inline": True},
                {"name": "Categories", "value": str(len(categories)), "inline": True}
            ]
        )
        
        return embed

    @commands.hybrid_group(name="tag", description="Manage support tags")
    @app_commands.guilds(discord.Object(id=Constants().main_server_id()))
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def tag(self, ctx: commands.Context):
        """Base command for tag management."""
        if ctx.invoked_subcommand is None:
            embed = EmbedDesign.info(
                title="Tag Commands",
                description="Available subcommands:\n"
                          "• `/tag create` - Create a new tag\n"
                          "• `/tag list` - List all tags\n"
                          "• `/tag view <name>` - View a specific tag\n"
                          "• `/tag edit <name>` - Edit a tag\n"
                          "• `/tag delete <name>` - Delete a tag\n"
                          "• `/tag search <query>` - Search for tags"
            )
            await ctx.reply(embed=embed, ephemeral=True)

    @tag.command(name="create", description="Create a new support tag")
    async def tag_create(self, ctx: commands.Context):
        """Create a new tag."""
        # Check permissions - only bot staff can create tags
        if not await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "manage_messages"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You need to be a staff member to create tags."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Show create tag modal
        modal = CreateTagModal(self.bot, ctx.interaction)
        await ctx.interaction.response.send_modal(modal)

    @tag.command(name="list", description="List all available tags")
    async def tag_list(self, ctx: commands.Context):
        """List all tags."""
        # Check permissions - only staff can list tags
        if not await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "manage_messages"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You need to be a staff member to view tags."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        embed = await self.create_tags_list_embed(ctx.guild)
        await ctx.reply(embed=embed)

    @tag.command(name="view", description="View a specific tag")
    @app_commands.describe(tag_name="Name of the tag to view")
    @validate_input(max_length=50, pattern="alphanumeric")
    async def tag_view(self, ctx: commands.Context, tag_name: str):
        """View a specific tag."""
        # Check permissions - only staff can view tags
        if not await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "manage_messages"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You need to be a staff member to view tags."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        tag = await self.get_tag(ctx.guild.id, tag_name)
        if not tag:
            embed = EmbedDesign.error(
                title="Tag Not Found",
                description=f"Tag `{tag_name}` not found. Use `/tag list` to see available tags."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Update usage statistics
        await self.bot.db.update_tag_usage(tag["id"])
        
        # Send tag as a simple embed (title = tag name, description = tag content)
        embed = EmbedDesign.info(title=tag['name'], description=tag['content'])
        await ctx.reply(embed=embed)

    @tag.command(name="edit", description="Edit an existing tag")
    @app_commands.describe(tag_name="Name of the tag to edit")
    @validate_input(max_length=50, pattern="alphanumeric")
    async def tag_edit(self, ctx: commands.Context, tag_name: str):
        """Edit a tag."""
        # Check permissions - only bot staff can edit tags
        if not await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "manage_messages"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You need to be a staff member to edit tags."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        tag = await self.get_tag(ctx.guild.id, tag_name)
        if not tag:
            embed = EmbedDesign.error(
                title="Tag Not Found",
                description=f"Tag `{tag_name}` not found. Use `/tag list` to see available tags."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Show edit tag modal
        modal = EditTagModal(self.bot, ctx.interaction, tag)
        await ctx.interaction.response.send_modal(modal)

    @tag.command(name="delete", description="Delete a tag")
    @app_commands.describe(tag_name="Name of the tag to delete")
    @validate_input(max_length=50, pattern="alphanumeric")
    async def tag_delete(self, ctx: commands.Context, tag_name: str):
        """Delete a tag."""
        # Check permissions - only developers can delete tags
        if not await StaffUtils.has_developer_permission_cross_guild(self.bot, ctx.author, "manage_messages"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You need to be a developer to delete tags."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        tag = await self.get_tag(ctx.guild.id, tag_name)
        if not tag:
            embed = EmbedDesign.error(
                title="Tag Not Found",
                description=f"Tag `{tag_name}` not found. Use `/tag list` to see available tags."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Show delete confirmation
        embed = EmbedDesign.warning(
            title="Delete Tag",
            description=f"Are you sure you want to delete the tag `{tag_name}`?",
            fields=[
                {"name": "Tag Content", "value": tag['content'][:100] + "..." if len(tag['content']) > 100 else tag['content'], "inline": False}
            ]
        )
        
        # Create confirmation buttons
        confirm_button = discord.ui.Button(
            label="Delete",
            style=discord.ButtonStyle.danger,
            custom_id=f"delete_tag_confirm_{tag_name}"
        )
        cancel_button = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.secondary,
            custom_id="delete_tag_cancel"
        )
        
        view = discord.ui.View()
        view.add_item(confirm_button)
        view.add_item(cancel_button)
        
        await ctx.reply(embed=embed, view=view, ephemeral=True)

    @tag.command(name="search", description="Search for tags by name or content")
    @app_commands.describe(
        query="Search term to find tags",
        category="Filter by category (optional)"
    )
    async def tag_search(self, ctx: commands.Context, query: str, category: Optional[str] = None):
        """Search for tags by name or content."""
        # Check permissions - only staff can search tags
        if not await StaffUtils.has_staff_permission_cross_guild(self.bot, ctx.author, "manage_messages"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You need to be a staff member to search tags."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Build search filter
        search_filter = {
            "guild_id": ctx.guild.id,
            "active": True,
            "$or": [
                {"name": {"$regex": query, "$options": "i"}},
                {"content": {"$regex": query, "$options": "i"}}
            ]
        }
        
        if category:
            search_filter["category"] = {"$regex": category, "$options": "i"}
        
        # Search for tags
        # Search tags in PostgreSQL
        all_tags = await self.bot.db.find_all_tags(ctx.guild.id)
        
        # Filter tags based on search criteria
        tags = []
        for tag in all_tags:
            matches_query = query.lower() in tag['name'].lower() or query.lower() in tag['content'].lower()
            matches_category = not category or category.lower() == tag.get('category', 'general').lower()
            
            if matches_query and matches_category:
                tags.append(tag)
        
        # Sort by usage and limit to 10
        tags = sorted(tags, key=lambda x: x.get('uses', 0), reverse=True)[:10]
        
        if not tags:
            embed = EmbedDesign.info(
                title="Tag Search",
                description=f"No tags found matching '{query}'" + (f" in category '{category}'" if category else "")
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Create search results embed
        description_parts = []
        for tag in tags:
            content_preview = tag['content'][:100] + "..." if len(tag['content']) > 100 else tag['content']
            description_parts.append(f"**`{tag['name']}`** ({tag.get('category', 'General')})\n{content_preview}")
        
        embed = EmbedDesign.info(
            title="Tag Search Results",
            description="\n\n".join(description_parts),
            fields=[
                {"name": "Query", "value": query, "inline": True},
                {"name": "Results", "value": str(len(tags)), "inline": True},
                {"name": "Usage", "value": "Use `/tag view <tag_name>` to view a specific tag", "inline": False}
            ]
        )
        
        await ctx.reply(embed=embed)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Handle button interactions for tag management."""
        if not interaction.type == discord.InteractionType.component:
            return
        
        custom_id = interaction.data.get("custom_id", "")
        
        if custom_id.startswith("delete_tag_confirm_"):
            tag_name = custom_id.replace("delete_tag_confirm_", "")
            await self.handle_delete_tag_confirm(interaction, tag_name)
            
        elif custom_id == "delete_tag_cancel":
            await self.handle_delete_tag_cancel(interaction)

    async def handle_delete_tag_confirm(self, interaction: discord.Interaction, tag_name: str):
        """Handle tag deletion confirmation."""
        try:
            # Get the tag
            tag = await self.get_tag(interaction.guild.id, tag_name)
            if not tag:
                embed = EmbedDesign.error(
                    title="Tag Not Found",
                    description=f"Tag `{tag_name}` no longer exists."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Soft delete the tag
            # Note: Soft delete needs custom implementation in PostgreSQL
            # For now, we'll use a placeholder method
            await self.bot.db.update_tag_status(tag["id"], active=False)
            
            embed = EmbedDesign.success(
                title="Tag Deleted",
                description=f"Tag `{tag_name}` has been deleted successfully.",
                fields=[
                    {"name": "Deleted by", "value": interaction.user.mention, "inline": True}
                ]
            )
            
            await interaction.response.edit_message(embed=embed, view=None)
            
        except Exception as e:
            logger.error(f"Error deleting tag: {e}")
            embed = EmbedDesign.error(
                title="Error",
                description="An error occurred while deleting the tag."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def handle_delete_tag_cancel(self, interaction: discord.Interaction):
        """Handle tag deletion cancellation."""
        embed = EmbedDesign.info(
            title="Deletion Cancelled",
            description="Tag deletion has been cancelled."
        )
        await interaction.response.edit_message(embed=embed, view=None)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle tag access via $tagname format."""
        # Ignore bot messages and messages without content
        if message.author.bot or not message.content:
            return
        
        # Check if message starts with $ and contains a tag name
        if message.content.startswith('$'):
            # Extract tag name (everything after $, before any spaces)
            tag_name = message.content[1:].split()[0].lower()
            
            if tag_name:
                # Check permissions - only staff can use $tagname
                if not await StaffUtils.has_staff_permission_cross_guild(self.bot, message.author, "manage_messages"):
                    return  # Silently ignore non-staff users
                
                # Get the tag
                tag = await self.get_tag(message.guild.id, tag_name)
                if tag:
                    # Update usage statistics
                    await self.bot.db.update_tag_usage(tag["id"])
                    
                    # Send tag as a simple embed
                    embed = EmbedDesign.info(title=tag['name'], description=tag['content'])
                    await message.channel.send(embed=embed)
                    
                    # Delete the original message if bot has permission
                    try:
                        await message.delete()
                    except discord.Forbidden:
                        # Bot doesn't have permission to delete messages, that's okay
                        pass
                    except Exception as e:
                        logger.error(f"Error deleting tag message: {e}")

class CreateTagModal(discord.ui.Modal, title="Create Support Tag"):
    def __init__(self, bot: commands.Bot, original_interaction: discord.Interaction):
        super().__init__()
        self.bot = bot
        self.original_interaction = original_interaction
        
        self.tag_name = discord.ui.TextInput(
            label="Tag Name",
            placeholder="Enter the tag name (e.g., welcome, rules, faq)",
            required=True,
            min_length=1,
            max_length=50
        )
        
        self.tag_content = discord.ui.TextInput(
            label="Tag Content",
            placeholder="Enter the tag content. You can use markdown formatting.",
            required=True,
            style=discord.TextStyle.paragraph,
            min_length=1,
            max_length=4000
        )
        
        self.tag_category = discord.ui.TextInput(
            label="Category (Optional)",
            placeholder="Enter a category (e.g., General, Rules, FAQ)",
            required=False,
            max_length=50
        )
        
        self.add_item(self.tag_name)
        self.add_item(self.tag_content)
        self.add_item(self.tag_category)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission for tag creation."""
        await interaction.response.defer(ephemeral=True)
        try:
            tag_name = self.tag_name.value.lower().strip()
            tag_content = self.tag_content.value.strip()
            tag_category = self.tag_category.value.strip() if self.tag_category.value else "General"
            
            if not tag_name.replace("_", "").replace("-", "").isalnum():
                embed = EmbedDesign.error(title="Invalid Tag Name", description="Tag names can only contain letters, numbers, underscores, and hyphens.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            existing_tag = await self.bot.get_cog('TagCommands').get_tag(interaction.guild.id, tag_name)
            if existing_tag:
                embed = EmbedDesign.error(title="Tag Already Exists", description=f"A tag named `{tag_name}` already exists.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            tag_data = {
                "guild_id": interaction.guild.id,
                "name": tag_name,
                "content": tag_content,
                "category": tag_category,
                "created_by": interaction.user.id,
            }
            
            await self.bot.db.insert_tag(tag_data)
            
            embed = EmbedDesign.success(title="Tag Created", description=f"Tag `{tag_name}` has been created successfully!")
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error creating tag: {e}")
            embed = EmbedDesign.error(title="Error", description="An error occurred while creating the tag.")
            await interaction.followup.send(embed=embed, ephemeral=True)

class EditTagModal(discord.ui.Modal, title="Edit Support Tag"):
    def __init__(self, bot: commands.Bot, original_interaction: discord.Interaction, tag: dict):
        super().__init__()
        self.bot = bot
        self.original_interaction = original_interaction
        self.tag = tag
        
        self.tag_content = discord.ui.TextInput(
            label="Tag Content",
            placeholder="Enter the new tag content. You can use markdown formatting.",
            required=True,
            style=discord.TextStyle.paragraph,
            min_length=1,
            max_length=4000,
            default=tag.get('content', '')
        )
        
        self.tag_category = discord.ui.TextInput(
            label="Category (Optional)",
            placeholder="Enter a category (e.g., General, Rules, FAQ)",
            required=False,
            max_length=50,
            default=tag.get('category', 'General')
        )
        
        self.add_item(self.tag_content)
        self.add_item(self.tag_category)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission for tag editing."""
        await interaction.response.defer(ephemeral=True)
        try:
            tag_content = self.tag_content.value.strip()
            tag_category = self.tag_category.value.strip() if self.tag_category.value else "General"
            
            await self.bot.db.update_tag_content(self.tag["id"], tag_content, interaction.user.id)
            
            embed = EmbedDesign.success(title="Tag Updated", description=f"Tag `{self.tag['name']}` has been updated successfully!")
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error editing tag: {e}")
            embed = EmbedDesign.error(title="Error", description="An error occurred while editing the tag.")
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(TagCommands(bot))
