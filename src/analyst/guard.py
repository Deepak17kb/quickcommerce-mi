"""
guard.py — the analyst's two non-negotiable checks, applied to BOTH modes (offline and Claude).

1. REFUSAL POLICY (before any retrieval)
   The data is supply-side only: no customers, orders, quantities, revenue (CLAUDE.md s.4). Questions that need them
   are refused with the reason and the honest substitute. So are claims the settled findings forbid, such as "which
   category sells out fastest" (one snapshot cannot separate depletion from restocking).

2. CLAIM VERIFIER (after the answer is written)
   Every claim must carry a provenance label, a source file and a date. The verifier then checks:
     label    a claim citing a SYNTHETIC source cannot be labelled REAL; if it is, it is relabelled and flagged
     numbers  every number in a claim must appear in the evidence the answer actually retrieved (tool outputs),
              to the precision it is written with; otherwise the claim is flagged unverified
     source   the cited file must exist in the knowledge base or be the REAL snapshot
     external a claim citing docs/external is EXTERNAL whatever it was labelled, must carry the source URL, and a claim
              labelled EXTERNAL must cite docs/external
   A SYNTHETIC banner is added whenever any claim is SYNTHETIC, whether or not the question asked; an EXTERNAL banner
   whenever any claim is EXTERNAL.
"""
import re

REFUSALS = [
    (r'\b(demand|sales|units? sold|sales? volume|sell[- ]through|how (many|much) .*\b(sold|sell|bought|ordered)\b)',
     'demand / sales volume',
     'There are no orders or quantities in this data. The honest substitute is time-until-stock-out '
     '(deliverable 7), which is itself SYNTHETIC.'),
    # GOV / NOV (gross / net order value) is how company sources state sales; "Nov 2025" and "gov.in" are not it
    (r'\b(revenue|gmv|aov|average order value|gross order value|net order value|turnover|profit|margin|earn(s|ings)?)\b'
     r'|\bgov\b(?!\.)|\bnov\b(?!\s*\d)',
     'revenue / GMV / profit',
     'No order, basket or cost data exists, so revenue, GMV, AOV and profit cannot be computed. SIMULATE and OPTIMIZE '
     'answer positioning questions (price rank, cheapest-of-4 share, availability, ETA) instead.'),
    (r'\b(elastic(ity)?|price sensitiv)',
     'price elasticity',
     'Elasticity needs demand, which is absent. The substitute is competitive price-response (deliverable 9, '
     'SYNTHETIC): how platforms respond to each other\'s prices.'),
    (r'\b(customers?|shoppers?|buyers?|users?|conversions?|basket)\b.*\b(buy|order|prefer|want|convert|spend|many)\b|'
     r'\b(how many|number of) (customers|orders|users|buyers)\b',
     'customer behaviour',
     'There are no customers or orders in the data. The substitute for recommendation is the assortment-gap model '
     '(deliverable 10, REAL): products similar real stores list.'),
    (r'\b(best[- ]?sell(er|ing)|most popular|sells? (the )?most|top[- ]selling)\b',
     'best sellers',
     'Sales are not observed. The only popularity signal is the platform\'s own is_bestseller badge, which is a '
     'display flag, not a sales count.'),
    (r'\bmarket share\b',
     'market share',
     'Market share needs sales across platforms; none are observed. Cheapest-of-4 share (a price-position measure) '
     'is available, and on the four-platform panel it is SYNTHETIC.'),
    (r'\bsells? out (the )?(faster|fastest|quick)|\bfastest[- ]selling\b|\bdeplet(es|ion) (faster|fastest|rate)',
     'depletion speed by category',
     'One real snapshot gives stock-out prevalence, which mixes how fast items run out with how slowly they come back. '
     'The generator\'s category hazard scales were calibrated to that prevalence, so they are not depletion rates '
     '(CLAUDE.md s.2). The REAL out-of-stock share by category can be reported; "sells out faster" cannot.'),
]

EXTERNAL_BANNER = ('EXTERNAL: part of this answer comes from cited public web sources (news reports, a store map), not '
                   'from the project\'s data, and was not checked against it. Each claim carries its URL.')
SYNTHETIC_BANNER = ('SYNTHETIC-DERIVED: part of this answer comes from generated data. It shows what the modelling '
                    'pipeline recovers from the v15.1 generator, not how the real market behaves.')


# the project's own latent "store demand pressure" (deliverables 5, 7, 11) is a supply-side construct, not demand
_LATENT_DEMAND = re.compile(r'(latent|store|b_)\s*demand|demand[\s_-]*(pressure|surge|index|term|effect|shock|proxy)')


def refusal(question: str):
    q = question.lower()
    if _LATENT_DEMAND.search(q):
        q = _LATENT_DEMAND.sub(' latent-pressure ', q)
    for pat, topic, why in REFUSALS:
        if re.search(pat, q):
            return {'topic': topic, 'reason': why}
    return None


_NUM = re.compile(r'(?<![\w.])[-+]?\d[\d,]*\.?\d*')


def numbers_in(text: str) -> list[str]:
    out = []
    for m in _NUM.finditer(text):
        s = m.group(0).rstrip('.').replace(',', '')
        if not s or s in ('-', '+'):
            continue
        # years, dates and deliverable / section numbers are identifiers, not measured values
        if re.fullmatch(r'20\d\d', s) or re.fullmatch(r'\d', s):
            continue
        out.append(s)
    return out


def _in_evidence(num: str, evidence: str, ev_numbers: set[float]) -> bool:
    if num in evidence:
        return True
    try:
        v = float(num)
    except ValueError:
        return False
    decimals = len(num.split('.')[1]) if '.' in num else 0
    tol = 0.5 * 10 ** (-decimals)
    for e in ev_numbers:
        # match as written (rounded) or as a percentage of a fraction in the evidence
        if abs(e - v) <= tol + 1e-9 or abs(100 * e - v) <= tol + 1e-9:
            return True
    return False


def verify(claims: list[dict], evidence_text: str, kb) -> list[dict]:
    ev_numbers = set()
    for s in numbers_in(evidence_text):
        try:
            ev_numbers.add(float(s))
        except ValueError:
            pass
    out = []
    for c in claims:
        c = dict(c)
        issues = []
        label = c.get('provenance')
        src = c.get('source_file', '')
        # the project's own code states methods and assumptions: a METHOD source, never a market fact
        src_prov = ('REAL' if src.startswith('data/raw') else 'METHOD' if src.startswith('src/') and (kb.root / src).exists()
                    else kb.provenance_of_file(src))
        if src_prov is None:
            issues.append(f'cited source {src!r} is not in the knowledge base')
        if label not in ('REAL', 'SYNTHETIC', 'METHOD', 'EXTERNAL'):
            issues.append('missing provenance label; set to SYNTHETIC (conservative)')
            c['provenance'] = 'SYNTHETIC'
        elif src_prov == 'EXTERNAL' and label != 'EXTERNAL':
            issues.append(f'labelled {label} but the source is an EXTERNAL web source; relabelled EXTERNAL')
            c['provenance'] = 'EXTERNAL'
        elif label == 'EXTERNAL' and src_prov != 'EXTERNAL':
            issues.append('labelled EXTERNAL but the cited file is not an external source; relabelled from the source')
            c['provenance'] = src_prov if src_prov in ('REAL', 'SYNTHETIC', 'METHOD') else 'SYNTHETIC'
        elif src_prov == 'METHOD' and label == 'REAL':
            issues.append('labelled REAL but the source is project code; relabelled METHOD')
            c['provenance'] = 'METHOD'
        elif src_prov == 'SYNTHETIC' and label != 'SYNTHETIC':
            issues.append(f'labelled {label} but the source is SYNTHETIC-derived; relabelled SYNTHETIC')
            c['provenance'] = 'SYNTHETIC'
        if c['provenance'] == 'EXTERNAL' and 'http' not in (c.get('source_detail', '') + ' ' + c.get('text', '')):
            issues.append('EXTERNAL claim without its source URL')
        missing = [n for n in numbers_in(c.get('text', '')) if not _in_evidence(n, evidence_text, ev_numbers)]
        if missing:
            issues.append(f'numbers not found in the retrieved evidence: {missing}')
        if not c.get('date'):
            c['date'] = '2026-07-10' if src.startswith('data/raw') else kb.date_of_file(src)
        c['verified'] = not issues
        c['issues'] = issues
        out.append(c)
    return out
