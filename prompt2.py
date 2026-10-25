import json
import config


def build_script_prompt(outline):
    return f"""You are a comedy scriptwriter. Turn this episode plan into a scene-by-scene script.
Language of spoken lines: {config.LANGUAGE}, natural everyday spoken style, like friends joking, never bookish.

PLAN:
{json.dumps(outline, ensure_ascii=False)}

CHARACTERS: speaker a = {config.NAME_A}, speaker b = {config.NAME_B}. {config.CAST_BIO}

Rules:
- {config.FORMAT_RULES}
- One scene per beat, in the same order ({config.NUM_SCENES - 1} scenes), then ONE extra final scene: a narrator or character looks at the camera and says exactly this question to the viewers: "{outline.get('comment_question', '')}" (image: both characters looking at the camera, pointing at the viewer, funny faces). Total {config.NUM_SCENES} scenes.
- About 60 percent of scenes are DIALOGUE between the two characters (speaker "a" or "b"); the rest are a quick narrator line (speaker "narrator").
- Humor is witty and relatable for all ages (observations, wordplay, absurd logic), never baby talk.
- Each spoken line is SHORT: {config.LINE_WORDS} words, one clear joke, setup then punchline. Add reactions and funny sound words.
- The running gag returns three times, bigger each time. The scene before the question ends on the biggest punchline.

ALIGNMENT RULES (very important, the viewer sees the picture while hearing the line):
- Each scene's spoken line must carry out its beat, and must react to what was said or shown in the previous scene (like a real conversation, no random jumps).
- The image_prompt must show EXACTLY what the line says or implies: the same action, the same objects, the speaker's emotion, and any object the line names.
- If the speaker is a or b, that character is in the picture, mouth open, and the other character reacts when present. Refer to the characters by their names ({config.NAME_A}, {config.NAME_B}) in image_prompt.
- Stay inside the plan's location_visual in every picture, and show the plan's gag_visual in every scene where the running gag happens.
- Never mention in a line something that cannot be seen or understood from the story so far.

Return ONLY valid JSON: {{"scenes": [{{
  "speaker": "a, b or narrator",
  "narration": "the spoken line in {config.LANGUAGE}",
  "image_prompt": "ENGLISH ONLY: one clear action moment matching the line, characters fully visible, funny exaggerated expression, simple background, no text",
  "motion": "zoom_in, zoom_out, pan_left, pan_right, pan_up, pan_down, shake or punch (shake for crashes, punch for surprises and the final line, pans for chases)",
  "sfx": "whoosh, boing, crash, pop or none (none on about half the scenes)"
}}]}}"""


def build_polish_prompt(scenes, outline):
    return f"""You are a stand-up comedy editor for {config.LANGUAGE}. Below is a script, scene by scene. Each scene has a spoken "narration" and an English "image_prompt" for the picture shown while it is spoken.

Your job:
1. Improve the "narration": real, casual spoken {config.LANGUAGE}, no stiff or bookish words, sharper punchlines, no filler, short lines ({config.LINE_WORDS} words).
2. Make every scene line react naturally to the previous one, so the whole thing reads as one connected story following this plan: {json.dumps(outline.get('beats', []), ensure_ascii=False)}
3. Then make sure each "image_prompt" matches its FINAL narration exactly (same action, objects, emotion, speaker {config.NAME_A} or {config.NAME_B} talking with mouth open). Rewrite the image_prompt ONLY where it does not match; otherwise copy it unchanged. Keep it English only, with no text in the picture, in this place: {outline.get('location_visual', '')}. Gag look: {outline.get('gag_visual', '')}.

Do not change the story events, the order, the number of scenes ({len(scenes)}), or the speakers.

SCENES:
{json.dumps(scenes, ensure_ascii=False)}

Return ONLY valid JSON: {{"scenes": [{{"scene": 1, "narration": "...", "image_prompt": "..."}}, ... exactly {len(scenes)} objects in the same order ...]}}"""
