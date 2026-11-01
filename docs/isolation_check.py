"""Problem 3.6 - prove test isolation: run the suite in original, reversed and shuffled
order (and each case twice) and check every case keeps the same status.
Run from repo root: python docs/isolation_check.py"""
import random, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from test_runner import read_cases, execute_case, fixture

cases = read_cases('test_cases.csv')
status = lambda rows: {r['test_case_id']: execute_case(r)['execution_status'] for r in rows}
base = status(cases)
orders = {'reversed': list(reversed(cases)), 'shuffled(seed=7)': random.Random(7).sample(cases, len(cases)),
          'each case twice': [r for r in cases for _ in (0, 1)]}
for name, rows in orders.items():
    diff = {k: (base[k], v) for k, v in status(rows).items() if base[k] != v}
    print(f'{name:18} cases={len(rows):3}  differences={len(diff)}  {diff or "OK"}')
a, _, _ = fixture('499999'); b, _, _ = fixture('500k')
print('distinct objects per fixture:', a is not b, a.catalog is not b.catalog,
      '| B price in 499999 fixture =', a.catalog.products['B'].price, '| next fixture =', b.catalog.products['B'].price)
