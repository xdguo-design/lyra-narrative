#!/usr/bin/env bash
set -euo pipefail

LEARNING_DIR="data/builtin-skill-learning"
TARGET_BRANCH="${NARRATIVE_PERSIST_BRANCH:-${GITHUB_REF_NAME:-dev}}"

if [ -z "$(git status --porcelain -- "$LEARNING_DIR")" ]; then
  echo "No new built-in Skill learning to persist."
  exit 0
fi

git config user.name "NarrativeOS Skill Learner"
git config user.email "narrativeos-skill-learner@users.noreply.github.com"
git add "$LEARNING_DIR"

if git diff --cached --quiet; then
  echo "No staged Skill learning changes."
  exit 0
fi

git commit -m "skill: persist automatic rejection learning [skip ci]"

for attempt in 1 2 3; do
  if git push origin "HEAD:$TARGET_BRANCH"; then
    echo "Persisted built-in Skill learning to $TARGET_BRANCH."
    exit 0
  fi

  echo "Push attempt $attempt failed; rebasing on latest $TARGET_BRANCH."
  git rebase --abort >/dev/null 2>&1 || true
  if ! git pull --rebase origin "$TARGET_BRANCH"; then
    git rebase --abort >/dev/null 2>&1 || true
    echo "::warning::Unable to rebase Skill learning onto $TARGET_BRANCH; generation result remains valid."
    exit 0
  fi
done

echo "::warning::Unable to persist built-in Skill learning after 3 attempts; generation result remains valid."
exit 0
