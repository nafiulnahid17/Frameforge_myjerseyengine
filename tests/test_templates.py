from frameforge_engine.config import ModelPools
from frameforge_engine.templates import MOCKUP_TEMPLATES, VIDEO_TEMPLATES, catalog, get_template


def test_catalog_has_three_unique_templates_per_stage():
    payload = catalog()
    assert len(payload["mockup"]) == 3
    assert len(payload["video"]) == 3
    ids = {item["template_id"] for items in payload.values() for item in items}
    assert len(ids) == 6
    assert all(item["preview_url"].endswith("preview.svg") for items in payload.values() for item in items)


def test_template_prompts_preserve_source_of_truth():
    assert all("preserve" in template.prompt.lower() for template in (*MOCKUP_TEMPLATES, *VIDEO_TEMPLATES))
    assert get_template("mockup_luxury_float", "mockup").name == "Luxury 3D Float"


def test_duration_selects_short_medium_and_long_model_pools():
    pools = ModelPools(("analysis",), ("image",), ("short",), ("medium",), ("long",))
    assert pools.video_for(10) == ("short",)
    assert pools.video_for(20) == ("medium",)
    assert pools.video_for(30) == ("long",)

