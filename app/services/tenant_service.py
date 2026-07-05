from sqlalchemy.orm import Session
from typing import TypeVar, Type

T = TypeVar("T")

def get_current_org_id(current_user) -> str:
    if not current_user.organization_id:
        raise ValueError("User is not associated with any organization")
    return str(current_user.organization_id)

def get_org_scoped_query(db: Session, model_class: Type[T], org_id: str):
    return db.query(model_class).filter(model_class.organization_id == org_id)
