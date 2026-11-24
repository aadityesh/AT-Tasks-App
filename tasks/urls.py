from rest_framework.routers import DefaultRouter
from .views import TaskModelView

router = DefaultRouter()
router.register("tasks", TaskModelView)

urlpatterns = router.urls
