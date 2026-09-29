#!/usr/bin/env bash
set -euo pipefail

LEARNING_DIR="data/builtin-skill-learning"

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
  if git push origin HEAD:main; then
    echo "Persisted built-in Skill learning to main."
    exit 0
  fi
  echo "Push attempt $attempt failed; rebasing on latest main."
  git pull --rebase origin main
done

echo "Unable to persist built-in Skill learning after 3 attempts." >&2
exit 1
