"""
Twilio verification service for command authentication using Verify API.
"""
import asyncio
import uuid
import pyotp
import discord
import functools
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Union, List
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.base.exceptions import TwilioException
from utils.constants import Constants, EmbedDesign, logger
from discord.ext import commands
import logging

# Initialize constants
constants = Constants()

class TwilioVerificationService:
    """Service for handling Twilio-based verification for sensitive commands using Verify API."""
    
    def __init__(self, bot):
        self.bot = bot
        self.client = None
        self.verify_service_sid = None
        self._setup_client()
    
    def _setup_client(self):
        """Setup Twilio client if credentials are available."""
        account_sid = constants.twilio_account_sid()
        auth_token = constants.twilio_auth_token()
        self.verify_service_sid = constants.twilio_verify_service_sid()
        
        # Check for debug mode
        if constants.twilio_debug_mode():
            logger.warning("Twilio debug mode is enabled. No real SMS will be sent.")
            self.client = True  # Mock client
            return
            
        if account_sid and auth_token:
            try:
                self.client = Client(account_sid, auth_token)
                logger.info("Twilio client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Twilio client: {e}")
                self.client = None
        else:
            logger.warning("Twilio credentials not configured - verification will use 2FA fallback")
    
    async def send_verification(self, phone_number: str, user_id: int) -> Optional[str]:
        """Send verification using Twilio Verify API."""
        logger.info(f"Attempting to send verification SMS to {phone_number} for user {user_id}")
        
        if not self.client or not self.verify_service_sid:
            logger.error(f"Twilio Verify service not configured - client: {bool(self.client)}, service_sid: {bool(self.verify_service_sid)}")
            return None
        
        # Validate phone number format before sending
        logger.info(f"Starting phone number validation for: '{phone_number}'")
        is_valid = self.is_valid_phone_number(phone_number)
        logger.info(f"Phone number validation result: {is_valid}")
        
        if not is_valid:
            logger.warning(f"Invalid phone number format: {phone_number}")
            return None
        
        # Format the phone number for Twilio
        logger.info(f"Starting phone number formatting for: '{phone_number}'")
        formatted_number = self.format_phone_number(phone_number)
        logger.info(f"Formatted phone number: {phone_number} -> {formatted_number}")
        
        # Check for emergency numbers before sending
        if self.is_emergency_number(formatted_number):
            logger.warning(f"Attempted to send verification to emergency number: {formatted_number}")
            return None
        
        try:
            # If in debug mode, bypass Twilio
            if constants.twilio_debug_mode():
                logger.info(f"DEBUG MODE: Bypassing Twilio verification for {formatted_number}")
                session_id = str(uuid.uuid4())
                await self.bot.db.create_verification_session(
                    user_id=user_id,
                    session_id=session_id,
                    verification_type="sms",
                    phone_number=formatted_number,
                    verification_code="DEBUG_CODE",
                    expires_at=datetime.utcnow() + timedelta(minutes=10)
                )
                logger.info(f"DEBUG MODE: Created dummy session {session_id} for user {user_id}")
                return session_id
                
            logger.info(f"Creating Twilio verification for {formatted_number} using service {self.verify_service_sid}")
            verification = self.client.verify.v2.services(self.verify_service_sid).verifications.create(
                to=formatted_number,
                channel='sms'
            )
            logger.info(f"Twilio verification created for {formatted_number}. SID: {verification.sid}")
            
            # Store the verification SID in the session
            session_id = str(uuid.uuid4())
            await self.bot.db.create_verification_session(
                user_id=user_id,
                session_id=session_id,
                verification_type="sms",
                phone_number=formatted_number,
                verification_code=verification.sid,
                expires_at=datetime.utcnow() + timedelta(minutes=10)
            )
            logger.info(f"Twilio verification session created for user {user_id}: {session_id}")
            return session_id
            
        except TwilioException as e:
            logger.error(f"Twilio Verify API error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error sending verification: {e}")
            return None
    
    async def verify_code(self, phone_number: str, provided_code: str) -> bool:
        """Verify the provided code using Twilio Verify API."""
        logger.info(f"Verifying code for phone {phone_number}")
        
        if not self.client or not self.verify_service_sid:
            logger.error(f"Twilio Verify service not configured - client: {bool(self.client)}, service_sid: {bool(self.verify_service_sid)}")
            return False
        
        try:
            # If in debug mode, use static code
            if constants.twilio_debug_mode():
                if provided_code == "1234":
                    logger.info(f"DEBUG MODE: Verification approved for {phone_number} with static code.")
                    
                    sessions = await self.bot.db.database.fetch_all(
                        "SELECT * FROM verification_sessions WHERE phone_number = :phone_number AND verification_type = 'sms' AND expires_at > CURRENT_TIMESTAMP ORDER BY created_at DESC LIMIT 1",
                        values={"phone_number": phone_number}
                    )
                    
                    if sessions:
                        session = dict(sessions[0])
                        await self.bot.db.verify_session(session['session_id'])
                        
                        await self.bot.db.store_user_phone_number(
                            session['user_id'], 
                            phone_number
                        )
                    
                    return True
                else:
                    logger.info(f"DEBUG MODE: Invalid code for {phone_number}.")
                    return False

            logger.info(f"Checking verification code with Twilio for {phone_number}")
            verification_check = self.client.verify.v2.services(self.verify_service_sid).verification_checks.create(
                to=phone_number,
                code=provided_code
            )
            logger.info(f"Twilio verification check result: {verification_check.status}")
            
            if verification_check.status == 'approved':
                logger.info(f"Verification approved for {phone_number}")
                sessions = await self.bot.db.database.fetch_all(
                    "SELECT * FROM verification_sessions WHERE phone_number = :phone_number AND verification_type = 'sms' AND expires_at > CURRENT_TIMESTAMP ORDER BY created_at DESC LIMIT 1",
                    values={"phone_number": phone_number}
                )
                
                if sessions:
                    session = dict(sessions[0])
                    await self.bot.db.verify_session(session['session_id'])
                    
                    await self.bot.db.store_user_phone_number(
                        session['user_id'], 
                        phone_number
                    )
                
                return True
            
            return False
            
        except TwilioException as e:
            logger.error(f"Twilio Verify API error: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error verifying code: {e}")
            return False
    
    def is_emergency_number(self, phone_number: str) -> bool:
        """Check if the phone number is an emergency service number."""
        # Remove + and get just the digits
        digits = ''.join(c for c in phone_number if c.isdigit())
        
        logger.debug(f"Checking emergency number: {phone_number} -> digits: {digits} (length: {len(digits)})")
        
        # If the number is longer than 6 digits, it's definitely not an emergency number
        # Emergency numbers are typically 3-6 digits long
        if len(digits) > 6:
            logger.debug(f"Number {phone_number} is too long ({len(digits)} digits), not emergency")
            return False
        
        # Common emergency numbers by country (exact matches only)
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
        
        # Check for exact emergency number matches
        if digits in emergency_numbers:
            logger.debug(f"Number {phone_number} matches emergency number: {digits}")
            return True
        
        # Check for numbers that start with emergency prefixes
        emergency_prefixes = ["911", "999", "112", "000", "110", "118", "119"]
        for prefix in emergency_prefixes:
            if digits.startswith(prefix):
                logger.debug(f"Number {phone_number} starts with emergency prefix: {prefix}")
                return True
        
        logger.debug(f"Number {phone_number} is not an emergency number")
        return False
    
    def is_valid_phone_number(self, phone_number: str) -> bool:
        """Validate phone number format for Twilio compatibility."""
        if not phone_number or not isinstance(phone_number, str):
            logger.debug(f"Invalid input: {phone_number}")
            return False
        
        # Remove all non-digit characters except +
        cleaned = ''.join(c for c in phone_number if c.isdigit() or c == '+')
        logger.debug(f"Cleaned phone number: '{phone_number}' -> '{cleaned}'")
        
        # Must start with +
        if not cleaned.startswith('+'):
            logger.debug(f"Phone number doesn't start with +: {cleaned}")
            return False
        
        # Get just the digits after the +
        digits = cleaned[1:]  # Remove the + and get digits
        logger.debug(f"Digits after +: '{digits}' (length: {len(digits)})")
        
        # Must be between 7 and 15 digits (E.164 standard)
        if len(digits) < 7 or len(digits) > 15:
            logger.debug(f"Phone number length invalid: {len(digits)} digits (must be 7-15)")
            return False
        
        # Universal E.164 validation - accept any valid international format
        # E.164 standard: 7-15 digits total, must start with country code
        # This is much more permissive and user-friendly
        
        # Basic E.164 compliance check
        if len(digits) >= 7 and len(digits) <= 15:
            logger.debug(f"Valid E.164 number: {phone_number} -> +{digits}")
            return True
        
        logger.debug(f"Phone number validation failed for: {phone_number} -> +{digits} (not E.164 compliant)")
        return False
    
    def format_phone_number(self, phone_number: str) -> str:
        """Format phone number for Twilio (E.164 format)."""
        logger.debug(f"Formatting phone number: '{phone_number}'")
        
        if not phone_number or not isinstance(phone_number, str):
            logger.debug(f"Invalid input for formatting: {phone_number}")
            return phone_number
        
        # Remove all non-digit characters except +
        cleaned = ''.join(c for c in phone_number if c.isdigit() or c == '+')
        logger.debug(f"Cleaned for formatting: '{phone_number}' -> '{cleaned}'")
        
        # If it doesn't start with +, add it
        if not cleaned.startswith('+'):
            cleaned = '+' + cleaned
            logger.debug(f"Added + prefix: '{cleaned}'")
        
        logger.debug(f"Final formatted number: '{phone_number}' -> '{cleaned}'")
        return cleaned
    
    def generate_2fa_secret(self, user_id: int) -> str:
        """Generate a 2FA secret for a user."""
        return pyotp.random_base32()
    
    def generate_2fa_code(self, secret: str) -> str:
        """Generate a 2FA code from secret."""
        totp = pyotp.TOTP(secret)
        return totp.now()
    
    def verify_2fa_code(self, secret: str, provided_code: str) -> bool:
        """Verify a 2FA code."""
        totp = pyotp.TOTP(secret)
        return totp.verify(provided_code, valid_window=1)  # Allow 1 window of tolerance
    
    async def create_2fa_session(self, user_id: int, secret: str) -> str:
        """Create a 2FA verification session."""
        session_id = str(uuid.uuid4())
        
        try:
            await self.bot.db.create_verification_session(
                user_id=user_id,
                session_id=session_id,
                verification_type="2fa",
                verification_code=secret,
                expires_at=datetime.utcnow() + timedelta(minutes=10)
            )
            return session_id
        except Exception as e:
            logger.error(f"Failed to create 2FA session: {e}")
            return None
    
    async def verify_2fa_session(self, session_id: str, provided_code: str) -> bool:
        """Verify a 2FA session."""
        try:
            session = await self.bot.db.find_verification_session(session_id)
            if not session:
                return False
            
            if self.verify_2fa_code(session['verification_code'], provided_code):
                await self.bot.db.verify_session(session_id)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error verifying 2FA session: {e}")
            return False
    
    async def cleanup_expired_sessions(self):
        """Clean up expired verification sessions."""
        try:
            count = await self.bot.db.cleanup_expired_sessions()
            if count > 0:
                logger.info(f"Cleaned up {count} expired verification sessions")
        except Exception as e:
            logger.error(f"Error cleaning up expired sessions: {e}")


class VerificationModal(discord.ui.Modal):
    """Modal for entering an SMS verification code."""
    def __init__(self, verification_service, phone_number: str, command_func: callable):
        super().__init__(title="Enter SMS Verification Code")
        self.verification_service = verification_service
        self.phone_number = phone_number
        self.command_func = command_func
        
        self.code_input = discord.ui.TextInput(
            label="Verification Code",
            placeholder="Enter the 4-digit code sent to your phone",
            required=True,
            max_length=4,
            min_length=4,
        )
        self.add_item(self.code_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle SMS code submission."""
        code = self.code_input.value.strip()
        
        try:
            # Defer the interaction first to prevent timeout
            await interaction.response.defer(ephemeral=True)
            
            logger.info(f"Verifying SMS code: {code} for phone: {self.phone_number}")
            is_verified = await self.verification_service.verify_code(self.phone_number, code)
            logger.info(f"SMS verification result: {is_verified}")

            if is_verified:
                logger.info("SMS verification successful, executing command callback")
                # The interaction has been deferred, so we can use followup
                await self.command_func(interaction)  # Pass the fresh interaction
            else:
                logger.info("SMS verification failed - invalid code")
                embed = EmbedDesign.error(
                    title="Verification Failed",
                    description="Invalid verification code. Please try again."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error in SMS verification: {e}")
            embed = EmbedDesign.error(
                title="Verification Error",
                description="An error occurred during verification. Please try again."
            )
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except:
                # If all else fails, try to send a new message
                try:
                    await interaction.user.send(embed=embed)
                except:
                    pass  # Can't send DM, just log the error


class TOTPVerificationModal(discord.ui.Modal):
    """Modal for entering a 2FA/TOTP code."""
    def __init__(self, verification_service, secret: str, command_func: callable):
        super().__init__(title="2FA Setup - Verify Code")
        self.verification_service = verification_service
        self.secret = secret
        self.command_func = command_func

        self.code_input = discord.ui.TextInput(
            label="Verification Code",
            placeholder="Enter the 6-digit code from your authenticator app",
            required=True,
            max_length=6,
            min_length=6,
        )
        self.add_item(self.code_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle 2FA code submission."""
        code = self.code_input.value.strip()
        
        try:
            # Defer the interaction first to prevent timeout
            await interaction.response.defer(ephemeral=True)
            
            logger.info(f"Verifying 2FA code: {code} with secret: {self.secret[:10]}...")
            is_verified = self.verification_service.verify_2fa_code(self.secret, code)
            logger.info(f"2FA verification result: {is_verified}")
            
            if is_verified:
                logger.info("2FA verification successful, executing command callback")
                # The interaction has been deferred, so we can use followup
                await self.command_func(interaction) # Pass the fresh interaction
            else:
                logger.info("2FA verification failed - invalid code")
                embed = EmbedDesign.error(
                    title="Verification Failed",
                    description="Invalid 2FA code. Please check the code and try again."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error in TOTP verification: {e}")
            embed = EmbedDesign.error(
                title="Verification Error",
                description="An error occurred during verification. Please try again."
            )
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except:
                # If all else fails, try to send a new message
                try:
                    await interaction.user.send(embed=embed)
                except:
                    pass  # Can't send DM, just log the error


class VerificationChoiceView(discord.ui.View):
    """A view that lets the user choose their verification method."""
    def __init__(self, bot, callback: callable, phone_number: str, user_2fa_secret: str):
        super().__init__(timeout=60)  # 1 minute timeout
        self.bot = bot
        self.callback = callback
        self.phone_number = phone_number
        self.user_2fa_secret = user_2fa_secret
        self.verification_service = bot.verification_service

        # Phone Verification Button
        phone_button = discord.ui.Button(
            label="Verify with Phone", 
            style=discord.ButtonStyle.secondary, 
            emoji="📱", 
            disabled=not self.phone_number
        )
        phone_button.callback = self.verify_with_phone
        self.add_item(phone_button)

        # 2FA Verification Button
        totp_button = discord.ui.Button(
            label="Verify with 2FA", 
            style=discord.ButtonStyle.secondary, 
            emoji="🔐", 
            disabled=not self.user_2fa_secret
        )
        totp_button.callback = self.verify_with_totp
        self.add_item(totp_button)

    async def verify_with_phone(self, interaction: discord.Interaction):
        # Update the original message to show SMS sending status
        embed = EmbedDesign.info(
            title="Sending SMS Code",
            description="Sending verification code to your phone number. Please wait...",
            fields=[{"name": "Status", "value": "🔄 Sending...", "inline": True}]
        )
        await interaction.response.edit_message(embed=embed, view=None)
        
        # Send the SMS verification
        session_id = await self.verification_service.send_verification(self.phone_number, interaction.user.id)
        if not session_id:
            embed = EmbedDesign.error(
                title="SMS Error", 
                description="Failed to send verification code to your phone. Please try again or use 2FA instead.",
                fields=[{"name": "Status", "value": "❌ Failed", "inline": True}]
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Update message with success and button to open modal
        embed = EmbedDesign.success(
            title="SMS Code Sent",
            description="Verification code has been sent to your phone. Click the button below to enter the code.",
            fields=[{"name": "Status", "value": "✅ Sent", "inline": True}]
        )
        
        class OpenModalButton(discord.ui.View):
            def __init__(self, verification_service, phone_number, callback):
                super().__init__(timeout=60)
                self.verification_service = verification_service
                self.phone_number = phone_number
                self.callback = callback
            
            @discord.ui.button(label="Enter Verification Code", style=discord.ButtonStyle.primary)
            async def open_modal_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = VerificationModal(self.verification_service, self.phone_number, self.callback)
                await interaction.response.send_modal(modal)
        
        view = OpenModalButton(self.verification_service, self.phone_number, self.callback)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def verify_with_totp(self, interaction: discord.Interaction):
        # Update the original message to show 2FA verification
        embed = EmbedDesign.info(
            title="2FA Verification Required",
            description="Please enter your 2FA code from your authenticator app.",
            fields=[{"name": "Status", "value": "🔐 Ready", "inline": True}]
        )
        
        # Create button to open modal
        class OpenTOTPModalButton(discord.ui.View):
            def __init__(self, verification_service, secret, callback):
                super().__init__(timeout=60)
                self.verification_service = verification_service
                self.secret = secret
                self.callback = callback
            
            @discord.ui.button(label="Enter 2FA Code", style=discord.ButtonStyle.primary)
            async def open_modal_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = TOTPVerificationModal(self.verification_service, self.secret, self.callback)
                await interaction.response.send_modal(modal)
        
        view = OpenTOTPModalButton(self.verification_service, self.user_2fa_secret, self.callback)
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_timeout(self):
        """Handle timeout when user doesn't respond within 1 minute."""
        # Disable all buttons
        for item in self.children:
            item.disabled = True
        
        # Note: We can't update the message here since we don't have a message reference
        # The view will simply become non-interactive after timeout


class CommandVerifier:
    """Handles verification for commands."""
    
    def __init__(self, bot):
        self.bot = bot
        self.verification_service = bot.verification_service

    async def verify_and_execute(self, ctx: commands.Context, callback: callable):
        """Sends a verification choice view and executes a callback on success."""
        interaction = ctx.interaction
        if not interaction:
            await ctx.send("This command must be used as a slash command for verification.", ephemeral=True)
            return

        phone_number = await self.bot.db.get_user_phone_number(interaction.user.id)
        user_2fa_secret = await self.bot.db.database.fetch_val(
            "SELECT verification_code FROM verification_sessions WHERE user_id = :user_id AND verification_type = '2fa' ORDER BY created_at DESC LIMIT 1",
            values={"user_id": interaction.user.id}
        )

        if not phone_number and not user_2fa_secret:
            embed = EmbedDesign.warning(
                title="Verification Not Configured",
                description="You must set up phone or 2FA verification to use this command."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Defer the interaction first to allow modals to work properly
        await interaction.response.defer(ephemeral=True)

        # Send an initial verification message with choices
        embed = EmbedDesign.info(
            title="Verification Required",
            description="This action requires verification. Please choose your preferred method below.\n\n**You have 1 minute to complete verification.**"
        )
        view = VerificationChoiceView(self.bot, callback, phone_number, user_2fa_secret)
        
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
