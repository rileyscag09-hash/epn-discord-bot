# 🔒 Suspicious Activity Detection System - Complete Guide

## 📋 **What is Suspicious Activity?**

`SUSPICIOUS_ACTIVITY` is a security event type in your bot that gets triggered when potentially harmful or unusual behavior patterns are detected. It's now **fully integrated** into your bot's security system.

## 🚨 **When is Suspicious Activity Triggered?**

Your suspicious activity detection system now automatically monitors for:

### **1. Message Pattern Detection** 🔍
- **Discord server invites** (`discord.gg/...`)
- **Mass mentions** (`@everyone`, `@here`)
- **Scam keywords** (`free`, `nitro`, `gift`, `hack`, `exploit`)
- **Shortened URLs** (`bit.ly`, `tinyurl.com`)
- **Excessive caps** (>70% uppercase characters)
- **Repeated identical messages** (spam)
- **New accounts** (<7 days old) sending suspicious content

### **2. Command Spam Detection** ⚡
- **Rapid command usage** (>10 commands in 60 seconds)
- **Repeated failed commands** (same command failing 5+ times)
- **Permission escalation attempts** (repeated permission-denied errors)

### **3. Suspicious Member Joins** 👤
- **Very new accounts** (<1 day old)
- **Default avatars** combined with other red flags
- **Suspicious usernames** (containing `discord`, `admin`, `bot`, lots of numbers)
- **Off-hours joining** (late night/early morning potential bot activity)

### **4. DM Spam Detection** 📩
- **Excessive DM activity** (>10 DMs to the bot in 1 hour)

## 🔧 **Integration Points**

The system is now integrated into:

1. **`cogs/events.py`** - Message and member join monitoring
2. **`UEC.py`** - Command error and spam detection
3. **Global before_invoke hook** - Command usage tracking

## 📊 **Severity Levels**

- **🔵 LOW**: Minor suspicious patterns
- **🟡 MEDIUM**: Multiple red flags or moderate concern
- **🔴 HIGH**: Clear suspicious behavior requiring attention
- **🟣 CRITICAL**: Severe threats (auto-triggers immediate alerts)

## 📈 **Detection Examples**

### ✅ **Successfully Detected Patterns:**

```
🚨 Message: "FREE NITRO! Click here: discord.gg/fakeserver"
   Flags: Discord invite + scam words + new account
   Severity: HIGH

🚨 Command Spam: 11 commands in 60 seconds
   Detection: Excessive command usage
   Severity: HIGH

🚨 Suspicious Join: Username "bot12345", 0 days old, default avatar
   Flags: New account + bot-like name + default avatar
   Severity: MEDIUM
```

### ✅ **Normal Activity (Not Flagged):**
- Regular conversation messages
- Normal command usage patterns
- Established users with normal names
- Moderate activity levels

## 🛠 **How to Test It**

### **Method 1: Run the Test Suite**
```bash
python test_suspicious_activity.py
```

### **Method 2: Live Testing with Your Bot**
1. Start your bot: `python main.py --dev`
2. Try these activities to trigger detection:
   - Send multiple commands rapidly (>10 in a minute)
   - Post messages with `discord.gg/test` links
   - Use `@everyone` mentions
   - Send messages in ALL CAPS WITH SCAM WORDS

### **Method 3: Monitor Logs**
Look for security events in your console:
```
[2025-09-26] - SECURITY EVENT: suspicious_activity | Severity: high | User: 123456
```

## 📍 **What Happens When Triggered?**

1. **🔍 Event Logged**: Activity is recorded with detailed context
2. **📋 Buffer Added**: Event goes into security event buffer
3. **⚠️ Immediate Alert**: High/Critical events send Discord alerts
4. **📊 Analytics**: Patterns tracked for trend analysis
5. **🔄 Auto-Flush**: Events stored every minute or when buffer is full

## 🎯 **Customization Options**

You can adjust detection thresholds in `suspicious_activity_detector.py`:

```python
# Command spam thresholds
if len(recent_commands) > 10:  # Change from 10 to your preference

# Message pattern sensitivity  
if caps_ratio > 0.7:  # Change caps threshold

# Account age sensitivity
if account_age < 7:  # Change new account threshold

# DM spam limits
if len(recent_dms) > 10:  # Change DM limit
```

## 📋 **Event Data Structure**

Each suspicious activity event includes:

```json
{
  "activity_type": "suspicious_message_pattern",
  "flags": ["Pattern: discord.gg/...", "New account (0 days old)"],
  "message_content": "Content snippet...",
  "account_age_days": 0,
  "detection_reason": "3 suspicious patterns detected",
  "user_id": 123456789,
  "guild_id": 987654321,
  "channel_id": 555666777,
  "timestamp": "2025-09-26T18:47:31+00:00"
}
```

## 🚀 **Next Steps**

1. **Start your bot** and the detection system activates automatically
2. **Monitor security logs** for suspicious activity events
3. **Customize thresholds** based on your server's needs
4. **Review alerts** in your designated security channel
5. **Analyze patterns** to improve detection over time

## 🔐 **Security Benefits**

- **Early Warning System**: Detects threats before they escalate
- **Pattern Recognition**: Identifies coordinated attacks
- **Evidence Collection**: Detailed logs for moderation decisions  
- **Automated Monitoring**: 24/7 surveillance without manual oversight
- **Trend Analysis**: Historical data for improving security

Your suspicious activity detection system is now **fully operational** and monitoring all the key attack vectors that Discord servers face! 🛡️