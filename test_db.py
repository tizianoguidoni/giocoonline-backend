import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

async def test_conn():
    load_dotenv()
    url = os.environ.get('MONGO_URL')
    db_name = os.environ.get('DB_NAME')
    print(f"Testing connection to: {url.split('@')[-1]}") # Hide credentials
    try:
        client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000)
        db = client[db_name]
        # Try a simple command
        res = await db.command('ping')
        print("✅ Connection successful:", res)
    except Exception as e:
        print("❌ Connection failed:", str(e))

if __name__ == "__main__":
    asyncio.run(test_conn())
