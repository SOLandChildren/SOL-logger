"""
Focused logging contract tests for SOL Search logging behavior.

These tests avoid starting the full app, so they can run as quick guardrails
alongside the existing Selenium tests.
"""

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


APP_ROOT = Path(__file__).resolve().parents[1]
LOGGER_JS = APP_ROOT / "static" / "logger.js"
WEBPAGE_HTML = APP_ROOT / "templates" / "webpage.html"
SEARCH_APP = APP_ROOT / "search_app.py"
LAYOUT_HTML = APP_ROOT / "templates" / "layout.html"
SEARCH_HTML = APP_ROOT / "templates" / "search.html"
CHECK_LOGS = APP_ROOT / "tools" / "check_logs.py"


def run_logger_node_script(script_body):
    script = f"""
        const fs = require("fs");
        const vm = require("vm");
        global.window = {{
            addEventListener() {{}},
            location: {{ origin: "http://127.0.0.1:7001" }}
        }};
        global.crypto = {{ randomUUID: () => "test-session" }};
        global.localStorage = {{
            data: {{}},
            getItem(key) {{ return this.data[key] || null; }},
            setItem(key, value) {{ this.data[key] = String(value); }},
            removeItem(key) {{ delete this.data[key]; }},
            clear() {{ this.data = {{}}; }}
        }};
        global.sessionStorage = {{
            data: {{}},
            getItem(key) {{ return this.data[key] || null; }},
            setItem(key, value) {{ this.data[key] = String(value); }},
            removeItem(key) {{ delete this.data[key]; }},
            clear() {{ this.data = {{}}; }}
        }};
        global.document = {{
            getElementById() {{ return null; }},
            querySelector() {{ return null; }},
            querySelectorAll() {{ return []; }},
            addEventListener() {{}}
        }};
        vm.runInThisContext(fs.readFileSync({json.dumps(str(LOGGER_JS))}, "utf8"));
        global.studyLogger = window.studyLogger;
        {script_body}
    """
    return subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )


def test_logger_uses_europe_zurich_timestamp_not_utc_iso():
    source = LOGGER_JS.read_text(encoding="utf-8")

    assert 'LOG_TIME_ZONE = "Europe/Zurich"' in source
    assert "timestamp: formatSwissTimestamp()" in source
    assert "new Date().toISOString()" not in source
    assert "+02:00" not in source
    assert "+03:00" not in source


def test_logged_event_timestamp_has_switzerland_offset():
    result = run_logger_node_script("""
        window.studyLogger.logEvent("timestampProbe");
        console.log(JSON.stringify(window.studyLogger.logs[0]));
    """)
    event = json.loads(result.stdout.strip().splitlines()[-1])
    timestamp = event["timestamp"]
    expected_offset = datetime.now(ZoneInfo("Europe/Zurich")).strftime("%z")
    expected_offset = f"{expected_offset[:3]}:{expected_offset[3:]}"

    assert event["type"] == "timestampProbe"
    assert timestamp.endswith(expected_offset)
    assert not timestamp.endswith("Z")
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}",
        timestamp,
    )


def test_webpage_closed_has_duration_exit_reason_guard_and_fallback():
    source = WEBPAGE_HTML.read_text(encoding="utf-8")

    assert 'studyLogger.logEvent("webpageOpened", { url: viewedUrl })' in source
    assert "let webpageClosedLogged = false" in source
    assert "webpageClosedLogged = true" in source
    assert 'studyLogger.logEvent("webpageClosed"' in source
    assert "durationMs: Date.now() - webpageOpenedAt" in source
    assert "exitReason: reason" in source
    assert "window.logOpenWebpageClosed = emitClosed" in source
    assert 'emitClosed("back-button")' in source
    assert 'window.addEventListener("pagehide", () => emitClosed("pagehide"))' in source


def test_answer_submission_closes_open_webpage_before_task_ended():
    source = LAYOUT_HTML.read_text(encoding="utf-8")
    exposure_index = source.index('window.flushActiveResultExposures("task-end")')
    close_index = source.index('window.logOpenWebpageClosed("end-task-button")')
    task_ended_index = source.index('studyLogger.logEvent("TaskEnded"')

    assert 'typeof window.flushActiveResultExposures === "function"' in source
    assert 'typeof window.logOpenWebpageClosed === "function"' in source
    assert exposure_index < task_ended_index
    assert close_index < task_ended_index


def test_log_session_warns_only_for_expected_logging_contract_issues():
    source = SEARCH_APP.read_text(encoding="utf-8")

    assert "def warn_logging_contract_issues(logs, default_task_number):" in source
    assert "warn_logging_contract_issues(logs, task_number)" in source
    assert "if session_id != server_session_id:" in source
    assert 'return jsonify({"error": "Session mismatch"}), 409' in source
    assert "mismatched_uids = [" in source
    assert 'return jsonify({"error": "User mismatch"}), 409' in source
    assert "duplicate consecutive querySubmitted" in source
    assert "pageNavigationClicked has null toPage" in source
    assert "wentBack missing fields" in source
    assert "SERP event missing query fields" in source
    assert "('url', 'durationMs', 'exitReason')" in source
    assert "[Logging WARN] webpageClosed missing fields" in source
    assert '"combined_file": combined_filename' in source
    assert '"task_file":     task_filename' in source


def test_log_session_writes_full_and_per_task_logs_without_aggregate_outputs():
    source = SEARCH_APP.read_text(encoding="utf-8")

    assert 'combined_filename = f"{safe_user}_{log_id}_FULL.log"' in source
    assert 'task_filename     = f"{safe_user}_{log_id}_task{visible_task_number}_topic{actual_topic_number}.log"' in source
    assert "full_f.write(line)" in source
    assert "task_f.write(line)" in source
    assert "write_aggregate_json" not in source
    assert "log_aggregation" not in source
    assert "_aggregate.log" not in source
    assert "with_suffix(\".json\")" not in source
    assert not (APP_ROOT / "log_aggregation.py").exists()
    assert not (APP_ROOT / "tests" / "test_log_aggregation.py").exists()


def test_start_post_resets_server_session_before_new_experiment_state():
    source = SEARCH_APP.read_text(encoding="utf-8")
    start_index = source.index("def start_page():")
    post_index = source.index("if request.method == 'POST':", start_index)
    clear_index = source.index("session.clear()", post_index)
    user_index = source.index("session['user_id'] = user_id", post_index)
    session_id_index = source.index("session['session_id'] = str(uuid.uuid4())", post_index)
    log_id_index = source.index("session['log_id'] = generate_log_id()", post_index)
    order_index = source.index("assign_random_task_order(user_id)", post_index)

    assert post_index < clear_index < user_index < session_id_index < log_id_index < order_index
    assert "session['pieces_earned'] = []" in source
    assert "session['tasks_started'] = []" in source
    assert "session['last_active'] = datetime.now().isoformat()" in source
    assert "session[\"search_results\"]" not in source[post_index:order_index]


def test_client_cleanup_clears_local_session_and_in_memory_logger_state():
    logger_source = LOGGER_JS.read_text(encoding="utf-8")
    layout_source = LAYOUT_HTML.read_text(encoding="utf-8")
    end_source = (APP_ROOT / "templates" / "end.html").read_text(encoding="utf-8")

    assert "clearClientData(options = {})" in logger_source
    assert "localStorage.clear()" in logger_source
    assert "sessionStorage.clear()" in logger_source
    assert "this.logs = []" in logger_source
    assert "this.historyTracker = []" in logger_source
    assert "studyLogger.clearClientData({ createNewSessionID: true })" in logger_source
    assert 'entry.type === "idSubmitted"' in logger_source
    assert "entry.uid === currentUser" in logger_source
    assert "sessionID: this.sessionID" in logger_source
    assert "window.studyLogger.clearClientData()" in layout_source
    assert "sessionStorage.clear()" in layout_source
    assert "await studyLogger.sendLogs();" in end_source
    assert "clearClientData();" in end_source
    assert 'window.location.href = "{{ url_for(\'welcome\') }}?reset=1";' in end_source


def test_duplicate_query_submit_suppression_contract():
    source = LOGGER_JS.read_text(encoding="utf-8")

    assert "querySubmitInProgress" in source
    assert "submittedQuery === query" in source
    assert "e.preventDefault()" in source
    assert "e.stopImmediatePropagation()" in source
    assert 'window.addEventListener("pageshow"' in source


def test_italian_pagination_target_parsing():
    result = run_logger_node_script("""
        const internals = window.__SOLLoggerInternals;
        console.log(JSON.stringify({
            previous: internals.getTargetPage("« Precedente", 2),
            next: internals.getTargetPage("Successiva »", 2),
            numeric: internals.getTargetPage("3", 1),
            href: internals.getTargetPage("ignored", 1, "http://127.0.0.1:7001/result?query=x&page=4")
        }));
    """)
    parsed = json.loads(result.stdout.strip().splitlines()[-1])

    assert parsed == {"previous": 1, "next": 3, "numeric": 3, "href": 4}


def test_went_back_return_metadata_contract():
    result = run_logger_node_script("""
        const internals = window.__SOLLoggerInternals;
        console.log(JSON.stringify({
            resource: internals.getReturnMetadata(
                "http://127.0.0.1:7001/webpage?url=https%3A%2F%2Fexample.com&query=q&page=1",
                "http://127.0.0.1:7001/result?query=q&page=1"
            ),
            serp: internals.getReturnMetadata(
                "http://127.0.0.1:7001/result?query=q&page=2",
                "http://127.0.0.1:7001/result?query=q&page=1"
            )
        }));
    """)
    parsed = json.loads(result.stdout.strip().splitlines()[-1])

    assert parsed["resource"]["returnType"] == "resource-to-serp"
    assert parsed["resource"]["fromPageType"] == "webpage"
    assert parsed["resource"]["toPageType"] == "serp"
    assert parsed["serp"]["returnType"] == "serp-to-serp"


def test_raw_and_sanitized_query_fields_on_serp_contract():
    logger_source = LOGGER_JS.read_text(encoding="utf-8")
    search_source = SEARCH_HTML.read_text(encoding="utf-8")

    assert "data-raw-query" in search_source
    assert "data-sanitized-query" in search_source
    assert "rawQuery: details.rawQuery" in logger_source
    assert "sanitizedQuery: details.sanitizedQuery" in logger_source
    assert "rawQuery: context.rawQuery" in logger_source
    assert "sanitizedQuery: context.sanitizedQuery" in logger_source


def test_result_exposure_logging_contract():
    source = LOGGER_JS.read_text(encoding="utf-8")

    assert "const RESULT_EXPOSURE_THRESHOLD = 0.5" in source
    assert "const RESULT_EXPOSURE_MIN_MS = 250" in source
    assert 'studyLogger.logEvent("resultExposureStarted"' in source
    assert 'studyLogger.logEvent("resultExposureEnded"' in source
    assert 'flushActiveResultExposures("result-click")' in source
    assert 'flushActiveResultExposures("pagination")' in source
    assert 'flushActiveResultExposures("new-search")' in source
    assert 'flushActiveResultExposures("pagehide")' in source
    assert 'flushActiveResultExposures("task-end")' in source
    assert "IntersectionObserver" in source
    assert "durationMs" in source
    assert "exitReason" in source


def test_autocomplete_and_no_results_logging_contract():
    logger_source = LOGGER_JS.read_text(encoding="utf-8")
    search_source = SEARCH_HTML.read_text(encoding="utf-8")

    assert 'studyLogger.logEvent("choseAutoCompleteSuggestion"' in logger_source
    assert 'searchbox.addEventListener("change"' in logger_source
    assert 'logAutocompleteSelection(query, "submit")' in logger_source
    assert 'studyLogger.logEvent("searchNoResults"' in logger_source
    assert "data-log-no-results=\"true\"" in search_source


def test_offline_checker_contains_checks_and_manual_checklist():
    source = CHECK_LOGS.read_text(encoding="utf-8")

    assert "Manual pilot checklist:" in source
    assert "duplicate consecutive querySubmitted" in source
    assert "pageNavigationClicked.toPage is null" in source
    assert "webpageOpened not closed" in source
    assert "resultExposureStarted not ended" in source


if __name__ == "__main__":
    for test in (
        test_logger_uses_europe_zurich_timestamp_not_utc_iso,
        test_logged_event_timestamp_has_switzerland_offset,
        test_webpage_closed_has_duration_exit_reason_guard_and_fallback,
        test_answer_submission_closes_open_webpage_before_task_ended,
        test_log_session_warns_only_for_expected_logging_contract_issues,
        test_log_session_writes_full_and_per_task_logs_without_aggregate_outputs,
        test_start_post_resets_server_session_before_new_experiment_state,
        test_client_cleanup_clears_local_session_and_in_memory_logger_state,
        test_duplicate_query_submit_suppression_contract,
        test_italian_pagination_target_parsing,
        test_went_back_return_metadata_contract,
        test_raw_and_sanitized_query_fields_on_serp_contract,
        test_result_exposure_logging_contract,
        test_autocomplete_and_no_results_logging_contract,
        test_offline_checker_contains_checks_and_manual_checklist,
    ):
        test()
