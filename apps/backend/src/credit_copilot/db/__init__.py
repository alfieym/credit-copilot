"""Data layer: Postgres schema + CSV seeding.

- ``schema.sql`` defines the 8 star-schema tables of the credit domain.
- ``seed.py`` creates those tables (``CREATE TABLE IF NOT EXISTS``) and COPY-loads
  ``data/seed/*.csv``; because it never ALTERs, a schema change needs a volume
  rebuild (``docker compose down -v && make db-up && make seed``).
"""
