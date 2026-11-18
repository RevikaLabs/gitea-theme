#!/usr/bin/env python3
"""Seeds the local dev Gitea with realistic data for theme work.

Users and the org are created idempotently; repo content is seeded only when revikalabs/web does not exist.
On every run main() also calls enrich(), which tops the seed up with extra orgs, issues, pull requests,
releases, wiki pages, stars and follows. enrich() is idempotent via a closed marker issue
("Seed marker: enrich v1"); when the marker is present only orgs, visibility, stars and follows are refreshed.
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


def api(method, path, body=None, user=ADMIN, ok404=False, ok400=False):
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
        # ok400 is only for the wiki endpoints: Gitea answers "page already exists" with 400, not 409.
        if (ok404 and e.code in (404, 409, 422)) or (ok400 and e.code == 400):
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


def put_file(path, content, message, branch="main", author=ADMIN, repo=REPO, org=ORG):
    existing = api("GET", f"/repos/{org}/{repo}/contents/{path}?ref={branch}", ok404=True)
    if existing and base64.b64decode(existing["content"]).decode() == content:
        return existing  # already up to date, do not create an empty commit
    body = {"content": base64.b64encode(content.encode()).decode(), "message": message, "branch": branch}
    if existing:
        body["sha"] = existing["sha"]
        return api("PUT", f"/repos/{org}/{repo}/contents/{path}", body, user=author)
    return api("POST", f"/repos/{org}/{repo}/contents/{path}", body, user=author)


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

README_BRANCH = README + """
## Loading states

Lists render `SkeletonRows` from `src/ui/Skeleton` while data is in flight.
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

PAGE_V3 = """import { useRideHistory } from "../hooks/useRideHistory";
import { SkeletonRows } from "../ui/Skeleton";

export function RideHistoryPage({ rides, loading }) {
  const { waitingStatusById } = useRideHistory(rides);
  if (loading) {
    return <SkeletonRows rows={6} rowHeight={72} />;
  }
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

# ---------------------------------------------------------------------------
# enrich() data: extra orgs, issues, commits and PR branches.
# ---------------------------------------------------------------------------

ENRICH_ORGS = {
    "northwind": {
        "full_name": "Northwind Studio",
        "description": "Design systems and brand tooling",
        "owners": ["lena", "karri"],
        "repos": {"design-tokens": "Shared design tokens for Revika surfaces",
                  "brand-site": "Northwind marketing site"},
    },
    "openfleet": {
        "full_name": "OpenFleet",
        "description": "Open telematics stack",
        "owners": ["andreas", "nan"],
        "repos": {"telemetry": "Vehicle telemetry ingestion service",
                  "fleet-cli": "Command line tools for fleet operators"},
    },
}

STARS = {"lena": ["api"], "didier": ["infra"], "andreas": ["mobile"], "karri": ["api"], "nan": ["infra"]}
FOLLOWS = {"lena": ["didier", "karri"], "didier": ["lena", "andreas"], "andreas": ["karri", "nan"],
           "karri": ["lena", "nan"], "nan": ["andreas", "lena"]}

# title, body, labels, author, closed, milestone cycle ("144", "145" or None)
ENRICH_ISSUES = [
    ("Ride receipt PDF misses VAT line",
     "The JSON payload has the VAT line, but the rendered receipt drops it whenever it follows a surge line.",
     ["Bug"], "lena", False, "145"),
    ("Add skeleton loaders to trip list",
     "Replace the trip list spinner with skeleton rows so the layout does not jump when data lands.",
     ["Design"], "didier", False, "145"),
    ("Trip list virtualization drops rows and leaves blank gaps after about five hundred rides",
     "Scrolling past roughly 500 entries skips rows. Likely the window recalculation in the virtualized list.",
     ["Bug", "Performance"], "karri", False, None),
    ("Map viewport resets when rotating the device",
     "Camera zoom and center are lost on orientation change; they should persist per session.",
     ["Bug"], "nan", False, "144"),
    ("Deep link from a driver chat does not resolve to the trip screen on a cold start",
     "Opening revika://ride/8817 when the app was killed shows the home screen instead of the trip.",
     ["Bug"], "andreas", True, "144"),
    ("Promo code input rejects valid codes with leading spaces",
     "Trim the value before validation; several support tickets report this.",
     ["Bug"], "lena", True, "144"),
    ("Switch fare estimates to streaming updates",
     "Polling every 5 seconds wastes battery; move to the streaming fare endpoint.",
     ["Performance"], "karri", False, "144"),
    ("Dark theme contrast fails WCAG AA on fare chips",
     "Muted text on the dark fare chip measures 3.9:1; it needs a lighter tone.",
     ["Design"], "nan", True, None),
    ("Add ride sharing ETA badges to scheduled rides screen",
     "Show the co-rider pickup ETA next to each scheduled ride.",
     ["Design"], "didier", False, "145"),
    ("Offline queue replays duplicate tip adjustments",
     "Retried mutations are not deduplicated, so tips are applied twice after a reconnect.",
     ["Bug"], "andreas", False, "144"),
    ("Trip detail map should keep the driver marker centered during pickup",
     "Camera should follow the marker smoothly instead of snapping on every position update.",
     ["Design"], "lena", False, None),
    ("Redesign payment methods sheet per new spec",
     "New sheet layout with saved cards, Apple Pay and invoicing tabs.",
     ["Design"], "karri", False, "145"),
    ("Session silently expires while a trip is in progress",
     "Long trips outlive the token lifetime; refresh must happen without interrupting the ride screen.",
     ["Bug"], "nan", True, None),
    ("Support partial refunds in the receipt view",
     "Refund lines currently collapse into one total; each partial refund should be listed separately.",
     ["Design"], "didier", False, None),
    ("Latency spike on /api/rides/active after drivers go online",
     "P95 jumps to 4 seconds for a few minutes every morning; probably a cache stampede.",
     ["Performance"], "andreas", False, "144"),
    ("Keyboard covers the promo input on checkout for viewports narrower than 640 pixels",
     "On small screens the keyboard hides the promo field, so users cannot see what they type.",
     ["Bug"], "nan", False, None),
    ("Add unit tests for the fare breakdown util",
     "Cover surge, VAT and rounding; the tip rounding case is already handled.",
     ["Performance"], "karri", True, "144"),
    ("Chat unread counter does not clear after opening a thread",
     "The badge persists until the next poll cycle; it should clear optimistically.",
     ["Bug"], "lena", False, None),
    ("Migrate the ride state machine to xstate",
     "The ad-hoc reducer has grown unreadable; move to an explicit state machine.",
     ["System2026"], "nan", False, None),
    ("Driver arrived notification fires before the marker actually reaches the pickup pin",
     "The notification races the live position; gate it on distance below 20 meters.",
     ["Bug"], "didier", True, "145"),
    ("Scheduled rides list ignores timezone changes mid-session",
     "Crossing a timezone border reorders upcoming rides until reload.",
     ["Bug"], "andreas", False, "144"),
    ("Add a saved places onboarding carousel",
     "First-run users should be prompted to add home and work right after sign in.",
     ["Design"], "karri", False, None),
    ("Trip history rows are not focusable via keyboard",
     "Rows are plain divs without tabindex, so tab navigation and screen readers skip them.",
     ["Bug"], "lena", True, "144"),
    ("Investigate the flaky E2E spec for the payment flow (fails about one in eight CI runs)",
     "payment-checkout.spec always fails after the 3DS step when it fails; screenshots show a stale iframe.",
     ["System2026"], "nan", False, "144"),
    ("Reduce bundle size by splitting the map SDK into an async chunk",
     "The map SDK is 1.1 MB and blocks first paint; load it only on screens that need it.",
     ["Performance"], "didier", True, "145"),
]

# (issue index into ENRICH_ISSUES, [(author, text), ...])
ENRICH_COMMENTS = [
    (0, [("karri", "Reproduced on staging: the payload has the VAT line, the renderer drops anything that "
                   "comes after a `surge` line."),
         ("andreas", "The PDF template only iterates the first four fare lines. Easy fix, but let's agree "
                     "on the layout first.")]),
    (1, [("didier", "Draft of the component is up on the skeleton branch:\n\n```tsx\n"
                    "<SkeletonRows rows={6} rowHeight={72} />\n```\n\nRow height matches `RideRow`, so "
                    "nothing jumps when the data lands.")]),
    (3, [("lena", "Only happens after a route change — `fitBounds` runs before the map has a size."),
         ("nan", "Confirmed, and it also loses the saved viewport. Attaching a screencast next.")]),
    (9, [("andreas", "Trace from Sentry — retries generate a fresh request id, so the replay guard never "
                     "matches:\n\n| Attempt | Request id | Replayed |\n| --- | --- | --- |\n"
                     "| 1 | rq_8812 | no |\n| 2 | rq_8819 | yes (bug) |")]),
    (12, [("nan", "The 401 handler clears the session but does not pause the trip timer, so the fare "
                  "keeps ticking."),
          ("karri", "Ouch. The interceptor should suspend timers until re-auth completes."),
          ("lena", "I can pick this up once the receipt fix is merged.")]),
    (16, [("andreas", "The tip rounding case is already covered; adding surge and VAT cases today.")]),
]

# Extra commits on main, applied before any branch is cut.
MAIN_COMMITS = [
    ("src/api/client.ts", """const BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

export class ApiError extends Error {
  constructor(readonly status: number, readonly body: string) {
    super(`API ${status}: ${body}`);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}
""", "feat: typed API client", "lena"),
    ("src/api/types.ts", """export type RideStatus = "awaiting" | "in_progress" | "completed" | "cancelled";

export interface Ride {
  id: string;
  status: RideStatus;
  pickup: Place;
  dropoff: Place;
  fare: Fare;
  driver: Driver;
}

export interface Place { lat: number; lng: number; label: string; }
export interface Fare { total: number; currency: string; breakdown: FareLine[]; }
export interface FareLine { kind: "base" | "distance" | "time" | "surge" | "vat"; amount: number; }
export interface Driver { id: string; name: string; vehicle: string; rating: number; }
""", "feat: shared API types", "didier"),
    ("src/api/rides.ts", """import { api } from "./client";
import type { Ride } from "./types";

export function listRides(limit = 50): Promise<Ride[]> {
  return api<Ride[]>(`/rides?limit=${limit}`);
}

export function getRide(id: string): Promise<Ride> {
  return api<Ride>(`/rides/${id}`);
}

export function cancelRide(id: string): Promise<void> {
  return api(`/rides/${id}/cancel`, { method: "POST" });
}
""", "feat: rides endpoints", "karri"),
    ("src/ui/Button.tsx", """import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "danger";

const styles: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700",
  secondary: "bg-transparent ring-1 ring-line hover:bg-surface",
  danger: "bg-danger text-white hover:bg-danger-strong",
};

export function Button({ variant = "primary", ...rest }:
                       ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return <button className={`rounded-xl px-4 py-2 text-sm font-medium ${styles[variant]}`} {...rest} />;
}
""", "feat: Button primitive", "nan"),
    ("src/ui/Spinner.tsx", """export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="spinner">
      <span className="spinner-wheel" aria-hidden />
      <span className="sr-only">{label}…</span>
    </div>
  );
}
""", "feat: Spinner primitive", "karri"),
    ("src/hooks/usePromoCode.ts", """import { useState } from "react";
import { api } from "../api/client";

export function usePromoCode(rideId: string) {
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  async function apply(code: string) {
    setApplying(true);
    setError(null);
    try {
      await api(`/rides/${rideId}/promo`, { method: "POST", body: JSON.stringify({ code: code.trim() }) });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Promo code rejected");
    } finally {
      setApplying(false);
    }
  }

  return { apply, applying, error };
}
""", "feat: promo code hook", "lena"),
    ("src/views/ReceiptView.tsx", """import type { Ride } from "../api/types";

export function ReceiptView({ ride }: { ride: Ride }) {
  return (
    <section className="receipt">
      <h2>Ride receipt</h2>
      <dl>
        {ride.fare.breakdown.map((line) => (
          <div key={line.kind} className="fare-line">
            <dt>{line.kind}</dt>
            <dd>{line.amount.toFixed(2)} {ride.fare.currency}</dd>
          </div>
        ))}
        <div className="fare-total">
          <dt>Total</dt>
          <dd>{ride.fare.total.toFixed(2)} {ride.fare.currency}</dd>
        </div>
      </dl>
    </section>
  );
}
""", "feat: ride receipt view", "andreas"),
    ("src/ui/FareChip.tsx", """export function FareChip({ total, currency, surge }:
                        { total: number; currency: string; surge?: number }) {
  return (
    <span className="fare-chip" data-surge={surge ? surge.toFixed(1) : undefined}>
      {total.toFixed(2)} {currency}
      {surge && surge > 1 ? <em className="surge-note"> ×{surge.toFixed(1)} surge</em> : null}
    </span>
  );
}
""", "feat: fare chip", "didier"),
]

SKELETON = """type Tone = "soft" | "strong";

const tones: Record<Tone, string> = {
  soft: "bg-surface-sunken",
  strong: "bg-surface-raised",
};

export function Skeleton({ height = 16, width, tone = "soft" }:
                         { height?: number; width?: number | string; tone?: Tone }) {
  return (
    <span aria-hidden className={`skeleton ${tones[tone]}`} style={{ height, width: width ?? "100%" }} />
  );
}

export function SkeletonRows({ rows = 6, rowHeight = 64 }: { rows?: number; rowHeight?: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} height={rowHeight} />
      ))}
    </>
  );
}
"""

RECEIPT_V2 = """import type { Ride } from "../api/types";

export function ReceiptView({ ride }: { ride: Ride }) {
  return (
    <section className="receipt">
      <h2>Ride receipt</h2>
      <dl>
        {ride.fare.breakdown.map((line) => (
          <div key={line.kind} className="fare-line">
            <dt>{line.kind}</dt>
            <dd>{line.amount.toFixed(2)} {ride.fare.currency}</dd>
          </div>
        ))}
        <div className="fare-line fare-vat">
          <dt>VAT (incl.)</dt>
          <dd>{vatOf(ride).toFixed(2)} {ride.fare.currency}</dd>
        </div>
        <div className="fare-total">
          <dt>Total</dt>
          <dd>{ride.fare.total.toFixed(2)} {ride.fare.currency}</dd>
        </div>
      </dl>
    </section>
  );
}

function vatOf(ride: Ride): number {
  return ride.fare.breakdown
    .filter((line) => line.kind === "vat")
    .reduce((sum, line) => sum + line.amount, 0);
}
"""

RIDE_CACHE = """import type { Ride } from "../api/types";

const KEY = "revika.ride-cache.v1";

// Spike: keep the last rides in localStorage so the trip list renders offline.
export function loadCache(limit = 20): Ride[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Ride[]).slice(0, limit) : [];
  } catch {
    return [];
  }
}

export function saveCache(rides: Ride[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(rides.slice(0, 50)));
  } catch {
    // quota exceeded — cache is best effort
  }
}
"""

MAP_PAGE = """import { useEffect, useRef } from "react";

// WIP: new map shell for the redesign exploration.
export function MapPage() {
  const canvasRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // TODO: replace with the vector tile renderer once the spike lands.
    return undefined;
  }, []);

  return (
    <div className="map-page">
      <div ref={canvasRef} className="map-canvas" />
      <aside className="map-legend">Draft — do not ship</aside>
    </div>
  );
}
"""

PACKAGE_V1 = {"name": "revika-web", "version": "1.0.0", "private": True,
              "scripts": {"dev": "vite", "build": "tsc -b && vite build", "test": "vitest"}}
PACKAGE_V2 = {**PACKAGE_V1, "version": "1.0.1"}

GO_RIDES = """package httpapi

import (
	"net/http"
)

// handleListRides returns the caller's rides, newest first.
func (s *Server) handleListRides(w http.ResponseWriter, r *http.Request) {
	limit := parseLimit(r, 50)
	rides, err := s.store.RidesByUser(r.Context(), userID(r), limit)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "lookup failed")
		return
	}
	writeJSON(w, rides)
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(v)
}
"""

GO_MOD = """module github.com/revikalabs/api

go 1.23
"""

KOTLIN_VM = """package labs.revika.mobile

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

data class RideHistoryUiState(
    val loading: Boolean = true,
    val rides: List<Ride> = emptyList(),
    val error: String? = null,
)

class RideHistoryViewModel(private val repo: RideRepository) : ViewModel() {

    private val _state = MutableStateFlow(RideHistoryUiState())
    val state: StateFlow<RideHistoryUiState> = _state

    fun load() {
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true)
            runCatching { repo.history(limit = 100) }
                .onSuccess { _state.value = RideHistoryUiState(loading = false, rides = it) }
                .onFailure { _state.value = RideHistoryUiState(loading = false, error = it.message) }
        }
    }
}
"""

GRADLE_CONFIG = """plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "labs.revika.mobile"
    compileSdk = 35
    defaultConfig {
        minSdk = 26
        targetSdk = 35
    }
}
"""

TELEMETRY_INGEST = """package telemetry

import "time"

// Sample is one telemetry frame reported by a vehicle.
type Sample struct {
	VehicleID  string    `json:"vehicle_id"`
	TS         time.Time `json:"ts"`
	SpeedKmh   float64   `json:"speed_kmh"`
	OdometerKm float64   `json:"odometer_km"`
	BatteryPct float64   `json:"battery_pct"`
}

// Ingest validates and buffers frames before they are flushed to storage.
type Ingest struct {
	buf []Sample
}

func (ing *Ingest) Add(s Sample) error {
	if s.VehicleID == "" {
		return ErrMissingVehicle
	}
	ing.buf = append(ing.buf, s)
	return nil
}

func (ing *Ingest) Flush() []Sample {
	out := ing.buf
	ing.buf = nil
	return out
}
"""

TELEMETRY_TEST = """package telemetry

import (
	"testing"
	"time"
)

func TestIngestFlush(t *testing.T) {
	ing := &Ingest{}
	if err := ing.Add(Sample{VehicleID: "v-1", TS: time.Now(), SpeedKmh: 42}); err != nil {
		t.Fatalf("add: %v", err)
	}
	if got := len(ing.Flush()); got != 1 {
		t.Fatalf("flushed %d samples, want 1", got)
	}
	if got := len(ing.Flush()); got != 0 {
		t.Fatalf("second flush returned %d, want 0", got)
	}
}
"""

TOKENS_COLORS = """{
  "color": {
    "brand": { "50": "#eef4ff", "500": "#3b6ef6", "600": "#2f5be0", "700": "#2549b8" },
    "surface": { "base": "#ffffff", "raised": "#f7f8fa", "sunken": "#eef0f3" },
    "text": { "primary": "#1c1e21", "muted": "#65676b", "inverse": "#ffffff" },
    "state": { "success": "#1f9d63", "warning": "#f2b230", "danger": "#d9483b" }
  }
}
"""

TOKENS_SPACING = """{
  "space": { "xs": "4px", "sm": "8px", "md": "16px", "lg": "24px", "xl": "40px" },
  "radius": { "sm": "6px", "md": "12px", "pill": "999px" }
}
"""

RELEASE_V090 = """## Features

- Skeleton loaders on the trip list
- Saved places onboarding carousel

## Fixes

- Ride receipt VAT line rendering
- Map viewport resets on device rotation
"""

RELEASE_V100 = """## Features

- Payment methods sheet with saved cards and invoicing
- Streaming fare estimates

## Fixes

- Session refresh during long trips
- Offline queue no longer replays duplicate tip adjustments
"""

WIKI_HOME = """# Revika Web

Customer-facing web client for Revika. React 19, TypeScript, Vite.

## Quick links

| Page | What it covers |
| --- | --- |
| Architecture | How the app is layered |
| Release process | How a release ships |

> Run `pnpm test` before opening a pull request.
"""

WIKI_ARCHITECTURE = """# Architecture

Revika Web is a single-page client talking to the platform API.

## Layers

| Layer | Location | Talks to |
| --- | --- | --- |
| Views | `src/views` | Hooks |
| Hooks | `src/hooks` | API client |
| API client | `src/api` | Platform REST |
| UI primitives | `src/ui` | Nothing (pure) |

## Data flow

```ts
View → useRideHistory() → api("/rides") → platform
```

> Never call `fetch` directly from a view — go through the client in `src/api/client.ts` so auth
> and retries stay in one place.
"""

WIKI_RELEASE = """# Release process

1. Make sure `main` is green: lint, unit tests and the E2E suite.
2. Bump `version` in `package.json` and update the changelog.
3. Open a `chore/release` pull request and get one approval.
4. After merge, tag `vX.Y.Z` on `main` — CI builds and attaches artifacts.
5. Publish the release notes and announce them in `#revika-web`.
"""

MARKER_TITLE = "Seed marker: enrich v1"


def seed_web():
    api("POST", f"/orgs/{ORG}/repos", {"name": REPO, "description": "Customer-facing web client",
                                       "default_branch": "main", "auto_init": True, "readme": "Default"})
    put_file("README.md", README, "docs: describe project layout")
    put_file("package.json", json.dumps(PACKAGE_V1, indent=2) + "\n", "chore: add package.json", author="lena")
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


def enrich_orgs():
    for name, spec in ENRICH_ORGS.items():
        api("POST", "/orgs", {"username": name, "full_name": spec["full_name"], "visibility": "public"}, ok404=True)
        api("PATCH", f"/orgs/{name}", {"full_name": spec["full_name"], "description": spec["description"],
                                       "visibility": "public"}, ok404=True)
        team = api("GET", f"/orgs/{name}/teams")[0]
        for login in spec["owners"]:
            api("PUT", f"/teams/{team['id']}/members/{login}", ok404=True)
        for repo, description in spec["repos"].items():
            api("POST", f"/orgs/{name}/repos", {"name": repo, "description": description,
                                                "auto_init": True, "readme": "Default"}, ok404=True)


def enrich_repo_files():
    put_file("internal/httpapi/rides.go", GO_RIDES, "feat: rides handler", author="andreas", repo="api")
    put_file("go.mod", GO_MOD, "chore: module scaffold", author="karri", repo="api")
    put_file("app/src/main/java/labs/revika/mobile/RideHistoryViewModel.kt", KOTLIN_VM,
             "feat: ride history view model", author="nan", repo="mobile")
    put_file("app/build.gradle.kts", GRADLE_CONFIG, "chore: android build config", author="lena", repo="mobile")
    put_file("pkg/ingest.go", TELEMETRY_INGEST, "feat: telemetry frame buffer",
             author="andreas", org="openfleet", repo="telemetry")
    put_file("pkg/ingest_test.go", TELEMETRY_TEST, "test: ingest buffer flush",
             author="nan", org="openfleet", repo="telemetry")
    put_file("tokens/colors.json", TOKENS_COLORS, "feat: color tokens",
             author="lena", org="northwind", repo="design-tokens")
    put_file("tokens/spacing.json", TOKENS_SPACING, "feat: spacing and radius tokens",
             author="karri", org="northwind", repo="design-tokens")


def enrich_issues():
    label_ids = {l["name"]: l["id"] for l in api("GET", f"/repos/{ORG}/{REPO}/labels")}
    milestones = {m["title"]: m["id"] for m in api("GET", f"/repos/{ORG}/{REPO}/milestones?state=all")}
    if "Cycle 145" not in milestones:
        api("POST", f"/repos/{ORG}/{REPO}/milestones",
            {"title": "Cycle 145", "description": "Receipts and loading states", "due_on": "2026-12-15T00:00:00Z"},
            ok404=True)
        milestones = {m["title"]: m["id"] for m in api("GET", f"/repos/{ORG}/{REPO}/milestones?state=all")}
    # Title-keyed numbers make a re-run after a crash idempotent instead of duplicating issues.
    numbers = {i["title"]: i["number"]
               for i in api("GET", f"/repos/{ORG}/{REPO}/issues?state=all&type=issues&limit=50")}
    for i, (title, body, labels, author, closed, cycle) in enumerate(ENRICH_ISSUES):
        if title in numbers:
            # An issue created right before a crash may still be open — close it on re-run.
            if closed:
                api("PATCH", f"/repos/{ORG}/{REPO}/issues/{numbers[title]}", {"state": "closed"}, ok404=True)
            continue
        issue = api("POST", f"/repos/{ORG}/{REPO}/issues", {
            "title": title, "body": body, "labels": [label_ids[l] for l in labels],
            "assignees": [USERS[i % len(USERS)][0]], "milestone": milestones.get(f"Cycle {cycle}")}, user=author)
        numbers[title] = issue["number"]
        if closed:
            api("PATCH", f"/repos/{ORG}/{REPO}/issues/{issue['number']}", {"state": "closed"})
    for index, comments in ENRICH_COMMENTS:
        number = numbers[ENRICH_ISSUES[index][0]]
        existing = {c["body"] for c in api("GET", f"/repos/{ORG}/{REPO}/issues/{number}/comments", ok404=True) or []}
        for author, text in comments:
            if text in existing:
                continue
            api("POST", f"/repos/{ORG}/{REPO}/issues/{number}/comments", {"body": text}, user=author)
    return numbers


def find_pull(head):
    for pr in api("GET", f"/repos/{ORG}/{REPO}/pulls?state=all"):
        if pr["head"]["ref"] == head:
            return pr
    return None


def ensure_pull(title, head, body, user):
    # Lookup first: Gitea only refuses a second PR for an *open* head, so POST-first would
    # duplicate a pull whose previous run got closed or merged.
    pr = find_pull(head)
    if pr:
        return pr
    pr = api("POST", f"/repos/{ORG}/{REPO}/pulls",
             {"title": title, "head": head, "base": "main", "body": body}, user=user, ok404=True)
    if not pr:
        sys.exit(f"pull request for branch {head} was neither created nor found")
    return pr


def ensure_review(number, event, body, user, comments=None):
    reviews = api("GET", f"/repos/{ORG}/{REPO}/pulls/{number}/reviews")
    if any(r["state"] == event and r["user"]["login"] == user for r in reviews):
        return
    payload = {"event": event, "body": body}
    if comments:
        payload["comments"] = comments
    api("POST", f"/repos/{ORG}/{REPO}/pulls/{number}/reviews", payload, user=user)


def enrich_pulls(numbers):
    # Commits on main first, so branches are cut from a history that already has depth.
    for path, content, message, author in MAIN_COMMITS:
        put_file(path, content, message, author=author)

    api("POST", f"/repos/{ORG}/{REPO}/branches",
        {"new_branch_name": "feat/trip-skeleton", "old_branch_name": "main"}, ok404=True)
    put_file("src/ui/Skeleton.tsx", SKELETON, "feat: skeleton loading rows", branch="feat/trip-skeleton", author="lena")
    put_file("src/views/RideHistoryPage.tsx", PAGE_V3, "feat: render skeleton rows while trips load",
             branch="feat/trip-skeleton", author="lena")
    put_file("README.md", README_BRANCH, "docs: document loading states", branch="feat/trip-skeleton", author="lena")
    skeleton = ensure_pull("Add skeleton loaders to trip list", "feat/trip-skeleton",
                           f"Adds `SkeletonRows` and swaps the trip list spinner for skeleton rows.\n\n"
                           f"Fixes #{numbers['Add skeleton loaders to trip list']}", "lena")
    ensure_review(skeleton["number"], "APPROVED",
                  "LGTM — row height matches RideRow, so nothing jumps on load.", "didier")

    api("POST", f"/repos/{ORG}/{REPO}/branches",
        {"new_branch_name": "fix/receipt-vat", "old_branch_name": "main"}, ok404=True)
    put_file("src/views/ReceiptView.tsx", RECEIPT_V2, "fix: render the VAT line on receipts",
             branch="fix/receipt-vat", author="andreas")
    receipt = ensure_pull("Fix VAT line on ride receipts", "fix/receipt-vat",
                          "The receipt renderer dropped the VAT line when it followed a surge line.\n\n"
                          f"Fixes #{numbers['Ride receipt PDF misses VAT line']}", "andreas")
    ensure_review(receipt["number"], "REQUEST_CHANGES",
                  "VAT should stay inside the breakdown loop instead of a separate row.", "nan",
                  comments=[{"path": "src/views/ReceiptView.tsx", "new_position": 15,
                             "body": "Render the VAT row only when the ride actually has a vat line."}])

    api("POST", f"/repos/{ORG}/{REPO}/branches",
        {"new_branch_name": "chore/deps", "old_branch_name": "main"}, ok404=True)
    put_file("package.json", json.dumps(PACKAGE_V2, indent=2) + "\n", "chore: bump version to 1.0.1",
             branch="chore/deps", author="karri")
    deps = ensure_pull("chore: bump version to 1.0.1", "chore/deps",
                       "Version bump ahead of the next release.", "karri")
    if not deps["merged"]:
        api("POST", f"/repos/{ORG}/{REPO}/pulls/{deps['number']}/merge", {"Do": "merge"}, ok404=True)

    api("POST", f"/repos/{ORG}/{REPO}/branches",
        {"new_branch_name": "spike/offline-cache", "old_branch_name": "main"}, ok404=True)
    put_file("src/offline/rideCache.ts", RIDE_CACHE, "spike: localStorage ride cache",
             branch="spike/offline-cache", author="didier")
    spike = ensure_pull("Spike: offline ride cache", "spike/offline-cache",
                        "Exploration only — cache shape and eviction strategy.", "didier")
    if spike["state"] == "open":
        api("PATCH", f"/repos/{ORG}/{REPO}/pulls/{spike['number']}", {"state": "closed"}, ok404=True)

    api("POST", f"/repos/{ORG}/{REPO}/branches",
        {"new_branch_name": "wip/map-redesign", "old_branch_name": "main"}, ok404=True)
    put_file("src/views/MapPage.tsx", MAP_PAGE, "wip: new map shell", branch="wip/map-redesign", author="nan")
    ensure_pull("WIP: map redesign", "wip/map-redesign",
                "Early exploration of the new map shell. Not ready for review.", "nan")


def enrich_releases():
    api("POST", f"/repos/{ORG}/{REPO}/releases", {
        "tag_name": "v0.9.0", "target_commitish": "main", "name": "v0.9.0", "prerelease": True,
        "body": RELEASE_V090}, ok404=True)
    api("POST", f"/repos/{ORG}/{REPO}/releases", {
        "tag_name": "v1.0.0", "target_commitish": "main", "name": "v1.0.0", "body": RELEASE_V100}, ok404=True)


def enrich_wiki():
    pages = [("Home", WIKI_HOME, "docs: wiki home"),
             ("Architecture", WIKI_ARCHITECTURE, "docs: architecture overview"),
             ("Release process", WIKI_RELEASE, "docs: release process")]
    for title, content, message in pages:
        api("POST", f"/repos/{ORG}/{REPO}/wiki/new",
            {"title": title, "content_base64": base64.b64encode(content.encode()).decode(), "message": message},
            ok404=True, ok400=True)


def enrich_social():
    for login, _ in USERS:
        api("PUT", f"/user/starred/{ORG}/{REPO}", user=login, ok404=True)
        for repo in STARS[login]:
            api("PUT", f"/user/starred/{ORG}/{repo}", user=login, ok404=True)
        for target in FOLLOWS[login]:
            api("PUT", f"/user/following/{target}", user=login, ok404=True)
        api("PUT", f"/repos/{ORG}/{REPO}/subscription", user=login, ok404=True)
    for owner, repo in [(ORG, REPO), (ORG, "api"), ("openfleet", "telemetry")]:
        api("PUT", f"/user/starred/{owner}/{repo}", ok404=True)
    for login in ["lena", "karri"]:
        api("PUT", f"/user/following/{login}", ok404=True)


def enrich_done():
    issues = api("GET", f"/repos/{ORG}/{REPO}/issues?state=all&type=issues&q=Seed%20marker&limit=50", ok404=True)
    if issues and any(i["title"] == MARKER_TITLE for i in issues):
        return True
    # The q= search is index-backed and can lag right after a fresh seed; fall back to the plain list
    # so a spurious re-run never creates a second marker.
    issues = api("GET", f"/repos/{ORG}/{REPO}/issues?state=all&type=issues&limit=50", ok404=True)
    return any(i["title"] == MARKER_TITLE for i in issues or [])


def enrich():
    enrich_orgs()
    enrich_social()
    if enrich_done():
        print("enrich v1 already applied; refreshed orgs, stars and follows")
        return
    numbers = enrich_issues()
    enrich_repo_files()
    enrich_pulls(numbers)
    enrich_releases()
    enrich_wiki()
    marker = api("POST", f"/repos/{ORG}/{REPO}/issues",
                 {"title": MARKER_TITLE,
                  "body": "Idempotency marker written last by dev/seed.py enrich(). Do not edit or reopen."})
    api("PATCH", f"/repos/{ORG}/{REPO}/issues/{marker['number']}", {"state": "closed"})
    print("enrich v1 applied")


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
    # Keep the org public on every run, otherwise explore/organizations comes up empty.
    api("PATCH", f"/orgs/{ORG}", {"visibility": "public"})

    if not api("GET", f"/repos/{ORG}/{REPO}", ok404=True):
        seed_web()
    else:
        print("revikalabs/web exists, content not reseeded; reset with: docker compose -f dev/docker-compose.yml down -v")
    enrich()
    print(f"seeded: http://localhost:3300/{ORG}/{REPO}  login {ADMIN} / {PASSWORD}")


if __name__ == "__main__":
    main()
