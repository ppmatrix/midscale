import asyncio
import sys
sys.path.insert(0, '.')

from app.database import init_db, get_session
from app.config import settings
from app.core.security import hash_password
from app.models.user import User
from sqlalchemy import select


async def seed():
    await init_db(settings.database_url)
    async for session in get_session():
        result = await session.execute(
            select(User).where(User.email == "admin@midscale.local")
        )
        if result.scalar_one_or_none():
            print("Admin user already exists")
            return

        user = User(
            email="admin@midscale.local",
            password_hash=hash_password("admin123"),
            display_name="Admin",
            is_superuser=True,
        )
        session.add(user)
        await session.flush()
        print(f"Created admin user: {user.email} / admin123")


if __name__ == "__main__":
    asyncio.run(seed())
