from rest_framework import serializers
from .models import Task

class TaskSerializer(serializers.ModelSerializer):

    class Meta:
        model = Task
        fields = "__all__"

    def validate_parent(self, parent):
        # parent is already a Task object (or None); DRF looked it up from the id
        if parent is None:
            return parent
        if parent.parent_id is not None:
            raise serializers.ValidationError("a subtask cannot have subtasks")
        if self.instance and parent.id == self.instance.id:
            raise serializers.ValidationError("a task cannot be its own parent")
        if self.instance and self.instance.subtasks.exists():
            raise serializers.ValidationError("a task with subtasks cannot become a subtask")
        return parent
