# Built-in Skill automatic learning

This directory is append-only training evidence for NarrativeOS built-in Writer and Reader Skills.

Every formal rejection batch (Reader, Character Voice, specialist reviewer, final review, or HUMAN_REJECT) writes one JSON file here. On database initialization, NarrativeOS replays these files into the built-in Writer/Reader Skills, so a fresh machine or CI database inherits prior rejection learning.

Raw rejection evidence is not automatically promoted to a new hard label. New patterns enter as CALIBRATING checks; repeated patterns are grouped by signature and counted as recurrences. Formal new blocking rules still follow the Skill Evolution Protocol.
