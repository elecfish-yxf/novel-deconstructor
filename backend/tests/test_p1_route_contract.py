from fastapi.routing import APIRoute

from novel_deconstructor.main import app


def _routes() -> dict[tuple[str, str], APIRoute]:
    routes: dict[tuple[str, str], APIRoute] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods or []:
            if method in {"HEAD", "OPTIONS"}:
                continue
            routes[(method, route.path)] = route
    return routes


def test_p1_frontend_backend_route_contract_exists():
    routes = _routes()
    required = {
        ("POST", "/api/auth/register"),
        ("POST", "/api/auth/login"),
        ("GET", "/api/auth/me"),
        ("POST", "/api/auth/logout"),
        ("POST", "/api/writing/works/{work_id}/knowledge/import-package"),
        ("POST", "/api/writing/works/{work_id}/knowledge/import-markdown"),
        ("POST", "/api/writing/works/{work_id}/knowledge/import-markdown-file"),
        ("GET", "/api/writing/works/{work_id}/knowledge/cards"),
        ("PATCH", "/api/writing/works/{work_id}/knowledge/cards/{card_id}"),
        ("DELETE", "/api/writing/works/{work_id}/knowledge/cards/{card_id}"),
        ("GET", "/api/writing/works/{work_id}/knowledge/docs"),
        ("POST", "/api/writing/works/{work_id}/knowledge/docs/{doc_id}/sync"),
        ("POST", "/api/writing/works/{work_id}/rag/search"),
        ("POST", "/api/writing/works/{work_id}/agent/outline"),
        ("POST", "/api/writing/works/{work_id}/agent/draft"),
        ("POST", "/api/writing/works/{work_id}/agent/draft-jobs"),
        ("GET", "/api/writing/works/{work_id}/agent/draft-jobs/{job_id}"),
        ("POST", "/api/writing/works/{work_id}/agent/draft-jobs/{job_id}/cancel"),
        ("POST", "/api/writing/works/{work_id}/agent/revision"),
        ("POST", "/api/writing/works/{work_id}/memory/confirm-outline"),
        ("POST", "/api/writing/works/{work_id}/memory/confirm-draft"),
        ("GET", "/health"),
        ("GET", "/api/health"),
    }

    missing = sorted(required - set(routes))

    assert missing == []


def test_p1_legacy_writing_routes_are_marked_deprecated():
    routes = _routes()
    for path in ["/api/writing/outline", "/api/writing/draft", "/api/writing/generate"]:
        route = routes[("POST", path)]
        assert route.deprecated is True
