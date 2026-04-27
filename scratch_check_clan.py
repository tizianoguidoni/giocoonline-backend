import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

async def check_clan():
    load_dotenv()
    url = os.environ.get('MONGO_URL')
    db_name = os.environ.get('DB_NAME')
    clan_id = "8f65e497-8d6e-48d3-95a1-ce77c9d75108"
    
    client = AsyncIOMotorClient(url)
    db = client[db_name]
    
    clan = await db.clans.find_one({'id': clan_id})
    print(f"Clan {clan_id}: {'Found' if clan else 'Not Found'}")
    if clan:
        print(f"Clan Details: {clan}")
    
    char = await db.characters.find_one({'clan_id': clan_id})
    if char:
        print(f"Character with this clan_id: {char['name']} ({char['id']})")
    else:
        print("No character found with this clan_id")

if __name__ == "__main__":
    asyncio.run(check_clan())
