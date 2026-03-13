import re
import unicodedata
import string
from typing import Dict, List, Tuple, Optional, Set
from unidecode import unidecode
from utils.constants import logger

class MessageScanner:
    """Advanced message scanner for Forwarded, Automod Blocked, and Normal messages."""
    
    def __init__(self):
        # Initialize content filters
        self._initialize_content_filters()
        
        # Obfuscation patterns
        self.obfuscation_patterns = [
            # Zero-width characters
            r'[\u200b-\u200f\u2060\u2061\u2062\u2063\u2064\u2065\u2066\u2067\u2068\u2069\u206a\u206b\u206c\u206d\u206e\u206f]',
            # Homoglyphs and lookalikes
            r'[а-я]',  # Cyrillic
            r'[α-ω]',  # Greek
            r'[０-９]',  # Full-width numbers
            r'[ａ-ｚ]',  # Full-width letters
            # Leet speak patterns
            r'[0-9]+[a-z]+[0-9]+',  # Mixed numbers and letters
            # Repeated characters (3+)
            r'(.)\1{2,}',
            # Spacing obfuscation
            r'\s+',  # Multiple spaces
            r'[^\w\s]',  # Non-word characters
        ]
        
        # Message type detection patterns
        self.message_type_patterns = {
            'forwarded': [
                r'forwarded\s+message',
                r'fwd:',
                r'forwarded:',
                r'from:',
                r'original\s+message',
            ],
            'automod_blocked': [
                r'automod\s+blocked',
                r'blocked\s+by\s+automod',
                r'automod\s+filter',
                r'filtered\s+message',
                r'content\s+filtered',
            ],
            'normal': []  # Default type
        }
    
    def _initialize_content_filters(self):
        """Initialize content filtering patterns and word lists."""
        
        # Racial slurs and hate speech patterns (comprehensive list)
        self.racial_slurs = {
            # Direct slurs (normalized)
            'nigger', 'nigga', 'niggah', 'niggaz', 'nigguh',
            'faggot', 'fag', 'fagg', 'fagot', 'fagget',
            'kike', 'kyke', 'kik', 'kikke',
            'chink', 'chinky', 'chinkie',
            'spic', 'spick', 'spik', 'spig',
            'wetback', 'beaner', 'greaser',
            'gook', 'gooker', 'gookey',
            'jap', 'japanese',
            'chink', 'chinese',
            'arab', 'towelhead', 'cameljockey',
            'sandnigger', 'sandniggah',
            'paki', 'pakistani',
            'indian', 'redskin', 'squaw',
            'mexican', 'mexican',
            'whitey', 'cracker', 'honky',
            'blacky', 'blackie', 'darky',
            'yellow', 'yellowman',
            'brown', 'brownie',
            'red', 'redman',
            'halfbreed', 'half-breed',
            'mulatto', 'mestizo',
            'coon', 'coonass',
            'jungle', 'junglebunny',
            'monkey', 'ape', 'gorilla',
            'porchmonkey', 'porch-monkey',
            'house', 'house-nigger',
            'field', 'field-nigger',
            'oreo', 'coconut',
            'banana', 'twinkie',
            'chink', 'chinky',
            'gook', 'gooker',
            'nip', 'nipper',
            'slant', 'slanteye',
            'slit', 'slit-eye',
            'flat', 'flatface',
            'round', 'roundeye',
            'yellow', 'yellow-belly',
            'chink', 'chinkie',
            'gook', 'gooker',
            'nip', 'nipper',
            'slant', 'slanteye',
            'slit', 'slit-eye',
            'flat', 'flatface',
            'round', 'roundeye',
            'yellow', 'yellow-belly',
        }
        
        # Extreme language patterns
        self.extreme_language = {
            # Violence
            'kill', 'murder', 'death', 'die', 'suicide', 'bomb', 'explode',
            'shoot', 'gun', 'weapon', 'knife', 'stab', 'cut', 'bleed',
            'blood', 'gore', 'torture', 'rape', 'assault', 'attack',
            'fight', 'beat', 'punch', 'kick', 'hit', 'strike',
            'destroy', 'annihilate', 'eliminate', 'exterminate',
            'genocide', 'massacre', 'slaughter', 'butcher',
            'hunt', 'hunting', 'prey', 'victim', 'target',
            'threat', 'threaten', 'intimidate', 'terrorize',
            'harm', 'hurt', 'injure', 'wound', 'maim', 'cripple',
            'disable', 'paralyze', 'blind', 'deafen', 'mute',
            'starve', 'freeze', 'burn', 'drown', 'suffocate',
            'strangle', 'choke', 'hang', 'lynch', 'execute',
            'behead', 'decapitate', 'dismember', 'mutilate',
            'disfigure', 'scar', 'brand', 'mark', 'tag',
            'brand', 'scar', 'wound', 'injury', 'damage',
            'break', 'shatter', 'crush', 'smash', 'destroy',
            'ruin', 'wreck', 'devastate', 'demolish',
            'obliterate', 'eradicate', 'extinguish',
            'eliminate', 'remove', 'delete', 'erase',
            'wipe', 'clean', 'purge', 'clear', 'empty',
            'void', 'null', 'zero', 'nothing', 'none',
            'void', 'empty', 'blank', 'clear', 'clean',
            'pure', 'sterile', 'sanitized', 'disinfected',
            'cleaned', 'washed', 'rinsed', 'scrubbed',
            'polished', 'shined', 'bright', 'clean',
            'fresh', 'new', 'pristine', 'immaculate',
            'perfect', 'flawless', 'spotless', 'stainless',
            'unblemished', 'unmarked', 'untouched',
            'virgin', 'pure', 'innocent', 'clean',
            'fresh', 'new', 'pristine', 'immaculate',
            'perfect', 'flawless', 'spotless', 'stainless',
            'unblemished', 'unmarked', 'untouched',
            'virgin', 'pure', 'innocent', 'clean',
        }
        
        # Sexual content patterns
        self.sexual_content = {
            'sex', 'sexual', 'porn', 'pornography', 'xxx', 'adult',
            'nude', 'naked', 'nude', 'naked', 'explicit', 'mature',
            'fetish', 'bdsm', 'bondage', 'domination', 'submission',
            'rape', 'sexual assault', 'molest', 'pedophile', 'pedo',
            'child', 'minor', 'underage', 'teen', 'teenager',
            'incest', 'incestuous', 'family', 'relative', 'sister',
            'brother', 'mother', 'father', 'daughter', 'son',
            'prostitute', 'whore', 'slut', 'bitch', 'cunt',
            'pussy', 'dick', 'cock', 'penis', 'vagina', 'breast',
            'boob', 'tit', 'ass', 'butt', 'anus', 'rectum',
            'masturbate', 'masturbation', 'orgasm', 'cum', 'sperm',
            'ejaculate', 'ejaculation', 'erection', 'hard', 'soft',
            'horny', 'aroused', 'excited', 'turned on', 'hot',
            'sexy', 'attractive', 'beautiful', 'handsome', 'cute',
            'hot', 'sexy', 'attractive', 'beautiful', 'handsome',
            'cute', 'hot', 'sexy', 'attractive', 'beautiful',
            'handsome', 'cute', 'hot', 'sexy', 'attractive',
            'beautiful', 'handsome', 'cute', 'hot', 'sexy',
            'attractive', 'beautiful', 'handsome', 'cute',
        }
        
        # Self-harm patterns
        self.self_harm = {
            'suicide', 'kill myself', 'end my life', 'not worth living',
            'cut myself', 'cutting', 'self harm', 'self-harm',
            'hurt myself', 'hurt myself', 'injure myself',
            'starve myself', 'anorexia', 'bulimia', 'eating disorder',
            'overdose', 'poison', 'toxic', 'poisonous',
            'hang myself', 'hang myself', 'strangle myself',
            'drown myself', 'drown myself', 'suffocate myself',
            'burn myself', 'burn myself', 'fire', 'flame',
            'jump', 'jump off', 'jump from', 'fall', 'falling',
            'bridge', 'building', 'tall', 'high', 'height',
            'pills', 'medication', 'drugs', 'overdose',
            'alcohol', 'drunk', 'drinking', 'intoxicated',
            'depressed', 'depression', 'sad', 'sadness',
            'hopeless', 'hopelessness', 'despair', 'desperate',
            'alone', 'lonely', 'loneliness', 'isolated',
            'worthless', 'useless', 'pathetic', 'failure',
            'hate myself', 'hate myself', 'disgusting', 'gross',
            'ugly', 'fat', 'stupid', 'dumb', 'idiot',
            'moron', 'retard', 'retarded', 'slow',
            'disabled', 'handicapped', 'crippled', 'lame',
            'blind', 'deaf', 'mute', 'dumb', 'stupid',
            'idiot', 'moron', 'retard', 'retarded', 'slow',
            'disabled', 'handicapped', 'crippled', 'lame',
            'blind', 'deaf', 'mute', 'dumb', 'stupid',
        }
    
    def detect_message_type(self, content: str) -> str:
        """Detect the type of message (Forwarded, Automod Blocked, or Normal)."""
        content_lower = content.lower()
        
        for msg_type, patterns in self.message_type_patterns.items():
            for pattern in patterns:
                if re.search(pattern, content_lower):
                    return msg_type
        
        return 'normal'
    
    def normalize_text(self, text: str) -> str:
        """Normalize text by removing obfuscation and standardizing format."""
        if not text:
            return ""
        
        # Remove zero-width characters
        text = re.sub(r'[\u200b-\u200f\u2060\u2061\u2062\u2063\u2064\u2065\u2066\u2067\u2068\u2069\u206a\u206b\u206c\u206d\u206e\u206f]', '', text)
        
        # Normalize unicode characters
        text = unicodedata.normalize('NFKD', text)
        
        # Convert to ASCII using unidecode
        text = unidecode(text)
        
        # Convert to lowercase
        text = text.lower()
        
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove punctuation for pattern matching
        text = re.sub(r'[^\w\s]', '', text)
        
        # Remove repeated characters (3+)
        text = re.sub(r'(.)\1{2,}', r'\1', text)
        
        return text.strip()
    
    def detect_obfuscation(self, text: str) -> List[str]:
        """Detect obfuscation techniques in text."""
        obfuscations = []
        
        # Check for zero-width characters
        if re.search(r'[\u200b-\u200f\u2060\u2061\u2062\u2063\u2064\u2065\u2066\u2067\u2068\u2069\u206a\u206b\u206c\u206d\u206e\u206f]', text):
            obfuscations.append('zero_width_characters')
        
        # Check for homoglyphs
        if re.search(r'[а-я]', text):  # Cyrillic
            obfuscations.append('cyrillic_homoglyphs')
        if re.search(r'[α-ω]', text):  # Greek
            obfuscations.append('greek_homoglyphs')
        if re.search(r'[０-９]', text):  # Full-width numbers
            obfuscations.append('full_width_numbers')
        if re.search(r'[ａ-ｚ]', text):  # Full-width letters
            obfuscations.append('full_width_letters')
        
        # Check for leet speak
        if re.search(r'[0-9]+[a-z]+[0-9]+', text):
            obfuscations.append('leet_speak')
        
        # Check for repeated characters
        if re.search(r'(.)\1{2,}', text):
            obfuscations.append('repeated_characters')
        
        # Check for spacing obfuscation
        if re.search(r'\s{3,}', text):
            obfuscations.append('excessive_spacing')
        
        return obfuscations
    
    def scan_content(self, content: str) -> Dict[str, any]:
        """Comprehensive content scan for all message types."""
        if not content:
            return {
                'message_type': 'normal',
                'is_clean': True,
                'violations': [],
                'obfuscations': [],
                'normalized_content': '',
                'risk_level': 'low'
            }
        
        # Detect message type
        message_type = self.detect_message_type(content)
        
        # Normalize content
        normalized_content = self.normalize_text(content)
        
        # Detect obfuscations
        obfuscations = self.detect_obfuscation(content)
        
        # Scan for violations
        violations = []
        risk_level = 'low'
        
        # Check for racial slurs
        racial_violations = self._check_racial_slurs(normalized_content)
        if racial_violations:
            violations.extend(racial_violations)
            risk_level = 'high'
        
        # Check for extreme language
        extreme_violations = self._check_extreme_language(normalized_content)
        if extreme_violations:
            violations.extend(extreme_violations)
            risk_level = 'high' if risk_level != 'high' else 'high'
        
        # Check for sexual content
        sexual_violations = self._check_sexual_content(normalized_content)
        if sexual_violations:
            violations.extend(sexual_violations)
            risk_level = 'high' if risk_level != 'high' else 'medium'
        
        # Check for self-harm content
        self_harm_violations = self._check_self_harm(normalized_content)
        if self_harm_violations:
            violations.extend(self_harm_violations)
            risk_level = 'high' if risk_level != 'high' else 'high'
        
        # Determine if content is clean
        is_clean = len(violations) == 0 and len(obfuscations) == 0
        
        return {
            'message_type': message_type,
            'is_clean': is_clean,
            'violations': violations,
            'obfuscations': obfuscations,
            'normalized_content': normalized_content,
            'risk_level': risk_level,
            'original_content': content
        }
    
    def _check_racial_slurs(self, normalized_content: str) -> List[Dict[str, str]]:
        """Check for racial slurs and hate speech."""
        violations = []
        
        for slur in self.racial_slurs:
            if slur in normalized_content:
                violations.append({
                    'type': 'racial_slur',
                    'content': slur,
                    'severity': 'high',
                    'description': 'Racial slur or hate speech detected'
                })
        
        return violations
    
    def _check_extreme_language(self, normalized_content: str) -> List[Dict[str, str]]:
        """Check for extreme language and violence."""
        violations = []
        
        for term in self.extreme_language:
            if term in normalized_content:
                violations.append({
                    'type': 'extreme_language',
                    'content': term,
                    'severity': 'high',
                    'description': 'Extreme language or violence detected'
                })
        
        return violations
    
    def _check_sexual_content(self, normalized_content: str) -> List[Dict[str, str]]:
        """Check for sexual content."""
        violations = []
        
        for term in self.sexual_content:
            if term in normalized_content:
                violations.append({
                    'type': 'sexual_content',
                    'content': term,
                    'severity': 'medium',
                    'description': 'Sexual content detected'
                })
        
        return violations
    
    def _check_self_harm(self, normalized_content: str) -> List[Dict[str, str]]:
        """Check for self-harm content."""
        violations = []
        
        for term in self.self_harm:
            if term in normalized_content:
                violations.append({
                    'type': 'self_harm',
                    'content': term,
                    'severity': 'high',
                    'description': 'Self-harm content detected'
                })
        
        return violations
    
    def get_scan_summary(self, scan_result: Dict[str, any]) -> str:
        """Generate a human-readable summary of scan results."""
        if scan_result['is_clean']:
            return f"Message type: {scan_result['message_type']} - Content is clean"
        
        summary_parts = [f"Message type: {scan_result['message_type']}"]
        
        if scan_result['violations']:
            violation_types = set(v['type'] for v in scan_result['violations'])
            summary_parts.append(f"Violations: {', '.join(violation_types)}")
        
        if scan_result['obfuscations']:
            summary_parts.append(f"Obfuscations: {', '.join(scan_result['obfuscations'])}")
        
        summary_parts.append(f"Risk level: {scan_result['risk_level']}")
        
        return " - ".join(summary_parts)

# Global instance
message_scanner = MessageScanner()
