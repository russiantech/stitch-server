# app/api/v1/flutterwave.py
"""app/api/v1/flutterwave.py — Tenant Flutterwave configuration: bank details, subaccounts."""
import logging
from fastapi import APIRouter, Depends
from app.utils.responses import api_response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Flutterwave"])

