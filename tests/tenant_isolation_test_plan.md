# Tenant isolation test plan

Run these against a disposable PostgreSQL database after enabling RLS.

1. Register Organization A and Organization B using different users.
2. Authenticate as A and create a workspace and project.
3. Authenticate as B and verify GET /workspaces and GET /projects return no A records.
4. Attempt to create a project in A's workspace using B's token; expect 404.
5. Attempt to switch to A using B's token; expect 403.
6. Add the same user to two organizations and verify `/auth/organizations` lists only memberships for that authenticated user; switch organizations and verify the new token accesses only the selected tenant.
7. Execute direct SQL as the application role without setting `app.current_tenant_id`; verify RLS returns zero tenant-owned rows.

Also test connection-pool reuse: make a request as tenant A, then tenant B, and confirm B never sees A's data.
