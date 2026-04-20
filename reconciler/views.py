from django.db import connection
from django.db.utils import OperationalError
from rest_framework.decorators import api_view
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema


@extend_schema(
    summary="Health check",
    description="Returns 200 if the API and database are reachable.",
    responses={200: {"type": "object", "properties": {"status": {"type": "string"}, "database": {"type": "string"}}}},
)
@api_view(["GET"])
def health_check(request):
    """Check API and database connectivity."""
    try:
        connection.ensure_connection()
        db_status = "ok"
    except OperationalError:
        db_status = "unavailable"
    return Response({"status": "ok", "database": db_status})