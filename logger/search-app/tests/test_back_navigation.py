"""
Tests for back button navigation logging.

These tests cover the native browser back blocker and the app-level back
button logging payloads.

Requirements:
    - selenium
    - pytest
    - Flask app running (or use the fixture)
    - Chrome/Chromium with chromedriver

Run with: pytest tests/test_back_navigation.py -v
"""

import json
import time
import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options


@pytest.fixture(scope="module")
def chrome_options():
    """Configure Chrome options for testing."""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    # Enable BFCache for testing (Chrome 96+)
    options.add_argument("--enable-features=BackForwardCache")
    return options


@pytest.fixture(scope="module")
def driver(chrome_options):
    """Create a Selenium WebDriver instance."""
    driver = webdriver.Chrome(options=chrome_options)
    driver.implicitly_wait(10)
    yield driver
    driver.quit()


@pytest.fixture(scope="module")
def app_url(base_url):
    """
    Return the URL of the running Flask app.

    For integration testing, the app should be running separately.
    Set the SEARCH_APP_URL environment variable to override the default.
    """
    return base_url


def clear_local_storage(driver):
    """Clear localStorage to reset logger state."""
    driver.execute_script("window.localStorage.clear();")


def get_session_logs(driver):
    """Retrieve logged events from localStorage."""
    logs_json = driver.execute_script(
        "return window.localStorage.getItem('sessionLogs');"
    )
    if logs_json:
        return json.loads(logs_json)
    return []


def get_browser_history(driver):
    """Retrieve browser history tracker from localStorage."""
    history_json = driver.execute_script(
        "return window.localStorage.getItem('browserHistory');"
    )
    if history_json:
        return json.loads(history_json)
    return []


def get_log_events(driver, event_type):
    return [
        log for log in get_session_logs(driver)
        if log.get("type") == event_type
    ]


def wait_for_log_event(driver, event_type, minimum_count=1):
    return WebDriverWait(driver, 10).until(
        lambda d: (
            events if len(events := get_log_events(d, event_type)) >= minimum_count else False
        )
    )


def click_viewer_back_to_serp(driver):
    back_button = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.ID, "viewer-back-btn"))
    )
    from_url = driver.current_url
    to_url = back_button.get_attribute("href")
    back_button.click()
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "article.content-section"))
    )
    return from_url, to_url


class TestBackNavigationLogging:
    """Tests for back navigation event logging."""

    def test_browser_back_blocked_event_logs_destination_url(self, driver, app_url, test_user_id):
        """
        Test that native browser Back is blocked and logs destination details.

        Steps:
        1. Navigate to start page and enter user ID
        2. Submit a search query
        3. Click on a search result
        4. Press browser back button
        5. Verify browserBackBlocked includes fromURL and toURL
        """
        # Clear any existing state
        driver.get(app_url + "/start")
        clear_local_storage(driver)

        # Enter user ID (use a test ID that exists in uids.txt)
        try:
            id_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "id-box"))
            )
            id_input.clear()
            id_input.send_keys(test_user_id)

            # Submit the form
            form = driver.find_element(By.ID, "enter-id-form")
            form.submit()
        except Exception:
            # If start page doesn't require ID, navigate directly
            driver.get(app_url)

        # Wait for home page and submit a search query
        search_box = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "search-box"))
        )
        search_box.clear()
        search_box.send_keys("test query")
        search_box.send_keys(Keys.RETURN)

        # Wait for search results
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "article.content-section"))
        )

        initial_logs = get_session_logs(driver)

        # Verify searchResultGenerated events were logged
        result_events = [
            log for log in initial_logs
            if log.get("type") == "searchResultGenerated"
        ]
        assert len(result_events) > 0, "No searchResultGenerated events logged"

        # Click on first search result
        result_link = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "a.result-link"))
        )
        navigation_url = result_link.get_attribute("href")

        # Store the current URL to verify we return to it
        serp_url = driver.current_url

        result_link.click()

        # Wait for navigation away from SERP
        # The click event handler logs before navigation, but we need to wait
        # for the page to actually change
        WebDriverWait(driver, 10).until(
            lambda d: d.current_url != serp_url
        )
        resource_page_url = driver.current_url

        # Navigate back using browser back button
        blocked_count_before = len(get_log_events(driver, "browserBackBlocked"))
        driver.back()
        blocked_events = wait_for_log_event(
            driver,
            "browserBackBlocked",
            blocked_count_before + 1,
        )

        # Now we can read localStorage again (same origin)
        logs_after_back = get_session_logs(driver)

        # Verify clickedResult was logged (happened before navigation)
        click_events = [
            log for log in logs_after_back
            if log.get("type") == "clickedResult"
        ]
        assert len(click_events) > 0, (
            f"clickedResult event not logged. "
            f"Event types found: {[log.get('type') for log in logs_after_back]}"
        )

        assert driver.current_url == resource_page_url, (
            f"Expected browser Back to stay on protected resource page. "
            f"Before: {resource_page_url}, after: {driver.current_url}"
        )

        blocked = blocked_events[-1]
        assert blocked["fromURL"] == resource_page_url
        assert blocked["toURL"], "browserBackBlocked missing toURL"
        assert blocked["url"] == blocked["fromURL"]
        assert blocked["targetURL"] == blocked["toURL"]
        assert not any(log.get("type") == "wentBack" for log in logs_after_back)

        click_event = click_events[0]
        assert click_event["navigationUrl"] == navigation_url, (
            f"clickedResult navigationUrl mismatch. "
            f"Expected {navigation_url}, got {click_event['navigationUrl']}"
        )

    def test_no_duplicate_search_result_events_on_back(self, driver, app_url):
        """
        Test that searchResultGenerated events are NOT duplicated on back navigation.

        Returning via the app-level back button should not log new
        searchResultGenerated events for results already logged.
        """
        # Clear state
        driver.get(app_url + "/start")
        clear_local_storage(driver)

        # Navigate through the flow (simplified - assuming session exists)
        try:
            driver.get(app_url)
            search_box = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "search-box"))
            )
        except Exception:
            pytest.skip("Could not access home page - session may be required")

        # Submit search
        search_box.clear()
        search_box.send_keys("duplicate test")
        search_box.send_keys(Keys.RETURN)

        # Wait for results
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "article.content-section"))
        )

        # Count initial searchResultGenerated events
        initial_logs = get_session_logs(driver)
        initial_result_count = len([
            log for log in initial_logs
            if log.get("type") == "searchResultGenerated"
        ])

        # Click result and return with the app-level back button
        result_link = driver.find_element(By.CSS_SELECTOR, "a.result-link")
        result_link.click()
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "viewer-back-btn"))
        )
        from_url, to_url = click_viewer_back_to_serp(driver)

        time.sleep(0.5)

        # Count searchResultGenerated events after back
        final_logs = get_session_logs(driver)
        final_result_count = len([
            log for log in final_logs
            if log.get("type") == "searchResultGenerated"
        ])

        # Should NOT have duplicate searchResultGenerated events
        assert final_result_count == initial_result_count, (
            f"searchResultGenerated events duplicated on back navigation. "
            f"Before: {initial_result_count}, After: {final_result_count}"
        )

        custom_back_events = get_log_events(driver, "customBackButtonClicked")
        assert custom_back_events, "customBackButtonClicked was not logged"
        assert custom_back_events[-1]["fromURL"] == from_url
        assert custom_back_events[-1]["toURL"] == to_url

    def test_event_listeners_not_duplicated(self, driver, app_url):
        """
        Test that event listeners are not duplicated after back navigation.

        Multiple back navigations should not cause multiple event handlers
        to fire for a single user action.
        """
        driver.get(app_url)
        clear_local_storage(driver)

        try:
            search_box = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "search-box"))
            )
        except Exception:
            pytest.skip("Could not access search page")

        # Submit search
        search_box.send_keys("listener test")
        search_box.send_keys(Keys.RETURN)

        # Wait for results
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "article.content-section"))
        )

        # Click result, return with the app back button, repeat multiple times
        for _ in range(3):
            result_link = driver.find_element(By.CSS_SELECTOR, "a.result-link")
            result_link.click()
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "viewer-back-btn"))
            )
            click_viewer_back_to_serp(driver)
            time.sleep(0.3)

        # Now hover over a result
        logs_before_hover = get_session_logs(driver)

        result = driver.find_element(By.CSS_SELECTOR, "article.content-section")
        webdriver.ActionChains(driver).move_to_element(result).perform()
        time.sleep(0.2)

        logs_after_hover = get_session_logs(driver)

        # Count cursorEnteredSnippet events from this hover
        hover_events_before = len([
            log for log in logs_before_hover
            if log.get("type") == "cursorEnteredSnippet"
        ])
        hover_events_after = len([
            log for log in logs_after_hover
            if log.get("type") == "cursorEnteredSnippet"
        ])

        new_hover_events = hover_events_after - hover_events_before

        # Should only have 1 new hover event, not multiple
        assert new_hover_events == 1, (
            f"Expected 1 cursorEnteredSnippet event, got {new_hover_events}. "
            f"Event listeners may be duplicated."
        )


class TestBFCacheSpecific:
    """
    Tests specifically targeting BFCache behavior.

    Note: BFCache behavior varies by browser and conditions.
    These tests may need adjustment based on the testing environment.
    """

    def test_pageshow_persisted_handling(self, driver, app_url):
        """
        Test that pageshow event with persisted=true is handled correctly.

        This test attempts to trigger BFCache restoration and verify
        the logger properly re-initializes.
        """
        driver.get(app_url)
        clear_local_storage(driver)

        try:
            search_box = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "search-box"))
            )
        except Exception:
            pytest.skip("Could not access search page")

        search_box.send_keys("bfcache test")
        search_box.send_keys(Keys.RETURN)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "article.content-section"))
        )

        # Get session ID before navigation
        session_id_before = driver.execute_script(
            "return window.localStorage.getItem('sessionID');"
        )

        # Navigate away and try native browser Back. The blocker should keep
        # the app on the resource page while preserving the session.
        result_link = driver.find_element(By.CSS_SELECTOR, "a.result-link")
        result_link.click()
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "viewer-back-btn"))
        )
        blocked_count_before = len(get_log_events(driver, "browserBackBlocked"))
        driver.back()
        wait_for_log_event(driver, "browserBackBlocked", blocked_count_before + 1)

        # Verify session ID is preserved (loaded from localStorage)
        session_id_after = driver.execute_script(
            "return window.studyLogger ? window.studyLogger.sessionID : null;"
        )

        assert session_id_after == session_id_before, (
            f"Session ID mismatch after back navigation. "
            f"Before: {session_id_before}, After: {session_id_after}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
