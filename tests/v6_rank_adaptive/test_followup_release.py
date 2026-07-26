from dvg_obs_ceo.v6_rank_adaptive.followup_release import (
    STAGES,
    _resolve,
)


def test_followup_stage_tags_resolve_to_declared_commits():
    for specification in STAGES.values():
        for tag_key in ("protocol_tag", "freeze_tag", "result_tag"):
            if tag_key not in specification:
                continue
            commit_key = tag_key.replace("_tag", "_commit")
            assert _resolve(specification[tag_key]).startswith(
                specification[commit_key]
            )
