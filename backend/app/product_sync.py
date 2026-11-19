from sqlalchemy import case, func
from .models import Product

def price_update_values(statement):
    changed = Product.price != statement.excluded.price
    return {
        "name": statement.excluded.name,
        "price": statement.excluded.price,
        "unit": statement.excluded.unit,
        "previous_price": case((changed, Product.price), else_=Product.previous_price),
        "price_changed_at": case((changed, func.now()), else_=Product.price_changed_at),
        "needs_reprint": case((changed, True), else_=Product.needs_reprint),
        "updated_at": func.now(),
    }
