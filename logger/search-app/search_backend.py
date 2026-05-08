"""
Search backend abstraction for the SOL-logger search-app.

Selects between Google Vertex AI Discovery Engine (default) and a local
PyTerrier service via the SEARCH_BACKEND environment variable.

Expected API_keys.json structure:
    {
      "vertex_ai": {
        "project_number": "425294702501",
        "location": "global",
        "engine_id": "sol-test-2_1776796467056",
        "data_store_id": "datastore-sample_1776796569534",
        "language_code": "it"
      }
    }

NOTE: data_store_id and engine_id are different values.
  - engine_id     -> required by SearchService (search)
  - data_store_id -> required by CompletionService (autocomplete)
Both must be present in API_keys.json (or the env vars below).
"""

import os
import json
import requests
from flask import jsonify

from google.cloud import discoveryengine_v1 as discoveryengine
from google.api_core.client_options import ClientOptions
from time import time


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_vertex_config():
    project = os.getenv('VERTEX_PROJECT_NUMBER')
    location = os.getenv('VERTEX_LOCATION', 'global')
    engine_id = os.getenv('VERTEX_ENGINE_ID')
    data_store_id = os.getenv('VERTEX_DATA_STORE_ID')
    language_code = os.getenv('VERTEX_LANGUAGE_CODE', 'it')

    if not project or not engine_id or not data_store_id:
        config_path = os.path.join(os.path.dirname(__file__), 'API_keys.json')
        if os.path.exists(config_path):
            try:
                with open(config_path) as f:
                    cfg = json.load(f).get('vertex_ai', {})
                project = project or cfg.get('project_number')
                location = cfg.get('location', location)
                engine_id = engine_id or cfg.get('engine_id')
                data_store_id = data_store_id or cfg.get('data_store_id')
                language_code = cfg.get('language_code', language_code)
            except (OSError, ValueError) as e:
                print(f"[Vertex Config WARN] Could not load API_keys.json: {e}")

    return project, location, engine_id, data_store_id, language_code


# ---------------------------------------------------------------------------
# Lazy client factories
# ---------------------------------------------------------------------------

def get_search_client(location):
    client_options = None
    if location and location != "global":
        client_options = ClientOptions(
            api_endpoint=f"{location}-discoveryengine.googleapis.com"
        )
    return discoveryengine.SearchServiceClient(client_options=client_options)


def get_completion_client(location):
    client_options = None
    if location and location != "global":
        client_options = ClientOptions(
            api_endpoint=f"{location}-discoveryengine.googleapis.com"
        )
    return discoveryengine.CompletionServiceClient(client_options=client_options)


# ---------------------------------------------------------------------------
# Vertex AI backend
# ---------------------------------------------------------------------------

# Always fetch up to this many results in a single Vertex call. The Flask
# route caches the full list in session and slices client-side, mirroring
# the existing PyTerrier behavior (maxres=100).
VERTEX_MAX_RESULTS = 100


def vertex_search(query, page, rpp, config):
    project, location, engine_id, data_store_id, language_code = config

    if not project or not engine_id:
        print("[Vertex Search ERROR] Missing project_number or engine_id in config")
        return [], 0

    client = get_search_client(location)

    serving_config = (
        f"projects/{project}/locations/{location}"
        f"/collections/default_collection/engines/{engine_id}"
        f"/servingConfigs/default_search"
    )

    try:
        request = discoveryengine.SearchRequest(
            serving_config=serving_config,
            query=query,
            page_size=VERTEX_MAX_RESULTS,
            offset=0,
            query_expansion_spec=discoveryengine.SearchRequest.QueryExpansionSpec(
                condition=discoveryengine.SearchRequest.QueryExpansionSpec.Condition.AUTO,
            ),
            spell_correction_spec=discoveryengine.SearchRequest.SpellCorrectionSpec(
                mode=discoveryengine.SearchRequest.SpellCorrectionSpec.Mode.AUTO,
            ),
            language_code=language_code,
        )
        response = client.search(request)
    except Exception as e:
        print(f"[Vertex Search ERROR] {e}")
        return [], 0

    results = []
    total = response.total_size if hasattr(response, "total_size") else 0

    for item in response.results:
        doc_data = dict(item.document.derived_struct_data)
        title = str(doc_data.get("title", ""))
        link = str(doc_data.get("link", ""))

        snippet = ""
        snippets = doc_data.get("snippets")
        if snippets:
            snippet_list = list(snippets)
            if snippet_list:
                snippet_data = dict(snippet_list[0])
                snippet = str(
                    snippet_data.get("htmlSnippet", snippet_data.get("snippet", ""))
                )
        if not snippet:
            snippet = str(doc_data.get("snippet", ""))

        displayed_link = link
        if "://" in link:
            displayed_link = link.split("://", 1)[1].split("/", 1)[0]

        thumbnail = None
        pagemap = doc_data.get("pagemap")
        if pagemap:
            pagemap_dict = dict(pagemap)
            cse_thumb = pagemap_dict.get("cse_thumbnail")
            if cse_thumb:
                thumb_list = list(cse_thumb)
                if thumb_list:
                    thumbnail = str(dict(thumb_list[0]).get("src", ""))

        results.append({
            "title": title,
            "snippet": snippet,
            "link": link,
            "displayed_link": displayed_link,
            "docid": str(item.document.id) if item.document.id else link,
            "thumbnail": thumbnail,
        })

    return results, total


def vertex_autocomplete(query, config, max_suggestions=5):
    # project, location, engine_id, data_store_id, language_code = config

    # if not project or not data_store_id:
    #     print("project or data_store_id not found")
    #     return []

    # client = get_completion_client(location)

    # data_store_path = (
    #     f"projects/{project}/locations/{location}"
    #     f"/collections/default_collection/dataStores/{data_store_id}"
    # )

    # try:
    #     request = discoveryengine.CompleteQueryRequest(
    #         data_store=data_store_path,
    #         query=query,
    #         query_model="document-completable",
    #         include_tail_suggestions=True,
    #     )
    #     response = client.complete_query(request)
    #     return [s.suggestion for s in response.query_suggestions][:max_suggestions]
    # except Exception as e:
    #     print(f"[Vertex Autocomplete ERROR] {e}")
    #     return []
    
    return pyterrier_autocomplete(query)


# ---------------------------------------------------------------------------
# PyTerrier fallback
# ---------------------------------------------------------------------------

def pyterrier_search(query, page, rpp, db_url="http://search_engine:7002"):
    url = f"{db_url}/ranking?query={query}&rpp={VERTEX_MAX_RESULTS}"
    try:
        response = requests.get(url)
    except requests.ConnectionError:
        return [], 0

    if response.status_code != 200:
        return [], 0

    try:
        data = response.json()
    except ValueError:
        return [], 0

    if isinstance(data, dict):
        itemlist = data.get("itemlist", [])
    elif isinstance(data, list):
        itemlist = data
    else:
        itemlist = []

    return itemlist, len(itemlist)


def pyterrier_autocomplete(query):

    with open("API_keys.json") as f:
        API_KEY = json.load(f)["serp_api"]["api_key"]

    AUTOCOMPLETE_CACHE = {}
    CACHE_TTL = 600  # 10 minutes
    MAX_SUGGESTIONS = 5

    cached = AUTOCOMPLETE_CACHE.get(query)
    if cached and time() - cached["time"] < CACHE_TTL:
        return jsonify(cached["data"])

    try:
        response = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_autocomplete",
                "q": query,
                "api_key": API_KEY,
                # uncomment for italian:
                "hl": "it",
            },
            timeout=5
        )

        response.raise_for_status()
        data = response.json()

        suggestions = [
            s["value"] for s in data.get("suggestions", [])
        ][:MAX_SUGGESTIONS]

        # ---- Store in cache ----
        AUTOCOMPLETE_CACHE[query] = {
            "time": time(),
            "data": suggestions
        }

        return suggestions

        # return jsonify(suggestions)

    except requests.RequestException as e:
        # graceful fallback (no retries)
        return e


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

SEARCH_BACKEND = os.getenv("SEARCH_BACKEND", "vertex").lower()
_vertex_config = load_vertex_config()


def search(query, page, rpp):
    if SEARCH_BACKEND == "vertex":
        return vertex_search(query, page, rpp, _vertex_config)
    return pyterrier_search(query, page, rpp)


def autocomplete(query):
    if SEARCH_BACKEND == "vertex":
        return vertex_autocomplete(query, _vertex_config)
    return pyterrier_autocomplete(query)
