from app.services.ai_service import _role_bucket, _role_profile_candidates


def test_role_buckets_split_writer_natural_reasoning_and_final():
    assert _role_bucket("writer") == "writer"
    assert _role_bucket("scene-director") == "writer"
    assert _role_bucket("blind-reader") == "natural-reader"
    assert _role_bucket("blind-natural-reader") == "natural-reader"
    assert _role_bucket("blind-dialogue-reader") == "natural-reader"
    assert _role_bucket("blind-artifice-reader") == "reasoning-reader"
    assert _role_bucket("reader-gap-reviewer") == "reasoning-reader"
    assert _role_bucket("plot-reviewer") == "reasoning-reader"
    assert _role_bucket("final-reviewer") == "final-review"
    assert _role_bucket("master-reader") == "natural-reader"
    assert _role_bucket("character-dialogue-reviewer") == "natural-reader"
    assert _role_bucket("language-rhythm-reviewer") == "natural-reader"
    assert _role_bucket("continuity-plot-reviewer") == "reasoning-reader"


def test_default_role_profiles_are_heterogeneous(monkeypatch):
    keys = [
        "NARRATIVE_WRITER_PROFILE",
        "NARRATIVE_WRITER_FALLBACK_PROFILES",
        "NARRATIVE_NATURAL_READER_PROFILE",
        "NARRATIVE_NATURAL_READER_FALLBACK_PROFILES",
        "NARRATIVE_REASONING_READER_PROFILE",
        "NARRATIVE_REASONING_READER_FALLBACK_PROFILES",
        "NARRATIVE_FINAL_REVIEW_PROFILE",
        "NARRATIVE_FINAL_REVIEW_FALLBACK_PROFILES",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)

    assert _role_profile_candidates("writer")[0] == "AGNES"
    assert _role_profile_candidates("blind-reader")[0] == "AGNES"
    assert _role_profile_candidates("blind-artifice-reader")[0] == "MODELSCOPE"
    assert _role_profile_candidates("final-reviewer")[0] == "SENSENOVA"
    assert _role_profile_candidates("master-reader")[0] == "AGNES"
    assert _role_profile_candidates("continuity-plot-reviewer")[0] == "GLM53FLASH"
    assert _role_profile_candidates("character-dialogue-reviewer")[0] == "AGNES"
    assert _role_profile_candidates("language-rhythm-reviewer")[0] == "XINGCHENAGI"


def test_role_profile_candidates_deduplicate(monkeypatch):
    monkeypatch.setenv("NARRATIVE_REASONING_READER_PROFILE", "GLM52")
    monkeypatch.setenv(
        "NARRATIVE_REASONING_READER_FALLBACK_PROFILES",
        "GLM52,ATRIA,GLM52",
    )
    assert _role_profile_candidates("plot-reviewer") == ["GLM52", "ATRIA"]


def test_specialist_readers_are_spread_across_profiles(monkeypatch):
    for key in [
        "NARRATIVE_ROLE_BLIND_ARTIFICE_READER_PROFILE",
        "NARRATIVE_ROLE_CONTINUITY_REVIEWER_PROFILE",
        "NARRATIVE_ROLE_CHARACTER_REVIEWER_PROFILE",
        "NARRATIVE_ROLE_BLIND_NATURAL_READER_PROFILE",
    ]:
        monkeypatch.delenv(key, raising=False)

    assert _role_profile_candidates("blind-artifice-reader")[0] == "MODELSCOPE"
    assert _role_profile_candidates("continuity-reviewer")[0] == "MODELSCOPE"
    assert _role_profile_candidates("character-reviewer")[0] == "AGNES"
    assert _role_profile_candidates("blind-natural-reader")[0] == "AGNES"


def test_named_profile_can_reuse_shared_profile_secret(monkeypatch):
    from app.services.ai_service import _named_provider_profile

    monkeypatch.setenv(
        "NARRATIVE_PROFILE_GLM52",
        "NOVEL_AI_KIND=openai-compatible "
        "NOVEL_AI_MODEL=glm-5.2 "
        "NOVEL_AI_BASE_URL=https://example.invalid/v1 "
        "NOVEL_AI_API_KEY_ENV=SENSENOVA",
    )
    monkeypatch.delenv("NARRATIVE_PROFILE_SECRET_GLM52", raising=False)
    monkeypatch.setenv("NARRATIVE_PROFILE_SECRET_SENSENOVA", "shared-secret")

    profile = _named_provider_profile("GLM52")
    assert profile is not None
    assert profile["api_key_env"] == "NARRATIVE_PROFILE_SECRET_SENSENOVA"
