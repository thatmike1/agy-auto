# What the Antigravity CLI actually does with permissions

Everything here was measured against `agy` on Linux, 2026-08-26, rather than
read off the docs. Where a claim came from the docs and turned out to be wrong
in practice, that is called out. Reproduce any of it with the commands given.

## The summary

| behaviour | result |
| --- | --- |
| hook returns `{"decision": "allow"}` | prompt appears anyway |
| hook returns `{"decision": "allow"}` + `permissionOverrides` | prompt appears anyway |
| hook returns `{"decision": "deny"}` | command blocked |
| hook returns `deny` under `--dangerously-skip-permissions` | **still blocked** |
| hook returns `ask` under `--dangerously-skip-permissions` | overridden, command runs |
| headless (`-p`) with no matching allow rule | auto-denied, no output |

The two that matter: a hook cannot approve, and the skip-permissions flag does
not skip hooks. That combination is the whole design. You get prompt-free
operation from the flag and a real gate from the hook, and neither half works
alone.

## A hook cannot approve a command

The [hooks documentation](https://antigravity.google/docs) lists four
`PreToolUse` decisions — `allow`, `deny`, `ask`, `force_ask` — and describes
`allow` as "automatically allow the tool execution". It does not do that.

Interactive run, with a hook returning `allow` for every command:

```
● Bash(python3 -c "print(6*7)")

Requesting permission for:
   python3 -c "print(6*7)"

Do you want to proceed?
> 1. Yes
```

The guard's own log confirms it was consulted and allowed the command that was
then prompted for:

```json
{"at": "...", "decision": "allow", "why": "", "cmd": "python3 -c \"print(6*7)\""}
```

Adding `permissionOverrides` — documented as "temporary permission grants" —
changed nothing. Same prompt, both interactive and headless.

## Skip-permissions does not skip hooks

This is the useful half. Run with the flag, ask for a command the guard denies:

```
$ agy --dangerously-skip-permissions -p='Run: echo GUARD_CANARY'
The command was denied by the `agy-guard` pre-tool hook:
tool call denied by pre-tool hook: agy-guard: canary pattern, used to verify the guard is being consulted
```

So the hook is a real gate even in the mode that exists to remove gates.

## Under the flag, `ask` silently becomes `allow`

```
$ agy --dangerously-skip-permissions -p='Run: systemctl --user stop nonexistent-service-xyz'
The command failed with exit code `5`.
Failed to stop nonexistent-service-xyz.service: Unit not loaded.
```

The guard returned `ask`. The command ran anyway. An `ask` verdict under the
flag is indistinguishable from `allow`, which is why this guard has an
`AGY_GUARD_STRICT` mode that promotes every `ask` to `deny` — under the flag
those are the only two honest options.

## Headless cannot prompt at all

```
jetski: no output produced — a tool required the "command" permission that
headless mode cannot prompt for, so it was auto-denied.
```

The binary names this path internally: `addFromDiff: print mode, soft-denying:
%s step %d`. So for any automated use of `agy -p`, the choice is a permission
rule that matches in advance or the skip-permissions flag. There is no third
option, and a hook `allow` is not one either.

## Allow rules are literal prefix matches

The rules in `~/.gemini/antigravity-cli/settings.json` under `permissions.allow`
are shaped `command(<prefix>)` and match by string prefix. That works for
`command(grep)`. It does not work for anything whose interesting part is an
argument:

```
2. Yes, and always allow in this conversation for commands that start with
   'python3 -c "import json, glob, os ...'
```

Accepting that grants exactly that script and nothing else. `python3 -c` is
unallowlistable in practice, and so is any other interpreter invoked with
inline code. This is the specific gap the guard fills.

There is a second rule form, `write_file(<dir>)`, which grants recursive writes
beneath a directory with no flag required — worth using where a job only writes
files. Credit to
[antigravity-for-claude-code](https://github.com/yuting0624/antigravity-for-claude-code)
for documenting it; the string is present in the binary.

## `--sandbox` is not a substitute

Measured by that same project on macOS with agy 1.1.19: `--sandbox` does not
contain `--dangerously-skip-permissions`, and writes to absolute paths outside
the added directory still succeeded. Not independently reproduced here, but
worth knowing before treating the sandbox flag as a safety net.

## What this guard is not

Regex over a shell string. It stops a model that reaches for something
destructive in the obvious way. It does not stop base64, a variable holding the
path, a shell alias, or a script written to disk and then executed. If your
threat model includes an adversary rather than a careless model, this is the
wrong tool.
