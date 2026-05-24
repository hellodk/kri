# fleet_platform/api/limiter.py
"""
Centralised SlowAPI limiter instance.

Importing from this module (instead of from main.py) avoids the circular
import that arises when routes import `limiter` from `main.py`, which itself
imports the routes.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
