# Alembic Setup — Stitch

## 1. Install and place the files

```bash
pip install alembic
```

Copy into your `server/` root (same level as `main.py`):

```
server/
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/        (empty folder, migrations go here)
├── app/
└── main.py
```

## 2. Fix the two placeholders in `alembic/env.py`

- `from app.core.config import settings` / `settings.DATABASE_URL` — point this
  at wherever your app actually builds its DB URL. If you don't have a
  `settings` object, delete that block and just rely on the `DATABASE_URL`
  env var fallback.
- The `import app.models.*` block — make sure every model module in
  `app/models/` is listed. Missing one means autogenerate can't see those
  tables and may propose dropping them.

## 3. The important part: your DB already has tables

Because you've been using `Base.metadata.create_all()`, your database
(assuming you ran `reset_db.py` and it's now clean) already matches your
current models exactly — but Alembic doesn't know that yet. It has no
`alembic_version` table and no history.

**Do not just run `alembic upgrade head` first.** If you do, Alembic will
think the DB is empty and try to `CREATE TABLE` everything, which will fail
since the tables already exist.

Do this instead, once, to get Alembic in sync with reality:

```bash
# 1. Generate a migration that represents your CURRENT schema
alembic revision --autogenerate -m "baseline: current schema"

# 2. Open the generated file in alembic/versions/ and sanity-check it.
#    It should contain CREATE TABLE for every table you have. Check for
#    anything that looks like an accidental DROP — that would mean a model
#    isn't imported in env.py.

# 3. Mark the DB as already being at this migration, WITHOUT running the
#    upgrade() SQL (since the tables already exist for real)
alembic stamp head
```

After this, `alembic_version` exists in your DB and Alembic considers your
current schema the baseline. From here on, every future model change goes
through the normal flow:

```bash
alembic revision --autogenerate -m "add order_id fk to laundry_orders"
# review the generated file
alembic upgrade head
```

## 4. Normal day-to-day workflow going forward

1. Change a model in `app/models/`.
2. `alembic revision --autogenerate -m "short description"`
3. **Always open and read the generated file** before applying it —
   autogenerate is good but not perfect (it won't detect renamed columns,
   for example; it'll see them as a drop + add and you'll lose data unless
   you edit the migration to use `op.alter_column` instead).
4. `alembic upgrade head` to apply.
5. Commit the migration file to git alongside the model change, same PR.
6. If something's wrong after applying: `alembic downgrade -1` to roll back
   one step.

## 5. Remove `create_all()` from app startup

Once Alembic is your source of truth, `Base.metadata.create_all()` in
`app/db/database.py` (or wherever it's called on startup) should be removed
or gated to a `if settings.ENV == "test"` type branch. Leaving both active
is exactly how you got into today's inconsistent-state mess — `create_all`
silently creates whatever's missing, out of step with what Alembic thinks
the schema is.

## Useful commands reference

| Command | What it does |
|---|---|
| `alembic current` | Shows which migration the DB is currently at |
| `alembic history` | Lists all migrations in order |
| `alembic upgrade head` | Apply all pending migrations |
| `alembic upgrade +1` | Apply just the next one |
| `alembic downgrade -1` | Roll back one migration |
| `alembic downgrade base` | Roll back everything (careful) |
| `alembic revision --autogenerate -m "msg"` | Generate a migration from model diffs |
| `alembic stamp head` | Mark DB as up-to-date without running SQL (baseline only) |
