"""
WebSocket server: computes Liénard-Wiechert E-fields via pycharge and streams
NX×NY Float32 Ez arrays to the browser.

Usage:
    python server.py          # listens on ws://127.0.0.1:8765/ws

Protocol:
    Client → JSON  { f0, d_m, N, srcs:[{amp,fmul,phase},...], t }
    Server → bytes Float32Array(NX*NY), layout Ez[i*NY+j] (row-major, C order)

Physics model:
    Each source n is modelled as a non-relativistic z-oscillating point charge at
    rest position (0, y_n, 0).  The position function fed to pycharge is:

        r_n(t) = [0, y_n, z_amp_n · sin(omega_n · t + phi_n)]

    z_amp_n = amp_n · 1e-4 · lambda   →   v_max/c ~ 6e-5  (deeply non-relativistic)

    pycharge evaluates the full Liénard-Wiechert field (velocity + acceleration
    terms) at every grid point by solving for the retarded time numerically.
    In the far field this converges to the analytical formula used by index.html;
    in the near field (x < 2λ) the 1/r² velocity term becomes visible.

Performance:
    pycharge/JAX retraces & recompiles when source params change (slider moved).
    First frame after a slider move: ~1–3 s (JAX JIT compilation).
    Subsequent frames with unchanged params: ~50–300 ms → 3–15 fps.
    The browser falls back to the analytical formula while the server is busy.
"""

import asyncio
import time as _time
import warnings
import numpy as np

# Silence uvicorn's internal use of the deprecated asyncio.iscoroutinefunction
# (Python 3.14+).  The call is inside uvicorn, not our code.
warnings.filterwarnings(
    "ignore",
    message="'asyncio.iscoroutinefunction' is deprecated",
    category=DeprecationWarning,
)

# Must be set before any JAX code runs.  JAX defaults to float32; without x64
# the retarded-time root-finder's convergence tolerance (atol=1e-20) is below
# float32 precision (~1e-14), so the solver always hits max_steps and raises.
import jax
jax.config.update("jax_enable_x64", True)

import jax.numpy as jnp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn
import pycharge as pc
from concurrent.futures import ThreadPoolExecutor

# ── Physical / grid constants ─────────────────────────────────────────────────
C_LIGHT = 299_792_458.0
NX, NY        = 110, 90    # display resolution sent to browser (must match index.html)
NX_LW, NY_LW  = 55, 45    # LW compute resolution (4× fewer root-finds; upsampled before send)
XL0, XL1 = 0.3, 10.55     # x range in λ
YL0, YL1 = -7.5, 7.5      # y range in λ

app      = FastAPI()
executor = ThreadPoolExecutor(max_workers=1)

# ── Cache: avoid JAX retrace when only t changes ──────────────────────────────
_cache_key = None
_field_fn  = None   # callable (x, y, z, t) → Quantities

# ── Server-side animation clock ───────────────────────────────────────────────
# The browser sends its own simTime, but by the time pycharge responds (200–500 ms
# later) that timestamp is stale and the displayed field is phase-shifted behind
# the animation.  Instead the server maintains its own wall-clock time so every
# frame is evaluated at "now" rather than at "when the request was sent".
_ANIM_SPEED    = 2.5      # animation periods per real second (matches browser)
_srv_phys_t    = 0.0      # current server physical time [s]
_srv_stamp     = None     # perf_counter at last computation


def _tick(T_per: float, anim_speed: float = _ANIM_SPEED) -> float:
    """Advance server time by actual elapsed wall time; return current physical t."""
    global _srv_phys_t, _srv_stamp
    now = _time.perf_counter()
    if _srv_stamp is not None:
        dt = min(now - _srv_stamp, 0.05)        # cap at 50 ms (tab-switch guard)
        _srv_phys_t += dt * anim_speed * T_per  # same formula as browser
    _srv_stamp = now
    return _srv_phys_t


def _source_key(f0: float, d_m: float, N: int, srcs: list) -> tuple:
    return (f0, d_m, N, tuple((s["amp"], s["fmul"], s["phase"]) for s in srcs[:N]))


def compute_lw_field(params: dict) -> bytes:
    global _cache_key, _field_fn

    f0   = float(params["f0"])
    d_m  = float(params["d_m"])
    N    = int(params["N"])
    srcs = params["srcs"]
    # params["t"] is ignored: server tracks its own wall-clock time so the
    # evaluated phase is always "now", not "when the request was sent".
    anim_speed = float(params.get("anim_speed", _ANIM_SPEED))
    t    = _tick(1.0 / f0, anim_speed)

    key = _source_key(f0, d_m, N, srcs)

    if key != _cache_key:
        lam = C_LIGHT / f0
        charges = []
        for n, src in enumerate(srcs[:N]):
            amp   = float(src["amp"])
            fmul  = float(src["fmul"])
            phase = float(src["phase"])
            if amp < 1e-6:
                continue
            yn    = float((n - (N - 1) / 2) * d_m)
            omega = float(fmul * 2.0 * np.pi * f0)
            # z_amp chosen so v_max = z_amp · omega << c (non-relativistic regime)
            z_amp = float(amp * 1e-4 * lam)

            def make_pos(yn_=yn, z_amp_=z_amp, omega_=omega, phase_=phase):
                def position_fn(t):
                    return jnp.array([0.0, yn_, z_amp_ * jnp.sin(omega_ * t + phase_)])
                return position_fn

            charges.append(pc.Charge(position_fn=make_pos()))

        # jax.jit compiles the vmapped LW kernel once per param change;
        # every subsequent frame (same sources, different t) reuses the XLA binary.
        raw = pc.potentials_and_fields(charges) if charges else None
        _field_fn  = jax.jit(raw) if raw is not None else None
        _cache_key = key

    lam = C_LIGHT / f0
    # Compute on the smaller LW grid (4× fewer retarded-time root-finds)
    xl1_lam = float(params.get("xl1", XL1))
    yl0_lam = float(params.get("yl0", YL0))
    yl1_lam = float(params.get("yl1", YL1))
    x   = np.linspace(XL0 * lam, xl1_lam * lam, NX_LW)
    y   = np.linspace(yl0_lam * lam, yl1_lam * lam, NY_LW)
    xx, yy = np.meshgrid(x, y, indexing="ij")  # shape (NX_LW, NY_LW)
    zz  = np.zeros_like(xx)
    tt  = np.full_like(xx, t)

    if _field_fn is None:
        return np.zeros(3 * NX * NY, dtype=np.float32).tobytes()

    quantities = _field_fn(xx, yy, zz, tt)

    def _up(arr):
        return np.array(jax.image.resize(arr, (NX, NY), method="linear"), dtype=np.float32)

    Ez = _up(quantities.electric[..., 2])   # z-component of E (out of plane)
    Bx = _up(quantities.magnetic[..., 0])   # x-component of B (in plane)
    By = _up(quantities.magnetic[..., 1])   # y-component of B (in plane)

    # Layout: [Ez(NX*NY) | Bx(NX*NY) | By(NX*NY)], all float32, row-major
    return np.concatenate([Ez.ravel(), Bx.ravel(), By.ravel()]).tobytes()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    loop = asyncio.get_event_loop()
    try:
        while True:
            params     = await ws.receive_json()
            field_bytes = await loop.run_in_executor(executor, compute_lw_field, params)
            await ws.send_bytes(field_bytes)
    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765)
