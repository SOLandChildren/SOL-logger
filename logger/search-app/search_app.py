from urllib import response
from flask import Flask, render_template, url_for, request, session, redirect, jsonify
from flask_session import Session
from flask_cors import CORS
import requests, json
from forms import SearchForm
import collections
import math
import os
import csv
import uuid
from datetime import datetime
import re
from spellchecker import SpellChecker
from time import time

app = Flask(__name__)

# -------------------------------------------------
# 1. Core app + session configuration FIRST
# -------------------------------------------------
app.config["SECRET_KEY"] = "OtulwLo7gQ"

app.config.update(
    SESSION_COOKIE_SECURE=False,      # True in production with HTTPS
    SESSION_COOKIE_SAMESITE="Lax",
)

app.config["SESSION_TYPE"] = "filesystem"   # or "redis"
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_USE_SIGNER"] = True

# Initialize server-side sessions
Session(app)

# -------------------------------------------------
# 2. Enable CORS LAST
# -------------------------------------------------
CORS(app, supports_credentials=True)

## old implementation for initialising the Flask APP, keeping it in case new implementation breaks
# app = Flask(__name__)

# CORS(app)

# app.config['SECRET_KEY'] = 'OtulwLo7gQ'       
# app.config.update(
#     SESSION_COOKIE_SECURE=False,    
#     SESSION_COOKIE_SAMESITE='Lax', 
# )

# Session(app)

# f = open("API_keys.json")
# data = json.load(f)

# API_KEY = data["serp_api"]["api_key"]
# SERP_endpoint = data["serp_api"]["SERP_endpoint"]
# f.close()

db_url = "http://search_engine:7002"
rpp = 10  # results per page for pagination; may be changed later

LOG_DIR = 'logs'
os.makedirs(LOG_DIR, exist_ok=True)

# spell = SpellChecker(language='en') 
spell = SpellChecker(language='it') # uncomment for final implementation

with open("API_keys.json") as f:
    API_KEY = json.load(f)["serp_api"]["api_key"]

AUTOCOMPLETE_CACHE = {}
CACHE_TTL = 600  # 10 minutes
MAX_SUGGESTIONS = 5

def sanitize_query(query):
    # Removes all characters except letters, numbers, and spaces
    # This is necessary for PyTerrier compatibility
    cleaned_query =  re.sub(r'[^\w\s]', '', query)
    
    # try:
    words = spell.split_words(cleaned_query)
    misspelled = spell.unknown(words)
    corrected_query = ''

    for word in words:
        if word in misspelled:
            corrected_word = spell.correction(word)
            if corrected_word is not None:
                word = corrected_word
        corrected_query += word
        corrected_query += ' '
    # except:
    #     corrected_query = cleaned_query
    
    ## using external API - edit to suit the specific API used

    # serpapi_payload = {
    #     "engine": "google",
    #     "q": cleaned_query,
    #     "num": 10,
    #     "filter": 0,
    #     "api_key": API_KEY
    #     }
    
    # serpapi_response = requests.get(url=SERP_endpoint, params=serpapi_payload)

    # serpapi_results = serpapi_response.json()
    # serpapi_query = serpapi_results["search_information"].get("showing_results_for", cleaned_query)

    return cleaned_query, corrected_query.strip()

def load_user_topics(filepath='data/user_topics.csv'):
    topics = {}
    with open(filepath, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=',')
        for row in reader:
            user = row['uid']
            topics[user] = {
                '1_short': row['topic1_keyword'],
                '1_full': row['topic1_question'],
                '1_gif': row.get('topic1_gif', '').strip(),
                '2_short': row['topic2_keyword'],
                '2_full': row['topic2_question'],
                '2_gif': row.get('topic2_gif', '').strip(),
                '3_short': row['topic3_keyword'],
                '3_full': row['topic3_question'],
                '3_gif': row.get('topic3_gif', '').strip(),
                'full_gif': row.get('full_gif', '').strip(),
            }
    return topics

USER_TOPICS = load_user_topics()
PUZZLE_ASSET_DIR = 'puzzle_pieces'

# ------------------------------------------------------------------------------------------------------------------------------------------
# TEMPORARY TESTING FLAG - If API GOOGLE IS NOT AVAILABLE, SET TO TRUE TO ALLOW ANSWER SUBMISSION WITHOUT SEARCH RESULTS.
# ------------------------------------------------------------------------------------------------------------------------------------------
# True  = allow answer submission even when there are no search results.
# False = production behavior: answer button only appears after valid results.
ALLOW_ANSWER_WITHOUT_RESULTS_FOR_TESTING = True
#-------------------------------------------------------------------------------------------------------------------------------------------

def get_total_tasks(user_id):
    """Return how many tasks this user has (count non-empty topic entries)."""
    user = USER_TOPICS.get(user_id, {})
    count = 0
    for i in range(1, 10):
        if user.get(f'{i}_full'):
            count += 1
        else:
            break
    return count

def current_phase():
    user_id = session.get('user_id')
    if not user_id:
        return 'pre_id'

    task_number = session.get('task_number')
    pieces = session.get('pieces_earned', [])
    tasks_started = session.get('tasks_started', [])
    total_tasks = get_total_tasks(user_id)

    if total_tasks and len(pieces) >= total_tasks:
        return 'completed'
    if task_number in pieces:
        return 'reward'
    if task_number in tasks_started:
        return 'searching'
    return 'task_intro'

def phase_redirect_url(phase=None):
    if phase is None:
        phase = current_phase()
    if phase == 'pre_id':
        return url_for('welcome')
    if phase == 'task_intro':
        return url_for('task')
    if phase == 'searching':
        return url_for('search_page')
    if phase == 'reward':
        return url_for('reward')
    if phase == 'completed':
        return url_for('thank_you')
    return url_for('welcome')

@app.after_request
def add_no_store_headers(response):
    content_type = response.headers.get('Content-Type', '')
    if content_type.startswith('text/html'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

class PuzzleConfigError(Exception):
    pass

#Global constants for template rendering
ERROR_URL = "error.html"
SEARCH_URL = "search.html"
HOME_URL = "home.html"

def render_puzzle_config_error(message):
    return render_template(ERROR_URL, show_search=False,
                           error_title="Puzzle Configuration Error",
                           error_message=message), 500

def get_user_config(user_id):
    user = USER_TOPICS.get(user_id)
    if not user:
        raise PuzzleConfigError(
            f"No topic configuration found in data/user_topics.csv for user '{user_id}'."
        )
    return user

def validate_puzzle_gif(user_id, csv_field):
    user = get_user_config(user_id)
    filename = user.get(csv_field, '').strip()
    if not filename:
        raise PuzzleConfigError(
            f"Missing '{csv_field}' in data/user_topics.csv for user '{user_id}'."
        )
    if os.path.basename(filename) != filename or not filename.lower().endswith('.gif'):
        raise PuzzleConfigError(
            f"Invalid '{csv_field}' value for user '{user_id}': '{filename}'. "
            "Use a .gif filename stored directly in static/puzzle_pieces."
        )

    static_path = os.path.join(app.static_folder, PUZZLE_ASSET_DIR, filename)
    if not os.path.isfile(static_path):
        raise PuzzleConfigError(
            f"Missing GIF file for user '{user_id}': static/{PUZZLE_ASSET_DIR}/{filename}."
        )
    return f"{PUZZLE_ASSET_DIR}/{filename}"

def get_unlocked_piece(user_id, task_number):
    try:
        task_num = int(task_number)
    except (TypeError, ValueError):
        raise PuzzleConfigError(f"Invalid task number for puzzle reward: '{task_number}'.")

    labels = {
        1: "primo",
        2: "secondo",
        3: "ultimo",
    }
    return {
        'task_num': task_num,
        'label': labels.get(task_num, str(task_num)),
        'static_filename': validate_puzzle_gif(user_id, f'{task_num}_gif'),
    }

@app.context_processor
def base():
    form = SearchForm()
    return dict(
        form=form,
        allow_answer_without_results_for_testing=ALLOW_ANSWER_WITHOUT_RESULTS_FOR_TESTING,
        session_id=session.get('session_id', '')
    )

@app.route("/")
def index():
    return redirect(url_for('welcome'))

@app.route("/welcome")
def welcome():
    """Splash page — SOL Search logo + Start button."""
    if request.args.get('reset') == '1':
        session.clear()
        return render_template("welcome.html", show_search=False)
    if current_phase() != 'pre_id':
        return redirect(phase_redirect_url())
    return render_template("welcome.html", show_search=False)

@app.route("/search")
def search_page():
    """Search bar page — the main SOL Search interface."""
    phase = current_phase()
    if phase not in ('task_intro', 'searching'):
        return redirect(phase_redirect_url(phase))

    # Check session TTL — expire after 60 minutes of inactivity
    last_active = session.get('last_active')
    if last_active:
        elapsed = (datetime.now() - datetime.fromisoformat(last_active)).total_seconds()
        if elapsed > 3600:  # 60 minutes
            session.clear()
            return redirect(url_for('welcome'))
    session['last_active'] = datetime.now().isoformat()

    # Mark this task as started — phase advances to 'searching'.
    task_number = session.get('task_number')
    tasks_started = session.get('tasks_started', [])
    if task_number not in tasks_started:
        tasks_started.append(task_number)
        session['tasks_started'] = tasks_started

    form = SearchForm()
    reminder = USER_TOPICS.get(session.get('user_id'), {}).get(str(session.get('task_number'))+'_full')
    return render_template(HOME_URL, form=form, show_search=True, reminder=reminder)

@app.route('/start', methods=['GET', 'POST'])
def start_page():
    if current_phase() != 'pre_id':
        return redirect(phase_redirect_url())
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        session['user_id'] = user_id
        session['session_id'] = str(uuid.uuid4())
        session['task_number'] = '1'
        session['pieces_earned'] = []
        session['tasks_started'] = []
        return redirect(url_for('task'))
    with open("data/uids.txt") as f:
        val_ids = [line.strip() for line in f if line.strip()]
    return render_template('start.html', show_search=False, valid_ids=val_ids)

@app.route('/task', methods=['GET', 'POST'])
def task():
    phase = current_phase()
    if phase != 'task_intro':
        return redirect(phase_redirect_url(phase))

    user_id = session.get('user_id')
    task_number = session.get('task_number')

    try:
        user = get_user_config(user_id)
    except PuzzleConfigError as err:
        return render_puzzle_config_error(str(err))

    topic = user.get(str(task_number)+'_full')
    topic_title = user.get(str(task_number)+'_short')

    return render_template("task.html", show_search=False, task_number=task_number, topic=topic, topic_title=topic_title, user_id=user_id)

@app.route("/result", methods=['GET', 'POST'])
def result():
    phase = current_phase()
    if phase != 'searching':
        return redirect(phase_redirect_url(phase))

    reminder = USER_TOPICS.get(session.get('user_id'), {}).get(str(session.get('task_number'))+'_full')
    form = SearchForm()
    page = 1

    if request.method == "POST":
        raw_query = request.form.get('query', '').strip()
    else:
        raw_query = (request.args.get("query") or session.get("query") or '').strip()
        try:
            page = max(1, int(request.args.get("page", 1)))
        except (TypeError, ValueError):
            page = 1

    if not raw_query:
        return render_template(HOME_URL,
                               form=form,
                               show_search=True,
                               reminder=reminder,
                               search_error="Inserisci una domanda prima di cercare.")

    url = "/ranking?query="
    url_affix = "&rpp="
    maxres = '100' # max 10 pages with max 10 results each
    rpp = 10 # results per page; may be changed later
    query, serpapi_query = sanitize_query(raw_query)

    if not query.strip():
        return render_template(HOME_URL,
                               form=form,
                               show_search=True,
                               reminder=reminder,
                               search_error="Inserisci una domanda prima di cercare.")

    def render_no_results(message):
        session["search_results"] = []
        session["query"] = query
        session["serpapi_query"] = serpapi_query
        return render_template(SEARCH_URL, title="Search Results",
                               search_results=[], query=query,
                               serpapi_query=serpapi_query, page=page,
                               total_pages=0, show_search=True,
                               reminder=reminder,
                               no_results_message=message)

    def normalize_result(result):
        if not isinstance(result, dict):
            return {}
        result.setdefault("displayed_link", result.get("source_title") or result.get("link", ""))
        result.setdefault("title", "")
        result.setdefault("snippet", "")
        result.setdefault("docid", "")
        result.setdefault("link", "")
        return result

    cached_results = session.get("search_results")
    use_cached_results = (
        request.method == "GET"
        and session.get("query") == query
        and isinstance(cached_results, list)
    )

    if use_cached_results:
        all_results = [normalize_result(result) for result in cached_results]
        serpapi_query = session.get("serpapi_query", serpapi_query)
    else:
        end_query = db_url + url + query + url_affix + maxres

        try:
            response = requests.get(end_query)
        except requests.ConnectionError:
            if ALLOW_ANSWER_WITHOUT_RESULTS_FOR_TESTING:
                return render_no_results("Modalità test: nessun risultato disponibile, ma puoi comunque scrivere una risposta.")
            return render_template(ERROR_URL, show_search=False,
                                error_title="Connection Error",
                                error_message="Could not connect to the search engine. Please try again later.",
                                is_search_engine_error=True), 503

        if response.status_code != 200:
            return render_no_results("Non ci sono risultati per la vostra domanda. Provate a fare un'altra domanda!")

        try:
            search_results = response.json()
        except ValueError:
            return render_no_results("Non ci sono risultati per la vostra domanda. Provate a fare un'altra domanda!")

        if isinstance(search_results, dict):
            all_results = search_results.get("itemlist", [])
        elif isinstance(search_results, list):
            all_results = search_results
        else:
            all_results = []

        all_results = [normalize_result(result) for result in all_results]
        session["search_results"] = all_results
        session["query"] = query
        session["serpapi_query"] = serpapi_query

    if len(all_results) == 0:
        return render_no_results("Non ci sono risultati per la vostra domanda. Provate a fare un'altra domanda!")

    total_results = len(all_results)
    total_pages = min(10, math.ceil(total_results / rpp))
    page = min(page, total_pages)
    start = (page - 1) * rpp
    end = start + rpp
    return render_template(SEARCH_URL, title="Search Results",
                           search_results=all_results[start:end],
                           query=query, serpapi_query=serpapi_query,
                           page=page, total_pages=total_pages,
                           show_search=True, reminder=reminder)

    # f = open("API_keys.json")
    # data = json.load(f)

    # API_KEY = data["serp_api"]["api_key"]
    # SERP_endpoint = data["serp_api"]["SERP_endpoint"]
    # f.close()

    # print(API_KEY, SERP_endpoint)

    # payload = {

    #     "engine": "google",
    #     "q": query,
    #     "start": page * 10,
    #     "num": 10,
    #     "filter": 0,
    #     "api_key": API_KEY

    #     }

    # SERP_response = requests.get(url=SERP_endpoint, params=payload)

    # search_results = SERP_response.json()

    # if len(search_results["organic_results"]) == 0:
    #         pass
    # else:
    #     total_results = len(search_results["organic_results"])
    #     total_pages = min(10, math.ceil(total_results / rpp))
    #     start = (page - 1) * rpp
    #     end = start + rpp
    #     return render_template(SEARCH_URL, title="Search Results", search_results = search_results['itemlist'][start:end], query=query, page=page, total_pages = total_pages, show_search=True, reminder=reminder)

@app.route("/webpage")
def webpage():
    """Embedded web viewer — renders external page in a sandboxed iframe."""
    phase = current_phase()
    if phase != 'searching':
        return redirect(phase_redirect_url(phase))
    url = request.args.get("url", "")
    query = request.args.get("query", "")
    page = request.args.get("page", "1")
    if not url:
        return redirect(url_for('search_page'))
    return render_template("webpage.html", url=url, query=query, page=page, show_search=False)

@app.route("/autocomplete")
def autocomplete():
    query = request.args.get("query")

    if not query or len(query) < 3:
        return jsonify([])

    # ---- Cache lookup ----
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

        return jsonify(suggestions)

    except requests.RequestException as e:
        # graceful fallback (no retries)
        return jsonify([]), 200

@app.route('/log_session', methods=['POST'])
def log_session():
    print("Received /log_session request")
    data = request.get_json(force=False, silent=True) or {}
    print(f"Request JSON data: {data}")

    session_id = data.get('session_id')
    logs = data.get('logs')
    
    user_id = session.get('user_id')
    task_number = session.get('task_number')
    print(f"user_id: {user_id}, task_number: {task_number}, session_id: {session_id}")
    if not (user_id and task_number and session_id and isinstance(logs, list) and logs):
        print("Missing required data: user_id, task_number, session_id or logs")
        return jsonify({"error": "Missing user_id, task_number, session_id or logs"}), 400

    log_id = session.get('log_id')
    if not log_id:
        log_id = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        session['log_id'] = log_id

    filename = f"{user_id}_{log_id}.log"
    filepath = os.path.join(LOG_DIR, filename)

    server_session_id = session.get('session_id')
    with open(filepath, 'a', encoding='utf-8') as f:
        for entry in logs:
            entry['task_number'] = task_number
            if server_session_id:
                entry['sessionID'] = server_session_id
            f.write(json.dumps(entry) + '\n')

    return jsonify({"status": "logged", "file": filename}), 200

@app.route('/end', methods=['POST'])
def end_task():
    phase = current_phase()
    if phase != 'searching':
        return redirect(phase_redirect_url(phase))
    task_number = session.get('task_number')

    # Record the earned puzzle piece for the current task
    pieces = session.get('pieces_earned', [])
    if task_number not in pieces:
        pieces.append(task_number)
        session['pieces_earned'] = pieces

    return redirect(url_for('reward'))

@app.route('/next_task')
def next_task():
    """Advance to the next task number and redirect to the Scenario Page."""
    phase = current_phase()
    if phase != 'reward':
        return redirect(phase_redirect_url(phase))
    task_number = session.get('task_number')
    next_num = str(int(task_number) + 1)
    session['task_number'] = next_num
    return redirect(url_for('task'))

@app.route('/reward')
def reward():
    phase = current_phase()
    if phase not in ('reward', 'completed'):
        return redirect(phase_redirect_url(phase))
    user_id = session.get('user_id')
    task_number = session.get('task_number')
    pieces = session.get('pieces_earned', [])
    total_tasks = get_total_tasks(user_id)
    is_last = len(pieces) >= total_tasks
    try:
        unlocked_piece = get_unlocked_piece(user_id, task_number)
    except PuzzleConfigError as err:
        return render_puzzle_config_error(str(err))

    return render_template('reward.html',
                           show_search=False,
                           task_number=task_number,
                           pieces_earned=pieces,
                           unlocked_piece=unlocked_piece,
                           total_tasks=total_tasks,
                           is_last=is_last)

@app.route('/thank_you')
def thank_you():
    phase = current_phase()
    if phase != 'completed':
        return redirect(phase_redirect_url(phase))
    user_id = session.get('user_id')
    pieces = session.get('pieces_earned', [])
    total_tasks = get_total_tasks(user_id)
    try:
        full_puzzle_static_filename = validate_puzzle_gif(user_id, 'full_gif')
    except PuzzleConfigError as err:
        return render_puzzle_config_error(str(err))
    # Don't clear session yet — the "Finish Experiment" button needs
    # user_id/task_number to send final logs via /log_session.
    # Session will be cleared client-side via clearClientData().
    return render_template('end.html', show_search=False,
                           pieces_earned=pieces,
                           total_tasks=total_tasks,
                           full_puzzle_static_filename=full_puzzle_static_filename)

@app.errorhandler(404)
def page_not_found(e):
    return render_template(ERROR_URL, show_search=False,
                           error_title="Page Not Found",
                           error_message="The page you are looking for does not exist."), 404

@app.errorhandler(500)
def internal_error(e):
    return render_template(ERROR_URL, show_search=False,
                           error_title="Server Error",
                           error_message="Something went wrong on our end. Please try again."), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7001, threaded=True, debug=True)
