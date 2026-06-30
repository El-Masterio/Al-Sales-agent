"""
app/workers/celery_app.py
=========================
Celery application instance + beat schedule.

The beat schedule drives the autonomous behavior of the sales agent:
  - Every 15 min: process due follow-ups
  - Every 10 min: research newly-added unresearched leads
  - Every 5 min:  dispatch initial outreach for ready leads in active campaigns
  - Every 5 min:  classify any unclassified replies (safety net for missed webhooks)
  - Every 10 min: send meeting reminders
  - Nightly:      aggregate daily stats, clean expired memory
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "ai_sales_agent",
    broker=settings.REDIS_CELERY_BROKER,
    backend=settings.REDIS_CELERY_BACKEND,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
    task_default_retry_delay=settings.CELERY_RETRY_BACKOFF,
    task_max_retries=settings.CELERY_MAX_RETRIES,
    result_expires=3600,
)

# ── Beat schedule — the autonomous heartbeat ──────────────────────────────────
celery_app.conf.beat_schedule = {
    "process-due-followups": {
        "task": "app.workers.tasks.process_due_followups_task",
        "schedule": crontab(minute="*/15"),
    },
    "research-new-leads": {
        "task": "app.workers.tasks.research_new_leads_task",
        "schedule": crontab(minute="*/10"),
    },
    "dispatch-initial-outreach": {
        "task": "app.workers.tasks.dispatch_initial_outreach_task",
        "schedule": crontab(minute="*/5"),
    },
    "classify-pending-replies": {
        "task": "app.workers.tasks.classify_pending_replies_task",
        "schedule": crontab(minute="*/5"),
    },
    "send-meeting-reminders": {
        "task": "app.workers.tasks.send_meeting_reminders_task",
        "schedule": crontab(minute="*/10"),
    },
    "propose-meetings-to-interested": {
        "task": "app.workers.tasks.propose_meetings_task",
        "schedule": crontab(minute="*/15"),
    },
    "aggregate-daily-stats": {
        "task": "app.workers.tasks.aggregate_daily_stats_task",
        "schedule": crontab(hour=0, minute=30),
    },
    "cleanup-expired-memory": {
        "task": "app.workers.tasks.cleanup_expired_memory_task",
        "schedule": crontab(hour=3, minute=0),
    },
    "generate-daily-report": {
        "task": "app.workers.tasks.generate_daily_report_task",
        "schedule": crontab(hour=8, minute=0),
    },
}
