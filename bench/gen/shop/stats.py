from world import World
from sim import CUT
from collections import Counter
from datetime import date
w=World(); w.run()
for k in (1,2):
    cut=CUT[k]
    os=[o for o in w.orders if o.created.date()<=cut]
    print(f'== cut {cut}: orders',len(os),'b2b',sum(1 for o in os if o.b2b),'lines',sum(len(o.lines) for o in os))
    print('gateways',Counter(o.gateway for o in os))
    print('countries',Counter(o.country for o in os))
    print('cancelled',sum(1 for o in os if o.cancelled_at and o.cancelled_at.date()<=cut))
    unf=[o for o in os if not o.fulfilled_at or o.fulfilled_at.date()>cut]
    unf=[o for o in unf if not (o.cancelled_at and o.cancelled_at.date()<=cut)]
    print('unfulfilled at cut',len(unf))
    for o in unf: print('  ',o.name,o.created,o.gateway,o.b2b.kno if o.b2b else '',o.ship_method,[ (l.v.sku,l.qty) for l in o.lines], sorted(o.flags), o.paid_at)
    print('returns',sum(1 for r in w.returns if r.arrived<=cut))
    print('invoices',len([i for i in w.inv if i.d<=cut]))
    print('bank lines',sum(1 for t in w.bank if t.d<=cut),'pp',sum(1 for p in w.pp if p.dt.date()<=cut),'sp',sum(1 for s in w.sp if s.dt.date()<=cut),'kl',sum(1 for k in w.kl if k.payout_date and k.payout_date<=cut))
    print('customers used',len({o.cust.email for o in os if not o.b2b}))
print('sinv',Counter(s.supplier for s in w.sinv))
print('scenario',{k:(v if not hasattr(v,'no') else v.no) for k,v in w.scenario.items() if k not in ('kb_gu','ds_gu')})
print('final bank balance',w.bank[-1].balance, 'min', min(t.balance for t in w.bank))
neg=[(s,q) for s,q in w.on_hand.items() if q<0]; print('neg stock',neg)
print('waited', sum(1 for o in w.orders if 'waited' in o.flags))
print('stock end', sorted(w.on_hand.items())[:80])
