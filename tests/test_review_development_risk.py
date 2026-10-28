import hashlib

import pytest
from scripts.review_development_risk import checked, same


def test_changed_evidence_is_rejected(tmp_path):
    source = tmp_path / "evidence.json"
    source.write_bytes(b"original")
    digest = hashlib.sha256(b"original").hexdigest()
    assert checked(source, digest) == b"original"
    source.write_bytes(b"modified")
    with pytest.raises(ValueError, match="source changed"):
        checked(source, digest)


@pytest.mark.parametrize("value", ["0.7", "nan", "inf"])
def test_mismatched_or_nonfinite_export_is_rejected(value):
    with pytest.raises(ValueError, match="score mismatch"):
        same({"score": value}, "score", 0.5)
