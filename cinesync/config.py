"""Central configuration. Edit the values below OR set environment variables
(DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, SECRET_KEY)."""
import os

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", "Deepanshu@43"),
    "database": os.environ.get("DB_NAME", "smart_movie"),
}

SECRET_KEY = os.environ.get("SECRET_KEY", "cinesync-change-this-secret-key")
POOL_SIZE = 8
MAX_SEATS_PER_BOOKING = 6
PREMIUM_MULTIPLIER = "1.5"      # premium seats cost 1.5x the show's base price
PAYMENT_MODES = ("DEMO", "UPI", "CARD", "NETBANKING")
