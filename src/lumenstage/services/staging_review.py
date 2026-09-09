"""Application service for staging-gate reviews."""

from __future__ import annotations

from lumenstage.models.staging_review import StagingReview
from lumenstage.services.base import EntityService
from lumenstage.storage.store import JsonDocumentStore


class StagingReviewService(EntityService[StagingReview]):
    def __init__(self, store: JsonDocumentStore) -> None:
        super().__init__(store, StagingReview, "staging_reviews", "staging review")

    def decide(self, review_id: str, decision: str, *, comment: str = "") -> StagingReview:
        review = self.get(review_id)
        review.decide(decision, comment=comment)
        return self.repo.save(review)

    def pending(self, *, stage: str | None = None) -> list[StagingReview]:
        reviews = [review for review in self.list(status="active") if review.decision == "pending"]
        if stage:
            reviews = [review for review in reviews if review.stage == stage]
        return reviews

    def approvals_for(self, stage: str) -> list[StagingReview]:
        return [review for review in self.list() if review.stage == stage and review.approved]
