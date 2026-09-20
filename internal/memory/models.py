import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from internal.memory.embeddings import EMBEDDING_DIM
from internal.memory.pgvector_type import Vector


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # ADR 0005 numeric privilege ladder (MEMBER=3 default; see internal/auth/roles.py)
    platform_level: Mapped[int] = mapped_column(Integer, default=3, server_default="3", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    memberships: Mapped[list["OrganizationMember"]] = relationship(back_populates="user")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user")


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    okf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    memberships: Mapped[list["OrganizationMember"]] = relationship(back_populates="organization")
    invites: Mapped[list["OrgInvite"]] = relationship(back_populates="organization")


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", name="uq_org_member"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="memberships")
    organization: Mapped["Entity"] = relationship(back_populates="memberships")


class OrgInvite(Base):
    __tablename__ = "org_invites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Entity"] = relationship(back_populates="invites")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class RawNewsEvent(Base):
    __tablename__ = "raw_news_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_id: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    region: Mapped[str] = mapped_column(String(10), nullable=False, default="HK")
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Edge(Base):
    __tablename__ = "edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    to_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    edge_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_signal_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RecommendedQuestions(Base):
    __tablename__ = "recommended_questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    questions: Mapped[list] = mapped_column(JSONB, nullable=False)
    source_signal_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuestionRun(Base):
    """One recommended-questions worker graph run (ADR 0018)."""

    __tablename__ = "question_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # running | succeeded | failed
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)  # get_miss | refresh | scheduler
    quality_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuestionNodeStep(Base):
    """One question-graph node invocation within a run (ADR 0018; mirrors session_node_steps)."""

    __tablename__ = "question_node_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("question_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    node: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    input: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="CHAT")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Fork lineage (ADR 0017). forked_from_message_id has no FK: messages
    # cascade-delete with their session, and the lineage label must survive that.
    forked_from_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    forked_from_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    forked_from_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # passive_deletes: rely on the FK ON DELETE CASCADE; ORM nullification would
    # violate the NOT NULL session_id on child rows.
    messages: Mapped[list["SessionMessage"]] = relationship(
        back_populates="session", passive_deletes=True
    )
    drafts: Mapped[list["PreviewDraft"]] = relationship(
        back_populates="session", passive_deletes=True
    )
    images: Mapped[list["PreviewImage"]] = relationship(
        back_populates="session", passive_deletes=True
    )


class SessionMessage(Base):
    __tablename__ = "session_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["Session"] = relationship(back_populates="messages")


class PreviewImage(Base):
    """Append-only image asset version for a session (ADR 0008)."""

    __tablename__ = "preview_images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="primary")
    format: Mapped[str] = mapped_column(String(40), nullable=False, default="single")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="ready")
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["Session"] = relationship(back_populates="images")


class PreviewDraft(Base):
    __tablename__ = "preview_drafts"
    __table_args__ = (
        UniqueConstraint("session_id", "revision", name="uq_preview_drafts_session_revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    copy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Ordered refs into preview_images (ADR 0008). Empty = no media.
    media_ids: Mapped[list] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list
    )
    platform: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_signal_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    approval_token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["Session"] = relationship(back_populates="drafts")


class ToolReceipt(Base):
    __tablename__ = "tool_receipts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LlmCallRecord(Base):
    """One provider call (ADR 0005) — the debug unit for prompt/node fine-tuning."""

    __tablename__ = "llm_call_records"
    __table_args__ = (
        CheckConstraint(
            "key_source IS NULL OR key_source IN ('env', 'org')",
            name="ck_llm_call_records_key_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Correlation: who/where. Nullable + SET NULL so records survive entity deletion.
    caller: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    node: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # One graph.ainvoke / resume turn — joins to session_node_steps.
    turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    # Request
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # chat_json | chat_text | image
    tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Response + metrics
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Diagnosis — the "which step went wrong" fields
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # ok | provider_error | cancelled | empty_response | error
    error: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    parse_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # ADR 0020 — which key paid for this call. Never the raw key / ciphertext.
    key_source: Mapped[str | None] = mapped_column(String(8), nullable=True)  # env | org
    key_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class SessionNodeStep(Base):
    """One LangGraph node invocation within a turn (admin Trace viewer)."""

    __tablename__ = "session_node_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    turn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    node: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    mode_in: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mode_out: Mapped[str | None] = mapped_column(String(40), nullable=True)
    intent_out: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_signal_ids_in: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_signal_ids_out: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    output_keys: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    output: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Product(Base):
    """Company or personal product catalog row (knowledge COLLECT K3/K3b)."""

    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_scope: Mapped[str] = mapped_column(String(10), nullable=False)  # org | user
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    sku: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    search_document: Mapped[str] = mapped_column(Text, nullable=False, default="")
    profile: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProductProposal(Base):
    """Mine → org product proposal (knowledge K6 / ADR 0011)."""

    __tablename__ = "product_proposals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    sku: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    profile: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ByokProvider(Base):
    """Org LLM provider credential (ADR 0020). Raw key is Fernet-encrypted."""

    __tablename__ = "byok_providers"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_byok_providers_id_company"),
        CheckConstraint(
            "provider_type IN ('openai', 'anthropic', 'openai_compatible', 'gemini', 'vertex_ai')",
            name="ck_byok_providers_type",
        ),
        CheckConstraint(
            "provider_type <> 'openai_compatible' OR "
            "(api_base IS NOT NULL AND btrim(api_base) <> '')",
            name="ck_byok_providers_api_base",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    key_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    api_base: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    models: Mapped[list["ByokModel"]] = relationship(
        back_populates="provider",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ByokModel(Base):
    """Org-registered model id against a provider key (ADR 0020)."""

    __tablename__ = "byok_models"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_byok_models_id_company"),
        UniqueConstraint("provider_id", "model_id", name="uq_byok_models_provider_model"),
        CheckConstraint(
            "capability IN ('chat', 'image')",
            name="ck_byok_models_capability",
        ),
        CheckConstraint(
            "capability_source IN ('provider_metadata', 'inferred', 'manual')",
            name="ck_byok_models_capability_source",
        ),
        ForeignKeyConstraint(
            ["provider_id", "company_id"],
            ["byok_providers.id", "byok_providers.company_id"],
            ondelete="CASCADE",
            name="fk_byok_models_provider_company",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    capability: Mapped[str] = mapped_column(String(16), nullable=False)
    capability_source: Mapped[str] = mapped_column(String(32), nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    provider: Mapped["ByokProvider"] = relationship(back_populates="models")


class ByokRouting(Base):
    """Per-company cheap/medium/strong/image slot assignment (ADR 0020)."""

    __tablename__ = "byok_routing"
    __table_args__ = (
        ForeignKeyConstraint(
            ["cheap_model_id", "company_id"],
            ["byok_models.id", "byok_models.company_id"],
            ondelete="SET NULL (cheap_model_id)",
            name="fk_byok_routing_cheap",
        ),
        ForeignKeyConstraint(
            ["medium_model_id", "company_id"],
            ["byok_models.id", "byok_models.company_id"],
            ondelete="SET NULL (medium_model_id)",
            name="fk_byok_routing_medium",
        ),
        ForeignKeyConstraint(
            ["strong_model_id", "company_id"],
            ["byok_models.id", "byok_models.company_id"],
            ondelete="SET NULL (strong_model_id)",
            name="fk_byok_routing_strong",
        ),
        ForeignKeyConstraint(
            ["image_model_id", "company_id"],
            ["byok_models.id", "byok_models.company_id"],
            ondelete="SET NULL (image_model_id)",
            name="fk_byok_routing_image",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    cheap_model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    medium_model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    strong_model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    image_model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SocialAccount(Base):
    """Org social platform credential for real publish (ADR 0022).

    Raw access token is Fernet-encrypted under BYOK_ENCRYPTION_KEY, same
    posture as ByokProvider. Never serialize the raw token — token_last4 only.
    """

    __tablename__ = "social_accounts"
    __table_args__ = (
        UniqueConstraint("company_id", "platform", name="uq_social_accounts_company_platform"),
        CheckConstraint(
            "platform IN ('instagram')",
            name="ck_social_accounts_platform",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    ig_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    token_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Instagram Login connect (ADR 0022 OAuth slice)
    # JSON-encrypted {row_id, csrf_token, started_at} while the exchange is in flight.
    oauth_connect_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StorageConfig(Base):
    """Active media backend + S3 credentials (ADR 0025). Deployment-wide v1."""

    __tablename__ = "storage_configs"
    __table_args__ = (
        CheckConstraint("backend IN ('local', 's3')", name="ck_storage_configs_backend"),
        Index(
            "uq_storage_configs_one_active",
            "active",
            unique=True,
            postgresql_where=text("active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Unused in v1 (deployment-wide); present so a later ADR can split buckets.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    backend: Mapped[str] = mapped_column(String(16), nullable=False)
    bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    endpoint_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    region: Mapped[str] = mapped_column(String(64), nullable=False, default="us-east-1")
    public_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    access_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    secret_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    seeded_from_env: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    active: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StorageMigration(Base):
    """Leased local→S3 copy (ADR 0025). At most one in-flight row."""

    __tablename__ = "storage_migrations"
    __table_args__ = (
        CheckConstraint(
            "state IN ("
            "'validating', 'copying', 'verifying', 'ready_to_flip', "
            "'flipping', 'completed', 'cleaning', 'done', 'failed'"
            ")",
            name="ck_storage_migrations_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="validating")
    target_config_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("storage_configs.id", ondelete="SET NULL"), nullable=True
    )
    source_config_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("storage_configs.id", ondelete="SET NULL"), nullable=True
    )
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_keys: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MigrationDoneKey(Base):
    """Per-key copy truth for an in-flight migrate (ADR 0025)."""

    __tablename__ = "migration_done_keys"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    migrated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class InstanceSettings(Base):
    """Deployment-wide singleton settings (ADR 0026). Exactly one row (id=1).

    `setup_completed_at IS NULL` on on-prem means the first-run wizard is
    pending; env values only seed the row — this table is the source of truth.
    """

    __tablename__ = "instance_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_instance_settings_singleton"),
        CheckConstraint(
            "email_backend IN ('link', 'smtp', 'console')",
            name="ck_instance_settings_email_backend",
        ),
        CheckConstraint(
            "meta_oauth_mode IN ('byo', 'relay')",
            name="ck_instance_settings_meta_oauth_mode",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    setup_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    web_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_backend: Mapped[str] = mapped_column(
        String(16), nullable=False, default="link", server_default="link"
    )
    email_from: Mapped[str | None] = mapped_column(String(320), nullable=True)
    smtp_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    smtp_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_password_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    smtp_tls: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # ADR 0032 — BYO Meta app creds; env seeds, portal wins. Empty string
    # meta_app_id means "cleared in the portal" (NULL = never set, env may seed).
    meta_app_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta_app_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_app_secret_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    meta_oauth_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="byo", server_default="byo"
    )
    # ADR 0032 §3 — relay opt-in: vendor relay base URL + the REGISTRY slug
    # the relay maps to this install's web_base_url (generated at seed).
    meta_oauth_relay_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    meta_oauth_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
