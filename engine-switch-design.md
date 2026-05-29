# Engine Switch Design — EM-Wave Lab

## 1. Requirements: Current State of `index.html`

### 1.1 Physics Engine (Liénard-Wiechert / Phasor)

- **Two source models**, selectable per session:
  - *Punkt Quellen* — N≤1000 coherent point sources in a linear array
  - *Dipolantenne* — continuous dipole antenna of length L/λ (finite) or infinite plane wave
- **Per-source parameters**: amplitude A (0–1× A₀), frequency multiplier fmul (0–1× f₀), phase φ (in units of π)
- **Presets**: Alt. Phase, Beam-Steering, Random Phase, Half off, Reset
- **Dual computation path**:
  - N ≤ 30: Liénard-Wiechert Web Worker (full retarded-potential solution, includes radiation reaction). Computes Ez, Bx, By at 110×90 output grid.
  - N > 30: phasor superposition on main thread (O(NX·NY) per frame after one-time precomputation)
- **2D time-averaging**: exact from phasors (½|Z|²); EMA accumulation in LW path
- **Instantaneous field**: Re[e^{iωt}·Z] — same O(NX·NY) per frame
- **Screen-column intensity**: exact from phasors, 1024-point resolution; EMA in LW path

### 1.2 Visualization

- **2D field canvas**: RdBu colormap, tanh tone-mapping with RMS auto-scaling
- **E-field layer** (Ez): toggle on/off
- **B-field streamlines** (Bx, By): toggle on/off; drawn with seeded Runge-Kutta integrator
- **Time-averaged mode**: replaces instantaneous Ez with √(acc2D)×r^½ display, toggle in header
- **Log intensity scale**: toggle in header (applied to time-avg display)
- **Intensity panel** (right strip): instantaneous Ez² profile (blue) + time-averaged profile (gold) at the draggable screen line
- **Analytical screen curve**: 1/r far-field phasor sum, normalised, drawn over FDTD/LW intensity
- **Screen line**: draggable left/right on the 2D canvas; also controlled via sidebar slider

### 1.3 Axes and Zoom

- **X axis**: range [0, XL1 λ], adjustable via bottom slider (1–100 λ) and pinch-to-zoom
- **Y axis**: range ±ylHalf λ, adjustable via left slider (0.5–30 λ) and pinch-to-zoom
- **Scale lock** (`X≠Y` / `X=Y`): coupled or independent axis scaling
- **Fraunhofer button**: auto-positions screen to far-field boundary r_FF = 2(N-1)²d²/λ
- Physical extents preserved across frequency changes (sliders track in metres)

### 1.4 Source Controls (Sidebar)

- **N**: number of sources (1–1000)
- **d**: source spacing with physical unit selector (pm → km), live λ-ratio display
- **f₀**: frequency with unit selector (µHz → THz), live λ display
- **Per-source editor**: select source n → adjust A, fmul, φ individually; preset dropdown
- **Dipole-specific**: L/λ slider; infinite checkbox

### 1.5 Derived Statistics (Sidebar)

- λ₀, d/λ, N·d, T, r_FF (far-field boundary)
- Mobile-only stats panel mirrors these

### 1.6 UI/Layout

- **Header**: title, play/pause, speed slider (c_sim display), time-avg toggle, Fraunhofer button, theme toggle
- **Sidebar** (315 px): collapse to 36 px strip with vertical "Einstellungen" label; mobile: overlay slide-in
- **Canvas overlays**: axis sliders (x-bottom, y-left), lock/logscale buttons, load-bar (linked to WS backend)
- **Mobile landscape**: header hidden, sidebar overlay, pinch-to-zoom, bottom safe area inset
- **Portrait**: rotate-device prompt
- **Dark/light theme**: CSS variable swap

### 1.7 WebSocket Integration

- Optional backend at `ws://127.0.0.1:8765/ws` (used in `index-server.html`)
- Load bar animates while WS computes; shows "reloading…" on reconnect
- WS delivers pre-computed Ez/Bx/By frames that replace the LW worker result

---

## 2. Engine Interface Design

### 2.1 Core Abstraction

Both engines are wrapped in a JavaScript class that the host page instantiates and drives. The host never calls engine internals directly — it calls only the interface methods below.

```js
class Engine {
  // Called once after construction; receives shared params
  init(params)            // { f0, N_SRC, d_lam, srcs[], XL1, ylHalf, obstacles[] }

  // Advance simulation by one logical tick (called every rAF when not paused)
  tick()                  // returns void; engine decides its own step count

  // Return current field snapshot — called once per rAF after tick()
  getField()              // → { Ez: Float32Array(NX×NY), Bx?, By? }

  // Return intensity at the screen column
  getScreenData(screenLam)  // → { inst: Float64Array(NY_SCR), avg: Float64Array(NY_SCR) }

  // Mutators — called when UI controls change
  setFrequency(f0)
  setSources(N, d_lam, srcs[])   // full source array replace
  setSourceParam(n, {amp, fmul, phase})  // single-source update
  setObstacles(list)      // [{x0λ, y0λ, x1λ, y1λ}] in λ-units; FDTD maps to cells
  setViewport(XL1, ylHalf)        // LW recomputes phasors; FDTD: advisory (no grid resize)
  setStepsPerFrame(n)     // FDTD: steps/rAF; LW: no-op (wall-clock driven)
  resetFields()           // clear accumulators and transients

  // Read-outs for stats panel
  getStats()              // → { step, fps, lam, rFF, gridLabel }

  // Capability flags (read by host to show/hide controls)
  capabilities            // { hasObstacles, hasBField, hasFmul, hasDipole,
                          //   hasAxisZoom, hasTimeAvg, maxSources }

  // Cleanup
  destroy()               // terminate worker, free buffers
}
```

### 2.2 Field Coordinate Contract

Both engines must deliver `Ez` as a `Float32Array` of shape `[NX_OUT × NY_OUT]` (row-major, i×NY_OUT+j), where:
- Index `(i=0, j=0)` maps to canvas position (x=XL_min, y=+ylHalf) — i.e. top-left
- `j` increases downward (canvas y increases downward, physical y decreases)
- `NX_OUT`, `NY_OUT` are engine-internal constants exposed via `engine.NX`, `engine.NY`

The host's `draw()` function uses `engine.NX`, `engine.NY` and `engine.getXRange()` / `engine.getYRange()` to build the pixel mapping — replacing the current hard-coded constants.

### 2.3 Concrete Engine Classes

#### `EngineAnalytic` (wraps current index.html physics)

- `NX = 110`, `NY = 90`
- `capabilities = { hasObstacles: false, hasBField: true, hasFmul: true, hasDipole: true, hasAxisZoom: true, hasTimeAvg: true, maxSources: 1000 }`
- `tick()` advances `simTime` by `dt * animSpeed`; requests new LW frame if needed
- `getField()` returns `{ Ez, Bx, By }` (from phasors or LW worker)
- `setViewport()` recomputes phasors
- `setObstacles()` is a no-op

#### `EngineFDTD` (wraps current index-fdtd.html physics)

- `NX = 200`, `NY = 300` (active cells only; PML stripped before delivery)
- `capabilities = { hasObstacles: true, hasBField: false, hasFmul: false, hasDipole: false, hasAxisZoom: false, hasTimeAvg: false, maxSources: 20 }`
- `tick()` runs `stepsPerFrame` FDTD steps
- `getField()` returns `{ Ez }` (Hx/Hy available internally but not exposed initially)
- `setViewport()` is a no-op (domain fixed at 10λ × 15λ)
- `setObstacles()` converts λ-unit rects to grid cells and calls `recomputePEC()`

### 2.4 Sidebar Panel Strategy

The sidebar is split into **shared** and **engine-specific** panel groups. Each group carries a `data-engines="lw fdtd"` attribute listing which engines show it.

```
Shared panels (always visible):
  [Quellen Array]   N, d, f₀, stats (λ, d/λ, T, r_FF)
  [Modifikation]    per-source A, phase (fmul hidden when FDTD active)
  [Presets]         Reset + common presets

Engine-specific panels:
  [Modus]           Punkt / Dipol selector        data-engines="lw"
  [Dipol]           L/λ, infinite checkbox         data-engines="lw"
  [Hindernisse]     Draw / Löschen buttons         data-engines="fdtd"
  [Tempo]           Steps-per-frame slider         data-engines="fdtd"
```

On engine switch, the host iterates all `[data-engines]` groups and toggles `display` based on the active engine ID.

### 2.5 Header Controls Strategy

Controls are similarly tagged:

| Control | Shown for |
|---|---|
| Time-avg toggle | `lw` |
| Log scale button | `lw` |
| Fraunhofer button | `lw` |
| Speed/c_sim slider | `lw` |
| Steps-per-frame slider | `fdtd` |
| B-field toggle | `lw` |

On engine switch the host shows/hides via `data-engines` attributes or direct `classList` calls.

### 2.6 Engine Switcher UI

A small segmented control in the header, positioned between the title and the play button:

```
[ LW | FDTD ]
```

Implemented as two radio-style buttons with `data-engine="lw"` / `data-engine="fdtd"`, styled like the existing `header-btn`. The active engine gets the gold highlight (`border-color: var(--gold)`).

On click:
1. `currentEngine.destroy()`
2. `currentEngine = new EngineFDTD(sharedParams)` (or `EngineAnalytic`)
3. Hide/show sidebar panels and header controls per `capabilities`
4. `currentEngine.resetFields()`
5. The rAF loop checks `currentEngine` each frame — no other changes

---

## 3. FDTD Improvements Required

### 3.1 Must-Have (parity with index.html)

**3.1.1 Obstacle coordinates in λ-units**  
Currently obstacles are stored as raw grid indices. They must be converted to and from λ-unit floats (using `N_LAM = cells/λ`) so the engine interface can pass physical coordinates. This also allows presets to be defined in λ-space (portable across frequency changes).

**3.1.2 Screen intensity in λ-units**  
`screenLam` must be accepted in λ-units and converted to grid column internally. Currently done correctly but tightly coupled to the slider.

**3.1.3 Analytical overlay curve**  
Already present in index-fdtd.html. Must be preserved in the combined app and driven by the same `N_SRC`, `d_lam`, `srcs[]` shared state.

**3.1.4 Stats: fps, step, r_FF**  
Already computed in index-fdtd.html. Must be exposed via `getStats()`.

**3.1.5 Source frequency independence**  
FDTD uses a single `omega = 2π/N_LAM`. When the host changes `f0`, the physical λ changes but the grid λ-count is fixed. `N_LAM` is a dimensionless constant (20 cells/λ). The mapping is: `f0` changes `lam = C_LIGHT/f0`, which changes the physical scale of the 10λ domain. No grid rebuild needed — just update the axis labels and `screenLam` mapping.

**3.1.6 Per-source amplitude and phase in `srcGridPos`**  
Already implemented. Must be kept in the shared `srcs[]` array.

### 3.2 Performance (main thread blocking)

The FDTD loop currently runs on the main thread. At 4 steps/frame on a 240×340 grid (~330k cells), each frame takes ~3–6 ms. This is acceptable for 60 fps but creates jank on low-end devices and completely blocks UI interactions during each step.

**Option A — Offscreen Worker (recommended)**  
Move the entire FDTD step and pixel-filling to a `Worker` with `OffscreenCanvas`. The worker posts back a rendered `ImageBitmap` each frame. The main thread calls `ctx.drawImage(bitmap, ...)`. This eliminates all main-thread blocking.

Trade-off: `OffscreenCanvas` requires Chrome 69+ / Firefox 105+ / Safari 16.4+. All current target browsers support it.

**Option B — SharedArrayBuffer double-buffer**  
Keep the FDTD step in a worker; share `Ez[]` via `SharedArrayBuffer`. Main thread reads directly for rendering. Requires COOP/COEP headers.

**Option C — Stay on main thread**  
Keep the current approach. Acceptable if steps/frame stays ≤ 8 and the host page has no heavy CSS transitions during simulation.

Recommendation: **Option A** for the integration. The worker boundary maps cleanly onto `EngineFDTD.tick()` / `EngineFDTD.getField()` — the worker is an implementation detail hidden inside the class.

### 3.3 Nice-to-Have (extended parity)

**3.3.1 B-field visualization**  
FDTD already computes `Hx` and `Hy` at each step. Exposing them costs nothing; the host's existing `drawStreamlines()` function can consume them directly. Requires delivering `{ Ez, Bx: Hx, By: Hy }` from `getField()`.

**3.3.2 2D time-averaging**  
Add an `acc2D` accumulator to FDTD (same EMA pattern as in index.html). Enables the "Normiert und zeitgemittelt" toggle to work in FDTD mode.

**3.3.3 Axis zoom (display-only)**  
The FDTD active domain is a fixed 10λ × 15λ window. Implementing a true zoom would require either grid-resize (expensive) or a sub-window render (crop + scale). A lightweight solution: render the full active region, and use CSS/canvas `drawImage` clipping to implement a display-only zoom. The X and Y sliders in the host would control the displayed sub-window, not the simulated domain.

**3.3.4 Screen intensity at full NY_SCR resolution**  
Currently the FDTD screen samples `screenAcc[iy]` at `ANY = 300` points. Index.html uses `NY_SCR = 1024`. For visual parity, bilinear-interpolate `screenAcc` up to 1024 when delivering to the host.

---

## 4. Implementation Plan

### Phase 0 — Groundwork (no visible changes)

**0.1** Extract shared state into a `Params` object at the top of `index.html`:  
`{ f0, N_SRC, d_lam, srcs[], XL1, ylHalf, screenLam, obstacles[], isPaused, isLight }`

**0.2** Audit all slider event handlers that write to globals. Redirect writes through `Params` so both engines see the same values.

**0.3** Add `data-engines` attributes to every sidebar `sb-group` and every header control, but leave visibility logic as no-op for now.

---

### Phase 1 — `EngineAnalytic` wrapper

**1.1** Wrap the existing Liénard-Wiechert + phasor code into `class EngineAnalytic`. Methods:  
- `constructor(params)` — initialize arrays, spawn worker  
- `tick(dt)` — advance `simTime`, request LW frame if due  
- `getField()` — return `{ Ez, Bx, By }`  
- `getScreenData(screenLam)` — return `{ inst, avg }`  
- `setFrequency`, `setSources`, `setSourceParam`, `setViewport`, `resetFields`, `getStats`, `destroy`

**1.2** Replace all direct global references in `draw()` and `render()` with `engine.getField()`, `engine.getScreenData()`, `engine.NX`, `engine.NY`.

**1.3** Verify: app behaves identically to current `index.html` with only `EngineAnalytic` instantiated.

---

### Phase 2 — `EngineFDTD` wrapper

**2.1** Port FDTD physics from `index-fdtd.html` into `class EngineFDTD`. Key adaptation points:
- Replace global `Ez/Hx/Hy/sponge/pecMask` with instance fields
- Replace hardcoded slider IDs with method calls (`setFrequency`, `setSources`, `setObstacles`)
- `getField()` returns active-region slice: `Ez[AX0..AX1, AY0..AY1]` reshaped to `[ANX × ANY]`
- `getScreenData()` returns `screenAcc` interpolated to `NY_SCR` points
- `getStats()` returns `{ step: simStep, fps: fpsVal, lam: C_LIGHT/f0, rFF }`
- `setObstacles(list)` converts λ-unit rects → cell indices → calls `recomputePEC()`

**2.2** Pre-fill transients on init: run 300 FDTD steps silently (same as current `index-fdtd.html` init).

**2.3** Add analytical overlay computation to `getScreenData()` (port from `index-fdtd.html` draw loop, using shared `srcs[]`).

**2.4** Unit test: open a scratch page that only instantiates `EngineFDTD` and calls `tick()` + `getField()` in a loop, checking that the field diverges if stability is violated and converges for the default params.

---

### Phase 3 — Engine switcher and panel visibility

**3.1** Add the `[ LW | FDTD ]` segmented control to the header HTML.

**3.2** Write `switchEngine(id)` function:
```js
function switchEngine(id) {
  currentEngine?.destroy();
  currentEngine = id === 'fdtd' ? new EngineFDTD(readParams())
                                : new EngineAnalytic(readParams());
  updatePanelVisibility(currentEngine.capabilities);
  currentEngine.resetFields();
}
```

**3.3** Implement `updatePanelVisibility(caps)`:
- Iterate `[data-engines]` elements; compare to active engine ID
- Show/hide header controls (B-field, time-avg, Fraunhofer, speed, steps/frame)
- Show/hide sidebar groups (Dipol, Hindernisse, Tempo)
- Disable/grey the Fraunhofer button when engine returns `caps.hasAxisZoom === false`

**3.4** Obstacle draw events: only bind canvas `mousedown/touchstart` draw handlers when `caps.hasObstacles === true`. Disconnect them on engine switch.

---

### Phase 4 — FDTD performance (Worker offload)

**4.1** Move `EngineFDTD` core arrays and `fdtdStep()` into a dedicated `Worker` script (inlined as a `Blob URL` to stay single-file).

**4.2** Worker protocol:
- Main → Worker: `{ type: 'tick', stepsPerFrame }` — triggers N steps
- Worker → Main: `{ type: 'frame', ez: ArrayBuffer, screenAcc: ArrayBuffer, stats }` — transferable buffers

**4.3** `EngineFDTD.tick()` becomes non-blocking: post to worker, return immediately. `getField()` returns the most-recent worker result (double-buffer: worker fills one, host reads other).

**4.4** If `OffscreenCanvas` is available, move pixel-filling into the worker too.

---

### Phase 5 — Extended FDTD parity

**5.1** Add `acc2D` accumulator to FDTD worker → enables "zeitgemittelt" toggle in FDTD mode  
**5.2** Expose `Hx/Hy` as `Bx/By` from `getField()` → enables B-field streamlines  
**5.3** Add display-zoom crop in `draw()` for FDTD: use the `XL1`/`ylHalf` values to compute a sub-window rect within the active 10λ×15λ canvas, then `drawImage` with source/dest rects  

---

### Risks and Open Questions

| Risk | Mitigation |
|---|---|
| FDTD + EngineAnalytic both running simultaneously could thrash memory | `destroy()` is synchronous; only one engine alive at a time |
| Transferable buffers in the FDTD worker require ping-pong allocation | Pre-allocate two `Ez` buffer pairs in Phase 4 |
| Safari <16.4 lacks `OffscreenCanvas` | Feature-detect; fall back to Phase 3 on-main-thread approach |
| Presets reference engine-specific grid constants (WALL_I etc.) | Presets become engine methods: `engine.applyPreset('einzelspalt')` |
| Switching engine resets obstacles — user may not expect this | Show a brief "Hindernisse werden gelöscht" toast if obstacles exist when switching away from FDTD |
| FDTD domain is fixed 10λ×15λ; index.html can zoom to 100λ | Document as known limitation; offer display-zoom (Phase 5.3) as visual workaround |
