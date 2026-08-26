#!/usr/bin/env python3
"""agy PreToolUse guard: block destructive run_command calls.

Reads the hook payload on stdin, writes {"decision": ...} on stdout, and logs
every verdict to agy-guard.log.

This exists to make `agy --dangerously-skip-permissions` survivable. A hook
"deny" is still honoured under that flag (verified), so the guard is a real
gate; a hook "allow" is NOT honoured without the flag (verified) — agy prompts
anyway — so the guard cannot be used to suppress prompts in a normal session.

Under the flag an "ask" verdict is overridden and the command just runs, which
is why AGY_GUARD_STRICT promotes ask to deny. The agy-auto wrapper sets it.

This is a regex over the shell string, so it stops a careless model, not a
determined one. Obfuscation (base64, variables, aliases) walks straight past it.
"""
import datetime
import json
import os
import re
import sys

RECURSIVE_DELETE = r'\brm\b[^|;&]*\s-[a-zA-Z]*[rR][a-zA-Z]*f|\brm\b[^|;&]*\s-[a-zA-Z]*f[a-zA-Z]*[rR]'
WIDE_PATH = r'\s(/|~|\$HOME|/home/\w+|/\*|\.\.)/?\*?\s*($|\s)'

# hard block: irreversible, or destroys something outside the working tree
DENY = [
    # harmless probe: run `echo GUARD_CANARY` to check the deny path is live
    (r'GUARD_CANARY', 'canary pattern, used to verify the guard is being consulted'),
    (r'\bmkfs\b|\bfdisk\b|\bparted\b', 'disk formatting or partitioning'),
    (r'\bdd\b[^|;&]*\bof=/dev/', 'dd writing to a raw device'),
    (r'>\s*/dev/(sd|nvme|hd)', 'redirect into a raw device'),
    (r'\bshred\b', 'shred is unrecoverable'),
    (r':\(\)\s*\{.*\|.*&.*\}', 'fork bomb'),
    (r'\bchmod\b[^|;&]*\s-[a-zA-Z]*R[a-zA-Z]*\s+\d+\s+(/|~|\$HOME)\s*$', 'recursive chmod of home or root'),
    (r'\bchown\b[^|;&]*\s-[a-zA-Z]*R[a-zA-Z]*\s+[^\s]+\s+(/|~|\$HOME)\s*$', 'recursive chown of home or root'),
    (r'\bgit\b[^|;&]*\bpush\b[^|;&]*(--force(?!-with-lease)|\s-f\b)', 'force push'),
    (r'\bgit\b[^|;&]*\bpush\b[^|;&]*--delete', 'deleting a remote branch'),
    (r'\bgit\b[^|;&]*\breflog\b[^|;&]*\bexpire\b|\bgit\b[^|;&]*\bgc\b[^|;&]*--prune=now', 'destroys git recovery history'),
    (r'\bcrontab\b[^|;&]*\s-r\b', 'wipes the crontab'),
    (r'\bdocker\b[^|;&]*\bsystem\b[^|;&]*\bprune\b[^|;&]*(-a|--all|--volumes)', 'prunes docker volumes and images globally'),
    (r'\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba)?sh\b', 'pipes a download straight into a shell'),
    (r'\bnpm\b[^|;&]*\b(un)?publish\b', 'publishes to a public registry'),
    (r'\bhistory\b\s+-c\b', 'clears shell history'),
    (r'\brm\b[^|;&]*\s(\.git|~/\.ssh|~/\.gnupg|~/\.claude|~/\.gemini)\b', 'deletes a config or repo metadata directory'),
    (r'>\s*~?/?\.ssh/|>\s*~/\.gnupg/', 'overwrites key material'),
]

# still worth a human look, but recoverable
ASK = [
    (r'\bsudo\b', 'runs as root'),
    (r'\bgit\b[^|;&]*\bpush\b', 'pushes to a remote'),
    (r'\bgit\b[^|;&]*\breset\b[^|;&]*--hard|\bgit\b[^|;&]*\bclean\b[^|;&]*-[a-zA-Z]*[fd]', 'discards uncommitted work'),
    (r'\bgit\b[^|;&]*\bcheckout\b[^|;&]*\s--\s|\bgit\b[^|;&]*\brestore\b', 'discards uncommitted work'),
    (r'\brm\b[^|;&]*\s-[a-zA-Z]*[rR]', 'recursive delete'),
    (r'\b(systemctl|service)\b[^|;&]*\b(stop|disable|mask)\b', 'stops a service'),
    (r'\b(apt|apt-get|dnf|yum|pacman|snap|flatpak)\b[^|;&]*\b(remove|purge|uninstall|autoremove)\b', 'removes packages'),
    (r'\bssh\b|\bscp\b|\brsync\b[^|;&]*:', 'acts on a remote host'),
    (r'\bgh\b[^|;&]*\b(delete|merge)\b', 'irreversible GitHub action'),
    (r'\bkill(all)?\b[^|;&]*\s-9\b', 'hard kill'),
    (r'\bmv\b[^|;&]*\s/(etc|usr|var|boot)\b', 'moves a system path'),
]


LOG = os.path.expanduser('~/.gemini/config/agy-guard.log')
LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agy-guard.local.json')


def load_local():
    """merge in machine-specific patterns, so this file stays shareable.

    agy-guard.local.json, if present: {"deny": [[regex, reason], ...], "ask": [...]}
    """
    try:
        with open(LOCAL) as f:
            extra = json.load(f)
    except FileNotFoundError:
        return
    except Exception as exc:
        sys.stderr.write('agy-guard: ignoring unreadable %s: %s\n' % (LOCAL, exc))
        return
    for key, target in (('deny', DENY), ('ask', ASK)):
        for pat, why in extra.get(key, []):
            re.compile(pat)
            target.append((pat, why))


def log(decision, cmd, why):
    """append every verdict so an unexpected allow/deny can be traced later."""
    try:
        with open(LOG, 'a') as f:
            f.write(json.dumps({
                'at': datetime.datetime.now().isoformat(timespec='seconds'),
                'decision': decision,
                'why': why,
                'cmd': cmd[:400],
            }) + '\n')
    except Exception:
        pass


def verdict(cmd, strict=False):
    """strict mode turns every ASK match into a block.

    agy runs under --dangerously-skip-permissions when it is being used
    unattended, and that flag overrides an "ask" decision — the command simply
    runs. So in that mode an ask verdict would be indistinguishable from allow,
    and the only honest options are block it or let it through.
    """
    if re.search(RECURSIVE_DELETE, cmd) and re.search(WIDE_PATH, cmd):
        return 'deny', 'recursive force delete of a home or root path'
    for pat, why in DENY:
        if re.search(pat, cmd):
            return 'deny', why
    for pat, why in ASK:
        if re.search(pat, cmd):
            if strict:
                return 'deny', why + ' (blocked unattended; rerun under plain agy to approve it)'
            return 'ask', why
    return 'allow', ''


def self_test():
    """confirm the guard is loadable and its deny path fires."""
    load_local()
    checks = [('deny', 'echo GUARD_CANARY'), ('deny', 'rm -rf ~'), ('allow', 'ls -la')]
    bad = [(w, c, verdict(c)[0]) for w, c in checks if verdict(c)[0] != w]
    for want, cmd, got in bad:
        sys.stderr.write('agy-guard self-test: %r gave %s, wanted %s\n' % (cmd, got, want))
    if bad:
        return 1
    print('agy-guard: ok (%d deny, %d ask patterns loaded)' % (len(DENY), len(ASK)))
    return 0


def main():
    if '--self-test' in sys.argv:
        raise SystemExit(self_test())
    load_local()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        print(json.dumps({'decision': 'ask', 'reason': 'guard could not parse the hook payload'}))
        return

    call = payload.get('toolCall') or {}
    args = call.get('args') or {}
    cmd = args.get('CommandLine') or args.get('commandLine') or ''
    if not cmd:
        print(json.dumps({'decision': 'allow'}))
        return

    decision, why = verdict(cmd, strict=bool(os.environ.get('AGY_GUARD_STRICT')))
    out = {'decision': decision}
    if why:
        out['reason'] = 'agy-guard: ' + why
    log(decision, cmd, why)
    print(json.dumps(out))


if __name__ == '__main__':
    main()
