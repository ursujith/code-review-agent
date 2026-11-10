"""Create a non-superuser application DB role for local development.

Run while DATABASE_URL still uses the bootstrap `review` role, then change
DATABASE_URL to the new `review_app` credentials.
"""
import asyncio
from sqlalchemy import text
from app.db.session import engine

async def main():
    async with engine.begin() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_roles WHERE rolname = 'review_app'")
        )
        if exists:
            await conn.execute(text("""
                ALTER ROLE review_app WITH LOGIN PASSWORD 'review_app_dev_only'
                NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
                NOREPLICATION NOBYPASSRLS
            """))
        else:
            await conn.execute(text("""
                CREATE ROLE review_app LOGIN PASSWORD 'review_app_dev_only'
                NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
                NOREPLICATION NOBYPASSRLS
            """))
        await conn.execute(text("GRANT CONNECT ON DATABASE review_platform TO review_app"))
        await conn.execute(text("GRANT USAGE ON SCHEMA public TO review_app"))
        await conn.execute(text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO review_app"
        ))
        await conn.execute(text(
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO review_app"
        ))
        await conn.execute(text("""
            ALTER DEFAULT PRIVILEGES FOR ROLE review IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO review_app
        """))
        await conn.execute(text("""
            ALTER DEFAULT PRIVILEGES FOR ROLE review IN SCHEMA public
            GRANT USAGE, SELECT ON SEQUENCES TO review_app
        """))
    await engine.dispose()
    print("Created/updated review_app as a non-superuser, non-BYPASSRLS role.")

if __name__ == "__main__":
    asyncio.run(main())
