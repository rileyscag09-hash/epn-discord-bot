import discord
from typing import List
from utils.constants import Constants, logger

constants = Constants()


class StaffUtils:
    @staticmethod
    def is_developer(user: discord.Member) -> bool:
        """Check if user is a developer in the current guild."""
        if not user:
            return False

        return user.get_role(constants.developer_role_id()) is not None

    @staticmethod
    def is_staff(user: discord.Member) -> bool:
        """Check if user is staff in the current guild."""
        if not user:
            return False

        allowed_staff_roles = {
            constants.staff_role_id(),
            constants.developer_role_id(),
            constants.affiliate_server_owner_id(),
            constants.affiliate_hr_id(),
        }

        return any(user.get_role(role_id) is not None for role_id in allowed_staff_roles)

    @staticmethod
    def get_staff_members(guild: discord.Guild) -> List[discord.Member]:
        """Get all staff members in a guild."""
        return [member for member in guild.members if StaffUtils.is_staff(member)]

    @staticmethod
    def get_developer_members(guild: discord.Guild) -> List[discord.Member]:
        """Get all developer members in a guild."""
        return [member for member in guild.members if StaffUtils.is_developer(member)]

    @staticmethod
    def has_developer_permission(user: discord.Member, permission: str) -> bool:
        """Check if user has developer permission in the current guild."""
        return StaffUtils.is_developer(user)

    @staticmethod
    def has_staff_permission(user: discord.Member, permission: str) -> bool:
        """Check if user has staff permission in the current guild."""
        return StaffUtils.is_staff(user)

    @staticmethod
    async def check_linked_role(bot, user: discord.Member, role_type: str) -> bool:
        """Check if user has a linked role of the specified type."""
        try:
            linked_role = await bot.db.find_linked_role(user.id, user.guild.id)
            return linked_role is not None
        except Exception as e:
            logger.error(f"Error checking linked role for user {getattr(user, 'id', 'unknown')}: {e}")
            return False

    @staticmethod
    async def has_developer_permission_with_linked(bot, user: discord.Member, permission: str) -> bool:
        """Check if user has developer permission (including linked roles)."""
        if StaffUtils.is_developer(user):
            return True

        return await StaffUtils.check_linked_role(bot, user, "developer")

    @staticmethod
    async def has_staff_permission_with_linked(bot, user: discord.Member, permission: str) -> bool:
        """Check if user has staff permission (including linked roles)."""
        if StaffUtils.is_staff(user):
            return True

        if await StaffUtils.check_linked_role(bot, user, "staff"):
            return True

        return False

    @staticmethod
    async def has_developer_permission_cross_guild(bot, user: discord.Member, permission: str = None) -> bool:
        """Check if user has developer permission in the main server (cross-guild)."""
        try:
            main_server_id = constants.main_server_id()
            guild = bot.get_guild(main_server_id)

            if guild is None:
                guild = await bot.fetch_guild(main_server_id)

            if not guild:
                try:
                    from utils.security_logger import get_security_logger
                    security_logger = get_security_logger(bot)
                    await security_logger.log_permission_denied(
                        user_id=user.id,
                        guild_id=getattr(user.guild, "id", None),
                        required_permission=permission or "developer"
                    )
                except Exception:
                    pass
                return False

            try:
                member = guild.get_member(user.id)
                if member is None:
                    member = await guild.fetch_member(user.id)
            except discord.NotFound:
                member = None

            if not member:
                try:
                    from utils.security_logger import get_security_logger
                    security_logger = get_security_logger(bot)
                    await security_logger.log_permission_denied(
                        user_id=user.id,
                        guild_id=getattr(user.guild, "id", None),
                        required_permission=permission or "developer"
                    )
                except Exception:
                    pass
                return False

            if member.get_role(constants.developer_role_id()):
                return True

            has_permission = await StaffUtils.check_linked_role(
                bot,
                user,
                permission if permission is not None else "developer"
            )

            if not has_permission:
                try:
                    from utils.security_logger import get_security_logger, SecurityEventType, SecurityEventSeverity
                    security_logger = get_security_logger(bot)

                    await security_logger.log_permission_denied(
                        user_id=user.id,
                        guild_id=getattr(user.guild, "id", None),
                        required_permission=permission or "developer"
                    )

                    await security_logger.log_event(
                        SecurityEventType.UNAUTHORIZED_API_ACCESS,
                        SecurityEventSeverity.HIGH,
                        user_id=user.id,
                        guild_id=getattr(user.guild, "id", None),
                        details={
                            "access_type": "developer_permission_check",
                            "required_permission": permission or "developer",
                            "user_roles": [role.name for role in member.roles] if member else [],
                            "access_attempt": "Cross-guild developer command"
                        },
                        action_taken="Access denied - developer permissions required"
                    )
                except Exception:
                    pass

            return has_permission

        except Exception as e:
            logger.error(f"Error checking cross-guild developer permission for user {user.id}: {e}")
            try:
                from utils.security_logger import get_security_logger
                security_logger = get_security_logger(bot)
                await security_logger.log_permission_denied(
                    user_id=user.id,
                    guild_id=getattr(user.guild, "id", None),
                    required_permission=permission or "developer"
                )
            except Exception:
                pass
            return False

    @staticmethod
    async def has_account_access_permission_cross_guild(bot, user: discord.Member, permission: str) -> bool:
        """Check if user has account access permission in main server (cross-guild)."""
        try:
            main_server_id = constants.main_server_id()
            guild = bot.get_guild(main_server_id)

            if guild is None:
                guild = await bot.fetch_guild(main_server_id)

            if not guild:
                return False

            try:
                member = guild.get_member(user.id)
                if member is None:
                    member = await guild.fetch_member(user.id)
            except discord.NotFound:
                member = None

            if not member:
                return False

            if (
                member.get_role(constants.staff_role_id()) or
                member.get_role(constants.developer_role_id()) or
                member.get_role(constants.affiliate_server_owner_id()) or
                member.get_role(constants.affiliate_hr_id())
            ):
                return True

            return await StaffUtils.check_linked_role(bot, user, "staff")

        except Exception as e:
            logger.error(f"Error checking cross-guild account access permission for user {user.id}: {e}")
            return False

    @staticmethod
    async def has_staff_permission_cross_guild(bot, user: discord.Member, permission: str = None) -> bool:
        """Check if user has staff permission in main server (cross-guild)."""
        try:
            main_server_id = constants.main_server_id()
            guild = bot.get_guild(main_server_id)

            if guild is None:
                guild = await bot.fetch_guild(main_server_id)

            if not guild:
                return False

            try:
                member = guild.get_member(user.id)
                if member is None:
                    member = await guild.fetch_member(user.id)
            except discord.NotFound:
                member = None

            if not member:
                return False

            allowed_roles = {
                constants.staff_role_id(),
                constants.developer_role_id(),
                constants.affiliate_server_owner_id(),
                constants.affiliate_hr_id(),
            }

            if any(member.get_role(role_id) for role_id in allowed_roles):
                return True

            return await StaffUtils.check_linked_role(bot, user, "staff")

        except Exception as e:
            logger.error(f"Error checking cross-guild staff permission for user {user.id}: {e}")
            return False

    @staticmethod
    async def has_core_staff_permission_cross_guild(bot, user: discord.Member, permission: str = None) -> bool:
        """Check if user has core staff permission in main server (cross-guild) - excludes affiliate roles."""
        try:
            main_server_id = constants.main_server_id()
            guild = bot.get_guild(main_server_id)

            if guild is None:
                guild = await bot.fetch_guild(main_server_id)

            if not guild:
                return False

            try:
                member = guild.get_member(user.id)
                if member is None:
                    member = await guild.fetch_member(user.id)
            except discord.NotFound:
                member = None

            if not member:
                return False

            if (
                member.get_role(constants.staff_role_id()) or
                member.get_role(constants.developer_role_id())
            ):
                return True

            return await StaffUtils.check_linked_role(bot, user, "staff")

        except Exception as e:
            logger.error(f"Error checking cross-guild core staff permission for user {user.id}: {e}")
            return False

    @staticmethod
    async def get_user_staff_roles(bot, user_id: int) -> List[str]:
        """Get user's staff roles from the main server using constants."""
        main_server_id = constants.main_server_id()
        logger.info(f"Checking staff roles for user {user_id} in main server {main_server_id}")

        try:
            guild = bot.get_guild(main_server_id)

            if guild is None:
                guild = await bot.fetch_guild(main_server_id)

            if not guild:
                logger.error(f"Could not fetch guild {main_server_id}")
                return []

            try:
                member = guild.get_member(user_id)
                if member is None:
                    member = await guild.fetch_member(user_id)
            except discord.NotFound:
                logger.warning(f"User {user_id} not found in main server {main_server_id}")
                return []
            except discord.Forbidden:
                logger.error(f"Bot doesn't have permission to fetch member {user_id} in main server")
                return []
            except Exception as e:
                logger.error(f"Error fetching member {user_id}: {e}")
                return []

            staff_roles = []
            if member:
                for role in member.roles:
                    if role.id == constants.developer_role_id():
                        staff_roles.append("Developer")
                        logger.info(f"Found developer role for user {user_id}")
                    elif role.id == constants.staff_role_id():
                        staff_roles.append("Staff")
                        logger.info(f"Found staff role for user {user_id}")
                    elif role.id == constants.affiliate_server_owner_id():
                        staff_roles.append("Affiliate Server Owner")
                        logger.info(f"Found affiliate server owner role for user {user_id}")
                    elif role.id == constants.affiliate_hr_id():
                        staff_roles.append("Affiliate HR")
                        logger.info(f"Found affiliate HR role for user {user_id}")

            logger.info(f"User {user_id} has staff roles: {staff_roles}")
            return staff_roles

        except discord.NotFound:
            logger.error(f"Main server {main_server_id} not found")
            return []
        except discord.Forbidden:
            logger.error(f"Bot doesn't have permission to access main server {main_server_id}")
            return []
        except Exception as e:
            logger.error(f"Error in get_user_staff_roles for user {user_id}: {e}")
            return []

    @staticmethod
    async def is_blacklisted(user_id: int) -> bool:
        """Check if user is blacklisted from EPN."""
        try:
            logger.warning(f"is_blacklisted called for user {user_id} but requires bot access")
            return False
        except Exception as e:
            logger.error(f"Error checking blacklist status for user {user_id}: {e}")
            return False
