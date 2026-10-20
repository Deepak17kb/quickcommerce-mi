"""
engine.py — the simulation engine behind SIMULATE (deliverable 11) and OPTIMIZE (12a, 12b). SYNTHETIC.

Every parameter is read from a fitted model's saved outputs through src.model_output (the contract), never
retyped:
    price_response      corrected leader / follower response, persistence and shock sizes, bootstrap draws
    stockout_survival   discrete-Weibull frailty hazard (k, category, platform, evening, promo, pressure, frailty)
    restock_interval    negative-binomial restock durations (category, platform, dispersion)
    eta_forecast        ETA terms (evening peak, discount, store OOS share)

WHAT A SIMULATION MAY CLAIM
  "Under the fitted (generated) dynamics, X moves from a to b." Positioning only: price rank, cheapest-of-4 share,
  availability, ETA. Never demand, orders, GMV or revenue; no order data exists (docs/PROJECT_PLAN.md, 11-12).
  Scenarios assume a platform's price move is a deviation the others respond to exactly as the fitted response
  model says; that is the model's definition of a response, not an observed fact.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import src.load as L
from src.model_output import MODELS_DIR, load_model_outputs
from src.models import price_response as PR

PLATFORMS = PR.PLATFORMS
LEADER, FOLLOWERS = PR.LEADER, PR.FOLLOWERS


# =========================================================================== prices
@dataclass
class PriceWorld:
    pan: pd.DataFrame
    T: int
    n_keys: int
    theta: dict
    wave_sd: dict
    boot: pd.DataFrame
    keys: list
    key_category: pd.Series

    @classmethod
    def load(cls):
        out = load_model_outputs('price_response')
        c, T = PR.load_panel()
        pan, X, n_keys = PR.structure(c, T)
        wave = out['metrics']['leader_and_noise']['wave_sd_read_off_data']
        boot = pd.read_csv(MODELS_DIR / 'price_response' / 'bootstrap.csv')
        keys = sorted(c.canonical_product_key.unique())
        cat = c.groupby('canonical_product_key').category.first().reindex(keys)
        return cls(pan, T, n_keys, out['params']['theta_corrected'], wave, boot, keys, cat)

    def simulate(self, cut: dict, horizon: int = 12, n_sims: int = 20, respond: bool = True, seed: int = 1,
                 param_uncertainty: bool = True, return_prices: bool = False) -> dict:
        """cut: {platform: array over keys of fractional price moves (-0.03 = a 3% cut)}. The move is a persistent
        shift of that platform's latent log price from the first horizon snapshot on.

        Each panel's latent deviation is y (the fitted AR / response process) plus its own scenario shift. The leader
        follows its own AR. A follower responds to the leader's FULL latent price (noise + any scenario shift) with
        the fitted beta and lag; respond=False removes the leader's scenario shift from what followers respond to
        (the static view: competitors do not react). Prices are snapped to each panel's inferred grid.
        return_prices=True adds 'platform_prices' (sim, platform, key, snapshot): each platform's mean grid price of the
        product, NaN where the platform does not list it."""
        rng = np.random.default_rng(seed)
        pan, K = self.pan, self.n_keys
        plat, k = pan.platform.to_numpy(), pan.k.to_numpy()
        n = len(pan)
        burn, TT = PR.BURN, PR.BURN + horizon
        lead_rows = pd.Series(np.flatnonzero(plat == LEADER), index=k[plat == LEADER])
        lead_rows = lead_rows[~lead_rows.index.duplicated()]
        lead_of = lead_rows.reindex(k).to_numpy()
        has = ~np.isnan(lead_of); lead_of = np.nan_to_num(lead_of).astype(int)
        lag = np.array([PR.PLANTED['lag'].get(p, 1) for p in plat])
        isL = plat == LEADER
        shift = np.zeros(n)
        for p, arr in cut.items():
            m = plat == p
            shift[m] = np.log1p(np.asarray(arr, float)[k[m]])
        on = np.zeros(TT); on[burn:] = 1.0
        cheap = np.zeros((n_sims, horizon, 4)); rank = np.zeros((n_sims, horizon, 4))
        final_move = np.zeros((n_sims, 4))
        cheap_key = np.zeros((4, K)); key_obs = np.zeros(K)
        sim_key = np.full((n_sims, 4, K), np.nan)          # per simulation: share of the horizon each key is cheapest
        key_t = np.zeros((4, K, horizon)); key_t_n = np.zeros((K, horizon))
        all_M = np.full((n_sims, 4, K, horizon), np.nan, np.float32) if return_prices else None
        for sidx in range(n_sims):
            th = dict(self.theta)
            if param_uncertainty and len(self.boot):
                th.update(self.boot.iloc[rng.integers(len(self.boot))].to_dict())
            rho = np.array([th[f'rho[{p}]'] for p in plat]); sig = np.array([th[f'sigma[{p}]'] for p in plat])
            beta = np.array([th.get(f'beta[{p}]', 0.0) for p in plat]) * has
            y = np.zeros((n, TT))
            eps = rng.standard_normal((n, TT))
            for t in range(1, TT):
                tl = np.maximum(t - lag, 0)
                ref = y[lead_of, tl] + (shift[lead_of] * on[tl] if respond else 0.0)
                fol = rho * y[:, t - 1] + beta * (ref - y[:, t - 1]) + sig * eps[:, t]
                y[:, t] = np.where(isL, rho * y[:, t - 1] + sig * eps[:, t], fol)
            x = y[:, burn:] + shift[:, None]
            w = np.stack([rng.normal(0, self.wave_sd[p], horizon) for p in plat])
            P = pan.level.to_numpy()[:, None] * np.exp(x + w)
            step, rem = pan.step.to_numpy()[:, None], pan.rem.to_numpy()[:, None]
            price = np.round((P - rem) / step) * step + rem
            price = np.where(price < 1, np.maximum(np.round(P), 1), price)
            M = np.full((4, K, horizon), np.nan)            # platform price per key: mean over its panels
            for j, p in enumerate(PLATFORMS):
                m = plat == p
                S = np.zeros((K, horizon)); N = np.zeros((K, 1))
                np.add.at(S, k[m], price[m]); np.add.at(N, k[m], 1)
                M[j] = np.where(N > 0, S / np.where(N > 0, N, 1), np.nan)
                final_move[sidx, j] = float(np.expm1(x[m, -1].mean()))
            if return_prices:
                all_M[sidx] = M
            ok = np.isfinite(M).all(0)                      # keys priced on all four platforms
            mn = np.nanmin(M, 0)
            key_obs += ok.sum(1)
            key_t_n += ok
            for j in range(4):
                is_min = (M[j] <= mn + 1e-9) & ok
                cheap[sidx, :, j] = is_min.sum(0) / ok.sum(0)
                cheap_key[j] += is_min.sum(1)
                key_t[j] += is_min
                with np.errstate(invalid='ignore'):
                    sim_key[sidx, j] = np.where(ok.any(1), is_min.sum(1) / np.maximum(ok.sum(1), 1), np.nan)
                rank[sidx, :, j] = np.nanmean(np.where(ok, (M < M[j][None] - 1e-9).sum(0) + 1, np.nan), 0)
        with np.errstate(invalid='ignore'):
            by_key = cheap_key / np.where(key_obs > 0, key_obs, np.nan)
            by_key_t = key_t / np.where(key_t_n > 0, key_t_n, np.nan)[None]
        out = {'cheapest_share': cheap, 'mean_rank': rank, 'final_mean_move': final_move,
                'cheapest_by_key': by_key,           # (platform, key): share of snapshots x sims cheapest
                'cheapest_by_sim_key': sim_key,      # (sim, platform, key): share of the horizon cheapest
                'cheapest_by_key_t': by_key_t}       # (platform, key, snapshot): share of sims cheapest
        if return_prices:
            out['platform_prices'] = all_M
        return out


# =========================================================================== stock
@dataclass
class StockWorld:
    cats: list
    a_haz: np.ndarray
    b_haz: np.ndarray
    g_eve: float
    d_promo: float
    th_pressure: float
    k: float
    s_frail: float
    a_rst: np.ndarray
    b_rst: np.ndarray
    n_rst: float
    phi: float
    eta: dict = field(default_factory=dict)

    @classmethod
    def load(cls):
        sv = load_model_outputs('stockout_survival')
        rs = load_model_outputs('restock_interval')
        eta = load_model_outputs('eta_forecast')
        e = sv['params']['estimates_V2']
        cats = sv['params']['categories']
        a_haz = np.array([e[f'a[{c}]'] for c in cats])
        b_haz = np.array([0.0] + [e[f'b[{p}]'] for p in PLATFORMS[1:]])
        r = rs['params']['recovery_estimates']
        a_rst = np.array([r[f'a[{c}]'] for c in cats])
        b_rst = np.array([0.0] + [r[f'b[{p}]'] for p in PLATFORMS[1:]])
        rec = {row['parameter']: row['estimate'] for row in eta['metrics']['structural_recovery']}
        eta_terms = {'peak': rec['evening peak (minutes)'],
                     'b_discount': rec['discount depth effect (minutes per 100% depth)'],
                     'b_store_oos_state_space': rec.get('store OOS share effect, state-space (Kalman ML)'),
                     'b_store_oos_note': 'confounded with demand; the state-space value is a partial correction'}
        return cls(cats, a_haz, b_haz, e['g_evening'], float(np.exp(e['log_d_promo'])), e['th_pressure'],
                   float(np.exp(e['log_k'])), float(np.exp(e['log_s'])), a_rst, b_rst,
                   float(np.exp(r['log_n'])), sv['metrics']['store_pressure_phi']['estimate'], eta_terms)

    # ---- state at the start of the test period (last val snapshot), SYNTHETIC listings
    def initial_state(self):
        import src.features.stock_clock as SC
        ml = SC.attach(L.load_ml())
        s = ml[ml.data_status == 'SYNTHETIC'].copy()
        s['_ts'] = pd.to_datetime(s.observed_at.astype(str), format='mixed')
        s = s.sort_values(['platform', 'store_id', 'product_id', '_ts'])
        s['pos'] = s.groupby(['platform', 'store_id', 'product_id']).cumcount()
        last_val = int(s[s.split == 'val'].pos.max())
        return self.state_from_rows(s[s.pos == last_val])

    def state_from_rows(self, st):
        """Simulation state from any set of SYNTHETIC rows (one per listing) carrying the stock-clock columns."""
        st = st.reset_index(drop=True)
        promo = st.mrp_source.eq('simulated_discounted')
        out = pd.DataFrame({
            'observation_key': st.observation_key, 'platform': st.platform, 'store_id': st.store_id,
            'category': st.category, 'in_stock': st.in_stock.astype(int),
            'clock': np.maximum(st.instock_run_length.fillna(0), 1).astype(float),
            'clock_censored': st.instock_clock_censored.fillna(0).astype(int),
            'oos_elapsed': st.oos_run_length.fillna(0).astype(float),
            'depth': np.where(promo, st.discount_7d_avg.fillna(st.discount_percent) / 100.0, 0.0),
            'next_evening': st.next_snapshot_is_evening.fillna(1.0).astype(float)})
        # a clock that started before the panel is a lower bound: add the expected pre-panel age under the fitted
        # hazard's equilibrium law, P(age a | survived o) proportional to S(a + o), as deliverable 7 does
        cen = (out.clock_censored == 1) & (out.in_stock == 1)
        if cen.any():
            c, p = self._codes(out[cen])
            e = np.exp(self.a_haz[c] + self.b_haz[p] + 0.5 * self.g_eve + np.log1p(self.d_promo * out.depth[cen].to_numpy()))
            ages = np.arange(0, 121, dtype=float)
            clock = ages[None, :] + out.clock[cen].to_numpy()[:, None]
            w = np.exp(-e[:, None] * (clock - 1) ** self.k)
            out.loc[cen, 'clock'] = (w * clock).sum(1) / w.sum(1)
        return out

    def _codes(self, st):
        return (pd.Categorical(st.category, categories=self.cats).codes,
                pd.Categorical(st.platform, categories=PLATFORMS).codes)

    def hazard(self, st, clock, evening, depth, pressure, z):
        c, p = self._codes(st)
        eta = self.a_haz[c] + self.b_haz[p] + self.g_eve * evening + np.log1p(self.d_promo * depth) \
            + self.th_pressure * pressure + self.s_frail * z
        inc = clock ** self.k - (clock - 1) ** self.k
        return 1 - np.exp(-np.exp(eta) * inc)

    def restock_mu(self, st):
        c, p = self._codes(st)
        return np.exp(self.a_rst[c] + self.b_rst[p])

    def draw_duration(self, rng, mu):
        m = np.maximum(mu - 1, 1e-6); n = self.n_rst
        return 1 + rng.negative_binomial(n, n / (n + m))

    def remaining_mean(self, st, elapsed):
        """E[D - a | D >= a] under the negative binomial, per OOS listing."""
        from scipy.stats import nbinom
        mu = self.restock_mu(st); m = np.maximum(mu - 1, 1e-6); n = self.n_rst; p = n / (n + m)
        a = np.maximum(elapsed, 1)
        sf_a = nbinom.sf(a - 2, n, p)                  # P(D >= a) = P(D - 1 >= a - 1)
        tot = np.zeros(len(a))
        for s in range(1, 61):
            tot += nbinom.sf(a + s - 2, n, p)          # P(D >= a + s)
        return tot / np.maximum(sf_a, 1e-12)

    def simulate(self, st, horizon=12, n_sims=20, seed=1, depth_delta=None, pressure_shock=None,
                 policy=None, capacity_share=0.0, outage=None, return_states=False, active=None):
        """Forward simulation. depth_delta: per-listing change in promo depth. pressure_shock: dict store -> (sd, snapshots).
        policy(state_dict, rng) -> indices to act on (expedite restock if OOS, refresh clock if in stock), at most
        capacity_share of each store's listings per snapshot.
        outage: {'mask': bool per listing, 'length': int or None}. The masked listings are out of stock NOW (the start).
        `length` = snapshots they stay out AFTER now (0 = restored before the next snapshot, which returns them with a
        fresh in-stock clock); None = a spell length D drawn from the fitted restock distribution (deliverable 8),
        which counts now, so D - 1 snapshots out after now, exactly as for a listing observed out today.
        return_states: also return 'in_stock_path' (sim, snapshot, listing), int8.
        active: bool per listing; inactive listings are simulated (keeping every random stream paired with a run where
        they are active) but the policy never sees or counts them."""
        rng_master = np.random.default_rng(seed)
        n = len(st)
        depth = st.depth.to_numpy() + (0 if depth_delta is None else np.asarray(depth_delta))
        depth = np.clip(depth, 0, 0.6)
        stores = st.store_id.to_numpy()
        su, s_idx = np.unique(stores, return_inverse=True)
        oos_path = np.zeros((n_sims, horizon)); actions = np.zeros(n_sims)
        per_listing_oos = np.zeros(n)
        per_sim_listing = np.zeros((n_sims, n), np.float32)
        states = np.zeros((n_sims, horizon, n), np.int8) if return_states else None
        mu = self.restock_mu(st)
        for si in range(n_sims):
            rng = np.random.default_rng(rng_master.integers(1 << 31))
            z = rng.standard_normal(n)
            D = np.zeros(len(su))
            ins = st.in_stock.to_numpy().copy(); clock = st.clock.to_numpy().copy()
            remaining = np.where(ins == 0, np.maximum(np.round(self.remaining_mean(st, st.oos_elapsed.to_numpy())), 1), 0)
            elapsed = np.where(ins == 0, np.maximum(st.oos_elapsed.to_numpy(), 1), 0).astype(float)
            eve = st.next_evening.to_numpy().copy()
            if outage is not None:
                om = np.asarray(outage['mask'], bool)
                ins[om] = 0; elapsed[om] = 1.0
                L_ = outage.get('length')
                # a separate stream for outage lengths, so every other draw stays paired with the no-outage run
                orng = np.random.default_rng([seed, si, 7])
                remaining[om] = L_ + 1 if L_ is not None else self.draw_duration(orng, mu[om])
            for t in range(horizon):
                D = self.phi * D + np.sqrt(1 - self.phi ** 2) * rng.standard_normal(len(su))
                pres = D[s_idx].copy()
                if pressure_shock:
                    for store, (size, dur) in pressure_shock.items():
                        if t < dur:
                            pres[stores == store] += size
                if policy is not None and capacity_share > 0:
                    # a policy sees only what an operator could: stock state, in-stock clock, time out so far
                    state = {'in_stock': ins, 'clock': clock, 'elapsed': elapsed, 'st': st, 'world': self,
                             'evening': eve, 'depth': depth, 't': t, 'horizon': horizon,
                             'active': None if active is None else np.asarray(active, bool)}
                    if getattr(policy, 'oracle', False):
                        # benchmark only: a clairvoyant policy that knows each outage's true remaining length
                        state['hidden_remaining'] = remaining
                    idx = policy(state, rng, capacity_share)
                    if len(idx):
                        oos_i = idx[ins[idx] == 0]; in_i = idx[ins[idx] == 1]
                        ins[oos_i] = 1; clock[oos_i] = 1; remaining[oos_i] = 0; elapsed[oos_i] = 0
                        clock[in_i] = 1
                        actions[si] += len(idx)
                h = self.hazard(st, clock, eve, depth, pres, z)
                goes = (ins == 1) & (rng.random(n) < h)
                remaining = np.where(ins == 0, remaining - 1, remaining)
                back = (ins == 0) & (remaining <= 0)
                dur = self.draw_duration(rng, mu)
                remaining = np.where(goes, dur, remaining)
                ins_new = np.where(ins == 1, ~goes, back).astype(int)
                clock = np.where((ins_new == 1) & (ins == 1), clock + 1, np.where(ins_new == 1, 1, clock))
                elapsed = np.where(ins_new == 0, elapsed + 1, 0)
                ins = ins_new
                oos_path[si, t] = 1 - ins.mean()
                per_listing_oos += (1 - ins)
                per_sim_listing[si] += (1 - ins)
                if return_states:
                    states[si, t] = ins
                eve = 1 - eve
        out = {'oos_share_path': oos_path, 'actions': actions, 'per_listing_oos_rate': per_listing_oos / (n_sims * horizon),
               'per_sim_listing_oos_rate': per_sim_listing / horizon}      # (sim, listing)
        if return_states:
            out['in_stock_path'] = states
        return out

    def eta_shift(self, depth_delta_mean, oos_share_delta):
        """Mean ETA change (minutes) from a promo-depth change and a store OOS-share change."""
        b_oos = self.eta['b_store_oos_state_space'] or 0.0
        return {'from_discount_depth': self.eta['b_discount'] * depth_delta_mean,
                'from_store_oos_share': b_oos * oos_share_delta,
                'note': 'the OOS term uses the partially de-confounded state-space estimate (deliverable 5)'}
