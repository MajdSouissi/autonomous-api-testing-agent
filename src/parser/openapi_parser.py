"""OpenAPI spec parser, $ref resolver, endpoint extractor, and test-payload helpers."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class EndpointInfo:
    path: str                       # e.g. "/items/{item_id}"
    method: str                     # e.g. "get", "post"
    operation_id: str               # from spec or auto-generated
    summary: str
    tags: List[str]
    requires_auth: bool             # True if endpoint or global scheme uses OAuth2/Bearer
    path_params: List[dict]         # resolved parameter schemas
    query_params: List[dict]        # resolved parameter schemas
    request_body: Optional[dict]    # resolved request body schema (None if absent)
    responses: Dict[str, dict]      # status_code -> resolved response schema
    success_status_code: int        # primary success code (200 or 201)
    content_type: str = "application/json"  # MIME type: application/json vs application/x-www-form-urlencoded
    request_content_type: str = "application/json"


# ---------------------------------------------------------------------------
# $ref resolver
# ---------------------------------------------------------------------------


def _resolve_ref(ref: str, root: dict) -> Any:
    """Resolve a JSON Pointer $ref string against *root* and return the target node."""
    if not ref.startswith("#/"):
        raise ValueError(f"Only local $ref values are supported, got: {ref!r}")
    parts = ref[2:].split("/")
    node: Any = root
    for part in parts:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            node = node[part]
        elif isinstance(node, list):
            node = node[int(part)]
        else:
            raise KeyError(f"Cannot descend into {type(node)} with key {part!r}")
    return node


def _resolve_refs(obj: Any, root: dict, _visiting: Optional[set] = None) -> Any:
    """Recursively replace every ``$ref`` in *obj* with the referenced schema.

    Uses deep-copy to prevent circular reference issues.
    """
    if _visiting is None:
        _visiting = set()

    if isinstance(obj, dict):
        if "$ref" in obj:
            ref_str: str = obj["$ref"]
            if ref_str in _visiting:
                # Circular reference guard – return a placeholder to avoid infinite recursion
                return {"$circular_ref": ref_str}
            _visiting = _visiting | {ref_str}
            target = _resolve_ref(ref_str, root)
            # Deep-copy before resolving nested refs so original spec stays intact
            target_copy = copy.deepcopy(target)
            return _resolve_refs(target_copy, root, _visiting)
        # Recurse into every key
        return {k: _resolve_refs(v, root, _visiting) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_refs(item, root, _visiting) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Auth detection helpers
# ---------------------------------------------------------------------------


def _scheme_requires_auth(scheme: dict) -> bool:
    """Return True if *scheme* is an OAuth2 or HTTP-Bearer security scheme."""
    scheme_type = scheme.get("type", "").lower()
    if scheme_type == "oauth2":
        return True
    if scheme_type == "http" and scheme.get("scheme", "").lower() == "bearer":
        return True
    return False


def _endpoint_requires_auth(
    operation: dict,
    global_security: List[dict],
    security_schemes: Dict[str, dict],
) -> bool:
    """Determine whether *operation* requires authentication."""
    # Per-operation security overrides global
    security_requirements: List[dict] = operation.get("security", global_security)
    if not security_requirements:
        return False
    for requirement in security_requirements:
        for scheme_name in requirement:
            scheme = security_schemes.get(scheme_name, {})
            if _scheme_requires_auth(scheme):
                return True
    return False


# ---------------------------------------------------------------------------
# Primary parsing function
# ---------------------------------------------------------------------------


def parse_spec(url: str) -> List[EndpointInfo]:
    """Fetch the OpenAPI spec from *url* and return a sorted list of :class:`EndpointInfo`."""
    response = httpx.get(url, timeout=30.0)
    response.raise_for_status()
    raw_spec: dict = response.json()

    # Resolve all $refs in a single pass against the original spec
    spec: dict = _resolve_refs(raw_spec, raw_spec)

    # Pull out security schemes once
    security_schemes: Dict[str, dict] = (
        spec.get("components", {}).get("securitySchemes", {})
    )
    global_security: List[dict] = spec.get("security", [])

    endpoints: List[EndpointInfo] = []

    for path, path_item in spec.get("paths", {}).items():
        # Collect path-level parameters (may be overridden at operation level)
        path_level_params: List[dict] = path_item.get("parameters", [])

        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            operation: Optional[dict] = path_item.get(method)
            if operation is None:
                continue

            # --- operation_id ---
            operation_id: str = operation.get(
                "operationId",
                f"{method}_{path.strip('/').replace('/', '_').replace('{', '').replace('}', '')}",
            )

            # --- summary / tags ---
            summary: str = operation.get("summary", "")
            tags: List[str] = operation.get("tags", [])

            # --- auth ---
            requires_auth: bool = _endpoint_requires_auth(
                operation, global_security, security_schemes
            )

            # --- parameters ---
            # Merge path-level params with operation-level params (operation wins on name+in)
            merged_params: Dict[tuple, dict] = {
                (p["name"], p["in"]): p for p in path_level_params
            }
            for p in operation.get("parameters", []):
                merged_params[(p["name"], p["in"])] = p

            path_params: List[dict] = [
                p for p in merged_params.values() if p.get("in") == "path"
            ]
            query_params: List[dict] = [
                p for p in merged_params.values() if p.get("in") == "query"
            ]

            # --- request body ---
            request_body: Optional[dict] = None
            content_type: str = "application/json"
            if "requestBody" in operation:
                rb = operation["requestBody"]
                content = rb.get("content", {})
                if "application/x-www-form-urlencoded" in content:
                    content_type = "application/x-www-form-urlencoded"
                    request_body = content["application/x-www-form-urlencoded"].get("schema")
                elif "application/json" in content:
                    content_type = "application/json"
                    request_body = content["application/json"].get("schema")
                elif content:
                    content_type = next(iter(content.keys()))
                    request_body = content[content_type].get("schema")

                # Explicitly flag content_type in the parsed schema dict
                if isinstance(request_body, dict):
                    request_body["content_type"] = content_type

            # --- responses ---
            responses: Dict[str, dict] = {}
            success_status_code: int = 200
            for status_code, resp_obj in operation.get("responses", {}).items():
                resp_content = resp_obj.get("content", {})
                schema: dict = {}
                if resp_content:
                    for media_type in ("application/json",):
                        if media_type in resp_content:
                            schema = resp_content[media_type].get("schema", {})
                            break
                    if not schema:
                        first = next(iter(resp_content.values()), {})
                        schema = first.get("schema", {})
                responses[status_code] = schema

            # Determine primary success status code
            for candidate in ("201", "200", "204"):
                if candidate in responses:
                    success_status_code = int(candidate)
                    break

            endpoints.append(
                EndpointInfo(
                    path=path,
                    method=method,
                    operation_id=operation_id,
                    summary=summary,
                    tags=tags,
                    requires_auth=requires_auth,
                    path_params=path_params,
                    query_params=query_params,
                    request_body=request_body,
                    responses=responses,
                    success_status_code=success_status_code,
                    content_type=content_type,
                    request_content_type=content_type,
                )
            )

    # Deterministic ordering: (first_tag, path, method)
    endpoints.sort(key=lambda e: (e.tags[0] if e.tags else "", e.path, e.method))
    return endpoints


# ---------------------------------------------------------------------------
# Dependency graph
# ---------------------------------------------------------------------------


def build_dependency_graph(endpoints: List[EndpointInfo]) -> Dict[str, List[str]]:
    """Return an adjacency dict of operation_id -> [dependant operation_ids].

    Heuristic: POST endpoints that look like resource-creation come before the
    GET / PUT / DELETE endpoints that reference the same resource path segment.
    """
    graph: Dict[str, List[str]] = {e.operation_id: [] for e in endpoints}

    # Group endpoints by their "resource base" (path without trailing /{id} segment)
    def _resource_base(path: str) -> str:
        parts = path.rstrip("/").split("/")
        # Drop trailing path-param segments to get the collection path
        while parts and parts[-1].startswith("{"):
            parts.pop()
        return "/".join(parts)

    # Map resource_base -> create operation_id (POST without path params)
    creators: Dict[str, str] = {}
    for ep in endpoints:
        if ep.method == "post" and not ep.path_params:
            creators[_resource_base(ep.path)] = ep.operation_id

    # For each non-POST endpoint that has path params, add an edge from its creator
    for ep in endpoints:
        if ep.method in ("get", "put", "patch", "delete") and ep.path_params:
            base = _resource_base(ep.path)
            creator_id = creators.get(base)
            if creator_id and creator_id != ep.operation_id:
                if ep.operation_id not in graph[creator_id]:
                    graph[creator_id].append(ep.operation_id)

    return graph


# ---------------------------------------------------------------------------
# Example payload generator
# ---------------------------------------------------------------------------


def generate_example_payload(schema: dict) -> Any:
    """Generate a minimal valid example value from a resolved JSON Schema dict."""
    if not schema:
        return {}

    schema_type = schema.get("type")
    schema_format = schema.get("format", "")

    # Handle allOf / anyOf / oneOf by using the first sub-schema
    for combiner in ("allOf", "anyOf", "oneOf"):
        if combiner in schema:
            sub_schemas = schema[combiner]
            if sub_schemas:
                return generate_example_payload(sub_schemas[0])

    # Use provided example if present
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]

    if schema_type == "object" or "properties" in schema:
        result: dict = {}
        required_fields: List[str] = schema.get("required", [])
        properties: dict = schema.get("properties", {})
        for prop_name, prop_schema in properties.items():
            # Always include required fields; include optional ones with sensible defaults
            result[prop_name] = generate_example_payload(prop_schema)
        return result

    if schema_type == "array":
        items_schema = schema.get("items", {})
        return [generate_example_payload(items_schema)]

    if schema_type == "string":
        min_length: int = schema.get("minLength", 0)
        if schema.get("format") == "email":
            return "user@example.com"
        if schema.get("format") == "date-time":
            return "2024-01-01T00:00:00Z"
        if schema.get("format") == "date":
            return "2024-01-01"
        if schema.get("format") == "uri":
            return "https://example.com"
        if schema.get("pattern"):
            # Return a simple string; pattern compliance is best-effort
            return "string"
        base = "a" * max(min_length, 1) if min_length > 0 else "string"
        max_length: Optional[int] = schema.get("maxLength")
        if max_length is not None:
            base = base[:max_length]
        return base

    if schema_type in ("number", "float"):
        exclusive_minimum = schema.get("exclusiveMinimum")
        minimum = schema.get("minimum")
        gt = schema.get("gt")
        if gt is not None:
            return round(gt + 0.1, 10)
        if exclusive_minimum is not None:
            return round(exclusive_minimum + 0.1, 10)
        if minimum is not None:
            return float(minimum)
        return 1.0

    if schema_type == "integer":
        exclusive_minimum = schema.get("exclusiveMinimum")
        minimum = schema.get("minimum")
        if exclusive_minimum is not None:
            return int(exclusive_minimum) + 1
        if minimum is not None:
            return int(minimum)
        return 1

    if schema_type == "boolean":
        return True

    if schema_type == "null":
        return None

    # Fallback for unknown / untyped schemas
    return {}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import sys

    target_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/openapi.json"
    print(f"Fetching spec from {target_url} …\n")

    try:
        all_endpoints = parse_spec(target_url)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(all_endpoints)} endpoint(s):\n")
    for ep in all_endpoints:
        auth_flag = " [AUTH]" if ep.requires_auth else ""
        print(
            f"  [{ep.success_status_code}] {ep.method.upper():7s} {ep.path}"
            f"  ({ep.operation_id}){auth_flag}"
        )
        if ep.tags:
            print(f"           tags={ep.tags}")
        if ep.request_body:
            print(f"           payload example: {json.dumps(generate_example_payload(ep.request_body))}")

    print("\nDependency graph (operation_id → dependants):")
    graph = build_dependency_graph(all_endpoints)
    for node, deps in graph.items():
        if deps:
            print(f"  {node} → {deps}")
