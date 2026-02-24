"""Database layer for dynamic asset masking."""

from __future__ import annotations

import abc
import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional

import structlog

LOGGER = structlog.getLogger(__name__)


class AssetCategory(str, Enum):
    VM_NAME = "VM_NAME"
    HOSTNAME = "HOSTNAME"
    DB_NAME = "DB_NAME"
    TABLE_NAME = "TABLE_NAME"
    STORAGE_RESOURCE = "STORAGE_RESOURCE"
    NETWORK_RESOURCE = "NETWORK_RESOURCE"
    INTERNAL_URL = "INTERNAL_URL"
    INTERNAL_SERVICE = "INTERNAL_SERVICE"
    PROJECT_NAME = "PROJECT_NAME"


VALID_CATEGORIES = {c.value for c in AssetCategory}


@dataclass
class MaskedAsset:
    id: str
    name: str
    category: str
    source: str = ""
    last_synced: str = ""
    is_active: bool = True
    aliases: list[str] = field(default_factory=list)


class AssetStore(abc.ABC):
    @abc.abstractmethod
    def initialize(self) -> None:
        ...

    @abc.abstractmethod
    def get_all_active(self) -> list[MaskedAsset]:
        ...

    @abc.abstractmethod
    def list_assets(
        self,
        category: Optional[str] = None,
        search: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[MaskedAsset], int]:
        ...

    @abc.abstractmethod
    def create(self, asset: MaskedAsset) -> MaskedAsset:
        ...

    @abc.abstractmethod
    def update(self, asset_id: str, updates: dict) -> Optional[MaskedAsset]:
        ...

    @abc.abstractmethod
    def delete(self, asset_id: str) -> bool:
        ...

    @abc.abstractmethod
    def bulk_create(self, assets: list[MaskedAsset]) -> int:
        ...

    @abc.abstractmethod
    def get_stats(self) -> dict[str, int]:
        ...


class SQLiteAssetStore(AssetStore):
    def __init__(self, db_path: str = "./data/masked_assets.db"):
        self._db_path = db_path
        self._lock = threading.Lock()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def initialize(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
        conn = self._get_conn()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS masked_assets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    last_synced TEXT DEFAULT '',
                    is_active INTEGER DEFAULT 1,
                    aliases TEXT DEFAULT '[]'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_masked_assets_name "
                "ON masked_assets(name COLLATE NOCASE)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_masked_assets_category "
                "ON masked_assets(category)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_masked_assets_active "
                "ON masked_assets(is_active)"
            )
            conn.commit()
            LOGGER.info("SQLite asset store initialized", db_path=self._db_path)
        finally:
            conn.close()

    def _row_to_asset(self, row: sqlite3.Row) -> MaskedAsset:
        return MaskedAsset(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            source=row["source"] or "",
            last_synced=row["last_synced"] or "",
            is_active=bool(row["is_active"]),
            aliases=json.loads(row["aliases"]) if row["aliases"] else [],
        )

    def get_all_active(self) -> list[MaskedAsset]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM masked_assets WHERE is_active = 1"
            ).fetchall()
            return [self._row_to_asset(r) for r in rows]
        finally:
            conn.close()

    def list_assets(
        self,
        category: Optional[str] = None,
        search: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[MaskedAsset], int]:
        conn = self._get_conn()
        try:
            where_clauses = []
            params: list = []

            if category:
                where_clauses.append("category = ?")
                params.append(category)

            if search:
                where_clauses.append("(name LIKE ? OR aliases LIKE ?)")
                params.extend([f"%{search}%", f"%{search}%"])

            where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            count = conn.execute(
                f"SELECT COUNT(*) FROM masked_assets{where_sql}", params
            ).fetchone()[0]

            rows = conn.execute(
                f"SELECT * FROM masked_assets{where_sql} ORDER BY name COLLATE NOCASE "
                f"LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()

            return [self._row_to_asset(r) for r in rows], count
        finally:
            conn.close()

    def create(self, asset: MaskedAsset) -> MaskedAsset:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO masked_assets (id, name, category, source, last_synced, "
                    "is_active, aliases) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        asset.id,
                        asset.name,
                        asset.category,
                        asset.source,
                        asset.last_synced,
                        int(asset.is_active),
                        json.dumps(asset.aliases),
                    ),
                )
                conn.commit()
                return asset
            finally:
                conn.close()

    def update(self, asset_id: str, updates: dict) -> Optional[MaskedAsset]:
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT * FROM masked_assets WHERE id = ?", (asset_id,)
                ).fetchone()
                if not row:
                    return None

                asset = self._row_to_asset(row)
                for key, value in updates.items():
                    if hasattr(asset, key):
                        setattr(asset, key, value)

                conn.execute(
                    "UPDATE masked_assets SET name=?, category=?, source=?, last_synced=?, "
                    "is_active=?, aliases=? WHERE id=?",
                    (
                        asset.name,
                        asset.category,
                        asset.source,
                        asset.last_synced,
                        int(asset.is_active),
                        json.dumps(asset.aliases),
                        asset_id,
                    ),
                )
                conn.commit()
                return asset
            finally:
                conn.close()

    def delete(self, asset_id: str) -> bool:
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "DELETE FROM masked_assets WHERE id = ?", (asset_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def bulk_create(self, assets: list[MaskedAsset]) -> int:
        with self._lock:
            conn = self._get_conn()
            try:
                count = 0
                for asset in assets:
                    try:
                        conn.execute(
                            "INSERT INTO masked_assets (id, name, category, source, "
                            "last_synced, is_active, aliases) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                asset.id,
                                asset.name,
                                asset.category,
                                asset.source,
                                asset.last_synced,
                                int(asset.is_active),
                                json.dumps(asset.aliases),
                            ),
                        )
                        count += 1
                    except sqlite3.IntegrityError:
                        LOGGER.warning("Duplicate asset skipped", asset_name=asset.name)
                conn.commit()
                return count
            finally:
                conn.close()

    def get_stats(self) -> dict[str, int]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT category, COUNT(*) as cnt FROM masked_assets "
                "WHERE is_active = 1 GROUP BY category"
            ).fetchall()
            stats = {row["category"]: row["cnt"] for row in rows}
            total = conn.execute(
                "SELECT COUNT(*) FROM masked_assets WHERE is_active = 1"
            ).fetchone()[0]
            stats["TOTAL"] = total
            return stats
        finally:
            conn.close()


class CachedAssetStore:
    """Thread-safe caching wrapper around an AssetStore."""

    def __init__(self, store: AssetStore, cache_ttl: int = 300):
        self._store = store
        self._cache_ttl = cache_ttl
        self._lock = threading.Lock()
        self._cache: list[MaskedAsset] = []
        self._last_refresh: float = 0

    @property
    def store(self) -> AssetStore:
        return self._store

    def get_lookup_data(self) -> list[MaskedAsset]:
        now = time.time()
        if now - self._last_refresh > self._cache_ttl:
            self.refresh()
        return self._cache

    def refresh(self) -> None:
        with self._lock:
            try:
                self._cache = self._store.get_all_active()
                self._last_refresh = time.time()
                LOGGER.info(
                    "Asset cache refreshed", asset_count=len(self._cache)
                )
            except Exception:
                LOGGER.exception("Failed to refresh asset cache")

    # Delegate CRUD operations to underlying store
    def list_assets(self, **kwargs):
        return self._store.list_assets(**kwargs)

    def create(self, asset: MaskedAsset) -> MaskedAsset:
        result = self._store.create(asset)
        self.refresh()
        return result

    def update(self, asset_id: str, updates: dict) -> Optional[MaskedAsset]:
        result = self._store.update(asset_id, updates)
        if result:
            self.refresh()
        return result

    def delete(self, asset_id: str) -> bool:
        result = self._store.delete(asset_id)
        if result:
            self.refresh()
        return result

    def bulk_create(self, assets: list[MaskedAsset]) -> int:
        count = self._store.bulk_create(assets)
        if count > 0:
            self.refresh()
        return count

    def get_stats(self) -> dict[str, int]:
        return self._store.get_stats()


def create_asset_store(config: dict) -> CachedAssetStore:
    """Factory function to create an asset store from config."""
    db_type = config.get("db_type", "sqlite")
    cache_ttl = int(config.get("cache_ttl", 300))

    if db_type == "sqlite":
        db_path = config.get("db_path", "./data/masked_assets.db")
        store = SQLiteAssetStore(db_path=db_path)
    else:
        raise ValueError(f"Unsupported db_type: {db_type}")

    store.initialize()
    cached = CachedAssetStore(store, cache_ttl=cache_ttl)
    cached.refresh()
    return cached
