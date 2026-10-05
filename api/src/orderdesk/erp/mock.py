"""A mock ERP sales-order API with fault injection, standing in for the customer's real ERP.

    POST /erp-mock/v1/sales-orders   (header Idempotency-Key)  -> 201 {erp_ref} | 200 replay | 503 | slow
    POST /erp-mock/v1/faults         set failures for testing and demos

Faults include the nasty one: the ERP books the order and then the response is lost. Only an idempotency
key keeps the retry from booking it twice.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from orderdesk.db.models import ErpOrder
from orderdesk.db.session import get_session

router = APIRouter(prefix="/erp-mock/v1", tags=["mock ERP"])


class Faults(BaseModel):
    fail_next: int = 0  # next N requests return 503 before booking anything
    lose_response_next: int = 0  # next N requests book the order, then fail as if the response were lost
    slow_next: int = 0  # next N requests take `slow_seconds`
    slow_seconds: float = 5.0


_faults = Faults()
_lock = threading.Lock()


def _take(field: str) -> bool:
    with _lock:
        n = getattr(_faults, field)
        if n > 0:
            setattr(_faults, field, n - 1)
            return True
        return False


@router.post("/faults")
def set_faults(f: Faults, request: Request) -> dict[str, Any]:
    if request.client and request.client.host not in ("127.0.0.1", "::1", "testclient"):
        raise HTTPException(403, "fault injection is local-only")
    global _faults
    with _lock:
        _faults = f
    return f.model_dump()


@router.post("/sales-orders", status_code=201)
def create_sales_order(payload: dict[str, Any], idempotency_key: str = Header(..., alias="Idempotency-Key"),
                       s: Session = Depends(get_session)) -> dict[str, Any]:  # fmt: skip
    if _take("fail_next"):
        raise HTTPException(503, "ERP temporarily unavailable")
    if _take("slow_next"):
        time.sleep(_faults.slow_seconds)
    if not payload.get("lines"):
        raise HTTPException(422, "an ERP sales order needs at least one line")
    stmt = (
        insert(ErpOrder)
        .values(
            idempotency_key=idempotency_key,
            erp_ref=f"ERP-{abs(hash(idempotency_key)) % 10**9:09d}",
            payload=payload,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    s.execute(stmt)
    s.flush()
    row = s.query(ErpOrder).filter_by(idempotency_key=idempotency_key).one()
    if _take("lose_response_next"):
        s.commit()  # booked...
        raise HTTPException(504, "gateway timeout")  # ...but the caller never hears about it
    return {"erp_ref": row.erp_ref, "idempotency_key": idempotency_key}
