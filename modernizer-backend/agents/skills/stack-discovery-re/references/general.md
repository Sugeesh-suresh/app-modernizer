# Any other stack — what to document

Use this checklist for a language, framework or component that has no dedicated
checklist. Adapt the items to the technology; skip what does not apply and say so.

Where to look:
- Its build/dependency manifests and lockfiles, and the directories that hold its source
- Its configuration files, environment variables and scripts that build, start or schedule it
- Its entry points: main modules, command-line scripts, handlers, routes, jobs, cron/scheduler definitions

What to record:
- What this part of the repository is for, where it lives, and how it is built, packaged and run
- Declared dependencies (name, version, scope) and what each is used for
- Structure: modules/packages/directories and how they depend on one another
- Entry points and interfaces: commands, endpoints, handlers, jobs, inputs and outputs
- Data it reads and writes: files, databases, queues, APIs — with where each is configured (credentials redacted)
- Business rules and processing steps, cited
- How it interacts with the other stacks in the repository (calls, shared files, shared databases)
- Tests: framework, location, what they cover, how they run
