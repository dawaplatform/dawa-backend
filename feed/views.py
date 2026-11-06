import secrets

from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.utils.urls import remove_query_param, replace_query_param

from DawaApp.serializers import ItemSerializer
from feed import config as C
from feed import service


class FeedItemSerializer(ItemSerializer):
    badge = serializers.SerializerMethodField()

    class Meta(ItemSerializer.Meta):
        fields = ItemSerializer.Meta.fields + ["created_at", "badge"]

    def get_badge(self, obj):
        return self.context.get("badges", {}).get(obj.id)


def _int(value, default=None, *, lo=0, hi=None):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    n = max(n, lo)
    return min(n, hi) if hi is not None else n


@api_view(["GET"])
@permission_classes([AllowAny])
def home_feed(request):
    """Ranked home feed. Pages are stable within a session: follow the `next` URL."""
    params = request.query_params
    session = (params.get("session") or "")[:64] or secrets.token_urlsafe(12)
    limit = _int(params.get("limit"), C.PAGE_SIZE, lo=1, hi=C.MAX_PAGE_SIZE)
    offset = _int(params.get("offset"), 0)
    category_id = _int(params.get("category_id"), lo=1)
    subcategory_id = _int(params.get("subcategory_id"), lo=1)
    location = (params.get("location") or "").strip()[:100] or None

    feed = service.ranked_for_session(
        session=session, category_id=category_id, subcategory_id=subcategory_id, location=location
    )
    total = len(feed.ids)
    items = service.page_items(feed.ids[offset : offset + limit])
    data = FeedItemSerializer(items, many=True, context={"badges": feed.badges}).data

    url = replace_query_param(request.build_absolute_uri(), "session", session)
    url = replace_query_param(url, "limit", limit)
    next_url = replace_query_param(url, "offset", offset + limit) if offset + limit < total else None
    prev_url = None
    if offset > 0:
        prev_offset = max(offset - limit, 0)
        prev_url = replace_query_param(url, "offset", prev_offset) if prev_offset else remove_query_param(url, "offset")

    return Response(
        {
            "count": total,
            "next": next_url,
            "previous": prev_url,
            "session": session,
            "results": {"data": data},
        }
    )
