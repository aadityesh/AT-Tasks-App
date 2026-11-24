from django.db import models

PRIORITY = {
    "low": "low",
    "medium": "medium",
    "high": "high",
}


class Task(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    completed = models.BooleanField(default=False)

    due_date = models.DateField(null=True, blank=True)
    priority = models.CharField(choices=PRIORITY, default="medium")
    parent = models.ForeignKey("self", null=True,           blank=True,
                               on_delete=models.CASCADE, related_name="subtasks")

    updated_at = models.DateField(auto_now=True)
    created_at = models.DateField(auto_now_add=True)
