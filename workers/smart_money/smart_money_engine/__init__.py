try:  # pragma: no cover - support package and script-style imports
    from .wallet_classifier import classify_wallet
    from .wallet_metrics import compute_wallet_scores
except ImportError:  # pragma: no cover
    from wallet_classifier import classify_wallet
    from wallet_metrics import compute_wallet_scores

__all__ = [
    "classify_wallet",
    "compute_wallet_scores",
]
