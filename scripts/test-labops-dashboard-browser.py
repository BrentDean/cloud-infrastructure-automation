#!/usr/bin/env python3
"""End-to-end browser evidence for the local-only Docker/PostgreSQL LabOps lab.

CI runs this while Compose is alive. All events use RFC 5737 example IPs and
explicit synthetic text; the script neither provisions AWS nor reads T-Pot.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
import re

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "dashboard"
ARTIFACTS.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:" + os.environ.get("API_TEST_PORT", "18080")
API = BASE + "/api/v1/incidents"


def post_json(url, body, method="POST"):
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=12) as response:
        assert response.status in (200, 201)
        return json.load(response)


def synthetic_incident(title, severity, status):
    record = post_json(API, {
        "title": title,
        "description": "Synthetic operator training record; no real user or host data.",
        "severity": severity,
    })["incident"]
    if status != "open":
        record = post_json(API + "/" + record["id"], {
            "status": status,
            "notes": "Synthetic triage notes for dashboard browser testing.",
        }, method="PATCH")["incident"]
    return record


# Add distinct labels/statuses so the screenshot demonstrates an actual
# incident queue, rather than a hard-coded demo dashboard with fake counters.
synthetic_incident("Synthetic suspicious login campaign", "critical", "investigating")
synthetic_incident("Synthetic HTTP anomaly review", "medium", "open")
synthetic_incident("Synthetic overnight health incident", "low", "resolved")

errors = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
    context = browser.new_context(
        viewport={"width": 1500, "height": 1000}, device_scale_factor=1,
    )
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE + "/dashboard", wait_until="networkidle", timeout=30000)
    expect(page).to_have_title("LabOps · Security operations")
    expect(page.locator("#connection-pill")).to_have_attribute("data-state", "online")
    assert page.locator("#new-incident-button").evaluate(
        "(el) => getComputedStyle(el).backgroundColor"
    ) == "rgb(18, 99, 255)"
    assert page.locator(".connection-pill .status-dot").evaluate(
        "(el) => getComputedStyle(el).backgroundColor"
    ) == "rgb(18, 201, 149)"
    expect(page.locator(".footer-brand")).to_have_text("A LaunchShell project")
    expect(page.locator("#count-visible")).to_have_text("4")
    expect(page.locator("#incident-list .incident-row")).to_have_count(4)
    expect(page.locator("#case-title")).not_to_be_empty()

    # Create through the visible browser workflow, not a test-only endpoint.
    page.locator("#new-incident-button").click()
    expect(page.locator("#create-dialog")).to_be_visible()
    page.locator("#new-title").fill("Synthetic repeated SSH login failures")
    page.locator("#new-description").fill(
        "Investigate five failed root/admin logins from a documentation IP."
    )
    page.locator("#new-severity").select_option("high")
    page.locator("#submit-create").click()
    expect(page.locator("#create-dialog")).not_to_be_visible()
    expect(page.locator("#count-visible")).to_have_text("5")
    expect(page.locator("#case-title")).to_have_text(
        "Synthetic repeated SSH login failures"
    )
    selected = page.url.split("incident=", 1)[1].split("&", 1)[0].split("#", 1)[0]
    assert re.fullmatch(r"[0-9a-f-]{36}", selected)

    page.locator("#case-status").select_option("investigating")
    page.locator("#case-notes").fill("Synthetic evidence reviewed; no response issued.")
    page.locator("#save-triage").click()
    expect(page.locator("#triage-message")).to_have_text("Saved to PostgreSQL")
    expect(page.locator("#count-investigating")).to_have_text("3")

    # Intake is now a real browser workflow, not exclusively a curl/API exercise.
    expect(page.locator("#new-event-button")).to_be_enabled()
    page.locator("#new-event-button").click()
    expect(page.locator("#event-dialog")).to_be_visible()
    expect(page.locator("#event-incident-title")).to_have_text(
        "Synthetic repeated SSH login failures"
    )
    page.locator("#new-event-ip").fill("8.8.8.8")
    page.locator("#new-event-username").fill("root")
    page.locator("#submit-event").click()
    expect(page.locator("#event-create-error")).to_contain_text("reserved documentation IP")

    page.locator("#new-event-ip").fill("198.51.100.23")
    expect(page.locator("#event-create-error")).not_to_be_visible()
    page.screenshot(path=str(ARTIFACTS / "desktop-event-intake.png"), full_page=True)

    # A failed browser request must leave the modal, immutable idempotency key
    # and observed timestamp intact so a retry cannot create a duplicate.
    post_target = re.compile(r"/api/v1/incidents/[0-9a-f-]+/events$")
    attempts = []

    def simulated_outage(route):
        attempts.append(route.request.post_data_json)
        route.fulfill(
            status=503,
            content_type="application/json",
            body='{"error":{"code":"database_unavailable","message":"Incident storage is unavailable"}}',
        )

    page.route(post_target, simulated_outage)
    first_observed = page.locator("#new-event-observed").inner_text()
    page.locator("#submit-event").click()
    expect(page.locator("#event-create-error")).to_contain_text("retry")
    expect(page.locator("#event-dialog")).to_be_visible()
    expect(page.locator("#new-event-observed")).to_have_text(first_observed)
    assert len(attempts) == 1
    page.unroute(post_target)
    with page.expect_request(
        lambda req: re.search(post_target, req.url) and req.method == "POST"
    ) as actual_request:
        page.locator("#submit-event").click()
    assert actual_request.value.post_data_json == attempts[0]
    assert attempts[0]["source_event_id"].startswith("manual-ui-")
    expect(page.locator("#event-dialog")).not_to_be_visible()
    expect(page.locator("#event-action-message")).to_contain_text("saved")
    expect(page.locator("#event-count")).to_have_text("1")
    expect(page.locator("#analysis-attempts")).to_have_text("1")

    observed = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    for number in range(1, 5):
        post_json(API + "/" + selected + "/events", {
            "source": "cowrie",
            "event_type": "cowrie.login.failed",
            "source_event_id": "dashboard-browser-primary-" + str(number),
            "source_ip": "198.51.100.23",
            "username": "root" if number < 2 else "admin",
            "observed_at": observed,
        })
    for number in range(2):
        post_json(API + "/" + selected + "/events", {
            "source": "cowrie",
            "event_type": "cowrie.login.failed",
            "source_event_id": "dashboard-browser-secondary-" + str(number),
            "source_ip": "203.0.113.7",
            "username": "test-user",
            "observed_at": observed,
        })

    page.locator("#refresh-button").click()
    expect(page.locator("#event-count")).to_have_text("7")
    expect(page.locator("#analysis-attempts")).to_have_text("7")
    expect(page.locator("#analysis-ips")).to_have_text("2")
    expect(page.locator(".source-row")).to_have_count(2)
    expect(page.locator(".source-row").first).to_have_attribute("data-signal", "true")
    expect(page.locator(".source-row").last).to_have_attribute("data-signal", "false")
    page.screenshot(path=str(ARTIFACTS / "desktop-incident-investigation.png"), full_page=True)

    # Persisted selection and triage survive a new browser page load.
    page.reload(wait_until="networkidle")
    expect(page.locator("#case-status")).to_have_value("investigating")
    expect(page.locator("#case-notes")).to_have_value(
        "Synthetic evidence reviewed; no response issued."
    )
    expect(page.locator("#event-count")).to_have_text("7")
    expect(page.locator("#analysis-attempts")).to_have_text("7")

    # Simulate a 503 response only in the browser. Retain stale UI with a
    # conspicuous error banner rather than silently replacing it with zeros.
    outage = re.compile(r"/api/v1/incidents\?limit=100$")
    page.route(outage, lambda route: route.fulfill(
        status=503, content_type="application/json",
        body='{"error":{"code":"database_unavailable","message":"Incident storage is unavailable"}}',
    ))
    page.locator("#refresh-button").click()
    expect(page.locator("#global-error")).to_be_visible()
    expect(page.locator("#count-visible")).to_have_text("5")
    page.screenshot(path=str(ARTIFACTS / "desktop-error-state.png"), full_page=True)
    page.unroute(outage)
    page.locator("#refresh-button").click()
    expect(page.locator("#global-error")).not_to_be_visible()

    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.locator("#count-visible")).to_be_visible()
    expect(page.locator("#case-title")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), (
        "Mobile dashboard has unexpected horizontal overflow"
    )
    page.screenshot(path=str(ARTIFACTS / "mobile-incident-investigation.png"), full_page=True)
    assert not errors, "Browser JavaScript errors: " + "; ".join(errors)

    context.close()
    browser.close()

print("PASS: Chromium UI incident triage, synthetic event intake/retry, investigation, persisted reload, "
      "503/recovery, mobile layout; synthetic screenshots saved to artifacts/dashboard")
