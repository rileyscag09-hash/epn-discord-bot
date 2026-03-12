"""
Test script to verify SQL injection detection and scraping detection functionality.
"""

import asyncio
import sys
import os

# Add the parent directory to the path so we can import from utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from utils.validation import InputSanitizer
from utils.scraping_detector import get_scraping_detector

async def test_sql_injection_detection():
    """Test SQL injection pattern detection."""
    print("Testing SQL injection detection...")
    
    # Test cases - these should trigger security logging
    malicious_inputs = [
        "'; DROP TABLE users; --",
        "' OR '1'='1",
        "' UNION SELECT * FROM passwords",
        "admin'; DELETE FROM accounts WHERE 1=1; --",
        "test' OR 1=1#",
        "user' AND (SELECT COUNT(*) FROM users) > 0 --"
    ]
    
    # Test cases - these should NOT trigger security logging
    safe_inputs = [
        "Hello world!",
        "This is a normal message",
        "User123",
        "test@example.com",
        "Normal text with some symbols: @#$%"
    ]
    
    print("\nTesting malicious inputs (should detect SQL injection):")
    for i, malicious_input in enumerate(malicious_inputs, 1):
        print(f"{i}. Testing: {malicious_input}")
        sanitized = InputSanitizer.sanitize_text(malicious_input)
        print(f"   Sanitized to: {sanitized}")
        print()
    
    print("\nTesting safe inputs (should NOT detect SQL injection):")
    for i, safe_input in enumerate(safe_inputs, 1):
        print(f"{i}. Testing: {safe_input}")
        sanitized = InputSanitizer.sanitize_text(safe_input)
        print(f"   Sanitized to: {sanitized}")
        print()

async def test_scraping_detection():
    """Test scraping detection functionality."""
    print("Testing scraping detection...")
    
    scraping_detector = get_scraping_detector()
    
    # Simulate rapid user lookups (should trigger scraping detection)
    print("\nSimulating rapid user lookups (should detect scraping):")
    for i in range(15):  # Exceed the rapid lookup threshold
        user_id = 123456789  # Simulated attacker
        target_user_id = 100000000 + i  # Different target users
        
        is_scraping = await scraping_detector.track_user_lookup(
            user_id=user_id,
            command="userinfo",
            target_user_id=target_user_id,
            guild_id=987654321
        )
        
        if is_scraping:
            print(f"   Scraping detected on lookup {i+1}")
            break
        else:
            print(f"   Lookup {i+1}: Normal behavior")
    
    # Get user stats
    stats = scraping_detector.get_user_stats(123456789)
    if stats:
        print(f"\nUser scraping stats: {stats}")

async def main():
    """Run all tests."""
    print("=== Security System Test ===\n")
    
    await test_sql_injection_detection()
    print("\n" + "="*50 + "\n")
    await test_scraping_detection()
    
    print("\n=== Test Complete ===")
    print("Check the console output above to see if security events were detected.")
    print("In a real bot environment, these would also be logged to Discord and the database.")

if __name__ == "__main__":
    asyncio.run(main())