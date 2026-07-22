/**
 * Euthyna opencode plugin (v0): tag every LLM call with the opencode session id so
 * the gateway's ledger and prefix watchdog group calls by real session instead of
 * falling back to prefix-chaining heuristics.
 *
 * Install: copy this file into your project's `.opencode/plugins/` directory
 * (or `~/.config/opencode/plugins/` for all projects). Nothing else to configure.
 */
export const EuthynaPlugin = async () => ({
  "chat.headers": async (input, output) => {
    output.headers["X-Euthyna-Session"] = input.sessionID;
  },
});

export default EuthynaPlugin;
