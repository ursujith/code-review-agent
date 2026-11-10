"""Create tables for local development only. Use Alembic migrations in production."""
import asyncio
from app.db.base import Base
from app.db.session import engine
import app.models  # noqa: F401

async def main():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
