"""Wallet ledger. Every balance change is a WalletTransaction with the resulting balance."""

from .. import repositories as repo
from ..errors import PaymentError
from ..models import Receipt, User, WalletTransaction
from ..timeutil import local_today


def locked_user(user_id):
    return repo.get_for_update(User, user_id)


def credit(user_id, amount_cents, kind, reference=None):
    user = locked_user(user_id)
    user.balance_cents += amount_cents
    repo.add(
        WalletTransaction(
            user_id=user.id,
            amount_cents=amount_cents,
            kind=kind,
            reference=reference,
            balance_after_cents=user.balance_cents,
        )
    )
    return user


def debit(user_id, amount_cents, kind, reference=None):
    user = locked_user(user_id)
    if user.balance_cents < amount_cents:
        raise PaymentError(
            "Not enough balance in your wallet.",
            code="insufficient_funds",
            details={"balance_cents": user.balance_cents, "required_cents": amount_cents},
        )
    user.balance_cents -= amount_cents
    repo.add(
        WalletTransaction(
            user_id=user.id,
            amount_cents=-amount_cents,
            kind=kind,
            reference=reference,
            balance_after_cents=user.balance_cents,
        )
    )
    return user


def create_receipt(
    user_id, description, amount_cents, method, discount_cents=0, payment_id=None, pass_id=None, revenue=True
):
    from ..extensions import db

    receipt = repo.add(
        Receipt(
            number="pending",
            user_id=user_id,
            description=description,
            amount_cents=amount_cents,
            discount_cents=discount_cents,
            method=method,
            payment_id=payment_id,
            pass_id=pass_id,
            revenue=revenue,
        )
    )
    db.session.flush()  # the id is unique and sequential, so numbers never collide under concurrency
    receipt.number = f"CB-{local_today().year}-{receipt.id:06d}"
    return receipt
