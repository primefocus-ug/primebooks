"""
sync/models.py
==============
Tracks sync sessions per tenant for audit and debugging.
Lightweight — just enough to answer "when did this desktop last sync?"
"""
import uuid
from django.db import models


class SyncSession(models.Model):
    """
    One row per sync cycle (push or pull) from a desktop client.
    Lives in the tenant schema.
    """
    id           = models.AutoField(primary_key=True)
    session_id   = models.UUIDField(default=uuid.uuid4, unique=True)
    user         = models.ForeignKey(
        "accounts.CustomUser",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="sync_sessions",
    )
    direction    = models.CharField(max_length=10, choices=[("pull", "Pull"), ("push", "Push")])
    started_at   = models.DateTimeField(auto_now_add=True)
    finished_at  = models.DateTimeField(null=True, blank=True)
    records_in   = models.IntegerField(default=0)   # pushed by client
    records_out  = models.IntegerField(default=0)   # pulled by client
    errors       = models.IntegerField(default=0)
    client_ip    = models.GenericIPAddressField(null=True, blank=True)
    schema_name  = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["schema_name", "started_at"]),
            models.Index(fields=["user", "started_at"]),
        ]

    def __str__(self):
        return f"SyncSession({self.direction}, {self.started_at:%Y-%m-%d %H:%M})"