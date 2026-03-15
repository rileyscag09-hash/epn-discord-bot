"""
PostgreSQL database models and connection management for EPN Bot.
"""
import asyncpg
import databases
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from utils.constants import logger
from utils.validation import sanitize_database_input, InputSanitizer, ValidationError
import asyncio
import time

class DatabaseManager:
    """Manages PostgreSQL database connections and operations."""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.database = databases.Database(database_url)
        self._pool = None
        
        # In-memory caching for frequently accessed data
        self._cache = {
            "blacklist": {},  # user_id -> (blacklist_data, timestamp)
            "configs": {}  # guild_id -> (config_data, timestamp)
        }
        self._cache_ttl = 300  # 5 minutes cache TTL
        self._cache_lock = asyncio.Lock()
    
    @staticmethod
    def normalize_datetime(dt) -> datetime:
        """Convert datetime to timezone-naive UTC for PostgreSQL storage."""
        if dt is None:
            return None
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            # Convert to UTC and remove timezone info
            return dt.replace(tzinfo=None)
        return dt
    
    async def _is_cache_valid(self, cache_key: str, cache_type: str) -> bool:
        """Check if cache entry is still valid."""
        if cache_key not in self._cache[cache_type]:
            return False
        _, timestamp = self._cache[cache_type][cache_key]
        return (time.time() - timestamp) < self._cache_ttl
    
    async def _get_from_cache(self, cache_key: str, cache_type: str):
        """Get data from cache if valid."""
        async with self._cache_lock:
            if await self._is_cache_valid(cache_key, cache_type):
                data, _ = self._cache[cache_type][cache_key]
                return data
            return None
    
    async def _set_cache(self, cache_key: str, cache_type: str, data):
        """Set data in cache with current timestamp."""
        async with self._cache_lock:
            self._cache[cache_type][cache_key] = (data, time.time())
    
    async def _invalidate_cache(self, cache_key: str, cache_type: str):
        """Remove entry from cache."""
        async with self._cache_lock:
            self._cache[cache_type].pop(cache_key, None)
    
    async def connect(self):
        """Connect to the database and create tables if they don't exist."""
        try:
            await self.database.connect()
            logger.info("Connected to PostgreSQL")
            await self.create_tables()
            logger.info("Database tables initialized")
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from the database."""
        await self.database.disconnect()
    
    async def create_tables(self):
        """Create all necessary tables."""

        
        await self.database.execute("""
            CREATE TABLE IF NOT EXISTS ignores (
                id SERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id BIGINT,
                channel_id BIGINT,
                reason TEXT,
                ignored_by BIGINT NOT NULL,
                timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                active BOOLEAN DEFAULT TRUE
            )
        """)
        
        await self.database.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                reason TEXT,
                evidence TEXT,
                blacklisted_by BIGINT NOT NULL,
                timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP WITHOUT TIME ZONE,
                active BOOLEAN DEFAULT TRUE,
                appeal_allowed BOOLEAN DEFAULT TRUE,
                updated_by BIGINT,
                updated_at TIMESTAMP WITHOUT TIME ZONE,
                appeal_reason TEXT
            )
        """)
        
        await self.database.execute("""
            CREATE TABLE IF NOT EXISTS log_configs (
                id SERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                log_channel_id BIGINT,
                created_by BIGINT NOT NULL,
                timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                active BOOLEAN DEFAULT TRUE
            )
        """)
        
        await self.database.execute("""
            CREATE TABLE IF NOT EXISTS alert_configs (
                id SERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                alert_channel_id BIGINT,
                created_by BIGINT NOT NULL,
                timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                active BOOLEAN DEFAULT TRUE
            )
        """)
        
        await self.database.execute("""
            CREATE TABLE IF NOT EXISTS ping_configs (
                id SERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                ping_role_id BIGINT,
                created_by BIGINT NOT NULL,
                timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                active BOOLEAN DEFAULT TRUE
            )
        """)
        

        
        
        await self.database.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                guild_id BIGINT NOT NULL,
                created_by BIGINT NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP WITHOUT TIME ZONE,
                uses INTEGER DEFAULT 0,
                active BOOLEAN DEFAULT TRUE
            )
        """)
        
        
        await self.database.execute("""
            CREATE TABLE IF NOT EXISTS server_bans (
                id SERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                guild_name TEXT,
                reason TEXT,
                evidence TEXT,
                banned_by BIGINT NOT NULL,
                timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP WITHOUT TIME ZONE,
                active BOOLEAN DEFAULT TRUE,
                appeal_allowed BOOLEAN DEFAULT TRUE,
                updated_by BIGINT,
                updated_at TIMESTAMP WITHOUT TIME ZONE,
                appeal_reason TEXT
            )
        """)
        
        # New blocking tables for bot usage prevention
        await self.database.execute("""
            CREATE TABLE IF NOT EXISTS user_blocks (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                reason TEXT NOT NULL,
                evidence TEXT,
                blocked_by BIGINT NOT NULL,
                timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP WITHOUT TIME ZONE,
                active BOOLEAN DEFAULT TRUE,
                appeal_allowed BOOLEAN DEFAULT TRUE,
                updated_by BIGINT,
                updated_at TIMESTAMP WITHOUT TIME ZONE,
                unblock_reason TEXT
            )
        """)
        
        await self.database.execute("""
            CREATE TABLE IF NOT EXISTS guild_blocks (
                id SERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                guild_name TEXT,
                reason TEXT NOT NULL,
                evidence TEXT,
                blocked_by BIGINT NOT NULL,
                timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP WITHOUT TIME ZONE,
                active BOOLEAN DEFAULT TRUE,
                appeal_allowed BOOLEAN DEFAULT TRUE,
                updated_by BIGINT,
                updated_at TIMESTAMP WITHOUT TIME ZONE,
                unblock_reason TEXT
            )
        """)
        
        await self.database.execute("""
            CREATE TABLE IF NOT EXISTS verification_sessions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                session_id TEXT UNIQUE NOT NULL,
                verification_type TEXT NOT NULL,
                phone_number TEXT,
                verification_code TEXT,
                expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                verified BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                verified_at TIMESTAMP WITHOUT TIME ZONE
            )
        """)
        
        await self.database.execute("""
            CREATE TABLE IF NOT EXISTS user_phone_numbers (
                id SERIAL PRIMARY KEY,
                user_id BIGINT UNIQUE NOT NULL,
                phone_number TEXT NOT NULL,
                verified BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                verified_at TIMESTAMP WITHOUT TIME ZONE
            )
        """)
        
        await self.database.execute("""
            CREATE TABLE IF NOT EXISTS user_2fa_backup (
                id SERIAL PRIMARY KEY,
                user_id BIGINT UNIQUE NOT NULL,
                backup_codes TEXT NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await self.database.execute("""
            CREATE TABLE IF NOT EXISTS authorized_servers (
                id SERIAL PRIMARY KEY,
                guild_id BIGINT UNIQUE NOT NULL,
                guild_name TEXT,
                authorized_by BIGINT NOT NULL,
                authorized_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                reason TEXT,
                active BOOLEAN DEFAULT TRUE
            )
        """)
        
        await self.database.execute("""
            CREATE TABLE IF NOT EXISTS rate_limiter_state (
                api_name TEXT PRIMARY KEY,
                request_times JSONB NOT NULL DEFAULT '[]',
                last_updated TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes for better performance
        await self.create_indexes()
        
        # Run schema migrations
        await self.run_migrations()
    
    async def create_indexes(self):
        """Create database indexes for better performance."""
        indexes = [

            "CREATE INDEX IF NOT EXISTS idx_ignores_guild_id ON ignores(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_ignores_user_id ON ignores(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_blacklist_user_id ON blacklist(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_blacklist_active ON blacklist(active)",
            "CREATE INDEX IF NOT EXISTS idx_log_configs_guild_id ON log_configs(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_alert_configs_guild_id ON alert_configs(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_ping_configs_guild_id ON ping_configs(guild_id)",

            "CREATE INDEX IF NOT EXISTS idx_tags_guild_id ON tags(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name)",
            "CREATE INDEX IF NOT EXISTS idx_verification_sessions_user_id ON verification_sessions(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_verification_sessions_session_id ON verification_sessions(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_verification_sessions_expires_at ON verification_sessions(expires_at)",
            "CREATE INDEX IF NOT EXISTS idx_user_phone_numbers_user_id ON user_phone_numbers(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_phone_numbers_phone_number ON user_phone_numbers(phone_number)",
            "CREATE INDEX IF NOT EXISTS idx_user_2fa_backup_user_id ON user_2fa_backup(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_authorized_servers_guild_id ON authorized_servers(guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_authorized_servers_active ON authorized_servers(active)"
        ]
        
        # Create partial unique indexes (these replace the WHERE clauses in table constraints)
        partial_unique_indexes = [

            "CREATE UNIQUE INDEX IF NOT EXISTS idx_log_configs_guild_active ON log_configs(guild_id) WHERE active = TRUE",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_configs_guild_active ON alert_configs(guild_id) WHERE active = TRUE", 
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_ping_configs_guild_active ON ping_configs(guild_id) WHERE active = TRUE",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_name_guild_active ON tags(name, guild_id) WHERE active = TRUE",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_server_bans_guild_active ON server_bans(guild_id) WHERE active = TRUE"
        ]
        
        # Create regular indexes
        for index_query in indexes:
            await self.database.execute(index_query)
        
        # Create partial unique indexes
        for index_query in partial_unique_indexes:
            await self.database.execute(index_query)

    async def run_migrations(self):
        """Run database schema migrations."""
        try:
            # Migration: Add appeal_reason column to blacklist table
            await self.database.execute("""
                ALTER TABLE blacklist 
                ADD COLUMN IF NOT EXISTS appeal_reason TEXT
            """)
            logger.info("Added appeal_reason column to blacklist table")
            
            # Migration: Add updated_by and updated_at columns to blacklist table
            await self.database.execute("""
                ALTER TABLE blacklist 
                ADD COLUMN IF NOT EXISTS updated_by BIGINT
            """)
            await self.database.execute("""
                ALTER TABLE blacklist 
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE
            """)
            logger.info("Added updated_by and updated_at columns to blacklist table")
            
            # Migration: Add appeal_reason column to server_bans table
            await self.database.execute("""
                ALTER TABLE server_bans 
                ADD COLUMN IF NOT EXISTS appeal_reason TEXT
            """)
            logger.info("Added appeal_reason column to server_bans table")
            
        except Exception as e:
            logger.error(f"Error running migrations: {e}")


    
    # Ignores operations
    async def find_ignore(self, guild_id: int, user_id: int = None, channel_id: int = None) -> Optional[Dict[str, Any]]:
        """Find an ignore record."""
        if user_id:
            query = "SELECT * FROM ignores WHERE guild_id = :guild_id AND user_id = :user_id AND active = TRUE ORDER BY timestamp DESC LIMIT 1"
            row = await self.database.fetch_one(query=query, values={"guild_id": guild_id, "user_id": user_id})
            return dict(row) if row else None
        elif channel_id:
            query = "SELECT * FROM ignores WHERE guild_id = :guild_id AND channel_id = :channel_id AND active = TRUE ORDER BY timestamp DESC LIMIT 1"
            row = await self.database.fetch_one(query=query, values={"guild_id": guild_id, "channel_id": channel_id})
            return dict(row) if row else None
    
    async def insert_ignore(self, guild_id: int, reason: str, ignored_by: int, user_id: int = None, channel_id: int = None) -> int:
        """Insert a new ignore record."""
        # Validate and sanitize inputs
        try:
            guild_id = InputSanitizer.validate_discord_id(guild_id)
            ignored_by = InputSanitizer.validate_discord_id(ignored_by)
            if user_id is not None:
                user_id = InputSanitizer.validate_discord_id(user_id)
            if channel_id is not None:
                channel_id = InputSanitizer.validate_discord_id(channel_id)
        except ValidationError as e:
            logger.error(f"Invalid Discord ID in insert_ignore: {e}")
            raise
        
        # Sanitize text inputs
        reason = InputSanitizer.sanitize_reason(reason)
        
        query = """
            INSERT INTO ignores (guild_id, user_id, channel_id, reason, ignored_by) 
            VALUES (:guild_id, :user_id, :channel_id, :reason, :ignored_by) 
            RETURNING id
        """
        return await self.database.fetch_val(query=query, values={
            "guild_id": guild_id,
            "user_id": user_id,
            "channel_id": channel_id,
            "reason": reason,
            "ignored_by": ignored_by
        })
    
    async def find_all_ignores(self, guild_id: int) -> List[Dict[str, Any]]:
        """Find all active ignore records for a guild."""
        query = "SELECT * FROM ignores WHERE guild_id = :guild_id AND active = TRUE LIMIT 20"
        rows = await self.database.fetch_all(query=query, values={"guild_id": guild_id})
        return [dict(row) for row in rows]
    
    async def update_ignore_status(self, ignore_id: int, active: bool) -> bool:
        """Update ignore record active status."""
        query = "UPDATE ignores SET active = :active WHERE id = :id"
        result = await self.database.execute(query=query, values={"id": ignore_id, "active": active})
        return result is not None and result > 0
    
    # Blacklist operations
    async def find_blacklist(self, user_id: int, active: bool = True, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """Find a blacklist record for a user with caching."""
        logger.info(f"Database - find_blacklist called for user_id={user_id}, active={active}")
        
        # Check if database is connected
        try:
            if not self.database.is_connected:
                logger.error("Database - Database is not connected!")
                return None
        except Exception as e:
            logger.error(f"Database - Error checking connection: {e}")
            return None
        
        # Check cache first for active blacklists (only if cache is enabled)
        if active and use_cache:
            cached_data = await self._get_from_cache(str(user_id), "blacklist")
            if cached_data is not None:
                logger.info(f"Database - Found cached data for user {user_id}: {cached_data}")
                return cached_data
        
        query = "SELECT * FROM blacklist WHERE user_id = :user_id AND active = :active ORDER BY timestamp DESC LIMIT 1"
        logger.info(f"Database - Executing query: {query} with values user_id={user_id}, active={active}")
        
        try:
            row = await self.database.fetch_one(query=query, values={"user_id": user_id, "active": active})
            result = dict(row) if row else None
            logger.info(f"Database - Query result for user {user_id}: {result}")
            
            # Cache the result for active blacklists (only if cache is enabled)
            if active and result and use_cache:
                await self._set_cache(str(user_id), "blacklist", result)
            
            return result
            
        except Exception as e:
            logger.error(f"Database - Error executing query for user {user_id}: {e}")
            return None
    
    async def find_all_blacklist_by_user(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Find all blacklist records for a user ordered by timestamp."""
        # Log potential data breach attempt if requesting excessive records
        if limit > 50:
            try:
                from utils.security_logger import get_security_logger, SecurityEventType, SecurityEventSeverity
                security_logger = get_security_logger(None)
                await security_logger.log_event(
                    SecurityEventType.DATA_BREACH_ATTEMPT,
                    SecurityEventSeverity.HIGH,
                    details={
                        "operation": "find_all_blacklist_by_user",
                        "requested_limit": limit,
                        "target_user_id": user_id,
                        "breach_indicator": "excessive_record_request"
                    },
                    action_taken="Request allowed but logged for investigation"
                )
            except Exception:
                pass
        
        query = "SELECT * FROM blacklist WHERE user_id = :user_id ORDER BY timestamp DESC LIMIT :limit"
        rows = await self.database.fetch_all(query=query, values={"user_id": user_id, "limit": limit})
        return [dict(row) for row in rows]
    
    async def find_all_active_blacklist(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Find all active blacklist records."""
        # Log potential data breach attempt if requesting excessive records
        if limit > 100:
            try:
                from utils.security_logger import get_security_logger, SecurityEventType, SecurityEventSeverity
                security_logger = get_security_logger(None)
                await security_logger.log_event(
                    SecurityEventType.DATA_BREACH_ATTEMPT,
                    SecurityEventSeverity.HIGH,
                    details={
                        "operation": "find_all_active_blacklist",
                        "requested_limit": limit,
                        "breach_indicator": "mass_data_extraction_attempt"
                    },
                    action_taken="Request allowed but logged for investigation"
                )
            except Exception:
                pass
        
        query = "SELECT * FROM blacklist WHERE active = TRUE ORDER BY timestamp DESC LIMIT :limit"
        rows = await self.database.fetch_all(query=query, values={"limit": limit})
        return [dict(row) for row in rows]
    
    async def insert_blacklist(self, user_id: int, reason: str, evidence: str, blacklisted_by: int, expires_at: datetime = None, appeal_allowed: bool = True) -> int:
        """Insert a new blacklist record."""
        # Validate and sanitize inputs
        try:
            user_id = InputSanitizer.validate_discord_id(user_id)
            blacklisted_by = InputSanitizer.validate_discord_id(blacklisted_by)
        except ValidationError as e:
            logger.error(f"Invalid Discord ID in insert_blacklist: {e}")
            raise
        
        # Sanitize text inputs
        sanitized_data = sanitize_database_input({
            "reason": reason,
            "evidence": evidence
        })
        
        query = """
            INSERT INTO blacklist (user_id, reason, evidence, blacklisted_by, expires_at, appeal_allowed) 
            VALUES (:user_id, :reason, :evidence, :blacklisted_by, :expires_at, :appeal_allowed) 
            RETURNING id
        """
        result = await self.database.fetch_val(query=query, values={
            "user_id": user_id,
            "reason": sanitized_data["reason"],
            "evidence": sanitized_data["evidence"],
            "blacklisted_by": blacklisted_by,
            "expires_at": self.normalize_datetime(expires_at) if expires_at else None,
            "appeal_allowed": appeal_allowed
        })
        
        # Invalidate cache since user now has a blacklist entry
        await self._invalidate_cache(str(user_id), "blacklist")
        
        return result
    
    async def update_blacklist_status(self, user_id: int, active: bool) -> bool:
        """Update blacklist record active status."""
        query = "UPDATE blacklist SET active = :active WHERE user_id = :user_id AND active = :current_active"
        result = await self.database.execute(query=query, values={
            "user_id": user_id, 
            "active": active, 
            "current_active": not active
        })
        
        # Invalidate cache since blacklist status changed
        await self._invalidate_cache(str(user_id), "blacklist")
        
        return result is not None and result > 0

    async def get_blacklist_status(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Return the latest blacklist record (active or inactive) for a user."""
        query = "SELECT * FROM blacklist WHERE user_id = :user_id ORDER BY timestamp DESC LIMIT 1"
        row = await self.database.fetch_one(query=query, values={"user_id": user_id})
        return dict(row) if row else None
    
    # Configuration operations
    async def find_log_config(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Find log config for a guild."""
        query = "SELECT * FROM log_configs WHERE guild_id = :guild_id AND active = TRUE"
        row = await self.database.fetch_one(query=query, values={"guild_id": guild_id})
        return dict(row) if row else None
    
    async def find_alert_config(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Find alert config for a guild."""
        query = "SELECT * FROM alert_configs WHERE guild_id = :guild_id AND active = TRUE"
        row = await self.database.fetch_one(query=query, values={"guild_id": guild_id})
        return dict(row) if row else None
    
    async def find_ping_config(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Find ping config for a guild."""
        query = "SELECT * FROM ping_configs WHERE guild_id = :guild_id AND active = TRUE"
        row = await self.database.fetch_one(query=query, values={"guild_id": guild_id})
        return dict(row) if row else None
    
    async def find_all_configs(self, guild_id: int) -> Dict[str, Optional[Dict[str, Any]]]:
        """Find all configurations for a guild in a single optimized query with caching."""
        # Check cache first
        cached_data = await self._get_from_cache(str(guild_id), "configs")
        if cached_data is not None:
            return cached_data
        
        # Use a UNION ALL query to get all configs in one database roundtrip
        query = """
            SELECT 'log' as config_type, log_channel_id::text as channel_id, NULL::text as role_id, id, created_by, timestamp, active
            FROM log_configs WHERE guild_id = :guild_id AND active = TRUE
            UNION ALL
            SELECT 'alert' as config_type, alert_channel_id::text as channel_id, NULL::text as role_id, id, created_by, timestamp, active
            FROM alert_configs WHERE guild_id = :guild_id AND active = TRUE
            UNION ALL
            SELECT 'ping' as config_type, NULL::text as channel_id, ping_role_id::text as role_id, id, created_by, timestamp, active
            FROM ping_configs WHERE guild_id = :guild_id AND active = TRUE
        """
        
        rows = await self.database.fetch_all(query=query, values={"guild_id": guild_id})
        
        configs = {
            "log_config": None,
            "alert_config": None,
            "ping_config": None
        }
        
        for row in rows:
            row_dict = dict(row)
            config_type = row_dict["config_type"]
            
            if config_type == "log":
                configs["log_config"] = {
                    "id": row_dict["id"],
                    "guild_id": guild_id,
                    "channel_id": int(row_dict["channel_id"]) if row_dict["channel_id"] else None,
                    "created_by": row_dict["created_by"],
                    "timestamp": row_dict["timestamp"],
                    "active": row_dict["active"]
                }
            elif config_type == "alert":
                configs["alert_config"] = {
                    "id": row_dict["id"],
                    "guild_id": guild_id,
                    "channel_id": int(row_dict["channel_id"]) if row_dict["channel_id"] else None,
                    "created_by": row_dict["created_by"],
                    "timestamp": row_dict["timestamp"],
                    "active": row_dict["active"]
                }
            elif config_type == "ping":
                configs["ping_config"] = {
                    "id": row_dict["id"],
                    "guild_id": guild_id,
                    "role_id": int(row_dict["role_id"]) if row_dict["role_id"] else None,
                    "created_by": row_dict["created_by"],
                    "timestamp": row_dict["timestamp"],
                    "active": row_dict["active"]
                }
        
        # Cache the result
        await self._set_cache(str(guild_id), "configs", configs)
        
        return configs
    

    
    
    # Tags operations
    async def find_tag(self, guild_id: int, name: str) -> Optional[Dict[str, Any]]:
        """Find a tag by name in a guild."""
        query = """
            SELECT * FROM tags 
            WHERE guild_id = :guild_id AND LOWER(name) = LOWER(:name) AND active = TRUE
        """
        row = await self.database.fetch_one(query=query, values={"guild_id": guild_id, "name": name})
        return dict(row) if row else None
    
    async def find_all_tags(self, guild_id: int) -> List[Dict[str, Any]]:
        """Find all active tags for a guild."""
        query = "SELECT * FROM tags WHERE guild_id = :guild_id AND active = TRUE ORDER BY name"
        rows = await self.database.fetch_all(query=query, values={"guild_id": guild_id})
        return [dict(row) for row in rows]
    
    async def insert_tag(self, tag_data: Dict[str, Any]) -> int:
        """Insert a new tag."""
        query = """
            INSERT INTO tags (name, content, guild_id, created_by) 
            VALUES (:name, :content, :guild_id, :created_by) 
            RETURNING id
        """
        return await self.database.fetch_val(query=query, values=tag_data)
    
    async def update_tag_usage(self, tag_id: int) -> bool:
        """Update tag usage count and last used timestamp."""
        query = """
            UPDATE tags SET uses = uses + 1, last_used = CURRENT_TIMESTAMP 
            WHERE id = :id
        """
        result = await self.database.execute(query=query, values={"id": tag_id})
        return result is not None and result > 0
    
    
    # Additional missing methods for complete implementation
    
    async def update_tag_status(self, tag_id: int, active: bool) -> bool:
        """Update tag active status."""
        query = "UPDATE tags SET active = :active WHERE id = :id"
        result = await self.database.execute(query=query, values={"id": tag_id, "active": active})
        return result is not None and result > 0
    
    async def update_tag_content(self, tag_id: int, content: str, updated_by: int) -> bool:
        """Update tag content and metadata."""
        query = """
            UPDATE tags 
            SET content = :content, updated_by = :updated_by, updated_at = CURRENT_TIMESTAMP 
            WHERE id = :id
        """
        result = await self.database.execute(query=query, values={
            "id": tag_id, 
            "content": content, 
            "updated_by": updated_by
        })
        return result is not None and result > 0
    
    async def clear_all_configs(self, guild_id: int, cleared_by: int) -> bool:
        """Clear all configurations for a guild."""
        queries = [
            "UPDATE log_configs SET active = FALSE WHERE guild_id = :guild_id AND active = TRUE",
            "UPDATE ping_configs SET active = FALSE WHERE guild_id = :guild_id AND active = TRUE",
            "UPDATE alert_configs SET active = FALSE WHERE guild_id = :guild_id AND active = TRUE"
        ]
        
        for query in queries:
            await self.database.execute(query=query, values={"guild_id": guild_id})
        return True
    
async def deactivate_blacklist(self, user_id: int, removed_by: int, appeal_reason: str = None) -> bool:
    """Deactivate a blacklist record."""

    try:
        # Check if an active blacklist entry exists first
        check_query = """
            SELECT id FROM blacklist
            WHERE user_id = :user_id AND active = TRUE
            ORDER BY timestamp DESC
            LIMIT 1
        """

        record = await self.database.fetch_one(
            query=check_query,
            values={"user_id": user_id}
        )

        if not record:
            logger.warning(f"No active blacklist record found for user {user_id}")
            return False

        # Deactivate the blacklist entry
        update_query = """
            UPDATE blacklist
            SET
                active = FALSE,
                updated_by = :removed_by,
                updated_at = CURRENT_TIMESTAMP,
                appeal_reason = :appeal_reason
            WHERE user_id = :user_id AND active = TRUE
        """

        await self.database.execute(
            query=update_query,
            values={
                "user_id": user_id,
                "removed_by": removed_by,
                "appeal_reason": appeal_reason
            }
        )

        # Clear cache
        await self._invalidate_cache(str(user_id), "blacklist")

        logger.info(f"Blacklist entry for user {user_id} deactivated by {removed_by}")

        return True

    except Exception as e:
        logger.error(f"Error deactivating blacklist for user {user_id}: {e}")
        return False
        
        # Invalidate config cache since configuration changed
        await self._invalidate_cache(str(guild_id), "configs")
        
        return result
    
    async def insert_alert_config(self, guild_id: int, alert_channel_id: int, created_by: int) -> int:
        """Insert a new alert configuration."""
        query = """
            INSERT INTO alert_configs (guild_id, alert_channel_id, created_by) 
            VALUES (:guild_id, :alert_channel_id, :created_by) 
            RETURNING id
        """
        return await self.database.fetch_val(query=query, values={
            "guild_id": guild_id,
            "alert_channel_id": alert_channel_id,
            "created_by": created_by
        })
    
    async def insert_ping_config(self, guild_id: int, ping_role_id: int, created_by: int) -> int:
        """Insert a new ping configuration."""
        query = """
            INSERT INTO ping_configs (guild_id, ping_role_id, created_by) 
            VALUES (:guild_id, :ping_role_id, :created_by) 
            RETURNING id
        """
        return await self.database.fetch_val(query=query, values={
            "guild_id": guild_id,
            "ping_role_id": ping_role_id,
            "created_by": created_by
        })
    

    
    async def remove_ignore_by_target(self, guild_id: int, target_id: int) -> int:
        """Remove ignore record by target ID and return the number of rows affected."""
        query = """
            UPDATE ignores 
            SET active = FALSE 
            WHERE guild_id = :guild_id AND (user_id = :target_id OR channel_id = :target_id) AND active = TRUE
        """
        result = await self.database.execute(query=query, values={
            "guild_id": guild_id, 
            "target_id": target_id
        })
        return result if result is not None else 0
    
    # Server ban operations
    async def insert_server_ban(self, guild_id: int, guild_name: str, reason: str, evidence: str, banned_by: int, expires_at: datetime = None, appeal_allowed: bool = True) -> int:
        """Insert a new server ban record."""
        query = """
            INSERT INTO server_bans (guild_id, guild_name, reason, evidence, banned_by, expires_at, appeal_allowed) 
            VALUES (:guild_id, :guild_name, :reason, :evidence, :banned_by, :expires_at, :appeal_allowed) 
            RETURNING id
        """
        return await self.database.fetch_val(query=query, values={
            "guild_id": guild_id,
            "guild_name": guild_name,
            "reason": reason,
            "evidence": evidence or "",
            "banned_by": banned_by,
            "expires_at": self.normalize_datetime(expires_at) if expires_at else None,
            "appeal_allowed": appeal_allowed
        })
    
    async def find_server_ban(self, guild_id: int, active: bool = True) -> Optional[Dict[str, Any]]:
        """Find a server ban record by guild ID."""
        query = "SELECT * FROM server_bans WHERE guild_id = :guild_id AND active = :active ORDER BY timestamp DESC LIMIT 1"
        row = await self.database.fetch_one(query=query, values={"guild_id": guild_id, "active": active})
        return dict(row) if row else None
    
    async def find_all_server_bans(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Find all active server ban records."""
        query = "SELECT * FROM server_bans WHERE active = TRUE ORDER BY timestamp DESC LIMIT :limit"
        rows = await self.database.fetch_all(query=query, values={"limit": limit})
        return [dict(row) for row in rows]
    
    async def find_expired_server_bans(self) -> List[Dict[str, Any]]:
        """Find all active server ban records that have expired."""
        query = """
            SELECT * FROM server_bans 
            WHERE active = TRUE AND expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP
        """
        rows = await self.database.fetch_all(query=query)
        return [dict(row) for row in rows]
    
    async def deactivate_server_ban(self, guild_id: int, removed_by: int, appeal_reason: str = None) -> bool:
        """Deactivate a server ban record."""
        # First check what records exist before update
        check_query = "SELECT id, active, guild_id FROM server_bans WHERE guild_id = :guild_id ORDER BY timestamp DESC LIMIT 1"
        existing = await self.database.fetch_one(query=check_query, values={"guild_id": guild_id})
        logger.info(f"Before deactivate - existing record for guild {guild_id}: {dict(existing) if existing else None}")
        
        # Use RETURNING to get more information about what was updated
        query = """
            UPDATE server_bans 
            SET active = FALSE, updated_by = :removed_by, updated_at = CURRENT_TIMESTAMP, appeal_reason = :appeal_reason
            WHERE guild_id = :guild_id AND active = TRUE
            RETURNING id, guild_id, active
        """
        
        try:
            updated_record = await self.database.fetch_one(query=query, values={
                "guild_id": guild_id,
                "removed_by": removed_by,
                "appeal_reason": appeal_reason
            })
            
            if updated_record:
                logger.info(f"Successfully updated server ban record: {dict(updated_record)}")
                return True
            else:
                logger.warning(f"No rows updated for guild {guild_id} - either no active record exists or race condition occurred")
                
                # Check final state to see if record was updated by something else
                after = await self.database.fetch_one(query=check_query, values={"guild_id": guild_id})
                logger.info(f"After failed update - record for guild {guild_id}: {dict(after) if after else None}")
                
                # If the record is now inactive, someone else updated it - consider this a success
                if after and not after['active']:
                    logger.info(f"Record for guild {guild_id} is now inactive - considering operation successful")
                    return True
                
                return False
                
        except Exception as e:
            logger.error(f"Exception in deactivate_server_ban for guild {guild_id}: {e}")
            return False
    
    async def expire_server_ban(self, server_ban_id: int) -> bool:
        """Mark a server ban as expired/inactive."""
        query = """
            UPDATE server_bans 
            SET active = FALSE, updated_by = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = :id AND active = TRUE
        """
        result = await self.database.execute(query=query, values={"id": server_ban_id})
        return result is not None and result > 0
    
    async def update_blacklist_reason(self, user_id: int, reason: str, updated_by: int) -> bool:
        """Update blacklist reason for a user."""
        logger.info(f"Database - update_blacklist_reason called for user_id={user_id}, reason='{reason}', updated_by={updated_by}")
        
        query = """
            UPDATE blacklist 
            SET reason = :reason, updated_by = :updated_by, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = :user_id AND active = TRUE
        """
        
        logger.info(f"Database - Executing update query: {query}")
        logger.info(f"Database - Update values: user_id={user_id}, reason='{reason}', updated_by={updated_by}")
        
        try:
            result = await self.database.execute(query=query, values={
                "user_id": user_id,
                "reason": reason,
                "updated_by": updated_by
            })
            
            logger.info(f"Database - Raw execute result: {result} (type: {type(result)})")
            
            # Consider it successful if the query executed without error
            # Some database drivers return None instead of row count
            success = True  # If we get here without exception, the query executed
            logger.info(f"Database - update_blacklist_reason result: {success} (rows affected: {result})")
            
            # Invalidate cache since blacklist was updated
            await self._invalidate_cache(str(user_id), "blacklist")
            
            return success
            
        except Exception as e:
            logger.error(f"Database - Error in update_blacklist_reason for user {user_id}: {e}")
            logger.error(f"Database - Exception type: {type(e)}")
            import traceback
            logger.error(f"Database - Traceback: {traceback.format_exc()}")
            return False
    
    async def update_blacklist_full(self, user_id: int, updated_by: int, **updates) -> bool:
        """Update multiple blacklist fields for a user."""
        if not updates:
            return False
        
        # Build SET clause dynamically
        set_clauses = []
        values = {"user_id": user_id, "updated_by": updated_by}
        
        for field, value in updates.items():
            if field in ['reason', 'evidence', 'expires_at', 'appeal_allowed']:
                set_clauses.append(f"{field} = :{field}")
                values[field] = self.normalize_datetime(value) if field == 'expires_at' and value else value
        
        if not set_clauses:
            return False
        
        set_clauses.append("updated_by = :updated_by")
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")
        
        query = f"""
            UPDATE blacklist 
            SET {', '.join(set_clauses)}
            WHERE user_id = :user_id AND active = TRUE
        """
        
        logger.info(f"Database - Executing full update query: {query}")
        logger.info(f"Database - Update values: {values}")
        
        try:
            result = await self.database.execute(query=query, values=values)
            
            # Consider it successful if the query executed without error
            # Some database drivers return None instead of row count
            success = True  # If we get here without exception, the query executed
            logger.info(f"Database - update_blacklist_full result: {success} (rows affected: {result})")
            
            # Invalidate cache since blacklist was updated
            await self._invalidate_cache(str(user_id), "blacklist")
            
            return success
            
        except Exception as e:
            logger.error(f"Database - Error in update_blacklist_full for user {user_id}: {e}")
            return False
    
    async def deactivate_blacklist(self, user_id: int, removed_by: int, appeal_reason: str = None) -> bool:
        """Deactivate a blacklist record."""
        query = """
            UPDATE blacklist 
            SET active = FALSE, updated_by = :removed_by, updated_at = CURRENT_TIMESTAMP, appeal_reason = :appeal_reason
            WHERE user_id = :user_id AND active = TRUE
        """
        result = await self.database.execute(query=query, values={
            "user_id": user_id,
            "removed_by": removed_by,
            "appeal_reason": appeal_reason
        })
        
        # Invalidate cache since blacklist status changed
        await self._invalidate_cache(str(user_id), "blacklist")
        
        return result is not None and result > 0
    
    # Verification operations
    async def create_verification_session(self, user_id: int, session_id: str, verification_type: str, phone_number: str = None, verification_code: str = None, expires_at: datetime = None) -> int:
        """Create a new verification session."""
        if expires_at is None:
            expires_at = datetime.utcnow() + timedelta(minutes=10)  # 10 minute default expiry
        
        query = """
            INSERT INTO verification_sessions (
                user_id, session_id, verification_type, phone_number, verification_code, expires_at
            ) VALUES (
                :user_id, :session_id, :verification_type, :phone_number, :verification_code, :expires_at
            ) RETURNING id
        """
        return await self.database.fetch_val(query=query, values={
            "user_id": user_id,
            "session_id": session_id,
            "verification_type": verification_type,
            "phone_number": phone_number,
            "verification_code": verification_code,
            "expires_at": self.normalize_datetime(expires_at)
        })
    
    async def find_verification_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Find a verification session by session ID."""
        query = """
            SELECT * FROM verification_sessions 
            WHERE session_id = :session_id AND expires_at > CURRENT_TIMESTAMP
        """
        row = await self.database.fetch_one(query=query, values={"session_id": session_id})
        return dict(row) if row else None
    
    async def verify_session(self, session_id: str) -> bool:
        """Mark a verification session as verified."""
        query = """
            UPDATE verification_sessions 
            SET verified = TRUE, verified_at = CURRENT_TIMESTAMP
            WHERE session_id = :session_id AND expires_at > CURRENT_TIMESTAMP
        """
        result = await self.database.execute(query=query, values={"session_id": session_id})
        return result is not None and result > 0
    
    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired verification sessions."""
        query = "DELETE FROM verification_sessions WHERE expires_at <= CURRENT_TIMESTAMP"
        result = await self.database.execute(query=query)
        return result or 0
    
    async def store_user_phone_number(self, user_id: int, phone_number: str) -> int:
        """Store or update a user's phone number."""
        query = """
            INSERT INTO user_phone_numbers (user_id, phone_number, verified)
            VALUES (:user_id, :phone_number, TRUE)
            ON CONFLICT (user_id) 
            DO UPDATE SET 
                phone_number = EXCLUDED.phone_number,
                verified = TRUE,
                verified_at = CURRENT_TIMESTAMP
            RETURNING id
        """
        return await self.database.fetch_val(query=query, values={
            "user_id": user_id,
            "phone_number": phone_number
        })
    
    async def get_user_phone_number(self, user_id: int) -> Optional[str]:
        """Get a user's verified phone number."""
        query = """
            SELECT phone_number FROM user_phone_numbers 
            WHERE user_id = :user_id AND verified = TRUE
        """
        result = await self.database.fetch_val(query=query, values={"user_id": user_id})
        return result
    
    # 2FA Backup codes operations
    async def store_2fa_backup_codes(self, user_id: int, backup_codes: str) -> int:
        """Store 2FA backup codes for a user."""
        query = """
            INSERT INTO user_2fa_backup (user_id, backup_codes)
            VALUES (:user_id, :backup_codes)
            ON CONFLICT (user_id) 
            DO UPDATE SET 
                backup_codes = EXCLUDED.backup_codes,
                created_at = CURRENT_TIMESTAMP
            RETURNING id
        """
        return await self.database.fetch_val(query=query, values={
            "user_id": user_id,
            "backup_codes": backup_codes
        })
    
    async def get_2fa_backup_codes(self, user_id: int) -> Optional[str]:
        """Get 2FA backup codes for a user."""
        query = """
            SELECT backup_codes FROM user_2fa_backup 
            WHERE user_id = :user_id
        """
        result = await self.database.fetch_val(query=query, values={"user_id": user_id})
        return result
    
    async def remove_2fa_backup_codes(self, user_id: int) -> bool:
        """Remove 2FA backup codes for a user."""
        query = "DELETE FROM user_2fa_backup WHERE user_id = :user_id"
        result = await self.database.execute(query=query, values={"user_id": user_id})
        return result is not None and result > 0
    
    # Authorized servers operations
    async def authorize_server(self, guild_id: int, guild_name: str, authorized_by: int, reason: str = None) -> int:
        """Authorize a server for EPN access."""
        query = """
            INSERT INTO authorized_servers (guild_id, guild_name, authorized_by, reason) 
            VALUES (:guild_id, :guild_name, :authorized_by, :reason) 
            ON CONFLICT (guild_id) 
            DO UPDATE SET 
                guild_name = EXCLUDED.guild_name,
                authorized_by = EXCLUDED.authorized_by,
                authorized_at = CURRENT_TIMESTAMP,
                reason = EXCLUDED.reason,
                active = TRUE
            RETURNING id
        """
        return await self.database.fetch_val(query=query, values={
            "guild_id": guild_id,
            "guild_name": guild_name,
            "authorized_by": authorized_by,
            "reason": reason
        })
    
    async def deauthorize_server(self, guild_id: int, deauthorized_by: int, reason: str = None) -> bool:
        """Deauthorize a server from EPN access."""
        query = """
            UPDATE authorized_servers 
            SET active = FALSE, authorized_by = :deauthorized_by, authorized_at = CURRENT_TIMESTAMP, reason = :reason
            WHERE guild_id = :guild_id AND active = TRUE
        """
        result = await self.database.execute(query=query, values={
            "guild_id": guild_id,
            "deauthorized_by": deauthorized_by,
            "reason": reason
        })
        return result is not None and result > 0
    
    async def is_server_authorized(self, guild_id: int) -> bool:
        """Check if a server is authorized for EPN access."""
        query = "SELECT 1 FROM authorized_servers WHERE guild_id = :guild_id AND active = TRUE LIMIT 1"
        result = await self.database.fetch_one(query=query, values={"guild_id": guild_id})
        return result is not None
    
    async def get_authorized_servers(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all authorized servers."""
        query = """
            SELECT * FROM authorized_servers 
            WHERE active = TRUE 
            ORDER BY authorized_at DESC 
            LIMIT :limit
        """
        rows = await self.database.fetch_all(query=query, values={"limit": limit})
        return [dict(row) for row in rows]
    
    async def get_server_authorization(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Get server authorization details."""
        query = """
            SELECT * FROM authorized_servers 
            WHERE guild_id = :guild_id AND active = TRUE 
            ORDER BY authorized_at DESC 
            LIMIT 1
        """
        row = await self.database.fetch_one(query=query, values={"guild_id": guild_id})
        return dict(row) if row else None
    
    # User blocking operations
    async def insert_user_block(self, user_id: int, reason: str, evidence: str = "", 
                               blocked_by: int = None, expires_at: datetime = None, 
                               appeal_allowed: bool = True) -> int:
        """Insert a new user block record."""
        query = """
            INSERT INTO user_blocks (user_id, reason, evidence, blocked_by, expires_at, appeal_allowed) 
            VALUES (:user_id, :reason, :evidence, :blocked_by, :expires_at, :appeal_allowed) 
            RETURNING id
        """
        result = await self.database.fetch_val(query=query, values={
            "user_id": user_id,
            "reason": reason,
            "evidence": evidence or "",
            "blocked_by": blocked_by,
            "expires_at": self.normalize_datetime(expires_at) if expires_at else None,
            "appeal_allowed": appeal_allowed
        })
        return result
    
    async def find_user_block(self, user_id: int, active: bool = True) -> Optional[Dict[str, Any]]:
        """Find a user block record by user ID."""
        query = "SELECT * FROM user_blocks WHERE user_id = :user_id AND active = :active ORDER BY timestamp DESC LIMIT 1"
        row = await self.database.fetch_one(query=query, values={"user_id": user_id, "active": active})
        return dict(row) if row else None
    
    async def deactivate_user_block(self, user_id: int, unblocked_by: int, unblock_reason: str = None) -> bool:
        """Deactivate a user block record."""
        query = """
            UPDATE user_blocks 
            SET active = FALSE, updated_by = :unblocked_by, updated_at = CURRENT_TIMESTAMP, unblock_reason = :unblock_reason
            WHERE user_id = :user_id AND active = TRUE
        """
        result = await self.database.execute(query=query, values={
            "user_id": user_id,
            "unblocked_by": unblocked_by,
            "unblock_reason": unblock_reason
        })
        return result is not None and result > 0
    
    async def get_all_user_blocks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all active user blocks."""
        # Log potential data breach attempt if requesting excessive user block records
        if limit > 100:
            try:
                from utils.security_logger import get_security_logger, SecurityEventType, SecurityEventSeverity
                security_logger = get_security_logger(None)
                await security_logger.log_event(
                    SecurityEventType.DATA_BREACH_ATTEMPT,
                    SecurityEventSeverity.HIGH,
                    details={
                        "operation": "get_all_user_blocks",
                        "requested_limit": limit,
                        "breach_indicator": "mass_user_data_extraction_attempt"
                    },
                    action_taken="Request allowed but logged for investigation"
                )
            except Exception:
                pass
        
        query = """
            SELECT * FROM user_blocks 
            WHERE active = TRUE 
            ORDER BY timestamp DESC 
            LIMIT :limit
        """
        rows = await self.database.fetch_all(query=query, values={"limit": limit})
        return [dict(row) for row in rows]
    
    # Guild blocking operations
    async def insert_guild_block(self, guild_id: int, guild_name: str, reason: str, evidence: str = "", 
                                blocked_by: int = None, expires_at: datetime = None, 
                                appeal_allowed: bool = True) -> int:
        """Insert a new guild block record."""
        query = """
            INSERT INTO guild_blocks (guild_id, guild_name, reason, evidence, blocked_by, expires_at, appeal_allowed) 
            VALUES (:guild_id, :guild_name, :reason, :evidence, :blocked_by, :expires_at, :appeal_allowed) 
            RETURNING id
        """
        result = await self.database.fetch_val(query=query, values={
            "guild_id": guild_id,
            "guild_name": guild_name,
            "reason": reason,
            "evidence": evidence or "",
            "blocked_by": blocked_by,
            "expires_at": self.normalize_datetime(expires_at) if expires_at else None,
            "appeal_allowed": appeal_allowed
        })
        return result
    
    async def find_guild_block(self, guild_id: int, active: bool = True) -> Optional[Dict[str, Any]]:
        """Find a guild block record by guild ID."""
        query = "SELECT * FROM guild_blocks WHERE guild_id = :guild_id AND active = :active ORDER BY timestamp DESC LIMIT 1"
        row = await self.database.fetch_one(query=query, values={"guild_id": guild_id, "active": active})
        return dict(row) if row else None
    
    async def deactivate_guild_block(self, guild_id: int, unblocked_by: int, unblock_reason: str = None) -> bool:
        """Deactivate a guild block record."""
        query = """
            UPDATE guild_blocks 
            SET active = FALSE, updated_by = :unblocked_by, updated_at = CURRENT_TIMESTAMP, unblock_reason = :unblock_reason
            WHERE guild_id = :guild_id AND active = TRUE
        """
        result = await self.database.execute(query=query, values={
            "guild_id": guild_id,
            "unblocked_by": unblocked_by,
            "unblock_reason": unblock_reason
        })
        return result is not None and result > 0
    
    async def get_all_guild_blocks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all active guild blocks."""
        query = """
            SELECT * FROM guild_blocks 
            WHERE active = TRUE 
            ORDER BY timestamp DESC 
            LIMIT :limit
        """
        rows = await self.database.fetch_all(query=query, values={"limit": limit})
        return [dict(row) for row in rows]
