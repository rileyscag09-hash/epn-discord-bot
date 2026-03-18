async def send_ban_notification(
    self,
    action: str,
    user: Union[discord.User, discord.Member],
    reason: str,
    staff_member: Union[discord.User, discord.Member],
    guild_name: Optional[str] = None,
    evidence: Optional[str] = None,
    expires_at: Optional[datetime] = None,
    appealable: bool = True
):
    """Send central main-server EPN notification."""
    try:
        notification_channel = self.bot.get_channel(constants.EPN_user_notification_channel_id())
        if not notification_channel:
            logger.error("Notification channel not found")
            return

        color = (
            EmbedDesign.ERROR if action.lower() == "ban"
            else EmbedDesign.SUCCESS if action.lower() == "unban"
            else EmbedDesign.WARNING
        )

        description_parts = [
            f"{user.mention} ({user.id}) was {action.lower()} in {guild_name or 'EPN'} by {staff_member.mention}"
        ]
        description_parts.append(f"**Reason:** {reason}")

        if evidence:
            description_parts.append(f"**Evidence:** {evidence}")

        if expires_at:
            description_parts.append(f"**Expires:** <t:{int(expires_at.timestamp())}:F>")

        if not appealable:
            description_parts.append("**Appeals:** Not allowed")

        if action.lower() == "ban":
            title = "🚫 EPN User Ban"
        elif action.lower() == "unban":
            title = "✅ EPN User Unban"
        elif action.lower() == "update":
            title = "📝 EPN Ban Update"
        else:
            title = f"EPN {action.title()}"

        embed = EmbedDesign.create_embed(
            title=title,
            description="\n".join(description_parts),
            color=color
        )

        await notification_channel.send(embed=embed)

    except Exception as e:
        logger.error(f"Error sending ban notification: {e}")
