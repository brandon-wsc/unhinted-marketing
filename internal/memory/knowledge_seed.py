"""Seed default marketing personas into PostgreSQL."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from internal.memory.models import Entity

DEFAULT_PERSONAS: list[dict] = [
    {
        "slug": "hk-young-professional",
        "name": "HK Young Professional (25–34)",
        "profile": {
            "label": "HK young professional (25-34)",
            "locale": "zh-HK",
            "description": (
                "Urban office worker in Hong Kong. Active on Instagram and Threads. "
                "Values authenticity, concise messaging, and mobile-first content."
            ),
            "content_preferences": [
                "Short-form video and carousel posts",
                "Bilingual (繁中 + English) captions",
                "Trend-aware but skeptical of hard sells",
            ],
            "marketing_angles": [
                "Highlight convenience and value without sounding corporate",
                "Use local cultural references sparingly but precisely",
            ],
        },
    },
    {
        "slug": "hk-parent-shopper",
        "name": "HK Parent Shopper (30–45)",
        "profile": {
            "label": "HK parent shopper (30-45)",
            "locale": "zh-HK",
            "description": (
                "Family-focused consumer balancing quality, safety, and price. "
                "Researches on Google and shares deals in WhatsApp groups."
            ),
            "content_preferences": [
                "Practical tips and comparison-style posts",
                "Trust signals: reviews, certifications, local availability",
                "Weekend-friendly posting windows",
            ],
            "marketing_angles": [
                "Emphasize family benefit and long-term value",
                "Clear CTA with pickup/delivery options when relevant",
            ],
        },
    },
]


async def ensure_default_personas(db: AsyncSession) -> None:
    for persona in DEFAULT_PERSONAS:
        existing = await db.scalar(select(Entity).where(Entity.slug == persona["slug"]))
        if existing:
            continue
        db.add(
            Entity(
                entity_type="persona",
                slug=persona["slug"],
                name=persona["name"],
                profile=persona["profile"],
            )
        )
    await db.flush()
