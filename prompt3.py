import json
import config


def build_director_prompt(outline, scenes):
    return f"""You are the director and final editor of a comedy cartoon in {config.LANGUAGE}. Fix the scenes below so story, voice and pictures match perfectly.

PLAN: {json.dumps(outline, ensure_ascii=False)}
SCENES: {json.dumps(scenes, ensure_ascii=False)}

Do all of this:
1. Story logic: every scene must follow from the one before it. Fix contradictions (who has which object, where they are, what just happened). The twist must be set up earlier, and the last story scene lands the punchline. The final scene still asks viewers the plan's comment question.
2. "narration": rewrite as natural casual spoken {config.LANGUAGE}, {config.LINE_WORDS} words, sharp punchlines, no stiff words. Dialogue stays in the voice of its speaker (a = {config.NAME_A}, b = {config.NAME_B}).
3. "image_prompt" (ENGLISH): rewrite so the picture shows EXACTLY what that narration says at that moment: who is speaking (shown prominently, mouth open, the other character reacting), what is happening, the key props, in the plan's location. Keep the characters' looks and the props identical in every scene. No text in the picture.
4. "title" ({config.TITLE_CHARS} characters, hook word first, one emoji at the end) and "description" (2-3 sentences) must match the final story exactly.
Keep "speaker", "motion", "sfx" and the number and order of scenes unchanged.

Return ONLY valid JSON: {{"title": "...", "description": "...", "scenes": [ ...all scenes, same fields... ]}}"""
