from datetime import timedelta

from django.test import SimpleTestCase
from django.utils import timezone

from feed import config as C
from feed import scoring
from feed.scoring import Candidate


def _cand(i, seller=1, sub=1, **kw):
    defaults = dict(
        name="Sample listing name", description="x" * 100, price=1000, location="Kampala",
        created_at=timezone.now(), promoted=False, photos=2,
    )
    defaults.update(kw)
    return Candidate(id=i, seller_id=seller, subcategory_id=sub, **defaults)


class ScoringTests(SimpleTestCase):
    def test_quality_rewards_complete_listings(self):
        full = _cand(1, photos=3)
        bare = _cand(2, photos=0, description="", price=0, location="")
        self.assertGreater(scoring.quality(full), scoring.quality(bare))

    def test_fresh_beats_old(self):
        now = timezone.now()
        fresh = _cand(1, created_at=now)
        old = _cand(2, created_at=now - timedelta(days=40))
        self.assertGreater(scoring.freshness(fresh, now), scoring.freshness(old, now))

    def test_diversify_caps_seller_per_block(self):
        ranked = [_cand(i, seller=1, sub=i) for i in range(5)] + [_cand(10 + i, seller=2 + i, sub=100 + i) for i in range(5)]
        out = scoring.diversify(ranked)
        first_block = out[: C.BLOCK_SIZE]
        self.assertEqual(len(out), len(ranked))
        self.assertLessEqual([c.seller_id for c in first_block[:7]].count(1), C.SELLER_CAP_PER_BLOCK)

    def test_diversify_breaks_subcategory_runs(self):
        ranked = [_cand(i, seller=i, sub=1) for i in range(5)] + [_cand(99, seller=99, sub=2)]
        out = scoring.diversify(ranked)
        self.assertEqual(out[C.MAX_SAME_SUBCATEGORY_RUN].subcategory_id, 2)

    def test_trending_requires_engagement(self):
        now = timezone.now()
        hot = _cand(1, views=50, wishes=5)
        cold = _cand(2, views=1)
        self.assertEqual(scoring.trending_ids([hot, cold], now), {1})

    def test_location_boost(self):
        now = timezone.now()
        a = _cand(1, location="Ntinda, Kampala")
        b = _cand(2, location="Gulu")
        scores = scoring.score_all([a, b], now, location="kampala")
        self.assertGreater(scores[1], scores[2])
