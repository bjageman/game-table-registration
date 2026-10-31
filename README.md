# Game table registration

Planned Discord signup bot and moderator dashboard for in-person games: weekly native polls, weighted table allocation, and automatic waitlist promotion.

Read the [development plan](docs/development-plan.md) and [implementation issues](https://github.com/bjageman/game-table-registration/issues).

Proposed stack: Python/FastAPI/discord.py/PostgreSQL, with React/TypeScript/Vite/Tailwind matching tinygrim. Deployment uses Docker Compose with reviewed local → dev → production stages.

Planning only; application code and CI are not implemented yet. Keep Discord credentials in the ignored `.env` file and never commit them.
