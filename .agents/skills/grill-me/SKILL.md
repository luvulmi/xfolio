---
name: grill-me
description: Stress-test a plan, decision, or idea through a thorough, round-based interview when the user asks to be grilled.
---

# Grill Me

Interview the user until the decisions in their plan or idea are clear. Map the decisions as a tree: a decision can depend on answers to earlier questions.

Work in rounds. In each round, ask all questions whose prerequisites are settled. Number the questions as **Q1**, **Q2**, and so on, separating each question and its recommended answer clearly. Give a recommended answer with a brief reason for each, and word each question so "yes" accepts the recommendation. Wait for the user's answers before asking the next round. Keep questions whose answers depend on an open question for a later round.

After each answer, update the decision tree and ask the newly unblocked questions. Check facts available from files, tools, or other sources yourself; ask the user for decisions and information only they can provide. When environmental facts need exploration and agent delegation is available, dispatch a sub-agent to find them. Continue with independent questions while that investigation runs; questions depending on its result wait for a later round.

Finish when no unresolved decision remains. Summarize the shared understanding and obtain the user's confirmation before acting on the resulting plan. If the user asks only for the interview, stop at the confirmed summary.
