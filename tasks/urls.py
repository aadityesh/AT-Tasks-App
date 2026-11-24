from rest_framework.routers import DefaultRouter
from .views import TaskModelView
from django.urls import path

router = DefaultRouter()
router.register("tasks", TaskModelView)

urlpatterns = [
    path("priority/<str:level>/", TaskModelView.as_view({"get": "get_tasks_by_priority"}))
    ] + router.urls
