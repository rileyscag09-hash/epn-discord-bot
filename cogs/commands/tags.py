import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from typing import Optional, List
import logging

from utils.constants import Constants, EmbedDesign
from utils.staff import StaffUtils
from utils.validation import InputSanitizer

logger = logging.getLogger(__name__)
constants = Constants()


class TagCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_tag(self, guild_id: int, tag_name: str) -> Optional[dict]:
        return await self.bot.db.find_tag(guild_id, tag_name)

    async def get_all_tags(self, guild_id: int) -> List[dict]:
        return await self.bot.db.find_all_tags(guild_id)

    async def create_tags_list_embed(self, guild: discord.Guild) -> discord.Embed:

        tags = await self.get_all_tags(guild.id)

        if not tags:
            return EmbedDesign.info(
                title="Support Tags",
                description="No tags exist yet. Use `/tag create`."
            )

        categories = {}
        for tag in tags:
            category = tag.get("category", "General")
            categories.setdefault(category, []).append(tag)

        description = []
        for cat, cat_tags in categories.items():
            names = ", ".join(f"`{t['name']}`" for t in cat_tags)
            description.append(f"**{cat}:** {names}")

        return EmbedDesign.info(
            title="Support Tags",
            description="\n".join(description),
            fields=[
                {"name": "Total Tags", "value": str(len(tags)), "inline": True},
                {"name": "Categories", "value": str(len(categories)), "inline": True},
            ],
        )

    @commands.hybrid_group(name="tag", description="Manage support tags")
    async def tag(self, ctx: commands.Context):

        if ctx.invoked_subcommand is None:
            embed = EmbedDesign.info(
                title="Tag Commands",
                description=(
                    "• `/tag create`\n"
                    "• `/tag list`\n"
                    "• `/tag view <name>`\n"
                    "• `/tag edit <name>`\n"
                    "• `/tag delete <name>`\n"
                    "• `/tag search <query>`"
                ),
            )
            await ctx.reply(embed=embed, ephemeral=True)

    # CREATE TAG

    @tag.command(name="create")
    async def tag_create(self, ctx: commands.Context):

        if not await StaffUtils.has_staff_permission_cross_guild(
            self.bot, ctx.author, "manage_messages"
        ):
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Permission Denied",
                    description="You must be staff to create tags.",
                ),
                ephemeral=True,
            )
            return

        if not ctx.interaction:
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Slash Command Required",
                    description="Use the slash command version.",
                ),
                ephemeral=True,
            )
            return

        await ctx.interaction.response.send_modal(CreateTagModal(self.bot))

    # LIST TAGS

    @tag.command(name="list")
    async def tag_list(self, ctx: commands.Context):

        if not await StaffUtils.has_staff_permission_cross_guild(
            self.bot, ctx.author, "manage_messages"
        ):
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Permission Denied",
                    description="You must be staff to view tags.",
                ),
                ephemeral=True,
            )
            return

        embed = await self.create_tags_list_embed(ctx.guild)
        await ctx.reply(embed=embed)

    # VIEW TAG

    @tag.command(name="view")
    async def tag_view(self, ctx: commands.Context, tag_name: str):

        tag_name = InputSanitizer.sanitize(tag_name)

        tag = await self.get_tag(ctx.guild.id, tag_name)

        if not tag:
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Tag Not Found",
                    description=f"`{tag_name}` does not exist.",
                ),
                ephemeral=True,
            )
            return

        await self.bot.db.update_tag_usage(tag["id"])

        embed = EmbedDesign.info(title=tag["name"], description=tag["content"])
        await ctx.reply(embed=embed)

    # EDIT TAG

    @tag.command(name="edit")
    async def tag_edit(self, ctx: commands.Context, tag_name: str):

        tag_name = InputSanitizer.sanitize(tag_name)

        tag = await self.get_tag(ctx.guild.id, tag_name)

        if not tag:
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Tag Not Found",
                    description=f"`{tag_name}` does not exist.",
                ),
                ephemeral=True,
            )
            return

        if not ctx.interaction:
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Slash Command Required",
                    description="Use the slash command version.",
                ),
                ephemeral=True,
            )
            return

        await ctx.interaction.response.send_modal(EditTagModal(self.bot, tag))

    # DELETE TAG

    @tag.command(name="delete")
    async def tag_delete(self, ctx: commands.Context, tag_name: str):

        if not await StaffUtils.has_developer_permission_cross_guild(
            self.bot, ctx.author, "manage_messages"
        ):
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Permission Denied",
                    description="Only developers can delete tags.",
                ),
                ephemeral=True,
            )
            return

        tag = await self.get_tag(ctx.guild.id, tag_name)

        if not tag:
            await ctx.reply(
                embed=EmbedDesign.error(
                    title="Tag Not Found",
                    description=f"`{tag_name}` does not exist.",
                ),
                ephemeral=True,
            )
            return

        await self.bot.db.update_tag_status(tag["id"], active=False)

        await ctx.reply(
            embed=EmbedDesign.success(
                title="Tag Deleted",
                description=f"`{tag_name}` was deleted.",
            )
        )

    # SEARCH TAG

    @tag.command(name="search")
    async def tag_search(self, ctx: commands.Context, query: str):

        all_tags = await self.get_all_tags(ctx.guild.id)

        matches = [
            t
            for t in all_tags
            if query.lower() in t["name"].lower()
            or query.lower() in t["content"].lower()
        ]

        if not matches:
            await ctx.reply(
                embed=EmbedDesign.info(
                    title="No Results",
                    description=f"No tags found for `{query}`.",
                ),
                ephemeral=True,
            )
            return

        matches = sorted(matches, key=lambda x: x.get("uses", 0), reverse=True)[:10]

        description = []
        for tag in matches:
            preview = tag["content"][:100] + "..."
            description.append(f"**`{tag['name']}`**\n{preview}")

        embed = EmbedDesign.info(
            title="Tag Search",
            description="\n\n".join(description),
        )

        await ctx.reply(embed=embed)

    # $TAG LISTENER

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        if message.author.bot or not message.content:
            return

        if not message.content.startswith("$"):
            return

        parts = message.content[1:].split()

        if not parts:
            return

        tag_name = parts[0].lower()

        tag = await self.get_tag(message.guild.id, tag_name)

        if not tag:
            return

        await self.bot.db.update_tag_usage(tag["id"])

        embed = EmbedDesign.info(title=tag["name"], description=tag["content"])

        await message.channel.send(embed=embed)

        try:
            await message.delete()
        except discord.Forbidden:
            pass


# CREATE MODAL


class CreateTagModal(discord.ui.Modal, title="Create Tag"):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

        self.tag_name = discord.ui.TextInput(label="Tag Name", max_length=50)
        self.tag_content = discord.ui.TextInput(
            label="Content",
            style=discord.TextStyle.paragraph,
            max_length=4000,
        )
        self.tag_category = discord.ui.TextInput(label="Category", required=False)

        self.add_item(self.tag_name)
        self.add_item(self.tag_content)
        self.add_item(self.tag_category)

    async def on_submit(self, interaction: discord.Interaction):

        name = self.tag_name.value.lower().strip()
        content = self.tag_content.value.strip()
        category = self.tag_category.value or "General"

        existing = await interaction.client.db.find_tag(interaction.guild.id, name)

        if existing:
            await interaction.response.send_message(
                embed=EmbedDesign.error(
                    title="Tag Exists",
                    description=f"`{name}` already exists.",
                ),
                ephemeral=True,
            )
            return

        await interaction.client.db.insert_tag(
            {
                "guild_id": interaction.guild.id,
                "name": name,
                "content": content,
                "category": category,
                "created_by": interaction.user.id,
            }
        )

        await interaction.response.send_message(
            embed=EmbedDesign.success(
                title="Tag Created",
                description=f"`{name}` created.",
            ),
            ephemeral=True,
        )


# EDIT MODAL


class EditTagModal(discord.ui.Modal, title="Edit Tag"):
    def __init__(self, bot, tag):
        super().__init__()
        self.bot = bot
        self.tag = tag

        self.tag_content = discord.ui.TextInput(
            label="Content",
            default=tag["content"],
            style=discord.TextStyle.paragraph,
        )

        self.add_item(self.tag_content)

    async def on_submit(self, interaction: discord.Interaction):

        content = self.tag_content.value.strip()

        await interaction.client.db.update_tag_content(
            self.tag["id"], content, interaction.user.id
        )

        await interaction.response.send_message(
            embed=EmbedDesign.success(
                title="Tag Updated",
                description=f"`{self.tag['name']}` updated.",
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(TagCommands(bot))
