import os
import sys
import json
import requests
import logging
from datetime import datetime
from typing import Dict, Tuple, Optional, Any
from dotenv import load_dotenv
import re

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('moderation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()
API_KEY = os.getenv("OPENROUTER_API_KEY")

if not API_KEY:
    logger.error("❌ OPENROUTER_API_KEY not found in .env")
    sys.exit(1)

WARNINGS_FILE = "warnings.json"
MODEL = "mistralai/mistral-7b-instruct"
TIMEOUT = 15

LOCAL_BLACKLIST = {
    # Profanity (explicit)
    'fuck', 'fucker', 'fucking',
    'shit', 'shitting',
    'asshole', 'ass',
    'bitch', 'bitches',
    'bastard',
    'motherfucker', 'motherfucking', 'mofo',
    'damn', 'crap', 'hell',
    
    # Strong racial slurs (only the worst)
    'nigger', 'nigga', 
    'chink', 'spic', 'kike', 'gook',
    
    # Severe sexual terms
    'rape', 'raping', 'rapist',
    'pedo', 'pedophile',
    'molest',
    
    # Extreme insults
    'retard', 'retarded',
}

SPACED_PROFANITY_PATTERNS = [
    r'f\s*u\s*c\s*k',  # f u c k
    r's\s*h\s*i\s*t',  # s h i t
    r'a\s*s\s*s',      # a s s
    r'b\s*i\s*t\s*c\s*h',  # b i t c h
]

def normalize_text(text: str) -> str:
    """Normalize text but keep words separate"""
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)  
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def contains_bad_words(text: str) -> Tuple[bool, Optional[str]]:
    """Local filtering - ONLY for clear, explicit profanity"""
    

    text_lower = text.lower()
    normalized = normalize_text(text_lower)
    words = normalized.split()
    

    for word in words:
        if word in LOCAL_BLACKLIST:
            return True, f"Contains explicit profanity: '{word}'"
    

    for pattern in SPACED_PROFANITY_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True, "Contains spaced-out profanity"
    
    # Check for common profanity combinations
    if any(phrase in text_lower for phrase in ["fuck you", "fuck off", "shit head", "ass hole"]):
        return True, "Contains profane phrase"
    
    return False, None

def parse_ai_response(content: str) -> Dict:
    """Parse AI response and extract JSON"""
    try:
       
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            json_str = json_match.group()
            result = json.loads(json_str)
            
        
            if "bad" not in result:
                result["bad"] = False
            if "reason" not in result:
                result["reason"] = "AI response missing reason field"
            if "severity" not in result:
                result["severity"] = "medium"
            if "category" not in result:
                result["category"] = "unknown"
            
            return result
        else:
   
            content_lower = content.lower()
            
     
            rejection_keywords = [
                "bad", "profanity", "insult", "hate", "offensive", 
                "inappropriate", "violation", "warning", "true"
            ]
            
            if any(keyword in content_lower for keyword in rejection_keywords):
                return {
                    "bad": True,
                    "reason": f"AI flagged: {content[:80]}...",
                    "severity": "medium",
                    "category": "ai_detected"
                }
            else:
               
                return {
                    "bad": False,
                    "reason": "Message appears clean",
                    "severity": "low",
                    "category": "none"
                }
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return {
            "bad": False,
            "reason": "Failed to parse AI response",
            "severity": "low",
            "category": "parse_error"
        }

def moderate_message(message: str) -> Dict:
    """
    Two-tier moderation system:
    1. Local filter for EXPLICIT profanity only
    2. AI analysis for everything else
    """
    
   
    if len(message.strip()) < 2:
        return {
            "bad": False,
            "reason": "Message too short",
            "severity": "low",
            "category": "none",
            "source": "short_message"
        }
    
   
    local_bad, local_reason = contains_bad_words(message)
    if local_bad:
        return {
            "bad": True, 
            "reason": local_reason, 
            "source": "local_filter",
            "severity": "high",
            "category": "explicit_content"
        }
    
   
    url = "https://openrouter.ai/api/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/daemonunit42/badword_detector",
        "X-Title": "Advanced Moderation System"
    }
    
   
    system_prompt = """You are a content moderator. Analyze if the message contains ANY inappropriate content.

Rules:
- Return ONLY JSON, no other text
- JSON format must be:
{
    "bad": true or false,
    "reason": "short explanation",
    "severity": "low", "medium", or "high",
    "category": "profanity", "insult", "hate", "threat", "sexual", "harassment", or "none"
}

Examples:
- "hello how are you?" → {"bad": false, "reason": "Clean message", "severity": "low", "category": "none"}
- "fuck you" → {"bad": true, "reason": "Contains profanity", "severity": "high", "category": "profanity"}
- "you are stupid" → {"bad": true, "reason": "Personal insult", "severity": "medium", "category": "insult"}

Be fair. Only mark as bad if truly inappropriate."""

    payload = {
        "model": MODEL,
        "temperature": 0.1,
        "max_tokens": 200,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
        content = data["choices"][0]["message"]["content"].strip()
        logger.debug(f"AI Raw Response: {content[:200]}")
        
        result = parse_ai_response(content)
        result["source"] = "ai"
        
        return result
        
    except requests.exceptions.Timeout:
        return {
            "bad": False,
            "reason": "Moderation timeout - passed",
            "severity": "low",
            "category": "none",
            "source": "timeout"
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return {
            "bad": False,
            "reason": "Moderation error - passed",
            "severity": "low",
            "category": "none",
            "source": "api_error"
        }
    except (KeyError, ValueError) as e:
        logger.error(f"Response error: {e}")
        return {
            "bad": False,
            "reason": "Parsing error - passed",
            "severity": "low",
            "category": "none",
            "source": "parse_error"
        }



class WarningSystem:
    def __init__(self, filename: str = WARNINGS_FILE):
        self.filename = filename
        self.data = self.load_data()
    
    def load_data(self) -> Dict:
        """Load warnings data with proper initialization"""
        default_data = {
            "users": {},
            "history": [],
            "version": "2.1",
            "created_at": datetime.now().isoformat()
        }
        
        if not os.path.exists(self.filename):
            return default_data
        
        try:
            with open(self.filename, "r", encoding="utf-8") as f:
                data = json.load(f)
            
         
            if "users" not in data:
                data["users"] = {}
            if "history" not in data:
                data["history"] = []
            
            return data
        except json.JSONDecodeError:
            return default_data
        except IOError:
            return default_data
    
    def save_data(self):
        """Save data with error handling"""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.filename)), exist_ok=True)
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except IOError:
            pass
    
    def get_warnings(self, username: str) -> int:
        """Get current warning count for user"""
        if "users" not in self.data:
            self.data["users"] = {}
        
        if username not in self.data["users"]:
            return 0
        
        return self.data["users"][username].get("count", 0)
    
    def add_warning(self, username: str, message: str, moderation_result: Dict) -> int:
        """Add warning with detailed history"""
        if "users" not in self.data:
            self.data["users"] = {}
        if "history" not in self.data:
            self.data["history"] = []
        
       
        if username not in self.data["users"]:
            self.data["users"][username] = {
                "count": 0,
                "first_warning": None,
                "last_warning": None,
                "created_at": datetime.now().isoformat(),
                "appeals": 0
            }
        
        user_data = self.data["users"][username]
        old_count = user_data["count"]
        user_data["count"] += 1
      
        if user_data["count"] > 3:
            user_data["count"] = 3
        
        warning_record = {
            "timestamp": datetime.now().isoformat(),
            "username": username,
            "message": message,
            "warning_number": user_data["count"],
            "previous_warnings": old_count,
            "reason": moderation_result.get("reason", "Unknown"),
            "severity": moderation_result.get("severity", "medium"),
            "category": moderation_result.get("category", "unknown"),
            "source": moderation_result.get("source", "ai")
        }
        
    
        user_data["last_warning"] = warning_record["timestamp"]
        if user_data["count"] == 1:
            user_data["first_warning"] = warning_record["timestamp"]
        
     
        self.data["history"].append(warning_record)
        if len(self.data["history"]) > 1000:
            self.data["history"] = self.data["history"][-1000:]
        
        self.save_data()
        return user_data["count"]
    
    def appeal_warning(self, username: str) -> bool:
        """Allow one warning appeal per user"""
        if "users" not in self.data or username not in self.data["users"]:
            return False
        
        user_data = self.data["users"][username]
        
      
        if user_data.get("appeals", 0) >= 1 or user_data.get("count", 0) == 0:
            return False
        
        # Remove one warning
        if user_data["count"] > 0:
            user_data["count"] -= 1
            user_data["appeals"] = 1
            self.save_data()
            return True
        
        return False
    
    def reset_warnings(self, username: str):
        """Reset warnings for a user"""
        if "users" not in self.data:
            self.data["users"] = {}
        
        if username in self.data["users"]:
            self.data["users"][username]["count"] = 0
            self.data["users"][username]["last_warning"] = None
            self.save_data()
    
    def get_user_stats(self, username: str) -> Dict:
        """Get detailed stats for a user"""
        if "users" not in self.data:
            self.data["users"] = {}
        
        if username not in self.data["users"]:
            return {
                "warnings": 0,
                "history": [],
                "status": "clean",
                "can_appeal": False
            }
        
    
        user_history = []
        if "history" in self.data:
            user_history = [
                record for record in self.data["history"]
                if record["username"] == username
            ]
        
        user_data = self.data["users"][username]
        warnings = user_data.get("count", 0)
        
        return {
            "warnings": warnings,
            "history": user_history[-5:],  # Last 5 warnings
            "first_warning": user_data.get("first_warning"),
            "last_warning": user_data.get("last_warning"),
            "created_at": user_data.get("created_at"),
            "appeals_used": user_data.get("appeals", 0),
            "can_appeal": warnings > 0 and user_data.get("appeals", 0) == 0,
            "status": "banned" if warnings >= 3 else "active"
        }


def display_banner():
    """Display welcome banner"""
    banner = """
╔══════════════════════════════════════════════════════════╗
║                  ADVANCED MODERATION BOT v2.1            ║
║                  Fixed False Positives                   ║
╚══════════════════════════════════════════════════════════╝
"""
    print(banner)

def main():
    if len(sys.argv) < 2:
        print("Usage: python one.py <username>")
        print("Optional: python one.py <username> --reset")
        sys.exit(1)
    
    username = sys.argv[1]
    reset_flag = len(sys.argv) > 2 and sys.argv[2] == "--reset"
    
    warning_system = WarningSystem()
    
    if reset_flag:
        warning_system.reset_warnings(username)
        print(f"✅ Warnings reset for {username}")
        return
    
    display_banner()
    current_warnings = warning_system.get_warnings(username)
    
    print(f" User: {username}")
    print(f"  Current warnings: {current_warnings}/3")
    print(f" Status: {'BANNED' if current_warnings >= 3 else 'ACTIVE'}")
    print("\n" + "="*50)
    print(" Commands: 'exit', 'quit', 'stats', or 'appeal'")
    print("="*50 + "\n")
    
    # Check if already banned
    if current_warnings >= 3:
        stats = warning_system.get_user_stats(username)
        print("⛔ ACCESS DENIED - You are banned!")
        print(f"📝 You have {stats.get('appeals_used', 0)}/1 appeals used")
        if stats.get('can_appeal'):
            print("💡 You can type 'appeal' to request one warning removal")
        else:
            print("📧 Contact admin@example.com to appeal")
        print("\nTo reset, run: python one.py daniel --reset")
        return
    
    while True:
        try:
            msg = input(f"{username}> ").strip()
            
            if not msg:
                continue
                
            if msg.lower() in ["exit", "quit"]:
                print("\n👋 Goodbye!")
                break
            elif msg.lower() == "stats":
                stats = warning_system.get_user_stats(username)
                print(f"\n📊 STATISTICS FOR {username}:")
                print(f"   Warnings: {stats['warnings']}/3")
                print(f"   Status: {stats['status'].upper()}")
                print(f"   Appeals used: {stats['appeals_used']}/1")
                
                if stats['can_appeal'] and stats['warnings'] > 0:
                    print(f"   💡 You can use 'appeal' command to remove 1 warning")
                
                if stats['history']:
                    print(f"\n   Recent Warnings:")
                    for i, record in enumerate(stats['history'], 1):
                        print(f"   {i}. [{record['timestamp'][:19]}]")
                        print(f"      Message: {record['message'][:40]}...")
                        print(f"      Reason: {record['reason']}")
                        print(f"      Source: {record.get('source', 'unknown')}")
                print()
                continue
            elif msg.lower() == "appeal":
                stats = warning_system.get_user_stats(username)
                if stats['can_appeal']:
                    print("\n🤔 Are you sure you want to use your appeal?")
                    print("This will remove 1 warning. (yes/no): ", end="")
                    confirm = input().strip().lower()
                    if confirm in ["yes", "y"]:
                        if warning_system.appeal_warning(username):
                            print("✅ Appeal granted! 1 warning removed.")
                            current_warnings = warning_system.get_warnings(username)
                            print(f"⚠️  Current warnings: {current_warnings}/3")
                        else:
                            print("❌ Could not process appeal.")
                    else:
                        print("Appeal cancelled.")
                else:
                    print("❌ No appeals available or no warnings to appeal.")
                continue
            
            # Perform moderation
            result = moderate_message(msg)
            
            if result.get("bad", False):
                warning_count = warning_system.add_warning(username, msg, result)
                
                reason = result.get("reason", "Inappropriate content")
                severity = result.get("severity", "medium")
                category = result.get("category", "unknown")
                source = result.get("source", "unknown")
                
                print(f"\n{'🔴' if severity == 'high' else '🟠' if severity == 'medium' else '🟡'} WARNING #{warning_count}")
                print(f"   Reason: {reason}")
                print(f"   Source: {source}")
                print(f"   Severity: {severity.upper()}")
                
                if warning_count == 1:
                    print(f"   ⚠️  You now have {3-warning_count} warnings remaining")
                    print(f"   💡 Type 'stats' to see details, 'appeal' to remove a warning")
                elif warning_count == 2:
                    print(f"   ⚠️  FINAL WARNING! Next violation = BAN")
                    print(f"   💡 You can use 'appeal' to remove 1 warning")
                else:
                    print(f"\n⛔ PERMANENT BAN")
                    print(f"   🔒 You have been banned after {warning_count} violations")
                    print(f"   📝 You can appeal once by typing 'appeal'")
                    
                 
                    current_warnings = warning_count
            else:
                print(f"✅ APPROVED")
                if result.get("reason") and result["reason"] != "Clean message":
                    print(f"   Note: {result['reason']}")
            
            # Check ban status after potential warning
            if warning_system.get_warnings(username) >= 3:
                stats = warning_system.get_user_stats(username)
                if not stats.get('can_appeal'):
                    print(f"\n⛔ BAN ACTIVE - No appeals remaining")
                    print(f"📧 Contact admin@example.com")
                    break
                
        except KeyboardInterrupt:
            print("\n\n🛑 Bot stopped by user")
            break
        except Exception as e:
            print(f"⚠️  Error: {str(e)[:50]}")

if __name__ == "__main__":
  
    logging.getLogger().setLevel(logging.ERROR)
    main()