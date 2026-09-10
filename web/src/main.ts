/**
 * kessler, the interface.
 *
 * The globe is the page. It is not a panel inside a layout, it fills the viewport and
 * everything else floats over it the way marginalia sit on a chart: identity and
 * search in one corner, provenance and legend in another, the clock along the bottom
 * edge. There is no permanent column. An object's record exists only once you have
 * clicked something, and it can be dismissed.
 *
 * That composition is deliberate and it is a correction. The first version put a
 * fixed record column on the left and the visual on the right under a two row header,
 * which is the same skeleton as the previous project in this portfolio. Two repos
 * that differ only in content and typeface read as one template with the serial
 * numbers filed off, which is exactly the signature this portfolio exists not to
 * have. See the second correction in docs/design.md.
 *
 * One clock still owns the page. The spine holds it, the globe reads it, the curve
 * reads it, and a burn moves it. Nothing here computes a miss distance: every number
 * in the readout comes from the service, which propagates at full precision. The
 * browser propagates only what it needs to draw the globe, and that costs up to 83 m
 * of position over the day, which is invisible at this scale and stated anyway.
 */

import "./style.css";

import { api, type ObjectDetail, type Passage, type Provenance } from "./api";
import { createGlobe, type GlobeHandle } from "./globe";
import { clock, isoDay, km, probability, speed } from "./format";
import { setGroundMode, type Ground } from "./palette";
import {
  curveColours,
  curveOffsetAt,
  drawCurve,
  drawSpine,
  spineOffsetAt,
  type SpineMark,
} from "./spine";

const WINDOW_S = 86400;
const PROPAGATE_INTERVAL_MS = 220;
const GROUND_KEY = "kessler.ground";

interface State {
  provenance: Provenance | null;
  norads: number[];
  names: string[];
  types: string[];
  indexByNorad: Map<number, number>;
  windowStart: Date;
  playheadS: number;
  playing: boolean;
  rate: number;
  selected: ObjectDetail | null;
  selectedIndex: number | null;
  passage: Passage | null;
  partnerIndex: number | null;
  curveBefore: { offsetsS: number[]; separationKm: (number | null)[] } | null;
  curveAfter: { offsetsS: number[]; separationKm: (number | null)[] } | null;
  burnMs: number;
  leadHours: number;
  sigmaKm: number | null;
  manoeuvreNote: string | null;
  manoeuvreDelta: number | null;
  inversionResidualM: number | null;
  probabilityBefore: number | null;
  probabilityAfter: number | null;
  busy: boolean;
}

const state: State = {
  provenance: null,
  norads: [],
  names: [],
  types: [],
  indexByNorad: new Map(),
  windowStart: new Date(),
  playheadS: 0,
  playing: false,
  rate: 60,
  selected: null,
  selectedIndex: null,
  passage: null,
  partnerIndex: null,
  curveBefore: null,
  curveAfter: null,
  burnMs: 0,
  leadHours: 3,
  sigmaKm: null,
  manoeuvreNote: null,
  manoeuvreDelta: null,
  inversionResidualM: null,
  probabilityBefore: null,
  probabilityAfter: null,
  busy: false,
};

const app = document.querySelector<HTMLDivElement>("#app")!;
app.innerHTML = `
  <div class="stage">
    <div class="globe" id="globe"></div>

    <div class="mark">
      <h1>kessler</h1>
      <p>close approaches in a dated snapshot of the public satellite catalogue</p>
      <div class="finder">
        <input id="search" class="finder-input" placeholder="find by name or NORAD id"
               autocomplete="off" spellcheck="false" aria-label="find a satellite" />
        <ul class="finder-results" id="results" role="listbox"></ul>
      </div>
    </div>

    <button class="ground-toggle" id="ground-toggle" type="button"
            aria-label="switch background"></button>

    <aside class="card" id="card" hidden aria-live="polite"></aside>

    <div class="marginalia" id="marginalia"></div>

    <section class="approach" id="approach" hidden>
      <header class="approach-head" id="approach-head"></header>
      <canvas id="curve"></canvas>
    </section>

    <div class="clock">
      <canvas id="spine"></canvas>
    </div>
  </div>
`;

const globeEl = document.querySelector<HTMLElement>("#globe")!;
const cardEl = document.querySelector<HTMLElement>("#card")!;
const marginaliaEl = document.querySelector<HTMLElement>("#marginalia")!;
const approachEl = document.querySelector<HTMLElement>("#approach")!;
const approachHeadEl = document.querySelector<HTMLElement>("#approach-head")!;
const spineCanvas = document.querySelector<HTMLCanvasElement>("#spine")!;
const curveCanvas = document.querySelector<HTMLCanvasElement>("#curve")!;
const searchInput = document.querySelector<HTMLInputElement>("#search")!;
const resultsEl = document.querySelector<HTMLUListElement>("#results")!;
const toggleEl = document.querySelector<HTMLButtonElement>("#ground-toggle")!;

let globe: GlobeHandle | null = null;
let worker: Worker | null = null;
let lastFrame = performance.now();
let lastPropagate = 0;

function escapeHtml(value: string): string {
  return value.replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!,
  );
}

function row(key: string, value: string): string {
  return `<div class="kv"><span class="k">${key}</span><span class="v">${escapeHtml(value)}</span></div>`;
}

function passageOffsetS(passage: Passage): number {
  return (new Date(passage.tca_utc).getTime() - state.windowStart.getTime()) / 1000;
}

/**
 * The corner block: what this is looking at, how much of the sky it covers, and what
 * it is not. A chart puts its source note and its legend in the margin, not in a
 * banner across the top, and the disclosure is a source note.
 */
function renderMarginalia(): void {
  const p = state.provenance;
  if (!p) {
    marginaliaEl.innerHTML = `<p class="loading">loading catalogue</p>`;
    return;
  }
  const c = p.coverage;
  marginaliaEl.innerHTML = `
    <dl class="facts">
      <div><dt>snapshot</dt><dd>${p.snapshot_date}</dd></div>
      <div><dt>screened</dt><dd>${p.objects.toLocaleString()} objects</dd></div>
      <div><dt>coverage</dt><dd>${c.screened.toLocaleString()} of ${c.on_orbit_catalogued.toLocaleString()} on orbit, ${c.screened_percent}%</dd></div>
      <div><dt>debris</dt><dd>${c.debris_screened.toLocaleString()} of ${c.debris_on_orbit.toLocaleString()}, ${c.debris_percent}%</dd></div>
      <div><dt>propagator</dt><dd>SGP4, no model trained</dd></div>
    </dl>
    <ul class="key">
      <li><i class="dot pay"></i>payload</li>
      <li><i class="dot deb"></i>debris</li>
      <li><i class="ring sel"></i>selected</li>
      <li><i class="ring par"></i>encounter partner</li>
    </ul>
    <p class="disclosure">
      Model output from one dated snapshot. Not live, and not a conjunction warning
      service. Element sets carry <b>no covariance</b>, so no collision probability is
      shown unless you supply the uncertainty yourself.
    </p>`;
}

const SIGMA_STEPS: (number | null)[] = [null, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5];

function sigmaToSlider(value: number | null): number {
  const index = SIGMA_STEPS.indexOf(value);
  return index < 0 ? 0 : index;
}

/**
 * The record for whatever is selected. Not a permanent drawer: it does not exist
 * until you click a point or pick a search result, and it closes.
 */
function renderCard(): void {
  const s = state.selected;
  if (!s) {
    cardEl.hidden = true;
    cardEl.innerHTML = "";
    return;
  }
  cardEl.hidden = false;

  const parts: string[] = [];
  parts.push(`
    <header class="card-head">
      <div>
        <h2>${escapeHtml(s.name)}</h2>
        <p class="sub">${s.object_type} &middot; ${escapeHtml(s.owner || "owner not listed")} &middot; ${s.object_id}</p>
      </div>
      <button class="close" id="card-close" type="button" aria-label="close record">&times;</button>
    </header>
    <div class="record">
      ${row("NORAD_CAT_ID", String(s.norad))}
      ${row("RCS_M2", s.rcs_m2 === null ? "not published" : s.rcs_m2.toFixed(4))}
      ${row("ELEMENT_EPOCH", s.epoch.replace("T", " ").slice(0, 19))}
      ${row("SOURCE_GROUP", s.group)}
    </div>`);

  const artefacts = s.artefacts.length;
  parts.push(`
    <h3>Passages within 5 km <span class="count">${s.passages_total}</span></h3>
    ${
      s.passages.length === 0
        ? `<p class="none">No passage under 5 km in the 24 hours screened, against any of the
           ${state.norads.length.toLocaleString()} objects here.</p>`
        : `<ol class="passages" id="passages">${s.passages
            .map((passage, i) => {
              const other = passage.norad_a === s.norad ? passage.name_b : passage.name_a;
              const kind = passage.norad_a === s.norad ? passage.type_b : passage.type_a;
              return `<li data-i="${i}" ${state.passage === passage ? 'aria-current="true"' : ""}>
                <span class="who">${escapeHtml(other)}${kind === "DEB" ? '<i class="chip">DEB</i>' : ""}</span>
                <span class="miss">${km(passage.miss_km)}</span>
                <span class="when">${clock(new Date(passage.tca_utc))}Z &middot; ${speed(passage.rel_speed_kms)}</span>
              </li>`;
            })
            .join("")}</ol>`
    }
    ${
      artefacts > 0
        ? `<p class="filtered">${artefacts} further pair${artefacts === 1 ? "" : "s"} filtered as
           artefacts rather than passages: same published element set, or flying in formation.</p>`
        : ""
    }`);

  if (state.passage) {
    const p = state.passage;
    const offset = passageOffsetS(p);
    const maxLead = Math.max(0.25, offset / 3600 - 0.1);
    parts.push(`
      <h3>Burn</h3>
      <div class="control">
        <label for="burn"><span>in-track</span><b>${state.burnMs.toFixed(1)} mm/s</b></label>
        <input type="range" id="burn" min="-200" max="200" step="1"
               value="${Math.round(state.burnMs * 10)}" />
        <label for="lead"><span>lead time</span><b>${state.leadHours.toFixed(2)} h before TCA</b></label>
        <input type="range" id="lead" min="0.25" max="${maxLead.toFixed(2)}" step="0.25"
               value="${Math.min(state.leadHours, maxLead)}" />
      </div>
      <div class="outcome" id="outcome">
        ${
          state.manoeuvreNote
            ? `<p class="warn">${escapeHtml(state.manoeuvreNote)}</p>`
            : state.manoeuvreDelta === null
              ? `<p class="hint">In-track is the component that does the work. It changes the
                 period, so the along-track offset grows with every revolution before the
                 encounter.</p>`
              : Math.abs(state.manoeuvreDelta) < 0.0005
                ? `<p class="delta small">no measurable change</p>
                   <p class="hint">this burn is too small, or too late, to move the encounter by
                   even half a metre. Rounding it to &minus;0 m would be worse than saying so.</p>`
                : `<p class="delta">${state.manoeuvreDelta >= 0 ? "+" : "&minus;"}${km(Math.abs(state.manoeuvreDelta))}</p>
                   <p class="hint">new miss ${km(p.miss_km + state.manoeuvreDelta)}, SGP4 refitted to
                   the post-burn state with ${state.inversionResidualM?.toFixed(4) ?? "-"} m residual</p>`
        }
      </div>

      <h3>Collision probability</h3>
      <div class="control">
        <label for="sigma"><span>assumed 1&sigma;</span><b>${state.sigmaKm === null ? "not assumed" : `${state.sigmaKm} km`}</b></label>
        <input type="range" id="sigma" min="0" max="7" step="1" value="${sigmaToSlider(state.sigmaKm)}" />
      </div>
      ${
        state.sigmaKm === null
          ? `<p class="hint">Element sets publish no covariance. Leave this alone and no
             probability is reported, which is the honest default.</p>`
          : `<div class="record">
               ${row("PC_BEFORE", probability(state.probabilityBefore))}
               ${row("PC_AFTER", state.probabilityAfter === null ? "-" : probability(state.probabilityAfter))}
             </div>
             <p class="hint">Conditional on a ${state.sigmaKm} km spherical position uncertainty
             combined over both objects. Nobody published that number. You chose it.</p>`
      }`);
  }

  cardEl.innerHTML = parts.join("");
  wireCard();
}

function renderApproachHead(): void {
  const p = state.passage;
  if (!p || !state.selected) return;
  const other = p.norad_a === state.selected.norad ? p.name_b : p.name_a;
  approachHeadEl.innerHTML = `
    <span class="pair">${escapeHtml(state.selected.name)} <b>&#8596;</b> ${escapeHtml(other)}</span>
    <span class="stat">${km(p.miss_km)} at ${speed(p.rel_speed_kms)}</span>
    <span class="stat">${isoDay(new Date(p.tca_utc))} ${clock(new Date(p.tca_utc))}Z</span>`;
}

function wireCard(): void {
  document.querySelector("#card-close")?.addEventListener("click", () => clearSelection());

  document.querySelector("#passages")?.addEventListener("click", (event) => {
    const item = (event.target as HTMLElement).closest("li[data-i]");
    if (!item || !state.selected) return;
    void selectPassage(state.selected.passages[Number(item.getAttribute("data-i"))]);
  });

  const burn = document.querySelector<HTMLInputElement>("#burn");
  burn?.addEventListener("input", () => {
    state.burnMs = Number(burn.value) / 10;
    const label = burn.previousElementSibling?.querySelector("b");
    if (label) label.textContent = `${state.burnMs.toFixed(1)} mm/s`;
  });
  burn?.addEventListener("change", () => void runManoeuvre());

  const lead = document.querySelector<HTMLInputElement>("#lead");
  lead?.addEventListener("input", () => {
    state.leadHours = Number(lead.value);
    const label = lead.previousElementSibling?.querySelector("b");
    if (label) label.textContent = `${state.leadHours.toFixed(2)} h before TCA`;
  });
  lead?.addEventListener("change", () => void runManoeuvre());

  const sigma = document.querySelector<HTMLInputElement>("#sigma");
  sigma?.addEventListener("change", () => {
    state.sigmaKm = SIGMA_STEPS[Number(sigma.value)];
    void runManoeuvre();
  });
}

function renderResults(query: string): void {
  const trimmed = query.trim().toLowerCase();
  if (trimmed.length < 2) {
    resultsEl.innerHTML = "";
    resultsEl.classList.remove("open");
    return;
  }
  const hits: string[] = [];
  for (let i = 0; i < state.names.length && hits.length < 40; i += 1) {
    if (
      state.names[i].toLowerCase().includes(trimmed) ||
      String(state.norads[i]).startsWith(trimmed)
    ) {
      hits.push(
        `<li role="option" data-norad="${state.norads[i]}">
           <span>${escapeHtml(state.names[i])}</span><span class="id">${state.norads[i]}</span>
         </li>`,
      );
    }
  }
  resultsEl.innerHTML = hits.length
    ? hits.join("")
    : `<li class="nothing">nothing in the snapshot matches that</li>`;
  resultsEl.classList.add("open");
}

function clearSelection(): void {
  state.selected = null;
  state.selectedIndex = null;
  state.passage = null;
  state.partnerIndex = null;
  state.curveBefore = null;
  state.curveAfter = null;
  state.manoeuvreDelta = null;
  state.manoeuvreNote = null;
  state.burnMs = 0;
  globe?.setHighlight(null, null);
  approachEl.hidden = true;
  renderCard();
  redrawSpine();
  redrawCurve();
}

async function selectObject(norad: number): Promise<void> {
  try {
    const detail = await api.object(norad);
    state.selected = detail;
    state.selectedIndex = state.indexByNorad.get(norad) ?? null;
    state.passage = null;
    state.partnerIndex = null;
    state.curveBefore = null;
    state.curveAfter = null;
    state.manoeuvreDelta = null;
    state.manoeuvreNote = null;
    state.burnMs = 0;
    approachEl.hidden = true;
    globe?.setHighlight(state.selectedIndex, null);
    renderCard();
    redrawSpine();
    redrawCurve();
    if (detail.passages.length > 0) await selectPassage(detail.passages[0]);
  } catch (error) {
    console.error("kessler: could not load object", norad, error);
  }
}

async function selectPassage(passage: Passage): Promise<void> {
  if (!state.selected) return;
  state.passage = passage;
  const otherNorad = passage.norad_a === state.selected.norad ? passage.norad_b : passage.norad_a;
  state.partnerIndex = state.indexByNorad.get(otherNorad) ?? null;
  globe?.setHighlight(state.selectedIndex, state.partnerIndex);

  const offset = passageOffsetS(passage);
  state.playheadS = offset;
  state.manoeuvreDelta = null;
  state.manoeuvreNote = null;
  state.curveAfter = null;
  state.burnMs = 0;
  state.leadHours = Math.min(3, Math.max(0.25, offset / 3600 - 0.25));

  try {
    const curve = await api.encounter(passage.norad_a, passage.norad_b, offset, 600);
    state.curveBefore = { offsetsS: curve.offsets_s, separationKm: curve.separation_km };
  } catch (error) {
    console.error("kessler: could not load the encounter curve", error);
  }
  approachEl.hidden = false;
  renderCard();
  renderApproachHead();
  redrawSpine();
  redrawCurve();
  if (state.sigmaKm !== null) void runManoeuvre();
}

async function runManoeuvre(): Promise<void> {
  if (!state.selected || !state.passage || state.busy) return;
  const passage = state.passage;
  const tcaOffset = passageOffsetS(passage);
  const burnOffset = tcaOffset - state.leadHours * 3600;
  if (burnOffset < 0) {
    state.manoeuvreNote = "that lead time puts the burn before the window starts";
    renderCard();
    return;
  }
  state.busy = true;
  try {
    const result = await api.manoeuvre({
      norad: state.selected.norad,
      partner_norad:
        passage.norad_a === state.selected.norad ? passage.norad_b : passage.norad_a,
      tca_offset_s: tcaOffset,
      burn_offset_s: burnOffset,
      in_track_ms: state.burnMs / 1000,
      position_sigma_km: state.sigmaKm,
    });
    state.curveBefore = {
      offsetsS: result.before.offsets_s,
      separationKm: result.before.separation_km,
    };
    state.curveAfter =
      state.burnMs === 0
        ? null
        : { offsetsS: result.after.offsets_s, separationKm: result.after.separation_km };
    state.manoeuvreDelta = state.burnMs === 0 ? null : result.change_km;
    state.inversionResidualM = result.inversion.residual_m;
    state.manoeuvreNote = null;
    state.probabilityBefore = result.probability?.before.probability ?? null;
    state.probabilityAfter = result.probability?.after.probability ?? null;
  } catch (error) {
    state.manoeuvreNote = error instanceof Error ? error.message : String(error);
    state.curveAfter = null;
    state.manoeuvreDelta = null;
  } finally {
    state.busy = false;
  }
  renderCard();
  redrawCurve();
}

function redrawSpine(): void {
  const marks: SpineMark[] = (state.selected?.passages ?? []).map((passage) => ({
    offsetS: passageOffsetS(passage),
    missKm: passage.miss_km,
    partner: passage.name_b,
  }));
  drawSpine(spineCanvas, {
    playheadS: state.playheadS,
    marks,
    selectedOffsetS: state.passage ? passageOffsetS(state.passage) : null,
    startDate: state.windowStart,
    hasSelection: state.selected !== null,
  });
}

function redrawCurve(): void {
  const series = [];
  if (state.curveBefore) {
    series.push({
      offsetsS: state.curveBefore.offsetsS,
      separationKm: state.curveBefore.separationKm,
      colour: curveColours().before,
      label: state.curveAfter ? "no burn" : "separation",
    });
  }
  if (state.curveAfter) {
    series.push({
      offsetsS: state.curveAfter.offsetsS,
      separationKm: state.curveAfter.separationKm,
      colour: curveColours().after,
      label: `after ${state.burnMs.toFixed(1)} mm/s`,
      dashed: true,
    });
  }
  drawCurve(curveCanvas, { series, playheadS: state.playheadS });
}

function applyGround(mode: Ground): void {
  setGroundMode(mode);
  document.documentElement.dataset.ground = mode;
  toggleEl.textContent = mode === "dark" ? "pale ground" : "dark ground";
  toggleEl.title =
    mode === "dark"
      ? "switch to the pale ground, which is the version the legibility test passed"
      : "switch back to the dark ground";
  globe?.refreshTheme();
  redrawSpine();
  redrawCurve();
}

function tick(now: number): void {
  const elapsed = (now - lastFrame) / 1000;
  lastFrame = now;

  if (state.playing) {
    state.playheadS = (state.playheadS + elapsed * state.rate) % WINDOW_S;
    redrawSpine();
  }

  if (globe) {
    globe.advance(elapsed * (state.playing ? state.rate : 0));
    globe.render();
  }

  if (worker && now - lastPropagate > PROPAGATE_INTERVAL_MS) {
    lastPropagate = now;
    worker.postMessage({
      type: "propagate",
      epochMs: state.windowStart.getTime() + state.playheadS * 1000,
    });
  }
  requestAnimationFrame(tick);
}

async function boot(): Promise<void> {
  // Dark is the design. docs/design.md holds two corrections about that: the
  // legibility criterion found dark was not necessary, and a second constraint the
  // criterion never covered, that this must not look like the previous project,
  // decided it. The pale ground stays a real, reachable design rather than a test
  // artefact, which is why there is a button and not just a query parameter.
  const requested = new URLSearchParams(location.search).get("ground");
  const remembered = localStorage.getItem(GROUND_KEY);
  applyGround(requested === "light" || (!requested && remembered === "light") ? "light" : "dark");

  renderMarginalia();

  const provenance = await api.provenance();
  state.provenance = provenance;
  state.windowStart = new Date(`${provenance.snapshot_date}T00:00:00Z`);
  renderMarginalia();

  const catalogue = await api.catalogue();
  state.norads = catalogue.norad;
  state.names = catalogue.name;
  state.types = catalogue.type;
  state.indexByNorad = new Map(catalogue.norad.map((n, i) => [n, i]));

  globe = await createGlobe(globeEl, catalogue.count);
  globe.setTypes(catalogue.type);
  globe.resize();

  worker = new Worker(new URL("./propagate.worker.ts", import.meta.url), { type: "module" });
  worker.onmessage = (event) => {
    const message = event.data;
    if (message.type === "positions") {
      globe?.setPositions(message.positions, message.velocities, message.ok);
    }
  };
  worker.postMessage({ type: "init", tle: await api.tle() });
  // One frame straight away. Waiting for the animation loop leaves the globe empty,
  // and the loop is paused on load.
  worker.postMessage({ type: "propagate", epochMs: state.windowStart.getTime() });

  // Clicking empty sky puts the record away, because the card is not a fixture. But
  // the globe is also a drag surface, and the end of a rotate fires a click too, so a
  // record with a burn set up on it could be thrown away by an ordinary drag. Only
  // treat it as a click if the pointer effectively did not move.
  let pressedAt: { x: number; y: number } | null = null;
  globe.canvas.addEventListener("pointerdown", (event) => {
    pressedAt = { x: event.clientX, y: event.clientY };
  });
  globe.canvas.addEventListener("click", (event) => {
    const moved = pressedAt
      ? Math.hypot(event.clientX - pressedAt.x, event.clientY - pressedAt.y)
      : 0;
    pressedAt = null;
    if (moved > 4) return;
    const index = globe?.pick(event.clientX, event.clientY);
    if (index !== null && index !== undefined) {
      void selectObject(state.norads[index]);
    } else if (state.selected) {
      clearSelection();
    }
  });

  searchInput.addEventListener("input", () => renderResults(searchInput.value));
  searchInput.addEventListener("focus", () => renderResults(searchInput.value));
  resultsEl.addEventListener("click", (event) => {
    const item = (event.target as HTMLElement).closest("li[data-norad]");
    if (!item) return;
    searchInput.value = "";
    resultsEl.innerHTML = "";
    resultsEl.classList.remove("open");
    void selectObject(Number(item.getAttribute("data-norad")));
  });

  toggleEl.addEventListener("click", () => {
    const next: Ground = document.documentElement.dataset.ground === "dark" ? "light" : "dark";
    localStorage.setItem(GROUND_KEY, next);
    applyGround(next);
  });

  spineCanvas.addEventListener("pointerdown", (event) => {
    state.playing = false;
    state.playheadS = spineOffsetAt(spineCanvas, event.clientX);
    redrawSpine();
    redrawCurve();
  });

  // The fine end of the same clock. A pixel on the spine is 57 seconds; a pixel here
  // is about three, which is the resolution an encounter actually happens at.
  curveCanvas.addEventListener("pointerdown", (event) => {
    const offset = curveOffsetAt(curveCanvas, event.clientX);
    if (offset === null) return;
    state.playing = false;
    state.playheadS = offset;
    redrawSpine();
    redrawCurve();
  });

  // A ResizeObserver rather than a window resize listener, because the first layout is
  // itself a resize. Sizing the canvases once during boot runs before the browser has
  // laid the new DOM out, which left every canvas at its default 300x150 backing
  // store, stretched to fill its element, until the user happened to drag the window.
  const observer = new ResizeObserver(() => {
    globe?.resize();
    redrawSpine();
    redrawCurve();
  });
  observer.observe(globeEl);
  observer.observe(spineCanvas);
  observer.observe(curveCanvas);

  window.addEventListener("keydown", (event) => {
    if ((event.target as HTMLElement).tagName === "INPUT") return;
    if (event.key === " ") {
      event.preventDefault();
      state.playing = !state.playing;
    }
    if (event.key === "Escape" && state.selected) clearSelection();
  });

  redrawSpine();
  redrawCurve();
  requestAnimationFrame(tick);
}

void boot();
