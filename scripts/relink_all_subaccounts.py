# scripts/relink_all_subaccounts.py
from app.db.database import get_session_maker
from app.models.organization import Organization
from app.services.payments.provider_resolver import _get_provider_for_org, relink_subaccount, key_fingerprint

db = get_session_maker()()
print("Active key set:", key_fingerprint("paystack"))
for org in db.query(Organization).filter(Organization.payout_configured_at.isnot(None)).all():
    r = _get_provider_for_org(db, str(org.id))
    if r.provider_name != "paystack" or not r.account:
        continue
    code = relink_subaccount(db, r)
    db.commit()
    print(org.id, org.name, "->", code or "FAILED (needs manual re-setup)")
db.close()

