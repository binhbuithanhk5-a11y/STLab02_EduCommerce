"""Reproduce DEF-001/DEF-002 on a clean fixture. Run from repo root: python docs/reproduce_defects.py"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from test_runner import fixture
for m in ['WALLET','cod','']:
    app,u,cart=fixture('600k'); before=app.catalog.products['A'].stock
    try: app.place(u,cart,method=m,key='R1')
    except ValueError as e: err=str(e)
    print(f"method={m!r:9} error={err:24} orders={len(app.orders)} stockA {before} -> {app.catalog.products['A'].stock}")
from ecommerce_app import Catalog, Cart
c=Cart(Catalog()); c.add('A',True); print('Cart.add("A", True) ->', c.lines, 'subtotal', c.subtotal())
