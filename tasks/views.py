import re
from django.db import transaction
from django.shortcuts import render
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.status import HTTP_201_CREATED, HTTP_400_BAD_REQUEST,  HTTP_200_OK, HTTP_404_NOT_FOUND, HTTP_422_UNPROCESSABLE_ENTITY, HTTP_502_BAD_GATEWAY
from .serializers import TaskSerializer
from .models import Task
from .ai import parse_task_text
from rest_framework.pagination import PageNumberPagination
from rest_framework.filters import OrderingFilter, SearchFilter
from django_filters.rest_framework.backends import DjangoFilterBackend
from rest_framework.decorators import api_view
# {key: {"path": ..., "body": ..., "response": {"data": ..., "status": ...}}}
IDEMPOTENCY_HEADER_CACHE = {}


def get_cached_response(request):
    key = request.headers.get("Idempotency-Key")
    if key is None:
        return None, None

    cached = IDEMPOTENCY_HEADER_CACHE.get(key)
    if cached is None:
        return key, None

    if cached["path"] != request.path or cached["body"] != request.data:
        details_list = [{"field": "Idempotency-Key",
                         "issue": f"'{key}' was already used with a different request"}]
        return key, err_response(
            code="IDEMPOTENCY_CONFLICT", message="Idempotency-Key reused with a different body",
            details=details_list, status=HTTP_422_UNPROCESSABLE_ENTITY)

    return key, Response(data=cached["response"]["data"], status=cached["response"]["status"])


def cache_response(key, request, response):

    if key is None:
        return
    IDEMPOTENCY_HEADER_CACHE[key] = {
        "path": request.path,
        "body": request.data.copy(),
        "response": {"data": response.data, "status": response.status_code},
    }


def build_details_list(err_dict):

    details = []
    for key, value in err_dict.items():

        if key in ["description", "title"]:
            issue = "must not be empty"

        elif key == "completed":
            issue = "must be of type boolean"

        elif key == "due_date":
            issue = "must be of type date and YYYY-MM-DD format"

        elif key == "priority":
            issue = "must be either low, medium or high"

        else:
            issue = value[0]

        details.append({
            "field": key, "issue": issue
        })

    return details


def err_response(code, message, details, status):

    return Response(data={

        "error": {

            "code": code,

            "message": message,

            "details": details

        }

    }, status=status)


def break_down_task(task):

    description = task.description.replace("and", ",")
    pieces = description.split(",")
    return [
        {
            "title": task.title,
            "description": piece.strip(),
            "due_date": task.due_date,
            "parent": task.id,
        }
        for piece in pieces
        if piece.strip()
    ]

class PaginationClass(PageNumberPagination):
    page_size = 10

class TaskModelView(ModelViewSet):

    queryset = Task.objects.all()
    serializer_class = TaskSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["priority", "completed"]
    search_fields = ["title", "description"]
    pagination_class = PaginationClass
    ordering_fields = ["created_at"]
    # list, retrieve, update, partial_update, destroy, create

    def create(self, request):

        key, cached = get_cached_response(request)
        if cached is not None:
            return cached

        serializer = TaskSerializer(data=request.data)

        if serializer.is_valid():
            new_task = serializer.save()
            response = Response(
                data={
                    "msg": f"Task ID: {new_task.id} created successfully",
                    "task": TaskSerializer(new_task).data
                },
                status=HTTP_201_CREATED
            )
            cache_response(key, request, response)
            return response
        else:
            details_list = build_details_list(serializer.errors)
            error_response = err_response(
                code="VALIDATION_ERROR", message="Validation failed", details=details_list, status=HTTP_400_BAD_REQUEST)
            print(serializer.errors)
            return error_response

    def retrieve(self, request, pk):

        try:
            task = Task.objects.get(id=pk)
            return Response(
                data={
                    "msg": f"Task ID: {pk} found",
                    "task": TaskSerializer(task).data
                },
                status=HTTP_200_OK
            )

        except Task.DoesNotExist:
            details_list = [f"Task ID: {pk} does not exist"]
            error_response = err_response(
                code="NOT_FOUND", message="Not found", details=details_list, status=HTTP_404_NOT_FOUND)
            return error_response

        except:
            details_list = [f"BAD REQUEST"]
            error_response = err_response(
                code="BAD_REQUEST", message="Bad request", details=details_list, status=HTTP_400_BAD_REQUEST)
            return error_response

    def update(self, request, pk):

        try:
            task = Task.objects.get(pk=pk)

        except Task.DoesNotExist:
            details_list = [f"Task ID: {pk} does not exist"]
            error_response = err_response(
                code="NOT_FOUND", message="Not found", details=details_list, status=HTTP_404_NOT_FOUND)
            return error_response

        serializer = TaskSerializer(task, data=request.data)

        if serializer.is_valid():
            updated_task = serializer.save()
            return Response(
                data={
                    "msg": f"Task ID: {updated_task.id} updated successfully",
                    "task": TaskSerializer(updated_task).data
                },
                status=HTTP_200_OK
            )
        else:
            details_list = build_details_list(serializer.errors)
            error_response = err_response(
                code="VALIDATION_ERROR", message="Validation failed", details=details_list, status=HTTP_400_BAD_REQUEST)
            print(serializer.errors)
            return error_response

    def partial_update(self, request, pk):

        try:
            task = Task.objects.get(pk=pk)

        except Task.DoesNotExist:
            details_list = [f"Task ID: {pk} does not exist"]
            error_response = err_response(
                code="NOT_FOUND", message="Not found", details=details_list, status=HTTP_404_NOT_FOUND)
            return error_response

        serializer = TaskSerializer(task, data=request.data, partial=True)

        if serializer.is_valid():
            updated_task = serializer.save()
            return Response(
                data={
                    "msg": f"Task ID: {updated_task.id} partially updated successfully",
                    "task": TaskSerializer(updated_task).data
                },
                status=HTTP_200_OK
            )
        else:
            details_list = build_details_list(serializer.errors)
            error_response = err_response(
                code="VALIDATION_ERROR", message="Validation failed", details=details_list, status=HTTP_400_BAD_REQUEST)
            print(serializer.errors)
            return error_response

    def destroy(self, request, pk):

        try:
            task = Task.objects.get(pk=pk)
            task.delete()
            return Response(
                data={
                    "msg": f"Task ID: {pk} deleted successfully",
                },
                status=HTTP_200_OK
            )

        except Task.DoesNotExist:
            details_list = [f"Task ID: {pk} does not exist"]
            error_response = err_response(
                code="NOT_FOUND", message="Not found", details=details_list, status=HTTP_404_NOT_FOUND)
            return error_response

        except:
            details_list = [f"BAD REQUEST"]
            error_response = err_response(
                code="BAD_REQUEST", message="Bad request", details=details_list, status=HTTP_400_BAD_REQUEST)
            return error_response

    @action(detail=False, methods=["post"], url_path="from-text")
    def from_text(self, request):

        # Check BEFORE parsing, so a replay never calls the parser again.
        key, cached = get_cached_response(request)
        if cached is not None:
            return cached

        text = request.data.get("text")
        try:
            task_dict = parse_task_text(text)
        except Exception as exc:
            return err_response(
                code="PARSER_ERROR", message="Parser failed",
                details=[{"field": "text", "issue": str(exc)}], status=HTTP_502_BAD_GATEWAY)

        serializer = TaskSerializer(data=task_dict)
        if serializer.is_valid():
            task_obj = serializer.save()
            response = Response(
                data={
                    "msg": f"Task ID: {task_obj.id} created successfully",
                    "task": TaskSerializer(task_obj).data
                },
                status=HTTP_201_CREATED
            )
            cache_response(key, request, response)
            return response
        else:
            # Parser output is untrusted: invalid output is a 502, and nothing is saved.
            details_list = build_details_list(serializer.errors)
            error_response = err_response(
                code="PARSER_ERROR", message="Parser returned invalid task data", details=details_list, status=HTTP_502_BAD_GATEWAY)
            print(serializer.errors)
            return error_response

    @action(detail=True, methods=["post", "get"], url_path="subtasks")
    def subtasks(self, request, pk):

        if request.method == "GET":
            if not Task.objects.filter(id=pk).exists():
                details_list = [f"Task ID: {pk} does not exist"]
                error_response = err_response(
                    code="NOT_FOUND", message="Not found", details=details_list, status=HTTP_404_NOT_FOUND)
                return error_response

            tasks = Task.objects.filter(parent=pk)
            serializer = TaskSerializer(tasks, many=True)
            return Response(data={
                "msg": f"All the subtasks for parent ID: {pk}",
                "subtasks": serializer.data,
            }, status=HTTP_200_OK)
        else:
            try:
                task = Task.objects.get(id=pk)
            except Task.DoesNotExist:
                details_list = [f"Task ID: {pk} does not exist"]
                error_response = err_response(
                    code="NOT_FOUND", message="Not found", details=details_list, status=HTTP_404_NOT_FOUND)
                return error_response

            # save(parent=task) bypasses validate_parent, so check the rule here.
            if task.parent_id is not None:
                return err_response(
                    code="VALIDATION_ERROR", message="Validation failed",
                    details=[{"field": "parent", "issue": "a subtask cannot have subtasks"}],
                    status=HTTP_400_BAD_REQUEST)

            serializer = TaskSerializer(data=request.data)
            if serializer.is_valid():
                new_task = serializer.save(parent=task)
                return Response(
                    data={
                        "msg": f"Subtask ID: {new_task.id} with parent ID: {pk} created successfully",
                        "task": TaskSerializer(new_task).data
                    },
                    status=HTTP_201_CREATED
                )
            else:
                details_list = build_details_list(serializer.errors)
                error_response = err_response(
                    code="VALIDATION_ERROR", message="Validation failed", details=details_list, status=HTTP_400_BAD_REQUEST)
                print(serializer.errors)
                return error_response

    @action(detail=True, methods=["post"], url_path="breakdown")
    def breakdown(self, request, pk):

        key, cached = get_cached_response(request)
        if cached is not None:
            return cached

        try:
            task = Task.objects.get(pk=pk)
        except Task.DoesNotExist:
            details_list = [f"Parent Task ID: {pk} does not exist"]
            error_response = err_response(
                code="NOT_FOUND", message="Not found", details=details_list, status=HTTP_404_NOT_FOUND)
            return error_response

        serializer = TaskSerializer(data=break_down_task(task), many=True)

        if not serializer.is_valid():
            details_list = [build_details_list(
                err) for err in serializer.errors if err]
            error_response = err_response(
                code="VALIDATION_ERROR", message="Validation failed", details=details_list, status=HTTP_400_BAD_REQUEST)
            return error_response

        with transaction.atomic():
            subtasks = serializer.save()

        response = Response(
            data={
                "msg": f"Created {len(subtasks)} subtasks for parent ID: {pk}",
                "subtasks": TaskSerializer(subtasks, many=True).data,
            },
            status=HTTP_201_CREATED
        )
        cache_response(key, request, response)
        return response

    def get_tasks_by_priority(self, request, level):
        
        if level not in ["low", "medium", "high"]:
            details_list = [f"BAD REQUEST"]
            error_response = err_response(
                code="BAD_REQUEST", message="Bad request", details=details_list, status=HTTP_400_BAD_REQUEST)
            return error_response
        
        tasks = Task.objects.filter(priority=level)
        serializer = TaskSerializer(tasks, many=True)
        return Response(
            data=serializer.data,
            status=HTTP_200_OK
        )

