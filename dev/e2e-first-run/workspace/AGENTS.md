# Rules for this workspace

- When you need to read, write, or run anything, ALWAYS call the provided tools.
- NEVER print a tool call as plain text, XML, or a ```json code block. Tool calls
  must be emitted in the exact tool-call format so the runtime can execute them.
- Work step by step: one tool call per turn, look at the result, continue.
- Keep answers short; do not repeat file contents back.
