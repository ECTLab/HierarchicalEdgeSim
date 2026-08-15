"""Loan registry helpers (paper L_j). Vicinity and global grants on remote spawn."""

from __future__ import annotations

from .models import Container, LoanRecord, LoanTier, Server


def get_loan(server: Server, borrower_cluster_id: str, ms_id: str) -> LoanRecord | None:
    for record in server.loans:
        if record.borrower_cluster_id == borrower_cluster_id and record.ms_id == ms_id:
            return record
    return None


def has_loan(server: Server, borrower_cluster_id: str, ms_id: str) -> bool:
    return get_loan(server, borrower_cluster_id, ms_id) is not None


def add_loan(
    server: Server,
    *,
    borrower_cluster_id: str,
    ms_id: str,
    tier: LoanTier,
    ts: int,
) -> LoanRecord:
    existing = get_loan(server, borrower_cluster_id, ms_id)
    if existing is not None:
        return existing
    record = LoanRecord(
        borrower_cluster_id=borrower_cluster_id,
        ms_id=ms_id,
        tier=tier,
        ts=ts,
    )
    server.loans.append(record)
    return record


def drop_loan(server: Server, borrower_cluster_id: str, ms_id: str) -> bool:
    before = len(server.loans)
    server.loans = [
        rec
        for rec in server.loans
        if not (rec.borrower_cluster_id == borrower_cluster_id and rec.ms_id == ms_id)
    ]
    return len(server.loans) < before


def count_ms_on_server(server: Server, containers: dict[str, Container], ms_id: str) -> int:
    return sum(1 for cid in server.container_ids if containers[cid].microservice_id == ms_id)
