"""Enable tenant RLS on existing local development tables.

Run after scripts.create_dev_schema:
    python -m scripts.enable_dev_rls

The application DB role must not be a superuser or have BYPASSRLS.
"""
import asyncio
from sqlalchemy import text
from app.db.session import engine

STATEMENTS = [
    "ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE workspaces FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON workspaces",
    """CREATE POLICY tenant_isolation ON workspaces
       USING (organization_id =
         NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
       WITH CHECK (organization_id =
         NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)""",

    "ALTER TABLE projects ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE projects FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON projects",
    """CREATE POLICY tenant_isolation ON projects
       USING (organization_id =
         NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
       WITH CHECK (organization_id =
         NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)""",

    "ALTER TABLE memberships ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE memberships FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS user_membership_isolation ON memberships",
    """CREATE POLICY user_membership_isolation ON memberships
       USING (
         user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
         AND (
           NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
           OR organization_id =
             NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
         )
       )
       WITH CHECK (
         user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
         AND organization_id =
           NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
       )""",
]

async def main():
    async with engine.begin() as conn:
        for statement in STATEMENTS:
            await conn.execute(text(statement))
    await engine.dispose()
    print("RLS enabled on workspaces, projects and memberships.")

if __name__ == "__main__":
    asyncio.run(main())
