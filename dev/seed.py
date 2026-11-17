#!/usr/bin/env python3
"""Seeds the local dev Gitea with realistic data for theme work.

Users and the org are created idempotently; repo content is seeded only when revikalabs/web does not exist.
To reseed from scratch: docker compose -f dev/docker-compose.yml down -v && up -d.
"""
import base64
import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:3300/api/v1"
ADMIN, PASSWORD = "revika", "revika-dev-pass"
COMPOSE_FILE = pathlib.Path(__file__).resolve().parent / "docker-compose.yml"
COMPOSE = ["docker", "compose", "-f", str(COMPOSE_FILE), "exec", "-T", "gitea"]


def wait_ready(timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE.removesuffix("/api/v1") + "/api/healthz", timeout=3):
                return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(2)
    sys.exit("Gitea is not reachable on http://localhost:3300; start it: docker compose -f dev/docker-compose.yml up -d")
ORG, REPO = "revikalabs", "web"


def api(method, path, body=None, user=ADMIN, ok404=False):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{ADMIN}:{PASSWORD}".encode()).decode())
    if user != ADMIN:
        # Admin acts on behalf of other users so the timeline has several authors.
        req.add_header("Sudo", user)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        if ok404 and e.code in (404, 409, 422):
            return None
        sys.exit(f"{method} {path} failed: {e.code} {e.read().decode()[:300]}")


def create_admin():
    cmd = COMPOSE + ["gitea", "admin", "user", "create", "--admin", "--username", ADMIN,
                     "--password", PASSWORD, "--email", "revika@example.com", "--must-change-password=false"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 and "already exists" not in res.stdout + res.stderr:
        sys.exit(f"admin create failed: {res.stdout}{res.stderr}")


USERS = [("lena", "Lena Petrova"), ("didier", "Didier Martin"), ("andreas", "Andreas Weber"),
         ("karri", "Karri Saarinen"), ("nan", "Nan Yu")]


def put_file(path, content, message, branch="main", author=ADMIN):
    existing = api("GET", f"/repos/{ORG}/{REPO}/contents/{path}?ref={branch}", ok404=True)
    body = {"content": base64.b64encode(content.encode()).decode(), "message": message, "branch": branch}
    if existing:
        body["sha"] = existing["sha"]
        return api("PUT", f"/repos/{ORG}/{REPO}/contents/{path}", body, user=author)
    return api("POST", f"/repos/{ORG}/{REPO}/contents/{path}", body, user=author)


README = """# Revika Web

Customer-facing web client for Revika. React 19, TypeScript, Vite.

## Getting started

```sh
pnpm install
pnpm dev
```

## Structure

| Path | What lives there |
| --- | --- |
| `src/views` | Route-level screens |
| `src/hooks` | Data hooks over the API client |
| `src/ui` | Shared primitives |

> Run `pnpm test` before opening a pull request.
"""

HOOK_V1 = """import { useComputed } from "../state";
import type { Ride } from "../api/types";

export function useRideHistory(rides: Ride[]) {
  const cancelledRideIds = rides.filter((r) => r.status === "cancelled").map((r) => r.id);
  const ridesAwaitingPickup = rides.filter((r) => r.status === "awaiting");

  // Build sections from ride history state
  const dimmedIds: Set<string> = useComputed(() => {
    const ids = new Set<string>();
    for (const id of cancelledRideIds) {
      ids.add(id);
    }
    for (const ride of ridesAwaitingPickup) {
      ids.add(ride.id);
    }
    return ids;
  });

  return { dimmedIds };
}
"""

HOOK_V2 = """import { useComputed } from "../state";
import type { Ride } from "../api/types";

export function useRideHistory(rides: Ride[]) {
  const ridesAwaitingPickup = rides.filter((r) => r.status === "awaiting");
  const ridesInProgress = rides.filter((r) => r.status === "in_progress");

  // Build sections from ride history state
  const waitingStatusById: Map<string, string> = useComputed(() => {
    const map = new Map<string, string>();
    for (const ride of ridesAwaitingPickup) {
      map.set(ride.id, "Driver en route");
    }

    for (const ride of ridesInProgress) {
      map.set(ride.id, "Trip in progress");
    }
    return map;
  });

  return { waitingStatusById };
}
"""

PAGE_V1 = """import { useRideHistory } from "../hooks/useRideHistory";

export function RideHistoryPage({ rides }) {
  const { dimmedIds } = useRideHistory(rides);
  return rides.map((ride) => (
    <RideRow key={ride.id} ride={ride} dimmed={dimmedIds.has(ride.id)} />
  ));
}
"""

PAGE_V2 = """import { useRideHistory } from "../hooks/useRideHistory";

export function RideHistoryPage({ rides }) {
  const { waitingStatusById } = useRideHistory(rides);
  return rides.map((ride) => (
    <RideRow key={ride.id} ride={ride} byline={waitingStatusById.get(ride.id)} />
  ));
}
"""

LABELS = [("Bug", "#eb5757"), ("Design", "#4ea7fc"), ("Performance", "#4cb782"), ("iOS", "#f2c94c"),
          ("Android", "#5e6ad2"), ("System2026", "#f2994a"), ("AI", "#9b9b9b")]

ISSUES = [
    ("Faster app launch", "Render UI before `vehicle_state` sync when minimum required state is present, "
     "instead of blocking on full refresh during iOS startup.", ["Performance", "iOS"], "karri", False),
    ("App freezes on splash screen", "After launch, the splash screen remains visible indefinitely with no "
     "change in state. The app does not progress to the homescreen.", ["Bug"], "nan", False),
    ("Show last known vehicle location", "When GPS is unavailable show the last known position with a timestamp.",
     [], "lena", False),
    ("Graceful error state when network drops", "Replace the infinite spinner with an inline retry state.",
     ["Design"], "didier", False),
    ("Sync on reconnect", "Queue mutations offline and replay them when the connection is back.",
     ["iOS", "System2026"], "andreas", False),
    ("Optimize state hydration", "Hydrate only the visible screen first.", ["Performance"], "karri", False),
    ("Improve empty states", "Empty lists should explain what to do next.", ["Android"], "lena", True),
    ("Align typography with updated system", "Use the new type scale everywhere.", ["iOS", "System2026"],
     "didier", True),
    ("TypeError: Cannot read properties of undefined (reading 'id')", "Seen in Sentry on the ride history page.",
     ["Bug"], "andreas", False),
    ("Refresh ride status screen visuals", "Follow the new status card spec.", ["Design"], "nan", False),
]

COMMENTS = [
    ("lena", "Anyone else noticing the iOS app feels slow to open if you haven't used it in a bit?"),
    ("didier", "Yea, we're still blocking initial render on a full `vehicle_state` sync every time..."),
    ("andreas", "Feels like we could render sooner and load the rest in the background. Probably also worth "
     "tracking startup timing so we know how often this happens!"),
]


def main():
    wait_ready()
    create_admin()
    for login, full in USERS:
        api("POST", "/admin/users", {"username": login, "full_name": full, "email": f"{login}@example.com",
                                     "password": PASSWORD, "must_change_password": False}, ok404=True)
    api("POST", "/orgs", {"username": ORG, "full_name": "Revika Labs", "visibility": "public"}, ok404=True)
    team = api("GET", f"/orgs/{ORG}/teams")[0]
    for login, _ in USERS:
        api("PUT", f"/teams/{team['id']}/members/{login}", ok404=True)

    if api("GET", f"/repos/{ORG}/{REPO}", ok404=True):
        print("revikalabs/web exists, content not reseeded; reset with: docker compose -f dev/docker-compose.yml down -v")
        return

    api("POST", f"/orgs/{ORG}/repos", {"name": REPO, "description": "Customer-facing web client",
                                       "default_branch": "main", "auto_init": True, "readme": "Default"})
    put_file("README.md", README, "docs: describe project layout")
    put_file("package.json", json.dumps({"name": "revika-web", "private": True, "scripts": {
        "dev": "vite", "build": "tsc -b && vite build", "test": "vitest"}}, indent=2) + "\n",
             "chore: add package.json", author="lena")
    put_file("src/hooks/useRideHistory.ts", HOOK_V1, "feat: ride history hook", author="didier")
    put_file("src/views/RideHistoryPage.tsx", PAGE_V1, "feat: ride history page", author="andreas")
    put_file(".gitignore", "node_modules\ndist\n", "chore: gitignore")

    api("POST", f"/repos/{ORG}/{REPO}/branches", {"new_branch_name": "ride/drv-364-reset-dimmed-rows",
                                                   "old_branch_name": "main"})
    put_file("src/hooks/useRideHistory.ts", HOOK_V2, "fix: replace dimmedIds with waitingStatusById",
             branch="ride/drv-364-reset-dimmed-rows", author="karri")
    put_file("src/views/RideHistoryPage.tsx", PAGE_V2, "fix: use byline instead of dimming",
             branch="ride/drv-364-reset-dimmed-rows", author="karri")

    label_ids = {}
    for name, color in LABELS:
        label_ids[name] = api("POST", f"/repos/{ORG}/{REPO}/labels", {"name": name, "color": color})["id"]
    milestone = api("POST", f"/repos/{ORG}/{REPO}/milestones",
                    {"title": "Cycle 144", "description": "Startup performance", "due_on": "2026-12-01T00:00:00Z"})

    issue_ids = []
    for i, (title, body, labels, author, closed) in enumerate(ISSUES):
        issue = api("POST", f"/repos/{ORG}/{REPO}/issues", {
            "title": title, "body": body, "labels": [label_ids[l] for l in labels],
            "assignees": [USERS[i % len(USERS)][0]], "milestone": milestone["id"] if i < 6 else None}, user=author)
        issue_ids.append((issue["number"], issue["id"]))
        if closed:
            api("PATCH", f"/repos/{ORG}/{REPO}/issues/{issue['number']}", {"state": "closed"})
    for author, text in COMMENTS:
        api("POST", f"/repos/{ORG}/{REPO}/issues/{issue_ids[0][0]}/comments", {"body": text}, user=author)
    api("POST", f"/repos/{ORG}/{REPO}/issues/{issue_ids[0][0]}/comments",
        {"body": "@karri can you take a stab at this?"}, user="nan")

    pr = api("POST", f"/repos/{ORG}/{REPO}/pulls", {
        "title": "Reset dimmed ride rows", "head": "ride/drv-364-reset-dimmed-rows", "base": "main",
        "body": "Removed `dimmedIds` — `isItemDimmed` now checks `waitingStatusById` directly.\n\n"
                f"Fixes #{issue_ids[0][0]}", "labels": [label_ids["Performance"]], "assignees": ["karri"]},
        user="karri")
    api("POST", f"/repos/{ORG}/{REPO}/pulls/{pr['number']}/reviews", {
        "event": "COMMENT", "body": "Mostly looks good, one question.",
        "comments": [{"path": "src/hooks/useRideHistory.ts", "new_position": 9,
                      "body": "Do we need both waitingStatusById and dimmedIds here?"}]}, user="nan")

    project = api("POST", f"/repos/{ORG}/{REPO}/projects", {"title": "Offline Mode", "template_type": "none",
                                                             "card_type": "text_only"})
    columns = {}
    for title in ["Backlog", "Todo", "In Progress", "Done"]:
        columns[title] = api("POST", f"/repos/{ORG}/{REPO}/projects/{project['id']}/columns", {"title": title})["id"]
    placement = ["In Progress", "Todo", "Todo", "In Progress", "Backlog", "Todo", "Done", "Done", "Backlog", "Todo"]
    for (_, global_id), col in zip(issue_ids, placement):
        api("POST", f"/repos/{ORG}/{REPO}/projects/{project['id']}/columns/{columns[col]}/issues/{global_id}")

    for name in ["api", "infra", "mobile"]:
        api("POST", f"/orgs/{ORG}/repos", {"name": name, "description": f"Revika {name}", "auto_init": True})
    print(f"seeded: http://localhost:3300/{ORG}/{REPO}  login {ADMIN} / {PASSWORD}")


if __name__ == "__main__":
    main()
