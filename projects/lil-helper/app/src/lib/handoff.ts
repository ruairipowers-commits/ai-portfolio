// Hands a recipe draft from one screen to the next (web import or "what I've got" → the recipe editor), and says
// which planned meal it's for, so saving can put it straight on the plan. Kept in memory only.
import { RecipeDraft } from "./api";

let pending: { draft: RecipeDraft; useFor?: string } | null = null;

export function giveDraft(draft: RecipeDraft, useFor?: string) { pending = { draft, useFor }; }
export function takeDraft() { const p = pending; pending = null; return p; }
