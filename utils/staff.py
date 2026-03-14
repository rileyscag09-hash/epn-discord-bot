import discord
from typing import List, Optional
from utils.constants import Constants, logger

# Initialize constants
constants = Constants()

class StaffUtils:
    @staticmethod
    def is_developer(user: discord.Member) -> bool:
        """Check if user is a developer (has developer role in main server or linked role)."""
        # Check if user has developer role in main server
        # Note: This method needs bot access to work properly
        # For now, just check the current guild
        if user.get_role(constants.developer_role_id()):
            return True
        
        # Check for linked role (this would need to be called from a cog with bot access)
        # This is handled in the individual command checks
        return False

    @staticmethod
    def is_staff(user: discord.Member) -> bool:
        """Check if user is staff (has staff role in main server or linked role)."""
        # Check if user has staff role in main server
        # Note: This method needs bot access to work properly
        # For now, just check the current guild
        if user.get_role(constants.staff_role_id()):
            return True
        
        # Developers are always considered staff
        if user.get_role(constants.developer_role_id()):
            return True
        
        # Affiliate server owners are considered staff
        if user.get_role(constants.affiliate_server_owner_id()):
            return True
        
        # Check for linked role (this would need to be called from a cog with bot access)
        # This is handled in the individual command checks
        return False

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
        """Check if user has developer permission."""
        return StaffUtils.is_developer(user)

    @staticmethod
    def has_staff_permission(user: discord.Member, permission: str) -> bool:
        """Check if user has staff permission."""
        # Developers and staff members have staff permissions
        return StaffUtils.has_staff_permission_cross_guild(user) or StaffUtils.has_developer_permission_cross_guild(user)

    @staticmethod
    async def check_linked_role(bot, user: discord.Member, role_type: str) -> bool:
        """Check if user has a linked role of the specified type."""
        try:
            linked_role = await bot.db.find_linked_role(user.id, user.guild.id)
            return linked_role is not None
        except Exception:
            return False

    @staticmethod
    async def has_developer_permission_with_linked(bot, user: discord.Member, permission: str) -> bool:
        """Check if user has developer permission (including linked roles)."""
        # Check Discord role first
        if StaffUtils.is_developer(user):
            return True
        
        # Check linked role
        return await StaffUtils.check_linked_role(bot, user, "developer")

    @staticmethod
    async def has_staff_permission_with_linked(bot, user: discord.Member, permission: str) -> bool:
        """Check if user has staff permission (including linked roles)."""
        # Check Discord role first
        if StaffUtils.is_staff(user):
            return True
        
        # Check linked role
        if await StaffUtils.check_linked_role(bot, user, "staff"):
            return True

    @staticmethod
    async def has_developer_permission_cross_guild(bot, user: discord.Member, permission: str = None) -> bool:
        """Check if user has developer permission in main server (cross-guild)."""
        try:
            main_server_id = constants.main_server_id()
            guild = await bot.fetch_guild(main_server_id)
            if not guild:
                # Log permission denial for security monitoring
                try:
                    from utils.security_logger import get_security_logger
                    security_logger = get_security_logger(bot)
                    await security_logger.log_permission_denied(
                        user_id=user.id,
                        guild_id=getattr(user.guild, 'id', None),
                        required_permission=permission or "developer"
                    )
                except Exception:
                    pass
                return False
            
            member = await guild.fetch_member(user.id)
            if not member:
                # Log permission denial for security monitoring
                try:
                    from utils.security_logger import get_security_logger
                    security_logger = get_security_logger(bot)
                    await security_logger.log_permission_denied(
                        user_id=user.id,
                        guild_id=getattr(user.guild, 'id', None),
                        required_permission=permission or "developer"
                    )
                except Exception:
                    pass
                return False
            
            # Check if user has developer role in main server
            if member.get_role(constants.developer_role_id()):
                return True
            
            # Check linked role
            has_permission = False
            if permission is not None:
                has_permission = await StaffUtils.check_linked_role(bot, user, permission)
            else:
                has_permission = await StaffUtils.check_linked_role(bot, user, "developer")
            
            # Log permission denial if access is denied
            if not has_permission:
                try:
                    from utils.security_logger import get_security_logger, SecurityEventType, SecurityEventSeverity
                    security_logger = get_security_logger(bot)
                    await security_logger.log_permission_denied(
                        user_id=user.id,
                        guild_id=getattr(user.guild, 'id', None),
                        required_permission=permission or "developer"
                    )
                    # Also log as unauthorized API access for developer-only operations
                    await security_logger.log_event(
                        SecurityEventType.UNAUTHORIZED_API_ACCESS,
                        SecurityEventSeverity.HIGH,
                        user_id=user.id,
                        guild_id=getattr(user.guild, 'id', None),
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
            # Log permission denial for security monitoring
            try:
                from utils.security_logger import get_security_logger
                security_logger = get_security_logger(bot)
                await security_logger.log_permission_denied(
                    user_id=user.id,
                    guild_id=getattr(user.guild, 'id', None),
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
            guild = await bot.fetch_guild(main_server_id)
            if not guild:
                return False
            
            member = await guild.fetch_member(user.id)
            if not member:
                return False
            
            # Check if user has staff role, developer role, affiliate server owner role, or affiliate HR role in main server
            if (member.get_role(constants.staff_role_id()) or 
                member.get_role(constants.developer_role_id()) or 
                member.get_role(constants.affiliate_server_owner_id()) or
                member.get_role(constants.affiliate_hr_id())):
                return True
            
            # Check linked role
            return await StaffUtils.check_linked_role(bot, user, "staff")
            
        except Exception as e:
            logger.error(f"Error checking cross-guild account access permission for user {user.id}: {e}")
            return False

    @staticmethod
    async def has_staff_permission_cross_guild(bot, user: discord.Member, permission: str) -> bool:
        """Check if user has staff permission in main server (cross-guild)."""
        try:
            main_server_id = constants.main_server_id()
            guild = await bot.fetch_guild(main_server_id)
            if not guild:
                return False
            
            member = await guild.fetch_member(user.id)
            if not member:
                return False
            
            # Check if user has staff role, developer role, or affiliate server owner role in main server
            if (member.get_role(constants.staff_role_id()) or 
                member.get_role(constants.developer_role_id()) or 
                member.get_role(constants.affiliate_server_owner_id())):
                return True
            
            # Check linked role
            return await StaffUtils.check_linked_role(bot, user, "staff")
            
        except Exception as e:
            logger.error(f"Error checking cross-guild staff permission for user {user.id}: {e}")
            return False

    @staticmethod
    async def has_core_staff_permission_cross_guild(bot, user: discord.Member, permission: str) -> bool:
        """Check if user has core staff permission in main server (cross-guild) - excludes affiliate roles."""
        try:
            main_server_id = constants.main_server_id()
            guild = await bot.fetch_guild(main_server_id)
            if not guild:
                return False
            
            member = await guild.fetch_member(user.id)
            if not member:
                return False
            
            # Check if user has staff role or developer role in main server (excludes affiliate roles)
            if (member.get_role(constants.staff_role_id()) or 
                member.get_role(constants.developer_role_id())):
                return True
            
            # Check linked role for core staff only
            return await StaffUtils.check_linked_role(bot, user, "staff")
            
        except Exception as e:
            logger.error(f"Error checking cross-guild core staff permission for user {user.id}: {e}")
            return False

    @staticmethod
    async def get_user_staff_roles(bot, user_id: int) -> List[str]:
        """Get user's staff roles from the main server using constants."""
        from utils.constants import logger
        
        main_server_id = constants.main_server_id()
        logger.info(f"Checking staff roles for user {user_id} in main server {main_server_id}")
        
        try:
            guild = await bot.fetch_guild(main_server_id)
            if not guild:
                logger.error(f"Could not fetch guild {main_server_id}")
                return []
            
            try:
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
                        staff_roles.append("Staff")
                        logger.info(f"Found affiliate server owner role for user {user_id}")
            
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
        from utils.constants import logger
        
        try:
            # This method needs bot access to work properly
            # For now, return False as a fallback
            # The actual implementation should be in a cog with bot access
            logger.warning(f"is_blacklisted called for user {user_id} but requires bot access")
            return False
        except Exception as e:
            logger.error(f"Error checking blacklist status for user {user_id}: {e}")
            return False 
