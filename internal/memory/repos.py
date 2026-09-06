import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Text, cast, delete, desc, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from internal.memory.embeddings import embed_texts
from internal.memory.models import (
    ByokModel,
    ByokProvider,
    ByokRouting,
    Edge,
    Entity,
    OrganizationMember,
    OrgInvite,
    PreviewDraft,
    PreviewImage,
    Product,
    ProductProposal,
    QuestionNodeStep,
    QuestionRun,
    RawNewsEvent,
    RecommendedQuestions,
    Session,
    SessionMessage,
    SocialAccount,
    ToolReceipt,
    User,
)
from internal.memory.product_import import build_search_document
from internal.memory.product_sku import allocate_unique_sku


def url_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _signal_update_fields(
    *,
    title: str,
    url: str | None,
    excerpt: str | None,
    metrics: dict,
    ingested_at: datetime,
) -> dict:
    return {
        "title": title,
        "url": url,
        "excerpt": excerpt,
        "metrics": metrics,
        "ingested_at": ingested_at,
    }


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
    """Insert or refresh a signal.

    ``signal_id`` and ``url_hash`` are both unique. RSS + Tavily often share a
    URL with different ids — collide on ``url_hash`` must not abort the outer
    transaction. Keep the first ``signal_id`` so existing refs stay stable.
    """
    dedupe_key = url or signal_id
    hash_val = url_hash(dedupe_key)
    now = ingested_at or datetime.now(UTC)
    fields = _signal_update_fields(
        title=title, url=url, excerpt=excerpt, metrics=metrics, ingested_at=now
    )
    stmt = (
        insert(RawNewsEvent)
        .values(
            id=uuid.uuid4(),
            signal_id=signal_id,
            source=source,
            url_hash=hash_val,
            region=region,
            **fields,
        )
        .on_conflict_do_update(
            index_elements=["signal_id"],
            set_=fields,
        )
        .returning(RawNewsEvent)
    )
    try:
        async with db.begin_nested():
            row = await db.scalar(stmt)
            assert row is not None
            return row
    except IntegrityError:
        existing = await db.scalar(
            select(RawNewsEvent).where(
                or_(RawNewsEvent.signal_id == signal_id, RawNewsEvent.url_hash == hash_val)
            )
        )
        if existing is None:
            raise
        existing.title = title
        existing.url = url
        existing.excerpt = excerpt
        existing.metrics = metrics
        existing.ingested_at = now
        await db.flush()
        return existing


async def list_top_signals(
    db: AsyncSession,
    *,
    limit: int = 20,
    region: str = "HK",
    since: datetime | None = None,
    sources: list[str] | None = None,
) -> list[RawNewsEvent]:
    q = select(RawNewsEvent).where(RawNewsEvent.region == region)
    if since:
        q = q.where(RawNewsEvent.ingested_at >= since)
    if sources:
        q = q.where(RawNewsEvent.source.in_(sources))
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


async def list_org_members(
    db: AsyncSession, company_id: uuid.UUID
) -> list[tuple[OrganizationMember, User]]:
    result = await db.execute(
        select(OrganizationMember, User)
        .join(User, OrganizationMember.user_id == User.id)
        .where(OrganizationMember.organization_id == company_id)
        .order_by(OrganizationMember.created_at)
    )
    return list(result.all())


async def get_org_member_by_email(
    db: AsyncSession, company_id: uuid.UUID, email: str
) -> OrganizationMember | None:
    return await db.scalar(
        select(OrganizationMember)
        .join(User, OrganizationMember.user_id == User.id)
        .where(
            OrganizationMember.organization_id == company_id,
            func.lower(User.email) == email,
        )
    )


async def update_company_name(db: AsyncSession, company: Entity, name: str) -> Entity:
    company.name = name.strip()
    await db.flush()
    return company


async def update_org_member_role(
    db: AsyncSession, membership: OrganizationMember, role: str
) -> OrganizationMember:
    membership.role = role
    await db.flush()
    return membership


async def delete_org_member(db: AsyncSession, membership: OrganizationMember) -> None:
    await db.delete(membership)
    await db.flush()


async def user_has_any_org(db: AsyncSession, user_id: uuid.UUID) -> bool:
    row = await db.scalar(
        select(OrganizationMember.id).where(OrganizationMember.user_id == user_id)
    )
    return row is not None


async def list_user_memberships(
    db: AsyncSession, user_id: uuid.UUID
) -> list[OrganizationMember]:
    result = await db.scalars(
        select(OrganizationMember).where(OrganizationMember.user_id == user_id)
    )
    return list(result.all())


async def count_org_members(db: AsyncSession, company_id: uuid.UUID) -> int:
    n = await db.scalar(
        select(func.count())
        .select_from(OrganizationMember)
        .where(OrganizationMember.organization_id == company_id)
    )
    return int(n or 0)


async def delete_company(db: AsyncSession, company: Entity) -> None:
    await db.delete(company)
    await db.flush()


async def _rehome_solo_products_to_mine(
    db: AsyncSession,
    *,
    from_company_id: uuid.UUID,
    to_company_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Move all catalog rows onto dest as Mine (ADR 0015). Org SKU wins over Mine dupes."""
    rows = list(
        (
            await db.scalars(select(Product).where(Product.company_id == from_company_id))
        ).all()
    )
    org_rows = [row for row in rows if row.owner_scope == "org"]
    mine_rows = [row for row in rows if row.owner_scope == "user"]
    taken_skus: set[str] = set()
    for row in org_rows:
        row.company_id = to_company_id
        row.owner_scope = "user"
        row.user_id = user_id
        taken_skus.add(row.sku)
    await db.flush()
    for row in mine_rows:
        if row.sku in taken_skus:
            await db.delete(row)
            continue
        row.company_id = to_company_id
        row.user_id = user_id
        taken_skus.add(row.sku)
    await db.flush()


async def clear_bootstrap_solo_org(
    db: AsyncSession, user_id: uuid.UUID, *, dest_company_id: uuid.UUID
) -> bool:
    """ADR 0013/0015: drop a register-bootstrap org so invite accept can proceed.

    Returns True if the user has no membership, or their only membership was
    sole owner of a single-member org (products rehomed to dest Mine, org
    deleted). Returns False if a real team membership blocks accept (caller
    should 409).
    """
    memberships = await list_user_memberships(db, user_id)
    if not memberships:
        return True
    if len(memberships) != 1:
        return False
    membership = memberships[0]
    if membership.role != "owner":
        return False
    if await count_org_members(db, membership.organization_id) != 1:
        return False
    company = await get_company(db, membership.organization_id)
    if company is None:
        return False
    await _rehome_solo_products_to_mine(
        db,
        from_company_id=company.id,
        to_company_id=dest_company_id,
        user_id=user_id,
    )
    await db.delete(membership)
    await db.flush()
    await delete_company(db, company)
    return True


async def create_org_member(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    role: str,
) -> OrganizationMember:
    membership = OrganizationMember(
        user_id=user_id,
        organization_id=company_id,
        role=role,
    )
    db.add(membership)
    await db.flush()
    return membership


async def create_org_invite(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    email: str,
    role: str,
    token_hash: str,
    invited_by: uuid.UUID,
    expires_at: datetime,
) -> OrgInvite:
    invite = OrgInvite(
        organization_id=organization_id,
        email=email,
        role=role,
        token_hash=token_hash,
        invited_by=invited_by,
        expires_at=expires_at,
    )
    db.add(invite)
    await db.flush()
    return invite


async def list_pending_org_invites(
    db: AsyncSession, company_id: uuid.UUID
) -> list[OrgInvite]:
    result = await db.scalars(
        select(OrgInvite)
        .where(
            OrgInvite.organization_id == company_id,
            OrgInvite.accepted_at.is_(None),
            OrgInvite.revoked_at.is_(None),
        )
        .order_by(OrgInvite.created_at.desc())
    )
    return list(result.all())


async def get_org_invite(
    db: AsyncSession, company_id: uuid.UUID, invite_id: uuid.UUID
) -> OrgInvite | None:
    return await db.scalar(
        select(OrgInvite).where(
            OrgInvite.id == invite_id,
            OrgInvite.organization_id == company_id,
        )
    )


async def get_org_invite_by_token_hash(
    db: AsyncSession, token_hash: str
) -> OrgInvite | None:
    return await db.scalar(
        select(OrgInvite)
        .options(selectinload(OrgInvite.organization))
        .where(OrgInvite.token_hash == token_hash)
    )


async def revoke_org_invite(db: AsyncSession, invite: OrgInvite) -> OrgInvite:
    invite.revoked_at = datetime.now(UTC)
    await db.flush()
    return invite


async def accept_org_invite(db: AsyncSession, invite: OrgInvite) -> OrgInvite:
    invite.accepted_at = datetime.now(UTC)
    await db.flush()
    return invite


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


async def list_recent_question_history(
    db: AsyncSession, company_id: uuid.UUID, *, days: int, skip_latest: bool = False
) -> dict[str, list[str]]:
    """Recently served question texts + signal ids (text + trend-combo dedupe)."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    result = await db.scalars(
        select(RecommendedQuestions.questions)
        .where(
            RecommendedQuestions.company_id == company_id,
            RecommendedQuestions.generated_at >= cutoff,
        )
        .order_by(desc(RecommendedQuestions.generated_at))
        .limit(20)
    )
    batches = list(result.all())
    if skip_latest and batches:
        batches = batches[1:]
    texts: list[str] = []
    signal_ids: list[str] = []
    for batch in batches:
        for q in batch or []:
            if not isinstance(q, dict):
                continue
            text = (q.get("text") or "").strip()
            if text:
                texts.append(text)
            for sid in q.get("source_signal_ids") or []:
                if sid and str(sid) not in signal_ids:
                    signal_ids.append(str(sid))
    return {"texts": texts, "signal_ids": signal_ids}


async def list_recent_question_texts(
    db: AsyncSession, company_id: uuid.UUID, *, days: int
) -> list[str]:
    """Question texts served to this company in the last N days (dedupe input)."""
    return (await list_recent_question_history(db, company_id, days=days))["texts"]


async def get_question_item(
    db: AsyncSession, company_id: uuid.UUID, question_id: str
) -> dict | None:
    """Look up one landing-card question in the company's latest cache (handoff)."""
    row = await get_latest_questions(db, company_id)
    if row is None:
        return None
    for q in row.questions or []:
        if isinstance(q, dict) and str(q.get("id") or "") == question_id:
            return q
    return None


async def create_question_run(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    trigger: str,
) -> QuestionRun:
    run = QuestionRun(company_id=company_id, status="running", trigger=trigger)
    db.add(run)
    await db.flush()
    return run


async def finish_question_run(
    db: AsyncSession,
    run: QuestionRun,
    *,
    status: str,
    quality_flags: list[str] | None = None,
    error: str | None = None,
) -> QuestionRun:
    run.status = status
    run.quality_flags = quality_flags or []
    run.error = error
    run.finished_at = datetime.now(UTC)
    await db.flush()
    return run


async def get_active_question_run(db: AsyncSession, company_id: uuid.UUID) -> QuestionRun | None:
    return await db.scalar(
        select(QuestionRun)
        .where(QuestionRun.company_id == company_id, QuestionRun.status == "running")
        .order_by(desc(QuestionRun.started_at))
        .limit(1)
    )


async def get_latest_question_run(db: AsyncSession, company_id: uuid.UUID) -> QuestionRun | None:
    return await db.scalar(
        select(QuestionRun)
        .where(QuestionRun.company_id == company_id)
        .order_by(desc(QuestionRun.started_at))
        .limit(1)
    )


async def list_question_runs(
    db: AsyncSession, company_id: uuid.UUID, *, limit: int = 20
) -> list[QuestionRun]:
    result = await db.scalars(
        select(QuestionRun)
        .where(QuestionRun.company_id == company_id)
        .order_by(desc(QuestionRun.started_at))
        .limit(limit)
    )
    return list(result.all())


async def save_question_node_step(
    db: AsyncSession,
    *,
    run_id: uuid.UUID,
    seq: int,
    node: str,
    input: dict,
    output: dict,
) -> QuestionNodeStep:
    step = QuestionNodeStep(run_id=run_id, seq=seq, node=node, input=input, output=output)
    db.add(step)
    await db.flush()
    return step


async def list_question_node_steps(db: AsyncSession, run_id: uuid.UUID) -> list[QuestionNodeStep]:
    result = await db.scalars(
        select(QuestionNodeStep)
        .where(QuestionNodeStep.run_id == run_id)
        .order_by(QuestionNodeStep.seq)
    )
    return list(result.all())


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


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search_user_sessions(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    q: str,
    company_id: uuid.UUID | None = None,
    limit: int = 40,
) -> list[tuple[Session, str | None, str | None, dict | None]]:
    """Search everything the user can see in a session (case-insensitive):
    title, chat messages, brief + current draft (``sessions.state`` JSONB),
    and all draft revisions (``preview_drafts.copy`` JSONB).

    Returns (session, first-user preview, first matching message content,
    latest matching draft copy). Flat newest-first order — pinned grouping
    is a browse-mode concern.
    """
    pattern = f"%{_escape_like(q)}%"
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
    content_match = SessionMessage.content.ilike(pattern, escape="\\")
    first_match = (
        select(SessionMessage.content)
        .where(SessionMessage.session_id == Session.id, content_match)
        .order_by(SessionMessage.created_at.asc())
        .limit(1)
        .correlate(Session)
        .scalar_subquery()
    )
    state_match = cast(Session.state, Text).ilike(pattern, escape="\\")
    draft_copy_match = cast(PreviewDraft.copy, Text).ilike(pattern, escape="\\")
    latest_matching_draft = (
        select(PreviewDraft.copy)
        .where(PreviewDraft.session_id == Session.id, draft_copy_match)
        .order_by(PreviewDraft.revision.desc())
        .limit(1)
        .correlate(Session)
        .scalar_subquery()
    )
    stmt = (
        select(Session, first_user, first_match, latest_matching_draft)
        .where(Session.user_id == user_id)
        .where(
            or_(
                Session.title.ilike(pattern, escape="\\"),
                exists(
                    select(SessionMessage.id).where(
                        SessionMessage.session_id == Session.id,
                        content_match,
                    )
                ),
                state_match,
                exists(
                    select(PreviewDraft.id).where(
                        PreviewDraft.session_id == Session.id,
                        draft_copy_match,
                    )
                ),
            )
        )
        .order_by(desc(Session.updated_at))
        .limit(limit)
    )
    if company_id is not None:
        stmt = stmt.where(Session.company_id == company_id)
    rows = (await db.execute(stmt)).all()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


def touch_session(session: Session) -> None:
    """Bump recency so history lists reorder after a turn.

    ``updated_at`` uses SQLAlchemy ``onupdate``, which only fires when the ORM
    row is dirty. A follow-up chat turn often writes an equal JSONB ``state``,
    so the row is skipped and an old session stays buried.
    """
    session.updated_at = datetime.now(UTC)


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
    created_at: datetime | None = None,
) -> SessionMessage:
    row = SessionMessage(
        session_id=session_id,
        role=role,
        content=content,
        metadata_=metadata or {},
    )
    if created_at is not None:
        # Fork copies keep the original timeline (ADR 0017); without this every
        # copied row shares one transaction timestamp and ordering is unstable.
        row.created_at = created_at
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


async def count_session_forks(db: AsyncSession, session_id: uuid.UUID) -> int:
    """How many sessions were forked directly from this session (ADR 0017)."""
    return int(
        await db.scalar(
            select(func.count(Session.id)).where(Session.forked_from_session_id == session_id)
        )
        or 0
    )


async def list_forks_for_messages(
    db: AsyncSession, message_ids: list[uuid.UUID]
) -> list[Session]:
    """Sessions forked from any of these messages, oldest first (ADR 0017)."""
    if not message_ids:
        return []
    rows = await db.scalars(
        select(Session)
        .where(Session.forked_from_message_id.in_(message_ids))
        .order_by(Session.created_at)
    )
    return list(rows.all())


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
    created_at: datetime | None = None,
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
    if created_at is not None:
        row.created_at = created_at
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


async def get_preview_draft_as_of(
    db: AsyncSession, session_id: uuid.UUID, as_of: datetime
) -> PreviewDraft | None:
    """Latest draft revision that existed at `as_of` (ADR 0017 time-aligned fork)."""
    return await db.scalar(
        select(PreviewDraft)
        .where(
            PreviewDraft.session_id == session_id,
            PreviewDraft.created_at <= as_of,
        )
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


async def get_latest_publish_receipt(
    db: AsyncSession, session_id: uuid.UUID
) -> ToolReceipt | None:
    return await db.scalar(
        select(ToolReceipt)
        .where(
            ToolReceipt.session_id == session_id,
            ToolReceipt.tool_name == "publish_social_post",
        )
        .order_by(ToolReceipt.created_at.desc())
        .limit(1)
    )


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
    create_only: bool = False,
) -> tuple[Product, bool]:
    """Upsert by SKU. Returns (row, created). Reactivates archived rows.

    When ``create_only`` is True, an existing SKU is returned unchanged
    (``created=False``) so callers can 409 instead of silently replacing.

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
        if create_only:
            return existing, False
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


async def get_scoped_product_by_sku(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    owner_scope: str,
    user_id: uuid.UUID | None,
    sku: str,
    exclude_id: uuid.UUID | None = None,
) -> Product | None:
    stmt = select(Product).where(
        Product.company_id == company_id,
        Product.owner_scope == owner_scope,
        Product.sku == sku,
    )
    if owner_scope == "user":
        stmt = stmt.where(Product.user_id == user_id)
    else:
        stmt = stmt.where(Product.user_id.is_(None))
    if exclude_id is not None:
        stmt = stmt.where(Product.id != exclude_id)
    return await db.scalar(stmt)


async def next_unique_sku(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    owner_scope: str,
    user_id: uuid.UUID | None,
    preferred: str,
    exclude_id: uuid.UUID | None = None,
) -> str:
    base = preferred.strip() or "SKU"
    stmt = select(Product.sku).where(
        Product.company_id == company_id,
        Product.owner_scope == owner_scope,
        or_(Product.sku == base, Product.sku.startswith(f"{base}-")),
    )
    if owner_scope == "user":
        stmt = stmt.where(Product.user_id == user_id)
    else:
        stmt = stmt.where(Product.user_id.is_(None))
    if exclude_id is not None:
        stmt = stmt.where(Product.id != exclude_id)
    taken = set(await db.scalars(stmt))
    return allocate_unique_sku(preferred, taken)


async def update_manual_product(
    db: AsyncSession,
    product: Product,
    *,
    sku: str,
    name: str,
    notes: str = "",
) -> Product:
    """Patch name / SKU / notes; keep other profile keys (import columns)."""
    from sqlalchemy.orm.attributes import flag_modified

    profile = {
        str(key): value if isinstance(value, str) else str(value)
        for key, value in (product.profile or {}).items()
        if value is not None and str(value).strip()
    }
    profile["name"] = name
    profile["sku"] = sku
    if notes:
        profile["notes"] = notes
    else:
        profile.pop("notes", None)

    search_document = build_search_document(profile, sku=sku, name=name)
    vecs = embed_texts([search_document])
    product.sku = sku
    product.name = name
    product.profile = profile
    product.search_document = search_document
    product.status = "active"
    if vecs:
        product.embedding = vecs[0]
    flag_modified(product, "profile")
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
        create_only=True,
    )


async def get_org_product_by_sku(
    db: AsyncSession, *, company_id: uuid.UUID, sku: str
) -> Product | None:
    return await db.scalar(
        select(Product).where(
            Product.company_id == company_id,
            Product.owner_scope == "org",
            Product.sku == sku,
            Product.status == "active",
        )
    )


async def get_pending_proposal_by_sku(
    db: AsyncSession, *, company_id: uuid.UUID, sku: str
) -> ProductProposal | None:
    return await db.scalar(
        select(ProductProposal).where(
            ProductProposal.company_id == company_id,
            ProductProposal.sku == sku,
            ProductProposal.status == "pending",
        )
    )


async def pending_proposal_ids_for_skus(
    db: AsyncSession, *, company_id: uuid.UUID, skus: list[str]
) -> dict[str, uuid.UUID]:
    if not skus:
        return {}
    rows = await db.execute(
        select(ProductProposal.sku, ProductProposal.id).where(
            ProductProposal.company_id == company_id,
            ProductProposal.status == "pending",
            ProductProposal.sku.in_(skus),
        )
    )
    return {sku: pid for sku, pid in rows.all()}


async def create_product_proposal(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    source_product: Product,
    proposed_by: uuid.UUID,
) -> ProductProposal:
    row = ProductProposal(
        company_id=company_id,
        source_product_id=source_product.id,
        proposed_by=proposed_by,
        sku=source_product.sku,
        name=source_product.name,
        profile=dict(source_product.profile or {}),
        status="pending",
    )
    db.add(row)
    await db.flush()
    return row


async def get_product_proposal(
    db: AsyncSession, *, company_id: uuid.UUID, proposal_id: uuid.UUID
) -> ProductProposal | None:
    return await db.scalar(
        select(ProductProposal).where(
            ProductProposal.id == proposal_id,
            ProductProposal.company_id == company_id,
        )
    )


async def list_product_proposals(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    status: str | None = "pending",
) -> list[ProductProposal]:
    stmt = select(ProductProposal).where(ProductProposal.company_id == company_id)
    if status is not None:
        stmt = stmt.where(ProductProposal.status == status)
    stmt = stmt.order_by(ProductProposal.created_at.desc())
    result = await db.scalars(stmt)
    return list(result.all())


async def mark_proposal_reviewed(
    db: AsyncSession,
    proposal: ProductProposal,
    *,
    status: str,
    reviewed_by: uuid.UUID,
) -> ProductProposal:
    proposal.status = status
    proposal.reviewed_by = reviewed_by
    proposal.reviewed_at = datetime.now(UTC)
    await db.flush()
    return proposal


ROUTING_SLOT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("cheap", "cheap_model_id"),
    ("medium", "medium_model_id"),
    ("strong", "strong_model_id"),
    ("image", "image_model_id"),
)


async def get_byok_routing(db: AsyncSession, company_id: uuid.UUID) -> ByokRouting | None:
    return await db.get(ByokRouting, company_id)


async def list_byok_providers(db: AsyncSession, company_id: uuid.UUID) -> list[ByokProvider]:
    stmt = (
        select(ByokProvider)
        .where(ByokProvider.company_id == company_id)
        .order_by(ByokProvider.created_at.asc())
    )
    result = await db.scalars(stmt)
    return list(result.all())


async def get_byok_provider(
    db: AsyncSession, company_id: uuid.UUID, provider_id: uuid.UUID
) -> ByokProvider | None:
    stmt = select(ByokProvider).where(
        ByokProvider.company_id == company_id,
        ByokProvider.id == provider_id,
    )
    return await db.scalar(stmt)


async def create_byok_provider(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    label: str,
    provider_type: str,
    api_key_encrypted: str,
    key_last4: str,
    api_base: str | None,
    created_by: uuid.UUID | None,
) -> ByokProvider:
    row = ByokProvider(
        company_id=company_id,
        label=label,
        provider_type=provider_type,
        api_key_encrypted=api_key_encrypted,
        key_last4=key_last4,
        api_base=api_base,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(row)
    await db.flush()
    return row


async def list_byok_models(db: AsyncSession, company_id: uuid.UUID) -> list[ByokModel]:
    stmt = (
        select(ByokModel)
        .where(ByokModel.company_id == company_id)
        .options(selectinload(ByokModel.provider))
        .order_by(ByokModel.created_at.asc())
    )
    result = await db.scalars(stmt)
    return list(result.all())


async def list_byok_models_for_provider(
    db: AsyncSession, company_id: uuid.UUID, provider_id: uuid.UUID
) -> list[ByokModel]:
    stmt = select(ByokModel).where(
        ByokModel.company_id == company_id,
        ByokModel.provider_id == provider_id,
    )
    result = await db.scalars(stmt)
    return list(result.all())


async def get_byok_model(
    db: AsyncSession, company_id: uuid.UUID, model_pk: uuid.UUID
) -> ByokModel | None:
    stmt = (
        select(ByokModel)
        .where(ByokModel.company_id == company_id, ByokModel.id == model_pk)
        .options(selectinload(ByokModel.provider))
    )
    return await db.scalar(stmt)


async def get_byok_model_by_provider_model(
    db: AsyncSession,
    company_id: uuid.UUID,
    provider_id: uuid.UUID,
    model_id: str,
) -> ByokModel | None:
    stmt = (
        select(ByokModel)
        .where(
            ByokModel.company_id == company_id,
            ByokModel.provider_id == provider_id,
            ByokModel.model_id == model_id,
        )
        .options(selectinload(ByokModel.provider))
    )
    return await db.scalar(stmt)


async def create_byok_model(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    provider_id: uuid.UUID,
    model_id: str,
    capability: str,
    capability_source: str,
) -> ByokModel:
    row = ByokModel(
        company_id=company_id,
        provider_id=provider_id,
        model_id=model_id,
        capability=capability,
        capability_source=capability_source,
    )
    db.add(row)
    await db.flush()
    return row


async def upsert_byok_routing(
    db: AsyncSession,
    company_id: uuid.UUID,
    *,
    cheap_model_id: uuid.UUID | None,
    medium_model_id: uuid.UUID | None,
    strong_model_id: uuid.UUID | None,
    image_model_id: uuid.UUID | None,
) -> ByokRouting:
    row = await get_byok_routing(db, company_id)
    if row is None:
        row = ByokRouting(
            company_id=company_id,
            cheap_model_id=cheap_model_id,
            medium_model_id=medium_model_id,
            strong_model_id=strong_model_id,
            image_model_id=image_model_id,
        )
        db.add(row)
    else:
        row.cheap_model_id = cheap_model_id
        row.medium_model_id = medium_model_id
        row.strong_model_id = strong_model_id
        row.image_model_id = image_model_id
    await db.flush()
    return row


def routing_slots_for_model(routing: ByokRouting | None, model_pk: uuid.UUID) -> list[str]:
    if routing is None:
        return []
    return [
        slot
        for slot, column in ROUTING_SLOT_COLUMNS
        if getattr(routing, column) == model_pk
    ]


def routing_slots_for_models(
    routing: ByokRouting | None, model_pks: set[uuid.UUID]
) -> list[str]:
    if routing is None or not model_pks:
        return []
    return [
        slot
        for slot, column in ROUTING_SLOT_COLUMNS
        if getattr(routing, column) in model_pks
    ]


async def list_byok_models_by_ids(
    db: AsyncSession,
    company_id: uuid.UUID,
    model_ids: list[uuid.UUID],
) -> list[ByokModel]:
    if not model_ids:
        return []
    stmt = select(ByokModel).where(
        ByokModel.company_id == company_id,
        ByokModel.id.in_(model_ids),
    )
    result = await db.scalars(stmt)
    return list(result.all())


async def list_byok_providers_by_ids(
    db: AsyncSession,
    company_id: uuid.UUID,
    provider_ids: list[uuid.UUID],
) -> list[ByokProvider]:
    if not provider_ids:
        return []
    stmt = select(ByokProvider).where(
        ByokProvider.company_id == company_id,
        ByokProvider.id.in_(provider_ids),
    )
    result = await db.scalars(stmt)
    return list(result.all())


async def get_social_account(
    db: AsyncSession, company_id: uuid.UUID, platform: str = "instagram"
) -> SocialAccount | None:
    return await db.scalar(
        select(SocialAccount).where(
            SocialAccount.company_id == company_id,
            SocialAccount.platform == platform,
        )
    )


async def get_social_account_by_id(db: AsyncSession, row_id: uuid.UUID) -> SocialAccount | None:
    return await db.get(SocialAccount, row_id)


def social_account_is_connected(row: SocialAccount | None) -> bool:
    """True when Confirm can publish with this row (not an OAuth placeholder)."""
    if row is None:
        return False
    return bool((row.ig_user_id or "").strip() and (row.token_last4 or "").strip())


async def list_social_accounts(
    db: AsyncSession, company_id: uuid.UUID
) -> list[SocialAccount]:
    stmt = (
        select(SocialAccount)
        .where(SocialAccount.company_id == company_id)
        .order_by(SocialAccount.created_at.asc())
    )
    result = await db.scalars(stmt)
    return list(result.all())


async def upsert_social_account(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    platform: str,
    ig_user_id: str,
    access_token_encrypted: str,
    token_last4: str,
    expires_at: datetime | None,
    created_by: uuid.UUID | None,
) -> SocialAccount:
    row = await get_social_account(db, company_id, platform)
    if row is None:
        row = SocialAccount(
            company_id=company_id,
            platform=platform,
            ig_user_id=ig_user_id,
            access_token_encrypted=access_token_encrypted,
            token_last4=token_last4,
            expires_at=expires_at,
            created_by=created_by,
            last_error_kind=None,
        )
        db.add(row)
    else:
        row.ig_user_id = ig_user_id
        row.access_token_encrypted = access_token_encrypted
        row.token_last4 = token_last4
        row.expires_at = expires_at
        row.last_error_kind = None
        row.last_verified_at = None
    await db.flush()
    return row



def social_pending_state_clear(row: SocialAccount) -> None:
    """Clear OAuth pending state after the exchange ends (success or failure)."""
    row.oauth_connect_state = None


async def abort_social_oauth_row(db: AsyncSession, row: SocialAccount) -> None:
    """Drop pending OAuth without disconnecting an already-linked account."""
    if social_account_is_connected(row):
        social_pending_state_clear(row)
    else:
        await db.delete(row)
    await db.flush()


async def cancel_social_oauth(
    db: AsyncSession, company_id: uuid.UUID, platform: str = "instagram"
) -> None:
    """Editor abort of an in-flight connect (timeout, cancel, popup closed)."""
    row = await get_social_account(db, company_id, platform)
    if row is None or not row.oauth_connect_state:
        return
    await abort_social_oauth_row(db, row)


async def find_social_account_by_oauth_state(
    db: AsyncSession, state: str
) -> SocialAccount | None:
    """Resolve the SocialAccount row from a callback state (row_id before the colon)."""
    try:
        row_id_str, _ = state.split(":", 1)
        row_uuid = uuid.UUID(row_id_str)
    except (ValueError, AttributeError):
        return None
    return await get_social_account_by_id(db, row_uuid)


async def clear_social_oauth_state_for_state(
    db: AsyncSession, state: str | None
) -> None:
    """Clear pending OAuth state after a failed / aborted callback.

    First-time connect leaves an empty placeholder — delete it so list /
    Confirm stay not-connected. Rotate keeps the already-connected row.
    """
    if not state:
        return
    row = await find_social_account_by_oauth_state(db, state)
    if row is None:
        return
    await abort_social_oauth_row(db, row)


async def delete_social_account(
    db: AsyncSession, company_id: uuid.UUID, platform: str = "instagram"
) -> bool:
    row = await get_social_account(db, company_id, platform)
    if row is None:
        return False
    await db.delete(row)
    return True
