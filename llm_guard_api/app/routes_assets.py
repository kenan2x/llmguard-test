"""CRUD API routes for masked asset management."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from .db import VALID_CATEGORIES, CachedAssetStore, MaskedAsset

LOGGER = structlog.getLogger(__name__)


# --- Request/Response models ---


class AssetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    category: str = Field(min_length=1)
    source: str = Field(default="")
    aliases: List[str] = Field(default_factory=list)
    is_active: bool = Field(default=True)


class AssetUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=500)
    category: Optional[str] = Field(default=None, min_length=1)
    source: Optional[str] = Field(default=None)
    aliases: Optional[List[str]] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)


class AssetResponse(BaseModel):
    id: str
    name: str
    category: str
    source: str
    last_synced: str
    is_active: bool
    aliases: List[str]


class AssetListResponse(BaseModel):
    items: List[AssetResponse]
    total: int
    offset: int
    limit: int


class BulkCreateRequest(BaseModel):
    assets: List[AssetCreateRequest]


class BulkCreateResponse(BaseModel):
    created: int
    total_submitted: int


class StatsResponse(BaseModel):
    stats: dict[str, int]


class SyncResponse(BaseModel):
    message: str
    asset_count: int


def _validate_category(category: str) -> None:
    if category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid category: {category}. Valid categories: {sorted(VALID_CATEGORIES)}",
        )


def _asset_to_response(asset: MaskedAsset) -> AssetResponse:
    return AssetResponse(
        id=asset.id,
        name=asset.name,
        category=asset.category,
        source=asset.source,
        last_synced=asset.last_synced,
        is_active=asset.is_active,
        aliases=asset.aliases,
    )


def create_asset_routes(cached_store: CachedAssetStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1/masked-assets", tags=["Masked Assets"])

    @router.get("/", response_model=AssetListResponse)
    async def list_assets(
        category: Optional[str] = Query(None, description="Filter by category"),
        search: Optional[str] = Query(None, description="Search by name or alias"),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
    ):
        if category:
            _validate_category(category)
        items, total = cached_store.list_assets(
            category=category, search=search, offset=offset, limit=limit
        )
        return AssetListResponse(
            items=[_asset_to_response(a) for a in items],
            total=total,
            offset=offset,
            limit=limit,
        )

    @router.post("/", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
    async def create_asset(req: AssetCreateRequest):
        _validate_category(req.category)
        asset = MaskedAsset(
            id=str(uuid.uuid4()),
            name=req.name,
            category=req.category,
            source=req.source,
            last_synced=datetime.now(timezone.utc).isoformat(),
            is_active=req.is_active,
            aliases=req.aliases,
        )
        created = cached_store.create(asset)
        LOGGER.info("Asset created", asset_id=created.id, name=created.name)
        return _asset_to_response(created)

    @router.put("/{asset_id}", response_model=AssetResponse)
    async def update_asset(asset_id: str, req: AssetUpdateRequest):
        updates = req.model_dump(exclude_none=True)
        if "category" in updates:
            _validate_category(updates["category"])
        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update",
            )
        updated = cached_store.update(asset_id, updates)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Asset {asset_id} not found",
            )
        LOGGER.info("Asset updated", asset_id=asset_id)
        return _asset_to_response(updated)

    @router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_asset(asset_id: str):
        deleted = cached_store.delete(asset_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Asset {asset_id} not found",
            )
        LOGGER.info("Asset deleted", asset_id=asset_id)

    @router.post("/bulk", response_model=BulkCreateResponse)
    async def bulk_create(req: BulkCreateRequest):
        assets = []
        for item in req.assets:
            _validate_category(item.category)
            assets.append(
                MaskedAsset(
                    id=str(uuid.uuid4()),
                    name=item.name,
                    category=item.category,
                    source=item.source,
                    last_synced=datetime.now(timezone.utc).isoformat(),
                    is_active=item.is_active,
                    aliases=item.aliases,
                )
            )
        count = cached_store.bulk_create(assets)
        LOGGER.info("Bulk create completed", created=count, submitted=len(req.assets))
        return BulkCreateResponse(created=count, total_submitted=len(req.assets))

    @router.post("/sync", response_model=SyncResponse)
    async def sync_cache():
        cached_store.refresh()
        data = cached_store.get_lookup_data()
        return SyncResponse(message="Cache refreshed", asset_count=len(data))

    @router.get("/stats", response_model=StatsResponse)
    async def get_stats():
        stats = cached_store.get_stats()
        return StatsResponse(stats=stats)

    return router
