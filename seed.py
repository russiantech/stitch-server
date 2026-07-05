"""
seed.py — Populate Stitch with demo/reference data.

Run from the project root with the venv active and APP_SQL_CONNECTION_STRING
pointing at your dev database:

    python seed.py

Safe to re-run: every insert is guarded by a "does this already exist"
lookup (by name/slug/email), so running it twice won't create duplicates.

NOTE on the Category table: this seed assumes the `categories` table
matches the current app/models/category.py shape (name, slug, description,
display_order, is_active — no organization_id). If you already have an
older `categories` table in Postgres from before this fix, `create_tables()`
below will NOT alter it (SQLAlchemy's create_all only creates missing
tables). In that case, drop the table first:

    psql $DATABASE_URL -c "DROP TABLE IF EXISTS product_categories, categories CASCADE;"

...or just drop your whole dev DB and let create_tables() rebuild everything
fresh, then re-run this script.
"""
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.db.database import create_tables, get_session_maker

# Import every model module so create_tables() (Base.metadata.create_all)
# actually knows about all the tables — SQLAlchemy only registers a model
# with Base.metadata once its module has been imported somewhere.
from app.models import (  # noqa: F401
    organization, users, rbac, pricing, category, products,
    inventory, tenant_billing, orders, payments, notifications,
    platform_billing,
)
from app.models.organization import Organization
from app.models.users import User
from app.models.rbac import Role
from app.models.pricing import GarmentType, LaundryService, DeliveryArea
from app.models.category import Category
from app.models.products import Product, ProductImage
from app.models.inventory import InventoryItem
from app.models.tenant_billing import ServicePlan
from app.enums.stitch import PlanInterval

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("seed")


def get_or_create(db, model, defaults=None, **lookup):
    """Fetch a row matching `lookup`, or create it with `lookup` + `defaults`."""
    instance = db.query(model).filter_by(**lookup).first()
    if instance:
        return instance, False
    params = {**lookup, **(defaults or {})}
    instance = model(**params)
    db.add(instance)
    db.flush()
    return instance, True


# ─────────────────────────────────────────────────────────────────────────
# Organization & Users
# ─────────────────────────────────────────────────────────────────────────

def seed_org_and_users(db):
    org, created = get_or_create(
        db, Organization,
        slug="stitch-demo",
        defaults=dict(
            name="Stitch Demo Laundry",
            description="Demo tenant seeded for local development.",
            plan="pro",
            max_users=25,
            max_products=500,
            allow_public_signup=True,
            is_active=True,
            invite_code=Organization.generate_invite_code(),
            subscription_status="active",
        ),
    )
    log.info("%s organization: %s", "Created" if created else "Found", org.name)

    role_defs = [
        ("super_admin", "Platform-level administrator", False),
        ("admin", "Organization administrator", False),
        ("manager", "Operations manager", False),
        ("staff", "Laundry/fashion floor staff", True),
        ("driver", "Pickup & delivery driver", False),
        ("customer", "Customer / end user", False),
        ("cashier", "Front-desk cashier", False),
    ]
    roles = {}
    for name, desc, is_default in role_defs:
        role, created = get_or_create(
            db, Role, name=name,
            defaults=dict(description=desc, is_default=is_default, organization_id=None),
        )
        roles[name] = role
        if created:
            log.info("Created role: %s", name)

    def ensure_user(*, username, email, names, phone, role_name, is_org_admin=False, password="Edidem12"):
        user = db.query(User).filter_by(email=email).first()
        if user:
            return user, False
        user = User(
            username=username, email=email, names=names, phone=phone,
            organization_id=org.id, is_org_admin=is_org_admin,
            is_active=True, email_verified=True,
        )
        user.set_password(password)
        user.roles.append(roles[role_name])
        db.add(user)
        db.flush()
        return user, True

    demo_users = [
        dict(username="edidem", email="edidem@stitch.ng", names="Chris Edidem",
             phone="08031112222", role_name="admin", is_org_admin=True),
        dict(username="chioma", email="chioma@stitch.ng", names="Chioma Uzoma",
             phone="08032223333", role_name="staff"),
        dict(username="tunde", email="tunde@stitch.ng", names="Tunde Bakare",
             phone="08033334444", role_name="staff"),
        dict(username="segun", email="segun@stitch.ng", names="Segun Adeola",
             phone="08034445555", role_name="driver"),
        dict(username="mfon", email="mfon@gmail.com", names="MfonObong Etefia",
             phone="08051112222", role_name="customer"),
        dict(username="bassey", email="bassey@gmail.com", names="Bassey Akpan",
             phone="08052223333", role_name="customer"),
        dict(username="kelechi", email="kelechi@gmail.com", names="Kelechi Obi",
             phone="08053334444", role_name="customer"),
    ]

    created_users = {}
    for u in demo_users:
        user, created = ensure_user(**u)
        created_users[u["email"]] = user
        log.info("%s user: %s (%s)", "Created" if created else "Found", user.names, u["role_name"])

    admin_user = created_users["edidem@stitch.ng"]
    if org.owner_id is None:
        org.owner_id = admin_user.id
        log.info("Set organization owner to %s", admin_user.names)

    db.commit()
    return org, created_users


# ─────────────────────────────────────────────────────────────────────────
# Delivery Areas
# ─────────────────────────────────────────────────────────────────────────

def seed_delivery_areas(db):
    areas = [
        ("Lekki Phase 1",     1500, "Standard delivery within Lekki Phase 1"),
        ("Ikoyi",             2000, "Premium zone delivery"),
        ("Victoria Island",   2000, "Premium zone delivery"),
        ("Ajah",              1200, "Standard delivery"),
        ("Yaba",              1000, "Standard delivery"),
        ("Surulere",          1000, "Standard delivery"),
        ("Ikeja",             1300, "Standard delivery"),
        ("Magodo",             900, "Standard delivery"),
        ("Ogudu",              800, "Standard delivery"),
        ("Gbagada",             800, "Standard delivery"),
        ("Ajao Estate",        1100, "Standard delivery"),
        ("Festac Town",        1400, "Extended zone delivery"),
    ]
    count = 0
    for i, (name, price, desc) in enumerate(areas):
        _, created = get_or_create(
            db, DeliveryArea, name=name,
            defaults=dict(price=Decimal(price), state="Lagos", description=desc,
                          is_active=True, display_order=i),
        )
        count += created
    db.commit()
    log.info("Delivery areas: %d created, %d total", count, len(areas))


# ─────────────────────────────────────────────────────────────────────────
# Garment Pricing
# ─────────────────────────────────────────────────────────────────────────

def seed_garment_types(db):
    garments = [
        ("Shirt",              "Tops",         350, "per piece"),
        ("T-Shirt",             "Tops",         250, "per piece"),
        ("Blouse",              "Tops",         350, "per piece"),
        ("Trousers",            "Bottoms",      400, "per piece"),
        ("Jeans",               "Bottoms",      450, "per piece"),
        ("Skirt",               "Bottoms",      350, "per piece"),
        ("Native Wear (2pc)",   "Native Wear", 1200, "per set"),
        ("Agbada (3pc)",        "Native Wear", 2500, "per set"),
        ("Gele/Head Wrap",      "Native Wear",  300, "per piece"),
        ("Suit (2pc)",          "Full outfits",1800, "per set"),
        ("Suit (3pc)",          "Full outfits",2200, "per set"),
        ("Gown/Dress",          "Full outfits",1000, "per piece"),
        ("Wedding Gown",        "Full outfits",5000, "per piece"),
        ("Jacket",              "Outerwear",    700, "per piece"),
        ("Coat",                "Outerwear",   1200, "per piece"),
        ("Sweater",             "Outerwear",    600, "per piece"),
        ("Underwear (set of 5)","Innerwear",    500, "per set"),
        ("Bedsheet (set)",      "Household",    900, "per set"),
        ("Duvet/Comforter",     "Household",   2000, "per piece"),
        ("Curtain (pair)",      "Household",   1500, "per pair"),
        ("Towel",               "Household",    300, "per piece"),
    ]
    count = 0
    for i, (name, category_, price, unit) in enumerate(garments):
        _, created = get_or_create(
            db, GarmentType, name=name,
            defaults=dict(category=category_, base_price=Decimal(price), unit=unit,
                          is_active=True, display_order=i),
        )
        count += created
    db.commit()
    log.info("Garment types: %d created, %d total", count, len(garments))


# ─────────────────────────────────────────────────────────────────────────
# Laundry Services
# ─────────────────────────────────────────────────────────────────────────

def seed_laundry_services(db):
    services = [
        ("Standard Wash",       "Regular wash and fold service",           1.0,  "fa-soap"),
        ("Wash & Fold",         "Wash, dry and neatly fold your garments", 1.0,  "fa-shirt"),
        ("Dry Cleaning",        "Professional dry cleaning for delicates", 2.5,  "fa-wind"),
        ("Express Service",     "Same-day turnaround",                     1.75, "fa-bolt"),
        ("Ironing Only",        "Pressing and ironing service",            0.6,  "fa-temperature-high"),
        ("Starching & Ironing", "Traditional starch finish for native wear",0.9, "fa-scroll"),
        ("Stain Treatment",     "Deep stain removal add-on",               1.5,  "fa-droplet"),
    ]
    count = 0
    for i, (name, desc, mult, icon) in enumerate(services):
        _, created = get_or_create(
            db, LaundryService, name=name,
            defaults=dict(description=desc, price_multiplier=Decimal(str(mult)),
                          icon=icon, is_active=True, display_order=i),
        )
        count += created
    db.commit()
    log.info("Laundry services: %d created, %d total", count, len(services))


# ─────────────────────────────────────────────────────────────────────────
# Subscription Plans
# ─────────────────────────────────────────────────────────────────────────

def seed_plans(db):
    plans = [
        ("Starter",  8000,  30, PlanInterval.MONTHLY, False,
         "Great for individuals — 30 garment units every month."),
        ("Basic",   15000,  70, PlanInterval.MONTHLY, True,
         "Our most popular plan — 70 units, ideal for small families."),
        ("Premium", 28000, 150, PlanInterval.MONTHLY, False,
         "For large households — 150 units per month with priority handling."),
        ("Family Weekly", 6000, 25, PlanInterval.WEEKLY, False,
         "Weekly billing for consistently high laundry volume."),
    ]
    count = 0
    for i, (name, amount, units, interval, popular, desc) in enumerate(plans):
        _, created = get_or_create(
            db, ServicePlan, name=name,
            defaults=dict(description=desc, amount=Decimal(amount), units=units,
                          interval=interval, is_popular=popular, is_active=True,
                          display_order=i, organization_id=None),
        )
        count += created
    db.commit()
    log.info("Service plans: %d created, %d total", count, len(plans))


# ─────────────────────────────────────────────────────────────────────────
# Fashion Categories & Products
# ─────────────────────────────────────────────────────────────────────────

def seed_fashion_catalog(db):
    categories = [
        ("Native Wear",     "Traditional and native attire"),
        ("Women's Wear",    "Dresses, gowns and women's fashion"),
        ("Men's Wear",      "Suits, shirts and men's fashion"),
        ("Kids Wear",       "Children's clothing"),
        ("Accessories",     "Bags, headwear and fashion accessories"),
        ("Bridal & Events",  "Wedding and event wear"),
    ]
    cat_objs = {}
    created_count = 0
    for i, (name, desc) in enumerate(categories):
        slug = name.lower().replace(" & ", "-").replace("'", "").replace(" ", "-")
        cat, created = get_or_create(
            db, Category, slug=slug,
            defaults=dict(name=name, description=desc, display_order=i, is_active=True),
        )
        cat_objs[name] = cat
        created_count += created
    db.commit()
    log.info("Fashion categories: %d created, %d total", created_count, len(categories))

    products = [
        ("Ankara Jumpsuit",        "Women's Wear",  15000, 12, "Bold-print ankara jumpsuit, custom tailored."),
        ("Aso-Oke Agbada Set",     "Native Wear",    45000,  5, "Premium 3-piece Aso-Oke agbada, hand-finished."),
        ("Senator Suit",           "Men's Wear",     22000,  8, "Classic senator wear, made to measure."),
        ("Kaftan Gown",            "Men's Wear",     18000, 10, "Flowing embroidered kaftan."),
        ("Wedding Reception Gown", "Bridal & Events",65000,  3, "Custom bridal reception gown."),
        ("Aso-Ebi Gele",           "Accessories",     5000, 20, "Ready-to-tie aso-ebi gele headwrap."),
        ("Kids Native Set",        "Kids Wear",       8000, 15, "Matching native wear set for children."),
        ("Ankara Skirt & Blouse",  "Women's Wear",   12000, 14, "Two-piece ankara skirt and blouse set."),
        ("Beaded Clutch Bag",      "Accessories",     6000, 18, "Hand-beaded clutch to match native outfits."),
        ("Agbada Cap (Fila)",      "Accessories",     3500, 25, "Traditional fila cap."),
    ]
    p_count = 0
    for name, cat_name, price, stock, desc in products:
        slug = name.lower().replace(" ", "-").replace("(", "").replace(")", "")
        sku = "STC-" + "".join(w[0] for w in name.split())[:4].upper() + str(price)[:3]
        product, created = get_or_create(
            db, Product, slug=slug,
            defaults=dict(name=name, description=desc, price=Decimal(price),
                          stock=stock, sku=sku, is_active=True),
        )
        if created:
            product.categories.append(cat_objs[cat_name])
            db.add(ProductImage(
                product_id=product.id,
                url=f"https://placehold.co/600x600?text={name.replace(' ', '+')}",
                media_type="image", display_order=0, alt_text=name,
            ))
        p_count += created
    db.commit()
    log.info("Fashion products: %d created, %d total", p_count, len(products))


# ─────────────────────────────────────────────────────────────────────────
# Inventory Items
# ─────────────────────────────────────────────────────────────────────────

def seed_inventory(db):
    # (name, category, quantity, unit, reorder_level, unit_cost, supplier)
    items = [
        ("Ariel Detergent Powder",  "Detergent",       80,  "kg",  20, 1800, "Lagos Wholesale Chemicals"),
        ("Persil Detergent Liquid", "Detergent",       15,  "L",   20, 2200, "Lagos Wholesale Chemicals"),
        ("Fabric Softener (Downy)", "Detergent",       40,  "L",   15, 1500, "Lagos Wholesale Chemicals"),
        ("Bleach",                  "Chemical",         0,  "L",   10,  900, "Chem Supplies Nigeria"),
        ("Starch Powder",           "Chemical",        25,  "kg",  10, 1200, "Chem Supplies Nigeria"),
        ("Stain Remover",           "Chemical",        12,  "L",    8, 2000, "Chem Supplies Nigeria"),
        ("Polythene Garment Bags",  "Packaging",      500,  "pcs", 100,   25, "Pack Right Ltd"),
        ("Garment Tags",            "Packaging",      120,  "pcs", 150,   10, "Pack Right Ltd"),
        ("Hangers (Plastic)",       "Packaging",      300,  "pcs", 100,   50, "Pack Right Ltd"),
        ("Ankara Fabric (Assorted)","Fashion Material", 60,  "yards", 20, 2500, "Balogun Market Textiles"),
        ("Aso-Oke Fabric",          "Fashion Material",  8,  "yards", 10, 6000, "Balogun Market Textiles"),
        ("Lining Material",         "Fashion Material", 45,  "yards", 15, 1000, "Balogun Market Textiles"),
        ("Buttons (Assorted)",      "Accessory",      400,  "pcs", 100,   15, "Tailoring Supplies Co"),
        ("Zippers (Assorted)",      "Accessory",      150,  "pcs",  50,   80, "Tailoring Supplies Co"),
        ("Sewing Thread Spools",    "Accessory",       90,  "spools", 30, 200, "Tailoring Supplies Co"),
        ("Industrial Sewing Machine Needles", "Equipment", 200, "pcs", 50, 30, "Tailoring Supplies Co"),
        ("Steam Iron (Industrial)", "Equipment",        4,  "pcs",   2, 45000, "Lagos Equipment Depot"),
        ("Washing Machine Filters", "Equipment",        3,  "pcs",   3, 8000, "Lagos Equipment Depot"),
    ]
    count = 0
    for name, category_, qty, unit, reorder, cost, supplier in items:
        _, created = get_or_create(
            db, InventoryItem, name=name,
            defaults=dict(category=category_, quantity=qty, unit=unit,
                          reorder_level=reorder, unit_cost=Decimal(cost), supplier=supplier),
        )
        count += created
    db.commit()
    log.info("Inventory items: %d created, %d total", count, len(items))


# ─────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────

def main():
    log.info("Creating any missing tables...")
    create_tables()

    Session = get_session_maker()
    db = Session()
    try:
        seed_org_and_users(db)
        seed_delivery_areas(db)
        seed_garment_types(db)
        seed_laundry_services(db)
        seed_plans(db)
        seed_fashion_catalog(db)
        seed_inventory(db)
        log.info("✅ Seed complete.")
        log.info("Demo logins (password: Edidem12):")
        log.info("  Admin:    chris@stitch.ng")
        log.info("  Staff:    chioma@stitch.ng / tunde@stitch.ng")
        log.info("  Driver:   segun@stitch.ng")
        log.info("  Customer: mfon@gmail.com / bassey@gmail.com / kelechi@gmail.com")
    except Exception:
        db.rollback()
        log.exception("Seed failed — rolled back.")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
