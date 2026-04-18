# AI Auto Marketing Platform — Global Development Rules

## Budget Failsafes
- All `daily_budget` and `lifetime_budget` variables must be declared as `0` by default and only set after explicit validation against the user's stored `budgetCap` (from `business_dna.budget_cap`).
- Any function that reads or writes a budget value to the Meta API must be annotated `// BUDGET-SENSITIVE` and must have a corresponding unit test asserting the cap is never exceeded.
- No code path may submit a Meta API payload with a budget value that exceeds `user.budgetCap`. This is an absolute hard stop.

## Meta API Error Handling (Milestone 2+)
- On any Meta API failure: log full error context, push a notification to the user's notification queue, halt that user's pipeline.
- Retry with exponential backoff only: 1s, 2s, 4s delays. Max 3 attempts. Never retry in a tight loop.
- On exhausted retries: mark the pipeline task as `failed` and surface a clear action item to the user.

## Data Privacy
- User questionnaire answers must never be sent raw to any LLM.
- `sanitizeForLLM()` in `lib/questionnaire/sanitize.ts` is the ONLY authorized path from raw questionnaire data to an AI prompt.
- PII fields (exact name, email, phone, physical address) must be excluded from all sanitized contexts.

## AI Provider Abstraction
- All LLM calls must go through the `AIProvider` interface in `lib/ai/types.ts`.
- Direct SDK calls (`anthropic.messages.create`, `openai.chat.completions.create`) are FORBIDDEN in business logic.
- Provider selection: `AI_PROVIDER=claude|openai` env var. Both providers must remain functional.

## Authentication (Milestone 1)
- NextAuth.js with email/password. Meta OAuth replaces this in Milestone 5.
- Session must always expose `userId` (used as `tenantId` throughout).

## Multi-Tenancy
- No global or singleton for user/tenant context. Every service function must accept an explicit `tenantId`.
- PostgreSQL RLS is enabled on all tenant-scoped tables. Cross-tenant data access must be structurally impossible at the query level.
- Never log or expose one tenant's data in another tenant's error messages or responses.

## Questionnaire Rule
- The `business_dna` record is the ONLY authorized input to strategy and copy generation.
- LLM prompts must never be constructed from raw form inputs or interview transcripts — always from sanitized `BusinessDNA` fields.

## Adjustment Engine Rules (Milestone 3+)
- The engine must never increase a budget above `budgetCap`. No exceptions.
- All automatic adjustments must be logged with full rationale.
- Budget patches to live Ad Sets must go exclusively through `skill_budget_adjustment`.

## Dependencies

- **Zod v4** is installed (not v3). Use the v4 API. Key difference: `z.string()`, `z.object()`, basic schemas are the same, but error shape (`z.ZodError`) and some refinement APIs differ. When in doubt, check zod.dev/v4.
- **Next.js 16** is installed (latest stable). Use App Router conventions. Do not import from `next/server` patterns that were deprecated before v15.

## Development Conventions
- File names: `kebab-case` for all files and directories
- TypeScript: strict mode is on — no `any` without explicit justification
- Testing: follow TDD — write failing test first, then implementation
- Imports: use `@/` path alias for all internal imports (never relative paths that traverse more than one level)
- Commits: one logical change per commit, conventional commit format (`feat:`, `fix:`, `test:`, `chore:`)
