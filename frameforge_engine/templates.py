from __future__ import annotations

from dataclasses import asdict, dataclass

from .errors import FrameForgeError


@dataclass(frozen=True)
class Template:
    template_id: str
    kind: str
    name: str
    description: str
    preview_path: str
    prompt: str

    def public(self) -> dict:
        item = asdict(self)
        item.pop("prompt")
        item["preview_url"] = f"/api/frameforge/templates/{self.template_id}/preview.svg"
        return item


MOCKUP_TEMPLATES = (
    Template(
        "mockup_luxury_float",
        "mockup",
        "Luxury 3D Float",
        "Floating premium product composition with cinematic studio lighting.",
        "mockup_luxury_float.svg",
        """Create a stunning, ultra-realistic 3D product advertisement. Make the supplied product or jersey design float elegantly in mid-air with a smooth dynamic perspective. Add premium context-appropriate elements that complement the product purpose, materials, colors, and brand identity. Use cinematic studio lighting, soft shadows, realistic reflections, glossy highlights, subtle atmosphere, and a luxury gradient background. Preserve the original design, packaging, brand marks, colors, labels, text, and proportions exactly as provided. Do not redraw, redesign, distort, replace, or invent any product detail. Position the product prominently in the center and create a clean high-end commercial composition with realistic texture, professional depth of field, and sharp detail.""",
    ),
    Template(
        "mockup_stadium_hero",
        "mockup",
        "Stadium Hero",
        "Dramatic jersey reveal inside a premium floodlit stadium.",
        "mockup_stadium_hero.svg",
        """Create an ultra-realistic premium sports campaign mockup using the supplied design. Present the exact jersey or product as the hero inside a modern floodlit stadium or arena, with dramatic tunnel depth, controlled haze, rim lighting, subtle crowd bokeh, and an energetic match-night atmosphere. Preserve every original color, logo, sponsor mark, number, label, pattern, proportion, and garment construction detail. Do not reinterpret or replace the supplied artwork. Use commercial sports-photography composition, believable fabric texture, natural folds, realistic shadows, and a sharp professional finish.""",
    ),
    Template(
        "mockup_editorial_launch",
        "mockup",
        "Editorial Launch",
        "Clean fashion-campaign layout with premium lifestyle direction.",
        "mockup_editorial_launch.svg",
        """Create a premium editorial launch campaign from the supplied product or jersey reference. Use a contemporary fashion-studio or refined urban setting, elegant directional lighting, tasteful negative space, subtle architectural geometry, and a sophisticated magazine-quality color grade. The exact supplied design must remain the visual source of truth: preserve branding, typography, colors, graphics, pattern placement, labels, shape, and proportions without hallucination. Produce realistic materials, natural depth, balanced composition, and polished commercial advertising quality.""",
    ),
)

VIDEO_TEMPLATES = (
    Template(
        "video_luxury_360",
        "video",
        "Luxury 360°",
        "Smooth 3D rotation, premium transitions, and studio lighting.",
        "video_luxury_360.svg",
        """Create a premium cinematic product advertisement video from the supplied approved mockup. Make the product rotate smoothly in 3D with a realistic 360-degree presentation, seamless shot transitions, elegant camera movement, floating contextual elements, soft cinematic lighting, realistic shadows, glossy reflections, and a clean luxury gradient environment. Preserve the original product, jersey artwork, branding, colors, labels, text, and proportions exactly as shown. Add subtle particles and engaging motion without distracting from the product. Use realistic physics, sharp detail, smooth animation, and commercial studio quality.""",
    ),
    Template(
        "video_stadium_reveal",
        "video",
        "Stadium Reveal",
        "Cinematic tunnel entrance followed by a floodlit hero reveal.",
        "video_stadium_reveal.svg",
        """Create a cinematic sports reveal video from the approved mockup. Begin with a controlled camera move through a dark premium stadium tunnel, reveal the exact product under sweeping floodlights, then orbit slowly around it while atmospheric haze, subtle particles, light streaks, and crowd bokeh build energy. Preserve every original design detail, logo, sponsor, number, color, pattern, and proportion. Use physically believable motion, fabric response, shadows, reflections, seamless transitions, and a strong final hero frame suitable for a professional jersey campaign.""",
    ),
    Template(
        "video_kinetic_social",
        "video",
        "Kinetic Social Promo",
        "Fast premium cuts and close-up details optimized for social media.",
        "video_kinetic_social.svg",
        """Create a high-impact premium social advertisement video from the approved mockup. Use a rhythm of clean wide shots, controlled push-ins, macro detail shots, smooth whip transitions, subtle speed ramps, and a final centered hero composition. Showcase fabric texture, graphics, logos, colors, and construction, and preserve all supplied artwork and proportions exactly. Keep motion polished rather than chaotic, use cinematic lighting and realistic reflections, and leave clean safe areas for deterministic brand and contact overlays.""",
    ),
)

ALL_TEMPLATES = {template.template_id: template for template in (*MOCKUP_TEMPLATES, *VIDEO_TEMPLATES)}


def get_template(template_id: str, expected_kind: str) -> Template:
    template = ALL_TEMPLATES.get(template_id)
    if template is None or template.kind != expected_kind:
        raise FrameForgeError("TEMPLATE_NOT_FOUND", f"Unknown {expected_kind} template.", 404)
    return template


def catalog() -> dict:
    return {
        "mockup": [template.public() for template in MOCKUP_TEMPLATES],
        "video": [template.public() for template in VIDEO_TEMPLATES],
    }

