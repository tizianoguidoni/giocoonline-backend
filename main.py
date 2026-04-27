from fastapi import FastAPI, APIRouter, HTTPException, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone, timedelta
import jwt
import bcrypt
import random

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# JWT Config
JWT_SECRET = os.environ.get('JWT_SECRET', 'mythic-arena-secret-key-2024')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_HOURS = 24

# Admin credentials - SUPER ADMIN (can do everything)
SUPER_ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@mythicarena.com')
SUPER_ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'AdminMaster2024!')

app = FastAPI(title="Mythic Arena API v3.0")
api_router = APIRouter(prefix="/api")
security = HTTPBearer()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== MODELS ====================

class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=20)
    email: EmailStr
    password: str = Field(..., min_length=6)

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    username: str
    email: str
    role: str = "player"  # player, co_admin, super_admin
    is_banned: bool = False
    ban_until: Optional[str] = None
    created_at: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class CharacterCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=20)
    race: str = Field(..., pattern="^(human|elf|dwarf|orc)$")
    char_class: str = Field(..., pattern="^(warrior|mage|assassin|healer)$")
    avatar_id: int = Field(..., ge=1, le=12)

class CharacterResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    name: str
    race: str
    char_class: str
    avatar_id: int
    level: int
    xp: int
    hp: int
    max_hp: int
    mana: int
    max_mana: int
    strength: int
    intelligence: int
    agility: int
    defense: int
    reputation: int
    gold: int
    gems: int = 0
    is_admin: bool = False
    role: str = "player"
    equipment: Dict[str, Optional[str]] = {}  # helmet, secondary, sword, shield, backpack
    clan_id: Optional[str] = None
    created_at: str

# Admin Models
class AdminDonateItem(BaseModel):
    target_character_id: str
    item_id: str
    quantity: int = 1

class AdminModifyPlayer(BaseModel):
    gold: Optional[int] = None
    gems: Optional[int] = None
    level: Optional[int] = None
    xp: Optional[int] = None
    hp: Optional[int] = None
    mana: Optional[int] = None
    strength: Optional[int] = None
    intelligence: Optional[int] = None
    agility: Optional[int] = None
    defense: Optional[int] = None
    reputation: Optional[int] = None

class CreateCoAdmin(BaseModel):
    user_id: str

class BanPlayer(BaseModel):
    user_id: str
    days: int = Field(..., ge=1, le=5)  # Co-admin can only ban for max 5 days
    reason: str

class ContestReward(BaseModel):
    character_id: str
    item_id: str
    achievement: str  # Description of what they achieved

class ShopPurchase(BaseModel):
    item_id: str
    quantity: int = 1

class EquipItem(BaseModel):
    item_id: str
    slot: str = Field(..., pattern="^(helmet|secondary|sword|shield|backpack)$")

class MazeWinRequest(BaseModel):
    gold: int = Field(..., ge=0)

class ResetCharacterRequest(BaseModel):
    email: str

class ClanCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=20)
    description: str = Field(..., max_length=100)
    tag: str = Field(..., min_length=2, max_length=5)

class ClanResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    tag: Optional[str] = None
    leader_id: str
    leader_name: str
    members: List[str]
    created_at: str

# ==================== COMPLETE ITEM CATALOG ====================


ITEM_CATALOG = {
    # ========== SWORDS (SPADE) - SHOP AVAILABLE ==========
    "wooden_sword": {"name": "Spada di Legno", "type": "weapon", "subtype": "sword", "slot": "sword", "rarity": "common", "stats": {"strength": 3, "damage": 5}, "price": 10, "shop": True},
    "iron_sword": {"name": "Spada di Ferro", "type": "weapon", "subtype": "sword", "slot": "sword", "rarity": "common", "stats": {"strength": 5, "damage": 10}, "price": 50, "shop": True},
    "steel_sword": {"name": "Spada d'Acciaio", "type": "weapon", "subtype": "sword", "slot": "sword", "rarity": "uncommon", "stats": {"strength": 8, "damage": 18}, "price": 150, "shop": True},
    "silver_blade": {"name": "Lama d'Argento", "type": "weapon", "subtype": "sword", "slot": "sword", "rarity": "rare", "stats": {"strength": 12, "damage": 28, "crit_chance": 5}, "price": 500, "shop": True},
    "flame_sword": {"name": "Spada Infuocata", "type": "weapon", "subtype": "sword", "slot": "sword", "rarity": "rare", "stats": {"strength": 15, "damage": 35, "fire_damage": 10}, "price": 800, "shop": True},
    "dragon_slayer": {"name": "Ammazza Draghi", "type": "weapon", "subtype": "sword", "slot": "sword", "rarity": "epic", "stats": {"strength": 25, "damage": 55, "crit_chance": 10}, "price": 2000, "shop": True},
    "frost_brand": {"name": "Lama Glaciale", "type": "weapon", "subtype": "sword", "slot": "sword", "rarity": "epic", "stats": {"strength": 22, "damage": 48, "ice_damage": 20}, "price": 1800, "shop": True},
    
    # LEGENDARY SWORDS - ADMIN ONLY (NOT IN SHOP)
    "excalibur": {"name": "Excalibur", "type": "weapon", "subtype": "sword", "slot": "sword", "rarity": "legendary", "stats": {"strength": 40, "damage": 85, "crit_chance": 20, "holy_damage": 30, "lifesteal": 10}, "price": 0, "shop": False, "admin_only": True},
    "shadow_blade": {"name": "Lama delle Ombre", "type": "weapon", "subtype": "sword", "slot": "sword", "rarity": "legendary", "stats": {"strength": 35, "damage": 75, "agility": 15, "crit_chance": 25}, "price": 0, "shop": False, "admin_only": True},
    "soul_reaper": {"name": "Mietitore di Anime", "type": "weapon", "subtype": "sword", "slot": "sword", "rarity": "legendary", "stats": {"strength": 38, "damage": 80, "lifesteal": 20, "dark_damage": 25}, "price": 0, "shop": False, "admin_only": True},
    "godslayer": {"name": "Uccisore di Dei", "type": "weapon", "subtype": "sword", "slot": "sword", "rarity": "legendary", "stats": {"strength": 50, "damage": 100, "all_damage": 30}, "price": 0, "shop": False, "admin_only": True},
    
    # ADMIN SWORDS - SUPER ADMIN ONLY
    "admin_excalibur": {"name": "Excalibur del Creatore", "type": "weapon", "subtype": "sword", "slot": "sword", "rarity": "admin", "stats": {"strength": 999, "damage": 9999}, "price": 0, "shop": False, "super_admin_only": True},
    "creator_blade": {"name": "Lama del Creatore", "type": "weapon", "subtype": "sword", "slot": "sword", "rarity": "admin", "stats": {"strength": 999, "damage": 9999, "god_mode": True}, "price": 0, "shop": False, "super_admin_only": True},
    "void_sword": {"name": "Spada del Vuoto", "type": "weapon", "subtype": "sword", "slot": "sword", "rarity": "admin", "stats": {"strength": 999, "damage": 9999}, "price": 0, "shop": False, "super_admin_only": True},
    
    # ========== SECONDARY WEAPONS (COLPO) ==========
    "wooden_dagger": {"name": "Pugnale di Legno", "type": "weapon", "subtype": "secondary", "slot": "secondary", "rarity": "common", "stats": {"agility": 2, "damage": 3}, "price": 8, "shop": True},
    "iron_dagger": {"name": "Pugnale di Ferro", "type": "weapon", "subtype": "secondary", "slot": "secondary", "rarity": "common", "stats": {"agility": 4, "damage": 7}, "price": 40, "shop": True},
    "steel_dagger": {"name": "Pugnale d'Acciaio", "type": "weapon", "subtype": "secondary", "slot": "secondary", "rarity": "uncommon", "stats": {"agility": 7, "damage": 12}, "price": 120, "shop": True},
    "assassin_blade": {"name": "Lama dell'Assassino", "type": "weapon", "subtype": "secondary", "slot": "secondary", "rarity": "rare", "stats": {"agility": 12, "damage": 20, "crit_chance": 15}, "price": 450, "shop": True},
    "shadow_dagger": {"name": "Pugnale Ombra", "type": "weapon", "subtype": "secondary", "slot": "secondary", "rarity": "epic", "stats": {"agility": 18, "damage": 35, "crit_chance": 25, "stealth": 10}, "price": 1500, "shop": True},
    "death_whisper": {"name": "Sussurro della Morte", "type": "weapon", "subtype": "secondary", "slot": "secondary", "rarity": "legendary", "stats": {"agility": 30, "damage": 60, "instant_kill_chance": 5}, "price": 0, "shop": False, "admin_only": True},
    
    # ========== SHIELDS (SCUDI) ==========
    "wooden_shield": {"name": "Scudo di Legno", "type": "armor", "subtype": "shield", "slot": "shield", "rarity": "common", "stats": {"defense": 3, "block": 5}, "price": 15, "shop": True},
    "iron_shield": {"name": "Scudo di Ferro", "type": "armor", "subtype": "shield", "slot": "shield", "rarity": "common", "stats": {"defense": 6, "block": 10}, "price": 60, "shop": True},
    "steel_shield": {"name": "Scudo d'Acciaio", "type": "armor", "subtype": "shield", "slot": "shield", "rarity": "uncommon", "stats": {"defense": 12, "block": 18}, "price": 180, "shop": True},
    "tower_shield": {"name": "Scudo Torre", "type": "armor", "subtype": "shield", "slot": "shield", "rarity": "rare", "stats": {"defense": 20, "block": 30, "hp_bonus": 50}, "price": 600, "shop": True},
    "dragon_shield": {"name": "Scudo del Drago", "type": "armor", "subtype": "shield", "slot": "shield", "rarity": "epic", "stats": {"defense": 35, "block": 45, "fire_resist": 30}, "price": 2000, "shop": True},
    "aegis": {"name": "Egida Divina", "type": "armor", "subtype": "shield", "slot": "shield", "rarity": "legendary", "stats": {"defense": 60, "block": 70, "all_resist": 40, "reflect": 20}, "price": 0, "shop": False, "admin_only": True},
    
    # ========== HELMETS (ELMI) ==========
    "leather_cap": {"name": "Cappuccio di Cuoio", "type": "armor", "subtype": "helmet", "slot": "helmet", "rarity": "common", "stats": {"defense": 2, "hp_bonus": 5}, "price": 12, "shop": True},
    "iron_helmet": {"name": "Elmo di Ferro", "type": "armor", "subtype": "helmet", "slot": "helmet", "rarity": "common", "stats": {"defense": 5, "hp_bonus": 15}, "price": 55, "shop": True},
    "steel_helmet": {"name": "Elmo d'Acciaio", "type": "armor", "subtype": "helmet", "slot": "helmet", "rarity": "uncommon", "stats": {"defense": 10, "hp_bonus": 30}, "price": 160, "shop": True},
    "knight_helmet": {"name": "Elmo del Cavaliere", "type": "armor", "subtype": "helmet", "slot": "helmet", "rarity": "rare", "stats": {"defense": 18, "hp_bonus": 60, "crit_resist": 10}, "price": 550, "shop": True},
    "dragon_helmet": {"name": "Elmo del Drago", "type": "armor", "subtype": "helmet", "slot": "helmet", "rarity": "epic", "stats": {"defense": 28, "hp_bonus": 100, "intimidation": 15}, "price": 1800, "shop": True},
    "crown_of_kings": {"name": "Corona dei Re", "type": "armor", "subtype": "helmet", "slot": "helmet", "rarity": "legendary", "stats": {"defense": 40, "hp_bonus": 200, "all_stats": 15, "leadership": 25}, "price": 0, "shop": False, "admin_only": True},
    "divine_crown": {"name": "Corona Divina", "type": "armor", "subtype": "helmet", "slot": "helmet", "rarity": "legendary", "stats": {"defense": 50, "hp_bonus": 300, "wisdom": 30, "aura": True}, "price": 0, "shop": False, "admin_only": True},
    
    # ========== BODY ARMOR (for reference, not equippable in 4-slot system) ==========
    "cloth_armor": {"name": "Armatura di Stoffa", "type": "armor", "subtype": "body", "rarity": "common", "stats": {"defense": 3, "hp_bonus": 10}, "price": 20, "shop": True},
    "leather_armor": {"name": "Armatura di Cuoio", "type": "armor", "subtype": "body", "rarity": "common", "stats": {"defense": 5, "hp_bonus": 20}, "price": 50, "shop": True},
    "chainmail": {"name": "Cotta di Maglia", "type": "armor", "subtype": "body", "rarity": "uncommon", "stats": {"defense": 10, "hp_bonus": 40}, "price": 200, "shop": True},
    "plate_armor": {"name": "Armatura a Piastre", "type": "armor", "subtype": "body", "rarity": "rare", "stats": {"defense": 18, "hp_bonus": 80}, "price": 600, "shop": True},
    "dragon_scale_armor": {"name": "Armatura Scaglie di Drago", "type": "armor", "subtype": "body", "rarity": "epic", "stats": {"defense": 30, "hp_bonus": 150}, "price": 2500, "shop": True},
    "divine_plate": {"name": "Armatura Divina", "type": "armor", "subtype": "body", "rarity": "legendary", "stats": {"defense": 50, "hp_bonus": 300}, "price": 0, "shop": False, "admin_only": True},
    
    # ========== POTIONS ==========
    "small_health_potion": {"name": "Pozione Vita Piccola", "type": "consumable", "subtype": "potion", "rarity": "common", "stats": {"heal": 30}, "price": 10, "shop": True},
    "medium_health_potion": {"name": "Pozione Vita Media", "type": "consumable", "subtype": "potion", "rarity": "uncommon", "stats": {"heal": 75}, "price": 30, "shop": True},
    "large_health_potion": {"name": "Pozione Vita Grande", "type": "consumable", "subtype": "potion", "rarity": "rare", "stats": {"heal": 150}, "price": 80, "shop": True},
    "small_mana_potion": {"name": "Pozione Mana Piccola", "type": "consumable", "subtype": "potion", "rarity": "common", "stats": {"mana": 20}, "price": 10, "shop": True},
    "medium_mana_potion": {"name": "Pozione Mana Media", "type": "consumable", "subtype": "potion", "rarity": "uncommon", "stats": {"mana": 50}, "price": 30, "shop": True},
    "large_mana_potion": {"name": "Pozione Mana Grande", "type": "consumable", "subtype": "potion", "rarity": "rare", "stats": {"mana": 100}, "price": 80, "shop": True},
    
    # ========== GEMS (GEMME) ==========
    "ruby": {"name": "Rubino", "type": "gem", "subtype": "gem", "rarity": "rare", "stats": {"strength": 5}, "price": 200, "shop": True},
    "sapphire": {"name": "Zaffiro", "type": "gem", "subtype": "gem", "rarity": "rare", "stats": {"intelligence": 5}, "price": 200, "shop": True},
    "emerald": {"name": "Smeraldo", "type": "gem", "subtype": "gem", "rarity": "rare", "stats": {"agility": 5}, "price": 200, "shop": True},
    "diamond": {"name": "Diamante", "type": "gem", "subtype": "gem", "rarity": "epic", "stats": {"all_stats": 3}, "price": 500, "shop": True},
    "legendary_gem": {"name": "Gemma Leggendaria", "type": "gem", "subtype": "gem", "rarity": "legendary", "stats": {"all_stats": 10}, "price": 0, "shop": False, "admin_only": True},
    
    # ========== CRAFTING MATERIALS ==========
    "iron_ore": {"name": "Minerale di Ferro", "type": "material", "subtype": "ore", "rarity": "common", "stats": {}, "price": 5, "shop": True},
    "silver_ore": {"name": "Minerale d'Argento", "type": "material", "subtype": "ore", "rarity": "uncommon", "stats": {}, "price": 15, "shop": True},
    "gold_ore": {"name": "Minerale d'Oro", "type": "material", "subtype": "ore", "rarity": "rare", "stats": {}, "price": 50, "shop": True},
    "mithril_ore": {"name": "Minerale di Mithril", "type": "material", "subtype": "ore", "rarity": "epic", "stats": {}, "price": 200, "shop": True},
    "dragon_scale": {"name": "Scaglia di Drago", "type": "material", "subtype": "drop", "rarity": "epic", "stats": {}, "price": 500, "shop": True},
    "phoenix_feather": {"name": "Piuma di Fenice", "type": "material", "subtype": "drop", "rarity": "legendary", "stats": {}, "price": 0, "shop": False, "admin_only": True},
    
    # ========== BACKPACKS (ZAINI) ==========
    "small_backpack": {"name": "Zaino Piccolo", "type": "armor", "subtype": "backpack", "slot": "backpack", "rarity": "common", "stats": {"defense": 1, "agility": 1}, "price": 30, "shop": True},
    "leather_backpack": {"name": "Zaino di Cuoio", "type": "armor", "subtype": "backpack", "slot": "backpack", "rarity": "uncommon", "stats": {"defense": 3, "agility": 2}, "price": 100, "shop": True},
    "adventurer_backpack": {"name": "Zaino dell'Avventuriero", "type": "armor", "subtype": "backpack", "slot": "backpack", "rarity": "rare", "stats": {"defense": 6, "agility": 5, "hp_bonus": 20}, "price": 400, "shop": True},
    "magical_backpack": {"name": "Zaino Magico", "type": "armor", "subtype": "backpack", "slot": "backpack", "rarity": "epic", "stats": {"defense": 10, "agility": 10, "hp_bonus": 50, "mana_bonus": 50}, "price": 1200, "shop": True},
}

# ========== BOSS CATALOG ==========
BOSS_CATALOG = {
    "goblin_chief": {"name": "Capo Goblin", "type": "normal", "level": 5, "hp": 500, "damage": 15, "defense": 5, "xp": 200, "gold": 100},
    "forest_troll": {"name": "Troll della Foresta", "type": "normal", "level": 10, "hp": 1200, "damage": 30, "defense": 15, "xp": 500, "gold": 250},
    "dark_knight": {"name": "Cavaliere Oscuro", "type": "rare", "level": 20, "hp": 3000, "damage": 60, "defense": 35, "xp": 1500, "gold": 800},
    "ice_queen": {"name": "Regina dei Ghiacci", "type": "rare", "level": 25, "hp": 4000, "damage": 70, "defense": 30, "xp": 2000, "gold": 1000},
    "demon_lord": {"name": "Signore dei Demoni", "type": "epic", "level": 35, "hp": 8000, "damage": 120, "defense": 50, "xp": 5000, "gold": 3000},
    "ancient_dragon": {"name": "Drago Antico", "type": "epic", "level": 40, "hp": 12000, "damage": 150, "defense": 70, "xp": 8000, "gold": 5000},
    "world_titan": {"name": "Titano Primordiale", "type": "world", "level": 50, "hp": 50000, "damage": 200, "defense": 100, "xp": 20000, "gold": 15000, "contest_eligible": True},
    "chaos_god": {"name": "Dio del Caos", "type": "world", "level": 60, "hp": 100000, "damage": 300, "defense": 150, "xp": 50000, "gold": 30000, "contest_eligible": True}
}

# ========== GAME DATA ==========
RACE_STATS = {
    'human': {'strength': 10, 'intelligence': 10, 'agility': 10, 'defense': 10},
    'elf': {'strength': 8, 'intelligence': 14, 'agility': 12, 'defense': 6},
    'dwarf': {'strength': 12, 'intelligence': 6, 'agility': 6, 'defense': 16},
    'orc': {'strength': 16, 'intelligence': 4, 'agility': 8, 'defense': 12}
}

CLASS_STATS = {
    'warrior': {'strength': 5, 'intelligence': 0, 'agility': 2, 'defense': 3, 'hp_bonus': 30, 'mana_bonus': 0},
    'mage': {'strength': 0, 'intelligence': 7, 'agility': 1, 'defense': 2, 'hp_bonus': 0, 'mana_bonus': 50},
    'assassin': {'strength': 3, 'intelligence': 2, 'agility': 7, 'defense': -2, 'hp_bonus': 10, 'mana_bonus': 20},
    'healer': {'strength': 1, 'intelligence': 5, 'agility': 2, 'defense': 2, 'hp_bonus': 20, 'mana_bonus': 30}
}

SKILLS = {
    'warrior': [
        {'id': 'slash', 'name': 'Fendente', 'damage': 20, 'mana_cost': 0},
        {'id': 'shield_bash', 'name': 'Colpo Scudo', 'damage': 15, 'mana_cost': 10, 'stun': 1},
        {'id': 'battle_cry', 'name': 'Grido di Battaglia', 'buff': 'strength', 'amount': 5, 'mana_cost': 15},
        {'id': 'whirlwind', 'name': 'Turbine', 'damage': 35, 'mana_cost': 25}
    ],
    'mage': [
        {'id': 'fireball', 'name': 'Palla di Fuoco', 'damage': 35, 'mana_cost': 20},
        {'id': 'ice_shard', 'name': 'Scheggia di Ghiaccio', 'damage': 25, 'mana_cost': 15},
        {'id': 'arcane_barrier', 'name': 'Barriera Arcana', 'buff': 'defense', 'amount': 10, 'mana_cost': 25},
        {'id': 'meteor', 'name': 'Meteora', 'damage': 80, 'mana_cost': 50}
    ],
    'assassin': [
        {'id': 'backstab', 'name': 'Pugnalata', 'damage': 40, 'mana_cost': 15},
        {'id': 'poison_blade', 'name': 'Lama Avvelenata', 'damage': 15, 'mana_cost': 10, 'dot': 5},
        {'id': 'vanish', 'name': 'Sparizione', 'buff': 'agility', 'amount': 8, 'mana_cost': 20},
        {'id': 'assassinate', 'name': 'Assassinio', 'damage': 100, 'mana_cost': 40}
    ],
    'healer': [
        {'id': 'heal', 'name': 'Cura', 'heal': 30, 'mana_cost': 20},
        {'id': 'smite', 'name': 'Punizione Divina', 'damage': 20, 'mana_cost': 15},
        {'id': 'blessing', 'name': 'Benedizione', 'buff': 'all', 'amount': 3, 'mana_cost': 30},
        {'id': 'resurrection', 'name': 'Resurrezione', 'revive': True, 'mana_cost': 100}
    ]
}

# ==================== AUTH HELPERS ====================

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def create_token(user_id: str, username: str, role: str = "player") -> str:
    payload = {
        'user_id': user_id,
        'username': username,
        'role': role,
        'exp': datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = await db.users.find_one({'id': payload['user_id']}, {'_id': 0, 'password': 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        # Check if banned
        if user.get('is_banned') and user.get('ban_until'):
            ban_until = datetime.fromisoformat(user['ban_until'])
            if datetime.now(timezone.utc) < ban_until:
                raise HTTPException(status_code=403, detail=f"Account banned until {user['ban_until']}")
            else:
                # Unban automatically
                await db.users.update_one({'id': user['id']}, {'$set': {'is_banned': False, 'ban_until': None}})
        
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_super_admin(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    user = await get_current_user(credentials)
    if user.get('role') != 'super_admin':
        raise HTTPException(status_code=403, detail="Super Admin access required")
    return user

async def get_any_admin(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    user = await get_current_user(credentials)
    if user.get('role') not in ['super_admin', 'co_admin']:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

# ==================== ADMIN ACTION LOGGING ====================

async def log_admin_action(admin_id: str, action: str, target_id: str, details: dict):
    log_entry = {
        'id': str(uuid.uuid4()),
        'admin_id': admin_id,
        'action': action,
        'target_id': target_id,
        'details': details,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
    await db.admin_logs.insert_one(log_entry)
    return log_entry

# ==================== AUTH ROUTES ====================

@api_router.post("/auth/register", response_model=TokenResponse)
async def register(data: UserRegister):
    existing = await db.users.find_one({'$or': [{'email': data.email}, {'username': data.username}]})
    if existing:
        if existing.get('email') == data.email:
            raise HTTPException(status_code=400, detail="Email already registered")
        raise HTTPException(status_code=400, detail="Username already taken")
    
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    # Check if this is the super admin
    is_super_admin = data.email == SUPER_ADMIN_EMAIL and data.password == SUPER_ADMIN_PASSWORD
    role = 'super_admin' if is_super_admin else 'player'
    
    user_doc = {
        'id': user_id,
        'username': data.username,
        'email': data.email,
        'password': hash_password(data.password),
        'role': role,
        'is_banned': False,
        'ban_until': None,
        'created_at': now
    }
    
    await db.users.insert_one(user_doc)
    token = create_token(user_id, data.username, role)
    
    return TokenResponse(
        access_token=token,
        user=UserResponse(id=user_id, username=data.username, email=data.email, role=role, is_banned=False, created_at=now)
    )

@api_router.post("/auth/login", response_model=TokenResponse)
async def login(data: UserLogin):
    # Special super admin login
    if data.email == SUPER_ADMIN_EMAIL and data.password == SUPER_ADMIN_PASSWORD:
        user = await db.users.find_one({'email': SUPER_ADMIN_EMAIL}, {'_id': 0})
        if not user:
            user_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            user = {
                'id': user_id,
                'username': 'SuperAdmin',
                'email': SUPER_ADMIN_EMAIL,
                'password': hash_password(SUPER_ADMIN_PASSWORD),
                'role': 'super_admin',
                'is_banned': False,
                'ban_until': None,
                'created_at': now
            }
            await db.users.insert_one(user)
        else:
            # Ensure role is super_admin
            await db.users.update_one({'id': user['id']}, {'$set': {'role': 'super_admin'}})
            user['role'] = 'super_admin'
        
        token = create_token(user['id'], user['username'], 'super_admin')
        return TokenResponse(
            access_token=token,
            user=UserResponse(**{k: v for k, v in user.items() if k != 'password'})
        )
    
    user = await db.users.find_one({'email': data.email}, {'_id': 0})
    if not user or not verify_password(data.password, user['password']):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Check ban
    if user.get('is_banned') and user.get('ban_until'):
        ban_until = datetime.fromisoformat(user['ban_until'])
        if datetime.now(timezone.utc) < ban_until:
            raise HTTPException(status_code=403, detail=f"Account banned until {user['ban_until']}")
    
    # Ensure role is set (for legacy users without role)
    user_role = user.get('role', 'player')
    if 'role' not in user:
        await db.users.update_one({'id': user['id']}, {'$set': {'role': 'player'}})
        user['role'] = 'player'
    
    token = create_token(user['id'], user['username'], user_role)
    
    # Build response ensuring role is included
    user_response = {k: v for k, v in user.items() if k != 'password'}
    user_response['role'] = user_role
    
    return TokenResponse(
        access_token=token,
        user=UserResponse(**user_response)
    )

@api_router.get("/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    return UserResponse(**user)

# ==================== CHARACTER ROUTES ====================

@api_router.post("/characters", response_model=CharacterResponse)
async def create_character(data: CharacterCreate, user: dict = Depends(get_current_user)):
    existing = await db.characters.find_one({'user_id': user['id']})
    if existing:
        raise HTTPException(status_code=400, detail="Character already exists")
    
    name_exists = await db.characters.find_one({'name': data.name})
    if name_exists:
        raise HTTPException(status_code=400, detail="Character name already taken")
    
    race_stats = RACE_STATS[data.race]
    class_stats = CLASS_STATS[data.char_class]
    
    char_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    is_super_admin = user.get('role') == 'super_admin'
    
    # Super admin gets standard multiplier but high base level/gold
    multiplier = 1
    
    character = {
        'id': char_id,
        'user_id': user['id'],
        'name': data.name,
        'race': data.race,
        'char_class': data.char_class,
        'avatar_id': data.avatar_id,
        'level': 99 if is_super_admin else 1,
        'xp': 0,
        'hp': (100 + class_stats['hp_bonus']) * multiplier,
        'max_hp': (100 + class_stats['hp_bonus']) * multiplier,
        'mana': (50 + class_stats['mana_bonus']) * multiplier,
        'max_mana': (50 + class_stats['mana_bonus']) * multiplier,
        'strength': (race_stats['strength'] + class_stats['strength']) * multiplier,
        'intelligence': (race_stats['intelligence'] + class_stats['intelligence']) * multiplier,
        'agility': (race_stats['agility'] + class_stats['agility']) * multiplier,
        'defense': (race_stats['defense'] + class_stats['defense']) * multiplier,
        'reputation': 0,
        'gold': 9999999 if is_super_admin else 100,
        'gems': 99999 if is_super_admin else 0,
        'is_admin': is_super_admin,
        'role': user.get('role', 'player'),
        'equipment': {'helmet': None, 'secondary': None, 'sword': None, 'shield': None, 'backpack': None},
        'clan_id': None,
        'created_at': now
    }
    
    await db.characters.insert_one(character)
    
    # Give starter items
    if is_super_admin:
        # Give all admin items
        admin_items = [k for k, v in ITEM_CATALOG.items() if v.get('super_admin_only')]
        for item_id in admin_items:
            item = ITEM_CATALOG[item_id]
            inv_item = {
                'id': str(uuid.uuid4()),
                'character_id': char_id,
                'item_id': item_id,
                'name': item['name'],
                'item_type': item['type'],
                'subtype': item.get('subtype'),
                'slot': item.get('slot'),
                'rarity': item['rarity'],
                'stats': item['stats'],
                'quantity': 999,  # Unlimited for admin
                'equipped': False
            }
            await db.inventory.insert_one(inv_item)
    else:
        starter_items = [
            {'item_id': 'iron_sword', 'quantity': 1},
            {'item_id': 'wooden_shield', 'quantity': 1},
            {'item_id': 'leather_cap', 'quantity': 1},
            {'item_id': 'wooden_dagger', 'quantity': 1},
            {'item_id': 'small_health_potion', 'quantity': 5},
            {'item_id': 'small_mana_potion', 'quantity': 3}
        ]
        
        for item_data in starter_items:
            base_item = ITEM_CATALOG.get(item_data['item_id'])
            if base_item:
                inv_item = {
                    'id': str(uuid.uuid4()),
                    'character_id': char_id,
                    'item_id': item_data['item_id'],
                    'name': base_item['name'],
                    'item_type': base_item['type'],
                    'subtype': base_item.get('subtype'),
                    'slot': base_item.get('slot'),
                    'rarity': base_item['rarity'],
                    'stats': base_item['stats'],
                    'quantity': item_data['quantity'],
                    'equipped': False
                }
                await db.inventory.insert_one(inv_item)
    
    return CharacterResponse(**character)

@api_router.get("/characters/me", response_model=CharacterResponse)
async def get_my_character(user: dict = Depends(get_current_user)):
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    return CharacterResponse(**character)

# ==================== EQUIPMENT SYSTEM (4 SLOTS) ====================

@api_router.get("/equipment")
async def get_equipment(user: dict = Depends(get_current_user)):
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    equipment = character.get('equipment', {'helmet': None, 'secondary': None, 'sword': None, 'shield': None, 'backpack': None})
    
    # Get item details for equipped items
    equipped_items = {}
    for slot, item_inv_id in equipment.items():
        if item_inv_id:
            item = await db.inventory.find_one({'id': item_inv_id}, {'_id': 0})
            if item:
                equipped_items[slot] = item
            else:
                equipped_items[slot] = None
        else:
            equipped_items[slot] = None
    
    return {
        'slots': ['helmet', 'secondary', 'sword', 'shield', 'backpack'],
        'equipment': equipped_items,
        'character_id': character['id']
    }

@api_router.post("/equipment/equip")
async def equip_item(data: EquipItem, user: dict = Depends(get_current_user)):
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    # Find item in inventory
    item = await db.inventory.find_one({'id': data.item_id, 'character_id': character['id']}, {'_id': 0})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found in inventory")
    
    # Check if item can be equipped in this slot
    item_slot = item.get('slot')
    if item_slot != data.slot:
        raise HTTPException(status_code=400, detail=f"This item cannot be equipped in {data.slot} slot. It belongs in {item_slot} slot.")
    
    # Unequip current item in that slot
    current_equipment = character.get('equipment', {})
    if current_equipment.get(data.slot):
        await db.inventory.update_one(
            {'id': current_equipment[data.slot]},
            {'$set': {'equipped': False}}
        )
    
    # Equip new item
    await db.inventory.update_one({'id': data.item_id}, {'$set': {'equipped': True}})
    
    # Update character equipment
    current_equipment[data.slot] = data.item_id
    await db.characters.update_one(
        {'id': character['id']},
        {'$set': {'equipment': current_equipment}}
    )
    
    return {"message": f"Equipped {item['name']} in {data.slot} slot"}

@api_router.post("/equipment/unequip/{slot}")
async def unequip_item(slot: str, user: dict = Depends(get_current_user)):
    if slot not in ['helmet', 'secondary', 'sword', 'shield']:
        raise HTTPException(status_code=400, detail="Invalid slot")
    
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    current_equipment = character.get('equipment', {})
    if not current_equipment.get(slot):
        raise HTTPException(status_code=400, detail="No item equipped in this slot")
    
    # Unequip item
    await db.inventory.update_one(
        {'id': current_equipment[slot]},
        {'$set': {'equipped': False}}
    )
    
    # Update character equipment
    current_equipment[slot] = None
    await db.characters.update_one(
        {'id': character['id']},
        {'$set': {'equipment': current_equipment}}
    )
    
    return {"message": f"Unequipped item from {slot} slot"}

# ==================== SHOP SYSTEM ====================

@api_router.get("/shop")
async def get_shop_items():
    """Get all items available in shop (excludes legendary and admin items)"""
    shop_items = []
    for item_id, item in ITEM_CATALOG.items():
        if item.get('shop', False) and not item.get('admin_only') and not item.get('super_admin_only'):
            shop_items.append({
                'id': item_id,
                **item
            })
    
    # Sort by type and price
    shop_items.sort(key=lambda x: (x['type'], x['price']))
    return shop_items

@api_router.post("/shop/buy")
async def buy_item(data: ShopPurchase, user: dict = Depends(get_current_user)):
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    item = ITEM_CATALOG.get(data.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    if not item.get('shop', False):
        raise HTTPException(status_code=400, detail="This item is not available in shop")
    
    if item.get('admin_only') or item.get('super_admin_only'):
        raise HTTPException(status_code=400, detail="This item cannot be purchased")
    
    total_cost = item['price'] * data.quantity
    if character['gold'] < total_cost:
        raise HTTPException(status_code=400, detail=f"Not enough gold. Need {total_cost}, have {character['gold']}")
    
    # Deduct gold
    await db.characters.update_one(
        {'id': character['id']},
        {'$inc': {'gold': -total_cost}}
    )
    
    # Add item to inventory
    existing = await db.inventory.find_one({
        'character_id': character['id'],
        'item_id': data.item_id
    }, {'_id': 0})
    
    if existing and item['type'] in ['consumable', 'material', 'gem']:
        # Stack consumables/materials/gems
        await db.inventory.update_one(
            {'id': existing['id']},
            {'$inc': {'quantity': data.quantity}}
        )
    else:
        # Add new item
        for _ in range(data.quantity):
            inv_item = {
                'id': str(uuid.uuid4()),
                'character_id': character['id'],
                'item_id': data.item_id,
                'name': item['name'],
                'item_type': item['type'],
                'subtype': item.get('subtype'),
                'slot': item.get('slot'),
                'rarity': item['rarity'],
                'stats': item['stats'],
                'quantity': 1,
                'equipped': False
            }
            await db.inventory.insert_one(inv_item)
    
    # Log purchase
    await log_admin_action(
        character['id'],
        'shop_purchase',
        character['id'],
        {'item_id': data.item_id, 'quantity': data.quantity, 'total_cost': total_cost}
    )
    
    return {"message": f"Purchased {data.quantity}x {item['name']} for {total_cost} gold"}

# ==================== SUPER ADMIN ROUTES ====================

@api_router.get("/admin/dashboard")
async def admin_dashboard(admin: dict = Depends(get_super_admin)):
    """Get admin dashboard overview"""
    users_count = await db.users.count_documents({})
    characters_count = await db.characters.count_documents({})
    co_admins_count = await db.users.count_documents({'role': 'co_admin'})
    banned_count = await db.users.count_documents({'is_banned': True})
    
    # Recent logs
    recent_logs = await db.admin_logs.find({}, {'_id': 0}).sort('timestamp', -1).limit(20).to_list(20)
    
    # Contest winners
    recent_contests = await db.contest_rewards.find({}, {'_id': 0}).sort('timestamp', -1).limit(10).to_list(10)
    
    return {
        'stats': {
            'total_users': users_count,
            'total_characters': characters_count,
            'co_admins': co_admins_count,
            'banned_users': banned_count
        },
        'recent_logs': recent_logs,
        'recent_contests': recent_contests,
        'admin_email': admin['email'],
        'admin_role': admin['role']
    }

@api_router.get("/admin/users")
async def admin_get_users(
    search: str = Query(None, description="Search by username or email"),
    admin: dict = Depends(get_any_admin)
):
    query = {}
    if search:
        query = {'$or': [
            {'username': {'$regex': search, '$options': 'i'}},
            {'email': {'$regex': search, '$options': 'i'}}
        ]}
    
    users = await db.users.find(query, {'_id': 0, 'password': 0}).to_list(100)
    return users

@api_router.get("/admin/characters")
async def admin_get_characters(
    search: str = Query(None, description="Search by character name"),
    admin: dict = Depends(get_any_admin)
):
    query = {}
    if search:
        query = {'name': {'$regex': search, '$options': 'i'}}
    
    characters = await db.characters.find(query, {'_id': 0}).to_list(100)
    return characters

@api_router.get("/admin/character/{char_id}")
async def admin_get_character(char_id: str, admin: dict = Depends(get_any_admin)):
    character = await db.characters.find_one({'id': char_id}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    # Get inventory
    inventory = await db.inventory.find({'character_id': char_id}, {'_id': 0}).to_list(100)
    
    # Get user info
    user = await db.users.find_one({'id': character['user_id']}, {'_id': 0, 'password': 0})
    
    return {
        'character': character,
        'inventory': inventory,
        'user': user
    }

@api_router.put("/admin/character/{char_id}")
async def admin_modify_character(char_id: str, data: AdminModifyPlayer, admin: dict = Depends(get_super_admin)):
    """Super Admin only: Modify any player's stats"""
    character = await db.characters.find_one({'id': char_id}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    # Update max values if needed
    if 'hp' in update and update['hp'] > character.get('max_hp', 100):
        update['max_hp'] = update['hp']
    if 'mana' in update and update['mana'] > character.get('max_mana', 50):
        update['max_mana'] = update['mana']
    
    await db.characters.update_one({'id': char_id}, {'$set': update})
    
    # Log action
    await log_admin_action(
        admin['id'],
        'modify_character',
        char_id,
        {'changes': update, 'character_name': character['name']}
    )
    
    return {"message": "Character updated", "changes": update}

@api_router.post("/admin/donate")
async def admin_donate_item(data: AdminDonateItem, admin: dict = Depends(get_super_admin)):
    """
    Super Admin: Donate any item to any player WITHOUT losing it from admin inventory.
    Admin has unlimited items.
    """
    target_char = await db.characters.find_one({'id': data.target_character_id}, {'_id': 0})
    if not target_char:
        raise HTTPException(status_code=404, detail="Target character not found")
    
    item = ITEM_CATALOG.get(data.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found in catalog")
    
    # Super admin can donate ANY item including legendaries
    # Check if item already exists in target inventory (for stacking)
    existing = await db.inventory.find_one({
        'character_id': data.target_character_id,
        'item_id': data.item_id
    }, {'_id': 0})
    
    if existing and item['type'] in ['consumable', 'material', 'gem']:
        await db.inventory.update_one(
            {'id': existing['id']},
            {'$inc': {'quantity': data.quantity}}
        )
    else:
        for _ in range(data.quantity):
            inv_item = {
                'id': str(uuid.uuid4()),
                'character_id': data.target_character_id,
                'item_id': data.item_id,
                'name': item['name'],
                'item_type': item['type'],
                'subtype': item.get('subtype'),
                'slot': item.get('slot'),
                'rarity': item['rarity'],
                'stats': item['stats'],
                'quantity': 1,
                'equipped': False
            }
            await db.inventory.insert_one(inv_item)
    
    # Log action
    await log_admin_action(
        admin['id'],
        'donate_item',
        data.target_character_id,
        {
            'item_id': data.item_id,
            'item_name': item['name'],
            'quantity': data.quantity,
            'target_name': target_char['name']
        }
    )
    
    return {"message": f"Donated {data.quantity}x {item['name']} to {target_char['name']}"}

@api_router.get("/admin/items")
async def admin_get_all_items(admin: dict = Depends(get_super_admin)):
    """Get complete item catalog including admin-only items"""
    items = []
    for item_id, item in ITEM_CATALOG.items():
        items.append({
            'id': item_id,
            **item
        })
    return items

# ==================== CO-ADMIN MANAGEMENT ====================

@api_router.post("/admin/co-admin/create")
async def create_co_admin(data: CreateCoAdmin, admin: dict = Depends(get_super_admin)):
    """Super Admin only: Create a co-admin"""
    user = await db.users.find_one({'id': data.user_id}, {'_id': 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.get('role') == 'super_admin':
        raise HTTPException(status_code=400, detail="Cannot modify super admin")
    
    await db.users.update_one({'id': data.user_id}, {'$set': {'role': 'co_admin'}})
    
    # Update character role too
    await db.characters.update_one({'user_id': data.user_id}, {'$set': {'role': 'co_admin'}})
    
    # Log action
    await log_admin_action(
        admin['id'],
        'create_co_admin',
        data.user_id,
        {'username': user['username']}
    )
    
    return {"message": f"User {user['username']} is now a co-admin"}

@api_router.post("/admin/co-admin/remove")
async def remove_co_admin(data: CreateCoAdmin, admin: dict = Depends(get_super_admin)):
    """Super Admin only: Remove co-admin privileges"""
    user = await db.users.find_one({'id': data.user_id}, {'_id': 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    await db.users.update_one({'id': data.user_id}, {'$set': {'role': 'player'}})
    await db.characters.update_one({'user_id': data.user_id}, {'$set': {'role': 'player'}})
    
    await log_admin_action(
        admin['id'],
        'remove_co_admin',
        data.user_id,
        {'username': user['username']}
    )
    
    return {"message": f"Removed co-admin privileges from {user['username']}"}

@api_router.get("/admin/co-admins")
async def get_co_admins(admin: dict = Depends(get_super_admin)):
    """List all co-admins"""
    co_admins = await db.users.find({'role': 'co_admin'}, {'_id': 0, 'password': 0}).to_list(50)
    return co_admins

# ==================== BAN SYSTEM ====================

@api_router.post("/admin/ban")
async def ban_player(data: BanPlayer, admin: dict = Depends(get_any_admin)):
    """
    Ban a player.
    Co-admins can only ban for max 5 days.
    Super admins can ban indefinitely.
    """
    user = await db.users.find_one({'id': data.user_id}, {'_id': 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.get('role') in ['super_admin', 'co_admin']:
        raise HTTPException(status_code=400, detail="Cannot ban admins")
    
    # Co-admin can only ban for max 5 days
    if admin.get('role') == 'co_admin' and data.days > 5:
        raise HTTPException(status_code=403, detail="Co-admins can only ban for maximum 5 days")
    
    ban_until = datetime.now(timezone.utc) + timedelta(days=data.days)
    
    await db.users.update_one(
        {'id': data.user_id},
        {'$set': {'is_banned': True, 'ban_until': ban_until.isoformat(), 'ban_reason': data.reason}}
    )
    
    await log_admin_action(
        admin['id'],
        'ban_player',
        data.user_id,
        {'days': data.days, 'reason': data.reason, 'username': user['username']}
    )
    
    return {"message": f"Banned {user['username']} for {data.days} days. Reason: {data.reason}"}

@api_router.post("/admin/unban/{user_id}")
async def unban_player(user_id: str, admin: dict = Depends(get_any_admin)):
    """Unban a player"""
    user = await db.users.find_one({'id': user_id}, {'_id': 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    await db.users.update_one(
        {'id': user_id},
        {'$set': {'is_banned': False, 'ban_until': None, 'ban_reason': None}}
    )
    
    await log_admin_action(
        admin['id'],
        'unban_player',
        user_id,
        {'username': user['username']}
    )
    
    return {"message": f"Unbanned {user['username']}"}

# ==================== CONTEST SYSTEM ====================

@api_router.get("/admin/contests")
async def get_contests(admin: dict = Depends(get_super_admin)):
    """Get contest-eligible boss achievements"""
    # Get recent boss fights with exceptional performance
    achievements = await db.boss_achievements.find({}, {'_id': 0}).sort('timestamp', -1).limit(50).to_list(50)
    return achievements

@api_router.post("/admin/contest/reward")
async def reward_contest_winner(data: ContestReward, admin: dict = Depends(get_super_admin)):
    """
    Super Admin ONLY: Reward a player with a legendary item for exceptional boss performance.
    Only super admin can donate legendary items.
    """
    character = await db.characters.find_one({'id': data.character_id}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    item = ITEM_CATALOG.get(data.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    # Only legendaries can be given as contest rewards
    if item['rarity'] not in ['legendary', 'admin']:
        raise HTTPException(status_code=400, detail="Contest rewards must be legendary items")
    
    # Add item to player inventory
    inv_item = {
        'id': str(uuid.uuid4()),
        'character_id': data.character_id,
        'item_id': data.item_id,
        'name': item['name'],
        'item_type': item['type'],
        'subtype': item.get('subtype'),
        'slot': item.get('slot'),
        'rarity': item['rarity'],
        'stats': item['stats'],
        'quantity': 1,
        'equipped': False
    }
    await db.inventory.insert_one(inv_item)
    
    # Record contest reward
    contest_record = {
        'id': str(uuid.uuid4()),
        'character_id': data.character_id,
        'character_name': character['name'],
        'item_id': data.item_id,
        'item_name': item['name'],
        'achievement': data.achievement,
        'admin_id': admin['id'],
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
    await db.contest_rewards.insert_one(contest_record)
    
    await log_admin_action(
        admin['id'],
        'contest_reward',
        data.character_id,
        {
            'item_id': data.item_id,
            'item_name': item['name'],
            'achievement': data.achievement,
            'character_name': character['name']
        }
    )
    
    return {"message": f"Awarded {item['name']} to {character['name']} for: {data.achievement}"}

@api_router.get("/admin/contest/rewards")
async def get_contest_rewards(admin: dict = Depends(get_super_admin)):
    """Get history of contest rewards"""
    rewards = await db.contest_rewards.find({}, {'_id': 0}).sort('timestamp', -1).to_list(100)
    return rewards

# ==================== ADMIN LOGS ====================

@api_router.get("/admin/logs")
async def get_admin_logs(
    limit: int = Query(50, le=200),
    action: str = Query(None),
    admin: dict = Depends(get_super_admin)
):
    """Get admin action logs"""
    query = {}
    if action:
        query['action'] = action
    
    logs = await db.admin_logs.find(query, {'_id': 0}).sort('timestamp', -1).limit(limit).to_list(limit)
    return logs

# ==================== BOSS FIGHTS ====================

@api_router.get("/bosses")
async def get_bosses():
    bosses = []
    for boss_id, boss in BOSS_CATALOG.items():
        bosses.append({'id': boss_id, **boss})
    return bosses

@api_router.get("/bosses/{boss_id}")
async def get_boss_details(boss_id: str):
    boss = BOSS_CATALOG.get(boss_id)
    if not boss:
        raise HTTPException(status_code=404, detail="Boss non trovato")
    
    # Add abilities and drops mapping for the UI
    details = {
        'id': boss_id,
        **boss,
        'abilities': [
            "Attacco Pesante", 
            "Furia" if boss['type'] in ['rare', 'epic', 'world'] else "Colpo Rapido",
            "Maledizione" if boss['type'] in ['epic', 'world'] else "Urlo di Battaglia"
        ][:2 if boss['type'] == 'normal' else 3],
        'rewards': {
            'xp': boss['xp'],
            'gold': boss['gold'],
            'drops': ["Pozione Minore", "Frammento"] if boss['type'] == 'normal' else ["Pozione Maggiore", "Cristallo", "Arma Rara"]
        }
    }
    
    if boss['type'] == 'world':
        details['rewards']['drops'] = ["Nucleo del Caos", "Armatura Leggendaria", "Spada Epica"]
        details['abilities'].append("Distruzione Globale")
        
    return details

@api_router.post("/bosses/{boss_id}/fight")
async def fight_boss(boss_id: str, user: dict = Depends(get_current_user)):
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    boss = BOSS_CATALOG.get(boss_id)
    if not boss:
        raise HTTPException(status_code=404, detail="Boss not found")
    
    # Calculate damage
    player_damage = character['strength'] * 2 + random.randint(10, 30)
    boss_damage = boss['damage'] - character['defense'] // 2
    boss_damage = max(5, boss_damage + random.randint(-10, 10))
    
    # Admin deals massive damage
    if character.get('role') == 'super_admin':
        player_damage = boss['hp']
        boss_damage = 0
    
    # Update HP
    new_hp = max(0, character['hp'] - boss_damage)
    await db.characters.update_one({'id': character['id']}, {'$set': {'hp': new_hp}})
    
    # Check victory
    victory = player_damage >= boss['hp']
    
    result = {
        'player_damage': player_damage,
        'boss_damage': boss_damage,
        'player_hp': new_hp,
        'victory': victory,
        'rewards': None
    }
    
    if victory:
        xp = boss['xp']
        gold = boss['gold']
        await db.characters.update_one(
            {'id': character['id']},
            {'$inc': {'xp': xp, 'gold': gold}}
        )
        result['rewards'] = {'xp': xp, 'gold': gold}
        
        # Record achievement if contest-eligible boss
        if boss.get('contest_eligible'):
            achievement = {
                'id': str(uuid.uuid4()),
                'character_id': character['id'],
                'character_name': character['name'],
                'boss_id': boss_id,
                'boss_name': boss['name'],
                'damage_dealt': player_damage,
                'time_taken': random.randint(30, 120),  # Simulated
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            await db.boss_achievements.insert_one(achievement)
    
    return result

# ==================== INVENTORY ====================

@api_router.get("/inventory")
async def get_inventory(user: dict = Depends(get_current_user)):
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    items = await db.inventory.find({'character_id': character['id']}, {'_id': 0}).to_list(500)  # Unlimited for admin
    return items

@api_router.post("/inventory/use/{item_id}")
async def use_item(item_id: str, user: dict = Depends(get_current_user)):
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    item = await db.inventory.find_one({'id': item_id, 'character_id': character['id']}, {'_id': 0})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    if item['item_type'] != 'consumable':
        raise HTTPException(status_code=400, detail="Item is not consumable")
    
    update = {}
    effects = {}
    
    if 'heal' in item['stats']:
        heal = item['stats']['heal']
        new_hp = min(character['max_hp'], character['hp'] + heal)
        update['hp'] = new_hp
        effects['hp_restored'] = heal
    
    if 'mana' in item['stats']:
        mana = item['stats']['mana']
        new_mana = min(character['max_mana'], character['mana'] + mana)
        update['mana'] = new_mana
        effects['mana_restored'] = mana
    
    if update:
        await db.characters.update_one({'id': character['id']}, {'$set': update})
    
    # Super admin doesn't lose items
    if character.get('role') != 'super_admin':
        if item['quantity'] > 1:
            await db.inventory.update_one({'id': item_id}, {'$inc': {'quantity': -1}})
        else:
            await db.inventory.delete_one({'id': item_id})
    
    return {"message": "Item used", "effects": effects}

# ==================== CHAT ====================

@api_router.get("/chat/history")
async def get_chat_history(channel: str = "global", limit: int = 50):
    messages = await db.chat_messages.find({'channel': channel}, {'_id': 0}).sort('timestamp', -1).limit(limit).to_list(limit)
    return list(reversed(messages))

@api_router.post("/chat/send")
async def send_chat_message(content: str, channel: str = "global", user: dict = Depends(get_current_user)):
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    prefix = ""
    if user.get('role') == 'super_admin':
        prefix = "[ADMIN] "
    elif user.get('role') == 'co_admin':
        prefix = "[MOD] "
    
    message = {
        'id': str(uuid.uuid4()),
        'character_id': character['id'],
        'character_name': prefix + character['name'],
        'content': content,
        'channel': channel,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
    await db.chat_messages.insert_one(message)
    return {"message": "Sent"}

@api_router.post("/admin/broadcast")
async def admin_broadcast(message: str, admin: dict = Depends(get_super_admin)):
    """Super Admin: Send system-wide announcement"""
    msg = {
        'id': str(uuid.uuid4()),
        'character_id': 'SYSTEM',
        'character_name': '[SYSTEM]',
        'content': message,
        'channel': 'global',
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
    await db.chat_messages.insert_one(msg)
    
    await log_admin_action(admin['id'], 'broadcast', 'all', {'message': message})
    
    return {"message": "Broadcast sent"}

# ==================== LEADERBOARD ====================

@api_router.get("/leaderboard")
async def get_leaderboard(sort_by: str = "level", limit: int = 50):
    sort_field = sort_by if sort_by in ['level', 'xp', 'reputation', 'gold'] else 'level'
    characters = await db.characters.find({}, {'_id': 0}).sort([(sort_field, -1)]).limit(limit).to_list(limit)
    
    return [{
        'rank': i + 1,
        'character_id': c['id'],
        'character_name': c['name'],
        'level': c['level'],
        'xp': c['xp'],
        'reputation': c['reputation'],
        'gold': c.get('gold', 0),
        'role': c.get('role', 'player')
    } for i, c in enumerate(characters)]

# ==================== GAME DATA ====================

@api_router.get("/game/races")
async def get_races():
    return [
        {'id': 'human', 'name': 'Umano', 'description': 'Versatile e bilanciato', 'stats': RACE_STATS['human']},
        {'id': 'elf', 'name': 'Elfo', 'description': 'Aggraziato e intelligente', 'stats': RACE_STATS['elf']},
        {'id': 'dwarf', 'name': 'Nano', 'description': 'Robusto e resistente', 'stats': RACE_STATS['dwarf']},
        {'id': 'orc', 'name': 'Orco', 'description': 'Potente e feroce', 'stats': RACE_STATS['orc']}
    ]

@api_router.get("/game/classes")
async def get_classes():
    return [
        {'id': 'warrior', 'name': 'Guerriero', 'description': 'Maestro di armi e armature', 'stats': CLASS_STATS['warrior'], 'skills': SKILLS['warrior']},
        {'id': 'mage', 'name': 'Mago', 'description': 'Utilizzatore di magia arcana', 'stats': CLASS_STATS['mage'], 'skills': SKILLS['mage']},
        {'id': 'assassin', 'name': 'Assassino', 'description': 'Rapido e letale', 'stats': CLASS_STATS['assassin'], 'skills': SKILLS['assassin']},
        {'id': 'healer', 'name': 'Guaritore', 'description': 'Protettore divino', 'stats': CLASS_STATS['healer'], 'skills': SKILLS['healer']}
    ]

@api_router.get("/combat/skills")
async def get_skills(user: dict = Depends(get_current_user)):
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    return SKILLS.get(character['char_class'], [])

# ==================== COMBAT SYSTEM ====================

ENEMIES = [
    {"id": "slime", "name": "Slime", "hp": 30, "damage": 5, "defense": 2, "xp": 15, "gold": 5, "min_level": 1},
    {"id": "goblin", "name": "Goblin", "hp": 50, "damage": 10, "defense": 5, "xp": 30, "gold": 12, "min_level": 1},
    {"id": "wolf", "name": "Lupo Selvaggio", "hp": 80, "damage": 15, "defense": 8, "xp": 50, "gold": 20, "min_level": 3},
    {"id": "skeleton", "name": "Scheletro", "hp": 100, "damage": 20, "defense": 10, "xp": 80, "gold": 35, "min_level": 5},
    {"id": "orc_warrior", "name": "Guerriero Orco", "hp": 150, "damage": 30, "defense": 15, "xp": 120, "gold": 50, "min_level": 8},
    {"id": "bandit", "name": "Bandito", "hp": 120, "damage": 25, "defense": 12, "xp": 100, "gold": 60, "min_level": 6},
    {"id": "dark_mage", "name": "Mago Oscuro", "hp": 90, "damage": 40, "defense": 5, "xp": 150, "gold": 80, "min_level": 10},
    {"id": "stone_golem", "name": "Golem di Pietra", "hp": 300, "damage": 35, "defense": 40, "xp": 200, "gold": 100, "min_level": 12},
    {"id": "vampire", "name": "Vampiro", "hp": 180, "damage": 45, "defense": 20, "xp": 250, "gold": 120, "min_level": 15},
    {"id": "demon", "name": "Demone", "hp": 250, "damage": 60, "defense": 30, "xp": 400, "gold": 200, "min_level": 20},
]

@api_router.get("/combat/enemies")
async def get_enemies(user: dict = Depends(get_current_user)):
    """Get available enemies to fight based on player level"""
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    player_level = character.get('level', 1)
    available = [e for e in ENEMIES if e['min_level'] <= player_level]
    return available

@api_router.post("/combat/attack/{enemy_id}")
async def attack_enemy(enemy_id: str, user: dict = Depends(get_current_user)):
    """Attack an enemy and get rewards"""
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    enemy = next((e for e in ENEMIES if e['id'] == enemy_id), None)
    if not enemy:
        raise HTTPException(status_code=404, detail="Enemy not found")
    
    # Check player level
    if character.get('level', 1) < enemy['min_level']:
        raise HTTPException(status_code=400, detail=f"Requires level {enemy['min_level']}")
    
    # Calculate damage
    player_strength = character.get('strength', 10)
    player_damage = player_strength * 2 + random.randint(5, 20)
    
    enemy_damage = enemy['damage'] - character.get('defense', 5) // 2
    enemy_damage = max(5, enemy_damage + random.randint(-5, 10))
    
    # Admin one-shots
    if character.get('is_admin') or character.get('role') == 'super_admin':
        player_damage = enemy['hp'] * 2
        enemy_damage = 0
    
    # Calculate result
    victory = player_damage >= enemy['hp']
    
    # Update player HP
    new_hp = max(0, character['hp'] - enemy_damage)
    updates = {'hp': new_hp}
    
    xp_gained = 0
    gold_gained = 0
    level_up = False
    
    if victory:
        xp_gained = enemy['xp']
        gold_gained = enemy['gold'] + random.randint(0, enemy['gold'] // 2)
        
        new_xp = character.get('xp', 0) + xp_gained
        new_gold = character.get('gold', 0) + gold_gained
        new_level = character.get('level', 1)
        
        # Level up check (100 XP per level)
        xp_for_next = new_level * 100
        if new_xp >= xp_for_next:
            new_level += 1
            new_xp -= xp_for_next
            level_up = True
            # Increase stats on level up
            updates['strength'] = character.get('strength', 10) + 2
            updates['intelligence'] = character.get('intelligence', 10) + 2
            updates['agility'] = character.get('agility', 10) + 1
            updates['defense'] = character.get('defense', 10) + 1
            updates['max_hp'] = character.get('max_hp', 100) + 10
            updates['max_mana'] = character.get('max_mana', 50) + 5
        
        updates['xp'] = new_xp
        updates['gold'] = new_gold
        updates['level'] = new_level
    
    await db.characters.update_one({'id': character['id']}, {'$set': updates})
    
    return {
        'victory': victory,
        'player_damage': player_damage,
        'enemy_damage': enemy_damage,
        'enemy_name': enemy['name'],
        'new_hp': new_hp,
        'xp_gained': xp_gained,
        'gold_gained': gold_gained,
        'level_up': level_up,
        'new_level': updates.get('level', character['level'])
    }

# ==================== QUESTS SYSTEM ====================

QUESTS = [
    {
        "id": "first_blood",
        "name": "Primo Sangue",
        "description": "Sconfiggi 3 Slime per dimostrare il tuo valore",
        "type": "combat",
        "target": "slime",
        "required": 3,
        "reward_xp": 100,
        "reward_gold": 50,
        "reward_item": None,
        "min_level": 1
    },
    {
        "id": "goblin_hunter",
        "name": "Cacciatore di Goblin",
        "description": "Elimina 5 Goblin che infestano le foreste",
        "type": "combat",
        "target": "goblin",
        "required": 5,
        "reward_xp": 200,
        "reward_gold": 100,
        "reward_item": "iron_sword",
        "min_level": 2
    },
    {
        "id": "wolf_pack",
        "name": "Branco di Lupi",
        "description": "Sconfiggi 5 Lupi Selvaggi",
        "type": "combat",
        "target": "wolf",
        "required": 5,
        "reward_xp": 300,
        "reward_gold": 150,
        "reward_item": "leather_armor",
        "min_level": 3
    },
    {
        "id": "skeleton_army",
        "name": "Esercito di Non-Morti",
        "description": "Distruggi 10 Scheletri nel dungeon",
        "type": "combat",
        "target": "skeleton",
        "required": 10,
        "reward_xp": 600,
        "reward_gold": 300,
        "reward_item": "steel_sword",
        "min_level": 5
    },
    {
        "id": "orc_slayer",
        "name": "Sterminatore di Orchi",
        "description": "Elimina 8 Guerrieri Orchi",
        "type": "combat",
        "target": "orc_warrior",
        "required": 8,
        "reward_xp": 800,
        "reward_gold": 400,
        "reward_item": "steel_helmet",
        "min_level": 8
    },
    {
        "id": "treasure_hunter",
        "name": "Cacciatore di Tesori",
        "description": "Accumula 1000 monete d'oro",
        "type": "collect",
        "target": "gold",
        "required": 1000,
        "reward_xp": 500,
        "reward_gold": 0,
        "reward_item": "ruby",
        "min_level": 5
    },
    {
        "id": "demon_hunter",
        "name": "Cacciatore di Demoni",
        "description": "Sconfiggi 5 Demoni",
        "type": "combat",
        "target": "demon",
        "required": 5,
        "reward_xp": 2000,
        "reward_gold": 1000,
        "reward_item": "flame_sword",
        "min_level": 20
    },
    {
        "id": "vampire_slayer",
        "name": "Uccisore di Vampiri",
        "description": "Elimina 7 Vampiri",
        "type": "combat",
        "target": "vampire",
        "required": 7,
        "reward_xp": 1500,
        "reward_gold": 700,
        "reward_item": "silver_blade",
        "min_level": 15
    }
]

@api_router.get("/quests")
async def get_quests(user: dict = Depends(get_current_user)):
    """Get available quests"""
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    player_level = character.get('level', 1)
    
    # Get player's quest progress
    progress = await db.quest_progress.find({'character_id': character['id']}, {'_id': 0}).to_list(100)
    progress_map = {p['quest_id']: p for p in progress}
    
    result = []
    for quest in QUESTS:
        if quest['min_level'] <= player_level:
            quest_data = {**quest}
            prog = progress_map.get(quest['id'])
            if prog:
                quest_data['progress'] = prog.get('progress', 0)
                quest_data['completed'] = prog.get('completed', False)
                quest_data['claimed'] = prog.get('claimed', False)
            else:
                quest_data['progress'] = 0
                quest_data['completed'] = False
                quest_data['claimed'] = False
            
            # Add reward item name
            if quest['reward_item'] and quest['reward_item'] in ITEM_CATALOG:
                quest_data['reward_item_name'] = ITEM_CATALOG[quest['reward_item']]['name']
            
            result.append(quest_data)
    
    return result

@api_router.post("/quests/{quest_id}/claim")
async def claim_quest(quest_id: str, user: dict = Depends(get_current_user)):
    """Claim quest rewards"""
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    quest = next((q for q in QUESTS if q['id'] == quest_id), None)
    if not quest:
        raise HTTPException(status_code=404, detail="Quest not found")
    
    progress = await db.quest_progress.find_one({
        'character_id': character['id'],
        'quest_id': quest_id
    }, {'_id': 0})
    
    if not progress or not progress.get('completed'):
        raise HTTPException(status_code=400, detail="Quest not completed")
    
    if progress.get('claimed'):
        raise HTTPException(status_code=400, detail="Quest already claimed")
    
    # Give rewards
    updates = {
        'xp': character.get('xp', 0) + quest['reward_xp'],
        'gold': character.get('gold', 0) + quest['reward_gold']
    }
    
    await db.characters.update_one({'id': character['id']}, {'$set': updates})
    
    # Mark as claimed
    await db.quest_progress.update_one(
        {'character_id': character['id'], 'quest_id': quest_id},
        {'$set': {'claimed': True}}
    )
    
    # Give item reward
    item_given = None
    if quest['reward_item']:
        item = ITEM_CATALOG.get(quest['reward_item'])
        if item:
            inv_item = {
                'id': str(uuid.uuid4()),
                'character_id': character['id'],
                'item_id': quest['reward_item'],
                'name': item['name'],
                'item_type': item['type'],
                'rarity': item['rarity'],
                'stats': item.get('stats', {}),
                'slot': item.get('slot'),
                'quantity': 1,
                'equipped': False,
                'acquired_at': datetime.now(timezone.utc).isoformat()
            }
            await db.inventory.insert_one(inv_item)
            item_given = item['name']
    
    return {
        'message': f"Quest '{quest['name']}' completed!",
        'xp_gained': quest['reward_xp'],
        'gold_gained': quest['reward_gold'],
        'item_given': item_given
    }

# ==================== CRAFTING SYSTEM ====================

CRAFTING_RECIPES = [
    {
        "id": "iron_sword_craft",
        "name": "Forgia Spada di Ferro",
        "result_item": "iron_sword",
        "materials": [{"item_id": "iron_ore", "quantity": 3}],
        "gold_cost": 20,
        "min_level": 1,
        "success_rate": 100
    },
    {
        "id": "steel_sword_craft",
        "name": "Forgia Spada d'Acciaio",
        "result_item": "steel_sword",
        "materials": [{"item_id": "iron_ore", "quantity": 5}, {"item_id": "silver_ore", "quantity": 2}],
        "gold_cost": 100,
        "min_level": 5,
        "success_rate": 90
    },
    {
        "id": "iron_helmet_craft",
        "name": "Forgia Elmo di Ferro",
        "result_item": "iron_helmet",
        "materials": [{"item_id": "iron_ore", "quantity": 2}],
        "gold_cost": 30,
        "min_level": 2,
        "success_rate": 100
    },
    {
        "id": "steel_helmet_craft",
        "name": "Forgia Elmo d'Acciaio",
        "result_item": "steel_helmet",
        "materials": [{"item_id": "iron_ore", "quantity": 4}, {"item_id": "silver_ore", "quantity": 1}],
        "gold_cost": 80,
        "min_level": 5,
        "success_rate": 90
    },
    {
        "id": "iron_shield_craft",
        "name": "Forgia Scudo di Ferro",
        "result_item": "iron_shield",
        "materials": [{"item_id": "iron_ore", "quantity": 3}],
        "gold_cost": 35,
        "min_level": 2,
        "success_rate": 100
    },
    {
        "id": "steel_shield_craft",
        "name": "Forgia Scudo d'Acciaio",
        "result_item": "steel_shield",
        "materials": [{"item_id": "iron_ore", "quantity": 5}, {"item_id": "silver_ore", "quantity": 2}],
        "gold_cost": 100,
        "min_level": 5,
        "success_rate": 90
    },
    {
        "id": "silver_blade_craft",
        "name": "Forgia Lama d'Argento",
        "result_item": "silver_blade",
        "materials": [{"item_id": "silver_ore", "quantity": 5}, {"item_id": "gold_ore", "quantity": 2}],
        "gold_cost": 300,
        "min_level": 10,
        "success_rate": 80
    },
    {
        "id": "dragon_sword_craft",
        "name": "Forgia Ammazza Draghi",
        "result_item": "dragon_slayer",
        "materials": [{"item_id": "mithril_ore", "quantity": 5}, {"item_id": "dragon_scale", "quantity": 3}],
        "gold_cost": 1000,
        "min_level": 20,
        "success_rate": 60
    },
    {
        "id": "dragon_helmet_craft",
        "name": "Forgia Elmo del Drago",
        "result_item": "dragon_helmet",
        "materials": [{"item_id": "mithril_ore", "quantity": 3}, {"item_id": "dragon_scale", "quantity": 2}],
        "gold_cost": 800,
        "min_level": 18,
        "success_rate": 65
    },
    {
        "id": "dragon_shield_craft",
        "name": "Forgia Scudo del Drago",
        "result_item": "dragon_shield",
        "materials": [{"item_id": "mithril_ore", "quantity": 4}, {"item_id": "dragon_scale", "quantity": 3}],
        "gold_cost": 1200,
        "min_level": 20,
        "success_rate": 55
    }
]

@api_router.get("/crafting/recipes")
async def get_crafting_recipes(user: dict = Depends(get_current_user)):
    """Get available crafting recipes"""
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    player_level = character.get('level', 1)
    
    result = []
    for recipe in CRAFTING_RECIPES:
        if recipe['min_level'] <= player_level:
            recipe_data = {**recipe}
            
            # Add result item info
            result_item = ITEM_CATALOG.get(recipe['result_item'])
            if result_item:
                recipe_data['result_name'] = result_item['name']
                recipe_data['result_rarity'] = result_item['rarity']
                recipe_data['result_stats'] = result_item.get('stats', {})
            
            # Add material names
            materials_info = []
            for mat in recipe['materials']:
                mat_item = ITEM_CATALOG.get(mat['item_id'])
                materials_info.append({
                    'item_id': mat['item_id'],
                    'name': mat_item['name'] if mat_item else mat['item_id'],
                    'quantity': mat['quantity']
                })
            recipe_data['materials_info'] = materials_info
            
            result.append(recipe_data)
    
    return result

@api_router.post("/crafting/craft/{recipe_id}")
async def craft_item(recipe_id: str, user: dict = Depends(get_current_user)):
    """Craft an item"""
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    recipe = next((r for r in CRAFTING_RECIPES if r['id'] == recipe_id), None)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    
    if character.get('level', 1) < recipe['min_level']:
        raise HTTPException(status_code=400, detail=f"Requires level {recipe['min_level']}")
    
    if character.get('gold', 0) < recipe['gold_cost']:
        raise HTTPException(status_code=400, detail="Not enough gold")
    
    # Check materials
    inventory = await db.inventory.find({'character_id': character['id']}, {'_id': 0}).to_list(1000)
    inv_map = {}
    for item in inventory:
        item_id = item.get('item_id', item.get('id'))
        inv_map[item_id] = inv_map.get(item_id, 0) + item.get('quantity', 1)
    
    for mat in recipe['materials']:
        if inv_map.get(mat['item_id'], 0) < mat['quantity']:
            mat_item = ITEM_CATALOG.get(mat['item_id'])
            mat_name = mat_item['name'] if mat_item else mat['item_id']
            raise HTTPException(status_code=400, detail=f"Not enough {mat_name}")
    
    # Consume materials
    for mat in recipe['materials']:
        remaining = mat['quantity']
        async for inv_item in db.inventory.find({'character_id': character['id'], 'item_id': mat['item_id']}):
            if remaining <= 0:
                break
            qty = inv_item.get('quantity', 1)
            if qty <= remaining:
                await db.inventory.delete_one({'_id': inv_item['_id']})
                remaining -= qty
            else:
                await db.inventory.update_one({'_id': inv_item['_id']}, {'$inc': {'quantity': -remaining}})
                remaining = 0
    
    # Deduct gold
    await db.characters.update_one({'id': character['id']}, {'$inc': {'gold': -recipe['gold_cost']}})
    
    # Check success
    success = random.randint(1, 100) <= recipe['success_rate']
    
    if success:
        result_item = ITEM_CATALOG.get(recipe['result_item'])
        if result_item:
            inv_item = {
                'id': str(uuid.uuid4()),
                'character_id': character['id'],
                'item_id': recipe['result_item'],
                'name': result_item['name'],
                'item_type': result_item['type'],
                'rarity': result_item['rarity'],
                'stats': result_item.get('stats', {}),
                'slot': result_item.get('slot'),
                'quantity': 1,
                'equipped': False,
                'acquired_at': datetime.now(timezone.utc).isoformat()
            }
            await db.inventory.insert_one(inv_item)
            
            return {
                'success': True,
                'message': f"Successfully crafted {result_item['name']}!",
                'item_name': result_item['name'],
                'item_rarity': result_item['rarity']
            }
    
    return {
        'success': False,
        'message': "Crafting failed! Materials were consumed.",
        'item_name': None
    }

@api_router.post("/combat/maze-win")
async def maze_win(data: MazeWinRequest, user: dict = Depends(get_current_user)):
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
        
    # Applica il gold accumulato nel run del labirinto
    # In futuro qui potremo salvare anche eventuali XP e oggetti raccolti nel labirinto.
    await db.characters.update_one(
        {'id': character['id']},
        {'$inc': {'gold': data.gold}}
    )
    
    return {"message": f"Successfully banked {data.gold} gold", "gold_gained": data.gold}

@api_router.post("/admin/reset-character")
async def admin_reset_character(data: ResetCharacterRequest, user: dict = Depends(get_current_user)):
    if user.get('role') not in ['super_admin', 'co_admin', 'owner']:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    target_user = await db.users.find_one({'email': data.email})
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Reset character to base stats
    await db.characters.update_one(
        {'user_id': target_user['id']},
        {
            '$set': {
                'level': 1,
                'xp': 0,
                'reputation': 50,
                'gold': 500,
                'strength': 10,
                'intelligence': 10,
                'agility': 10,
                'defense': 10,
                'hp': 100,
                'max_hp': 100,
                'mana': 100,
                'max_mana': 100,
                'stat_points': 5,
                'is_super_admin_stats': False if target_user['role'] != 'super_admin' else True
            }
        }
    )
    
    return {"message": f"Character for {data.email} has been reset to level 1"}


# ==================== CLAN SYSTEM ====================

@api_router.get("/clans", response_model=List[ClanResponse])
async def get_clans():
    clans = await db.clans.find({}, {'_id': 0}).to_list(100)
    return clans

@api_router.post("/clans", response_model=ClanResponse)
async def create_clan(data: ClanCreate, user: dict = Depends(get_current_user)):
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    if character.get('clan_id'):
        raise HTTPException(status_code=400, detail="Character already in a clan")
    
    clan_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    clan = {
        'id': clan_id,
        'name': data.name,
        'description': data.description,
        'tag': data.tag,
        'leader_id': character['id'],
        'leader_name': character['name'],
        'members': [character['id']],
        'created_at': now
    }
    
    await db.clans.insert_one(clan)
    await db.characters.update_one({'id': character['id']}, {'$set': {'clan_id': clan_id}})
    
    return ClanResponse(**clan)

@api_router.get("/clans/{clan_id}", response_model=ClanResponse)
async def get_clan(clan_id: str):
    clan = await db.clans.find_one({'id': clan_id}, {'_id': 0})
    if not clan:
        raise HTTPException(status_code=404, detail="Clan not found")
    return ClanResponse(**clan)

@api_router.post("/clans/{clan_id}/join")
async def join_clan(clan_id: str, user: dict = Depends(get_current_user)):
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    if character.get('clan_id'):
        raise HTTPException(status_code=400, detail="Character already in a clan")
    
    clan = await db.clans.find_one({'id': clan_id})
    if not clan:
        raise HTTPException(status_code=404, detail="Clan not found")
    
    await db.clans.update_one({'id': clan_id}, {'$push': {'members': character['id']}})
    await db.characters.update_one({'id': character['id']}, {'$set': {'clan_id': clan_id}})
    
    return {"message": f"Joined clan {clan['name']}"}

@api_router.post("/clans/leave")
async def leave_clan(user: dict = Depends(get_current_user)):
    character = await db.characters.find_one({'user_id': user['id']}, {'_id': 0})
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    clan_id = character.get('clan_id')
    if not clan_id:
        raise HTTPException(status_code=400, detail="Character not in a clan")
    
    clan = await db.clans.find_one({'id': clan_id})
    if not clan:
        await db.characters.update_one({'id': character['id']}, {'$set': {'clan_id': None}})
        return {"message": "Left clan (clan data was missing)"}
    
    if clan['leader_id'] == character['id']:
        # Disband if leader leaves
        await db.clans.delete_one({'id': clan_id})
        await db.characters.update_many({'clan_id': clan_id}, {'$set': {'clan_id': None}})
        return {"message": "Clan disbanded as leader left"}
    else:
        await db.clans.update_one({'id': clan_id}, {'$pull': {'members': character['id']}})
        await db.characters.update_one({'id': character['id']}, {'$set': {'clan_id': None}})
        return {"message": "Left clan"}

@api_router.get("/")
async def root():
    return {
        "message": "Mythic Arena API",
        "version": "3.0.0",
        "features": ["Super Admin", "Co-Admin", "Shop", "Contest", "Equipment Slots", "Admin Logs"],
        "admin_email": SUPER_ADMIN_EMAIL
    }

# Include router

@api_router.post("/admin/toggle-ban")
async def admin_toggle_ban(data: dict, user: dict = Depends(get_current_user)):
    if user.get('role') not in ['super_admin', 'co_admin', 'owner']:
        raise HTTPException(status_code=403, detail="Not authorized")
    username = data.get('username')
    target_user = await db.users.find_one({'username': username})
    if not target_user: raise HTTPException(status_code=404, detail="User not found")
    new_state = not target_user.get('is_banned', False)
    await db.users.update_one({'username': username}, {'$set': {'is_banned': new_state}})
    return {"message": f"User {username} ban state: {new_state}"}

@api_router.post("/admin/set-role")
async def admin_set_role(data: dict, user: dict = Depends(get_current_user)):
    if user.get('role') != 'owner' and user.get('role') != 'super_admin':
        raise HTTPException(status_code=403, detail="Only Owners can change roles")
    username = data.get('username')
    new_role = data.get('role')
    await db.users.update_one({'username': username}, {'$set': {'role': new_role}})
    return {"message": f"User {username} role: {new_role}"}

@api_router.post("/admin/give-gold")
async def admin_give_gold(data: dict, user: dict = Depends(get_current_user)):
    if user.get('role') not in ['super_admin', 'owner']:
        raise HTTPException(status_code=403, detail="Not authorized")
    username = data.get('username')
    amount = data.get('amount', 0)
    target_user = await db.users.find_one({'username': username})
    if not target_user: raise HTTPException(status_code=404, detail="User not found")
    await db.characters.update_one({'user_id': target_user['id']}, {'$inc': {'gold': amount}})
    return {"message": f"Gave {amount} gold to {username}"}
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
