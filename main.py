from fastapi import FastAPI, APIRouter
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI()
api_router = APIRouter(prefix="/api")


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


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
