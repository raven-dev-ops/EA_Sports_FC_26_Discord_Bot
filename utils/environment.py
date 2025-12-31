from __future__ import annotations

import os


def app_env() -> str:
    env = os.getenv("APP_ENV", "development").strip().lower()
    return env or "development"


def stripe_mode() -> str:
    return os.getenv("STRIPE_MODE", "").strip().lower()


def validate_stripe_environment() -> None:
    secret_key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret_key:
        return
    mode = stripe_mode()
    if not mode:
        raise RuntimeError("STRIPE_MODE must be set when STRIPE_SECRET_KEY is configured.")
    if mode not in {"test", "live"}:
        raise RuntimeError("STRIPE_MODE must be 'test' or 'live'.")

    env = app_env()
    if env in {"staging", "development", "dev"} and mode == "live":
        raise RuntimeError("Refusing live Stripe keys outside production.")
    if env in {"production", "prod"} and mode == "test":
        raise RuntimeError("Refusing test Stripe keys in production.")

    if secret_key.startswith("sk_live_") and mode != "live":
        raise RuntimeError("STRIPE_SECRET_KEY is live but STRIPE_MODE is not 'live'.")
    if secret_key.startswith("sk_test_") and mode != "test":
        raise RuntimeError("STRIPE_SECRET_KEY is test but STRIPE_MODE is not 'test'.")
