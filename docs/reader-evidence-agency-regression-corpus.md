# Evidence / Agency / Callback Reader Regression Corpus v1

## FAIL

### ER001 — Knowledge provenance gap
“正好，我找你。”角色随后直接核问关键事实，但正文从未给出他如何锁定此人。
Expected: KNOWLEDGE_PROVENANCE_GAP.

### ER002 — Salient signal orphan
作者特写“袋子落地明显过轻”，所有人物却像没听见、没看见，后文也不形成记忆或待查项。
Expected: SALIENT_SIGNAL_ORPHAN_GAP.

### ER003 — Protagonist as camera
章内关键发现、决定、验证、行动全由配角完成；主角只看、听、跟随。
Expected: PROTAGONIST_AGENCY_GAP.

### ER004 — Unseeded callback
第二章说“昨儿在西库门口吵车钱那个”，第一章没有这场戏，也没有说明这是人物拥有而读者未知的旧事。
Expected: UNSEEDED_CALLBACK_GAP.

## PASS

### EP001 — Minimal knowledge source
“守库的只记得孙司吏喊过后厨的人，灶上说昨晚跑外差的是你。”
Why PASS: 给出足够来源，不扩成说明会。

### EP002 — Signal received, answer deferred
人物发现袋子明显过轻，只说“分量不对”，随后交给过秤验证。
Why PASS: 接收异常，但没有当场解谜。

### EP003 — Protagonist contributes without overreach
白役指出自己扛过该袋、觉得重量异常；班头决定封存和过秤。
Why PASS: 主角有独占贡献，但权限边界不漂移。

### EP004 — New information, not fake callback
“昨儿给咱们送赈粮的车夫。”
Why PASS: 当前场景第一次明确介绍，不伪装成读者之前见过。
