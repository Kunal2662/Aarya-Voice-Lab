// Pluggable Claude Code command execution transport (VL-D1 §14, §16).
//
// identity/command_center.py is explicit that it "executes nothing —
// the desktop invokes the ordinary CLI so every run passes the same
// gates and audit log." VL-D1's governing spec forbids building an
// unrestricted terminal or exposing arbitrary shell execution to the
// browser, and requires stopping rather than silently bypassing that if
// "Claude requires unrestricted shell access" turns out to be necessary.
//
// No browser-safe execution transport exists yet in this project — there
// is no HTTP API server or desktop-shell IPC bridge to invoke the CLI
// through (the desktop runtime itself is still an open choice; see
// docs/VLD0_DESIGN_SYSTEM.md "Why no framework"). Rather than fabricate
// one, or fake command output, this module defines the executor
// *interface* the real transport will implement later, and ships exactly
// one implementation for VL-D1: `NullCommandExecutor`, which honestly
// reports that no execution transport is connected. This is not a
// silent downgrade — every caller can see `available()` is false and
// the UI states that plainly (see components/claude-command-shell.js /
// workspace-claude.js), rather than pretending a command ran.
//
// A future executor (VL-D2+) implements the same `execute()` contract
// against a real transport, still going through
// identity/command_center.py's existing catalogue/gates/audit log —
// this module only defines the shape that plugs into.

export const CommandExecutionOutcome = Object.freeze({
  NOT_AVAILABLE: "not_available",
  SUCCESS: "success",
  FAILED: "failed",
  DENIED: "denied",
});

/**
 * @typedef {{outcome:string,command:string,output:string|null,error:string|null}} CommandExecutionResult
 */

export class CommandExecutor {
  /** @returns {boolean} whether a real execution transport is connected. */
  available() {
    throw new Error("not implemented");
  }

  /**
   * @param {string} command
   * @returns {Promise<CommandExecutionResult>}
   */
  async execute(command) {
    throw new Error("not implemented");
  }
}

/** The only executor VL-D1 ships. Always honest, never fabricates output. */
export class NullCommandExecutor extends CommandExecutor {
  available() {
    return false;
  }

  async execute(command) {
    return {
      outcome: CommandExecutionOutcome.NOT_AVAILABLE,
      command,
      output: null,
      error:
        "No execution transport is connected in VL-D1. Command Center UI, contracts, and the " +
        "fix-review workflow exist; nothing executes yet — see docs/VLD1_COMMAND_CENTER.md.",
    };
  }
}
