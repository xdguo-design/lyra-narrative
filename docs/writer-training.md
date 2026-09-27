# Writer Training Pipeline

## Purpose

The writer-training pipeline is deliberate practice for the Writer role. It is separate from the publication pipeline.

A publication run asks: “Can this chapter ship?”

A training run asks: “Which writing ability is weak, can the Writer correct it after feedback, and can the same ability transfer to a new scene?”

The training run must not overwrite the official chapter draft. Its only persistent output is a compact project-level **Writer Craft Profile**.

## Entry point

`POST /api/tasks/{task_id}/train-writer`

Request:

```json
{
  "source": "",
  "transfer_brief": ""
}
```

- `source` is optional. When empty, the service uses the current task draft and then the linked chapter content.
- `transfer_brief` is optional. When empty, the training examiner generates a fresh transfer exercise.
- A real AI provider is required. Demo/mock output is rejected as invalid training evidence.

## Pipeline

### 1. Baseline diagnosis

Role: `writer-coach`

Output: `WRITER_TRAINING_DIAGNOSIS_V1`

The coach selects at most three recurring, high-leverage weaknesses and must cite evidence from the text. It does not spend a training session on isolated typos or one-off wording mistakes.

Primary dimensions: scene direction, character behavior, language rhythm.

### 2. Scene direction attempt

Role: `writer-trainee`

The Writer produces a Scene Direction Card before writing prose. It must force choices: one core tension, POV attention filter, no more than three primary details, deliberately ignored details, fast zones, slow zones, relationship-distance change, required end-state change, and recently used patterns forbidden in this scene.

### 3. Scene direction feedback

Role: `scene-coach`

The coach does not rewrite the card. It identifies at most three failures in selection, POV, detail hierarchy, or pacing.

### 4. Scene direction rewrite

Role: `writer-trainee`

The Writer rewrites the card from coach evidence. This is the first learning loop: `attempt -> evidence -> rewrite`.

### 5. Character behavior attempt

Role: `writer-trainee`

The Writer first creates a Behavior Matrix for the people in the selected scene: immediate goal, fear/secret, leverage, status advantage/disadvantage, first response under pressure, evasion/lying strategy, admission threshold, and maximum concession.

Then the Writer writes a focused 500–900 Chinese-character practice scene. At least one participant must resist cooperation. Critical information must be released in layers.

### 6. Character behavior feedback

Role: `character-coach`

The coach checks whether character cards actually constrain behavior. Typical blocking patterns include: cautious character answers too honestly, strong character cooperates without leverage, dialogue becomes question-answer data transfer, everyone has the same speaking rhythm, or a character becomes temporarily stupid or brilliant to serve plot.

### 7. Character behavior rewrite

Role: `writer-trainee`

The Writer keeps the same facts and outcome but rewrites behavior, information release, and voice.

### 8. Language rhythm attempt

Role: `writer-trainee`

The Writer now works on the already-correct character scene. Facts and information order are frozen. The minimum unit of judgment is a sentence group of 3–5 sentences, not an isolated sentence.

The Writer explicitly marks the rhythm purpose of several sentence groups before rewriting: entry, continuation, pressure, pause, landing.

### 9. Language rhythm feedback

Role: `rhythm-coach`

Checks include repeated syntax, fake rhythm created by excessive one-line paragraphs, slow writing where compression is needed, rushing through a decision that should breathe, emotional over-explanation, and character voice polished into a common house style.

### 10. Language rhythm rewrite

Role: `writer-trainee`

The Writer rewrites only rhythm, pacing, and emotional whitespace. Story facts and character behavior remain frozen.

### 11. Integrated scene

Role: `writer-trainee`

The Writer writes a complete 900–1600 Chinese-character scene combining scene selection, POV filtering, behavior thresholds, subtext, and sentence-group rhythm. This is not yet the final mastery test because it still follows coaching from the same exercise.

### 12. Transfer exercise

Role: `training-examiner`

A new scene is generated within the same story world. It changes location, immediate goal, or relationship pressure and forbids reuse of the original exercise's major actions, evidence, dialogue, and ending structure.

The transfer scene is written without exposing the previous coach's exact rewrite suggestions.

### 13. Blind transfer review

Role: `training-examiner`

Each dimension receives one state:

- `NEEDS_WORK`: the original failure still dominates.
- `EMERGING`: correct after guidance, but unstable in new scenes.
- `STABLE`: works reliably in both corrected and new scenes.
- `TRANSFERABLE`: the Writer independently adapts the skill to a different scene shape.

There is no single overall score.

## Writer Craft Profile

Each completed training run is distilled into `WRITER_CRAFT_PROFILE_V1` with stable abilities, emerging abilities, needs-work abilities, transferable abilities, high-frequency failure modes, at most two next training targets, and at most six formal-writing activation rules.

The profile is stored as confirmed project memory using the stable source reference `writer-training:craft-profile`.

Subsequent training replaces the active profile and creates a memory version, so progress can be inspected over time.

## Separation from production writing

The built-in training skill is visible in the skill registry but is excluded from the default skill set frozen into new writing tasks.

This prevents training instructions such as “show your exercise” or “write a Behavior Matrix” from leaking into normal chapter generation.

The publication pipeline may consume only the distilled Writer Craft Profile through project context.

## Mastery rule

Correcting the original paragraph is not mastery.

A skill is considered learned only when:
1. the Writer can apply the relevant choice in its output structure;
2. the rewritten original scene removes the diagnosed failure;
3. the same failure does not recur in a structurally different transfer scene.

This is the core difference between editing a manuscript and training a Writer.

## Reader Gate decision rule

Core rule:

**A reader may not know the answer, but must know what the unanswered question is.**

A passage passes as intentional suspense/omission only when all of the following hold:

- the object is clear;
- the known boundary is clear;
- the reader can name the missing item in one sentence;
- the missing answer is intentionally withheld rather than accidentally omitted;
- the current scene is still understandable without the answer.

Reader labels:

- `INTENTIONAL_UNKNOWN`: “I know the question, but not the answer.” This may pass.
- `READER_GAP`: “I do not know what this sentence/action refers to.” This must be revised.
- `AMBIGUOUS_GAP`: “Two or more interpretations are equally plausible.” This passes only when that ambiguity is intentional and does not block current understanding.

Failure examples:

1. `县衙那边也没完。`
   - Could mean the case, the day's work, official blame, or Chen An's personal risk.
   - The unknown itself is undefined.
   - Verdict: `semantic-gap / LOCAL_REWRITE`.

2. `事情还没完。` when the scene currently contains debt, the grain case, and unfinished yamen work.
   - Object missing.
   - Verdict: `semantic-gap / LOCAL_REWRITE`.

3. `他终于明白了。`
   - If the text never establishes what belief changed or what fact caused the realization, the reader cannot identify the cognitive object.
   - Verdict: `causal-gap`; escalate to `REWRITE_BLOCK` when later action depends on it.

4. `她把钱收起来。“算了。”`
   - If “算了” could equally mean stop buying medicine, stop asking, stop lending money, or stop trusting Chen An, the relationship change is not readable.
   - Verdict: `semantic-gap / relationship-gap`.

Passing examples:

1. “县衙里出了事，陈安今天还得回去。至于会不会牵到他，现在没人说得准。”
   - Unknown: whether Chen An will be implicated.
   - Verdict: `INTENTIONAL_UNKNOWN / PASS`.

2. 孙成听见王顺作证后只问：“还有谁听见？”
   - The sentence meaning is clear; the unknown is why he cares about the spread of the testimony.
   - Verdict: `INTENTIONAL_UNKNOWN / PASS`.

A later explanation does not repair a current sentence that lacks a basic semantic anchor. “The reader can reread and infer it” is not a pass condition.
