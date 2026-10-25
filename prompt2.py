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

Return ONLY valid JSON: {{"scenes": [{{
  "speaker": "a, b or narrator",
  "narration": "the spoken line in {config.LANGUAGE}",
  "image_prompt": "ENGLISH ONLY: one clear action moment, both or one character fully visible, funny exaggerated expression, simple background, no text",
  "motion": "zoom_in, zoom_out, pan_left, pan_right, pan_up, pan_down, shake or punch (shake for crashes, punch for surprises and the final line, pans for chases)",
  "sfx": "whoosh, boing, crash, pop or none (none on about half the scenes)"
}}]}}"""


def build_polish_prompt(scenes):
    return f"""You are a stand-up comedy editor for {config.LANGUAGE}. Improve ONLY the "narration" text of every scene below:
- Make it sound like real, casual spoken {config.LANGUAGE}; replace stiff or bookish words.
- Sharpen each punchline, cut filler, keep every line short ({config.LINE_WORDS} words).
- Keep the story, jokes' meaning, number of scenes, and all other fields EXACTLY unchanged.

SCENES:
{json.dumps(scenes, ensure_ascii=False)}

Return ONLY valid JSON: {{"scenes": [ ...same objects, with improved "narration"... ]}}"""
