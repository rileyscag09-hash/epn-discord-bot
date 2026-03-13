import discord

class Paginator(discord.ui.View):
    """Button-based paginator restricted to the original user."""

    def __init__(self, user: discord.abc.User, embeds: list[discord.Embed], timeout: float | None = 120):
        super().__init__(timeout=timeout)
        self.user = user
        self.embeds = embeds
        self.index = 0

        # Disable buttons if only one page
        if len(self.embeds) == 1:
            for item in self.children:
                item.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only the invoking user can interact."""
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This paginator isn't for you.", ephemeral=True)
            return False
        return True

    async def _update(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = (self.index - 1) % len(self.embeds)
        await self._update(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = (self.index + 1) % len(self.embeds)
        await self._update(interaction)

    @discord.ui.button(label="⏹", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Delete the paginator message when pressed."""
        try:
            await interaction.message.delete()
            try:
                await interaction.response.defer()  # acknowledge interaction
            except Exception:
                pass
        except Exception:
            # If deletion fails, just disable buttons gracefully
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(view=self)
        finally:
            self.stop() 