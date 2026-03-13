"""
Rate limiter for external APIs with persistence across restarts.
"""
import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, Optional
from collections import deque
from utils.constants import logger
from utils.database import DatabaseManager


class RateLimiter:
    """Rate limiter that respects API limits and persists state across restarts."""
    
    def __init__(self, max_requests: int, time_window: int, api_name: str, database_manager: Optional[DatabaseManager] = None):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum number of requests allowed
            time_window: Time window in seconds
            api_name: Name of the API for database storage
            database_manager: Database manager for persistence
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.api_name = api_name
        self.database_manager = database_manager
        
        # In-memory request tracking
        self.request_times: deque = deque()
        self._lock = asyncio.Lock()
        
        # Load existing state from database if available
        if self.database_manager:
            asyncio.create_task(self._load_state_from_db())
    
    async def _load_state_from_db(self):
        """Load rate limiter state from database on startup."""
        try:
            if not self.database_manager:
                return
                
            # Get the most recent rate limit state for this API
            query = """
                SELECT request_times, last_updated 
                FROM rate_limiter_state 
                WHERE api_name = :api_name 
                ORDER BY last_updated DESC 
                LIMIT 1
            """
            
            row = await self.database_manager.database.fetch_one(
                query=query, 
                values={"api_name": self.api_name}
            )
            
            if row:
                # Parse stored request times and filter out expired ones
                stored_times = row.get("request_times", [])
                current_time = time.time()
                cutoff_time = current_time - self.time_window
                
                # Only keep requests within the current time window
                valid_times = [t for t in stored_times if t > cutoff_time]
                self.request_times = deque(valid_times, maxlen=self.max_requests)
                
                logger.info(f"Loaded {len(valid_times)} recent requests for {self.api_name} from database")
            else:
                logger.info(f"No previous state found for {self.api_name}, starting fresh")
                
        except Exception as e:
            logger.error(f"Error loading rate limiter state for {self.api_name}: {e}")
    
    async def _save_state_to_db(self):
        """Save current rate limiter state to database."""
        if not self.database_manager:
            return
            
        try:
            # Convert deque to list for JSON serialization
            request_times_list = list(self.request_times)
            
            # Upsert the rate limiter state
            query = """
                INSERT INTO rate_limiter_state (api_name, request_times, last_updated)
                VALUES (:api_name, :request_times, :last_updated)
                ON CONFLICT (api_name) 
                DO UPDATE SET 
                    request_times = EXCLUDED.request_times,
                    last_updated = EXCLUDED.last_updated
            """
            
            await self.database_manager.database.execute(
                query=query,
                values={
                    "api_name": self.api_name,
                    "request_times": request_times_list,
                    "last_updated": datetime.utcnow()
                }
            )
            
        except Exception as e:
            logger.error(f"Error saving rate limiter state for {self.api_name}: {e}")
    
    async def can_make_request(self) -> bool:
        """
        Check if a request can be made without exceeding the rate limit.
        
        Returns:
            True if request can be made, False otherwise
        """
        async with self._lock:
            current_time = time.time()
            cutoff_time = current_time - self.time_window
            
            # Remove expired requests
            while self.request_times and self.request_times[0] <= cutoff_time:
                self.request_times.popleft()
            
            # Check if we can make another request
            if len(self.request_times) < self.max_requests:
                return True
            
            # Calculate time until next request is allowed
            oldest_request = self.request_times[0]
            next_allowed_time = oldest_request + self.time_window
            wait_time = next_allowed_time - current_time
            
            logger.warning(f"Rate limit exceeded for {self.api_name}. Next request allowed in {wait_time:.2f} seconds")
            
            # Log security event for rate limit exceeded
            try:
                from utils.security_logger import get_security_logger, SecurityEventType, SecurityEventSeverity
                security_logger = get_security_logger(None)  # Bot instance not available in rate limiter
                await security_logger.log_event(
                    SecurityEventType.RATE_LIMIT_EXCEEDED,
                    SecurityEventSeverity.MEDIUM,
                    details={
                        "api_name": self.api_name,
                        "current_requests": len(self.request_times),
                        "max_requests": self.max_requests,
                        "time_window": self.time_window,
                        "wait_time": wait_time
                    },
                    action_taken="Request blocked due to rate limiting"
                )
            except Exception as e:
                logger.error(f"Failed to log rate limit security event: {e}")
            
            return False
    
    async def record_request(self):
        """Record a request and save state to database."""
        async with self._lock:
            current_time = time.time()
            self.request_times.append(current_time)
            
            # Save state to database (fire and forget)
            if self.database_manager:
                asyncio.create_task(self._save_state_to_db())
    
    async def get_wait_time(self) -> float:
        """
        Get the time in seconds until the next request is allowed.
        
        Returns:
            Time in seconds until next request is allowed, or 0 if no wait needed
        """
        async with self._lock:
            if len(self.request_times) < self.max_requests:
                return 0.0
            
            current_time = time.time()
            cutoff_time = current_time - self.time_window
            
            # Remove expired requests
            while self.request_times and self.request_times[0] <= cutoff_time:
                self.request_times.popleft()
            
            if len(self.request_times) < self.max_requests:
                return 0.0
            
            oldest_request = self.request_times[0]
            next_allowed_time = oldest_request + self.time_window
            return max(0.0, next_allowed_time - current_time)
    
    async def get_remaining_requests(self) -> int:
        """
        Get the number of requests remaining in the current time window.
        
        Returns:
            Number of requests remaining
        """
        async with self._lock:
            current_time = time.time()
            cutoff_time = current_time - self.time_window
            
            # Remove expired requests
            while self.request_times and self.request_times[0] <= cutoff_time:
                self.request_times.popleft()
            
            return max(0, self.max_requests - len(self.request_times))
    
    def get_stats(self) -> Dict[str, any]:
        """Get current rate limiter statistics."""
        return {
            "api_name": self.api_name,
            "max_requests": self.max_requests,
            "time_window": self.time_window,
            "current_requests": len(self.request_times),
            "remaining_requests": self.max_requests - len(self.request_times)
        }


class MelonlyRateLimiter(RateLimiter):
    """Specialized rate limiter for Melonly API with 60 requests per minute."""
    
    def __init__(self, database_manager: Optional[DatabaseManager] = None):
        super().__init__(
            max_requests=60,
            time_window=60,  # 60 seconds
            api_name="melonly",
            database_manager=database_manager
        )


class UserCommandRateLimiter:
    """Rate limiter for user commands with per-user tracking."""
    
    def __init__(self, max_requests: int, time_window: int, command_name: str):
        """
        Initialize user command rate limiter.
        
        Args:
            max_requests: Maximum number of requests allowed per user
            time_window: Time window in seconds
            command_name: Name of the command for logging
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.command_name = command_name
        
        # Per-user request tracking: {user_id: deque of timestamps}
        self.user_requests: Dict[int, deque] = {}
        self._lock = asyncio.Lock()
    
    async def can_make_request(self, user_id: int) -> bool:
        """
        Check if a user can make a request without exceeding the rate limit.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            True if request can be made, False otherwise
        """
        async with self._lock:
            current_time = time.time()
            cutoff_time = current_time - self.time_window
            
            # Get or create user's request history
            if user_id not in self.user_requests:
                self.user_requests[user_id] = deque()
            
            user_deque = self.user_requests[user_id]
            
            # Remove expired requests
            while user_deque and user_deque[0] <= cutoff_time:
                user_deque.popleft()
            
            # Check if user can make another request
            if len(user_deque) < self.max_requests:
                return True
            
            logger.warning(f"Rate limit exceeded for user {user_id} on {self.command_name}. {len(user_deque)}/{self.max_requests} requests in {self.time_window}s")
            
            # Log security event for user command rate limit exceeded
            try:
                from utils.security_logger import get_security_logger, SecurityEventType, SecurityEventSeverity
                security_logger = get_security_logger(None)  # Bot instance not available in rate limiter
                await security_logger.log_event(
                    SecurityEventType.RATE_LIMIT_EXCEEDED,
                    SecurityEventSeverity.MEDIUM,
                    user_id=user_id,
                    details={
                        "command_name": self.command_name,
                        "current_requests": len(user_deque),
                        "max_requests": self.max_requests,
                        "time_window": f"{self.time_window}s",
                        "rate_limit_type": "user_command_limit"
                    },
                    action_taken="Command request blocked due to rate limiting"
                )
            except Exception as e:
                logger.error(f"Failed to log user command rate limit security event: {e}")
            
            return False
    
    async def record_request(self, user_id: int):
        """Record a request for a user."""
        async with self._lock:
            current_time = time.time()
            
            # Get or create user's request history
            if user_id not in self.user_requests:
                self.user_requests[user_id] = deque()
            
            self.user_requests[user_id].append(current_time)
    
    async def get_wait_time(self, user_id: int) -> float:
        """
        Get the time in seconds until the next request is allowed for a user.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            Time in seconds until next request is allowed, or 0 if no wait needed
        """
        async with self._lock:
            if user_id not in self.user_requests:
                return 0.0
            
            user_deque = self.user_requests[user_id]
            if len(user_deque) < self.max_requests:
                return 0.0
            
            current_time = time.time()
            cutoff_time = current_time - self.time_window
            
            # Remove expired requests
            while user_deque and user_deque[0] <= cutoff_time:
                user_deque.popleft()
            
            if len(user_deque) < self.max_requests:
                return 0.0
            
            oldest_request = user_deque[0]
            next_allowed_time = oldest_request + self.time_window
            return max(0.0, next_allowed_time - current_time)
    
    async def get_remaining_requests(self, user_id: int) -> int:
        """
        Get the number of requests remaining for a user in the current time window.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            Number of requests remaining
        """
        async with self._lock:
            if user_id not in self.user_requests:
                return self.max_requests
            
            current_time = time.time()
            cutoff_time = current_time - self.time_window
            user_deque = self.user_requests[user_id]
            
            # Remove expired requests
            while user_deque and user_deque[0] <= cutoff_time:
                user_deque.popleft()
            
            return max(0, self.max_requests - len(user_deque))
    
    def get_stats(self, user_id: int) -> Dict[str, any]:
        """Get current rate limiter statistics for a user."""
        user_deque = self.user_requests.get(user_id, deque())
        return {
            "command_name": self.command_name,
            "user_id": user_id,
            "max_requests": self.max_requests,
            "time_window": self.time_window,
            "current_requests": len(user_deque),
            "remaining_requests": max(0, self.max_requests - len(user_deque))
        }