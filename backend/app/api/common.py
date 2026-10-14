from fastapi import Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session


class PageParams:
    def __init__(self, page: int = Query(1, ge=1, le=10000), page_size: int = Query(25, ge=1, le=100, alias="pageSize")):
        self.page, self.size = page, page_size


def paginate(db: Session, stmt, params: PageParams) -> tuple[list, int]:
    total = db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    rows = db.execute(stmt.limit(params.size).offset((params.page - 1) * params.size)).unique().all()
    return rows, total


def page_out(items: list, total: int, params: PageParams) -> dict:
    return {"items": items, "total": total, "page": params.page, "pageSize": params.size}
