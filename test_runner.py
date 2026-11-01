"""STLab02 - CSV/Excel data-driven test runner for EduCommerce.

Flow: read test cases -> validate schema/input -> fresh fixture per case -> dispatch to
the business function -> observe return value AND state -> compare with expected_json
-> PASS / FAIL / BLOCKED -> export CSV, Excel, HTML dashboard.

Status rules
  PASS     every key in expected_json equals the observed value
  FAIL     at least one key differs (including an unexpected exception from the app)
  BLOCKED  the case could not be executed: bad schema/JSON, unknown fixture/action,
           error while preparing preconditions. BLOCKED rows are counted, never skipped.
"""
from pathlib import Path
import argparse, base64, datetime, html, io, json, time, traceback
import pandas as pd
from ecommerce_app import Checkout, Customer, Cart, CartLine, D

ROOT = Path(__file__).resolve().parent
REQUIRED_COLUMNS = ['test_case_id', 'requirement_id', 'condition_id', 'scenario_id', 'title',
                    'priority', 'precondition', 'fixture_key', 'input_json', 'expected_type',
                    'expected_json', 'execution_status', 'actual_result', 'error_message',
                    'evidence_reference']
EXPECTED_TYPES = {'RETURN', 'EXCEPTION'}


class BlockedError(Exception):
    """Raised when a case cannot be executed because of test data / setup problems."""


# ---------------------------------------------------------------- fixture
# Each fixture key builds a NEW Checkout (own Catalog, Payments, orders), a NEW Customer
# and a NEW Cart. Nothing is shared between test cases -> test isolation.
FIXTURES = {
    'empty':   {'lines': []},                                         # empty cart
    '300k':    {'lines': [('B', 1)]},                                 # 300.000
    '499999':  {'lines': [('A', 1), ('B', 1)], 'price': {'B': 299999}},  # just below 500k
    '500k':    {'lines': [('A', 1), ('B', 1)]},                       # exactly 500.000
    '500001':  {'lines': [('A', 1), ('B', 1)], 'price': {'B': 300001}},  # just above 500k
    '600k':    {'lines': [('A', 3)]},                                 # 600.000
    '1500k':   {'lines': [('B', 5)]},                                 # 1.500.000
    'A2_B1':   {'lines': [('A', 2), ('B', 1)]},                       # 2 SKUs, enough stock
    'A2_B100': {'lines': [('A', 2), ('B', 100)]},                     # B stock 15 < 100
    'B100_A2': {'lines': [('B', 100), ('A', 2)]},                     # same, short SKU first
    'A20':     {'lines': [('A', 20)]},                                # == stock of A
    'A21':     {'lines': [('A', 21)]},                                # stock of A + 1
}


def fixture(key, authenticated=True, used_codes=()):
    if key not in FIXTURES:
        raise BlockedError(f'UNKNOWN_FIXTURE:{key}')
    spec = FIXTURES[key]
    service = Checkout()
    customer = Customer('U_NEW', authenticated=authenticated, used_codes=set(used_codes))
    cart = Cart(service.catalog)
    for sku, price in spec.get('price', {}).items():
        service.catalog.products[sku].price = D(price)
    for sku, qty in spec['lines']:
        # Cart lines bypass Cart.add() so a fixture never depends on the code under test.
        cart.lines.append(CartLine(sku, qty))
    return service, customer, cart


# ---------------------------------------------------------------- observation helpers
def stock_of(app):
    return {k: p.stock for k, p in app.catalog.products.items()}


def snapshot(app, customer, cart, before, order=None):
    after = stock_of(app)
    delta = {k: after[k] - before[k] for k in after if after[k] != before[k]}
    obs = {
        'orders': len(app.orders),
        'charges': len(app.payments.charges),
        'charge_amount': int(sum(c['amount'] for c in app.payments.charges)),
        'stock_delta': delta,
        'used_codes': sorted(customer.used_codes),
        'cart_lines': [[x.sku, x.quantity] for x in cart.lines],
        'subtotal': int(cart.subtotal()) if all(isinstance(x.quantity, int) for x in cart.lines) else None,
    }
    if order is not None:
        obs.update({'order_id': order.order_id, 'status': order.status, 'discount': int(order.discount),
                    'shipping': int(order.shipping), 'total': int(order.total),
                    'customer_id': order.customer_id})
    return obs


# ---------------------------------------------------------------- dispatcher
def act_cart_add(app, customer, cart, inp):
    """REQ-02: call Cart.add() for each [sku, qty] in order. Stops at first exception."""
    for sku, qty in inp['adds']:
        cart.add(sku, qty)
    return None


def act_place(app, customer, cart, inp, key):
    """Call Checkout.place() once with the arguments from input_json."""
    return app.place(customer, cart, area=inp.get('area', 'inner'), voucher=inp.get('voucher'),
                     method=inp.get('method', 'COD'), approved=inp.get('approved', True), key=key)


def act_place_sequence(app, customer, cart, inp, key):
    """Several place() attempts on the SAME fixture (e.g. declined then approved).
    Only the last attempt's exception is reported; earlier expected failures are recorded."""
    order, notes = None, []
    for i, attempt in enumerate(inp['attempts'], 1):
        try:
            order = act_place(app, customer, cart, attempt, f'{key}-{i}')
            notes.append(f'#{i}:{order.status}')
        except ValueError as exc:
            notes.append(f'#{i}:ERROR:{exc}')
    return order, notes


def execute_case(row):
    """Run one CSV row. Returns the row enriched with execution_status/actual_result/..."""
    started = time.perf_counter()
    case_id = row.get('test_case_id', '')
    result = {'execution_status': 'BLOCKED', 'actual_result': '', 'error_message': '',
              'observed_json': '', 'stock_before': '', 'stock_after': ''}
    try:
        # ---- 1. setup (problems here => BLOCKED, never FAIL)
        try:
            inp = json.loads(row['input_json'] or '{}')
            expected = json.loads(row['expected_json'])
        except json.JSONDecodeError as exc:
            raise BlockedError(f'INVALID_JSON:{exc.msg}')
        etype = row['expected_type'].strip().upper()
        if etype not in EXPECTED_TYPES:
            raise BlockedError(f'UNKNOWN_EXPECTED_TYPE:{etype}')
        action = inp.get('action')
        if action not in ('cart_add', 'place', 'place_sequence'):
            raise BlockedError(f'UNKNOWN_TEST_ACTION:{action}')
        app, customer, cart = fixture(row['fixture_key'], inp.get('authenticated', True),
                                      inp.get('pre_used_codes', []))
        before = stock_of(app)

        # ---- 2. execute the function under test
        order, error, notes = None, '', []
        try:
            if action == 'cart_add':
                act_cart_add(app, customer, cart, inp)
            elif action == 'place':
                order = act_place(app, customer, cart, inp, case_id)
            else:
                order, notes = act_place_sequence(app, customer, cart, inp, case_id)
        except ValueError as exc:            # business rule rejection raised by the app
            error = str(exc)
        except Exception as exc:              # crash inside the app = unexpected => FAIL
            error = f'UNEXPECTED:{type(exc).__name__}:{exc}'

        # ---- 3. observe return value + state, then compare
        obs = snapshot(app, customer, cart, before, order)
        obs['error'] = error
        if notes:
            obs['attempts'] = notes
        if etype == 'RETURN' and 'error' not in expected:
            expected = {**expected, 'error': ''}      # a RETURN case must not raise
        mismatches = {k: {'expected': v, 'actual': obs.get(k, '<missing>')}
                      for k, v in expected.items() if obs.get(k, '<missing>') != v}
        result.update({
            'execution_status': 'PASS' if not mismatches else 'FAIL',
            'actual_result': json.dumps({k: obs.get(k, '<missing>') for k in expected}, ensure_ascii=False),
            'error_message': error if not mismatches else json.dumps(mismatches, ensure_ascii=False),
            'observed_json': json.dumps(obs, ensure_ascii=False, default=str),
            'stock_before': json.dumps(before), 'stock_after': json.dumps(stock_of(app)),
        })
    except BlockedError as exc:
        result['error_message'] = str(exc)
    except Exception as exc:                  # bug in the test harness itself
        result['error_message'] = f'HARNESS_ERROR:{type(exc).__name__}:{exc}'
        result['traceback'] = traceback.format_exc(limit=3)
    result['duration_ms'] = round((time.perf_counter() - started) * 1000, 3)
    result['executed_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    return {**row, **result}


# ---------------------------------------------------------------- reader + validation
def read_cases(path):
    path = Path(path)
    if path.suffix.lower() in ('.xlsx', '.xls'):
        df = pd.read_excel(path, dtype=str)
    else:
        df = pd.read_csv(path, dtype=str, encoding='utf-8-sig', keep_default_na=False)
    df = df.fillna('')
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f'MISSING_COLUMNS:{missing}')
    dup = df.test_case_id[df.test_case_id.duplicated()].tolist()
    if dup:
        raise ValueError(f'DUPLICATE_TEST_IDS:{dup}')
    return df.to_dict('records')


# ---------------------------------------------------------------- reporting
def _chart_png(df):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    pivot = (df.groupby(['requirement_id', 'execution_status']).size().unstack(fill_value=0)
               .reindex(columns=['PASS', 'FAIL', 'BLOCKED'], fill_value=0))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4), gridspec_kw={'width_ratios': [1, 2.2]})
    colors = {'PASS': '#16a34a', 'FAIL': '#dc2626', 'BLOCKED': '#f59e0b'}
    tot = pivot.sum()
    bars = ax1.bar(tot.index, tot.values, color=[colors[s] for s in tot.index])
    ax1.bar_label(bars, padding=3); ax1.set_title('Overall status'); ax1.set_ylim(0, max(tot) * 1.2 + 1)
    bottom = None
    for s in ['PASS', 'FAIL', 'BLOCKED']:
        b = ax2.bar(pivot.index, pivot[s], bottom=bottom, color=colors[s], label=s)
        ax2.bar_label(b, labels=[str(v) if v else '' for v in pivot[s]], label_type='center', color='white')
        bottom = pivot[s] if bottom is None else bottom + pivot[s]
    ax2.set_title('Status by requirement'); ax2.set_ylim(0, pivot.sum(axis=1).max() + 2); ax2.legend(loc='upper right', ncol=3)
    for ax in (ax1, ax2):
        ax.spines[['top', 'right']].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format='png', dpi=130); plt.close(fig)
    return buf.getvalue()


def build_traceability(df):
    cols = ['requirement_id', 'condition_id', 'scenario_id', 'test_case_id', 'execution_status']
    return df[cols].rename(columns={'execution_status': 'run_status'}).sort_values(cols[:4])


def run_suite(cases_path=None, out_dir=None, selected_reqs=None):
    cases_path = Path(cases_path or ROOT / 'test_cases.csv')
    output = Path(out_dir or ROOT / 'reports'); output.mkdir(parents=True, exist_ok=True)
    run_id = datetime.datetime.now().strftime('RUN-%Y%m%d-%H%M%S')
    cases = read_cases(cases_path)
    results = [execute_case(row) for row in cases]
    df = pd.DataFrame(results); df.insert(0, 'run_id', run_id)

    # data completeness: rows read == rows reported (BLOCKED rows are counted)
    assert len(df) == len(cases), 'DATA_COMPLETENESS_VIOLATION'
    counts = df.execution_status.value_counts().reindex(['PASS', 'FAIL', 'BLOCKED'], fill_value=0)
    by_req = (df.groupby(['requirement_id', 'execution_status']).size().unstack(fill_value=0)
                .reindex(columns=['PASS', 'FAIL', 'BLOCKED'], fill_value=0))
    by_req['TOTAL'] = by_req.sum(axis=1)
    by_req['PASS_RATE_%'] = (100 * by_req.PASS / by_req.TOTAL).round(1)
    by_req = by_req.reset_index()
    reqs = selected_reqs or sorted(df.requirement_id.unique())
    covered = [r for r in reqs if (df[(df.requirement_id == r) & (df.execution_status != 'BLOCKED')].shape[0] > 0)]
    summary = pd.DataFrame([{
        'run_id': run_id, 'source_file': cases_path.name, 'rows_read': len(cases), 'executed': len(df),
        'passed': int(counts.PASS), 'failed': int(counts.FAIL), 'blocked': int(counts.BLOCKED),
        'pass_rate_%': round(100 * counts.PASS / len(df), 1) if len(df) else 0.0,
        'requirements': len(reqs), 'requirements_covered': len(covered),
        'requirement_coverage_%': round(100 * len(covered) / len(reqs), 1) if reqs else 0.0,
        'total_duration_ms': round(df.duration_ms.sum(), 2),
    }])
    trace = build_traceability(df)

    df.to_csv(output / 'test_execution.csv', index=False, encoding='utf-8-sig')
    with pd.ExcelWriter(output / 'test_report.xlsx', engine='openpyxl') as xls:
        summary.to_excel(xls, index=False, sheet_name='Summary')
        by_req.to_excel(xls, index=False, sheet_name='ByRequirement')
        trace.to_excel(xls, index=False, sheet_name='Traceability')
        df.to_excel(xls, index=False, sheet_name='Execution')
    png = _chart_png(df)
    (output / 'test_summary_chart.png').write_bytes(png)
    _write_html(output / 'test_dashboard.html', df, summary.iloc[0], by_req, png)

    s = summary.iloc[0]
    print(f'[{run_id}] source={cases_path.name} rows_read={s.rows_read} executed={s.executed} '
          f'PASS={s.passed} FAIL={s.failed} BLOCKED={s.blocked} pass_rate={s["pass_rate_%"]}%')
    return df, summary, by_req, output


def _write_html(path, df, s, by_req, png):
    badge = {'PASS': '#16a34a', 'FAIL': '#dc2626', 'BLOCKED': '#d97706'}
    rows = ''.join(
        '<tr>' + ''.join(f'<td>{html.escape(str(r[k]))}</td>' for k in
                         ['test_case_id', 'requirement_id', 'condition_id', 'scenario_id', 'title',
                          'expected_json', 'actual_result'])
        + f'<td><b style="color:{badge[r["execution_status"]]}">{r["execution_status"]}</b></td></tr>'
        for _, r in df.iterrows())
    req_rows = ''.join('<tr>' + ''.join(f'<td>{html.escape(str(v))}</td>' for v in r) + '</tr>'
                       for r in by_req.itertuples(index=False))
    img = base64.b64encode(png).decode()
    page = f'''<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EduCommerce Test Report</title><style>
body{{font:14px/1.45 Segoe UI,Arial,sans-serif;margin:28px;color:#14233c;background:#fff}}h1{{color:#17385f;margin:0 0 4px}}
.meta{{color:#475569;margin-bottom:14px}}.m{{display:inline-block;margin:6px 10px 6px 0;padding:12px 18px;border-radius:10px;background:#edf3f9;font-size:18px}}
table{{border-collapse:collapse;width:100%;margin:10px 0 24px}}td,th{{border:1px solid #cbd5e1;padding:6px 8px;text-align:left;vertical-align:top;font-size:13px}}
th{{background:#16385e;color:#fff}}tr:nth-child(even){{background:#f8fafc}}img{{max-width:100%}}td:nth-child(6),td:nth-child(7){{font-family:Consolas,monospace;font-size:12px}}
</style></head><body><h1>EduCommerce – STLab02 Automated Test Execution</h1>
<div class="meta">Run: {s.run_id} • Source: {s.source_file} • Rows read: {s.rows_read} • Duration: {s.total_duration_ms} ms</div>
<div class="m">Total: {s.executed}</div><div class="m" style="color:#16a34a">PASS: {s.passed}</div>
<div class="m" style="color:#dc2626">FAIL: {s.failed}</div><div class="m" style="color:#d97706">BLOCKED: {s.blocked}</div>
<div class="m">Pass rate: {s["pass_rate_%"]}%</div><div class="m">REQ coverage: {s.requirements_covered}/{s.requirements}</div>
<h2>Chart</h2><img alt="status chart" src="data:image/png;base64,{img}">
<h2>Summary by requirement</h2><table><tr>{''.join(f'<th>{c}</th>' for c in by_req.columns)}</tr>{req_rows}</table>
<h2>Traceability &amp; execution</h2><table><tr><th>TC</th><th>REQ</th><th>COND</th><th>TS</th><th>Title</th><th>Expected</th><th>Actual</th><th>Status</th></tr>{rows}</table>
</body></html>'''
    path.write_text(page, encoding='utf-8')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Run EduCommerce data-driven tests')
    ap.add_argument('cases', nargs='?', default=str(ROOT / 'test_cases.csv'), help='CSV or XLSX test case file')
    ap.add_argument('--out', default=str(ROOT / 'reports'), help='report output folder')
    a = ap.parse_args()
    frame, *_ = run_suite(a.cases, a.out)
    print(frame[['test_case_id', 'requirement_id', 'execution_status', 'duration_ms']].to_string(index=False))
    fails = frame[frame.execution_status != 'PASS']
    if len(fails):
        print('\nNon-PASS details:')
        for _, r in fails.iterrows():
            print(f'  {r.test_case_id} [{r.execution_status}] {r.error_message}')
