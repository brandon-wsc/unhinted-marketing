"""Notification delivery seams (invite email, password reset later)."""

from internal.notify.invites import send_invite_email

__all__ = ["send_invite_email"]
