"""
build_v15_dynamics.py — regenerate the SYNTHETIC rows with learnable temporal and cross-platform
structure. REAL rows pass through untouched.

    python -m src.pipeline.build_v15_dynamics            # writes data/raw/*_RAW.parquet
    python -m src.pipeline.build_v15_dynamics --dry-run  # simulate + verify, write nothing

VERSION v15.1 (2026-09-17): v15.0 + calibration against the REAL Blinkit snapshot
  - per-category stock-out hazard scales calibrated to the real per-category stock-out rates
  - price endings drawn from the real Blinkit price-ending distribution (whole rupees everywhere)
  See PARAMS['provenance'] for which parameters are real-calibrated and which are assumptions.

INPUT: the archived pre-v15 raw layer (data/archive/v14_pre_regen/, hash-checked), NOT data/raw/.
  The generator reads panel price levels, promo depth, bestseller flags and offer draws from its
  input, so reading its own previous output would compound (e.g. offers cleared on v15.0 stock-outs
  would stay cleared). Every run is one clean v14 -> v15.x transformation. REAL rows in that archive
  are cell-for-cell identical to the REAL rows in data/raw/ (checked again on every run).

WHY
  scripts/audit_signal.py showed the v10/v14 synthetic panel had no structure for models 2-9 to
  learn: memoryless stock-outs, 91% one-snapshot restocks, no cross-platform price response,
  and delivery ETA that was flat noise around a per-platform mean.

WHAT IS KEPT, EXACTLY
  Every REAL row (all columns). For SYNTHETIC rows: every identifier, time, store, catalog and
  listing column; the 60-snapshot grid; the 2,000-product common panel; row counts and order;
  each panel's price LEVEL (its v14 mean selling price, which carries the per-platform
  positioning); each panel's promo status (mrp_source), promo depth, sponsorship, bestseller
  flag, delivery fee, minimum order value and offer draws.

WHAT IS RE-SIMULATED (SYNTHETIC rows only)
  selling_price, mrp, discount_percent, unit_price, stock_status, in_stock, is_bestseller
  (0 when out of stock), delivery_eta_min, delivery_eta_max, offer fields (cleared when out of
  stock or when a flat/bank/combo offer is worth >= the price), notes, source, price_provenance.

PLANTED STRUCTURE — every value is in PARAMS below and in docs/GENERATOR_v15_PARAMETERS.md.
Recovering these values with a model proves the MODELING PIPELINE works. It is NOT a market
finding, exactly like the Flipkart -6% positioning check proves the join works.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / 'data' / 'raw'
REALIZED = ROOT / 'docs' / 'GENERATOR_v15_realized.json'
INPUT = ROOT / 'data' / 'archive' / 'v14_pre_regen'
PANEL = ['platform', 'store_id', 'product_id']
FILES = {'Blinkit': 'Blinkit', 'Instamart': 'Swiggy Instamart',
         'FlipkartMinutes': 'Flipkart Minutes', 'BigBasket': 'BigBasket'}

SEED = 20260917
SOURCE = 'SIMULATED_GENERATOR_v15.1'
PRICE_PROVENANCE = 'simulated_v15.1_dynamics_around_v14_panel_level_from_blinkit_median_reference_real_calibrated_endings'
NOTES = 'SYNTHETIC ROW - v15.1 dynamics generator (docs/GENERATOR_v15_PARAMETERS.md); not a real observation'

GROUP_OF = {
    'Fruits & Vegetables': 'FAST', 'Dairy, Bread & Eggs': 'FAST',
    'Home & Cleaning': 'SLOW', 'Kitchen & Dining': 'SLOW', 'Electronics & Stationery': 'SLOW',
    'Fashion & Lifestyle': 'SLOW', 'Other / General Merchandise': 'SLOW',
}   # every other category -> 'MEDIUM'.  Used ONLY for restock means (an assumption, not real-derived).

# Real-data calibration targets (docs/GENERATOR_v15_PARAMETERS.md): REAL Blinkit 2026-07-10 stock-out rate per
# category, shrunk toward the overall real rate 6.17% with 200 pseudo-rows. Percent.
REAL_CATEGORY_OOS_TARGET_PCT = {
    'Baby Care': 4.62, 'Bakery & Biscuits': 7.5, 'Beverages': 2.29, 'Dairy, Bread & Eggs': 3.9,
    'Dry Fruits & Nuts': 12.24, 'Electronics & Stationery': 5.43, 'Fashion & Lifestyle': 4.36,
    'Frozen Foods': 4.85, 'Fruits & Vegetables': 9.21, 'Health & Wellness': 4.69, 'Home & Cleaning': 3.22,
    'Instant & Ready to Eat': 7.32, 'Kitchen & Dining': 5.11, 'Masala, Oil & More': 7.18,
    'Other / General Merchandise': 5.38, 'Personal Care': 4.42, 'Pet Supplies': 3.54,
    'Sauces, Spreads & Pickles': 5.64, 'Snacks & Munchies': 13.2, 'Staples & Grains': 11.97,
    'Sweets & Chocolates': 4.63, 'Tea, Coffee & More': 5.76,
}

PARAMS = {
    'burn_in_snapshots': 60,
    # ---- A. stock-out hazard: discrete Weibull, shape > 1 = rises with time in stock ----------
    'hazard': {
        'form': 'h(r) = 1 - exp(-m * ((r/lam)^k - ((r-1)/lam)^k)),  r = consecutive in-stock snapshots so far',
        'shape_k': 2.0,
        # REAL-CALIBRATED (v15.1): chosen so the SIMULATED Blinkit stock-out rate per category matches
        # REAL_CATEGORY_OOS_TARGET_PCT given the restock assumptions below. NOT depletion rates.
        'scale_lam_by_category': {
            'Baby Care': 48.8, 'Bakery & Biscuits': 28.73, 'Beverages': 116.67, 'Dairy, Bread & Eggs': 45.09,
            'Dry Fruits & Nuts': 18.88, 'Electronics & Stationery': 50.24, 'Fashion & Lifestyle': 95.53,
            'Frozen Foods': 46.78, 'Fruits & Vegetables': 16.29, 'Health & Wellness': 41.21,
            'Home & Cleaning': 111.07, 'Instant & Ready to Eat': 37.71, 'Kitchen & Dining': 65.94,
            'Masala, Oil & More': 33.69, 'Other / General Merchandise': 71.54, 'Personal Care': 55.96,
            'Pet Supplies': 83.03, 'Sauces, Spreads & Pickles': 47.73, 'Snacks & Munchies': 15.28,
            'Staples & Grains': 19.98, 'Sweets & Chocolates': 50.54, 'Tea, Coffee & More': 35.62},
        # ASSUMPTION (v14 persona ratios): tuned so platform OOS rates keep the v14 persona ordering relative to
        # Blinkit (BigBasket .055 < Blinkit .060 < Instamart .065 < Flipkart .085). Not real-derived.
        'scale_mult_by_platform': {'Blinkit': 1.0, 'Swiggy Instamart': 0.9943,
                                   'Flipkart Minutes': 1.0637, 'BigBasket': 1.5239},
        'scale_product_frailty_lognormal_sd': 0.25,
        'm_hour': {'9': 0.70, '18': 1.40},
        'm_promo_depth': 'm *= 1 + 1.5 * discount_depth',          # E. promo depletion
        'm_store_demand': 'm *= exp(0.30 * D[store, t])',
        'resets_on_restock': True,
    },
    # ---- B. restock duration: 1 + NegBin(n, mean - 1) snapshots --------------------------------
    'restock': {
        'form': 'D = 1 + NegativeBinomial(n=2, mean=mu - 1)',
        'negbin_n': 2.0,
        'mean_mu_by_group': {'FAST': 1.6, 'MEDIUM': 2.5, 'SLOW': 4.0},
        'mean_mult_by_platform': {'Blinkit': 0.85, 'Swiggy Instamart': 0.90,
                                  'Flipkart Minutes': 1.25, 'BigBasket': 1.15},
    },
    # ---- store-level demand pressure shared by stock and ETA ---------------------------------
    'store_demand': {'form': 'D[s,t] = phi * D[s,t-1] + sqrt(1 - phi^2) * N(0,1)', 'phi': 0.5},
    # ---- C. prices: log deviation x from the panel's own v14 level ---------------------------
    'price': {
        'form_leader': 'x[t] = rho_leader * x[t-1] + N(0, sigma_leader)',
        'form_follower': 'x[t] = rho_follower * x[t-1] + beta * (x_leader[t-lag] - x[t-1]) + N(0, sigma_follower)',
        'price': 'selling_price = round(level * exp(x + wave[platform, t]))',
        'leader': 'Blinkit',
        'rho_leader': 0.60, 'sigma_leader': 0.030,
        'rho_follower': 0.60, 'sigma_follower': 0.020,
        'followers': {'Swiggy Instamart': {'beta': 0.45, 'lag': 1},
                      'Flipkart Minutes': {'beta': 0.30, 'lag': 1},
                      'BigBasket':        {'beta': 0.35, 'lag': 2}},
        'no_leader_listing': 'beta = 0 when the product is not carried by Blinkit',
        'platform_wave_sd': 0.005,
        'rounding': 'empirical endings: whole rupees; one pricing style per panel drawn from the REAL '
                    "Blinkit style shares of its price band; price snapped to that style's grid",
        # REAL-CALIBRATED (v15.1): shares of REAL Blinkit 2026-07-10 selling prices by ending style and band
        'ending_style_probs_by_band': {
            '<20':     {'x9': 0.3046, 'x0': 0.1126, 'x5': 0.1589, 'rupee': 0.4238},
            '20-99':   {'x9': 0.1284, 'x0': 0.3147, 'x5': 0.1868, 'rupee': 0.3701},
            '100-499': {'x99': 0.1208, 'x9': 0.1672, 'x0': 0.319, 'x5': 0.1731, 'rupee': 0.2199},
            '500+':    {'x49_x99': 0.521, 'x50_x00': 0.1303, 'x9': 0.0367, 'x0': 0.0977, 'x5': 0.0865,
                        'rupee': 0.1278}},
        'style_grid': {'x9': [10, 9], 'x0': [10, 0], 'x5': [10, 5], 'x99': [100, 99], 'x49_x99': [50, 49],
                       'x50_x00': [50, 0], 'rupee': [1, 0]},   # [step, remainder]
        'style_assignment': 'drawn once per panel from the band of its v14 price level; fixed over time '
                            '(assumption: one real snapshot cannot show whether a product keeps its ending style)',
        # Measured on the generated data with the audit regression (log deviation, documented lag).
        # Coarse price grids attenuate the measured coefficient: see docs/GENERATOR_v15_PARAMETERS.md.
        'expected_measured_beta': {'Swiggy Instamart': 0.220, 'Flipkart Minutes': 0.154, 'BigBasket': 0.181},
        'level': "panel mean of v14 selling_price (keeps each platform's positioning)",
        'mrp': 'promo panels: mrp = ceil_to_rupee(price / (1 - depth * U(0.75, 1.15))), depth clipped to '
               '[0.02, 0.60], at least price + 1; else mrp = price (MRP endings are not calibrated)',
    },
    # ---- D. delivery ETA ----------------------------------------------------------------------
    'eta': {
        'form': 'eta_min = round(base[platform] + store_eff[store] + peak*[hour==18] + b_demand*D[s,t] '
                '+ b_discount*discount_depth + b_store_oos*(store OOS share - platform mean) + N(0, noise_sd)), >= 5',
        'base_by_platform': {'Blinkit': 9.5, 'Swiggy Instamart': 9.5, 'Flipkart Minutes': 11.5, 'BigBasket': 13.5},
        'store_effect_sd': 1.5,
        'peak_18h_minutes': 3.5,
        'b_demand': 1.6,
        'b_discount': 4.0,
        'b_store_oos': 8.0,
        'noise_sd': 1.0,
        'eta_max': 'eta_min + U{4..10}',
    },
    # ---- which parameters come from real data and which are assumptions --------------------------
    'provenance': {
        'REAL_CALIBRATED': {
            'hazard.scale_lam_by_category': 'REAL Blinkit per-category stock-out rate, 2026-07-10 (shrunk targets)',
            'price.ending_style_probs_by_band': 'REAL Blinkit selling-price endings, 2026-07-10',
        },
        'ASSUMPTION_NOT_REAL_DERIVED': {
            'hazard.shape_k': 'k = 2 depletion shape (v15.0 design choice)',
            'hazard.scale_mult_by_platform': 'v14 persona stock-out ratios between platforms',
            'hazard.m_hour': 'time-of-day multipliers (real clock time was never recorded)',
            'hazard.scale_product_frailty_lognormal_sd': 'v15.0 design choice',
            'hazard.m_promo_depth, hazard.m_store_demand': 'v15.0 design choice',
            'restock.*': 'group means FAST/MEDIUM/SLOW and platform multipliers (v15.0 assumptions)',
            'store_demand.*': 'v15.0 design choice',
            'price.* except ending_style_probs_by_band': 'leader/follower, rho, sigma, wave, style persistence',
            'eta.*': 'v15.0 design choice; platform base means from v14 personas',
        },
    },
}


def _band(p):
    p = np.asarray(p, float)
    return np.select([p < 20, p < 100, p < 500], ['<20', '20-99', '100-499'], '500+')


def draw_ending_styles(level, rng):
    """One pricing style per panel, drawn from the REAL style shares of the band of its price level."""
    probs = PARAMS['price']['ending_style_probs_by_band']
    band = _band(level)
    style = np.empty(len(level), dtype=object)
    for lab, pr in probs.items():
        m = band == lab
        keys = list(pr)
        w = np.array([pr[k] for k in keys], float)
        style[m] = rng.choice(keys, size=int(m.sum()), p=w / w.sum())
    return style


def _round_price(P, style):
    """Snap each panel's prices (rows of P) to its style grid; whole rupees, at least Rs 1."""
    grid = PARAMS['price']['style_grid']
    step = np.array([grid[s][0] for s in style], float)[:, None]
    rem = np.array([grid[s][1] for s in style], float)[:, None]
    P = np.asarray(P, float)
    out = np.round((P - rem) / step) * step + rem
    return np.where(out < 1, np.maximum(np.round(P), 1), out)


def _ceil_price(p):
    return np.ceil(p)


def simulate(syn: pd.DataFrame, rng: np.random.Generator):
    """syn: all SYNTHETIC rows, all platforms. Returns (new column frame aligned to syn.index, realized)."""
    P = PARAMS
    syn = syn.sort_values(PANEL + ['observed_at'])
    keys = syn[PANEL].drop_duplicates()
    n_pan = len(keys)
    T = syn.groupby(PANEL, sort=False).size().unique()
    assert len(T) == 1, "every synthetic panel must have the same number of snapshots"
    T = int(T[0])
    B = P['burn_in_snapshots']
    TT = B + T

    first = syn.groupby(PANEL, sort=False).head(1).reset_index(drop=True)
    plat = first.platform.to_numpy()
    grp = first.category.map(GROUP_OF).fillna('MEDIUM').to_numpy()
    cat = first.category.to_numpy()
    unknown = set(cat) - set(P['hazard']['scale_lam_by_category'])
    assert not unknown, f"no calibrated hazard scale for categories {unknown}"
    canon = first.canonical_product_key.to_numpy()
    store = first.store_id.to_numpy()
    level = syn.groupby(PANEL, sort=False).selling_price.mean().to_numpy()
    promo = first.mrp_source.eq('simulated_discounted').to_numpy()
    disc_mean = syn[syn.discount_percent > 0].groupby(PANEL, sort=False).discount_percent.mean()
    depth = first.set_index(PANEL).index.map(disc_mean).to_numpy(dtype=float)
    depth = np.where(promo, np.nan_to_num(depth, nan=15.0) / 100.0, 0.0)
    hours_real = syn.hour.to_numpy().reshape(n_pan, T)[0]
    hours = np.r_[np.resize(hours_real[::-1], B)[::-1], hours_real]   # burn-in keeps the 9/18 rhythm

    # ---- store demand pressure
    stores = np.unique(store)
    s_idx = pd.Index(stores).get_indexer(store)
    phi = P['store_demand']['phi']
    D = np.zeros((len(stores), TT))
    for t in range(1, TT):
        D[:, t] = phi * D[:, t - 1] + np.sqrt(1 - phi ** 2) * rng.standard_normal(len(stores))

    # ---- A/B/E. stock
    H, R = P['hazard'], P['restock']
    lam = (np.vectorize(H['scale_lam_by_category'].get)(cat) * np.vectorize(H['scale_mult_by_platform'].get)(plat)
           * rng.lognormal(0, H['scale_product_frailty_lognormal_sd'], n_pan))
    mu = np.vectorize(R['mean_mu_by_group'].get)(grp) * np.vectorize(R['mean_mult_by_platform'].get)(plat)
    k = H['shape_k']
    dep_t = np.clip(depth[:, None] * rng.uniform(0.75, 1.15, (n_pan, TT)), 0.02, 0.60) * promo[:, None]
    instock = np.ones((n_pan, TT), dtype=np.int64)
    run = np.ones(n_pan)
    remaining = np.zeros(n_pan, dtype=np.int64)
    for t in range(1, TT):
        was_in = instock[:, t - 1] == 1
        m = (np.where(hours[t] == 18, H['m_hour']['18'], H['m_hour']['9'])
             * (1 + 1.5 * dep_t[:, t]) * np.exp(0.30 * D[s_idx, t]))
        inc = (run / lam) ** k - ((run - 1) / lam) ** k
        goes_out = was_in & (rng.random(n_pan) < 1 - np.exp(-m * inc))
        # restock countdown for items already out
        remaining = np.where(~was_in, remaining - 1, remaining)
        back = ~was_in & (remaining <= 0)
        dur = 1 + rng.negative_binomial(R['negbin_n'], R['negbin_n'] / (R['negbin_n'] + (mu - 1)))
        remaining = np.where(goes_out, dur, remaining)     # spell occupies snapshots t .. t+dur-1
        now_in = np.where(was_in, ~goes_out, back)
        instock[:, t] = now_in.astype(np.int64)
        run = np.where(now_in & was_in, run + 1, np.where(now_in, 1, run))
    # ---- C. prices
    Pr = P['price']
    leader = plat == Pr['leader']
    lead_row = pd.Series(np.flatnonzero(leader), index=canon[leader])
    lead_of = lead_row.reindex(canon).to_numpy()
    has_lead = ~np.isnan(lead_of)
    lead_of = np.nan_to_num(lead_of, nan=0).astype(int)
    beta = np.zeros(n_pan); lag = np.ones(n_pan, dtype=int)
    for p, cfg in Pr['followers'].items():
        sel = (plat == p) & has_lead
        beta[sel] = cfg['beta']; lag[plat == p] = cfg['lag']
    x = np.zeros((n_pan, TT))
    for t in range(1, TT):
        xl = x[lead_of, np.maximum(t - lag, 0)]
        fol = Pr['rho_follower'] * x[:, t - 1] + beta * (xl - x[:, t - 1]) \
            + rng.normal(0, Pr['sigma_follower'], n_pan)
        led = Pr['rho_leader'] * x[:, t - 1] + rng.normal(0, Pr['sigma_leader'], n_pan)
        x[:, t] = np.where(leader, led, fol)
    plats = np.unique(plat)
    wave = pd.DataFrame(rng.normal(0, Pr['platform_wave_sd'], (len(plats), TT)), index=plats)
    w = wave.loc[plat].to_numpy()

    sl = slice(B, TT)
    style = draw_ending_styles(level, rng)
    price = _round_price(level[:, None] * np.exp(x[:, sl] + w[:, sl]), style)
    dep = dep_t[:, sl]
    mrp = np.where(promo[:, None], np.maximum(_ceil_price(price / (1 - dep)), price + 1.0), price)
    disc = np.round((mrp - price) / mrp * 100, 2)
    ins = instock[:, sl]

    # ---- D. ETA
    E = P['eta']
    store_eff = pd.Series(rng.normal(0, E['store_effect_sd'], len(stores)), index=stores)
    oos_share = pd.DataFrame(1 - ins).groupby(s_idx).transform('mean').to_numpy()
    plat_mean_oos = pd.DataFrame(oos_share).groupby(plat).transform('mean').to_numpy()
    eta = (np.vectorize(E['base_by_platform'].get)(plat)[:, None] + store_eff.loc[store].to_numpy()[:, None]
           + E['peak_18h_minutes'] * (hours[sl] == 18)[None, :] + E['b_demand'] * D[s_idx][:, sl]
           + E['b_discount'] * dep + E['b_store_oos'] * (oos_share - plat_mean_oos)
           + rng.normal(0, E['noise_sd'], (n_pan, T)))
    eta_min = np.maximum(np.round(eta), 5).astype(np.int64)
    eta_max = eta_min + rng.integers(4, 11, (n_pan, T))

    out = pd.DataFrame({
        'selling_price': price.ravel(), 'mrp': mrp.ravel(), 'discount_percent': disc.ravel(),
        'in_stock': ins.ravel(), 'delivery_eta_min': eta_min.ravel(), 'delivery_eta_max': eta_max.ravel(),
    }, index=syn.index)
    realized = {
        'seed': SEED,
        'store_effect_minutes': store_eff.round(3).to_dict(),
        'panels': int(n_pan), 'snapshots': T,
        'panels_by_restock_group': pd.Series(grp).value_counts().to_dict(),
        'panels_by_ending_style': pd.Series(style).value_counts().to_dict(),
        'followers_without_leader_listing': int(((plat != Pr['leader']) & ~has_lead).sum()),
    }
    return out, realized


def build(dry_run=False):
    rng = np.random.default_rng(SEED)
    check_input_hashes()
    files = {f: pd.read_parquet(INPUT / f'{f}_RAW.parquet') for f in FILES}
    for f in FILES:
        cur = pd.read_parquet(RAW / f'{f}_RAW.parquet')
        r_in, r_cur = files[f].data_status.eq('REAL'), cur.data_status.eq('REAL')
        assert files[f][r_in].reset_index(drop=True).equals(cur[r_cur].reset_index(drop=True)), \
            f"{f}: REAL rows in the archived input differ from data/raw - refusing to run"
    before = {f: d.copy() for f, d in files.items()}
    allp = pd.concat([d.assign(_file=f, _row=np.arange(len(d))) for f, d in files.items()], ignore_index=True)
    syn_mask = allp.data_status.eq('SYNTHETIC')
    syn = allp[syn_mask]

    # ---- pre-checks: panel overlap FIRST
    cp = syn[syn.in_common_panel == 1]
    sets = [set(g.canonical_product_key) for _, g in cp.groupby('platform')]
    overlap_before = len(set.intersection(*sets))
    snaps = cp.groupby(['platform', 'canonical_product_key']).snapshot_id.nunique()
    print(f"common panel before: {overlap_before:,} products on all 4 platforms; "
          f"snapshots per (platform, product): {sorted(snaps.unique())}")
    assert overlap_before == 2000 and set(snaps.unique()) == {60}

    new, realized = simulate(syn, rng)
    a = allp.loc[syn.index].copy()
    for c in ['selling_price', 'mrp', 'discount_percent', 'in_stock', 'delivery_eta_min', 'delivery_eta_max']:
        a[c] = new[c]
    a['unit_price'] = np.round(a.selling_price / a.pack_qty.where(a.pack_qty > 0, 1), 4)
    a['stock_status'] = np.where(a.in_stock == 1, 'Available', 'Out of Stock')
    panel_bs = allp.loc[syn.index].groupby(PANEL).is_bestseller.transform('max')
    a['is_bestseller'] = np.where(a.in_stock == 1, panel_bs, 0)
    bad_offer = a.offer_type.isin(['FLAT_OFF', 'BANK_OFFER', 'COMBO_DEAL']) & (a.offer_value >= a.selling_price)
    clear = (a.in_stock == 0) | bad_offer
    a.loc[clear, 'offer_type'] = 'NO_OFFER'
    a.loc[clear, ['offer_value']] = 0.0
    a.loc[clear, ['coupon_required', 'buy_quantity', 'get_quantity']] = 0
    a['notes'] = NOTES
    a['source'] = SOURCE
    a['price_provenance'] = PRICE_PROVENANCE
    allp.loc[syn.index, a.columns] = a
    realized['offers_cleared_out_of_stock'] = int((a.in_stock == 0).sum())
    realized['offers_cleared_value_ge_price'] = int((bad_offer & (a.in_stock == 1)).sum())

    # ---- rebuild per-file frames in original row order and dtypes, then verify
    out = {}
    for f, orig in before.items():
        d = allp[allp._file == f].sort_values('_row').drop(columns=['_file', '_row']).reset_index(drop=True)
        d = d[orig.columns]
        for c in orig.columns:
            d[c] = d[c].astype(orig[c].dtype)
        out[f] = d
        verify_file(f, orig, d)

    sets = [set(d[(d.data_status == 'SYNTHETIC') & (d.in_common_panel == 1)].canonical_product_key)
            for d in out.values()]
    overlap_after = len(set.intersection(*sets))
    print(f"common panel after: {overlap_after:,}")
    assert overlap_after == overlap_before

    realized['common_panel_before'] = overlap_before
    realized['common_panel_after'] = overlap_after
    if dry_run:
        print("dry run - nothing written")
        return out, realized
    for f, d in out.items():
        d.to_parquet(RAW / f'{f}_RAW.parquet', compression='zstd', index=False)
    REALIZED.write_text(json.dumps({'params': PARAMS, 'realized': realized}, indent=2, default=str),
                        encoding='utf-8')
    print(f"wrote 4 parquet files and {REALIZED.relative_to(ROOT)}")
    return out, realized


def check_input_hashes():
    import hashlib
    want = {}
    for line in (INPUT / 'SHA256SUMS.txt').read_text().splitlines():
        h, name = line.split(maxsplit=1)
        want[name.lstrip('*').strip()] = h
    for f in FILES:
        name = f'{f}_RAW.parquet'
        got = hashlib.sha256((INPUT / name).read_bytes()).hexdigest()
        assert got == want[name], f"archived input {name} does not match SHA256SUMS.txt"


def verify_file(name, orig, new):
    assert list(new.columns) == list(orig.columns), f"{name}: columns changed"
    assert len(new) == len(orig), f"{name}: row count changed"
    assert new.observation_key.is_unique and new.observation_key.equals(orig.observation_key), f"{name}: keys"
    for c in orig.columns:
        assert new[c].dtype == orig[c].dtype, f"{name}: dtype {c}"
    real = orig.data_status.eq('REAL')
    assert new.data_status.equals(orig.data_status) and new.is_real_observation.equals(orig.is_real_observation)
    if real.any():
        assert new[real].equals(orig[real]), f"{name}: REAL rows changed"
    fixed = ['observation_key', 'snapshot_id', 'observed_at', 'snapshot_date', 'snapshot_time', 'hour',
             'day_of_week', 'platform', 'store_id', 'store_name', 'area', 'pincode', 'city', 'product_id',
             'canonical_product_key', 'listing_seq', 'listing_class', 'is_preferred_listing', 'product_name',
             'brand', 'category', 'subcategory', 'pack_size', 'pack_qty', 'pack_unit', 'mrp_source',
             'is_sponsored', 'delivery_fee', 'minimum_order_value', 'enrichment_provenance', 'data_status',
             'is_real_observation', 'in_common_panel', 'store_id_source']
    for c in fixed:
        assert new[c].equals(orig[c]), f"{name}: kept column {c} changed"
    s = new[~real]
    assert (s.selling_price > 0).all() and (s.mrp >= s.selling_price).all()
    assert s.in_stock.eq(s.stock_status.eq('Available').astype(int)).all()
    assert (s.delivery_eta_min <= s.delivery_eta_max).all()
    assert s.source.eq(SOURCE).all() and s.data_status.eq('SYNTHETIC').all()
    print(f"  {name:<16} verified: {len(new):,} rows, REAL {int(real.sum()):,} identical, schema identical")


if __name__ == '__main__':
    build(dry_run='--dry-run' in sys.argv)
