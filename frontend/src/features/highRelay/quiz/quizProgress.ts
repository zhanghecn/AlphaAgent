// 高位接力答题训练 · 进度存储(localStorage)
// key 嵌题库版本串:口诀或讲解文案一变,旧进度自动作废(版本漂移教训)。
// localStorage 不可用时降级为内存 Map(不崩页面)。

import type { QuizAnswerRec, QuizChoice } from "./quizScore";
import { quizQuestionId } from "./quizScore";
import type { HprQuizQuestion } from "@/api/highRelay";

const storageKey = (rulesVersion: string) => `hpr-quiz-progress:${rulesVersion}`;

const memoryFallback = new Map<string, Record<string, QuizAnswerRec>>();

function readAll(rulesVersion: string): Record<string, QuizAnswerRec> {
  const key = storageKey(rulesVersion);
  try {
    const raw = window.localStorage.getItem(key);
    if (raw) return JSON.parse(raw) as Record<string, QuizAnswerRec>;
  } catch {
    // 降级内存
  }
  return memoryFallback.get(key) ?? {};
}

function writeAll(rulesVersion: string, data: Record<string, QuizAnswerRec>) {
  const key = storageKey(rulesVersion);
  memoryFallback.set(key, data);
  try {
    window.localStorage.setItem(key, JSON.stringify(data));
  } catch {
    // 仅内存
  }
}

export function loadProgress(rulesVersion: string): Record<string, QuizAnswerRec> {
  return readAll(rulesVersion);
}

export function saveAnswer(
  rulesVersion: string,
  questionId: string,
  rec: QuizAnswerRec,
): Record<string, QuizAnswerRec> {
  const all = readAll(rulesVersion);
  if (all[questionId]) return all; // 已答不改(只能重置重来)
  const next = { ...all, [questionId]: rec };
  writeAll(rulesVersion, next);
  return next;
}

/** 错题重练专用:允许覆盖已答记录(首答仍走 saveAnswer 的已答不改)。
 *  重练答对后错题出列,答错继续留在错题池——成绩以最后一次为准。 */
export function overwriteAnswer(
  rulesVersion: string,
  questionId: string,
  rec: QuizAnswerRec,
): Record<string, QuizAnswerRec> {
  const all = readAll(rulesVersion);
  const next = { ...all, [questionId]: rec };
  writeAll(rulesVersion, next);
  return next;
}

export function resetMonth(
  rulesVersion: string,
  questions: HprQuizQuestion[],
): Record<string, QuizAnswerRec> {
  const drop = new Set(questions.map((q) => quizQuestionId(q)));
  const all = readAll(rulesVersion);
  const next: Record<string, QuizAnswerRec> = {};
  for (const [k, v] of Object.entries(all)) {
    if (!drop.has(k)) next[k] = v;
  }
  writeAll(rulesVersion, next);
  return next;
}

export function resetAll(rulesVersion: string): Record<string, QuizAnswerRec> {
  writeAll(rulesVersion, {});
  return {};
}

export type { QuizAnswerRec, QuizChoice };
