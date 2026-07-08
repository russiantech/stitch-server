# app/api/v1/palmpay.py
"""app/api/v1/palmpay.py — Tenant PalmPay configuration: bank details, subaccounts."""
import logging
from fastapi import APIRouter, Depends
from app.utils.responses import api_response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Palmpay"])

