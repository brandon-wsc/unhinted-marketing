import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory.embeddings import embed_texts
from internal.memory.models import (
    Edge,
    Entity,
    OrganizationMember,
    PreviewDraft,
    PreviewImage,
    Product,
    RawNewsEvent,
    RecommendedQuestions,
    Session,
    SessionMessage,
    ToolReceipt,
)
from internal.memory.product_import import build_search_document


def url_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def upsert_signal(
    db: AsyncSession,
    *,
    signal_id: str,
    source: str,
    title: str,
    url: str | None,
    excerpt: str | None,
    metrics: dict,
    region: str = "HK",
    ingested_at: datetime | None = None,
) -> RawNewsEvent:
    dedupe_key = url or signal_id
    now = ingested_at or datetime.now(UTC)
    stmt = (
        insert(RawNewsEvent)
        .values(
            id=uuid.uuid4(),
            signal_id=signal_id,
            source=source,
            title=title,
            url=url,
            excerpt=excerpt,
            url_hash=url_hash(dedupe_key),
            region=region,
            metrics=metrics,
            ingested_at=now,
        )
        .on_conflict_do_update(
            index_elements=["signal_id"],
            set_={
                "title": title,
                "url": url,
                "excerpt": excerpt,
                "metrics": metrics,
                "ingested_at": now,
            },
        )
        .returning(RawNewsEvent)
    )
    row = await db.scalar(stmt)
    assert row is not None
    return row


async def list_top_signals(
    db: AsyncSession,
    *,
    limit: int = 20,
    region: str = "HK",
    since: datetime | None = None,
) -> list[RawNewsEvent]:
    q = select(RawNewsEvent).where(RawNewsEvent.region == region)
    if since:
        q = q.where(RawNewsEvent.ingested_at >= since)
    q = q.order_by(desc(RawNewsEvent.ingested_at)).limit(limit)
    result = await db.scalars(q)
    return list(result.all())


async def get_signals_by_ids(db: AsyncSession, signal_ids: list[str]) -> list[RawNewsEvent]:
    if not signal_ids:
        return []
    result = await db.scalars(select(RawNewsEvent).where(RawNewsEvent.signal_id.in_(signal_ids)))
    return list(result.all())


async def create_edge(
    db: AsyncSession,
    *,
    edge_type: str,
    source_signal_id: str,
    from_entity_id: uuid.UUID | None = None,
    to_entity_id: uuid.UUID | None = None,
    metadata: dict | None = None,
) -> Edge:
    edge = Edge(
        edge_type=edge_type,
        source_signal_id=source_signal_id,
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
        metadata_=metadata or {},
    )
    db.add(edge)
    await db.flush()
    return edge


async def get_company(db: AsyncSession, company_id: uuid.UUID) -> Entity | None:
    return await db.scalar(
        select(Entity).where(Entity.id == company_id, Entity.entity_type == "company")
    )


async def list_companies(db: AsyncSession) -> list[Entity]:
    result = await db.scalars(select(Entity).where(Entity.entity_type == "company"))
    return list(result.all())


async def user_has_org_access(
    db: AsyncSession, user_id: uuid.UUID, company_id: uuid.UUID
) -> bool:
    row = await db.scalar(
        select(OrganizationMember.id).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == company_id,
        )
    )
    return row is not None


async def get_org_membership(
    db: AsyncSession, user_id: uuid.UUID, company_id: uuid.UUID
) -> OrganizationMember | None:
    return await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == company_id,
        )
    )


async def update_company_profile(
    db: AsyncSession, company: Entity, *, patch: dict
) -> Entity:
    """Shallow-merge keys into company.profile JSONB (preserves unrelated keys)."""
    from sqlalchemy.orm.attributes import flag_modified

    profile = dict(company.profile or {})
    profile.update(patch)
    company.profile = profile
    flag_modified(company, "profile")
    await db.flush()
    return company


async def save_recommended_questions(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    questions: list[dict],
    source_signal_ids: list[str],
    ttl_hours: int = 12,
) -> RecommendedQuestions:
    now = datetime.now(UTC)
    row = RecommendedQuestions(
        company_id=company_id,
        questions=questions,
        source_signal_ids=source_signal_ids,
        generated_at=now,
        expires_at=now + timedelta(hours=ttl_hours),
    )
    db.add(row)
    await db.flush()
    return row


async def get_latest_questions(
    db: AsyncSession, company_id: uuid.UUID
) -> RecommendedQuestions | None:
    return await db.scalar(
        select(RecommendedQuestions)
        .where(RecommendedQuestions.company_id == company_id)
        .order_by(desc(RecommendedQuestions.generated_at))
        .limit(1)
    )


async def get_or_create_topic_entity(
    db: AsyncSession, *, slug: str, name: str, profile: dict | None = None
) -> Entity:
    existing = await db.scalar(select(Entity).where(Entity.slug == slug))
    if existing:
        existing.name = name
        if profile is not None:
            existing.profile = profile
        return existing
    entity = Entity(entity_type="topic", slug=slug, name=name, profile=profile)
    db.add(entity)
    await db.flush()
    return entity


async def list_personas(db: AsyncSession) -> list[Entity]:
    result = await db.scalars(select(Entity).where(Entity.entity_type == "persona"))
    return list(result.all())


async def signal_has_promotion_edge(db: AsyncSession, signal_id: str) -> bool:
    row = await db.scalar(
        select(Edge.id)
        .where(Edge.source_signal_id == signal_id, Edge.edge_type == "AFFECTS")
        .limit(1)
    )
    return row is not None


async def reset_market_signals(db: AsyncSession) -> dict[str, int]:
    """Delete all ingested signals, graph edges, topic entities, and question cache."""
    questions = await db.execute(delete(RecommendedQuestions))
    edges = await db.execute(delete(Edge))
    signals = await db.execute(delete(RawNewsEvent))
    topics = await db.execute(delete(Entity).where(Entity.entity_type == "topic"))
    await db.commit()
    return {
        "recommended_questions": questions.rowcount,
        "edges": edges.rowcount,
        "raw_news_events": signals.rowcount,
        "topic_entities": topics.rowcount,
    }


async def create_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    mode: str = "CHAT",
) -> Session:
    row = Session(user_id=user_id, company_id=company_id, mode=mode, state={})
    db.add(row)
    await db.flush()
    return row


async def get_session(db: AsyncSession, session_id: uuid.UUID) -> Session | None:
    return await db.scalar(select(Session).where(Session.id == session_id))


async def list_user_sessions(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID | None = None,
    limit: int = 40,
) -> list[tuple[Session, str | None]]:
    """Return sessions pinned-first then newest, with display title."""
    first_user = (
        select(SessionMessage.content)
        .where(
            SessionMessage.session_id == Session.id,
            SessionMessage.role == "user",
        )
        .order_by(SessionMessage.created_at.asc())
        .limit(1)
        .correlate(Session)
        .scalar_subquery()
    )
    stmt = select(Session, first_user).where(Session.user_id == user_id)
    if company_id is not None:
        stmt = stmt.where(Session.company_id == company_id)
    stmt = stmt.order_by(desc(Session.pinned), desc(Session.updated_at)).limit(limit)
    rows = (await db.execute(stmt)).all()
    return [(row[0], row[1]) for row in rows]


async def update_session_meta(
    db: AsyncSession,
    session: Session,
    *,
    title: str | None = None,
    clear_title: bool = False,
    pinned: bool | None = None,
) -> Session:
    if clear_title:
        session.title = None
    elif title is not None:
        cleaned = title.strip()[:200]
        session.title = cleaned or None
    if pinned is not None:
        session.pinned = pinned
    await db.flush()
    return session


async def delete_session(db: AsyncSession, session: Session) -> None:
    await db.delete(session)
    await db.flush()


async def add_session_message(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    role: str,
    content: str,
    metadata: dict | None = None,
) -> SessionMessage:
    row = SessionMessage(
        session_id=session_id,
        role=role,
        content=content,
        metadata_=metadata or {},
    )
    db.add(row)
    await db.flush()
    return row


async def list_session_messages(
    db: AsyncSession, session_id: uuid.UUID
) -> list[SessionMessage]:
    result = await db.scalars(
        select(SessionMessage)
        .where(SessionMessage.session_id == session_id)
        .order_by(SessionMessage.created_at)
    )
    return list(result.all())


async def delete_session_messages_by_ids(
    db: AsyncSession,
    session_id: uuid.UUID,
    message_ids: list[uuid.UUID],
) -> int:
    """Delete specific messages belonging to a session. Returns rows deleted."""
    if not message_ids:
        return 0
    result = await db.execute(
        delete(SessionMessage).where(
            SessionMessage.session_id == session_id,
            SessionMessage.id.in_(message_ids),
        )
    )
    await db.flush()
    return int(result.rowcount or 0)


async def insert_preview_image(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    url: str | None,
    plan: dict | None,
    format: str = "single",
    role: str = "primary",
    seq: int = 0,
    status: str = "ready",
) -> PreviewImage:
    """Append-only image version (ADR 0008). Never mutate plan/url of returned rows later."""
    row = PreviewImage(
        session_id=session_id,
        seq=seq,
        role=role,
        format=format,
        status=status,
        url=url,
        plan=dict(plan or {}),
    )
    db.add(row)
    await db.flush()
    return row


async def get_preview_image(
    db: AsyncSession, image_id: uuid.UUID
) -> PreviewImage | None:
    return await db.scalar(select(PreviewImage).where(PreviewImage.id == image_id))


async def get_preview_images_by_ids(
    db: AsyncSession, image_ids: list[uuid.UUID]
) -> list[PreviewImage]:
    if not image_ids:
        return []
    rows = (
        await db.scalars(select(PreviewImage).where(PreviewImage.id.in_(image_ids)))
    ).all()
    by_id = {r.id: r for r in rows}
    return [by_id[i] for i in image_ids if i in by_id]


async def upsert_preview_draft(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    revision: int,
    copy: dict,
    image_url: str | None,
    image_plan: dict | None,
    source_signal_ids: list[str],
    approval_token: str,
    platform: str | None = None,
    media_ids: list[uuid.UUID] | None = None,
) -> PreviewDraft:
    row = PreviewDraft(
        session_id=session_id,
        revision=revision,
        copy=copy,
        image_url=image_url,
        image_plan=image_plan,
        media_ids=list(media_ids or []),
        source_signal_ids=source_signal_ids,
        approval_token=approval_token,
        platform=platform,
    )
    db.add(row)
    await db.flush()
    return row


async def get_latest_preview_draft(
    db: AsyncSession, session_id: uuid.UUID
) -> PreviewDraft | None:
    return await db.scalar(
        select(PreviewDraft)
        .where(PreviewDraft.session_id == session_id)
        .order_by(desc(PreviewDraft.revision))
        .limit(1)
    )


async def get_preview_draft_by_token(
    db: AsyncSession, session_id: uuid.UUID, approval_token: str
) -> PreviewDraft | None:
    return await db.scalar(
        select(PreviewDraft).where(
            PreviewDraft.session_id == session_id,
            PreviewDraft.approval_token == approval_token,
        )
    )


async def get_tool_receipt_by_idempotency(
    db: AsyncSession, idempotency_key: str
) -> ToolReceipt | None:
    return await db.scalar(
        select(ToolReceipt).where(ToolReceipt.idempotency_key == idempotency_key)
    )


async def create_tool_receipt(
    db: AsyncSession,
    *,
    session_id: uuid.UUID | None,
    user_id: uuid.UUID,
    tool_name: str,
    idempotency_key: str,
    status: str,
    request: dict,
    response: dict,
) -> ToolReceipt:
    row = ToolReceipt(
        session_id=session_id,
        user_id=user_id,
        tool_name=tool_name,
        idempotency_key=idempotency_key,
        status=status,
        request=request,
        response=response,
    )
    db.add(row)
    await db.flush()
    return row


async def list_products(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    owner_scope: str,
    user_id: uuid.UUID | None = None,
    status: str | None = "active",
) -> list[Product]:
    stmt = select(Product).where(
        Product.company_id == company_id,
        Product.owner_scope == owner_scope,
    )
    if owner_scope == "user":
        if user_id is None:
            return []
        stmt = stmt.where(Product.user_id == user_id)
    if status is not None:
        stmt = stmt.where(Product.status == status)
    stmt = stmt.order_by(Product.name.asc(), Product.sku.asc())
    result = await db.scalars(stmt)
    return list(result.all())


async def list_org_skus(
    db: AsyncSession, *, company_id: uuid.UUID, status: str = "active"
) -> set[str]:
    rows = await db.scalars(
        select(Product.sku).where(
            Product.company_id == company_id,
            Product.owner_scope == "org",
            Product.status == status,
        )
    )
    return set(rows.all())


async def get_product(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    product_id: uuid.UUID,
) -> Product | None:
    return await db.scalar(
        select(Product).where(Product.id == product_id, Product.company_id == company_id)
    )


async def upsert_product_row(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    owner_scope: str,
    user_id: uuid.UUID | None,
    sku: str,
    name: str,
    search_document: str,
    profile: dict,
    embedding: list[float] | None = None,
    embed: bool = True,
) -> tuple[Product, bool]:
    """Upsert by SKU. Returns (row, created). Reactivates archived rows.

    When ``embedding`` is omitted and ``embed`` is True, embeds ``search_document``
    inline (COLLECT K4 re-embed on upsert).
    """
    from sqlalchemy.orm.attributes import flag_modified

    if embedding is None and embed:
        vecs = embed_texts([search_document])
        embedding = vecs[0] if vecs else None

    stmt = select(Product).where(
        Product.company_id == company_id,
        Product.owner_scope == owner_scope,
        Product.sku == sku,
    )
    if owner_scope == "user":
        stmt = stmt.where(Product.user_id == user_id)
    else:
        stmt = stmt.where(Product.user_id.is_(None))

    existing = await db.scalar(stmt)
    if existing:
        existing.name = name
        existing.search_document = search_document
        existing.profile = profile
        existing.status = "active"
        if embed or embedding is not None:
            existing.embedding = embedding
        flag_modified(existing, "profile")
        await db.flush()
        return existing, False

    row = Product(
        company_id=company_id,
        owner_scope=owner_scope,
        user_id=user_id if owner_scope == "user" else None,
        sku=sku,
        name=name,
        search_document=search_document,
        profile=profile,
        embedding=embedding,
        status="active",
    )
    db.add(row)
    await db.flush()
    return row, True


async def archive_product(db: AsyncSession, product: Product) -> Product:
    product.status = "archived"
    await db.flush()
    return product


async def create_manual_product(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    owner_scope: str,
    user_id: uuid.UUID | None,
    sku: str,
    name: str,
    notes: str = "",
) -> tuple[Product, bool]:
    profile: dict[str, str] = {"name": name, "sku": sku}
    if notes:
        profile["notes"] = notes
    search_document = build_search_document(profile, sku=sku, name=name)
    return await upsert_product_row(
        db,
        company_id=company_id,
        owner_scope=owner_scope,
        user_id=user_id,
        sku=sku,
        name=name,
        search_document=search_document,
        profile=profile,
    )
