# agy-auto

A guarded auto mode for Google's [Antigravity CLI](https://antigravity.google), plus the
Claude Code pieces that use it.

---

Antigravity has three permission modes and none of them is Claude Code's auto mode. `default`
and `accept-edits` prompt you before every shell command. `--dangerously-skip-permissions`
prompts you before none of them. There is nothing in between, so using `agy` for a quick job
means either approving thirty prompts or handing a Gemini model an unsupervised shell.

The allowlist doesn't close the gap either. Rules are literal prefix matches, so approving
`python3 -c "import json, glob, os ..."` grants exactly that script and nothing else. Any
interpreter called with inline code is unallowlistable in practice.

**`agy-auto` runs agy with prompts off and a deny list underneath.** Ordinary work — reading,
grepping, building, running scripts — goes through silently. Destructive commands are blocked
before they reach the shell.

```
$ agy-auto -p='Run: echo GUARD_CANARY'
The command was denied by the `agy-guard` pre-tool hook:
agy-guard: canary pattern, used to verify the guard is being consulted
```

## Why this works

Antigravity's `PreToolUse` hook can return `allow`, `deny`, or `ask`. Two measured facts drive
the whole design:

- **A hook cannot approve a command.** Returning `allow` does not suppress the prompt. Neither
  does `permissionOverrides`. The docs say otherwise; it does not work.
- **`--dangerously-skip-permissions` does not skip hooks.** A `deny` is still enforced under it.

So the flag handles the prompting and the hook handles the blocking. Neither half does anything
useful alone. Full measurements, with reproduction commands, in [docs/findings.md](docs/findings.md).

One consequence worth stating plainly: under that flag an `ask` verdict is silently overridden
and the command runs. `agy-auto` therefore sets `AGY_GUARD_STRICT=1`, which promotes every `ask`
to `deny` — with no way to prompt, block and allow are the only honest options.

## What it blocks

**Denied always:** `rm -rf` on a home or root path, force push, deleting a remote branch,
`curl | sh`, `dd of=/dev/*`, `mkfs`, `shred`, `crontab -r`, `docker system prune -a`,
`npm publish`, fork bombs, recursive `chmod`/`chown` of `/` or `~`, deleting `.git`/`.ssh`/`.gnupg`,
overwriting key material, expiring the git reflog.

**Denied under `agy-auto`, prompted under plain `agy`:** `sudo`, `git push`, `git reset --hard`,
`git clean -fd`, any recursive `rm`, package removal, stopping services, ssh/scp/rsync to a
remote, `gh delete`/`gh merge`, `kill -9`, moving a system path.

Everything else runs. Every verdict is logged to `~/.gemini/config/agy-guard.log` as JSONL, so
you can see what would have been blocked before you trust it.

**This is regex over a shell string.** It stops a model that reaches for something destructive
the obvious way. It does not stop base64, a variable holding the path, an alias, or a script
written to disk and then run. If your threat model has an adversary in it rather than a careless
model, this is the wrong tool.

## Install

```bash
git clone https://github.com/thatmike1/agy-auto
cd agy-auto
./install.sh
```

That puts `agy-auto` on your `PATH`, installs the hook into `~/.gemini/config/`, and registers it
in `hooks.json`. It refuses to overwrite an existing `hooks.json` and prints the block to merge
by hand instead. `--with-claude` also installs the `grunt` subagent.

Verify:

```bash
agy-auto -p='Run: echo GUARD_CANARY'   # must be blocked
python3 ~/.gemini/config/agy-guard.py --self-test
```

Hooks load when agy starts, so restart any running session after installing.

## Tuning it

Edit the `DENY` and `ASK` lists in `guard/agy-guard.py` — they're `(regex, reason)` pairs. Run
`python3 guard/test-agy-guard.py` after; it checks 24 commands against both modes.

Machine-specific patterns belong in `~/.gemini/config/agy-guard.local.json`, which is merged at
startup and keeps the shared guard clean:

```json
{
  "ask": [["\\b(203\\.0\\.113\\.7|my-vps-host)\\b", "touches the production box"]]
}
```

See `guard/agy-guard.local.example.json`.

## The Claude Code side

`agy` is useful from Claude Code because it spends Google's quota instead of Anthropic's. Two
pieces here do that:

- **`claude/agents/grunt.md`** — a subagent that forwards one bulk job to agy and relays the
  answer. Big-and-shallow work (piles of logs, repo-wide sweeps, mechanical edits) grinds outside
  Claude's context. It calls `agy-auto`, because headless agy cannot prompt and dies silently on
  any command outside the allowlist.
- **`bin/agy-image`** — image generation through agy's `generate_image` tool, landing the result
  at a path you choose. Useful on a harness with no native image tool.

For a much larger take on the same bridge — background jobs, cost measurement, slash commands —
see [antigravity-for-claude-code](https://github.com/yuting0624/antigravity-for-claude-code). It
has no guarded auto mode, which is what this repo adds.

## Requirements

`agy` installed and authenticated, Python 3, bash. Linux and macOS.

## License

MIT
