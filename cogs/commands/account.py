"""
Account management commands for verification settings.
"""
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from typing import Optional
import pyotp
import qrcode
import io
import uuid
from utils.constants import logger, EmbedDesign
from utils.staff import StaffUtils
from utils.twilio_verification import TwilioVerificationService

class AccountCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.verification_service = TwilioVerificationService(bot)
    
    async def phone_verification_complete_callback(self, interaction: discord.Interaction):
        """Handle phone verification completion."""
        logger.info(f"Phone verification completed for user {interaction.user.id}")
        
        try:
            phone_number = await self.bot.db.database.fetch_val(
                "SELECT phone_number FROM verification_sessions WHERE user_id = :user_id AND verification_type = 'sms' AND verified = TRUE ORDER BY created_at DESC LIMIT 1",
                values={"user_id": interaction.user.id}
            )
        except Exception as e:
            logger.error(f"Error getting phone number for verification completion: {e}")
            phone_number = "your phone number"
        
        display_phone = f"****{phone_number[-4:]}" if phone_number and isinstance(phone_number, str) and len(phone_number) > 4 else "your phone number"
        
        embed = EmbedDesign.success(
            title="Phone Verification Complete",
            description=f"Your phone number **{display_phone}** has been successfully verified and added to your account.",
            fields=[
                {"name": "Status", "value": "✅ Phone verification enabled", "inline": True},
                {"name": "Security", "value": "Your phone number is encrypted and secure", "inline": True}
            ]
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    def validate_phone_number(self, phone_number: str) -> tuple[bool, str]:
        """Validate phone number format and return (is_valid, formatted_number)."""
        # Remove all non-digit characters except +
        cleaned = ''.join(c for c in phone_number if c.isdigit() or c == '+')
        
        # Must start with +
        if not cleaned.startswith('+'):
            cleaned = '+' + cleaned
        
        # Basic validation: 10-15 digits total
        digits = ''.join(c for c in cleaned if c.isdigit())
        if len(digits) < 10 or len(digits) > 15:
            return False, ""
        
        # Check for emergency numbers
        if self.is_emergency_number(cleaned):
            return False, ""
        
        return True, cleaned
    
    def is_emergency_number(self, phone_number: str) -> bool:
        """Check if the phone number is an emergency service number."""
        # Remove + and get just the digits
        digits = ''.join(c for c in phone_number if c.isdigit())
        
        # Common emergency numbers by country
        emergency_numbers = {
            # Universal emergency numbers
            "112", "911", "999", "000", "08", "110", "118", "119",
            
            # US/Canada
            "911",
            
            # UK
            "999", "112",
            
            # Australia
            "000", "112",
            
            # Germany
            "110", "112",
            
            # France
            "15", "17", "18", "112",
            
            # Japan
            "110", "119", "118",
            
            # India
            "100", "101", "102", "108",
            
            # Brazil
            "190", "192", "193", "194", "197", "198", "199",
            
            # Russia
            "01", "02", "03", "04", "112",
            
            # China
            "110", "119", "120", "122",
            
            # South Korea
            "112", "119", "113", "114", "117", "118",
            
            # Italy
            "112", "113", "115", "118",
            
            # Spain
            "112", "091", "092", "061", "080", "085", "062",
            
            # Netherlands
            "112",
            
            # Sweden
            "112", "11414",
            
            # Norway
            "112", "113",
            
            # Denmark
            "112",
            
            # Finland
            "112",
            
            # Poland
            "112", "997", "998", "999",
            
            # Czech Republic
            "112", "150", "155", "158",
            
            # Hungary
            "112", "104", "105", "107",
            
            # Romania
            "112", "981", "982", "983",
            
            # Bulgaria
            "112", "150", "160", "166",
            
            # Greece
            "112", "100", "166", "199",
            
            # Turkey
            "112", "110", "155", "156", "158", "177", "199",
            
            # Israel
            "100", "101", "102", "112",
            
            # South Africa
            "10111", "10177", "112",
            
            # Egypt
            "122", "123", "126", "128", "180", "182", "190",
            
            # Nigeria
            "199", "112",
            
            # Kenya
            "999", "112",
            
            # Morocco
            "19", "15", "177", "112",
            
            # Saudi Arabia
            "911", "997", "998", "999", "112",
            
            # UAE
            "999", "112",
            
            # India regional
            "100", "101", "102", "108", "1091", "1092", "1093", "1094", "1095", "1096", "1097", "1098",
            
            # Mexico
            "911", "066", "068", "080", "089",
            
            # Argentina
            "911", "100", "101", "107", "911",
            
            # Chile
            "131", "132", "133", "134", "135", "136", "137", "138", "139",
            
            # Colombia
            "123", "125", "127", "128", "129", "911",
            
            # Peru
            "105", "106", "116", "911",
            
            # Venezuela
            "171", "911",
            
            # Canada regional
            "911", "311", "411", "511", "611", "711", "811", "911",
        }
        
        # Check if the number matches any emergency number
        for emergency in emergency_numbers:
            if digits.endswith(emergency) or digits == emergency:
                return True
        
        # Check for short emergency numbers (3 digits or less)
        if len(digits) <= 3:
            return True
        
        # Check for numbers that start with emergency prefixes
        emergency_prefixes = ["911", "999", "112", "000", "110", "118", "119"]
        for prefix in emergency_prefixes:
            if digits.startswith(prefix):
                return True
        
        return False
    
    def get_country_codes(self) -> dict:
        """Get common country codes for validation."""
        return {
            "US": "+1", "CA": "+1", "GB": "+44", "AU": "+61", "DE": "+49",
            "FR": "+33", "IT": "+39", "ES": "+34", "NL": "+31", "SE": "+46",
            "NO": "+47", "DK": "+45", "FI": "+358", "PL": "+48", "CZ": "+420",
            "HU": "+36", "RO": "+40", "BG": "+359", "HR": "+385", "SI": "+386",
            "SK": "+421", "LT": "+370", "LV": "+371", "EE": "+372", "IE": "+353",
            "PT": "+351", "GR": "+30", "CY": "+357", "MT": "+356", "LU": "+352",
            "BE": "+32", "AT": "+43", "CH": "+41", "LI": "+423", "IS": "+354",
            "JP": "+81", "KR": "+82", "CN": "+86", "IN": "+91", "SG": "+65",
            "MY": "+60", "TH": "+66", "ID": "+62", "PH": "+63", "VN": "+84",
            "BR": "+55", "MX": "+52", "AR": "+54", "CL": "+56", "CO": "+57",
            "PE": "+51", "VE": "+58", "UY": "+598", "PY": "+595", "BO": "+591",
            "EC": "+593", "GY": "+592", "SR": "+597", "GF": "+594", "ZA": "+27",
            "NG": "+234", "KE": "+254", "EG": "+20", "MA": "+212", "TN": "+216",
            "DZ": "+213", "LY": "+218", "SD": "+249", "ET": "+251", "UG": "+256",
            "TZ": "+255", "GH": "+233", "CI": "+225", "SN": "+221", "ML": "+223",
            "BF": "+226", "NE": "+227", "TD": "+235", "CF": "+236", "CM": "+237",
            "GQ": "+240", "GA": "+241", "CG": "+242", "CD": "+243", "AO": "+244",
            "ZM": "+260", "ZW": "+263", "BW": "+267", "NA": "+264", "SZ": "+268",
            "LS": "+266", "MG": "+261", "MU": "+230", "SC": "+248", "KM": "+269",
            "YT": "+262", "RE": "+262", "DJ": "+253", "SO": "+252", "ER": "+291",
            "SS": "+211", "RW": "+250", "BI": "+257", "MW": "+265", "MZ": "+258"
        }

    @commands.hybrid_group(name="my", description="User account commands")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def my_group(self, ctx: commands.Context):
        """User account commands."""
        pass
    
    @my_group.command(name="account", description="Manage your account verification settings")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def my_account(self, ctx: commands.Context):
        """Manage your account verification settings."""
        await ctx.defer(ephemeral=True)
        if not await StaffUtils.has_account_access_permission_cross_guild(self.bot, ctx.author, "verify"):
            embed = EmbedDesign.error(
                title="Permission Denied",
                description="You don't have permission to use account management. This requires Staff access."
            )
            await ctx.reply(embed=embed, ephemeral=True)
            return
        
        # Get current verification status
        phone_number = await self.bot.db.get_user_phone_number(ctx.author.id)
        
        # Check if user has 2FA secret stored
        user_2fa_secret = await self.bot.db.database.fetch_val(
            "SELECT verification_code FROM verification_sessions WHERE user_id = :user_id AND verification_type = '2fa' ORDER BY created_at DESC LIMIT 1",
            values={"user_id": ctx.author.id}
        )
        
        # Check if user has backup codes
        backup_codes = await self.bot.db.database.fetch_val(
            "SELECT backup_codes FROM user_2fa_backup WHERE user_id = :user_id ORDER BY created_at DESC LIMIT 1",
            values={"user_id": ctx.author.id}
        )
        
        fields = []
        if phone_number:
            # Always redact phone number, only show last 4 digits
            fields.append({"name": "Phone Verification", "value": f"✅ Verified (****{phone_number[-4:]})", "inline": True})
        else:
            fields.append({"name": "Phone Verification", "value": "❌ Not verified", "inline": True})
        
        if user_2fa_secret:
            fields.append({"name": "2FA Setup", "value": "✅ Configured", "inline": True})
            if backup_codes:
                fields.append({"name": "Backup Codes", "value": f"✅ Available ({len(backup_codes.split(','))} codes)", "inline": True})
            else:
                fields.append({"name": "Backup Codes", "value": "❌ Not generated", "inline": True})
        else:
            fields.append({"name": "2FA Setup", "value": "❌ Not configured", "inline": True})
        
        embed = EmbedDesign.info(
            title="🔐 Account Verification Settings",
            description="Manage your account security and verification methods",
            fields=fields
        )
        
        # Create view with select menu
        view = AccountManagementSelectView(self.bot, ctx.author)
        await ctx.reply(embed=embed, view=view, ephemeral=True)


class PhoneSetupModal(discord.ui.Modal):
    """Modal for phone number setup."""
    
    def __init__(self, bot, user):
        super().__init__(title="Phone Number Setup")
        self.bot = bot
        self.user = user
        
        self.phone_input = discord.ui.TextInput(
            label="Phone Number",
            placeholder="Enter your phone number with country code (e.g., +1234567890)",
            required=True,
            max_length=20
        )
        self.add_item(self.phone_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle phone number submission."""
        await interaction.response.defer(ephemeral=True)
        
        phone_number = self.phone_input.value.strip()
        logger.info(f"Phone setup modal submitted by user {self.user.id} with number: {phone_number}")
        
        verification_service = getattr(self.bot, 'verification_service', None)
        if not verification_service:
            logger.error(f"Verification service not available for phone setup by user {self.user.id}")
            embed = EmbedDesign.error(
                title="Verification Service Unavailable",
                description="The verification service is not available. Please try again later."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Use the verification service's validation
        is_valid = verification_service.is_valid_phone_number(phone_number)
        logger.info(f"Phone number validation for user {self.user.id}: valid={is_valid}")
        
        if not is_valid:
            embed = EmbedDesign.error(
                title="Invalid Phone Number",
                description="Please enter a valid phone number with country code (e.g., +1234567890).",
                fields=[
                    {"name": "Format", "value": "Use international format: `+1234567890`", "inline": True},
                    {"name": "Length", "value": "7-15 digits total", "inline": True}
                ]
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Format the phone number using the verification service
        formatted_number = verification_service.format_phone_number(phone_number)
        logger.info(f"Formatted phone number for user {self.user.id}: {phone_number} -> {formatted_number}")
        
        # Check for emergency numbers using the verification service
        if verification_service.is_emergency_number(formatted_number):
            embed = EmbedDesign.error(
                title="Emergency Number Detected",
                description="Emergency service numbers cannot be used for verification.",
                fields=[
                    {"name": "What happened?", "value": "You entered an emergency service number (like 911, 999, 112, etc.)", "inline": False},
                    {"name": "Why blocked?", "value": "Emergency numbers are reserved for emergency services and cannot be used for verification.", "inline": False},
                    {"name": "What to do?", "value": "Please use your personal phone number with country code (e.g., +1234567890)", "inline": False}
                ]
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        logger.info(f"Sending verification SMS to {formatted_number} for user {self.user.id}")
        session_id = await verification_service.send_verification(formatted_number, self.user.id)
        logger.info(f"Verification SMS result for user {self.user.id}: session_id={session_id}")
        
        if session_id:
            embed = EmbedDesign.info(
                title="Verification Code Sent",
                description=f"A verification code has been sent to your phone number ending in `{formatted_number[-4:]}`. Please click the button below to enter it."
            )
            account_cog = self.bot.get_cog('AccountCommands')
            view = PhoneVerificationView(
                bot=self.bot,
                user=self.user,
                phone_number=formatted_number,
                on_success=account_cog.phone_verification_complete_callback
            )
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            embed = EmbedDesign.error(
                title="Verification Failed",
                description="Failed to send verification code. Please check your phone number and try again."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


class PhoneVerificationCodeModal(discord.ui.Modal):
    """Modal to enter the phone verification code."""
    
    def __init__(self, bot, user, phone_number: str, on_success):
        super().__init__(title="Enter Verification Code")
        self.bot = bot
        self.user = user
        self.phone_number = phone_number
        self.on_success = on_success
        
        self.code_input = discord.ui.TextInput(
            label="Verification Code",
            placeholder="Enter the 4-digit code sent to your phone",
            required=True,
            max_length=4,
            min_length=4
        )
        self.add_item(self.code_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle verification code submission."""
        await interaction.response.defer(ephemeral=True)
        
        code = self.code_input.value.strip()
        verification_service = getattr(self.bot, 'verification_service', None)
        
        if not verification_service:
            logger.error(f"Verification service not available for phone verification by user {self.user.id}")
            embed = EmbedDesign.error(
                title="Verification Service Unavailable",
                description="The verification service is not available. Please try again later."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
            
        is_verified = await verification_service.verify_code(self.phone_number, code)
        
        if is_verified:
            await self.on_success(interaction)
        else:
            embed = EmbedDesign.error(
                title="Verification Failed",
                description="Invalid verification code. Please try again."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


class PhoneVerificationView(discord.ui.View):
    """View with a button to open the phone verification modal."""

    def __init__(self, bot, user, phone_number: str, on_success):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.user = user
        self.phone_number = phone_number
        self.on_success = on_success

    @discord.ui.button(label="Enter Verification Code", style=discord.ButtonStyle.primary)
    async def enter_code_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show the modal to enter the verification code."""
        modal = PhoneVerificationCodeModal(
            bot=self.bot,
            user=self.user,
            phone_number=self.phone_number,
            on_success=self.on_success
        )
        await interaction.response.send_modal(modal)


class TwoFASetupModal(discord.ui.Modal):
    """Modal for 2FA setup."""
    
    def __init__(self, bot, user, secret: str):
        super().__init__(title="2FA Setup - Verify Code")
        self.bot = bot
        self.user = user
        self.secret = secret
        
        self.code_input = discord.ui.TextInput(
            label="Verification Code",
            placeholder="Enter the 6-digit code from your authenticator app",
            required=True,
            max_length=6,
            min_length=6
        )
        self.add_item(self.code_input)
    
    def generate_backup_codes(self) -> str:
        """Generate 10 backup codes for 2FA recovery."""
        import secrets
        import string
        
        codes = []
        for _ in range(10):
            # Generate 8-character alphanumeric codes
            code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            codes.append(code)
        
        return ','.join(codes)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle 2FA code verification."""
        await interaction.response.defer(ephemeral=True)
        
        code = self.code_input.value.strip()
        
        # Verify the code
        verification_service = getattr(self.bot, 'verification_service', None)
        if not verification_service:
            embed = EmbedDesign.error(
                title="Verification Service Unavailable",
                description="The verification service is not available. Please try again later."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        if verification_service.verify_2fa_code(self.secret, code):
            # Store the 2FA secret
            await self.bot.db.create_verification_session(
                user_id=self.user.id,
                session_id=str(uuid.uuid4()),
                verification_type="2fa",
                verification_code=self.secret,
                expires_at=datetime.utcnow() + timedelta(days=365)  # Store for 1 year
            )
            
            # Generate backup codes
            backup_codes = self.generate_backup_codes()
            await self.bot.db.store_2fa_backup_codes(self.user.id, backup_codes)
            
            embed = EmbedDesign.success(
                title="2FA Setup Complete",
                description="Your 2FA has been successfully configured!",
                fields=[
                    {"name": "Status", "value": "✅ 2FA Enabled", "inline": True},
                    {"name": "Backup Codes", "value": f"`{backup_codes}`", "inline": False},
                    {"name": "Important", "value": "Save these backup codes in a safe place! You'll need them if you lose access to your authenticator app.", "inline": False}
                ]
            )
        else:
            embed = EmbedDesign.error(
                title="2FA Setup Failed",
                description="Invalid verification code. Please try again."
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)


class AccountManagementSelectView(discord.ui.View):
    """View for account management with select menu."""
    
    def __init__(self, bot, user):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.user = user
        self.add_item(AccountManagementSelect(bot, user))


class AccountManagementSelect(discord.ui.Select):
    """Select menu for account management options."""
    
    def __init__(self, bot, user):
        self.bot = bot
        self.user = user
        
        options = [
            discord.SelectOption(
                label="Setup Phone Verification",
                description="Add phone number for SMS verification",
                value="setup_phone"
            ),
            discord.SelectOption(
                label="Setup 2FA",
                description="Configure two-factor authentication",
                value="setup_2fa"
            ),
            discord.SelectOption(
                label="Remove Phone",
                description="Remove phone verification",
                value="remove_phone"
            ),
            discord.SelectOption(
                label="Remove 2FA",
                description="Remove two-factor authentication",
                value="remove_2fa"
            )
        ]
        
        super().__init__(
            placeholder="Choose an action...",
            min_values=1,
            max_values=1,
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle select menu selection."""
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This is not your account management panel.", ephemeral=True)
            return
        
        value = self.values[0]
        
        if value == "setup_phone":
            await self.setup_phone(interaction)
        elif value == "setup_2fa":
            await self.setup_2fa(interaction)
        elif value == "remove_phone":
            await self.remove_phone(interaction)
        elif value == "remove_2fa":
            await self.remove_2fa(interaction)
    
    async def setup_phone(self, interaction: discord.Interaction):
        """Setup phone verification."""
        modal = PhoneSetupModal(self.bot, self.user)
        await interaction.response.send_modal(modal)
    
    async def setup_2fa(self, interaction: discord.Interaction):
        """Setup 2FA verification."""
        verification_service = getattr(self.bot, 'verification_service', None)
        if not verification_service:
            embed = EmbedDesign.error(
                title="Verification Service Unavailable",
                description="The verification service is not available. Please try again later."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Generate 2FA secret
        secret = verification_service.generate_2fa_secret(self.user.id)
        
        # Generate QR code
        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(
            name=f"UEC Bot ({self.user.name})",
            issuer_name="UEC Bot"
        )
        
        # Create QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        
        # Create file
        file = discord.File(img_bytes, filename="2fa_qr.png")
        
        embed = EmbedDesign.info(
            title="🔐 2FA Setup",
            description="Scan the QR code with your authenticator app (Google Authenticator, Authy, etc.)",
            fields=[
                {"name": "Manual Entry", "value": f"`{secret}`", "inline": False},
                {"name": "Next Steps", "value": "After scanning, click 'Verify 2FA' to complete setup.", "inline": False}
            ]
        )
        
        # Add verify button
        view = TwoFASetupView(self.bot, self.user, secret)
        
        await interaction.response.send_message(embed=embed, file=file, view=view, ephemeral=True)
    
    async def remove_phone(self, interaction: discord.Interaction):
        """Remove phone verification."""
        # Remove phone number
        await self.bot.db.database.execute(
            "DELETE FROM user_phone_numbers WHERE user_id = :user_id",
            values={"user_id": self.user.id}
        )
        
        embed = EmbedDesign.success(
            title="Phone Number Removed",
            description="Your phone number has been removed from your account."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def remove_2fa(self, interaction: discord.Interaction):
        """Remove 2FA verification."""
        # Check if user has 2FA configured
        user_2fa_secret = await self.bot.db.database.fetch_val(
            "SELECT verification_code FROM verification_sessions WHERE user_id = :user_id AND verification_type = '2fa' ORDER BY created_at DESC LIMIT 1",
            values={"user_id": self.user.id}
        )
        
        if not user_2fa_secret:
            embed = EmbedDesign.error(
                title="No 2FA Configured",
                description="You don't have 2FA configured on your account."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check if user has backup codes
        backup_codes = await self.bot.db.get_2fa_backup_codes(self.user.id)
        
        # Require 2FA verification before removal
        verification_service = getattr(self.bot, 'verification_service', None)
        if not verification_service:
            embed = EmbedDesign.error(
                title="Verification Service Unavailable",
                description="The verification service is not available. Please try again later."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Create verification choice view
        embed = EmbedDesign.info(
            title="🔐 Remove 2FA - Verification Required",
            description="To remove 2FA, you must verify your identity using one of the methods below.\n\n**You have 2 minutes to complete verification.**"
        )
        
        view = TwoFARemovalChoiceView(self.bot, self.user, user_2fa_secret, backup_codes)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class TwoFARemovalChoiceView(discord.ui.View):
    """View for choosing 2FA removal verification method."""
    
    def __init__(self, bot, user, secret, backup_codes):
        super().__init__(timeout=120)  # 2 minutes timeout
        self.bot = bot
        self.user = user
        self.secret = secret
        self.backup_codes = backup_codes
    
    @discord.ui.button(label="Use 2FA Code", style=discord.ButtonStyle.primary, emoji="🔐")
    async def use_2fa_code(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Use 2FA code for verification."""
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This is not your verification panel.", ephemeral=True)
            return
        
        modal = TwoFARemovalModal(self.bot, self.user, self.secret, "2fa")
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Use Backup Code", style=discord.ButtonStyle.secondary, emoji="🔑")
    async def use_backup_code(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Use backup code for verification."""
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This is not your verification panel.", ephemeral=True)
            return
        
        if not self.backup_codes:
            embed = EmbedDesign.error(
                title="No Backup Codes",
                description="You don't have any backup codes configured. Please use your 2FA code instead."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        modal = TwoFARemovalModal(self.bot, self.user, self.secret, "backup")
        await interaction.response.send_modal(modal)
    
    async def on_timeout(self):
        """Handle view timeout."""
        try:
            embed = EmbedDesign.warning(
                title="Verification Timeout",
                description="The verification process has timed out. Please try again."
            )
            await self.message.edit(embed=embed, view=None)
        except:
            pass


class TwoFARemovalModal(discord.ui.Modal):
    """Modal for 2FA removal verification."""
    
    def __init__(self, bot, user, secret, verification_type):
        super().__init__(title="Remove 2FA - Verify Code")
        self.bot = bot
        self.user = user
        self.secret = secret
        self.verification_type = verification_type  # "2fa" or "backup"
        
        if verification_type == "2fa":
            self.code_input = discord.ui.TextInput(
                label="2FA Code",
                placeholder="Enter your current 6-digit 2FA code to confirm removal",
                required=True,
                max_length=6,
                min_length=6
            )
        else:  # backup
            self.code_input = discord.ui.TextInput(
                label="Backup Code",
                placeholder="Enter one of your backup codes to confirm removal",
                required=True,
                max_length=8,
                min_length=8
            )
        
        self.add_item(self.code_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle 2FA removal verification."""
        await interaction.response.defer(ephemeral=True)
        
        code = self.code_input.value.strip()
        is_verified = False
        
        if self.verification_type == "2fa":
            # Verify using 2FA code
            verification_service = getattr(self.bot, 'verification_service', None)
            if not verification_service:
                embed = EmbedDesign.error(
                    title="Verification Service Unavailable",
                    description="The verification service is not available. Please try again later."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            is_verified = verification_service.verify_2fa_code(self.secret, code)
            
        else:  # backup code verification
            # Get current backup codes
            backup_codes_str = await self.bot.db.get_2fa_backup_codes(self.user.id)
            if not backup_codes_str:
                embed = EmbedDesign.error(
                    title="No Backup Codes",
                    description="No backup codes found for your account."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Check if the provided code matches any backup code
            backup_codes = [bc.strip() for bc in backup_codes_str.split(',')]
            is_verified = code in backup_codes
            
            if is_verified:
                # Remove the used backup code
                remaining_codes = [bc for bc in backup_codes if bc != code]
                if remaining_codes:
                    await self.bot.db.store_2fa_backup_codes(self.user.id, ','.join(remaining_codes))
                else:
                    # No more backup codes, remove the record
                    await self.bot.db.remove_2fa_backup_codes(self.user.id)
        
        if is_verified:
            # Remove 2FA secret and any remaining backup codes
            await self.bot.db.database.execute(
                "DELETE FROM verification_sessions WHERE user_id = :user_id AND verification_type = '2fa'",
                values={"user_id": self.user.id}
            )
            await self.bot.db.remove_2fa_backup_codes(self.user.id)
            
            verification_method = "2FA code" if self.verification_type == "2fa" else "backup code"
            embed = EmbedDesign.success(
                title="2FA Removed",
                description=f"Your 2FA has been successfully removed using your {verification_method}.",
                fields=[
                    {"name": "Status", "value": "✅ 2FA Disabled", "inline": True},
                    {"name": "Security", "value": "Your account is now less secure", "inline": True},
                    {"name": "Verification Method", "value": verification_method.title(), "inline": True}
                ]
            )
        else:
            code_type = "2FA code" if self.verification_type == "2fa" else "backup code"
            embed = EmbedDesign.error(
                title=f"Invalid {code_type.title()}",
                description=f"The {code_type} you entered is incorrect. Please try again."
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)


class TwoFASetupView(discord.ui.View):
    """View for 2FA setup verification."""
    
    def __init__(self, bot, user, secret: str):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.user = user
        self.secret = secret
    
    @discord.ui.button(label="Verify 2FA", style=discord.ButtonStyle.success)
    async def verify_2fa(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Verify 2FA setup."""
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This is not your account management panel.", ephemeral=True)
            return
        
        modal = TwoFASetupModal(self.bot, self.user, self.secret)
        await interaction.response.send_modal(modal)


async def setup(bot: commands.Bot):
    await bot.add_cog(AccountCommands(bot))
