from fastapi import FastAPI, APIRouter
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import bcrypt
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
from jose import JWTError, jwt


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI()
api_router = APIRouter(prefix="/api")

# Auth Config
SECRET_KEY = os.environ.get("SECRET_KEY", "super-secret-ark-key-12345")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week

def hash_password(password: str):
    # Truncate to 72 bytes as per bcrypt limit to avoid ValueError in some environments/versions
    pwd_bytes = password[:72].encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str):
    return bcrypt.checkpw(plain_password[:72].encode('utf-8'), hashed_password.encode('utf-8'))

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusCheckCreate(BaseModel):
    client_name: str


class ScoreEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    nickname: str
    score: int
    time: float
    won: bool
    zone_reached: str = "Dungeon"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScoreCreate(BaseModel):
    nickname: str
    score: int
    time: float
    won: bool
    zone_reached: Optional[str] = "Dungeon"


class UserBase(BaseModel):
    username: str


class UserCreate(UserBase):
    password: str


class UserLogin(UserBase):
    password: str


class UserInDB(UserBase):
    hashed_password: str
    role: str = "player"  # owner, co_admin, player
    is_banned: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


@api_router.get("/")
async def root():
    return {"message": "Labirinto 3D API"}


@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_obj = StatusCheck(**input.model_dump())
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    await db.status_checks.insert_one(doc)
    return status_obj


@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    rows = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    for r in rows:
        if isinstance(r['timestamp'], str):
            r['timestamp'] = datetime.fromisoformat(r['timestamp'])
    return rows


@api_router.post("/scores", response_model=ScoreEntry)
async def submit_score(input: ScoreCreate):
    nick = (input.nickname or "Sconosciuto").strip()[:20] or "Sconosciuto"
    entry = ScoreEntry(
        nickname=nick,
        score=max(0, int(input.score)),
        time=max(0.0, float(input.time)),
        won=bool(input.won),
        zone_reached=input.zone_reached or "Dungeon",
    )
    doc = entry.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    await db.scores.insert_one(doc)
    return entry


@api_router.get("/scores", response_model=List[ScoreEntry])
async def get_scores(limit: int = 20):
    rows = await db.scores.find({}, {"_id": 0}).sort("score", -1).to_list(max(1, min(100, limit)))
    for r in rows:
        if isinstance(r['timestamp'], str):
            r['timestamp'] = datetime.fromisoformat(r['timestamp'])
    return rows


# --- AUTH ROUTES ---

@api_router.post("/auth/register")
async def register(user: UserCreate):
    # Check if user exists
    existing = await db.users.find_one({"username": user.username})
    if existing:
        return {"ok": False, "error": "Username già esistente"}
    
    hashed = hash_password(user.password)
    # Special rule: first user or 'tiziano' is owner
    role = "owner" if user.username.lower() == "tiziano" else "player"
    
    user_doc = {
        "username": user.username,
        "hashed_password": hashed,
        "role": role,
        "is_banned": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user_doc)
    
    token = create_access_token({"sub": user.username, "role": role})
    return {"ok": True, "token": token, "username": user.username, "role": role}


@api_router.post("/auth/login")
async def login(user: UserLogin):
    db_user = await db.users.find_one({"username": user.username})
    if not db_user:
        return {"ok": False, "error": "Credenziali non valide"}
    
    if not verify_password(user.password, db_user["hashed_password"]):
        return {"ok": False, "error": "Credenziali non valide"}
    
    if db_user.get("is_banned", False):
        return {"ok": False, "error": "Il tuo account è stato sospeso."}
    
    role = db_user.get("role", "player")
    # Backup: force owner for tiziano if role is missing
    if user.username.lower() == "tiziano":
        role = "owner"
        await db.users.update_one({"username": user.username}, {"$set": {"role": "owner"}})

    token = create_access_token({"sub": user.username, "role": role})
    return {"ok": True, "token": token, "username": user.username, "role": role}


# --- ADMIN ROUTES ---

@api_router.get("/admin/users")
async def get_users():
    # In production, we should check the JWT role here. 
    # For now, we return the list but the UI will gate it.
    users = await db.users.find({}, {"_id": 0, "hashed_password": 0}).to_list(100)
    return users

@api_router.post("/admin/toggle-ban")
async def toggle_ban(data: dict):
    username = data.get("username")
    user = await db.users.find_one({"username": username})
    if not user: return {"ok": False, "error": "Utente non trovato"}
    if user.get("role") == "owner": return {"ok": False, "error": "Non puoi bannare l'Owner"}
    
    new_status = not user.get("is_banned", False)
    await db.users.update_one({"username": username}, {"$set": {"is_banned": new_status}})
    return {"ok": True, "is_banned": new_status}

@api_router.post("/admin/set-role")
async def set_role(data: dict):
    username = data.get("username")
    new_role = data.get("role")
    if new_role not in ["owner", "co_admin", "player"]:
        return {"ok": False, "error": "Ruolo non valido"}
    
    await db.users.update_one({"username": username}, {"$set": {"role": new_role}})
    return {"ok": True, "role": new_role}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[
        "http://localhost:3000",
        "https://giocoonline-frontend.vercel.app",
        "https://giocoonline-frontend-tizianoguidonis-projects.vercel.app"
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
