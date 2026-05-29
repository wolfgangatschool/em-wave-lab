# EM-Wave Lab · Beugungsgitter — Requirements, Architecture & Design Decisions

> **Continuity contract**: Before adding any feature, verify it is consistent with the
> physics model (Section 3), does not break the analytical overlay conditions (Section 5 DD6),
> and matches the visual style (Section 4).

---

## 1. Purpose

Interactive, browser-based simulation of electromagnetic wave diffraction and interference
for secondary / university physics education (German-speaking context).

**Target audience**: students and teachers who already know basic wave optics.  
**Goal**: make the physics of coherent sources, grating diffraction, phased arrays, and
beam-steering immediately tangible through live sliders — no install, no Python, no kernel.

---

## 2. File Structure

```
em-wave-lab/
  index.html        — complete app (single self-contained file, no build step)
  requirements.md   — this document
```

The entire application lives in `index.html`. There are **no external JS libraries**,
no bundler, no node_modules. The only network dependency is the Google Fonts CDN
(DM Sans, DM Mono, Playfair Display) — the app works offline if fonts are cached.

---

## 3. Physics Model

### 3.1 Simulation engine

The field is computed with the **analytical far-field Green's function** (not pycharge):

$$E_z(x, y, t) = \sum_{n=0}^{N-1} \frac{A_n}{r_n + \varepsilon} \cos(\omega_n t - k_n r_n + \varphi_n)$$

where:

| Symbol | Meaning |
|--------|---------|
| $N$ | number of sources (1–16) |
| $A_n$ | per-source amplitude [0, 1] |
| $\omega_n = 2\pi f_0 \cdot \text{fmul}_n$ | per-source angular frequency |
| $k_n = \omega_n / c$ | per-source wavenumber |
| $\varphi_n$ | per-source phase offset [0, 2π] |
| $r_n = \sqrt{x^2 + (y - y_n)^2}$ | distance from source n to grid point |
| $\varepsilon = 10^{-10}$ | singularity guard at source location |

Sources are arranged in a vertical line at x = 0, centred on y = 0:

$$y_n = \left(n - \frac{N-1}{2}\right) \cdot d \quad (n = 0 \ldots N-1)$$

This matches the Liénard-Wiechert far-field but is computed analytically so every
slider responds in real time — no JIT warmup, no Python process.

### 3.2 Physical parameters

| Parameter | Symbol | Default | Slider range |
|-----------|--------|---------|--------------|
| Source frequency | f₀ | 1 GHz | 0.1 – 10 GHz |
| Slit spacing (physical) | d | 45 cm | 5 – 200 cm |
| Number of sources | N | 10 | 1 – 16 |
| Per-source amplitude | Aₙ | 1.0 | 0.0 – 1.0 |
| Per-source freq. multiplier | fmul_n | 1.0 | 0.50 – 2.00 (step 0.25) |
| Per-source phase offset | φₙ | 0.0 rad | −2π – +2π |

Speed of light: `C_LIGHT = 299792458 m/s` (exact SI definition).

### 3.3 Why d is physical (not d/λ)

**DD1 — Physical slit spacing, not normalised.**  
If d were stored as d/λ (normalised), the field in λ-coordinates is exactly
scale-invariant: changing f₀ cancels out of every phase term `k·r = (2π/λ)·(x_λ·λ) = 2π·x_λ`
and the plot would not change at all. Storing d in **metres** means d/λ = d·f₀/c changes
with frequency, so the interference pattern evolves correctly when the frequency slider moves.
`d_lam` is always a derived quantity: `d_lam = d_m * f0 / C_LIGHT`.

### 3.4 Simulation grid

| Constant | Value | Meaning |
|----------|-------|---------|
| `NX = 110` | — | grid points along x |
| `NY = 90` | — | grid points along y |
| `XL0 = 0.3λ, XL1 = 10.55λ` | — | x range (avoids singularity at x=0) |
| `YL0 = -7.5λ, YL1 = 7.5λ` | — | y range (covers grating for d/λ up to ~1.5) |

Grid arrays (`xGrid`, `yGrid`) are in **metres**. The distance matrix `R_mat[n·NX·NY + i·NY + j]`
is pre-computed in `recompute()` and reused every frame — this is the main performance
optimisation (avoids sqrt in the inner loop).

The grid axes are labelled in units of **λ** (x/λ, y/λ). The screen intensity y-axis
is labelled in **physical units** (km, m, mm, µm, nm, pm) with auto-selected unit.

### 3.5 Animation timing

`simTime` advances by `dt * 2.5` periods per real second (i.e., the animation runs at
2.5× the physical wave frequency). `dt` is capped at 50 ms to prevent jumps after
tab switches. At 60 fps the wave completes ~2.5 periods per second, giving a visually
smooth propagation without being too fast to follow.

---

## 4. Visual Style & Architecture

### 4.1 Tech stack

| Item | Choice |
|------|--------|
| Language | Vanilla JS (ES2020 `'use strict'`) |
| Rendering | Canvas 2D API — one main canvas, one offscreen NX×NY buffer |
| Layout | CSS Flexbox + Grid, CSS custom properties for theming |
| Fonts | Google Fonts: DM Sans (UI), DM Mono (numbers/labels), Playfair Display (title) |
| Dependencies | None (zero JS libraries) |

### 4.2 Style reference

Matches **em-schwingkreis** (`/Users/wolfgang.kiesenhofer/Projects/school/physics/em-schwingkreis/index.html`):

- Dark-mode default with a light-mode toggle (☀/☾ button, top-right)
- CSS variables: `--bg`, `--panel`, `--panel2`, `--border`, `--text`, `--text-dim`, `--text-bright`, `--gold`, `--blue`, `--orange`, `--red`, `--radius`, `--radius-sm`
- Dark palette: bg `#0a0b0e`, panel `#13151b`, gold `#d4a85a`, blue `#6ed0ff`
- Light palette: bg `#f5f6fa`, panel `#ffffff`, gold `#a07020`, blue `#1a7fb5`
- Slider thumb: circle with 2px border in `currentColor`, fills with bg on hover
- Section labels: DM Mono, uppercase, letter-spacing 0.14em, gold colour, full-width rule after
- Preset buttons: DM Mono, border, hover → gold border + gold text

### 4.3 Layout structure

```
<header>          title + theme toggle
<main>
  global params   3-column slider row  (f₀ · d · N)
  presets         row of buttons
  sim-layout      flex row:
    source-panel    290px fixed, per-source grid (10 rows × 3 sliders)
    canvas-area     flex-1, aspect-ratio 16/10
      canvas#field  (main + offscreen buffer)
  stats-bar       λ · T · k · Gitterbreite · Hauptmaxima · fps
```

### 4.4 Canvas layout (inside `draw()`)

```
┌─────────────────────────────────┬──────────────────────────────┐
│  2D field (FIELD_W = W - SCREEN_W - 1)  │  Screen panel (SCREEN_W = max(100, 20% W)) │
│  offscreen NX×NY → stretched    │  [y-axis 46px][curve iPW px] │
│  RdBu colormap, tanh compress   │  CYAN curve + GOLD analytical │
└─────────────────────────────────┴──────────────────────────────┘
```

Canvas backing store is resized every frame if `offsetWidth/offsetHeight` changes
(handles window resize, font loading). `ctx.setTransform(dpr, 0, 0, dpr, 0, 0)` is
called at the top of every `draw()` call — **never accumulate transforms across frames**.

### 4.5 Colormap

**DD2 — RdBu with tanh compression (not SymLogNorm).**  
9-stop RdBu diverging colormap: negative Ez → blue, positive → red, zero → white.
Amplitude compression: `t = tanh(Ez · scale)` where `scale = 1 / (RMS(Ez) · 4)`.
This compresses the dynamic range similarly to matplotlib's `SymLogNorm`, making
near-field spikes and far-field radiation visible simultaneously.

```javascript
const CM = [
  [5,48,97],[33,102,172],[67,147,195],[146,197,222],[247,247,247],
  [244,165,130],[214,96,77],[178,24,43],[103,0,31]
];
```

The offscreen NX×NY canvas is filled via `ImageData` (pixel-by-pixel) and then
`drawImage`-scaled to FIELD_W×H with `imageSmoothingQuality = 'high'`.

---

## 5. Design Decisions

### DD3 — Screen intensity: exponential-decay accumulator

The screen panel shows the time-averaged intensity at x = 10λ. Instead of a fixed
running-mean (which would freeze on slider change), an **exponential decay** is used:

```javascript
screenAcc[j] = screenAcc[j] * (1 - SCREEN_DECAY) + Ez[iScreen * NY + j]² * SCREEN_DECAY
```

`SCREEN_DECAY = 0.05` means ~20-frame memory. This means:
- The pattern builds up visibly over ~0.3 s after a slider change
- Old state decays away automatically — no explicit reset needed on most changes
- `screenAcc.fill(0)` is called on geometry changes (f₀, d, N) for a clean restart

### DD4 — Screen y-axis: auto-scaling physical units

The screen intensity y-axis shows physical distance (not λ-normalised) so students
can see how the fringe spacing changes in absolute terms when frequency changes.

Unit selection: scan `[km, m, mm, µm, nm, pm]`, pick the largest unit where
`|yMax_physical| / unit_scale ≥ 0.5`. Tick step uses a standard nice-number algorithm
(1/2/5 × 10ⁿ, targeting ~5 ticks). Float drift in the tick loop is suppressed by
rounding to `tStep * 1e-6` precision.

### DD5 — Analytical overlay: phasor sum (not equal-amplitude formula)

**DD5 — General phasor sum, not the closed-form sinc² formula.**  
The old `(sin(Nδ)/N·sin(δ))²` formula is only valid when all Aₙ are equal. It is
replaced by the exact far-field phasor sum:

$$I(y) \propto \left|\sum_n A_n e^{i(\phi_n + k d_n \sin\theta)}\right|^2
= \left(\sum_n A_n \cos\Phi_n\right)^2 + \left(\sum_n A_n \sin\Phi_n\right)^2$$

where $\Phi_n = 2\pi d_\lambda \sin\theta \cdot (n - \tfrac{N-1}{2}) + \varphi_n$
and $\sin\theta = y / \sqrt{L^2 + y^2}$ (exact, not small-angle).

The overlay is shown whenever **all sources share the same fmul** (`|fmul_n − 1| < 0.01`),
regardless of amplitude or phase. It disappears for incoherent configurations (mixed
frequencies), because time-averaged intensity then requires separate phasor sums per
frequency — not a single static curve.

### DD6 — sinθ = y/√(L²+y²), not y/L (no small-angle approximation)

The small-angle approximation sinθ ≈ y/L shifts the m=1 maximum from the exact
position y = L·sinθ/cosθ to y ≈ L/d_lam. For d/λ = 1.5 (sinθ = 0.667, θ = 42°),
this is a 34% position error. The exact expression is always used.

### DD7 — Source panel: 16 pre-allocated slots

The `srcs` array always has 16 entries. When N changes, only `srcs[0..N-1]` are
read by `computeField`. The per-source UI rows are rebuilt by `buildRows()` (innerHTML
clear + recreate). Slider values survive N changes because `srcs[]` state is not
cleared, only the DOM is rebuilt.

### DD8 — Animation runs always (no pause button)

The `requestAnimationFrame` loop runs unconditionally. Adding a pause/play button
is a natural next step; it would require storing the `animId` and calling
`cancelAnimationFrame(animId)`.

### DD9 — Per-source frequency multiplier: discrete steps

`fmul_n` slider uses `step=25` on the range `[50, 200]` (mapped to [0.50, 2.00]).
This gives discrete values: 0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00.
Rationale: irrational frequency ratios produce no stable interference pattern
(incoherent superposition), so discrete rational multiples are more pedagogically
useful. A finer step is technically fine but visually harder to interpret.

---

## 6. Controls Reference

### Global parameters

| Slider | ID | Range | Maps to |
|--------|----|-------|---------|
| f₀ | `sl-f0` | 1–100 (×1e8 Hz) | 0.1 GHz – 10 GHz |
| d | `sl-d` | 5–200 (cm) | 0.05 m – 2.00 m physical spacing |
| N | `sl-N` | 1–16 | number of active sources |

### Presets

| Button | Effect |
|--------|--------|
| Reset | All Aₙ=1, fmul=1, φₙ=0 |
| Alt. Phase | φₙ = 0 for even n, π for odd n |
| Beam-Steering | φₙ = (n · π/4) mod 2π (linear ramp) |
| Zufällige Phase | φₙ = random ∈ [0, 2π] |
| Hälfte aus | Aₙ = 0 for n < N/2, else 1 |

### Per-source sliders

| Slider | Range (internal) | Maps to |
|--------|-----------------|---------|
| A (amplitude) | 0–100 (÷100) | 0.00 – 1.00 |
| f × (freq. mult.) | 50–200, step 25 (÷100) | 0.50× – 2.00× f₀ |
| φ (phase) | −200 to +200, step 25 (÷100 × π) | −2π – +2π rad |

---

## 7. Known Limitations & Open Work

| # | Issue / Planned feature | Notes |
|---|------------------------|-------|
| L1 | No pause/play button | `animId` not stored; easy to add |
| L2 | No animation speed control | `simTime += dt * 2.5` hardcoded |
| L3 | Scale distortion in 2D field | x and y have different px/λ due to landscape aspect ratio; physically correct, visually stretched |
| L4 | Screen at fixed x = 10λ | Could be a draggable line or slider |
| L5 | Per-source position sliders | `y_srcs` is hard-coded as equidistant; all infrastructure in place to make it dynamic |
| L6 | No mobile / touch layout | Source panel is too wide below 920px; needs redesign for small screens |
| L7 | No export / screenshot button | Canvas `toBlob()` + `<a download>` would be straightforward |
| L8 | Refraction not modelled | Free-space only; Snell / Huygens would need a separate analytical module |
| L9 | Analytical overlay only for equal fmul | Mixed-frequency incoherent sum needs time-averaging over many periods — expensive |

---

## 8. Performance Notes

At default settings (N=10, NX=110, NY=90, 60 fps):
- Inner loop: 10 × 110 × 90 = 99 000 `Math.cos` evaluations per frame
- Measured: ~120 fps on M-series Apple Silicon (arm64 Safari/Chrome)
- Distance matrix (`R_mat`) is pre-computed on geometry change — only `cos` in hot path
- `Float32Array` for `Ez`, `Float64Array` for `R_mat` (precision needed for distances)
- `ImageData` pixel fill is the second-most expensive step; no further optimisation needed

If N or NX/NY is increased significantly, consider:
- Reducing `NX/NY` and upscaling with CSS `image-rendering: pixelated` for a retro look
- Moving `computeField` to a Web Worker (postMessage Ez buffer back each frame)
- Using WebGL for the pixel fill (fragment shader replaces the ImageData loop)

---

## 9. Consistency Rules for Future Development

Before adding any new feature:

1. **Physics formula changes** must be documented in Section 5 with the old formula,
   the new formula, and the reason.
2. **New sliders** follow the existing pattern: raw integer slider → mapped value in `readGlobals()`
   or per-source listener; display value updated in the same listener.
3. **Colormap / rendering changes** must keep the `tanh`-based amplitude compression
   (or document the replacement in DD2).
4. **Visual style** must match em-schwingkreis: same fonts, same CSS variable names,
   same dark/light toggle pattern.
5. **The analytical overlay** must use the phasor sum (DD5) — never revert to
   the equal-amplitude sinc formula.
6. **No external JS libraries** unless explicitly approved. The single-file constraint
   is a feature: the app works from a USB stick or local file system with no server.
